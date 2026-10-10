#!/bin/bash
# check-install.sh — is this project's install actually working?
#
#   bash scripts/check-install.sh [project-root]
#
# Read-only. Changes nothing, installs nothing, and never contacts the network.
#
# It exists because the expensive failure mode of this framework is SILENCE. A
# project upgraded across 0.4.0 keeps its policy where 0.3.x put it, the plugin
# looks somewhere else, and everything simply stops: no charter, no policy, no
# guards, no error. Nothing tells you, and the sessions look normal.
#
# Exit codes, the same contract the scripts here share:
#   0  conformant
#   1  not conformant — the report says what to do
#   2  cannot tell (not a directory, no python3)

set -uo pipefail

ROOT="${1:-$(pwd)}"
[ -d "$ROOT" ] || { echo "not a directory: $ROOT" >&2; exit 2; }
ROOT=$(cd "$ROOT" && pwd)

PROBLEMS=0
NOTES=0

ok()   { printf '  ok    %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; PROBLEMS=$((PROBLEMS + 1)); }
note() { printf '  note  %s\n' "$1"; NOTES=$((NOTES + 1)); }

printf '\nefficiency install check — %s\n\n' "$ROOT"

# ── 1. adopted at all? ───────────────────────────────────────────────────────
POLICY="$ROOT/.efficiency/policy.md"
LEGACY_POLICY="$ROOT/.claude/efficiency.md"

if [ -f "$POLICY" ]; then
    ok "policy present at .efficiency/policy.md"
elif [ -f "$LEGACY_POLICY" ]; then
    bad "policy is still at .claude/efficiency.md — this install predates 0.4.0"
    printf '        The framework is INERT: nothing fires and nothing warns you except this.\n'
    printf '        Fix: move it to .efficiency/policy.md, or run /efficiency:init.\n'
else
    printf '  This project has not adopted the framework. Run /efficiency:init to set it up.\n\n'
    exit 0
fi

# ── 2. the gate, which is what makes autonomy safe rather than reckless ──────
# Read with sed rather than a parser: it is one `key: value` line in the
# frontmatter, and this script should work on a machine where python3 is the
# thing that is missing.
GATE=$(sed -n '/^---$/,/^---$/{s/^gate:[[:space:]]*//p;}' "$POLICY" | head -1 | tr -d '"'"'"'\047')

if [ -n "$GATE" ]; then
    ok "gate declared: $GATE"
else
    bad "no gate declared in the policy — /efficiency:run will refuse to start"
    printf '        Autonomy without an executable oracle is drift. Declare the command\n'
    printf '        you would run before committing.\n'
fi

if ! command -v python3 >/dev/null 2>&1; then
    bad "python3 is not on PATH — every hook in this plugin needs it"
fi

# ── 3. state that should not be committed ────────────────────────────────────
if [ -d "$ROOT/.git" ] || git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    for f in .efficiency/run.md .efficiency/autopilot.json .efficiency/tools.md; do
        if git -C "$ROOT" check-ignore -q "$f" 2>/dev/null; then
            ok "$f is gitignored"
        else
            bad "$f is not gitignored — run state and a machine inventory would be committed"
        fi
    done
    if git -C "$ROOT" ls-files --error-unmatch .efficiency/policy.md >/dev/null 2>&1; then
        ok ".efficiency/policy.md is tracked, so it travels with the repo"
    else
        note ".efficiency/policy.md is not committed — the policy is meant to be shared"
    fi
else
    note "not a git repository, so ignore rules were not checked"
fi

# ── 4. the inventory, which is what stops the model rebuilding tools ─────────
if [ -f "$ROOT/.efficiency/tools.md" ]; then
    ok "tool inventory present"
else
    note "no tool inventory — run scripts/detect-tools.sh so sessions use what is installed"
fi

# ── 5. a run left mid-flight ────────────────────────────────────────────────
RUN="$ROOT/.efficiency/run.md"
if [ -f "$RUN" ]; then
    STATUS=$(sed -n 's/^status:[[:space:]]*//p' "$RUN" | head -1)
    case "$STATUS" in
        ACTIVE)  note "a run is ACTIVE — the autopilot will keep turns going until it finishes" ;;
        BLOCKED) note "a run is BLOCKED and waiting on a human: $(sed -n 's/^blocked_reason:[[:space:]]*//p' "$RUN" | head -1 | cut -c1-70)" ;;
        *)       ok "no run in flight" ;;
    esac
fi

# ── verdict ─────────────────────────────────────────────────────────────────
printf '\n'
if [ "$PROBLEMS" -gt 0 ]; then
    printf 'NOT CONFORMANT — %d problem(s), %d note(s)\n\n' "$PROBLEMS" "$NOTES"
    exit 1
fi
printf 'CONFORMANT — %d note(s)\n\n' "$NOTES"
