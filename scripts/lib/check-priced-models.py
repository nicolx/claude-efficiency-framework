#!/usr/bin/env python3
"""The cost table must price the models this framework actually routes to.

The framework routes by **alias** — `model: haiku` in an agent, `implement:
sonnet` in a policy. Claude Code resolves that alias to an **id** at session
start, and `hooks/lib/spend.py` prices the id. Nothing connected the two ends,
so the table could be complete, consistent, recently dated — and still know
none of the models in use.

That is not hypothetical. A real run on 2.1.296 resolved all three aliases to
the 5-5 generation, none of which the table held, so every one of them was
priced at the deliberately-expensive fallback. The report then printed a
confident per-model split that was three different models at one wrong price,
and the gate was green throughout: it checked the table against *itself*.

So this check asks a different question. Which aliases does the framework route
to, and does the table hold the id each one resolves to?

The second half of that cannot be answered for free — resolving an alias means
starting a session, which costs money and needs the network. That belongs in a
probe, and `scripts/probes/model-ids.sh` is it. The probe measures the mapping
and prints it; the mapping is recorded in the cost table under `resolved`,
beside the prices it selects; and this check — free, offline — holds the two
halves together:

  * every alias the shipped artefacts route to has a measured id, and
  * every measured id has a price.

Exit codes, for `scripts/qa.sh`: 0 complete, 1 a gap, 3 the mapping is older
than the platform is likely to have stayed still.
"""

import datetime
import glob
import json
import os
import re
import sys

STALE_DAYS = 90
COSTS = "hooks/lib/model-costs.json"

# `model: haiku` in an agent's frontmatter.
AGENT_MODEL = re.compile(r"^model:\s*([A-Za-z0-9._-]+)\s*$", re.M)
# `implement: sonnet` / `review: opus` / `design: opus` in the policy's routing
# table. `none` is a real value there and means nobody does that step.
ROUTING_ROLE = re.compile(r"\b(?:design|implement|review):\s*([A-Za-z0-9._-]+)")
NOT_A_MODEL = {"none", "never"}


def aliases_routed(root):
    """Every model alias the shipped artefacts send work to.

    Read from the artefacts rather than listed here, so a new agent or a new
    tier is covered on the day it lands rather than the day someone remembers
    this file exists.
    """
    found = set()
    for path in sorted(glob.glob(os.path.join(root, "agents", "*.md"))):
        with open(path, errors="replace") as fh:
            found.update(AGENT_MODEL.findall(fh.read()))
    policy = os.path.join(root, "templates", "efficiency.md")
    if os.path.exists(policy):
        with open(policy, errors="replace") as fh:
            text = fh.read()
        block = re.search(r"^routing:\n((?:[ \t]+.*\n)+)", text, re.M)
        if block:
            found.update(ROUTING_ROLE.findall(block.group(1)))
    return {a for a in found if a not in NOT_A_MODEL}


def run(root):
    path = os.path.join(root, COSTS)
    try:
        with open(path) as fh:
            costs = json.load(fh)
    except (OSError, ValueError) as exc:
        print("cannot read %s: %s" % (path, exc), file=sys.stderr)
        return 1

    routed = aliases_routed(root)
    if not routed:
        print("no routed aliases found in agents/ or templates/ — the reader is "
              "broken, not the artefacts", file=sys.stderr)
        return 1

    resolved = costs.get("resolved")
    if not isinstance(resolved, dict):
        print("%s has no `resolved` block, so nothing records which ids the "
              "aliases %s actually resolve to. Run scripts/probes/model-ids.sh."
              % (COSTS, ", ".join(sorted(routed))), file=sys.stderr)
        return 1

    mapping = resolved.get("aliases")
    if not isinstance(mapping, dict):
        print("%s: `resolved.aliases` is missing or not a mapping" % COSTS, file=sys.stderr)
        return 1

    priced = costs.get("models", {})
    unmeasured = sorted(a for a in routed if a not in mapping)
    unpriced = sorted({mapping[a] for a in routed
                       if a in mapping and mapping[a] not in priced})

    if unmeasured or unpriced:
        if unmeasured:
            print("routed to, but never resolved to an id: %s — run "
                  "scripts/probes/model-ids.sh" % ", ".join(unmeasured), file=sys.stderr)
        for alias in sorted(routed):
            if alias in mapping and mapping[alias] in unpriced:
                print("alias %-8s resolves to %s, which %s does not price — every "
                      "run that routes there is measured at the fallback rate"
                      % (alias, mapping[alias], COSTS), file=sys.stderr)
        return 1

    measured = resolved.get("measured")
    try:
        y, m, d = (int(x) for x in str(measured).split("-"))
        when = datetime.date(y, m, d)
    except (ValueError, TypeError):
        print("%s: `resolved.measured` is missing or unreadable (%r). A mapping "
              "with no date cannot be re-derived." % (COSTS, measured), file=sys.stderr)
        return 1

    age = (datetime.date.today() - when).days
    if age < 0:
        print("%s: `resolved.measured` is in the future (%s)" % (COSTS, measured), file=sys.stderr)
        return 1

    summary = "%d alias(es) — %s — each resolving to a priced id" % (
        len(routed), ", ".join("%s→%s" % (a, mapping[a]) for a in sorted(routed)))
    if age > STALE_DAYS:
        print("%s, but measured %d days ago on Claude Code %s — re-run "
              "scripts/probes/model-ids.sh"
              % (summary, age, resolved.get("claude_code_version", "an unrecorded version")))
        return 3
    print("%s (measured %d day(s) ago)" % (summary, age))
    return 0


