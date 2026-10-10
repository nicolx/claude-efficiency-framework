#!/usr/bin/env python3
"""prompt-reminder.py — put the arming reminder where the decision is made.

The charter already tells the model to arm the autopilot when the developer asks
for work to be carried through to the end. Measured: that is not enough. Asked
what it should do on such an instruction, a session answers correctly and names
the skill — and then, handed actual work with exactly that instruction, goes
straight to the work and arms nothing.

Knowing is not doing. The charter is read once at session start, many turns
before it matters; the instruction arrives later, and by then the salient thing
is the task. So this hook repeats one line at the moment the instruction lands.

It is deliberately small and deliberately conditional:

  * nothing at all unless the project adopted the framework;
  * nothing once a run is armed, because then the reminder is noise;
  * one short line, not a restatement of the charter.

Never fatal: any failure prints nothing and exits 0. A missing reminder costs a
turn; a broken hook costs the session.
"""

import json
import os
import sys

RUN = os.path.join(".efficiency", "run.md")
POLICY = os.path.join(".efficiency", "policy.md")

REMINDER = (
    "[efficiency] If this message asks you to carry work through to completion "
    "without check-ins — in any words, in any language — then arm the autopilot "
    "with the `efficiency:autopilot` skill BEFORE starting, and say in one line "
    "what you armed. Arming is what makes the turn refuse to end while tasks "
    "remain: agreeing to keep going without it means the turn ends after the "
    "first chunk anyway. If this is an ordinary request, ignore this line."
)


def run_is_armed(path):
    """True when a run exists and is still ACTIVE."""
    try:
        with open(path, errors="replace") as fh:
            if fh.readline().strip() != "---":
                return False
            for line in fh:
                if line.strip() == "---":
                    return False
                key, _, value = line.partition(":")
                if key.strip() == "status":
                    return value.strip().upper() == "ACTIVE"
    except OSError:
        return False
    return False


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ""
    if not project or not os.path.isdir(project):
        return 0
    if not os.path.exists(os.path.join(project, POLICY)):
        return 0
    if run_is_armed(os.path.join(project, RUN)):
        return 0

    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": REMINDER,
    }}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
