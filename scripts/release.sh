#!/bin/bash
# release.sh — cut the tag the catalogue pins, and push it.
#
#   bash scripts/release.sh            # gate, tag, push, verify the remote resolves it
#   bash scripts/release.sh --dry-run  # everything except the tag and the push
#
# This script exists because the step it performs was never written down. Rule 6
# of CLAUDE.md said to bump VERSION, plugin.json and CHANGELOG in the same commit
# and stopped there, so that is exactly what happened: 0.14.0 through 0.18.1 were
# committed, announced in the changelog, and never tagged or pushed. Consumers
# pin by ref, so six releases existed only on one laptop while `origin` served
# 0.13.0 — and `scripts/qa.sh` was green throughout, because it compared five
# copies of the version to each other and never asked git whether the release was
# real.
#
# A step that lives only in someone's head is a step that is skipped. This is the
# head it came out of.

set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

DRY=no
[ "${1:-}" = "--dry-run" ] && DRY=yes

bold() { printf '\033[1m%s\033[0m\n' "$1"; }
die()  { printf '\033[31mrefused\033[0m — %s\n' "$1" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "git is not on PATH"

# ── 1. nothing uncommitted ──────────────────────────────────────────────────
# A tag names a commit, not a working tree. Tagging with changes in flight ships
# a tree that exists nowhere, and the difference is invisible afterwards.
if [ -n "$(git status --porcelain)" ]; then
    git status --short >&2
    die "the working tree is dirty. A tag names a commit; commit or stash first."
fi

VERSION=$(cat VERSION 2>/dev/null) || die "cannot read VERSION"
TAG="v$VERSION"
bold "== releasing $TAG"

# ── 2. the gate ─────────────────────────────────────────────────────────────
# qa.sh exits 2 for "passed what could run", which is a pass. Anything else is not.
bold "== gate"
bash scripts/qa.sh >/tmp/release-qa.$$ 2>&1
QA=$?
case "$QA" in
    0|2) printf '  gate passed (exit %s)\n' "$QA" ;;
    *)   cat /tmp/release-qa.$$ >&2; rm -f /tmp/release-qa.$$
         die "the gate did not pass (exit $QA). A release is the one thing that cannot ship red." ;;
esac
rm -f /tmp/release-qa.$$

# ── 3. the tag must not already exist ───────────────────────────────────────
if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    AT=$(git rev-parse --short "$TAG^{commit}")
    HEAD_SHA=$(git rev-parse --short HEAD)
    if [ "$AT" = "$HEAD_SHA" ]; then
        printf '  %s already exists at HEAD — nothing to cut\n' "$TAG"
    else
        die "$TAG already exists, at $AT, and HEAD is $HEAD_SHA. Bump VERSION rather than moving a tag consumers may already have resolved."
    fi
else
    SUBJECT=$(git log -1 --format=%s)
    bold "== tag"
    if [ "$DRY" = yes ]; then
        printf '  would cut %s at %s — %s\n' "$TAG" "$(git rev-parse --short HEAD)" "$SUBJECT"
    else
        git tag -a "$TAG" -m "$TAG — $SUBJECT" || die "could not create $TAG"
        printf '  cut %s at %s\n' "$TAG" "$(git rev-parse --short HEAD)"
    fi
fi

# ── 4. push the branch and the tag, in that order ───────────────────────────
# The tag last: a tag that resolves to a commit the remote does not have is a ref
# consumers can see and cannot fetch.
BRANCH=$(git rev-parse --abbrev-ref HEAD)
bold "== push"
if [ "$DRY" = yes ]; then
    printf '  would push %s, then %s, to origin\n' "$BRANCH" "$TAG"
else
    git push origin "$BRANCH" || die "could not push $BRANCH"
    git push origin "$TAG"    || die "could not push $TAG — the branch is out, the tag is not"
    printf '  pushed %s and %s\n' "$BRANCH" "$TAG"
fi

# ── 5. verify against the remote, not against ourselves ─────────────────────
# The whole point. A release that was not checked against the thing consumers
# resolve has not been checked.
bold "== verify"
if [ "$DRY" = yes ]; then
    printf '  would ask origin whether %s resolves\n' "$TAG"
    exit 0
fi
python3 scripts/lib/check-release-tag.py --remote
RC=$?
case "$RC" in
    0) printf '\033[1m%s is live\033[0m — the catalogue ref %s now resolves on origin.\n' "$TAG" "$TAG" ;;
    3) printf '  the remote could not be reached; %s is local and pushed, but unverified.\n' "$TAG" ;;
    *) die "$TAG does not resolve on origin after pushing it." ;;
esac
exit 0
