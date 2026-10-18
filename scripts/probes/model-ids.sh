#!/bin/bash
# model-ids.sh — measure which model id Claude Code resolves each routing alias
# to, and whether the cost table prices it.
#
#   bash scripts/probes/model-ids.sh
#
# Costs about a cent and a minute: one near-empty session per alias.
#
# Why this needs measuring at all. The framework routes by alias — `model:
# haiku` in an agent, `implement: sonnet` in a policy — and never names an id.
# `hooks/lib/spend.py` prices ids. The alias is resolved by Claude Code, at
# session start, to whatever the current generation happens to be, and that
# resolution is invisible from inside the repo: nothing in the plugin changes
# when `haiku` starts meaning something else.
#
# It did. A real run on 2.1.296 resolved all three aliases to the 5-5
# generation, none of which the table held, so each was priced at the
# deliberately-expensive fallback — and the gate stayed green, because the gate
# only ever compared the table with itself.
#
# What it reads: the first line of a `--output-format stream-json` session is
# the init event, and it carries the resolved id. That is cheaper and more
# direct than inferring the id from a transcript after the fact.
#
# The aliases are not listed here. They come from `agents/*.md` and
# `templates/efficiency.md`, through the same reader the gate uses, so an alias
# added to the framework is measured without anyone editing this file.

set -uo pipefail

ROOT_REPO=$(cd "$(dirname "$0")/../.." && pwd) || exit 2
command -v claude   >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3  >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

VERSION=$(claude --version 2>/dev/null | head -1 | awk '{print $1}')
echo "claude: ${VERSION:-unknown}"

COSTS="$ROOT_REPO/hooks/lib/model-costs.json"
ALIASES=$(python3 "$ROOT_REPO/scripts/lib/check-priced-models.py" --aliases "$ROOT_REPO")
[ -n "$ALIASES" ] || { echo "no routed aliases found — the reader is broken, not the repo" >&2; exit 2; }

# A clean directory, so the session picks up no CLAUDE.md, no hooks and no
# plugin of this repo's. Those would change neither the answer nor the price
# list, but they would make the measurement cost several times as much.
WORK=$(mktemp -d) || exit 2
trap 'rm -rf "$WORK"' EXIT

echo "aliases routed to by this framework: $(echo "$ALIASES" | tr '\n' ' ')"
echo

printf '| alias | resolves to | priced |\n|---|---|---|\n'

MISSING=0
MAP=""
for alias in $ALIASES; do
    out="$WORK/$alias.json"
    ( cd "$WORK" && claude -p 'hi' --model "$alias" \
        --setting-sources project,local \
        --output-format stream-json --verbose --max-turns 1 ) > "$out" 2>"$out.err"

    id=$(python3 - "$out" <<'PY'
import json, sys
try:
    with open(sys.argv[1], errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line[0] != "{":
                continue
            ev = json.loads(line)
            if ev.get("type") == "system" and ev.get("subtype") == "init":
                print(ev.get("model") or "")
                break
except Exception:
    pass
PY
)
    if [ -z "$id" ]; then
        # Silence here would read as "resolved to nothing", which is a finding
        # about the probe wearing the costume of a finding about the platform.
        printf '| %s | — | **could not resolve** |\n' "$alias"
        printf '  claude said: %s\n' "$(head -2 "$out.err" | tr '\n' ' ' | cut -c1-160)"
        MISSING=$((MISSING + 1))
        continue
    fi

    # Backticks below are markdown, not command substitution.
    # shellcheck disable=SC2016
    if python3 -c 'import json,sys; sys.exit(0 if sys.argv[2] in json.load(open(sys.argv[1]))["models"] else 1)' "$COSTS" "$id"; then
        printf '| %s | `%s` | yes |\n' "$alias" "$id"
    else
        printf '| %s | `%s` | **NO — measured at the fallback rate** |\n' "$alias" "$id"
        MISSING=$((MISSING + 1))
    fi
    MAP="$MAP$alias=$id"$'\n'
done

echo
echo "To record this, put it in hooks/lib/model-costs.json under \"resolved\":"
# Passed as a file, not on stdin: the heredoc that carries the script is stdin.
printf '%s' "$MAP" > "$WORK/map"
python3 - "$WORK/map" "${VERSION:-unknown}" <<'PY'
import datetime, json, sys
with open(sys.argv[1]) as fh:
    pairs = dict(l.split("=", 1) for l in fh.read().splitlines() if "=" in l)
print(json.dumps({"measured": datetime.date.today().isoformat(),
                  "claude_code_version": sys.argv[2],
                  "aliases": pairs}, indent=2))
PY

echo
if [ "$MISSING" -gt 0 ]; then
    echo "verdict: UNPRICED ROUTING — $MISSING alias(es) above route to a model the"
    echo "         cost table does not hold. Every run that goes there is measured"
    echo "         at the fallback rate, which is a ceiling, not a cost."
    exit 1
fi
echo "verdict: PRICED — every alias this framework routes to resolves to an id"
echo "         the cost table prices."
