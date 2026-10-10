#!/bin/bash
# run-routing.sh — does a run actually route work to the agents it promises?
#
# Model routing is this framework's headline contribution and was its least
# exercised part: `skills/run/SKILL.md` says a haiku task goes to the
# `efficiency:implementer-fast` agent and a review goes to `efficiency:reviewer`,
# and nothing had ever watched a run do either. A promise about which model does
# the work is worth nothing until someone has seen the delegation happen.
#
#   bash scripts/probes/run-routing.sh
#
# Costs real money — a couple of dollars at most, bounded by --max-budget-usd —
# because the reviewer and the architect are pinned to Opus and the point is to
# let them actually run. Writes nothing outside its own temporary directory, and
# keeps the transcripts.
#
# Two phases, because two separate claims are being checked:
#
#   1. a run executes and delegates. Read from the session stream: which
#      `Task` calls were made and to which `subagent_type`, plus what the run
#      file looks like afterwards.
#   2. `/efficiency:run-report` can report on it. It does not measure spend
#      itself — it reads `task_spend_micro_usd` and `task_spend_by_model`, which
#      the autopilot's Stop hook writes into the run file. So those keys being
#      present is itself part of the finding: without them the report has
#      nothing to report.

set -uo pipefail

cd "$(dirname "$0")/../.." || exit 2
PLUGIN=$(pwd)

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

DRIVER=${DRIVER:-sonnet}
BUDGET=${BUDGET:-5.00}

echo "claude: $(claude --version 2>/dev/null | head -1)"
echo "driver: $DRIVER   budget ceiling: \$$BUDGET"
echo

DIR=$(mktemp -d) || exit 2
echo "project: $DIR"
echo

# ── the project ──────────────────────────────────────────────────────────────
# Three tasks across two tiers, so both routes are exercised in one run: two
# routine tasks that the policy sends to Haiku, and one sensitive task that is
# done in session and then reviewed.
mkdir -p "$DIR/src" "$DIR/.efficiency"
( cd "$DIR" && git init -q . )

printf 'def alpha(x):\n    return x + 1\n'            > "$DIR/src/alpha.py"
printf 'def beta(x):\n    return x * 2\n'             > "$DIR/src/beta.py"
printf 'def post_entry(payload):\n    return {"ok": True, "entry": payload}\n' > "$DIR/src/api.py"

cat > "$DIR/.efficiency/policy.md" <<'EOF'
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

critical:
  - "src/auth/**"

sensitive:
  - "src/api.py"

stop_for:
  - a public interface changing shape
---

# Declared defaults

- raise ValueError for a missing required key, never return an error dict
EOF

# The frontmatter is what `/efficiency:plan-run` writes, ceilings included. An
# earlier version of this probe hand-wrote a shorter one and the whole spend
# guard silently did not run: the hook seeds `spend_max` from
# `task_spend_max_micro_usd` here, and `if spend_max > 0` means a missing key
# disables the guard rather than failing closed. The symptom surfaced three
# minutes later as a report that could not say what anything cost.
cat > "$DIR/.efficiency/run.md" <<EOF
---
status: ACTIVE
objective: Harden the ledger API and document the helpers
gate: "python3 -m compileall -q src"
continuations_used: 0
continuations_max: 40
gate_retries: 0
gate_retries_max: 2
current_task: 1
task_started_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)
task_spend_micro_usd: 0
task_spend_max_micro_usd: 2000000
blocked_reason:
---

## Tasks

- [ ] 1 · routine · haiku · add a one-line module docstring to src/alpha.py · the file's first line is a docstring and the gate is green
- [ ] 2 · sensitive · sonnet · make post_entry in src/api.py raise ValueError when payload has no "amount" key · calling it with {} raises ValueError; review required
- [ ] 3 · routine · haiku · add a one-line module docstring to src/beta.py · the file's first line is a docstring and the gate is green

## Log
EOF

# ── phase 1: the run ─────────────────────────────────────────────────────────
echo "Phase 1 — executing the run. This takes a few minutes and spends real money."
( cd "$DIR" && claude -p "Go ahead with the approved plan and start the run." \
    --model "$DRIVER" --max-turns 60 --max-budget-usd "$BUDGET" \
    --permission-mode bypassPermissions \
    --plugin-dir "$PLUGIN" \
    --output-format stream-json --verbose </dev/null > "$DIR/run-stream.json" 2>&1 )

# Every delegation the session made, in order.
delegations() {
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
    if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
        continue
    for b in msg["content"]:
        if not isinstance(b, dict) or b.get("type") != "tool_use":
            continue
        if b.get("name") not in ("Task", "Agent"):
            continue
        got = (b.get("input") or {}).get("subagent_type") or "(none given)"
        print(got)
PY
}

