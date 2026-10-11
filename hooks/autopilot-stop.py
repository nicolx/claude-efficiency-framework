#!/usr/bin/env python3
"""autopilot-stop.py — refuse to end the turn while an approved run has work left.

Wired as a `Stop` hook. It is the only thing in this plugin that removes the
structural interruption: Claude finishes a task and the turn ends, and the
developer has to type "continue" for work they already approved.

  bash/python3 autopilot-stop.py --selftest    verify the plumbing, change nothing

── When it does anything at all ─────────────────────────────────────────────

Only while a run exists. No `.efficiency/run.md` in the project means
this exits 0 in silence and Claude Code behaves exactly as it would without the
plugin. There is no switch to forget: the run file *is* the switch, which is the
activation pattern Claude Code documents for conditional hooks.

── The five guards, nested ──────────────────────────────────────────────────

  declared ceilings a run file that never names its ceilings does not run: a
                   ceiling that was never set is not a ceiling. An explicit 0 is
                   a decision and is honoured, but it is announced every turn
  spend_max        stops a task that keeps looking productive and never closes.
                   Its window opens when a task is CLOSED, not when the model
                   rewrites `current_task`: see "the model does not hold its own
                   leash" below. This is the verdict half only — the same ceiling
                   is also held inside the turn by autopilot-pretool.py, which
                   refuses tool calls rather than waiting for the boundary
  gate_retries_max stops repair attempts on the same red gate
  continuations_max stops the run as a whole
  the platform      overrides any Stop hook after 8 consecutive blocks WITHOUT
                    progress (measured — see docs/verified-platform-behaviour.md).
                    Any tool call resets that counter, so it never truncates a
                    run that is working; it is a free anti-stall guard.

The first four write a reason a human can read. The platform's does not — which
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

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SPEND = os.path.join(HERE, "lib", "spend.py")
COSTS = os.path.join(HERE, "lib", "model-costs.json")

# The run state lives OUTSIDE .claude/ deliberately. Claude Code refuses writes
# into .claude/ under acceptEdits — measured: an identical write one directory up
# succeeds — and project permission rules do not override it. With the run file
# in there the autopilot could never arm itself, which is the whole mechanism.
RUN_FILE = os.path.join(".efficiency", "run.md")

# The hook's own state. Deliberately NOT the run file: a model told to update
# `current_task` rewrote that frontmatter and dropped every key it did not
# recognise, resetting the stall counter to zero and erasing two others. It was
# not evading anything — it simply did not know they mattered. Measured on this
# framework's own second run.
#
# So the counters and the ceilings live here, no skill mentions this file, and
# the charter forbids touching it. That is not a security boundary — anything
# with a shell can delete it — but it turns "erased while editing" into a
# deliberate, named act that shows up in the transcript.
STATE_FILE = os.path.join(".efficiency", "autopilot.json")

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

def unquote(value):
    """Drop one layer of matching surrounding quotes.

    The frontmatter is read by hand rather than by a YAML parser — there is no
    dependency to install — and for a long time that reader kept the quotes.
    `gate: "pytest -q"` therefore reached the shell as a command whose *name*
    was the whole quoted string, and `/bin/sh` answered "command not found".

    That failure is worse than it sounds. A missing command exits 127, which is
    indistinguishable from a test suite that failed, so the run did not report an
    unrunnable gate: it reported a red one, and spent its repair attempts fixing
    code that was never broken. Measured, and the quoted form is exactly what
    `templates/efficiency.md` ships.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


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
                    self.values[k] = unquote(v.strip())
            else:
                raise ValueError("frontmatter is never closed")
        else:
            raise ValueError("no frontmatter")

    def get(self, key, default=""):
        return self.values.get(key, default)

    def has(self, key):
        """Was the key written at all? Not the same question as its value.

        A ceiling of 0 is a choice someone made and approved. A ceiling that was
        never written is an incomplete run file, and the two had been
        indistinguishable — which is how a run executed with every guard
        disabled and nothing said so.
        """
        return key in self.values

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


