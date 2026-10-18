#!/bin/bash
# stop-coexistence.sh — does a project's own Stop hook still coexist with the autopilot?
#
# Two claims in docs/verified-platform-behaviour.md rest on a single run from
# 2026-09-05 (`dfa61e0`) that committed no probe at all:
#
#   § 2  both hooks are invoked on every turn; `stop_hook_active` is information,
#        not a lock, so neither stands down because the other blocked first;
#   § 3  the cap counts blocked TURNS, not blocks — two hooks blocking together
#        consume one of the eight occasions, not two (row A2).
#
# Neither has been re-measured since the counters moved out of the run file and
# into `.efficiency/autopilot.json`, and § 3's own margin — guard 4 at block 6,
# two inside the platform's 8 — was measured with ONE hook registered. If the cap
# ever starts counting blocks rather than turns, a project hook blocking alongside
# the autopilot halves that margin and the platform stops the run first, silently.
# That is the failure this probe exists to catch.
#
#   bash scripts/probes/stop-coexistence.sh [cap|autopilot|both] [max-turns]
#
# Costs a few cents of Haiku and a couple of minutes per mode. Runs the SHIPPED
# hook unmodified in `autopilot` mode — a counting wrapper execs it. Writes
# nothing outside its own temporary directory.
#
#   cap        two dumb always-blocking hooks, no tool calls between blocks. The
#              direct re-measure of § 2 and of row A2: how many invocations does
#              each hook get, and are the two numbers equal?
#   autopilot  the real autopilot against an unfinishable run, with a project
#              quality-gate hook blocking beside it on every turn. Does guard 4
#              still stop the run at block 6, does the private counter advance
#              once per turn rather than twice, and do BOTH block reasons reach
#              the model?

set -uo pipefail

MODE="${1:-both}"
MAX_TURNS="${2:-}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$HERE/hooks/autopilot-stop.py"

case "$MODE" in
    cap|autopilot|both) ;;
    *) echo "unknown mode: $MODE (expected cap|autopilot|both)" >&2; exit 2 ;;
esac

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }
[ -f "$HOOK" ] || { echo "hook not found: $HOOK" >&2; exit 2; }

echo "claude $(claude --version 2>/dev/null | head -1)"

# Every temporary project is registered before it is used, so an interrupted run
# leaves nothing behind. A probe that litters is one people stop running.
TMPDIRS=()
cleanup() { for d in "${TMPDIRS[@]:-}"; do [ -n "$d" ] && rm -rf "$d"; done; }
trap cleanup EXIT

# Two hooks in two SEPARATE groups, which is the shape a real adopter gets: the
# plugin ships its own group in hooks.json and the project declares its own. A
# single group holding both would test a configuration nobody actually has.
write_settings() {
    SET_DIR="$1" SET_A="$2" SET_B="$3" python3 - <<'PY'
import json, os
d, a, b = os.environ["SET_DIR"], os.environ["SET_A"], os.environ["SET_B"]
entry = lambda cmd: {"hooks": [{"type": "command", "command": 'bash "%s"' % cmd,
                                "timeout": 60}]}
json.dump({"hooks": {"Stop": [entry(a), entry(b)]}},
          open(os.path.join(d, "settings.json"), "w"))
PY
}

