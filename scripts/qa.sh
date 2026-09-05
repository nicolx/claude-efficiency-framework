#!/bin/bash
# qa.sh — this repo's own gate. Green before every commit.
#
# It reports what it could NOT run rather than passing silently: a check that is
# absent looks identical to a check that passed, and that is how a gate quietly
# stops being one. Missing optional tooling exits 2 ("passed what could run"),
# never 0.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
ROOT=$(pwd)

FAILED=0
SKIPPED=0

section() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok()      { printf '  ok    %s\n' "$1"; }
bad()     { printf '  FAIL  %s\n' "$1"; FAILED=$((FAILED + 1)); }
skip()    { printf '  skip  %s (%s)\n' "$1" "$2"; SKIPPED=$((SKIPPED + 1)); }

# ── 1. every shipped JSON parses ─────────────────────────────────────────────
section "JSON"
if command -v python3 >/dev/null 2>&1; then
    while IFS= read -r f; do
        if python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$f" 2>/dev/null; then
            ok "$f"
        else
            bad "$f does not parse"
        fi
    done < <(find . -name '*.json' -not -path './.git/*' | sort)
else
    skip "JSON parsing" "python3 not found"
fi

# ── 2. the cost table says what it claims ────────────────────────────────────
section "cost table"
if command -v python3 >/dev/null 2>&1; then
    if python3 - <<'PY'
import json, sys
d = json.load(open("hooks/lib/model-costs.json"))
if d.get("default") not in d.get("models", {}):
    sys.exit("default model is not in the table")
for name, p in d["models"].items():
    for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"):
        if not isinstance(p.get(k), (int, float)):
            sys.exit("%s: %s is missing or not a number" % (name, k))
    # These ratios are the documented billing rule, not a preference. A table
    # that drifts from them measures spend wrong in silence.
    if abs(p["cache_write_5m"] - p["input"] * 1.25) > 1e-9:
        sys.exit("%s: 5m cache write is not 1.25x input" % name)
    if abs(p["cache_write_1h"] - p["input"] * 2.0) > 1e-9:
        sys.exit("%s: 1h cache write is not 2x input" % name)
if not d.get("verified"):
    sys.exit("the table has no verified date")
PY
    then ok "prices consistent, default present, verified date recorded"
    else bad "cost table is inconsistent"
    fi
else
    skip "cost table" "python3 not found"
fi

# ── 3. python compiles, and the hook's selftest is green ─────────────────────
section "python"
if command -v python3 >/dev/null 2>&1; then
    while IFS= read -r f; do
        if python3 -c 'import ast,sys; ast.parse(open(sys.argv[1]).read())' "$f" 2>/dev/null; then
            ok "$f"
        else
            bad "$f does not compile"
        fi
    done < <(find . -name '*.py' -not -path './.git/*' | sort)

    if out=$(python3 hooks/autopilot-stop.py --selftest 2>&1); then
        ok "autopilot selftest: $(printf '%s' "$out" | tail -1)"
    else
        bad "autopilot selftest"
        printf '%s\n' "$out" | sed 's/^/        /'
    fi
else
    skip "python checks" "python3 not found"
fi

# ── 4. every agent and skill has usable frontmatter ──────────────────────────
section "frontmatter"
for f in agents/*.md skills/*/SKILL.md; do
    [ -e "$f" ] || continue
    if ! head -1 "$f" | grep -q '^---$'; then
        bad "$f has no frontmatter"
        continue
    fi
    missing=""
    for key in name description; do
        grep -q "^$key:" "$f" || missing="$missing $key"
    done
    # An agent with no pinned model defeats the point of the framework.
    case "$f" in
        agents/*) grep -q '^model:' "$f" || missing="$missing model" ;;
    esac
    if [ -n "$missing" ]; then
        bad "$f is missing:$missing"
    else
        ok "$f"
    fi
done

# ── 5. paths written in prose are real ───────────────────────────────────────
# A path in a document is a live reference: a consumer resolves it. When a file
# moves, this is what catches the stragglers.
section "load-bearing paths"
if command -v python3 >/dev/null 2>&1; then
    if out=$(python3 scripts/lib/check-paths.py "$ROOT" 2>&1); then
        ok "$out"
    else
        bad "$out"
    fi
else
    skip "load-bearing paths" "python3 not found"
fi

# ── 6. VERSION, the manifest and the changelog agree ────────────────────────
# A consumer pins this plugin by ref, so a shipped change they cannot see in the
# changelog is a change to their sessions made behind their back.
section "version"
V_FILE=$(tr -d ' \n\r' < VERSION 2>/dev/null)
if [ -z "$V_FILE" ]; then
    bad "VERSION is empty or missing"
elif ! command -v python3 >/dev/null 2>&1; then
    skip "version consistency" "python3 not found"
else
    V_MANIFEST=$(python3 -c 'import json;print(json.load(open(".claude-plugin/plugin.json")).get("version",""))')
    if [ "$V_FILE" != "$V_MANIFEST" ]; then
        bad "VERSION ($V_FILE) and plugin.json ($V_MANIFEST) disagree"
    else
        ok "VERSION and plugin.json agree on $V_FILE"
    fi
    if grep -q "^## \[$V_FILE\]" CHANGELOG.md 2>/dev/null; then
        ok "CHANGELOG.md has an entry for $V_FILE"
    elif grep -q '^## \[Unreleased\]' CHANGELOG.md 2>/dev/null; then
        skip "changelog entry for $V_FILE" "only [Unreleased] is present"
    else
        bad "CHANGELOG.md has no entry for $V_FILE and no [Unreleased] section"
    fi
fi

# ── 7. markdown lint, if available ───────────────────────────────────────────
section "markdown"
if command -v npx >/dev/null 2>&1 && [ -f .markdownlint.json ]; then
    # Capture, then test the real exit status. Piping into `tail` would make the
    # `if` test tail's status instead: the gate would report ok on every run and
    # nobody would notice, which is the same thing as having no gate at all.
    if out=$(npx --yes markdownlint-cli@0.42.0 '**/*.md' --ignore node_modules 2>&1); then
        ok "markdownlint"
    else
        bad "markdownlint"
        printf '%s\n' "$out" | head -25 | sed 's/^/        /'
    fi
else
    skip "markdownlint" "npx or .markdownlint.json missing"
fi

# ── verdict ──────────────────────────────────────────────────────────────────
printf '\n'
if [ "$FAILED" -gt 0 ]; then
    printf '\033[1mFAILED\033[0m — %d check(s) failed, %d skipped\n' "$FAILED" "$SKIPPED"
    exit 1
fi
if [ "$SKIPPED" -gt 0 ]; then
    printf '\033[1mPASSED WHAT COULD RUN\033[0m — %d check(s) skipped, so this is not a green gate\n' "$SKIPPED"
    exit 2
fi
printf '\033[1mPASSED\033[0m — everything ran\n'
