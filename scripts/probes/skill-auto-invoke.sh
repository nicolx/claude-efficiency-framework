#!/bin/bash
# skill-auto-invoke.sh — does a plain request actually reach the skill meant for it?
#
# A skill is invoked in two ways: the developer types `/efficiency:<name>`, or
# the model reads the description and decides it applies. The second is the one
# the framework depends on — a developer who has to remember a command name is a
# developer being interrupted — and it had never been observed for six of the
# seven skills. A description too vague to match fails silently: the skill simply
# never fires and the session does the work the long way round.
#
#   bash scripts/probes/skill-auto-invoke.sh
#   TRIALS=5 MODEL=sonnet bash scripts/probes/skill-auto-invoke.sh
#
# Choosing a skill is a model decision, so one session is a sample and not a
# measurement. Each case is run TRIALS times and reported as a hit rate. The
# default model is Haiku because the probe has to be cheap enough to re-run; a
# developer whose sessions are driven by a larger model is measuring something
# adjacent to their own, not identical to it.
#
# Costs well under a dollar of Haiku and a few minutes. Writes nothing outside
# its own temporary directory.
#
# Method: one headless session per case, in a throwaway project, with this repo
# loaded through `--plugin-dir`. The request is phrased the way a developer
# would phrase it and never names the skill. The session's own stream is then
# read for a `Skill` tool call — what the model *chose*, not what it said it
# would do, and not whether the skill then succeeded.
#
# The throwaway project is scaffolded with real files, and every request names
# things that exist in it. The first run of this probe did neither, and three of
# its four misses were the model correctly declining a request with no referent:
# "run these four migrations in parallel" in an empty directory has no migrations
# to run, and a session that asks which ones is behaving well. A probe must not
# charge a description for that.
#
# What this does and does not include, measured rather than assumed. In these
# sessions the `SessionStart` hook runs but emits nothing — it stays silent in a
# project that has not adopted the framework — and the `UserPromptSubmit` hook,
# which in a real session injects a line naming the autopilot outright, never
# fires at all under `-p`. Checked in every retained transcript.
#
# So the probe measures a description **on its own**, with no charter and no
# reminder helping it. That is a cleaner instrument than a consumer session, and
# a harder test: whatever is reached here is reached by the description alone.
# It is also why a miss here is not automatically a miss in production.
#
# The negative controls are what stop this from being a test every skill passes
# by firing constantly. A skill that matches "what is 17 times 23" is as broken
# as one that never matches anything.
#
# The sessions run with `--setting-sources project,local`, so nothing in the
# developer's own ~/.claude/settings.json reaches them. Before 2026-10-18 it
# did: every session on the author's machine ran their personal output style,
# visible in the `init` event and in replies written in Italian to English
# requests. § 18 measures that the flag keeps it out.
#
# The sessions run under `bypassPermissions`, which is not laziness about the
# fence: under `dontAsk` the platform denies `Bash` and `Edit` outright, and a
# model that cannot write will not invoke a skill whose whole action is to write.
# The autopilot scored 0/3 for two rounds for exactly that reason, and said so in
# its own words once the transcripts were kept. Permissions are measured in
# `dot-claude-writes.sh`; here they are a confound to remove.
#
# A row whose session ran out of turns is reported as inconclusive, never as a
# miss. The first useful run of this probe scored the autopilot 0/3 when both
# sessions had simply been cut off mid-exploration at `--max-turns 3`, which is
# a budget, not a decision.

set -uo pipefail

cd "$(dirname "$0")/../.." || exit 2
PLUGIN=$(pwd)

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

TRIALS=${TRIALS:-3}
MODEL=${MODEL:-haiku}

echo "claude: $(claude --version 2>/dev/null | head -1)"
echo "plugin: $PLUGIN"
echo "model:  $MODEL   trials per case: $TRIALS"
echo

ROOT=$(mktemp -d) || exit 2
# Evidence for the rows that did not reach their skill survives the run: a miss
# with no transcript is a verdict nobody can check, and the first run of this
# probe threw away exactly the four streams that would have explained it.
KEEP=$(mktemp -d) || exit 2
trap 'rm -rf "$ROOT"' EXIT

