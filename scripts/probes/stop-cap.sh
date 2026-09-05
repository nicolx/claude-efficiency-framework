#!/bin/bash
# stop-cap.sh — re-measure the platform's Stop-hook block cap.
#
# The claims in docs/verified-platform-behaviour.md rest on this. Re-run it after a
# Claude Code upgrade rather than trusting a number someone wrote down once.
#
#   bash scripts/probes/stop-cap.sh stall [max-turns]   # no tool call between blocks
#   bash scripts/probes/stop-cap.sh write [max-turns]   # one file written per turn
#   bash scripts/probes/stop-cap.sh read  [max-turns]   # one read-only command per turn
#
# Costs a few cents of Haiku and a couple of minutes. Writes nothing outside its own
# temporary directory.
#
# Why --settings and not a .claude/settings.json in the temp project: a freshly created
# directory is not a trusted workspace, and its project settings are silently ignored —
# hooks never fire and the probe reports a clean zero. That failure looks exactly like
# "the platform changed". --settings sidesteps trust entirely.

set -uo pipefail

MODE="${1:-stall}"
MAX_TURNS="${2:-40}"

case "$MODE" in
    stall) INSTRUCTION="Reply with the single word: ok"
           PROMPT="Reply with the single word: ok"
           PERM=dontAsk ;;
    write) INSTRUCTION="Create ONE new file named step-N.txt (N = this invocation number) containing the word done, then stop"
           PROMPT="Create a file step-0.txt containing the word done."
           PERM=acceptEdits ;;
    read)  INSTRUCTION="Run exactly this shell command and nothing else: echo tick. Do not create or edit any file."
           PROMPT="Run the shell command: echo tick"
           PERM=dontAsk ;;
    *)     echo "unknown mode: $MODE (expected stall|write|read)" >&2; exit 2 ;;
esac

command -v claude   >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3  >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

DIR=$(mktemp -d) || exit 2
trap 'rm -rf "$DIR"' EXIT

cat > "$DIR/probe.sh" <<'HOOK'
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
payload=$(cat)
n=$(( $(cat "$DIR/count" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$DIR/count"
printf '=== invocation %s ===\n%s\n' "$n" "$payload" >> "$DIR/payloads.log"
python3 -c 'import json,sys; print(json.dumps({"decision":"block","reason":sys.argv[1]}))' \
    "invocation $n. $(cat "$DIR/instruction")"
exit 0
HOOK
chmod +x "$DIR/probe.sh"
printf '%s' "$INSTRUCTION" > "$DIR/instruction"

DIR="$DIR" python3 - <<'PY'
import json, os
d = os.environ["DIR"]
json.dump({"permissions": {"allow": ["Bash(echo:*)"]},
           "hooks": {"Stop": [{"hooks": [{"type": "command",
                                          "command": 'bash "%s/probe.sh"' % d,
                                          "timeout": 10}]}]}},
          open(os.path.join(d, "settings.json"), "w"))
PY

echo "mode=$MODE  max_turns=$MAX_TURNS"
OUT=$( cd "$DIR" && claude -p "$PROMPT" --model haiku \
         --max-turns "$MAX_TURNS" --max-budget-usd 0.50 \
         --permission-mode "$PERM" --settings "$DIR/settings.json" </dev/null 2>&1 )

COUNT=$(cat "$DIR/count" 2>/dev/null || echo 0)
echo "hook invocations: $COUNT"

if [ "$COUNT" -eq 0 ]; then
    echo "verdict: THE HOOK NEVER FIRED — the probe is broken, not the platform."
    echo "$OUT" | tail -3
elif printf '%s' "$OUT" | grep -qi 'reached max turns'; then
    echo "verdict: --max-turns bound this run. The platform cap never fired, so progress"
    echo "         resets its counter. Re-run with a larger max-turns to confirm it scales."
else
    echo "verdict: the PLATFORM cap bound this run at $COUNT invocations — progress did not"
    echo "         reset the counter, or there was no progress to reset it."
fi
