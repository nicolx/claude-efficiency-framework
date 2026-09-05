#!/bin/bash
# settings-trust.sh — re-measure that a freshly created directory's project
# settings are silently ignored, while the identical hook passed via --settings
# fires normally.
#
# The claim in docs/verified-platform-behaviour.md § 7 rests on this. Re-run it
# after a Claude Code upgrade rather than trusting a number someone wrote down
# once.
#
#   bash scripts/probes/settings-trust.sh
#
# Costs a few cents of Haiku and a few seconds. Writes nothing outside its own
# temporary directory.

set -uo pipefail

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

DIR=$(mktemp -d) || exit 2
trap 'rm -rf "$DIR"' EXIT

PROJECT_MARKER="$DIR/project-fired"
EXPLICIT_MARKER="$DIR/explicit-fired"

make_settings() {
    # $1 = path the hook should touch when it fires, $2 = settings.json to write
    MARKER="$1" OUT="$2" python3 - <<'PY'
import json, os
marker = os.environ["MARKER"]
out = os.environ["OUT"]
json.dump({"hooks": {"SessionStart": [{"hooks": [{"type": "command",
                                                    "command": 'touch "%s"' % marker,
                                                    "timeout": 10}]}]}},
          open(out, "w"))
PY
}

# Case A: project settings written into a directory nobody has ever trusted.
# Per section 7, this should be silently ignored — no warning, no error, the
# hook simply never runs.
PROJECT_DIR="$DIR/project"
mkdir -p "$PROJECT_DIR/.claude"
make_settings "$PROJECT_MARKER" "$PROJECT_DIR/.claude/settings.json"

( cd "$PROJECT_DIR" && claude -p "Reply with the single word: ok" --model haiku \
    --max-turns 1 --max-budget-usd 0.20 --permission-mode dontAsk </dev/null >/dev/null 2>&1 )

# Case B: the identical hook, passed via --settings — the documented way to
# test a hook without needing workspace trust at all.
EXPLICIT_DIR="$DIR/explicit"
mkdir -p "$EXPLICIT_DIR"
make_settings "$EXPLICIT_MARKER" "$DIR/explicit-settings.json"

( cd "$EXPLICIT_DIR" && claude -p "Reply with the single word: ok" --model haiku \
    --max-turns 1 --max-budget-usd 0.20 --permission-mode dontAsk \
    --settings "$DIR/explicit-settings.json" </dev/null >/dev/null 2>&1 )

PROJECT_FIRED=0
[ -f "$PROJECT_MARKER" ] && PROJECT_FIRED=1
EXPLICIT_FIRED=0
[ -f "$EXPLICIT_MARKER" ] && EXPLICIT_FIRED=1

project_word() { [ "$PROJECT_FIRED" -eq 1 ] && echo yes || echo no; }
explicit_word() { [ "$EXPLICIT_FIRED" -eq 1 ] && echo yes || echo no; }

echo "project settings in a fresh directory fired the hook: $(project_word)"
echo "the same hook via --settings fired:                    $(explicit_word)"

if [ "$PROJECT_FIRED" -eq 0 ] && [ "$EXPLICIT_FIRED" -eq 1 ]; then
    echo "verdict: CONFIRMED — a fresh directory's project settings are silently ignored;"
    echo "         --settings is the reliable way to test a hook."
elif [ "$PROJECT_FIRED" -eq 0 ] && [ "$EXPLICIT_FIRED" -eq 0 ]; then
    echo "verdict: NEITHER CASE FIRED — this is the probe being broken, not evidence of"
    echo "         the finding. Check that claude and the hook command both work at all."
elif [ "$PROJECT_FIRED" -eq 1 ] && [ "$EXPLICIT_FIRED" -eq 1 ]; then
    echo "verdict: NOT REPRODUCED — the platform now trusts a fresh directory's project"
    echo "         settings. Re-check docs/verified-platform-behaviour.md section 7."
else
    echo "verdict: UNEXPECTED — project settings fired but --settings did not. Investigate"
    echo "         before trusting either result."
fi
