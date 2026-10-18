#!/usr/bin/env python3
"""Every measured claim must say when, on what, and how to measure it again.

`docs/verified-platform-behaviour.md` opens by promising that each entry carries
its date, its Claude Code version and its method. Eight of its thirteen entries
did not, which is how section 7 managed to be wrong for a month: you cannot
notice that a finding has expired when most findings never said when they were
taken.

So every numbered section ends with one line, and only that line is read:

    Verified: 2026-10-18 · Claude Code 2.1.302 · `scripts/probes/stop-cap.sh`
    Verified: 2026-10-10 · Claude Code 2.1.296 · manual (`scripts/probes/statusline.sh`)

Prose is not read, because prose cites versions for other reasons — "EXPIRED on
2.1.289" is a finding, not a provenance.

What invalidates a measurement is a Claude Code release, not the calendar. That
was learnt on the alias mapping (`check-priced-models.py`) and it holds for
every section: the day an upgrade lands, everything measured on the previous
version is unconfirmed. A section re-derivable by a headless probe is therefore
compared with `claude --version`, and a mismatch names the probes to run. A
section marked `manual` needs a person in a session; it follows the calendar
only and is named as such, so it is never mistaken for a checked one. The
calendar stays behind both, for a behaviour that moves server-side.

Not the same severity, deliberately:

  * **no provenance line is a defect.** A claim with no provenance cannot be
    re-derived, which is the one thing this document exists to make possible. It
    fails the gate. So does a date in the future, or a probe that is not a file.
  * **a different version, or an old date, is a warning.** The claim is not
    wrong, it is unconfirmed. It reports as a skip, the same way the price
    table's staleness does — a gate that goes red on every upgrade is a gate
    people learn to ignore.

Where `claude` is not installed (CI) the version cannot be compared, and only
the calendar is left; that is said, not failed.

Exit codes, for `scripts/qa.sh`: 0 everything verified, 1 a provenance defect,
3 something is due a re-measurement.
"""

import datetime
import importlib.util
import os
import re
import sys

STALE_DAYS = 90
DOC = "docs/verified-platform-behaviour.md"

SECTION = re.compile(r"^## (\d+)\.\s*(.+)$", re.M)
# The line may wrap — markdownlint holds the document to 100 columns — so the
# probe list runs to the end of its paragraph.
PROVENANCE = re.compile(r"^Verified: (\S+) · Claude Code (\S+) · (.+(?:\n.+)*)$", re.M)
PROBE = re.compile(r"`(scripts/probes/[^`\s]+)`")


