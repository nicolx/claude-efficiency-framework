#!/bin/bash
# transcript-shape.sh — inspect the shape of a session transcript and its subagents.
#
# The claims in docs/verified-platform-behaviour.md § 6 (Subagent turns are in
# separate transcripts) rest on this probe. Use it to verify the directory structure
# and the usage keys present in a real session.
#
#   bash scripts/probes/transcript-shape.sh <path-to-session-transcript.jsonl>
#
# Prints the subagents directory (or reports none exists) and the set of usage keys
# found in the transcript and any subagent transcripts, plus the count of rows bearing
# usage data. Never prints conversation content, token values, or model ids.
#
# Why this matters: a measurement that reads only transcript_path misses subagent
# spend entirely. A spending ceiling blind to them is a ceiling on the cheap work only.

set -uo pipefail

TRANSCRIPT_PATH="${1:-}"

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

# Create a temp dir for our scratch work (following stop-cap.sh pattern)
TMPDIR=$(mktemp -d) || exit 2
trap 'rm -rf "$TMPDIR"' EXIT

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