def _drop_price(c):
    del c["models"]["claude-haiku-5-5"]
    return c


def _drop_alias(c):
    del c["resolved"]["aliases"]["haiku"]
    return c


def _drop_date(c):
    del c["resolved"]["measured"]
    return c


def _age_the_mapping(c):
    c["resolved"]["measured"] = "2019-01-01"
    return c


def _drop_resolved(c):
    del c["resolved"]
    return c


SELFTEST_CASES = [
    # name, mutation applied to a known-good table, expected exit, expected words
    ("complete and fresh", lambda c: c, 0, "each resolving to a priced id"),
    ("an alias resolves to an id with no price", _drop_price, 1, "does not price"),
    ("an alias was never resolved at all", _drop_alias, 1, "never resolved to an id"),
    ("the mapping has no date", _drop_date, 1, "cannot be re-derived"),
    ("the mapping is years old", _age_the_mapping, 3, "re-run"),
    ("nothing was ever measured", _drop_resolved, 1, "no `resolved` block"),
]


def selftest():
    """Prove each verdict is reachable.

    The bug this file exists to catch passed a green gate for a release, so a
    case that merely shows the happy path would be the same mistake twice:
    every failure below is the real one, reproduced.
    """
    import copy
    import shutil
    import tempfile

    today = datetime.date.today().isoformat()
    good = {
        "default": "claude-fable-5-1",
        "models": {"claude-fable-5-1": {}, "claude-haiku-5-5": {}, "claude-opus-5-5": {}},
        "resolved": {"measured": today, "claude_code_version": "2.1.296",
                     "aliases": {"haiku": "claude-haiku-5-5", "opus": "claude-opus-5-5"}},
    }

    failures = []
    for name, mutate, expected, words in SELFTEST_CASES:
        tmp = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(tmp, "hooks", "lib"))
            os.makedirs(os.path.join(tmp, "agents"))
            with open(os.path.join(tmp, "agents", "a.md"), "w") as fh:
                fh.write("---\nname: a\nmodel: haiku\n---\n")
            with open(os.path.join(tmp, "agents", "b.md"), "w") as fh:
                fh.write("---\nname: b\nmodel: opus\n---\n")
            with open(os.path.join(tmp, COSTS), "w") as fh:
                json.dump(mutate(copy.deepcopy(good)), fh)
            import io
            saved = sys.stdout, sys.stderr
            sink = io.StringIO()
            try:
                sys.stdout = sys.stderr = sink
                got = run(tmp)
            finally:
                sys.stdout, sys.stderr = saved
            said = sink.getvalue()
            if got != expected:
                failures.append("%s: expected exit %d, got %d" % (name, expected, got))
            elif words not in said:
                # Three cases exit 1. An exit code alone cannot tell them
                # apart, so a case that only checked the number would pass
                # while the check reported the wrong defect.
                failures.append("%s: exit %d was right, but it said %r"
                                % (name, got, said.strip().splitlines()[:1]))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # The reader has to see a `none` in the routing table for what it is, or it
    # reports a missing price for a model nobody ever routes to.
    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "templates"))
        with open(os.path.join(tmp, "templates", "efficiency.md"), "w") as fh:
            fh.write("routing:\n  mechanical: { implement: haiku, review: none, ask: never }\n"
                     "  critical:   { design: opus, implement: sonnet, review: opus }\n")
        got = aliases_routed(tmp)
        if got != {"haiku", "sonnet", "opus"}:
            failures.append("routing table read as %s" % sorted(got))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        for f in failures:
            print("selftest FAIL %s" % f, file=sys.stderr)
        return 1
    print("selftest: %d case(s), and `none` is not read as a model"
          % (len(SELFTEST_CASES) + 1))
    return 0


def main():
    argv = sys.argv[1:]
    if "--selftest" in argv:
        return selftest()
    root = next((a for a in argv if not a.startswith("-")), ".")
    if "--aliases" in argv:
        for alias in sorted(aliases_routed(root)):
            print(alias)
        return 0
    return run(root)


if __name__ == "__main__":
    sys.exit(main())