class Private:
    """State the hook owns: counters, ceilings, and the blocked verdict.

    Two things are captured here on first sight of a run and read from here
    afterwards, never from the run file:

      * the ceilings, so a model cannot raise its own budget mid-run;
      * the blocked verdict, so setting `status: ACTIVE` in the run file does
        not resume a run that a guard stopped.

    A run is identified by the fingerprint of its task statements with the
    checkbox marks stripped, so ticking a box does not look like a new run but
    re-planning does — which is the one legitimate way to start over.
    """

    KEYS = ("fingerprint", "continuations_used", "continuations_max",
            "gate_retries", "gate_retries_max", "spend_max", "task_key",
            "task_started_at", "same_task_blocks", "open_tasks_sig",
            "blocked", "blocked_reason")

    def __init__(self, path):
        self.path = path
        self.data = {}
        try:
            with open(path, errors="replace") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                self.data = loaded
        except (OSError, ValueError):
            self.data = {}   # absent or corrupt reads as "no run seen yet"

    def get(self, key, default=None):
        return self.data.get(key, default)

    def get_int(self, key, default=0):
        try:
            return int(self.data.get(key, default))
        except (TypeError, ValueError):
            return default

    def set(self, key, value):
        self.data[key] = value

    def save(self):
        d = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".autopilot-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(self.data, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def block_run(self, run, reason):
        """Stop the run in both places, so neither can contradict the other."""
        self.set("blocked", True)
        self.set("blocked_reason", reason)
        self.save()
        run.stop(reason)


def fingerprint(run):
    """Identify a run by its task statements, ignoring the checkbox marks."""
    statements = "\n".join(text for _mark, text in run.tasks())
    return hashlib.sha256(statements.encode("utf-8", "replace")).hexdigest()


def open_signature(open_tasks):
    """Identify the *state* of a run: which of its tasks are still open.

    This is the only progress signal the model cannot move without actually
    making progress — ticking a box is a claim it has to live with, where
    `current_task` is a line the block reason tells it to rewrite every time.
    Both the spend window and the stall guard key off this, for that reason.
    """
    return hashlib.sha256("\n".join(open_tasks).encode("utf-8", "replace")).hexdigest()


def window_start(run):
    """When a fresh run's first spend window opens.

    Taken from the run file, because the hook does not see the run until the
    first turn boundary and the work of that first turn has to be inside the
    window. But `task_started_at` is frontmatter, so the model writes it: a date
    in the *future* leaves `measure_spend` an empty window for the rest of the
    run, the ceiling never fires, and nothing says so — a guard that is blind
    without announcing it, which is exactly what rule 2 forbids.

    A date in the past only widens the window and charges the task with more
    than its own spend, so it is taken as written: wrong in the safe direction.
    Unparseable or still ahead of now falls back to now.
    """
    from datetime import datetime, timezone
    declared = (run.get("task_started_at") or "").strip()
    if not declared:
        return iso_now()
    try:
        when = datetime.fromisoformat(declared.replace("Z", "+00:00"))
    except ValueError:
        return iso_now()
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return declared if when <= datetime.now(timezone.utc) else iso_now()


# ── the guards ───────────────────────────────────────────────────────────────

def measure_spend(transcript, since, by_model=False):
    """Micro-dollars spent since `since`, or None when it cannot be measured.

    With by_model, returns the parsed breakdown instead. The breakdown is written
    into the run file because a session cannot execute spend.py itself: it lives
    in the plugin's directory, and nothing outside the project is reachable from
    a session. Anything the model needs has to be put inside the project by a
    hook, and this is that.
    """
    if not transcript or not since or not os.path.exists(transcript):
        return None
    cmd = [sys.executable, SPEND, transcript, since, COSTS]
    if by_model:
        cmd.append("--by-model")
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        return json.loads(done.stdout) if by_model else int(done.stdout.strip())
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


