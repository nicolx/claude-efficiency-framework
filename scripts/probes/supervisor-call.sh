#!/bin/bash
# supervisor-call.sh — can a Stop hook ask a second, cheaper model for a verdict?
#
# The spend ceiling is blind: it stops a task that is converging exactly as it
# stops one that loops. A supervisor that judges the work at the ceiling would let
# the first through and stop the second. Before building one, three things have to
# be measured rather than assumed:
#
#   nested   a command Stop hook spawns `claude -p` on Haiku. Does it work from
#            inside the hook, how long does it take, does its JSON carry its own
#            cost, does it re-fire the parent's hooks, and does its spend leak
#            into the parent transcript (where spend.py would count it) or not?
#   prompt   the platform's own `type: "prompt"` Stop hook. Does it fire on this
#            release, can it block, and is its cost visible anywhere a hook reads?
#
#   bash scripts/probes/supervisor-call.sh nested
#   bash scripts/probes/supervisor-call.sh prompt [model-id]
#
# Costs a few cents of Haiku each. Writes nothing outside its own temporary
# directory, except the transcripts Claude Code writes for any session.

set -uo pipefail

MODE="${1:-nested}"
# The prompt hook's model. On 2.1.306 the alias `haiku` is refused there
# (unrecognized_model) although `--model haiku` is accepted: pass a full id.
PROMPT_MODEL="${2:-claude-haiku-5-5}"
command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

DIR=$(mktemp -d) || exit 2
DIR=$(cd "$DIR" && pwd -P)
trap 'rm -rf "$DIR"' EXIT
mkdir -p "$DIR/.claude"

# A SessionStart marker: if the nested session re-fires the parent's hooks, the
# count is 2, and a supervisor would recurse into the framework that called it.
cat > "$DIR/session-start.sh" <<SS
#!/bin/bash
cat >/dev/null
echo x >> "$DIR/session-starts"
SS
chmod +x "$DIR/session-start.sh"

# The verdict shape a real supervisor would return.
SCHEMA='{"type":"object","properties":{"verdict":{"type":"string","enum":["converging","looping","diverging"]},"why":{"type":"string"}},"required":["verdict","why"]}'

cat > "$DIR/nested.sh" <<NESTED
#!/bin/bash
D="$DIR"
payload=\$(cat)
printf '%s' "\$payload" > "\$D/stop-payload.json"
n=\$(( \$(cat "\$D/count" 2>/dev/null || echo 0) + 1 ))
echo "\$n" > "\$D/count"
[ "\$n" -gt 1 ] && exit 0
env | grep -E '^(CLAUDE|ANTHROPIC)' | sed 's/=.*//' | sort > "\$D/hook-env"
start=\$(python3 -c 'import time; print(time.time())')
claude -p "A task asked for a function add(a,b) returning a+b. The diff so far adds 'def add(a, b): return a + b' and its test passes. Is the work converging, looping or diverging?" \
    --safe-mode --setting-sources project,local --model haiku --tools "" --no-session-persistence \
    --output-format json --json-schema '$SCHEMA' --max-budget-usd 0.05 \
    </dev/null > "\$D/nested.json" 2> "\$D/nested.err"
echo \$? > "\$D/nested.rc"
python3 -c "import time; print(round(time.time()-\$start, 1))" > "\$D/nested.secs"
exit 0
NESTED
chmod +x "$DIR/nested.sh"

case "$MODE" in
    nested)
        STOP_HOOK='{"type":"command","command":"bash '"$DIR"'/nested.sh","timeout":120}' ;;
    prompt)
        # The documented shape: the model answers {"ok": bool, "reason": str}.
        # Told to refuse the first stop, so a block is observable as a second turn.
        STOP_HOOK='{"type":"prompt","model":"'"$PROMPT_MODEL"'","timeout":60,"prompt":"You supervise an agent. If the transcript below contains the word BANANA anywhere in an assistant message, answer ok=true. Otherwise answer ok=false with reason: Say the word BANANA, then stop. $ARGUMENTS"}' ;;
    *) echo "unknown mode: $MODE (expected nested|prompt)" >&2; exit 2 ;;
esac

cat > "$DIR/settings.json" <<JSON
{"hooks": {
  "SessionStart": [{"hooks": [{"type": "command", "command": "bash $DIR/session-start.sh"}]}],
  "Stop": [{"hooks": [$STOP_HOOK]}]
}}
JSON

echo "mode=$MODE  claude=$(claude --version)"
OUT=$( cd "$DIR" && claude -p "Reply with the single word: ok" \
         --setting-sources project,local --model haiku --max-turns 6 \
         --max-budget-usd 0.30 --output-format json \
         --permission-mode dontAsk --settings "$DIR/settings.json" </dev/null 2>&1 )
printf '%s' "$OUT" > "$DIR/parent.json"

DIR="$DIR" MODE="$MODE" python3 - <<'PY'
import glob, json, os
d, mode = os.environ["DIR"], os.environ["MODE"]

def read(name, default=""):
    try:
        return open(os.path.join(d, name)).read().strip()
    except OSError:
        return default

def parse(text):
    try:
        return json.loads(text)
    except ValueError:
        return {}

parent = parse(read("parent.json"))
print("parent result:     %r" % (parent.get("result") or read("parent.json")[:200]))
print("parent cost (USD): %s" % parent.get("total_cost_usd"))
print("session starts:    %s" % len(read("session-starts").splitlines()))

# Where Claude Code keeps this project's transcripts.
slug = d.replace("/", "-").replace(".", "-").replace("_", "-")
tdir = os.path.expanduser("~/.claude/projects/" + slug)
transcripts = sorted(glob.glob(os.path.join(tdir, "*.jsonl")))
print("transcripts:       %d in %s" % (len(transcripts), tdir))
for t in transcripts:
    models, n = {}, 0
    for line in open(t):
        rec = parse(line)
        msg = rec.get("message") or {}
        if rec.get("type") == "assistant" and msg.get("usage"):
            n += 1
            models[msg.get("model")] = models.get(msg.get("model"), 0) + 1
    print("  %s  assistant-with-usage=%d models=%s" % (os.path.basename(t), n, models))
    if mode == "prompt":
        for line in open(t):
            if "BANANA" in line or "hook" in line.lower() and "prompt" in line.lower():
                rec = parse(line)
                print("    %s: %s" % (rec.get("type"), line[:240].rstrip()))

if mode == "nested":
    print("hook invocations:  %s" % read("count", "0"))
    print("hook env (names):  %s" % " ".join(read("hook-env").split()))
    print("nested rc:         %s" % read("nested.rc", "never ran"))
    print("nested seconds:    %s" % read("nested.secs"))
    nested = parse(read("nested.json"))
    print("nested cost (USD): %s" % nested.get("total_cost_usd"))
    print("nested structured: %s" % nested.get("structured_output"))
    print("nested usage keys: %s" % sorted((nested.get("modelUsage") or {}).keys()))
    err = read("nested.err")
    if err:
        print("nested stderr:     %s" % err[:400])
    if not nested:
        print("nested raw:        %s" % read("nested.json")[:400])
else:
    print("parent turns:      %s" % parent.get("num_turns"))
    print("parent modelUsage: %s" % json.dumps(parent.get("modelUsage"), indent=None)[:600])
PY

# Clean up the transcripts this probe created, so it leaves nothing behind.
SLUG=$(printf '%s' "$DIR" | tr '/._' '---')
rm -rf "$HOME/.claude/projects/$SLUG"
