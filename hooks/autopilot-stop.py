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
                   leash" below. Each task's ceiling is the per-task one times
                   its tier's multiplier; in a fast run the window is a whole
                   wave, and its ceiling is the sum of its tasks'. This is the
                   verdict half only — the same ceiling is also held inside the
                   turn by autopilot-pretool.py, which refuses tool calls
                   rather than waiting for the boundary
  gate_retries_max stops repair attempts on the same red gate
  continuations_max stops the run as a whole
  the platform      overrides any Stop hook after 8 consecutive blocks WITHOUT
                    progress (measured — see docs/verified-platform-behaviour.md).
                    Any tool call resets that counter, so it never truncates a
                    run that is working; it is a free anti-stall guard.

The first four write a reason a human can read. The platform's does not — which
is why ours must fire first.

With `budget.supervisor` captured, the count-based guards — spend, continuations,
blocks without a task closing, and spend without progress — hold a checkpoint
instead of stopping: see "checkpoints" below and hooks/lib/supervisor.py.

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
import math
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

# A task line may carry two scheduling annotations: `after=T1,T2`, the tasks
# that must close first, and `files=a.py,b.py`, what it will touch. They say
# *when* a task may run, not *what* it is, and they are kept out of every
# identity this hook computes — see `statement` below.
SCHED_RE = re.compile(r"\s+(?:after|files)=\S+")
AFTER_RE = re.compile(r"(?:^|\s)after=(\S+)")
FILES_RE = re.compile(r"(?:^|\s)files=(\S+)")

# Where `parallel.max_agents` lives. Read once per run, on first sight.
POLICY_FILE = os.path.join(".efficiency", "policy.md")
# The value `templates/efficiency.md` ships. A policy written before 0.21 has
# no `parallel:` block at all, and the run skill reads that as this default too:
# the hook must size the same wave the skill dispatches, or the ceiling is wrong.
DEFAULT_MAX_AGENTS = 10

# A task's criticality tier, written after its id: `T2 [critical] ...`. It is
# kept out of every identity, like the scheduling annotations: relabelling a
# task must not be a re-plan, or `[critical]` would buy a fresh window at four
# times the ceiling. Any bracketed word in that position is a tag; one that
# names no known tier scales by 1.
TIER_TAG_RE = re.compile(r"^(\S+)\s+\[([^\]\s]+)\]")

# `budget.tier_multiplier` as `templates/efficiency.md` ships it. A policy
# written before 0.21 has no such key, and gets these, for the same reason as
# DEFAULT_MAX_AGENTS: the run skill plans with them, and the hook must agree.
DEFAULT_TIER_MULTIPLIER = {"mechanical": 0.5, "standard": 1.0,
                           "sensitive": 2.0, "critical": 4.0}

# No multiplier is believed above this. The multiplier turns a per-task figure
# into a ceiling, and nothing else bounds it: a typo of `40` for `4.0`, or
# `1000` meant as a joke, would make the ceiling effectively infinite and the
# guard decorative, with nothing said. Ten times the base still lets the most
# expensive tier do real work; anything above it is more plausibly a mistake
# than a decision, and a decision that large belongs in `task_usd` itself.
MAX_TIER_MULTIPLIER = 10.0

# The supervisor (hooks/lib/supervisor.py). A policy without `budget.supervisor`
# gets this model; `off` restores the hard stops. A project with no policy at
# all has not adopted the framework's defaults and keeps the hard stops too.
DEFAULT_SUPERVISOR = "sonnet"
SUPERVISOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\[\]-]*$")

# The idle checkpoint: this share of the window's ceiling spent since the last
# sign of progress — a task closing, or the working tree reaching a state it was
# never in before — and the supervisor is asked early, before the ceiling.
IDLE_PCT = 50

# Checkpoints in a row with no progress between them, after which the run stops
# without asking. The supervisor judges the work; with no work to judge there
# is nothing for it to see, and a run that only talks is not a run that is
# nearly done. One barren checkpoint is allowed, because reading and diagnosis
# change nothing on disk and are still work.
BARREN_STOP = 2


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
            "blocked", "blocked_reason",
            # fast mode only — see "the spend window, per wave" in main()
            "mode", "task_spend_max", "deps", "files", "max_agents", "wave",
            "wave_history",
            # the per-task ceiling's tier scaling, captured with the plan
            "order", "tiers", "multipliers",
            # the supervisor — see "checkpoints" below
            "supervisor", "base_head", "seen_states", "progress_open_sig",
            "progress_at", "progress_since_checkpoint", "barren_checkpoints",
            "checkpoints", "supervisor_window_micro", "supervisor_spend_micro",
            "continuations_tranche")

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


