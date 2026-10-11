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


def check_card(label, p):
    for k in ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h"):
        if not isinstance(p.get(k), (int, float)):
            sys.exit("%s: %s is missing or not a number" % (label, k))
    # These ratios are the documented billing rule, not a preference. A table
    # that drifts from them measures spend wrong in silence.
    if abs(p["cache_write_5m"] - p["input"] * 1.25) > 1e-9:
        sys.exit("%s: 5m cache write is not 1.25x input" % label)
    if abs(p["cache_write_1h"] - p["input"] * 2.0) > 1e-9:
        sys.exit("%s: 1h cache write is not 2x input" % label)


for name, p in d["models"].items():
    check_card(name, p)
    # A model may carry a second rate card for long prompts. It is a full card,
    # charged on every line, so it gets the same scrutiny as the first — an
    # unchecked tier is a price nobody reads until it is in a ceiling.
    tier = p.get("long_prompt")
    if tier is not None:
        if not isinstance(tier.get("over_tokens"), (int, float)):
            sys.exit("%s: long_prompt has no over_tokens threshold" % name)
        check_card("%s (long prompt)" % name, tier)
        if tier["input"] <= p["input"]:
            sys.exit("%s: the long-prompt card is not dearer than the short one, "
                     "so it would never be worth selecting" % name)
if not d.get("verified"):
    sys.exit("the table has no verified date")
PY
    then ok "prices consistent, default present, verified date recorded"
    else bad "cost table is inconsistent"
    fi

    # A price table nobody re-checked is a ceiling that lies in whichever
    # direction the price moved. Stale is a skip, not a failure: the table is
    # not wrong, just unconfirmed. A date that cannot be parsed at all is a
    # real defect, so that stays a bad(), never folded into the same skip.
    AGE_OUT=$(python3 - <<'PY' 2>&1
import json
from datetime import date

try:
    d = json.load(open("hooks/lib/model-costs.json"))
    y, m, dd = (int(x) for x in d.get("verified", "").split("-"))
    print((date.today() - date(y, m, dd)).days)
except Exception as e:
    print("%s: %s" % (type(e).__name__, e))
    raise SystemExit(1)
PY
    )
    AGE_STATUS=$?
    if [ "$AGE_STATUS" -ne 0 ]; then
        bad "hooks/lib/model-costs.json verified date unreadable: $AGE_OUT"
    elif [ "$AGE_OUT" -lt 0 ]; then
        bad "hooks/lib/model-costs.json verified date is in the future ($AGE_OUT days)"
    elif [ "$AGE_OUT" -gt 90 ]; then
        skip "hooks/lib/model-costs.json prices" "verified $AGE_OUT days ago, older than 90 — re-check against the claude-api skill"
    else
        ok "hooks/lib/model-costs.json verified $AGE_OUT day(s) ago"
    fi
else
    skip "cost table" "python3 not found"
fi

# ── 2b. the table prices the models this framework actually routes to ────────
# Section 2 checks the table against itself, which is how it stayed green while
# every model of a real run fell through to the expensive fallback. The
# framework routes by alias; the meter prices by id; Claude Code decides what an
# alias means, and it moved a generation without anything here changing. The
# alias-to-id mapping is measured by scripts/probes/model-ids.sh and recorded in
# the table; this check is the free half that holds the two ends together — and
# compares the Claude Code that measured the mapping with the one installed,
# because what falsifies a mapping is a release, not the passage of time.
section "routed models"
if command -v python3 >/dev/null 2>&1; then
    if out=$(python3 scripts/lib/check-priced-models.py --selftest 2>&1); then
        ok "$out"
    else
        bad "the routed-model check cannot reach the verdicts it claims"
        printf '%s\n' "$out" | sed 's/^/        /'
    fi

    out=$(python3 scripts/lib/check-priced-models.py "$ROOT" 2>&1)
    case "$?" in
        0) ok "$(printf '%s' "$out" | head -1)" ;;
        3) skip "alias resolution" "$(printf '%s' "$out" | head -1)" ;;
        *) bad "an alias this framework routes to has no priced model behind it"
           printf '%s\n' "$out" | sed 's/^/        /' ;;
    esac
