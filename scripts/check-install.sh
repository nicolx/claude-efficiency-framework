#!/bin/bash
# check-install.sh — does this project's install actually work?
#
#   bash scripts/check-install.sh [project-root]
#
# Read-only. Changes nothing, installs nothing, contacts no network, and runs no
# project command.
#
# It exists because the expensive failure mode of this framework is SILENCE. A
# project upgraded across 0.4.0 keeps its policy where 0.3.x put it, the plugin
# looks elsewhere, and everything stops: no charter, no policy, no guards, no
# error. Nothing tells you, and the sessions look entirely normal.
#
# So this validates the whole CHAIN, not the files. An earlier version checked
# that the project's own files looked right and reported CONFORMANT for a project
# where the plugin was not installed at all — a validator that says "all good"
# about nothing is worse than no validator.
#
#   0  conformant
#   1  not conformant — the report says what to do
#   2  cannot tell (not a directory, or python3 missing)

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
PLUGIN=$(cd "$HERE/.." && pwd)
ROOT="${1:-$(pwd)}"
[ -d "$ROOT" ] || { echo "not a directory: $ROOT" >&2; exit 2; }
ROOT=$(cd "$ROOT" && pwd)

PROBLEMS=0
NOTES=0

section() { printf '\n%s\n' "$1"; }
ok()      { printf '  ok    %s\n' "$1"; }
bad()     { printf '  FAIL  %s\n' "$1"; PROBLEMS=$((PROBLEMS + 1)); }
note()    { printf '  note  %s\n' "$1"; NOTES=$((NOTES + 1)); }
hint()    { printf '        %s\n' "$1"; }

printf '\nefficiency install check\n  project: %s\n  plugin:  %s\n' "$ROOT" "$PLUGIN"

# Settled first: a project that never adopted the framework is not a broken
# install, and every judgement below depends on knowing which of the two it is.
POLICY="$ROOT/.efficiency/policy.md"
LEGACY="$ROOT/.claude/efficiency.md"
if [ -f "$POLICY" ]; then
    ADOPTED=1
elif [ -f "$LEGACY" ]; then
    ADOPTED=stale
else
    ADOPTED=0
fi

# ── 1. prerequisites ─────────────────────────────────────────────────────────
section "Prerequisites"
if ! command -v python3 >/dev/null 2>&1; then
    bad "python3 is not on PATH — every hook in this plugin is a python3 script"
    hint "Nothing below can be checked without it."
    printf '\nCANNOT TELL\n\n'
    exit 2
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
PYOK=$(python3 -c 'import sys; print(1 if sys.version_info[:2] >= (3, 7) else 0)')
if [ "$PYOK" = "1" ]; then
    ok "python3 $PYV (3.7 or newer, as the hooks require)"
else
    bad "python3 $PYV is older than the 3.7 the hooks require"
fi

# ── 2. is the plugin reachable from this project at all? ────────────────────
# The check that was missing, and the one that makes every other check mean
# something: a perfect .efficiency/ in a project where nothing is enabled is a
# project where nothing happens.
section "Is the plugin enabled here?"
export ROOT
ENABLED=$(python3 "$PLUGIN/scripts/lib/check_enabled.py" 2>&1)
case "$ENABLED" in
    enabled:*)   ok "${ENABLED#enabled:}" ;;
    disabled:*)  if [ "$ADOPTED" = "0" ]; then
                     note "${ENABLED#disabled:}"
                 else
                     bad "${ENABLED#disabled:}"
                     hint "claude plugin install efficiency@claude-efficiency-framework --scope project"
                     hint "then restart Claude Code — hooks load at session start."
                 fi ;;
    *)           note "could not determine whether the plugin is enabled: $ENABLED" ;;
esac

# ── 3. the project's own files ──────────────────────────────────────────────
section "Project files"
if [ "$ADOPTED" = "1" ]; then
    ok "policy at .efficiency/policy.md"
elif [ "$ADOPTED" = "stale" ]; then
    bad "policy is still at .claude/efficiency.md — this install predates 0.4.0"
    hint "The framework is INERT: nothing fires and nothing warns you but this."
    hint "Fix: run /efficiency:init, which migrates it."
else
    printf '  This project has not adopted the framework.\n'
    printf '  Run /efficiency:init to set it up.\n\n'
    [ "$PROBLEMS" -gt 0 ] && exit 1
    exit 0
fi

