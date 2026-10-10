#!/bin/bash
# stall-ordering.sh — when a run genuinely stalls, which guard stops it first?
#
# Two anti-stall mechanisms sit on the same Stop event and neither knows about the
# other. The platform honours 8 consecutive blocks with no progress and overrides
# the ninth (§ 3). This framework's guard 4 stops the run after STALL_STOP
# continuations that closed no task. Only the one that fires FIRST produces a
# reason anybody reads: the platform's override is silent.
#
# hooks/selftest.py measures the framework's number offline and deterministically
# — block 6. What it cannot measure is the other half: whether a real model, told
# by a real block reason to keep working, behaves the way the arithmetic assumes.
# That needs a session.
#
#   bash scripts/probes/stall-ordering.sh [max-turns]
#
# Costs a few cents of Haiku and a couple of minutes. Runs the SHIPPED hook
# unmodified — a counting wrapper execs it, so what fires is the real guard, not a
# stand-in. Writes nothing outside its own temporary directory.
#
# The run it builds cannot be finished: its one task asks for a file that does not
# exist. That is the stall worth guarding against — work blocked on something the
# plan never declared — and it is the case the model cannot escape by being clever.

set -uo pipefail

MAX_TURNS="${1:-24}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$HERE/hooks/autopilot-stop.py"

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }
[ -f "$HOOK" ] || { echo "hook not found: $HOOK" >&2; exit 2; }

DIR=$(mktemp -d) || exit 2
trap 'rm -rf "$DIR"' EXIT

mkdir -p "$DIR/.efficiency" "$DIR/.claude"

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

- run opened by the stall-ordering probe
RUN

# A counting wrapper, so the hook that runs is the shipped one. Each invocation is
# numbered and the run file's status is sampled immediately after, which is what
# dates the stop to a block number.
cat > "$DIR/probe.sh" <<HOOK_WRAPPER
#!/bin/bash
D="$DIR"
payload=\$(cat)
n=\$(( \$(cat "\$D/count" 2>/dev/null || echo 0) + 1 ))
echo "\$n" > "\$D/count"
out=\$(printf '%s' "\$payload" | CLAUDE_PROJECT_DIR="\$D" python3 "$HOOK")
code=\$?
printf '=== invocation %s (exit %s) ===\n%s\n' "\$n" "\$code" "\$out" >> "\$D/hook.log"
status=\$(grep -m1 '^status:' "\$D/.efficiency/run.md" | cut -d: -f2- | tr -d ' ')
printf '%s %s\n' "\$n" "\$status" >> "\$D/timeline"
printf '%s' "\$out"
exit \$code
HOOK_WRAPPER
chmod +x "$DIR/probe.sh"

DIR="$DIR" python3 - <<'PY'
import json, os
d = os.environ["DIR"]
json.dump({"hooks": {"Stop": [{"hooks": [{"type": "command",
                                          "command": 'bash "%s/probe.sh"' % d,
                                          "timeout": 30}]}]}},
          open(os.path.join(d, "settings.json"), "w"))
PY

echo "max_turns=$MAX_TURNS  hook=$HOOK"
OUT=$( cd "$DIR" && claude -p "Work the run in .efficiency/run.md, starting with T1." \
         --model haiku --max-turns "$MAX_TURNS" --max-budget-usd 0.50 \
         --permission-mode acceptEdits --settings "$DIR/settings.json" </dev/null 2>&1 )

COUNT=$(cat "$DIR/count" 2>/dev/null || echo 0)
STATUS=$(grep -m1 '^status:' "$DIR/.efficiency/run.md" | cut -d: -f2- | tr -d ' ')
REASON=$(grep -m1 '^blocked_reason:' "$DIR/.efficiency/run.md" | cut -d: -f2-)
STOPPED=$(awk '$2 == "BLOCKED" {print $1; exit}' "$DIR/timeline" 2>/dev/null)

echo "hook invocations: $COUNT"
echo "run status:       $STATUS"
echo "stopped at block: ${STOPPED:-never}"
echo "reason:           ${REASON:-(none)}"

echo
if [ "$COUNT" -eq 0 ]; then
    echo "verdict: THE HOOK NEVER FIRED — the probe is broken, not the platform."
    printf '%s\n' "$OUT" | tail -3
elif [ "$STATUS" = "DONE" ]; then
    echo "verdict: INCONCLUSIVE — the model closed a task it could not have finished, so"
    echo "         this run never stalled. That is a finding about the model, not about"
    echo "         the guards: re-run, and if it repeats, the task text is too tickable."
elif [ -z "$STOPPED" ]; then
    echo "verdict: NEITHER GUARD STOPPED IT in $COUNT invocations. If the session ended on"
    echo "         max-turns the probe was too short; if it ended earlier, the PLATFORM cap"
    echo "         overrode the block and the developer was told nothing. Check hook.log."
elif [ "$STOPPED" -le 8 ]; then
    echo "verdict: the FRAMEWORK stopped the run at block $STOPPED, inside the platform's 8"
    echo "         honoured blocks. The developer gets the reason above, not a silent end."
else
    echo "verdict: the framework stopped the run at block $STOPPED, OUTSIDE the platform's 8"
    echo "         honoured blocks — so the platform had already overridden the block and"
    echo "         the run spun on unheard. STALL_STOP is too high. Check § 3."
fi