else
    skip "routed models" "python3 not found"
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
# Two checks, because the frontmatter has to be both present and useful. A
# skill's description is the whole input to the model's decision to invoke it,
# so one that never names its trigger phrases fails in the way nobody notices:
# it simply never fires.
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

if command -v python3 >/dev/null 2>&1; then
    # The checker first proves it still refuses what it claims to refuse. A
    # trigger check nobody has watched reject a vague description is worth
    # exactly as much as no check at all.
    if out=$(python3 scripts/lib/check-skill-triggers.py --selftest 2>&1); then
        ok "$out"
    else
        bad "the trigger checker cannot reject a description it should"
        printf '%s\n' "$out" | sed 's/^/        /'
    fi
    if out=$(python3 scripts/lib/check-skill-triggers.py "$ROOT" 2>&1); then
        ok "$out"
    else
        bad "a skill description cannot be auto-invoked"
        printf '%s\n' "$out" | sed 's/^/        /'
    fi
else
    skip "skill trigger phrases" "python3 not found"
fi

# ── 4b. every measured claim says when it was measured ───────────────────────
# Section 7 was wrong for a month because nobody could see it had expired: eight
# of the thirteen entries carried no date at all. Undated is a failure — a claim
# with no provenance cannot be re-derived. Merely old is a skip, like the price
# table: the claim is not wrong, it is unconfirmed, and a gate that goes red on
# the calendar is a gate people learn to ignore.
section "measurement provenance"
if command -v python3 >/dev/null 2>&1; then
    if out=$(python3 scripts/lib/check-measurement-age.py --selftest 2>&1); then
        ok "$out"
    else
        bad "the staleness guard cannot reach the verdicts it claims"
        printf '%s\n' "$out" | sed 's/^/        /'
    fi

    out=$(python3 scripts/lib/check-measurement-age.py "$ROOT" 2>&1)
    case "$?" in
        0) ok "$(printf '%s' "$out" | head -1)" ;;
        3) skip "re-measurement" "$(printf '%s' "$out" | head -1)"
           printf '%s\n' "$out" | tail -n +2 | sed 's/^/        /' ;;
        *) bad "a documented claim has no date"
           printf '%s\n' "$out" | sed 's/^/        /' ;;
    esac
else
    skip "measurement provenance" "python3 not found"
fi

# ── 4c. the probes' own command-line flags still exist ───────────────────────
# `--max-turns` left `claude --help` on 2.1.296 while staying accepted, and the
# probes bound themselves with it. A flag that quietly stops being honoured does
# not error: the probe keeps reporting a number, and the number measures
# something else. Costs nothing and calls no API.
section "probe flags"
if command -v claude >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
    if out=$(python3 scripts/lib/check-probe-flags.py --selftest 2>&1); then
        ok "$out"
    else
        bad "the flag guard cannot tell a live flag from a dead one"
        printf '%s\n' "$out" | sed 's/^/        /'
    fi
    if out=$(python3 scripts/lib/check-probe-flags.py "$ROOT" 2>&1); then
        ok "$out"
    else
        bad "a probe depends on a flag this claude no longer accepts"
        printf '%s\n' "$out" | sed 's/^/        /'
    fi
else
    skip "probe flags" "claude or python3 not on PATH, so the probes cannot be checked here"