if [ "$ADOPTED" = "1" ]; then
    SHAPE=$(POLICY="$POLICY" python3 "$PLUGIN/scripts/lib/check_policy.py" 2>&1)
    while IFS='|' read -r level msg extra; do
        [ -z "$level" ] && continue
        case "$level" in
            ok)   ok "$msg" ;;
            bad)  bad "$msg"; [ -n "$extra" ] && hint "$extra" ;;
            note) note "$msg" ;;
        esac
    done <<< "$SHAPE"
fi

# ── 4. the gate, which is what makes autonomy safe rather than reckless ─────
section "The gate"
GATE=$(sed -n '/^---$/,/^---$/{s/^gate:[[:space:]]*//p;}' "$POLICY" 2>/dev/null | head -1 | tr -d '"'"'"'\047')
if [ -z "$GATE" ]; then
    bad "no gate declared — /efficiency:run refuses to start without one"
    hint "Declare the command you would run before committing."
else
    ok "declared: $GATE"
    # Resolvable, not executed: running a project's test suite from a validator
    # would be slow and has side effects. What breaks in practice is a gate
    # pointing at a script that was renamed or deleted, and that is cheap to see.
    GATE_CMD=$(printf '%s' "$GATE" | awk '{print $1}')
    case "$GATE_CMD" in
        bash|sh|zsh|make|npm|npx|composer|php|python|python3|node|cargo|go|just)
            GATE_ARG=$(printf '%s' "$GATE" | awk '{print $2}')
            if command -v "$GATE_CMD" >/dev/null 2>&1; then
                ok "runner \`$GATE_CMD\` is on PATH"
            else
                bad "runner \`$GATE_CMD\` is not on PATH — the gate cannot run"
            fi
            case "$GATE_ARG" in
                ""|-*) : ;;
                */*|*.sh|*.py|*.js)
                    if [ -e "$ROOT/$GATE_ARG" ]; then
                        ok "gate target \`$GATE_ARG\` exists"
                    else
                        bad "gate target \`$GATE_ARG\` does not exist — the gate would fail on every turn"
                    fi ;;
            esac ;;
        *)
            if command -v "$GATE_CMD" >/dev/null 2>&1 || [ -e "$ROOT/$GATE_CMD" ]; then
                ok "\`$GATE_CMD\` resolves"
            else
                bad "\`$GATE_CMD\` is neither on PATH nor a file in the project"
            fi ;;
    esac
fi

# ── 5. do the hooks actually produce anything? ──────────────────────────────
# The difference between "the files look right" and "it works".
section "Hooks, actually run"
SS_OUT=$(printf '{"cwd":"%s","hook_event_name":"SessionStart"}' "$ROOT" \
         | CLAUDE_PROJECT_DIR="$ROOT" python3 "$PLUGIN/hooks/session-start.py" 2>&1)
if printf '%s' "$SS_OUT" | grep -q "autonomy charter"; then
    SS_LEN=$(printf '%s' "$SS_OUT" | wc -c | tr -d ' ')
    ok "SessionStart injects the charter and policy (~$((SS_LEN / 4)) tokens)"
elif printf '%s' "$SS_OUT" | grep -q "INERT after an upgrade"; then
    bad "SessionStart reports this install as inert — see the policy location above"
else
    bad "SessionStart produced nothing usable"
    hint "A session here would get no charter, no policy and no guards."
fi

ST_OUT=$(printf '{"cwd":"%s","hook_event_name":"Stop","transcript_path":"/nonexistent","stop_hook_active":false}' "$ROOT" \
         | CLAUDE_PROJECT_DIR="$ROOT" python3 "$PLUGIN/hooks/autopilot-stop.py" 2>&1)
ST_CODE=$?
if [ "$ST_CODE" -eq 0 ]; then
    ok "Stop hook runs and exits 0 when it should stand aside"
else
    bad "Stop hook exited $ST_CODE with no run in flight — it must never be fatal for its own defects"
    hint "$(printf '%s' "$ST_OUT" | head -c 120)"
fi

PR_OUT=$(printf '{"cwd":"%s","hook_event_name":"UserPromptSubmit"}' "$ROOT" \
         | CLAUDE_PROJECT_DIR="$ROOT" python3 "$PLUGIN/hooks/prompt-reminder.py" 2>&1)
if printf '%s' "$PR_OUT" | grep -q "efficiency" || [ -z "$PR_OUT" ]; then
    ok "UserPromptSubmit reminder behaves"
else
    note "UserPromptSubmit produced unexpected output: $(printf '%s' "$PR_OUT" | head -c 60)"
fi

# ── 6. hygiene ──────────────────────────────────────────────────────────────
section "Repository hygiene"
if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    for f in .efficiency/run.md .efficiency/autopilot.json .efficiency/tools.md; do
        if git -C "$ROOT" check-ignore -q "$f" 2>/dev/null; then
            ok "$f is gitignored"
        else
            bad "$f is not gitignored — run state or a machine inventory would be committed"
        fi
    done
    if [ -f "$ROOT/.efficiency/statusline.py" ] \
       && ! git -C "$ROOT" check-ignore -q .efficiency/statusline.py 2>/dev/null; then
        note ".efficiency/statusline.py is not gitignored — it is a copy of plugin code, refreshed by the hook"
    fi
    for f in .efficiency/policy.md .efficiency/backlog.md; do
        if [ ! -e "$ROOT/$f" ]; then
            note "$f does not exist yet"
        elif git -C "$ROOT" ls-files --error-unmatch "$f" >/dev/null 2>&1; then
            ok "$f is tracked, so it travels with the repo"
        else
            note "$f is not committed — it is meant to be shared"
        fi
    done
else
    note "not a git repository, so ignore rules were not checked"
fi

# ── 7. tools and state ──────────────────────────────────────────────────────
section "Inventory and state"
if [ -f "$ROOT/.efficiency/tools.md" ]; then
    N=$(grep -c '^- `' "$ROOT/.efficiency/tools.md" 2>/dev/null || echo 0)
    ok "tool inventory present ($N entries)"
else
    note "no tool inventory — run scripts/detect-tools.sh so sessions use what is installed"
fi

RUN="$ROOT/.efficiency/run.md"
if [ -f "$RUN" ]; then
    STATUS=$(sed -n 's/^status:[[:space:]]*//p' "$RUN" | head -1)
    case "$STATUS" in
        ACTIVE)  note "a run is ACTIVE — turns will keep going until it finishes or a guard stops it" ;;
        BLOCKED) note "a run is BLOCKED: $(sed -n 's/^blocked_reason:[[:space:]]*//p' "$RUN" | head -1 | cut -c1-64)" ;;
        DONE)    ok "last run finished" ;;
        *)       note "run file has an unrecognised status: ${STATUS:-(none)}" ;;
    esac
