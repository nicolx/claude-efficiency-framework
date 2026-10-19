#!/bin/bash
# transcript-shape.sh — inspect the shape of a session transcript and its subagents.
#
# The claims in docs/verified-platform-behaviour.md § 6 (Subagent turns are in
# separate transcripts; one row per content block) rest on this probe.
#
#   bash scripts/probes/transcript-shape.sh <path-to-session-transcript.jsonl>
#   bash scripts/probes/transcript-shape.sh --live [max-turns]
#
# Prints the subagents directory (or reports none exists), the set of usage keys found
# in the transcript and any subagent transcripts, the count of rows bearing usage data,
# and how those rows group into messages: how many messages span several rows, whether
# their input/cache usage repeats, and whether output_tokens differs between them. Then
# it prices the session twice — every row summed, and hooks/lib/spend.py (one per
# message). Never prints conversation content.
#
# --live runs a small headless Haiku session that thinks, calls tools and delegates to a
# subagent, then does all of the above on its transcript AND compares both figures with
# the session's own total_cost_usd. Costs a few cents. That comparison is the ground
# truth: on 2026-10-18 the row sum was 2-4x total_cost_usd, the per-message sum within
# a cent.
#
# Why this matters: a measurement that reads only transcript_path misses subagent
# spend entirely. A spending ceiling blind to them is a ceiling on the cheap work only.

set -uo pipefail

HERE=$(cd "$(dirname "$0")/../.." && pwd)
TRANSCRIPT_PATH="${1:-}"
REPORTED_COST=""

if [ "$TRANSCRIPT_PATH" = "--live" ]; then
    command -v claude >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
    MAX_TURNS="${2:-15}"
    LIVE=$(mktemp -d) || exit 2
    trap 'rm -rf "$LIVE"' EXIT
    printf '%s' '{"permissions": {"allow": ["Bash(echo:*)", "Task", "Agent"]}}' > "$LIVE/settings.json"
    PROMPT="Think briefly first. Then, in ONE reply, use the Bash tool twice: 'echo one' and 'echo two'. Then use the Task tool to launch exactly one general-purpose subagent that runs 'echo three' with Bash and reports the output. Do not run that command yourself. Finally reply with the three outputs and nothing else."
    echo "claude --version: $(claude --version 2>/dev/null)"
    JSON=$( cd "$LIVE" && claude -p "$PROMPT" --model haiku --output-format json \
              --setting-sources project,local --settings "$LIVE/settings.json" \
              --max-turns "$MAX_TURNS" --max-budget-usd 0.75 --permission-mode dontAsk \
              </dev/null 2>/dev/null )
    read -r SID REPORTED_COST < <(printf '%s' "$JSON" | python3 -c '
import json, sys
d = {}
for line in sys.stdin.read().splitlines():
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if isinstance(ev, dict) and ev.get("type") == "result":
        d = ev
print(d.get("session_id", ""), d.get("total_cost_usd", ""))')
    if [ -z "${SID:-}" ]; then
        echo "verdict: the live session returned no result event — the probe is broken, not the platform." >&2
        exit 2
    fi
    TRANSCRIPT_PATH=$(find "$HOME/.claude/projects" -name "$SID.jsonl" -type f 2>/dev/null | head -1)
    echo "live session $SID · total_cost_usd=$REPORTED_COST"
fi

if [ -z "$TRANSCRIPT_PATH" ]; then
    echo "usage: bash scripts/probes/transcript-shape.sh <path-to-session-transcript.jsonl>" >&2
    exit 2
fi

if [ ! -f "$TRANSCRIPT_PATH" ]; then
    echo "error: $TRANSCRIPT_PATH does not exist or is not a regular file" >&2
    exit 2
fi

# Derive session id from transcript filename (without .jsonl)
SESSION_ID=$(basename "$TRANSCRIPT_PATH" .jsonl)
PROJECT_DIR=$(dirname "$TRANSCRIPT_PATH")
SUBAGENTS_DIR="$PROJECT_DIR/$SESSION_ID/subagents"

# Report where we looked
echo "Subagents directory: $SUBAGENTS_DIR"
if [ -d "$SUBAGENTS_DIR" ]; then
    SUBAGENT_FILES=$(find "$SUBAGENTS_DIR" -maxdepth 1 -name "agent-*.jsonl" -type f 2>/dev/null | wc -l)
    echo "  └─ Found $SUBAGENT_FILES subagent transcript(s)"
else
    echo "  └─ (does not exist — this session spawned no subagents)"
fi

# Parse transcripts to extract usage keys and count rows
python3 - "$TRANSCRIPT_PATH" "$SUBAGENTS_DIR" <<'PY'
import json
import sys
import os

transcript_path = sys.argv[1]
subagents_dir = sys.argv[2]

usage_keys = set()
total_usage_rows = 0

def extract_usage_keys_from_file(filepath):
    global usage_keys, total_usage_rows
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    # Navigate to message.usage if it exists
                    if isinstance(row, dict) and 'message' in row:
                        msg = row['message']
                        if isinstance(msg, dict) and 'usage' in msg:
                            usage_obj = msg['usage']
                            if isinstance(usage_obj, dict):
                                usage_keys.update(usage_obj.keys())
                                total_usage_rows += 1
                except (json.JSONDecodeError, KeyError, TypeError):
                    # Skip malformed lines or rows without usage
                    pass
    except IOError as e:
        print(f"warning: could not read {filepath}: {e}", file=sys.stderr)

# Read main transcript
print("Main transcript: " + os.path.basename(transcript_path))
extract_usage_keys_from_file(transcript_path)
main_usage_rows = total_usage_rows

# Read subagent transcripts if they exist
if os.path.isdir(subagents_dir):
    subagent_files = sorted([f for f in os.listdir(subagents_dir)
                            if f.startswith('agent-') and f.endswith('.jsonl')])
    if subagent_files:
        for filename in subagent_files:
            filepath = os.path.join(subagents_dir, filename)
            print(f"Subagent transcript: {filename}")
            subagent_start = total_usage_rows
            extract_usage_keys_from_file(filepath)
            subagent_rows = total_usage_rows - subagent_start
            if subagent_rows > 0:
                print(f"  └─ {subagent_rows} row(s) with usage data")
            else:
                print(f"  └─ 0 rows with usage data")

# Report results
print()
print("Usage keys present (union across all transcripts):")
if usage_keys:
    for key in sorted(usage_keys):
        print(f"  - {key}")
    print()
    print(f"Total rows with usage data: {total_usage_rows}")
    print(f"  (Main: {main_usage_rows}, Subagent(s): {total_usage_rows - main_usage_rows})")
else:
    print("  (no usage data found)")
    print()
    print(f"Total rows with usage data: 0")

PY

# Rows versus messages, and what each reading of them costs.
python3 - "$TRANSCRIPT_PATH" "$HERE" "$REPORTED_COST" <<'PY'
import collections, importlib.util, json, os, sys

transcript, here, reported = sys.argv[1], sys.argv[2], sys.argv[3]
spec = importlib.util.spec_from_file_location("spend", os.path.join(here, "hooks", "lib", "spend.py"))
spend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spend)
costs = json.load(open(os.path.join(here, "hooks", "lib", "model-costs.json")))