# Reads `stop_hook_active` out of every payload a hook logged, in order. § 2's
# claim is about that flag, so the probe records it rather than assuming it.
flag_series() {
    python3 - "$1" <<'PY'
import json, sys
seen = []
for line in open(sys.argv[1], errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        seen.append(str(json.loads(line).get("stop_hook_active")))
    except ValueError:
        seen.append("?")
print(",".join(seen) if seen else "(none)")
PY
}

# What ended the session, in its own words. Without this the invocation count has
# to be read as a motive — "it stopped at 10, so probably the budget" — which is
# the kind of guess this directory exists to make unnecessary.
session_end() {
    python3 - "$1" <<'PYEND'
import json, sys
raw = open(sys.argv[1], errors="replace").read()
start = raw.find("{")
while start != -1:
    try:
        d = json.loads(raw[start:])
    except ValueError:
        start = raw.find("{", start + 1)
        continue
    if isinstance(d, dict) and "subtype" in d:
        print("%s after %s turns, $%s"
              % (d.get("subtype"), d.get("num_turns", "?"),
                 round(d.get("total_cost_usd", 0) or 0, 4)))
        break
    start = raw.find("{", start + 1)
else:
    print("(no result object - see the raw output)")
PYEND
}

# ─────────────────────────────────────────────────────────────────────────────
# mode: cap
# ─────────────────────────────────────────────────────────────────────────────
run_cap() {
    local turns="${MAX_TURNS:-40}"
    local DIR
    DIR=$(mktemp -d) || return 2
    TMPDIRS+=("$DIR")

    for name in alpha beta; do
        cat > "$DIR/$name.sh" <<HOOK_SH
#!/bin/bash
D="$DIR"
payload=\$(cat)
n=\$(( \$(cat "\$D/count.$name" 2>/dev/null || echo 0) + 1 ))
echo "\$n" > "\$D/count.$name"
printf '%s\n' "\$payload" >> "\$D/payloads.$name"
python3 -c 'import json,sys; print(json.dumps({"decision":"block","reason":sys.argv[1]}))' \\
    "invocation \$n. Reply with the single word: ok"
exit 0
HOOK_SH
        chmod +x "$DIR/$name.sh"
    done

    write_settings "$DIR" "$DIR/alpha.sh" "$DIR/beta.sh"

    echo
    echo "── mode: cap ── two always-blocking hooks, no tool calls (max-turns $turns)"
    ( cd "$DIR" && claude -p "Reply with the single word: ok" \
        --setting-sources project,local \
        --model haiku --max-turns "$turns" --max-budget-usd 0.50 --output-format json \
        --permission-mode dontAsk --settings "$DIR/settings.json" </dev/null 2>&1 ) > "$DIR/session.json"

    local A B
    A=$(cat "$DIR/count.alpha" 2>/dev/null || echo 0)
    B=$(cat "$DIR/count.beta"  2>/dev/null || echo 0)

    echo "alpha invocations: $A"
    echo "beta  invocations: $B"
    echo "alpha stop_hook_active: $(flag_series "$DIR/payloads.alpha")"
    echo "beta  stop_hook_active: $(flag_series "$DIR/payloads.beta")"
    echo "session ended:     $(session_end "$DIR/session.json")"
    echo

    if [ "$A" -eq 0 ] || [ "$B" -eq 0 ]; then
        echo "verdict: A HOOK NEVER FIRED (alpha $A, beta $B). Either the probe is broken or"
        echo "         a second Stop group is no longer registered at all — which would be the"
        echo "         most consequential change this file can report. Check settings.json."
    elif [ "$A" -ne "$B" ]; then
        echo "verdict: THE HOOKS NO LONGER RUN IN LOCKSTEP (alpha $A, beta $B). § 2 says neither"
        echo "         is skipped because the other blocked. That is no longer true, and a"
        echo "         project's hook and the autopilot are now interfering. § 2 and § 3 row A2"
        echo "         both need rewriting before anything else in this repo is trusted."
    elif [ "$A" -eq 9 ]; then
        echo "verdict: UNCHANGED — $A invocations each, the same total as one hook alone. The cap"
        echo "         still counts blocked turns, not blocks: two hooks share one of the eight"
        echo "         occasions rather than halving them. § 2 and § 3 row A2 hold."
    elif [ "$A" -le 5 ]; then
        echo "verdict: THE CAP NOW COUNTS BLOCKS (alpha $A, beta $B — roughly half of 9). Two"
        echo "         hooks consume two occasions. Guard 4's two blocks of margin in § 3 are"
        echo "         gone for any project with its own Stop hook: the platform stops the run"
        echo "         first and says nothing. STALL_STOP must come down. Fix before release."
    else
        echo "verdict: CHANGED — $A invocations each, neither 9 nor half of it. The cap's"
        echo "         arithmetic has moved in some other direction; re-derive § 3 from"
        echo "         scripts/probes/stop-cap.sh before touching STALL_STOP."
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# mode: autopilot
# ─────────────────────────────────────────────────────────────────────────────
run_autopilot() {
    local turns="${MAX_TURNS:-24}"
    local DIR
    DIR=$(mktemp -d) || return 2
    TMPDIRS+=("$DIR")
    mkdir -p "$DIR/.efficiency"

    # The same unfinishable run stall-ordering.sh uses, so the two numbers are
    # comparable: the only difference between the probes is the neighbour.
    cat > "$DIR/.efficiency/run.md" <<'RUN'
---
status: ACTIVE
gate:
continuations_used: 0
continuations_max: 40
gate_retries: 0
gate_retries_max: 2
current_task: T1
task_started_at: 2000-01-01T00:00:00Z
task_spend_micro_usd: 0
task_spend_max_micro_usd: 0
blocked_reason:
---

## Tasks

- [ ] T1 Read the licence key out of /nonexistent/licence-key.txt and report it. Do not
  tick this box unless you have actually read the key out of that file.
- [ ] T2 Report the key's expiry date, which is on the second line of the same file.

## Log

- run opened by the stop-coexistence probe
RUN

    # Hook A: the shipped autopilot, wrapped only to count and to date the stop
    # to a block number. What fires is the real guard, not a stand-in.
    cat > "$DIR/autopilot.sh" <<HOOK_SH
#!/bin/bash
D="$DIR"
payload=\$(cat)
n=\$(( \$(cat "\$D/count.autopilot" 2>/dev/null || echo 0) + 1 ))
echo "\$n" > "\$D/count.autopilot"
printf '%s\n' "\$payload" >> "\$D/payloads.autopilot"
out=\$(printf '%s' "\$payload" | CLAUDE_PROJECT_DIR="\$D" python3 "$HOOK")
code=\$?
printf '=== invocation %s (exit %s) ===\n%s\n' "\$n" "\$code" "\$out" >> "\$D/hook.log"
status=\$(grep -m1 '^status:' "\$D/.efficiency/run.md" | cut -d: -f2- | tr -d ' ')
used=\$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("continuations_used"))
except Exception: print("-")' "\$D/.efficiency/autopilot.json")
printf '%s %s %s\n' "\$n" "\$status" "\$used" >> "\$D/timeline"
printf '%s' "\$out"
exit \$code
HOOK_SH
    chmod +x "$DIR/autopilot.sh"

    # Hook B: a project's own quality gate, red on every turn. Its reason asks for
    # one observable act, so the probe can tell whether BOTH reasons reach the
    # model or only one of them does.
    cat > "$DIR/gate.sh" <<HOOK_SH
#!/bin/bash
D="$DIR"
payload=\$(cat)
n=\$(( \$(cat "\$D/count.gate" 2>/dev/null || echo 0) + 1 ))
echo "\$n" > "\$D/count.gate"
printf '%s\n' "\$payload" >> "\$D/payloads.gate"
python3 -c 'import json,sys; print(json.dumps({"decision":"block","reason":sys.argv[1]}))' \\
    "project gate is red (check \$n). Before anything else, append the line 'gate \$n' to the file gate.log in the project root."
exit 0
HOOK_SH
    chmod +x "$DIR/gate.sh"

    write_settings "$DIR" "$DIR/autopilot.sh" "$DIR/gate.sh"

    echo
    echo "── mode: autopilot ── shipped hook + a project gate blocking beside it (max-turns $turns)"
    ( cd "$DIR" && claude -p "Work the run in .efficiency/run.md, starting with T1." \
        --setting-sources project,local \
        --model haiku --max-turns "$turns" --max-budget-usd 0.50 --output-format json \
        --permission-mode acceptEdits --settings "$DIR/settings.json" </dev/null 2>&1 ) > "$DIR/session.json"

    local A G STATUS STOPPED REASON USED GATELOG
    A=$(cat "$DIR/count.autopilot" 2>/dev/null || echo 0)
    G=$(cat "$DIR/count.gate" 2>/dev/null || echo 0)
    STATUS=$(grep -m1 '^status:' "$DIR/.efficiency/run.md" | cut -d: -f2- | tr -d ' ')
    REASON=$(grep -m1 '^blocked_reason:' "$DIR/.efficiency/run.md" | cut -d: -f2-)
    STOPPED=$(awk '$2 == "BLOCKED" {print $1; exit}' "$DIR/timeline" 2>/dev/null)
    USED=$(awk '{print $3}' "$DIR/timeline" 2>/dev/null | tail -1)
    GATELOG=$(wc -l < "$DIR/gate.log" 2>/dev/null | tr -d ' ' || echo 0)

    echo "autopilot invocations: $A"
    echo "gate invocations:      $G"
    echo "run status:            $STATUS"
    echo "stopped at block:      ${STOPPED:-never}"
    echo "continuations_used:    ${USED:-(none)} (private state, after the last block)"
    echo "gate.log lines:        ${GATELOG:-0} (turns on which the NEIGHBOUR's reason was obeyed)"
    echo "session ended:         $(session_end "$DIR/session.json")"
    echo "reason:                ${REASON:-(none)}"
    echo
    echo "timeline (block, run status, continuations_used):"
    sed 's/^/  /' "$DIR/timeline" 2>/dev/null || echo "  (empty)"
    echo

    if [ "$A" -eq 0 ]; then
        echo "verdict: THE AUTOPILOT NEVER FIRED — the probe is broken, not the platform."
    elif [ "$G" -eq 0 ]; then
        echo "verdict: THE PROJECT HOOK NEVER FIRED while the autopilot ran $A times. The two no"
        echo "         longer coexist, and an adopting project's own Stop hook is being silently"
        echo "         disabled by this framework. § 2 is wrong. Nothing ships until it is fixed."
    elif [ "$STATUS" = "DONE" ]; then
        echo "verdict: INCONCLUSIVE — the model closed a task it could not have finished, so this"
        echo "         run never stalled. A finding about the model, not the guards: re-run, and"
        echo "         if it repeats the task text is too tickable."
    elif [ -z "$STOPPED" ]; then
        echo "verdict: NEITHER GUARD STOPPED IT in $A invocations. If the session ended on"
        echo "         max-turns the probe was too short; if it ended earlier, the PLATFORM cap"
        echo "         overrode the block with a neighbour present and the developer was told"
        echo "         nothing — which is exactly the regression this probe looks for. hook.log."
    elif [ "$STOPPED" -gt 8 ]; then
        echo "verdict: the framework stopped the run at block $STOPPED, OUTSIDE the platform's 8"
        echo "         honoured blocks. The platform had already overridden the block and the run"
        echo "         spun on unheard. STALL_STOP is too high. § 3."
    elif [ "$A" -ne "$G" ]; then
        echo "verdict: the run stopped at block $STOPPED, but the two hooks ran a DIFFERENT number"
        echo "         of times ($A vs $G). That is expected only after the autopilot stops"
        echo "         blocking and the neighbour keeps going — check the timeline before"
        echo "         concluding anything: if they diverge BEFORE the stop, § 2 is wrong."
    else
        echo "verdict: UNCHANGED — guard 4 stopped the run at block $STOPPED with a neighbouring"
        echo "         Stop hook blocking on every turn, inside the platform's 8, and the private"
        echo "         counter advanced once per turn. The margin in § 3 survives a project that"
        echo "         has its own Stop hook."
    fi

    if [ "${GATELOG:-0}" -eq 0 ] && [ "$G" -gt 0 ]; then
        echo
        echo "note:    the neighbour blocked $G times and its instruction was never carried out."
        echo "         Both reasons reach the model, but only one is acted on — the project's"
        echo "         gate is heard as noise. Worth recording: an adopter whose gate asks for"
        echo "         something will not get it while the autopilot is armed."
    fi
}

case "$MODE" in
    cap)       run_cap ;;
    autopilot) run_autopilot ;;
    both)      run_cap; run_autopilot ;;
esac
