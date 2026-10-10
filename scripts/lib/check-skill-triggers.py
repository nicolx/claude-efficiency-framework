#!/usr/bin/env python3
"""A skill's description is its only trigger, so it must name the words that fire it.

A skill is invoked in two ways: the developer types `/efficiency:<name>`, or the
model reads the description and decides it applies. The second is the one the
framework actually depends on — a developer who has to remember a command name
is a developer being interrupted — and the description is the *entire* input to
that decision. Nothing else about the skill is read beforehand.

So a description that only says what the skill does, without the literal words a
developer would say when they want it, fails silently and in the one way nobody
notices: the skill simply never fires, and the session does the work the long
way round instead.

This is a house rule, not a measured platform behaviour. What was observed is
narrower: `efficiency:autopilot` is the only skill seen auto-invoking from plain
language, in English and Italian, and it is also the only one that listed its
trigger phrases verbatim. One observation is not a mechanism. The check exists so
the omission is *visible* at the gate rather than discovered in a session that
quietly did without; confirming it actually changes firing is a separate piece of
work, filed in the backlog.

Three things are required of each description:

  1. a clause saying **when** to use it, not only what it does
  2. at least two **quoted trigger phrases** — what a developer would say
  3. a length that can carry both without being padded or truncated
"""

import os
import re
import sys

MIN_LEN = 120
MAX_LEN = 1024
MIN_PHRASES = 2

# "Use when", "Use it whenever", "Use this skill when", "Use only when",
# "Use after", "Use it to" — any of the forms the shipped skills already use.
WHEN_CLAUSE = re.compile(r"\buse\s+(?:it\s+|this\s+skill\s+)?(?:when|whenever|only\s+when|after|to)\b",
                         re.IGNORECASE)

QUOTED = re.compile(r"[\"“]([^\"“”]+)[\"”]")


def description_of(path):
    """The description field of a frontmatter block, continuation lines included."""
    with open(path, errors="replace") as fh:
        lines = fh.read().splitlines()

    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None

    out = None
    for line in lines[1:end]:
        if out is not None:
            # A continuation is indented; anything at column 0 is the next key.
            if line.startswith((" ", "\t")):
                out += " " + line.strip()
                continue
            break
        if line.startswith("description:"):
            out = line[len("description:"):].strip()
    return out


def phrases(text):
    """Quoted spans that read as something a person would actually say.

    A single word in quotes is usually a term being named, not an utterance, so
    a phrase has to have a space in it to count.
    """
    return [p for p in QUOTED.findall(text) if " " in p.strip() and len(p.strip()) >= 8]


SELFTEST_CASES = [
    # name, description, must the check reject it
    ("good",
     'File something for a later session. Use it when you notice work that is not the '
     'task at hand — "that should be refactored", "there is a bug over there" — or when '
     'the developer asks what is still outstanding and what was deferred.',
     False),
    ("no phrases",
     'File something for a later session. Use it when the developer notices work that '
     'belongs to a different session than the one they are in, and wants it recorded '
     'somewhere it will survive the end of this one.',
     True),
    ("no when clause",
     'Files something for a later session, the way a developer would ask for it — '
     '"that should be refactored", "there is a bug over there", "this could be faster" — '
     'so that it survives the session that noticed it and reaches one with a clear head.',
     True),
    ("too short", 'Files things for later.', True),
]


def selftest():
    """Prove the check rejects what it claims to, not just that it runs.

    A gate nobody has watched refuse something is indistinguishable from a gate
    that passes everything, which is how a check quietly stops being one.
    """
    import shutil
    import tempfile

    failures = []
    for name, desc, must_reject in SELFTEST_CASES:
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "skills", "sample"))
            with open(os.path.join(tmp, "skills", "sample", "SKILL.md"), "w") as fh:
                fh.write("---\nname: sample\ndescription: %s\n---\n\n# Sample\n" % desc)
            rejected = check(tmp, quiet=True) != 0
            if rejected != must_reject:
                failures.append("%s: expected %s, got %s"
                                % (name,
                                   "rejected" if must_reject else "accepted",
                                   "rejected" if rejected else "accepted"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # A skill directory with no frontmatter at all must be caught too.
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "skills", "sample"))
        with open(os.path.join(tmp, "skills", "sample", "SKILL.md"), "w") as fh:
            fh.write("# Sample\n\nNo frontmatter at all.\n")
        if check(tmp, quiet=True) == 0:
            failures.append("no frontmatter: expected rejected, got accepted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            print("selftest FAIL %s" % f, file=sys.stderr)
        return 1
    print("selftest: %d case(s), each rejected or accepted as claimed"
          % (len(SELFTEST_CASES) + 1))
    return 0


def check(root, quiet=False):
    """Run the check against a project root, optionally without its own output.

    The selftest runs the check a dozen times over throwaway projects; letting
    each one report would bury the one line that matters in the failures it was
    supposed to produce.
    """
    here = os.getcwd()
    saved = sys.stdout, sys.stderr
    sink = open(os.devnull, "w") if quiet else None
    os.chdir(root)
    try:
        if sink:
            sys.stdout = sys.stderr = sink
        return _check()
    finally:
        sys.stdout, sys.stderr = saved
        if sink:
            sink.close()
        os.chdir(here)


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    return check(root)


def _check():

    skills = sorted(
        os.path.join("skills", d, "SKILL.md")
        for d in os.listdir("skills")
        if os.path.isfile(os.path.join("skills", d, "SKILL.md"))
    ) if os.path.isdir("skills") else []

    if not skills:
        print("no skills found under skills/ — nothing to check", file=sys.stderr)
        return 1

    problems = []
    for path in skills:
        desc = description_of(path)
        if not desc:
            problems.append("%s: no description in frontmatter" % path)
            continue

        found = phrases(desc)
        if len(found) < MIN_PHRASES:
            problems.append(
                "%s: names %d trigger phrase(s), needs %d — quote the words a developer "
                "would actually say, e.g. \"work through the whole list\""
                % (path, len(found), MIN_PHRASES))
        if not WHEN_CLAUSE.search(desc):
            problems.append(
                "%s: says what it does but never when to use it — add a \"Use when …\" clause"
                % path)
        if len(desc) < MIN_LEN:
            problems.append("%s: description is %d characters, under the %d minimum"
                            % (path, len(desc), MIN_LEN))
        if len(desc) > MAX_LEN:
            problems.append("%s: description is %d characters, over the %d maximum"
                            % (path, len(desc), MAX_LEN))

    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        return 1

    print("%d skill description(s), each naming its trigger phrases" % len(skills))
    return 0


if __name__ == "__main__":
    sys.exit(main())
