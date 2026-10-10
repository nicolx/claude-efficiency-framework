#!/usr/bin/env python3
"""session-start.py — carry the charter AND the project's policy into every session.

A plugin has no CLAUDE.md and no `instructions` field, so a SessionStart hook is
the only way to ship always-on guidance. That makes restraint part of the design:
this fires in every session of every project where the plugin is enabled, and
whatever it prints is paid for on every one of them.

So it prints nothing unless the project actually opted in, which it signals by
having a policy at .efficiency/policy.md. A project that has never run
/efficiency:init sees nothing and pays no tokens for it.

Two documents go in, and the second was missing until 0.4.0:

  * the charter — the behavioural contract, versioned with the plugin;
  * the project's own policy — its criticality tiers, its routing table, its
    stop_for list and its declared defaults.

The charter without the policy was a measurable hole. Asked which paths this
project declares critical, a session answered "NOT IN MY INSTRUCTIONS": the
charter kept pointing at a file nobody had told the model to read. The declared
defaults are, by the design's own argument, the largest source of avoidable
interruptions — and they were reaching the model only inside /efficiency:plan-run,
which reads the file explicitly.

Comments are stripped from the policy's frontmatter before injection. The shipped
template teaches through its comments, which is right on disk and pure waste in a
context window paid for at every session of every adopting project.

Never fatal: on any failure it prints nothing and exits 0. A session that starts
without this is worse than one that starts with it; a session that does not start
at all is worse than both.
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHARTER = os.path.join(os.path.dirname(HERE), "AUTONOMY-CHARTER.md")

POLICY = os.path.join(".efficiency", "policy.md")
RUN = os.path.join(".efficiency", "run.md")
BACKLOG = os.path.join(".efficiency", "backlog.md")


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


def strip_comments(text):
    """Drop whole-line `#` comments from the policy's YAML frontmatter.

    Only the frontmatter: the markdown body holds the declared defaults, where a
    line starting with `#` is a heading and load-bearing. An inline `# ...` after
    a value is left alone too — quoting rules make stripping it unsafe for the
    sake of a few characters.
    """
    out, in_front, seen_fence = [], False, False
    for line in text.split("\n"):
        if line.strip() == "---" and not seen_fence:
            in_front, seen_fence = True, True
            out.append(line)
            continue
        if in_front and line.strip() == "---":
            in_front = False
            out.append(line)
            continue
        if in_front:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
        out.append(line)
    return "\n".join(out)


def open_backlog(path):
    """(count, one-line summaries) of unclosed backlog entries.

    Fenced code blocks are skipped. The shipped template documents the entry
    format with a real-looking example inside a fence, and counting it reported a
    phantom item on day one — in a file whose only job is to be trusted about how
    much is outstanding.
    """
    items, fenced = [], False
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.startswith("```"):
                    fenced = not fenced
                    continue
                if not fenced and stripped.startswith("- [ ]"):
                    items.append(stripped[5:].strip())
    except OSError:
        return 0, []
    return len(items), items


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

    # The policy is the project's own file, so a failure to read it must not cost
    # the charter as well — ship what can be shipped.
    try:
        policy = strip_comments(open(os.path.join(project, POLICY), errors="replace").read())
        text += ("\n\n---\n\n# This project's efficiency policy\n\n"
                 "From `.efficiency/policy.md`, with frontmatter comments stripped. These are the "
                 "project's own declarations: its criticality tiers, its routing table, the only "
                 "reasons it accepts for stopping, and the defaults that answer questions you would "
                 "otherwise have to ask.\n\n" + policy)
    except OSError:
        pass

    # The backlog goes FIRST and loudly. Its whole purpose is work deferred to a
    # fresh session, and a deferral nobody is reminded of is just a deletion with
    # extra steps. The model is asked to surface it once, briefly, rather than
    # left to decide whether it is worth mentioning.
    count, items = open_backlog(os.path.join(project, BACKLOG))
    if count:
        shown = "\n".join("  - %s" % i for i in items[:5])
        more = "\n  …and %d more" % (count - 5) if count > 5 else ""
        text = ("# ⚠ %d open backlog item(s) in this project\n\n"
                "From `.efficiency/backlog.md` — work earlier sessions deliberately deferred so it "
                "could be done with a clear head:\n\n%s%s\n\n"
                "**Tell the developer this once, in your first reply, in no more than two lines.** "
                "Do not start on any of it unless they ask: these were set aside on purpose, and "
                "picking one up uninvited is the scope creep the deferral existed to prevent.\n\n"
                "---\n\n" % (count, shown, more)) + text

    run_path = os.path.join(project, RUN)
    if os.path.exists(run_path):
        status = (frontmatter_value(run_path, "status") or "").upper()
        task = frontmatter_value(run_path, "current_task") or "unknown"
        if status == "ACTIVE":
            text += ("\n\n## A run is active right now\n\n"
                     "`.efficiency/run.md` holds an approved run, currently on **%s**. "
                     "The autopilot will refuse to end the turn while tasks remain open and the "
                     "gate is green, so keep working through the list.\n" % task)
        elif status == "BLOCKED":
            reason = frontmatter_value(run_path, "blocked_reason") or "no reason recorded"
            text += ("\n\n## A run is BLOCKED and needs the developer\n\n"
                     "`.efficiency/run.md` stopped on its own: %s\n\n"
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
