#!/bin/bash
# dot-claude-writes.sh — re-measure whether Claude Code refuses to write inside
# `.claude/`, across tools and permission modes.
#
# The claim in docs/verified-platform-behaviour.md § 9 rests on this, and § 9 is
# the finding that decided where every file this framework writes actually lives.
# It was measured once, on 2.1.289, under one permission mode, and a later
# session on 2.1.296 saw the opposite. This probe settles it.
#
#   bash scripts/probes/dot-claude-writes.sh
#
# Costs a few cents of Haiku and a couple of minutes. Writes nothing outside its
# own temporary directory.
#
# How it discriminates: each session is asked to write in two places — the
# project root and `.claude/` inside it — in that order. The root write is the
# control. If the root succeeds and `.claude/` does not, the *path* is the
# reason. If neither succeeds, the session was blocked from writing at all and
# the cell proves nothing about `.claude/`; it is reported as inconclusive
# rather than quietly counted as a refusal.
#
# `Edit` is asked only to overwrite files that already exist. It cannot reliably
# create one, so asking it to was measuring the tool's shape rather than the
# path — the first run of this probe returned "inconclusive" for three of its
# four Edit cells for exactly that reason.

set -uo pipefail

command -v claude >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }

VERSION=$(claude --version 2>/dev/null | head -1)
echo "claude: ${VERSION:-unknown}"
echo

ROOT=$(mktemp -d) || exit 2
trap 'rm -rf "$ROOT"' EXIT

MODES="acceptEdits auto dontAsk bypassPermissions"
TOOLS="Write Edit Bash"

RESULTS="$ROOT/results"
: > "$RESULTS"

# Build a throwaway project with a file to overwrite in each of the two places.
make_project() {
    local dir="$1"
    mkdir -p "$dir/.claude" || return 1
    echo before > "$dir/probe-existing.txt"
    echo before > "$dir/.claude/probe-existing.txt"
}

# "after" means the write landed. Anything else — missing file, untouched
# "before" — means it did not.
landed() { [ -f "$1" ] && grep -qx after "$1"; }

# Edit cannot create a file; every other tool here can.
creates() { [ "$1" != Edit ]; }

prompt_for() {
    local tool="$1"
    if creates "$tool"; then
        cat <<EOF
Use ONLY the $tool tool for the file changes below. Attempt all four, in this
order, and do not stop early: if one fails, say which and move on to the next.

1. Overwrite probe-existing.txt so it contains exactly: after
2. Create probe-new.txt containing exactly: after
3. Overwrite .claude/probe-existing.txt so it contains exactly: after
4. Create .claude/probe-new.txt containing exactly: after

Then reply with the single word DONE.
EOF
    else
        cat <<EOF
Use ONLY the $tool tool for the file changes below. Both files already exist and
contain the single word "before". Attempt both, in this order, and do not stop
early: if one fails, say which and move on to the next.

1. Change probe-existing.txt so it contains exactly: after
2. Change .claude/probe-existing.txt so it contains exactly: after

Then reply with the single word DONE.
EOF
    fi
}

# One session. Records: mode, tool, whether the root pair landed, whether the
# .claude pair landed.
run_cell() {
    local mode="$1" tool="$2"
    local dir="$ROOT/$mode-$tool"
    make_project "$dir" || return 1

    local deny
    case "$tool" in
        Write) deny="Edit Bash NotebookEdit" ;;
        Edit)  deny="Write Bash NotebookEdit" ;;
        Bash)  deny="Write Edit NotebookEdit" ;;
    esac

    # Read is allowed throughout: Write and Edit both refuse to touch a file the
    # session has not read, and that refusal has nothing to do with the path.
    # shellcheck disable=SC2086
    ( cd "$dir" && claude -p "$(prompt_for "$tool")" \
        --setting-sources project,local \
        --model haiku --max-turns 10 --max-budget-usd 0.30 \
        --permission-mode "$mode" \
        --allowedTools "$tool" Read \
        --disallowedTools $deny </dev/null >"$dir/session.log" 2>&1 )

    local root_ok=no dot_ok=no
    if creates "$tool"; then
        landed "$dir/probe-existing.txt" && landed "$dir/probe-new.txt" && root_ok=yes
        landed "$dir/.claude/probe-existing.txt" && landed "$dir/.claude/probe-new.txt" && dot_ok=yes
    else
        landed "$dir/probe-existing.txt" && root_ok=yes
        landed "$dir/.claude/probe-existing.txt" && dot_ok=yes
    fi

    echo "$mode $tool $root_ok $dot_ok" >> "$RESULTS"
    printf '  %-18s %-5s  root=%-3s  .claude=%s\n' "$mode" "$tool" "$root_ok" "$dot_ok"
}

echo "Running $(echo "$MODES" | wc -w | tr -d ' ') modes x $(echo "$TOOLS" | wc -w | tr -d ' ') tools:"
for mode in $MODES; do
    for tool in $TOOLS; do
        run_cell "$mode" "$tool"
    done
done

echo
echo "| permission mode | tool | project root | inside .claude/ | reading |"
echo "|---|---|---|---|---|"

REFUSED=0
ALLOWED=0
INCONCLUSIVE=0

while read -r mode tool root_ok dot_ok; do
    if [ "$root_ok" = no ]; then
        reading="inconclusive — nothing was written anywhere"
        INCONCLUSIVE=$((INCONCLUSIVE + 1))
    elif [ "$dot_ok" = no ]; then
        reading="**refused** — the path is the reason"
        REFUSED=$((REFUSED + 1))
    else
        reading="allowed"
        ALLOWED=$((ALLOWED + 1))
    fi
    echo "| $mode | $tool | $root_ok | $dot_ok | $reading |"
done < "$RESULTS"

echo
echo "refused: $REFUSED   allowed: $ALLOWED   inconclusive: $INCONCLUSIVE"
echo

if [ "$((REFUSED + ALLOWED))" -eq 0 ]; then
    echo "verdict: PROBE BROKEN — no session wrote anything, anywhere. This is not"
    echo "         evidence about .claude/. Check that claude runs headless at all"
    echo "         before reading anything into it."
    exit 1
elif [ "$ALLOWED" -eq 0 ]; then
    echo "verdict: CONFIRMED — writes inside .claude/ are refused wherever the session"
    echo "         could write at all. Section 9 stands; the 2.1.296 anomaly does not"
    echo "         reproduce."
elif [ "$REFUSED" -eq 0 ]; then
    echo "verdict: NOT REPRODUCED — every session that could write at all wrote inside"
    echo "         .claude/ too. Section 9 is no longer true and must be rewritten with"
    echo "         today's date, not merely annotated."
else
    echo "verdict: MODE-DEPENDENT — .claude/ is refused in some cells and allowed in"
    echo "         others. The table above is the finding: section 9 must name the"
    echo "         modes it holds for instead of claiming a blanket refusal."
fi