def iso_now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
    if os.path.dirname(os.path.realpath(run_path)) != os.path.join(project, ".efficiency"):
        allow_with_note("efficiency autopilot: %s resolves outside the project, "
                        "standing aside." % RUN_FILE)

    try:
        run = Run(run_path)
    except (OSError, ValueError) as exc:
        allow_with_note("efficiency autopilot: cannot read %s (%s), standing aside."
                        % (RUN_FILE, exc))

    priv = Private(os.path.join(project, STATE_FILE))
    now = fingerprint(run)

    if priv.get("fingerprint") != now:
        # A different task list: a fresh run, or one that was re-planned. This is
        # the only legitimate way counters go back to zero, and it cannot happen
        # by editing the frontmatter — only by changing the work itself.
        priv.data = {
            "fingerprint": now,
            "continuations_used": 0,
            "continuations_max": run.get_int("continuations_max", 0),
            "gate_retries": 0,
            "gate_retries_max": run.get_int("gate_retries_max", 2),
            "spend_max": run.get_int("task_spend_max_micro_usd", 0),
            # Two keys that hold the same kind of hash and must NOT be collapsed
            # into one. `task_key` is the open-task set as of when the current
            # spend window opened, seeded with the real signature so a fresh run
            # keeps the window start below rather than restarting it at the first
            # block. `open_tasks_sig` is what the *previous* block saw, seeded
            # empty so that first block counts as progress and the stall counter
            # starts at zero — the measured block-6 stop depends on it.
            "task_key": open_signature(run.open_tasks()),
            "task_started_at": window_start(run),
            "same_task_blocks": 0,
            "open_tasks_sig": "",
            "blocked": False,
            "blocked_reason": "",
        }
        priv.save()

    # ── guard 0: the run file must actually declare its ceilings ────────────
    # Rule 2 of this project says an unmeasured ceiling is not a ceiling, and the
    # spend guard already fails closed when it cannot measure. But it only runs
    # at all when `spend_max > 0`, so a run file that never named a ceiling
    # skipped the guard *and* its fail-closed branch together, and the run went
    # ahead unbounded without a word. Measured: a hand-written run file executed
    # three tasks with spend_max and continuations_max both 0, and the only
    # symptom was a report three minutes later that could not say what anything
    # cost.
    #
    # An explicit 0 is left alone. Someone wrote it and a developer approved the
    # plan that contains it, so it is a decision — but it is announced below
    # rather than kept quiet.
    missing = [k for k in ("task_spend_max_micro_usd", "continuations_max") if not run.has(k)]
    if missing:
        priv.block_run(run, "the run file does not declare %s, so the run would have no %s at all. "
                            "A ceiling that was never set is not a ceiling. Re-plan with "
                            "/efficiency:plan-run, which writes them from the policy's budget."
                            % (" or ".join(missing),
                               "ceilings" if len(missing) > 1 else "ceiling"))
        allow_with_note("efficiency autopilot: stopped — %s missing from the run file, so the run "
                        "had no ceiling. /efficiency:plan-run writes them from the policy."
                        % " and ".join(missing))

    # The private verdict wins. A run file flipped back to ACTIVE does not
    # resume a run a guard stopped; only re-planning or deleting the state file
    # does, and both are deliberate.
    if priv.get("blocked"):
        if run.get("status").upper() == "ACTIVE":
            run.stop(priv.get("blocked_reason") or "stopped by a guard")
            allow_with_note(
                "efficiency autopilot: this run is stopped — %s\nRe-plan the work, or "
                "delete %s to resume deliberately."
                % (priv.get("blocked_reason") or "no reason recorded", STATE_FILE))
        allow_silently()

    if run.get("status").upper() != "ACTIVE":
        allow_silently()

    task = run.get("current_task") or "the current task"
    remaining = run.open_tasks()
    open_sig = open_signature(remaining)

    # The hook owns the spend window, and until 0.18.2 it opened a fresh one
    # whenever `current_task` changed — a field the model writes, and which the
    # block reason below explicitly tells it to write on every task it closes.
    # So the ceiling the plan calls "per task" was really "per edit of one line
    # of frontmatter": a model alternating between two open tasks, the confusion
    # already measured in guard 4, reopened a clean window on every block and
    # could spend the whole ceiling again each time.
    #
    # Rule 3 again: the window follows the one signal the model cannot fake,
    # which is a task closing. The cost is that the window now also holds the
    # tail of the turn in which the previous task closed — a ceiling that
    # charges slightly too much, which is the safe direction for a ceiling.
    if priv.get("task_key") != open_sig:
        priv.set("task_key", open_sig)
        priv.set("task_started_at", iso_now())
        priv.save()

    # ── guard 1: spend on the current task ───────────────────────────────────
    spend_max = priv.get_int("spend_max", 0)
    started = priv.get("task_started_at")

    if spend_max > 0:
        spent = measure_spend(payload.get("transcript_path"), started)
        if spent is None:
            priv.block_run(run, "spend could not be measured, so the ceiling was not "
                                "enforced. An unmeasured ceiling is not a ceiling: the run "
                                "stopped instead of continuing blind.")
            allow_with_note(
                "efficiency autopilot: stopped — spend could not be measured for %s. "
                "Check transcript_path and hooks/lib/spend.py." % task)
        run.set("task_spend_micro_usd", spent)
        # The per-model split as well, so /efficiency:run-report can read it from
        # the project instead of running a script it has no way to reach.
        breakdown = measure_spend(payload.get("transcript_path"), started, by_model=True)
        if isinstance(breakdown, dict):
            by = breakdown.get("by_model") or {}
            run.set("task_spend_by_model",
                    ", ".join("%s=%s" % (m, v) for m, v in by.items() if v))
            # A model the table does not price is charged at the fallback, which
            # is the most expensive row on purpose. That is the safe direction
            # for a ceiling and the wrong one for a report: it makes the cheap
            # model look like the expensive one, which is precisely the claim
            # routing exists to support. Say which ids it happened to, so the
            # figure can be read as the upper bound it is.
            unpriced = breakdown.get("unpriced_models") or []
            if unpriced:
                run.set("task_spend_unpriced_models", ", ".join(unpriced))
        run.save()
        if spent >= spend_max:
            priv.block_run(run, "%s reached its spend ceiling (%s of %s) without closing. "
                                "It needs a human opinion before more is spent on it."
                                % (task, usd(spent), usd(spend_max)))
            allow_with_note(
                "efficiency autopilot: stopped — %s spent %s against a ceiling of %s "
                "without closing. Your call on what to do with it."
                % (task, usd(spent), usd(spend_max)))

    # ── guard 2: continuations for the whole run ─────────────────────────────
    used = priv.get_int("continuations_used", 0)
    used_max = priv.get_int("continuations_max", 0)
    if used_max > 0 and used >= used_max:
        priv.block_run(run, "the run used all %d automatic continuations. Still open: %s."
                            % (used_max, ", ".join(run.open_tasks()) or "nothing"))
        allow_with_note("efficiency autopilot: stopped — %d continuations used." % used_max)

    # ── guard 3: the gate ────────────────────────────────────────────────────
    gate = run.get("gate")
    if gate:
        ok, out = run_gate(gate, project)
        if ok is None:
            priv.block_run(run, "the gate command could not be run (%s). Autonomy without a "
                                "working gate is unsupervised drift, so the run stopped." % out)
            allow_with_note("efficiency autopilot: stopped — the gate could not be run.")
        if not ok:
            tries = priv.get_int("gate_retries", 0)
            tries_max = priv.get_int("gate_retries_max", 2)
            if tries < tries_max:
                priv.set("gate_retries", tries + 1)
                priv.save()
                run.set("gate_retries", tries + 1)
                run.save()
                block("The gate is red, so this work is not done. Repair attempt %d of %d "
                      "on %s. Fix what the gate reports, then continue the run — do not "
                      "ask whether to proceed.\n\n$ %s\n%s"
                      % (tries + 1, tries_max, task, gate, out))
            priv.block_run(run, "the gate stayed red after %d repair attempts on %s.\n\n$ %s\n%s"
                                % (tries_max, task, gate, out))
            allow_with_note("efficiency autopilot: stopped — the gate is still red after "
                            "%d attempts on %s." % (tries_max, task))
        if priv.get_int("gate_retries", 0):
            priv.set("gate_retries", 0)
            priv.save()
        # Mirror unconditionally: a green gate that leaves a stale retry count in
        # the file the human reads is a small lie with no upside.
        if run.get("gate_retries") != "0":
            run.set("gate_retries", 0)
            run.save()

    # ── continue, or finish ──────────────────────────────────────────────────
    if not remaining:
        priv.set("blocked", False)
        priv.save()
        run.set("status", "DONE")
        run.set("blocked_reason", "")
        run.save()
        allow_with_note("efficiency autopilot: run complete — every task closed and the gate "
                        "green. Report it to the developer starting with the verdict on its own "
                        "line (DONE / NOT DONE / BLOCKED), then the detail. If any task was closed "
                        "whose criteria you cannot confirm, the honest verdict is NOT DONE.")

    # ── guard 4: is the run actually advancing? ──────────────────────────────
    # A task whose work is finished but whose box is never ticked looks identical
    # to a task still in progress, and the autopilot will hand it back forever.
    # Measured on this framework's own first run: 12 blocks, one task's work, no
    # box ticked, no log line.
    #
    # What counts as advancing is the set of OPEN tasks changing — deliberately
    # not `current_task`, which the model writes and which the block reason
    # below explicitly tells it to write. Until 0.18.1 the counter also required
    # `current_task` to have stayed put, so a model alternating between two open
    # tasks reset this guard on every single block and the run was bounded only
    # by continuations_max, forty blocks away. Rule 3: the leash cannot hang off
    # a field the model holds. Closing a task is the one progress signal it
    # cannot fake without actually making progress — which is why, as of 0.18.2,
    # the spend window keys off this same signature, computed once above.
    open_now = len(remaining)
    same = priv.get_int("same_task_blocks", 0)
    if priv.get("open_tasks_sig") == open_sig:
        same += 1
    else:
        same = 0
    priv.set("same_task_blocks", same)
    priv.set("open_tasks_sig", open_sig)
    priv.save()
    run.set("same_task_blocks", same)

    if same >= STALL_STOP:
        priv.block_run(run,
                 "the run stopped advancing: %d continuation(s) in a row closed no "
                 "task, and %d task(s) are still open (currently %s). Either the work "
                 "is blocked on something undeclared, or finished work is not being "
                 "closed. Both need a human to look." % (same, open_now, task))
        allow_with_note("efficiency autopilot: stopped — %d continuation(s) without a "
                        "task closing, on %s." % (same, task))

    priv.set("continuations_used", used + 1)
    priv.save()
    run.set("continuations_used", used + 1)
    run.save()

    # The block reason is the only instruction the model reliably reads on a
    # continuation — the skill's text was read once, several turns ago. So the
    # state transitions the autopilot depends on have to be spelled out here,
    # imperatively, or they do not happen.
    steps = (
        "Do this now, in order:\n"
        "1. If %(task)s's acceptance criteria are met and the gate is green, mark its "
        "line `- [x]`, append ONE line to `## Log` saying what you decided and why, and "
        "set `current_task` to the next task's id. Change nothing else in the "
        "frontmatter — the counters and the spend window belong to the hook.\n"
        "2. Then start the next task's actual work.\n"
        "3. If %(task)s is NOT finished, keep working on it — do not report progress.\n\n"
        "Do not summarise, do not describe the counters, and do not ask whether to "
        "proceed: the run was approved, and a status report costs a continuation without "
        "advancing anything."
    ) % {"task": task}

    warning = ""
    if same >= STALL_WARN:
        warning = ("\n\nATTENTION: %d continuation(s) in a row have closed no task, with "
                   "the same %d still open. If %s's work is done, what is missing is the "
                   "`- [x]` and the log line — do that first. If it cannot be finished, "
                   "say why instead of trying again; this run stops on its own after %d. "
                   "Moving `current_task` is not progress and does not reset this.\n"
                   % (same, open_now, task, STALL_STOP))

    # A ceiling someone deliberately set to zero is honoured, but not hidden. It
    # is a real decision with a real consequence — the run is unbounded in that
    # dimension — and the developer reading the transcript afterwards should not
    # have to infer it from the absence of a number.
    unbounded = []
    if priv.get_int("spend_max", 0) <= 0:
        unbounded.append("no spend ceiling")
    if priv.get_int("continuations_max", 0) <= 0:
        unbounded.append("no limit on continuations")
    note = ""
    if unbounded:
        note = ("\n\nRunning with %s — set in the run file as 0. Nothing will stop this run "
                "on that count.\n" % " and ".join(unbounded))

    block("%d task(s) still open, gate green. Current task: %s.\n\n%s%s%s\nNext open task: %s"
          % (open_now, task, steps, warning, note, remaining[0]))


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        # Import by absolute location rather than relying on the caller's cwd
        # being this directory — the whole point of --selftest is that it works
        # when invoked from anywhere.
        sys.path.insert(0, HERE)
        import selftest
        sys.exit(selftest.run())
    main()
