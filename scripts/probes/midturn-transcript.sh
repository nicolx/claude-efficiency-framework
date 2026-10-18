#!/bin/bash
# midturn-transcript.sh — does the session transcript grow DURING a turn, or only at its end?
#
# This is the question that decides whether a spend ceiling can be enforced mid-turn at
# all. hooks/lib/spend.py measures spend by summing `message.usage` out of the session
# transcript. The Stop hook can do that because § 1 established that `transcript_path`
# arrives on Stop. Nothing here has ever established *when the rows land*: if the JSONL
# is only flushed as the turn closes, then a hook firing mid-turn has nothing to read and
# a mid-turn ceiling is impossible, however it is wired.
#
#   bash scripts/probes/midturn-transcript.sh [max-turns]
#
# Costs a few cents of Haiku. Writes nothing outside its own temporary directory.
#
# Method: a PostToolUse hook counts the transcript's rows on every tool call of a single
# turn, and a Stop hook counts them again at the end. Three separate Bash calls are forced
# into one turn, so an incremental transcript must show the count rising between them.
#
# What is being read, per invocation:
#   * whether the payload carries transcript_path at all (undocumented for PostToolUse,
#     exactly as it was for Stop);
#   * how many rows the file holds, and how many of them carry message.usage — usage rows
#     are the only ones spend.py can price, so a growing row count with a flat usage count
#     would still mean a blind meter;
#   * how stale the file is, so "it grew" can be told apart from "it was already there".
#
# `--settings` rather than a .claude/settings.json in the temp project, as in stop-cap.sh:
# it makes the probe independent of whatever the directory-trust rules are in a release.

set -uo pipefail

MAX_TURNS="${1:-12}"

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

DIR=$(mktemp -d) || exit 2
trap 'rm -rf "$DIR"' EXIT

cat > "$DIR/observe.py" <<'HOOK'
#!/usr/bin/env python3
"""Record what the transcript looks like at the instant this hook fires.

Never blocks and never fails the turn: a probe that wedges the session it is
measuring produces no measurement.
"""
import json, os, sys, time

DIR = os.path.dirname(os.path.abspath(__file__))
OBS = os.path.join(DIR, "obs.jsonl")