# key ~ expected skill (or "-" for a negative control) ~ the request
CASES=$(cat <<'EOF'
autopilot-en ~ efficiency:autopilot ~ TODO.md has three things in it. Work through the whole list and do not check in with me.
autopilot-it ~ efficiency:autopilot ~ In TODO.md ci sono tre cose. Procedi fino a completarle tutte, non fermarti a chiedermi conferma.
backlog-en ~ efficiency:backlog ~ The query builder in src/query.py should really be refactored at some point. Jot it down somewhere so it does not get lost, but do not do it now.
backlog-it ~ efficiency:backlog ~ Il query builder in src/query.py andrebbe rifattorizzato prima o poi. Segnalo da qualche parte per dopo, non farlo adesso.
fanout-en ~ efficiency:fanout ~ The four report writers in src/report_daily.py, src/report_weekly.py, src/report_monthly.py and src/report_yearly.py each need the docstring "Render rows for this report period." added to render(). They do not touch each other. Run all four at once, in parallel, rather than one after another.
fanout-it ~ efficiency:fanout ~ I quattro report writer in src/report_daily.py, src/report_weekly.py, src/report_monthly.py e src/report_yearly.py hanno bisogno della docstring "Render rows for this report period." su render(). Sono indipendenti fra loro. Falli tutti e quattro insieme in parallelo invece che uno dopo l altro.
init-en ~ efficiency:init ~ Set up the efficiency framework in this project.
init-it ~ efficiency:init ~ Configura il framework di efficienza in questo progetto.
plan-run-en ~ efficiency:plan-run ~ We need input validation on src/api.py and the tests updated to match. Before we start, plan this out properly and turn it into a task list I can approve.
plan-run-it ~ efficiency:plan-run ~ Serve la validazione degli input in src/api.py e i test aggiornati di conseguenza. Prima di partire prepara il piano e trasformalo in una lista di task che posso approvare.
run-en ~ efficiency:run ~ Go ahead with the approved plan and start the run.
run-it ~ efficiency:run ~ Vai avanti con il piano approvato e parti con il run.
run-report-en ~ efficiency:run-report ~ How did that run go, and what did it cost?
run-report-it ~ efficiency:run-report ~ Com e andato quel run, e quanto e costato?
control-math ~ - ~ What is 17 times 23?
control-prose ~ - ~ Write me a two sentence description of what a binary search does.
EOF
)

# The first Skill call in the session stream, or nothing. Reads what the model
# chose; a skill that was chosen and then failed still counts as reached.
first_skill() {
    python3 - "$1" <<'PY'
import json, sys
for line in open(sys.argv[1], errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    msg = ev.get("message")
    if not isinstance(msg, dict):
        continue
    content = msg.get("content")
    if not isinstance(content, list):
        continue
    for b in content:
        if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Skill":
            print((b.get("input") or {}).get("skill", ""))
            raise SystemExit(0)
PY
}

# A small, plausible project. Every request below names something in here, so a
# session that does not invoke a skill is declining the skill, not the referent.
make_fixture() {
    local dir="$1" key="$2"
    mkdir -p "$dir/src" || return 1
    cat > "$dir/README.md" <<'EOF'
# ledger

A small accounting service. The API layer is in src/api.py, the query builder in
src/query.py, and the four report writers each stand alone.
EOF
    cat > "$dir/src/api.py" <<'EOF'
def post_entry(payload):
    return {"ok": True, "entry": payload}
EOF
    cat > "$dir/src/query.py" <<'EOF'
def build(table, where):
    return "SELECT * FROM " + table + " WHERE " + where
EOF
    for name in daily weekly monthly yearly; do
        printf 'def render(rows):\n    return rows\n' > "$dir/src/report_$name.py"
    done
    cat > "$dir/TODO.md" <<'EOF'
- rename the config module to settings
- add a docstring to each public function in src/api.py
- fix the typo in README.md
EOF

    # `run` and `run-report` both document a precondition: an approved run to
    # execute or to report on. Without one a session is right to decline, and
    # charging the description for that measures the fixture, not the skill.
    case "$key" in
        run-*)   # covers run-report-* too
            mkdir -p "$dir/.efficiency"
            cat > "$dir/.efficiency/policy.md" <<'EOF'
---
gate: "python3 -m compileall -q src"
budget:
  continuations: 40
  gate_retries: 2
  task_usd: 2.00
tiers:
  routine: haiku
  sensitive: sonnet
  critical: opus
---
EOF
            cat > "$dir/.efficiency/run.md" <<'EOF'
---
status: ACTIVE
objective: Add input validation to the API layer
---

## Tasks

- [x] 1 · routine · haiku · add a docstring to src/query.py · done
- [ ] 2 · sensitive · sonnet · validate the payload in post_entry · raises on a missing key
- [ ] 3 · routine · haiku · update the tests to match · the gate is green

## Log

- task 1 closed, gate green
EOF
            ;;
    esac
}