BILLED_INPUT = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
                "cache_creation")
rows = msgs = multi = same_input = output_differs = keyless = 0
row_sum = 0.0
for path in spend.transcripts_for(transcript):
    groups = collections.defaultdict(list)
    for line in open(path, errors="replace"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        m = rec.get("message") if isinstance(rec, dict) else None
        if not (isinstance(m, dict) and isinstance(m.get("usage"), dict)):
            continue
        rows += 1
        u = m["usage"]
        row_sum += spend.line_cost(u, spend.price_for(costs, spend.normalise_model(m.get("model"))))
        key = spend.message_key(rec, m)
        if key is None:
            keyless += 1
            continue
        groups[key].append(u)
    msgs += len(groups)
    for us in groups.values():
        if len(us) < 2:
            continue
        multi += 1
        # The billed input side. output_tokens, output_tokens_details, iterations and
        # server_tool_use are expected to differ: they grow as the message streams.
        strip = lambda u: json.dumps({k: u.get(k) for k in BILLED_INPUT}, sort_keys=True)
        same_input += len({strip(u) for u in us}) == 1
        output_differs += len({u.get("output_tokens") for u in us}) > 1

print()
print("Rows with usage: %d · distinct messages (message.id / requestId): %d · rows with neither: %d"
      % (rows, msgs, keyless))
print("Messages spanning >1 row: %d · of which input+cache usage identical on every row: %d"
      " · output_tokens differs between rows: %d" % (multi, same_input, output_differs))

import subprocess
done = subprocess.run([sys.executable, os.path.join(here, "hooks", "lib", "spend.py"), transcript,
                       "2000-01-01T00:00:00Z", os.path.join(here, "hooks", "lib", "model-costs.json")],
                      capture_output=True, text=True)
per_message = int(done.stdout.strip()) / 1e6 if done.returncode == 0 else float("nan")
print("Every row summed:        $%.4f" % row_sum)
print("spend.py (per message):  $%.4f" % per_message)
if reported:
    r = float(reported)
    print("total_cost_usd reported: $%.4f   row sum is %.2fx it · spend.py is %.2fx it"
          % (r, row_sum / r if r else 0, per_message / r if r else 0))
PY
