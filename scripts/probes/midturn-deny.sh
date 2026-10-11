#!/bin/bash
# midturn-deny.sh — can a hook actually arrest a turn that is already running?
#
# midturn-transcript.sh established that spend is *measurable* mid-turn. That is only half
# of a ceiling. The other half is whether anything can be done about it: the Stop hook
# stops a run by refusing to let the turn end, and no such lever is documented for a turn
# in flight. PreToolUse can refuse one tool call — the question is what a turn does when
# every subsequent call is refused, and how much work it gets through first.
#
#   bash scripts/probes/midturn-deny.sh [allow-first] [max-turns]
#
# Costs a few cents of Haiku. Writes nothing outside its own temporary directory.
#
# Method: a PreToolUse hook permits the first N tool calls of a turn and denies every one
# after that, as a spend guard would at the moment the ceiling is crossed. The prompt asks
# for far more calls than N. A PostToolUse hook fires alongside it, because the only
# trustworthy evidence that a denial was honoured is that the tool did not then run.
#
# Three numbers come out of it, and the middle one is the finding:
#   * were denials honoured at all (PostToolUse count vs permitted count);
#   * how many further calls the turn attempted before giving up — the overshoot a
#     deny-based ceiling still pays, in refused calls rather than in work;
#   * whether the turn ended on its own, or had to be bound by --max-turns.

set -uo pipefail

ALLOW_FIRST="${1:-2}"
MAX_TURNS="${2:-20}"

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

DIR=$(mktemp -d) || exit 2
trap 'rm -rf "$DIR"' EXIT
printf '%s' "$ALLOW_FIRST" > "$DIR/allow_first"

cat > "$DIR/gate.py" <<'HOOK'
#!/usr/bin/env python3
"""Permit the first N tool calls of the session, deny every one after it.

Stands in for a spend guard that has just measured the ceiling crossed. Never
raises: on any internal failure it permits, because a probe that wedges the
session it is measuring produces no measurement.
"""
import json, os, sys, time

DIR = os.path.dirname(os.path.abspath(__file__))
OBS = os.path.join(DIR, "obs.jsonl")
COUNT = os.path.join(DIR, "count")

REASON = ("Spend ceiling reached for this task. Stop calling tools, and end your turn "
          "with a short report of what you completed.")


def emit(record):
    with open(OBS, "a") as fh:
        fh.write(json.dumps(record) + "\n")


def main():
    payload = json.loads(sys.stdin.read())
    event = payload.get("hook_event_name", "?")

    if event != "PreToolUse":
        emit({"event": event, "at": time.time(), "tool": payload.get("tool_name"),
              "has_transcript_path": bool(payload.get("transcript_path"))})
        return

    allow_first = int(open(os.path.join(DIR, "allow_first")).read().strip())
    try:
        n = int(open(COUNT).read().strip())
    except Exception:
        n = 0
    n += 1
    with open(COUNT, "w") as fh:
        fh.write(str(n))

    denied = n > allow_first
    emit({"event": event, "at": time.time(), "n": n, "denied": denied,
          "tool": payload.get("tool_name"),
          "payload_keys": sorted(payload),
          "has_transcript_path": bool(payload.get("transcript_path"))})

    if denied:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON}}))


try:
    main()
except Exception as exc:
    try:
        emit({"error": "hook raised: %s" % exc})
    except Exception:
        pass
sys.exit(0)
HOOK

DIR="$DIR" python3 - <<'PY'
import json, os
d = os.environ["DIR"]
hook = {"type": "command", "command": 'python3 "%s/gate.py"' % d, "timeout": 15}
json.dump({"permissions": {"allow": ["Bash(echo:*)"]},
           "hooks": {"PreToolUse":  [{"hooks": [hook]}],
                     "PostToolUse": [{"hooks": [hook]}],
                     "Stop":        [{"hooks": [hook]}]}},
          open(os.path.join(d, "settings.json"), "w"))
PY

PROMPT='Run the shell command "echo tick" eight times, as eight separate Bash tool calls, one at a time. Do not combine them and do not use a loop. When all eight are done, reply with the word finished.'

echo "allow_first=$ALLOW_FIRST  max_turns=$MAX_TURNS"
OUT=$( cd "$DIR" && claude -p "$PROMPT" --model haiku \
         --max-turns "$MAX_TURNS" --max-budget-usd 0.50 \
         --permission-mode dontAsk --settings "$DIR/settings.json" </dev/null 2>&1 )

echo "--- session said ---"
printf '%s\n' "$OUT" | tail -5
echo "--------------------"

printf '%s' "$OUT" > "$DIR/out.txt"
DIR="$DIR" ALLOW_FIRST="$ALLOW_FIRST" python3 - <<'PY'
import json, os

d = os.environ["DIR"]
allow_first = int(os.environ["ALLOW_FIRST"])
obs_path = os.path.join(d, "obs.jsonl")
if not os.path.isfile(obs_path):
    print("verdict: THE HOOK NEVER FIRED — the probe is broken, not the platform.")
    raise SystemExit(2)

obs = [json.loads(l) for l in open(obs_path) if l.strip()]
pre = [o for o in obs if o.get("event") == "PreToolUse"]
post = [o for o in obs if o.get("event") == "PostToolUse"]
stop = [o for o in obs if o.get("event") == "Stop"]
permitted = [o for o in pre if not o.get("denied")]
denied = [o for o in pre if o.get("denied")]

print("PreToolUse: %d (%d permitted, %d denied) · PostToolUse: %d · Stop: %d"
      % (len(pre), len(permitted), len(denied), len(post), len(stop)))
if pre:
    print("PreToolUse payload keys: %s" % ", ".join(pre[0].get("payload_keys", [])))
    print("PreToolUse carries transcript_path: %s"
          % ("yes" if all(o.get("has_transcript_path") for o in pre) else "NO"))
print()

out = open(os.path.join(d, "out.txt"), errors="replace").read()
bound_by_max_turns = "reached max turns" in out.lower()

if not denied:
    print("verdict: the turn never made more than %d tool call(s), so nothing was denied"
          % allow_first)
    print("         and this run measured nothing. Lower allow-first and re-run.")
    raise SystemExit(2)

if len(post) > len(permitted):
    print("verdict: DENIALS WERE NOT HONOURED. %d tool call(s) completed but only %d were"
          % (len(post), len(permitted)))
    print("         permitted — the deny decision did not stop the tool from running, so a")
    print("         PreToolUse guard cannot arrest a turn.")
    raise SystemExit(1)

print("verdict: DENIALS WERE HONOURED. %d call(s) ran, exactly the %d permitted; the other"
      % (len(post), len(permitted)))
print("         %d were refused and did not execute." % len(denied))
print()
print("         The turn attempted %d further tool call(s) after the first refusal before"
      % len(denied))
if bound_by_max_turns:
    print("         giving up — and it did NOT give up on its own: --max-turns bound it.")
    print("         A deny-based ceiling therefore stops the work but not the turn, and the")
    print("         refused calls are the overshoot it still pays for.")
    raise SystemExit(1)
print("         it ended the turn by itself. That is the overshoot a deny-based ceiling")
print("         still pays: refused calls, each one a model round trip, not work.")
PY
