#!/bin/bash
# supervisor-checkpoint.sh — does a checkpoint let real work through and stop a loop?
#
# hooks/selftest.py proves the checkpoint logic against a fake supervisor. What it
# cannot prove is the end-to-end claim: that a real session, under the SHIPPED Stop
# and PreToolUse hooks, reaches its ceiling, gets a verdict from a real model, and
# goes on when the work is real — and is stopped when it is not.
#
#   bash scripts/probes/supervisor-checkpoint.sh converging [max-turns]
#   bash scripts/probes/supervisor-checkpoint.sh impossible [max-turns]
#
# The agent is Haiku and so is the supervisor (`budget.supervisor: haiku`), against
# a per-task ceiling of a few cents, so a checkpoint is reached within a turn or
# two. Costs well under a dollar per mode. Writes nothing outside its own temporary
# directory, except the transcripts Claude Code keeps for any session, which it
# removes.

set -uo pipefail

MODE="${1:-converging}"
MAX_TURNS="${2:-40}"
HERE="$(cd "$(dirname "$0")/../.." && pwd)"
STOP="$HERE/hooks/autopilot-stop.py"
PRETOOL="$HERE/hooks/autopilot-pretool.py"
CEILING="${CEILING:-20000}"     # micro-dollars per task

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }
command -v git     >/dev/null 2>&1 || { echo "git not on PATH" >&2; exit 2; }

DIR=$(mktemp -d) || exit 2
DIR=$(cd "$DIR" && pwd -P)
cleanup() {
    rm -rf "$HOME/.claude/projects/$(printf '%s' "$DIR" | tr '/._' '---')"
    rm -rf "$DIR"
}
trap cleanup EXIT
mkdir -p "$DIR/.efficiency" "$DIR/.claude"

case "$MODE" in
    # One task longer than its ceiling, producing something every turn: the case
    # the checkpoint exists for. A blind ceiling stops it partway; a working
    # checkpoint grants tranches until it closes.
    # One task longer than its ceiling, producing something every turn: the case
    # the checkpoint exists for. A blind ceiling stops it partway; a working
    # checkpoint grants tranches until it closes.
    converging) TASKS='- [ ] T1 Create part-01.txt through part-20.txt, each holding only its own number, exactly ONE file per turn and then end your turn (the autopilot continues you); tick T1 once all twenty exist.' ;;
    impossible) TASKS='- [ ] T1 Read the licence key out of /nonexistent/licence-key.txt and write it to key.txt; do not tick this box unless you actually read the key out of that file.
- [ ] T2 Write the key'"'"'s expiry date, on the second line of the same file, to expiry.txt.' ;;
    *) echo "unknown mode: $MODE (expected converging|impossible)" >&2; exit 2 ;;
esac

cat > "$DIR/.efficiency/policy.md" <<'POLICY'
---
gate: ""
budget:
  supervisor: haiku
---
POLICY

cat > "$DIR/.efficiency/run.md" <<RUN
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
task_spend_max_micro_usd: $CEILING
blocked_reason:
---

## Tasks

$TASKS

## Log

- run opened by the supervisor-checkpoint probe
RUN

( cd "$DIR" && git init -q && git config user.email p@p && git config user.name p \
  && printf '.efficiency/\n.claude/\nhook.log\nstop.sh\npretool.sh\nsettings.json\n' > .gitignore \
  && git add .gitignore && git commit -qm base )

for h in stop pretool; do
    script=$STOP; [ "$h" = pretool ] && script=$PRETOOL
    cat > "$DIR/$h.sh" <<WRAP
#!/bin/bash
payload=\$(cat)
out=\$(printf '%s' "\$payload" | CLAUDE_PROJECT_DIR="$DIR" python3 "$script")
code=\$?
[ "$h" = stop ] && printf '=== stop (exit %s) ===\n%s\n' "\$code" "\$out" >> "$DIR/hook.log"
printf '%s' "\$out"
exit \$code
WRAP
    chmod +x "$DIR/$h.sh"
done

cat > "$DIR/settings.json" <<JSON
{"hooks": {
  "Stop": [{"hooks": [{"type": "command", "command": "bash $DIR/stop.sh", "timeout": 600}]}],
  "PreToolUse": [{"hooks": [{"type": "command", "command": "bash $DIR/pretool.sh", "timeout": 20}]}]
}}
JSON

echo "mode=$MODE  ceiling=$CEILING micro-USD  claude=$(claude --version)"
( cd "$DIR" && claude -p "Work the run in .efficiency/run.md, starting with T1." \
    --setting-sources project,local --model haiku --max-turns "$MAX_TURNS" \
    --max-budget-usd 1.00 --permission-mode acceptEdits \
    --settings "$DIR/settings.json" </dev/null >/dev/null 2>&1 )

DIR="$DIR" MODE="$MODE" python3 - <<'PY'
import json, os, re
d, mode = os.environ["DIR"], os.environ["MODE"]
priv = json.load(open(os.path.join(d, ".efficiency", "autopilot.json")))
run = open(os.path.join(d, ".efficiency", "run.md")).read()
front = dict(l.split(":", 1) for l in run.split("---")[1].strip().split("\n") if ":" in l)
status = front.get("status", "").strip()
closed = len(re.findall(r"^- \[x\]", run, re.M))
total = len(re.findall(r"^- \[[ xX>]\]", run, re.M))
cps = priv.get("checkpoints") or []
print("status:            %s" % status)
print("tasks closed:      %d of %d" % (closed, total))
print("checkpoints:       %d" % len(cps))
for c in cps:
    print("  %-24s %-11s %s" % (c.get("kind"), c.get("verdict"), c.get("why")))
print("supervisor spend:  $%.4f" % (priv.get("supervisor_spend_micro", 0) / 1e6))
print("blocked_reason:    %s" % (front.get("blocked_reason") or "").strip()[:400])
print()
granted = [c for c in cps if c.get("verdict") == "converging"]
if not cps and status == "DONE":
    print("verdict: INCONCLUSIVE — the run finished without reaching a checkpoint. Lower")
    print("         CEILING and re-run.")
elif mode == "converging":
    if status == "DONE" and granted:
        print("verdict: the checkpoint LET REAL WORK THROUGH: %d tranche(s) granted, run DONE."
              % len(granted))
    elif granted:
        print("verdict: tranches were granted (%d) but the run ended %s — check the reason."
              % (len(granted), status))
    else:
        print("verdict: the supervisor STOPPED CONVERGING WORK — too strict. Read its reason.")
else:
    if status == "BLOCKED" and "checkpoint" in (front.get("blocked_reason") or ""):
        print("verdict: the checkpoint STOPPED THE LOOP, with the supervisor's or the barren rule's")
        print("         reason, after %d verdict(s)." % len(cps))
    elif status == "BLOCKED":
        print("verdict: stopped, but not by a checkpoint — read the reason.")
    else:
        print("verdict: NOT STOPPED (%s) — the loop ran on. That is a failure." % status)
PY
