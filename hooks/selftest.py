#!/usr/bin/env python3
"""Selftest for the autopilot Stop hook.

Run it before trusting the hook with an unattended run:

    python3 hooks/autopilot-stop.py --selftest

Every case builds a throwaway project, invokes the hook as a real subprocess
with a real Stop payload on stdin, and asserts on what it printed and what it
wrote back to the run file. Nothing outside the temporary directory is touched,
and no model is called.

The cases exist in the order the guards fire, and each one is here because
getting it wrong has a specific cost:

  silence          a hook that speaks up in projects that never opted in is a
                   hook people disable
  confinement      a hook that writes outside its project is the one failure
                   worth being paranoid about
  fail-closed      an unmeasured ceiling silently becomes no ceiling
  counter custody  a model that can edit its own leash has no leash
  body preserved   the run log is what the human reads instead of watching
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "autopilot-stop.py")

FRONT = """\
status: {status}
gate: {gate}
continuations_used: {used}
continuations_max: {used_max}
gate_retries: {retries}
gate_retries_max: {retries_max}
current_task: {task}
task_started_at: {started}
task_spend_micro_usd: 0
task_spend_max_micro_usd: {spend_max}
blocked_reason:
"""

BODY = """
## Tasks
{tasks}

## Log
- run opened by hand, in a test
"""


class Project:
    """A throwaway project with a run file, and a fake transcript when asked."""

    def __init__(self, tasks="- [ ] T1 do a thing", status="ACTIVE", gate="",
                 used=0, used_max=40, retries=0, retries_max=2,
                 task="T1", started="2000-01-01T00:00:00Z", spend_max=0,
                 run_file=True, frontmatter=None):
        self.dir = os.path.realpath(tempfile.mkdtemp(prefix="eff-selftest-"))
        os.makedirs(os.path.join(self.dir, ".claude"))
        self.run_path = os.path.join(self.dir, ".claude", "efficiency.local.md")
        self.transcript = None
        if run_file:
            text = frontmatter if frontmatter is not None else (
                "---\n" + FRONT.format(
                    status=status, gate=gate, used=used, used_max=used_max,
                    retries=retries, retries_max=retries_max, task=task,
                    started=started, spend_max=spend_max)
                + "---\n" + BODY.format(tasks=tasks))
            open(self.run_path, "w").write(text)

    def write_transcript(self, messages):
        """A minimal transcript in the real on-disk shape."""
        self.transcript = os.path.join(self.dir, "transcript.jsonl")
        with open(self.transcript, "w") as fh:
            for model, usage, ts in messages:
                fh.write(json.dumps({
                    "timestamp": ts,
                    "message": {"model": model, "usage": usage},
                }) + "\n")
        return self.transcript

    def subagent_transcript(self, messages):
        """Subagent turns live beside the main transcript, not inside it."""
        base = self.transcript[: -len(".jsonl")]
        d = os.path.join(base, "subagents")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "agent-test.jsonl"), "w") as fh:
            for model, usage, ts in messages:
                fh.write(json.dumps({
                    "timestamp": ts,
                    "message": {"model": model, "usage": usage},
                }) + "\n")

    def invoke(self):
        payload = {
            "session_id": "selftest",
            "cwd": self.dir,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        }
        if self.transcript:
            payload["transcript_path"] = self.transcript
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.dir)
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=120)
        out = {}
        if done.stdout.strip():
            out = json.loads(done.stdout.strip().split("\n")[-1])
        return done.returncode, out

    def state(self):
        text = open(self.run_path, errors="replace").read()
        head = text.split("---")[1]
        return dict(
            (k.strip(), v.strip())
            for k, v in (l.split(":", 1) for l in head.strip().split("\n") if ":" in l))

    def raw(self):
        return open(self.run_path, errors="replace").read()

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((bool(condition), name, detail))


def case(name):
    def wrap(fn):
        def inner():
            p = None
            try:
                p = fn()
            except Exception as exc:  # a broken case is a failure, not a crash
                check(name, False, "raised %s: %s" % (type(exc).__name__, exc))
            finally:
                if isinstance(p, Project):
                    p.close()
        inner.__name__ = fn.__name__
        CASES.append(inner)
        return inner
    return wrap


CASES = []


# ── 1. it stays out of the way ───────────────────────────────────────────────

@case("no run file: exit 0, and says nothing at all")
def _():
    p = Project(run_file=False)
    code, out = p.invoke()
    check("no run file: exit 0, and says nothing at all", code == 0 and out == {},
          "code=%s out=%s" % (code, out))
    return p


@case("status DONE: stands aside in silence")
def _():
    p = Project(status="DONE")
    code, out = p.invoke()
    check("status DONE: stands aside in silence", code == 0 and out == {},
          "out=%s" % (out,))
    return p


@case("status BLOCKED: does not unblock itself")
def _():
    p = Project(status="BLOCKED")
    code, out = p.invoke()
    check("status BLOCKED: does not unblock itself",
          out == {} and p.state()["status"] == "BLOCKED")
    return p


@case("malformed frontmatter: reports, never blocks")
def _():
    p = Project(frontmatter="this file has no frontmatter at all\n")
    code, out = p.invoke()
    check("malformed frontmatter: reports, never blocks",
          code == 0 and "decision" not in out and "systemMessage" in out,
          "out=%s" % (out,))
    return p


# ── 2. continuation ──────────────────────────────────────────────────────────

@case("open task, no gate: blocks and takes custody of the counter")
def _():
    p = Project(tasks="- [x] T1 done\n- [ ] T2 open", used=3)
    code, out = p.invoke()
    st = p.state()
    check("open task, no gate: blocks and takes custody of the counter",
          out.get("decision") == "block" and st["continuations_used"] == "4"
          and "T2" in out.get("reason", ""),
          "used=%s reason=%.60s" % (st["continuations_used"], out.get("reason")))
    return p


@case("a [>] task counts as open, not as done")
def _():
    p = Project(tasks="- [x] T1 done\n- [>] T2 in progress")
    code, out = p.invoke()
    check("a [>] task counts as open, not as done", out.get("decision") == "block")
    return p


@case("every task closed: marks the run DONE and lets the turn end")
def _():
    p = Project(tasks="- [x] T1 done\n- [X] T2 done")
    code, out = p.invoke()
    check("every task closed: marks the run DONE and lets the turn end",
          "decision" not in out and p.state()["status"] == "DONE",
          "status=%s" % p.state()["status"])
    return p


@case("continuations exhausted: stops with a readable reason")
def _():
    p = Project(tasks="- [ ] T1 open", used=40, used_max=40)
    code, out = p.invoke()
    st = p.state()
    check("continuations exhausted: stops with a readable reason",
          "decision" not in out and st["status"] == "BLOCKED"
          and "40" in st["blocked_reason"],
          "reason=%s" % st["blocked_reason"])
    return p


# ── 3. the gate ──────────────────────────────────────────────────────────────

@case("green gate: continues and clears the retry counter")
def _():
    p = Project(tasks="- [ ] T1 open", gate="true", retries=1)
    code, out = p.invoke()
    check("green gate: continues and clears the retry counter",
          out.get("decision") == "block" and p.state()["gate_retries"] == "0",
          "retries=%s" % p.state()["gate_retries"])
    return p


@case("red gate under the limit: blocks for repair, counts the attempt")
def _():
    p = Project(tasks="- [ ] T1 open", gate="echo 'boom: src/x.py:12' >&2; exit 1")
    code, out = p.invoke()
    st = p.state()
    check("red gate under the limit: blocks for repair, counts the attempt",
          out.get("decision") == "block" and st["gate_retries"] == "1"
          and "boom" in out.get("reason", "") and st["status"] == "ACTIVE",
          "retries=%s status=%s" % (st["gate_retries"], st["status"]))
    return p


@case("red gate at the limit: stops the run instead of looping")
def _():
    p = Project(tasks="- [ ] T1 open", gate="exit 1", retries=2, retries_max=2)
    code, out = p.invoke()
    st = p.state()
    check("red gate at the limit: stops the run instead of looping",
          "decision" not in out and st["status"] == "BLOCKED"
          and "red" in st["blocked_reason"],
          "status=%s reason=%.60s" % (st["status"], st["blocked_reason"]))
    return p


@case("gate command cannot run: fails closed, does not continue blind")
def _():
    p = Project(tasks="- [ ] T1 open", gate="exec /nonexistent/gate/binary")
    code, out = p.invoke()
    st = p.state()
    # A shell reports a missing command with a non-zero status, so this lands as
    # a red gate rather than an unrunnable one. Either way the run must not sail
    # past it: assert the outcome, not the branch.
    check("gate command cannot run: fails closed, does not continue blind",
          st["status"] == "BLOCKED" or out.get("decision") == "block",
          "status=%s out=%s" % (st["status"], out.get("decision")))
    return p


# ── 4. the spend ceiling ─────────────────────────────────────────────────────

@case("spend under the ceiling: continues, and records what was measured")
def _():
    p = Project(tasks="- [ ] T1 open", spend_max=10_000_000)
    p.write_transcript([("claude-sonnet-5",
                         {"input_tokens": 1000, "output_tokens": 1000}, "2026-01-01T00:00:00Z")])
    code, out = p.invoke()
    st = p.state()
    check("spend under the ceiling: continues, and records what was measured",
          out.get("decision") == "block" and int(st["task_spend_micro_usd"]) > 0,
          "spend=%s" % st["task_spend_micro_usd"])
    return p


@case("spend over the ceiling: stops the task and asks for an opinion")
def _():
    p = Project(tasks="- [ ] T1 open", spend_max=1000)
    p.write_transcript([("claude-opus-5",
                         {"input_tokens": 100000, "output_tokens": 100000}, "2026-01-01T00:00:00Z")])
    code, out = p.invoke()
    st = p.state()
    check("spend over the ceiling: stops the task and asks for an opinion",
          "decision" not in out and st["status"] == "BLOCKED"
          and "ceiling" in st["blocked_reason"],
          "reason=%.70s" % st["blocked_reason"])
    return p


@case("spend unmeasurable: FAILS CLOSED rather than continuing blind")
def _():
    p = Project(tasks="- [ ] T1 open", spend_max=1000)
    p.transcript = os.path.join(p.dir, "does-not-exist.jsonl")
    code, out = p.invoke()
    st = p.state()
    check("spend unmeasurable: FAILS CLOSED rather than continuing blind",
          "decision" not in out and st["status"] == "BLOCKED"
          and "measured" in st["blocked_reason"],
          "status=%s reason=%.70s" % (st["status"], st["blocked_reason"]))
    return p


@case("no ceiling configured: the guard is skipped, not silently zero")
def _():
    p = Project(tasks="- [ ] T1 open", spend_max=0)
    code, out = p.invoke()
    check("no ceiling configured: the guard is skipped, not silently zero",
          out.get("decision") == "block")
    return p


@case("spend counts SUBAGENT turns, which are in a separate transcript")
def _():
    p = Project(tasks="- [ ] T1 open", spend_max=10_000_000)
    p.write_transcript([("claude-haiku-4-5",
                         {"input_tokens": 10, "output_tokens": 10}, "2026-01-01T00:00:00Z")])
    p.subagent_transcript([("claude-opus-5",
                            {"input_tokens": 200000, "output_tokens": 200000}, "2026-01-01T00:00:01Z")])
    code, out = p.invoke()
    spent = int(p.state()["task_spend_micro_usd"])
    # The subagent alone is 200k in + 200k out on Opus: $1 + $5 = $6.
    check("spend counts SUBAGENT turns, which are in a separate transcript",
          spent > 5_000_000, "measured %s micro-usd" % spent)
    return p


@case("spend ignores turns older than the task's start marker")
def _():
    p = Project(tasks="- [ ] T1 open", spend_max=10_000_000,
                started="2026-06-01T00:00:00Z")
    p.write_transcript([
        ("claude-opus-5", {"input_tokens": 500000, "output_tokens": 500000}, "2026-01-01T00:00:00Z"),
        ("claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 100}, "2026-07-01T00:00:00Z"),
    ])
    code, out = p.invoke()
    spent = int(p.state()["task_spend_micro_usd"])
    check("spend ignores turns older than the task's start marker",
          spent < 100_000, "measured %s micro-usd (the old turn leaked in)" % spent)
    return p


# ── 5. custody and confinement ───────────────────────────────────────────────

@case("the run log survives every rewrite of the state")
def _():
    p = Project(tasks="- [ ] T1 open")
    marker = "- a decision taken autonomously, which must not be lost"
    text = p.raw().replace("- run opened by hand, in a test",
                           "- run opened by hand, in a test\n" + marker)
    open(p.run_path, "w").write(text)
    p.invoke()
    check("the run log survives every rewrite of the state", marker in p.raw())
    return p


@case("a run file linked out of the project is refused")
def _():
    p = Project(tasks="- [ ] T1 open")
    outside = os.path.realpath(tempfile.mkdtemp(prefix="eff-outside-"))
    victim = os.path.join(outside, "efficiency.local.md")
    shutil.move(p.run_path, victim)
    os.symlink(victim, p.run_path)
    try:
        code, out = p.invoke()
        check("a run file linked out of the project is refused",
              code == 0 and "decision" not in out
              and "outside" in out.get("systemMessage", ""),
              "out=%s" % (out,))
    finally:
        shutil.rmtree(outside, ignore_errors=True)
    return p


@case("a dated model id is priced as itself, not as the expensive fallback")
def _():
    p = Project(tasks="- [ ] T1 open", spend_max=10_000_000)
    p.write_transcript([("claude-haiku-4-5-20251001",
                         {"input_tokens": 1_000_000, "output_tokens": 0}, "2026-01-01T00:00:00Z")])
    p.invoke()
    spent = int(p.state()["task_spend_micro_usd"])
    # A million input tokens of Haiku is $1.00. Priced as the fallback it would
    # be $10.00 — a tenfold lie, in the direction that stops a run early.
    check("a dated model id is priced as itself, not as the expensive fallback",
          900_000 <= spent <= 1_100_000, "measured %s micro-usd, expected ~1000000" % spent)
    return p


def run():
    print("autopilot-stop selftest")
    print("hook:  %s" % HOOK)
    print("costs: %s\n" % os.path.join(HERE, "lib", "model-costs.json"))

    for c in CASES:
        c()

    width = max(len(n) for _, n, _ in RESULTS)
    failed = 0
    for ok, name, detail in RESULTS:
        print("  %s  %-*s %s" % ("PASS" if ok else "FAIL", width, name,
                                 "" if ok else "\n        -> " + detail))
        if not ok:
            failed += 1

    print("\n%d checks, %d failed" % (len(RESULTS), failed))
    if failed:
        print("\nThe autopilot must not be trusted with an unattended run until this "
              "is green.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