def emit(record):
    with open(OBS, "a") as fh:
        fh.write(json.dumps(record) + "\n")


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception as exc:
        emit({"error": "payload did not parse: %s" % exc, "raw_len": len(raw)})
        return

    event = payload.get("hook_event_name", "?")
    path = payload.get("transcript_path")
    rec = {
        "event": event,
        "at": time.time(),
        "payload_keys": sorted(payload),
        "has_transcript_path": bool(path),
        "tool": payload.get("tool_name"),
    }

    if path and os.path.isfile(path):
        rows = usage_rows = assistant_rows = 0
        last_ts = None
        try:
            with open(path, errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    rows += 1
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(row, dict):
                        continue
                    if row.get("timestamp"):
                        last_ts = row["timestamp"]
                    msg = row.get("message")
                    if isinstance(msg, dict):
                        if msg.get("role") == "assistant":
                            assistant_rows += 1
                        if isinstance(msg.get("usage"), dict):
                            usage_rows += 1
            rec.update(rows=rows, usage_rows=usage_rows,
                       assistant_rows=assistant_rows, last_row_ts=last_ts,
                       file_age_s=round(time.time() - os.path.getmtime(path), 3))
        except Exception as exc:
            rec["read_error"] = str(exc)
    elif path:
        rec["read_error"] = "transcript_path points at nothing on disk"

    emit(rec)


try:
    main()
except Exception as exc:  # a probe is never fatal to the session it measures
    try:
        emit({"error": "hook raised: %s" % exc})
    except Exception:
        pass
sys.exit(0)
HOOK

DIR="$DIR" python3 - <<'PY'
import json, os
d = os.environ["DIR"]
hook = {"type": "command", "command": 'python3 "%s/observe.py"' % d, "timeout": 15}
json.dump({"permissions": {"allow": ["Bash(echo:*)"]},
           "hooks": {"PostToolUse": [{"hooks": [hook]}],
                     "Stop":        [{"hooks": [hook]}]}},
          open(os.path.join(d, "settings.json"), "w"))
PY

PROMPT='Run these three shell commands as three separate Bash tool calls, one at a time, in order: first "echo one", then "echo two", then "echo three". Do not combine them into a single command. Then reply with the word done.'

echo "max_turns=$MAX_TURNS"
OUT=$( cd "$DIR" && claude -p "$PROMPT" --model haiku \
         --setting-sources project,local \
         --max-turns "$MAX_TURNS" --max-budget-usd 0.50 \
         --permission-mode dontAsk --settings "$DIR/settings.json" </dev/null 2>&1 )

echo "--- session said ---"
printf '%s\n' "$OUT" | tail -3
echo "--------------------"

DIR="$DIR" python3 - <<'PY'
import json, os, sys

obs_path = os.path.join(os.environ["DIR"], "obs.jsonl")
if not os.path.isfile(obs_path):
    print("verdict: THE HOOK NEVER FIRED — the probe is broken, not the platform.")
    raise SystemExit(2)

obs = []
for line in open(obs_path):
    line = line.strip()
    if line:
        obs.append(json.loads(line))

post = [o for o in obs if o.get("event") == "PostToolUse"]
stop = [o for o in obs if o.get("event") == "Stop"]

print("observations: %d PostToolUse, %d Stop" % (len(post), len(stop)))
if post:
    print("PostToolUse payload keys: %s" % ", ".join(post[0].get("payload_keys", [])))
print()
print("  %-14s %-6s %7s %7s %10s %9s" % ("event", "tool", "rows", "usage", "assistant", "age_s"))
for o in obs:
    if o.get("error"):
        print("  %-14s %s" % (o.get("event", "?"), o["error"]))
        continue
    print("  %-14s %-6s %7s %7s %10s %9s" % (
        o.get("event", "?"), (o.get("tool") or "-")[:6],
        o.get("rows", "-"), o.get("usage_rows", "-"),
        o.get("assistant_rows", "-"), o.get("file_age_s", "-")))
print()

if not post:
    print("verdict: no PostToolUse invocation was recorded — the turn made no tool call,")
    print("         so this run measured nothing. Re-run; if it repeats, the prompt is")
    print("         no longer producing three separate Bash calls.")
    raise SystemExit(2)

missing = [o for o in post if not o.get("has_transcript_path")]
if missing:
    print("verdict: PostToolUse does NOT carry transcript_path (%d of %d invocations)."
          % (len(missing), len(post)))
    print("         A mid-turn hook cannot locate the transcript from its payload. It could")
    print("         still be derived from session_id, which is a separate question.")
    raise SystemExit(1)

usage = [o.get("usage_rows") for o in post if isinstance(o.get("usage_rows"), int)]
if not usage:
    print("verdict: transcript_path arrived but could not be read — see read_error above.")
    raise SystemExit(1)

grew = len(usage) > 1 and usage[-1] > usage[0]
final = stop[-1].get("usage_rows") if stop and isinstance(stop[-1].get("usage_rows"), int) else None

if grew:
    print("verdict: THE TRANSCRIPT IS INCREMENTAL. Usage rows went %s across the turn's"
          % " -> ".join(str(u) for u in usage))
    print("         tool calls, so a hook firing mid-turn can price what has been spent so")
    print("         far. A mid-turn ceiling is measurable.")
    if final is not None:
        print("         Stop saw %d; the last mid-turn reading was %d, so the gap a mid-turn"
              % (final, usage[-1]))
        print("         guard cannot see is %d usage row(s)." % (final - usage[-1]))
elif final is not None and final > usage[-1]:
    print("verdict: THE TRANSCRIPT IS NOT INCREMENTAL WITHIN THE TURN. Mid-turn readings")
    print("         stayed at %s while Stop saw %d — the rows for this turn land only as it"
          % (usage, final))
    print("         closes. A mid-turn spend ceiling cannot be built on this transcript.")
    raise SystemExit(1)
else:
    print("verdict: INCONCLUSIVE. Mid-turn usage rows %s and Stop %s do not separate the two"
          % (usage, final))
    print("         cases. Most likely the turn made too few tool calls to tell.")
    raise SystemExit(2)
PY
