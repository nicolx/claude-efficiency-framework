#!/usr/bin/env python3
"""autopilot-stop.py — refuse to end the turn while an approved run has work left.

Wired as a `Stop` hook. It is the only thing in this plugin that removes the
structural interruption: Claude finishes a task and the turn ends, and the
developer has to type "continue" for work they already approved.

  bash/python3 autopilot-stop.py --selftest    verify the plumbing, change nothing

── When it does anything at all ─────────────────────────────────────────────

Only while a run exists. No `.claude/efficiency.local.md` in the project means
this exits 0 in silence and Claude Code behaves exactly as it would without the
plugin. There is no switch to forget: the run file *is* the switch, which is the
activation pattern Claude Code documents for conditional hooks.

── The four guards, nested ──────────────────────────────────────────────────

  spend_max        stops a task that keeps looking productive and never closes
  gate_retries_max stops repair attempts on the same red gate
  continuations_max stops the run as a whole
  the platform      overrides any Stop hook after 8 consecutive blocks WITHOUT
                    progress (measured — see docs/verified-platform-behaviour.md).
                    Any tool call resets that counter, so it never truncates a
                    run that is working; it is a free anti-stall guard.

The first three write a reason a human can read. The platform's does not — which
is why ours must fire first.

── Rules it obeys ───────────────────────────────────────────────────────────

NEVER FATAL FOR ITS OWN DEFECTS. A broken hook must not stand between a
developer and their work: on any internal failure it reports and exits 0. The
one thing that authorises it to block is a live run with work left.

FAIL CLOSED ON A BLIND GUARD. If spend cannot be measured, the run is stopped
rather than continued — an unmeasured ceiling is not a ceiling. Stopping the run
is not the same as wedging the session: the turn still ends.

THE MODEL DOES NOT HOLD ITS OWN LEASH. Counters are read, incremented and
written by this script. A model that could edit them could grant itself an
unbounded run.
"""

import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SPEND = os.path.join(HERE, "lib", "spend.py")
COSTS = os.path.join(HERE, "lib", "model-costs.json")

RUN_FILE = os.path.join(".claude", "efficiency.local.md")
POLICY_FILE = os.path.join(".claude", "efficiency.md")

GATE_TIMEOUT = 900          # seconds; a test suite is allowed to be slow
GATE_OUTPUT_CHARS = 4000    # what goes back to the model on a red gate

# How many times the same task may be handed back before the wording escalates,
# and before the run stops. Both exist because of a measured failure: on this
# framework's first real run the autopilot blocked 12 times on one task, the work
# got done, the checkbox never got ticked, and the last continuations were spent
# narrating the counter instead of working. Nothing detected it.
STALL_WARN = 3
STALL_STOP = 5

TASK_RE = re.compile(r"^\s*-\s*\[(?P<mark>[ xX>])\]\s*(?P<text>.+?)\s*$")


# ── talking to Claude Code ───────────────────────────────────────────────────

def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")


def allow_silently():
    sys.exit(0)


def allow_with_note(note):
    emit({"systemMessage": note})
    sys.exit(0)


def block(reason):
    # The measured contract for Stop: a top-level decision, on stdout, exit 0.
    emit({"decision": "block", "reason": reason, "systemMessage": reason})
    sys.exit(0)


# ── the run file ─────────────────────────────────────────────────────────────

class Run:
    """A run file: `key: value` frontmatter, then a task checklist, then a log.

    Only the frontmatter is machine-owned. The body is for the human who comes
    back in the morning, and is never rewritten by this script.
    """

    def __init__(self, path):
        self.path = path
        self.keys = []          # preserves order on write
        self.values = {}
        self.body = ""
        text = open(path, errors="replace").read()
        lines = text.split("\n")
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    self.body = "\n".join(lines[i + 1:])
                    break
                if ":" in lines[i]:
                    k, v = lines[i].split(":", 1)
                    k = k.strip()
                    self.keys.append(k)
                    self.values[k] = v.strip()
            else:
                raise ValueError("frontmatter is never closed")
        else:
            raise ValueError("no frontmatter")

    def get(self, key, default=""):
        return self.values.get(key, default)

    def get_int(self, key, default=0):
        try:
            return int(self.get(key, "").strip() or default)
        except ValueError:
            return default

    def set(self, key, value):
        if key not in self.values:
            self.keys.append(key)
        self.values[key] = str(value)

    def save(self):
        """Write via a temp file in the same directory, then replace.

        os.replace is atomic on the same filesystem, so a crash mid-write leaves
        the previous run file intact rather than a truncated one that the next
        invocation would read as "no run".
        """
        out = ["---"]
        for k in self.keys:
            out.append("%s: %s" % (k, self.values[k]))
        out.append("---")
        text = "\n".join(out) + "\n" + self.body
        d = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".efficiency-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def tasks(self):
        """(mark, text) for every checklist line in the body."""
        found = []
        for line in self.body.split("\n"):
            m = TASK_RE.match(line)
            if m:
                found.append((m.group("mark").lower(), m.group("text")))
        return found

    def open_tasks(self):
        return [t for mark, t in self.tasks() if mark != "x"]

    def stop(self, reason):
        self.set("status", "BLOCKED")
        self.set("blocked_reason", reason)
        self.save()


