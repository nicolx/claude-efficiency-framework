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
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
CHARTER = os.path.join(PLUGIN_ROOT, "AUTONOMY-CHARTER.md")

POLICY = os.path.join(".efficiency", "policy.md")
RUN = os.path.join(".efficiency", "run.md")
BACKLOG = os.path.join(".efficiency", "backlog.md")
TOOLS = os.path.join(".efficiency", "tools.md")
STATUSLINE = os.path.join(".efficiency", "statusline.py")

# Both files Claude Code merges project settings from. A status line declared in
# either one is installed, and only a project that has neither gets offered one.
SETTINGS = [os.path.join(".claude", "settings.json"),
            os.path.join(".claude", "settings.local.json")]

# Where these files lived before 0.4.0, when they were still under .claude/ and
# could therefore never be written by the model. An install that upgraded across
# that move has its policy in the old place and the plugin looking in the new
# one, which makes the framework go INERT without saying a word — the worst way
# for anything to fail. Detected here, loudly, and never migrated silently:
# moving a developer's files unasked is the invasive act this framework avoids.
LEGACY = [
    (os.path.join(".claude", "efficiency.md"), ".efficiency/policy.md"),
    (os.path.join(".claude", "efficiency.local.md"), ".efficiency/run.md"),
    (os.path.join(".claude", ".efficiency-autopilot.json"), ".efficiency/autopilot.json"),
]


def load_language():
    sys.path.insert(0, os.path.join(HERE, "lib"))
    import language
    return language


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


TOOLS_MAX_AGE_DAYS = 7


