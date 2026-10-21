#!/bin/bash
# dialogue-language.sh — can a hook know the OS language, and does telling the model hold?
#
# The dialogue should be in the developer's language, not in English. Two things
# have to be measured before a hook is built on them:
#
#   env     which locale signals reach a hook's environment — LANG and friends,
#           and macOS's AppleLanguages through `defaults` — both with the
#           launching shell's LANG and with LANG removed, the way an app started
#           from the Dock or Finder may run.
#   drift   whether an injected language line survives English work. A headless
#           Haiku session is given an English task in an English prompt, twice
#           (the second turn via --continue), in three cells: no line, the line
#           at SessionStart only, the line at SessionStart and on every prompt.
#           The report after each turn is classified Italian or English by
#           counting stopwords — crude, but the two languages share few.
#
#   bash scripts/probes/dialogue-language.sh env
#   bash scripts/probes/dialogue-language.sh drift [language-name]
#
# Costs a few cents of Haiku for `drift`, nothing for `env` beyond one short
# session per cell. Writes nothing outside its own temporary directories, except
# the transcripts Claude Code keeps for any session, which it removes.

set -uo pipefail

MODE="${1:-env}"
LANGUAGE="${2:-Italian}"
command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

DIRS=()
fresh() {
    local d
    d=$(mktemp -d) || exit 2
    d=$(cd "$d" && pwd -P)
    DIRS+=("$d")
    printf '%s' "$d"
}
cleanup() {
    for d in "${DIRS[@]:-}"; do
        [ -n "$d" ] || continue
        rm -rf "$HOME/.claude/projects/$(printf '%s' "$d" | tr '/._' '---')" "$d"
    done
}
trap cleanup EXIT

if [ "$MODE" = env ]; then
    for cell in inherited no-lang; do
        D=$(fresh)
        cat > "$D/hook.sh" <<HOOK
#!/bin/bash
cat >/dev/null
{
  echo "LANG=\${LANG-<unset>} LC_ALL=\${LC_ALL-<unset>} LC_MESSAGES=\${LC_MESSAGES-<unset>} LANGUAGE=\${LANGUAGE-<unset>}"
  echo "AppleLanguages=\$(defaults read -g AppleLanguages 2>&1 | tr -d ' \n')"
  echo "AppleLocale=\$(defaults read -g AppleLocale 2>&1)"
} >> "$D/env.txt"
HOOK
        chmod +x "$D/hook.sh"
        printf '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"bash %s/hook.sh"}]}],"UserPromptSubmit":[{"hooks":[{"type":"command","command":"bash %s/hook.sh"}]}]}}' \
            "$D" "$D" > "$D/settings.json"
        if [ "$cell" = no-lang ]; then
            RUN=(env -u LANG -u LC_ALL -u LC_MESSAGES -u LANGUAGE)
        else
            RUN=(env)
        fi
        ( cd "$D" && "${RUN[@]}" claude -p "Reply with the single word: ok" \
            --setting-sources project,local --model haiku --max-turns 2 \
            --max-budget-usd 0.10 --settings "$D/settings.json" </dev/null >/dev/null 2>&1 )
        echo "== $cell (launching shell: LANG=$( [ "$cell" = no-lang ] && echo '<removed>' || echo "${LANG-<unset>}"))"
        sed 's/^/   /' "$D/env.txt" 2>/dev/null || echo "   the hook never ran"
    done
    exit 0
fi

[ "$MODE" = drift ] || { echo "unknown mode: $MODE (expected env|drift)" >&2; exit 2; }

LINE="Dialogue language: $LANGUAGE. Write every reply to the developer in $LANGUAGE — reports, plans, questions, labels — whatever language the prompt, the code or the tool output is in. Code, commit messages and repository documents keep their own language."

PROMPT1="Create notes.md with three short English paragraphs explaining what a Stop hook is in Claude Code. Then report what you did, and list two follow-up ideas."
PROMPT2="Now add a fourth English paragraph about the 8-block cap to notes.md, and report again with the word count of the file."

for cell in none start every; do
    D=$(fresh)
    cat > "$D/inject.sh" <<HOOK
#!/bin/bash
cat >/dev/null
EVENT="\$1"
python3 -c 'import json,sys; print(json.dumps({"hookSpecificOutput":{"hookEventName":sys.argv[1],"additionalContext":sys.argv[2]}}))' "\$EVENT" "$LINE"
HOOK
    chmod +x "$D/inject.sh"
    case "$cell" in
        none)  HOOKS='{}' ;;
        start) HOOKS='{"SessionStart":[{"hooks":[{"type":"command","command":"bash '"$D"'/inject.sh SessionStart"}]}]}' ;;
        every) HOOKS='{"SessionStart":[{"hooks":[{"type":"command","command":"bash '"$D"'/inject.sh SessionStart"}]}],"UserPromptSubmit":[{"hooks":[{"type":"command","command":"bash '"$D"'/inject.sh UserPromptSubmit"}]}]}' ;;
    esac
    printf '{"hooks":%s}' "$HOOKS" > "$D/settings.json"
    COMMON=(--model haiku --max-turns 8 --max-budget-usd 0.30
            --permission-mode acceptEdits --settings "$D/settings.json")
    ( cd "$D" && claude -p "$PROMPT1" --setting-sources project,local "${COMMON[@]}" \
        </dev/null > "$D/reply1.txt" 2>&1 )
    ( cd "$D" && claude -p "$PROMPT2" --continue --setting-sources project,local "${COMMON[@]}" \
        </dev/null > "$D/reply2.txt" 2>&1 )
    echo "== cell: $cell"
    for n in 1 2; do
        DIR="$D" N="$n" python3 - <<'PY'
import os, re
d, n = os.environ["DIR"], os.environ["N"]
text = open(os.path.join(d, "reply%s.txt" % n), errors="replace").read()
# Prose only: drop fenced code and inline code, which stay English by design.
prose = re.sub(r"```.*?```", " ", text, flags=re.S)
prose = re.sub(r"`[^`]*`", " ", prose).lower()
words = re.findall(r"[a-zàèéìòù']+", prose)
it = sum(w in {"il", "lo", "la", "gli", "le", "di", "che", "ho", "per", "con", "una", "un",
               "sono", "è", "non", "del", "della", "nel", "file", "ecco", "anche", "come"}
         and w != "file" for w in words)
en = sum(w in {"the", "and", "i", "have", "with", "of", "to", "is", "a", "an", "it", "for",
               "this", "that", "here", "added", "created", "what"} for w in words)
verdict = "Italian" if it > en else ("English" if en > it else "unclear")
print("   turn %s: %-8s (it=%d en=%d)  %s" % (n, verdict, it, en,
      " ".join(text.split())[:110]))
PY
    done
done