# ── the guards ───────────────────────────────────────────────────────────────

def measure_spend(transcript, since):
    """Micro-dollars spent since `since`, or None when it cannot be measured."""
    if not transcript or not since or not os.path.exists(transcript):
        return None
    try:
        done = subprocess.run(
            [sys.executable, SPEND, transcript, since, COSTS],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        return int(done.stdout.strip())
    except ValueError:
        return None


def run_gate(command, cwd):
    """(ok, output). `ok` is None when the gate itself could not be run."""
    try:
        done = subprocess.run(command, shell=True, cwd=cwd,
                              capture_output=True, text=True, timeout=GATE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return False, "the gate did not finish within %ds" % GATE_TIMEOUT
    except (OSError, subprocess.SubprocessError) as exc:
        return None, str(exc)
    out = ((done.stdout or "") + (done.stderr or "")).strip()
    return done.returncode == 0, out[-GATE_OUTPUT_CHARS:]


def usd(micro):
    return "$%.2f" % (micro / 1_000_000.0)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        allow_with_note("efficiency autopilot: unreadable Stop payload, standing aside.")

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ""
    if not project or not os.path.isdir(project):
        allow_with_note("efficiency autopilot: no project directory, standing aside.")

    project = os.path.realpath(project)
    run_path = os.path.join(project, RUN_FILE)

    # No run, no autopilot. The common case, and it must cost nothing.
    if not os.path.exists(run_path):
        allow_silently()

    # Confinement: the run file must really live inside this project, not be a
    # link pointing out of it. A hook that writes outside the project it was
    # invoked for is the one failure worth being paranoid about.
    if os.path.dirname(os.path.realpath(run_path)) != os.path.join(project, ".claude"):
        allow_with_note("efficiency autopilot: %s resolves outside the project, "
                        "standing aside." % RUN_FILE)

    try:
        run = Run(run_path)
    except (OSError, ValueError) as exc:
        allow_with_note("efficiency autopilot: cannot read %s (%s), standing aside."
                        % (RUN_FILE, exc))

    if run.get("status").upper() != "ACTIVE":
        allow_silently()

    # ── guard 1: spend on the current task ───────────────────────────────────
    spend_max = run.get_int("task_spend_max_micro_usd", 0)
    started = run.get("task_started_at")
    task = run.get("current_task") or "the current task"

    if spend_max > 0:
        spent = measure_spend(payload.get("transcript_path"), started)
        if spent is None:
            run.stop("spend could not be measured, so the ceiling was not enforced. "
                     "An unmeasured ceiling is not a ceiling: the run stopped instead "
                     "of continuing blind.")
            allow_with_note(
                "efficiency autopilot: stopped — spend could not be measured for %s. "
                "Check transcript_path and hooks/lib/spend.py." % task)
        run.set("task_spend_micro_usd", spent)
        run.save()
        if spent >= spend_max:
            run.stop("%s reached its spend ceiling (%s of %s) without closing. "
                     "It needs a human opinion before more is spent on it."
                     % (task, usd(spent), usd(spend_max)))
            allow_with_note(
                "efficiency autopilot: stopped — %s spent %s against a ceiling of %s "
                "without closing. Your call on what to do with it." % (task, usd(spent), usd(spend_max)))

    # ── guard 2: continuations for the whole run ─────────────────────────────
    used = run.get_int("continuations_used", 0)
    used_max = run.get_int("continuations_max", 0)
    if used_max > 0 and used >= used_max:
        run.stop("the run used all %d automatic continuations. Still open: %s."
                 % (used_max, ", ".join(run.open_tasks()) or "nothing"))
        allow_with_note("efficiency autopilot: stopped — %d continuations used." % used_max)

    # ── guard 3: the gate ────────────────────────────────────────────────────
    gate = run.get("gate")
    if gate:
        ok, out = run_gate(gate, project)
        if ok is None:
            run.stop("the gate command could not be run (%s). Autonomy without a "
                     "working gate is unsupervised drift, so the run stopped." % out)
            allow_with_note("efficiency autopilot: stopped — the gate could not be run.")
        if not ok:
            tries = run.get_int("gate_retries", 0)
            tries_max = run.get_int("gate_retries_max", 2)
            if tries < tries_max:
                run.set("gate_retries", tries + 1)
                run.save()
                block("The gate is red, so this work is not done. Repair attempt %d of %d "
                      "on %s. Fix what the gate reports, then continue the run — do not "
                      "ask whether to proceed.\n\n$ %s\n%s"
                      % (tries + 1, tries_max, task, gate, out))
            run.stop("the gate stayed red after %d repair attempts on %s.\n\n$ %s\n%s"
                     % (tries_max, task, gate, out))
            allow_with_note("efficiency autopilot: stopped — the gate is still red after "
                            "%d attempts on %s." % (tries_max, task))
        if run.get_int("gate_retries", 0):
            run.set("gate_retries", 0)
            run.save()

    # ── continue, or finish ──────────────────────────────────────────────────
    remaining = run.open_tasks()
    if not remaining:
        run.set("status", "DONE")
        run.set("blocked_reason", "")
        run.save()
        allow_with_note("efficiency autopilot: run complete, every task closed and the "
                        "gate green.")

    # ── guard 4: is the run actually advancing? ──────────────────────────────
    # A task whose work is finished but whose box is never ticked looks identical
    # to a task still in progress, and the autopilot will hand it back forever.
    # Measured on this framework's own first run: 12 blocks, one task's work, no
    # box ticked, no log line.
    open_now = len(remaining)
    same = run.get_int("same_task_blocks", 0)
    if (run.get_int("open_tasks_seen", -1) == open_now
            and run.get("last_blocked_task") == task):
        same += 1
    else:
        same = 0
    run.set("same_task_blocks", same)
    run.set("open_tasks_seen", open_now)
    run.set("last_blocked_task", task)

    if same >= STALL_STOP:
        run.stop("the run stopped advancing: %s was handed back %d times in a row and "
                 "%d task(s) are still open. Either the work is blocked on something "
                 "undeclared, or finished work is not being closed. Both need a human "
                 "to look." % (task, same, open_now))
        allow_with_note("efficiency autopilot: stopped — %s was handed back %d times "
                        "without the run advancing." % (task, same))

    run.set("continuations_used", used + 1)
    run.save()

    # The block reason is the only instruction the model reliably reads on a
    # continuation — the skill's text was read once, several turns ago. So the
    # state transitions the autopilot depends on have to be spelled out here,
    # imperatively, or they do not happen.
    steps = (
        "Do this now, in order:\n"
        "1. If %(task)s's acceptance criteria are met and the gate is green, mark its "
        "line `- [x]`, append ONE line to `## Log` saying what you decided and why, set "
        "`current_task` to the next task's id, and set `task_started_at` to the current "
        "UTC time in ISO-8601.\n"
        "2. Then start the next task's actual work.\n"
        "3. If %(task)s is NOT finished, keep working on it — do not report progress.\n\n"
        "Do not summarise, do not describe the counters, and do not ask whether to "
        "proceed: the run was approved, and a status report costs a continuation without "
        "advancing anything."
    ) % {"task": task}

    warning = ""
    if same >= STALL_WARN:
        warning = ("\n\nATTENTION: %s has now been handed back %d times in a row with "
                   "the same %d task(s) open. If its work is done, what is missing is the "
                   "`- [x]` and the log line — do that first. If it cannot be finished, "
                   "say why instead of trying again; this run stops on its own after %d.\n"
                   % (task, same, open_now, STALL_STOP))

    block("%d task(s) still open, gate green. Current task: %s.\n\n%s%s\nNext open task: %s"
          % (open_now, task, steps, warning, remaining[0]))


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        # Import by absolute location rather than relying on the caller's cwd
        # being this directory — the whole point of --selftest is that it works
        # when invoked from anywhere.
        sys.path.insert(0, HERE)
        import selftest
        sys.exit(selftest.run())
    main()