if ! DELEGATED=$(delegations "$DIR/run-stream.json"); then
    echo "cannot read the run stream — this is the probe failing, not a finding" >&2
    exit 2
fi

echo
echo "Delegations the run made, in order:"
if [ -z "$DELEGATED" ]; then
    echo "  (none)"
else
    printf '%s\n' "$DELEGATED" | sed 's/^/  /'
fi

ROUTED_FAST=no; ROUTED_REVIEW=no
printf '%s\n' "$DELEGATED" | grep -q "implementer-fast" && ROUTED_FAST=yes
printf '%s\n' "$DELEGATED" | grep -q "reviewer"         && ROUTED_REVIEW=yes

echo
echo "| claim | expected | observed |"
echo "|---|---|---|"
echo "| a haiku task is delegated to the fast implementer | efficiency:implementer-fast | $ROUTED_FAST |"
echo "| the review gate is delegated to the reviewer | efficiency:reviewer | $ROUTED_REVIEW |"

# ── what the run left behind ─────────────────────────────────────────────────
CLOSED=$(grep -c '^- \[x\]' "$DIR/.efficiency/run.md" 2>/dev/null); CLOSED=${CLOSED:-0}
OPEN=$(grep -c '^- \[ \]'  "$DIR/.efficiency/run.md" 2>/dev/null); OPEN=${OPEN:-0}
SPEND_KEY=no
grep -q 'task_spend_by_model' "$DIR/.efficiency/run.md" 2>/dev/null && SPEND_KEY=yes
GATE=red
( cd "$DIR" && python3 -m compileall -q src >/dev/null 2>&1 ) && GATE=green

echo "| tasks closed | 3 | $CLOSED (and $OPEN still open) |"
CEILING=$(grep -c 'task_spend_max_micro_usd' "$DIR/.efficiency/run.md" 2>/dev/null); CEILING=${CEILING:-0}
CEIL_OK=no; [ "$CEILING" -gt 0 ] && CEIL_OK=yes
echo "| the run file carried a spend ceiling at all | yes | $CEIL_OK |"
echo "| the hook wrote the spend keys the report reads | task_spend_by_model | $SPEND_KEY |"
echo "| the gate is green at the end | green | $GATE |"

# ── phase 2: the report ──────────────────────────────────────────────────────
echo
echo "Phase 2 — asking a fresh session to report on it."
( cd "$DIR" && claude -p "How did that run go, and what did it cost?" \
    --model "$DRIVER" --max-turns 15 --max-budget-usd 1.00 \
    --permission-mode bypassPermissions \
    --plugin-dir "$PLUGIN" \
    --output-format stream-json --verbose </dev/null > "$DIR/report-stream.json" 2>&1 )

report_text() {
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
    if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
        continue
    for b in msg["content"]:
        if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
            last = b["text"]
print(last)
PY
}

REPORT=$(report_text "$DIR/report-stream.json")
VERDICT_FIRST=no
printf '%s' "$REPORT" | head -1 | grep -qE '^\**(DONE|NOT DONE|BLOCKED)' && VERDICT_FIRST=yes
NAMES_SPEND=no
printf '%s' "$REPORT" | grep -qiE '\$[0-9]|haiku|opus|sonnet' && NAMES_SPEND=yes

echo
echo "| claim | expected | observed |"
echo "|---|---|---|"
echo "| the report opens with a verdict on its own line | DONE / NOT DONE / BLOCKED | $VERDICT_FIRST |"
echo "| the report names spend, by model | dollars and model names | $NAMES_SPEND |"
echo
echo "The report, as written:"
printf '%s\n' "$REPORT" | head -40 | sed 's/^/  /'

# ── verdict ──────────────────────────────────────────────────────────────────
echo
echo "transcripts and project kept at: $DIR"
echo

if [ "$ROUTED_FAST" = yes ] && [ "$ROUTED_REVIEW" = yes ]; then
    echo "verdict: ROUTING OBSERVED — a run delegated a haiku task to the fast"
    echo "         implementer and its review to the reviewer. The framework's"
    echo "         headline claim has been watched working, once, on this version."
else
    echo "verdict: ROUTING NOT OBSERVED — the run did not delegate what the skill says"
    echo "         it delegates. Read the stream at $DIR/run-stream.json before"
    echo "         concluding anything: a run that never started, or stopped at its"
    echo "         first task, proves nothing about routing either way."
    exit 1
fi
