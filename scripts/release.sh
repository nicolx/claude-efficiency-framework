#!/bin/bash
# release.sh — cut the tag the catalogue pins, and push it.
#
#   bash scripts/release.sh            # gate, changelog, tag, push, verify the remote
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

# ── 2b. [Unreleased] must be empty ────────────────────────────────────
# Repo-internal work does not bump VERSION, so it lands under [Unreleased] and
# nothing was ever responsible for moving it out. By 0.19.0 three of that
# section's four entries were already inside the tag origin was serving, and the
# changelog described as pending what consumers had had for a release.
#
# Cutting the tag is the one moment that can force the question, so it is asked
# here rather than in qa.sh: between releases a populated [Unreleased] is exactly
# right, and a gate red on it would be red for most of this repo's life.
bold "== changelog"
python3 scripts/lib/check-changelog.py \
    || die "[Unreleased] still has entries. File them under $TAG — they ship in it."

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
    printf '  would ask origin whether %s resolves, and whether it serves the tree we checked\n' "$TAG"
    exit 0
fi

# Two questions, and they are not the same one. The first is whether the ref a
# consumer resolves exists at all. The second is whether what it resolves TO is
# what the gate just validated — a tag can resolve perfectly and carry a tree
# missing a file nobody noticed was never committed.
UNVERIFIED=no
python3 scripts/lib/check-release-tag.py --remote
case "$?" in
    0) ;;
    3) UNVERIFIED=yes ;;
    *) die "$TAG does not resolve on origin after pushing it." ;;
esac

python3 scripts/lib/check-published-tree.py --remote
case "$?" in
    0) ;;
    3) UNVERIFIED=yes ;;
    *) die "origin serves $TAG, but not the tree this gate checked." ;;
esac

if [ "$UNVERIFIED" = yes ]; then
    printf '  %s is pushed, but the remote could not be reached to confirm it.\n' "$TAG"
else
    printf '\033[1m%s is live\033[0m — origin resolves %s, and serves the tree that was checked.\n' "$TAG" "$TAG"
fi
exit 0