fi

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
    V_REF=$(python3 -c 'import json
s = json.load(open(".claude-plugin/marketplace.json"))["plugins"][0]["source"]
print(s.get("ref", "") if isinstance(s, dict) else "")')
    if [ -z "$V_REF" ]; then
        skip "marketplace ref" "the catalogue pins no ref, so consumers track the default branch"
    elif [ "$V_REF" != "v$V_FILE" ]; then
        bad "marketplace.json pins $V_REF but VERSION says $V_FILE — consumers would get the wrong release"
    else
        ok "marketplace.json pins $V_REF, matching VERSION"
    fi
    # The catalogue carries the version twice — once as the ref consumers pin,
    # once as a field beside the description. Only the ref was checked, and the
    # field sat at 0.13.0 through four releases: a duplicated fact going wrong
    # in exactly the copy nobody was reading.
    V_CAT=$(python3 -c 'import json
print(json.load(open(".claude-plugin/marketplace.json"))["plugins"][0].get("version", ""))')
    if [ -z "$V_CAT" ]; then
        skip "marketplace version field" "the catalogue entry declares none"
    elif [ "$V_CAT" != "$V_FILE" ]; then
        bad "marketplace.json's plugin entry says $V_CAT but VERSION says $V_FILE"
    else
        ok "marketplace.json's plugin entry agrees on $V_FILE"
    fi
    if grep -q "^## \[$V_FILE\]" CHANGELOG.md 2>/dev/null; then
        ok "CHANGELOG.md has an entry for $V_FILE"
    elif grep -q '^## \[Unreleased\]' CHANGELOG.md 2>/dev/null; then
        skip "changelog entry for $V_FILE" "only [Unreleased] is present"
    else
        bad "CHANGELOG.md has no entry for $V_FILE and no [Unreleased] section"
    fi
fi

# ── 6b. the tag the catalogue pins actually exists ───────────────────────────
# Everything above compares five copies of the version to each other, all of them
# in this working tree. They can agree perfectly while the release does not
# exist, and for six versions they did: 0.14.0 through 0.18.1 were committed,
# announced in the changelog, and never tagged or pushed, with this gate green
# throughout. Consumers resolve a ref, so a release nobody cut is a release
# nobody has. This is the only check here that asks git instead of JSON.
#
# The remote half needs the network, so it is left to scripts/release.sh. The
# gate stays runnable offline.
section "release tags"
if command -v python3 >/dev/null 2>&1 && command -v git >/dev/null 2>&1; then
    if out=$(python3 scripts/lib/check-release-tag.py --selftest 2>&1); then
        ok "$out"
    else
        bad "the tag guard cannot tell a cut release from an uncut one"
        printf '%s\n' "$out" | sed 's/^/        /'
    fi

    out=$(python3 scripts/lib/check-release-tag.py "$ROOT" 2>&1)
    case "$?" in
        0) ok "$(printf '%s' "$out" | head -1)" ;;
        3) skip "release tag" "$(printf '%s' "$out" | head -1)"
           printf '%s\n' "$out" | tail -n +2 | sed 's/^/        /' ;;
        *) bad "the catalogue pins a tag that does not exist"
           printf '%s\n' "$out" | sed 's/^/        /' ;;
    esac
else
    skip "release tags" "git or python3 not found"
fi

# ── 7. this repo's own install of its own framework ─────────────────────────
# Dogfooding, and it has already earned its place: the check exists because an
# upgrade across 0.4.0 leaves a project silently inert, and this repo is a
# project like any other.
section "the validator itself"
if out=$(bash scripts/test-check-install.sh 2>&1); then
    ok "$(printf '%s' "$out" | grep -E '^[0-9]+ checks' | head -1)"
else
    bad "the install validator cannot report a problem it should"
    printf '%s\n' "$out" | grep -E '^\s+FAIL' | sed 's/^/        /'
fi

section "own install"
if out=$(bash scripts/check-install.sh "$ROOT" 2>&1); then
    ok "$(printf '%s' "$out" | grep -E '^(CONFORMANT|NOT CONFORMANT)' | head -1)"
else
    bad "this repo's own install is not conformant"
    printf '%s\n' "$out" | sed 's/^/        /'
fi

# ── 8. markdown lint, if available ───────────────────────────────────────────
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
