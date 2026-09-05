#!/usr/bin/env python3
"""session-start.py — carry the autonomy charter into projects that adopted the framework.

A plugin has no CLAUDE.md and no `instructions` field, so a SessionStart hook is
the only way to ship always-on guidance. That makes restraint part of the design:
this fires in every session of every project where the plugin is enabled, and
whatever it prints is paid for on every one of them.

So it prints nothing unless the project actually opted in, which it signals by
having a policy at .claude/efficiency.md. A project that has never run
/efficiency:init sees no charter and pays no tokens for one.

Keeping the charter here rather than copying it into each project's CLAUDE.md is
the point of shipping as a plugin: it stays versioned with the code that enforces
it, and a release updates every consumer at once instead of leaving a stale copy
in each of them.

Never fatal: on any failure it prints nothing and exits 0. A session that starts
without the charter is worse than one that starts with it, but a session that
does not start at all is worse than both.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHARTER = os.path.join(os.path.dirname(HERE), "AUTONOMY-CHARTER.md")

POLICY = os.path.join(".claude", "efficiency.md")
RUN = os.path.join(".claude", "efficiency.local.md")


def frontmatter_value(path, key):
    """One frontmatter value, without pulling in a YAML parser for four lines."""
    try:
        with open(path, errors="replace") as fh:
            if fh.readline().strip() != "---":
                return None
            for line in fh:
                if line.strip() == "---":
                    return None
                if line.split(":", 1)[0].strip() == key:
                    return line.split(":", 1)[1].strip()
    except (OSError, IndexError):
        return None
    return None


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ""
    if not project or not os.path.isdir(project):
        return 0

    if not os.path.exists(os.path.join(project, POLICY)):
        return 0  # not adopted here: say nothing, cost nothing

    try:
        text = open(CHARTER, errors="replace").read()
    except OSError:
        return 0

    run_path = os.path.join(project, RUN)
    if os.path.exists(run_path):
        status = (frontmatter_value(run_path, "status") or "").upper()
        task = frontmatter_value(run_path, "current_task") or "unknown"
        if status == "ACTIVE":
            text += ("\n\n## A run is active right now\n\n"
                     "`.claude/efficiency.local.md` holds an approved run, currently on **%s**. "
                     "The autopilot will refuse to end the turn while tasks remain open and the "
                     "gate is green, so keep working through the list.\n" % task)
        elif status == "BLOCKED":
            reason = frontmatter_value(run_path, "blocked_reason") or "no reason recorded"
            text += ("\n\n## A run is BLOCKED and needs the developer\n\n"
                     "`.claude/efficiency.local.md` stopped on its own: %s\n\n"
                     "Do not resume it silently — this is one of the interruptions the charter "
                     "says is genuinely theirs.\n" % reason)

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": text,
    }}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