else
    ok "no run in flight"
fi

# The status line is optional, so neither state is a problem — but a half-wired
# one is. A settings file that names the script while the script is absent paints
# a blank line under the prompt, and a blank line is exactly how this framework
# fails worst: silently, looking fine.
SL_DECL=$(python3 - "$ROOT" <<'PYEOF' 2>/dev/null
import json, os, sys
root = sys.argv[1]
for name in ("settings.json", "settings.local.json"):
    try:
        with open(os.path.join(root, ".claude", name)) as fh:
            sl = json.load(fh).get("statusLine") or {}
        if sl:
            print(sl.get("command", "yes"))
            break
    except Exception:
        continue
PYEOF
)
SL_SCRIPT="$ROOT/.efficiency/statusline.py"
if [ -n "$SL_DECL" ] && [ -f "$SL_SCRIPT" ]; then
    LINES=$(echo '{}' | CLAUDE_PROJECT_DIR="$ROOT" NO_COLOR=1 python3 "$SL_SCRIPT" 2>/dev/null | wc -l | tr -d ' ')
    ok "status line wired and printing $LINES line(s)"
elif [ -n "$SL_DECL" ] && [ ! -f "$SL_SCRIPT" ]; then
    case "$SL_DECL" in
        *statusline.py*)
            bad "settings declare a status line, but .efficiency/statusline.py is missing"
            hint "it is written by the SessionStart hook — start one session, or the line stays blank" ;;
        *) ok "the project has a status line of its own" ;;
    esac
else
    note "no status line — the backlog is announced once per session and then scrolls away"
    hint "offer it: python3 \"\$CLAUDE_PROJECT_DIR/.efficiency/statusline.py\" in .claude/settings.json"
fi

# ── verdict ─────────────────────────────────────────────────────────────────
printf '\n'
if [ "$PROBLEMS" -gt 0 ]; then
    printf 'NOT CONFORMANT — %d problem(s), %d note(s)\n\n' "$PROBLEMS" "$NOTES"
    exit 1
fi
printf 'CONFORMANT — %d note(s)\n\n' "$NOTES"