# What the session said instead. For a row that did not reach its skill this is
# the entire diagnosis: a model asking which files to parallelise is declining a
# request it could not act on, which is not the same defect as a model that read
# the description and found nothing in it.
last_text() {
    python3 - "$1" <<'PY'
import json, sys
last = ""
for line in open(sys.argv[1], errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    msg = ev.get("message")
    if not isinstance(msg, dict):
        continue
    content = msg.get("content")
    if not isinstance(content, list):
        continue
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
            last = " ".join(b["text"].split())
print(last[:240])
PY
}

# Did the session end by choosing to, or by running out of turns? A row cut off
# mid-exploration never got to the point where it would have invoked anything.
cut_off() {
    python3 - "$1" <<'PY'
import json, sys
for line in open(sys.argv[1], errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("type") == "result":
        print("yes" if ev.get("stop_reason") == "tool_use" else "no")
        raise SystemExit(0)
print("unknown")
PY
}

run_case() {
    local key="$1" prompt="$2"
    local dir="$ROOT/$key"
    mkdir -p "$dir" || return 1
    make_fixture "$dir" "$key" || return 1
    # ScheduleWakeup and CronCreate are withheld because under -p a scheduled
    # wakeup keeps the process alive until it fires: on 2026-10-18 a `run` trial
    # launched its reviewer in the background, scheduled a wakeup to wait for it,
    # then another for 30 minutes, and the whole probe sat behind that one
    # session. --max-turns bounds turns, not wall-clock time. No skill needs either.
    ( cd "$dir" && git init -q . >/dev/null 2>&1
      claude -p "$prompt" \
        --model "$MODEL" --max-turns 10 --max-budget-usd 0.40 \
        --permission-mode bypassPermissions \
        --disallowedTools ScheduleWakeup CronCreate \
        --setting-sources project,local \
        --plugin-dir "$PLUGIN" \
        --output-format stream-json --verbose </dev/null >"$dir/stream.json" 2>&1 )
}

# Four at a time: sixteen sessions one after another is a coffee break, and they
# share nothing. A rolling queue, not batches: a new session starts the moment
# any slot frees. Batching four and waiting for all of them made every batch
# cost as much as its slowest member while three workers idled — 48 sessions
# took eleven minutes. `wait -n` would do this directly, but macOS ships bash
# 3.2, which lacks it, so the free slot is found by counting running jobs.
SLOTS=4
NCASES=$(printf '%s\n' "$CASES" | grep -c '~')
echo "Running $((NCASES * TRIALS)) sessions, $SLOTS at a time:"
STARTED=$(date +%s)
t=1
while [ "$t" -le "$TRIALS" ]; do
    while IFS='~' read -r key expected prompt; do
        key=$(echo "$key" | xargs); prompt=$(echo "$prompt" | sed 's/^ *//;s/ *$//')
        [ -n "$key" ] || continue
        while [ "$(jobs -rp | wc -l)" -ge "$SLOTS" ]; do sleep 1; done
        run_case "$key-t$t" "$prompt" &
    done <<< "$CASES"
    t=$((t + 1))
done
wait
echo "all sessions finished in $(( $(date +%s) - STARTED ))s"

echo
echo "| case | expected | reached | what it chose instead | reading |"
echo "|---|---|---|---|---|"

MISS=0; HIT=0; MISFIRE=0; CONTROL_FIRED=0; FLAKY=0; INCONCLUSIVE=0

while IFS='~' read -r key expected prompt; do
    key=$(echo "$key" | xargs); expected=$(echo "$expected" | xargs)
    [ -n "$key" ] || continue

    hits=0; cuts=0; others=""
    t=1
    while [ "$t" -le "$TRIALS" ]; do
        if ! got=$(first_skill "$ROOT/$key-t$t/stream.json"); then
            echo "cannot read the stream for $key-t$t — this is the probe failing, not a finding" >&2
            exit 2
        fi
        if [ "$got" = "$expected" ]; then
            hits=$((hits + 1))
        elif [ -n "$got" ]; then
            case " $others " in *" $got "*) ;; *) others="$others $got" ;; esac
        elif [ "$(cut_off "$ROOT/$key-t$t/stream.json")" = yes ]; then
            # Cut off mid-exploration. It never reached the point of choosing,
            # so it is not evidence either way and leaves the denominator.
            cuts=$((cuts + 1))
        fi
        t=$((t + 1))
    done
    others=${others# }
    shown=${others:-"—"}
    effective=$((TRIALS - cuts))

    if [ "$expected" = "-" ]; then
        # For a control, any skill at all is the failure.
        fired=0
        t=1
        while [ "$t" -le "$TRIALS" ]; do
            got=$(first_skill "$ROOT/$key-t$t/stream.json")
            [ -n "$got" ] && fired=$((fired + 1))
            t=$((t + 1))
        done
        if [ "$fired" -eq 0 ]; then
            reading="correct — no skill claimed an ordinary request"
        else
            reading="**over-matching** — fired on $fired of $TRIALS"
            CONTROL_FIRED=$((CONTROL_FIRED + 1))
        fi
        echo "| $key | $expected | — | $shown | $reading |"
        continue
    fi

    if [ "$effective" -eq 0 ]; then
        reading="inconclusive — every trial ran out of turns before choosing"
        INCONCLUSIVE=$((INCONCLUSIVE + 1))
    elif [ "$hits" -eq "$effective" ]; then
        reading="reached, every time it got the chance"
        HIT=$((HIT + 1))
    elif [ "$((hits * 2))" -ge "$effective" ]; then
        reading="**unreliable** — reached more often than not, but not always"
        FLAKY=$((FLAKY + 1))
    elif [ "$hits" -gt 0 ]; then
        reading="**mostly missed** — reached $hits of $effective"
        FLAKY=$((FLAKY + 1))
    elif [ -n "$others" ]; then
        reading="**misfire** — a neighbouring skill answered every time"
        MISFIRE=$((MISFIRE + 1))
    else
        reading="**never fired** — the description did not match, in any trial"
        MISS=$((MISS + 1))
    fi
    echo "| $key | $expected | $hits/$effective | $shown | $reading |"

    case "$reading" in
        "reached, every time"*) ;;
        *) cp "$ROOT/$key-t1/stream.json" "$KEEP/$key.json" 2>/dev/null
           printf '%s\n' "$key" >> "$KEEP/.rows" ;;
    esac
