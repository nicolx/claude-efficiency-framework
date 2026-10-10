#!/usr/bin/env python3
"""Every measured claim must say when it was measured, and say it recently enough.

`docs/verified-platform-behaviour.md` opens by promising that each entry carries
its date, its Claude Code version and its method. Eight of its thirteen entries
did not, which is how section 7 managed to be wrong for a month: you cannot
notice that a finding has expired when most findings never said when they were
taken.

Two separate things are checked, and they are deliberately not the same severity:

  * **a section with no date is a defect.** A claim with no provenance cannot be
    re-derived, which is the one thing this document exists to make possible. It
    fails the gate.
  * **a section measured long ago is a warning.** The claim is not wrong, it is
    unconfirmed, and the platform has had time to move underneath it. It reports
    as a skip, the same way the price table's staleness does — a gate that goes
    red on the calendar is a gate people learn to ignore.

Exit codes, for `scripts/qa.sh`: 0 everything dated and fresh, 1 something is
undated, 3 everything is dated but something is stale.
"""

import datetime
import re
import sys

STALE_DAYS = 90
DOC = "docs/verified-platform-behaviour.md"

SECTION = re.compile(r"^## (\d+)\.\s*(.+)$", re.M)
DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")
VERSION = re.compile(r"\b(\d+\.\d+\.\d+)\b")


def sections(text):
    """Numbered sections only, as (number, title, body). A prose heading is not a claim."""
    marks = list(SECTION.finditer(text))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        yield m.group(1), m.group(2).strip(), text[m.end():end]


def newest_date(body):
    best = None
    for y, mo, d in DATE.findall(body):
        try:
            got = datetime.date(int(y), int(mo), int(d))
        except ValueError:
            continue
        if best is None or got > best:
            best = got
    return best


SELFTEST_CASES = [
    # name, body under a numbered heading, expected exit
    ("dated and fresh", "Measured on %s on 2.1.296.", 0),
    ("no date at all", "Measured carefully, on a real session, with a probe.", 1),
    ("long expired", "Measured on 2019-01-01 on 2.1.100.", 3),
    ("dated in the future", "Measured on 2099-01-01 on 2.1.296.", 1),
]


def selftest():
    """Prove each verdict can actually be reached.

    A staleness guard nobody has watched call something stale is a guard that
    reports "all fresh" forever, which is what the document already had.
    """
    import os
    import shutil
    import tempfile

    today = datetime.date.today().isoformat()
    failures = []
    for name, body, expected in SELFTEST_CASES:
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "docs"))
            with open(os.path.join(tmp, DOC), "w") as fh:
                fh.write("# Doc\n\n## 1. A claim\n\n%s\n" % (body % today if "%s" in body else body))
            saved = sys.stdout, sys.stderr
            sink = open(os.devnull, "w")
            try:
                sys.stdout = sys.stderr = sink
                got = run(tmp)
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
    return run(sys.argv[1] if len(sys.argv) > 1 else None)


def run(root):
    path = root + "/" + DOC if root else DOC
    try:
        text = open(path, errors="replace").read()
    except OSError as e:
        print("cannot read %s: %s" % (path, e), file=sys.stderr)
        return 1

    today = datetime.date.today()
    undated, stale, dated = [], [], 0

    for num, title, body in sections(text):
        when = newest_date(body)
        if when is None:
            undated.append("§%s %s" % (num, title))
            continue
        dated += 1
        age = (today - when).days
        if age < 0:
            undated.append("§%s %s — dated %s, which is in the future" % (num, title, when))
        elif age > STALE_DAYS:
            vers = VERSION.findall(body)
            against = (", last taken against %s" % max(vers)) if vers else ", version never noted"
            stale.append("§%s %s — %d days old%s" % (num, title, age, against))

    if undated:
        print("sections with no date, so nothing can tell whether they still hold:", file=sys.stderr)
        for u in undated:
            print("  " + u, file=sys.stderr)
        return 1

    if stale:
        print("%d dated section(s); %d older than %d days and due a re-measurement:"
              % (dated, len(stale), STALE_DAYS))
        for sct in stale:
            print("  " + sct)
        print("re-run the matching probe in scripts/probes/, then update the date in place")
        return 3

    print("%d section(s), each dated and none older than %d days" % (dated, STALE_DAYS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