def statement(text, legacy=False):
    """A task line without its scheduling annotations or its tier tag.

    Both identities below hash this rather than the raw line. If they hashed
    `after=` as well, rewriting it would be a re-plan — every counter back to
    zero — and in an economy run it would also change the open-task signature
    and reopen the spend window, so a line of bookkeeping could buy a fresh
    ceiling. Rule 3 forbids both. The dependencies the hook sizes a ceiling
    from are captured once, on first sight, in the private state.

    The tier tag is dropped for the same reason: it scales the ceiling, so it
    is captured once and a relabel must not reach a fresh capture. Run files
    before 0.21 did carry the tag, so their state files hold a fingerprint that
    includes it; `legacy` computes that one, and main() migrates a state file
    that matches it rather than reading the upgrade as a re-plan.

    A line with neither is returned unchanged, so a run file written without
    them fingerprints exactly as it always did.
    """
    text = SCHED_RE.sub("", text)
    return text if legacy else TIER_TAG_RE.sub(r"\1", text, count=1)


def task_id(text):
    """The id a task line starts with: `T3` in `T3 [mechanical] ...`."""
    words = text.split(None, 1)
    return words[0].rstrip(":.)") if words else ""


def fingerprint(run, legacy=False):
    """Identify a run by its task statements, ignoring the checkbox marks."""
    statements = "\n".join(statement(text, legacy) for _mark, text in run.tasks())
    return hashlib.sha256(statements.encode("utf-8", "replace")).hexdigest()


def known_run(priv, run):
    """Has the hook already captured this run, under either fingerprint rule?"""
    return priv.get("fingerprint") in (fingerprint(run), fingerprint(run, legacy=True))


def open_signature(open_tasks, legacy=False):
    """Identify the *state* of a run: which of its tasks are still open.

    This is the only progress signal the model cannot move without actually
    making progress — ticking a box is a claim it has to live with, where
    `current_task` is a line the block reason tells it to rewrite every time.
    Both the spend window and the stall guard key off this, for that reason.
    """
    joined = "\n".join(statement(t, legacy) for t in open_tasks)
    return hashlib.sha256(joined.encode("utf-8", "replace")).hexdigest()


def run_mode(run):
    """`fast` only when the run file says so; anything else is today's economy."""
    return "fast" if run.get("mode").strip().lower() == "fast" else "economy"


def task_deps(run):
    """{id: [ids it waits for]}, as the run file declares them right now."""
    deps = {}
    for _mark, text in run.tasks():
        found = AFTER_RE.search(text)
        deps[task_id(text)] = [d for d in found.group(1).split(",") if d] if found else []
    return deps


def task_files(run):
    """{id: [paths or globs]}, or None for a task that declared none."""
    files = {}
    for _mark, text in run.tasks():
        found = FILES_RE.search(text)
        paths = [f for f in found.group(1).split(",") if f] if found else []
        files[task_id(text)] = paths or None
    return files


def policy_front(project):
    """The policy's frontmatter lines, or None when there is none to read."""
    try:
        text = open(os.path.join(project, POLICY_FILE), errors="replace").read()
    except OSError:
        return None
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None
    return lines[1:end]


