#!/usr/bin/env python3
"""Every command-line flag the probes depend on must still exist.

`--max-turns` vanished from `claude --help` on 2.1.296 while remaining accepted.
A flag that is no longer documented is one release away from being removed, and
its removal would be the worst kind of failure here: `stop-cap.sh` bounds itself
with `--max-turns`, so a session that silently stopped honouring it would not
error — it would run on, and the probe would report a number that measured the
budget rather than the platform.

The check costs nothing and calls no API. `claude <flag> --print` with stdin
closed is rejected at parse time:

    claude --bogus-flag --print   ->  error: unknown option '--bogus-flag'
    claude --max-turns  --print   ->  Error: Input must be provided ...

The second message means the flag was understood and the command then failed for
a reason that has nothing to do with it. No value is passed, deliberately: a
value after a boolean flag becomes a positional argument, which would be read as
a prompt and spend real money to answer.

Flags are read out of the probes themselves rather than listed here, so a new
probe using a new flag is covered the day it lands.

The same reader holds a second rule, and this one costs not even a subprocess:
every `claude -p` in a probe passes `--setting-sources`. Without it the
developer's own ~/.claude/settings.json reaches the session — on the author's
machine a personal output style was in every probe session until 2026-10-18 —
and the number recorded is a measurement of one machine, not of the platform.
"""

import glob
import os
import re
import subprocess
import sys

INVOCATION = re.compile(r"\bclaude\b")
SESSION = re.compile(r"\bclaude -p\b")
# Camel case is real here: --allowedTools, --disallowedTools. A character
# class that stops at the first capital silently reports "--allowed" missing.
FLAG = re.compile(r"(--[a-zA-Z][a-zA-Z0-9-]+)")


def invocations(paths):
    """(path, text) for every `claude ...` invocation, continuations joined."""
    for path in paths:
        with open(path, errors="replace") as fh:
            lines = fh.read().splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if INVOCATION.search(line) and "--version" not in line:
                chunk = [line]
                # A trailing backslash continues the invocation onto the next line.
                while chunk[-1].rstrip().endswith("\\") and i + 1 < len(lines):
                    i += 1
                    chunk.append(lines[i])
                yield path, " ".join(chunk)
            i += 1


def flags_used(paths):
    """Flags appearing inside a `claude ...` invocation."""
    found = {}
    for path, text in invocations(paths):
        for f in FLAG.findall(text):
            found.setdefault(f, set()).add(os.path.basename(path))
    return found


def unisolated(paths):
    """Probes with a session that would load the developer's user settings."""
    return sorted({os.path.basename(path) for path, text in invocations(paths)
                   if SESSION.search(text) and not text.lstrip().startswith("#")
                   and "--setting-sources" not in text})


def accepted(flag):
    try:
        p = subprocess.run(["claude", flag, "--print"],
                           stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    out = (p.stdout or "") + (p.stderr or "")
    first = out.strip().splitlines()[0] if out.strip() else ""
    if "unknown option" in out:
        return False, first
    return True, first


def selftest():
    """Prove the reader can tell a live flag from a dead one.

    Both halves matter and both have been wrong here: the regex once stopped at
    the first capital letter and reported `--allowedTools` as a missing
    `--allowed`, which is a guard inventing a failure rather than finding one.
    """
    failures = []

    live, _ = accepted("--max-turns")
    if live is not True:
        failures.append("--max-turns reads as absent, but it is accepted")
    dead, _ = accepted("--definitely-not-a-real-flag")
    if dead is not False:
        failures.append("an invented flag reads as present, so nothing would ever fail")

    sample = "claude -p x --allowedTools Write Read \\\n  --max-budget-usd 1 --permission-mode auto"
    import tempfile
    tmp = tempfile.mkdtemp()
    try:
        d = os.path.join(tmp, "scripts", "probes")
        os.makedirs(d)
        with open(os.path.join(d, "sample.sh"), "w") as fh:
            fh.write(sample + "\n")
        got = set(flags_used([os.path.join(d, "sample.sh")]))
        want = {"--allowedTools", "--max-budget-usd", "--permission-mode"}
        if not want <= got:
            failures.append("the reader missed %s" % ", ".join(sorted(want - got)))
        if unisolated([os.path.join(d, "sample.sh")]) != ["sample.sh"]:
            failures.append("a session without --setting-sources reads as isolated")
        with open(os.path.join(d, "isolated.sh"), "w") as fh:
            fh.write("claude -p x \\\n  --setting-sources project,local --max-turns 1\n")
        if unisolated([os.path.join(d, "isolated.sh")]):
            failures.append("a flag on a continuation line reads as missing")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            print("selftest FAIL %s" % f, file=sys.stderr)
        return 1
    print("selftest: a live flag reads live, an invented one reads dead, camel case survives,"
          " an unisolated session is caught")
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    paths = sorted(glob.glob(os.path.join(root, "scripts", "probes", "*.sh")))
    if not paths:
        print("no probes found under scripts/probes/", file=sys.stderr)
        return 1

    leaky = unisolated(paths)
    if leaky:
        print("probes whose sessions load the developer's ~/.claude/settings.json"
              " (add --setting-sources project,local):", file=sys.stderr)
        for name in leaky:
            print("  " + name, file=sys.stderr)
        return 1

    used = flags_used(paths)
    if not used:
        print("no claude flags found in the probes — the reader is broken, not the probes",
              file=sys.stderr)
        return 1

    gone = []
    for flag in sorted(used):
        ok, detail = accepted(flag)
        if ok is None:
            print("cannot run claude to check %s: %s" % (flag, detail), file=sys.stderr)
            return 1
        if not ok:
            gone.append("%s — used by %s — %s" % (flag, ", ".join(sorted(used[flag])), detail))

    if gone:
        print("flags the probes depend on that this claude no longer accepts:", file=sys.stderr)
        for g in gone:
            print("  " + g, file=sys.stderr)
        return 1

    print("%d flag(s) across %d probe(s), all still accepted" % (len(used), len(paths)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
