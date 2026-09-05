#!/usr/bin/env python3
"""Every path written in a shipped document must exist.

A path in prose is a live reference: a consumer resolves it at session start, so
a stale one is a broken feature rather than a typo. When a file moves, this is
what catches the stragglers.

Written in Python rather than as a shell one-liner because the match must not
start mid-word — a naive regex pulls "agents/agent-" out of
"subagents/agent-<id>.jsonl" and fails on a path nobody ever claimed.
"""

import os
import re
import sys

PATTERN = re.compile(r"(?<![\w/.-])(?:hooks|skills|agents|templates|scripts|docs)/[\w./-]+")
PLACEHOLDER = set("<>*$")

# The most load-bearing references are the ones a consuming session resolves at
# runtime, and they are written against the plugin root. Strip that prefix so
# the path after it is matched at a boundary instead of being skipped for having
# a slash in front of it — which silently left them unchecked.
PLUGIN_ROOT = re.compile(r"\$\{?CLAUDE_PLUGIN_ROOT\}?/")


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    os.chdir(root)

    found = set()
    for dirpath, dirnames, filenames in os.walk("."):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        for name in filenames:
            if not name.endswith((".md", ".json")):
                continue
            with open(os.path.join(dirpath, name), errors="replace") as fh:
                text = PLUGIN_ROOT.sub(" ", fh.read())
                for ref in PATTERN.findall(text):
                    found.add(ref.rstrip(".,)`\"'"))

    checked = [r for r in sorted(found) if not (PLACEHOLDER & set(r))]
    broken = [r for r in checked if not os.path.exists(r)]

    if broken:
        print("referenced but missing: " + ", ".join(broken), file=sys.stderr)
        return 1
    print("%d referenced path(s), all present" % len(checked))
    return 0


if __name__ == "__main__":
    sys.exit(main())