def policy_max_agents(project):
    """`parallel.max_agents` from the project's policy.

    A policy without a `parallel:` block, or a block without the key, predates
    it and gets the shipped default. A policy that is missing, unreadable, or
    holds a value that is not a whole number gets 1 — the safe reading, not a
    guess: every wave becomes one task wide and the ceiling is economy's.
    """
    front = policy_front(project)
    if front is None:
        return 1
    try:
        start = next(i for i, l in enumerate(front) if re.match(r"parallel:\s*(#.*)?$", l))
    except StopIteration:
        return DEFAULT_MAX_AGENTS
    for line in front[start + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            break              # the block ended without naming the key
        key, _, value = line.strip().partition(":")
        if key.strip() == "max_agents":
            value = value.split("#", 1)[0].strip()
            return max(1, int(value)) if value.isdigit() else 1
    return DEFAULT_MAX_AGENTS


def sane_multiplier(value):
    """A multiplier as a number in (0, MAX_TIER_MULTIPLIER], or 1.

    Anything that is not a positive finite number — text, zero, a negative, a
    NaN, a boolean — scales by 1, which is the ceiling the plan would have had
    without tiers at all. Used on the policy and again on the captured state,
    which a person can edit.
    """
    if isinstance(value, bool):
        return 1.0
    try:
        m = float(value)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(m) or m <= 0:
        return 1.0
    return min(m, MAX_TIER_MULTIPLIER)


def _multiplier_entries(front, start, indent):
    """`key: value` pairs of a `tier_multiplier:` written as an indented block."""
    entries = []
    for line in front[start + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip()) <= indent:
            break
        entries.append(line.split("#", 1)[0].strip())
    return entries


def policy_tier_multipliers(project):
    """`budget.tier_multiplier` from the project's policy, one number per tier.

    A policy without the key — no `budget:` block, or a block that does not
    name it — predates it and gets DEFAULT_TIER_MULTIPLIER. A policy that is
    missing, has no readable frontmatter, or writes the key in a shape that
    cannot be read gets 1 for every tier: today's flat ceiling, not a guess.
    A tier the map does not name, or names with something that is not a
    positive number, gets 1 on its own. Every value is capped.
    """
    flat = dict((t, 1.0) for t in DEFAULT_TIER_MULTIPLIER)
    front = policy_front(project)
    if front is None:
        return flat
    try:
        start = next(i for i, l in enumerate(front) if re.match(r"budget:\s*(#.*)?$", l))
    except StopIteration:
        return dict(DEFAULT_TIER_MULTIPLIER)
    for i in range(start + 1, len(front)):
        line = front[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            break              # the block ended without naming the key
        key, _, value = line.strip().partition(":")
        if key.strip() != "tier_multiplier":
            continue
        value = value.split("#", 1)[0].strip()
        if not value:
            entries = _multiplier_entries(front, i, len(line) - len(line.lstrip()))
        elif value.startswith("{") and value.endswith("}"):
            entries = [e.strip() for e in value[1:-1].split(",") if e.strip()]
        else:
            return flat
        found = {}
        for entry in entries:
            if ":" not in entry:
                return flat
            tier, _, number = entry.partition(":")
            found[unquote(tier.strip()).lower()] = unquote(number.strip())
        if not found:
            return flat
        return dict((t, sane_multiplier(found[t]) if t in found else 1.0) for t in flat)
    return dict(DEFAULT_TIER_MULTIPLIER)


def policy_supervisor(project):
    """`budget.supervisor`: the model that holds the checkpoints, or "" for off.

    No policy file reads as off — the hard stops this hook has always had. A
    policy that does not name the key predates it and gets DEFAULT_SUPERVISOR.
    A value that does not look like a model name is read as off, not as the
    default: a typo must not be what decides to keep spending.
    """
    front = policy_front(project)
    if front is None:
        return ""
    try:
        start = next(i for i, l in enumerate(front) if re.match(r"budget:\s*(#.*)?$", l))
    except StopIteration:
        return DEFAULT_SUPERVISOR
    for line in front[start + 1:]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            break
        key, _, value = line.strip().partition(":")
        if key.strip() != "supervisor":
            continue
        value = unquote(value.split("#", 1)[0].strip())
        if value.lower() in ("", "off", "false", "no", "none"):
            return ""
        return value if SUPERVISOR_RE.match(value) else ""
    return DEFAULT_SUPERVISOR


def task_tiers(run):
    """{id: tier} for every task, "" for a task line with no tier tag."""
    tiers = {}
    for _mark, text in run.tasks():
        found = TIER_TAG_RE.match(text)
        tiers[task_id(text)] = found.group(2).lower() if found else ""
    return tiers


def task_plan(run, project):
    """Everything a window's ceiling is computed from, to be captured once."""
    return {"deps": task_deps(run), "files": task_files(run),
            "max_agents": policy_max_agents(project),
            "order": [task_id(text) for _mark, text in run.tasks()],
            "tiers": task_tiers(run),
            "multipliers": policy_tier_multipliers(project)}


def tier_scale(plan, tid):
    """The captured multiplier of one task's captured tier.

    Read from what was captured, never from the run file or the policy, so
    relabelling a task `[critical]` or raising a multiplier mid-run moves
    nothing. A state without tiers — written before they existed, or edited
    into another shape — scales every task by 1, which is today's ceiling.
    """
    tiers = plan.get("tiers") if isinstance(plan.get("tiers"), dict) else {}
    mults = plan.get("multipliers") if isinstance(plan.get("multipliers"), dict) else {}
    tier = tiers.get(tid)
    if not isinstance(tier, str) or tier not in mults:
        return 1.0
    return sane_multiplier(mults.get(tier))


def first_open(run, plan):
    """An economy window's task: the first open one, in the captured order."""
    order = plan.get("order")
    if not isinstance(order, list):
        order = [task_id(text) for _mark, text in run.tasks()]
    closed = closed_ids(run)
    for tid in order:
        if str(tid) not in closed:
            return [str(tid)]
    return []


def closed_ids(run):
    return {task_id(text) for mark, text in run.tasks() if mark == "x"}


WILDCARDS = "*?[{"


def _stem(pattern):
    """The literal part of a path or glob, before its first wildcard.

    `{` counts although fnmatch does not know it: `src/{a,b}.py` is a brace
    pattern to every shell and glob library a task is likely to be written for.
    """
    cut = min([i for i in (pattern.find(c) for c in WILDCARDS) if i >= 0] or [len(pattern)])
    return pattern[:cut]


def _norm(path):
    """One spelling per path: `./src//A.py` and `src/a.py` are the same file.

    Lower-cased because the default macOS filesystem is case-insensitive, and
    a false "same" only splits a wave.
    """
    path = os.path.normpath(str(path).strip().replace("\\", "/"))
    while path.startswith("./"):
        path = path[2:]
    return path.lower()


def _pair_overlaps(x, y):
    import fnmatch
    x, y = _norm(x), _norm(y)
    if x.startswith("/") != y.startswith("/"):
        # One absolute, one relative, and no project root to resolve against.
        # The same file only if the absolute one ends with the relative one;
        # with a wildcard or a `..` in sight, nobody can tell, so: overlap.
        absolute, relative = (x, y) if x.startswith("/") else (y, x)
        if relative.startswith("..") or any(c in x + y for c in WILDCARDS):
            return True
        return absolute.endswith("/" + relative)
    if x == y or fnmatch.fnmatch(x, y) or fnmatch.fnmatch(y, x):
        return True
    sx, sy = _stem(x), _stem(y)
    if (sx != x and y.startswith(sx)) or (sy != y and x.startswith(sy)):
        return True
    return x.startswith(y.rstrip("/") + "/") or y.startswith(x.rstrip("/") + "/")


def files_overlap(a, b):
    """Could two `files=` lists touch the same path? Says yes when unsure.

    Globs are compared by matching each against the other and by the literal
    stem before their first wildcard, so `src/**` and `src/a.py` overlap and so
    do `src/a*` and `src/ab*`. A false "yes" splits a wave in two, which costs
    time and narrows the ceiling; a false "no" would widen it.
    """
    return any(_pair_overlaps(x, y) for x in a for y in b)


def current_wave(run, plan):
    """The wave the run skill would dispatch next, by the same three rules.

    The open tasks whose `after=` dependencies are all closed; then, in list
    order, a task joins only if its `files=` overlap no task already in, and a
    task with no `files=` runs alone; then no more than `max_agents`.

    A dependency naming a task that does not exist never closes, so its task
    never joins a wave. That, like every other doubt here, leaves the ceiling
    narrower than intended, which is the safe direction to be wrong in.
    """
    # The plan normally comes from the hook's own state file, which a person can
    # edit. Any shape other than the one written reads in the narrow direction:
    # a dependency that is not a list never closes, a `files=` that is not a
    # list touches everything.
    deps = plan.get("deps") if isinstance(plan.get("deps"), dict) else {}
    files = plan.get("files") if isinstance(plan.get("files"), dict) else {}

    def waits_for(tid):
        d = deps.get(tid)
        if d is None:
            return []
        return [str(x) for x in d] if isinstance(d, list) else [None]

    def touches(tid):
        f = files.get(tid)
        return [str(x) for x in f] if isinstance(f, list) and f else None
    try:
        cap = max(1, int(plan.get("max_agents", 1)))
    except (TypeError, ValueError):
        cap = 1
    closed = closed_ids(run)
    wave = []
    for mark, text in run.tasks():
        tid = task_id(text)
        if mark == "x" or tid in wave:
            continue
        if not all(d in closed for d in waits_for(tid)):
            continue
        mine = touches(tid)
        if not mine:
            if not wave:
                wave.append(tid)
                break          # touches everything: it runs alone
            continue           # it will lead a wave of its own later
        if any(not touches(o) or files_overlap(mine, touches(o)) for o in wave):
            continue
        wave.append(tid)
        if len(wave) >= cap:
            break
    return wave


def window_ceiling(per_task, mode, ids, plan):
    """The spend ceiling of one window.

    Each task's ceiling is the per-task figure times its tier's multiplier. An
    economy window holds one task, the first of `ids`; a fast window holds the
    whole wave and its ceiling is the sum of its tasks'. With no task to price
    — a wave nothing is ready for — it is the per-task figure, unscaled.
    """
    if mode != "fast":
        ids = ids[:1]
    if not ids:
        return per_task
    return sum(int(round(per_task * tier_scale(plan, tid))) for tid in ids)


def window_ids(run, plan, mode):
    """The tasks the window open now is spent on: a wave, or one task."""
    return current_wave(run, plan) if mode == "fast" else first_open(run, plan)


def first_window_ceiling(run, project):
    """The ceiling of a run's first window, before this hook has captured one.

    For autopilot-pretool.py, which bounds the first turn from the run file
    because nothing has been captured yet. In a fast run that turn dispatches
    the whole first wave, so the per-task figure alone would refuse it early.
    The same function sizes the window main() captures, so the two agree.
    """
    mode = run_mode(run)
    plan = task_plan(run, project)
    return window_ceiling(run.get_int("task_spend_max_micro_usd", 0), mode,
                          window_ids(run, plan, mode), plan)


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


# ── checkpoints ──────────────────────────────────────────────────────────────
#
# Four guards used to stop a run on a count: the spend ceiling, the
# continuations ceiling, and the stall guard — plus a fourth, new with them,
# that fires on spend since the last sign of progress. With a supervisor
# captured, each of them holds a checkpoint instead: a second model reads the
# work and says whether it is converging. If it is, the guard grants one more
# tranche of the same size and the run goes on; if not, the run stops with the
# supervisor's reason. There is no cap on tranches, deliberately — a run that
# keeps producing keeps going — so what bounds a run is the verdict, and two
# conditions the verdict cannot override:
#
#   * BARREN_STOP checkpoints in a row with no progress between them stop the
#     run without asking. Progress is measured here, not reported: a task
#     closing, or the working tree reaching a state it has never been in.
#   * Every failure of the supervisor — not on PATH, timed out, no verdict, no
#     cost — stops the run. A checkpoint nobody answered is not a checkpoint.
#
# What still stops a run outright, by design: the gate red after its retries,
# spend that cannot be measured, and the supervisor's own failures.

_SUPERVISOR = None
_GRANTED = None     # one verdict per invocation: several guards may ask at once
_NOTES = []         # what the checkpoints decided, for the block reason


def load_supervisor():
    global _SUPERVISOR
    if _SUPERVISOR is None:
        sys.path.insert(0, os.path.join(HERE, "lib"))
        import supervisor
        _SUPERVISOR = supervisor
    return _SUPERVISOR


def note_progress(priv, project, open_sig):
    """Record whether the work moved since the last invocation.

    A task closing counts, and so does the working tree reaching a state never
    seen in this run — never seen, not merely different, so an edit undone and
    redone is not progress twice. Only with a supervisor captured: without one,
    nothing reads it, and the git calls are not free.
    """
    if not priv.get("supervisor"):
        return
    progressed = False
    if priv.get("progress_open_sig") != open_sig:
        priv.set("progress_open_sig", open_sig)
        progressed = True
    sig = load_supervisor().state_signature(project)
    if sig:
        seen = priv.get("seen_states")
        seen = [x for x in seen if isinstance(x, str)] if isinstance(seen, list) else []
        if sig not in seen:
            seen.append(sig)
            priv.set("seen_states", seen[-500:])
            progressed = True
    if progressed:
        priv.set("progress_at", iso_now())
        priv.set("progress_since_checkpoint", True)
    priv.save()


def checkpoint_stop(priv, run, kind, reason):
    priv.block_run(run, "checkpoint (%s): %s" % (kind, reason))
    allow_with_note("efficiency autopilot: stopped at a checkpoint (%s) — %s" % (kind, reason))


def checkpoint(priv, run, project, payload, kind, situation):
    """Ask the supervisor whether the run may go on. Returns only if it may.

    None when no supervisor was captured: the caller stops the run exactly as
    it always has. Otherwise it either returns the verdict, and the caller
    grants its tranche, or it stops the run and does not return.
    """
    global _GRANTED
    model = priv.get("supervisor")
    if not model:
        return None
    if _GRANTED is not None:
        _NOTES.append("%s: covered by the verdict above" % kind)
        return _GRANTED
    if not run.open_tasks():
        # Every task is closed: the turn is ending, nothing further is asked
        # for, and there is no work left for a verdict to be about. Found by
        # scripts/probes/supervisor-checkpoint.sh — a run that finished all its
        # tasks inside its first turn was stopped as "looping" for having
        # nothing left to do.
        _GRANTED = {"verdict": "converging", "why": "no task is open"}
        return _GRANTED

    progressed = bool(priv.get("progress_since_checkpoint"))
    barren = 0 if progressed else priv.get_int("barren_checkpoints", 0) + 1
    priv.set("progress_since_checkpoint", False)
    priv.set("barren_checkpoints", barren)
    priv.save()
    history = priv.get("checkpoints")
    history = [h for h in history if isinstance(h, dict)] if isinstance(history, list) else []

    if barren >= BARREN_STOP:
        checkpoint_stop(priv, run, kind,
                        "%s. %d checkpoints in a row with no task closed and no new change "
                        "in the working tree, so there was no work for the supervisor to "
                        "judge. It needs a human to look." % (situation, barren))

    lib = load_supervisor()
    tasks = run.tasks()
    question = lib.prompt(
        kind, situation,
        [t for mark, t in tasks if mark != "x"], [t for mark, t in tasks if mark == "x"],
        lib.diff_evidence(project, priv.get("base_head") or ""),
        # Since the previous checkpoint, not since the last progress: progress
        # noted at the top of this very invocation would otherwise move the
        # start past the turn being judged, and the supervisor would see none
        # of the calls it is asked about. Measured in the live probe.
        lib.tool_calls(payload.get("transcript_path"),
                       history[-1].get("at") if history else priv.get("task_started_at")),
        [{"kind": h.get("kind"), "verdict": h.get("verdict"), "why": h.get("why")}
         for h in history[-10:]])
    answer = lib.ask(model, question)

    cost = answer.get("cost_micro")
    if cost is None:
        checkpoint_stop(priv, run, kind,
                        "%s. The supervisor (%s) gave no cost the run could be charged "
                        "(%s), and a checkpoint whose spend cannot be measured is a blind "
                        "guard." % (situation, model, answer.get("error") or "no reply"))
    priv.set("supervisor_window_micro", priv.get_int("supervisor_window_micro", 0) + cost)
    priv.set("supervisor_spend_micro", priv.get_int("supervisor_spend_micro", 0) + cost)
    run.set("supervisor_spend_micro_usd", priv.get_int("supervisor_spend_micro", 0))

    if answer.get("error"):
        priv.save()
        checkpoint_stop(priv, run, kind, "%s. The supervisor (%s) %s, so nobody judged the "
                                         "work." % (situation, model, answer["error"]))

    history.append({"at": iso_now(), "kind": kind, "verdict": answer["verdict"],
                    "why": answer["why"], "cost_micro": cost, "progressed": progressed})
    priv.set("checkpoints", history[-100:])
    priv.save()
    run.set("supervisor_checkpoints", len(history))
    run.set("supervisor_last", "%s: %s — %s" % (kind, answer["verdict"], answer["why"]))
    run.save()

    if answer["verdict"] != "converging":
        checkpoint_stop(priv, run, kind, "%s. The supervisor judged the run %s: %s"
                                         % (situation, answer["verdict"], answer["why"]))
    _GRANTED = answer
    _NOTES.append("%s: converging — %s" % (kind, answer["why"]))
    return answer


def window_tranche(priv, run):
    """One more window's worth of spend: the ceiling the open window started with."""
    per_task = priv.get_int("task_spend_max", priv.get_int("spend_max", 0))
    if priv.get("mode") == "fast":
        wave = priv.get("wave")
        wave = [str(i) for i in wave] if isinstance(wave, list) else []
        return window_ceiling(per_task, "fast", wave, priv.data)
    return window_ceiling(per_task, "economy", first_open(run, priv.data), priv.data)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    # The supervisor's own session. It runs in an empty directory and would find
    # no run here anyway; this says so without looking.
    if os.environ.get("EFFICIENCY_SUPERVISOR"):
        allow_silently()
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

    # A state file written before 0.21 fingerprinted the tier tags too. Same
    # run, older rule: carry its counters across rather than read the upgrade
    # as a re-plan. It captured no tiers, so every task keeps scaling by 1 —
    # exactly the ceiling it was approved under.
    if priv.get("fingerprint") != now and priv.get("fingerprint") == fingerprint(run, legacy=True):
        priv.set("fingerprint", now)
        for key, rule in (("task_key", run.open_tasks()), ("open_tasks_sig", run.open_tasks())):
            if priv.get(key) == open_signature(rule, legacy=True):
                priv.set(key, open_signature(rule))
        priv.save()

    if priv.get("fingerprint") != now:
        # A different task list: a fresh run, or one that was re-planned. This is
        # the only legitimate way counters go back to zero, and it cannot happen
        # by editing the frontmatter — only by changing the work itself.
        #
        # The mode, the `after=` and `files=` of every task, and the policy's
        # `parallel.max_agents` are captured here with the ceilings, and for the
        # same reason: each of them sizes the spend ceiling of a fast run, so each
        # is read once, when the developer has just approved the plan, and never
        # again. Flipping `mode:` to fast, deleting an `after=`, splitting a
        # `files=` or raising `max_agents` mid-run changes nothing the hook reads.
        # Every task's tier, and the policy's multiplier per tier, are captured
        # the same way: they scale every window's ceiling, in either mode.
        mode = run_mode(run)
        plan = task_plan(run, project)
        per_task = run.get_int("task_spend_max_micro_usd", 0)
        wave = current_wave(run, plan) if mode == "fast" else []
        priv.data = {
            "fingerprint": now,
            "continuations_used": 0,
            "continuations_max": run.get_int("continuations_max", 0),
            "gate_retries": 0,
            "gate_retries_max": run.get_int("gate_retries_max", 2),
            # `spend_max` is the ceiling of the window open NOW, which is what
            # autopilot-pretool.py reads; `task_spend_max` is the approved
            # per-task figure it is computed from. In economy they are equal.
            "spend_max": window_ceiling(per_task, mode, window_ids(run, plan, mode), plan),
            "task_spend_max": per_task,
            "mode": mode,
            "deps": plan["deps"],
            "files": plan["files"],
            "max_agents": plan["max_agents"],
            "order": plan["order"],
            "tiers": plan["tiers"],
            "multipliers": plan["multipliers"],
            "wave": wave,
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
        # The supervisor is captured with the ceilings, like everything else a
        # checkpoint's outcome depends on: switching it off mid-run only makes
        # the run stricter, but pointing it at a weaker model would not.
        model = policy_supervisor(project)
        if model:
            lib = load_supervisor()
            priv.data.update({
                "supervisor": model,
                "base_head": lib.head(project),
                "seen_states": [s for s in [lib.state_signature(project)] if s],
                "progress_open_sig": open_signature(run.open_tasks()),
                "progress_at": priv.data["task_started_at"],
                "progress_since_checkpoint": False,
                "barren_checkpoints": 0,
                "checkpoints": [],
                "supervisor_window_micro": 0,
                "supervisor_spend_micro": 0,
                "continuations_tranche": priv.data["continuations_max"],
            })
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
    #
    # ── the spend window, per wave ──────────────────────────────────────────
    # A fast run works a whole wave at once, one subagent per task, and every
    # subagent's spend lands in this one session's transcript. Keyed per task,
    # the window was wrong twice over: N tasks' spend measured against one
    # task's ceiling, and each closure reopening the window and erasing the
    # spend of the wave's tasks still running.
    #
    # So in fast mode the window belongs to the wave: the ids that were ready
    # when it opened, held in the private state, never re-derived from the run
    # file while any of them is open. It closes only when all of them have, and
    # its ceiling is the sum of its tasks' tier-scaled ceilings. The wave is the
    # one the run skill dispatches — dependencies, then file conflicts, then
    # `max_agents` — computed from what was captured on first sight. A model
    # that widens it mid-flight, by editing `after=`, `files=` or the policy, or
    # by adding a task, moves nothing: the edits are ignored, and a new task is
    # a re-plan, which is the existing, visible way to start over.
    #
    # `current_task` is a label here as in economy: the run skill points it at
    # the wave's first id, and nothing below keys on it.
    #
    # A state file from before fast mode existed has no `mode`, and reads as
    # economy: exactly the behaviour it was written under.
    spent_on = task
    if priv.get("mode") == "fast":
        # Hand-edited into another shape, this state reads as an empty wave,
        # which reopens the window at the next one — a report, not a crash.
        wave = priv.get("wave")
        wave = [str(i) for i in wave] if isinstance(wave, list) else []
        if all(i in closed_ids(run) for i in wave):
            following = current_wave(run, priv.data)
            if following != wave:
                # What the closing wave cost, measured here — the one moment its
                # window is known to be complete — so run-report reads a figure
                # this hook wrote rather than one the model copied. None when it
                # cannot be measured; the guard below is what fails closed.
                if wave:
                    history = priv.get("wave_history")
                    history = [h for h in history if isinstance(h, dict)] \
                        if isinstance(history, list) else []
                    history.append({"wave": wave,
                                    "started_at": priv.get("task_started_at"),
                                    "spent": measure_spend(payload.get("transcript_path"),
                                                           priv.get("task_started_at"))})
                    priv.set("wave_history", history)
                    run.set("wave_spend_micro_usd", "; ".join(
                        "%s=%s" % (",".join(str(i) for i in h.get("wave"))
                                   if isinstance(h.get("wave"), list) else "?",
                                   "unmeasured" if h.get("spent") is None else h["spent"])
                        for h in history))
                    run.save()
                wave = following
                priv.set("wave", wave)
                priv.set("spend_max", window_ceiling(
                    priv.get_int("task_spend_max", priv.get_int("spend_max", 0)),
                    "fast", wave, priv.data))
                priv.set("task_started_at", iso_now())
                priv.set("supervisor_window_micro", 0)
                priv.save()
        spent_on = "the wave %s" % (", ".join(wave) or "(no task ready)")
    elif priv.get("task_key") != open_sig:
        # A task closed, so the window moves to the next one in captured order,
        # at that task's tier. A state from before tiers has no per-task figure
        # of its own: its ceiling is the per-task one, so record that first.
        if "task_spend_max" not in priv.data:
            priv.set("task_spend_max", priv.get_int("spend_max", 0))
        priv.set("spend_max", window_ceiling(priv.get_int("task_spend_max", 0), "economy",
                                             first_open(run, priv.data), priv.data))
        priv.set("task_key", open_sig)
        priv.set("task_started_at", iso_now())
        priv.set("supervisor_window_micro", 0)
        priv.save()

    note_progress(priv, project, open_sig)

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
                "Check transcript_path and hooks/lib/spend.py." % spent_on)
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
        # What the supervisor cost in this window is spend too, and spend.py
        # cannot see it (§ 22): the hook adds what it was charged.
        spent += priv.get_int("supervisor_window_micro", 0)
        if spent >= spend_max:
            situation = ("%s reached its spend ceiling (%s of %s) without closing"
                         % (spent_on, usd(spent), usd(spend_max)))
            if checkpoint(priv, run, project, payload, "spend ceiling", situation) is None:
                priv.block_run(run, "%s. It needs a human opinion before more is spent on it."
                                    % situation)
                allow_with_note(
                    "efficiency autopilot: stopped — %s spent %s against a ceiling of %s "
                    "without closing. Your call on what to do with it."
                    % (spent_on, usd(spent), usd(spend_max)))
            # One more tranche, counted from what is already spent: a single
            # long turn can overshoot the ceiling, and the next window must not
            # start in debt.
            spend_max = spent + window_tranche(priv, run)
            priv.set("spend_max", spend_max)
            priv.save()
        elif priv.get("supervisor"):
            # ── the idle checkpoint ───────────────────────────────────────────
            # Spend since the last sign of progress, held against a share of
            # the window. It is the one that saves money: a run going nowhere
            # is stopped halfway to the ceiling instead of at it.
            since = priv.get("progress_at") or started
            idle = spent if since <= started else measure_spend(
                payload.get("transcript_path"), since)
            if idle is None:
                priv.block_run(run, "spend since the last progress could not be measured, so "
                                    "the idle checkpoint was not enforced. The run stopped "
                                    "instead of continuing blind.")
                allow_with_note("efficiency autopilot: stopped — spend could not be measured "
                                "for %s." % spent_on)
            threshold = window_tranche(priv, run) * IDLE_PCT // 100
            if threshold > 0 and idle >= threshold:
                checkpoint(priv, run, project, payload, "spend without progress",
                           "%s spent %s since the last task closed or the working tree last "
                           "changed, %d%% of its window" % (spent_on, usd(idle), IDLE_PCT))
                priv.set("progress_at", iso_now())
                priv.save()

    # ── guard 2: continuations for the whole run ─────────────────────────────
    used = priv.get_int("continuations_used", 0)
    used_max = priv.get_int("continuations_max", 0)
    if used_max > 0 and used >= used_max:
        situation = ("the run used all %d automatic continuations. Still open: %s"
                     % (used_max, ", ".join(run.open_tasks()) or "nothing"))
        if checkpoint(priv, run, project, payload, "continuations", situation) is None:
            priv.block_run(run, situation + ".")
            allow_with_note("efficiency autopilot: stopped — %d continuations used." % used_max)
        used_max = used + max(1, priv.get_int("continuations_tranche", used_max))
        priv.set("continuations_max", used_max)
        priv.save()
        run.set("continuations_max", used_max)
        run.save()

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
        situation = ("%d continuation(s) in a row closed no task, and %d task(s) are still "
                     "open (currently %s)" % (same, open_now, task))
        if checkpoint(priv, run, project, payload, "no task closing", situation) is None:
            priv.block_run(run,
                     "the run stopped advancing: %s. Either the work is blocked on something "
                     "undeclared, or finished work is not being closed. Both need a human to "
                     "look." % situation)
            allow_with_note("efficiency autopilot: stopped — %d continuation(s) without a "
                            "task closing, on %s." % (same, task))
        same = 0
        priv.set("same_task_blocks", 0)
        priv.save()
        run.set("same_task_blocks", 0)

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
        if priv.get("supervisor"):
            warning = warning.replace(
                "this run stops on its own after %d" % STALL_STOP,
                "after %d a supervisor reads the work and decides whether the run goes on"
                % STALL_STOP)

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

    # A checkpoint that let the run go on is said, not hidden: the developer
    # reading the transcript later should see every tranche and why.
    granted = ""
    if _NOTES:
        granted = ("\n\nSupervisor checkpoint — the run continues. %s\n"
                   % " · ".join(_NOTES))

    block("%d task(s) still open, gate green. Current task: %s.\n\n%s%s%s%s\nNext open task: %s"
          % (open_now, task, steps, warning, note, granted, remaining[0]))


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        # Import by absolute location rather than relying on the caller's cwd
        # being this directory — the whole point of --selftest is that it works
        # when invoked from anywhere.
        sys.path.insert(0, HERE)
        import selftest
        sys.exit(selftest.run())
    main()
