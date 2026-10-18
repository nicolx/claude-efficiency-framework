#!/bin/bash
# midturn-subagent.sh — does a SUBAGENT's tool call reach a PreToolUse hook, and which
# transcript does its payload name?
#
# This decides whether a mid-turn spend ceiling covers the expensive half of a routed run.
# § 6 established that subagent turns live in a sibling directory and were 17% of real
# spend on the session that produced this framework, which is why hooks/lib/spend.py reads
# both. A mid-turn guard inherits that problem in a sharper form: it is handed ONE
# transcript path by its payload, and if a subagent's call names the subagent's own
# transcript, measuring from it would price the delegated work alone — the wrong total,
# over the wrong window, at exactly the moment spend is highest.
#
#   bash scripts/probes/midturn-subagent.sh [max-turns]
#
# Costs a few cents of Haiku. Writes nothing outside its own temporary directory.
#
# Method: one session delegates a trivial command to a subagent. The command carries a
# marker word that ONLY the subagent is ever told to run, and the hook records each call's
# tool_input — so a Bash call bearing the marker came from inside the subagent, whoever
# the payload says it belongs to.
#
# The marker is there because the obvious test does not work. Timing looks like it should
# settle it — bracket the calls between the delegation's PreToolUse and its PostToolUse —
# and it is wrong: on 2.1.296 the delegation returns as soon as the subagent is *launched*,
# so PostToolUse for it fires before the subagent has called anything at all. A bracket
# built on that reports "no subagent calls arrived" for a run where they plainly did.

set -uo pipefail

MAX_TURNS="${1:-15}"
MARKER="subagent-side-marker"

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

DIR=$(mktemp -d) || exit 2
trap 'rm -rf "$DIR"' EXIT

cat > "$DIR/observe.py" <<'HOOK'
#!/usr/bin/env python3
"""Record which transcript each tool call names, and what it was about to run.

Never blocks and never fails: a probe that wedges the session it is measuring
produces no measurement.
"""
import json, os, sys, time

DIR = os.path.dirname(os.path.abspath(__file__))
OBS = os.path.join(DIR, "obs.jsonl")


def main():
    payload = json.loads(sys.stdin.read())
    path = payload.get("transcript_path") or ""
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        detail = tool_input.get("command") or tool_input.get("prompt") or ""
    else:
        detail = ""
    with open(OBS, "a") as fh:
        fh.write(json.dumps({
            "event": payload.get("hook_event_name"),
            "at": time.time(),
            "tool": payload.get("tool_name"),
            "session_id": payload.get("session_id"),
            "transcript_path": path,
            "is_subagent_transcript": "/subagents/" in path,
            "exists": os.path.isfile(path) if path else False,
            "detail": str(detail)[:200],
        }) + "\n")


try:
    main()
except Exception:
    pass
sys.exit(0)
HOOK

DIR="$DIR" python3 - <<'PY'
import json, os
d = os.environ["DIR"]
hook = {"type": "command", "command": 'python3 "%s/observe.py"' % d, "timeout": 15}
json.dump({"permissions": {"allow": ["Bash(echo:*)", "Task", "Agent"]},
           "hooks": {"PreToolUse":    [{"hooks": [hook]}],
                     "PostToolUse":   [{"hooks": [hook]}],
                     "SubagentStop":  [{"hooks": [hook]}],
                     "Stop":          [{"hooks": [hook]}]}},
          open(os.path.join(d, "settings.json"), "w"))
PY

PROMPT="Use the Task tool to launch exactly one general-purpose subagent. Instruct that subagent to run the shell command \"echo $MARKER\" with the Bash tool and report the output it got. Do not run any shell command yourself — delegate it, and never type the word $MARKER into a tool call of your own. When the subagent reports back, reply with its output and nothing else."

