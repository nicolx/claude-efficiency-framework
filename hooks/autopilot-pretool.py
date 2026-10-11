#!/usr/bin/env python3
"""autopilot-pretool.py — stop the spending inside a turn, not only at its end.

Wired as a `PreToolUse` hook. It is the second half of the spend ceiling: the
`Stop` hook owns the verdict, this one owns the bleeding.

── Why it exists ────────────────────────────────────────────────────────────

Until 0.19.0 the ceiling was read exactly once per turn, as the turn ended.
Inside a turn there was no ceiling at all — and a turn has no length limit, so
a task that kept calling tools could spend any amount before anything looked.
The README called that a limit; it is better described as the guard being
absent for the entire interval that matters.

── What was measured before it was written ──────────────────────────────────

Three facts, all in docs/verified-platform-behaviour.md § 17, none of them
documented by the platform and none safe to assume:

  * the transcript is written AS the turn runs, so spend is measurable mid-turn
    (scripts/probes/midturn-transcript.sh);
  * a PreToolUse denial is honoured — the tool does not run — and the turn then
    ends on its own rather than hammering at the refusal
    (scripts/probes/midturn-deny.sh);
  * a subagent's own tool calls reach this hook carrying the PARENT session's
    transcript_path, so delegated work — the expensive half of a routed run —
    is covered by the same measurement with no special handling
    (scripts/probes/midturn-subagent.sh).

── Rules it obeys, and the one it deliberately inverts ──────────────────────

NEVER FATAL FOR ITS OWN DEFECTS, as everywhere else: any internal failure
permits the call and says nothing.

IT FAILS **OPEN**, WHERE THE STOP HOOK FAILS CLOSED. This is the deliberate
inversion, and it is not a softening of rule 2. Stopping a run at a turn
boundary ends the turn; refusing every tool call mid-turn does not — it leaves
the developer in a session where nothing works, which is precisely what rule 2
forbids. So when spend cannot be measured here, the call is permitted and the
Stop hook does what it has always done: stop the run, fail closed, at the
boundary. Nothing that was enforced before is enforced less.

THE MODEL DOES NOT HOLD ITS OWN LEASH. This hook writes no counter and no
ceiling. It reads the private state the Stop hook owns and never writes to it —
deliberately, because a PreToolUse hook runs concurrently with itself (several
tool calls can be in flight) and a careless write here could clobber counters
that belong to the other hook. Its only writes go to a throttle cache of its
own, whose worst possible corruption is one redundant measurement or one
postponed by `CACHE_TTL_S` seconds.
"""

import importlib.util
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))

RUN_FILE = os.path.join(".efficiency", "run.md")
STATE_FILE = os.path.join(".efficiency", "autopilot.json")

# This hook's own scratch file. Separate from autopilot.json on purpose — see
# the module docstring. Nothing but this hook reads or writes it, and losing it
# entirely costs one extra measurement.
CACHE_FILE = os.path.join(".efficiency", "midturn-cache.json")

# How long a measurement may be reused before another is taken. Measuring means
# parsing the whole transcript in a subprocess, and this hook runs on EVERY tool
# call, so measuring every time would put that cost in front of every action the
# model takes. The number is the real ceiling resolution: between two checks a
# run can overshoot by whatever it manages to spend in this many seconds, which
# at a handful of seconds is a round trip or two — against the unbounded
# overshoot of a whole turn that this replaces.
CACHE_TTL_S = 5

# Being over the ceiling is never cached away: once the cached figure is at or
# above the ceiling the call is refused without re-measuring, so the expensive
# path runs while the run is healthy and the cheap path while it is stopping.


def _load_stop_hook():
    """The Stop hook, imported as a library.

    Its name has a hyphen, so it cannot be imported by name. It is imported
    rather than copied because every fact here — how a run file parses, what the
    private state holds, how spend is measured, which window it is measured over
    — must have exactly one definition. Two copies of the spend window would
    disagree within one release, and the half that disagreed would be this one,
    which nobody reads.
    """
    spec = importlib.util.spec_from_file_location(
        "autopilot_stop", os.path.join(HERE, "autopilot-stop.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def permit():
    """Say nothing. Silence is 'no opinion', which lets the normal rules decide."""
    sys.exit(0)


def refuse(reason):
    # The measured contract for PreToolUse (§ 17): hookSpecificOutput on stdout,
    # exit 0. Only the keys that were measured are emitted — an unrecognised key
    # risks the whole decision being discarded, and a discarded refusal is a
    # ceiling that silently is not one.
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason}}) + "\n")
    sys.exit(0)


