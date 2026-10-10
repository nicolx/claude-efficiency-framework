#!/usr/bin/env python3
"""Is the policy well-formed enough for the framework to use?

Prints `level|message|hint` lines for the caller to render. A policy that parses
but omits a section does not fail loudly at runtime — the model simply never sees
that part, which is the same silent degradation this whole script exists to
catch.
"""

import os
import sys

# section -> what the framework loses when it is absent
EXPECTED = {
    "budget": "no ceilings: a run would have no spend limit and no continuation budget",
    "tiers": "no declared criticality, so every task is classified by judgement",
    "routing": "no model routing, which is the framework's main contribution",
    "stop_for": "no declared stop reasons, so the charter's defaults are all that apply",
}


def main():
    path = os.environ.get("POLICY", "")
    try:
        with open(path, errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        print("bad|the policy cannot be read (%s)|" % exc)
        return 0

    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        print("bad|the policy has no frontmatter|"
              "It must open with --- on the first line.")
        return 0

    front, closed = [], False
    for line in lines[1:]:
        if line.strip() == "---":
            closed = True
            break
        front.append(line)
    if not closed:
        print("bad|the policy's frontmatter is never closed|"
              "Add a closing --- line.")
        return 0

    present = set()
    for line in front:
        if line[:1] not in (" ", "\t", "#", "") and ":" in line:
            present.add(line.split(":", 1)[0].strip())

    missing = [k for k in EXPECTED if k not in present]
    if missing:
        for k in sorted(missing):
            print("note|the policy declares no `%s`|%s" % (k, EXPECTED[k]))
    else:
        print("ok|policy declares budget, tiers, routing and stop_for|")

    body = text.split("---", 2)[-1]
    defaults = [l for l in body.split("\n") if l.strip().startswith("- ")]
    if defaults:
        print("ok|%d declared default(s)|" % len(defaults))
    else:
        print("note|no declared defaults|"
              "These are the largest source of avoidable interruptions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