def refresh_tools(project, plugin_root):
    """Write .efficiency/tools.md when it is missing or stale.

    The inventory used to be the adopter's job, via a script in the plugin's own
    directory. Measured: a session cannot read or execute anything outside the
    project it is working in, and it is never told where the plugin lives — so
    that instruction could not be followed by anyone.

    A hook has neither limitation. It knows CLAUDE_PLUGIN_ROOT and runs outside
    the model's permission surface, so the inventory writes itself and no adopter
    has to remember. Conditional on age because the detection shells out around
    twenty-five times, which is pointless at every session start.

    Launched DETACHED and never waited for. Measured 2026-10-21: on a machine
    with docling and marker installed the detection took 53 s, against this
    hook's 15 s timeout, so the hook was killed and the inventory never written.
    Capped per tool it takes about 11 s, still most of the budget, and a session
    start should not wait on it at all. The cost is that the session which writes
    the inventory does not see it; the next one does.
    """
    out = os.path.join(project, TOOLS)
    try:
        if os.path.exists(out):
            age = time.time() - os.path.getmtime(out)
            if age < TOOLS_MAX_AGE_DAYS * 86400:
                return
        script = os.path.join(plugin_root, "scripts", "detect-tools.sh")
        if not os.path.exists(script):
            return
        subprocess.Popen(["bash", script, project], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
    except (OSError, subprocess.SubprocessError):
        return  # never fatal: a missing inventory costs tokens, not the session


def refresh_statusline(project, plugin_root):
    """Copy hooks/statusline.py into the project, replacing an older copy.

    The status line is the framework's only continuously visible surface, and the
    command that paints it cannot name the plugin: measured, its environment has
    `CLAUDE_PROJECT_DIR` but **no `CLAUDE_PLUGIN_ROOT`**, and a plugin's install
    path is not stable enough to hard-code into a developer's settings anyway.

    So the script travels into the project, by the same rule that moved the tool
    inventory here: anything outside the project is unreachable from a session,
    and a hook is the one thing that can see both sides. Copied on content, not
    on age — a plugin upgrade must reach the status line the next session, and
    the file is small enough that comparing it costs nothing.
    """
    src = os.path.join(plugin_root, "hooks", "statusline.py")
    dst = os.path.join(project, STATUSLINE)
    try:
        wanted = open(src, "rb").read()
    except OSError:
        return
    try:
        if os.path.exists(dst) and open(dst, "rb").read() == wanted:
            return
        with open(dst, "wb") as fh:
            fh.write(wanted)
        os.chmod(dst, 0o755)
    except OSError:
        return  # never fatal: a stale status line is better than a dead session


def statusline_declared(project):
    """True when either settings file already declares a `statusLine`.

    An existing one is never touched. A developer who has built their own status
    line has made exactly the decision this framework otherwise argues for, and
    overwriting it to say the same thing differently would be the rudest possible
    way to deliver a reminder.
    """
    for name in SETTINGS:
        try:
            with open(os.path.join(project, name), errors="replace") as fh:
                if json.load(fh).get("statusLine"):
                    return True
        except (OSError, ValueError):
            continue
    return False


def available_tools(path):
    """The `name — purpose` half of each available tool, versions dropped.

    Only the "Available" section, and only up to "Not installed": what is absent
    is worth knowing when something needs it, not worth paying for at the start
    of every session. Versions are dropped for the same reason — they are in the
    file when anyone wants them.
    """
    lines, inside = [], False
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                if line.startswith("## Available"):
                    inside = True
                    continue
                if line.startswith("## "):
                    inside = False
                    continue
                if inside and line.startswith("- `"):
                    lines.append(line.rstrip().split(" · ")[0])
    except OSError:
        return []
    return lines


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ""
    if not project or not os.path.isdir(project):
        return 0

    if not os.path.exists(os.path.join(project, POLICY)):
        stale = [(old, new) for old, new in LEGACY
                 if os.path.exists(os.path.join(project, old))]
        if stale:
            moves = "\n".join("  - `%s` → `%s`" % (old, new) for old, new in stale)
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": (
                    "# ⚠ This project's efficiency framework is INERT after an upgrade\n\n"
                    "It was set up before 0.4.0, when these files lived under `.claude/`. They moved "
                    "because **Claude Code refuses writes into `.claude/`**, which meant the model "
                    "could never tick a task closed, append to the run log, or arm the autopilot at "
                    "all.\n\n"
                    "Found in the old place:\n\n%s\n\n"
                    "Until they move, nothing fires: no charter, no policy, no guards, and no "
                    "warning other than this one. **Tell the developer in your first reply**, and "
                    "offer to run `/efficiency:init`, which migrates them. Do not move their files "
                    "without asking." % moves),
            }}))
        return 0  # not adopted here, or adopted at a version whose files have moved

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

    # The dialogue language goes above everything, the backlog included. The
    # harness shows this injection as a 2 KB preview of ~18 KB, and a line below
    # the cut is a line the model may never read; this one decides the language
    # of every reply in the session.
    text = load_language().session_line(project) + text

    # The backlog is also published continuously, under the prompt, by a status
    # line — because announcing it here once is demonstrably not enough: this
    # injection is ~18 KB, the harness truncates it to a 2 KB preview, and the
    # instruction above asks for two lines in one reply. The script is refreshed
    # unconditionally; wiring it into settings stays the developer's call.
    refresh_statusline(project, PLUGIN_ROOT)
    if (not statusline_declared(project)
            and (frontmatter_value(os.path.join(project, POLICY), "statusline")
                 or "").lower() != "off"):
        text += ("\n\n---\n\n# The backlog is not permanently visible here\n\n"
                 "This project has no `statusLine`, so the backlog above is announced once per "
                 "session and then scrolls away. `.efficiency/statusline.py` is already in place "
                 "and prints the open count and the top three items under the prompt, re-rendered "
                 "on every update.\n\n"
                 "**Offer it once, in one line, then drop the subject.** It takes effect "
                 "immediately — a status line is read live, unlike a hook. To install, merge into "
                 "`.claude/settings.json`:\n\n"
                 "```json\n"
                 "{\n"
                 "  \"statusLine\": {\n"
                 "    \"type\": \"command\",\n"
                 "    \"command\": \"python3 \\\"$CLAUDE_PROJECT_DIR/.efficiency/statusline.py\\\"\",\n"
                 "    \"padding\": 0\n"
                 "  }\n"
                 "}\n"
                 "```\n\n"
                 "If they decline, add `statusline: off` to the frontmatter of "
                 "`.efficiency/policy.md` so this is never raised again.\n")

    refresh_tools(project, PLUGIN_ROOT)
    tools = available_tools(os.path.join(project, TOOLS))
    if tools:
        text += ("\n\n---\n\n# Operational tools already on this machine\n\n"
                 "From `.efficiency/tools.md`. **Use these instead of writing a script to do the "
                 "same thing** — that is what they are listed for, and the saving is large: one "
                 "command where a reimplementation costs thousands of tokens and gets the edge "
                 "cases wrong.\n\n" + "\n".join(tools) +
                 "\n\nA tool not listed here is not installed. If you need one, name it and offer "
                 "to install it once, rather than working around its absence.\n")

    text += ("\n\n---\n\n# Where this plugin lives\n\n`%s`\n\n"
             "**You cannot read or execute anything in there** — it is outside the directory this "
             "session may touch, and that is the platform's rule, not a missing permission. The path "
             "is here so you can hand the developer a command they can run themselves:\n\n"
             "- `bash %s/scripts/check-install.sh .` — is this project's install working?\n"
             "- `python3 %s/hooks/autopilot-stop.py --selftest` — is the autopilot's plumbing sound?\n\n"
             "Everything you need yourself is inside the project, put there by these hooks.\n"
             % (PLUGIN_ROOT, PLUGIN_ROOT, PLUGIN_ROOT))

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