done <<< "$CASES"

# Why each row that did not reach its skill did not, in the session's own words.
if [ -s "$KEEP/.rows" ]; then
    echo
    echo "What those sessions did instead, on the first trial:"
    while read -r key; do
        printf '  %-16s %s\n' "$key" "$(last_text "$KEEP/$key.json")"
    done < "$KEEP/.rows"
fi

echo
echo "reached every time: $HIT   unreliable: $FLAKY   misfired: $MISFIRE   never fired: $MISS   inconclusive: $INCONCLUSIVE   controls that fired: $CONTROL_FIRED"
if [ -s "$KEEP/.rows" ]; then
    echo "transcripts for the rows above: $KEEP"
else
    rm -rf "$KEEP"
fi
echo

if [ "$MISS" -eq 0 ] && [ "$MISFIRE" -eq 0 ] && [ "$CONTROL_FIRED" -eq 0 ] && [ "$FLAKY" -eq 0 ]; then
    echo "verdict: CONFIRMED — every skill is reachable from a plain request in both"
    echo "         languages, and no skill claims a request that is not its business."
elif [ "$MISS" -gt 0 ]; then
    echo "verdict: UNREACHABLE SKILLS — the rows marked 'never fired' cannot be invoked"
    echo "         except by typing their command. Read their transcripts before blaming"
    echo "         the wording: a skill whose task the model would rather perform than"
    echo "         delegate is missed however well its description is written, and that"
    echo "         is a different problem with a different fix."
    exit 1
elif [ "$CONTROL_FIRED" -gt 0 ]; then
    echo "verdict: OVER-MATCHING — a skill fired on a control. A description that claims"
    echo "         everything interrupts as surely as one that claims nothing."
    exit 1
elif [ "$FLAKY" -gt 0 ] && [ "$MISFIRE" -eq 0 ]; then
    echo "verdict: REACHABLE BUT NOT RELIABLY — every skill was reached at least once,"
    echo "         so no description is simply invisible, but some are reached only"
    echo "         sometimes. A skill that fires two runs in three is a skill the"
    echo "         developer learns not to rely on."
    exit 1
else
    echo "verdict: REACHABLE BUT BLURRED — nothing is unreachable, but neighbouring"
    echo "         skills answer for each other. Read the misfire rows: the question is"
    echo "         whether the pair is genuinely ambiguous or one description overreaches."
fi
