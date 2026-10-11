#!/usr/bin/env python3
"""`[Unreleased]` must be empty when a release is cut.

The section had no definition, only a habit, and it quietly came to mean two
different things in the same file. Repo-internal work — `scripts/`, `docs/`,
`CLAUDE.md` — does not change what a consumer receives, so rule 6 never asked it
to bump `VERSION`. It was filed under `[Unreleased]` and nothing ever moved it
out, because nothing was responsible for moving it. By 0.19.0 three of the four
entries there were already inside the tag `origin` was serving: the changelog
described as pending what consumers had had for a release.

Tidying those three by hand fixes the file for about a week. The next
repo-internal commit followed by a release puts it straight back, and nobody
notices, which is the same shape as the six releases that were announced and
never pushed — a step that exists only in someone's head is a step that is
skipped.

So `[Unreleased]` gets one checkable meaning: **committed, and not yet inside any
tag.** `scripts/release.sh` calls this before cutting, and refuses while the
section has entries. Cutting a release is then the thing that forces them to be
filed under the version they ship in, and the section cannot accumulate past a
release again.

Deliberately **not** wired into `scripts/qa.sh` as a live check. Between releases
a populated `[Unreleased]` is exactly right, and a gate that went red on it would
be red for most of the repo's life. Only the selftest runs at gate time, which is
what proves the refusal still fires. Same split as `check-release-tag.py
--remote`: the expensive or situational half belongs to the release path.

What counts as an entry is a `###` heading. Prose directly under `## [Unreleased]`
is the section explaining itself and is not work — without that distinction the
check would refuse to ever release again the moment anyone documented the rule.

Exit codes, for `scripts/release.sh`: 0 the section is clear, 1 it has entries.
"""

import os
import re
import sys

CHANGELOG = "CHANGELOG.md"
UNRELEASED = re.compile(r"^## \[Unreleased\]\s*$", re.M)
VERSION_HEAD = re.compile(r"^## \[", re.M)
ENTRY = re.compile(r"^### (.+)$", re.M)


def entries(text):
    """The `###` headings between `## [Unreleased]` and the next `## [` heading.

    Returns None when the section is absent, which is a different answer from
    "the section is empty" and has to stay distinguishable: a changelog with no
    `[Unreleased]` at all is not a changelog that is ready to release, it is one
    somebody restructured without telling this check.
    """
    start = UNRELEASED.search(text)
    if not start:
        return None
    nxt = VERSION_HEAD.search(text, start.end())
    body = text[start.end():nxt.start() if nxt else len(text)]
    return ENTRY.findall(body)


def check(path=CHANGELOG):
    try:
        with open(path, errors="replace") as fh:
            text = fh.read()
    except OSError as e:
        print("cannot read %s: %s" % (path, e), file=sys.stderr)
        return 1

    found = entries(text)
    if found is None:
        print("%s has no [Unreleased] section. Add one, even empty: it is where work "
              "lands between releases, and its absence is how work stops being recorded "
              "at all." % path, file=sys.stderr)
        return 1

    if found:
        print("%s still has %d entr%s under [Unreleased]:"
              % (path, len(found), "y" if len(found) == 1 else "ies"), file=sys.stderr)
        for e in found:
            print("    %s" % e, file=sys.stderr)
        print("\nMove them under the version being cut. They ship in it, so that is where "
              "they belong — leaving them here is how the section came to describe work "
              "consumers already had.", file=sys.stderr)
        return 1

    print("[Unreleased] is clear")
    return 0


def selftest():
    """Prove the refusal fires, and prove it does not fire on prose.

    The second case is the one that matters. A check that counted any text under
    the heading would refuse every release from the moment the section documents
    itself — a guard whose first act is to block the thing it was built to
    protect.
    """
    import contextlib
    import io
    import shutil
    import tempfile

    cases = [
        ("a section with entries", """# Changelog

## [Unreleased]

### Fixed — something

Detail.

## [1.0.0] — 2026-01-01

### Added — a thing
""", 1),
        ("a section with only its own prose", """# Changelog

## [Unreleased]

Work that is committed and not yet inside any tag.

## [1.0.0] — 2026-01-01

### Added — a thing
""", 0),
        ("an empty section", """# Changelog

## [Unreleased]

## [1.0.0] — 2026-01-01

### Added — a thing
""", 0),
        # [Unreleased] last in the file, with no version heading after it to
        # bound the search. The scan has to stop at end-of-file rather than
        # running off it, and an entry there must still be seen.
        ("entries in a trailing section", """# Changelog

## [1.0.0] — 2026-01-01

### Added — a thing

## [Unreleased]

### Fixed — something later
""", 1),
        ("no section at all", """# Changelog

## [1.0.0] — 2026-01-01

### Added — a thing
""", 1),
    ]

    failures = []
    tmp = tempfile.mkdtemp()
    try:
        for name, body, want in cases:
            path = os.path.join(tmp, "CHANGELOG.md")
            with open(path, "w") as fh:
                fh.write(body)
            # Each case's own reporting is captured rather than printed: qa.sh
            # shows a selftest's output as its `ok` line, so a passing run that
            # narrates five refusals is unreadable. A FAILING case gets its
            # output back, because that is when it is worth reading.
            noise, quiet = io.StringIO(), io.StringIO()
            with contextlib.redirect_stderr(noise), contextlib.redirect_stdout(quiet):
                got = check(path)
            if got != want:
                failures.append("%s: expected exit %d, got %d -- it said: %s"
                                % (name, want, got,
                                   (noise.getvalue() or quiet.getvalue()).strip()
                                   .replace("\n", " ") or "nothing"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for line in failures:
            print("selftest FAIL " + line, file=sys.stderr)
        return 1
    print("selftest: %d case(s) — entries stop a release, the section's own prose does not"
          % len(cases))
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--selftest" in sys.argv[1:]:
        return selftest()
    if args and os.path.isdir(args[0]):
        os.chdir(args[0])
    return check()


if __name__ == "__main__":
    sys.exit(main())
