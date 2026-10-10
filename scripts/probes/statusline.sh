#!/bin/bash
# statusline.sh — measure what a `statusLine` command actually gets, how often
# it is re-run, and how many of the lines it prints are rendered.
#
# docs/verified-platform-behaviour.md § 12 rests on this. The status line is the
# only surface in Claude Code that is *continuously visible to the developer*,
# which is why the backlog is published through it — so how many lines survive
# the render is not cosmetic, it decides what can be shown at all.
#
# This probe cannot run headless: `claude -p` paints no status line. It installs
# a recorder, hands the session back to you, and reads what the recorder caught.
#
#   bash scripts/probes/statusline.sh install     # then START A NEW SESSION
#   bash scripts/probes/statusline.sh show        # what was caught, and the verdict
#   bash scripts/probes/statusline.sh uninstall   # put settings.json back
#
# It edits the project's `.claude/settings.json` — the one thing in this repo's
# probes that touches a file you care about — and backs it up first, beside it.
# `uninstall` restores the backup. Costs nothing: no model is called.

set -uo pipefail

command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

PROJECT=${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "$0")/../.." && pwd)}
SETTINGS="$PROJECT/.claude/settings.json"
BACKUP="$PROJECT/.claude/settings.json.statusline-probe.bak"
WORK="${TMPDIR:-/tmp}/efficiency-statusline-probe"
RECORDER="$WORK/recorder.py"
LOG="$WORK/observations.jsonl"

MODE=${1:-}

# The recorder prints five distinguishable lines on purpose. The question the
# probe exists to answer is how many of them the renderer keeps, and numbering
# them is the only way the answer survives being read off a terminal by eye.
write_recorder() {
    mkdir -p "$WORK" || exit 2
    cat > "$RECORDER" <<PY
#!/usr/bin/env python3
"""Written by scripts/probes/statusline.sh. Records, then prints five lines."""
import json, os, sys, time

raw = sys.stdin.read()
try:
    payload = json.loads(raw)
except ValueError:
    payload = {"_unparsed": raw[:2000]}

with open("$LOG", "a") as fh:
    fh.write(json.dumps({
        "at": time.time(),
        "pwd": os.getcwd(),
        "argv": sys.argv[1:],
        "env": {k: os.environ.get(k) for k in
                ("CLAUDE_PROJECT_DIR", "CLAUDE_PLUGIN_ROOT", "CLAUDE_SESSION_ID")},
        "payload": payload,
    }) + "\n")

for n in range(1, 6):
    print("PROBE-L%d %s" % (n, "x" * 20))
PY
    chmod +x "$RECORDER"
}

case "$MODE" in
install)
    [ -f "$SETTINGS" ] || { echo "no $SETTINGS to patch" >&2; exit 2; }
    if [ -f "$BACKUP" ]; then
        echo "a backup already exists at $BACKUP — run 'uninstall' first" >&2
        exit 2
    fi
    cp "$SETTINGS" "$BACKUP" || exit 2
    write_recorder
    : > "$LOG"
    SETTINGS="$SETTINGS" RECORDER="$RECORDER" python3 - <<'PY' || exit 2
import json, os
path = os.environ["SETTINGS"]
with open(path) as fh:
    data = json.load(fh)
data["statusLine"] = {"type": "command",
                      "command": 'python3 "%s"' % os.environ["RECORDER"],
                      "padding": 0}
with open(path, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
PY
    echo "recorder installed in $SETTINGS (backup: $BACKUP)"
    echo
    echo "NOW: start a new Claude Code session in this project, send two or three"
    echo "messages, and LOOK AT THE BOTTOM OF THE TERMINAL. The recorder prints five"
    echo "lines, PROBE-L1 … PROBE-L5. Write down how many of them you can see."
    echo
    echo "Then: bash scripts/probes/statusline.sh show"
    ;;

show)
    [ -s "$LOG" ] || { echo "nothing recorded yet — did a new session start since 'install'?" >&2; exit 1; }
    LOG="$LOG" python3 - <<'PY'
import json, os

rows = []
with open(os.environ["LOG"]) as fh:
    for line in fh:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

print("invocations recorded: %d" % len(rows))
if len(rows) > 1:
    gaps = [b["at"] - a["at"] for a, b in zip(rows, rows[1:])]
    gaps.sort()
    print("gap between invocations: min %.2fs  median %.2fs  max %.2fs"
          % (gaps[0], gaps[len(gaps) // 2], gaps[-1]))
    print("  (a gap far below a turn's length means it re-runs on conversation"
          "\n   updates, not once per turn — so the command must be cheap)")

last = rows[-1]
print("\ncwd of the command: %s" % last["pwd"])
print("argv: %r" % (last["argv"],))
for k, v in last["env"].items():
    print("env %s: %s" % (k, "SET -> %s" % v if v else "not set"))

payload = last["payload"]
print("\npayload keys: %s" % ", ".join(sorted(payload)))


def walk(d, prefix=""):
    for k in sorted(d):
        v = d[k]
        if isinstance(v, dict):
            walk(v, prefix + k + ".")
        else:
            shown = v if not isinstance(v, str) or len(v) < 60 else v[:57] + "…"
            print("  %s%s = %r" % (prefix, k, shown))


walk(payload)
print("\nVERDICT needs your eye too: how many of PROBE-L1…L5 did the terminal show?")
print("Record the number in docs/verified-platform-behaviour.md § 12 with today's date.")
PY
    ;;

uninstall)
    [ -f "$BACKUP" ] || { echo "no backup at $BACKUP — nothing to restore" >&2; exit 2; }
    mv "$BACKUP" "$SETTINGS" || exit 2
    echo "restored $SETTINGS"
    echo "observations kept at $LOG"
    ;;

*)
    sed -n '2,20p' "$0"
    exit 2
    ;;
esac
