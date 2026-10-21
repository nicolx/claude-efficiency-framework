#!/bin/bash
# hook-allow.sh — can a PreToolUse hook grant a permission the session would not?
#
# The framework stops asking for commands it classifies as safe by answering
# `permissionDecision: "allow"` from its PreToolUse hook, instead of writing a static
# allowlist into the project. Three things have to be true for that to be worth anything,
# and none is safe to assume:
#
#   (a) the allow is honoured — a Bash call the permission mode would refuse runs;
#   (b) a deny rule still wins over the hook's allow — so a project's own fence keeps
#       its meaning, and the classifier does not have to re-implement it;
#   (c) it works in a directory nobody has trusted, where § 7 says permission rules
#       from project settings are ignored. That is the gap a static allowlist cannot
#       close and the reason the hook is the carrier.
#
#   bash scripts/probes/hook-allow.sh
#
# Costs a few cents of Haiku. Writes nothing outside its own temporary directory.
#
# Method: one headless session under `--permission-mode default`, where any Bash call no
# rule allows is refused (there is nobody to ask). It is told to run three `touch`
# commands. The hook allows two of them; the settings deny one of those two. A file that
# exists afterwards is a command that ran.
#
#   touch allowed   hook allows, no rule          → expected to exist   (a)
#   touch control   hook silent, no rule          → expected absent     the baseline
#   touch denied    hook allows, deny rule        → absent if (b) holds
#
# The working directory is a fresh mktemp one, never trusted, so the whole run is (c).

set -uo pipefail

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

DIR=$(mktemp -d) || exit 2
trap 'rm -rf "$DIR"' EXIT
WORK="$DIR/work"
mkdir -p "$WORK"

cat > "$DIR/gate.py" <<'HOOK'
#!/usr/bin/env python3
"""Allow `touch allowed` and `touch denied`; say nothing about anything else."""
import json, os, sys

DIR = os.path.dirname(os.path.abspath(__file__))
try:
    payload = json.loads(sys.stdin.read())
    cmd = (payload.get("tool_input") or {}).get("command", "")
    with open(os.path.join(DIR, "obs.jsonl"), "a") as fh:
        fh.write(json.dumps({"cmd": cmd, "mode": payload.get("permission_mode")}) + "\n")
    if "touch allowed" in cmd or "touch denied" in cmd:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "probe: classified safe"}}))
except Exception:
    pass
sys.exit(0)
HOOK

DIR="$DIR" python3 - <<'PY'
import json, os
d = os.environ["DIR"]
hook = {"type": "command", "command": 'python3 "%s/gate.py"' % d, "timeout": 15}
json.dump({"permissions": {"deny": ["Bash(touch denied)"]},
           "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [hook]}]}},
          open(os.path.join(d, "settings.json"), "w"))
PY

PROMPT='Run exactly these three shell commands, each as its own separate Bash tool call, in this order: "touch allowed", then "touch control", then "touch denied". If one is refused, do not retry it and do not try another way; move on to the next. Then reply with the word finished.'

OUT=$( cd "$WORK" && claude -p "$PROMPT" --model haiku \
         --setting-sources project,local \
         --max-turns 8 --max-budget-usd 0.30 \
         --permission-mode default --settings "$DIR/settings.json" </dev/null 2>&1 )

echo "--- session said ---"
printf '%s\n' "$OUT" | tail -4
echo "--------------------"

DIR="$DIR" WORK="$WORK" python3 - <<'PY'
import json, os

d, w = os.environ["DIR"], os.environ["WORK"]
obs_path = os.path.join(d, "obs.jsonl")
if not os.path.isfile(obs_path):
    print("verdict: THE HOOK NEVER FIRED — the probe is broken, not the platform.")
    raise SystemExit(2)
obs = [json.loads(l) for l in open(obs_path) if l.strip()]
print("hook saw: %s" % "; ".join("%s [%s]" % (o["cmd"], o["mode"]) for o in obs))

ran = {n: os.path.exists(os.path.join(w, n)) for n in ("allowed", "control", "denied")}
for n, r in ran.items():
    print("  touch %-8s %s" % (n, "RAN" if r else "did not run"))
print()

if ran["control"]:
    print("verdict: the control ran, so this permission mode refuses nothing and the probe")
    print("         measured nothing about the hook. The baseline is broken.")
    raise SystemExit(2)

fail = 0
if ran["allowed"]:
    print("(a) HOLDS: a hook allow runs a command the permission mode would have refused.")
else:
    print("(a) FAILS: the hook's allow was ignored; the command was refused anyway.")
    fail = 1
if ran["denied"]:
    print("(b) FAILS: the hook's allow OVERRODE a deny rule. A classifier must read the")
    print("           project's deny rules itself before allowing anything.")
    fail = 1
else:
    print("(b) HOLDS: a deny rule wins over the hook's allow.")
if ran["allowed"]:
    print("(c) HOLDS: all of it in a directory nobody has trusted.")
raise SystemExit(fail)
PY