echo "max_turns=$MAX_TURNS  marker=$MARKER"
OUT=$( cd "$DIR" && claude -p "$PROMPT" --model haiku \
         --setting-sources project,local \
         --max-turns "$MAX_TURNS" --max-budget-usd 0.75 \
         --permission-mode dontAsk --settings "$DIR/settings.json" </dev/null 2>&1 )

echo "--- session said ---"
printf '%s\n' "$OUT" | tail -3
echo "--------------------"

DIR="$DIR" MARKER="$MARKER" python3 - <<'PY'
import json, os

obs_path = os.path.join(os.environ["DIR"], "obs.jsonl")
marker = os.environ["MARKER"]
if not os.path.isfile(obs_path):
    print("verdict: THE HOOK NEVER FIRED — the probe is broken, not the platform.")
    raise SystemExit(2)

obs = [json.loads(l) for l in open(obs_path) if l.strip()]
pre = [o for o in obs if o.get("event") == "PreToolUse"]

# Agent on 2.1.296, Task on earlier builds. Matching both: a probe that misses the tool
# name reports "it never delegated" for a run that delegated perfectly well.
DELEGATION = ("Task", "Agent")

print("  %-4s %-13s %-8s %-9s %-38s %s"
      % ("#", "event", "tool", "sub-tx?", "transcript", "detail"))
for i, o in enumerate(obs, 1):
    print("  %-4d %-13s %-8s %-9s %-38s %s" % (
        i, (o.get("event") or "?")[:13], (o.get("tool") or "-")[:8],
        "yes" if o.get("is_subagent_transcript") else "no",
        os.path.basename(o.get("transcript_path") or "-")[:38],
        (o.get("detail") or "")[:60].replace("\n", " ")))
print()

delegations = [o for o in pre if o.get("tool") in DELEGATION]
paths = {o.get("transcript_path") for o in pre if o.get("transcript_path")}
sub_paths = {o.get("transcript_path") for o in pre if o.get("is_subagent_transcript")}
sessions = {o.get("session_id") for o in pre if o.get("session_id")}

# The marker appears in the delegation's own prompt too — that is the parent asking for
# the work, not doing it. Only a non-delegation call carrying it came from inside.
inside = [o for o in pre if o.get("tool") not in DELEGATION and marker in (o.get("detail") or "")]
substops = [o for o in obs if o.get("event") == "SubagentStop"]

print("PreToolUse invocations: %d (delegation: %d, marked as inside the subagent: %d)"
      % (len(pre), len(delegations), len(inside)))
print("distinct transcript paths: %d · distinct session ids: %d · SubagentStop events: %d"
      % (len(paths), len(sessions), len(substops)))
print()

if not delegations:
    print("verdict: the session never delegated — no %s call was seen, so this run"
          % "/".join(DELEGATION))
    print("         measured nothing about subagents. Re-run.")
    raise SystemExit(2)

if not inside:
    print("verdict: A SUBAGENT'S OWN TOOL CALLS DO NOT REACH THIS HOOK. The delegation was")
    print("         seen, but no marked call followed it. A PreToolUse ceiling can refuse")
    print("         the delegation before it starts and nothing inside it: spend within a")
    print("         subagent stays bounded at the turn boundary alone.")
    raise SystemExit(1)

if sub_paths:
    print("verdict: SUBAGENT CALLS ARRIVE, NAMING THE SUBAGENT'S OWN TRANSCRIPT (%d of %d"
          % (len(sub_paths), len(paths)))
    print("         distinct paths). A guard must map that path back to the parent session")
    print("         before measuring, or it prices the delegated work alone, over the wrong")
    print("         window.")
else:
    print("verdict: SUBAGENT CALLS ARRIVE, AND NAME THE PARENT SESSION'S TRANSCRIPT.")
    print("         %d marked call(s) reached the hook carrying the parent's transcript_path"
          % len(inside))
    print("         and session_id — the same payload the Stop hook already gets, so the")
    print("         measurement applies unchanged, and a mid-turn guard can refuse a")
    print("         subagent's own tool call rather than only the delegation.")
PY