def installed_version():
    """`claude --version`, read the one way the alias check reads it."""
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "check_priced_models", os.path.join(here, "check-priced-models.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.installed_claude_version()


def sections(text):
    """Numbered sections only, as (number, title, body). A prose heading is not a claim."""
    marks = list(SECTION.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        yield m.group(1), m.group(2).strip(), text[m.end():end]


def run(root, installed):
    root = root or "."
    path = os.path.join(root, DOC)
    try:
        text = open(path, errors="replace").read()
    except OSError as e:
        print("cannot read %s: %s" % (path, e), file=sys.stderr)
        return 1

    today = datetime.date.today()
    defects, stale, manual, rerun = [], [], [], []
    count = 0

    for num, title, body in sections(text):
        count += 1
        name = "§%s %s" % (num, title)
        lines = PROVENANCE.findall(body)
        if len(lines) != 1:
            defects.append("%s — %s" % (name, "no `Verified:` line" if not lines
                                        else "%d `Verified:` lines" % len(lines)))
            continue
        when, version, how = lines[0]
        try:
            date = datetime.date.fromisoformat(when)
        except ValueError:
            defects.append("%s — `%s` is not a date" % (name, when))
            continue
        if date > today:
            defects.append("%s — dated %s, which is in the future" % (name, date))
            continue

        probes = PROBE.findall(how)
        missing = [p for p in probes if not os.path.isfile(os.path.join(root, p))]
        if missing:
            defects.append("%s — %s is not a file" % (name, ", ".join(missing)))
            continue
        is_manual = how.startswith("manual")
        if not is_manual and not probes:
            defects.append("%s — names no probe and is not marked manual" % name)
            continue

        age = (today - date).days
        if age > STALE_DAYS:
            stale.append("%s — %d days old, on %s" % (name, age, version))
            rerun += probes
        elif not is_manual and installed and version != installed:
            stale.append("%s — measured on %s, %s is installed" % (name, version, installed))
            rerun += probes
        if is_manual:
            manual.append("§" + num)

    if defects:
        print("sections whose provenance cannot be trusted:", file=sys.stderr)
        for d in defects:
            print("  " + d, file=sys.stderr)
        return 1

    note = []
    if manual:
        note.append("calendar only, a person must re-measure: %s" % " ".join(manual))
    if not installed:
        note.append("claude is not on PATH, so no version was compared")

    if stale:
        print("%d section(s); %d due a re-measurement:" % (count, len(stale)))
        for s in stale:
            print("  " + s)
        if rerun:
            print("run, then update each `Verified:` line:")
            for p in sorted(set(rerun)):
                print("  bash " + p)
        for n in note:
            print(n)
        return 3

    head = "%d section(s), each verified" % count
    head += (" on %s" % installed) if installed else ""
    print(head + " and none older than %d days" % STALE_DAYS)
    for n in note:
        print(n)
    return 0


SELFTEST_CASES = [
    # name, provenance line ({today}, {probe} filled in), installed version, expected exit
    ("verified on the installed version",
     "Verified: {today} · Claude Code 2.1.302 · `{probe}`", "2.1.302", 0),
    ("a release since the measurement",
     "Verified: {today} · Claude Code 2.1.296 · `{probe}`", "2.1.302", 3),
    ("manual follows only the calendar",
     "Verified: {today} · Claude Code 2.1.296 · manual", "2.1.302", 0),
    ("manual still expires",
     "Verified: 2019-01-01 · Claude Code 2.1.100 · manual", "2.1.302", 3),
    ("claude not on PATH leaves the calendar",
     "Verified: {today} · Claude Code 2.1.296 · `{probe}`", None, 0),
    ("long expired, whatever is installed",
     "Verified: 2019-01-01 · Claude Code 2.1.100 · `{probe}`", None, 3),
    ("no provenance line",
     "*Measured {today} on Claude Code 2.1.302.*", "2.1.302", 1),
    ("dated in the future",
     "Verified: 2099-01-01 · Claude Code 2.1.302 · `{probe}`", "2.1.302", 1),
    ("a probe list wrapped onto a second line",
     "Verified: {today} · Claude Code 2.1.302 · `{probe}`\n`scripts/probes/gone.sh`", "2.1.302", 1),
    ("a probe that does not exist",
     "Verified: {today} · Claude Code 2.1.302 · `scripts/probes/gone.sh`", "2.1.302", 1),
    ("neither a probe nor manual",
     "Verified: {today} · Claude Code 2.1.302 · by hand, probably", "2.1.302", 1),
]


def selftest():
    """Prove each verdict can actually be reached.

    A staleness guard nobody has watched call something stale is a guard that
    reports "all fresh" forever, which is what the document already had.
    """
    import shutil
    import tempfile

    today = datetime.date.today().isoformat()
    probe = "scripts/probes/real.sh"
    failures = []
    for name, line, installed, expected in SELFTEST_CASES:
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "docs"))
            os.makedirs(os.path.join(tmp, "scripts", "probes"))
            open(os.path.join(tmp, probe), "w").close()
            with open(os.path.join(tmp, DOC), "w") as fh:
                fh.write("# Doc\n\n## 1. A claim\n\nIt holds.\n\n%s\n"
                         % line.format(today=today, probe=probe))
            saved = sys.stdout, sys.stderr
            sink = open(os.devnull, "w")
            try:
                sys.stdout = sys.stderr = sink
                got = run(tmp, installed)
            finally:
                sys.stdout, sys.stderr = saved
                sink.close()
            if got != expected:
                failures.append("%s: expected exit %d, got %d" % (name, expected, got))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            print("selftest FAIL %s" % f, file=sys.stderr)
        return 1
    print("selftest: %d case(s), each reaching the verdict it should" % len(SELFTEST_CASES))
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    return run(sys.argv[1] if len(sys.argv) > 1 else None, installed_version())


if __name__ == "__main__":
    sys.exit(main())