def read_cache(path, window, size):
    """The last measurement, if it still describes this window and this file.

    Returns None whenever anything about it fails to line up, which simply means
    'measure again'. A clock reading from the future is rejected rather than
    trusted: the same shape of bug — a future timestamp emptying a window and
    silencing a guard for the rest of a run — has already been found once in this
    framework, in `task_started_at`.
    """
    try:
        with open(path, errors="replace") as fh:
            cache = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(cache, dict):
        return None
    if cache.get("window") != window or cache.get("size") != size:
        return None
    try:
        at = float(cache.get("at"))
        spent = int(cache.get("spent"))
    except (TypeError, ValueError):
        return None
    now = time.time()
    if at > now or now - at > CACHE_TTL_S:
        return None
    return spent


def write_cache(path, window, size, spent):
    """Best effort: a cache that cannot be written costs a measurement, nothing more."""
    try:
        d = os.path.dirname(path) or "."
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".midturn-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump({"window": window, "size": size,
                           "spent": spent, "at": time.time()}, fh)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except OSError:
        pass


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        permit()

    project = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or ""
    if not project or not os.path.isdir(project):
        permit()
    project = os.path.realpath(project)
    run_path = os.path.join(project, RUN_FILE)

    # No run, no ceiling, nothing to do. This is the overwhelmingly common case —
    # every tool call of every session in every project that merely has the plugin
    # installed lands here — so it must cost one stat() and nothing else. In
    # particular the Stop hook is not imported until after this test.
    if not os.path.exists(run_path):
        permit()

    if os.path.dirname(os.path.realpath(run_path)) != os.path.join(project, ".efficiency"):
        permit()   # a run file resolving outside the project is the Stop hook's to report

    stop = _load_stop_hook()

    try:
        run = stop.Run(run_path)
    except (OSError, ValueError):
        permit()

    if run.get("status").upper() != "ACTIVE":
        permit()

    priv = stop.Private(os.path.join(project, STATE_FILE))
    if priv.get("blocked"):
        # Already stopped. The developer may well be driving by hand now, and
        # refusing their tool calls would be this hook enforcing a verdict that
        # has already been delivered.
        permit()

    # Whose ceiling to believe. Once the Stop hook has seen this run it owns the
    # number, and the run file's copy is ignored however it has been edited —
    # that is rule 3. Before it has seen it, there is no captured number to
    # defend and the run file holds what the developer approved minutes ago, so
    # the first turn of a run is bounded too. It is the longest turn of most
    # runs, and leaving it out would have left the gap this hook exists to close.
    fresh = priv.get("fingerprint") != stop.fingerprint(run)
    if fresh:
        spend_max = run.get_int("task_spend_max_micro_usd", 0)
        window = stop.window_start(run)
    else:
        spend_max = priv.get_int("spend_max", 0)
        window = priv.get("task_started_at")

    if spend_max <= 0 or not window:
        permit()   # an explicit 0 is a decision, announced each turn by the Stop hook

    transcript = payload.get("transcript_path")
    if not transcript or not os.path.isfile(transcript):
        permit()   # blind: fail OPEN here, and let the Stop hook fail closed

    cache_path = os.path.join(project, CACHE_FILE)
    try:
        size = os.path.getsize(transcript)
    except OSError:
        permit()

    spent = read_cache(cache_path, window, size)
    if spent is None:
        spent = stop.measure_spend(transcript, window)
        if spent is None:
            permit()   # blind again, and again the Stop hook is the one that stops
        write_cache(cache_path, window, size, spent)

    if spent < spend_max:
        permit()

    task = run.get("current_task") or "the current task"
    refuse(
        "The spend ceiling for %s is reached: %s of %s, measured from this session's "
        "transcript. Stop calling tools now. Say what you completed and what is left, "
        "and end your turn — the autopilot will stop the run at the turn boundary and "
        "hand it to the developer. Raising the ceiling is not yours to do: it is set in "
        "the approved plan, and re-planning is how it changes."
        % (task, stop.usd(spent), stop.usd(spend_max)))


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.path.insert(0, HERE)
        import selftest
        sys.exit(selftest.run())
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Never fatal for its own defects, and never noisy about them either: a
        # PreToolUse hook speaks before every single action, so a complaint here
        # would be printed hundreds of times in a session.
        sys.exit(0)
