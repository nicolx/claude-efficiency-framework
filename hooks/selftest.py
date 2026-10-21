#!/usr/bin/env python3
"""Selftest for the autopilot hooks — the Stop guard and the mid-turn one.

Run it before trusting them with an unattended run:

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
  mid-turn         a ceiling read only at the turn boundary is not enforced
                   for the whole interval in which it can be exceeded
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "autopilot-stop.py")
PRETOOL = os.path.join(HERE, "autopilot-pretool.py")
SESSION_START = os.path.join(HERE, "session-start.py")
PROMPT_REMINDER = os.path.join(HERE, "prompt-reminder.py")
STATUSLINE = os.path.join(HERE, "statusline.py")
PLUGIN = os.path.dirname(HERE)


def _load_hook():
    """The Stop hook as a module, for the few cases that read its constants.

    Everything else invokes it as a subprocess; this exists so a default the
    hook falls back to can be compared with the documents that ship it, instead
    of with a copy of the number written here a third time.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("autopilot_stop", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK_MODULE = _load_hook()

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
        os.makedirs(os.path.join(self.dir, ".efficiency"))
        self.run_path = os.path.join(self.dir, ".efficiency", "run.md")
        self.transcript = None
        # A fake `claude`, first on the hook's PATH, so no case ever reaches a
        # real model. It answers with `bin/reply.json` when a case wrote one and
        # fails otherwise, records every prompt it was given, and counts calls.
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        stub = os.path.join(self.bin, "claude")
        with open(stub, "w") as fh:
            fh.write("#!/bin/sh\n"
                     "d=\"$(dirname \"$0\")\"\n"
                     "n=$(( $(cat \"$d/calls\" 2>/dev/null || echo 0) + 1 ))\n"
                     "echo \"$n\" > \"$d/calls\"\n"
                     "cat > \"$d/prompt-$n.txt\"\n"
                     "printf '%s\\n' \"$PWD\" \"$@\" > \"$d/args-$n.txt\"\n"
                     "env > \"$d/env-$n.txt\"\n"
                     "[ -f \"$d/reply.json\" ] || { echo 'selftest: no supervisor' >&2; exit 1; }\n"
                     "cat \"$d/reply.json\"\n")
        os.chmod(stub, 0o755)
        if run_file:
            text = frontmatter if frontmatter is not None else (
                "---\n" + FRONT.format(
                    status=status, gate=gate, used=used, used_max=used_max,
                    retries=retries, retries_max=retries_max, task=task,
                    started=started, spend_max=spend_max)
                + "---\n" + BODY.format(tasks=tasks))
            open(self.run_path, "w").write(text)

    def write_tools(self, text=None):
        if text is None:
            text = ("# Operational tools on this machine\n\n"
                    "## Available — use these instead of writing a script\n\n"
                    "- `pandoc` — convert between document formats · pandoc 3.1.2\n"
                    "- `jq` — query and transform JSON · jq-1.7\n\n"
                    "## Not installed\n\n"
                    "- `ffmpeg` — convert, trim and inspect audio and video\n")
        with open(os.path.join(self.dir, ".efficiency", "tools.md"), "w") as fh:
            fh.write(text)
        return self

    def write_backlog(self, text):
        with open(os.path.join(self.dir, ".efficiency", "backlog.md"), "w") as fh:
            fh.write(text)
        return self

    def write_policy(self, text=None):
        """The project's own policy, which SessionStart injects alongside the charter."""
        if text is None:
            text = ("---\n"
                    "# a teaching comment that costs tokens at every single session\n"
                    "gate: \"make check\"\n"
                    "\n"
                    "tiers:\n"
                    "  # another comment\n"
                    "  critical: [\"src/auth/**\"]\n"
                    "---\n"
                    "\n"
                    "# Declared defaults\n"
                    "\n"
                    "- prefer extending an existing type over adding a parallel one\n")
        with open(os.path.join(self.dir, ".efficiency", "policy.md"), "w") as fh:
            fh.write(text)
        return self

    def write_settings(self, data):
        """The project's `.claude/settings.json`, which the model cannot write."""
        with open(os.path.join(self.dir, ".claude", "settings.json"), "w") as fh:
            json.dump(data, fh)
        return self

    def invoke_statusline(self, columns="120", script=None, session=None, colour=False):
        """Invoke the status line exactly as Claude Code does.

        Measured in scripts/probes/statusline.sh: the payload arrives on stdin,
        no arguments are passed, and `CLAUDE_PROJECT_DIR` and `COLUMNS` are both
        set in the environment. `script` points at the project's own deployed
        copy when the case is about deployment rather than about rendering.
        """
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.dir, COLUMNS=columns)
        env.pop("NO_COLOR", None)
        if not colour:
            env["NO_COLOR"] = "1"
        payload = {"cwd": self.dir, "workspace": {"project_dir": self.dir}}
        payload.update(session or {})
        done = subprocess.run([sys.executable, script or STATUSLINE],
                              input=json.dumps(payload), capture_output=True,
                              text=True, env=env, timeout=30)
        return done.returncode, done.stdout

    def locale_env(self, env, locale=None, apple=None, path=None):
        """The machine's language as a case declares it, never the host's.

        The locale variables are removed and replaced by `locale`, and a fake
        `defaults` first on PATH answers AppleLanguages with `apple`, or fails.
        Without this every session-start case would read whatever language the
        machine running the gate is in.
        """
        for var in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
            env.pop(var, None)
        env.update(locale or {})
        stub = os.path.join(self.bin, "defaults")
        with open(stub, "w") as fh:
            if apple:
                fh.write('#!/bin/sh\nprintf \'(\\n    "%s"\\n)\\n\'\n' % apple)
            else:
                fh.write("#!/bin/sh\nexit 1\n")
        os.chmod(stub, 0o755)
        env["PATH"] = self.bin + os.pathsep + (path if path is not None
                                               else os.environ.get("PATH", ""))
        return env

    def invoke_prompt(self, locale=None, apple=None):
        """Invoke UserPromptSubmit; returns the injected context, or ""."""
        payload = {"cwd": self.dir, "hook_event_name": "UserPromptSubmit", "prompt": "hi"}
        env = self.locale_env(dict(os.environ, CLAUDE_PROJECT_DIR=self.dir), locale, apple)
        done = subprocess.run([sys.executable, PROMPT_REMINDER], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=30)
        if not done.stdout.strip():
            return ""
        return json.loads(done.stdout).get("hookSpecificOutput", {}).get("additionalContext", "")

    def invoke_session_start(self, inventory=True, path=None, locale=None, apple=None):
        """Invoke SessionStart. A missing inventory is seeded first unless asked not to.

        Without the seed every case would launch the real detection, which asks
        each installed tool for its version — measured at 53 s on a machine with
        docling and marker, and it was most of the gate's twenty minutes.
        """
        tools = os.path.join(self.dir, ".efficiency", "tools.md")
        if inventory and not os.path.exists(tools):
            self.write_tools()
        payload = {"cwd": self.dir, "hook_event_name": "SessionStart"}
        env = self.locale_env(dict(os.environ, CLAUDE_PROJECT_DIR=self.dir), locale, apple, path)
        done = subprocess.run([sys.executable, SESSION_START], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=60)
        if not done.stdout.strip():
            return done.returncode, ""
        out = json.loads(done.stdout.strip().split("\n")[-1])
        return done.returncode, out.get("hookSpecificOutput", {}).get("additionalContext", "")

    def seed_private(self, **values):
        """Set the hook's own state, which no longer lives in the run file.

        A test that seeds counters in the frontmatter is testing the old design:
        the hook captures its ceilings and counters privately on first sight of a
        run, precisely so a rewrite of that frontmatter cannot touch them.
        """
        import hashlib
        import re
        # Scheduling annotations and the tier tag are not part of a task's
        # identity, by the hook's rule; a line without them is hashed as it is.
        sched = re.compile(r"\s+(?:after|files)=\S+")
        tier = re.compile(r"^(- \[.\]\s*\S+)\s+\[[^\]\s]+\]")
        lines = [tier.sub(r"\1", sched.sub("", l.strip()))
                 for l in open(self.run_path, errors="replace").read().split("\n")
                 if l.strip().startswith("- [")]
        statements = "\n".join(l.split("]", 1)[1].strip() for l in lines)
        # The open-task signature, by the same rule the hook uses. Seeding it is
        # what makes `task_started_at` below mean "a window already open since
        # then": seed anything else and the hook reads a closure that never
        # happened, reopens the window at now, and every transcript the case
        # wrote falls outside it.
        open_sig = hashlib.sha256("\n".join(
            l.split("]", 1)[1].strip() for l in lines
            if l[3:4].lower() != "x").encode()).hexdigest()
        state = {
            "fingerprint": hashlib.sha256(statements.encode()).hexdigest(),
            "continuations_used": 0, "continuations_max": 40,
            "gate_retries": 0, "gate_retries_max": 2, "spend_max": 0,
            "task_key": open_sig, "task_started_at": "2000-01-01T00:00:00Z",
            "same_task_blocks": 0, "open_tasks_sig": "",
            "blocked": False, "blocked_reason": "",
        }
        state.update(values)
        with open(os.path.join(self.dir, ".efficiency", "autopilot.json"), "w") as fh:
            json.dump(state, fh)
        return self

    def private(self):
        path = os.path.join(self.dir, ".efficiency", "autopilot.json")
        try:
            return json.load(open(path))
        except (OSError, ValueError):
            return {}

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

    def invoke(self, extra_env=None):
        payload = {
            "session_id": "selftest",
            "cwd": self.dir,
            "hook_event_name": "Stop",
            "stop_hook_active": False,
        }
        if self.transcript:
            payload["transcript_path"] = self.transcript
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.dir,
                   PATH=self.bin + os.pathsep + os.environ.get("PATH", ""))
        env.pop("EFFICIENCY_SUPERVISOR", None)
        env.update(extra_env or {})
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=120)
        out = {}
        if done.stdout.strip():
            out = json.loads(done.stdout.strip().split("\n")[-1])
        return done.returncode, out

    def invoke_pretool(self, tool="Bash", command="make build", mode="dontAsk"):
        """Invoke the mid-turn hook with a real PreToolUse payload.

        The default command is one the auto-allow never classifies as safe, so a
        ceiling case reads silence as "not refused" without the allow answering
        for it.

        The payload shape is the measured one (§ 17), not an invented one: a
        selftest written against a payload the platform does not send proves
        only that the hook agrees with the test.
        """
        payload = {
            "session_id": "selftest",
            "cwd": self.dir,
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": {"command": command},
            "tool_use_id": "selftest-1",
            "permission_mode": mode,
        }
        if self.transcript:
            payload["transcript_path"] = self.transcript
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.dir)
        done = subprocess.run([sys.executable, PRETOOL], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=120)
        out = {}
        if done.stdout.strip():
            out = json.loads(done.stdout.strip().split("\n")[-1])
        return done.returncode, out

    def decision(self, out):
        """The permission decision in a PreToolUse reply, or None for silence."""
        return (out or {}).get("hookSpecificOutput", {}).get("permissionDecision")

    def write_midturn_cache(self, **values):
        path = os.path.join(self.dir, ".efficiency", "midturn-cache.json")
        with open(path, "w") as fh:
            json.dump(values, fh)
        return path

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


def flat(text):
    """Collapse whitespace, so a prose assertion survives a reflow.

    Shipped documents are wrapped at 100 columns, and a sentence that moves
    across the wrap breaks a literal `in` check while nothing about the content
    changed. Twice now. Assert on meaning, not on line width.
    """
    return " ".join(text.split())


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
    p = Project(tasks="- [x] T1 done\n- [ ] T2 open").seed_private(continuations_used=3)
    code, out = p.invoke()
    check("open task, no gate: blocks and takes custody of the counter",
          out.get("decision") == "block" and p.private()["continuations_used"] == 4
          and p.state()["continuations_used"] == "4"
          and "T2" in out.get("reason", ""),
          "private=%s mirrored=%s" % (p.private().get("continuations_used"),
                                      p.state().get("continuations_used")))
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
    p = Project(tasks="- [ ] T1 open").seed_private(continuations_used=40, continuations_max=40)
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
    p = Project(tasks="- [ ] T1 open", gate="true", retries=1).seed_private(gate_retries=1)
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
    p = Project(tasks="- [ ] T1 open", gate="exit 1").seed_private(gate_retries=2, gate_retries_max=2)
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
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10_000_000)
    p.write_transcript([("claude-sonnet-5",
                         {"input_tokens": 1000, "output_tokens": 1000}, "2026-01-01T00:00:00Z")])
    code, out = p.invoke()
    st = p.state()
    check("spend under the ceiling: continues, and records what was measured",
          out.get("decision") == "block" and int(st["task_spend_micro_usd"]) > 0,
          "spend=%s" % st["task_spend_micro_usd"])
    return p


@case("the per-model split is written into the run file, not left to a script")
def _():
    # run-report cannot execute spend.py: it lives in the plugin's directory and
    # nothing outside the project is reachable from a session. So the hook, which
    # has no such limit, puts the answer where the model can read it.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10_000_000)
    p.write_transcript([
        ("claude-opus-5", {"input_tokens": 1_000_000, "output_tokens": 0}, "2026-01-01T00:00:00Z"),
        ("claude-haiku-4-5", {"input_tokens": 1_000_000, "output_tokens": 0}, "2026-01-01T00:00:01Z"),
    ])
    p.invoke()
    split = p.state().get("task_spend_by_model", "")
    check("the per-model split is written into the run file, not left to a script",
          "claude-opus-5=5000000" in split and "claude-haiku-4-5=1000000" in split,
          "got %r" % split)
    return p


@case("a model priced by prompt length is charged at the card its prompt earns")
def _():
    # Claude Haiku 5.5 is the first model whose price depends on the size of the
    # request: over 100,000 prompt tokens it costs about five times as much, on
    # every line. A table holding one number per model had to be wrong one way
    # or the other — and `haiku` resolves to it, so the error would have landed
    # on exactly the routing the framework exists to recommend.
    #
    # 100,000 input tokens is the boundary itself: "over 100,000" is strictly
    # over, so this is the cheap card. 100_000 * $0.10/MTok = $0.01.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10**9)
    p.write_transcript([("claude-haiku-5-5",
                         {"input_tokens": 100_000, "output_tokens": 0},
                         "2026-01-01T00:00:00Z")])
    p.invoke()
    split = p.state().get("task_spend_by_model", "")
    check("a model priced by prompt length is charged at the card its prompt earns",
          "claude-haiku-5-5=10000" in split, "got %r" % split)
    return p


@case("a prompt is long because of its cache reads, not its input_tokens")
def _():
    # On a Claude Code turn `input_tokens` is usually a handful: almost the whole
    # prompt arrives as a cache read. The pricing rule counts every input token
    # of the request, cache reads included, so a reading that looked at
    # `input_tokens` alone would price a 400k-token turn as a small one and
    # under-report it fivefold — the direction a ceiling must never be wrong in.
    #
    # 400,000 cache-read tokens, nothing else: $0.05/MTok on the long card is
    # $0.02, against $0.004 if the short card had been chosen.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10**9)
    p.write_transcript([("claude-haiku-5-5",
                         {"input_tokens": 0, "output_tokens": 0,
                          "cache_read_input_tokens": 400_000},
                         "2026-01-01T00:00:00Z")])
    p.invoke()
    split = p.state().get("task_spend_by_model", "")
    check("a prompt is long because of its cache reads, not its input_tokens",
          "claude-haiku-5-5=20000" in split, "got %r" % split)
    return p


@case("spend over the ceiling: stops the task and asks for an opinion")
def _():
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=1000)
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
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=1000)
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
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10_000_000)
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
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10_000_000,
                task_started_at="2026-06-01T00:00:00Z")
    p.write_transcript([
        ("claude-opus-5", {"input_tokens": 500000, "output_tokens": 500000}, "2026-01-01T00:00:00Z"),
        ("claude-haiku-4-5", {"input_tokens": 100, "output_tokens": 100}, "2026-07-01T00:00:00Z"),
    ])
    code, out = p.invoke()
    spent = int(p.state()["task_spend_micro_usd"])
    check("spend ignores turns older than the task's start marker",
          spent < 100_000, "measured %s micro-usd (the old turn leaked in)" % spent)
    return p


@case("spend counts a message ONCE, though the transcript writes a row per content block")
def _():
    # The real shape (docs/verified-platform-behaviour.md § 6): thinking, text
    # and a tool call are three rows, each repeating the whole message's input
    # usage, with output_tokens growing as it streams — only the last is the
    # bill. Summing rows charged $0.89 for a session that cost $0.22.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10_000_000)
    path = p.write_transcript([])
    ts = "2026-01-01T00:00:%02dZ"
    rows = []
    # msg_A: 200k Opus input ($1.00) + 40k output ($1.00), split over 3 blocks.
    for i, (block, out) in enumerate((("thinking", 3), ("text", 3), ("tool_use", 40_000))):
        rows.append({"timestamp": ts % i, "requestId": "req_A",
                     "message": {"id": "msg_A", "model": "claude-opus-5",
                                 "content": [{"type": block}],
                                 "usage": {"input_tokens": 200_000, "output_tokens": out}}})
    # Keyed by requestId alone: two rows, one message ($1.00).
    for i in range(2):
        rows.append({"timestamp": ts % (10 + i), "requestId": "req_B",
                     "message": {"model": "claude-opus-5",
                                 "usage": {"input_tokens": 200_000, "output_tokens": 0}}})
    # No id at all: nothing to match, so each row still counts ($1.00 x 2).
    for i in range(2):
        rows.append({"timestamp": ts % (20 + i),
                     "message": {"model": "claude-opus-5",
                                 "usage": {"input_tokens": 200_000, "output_tokens": 0}}})
    with open(path, "w") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))
    p.invoke()
    spent = int(p.state()["task_spend_micro_usd"])
    # $5.00. Summing rows says $8.00; keeping each message's FIRST row, $4.00.
    check("spend counts a message ONCE, though the transcript writes a row per content block",
          spent == 5_000_000, "measured %s micro-usd, expected 5000000" % spent)
    return p


@case("a window the run file dates in the future would never measure anything")
def _():
    # `task_started_at` is frontmatter, so the model writes it, and the hook
    # takes it as the start of the first window — it cannot see the run before
    # the first turn boundary, and the work of that turn has to be inside. A
    # date in the future costs nothing to write and silently empties the window
    # for the rest of the run: spend measures 0 forever and the ceiling, the one
    # guard that is deliberately fail-closed, never fires once.
    #
    # The turn below is stamped a minute from now, so it lands inside any window
    # that starts at the fallback and outside one that starts in 2099. $5 of
    # Opus against a $1 ceiling: the guard fires, or the lever is still there.
    from datetime import datetime, timedelta, timezone
    soon = (datetime.now(timezone.utc) + timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    p = Project(tasks="- [ ] T1 open", started="2099-01-01T00:00:00Z",
                spend_max=1_000_000)
    p.write_transcript([("claude-opus-5", {"input_tokens": 1_000_000, "output_tokens": 0}, soon)])
    code, out = p.invoke()
    st = p.state()
    check("a window the run file dates in the future would never measure anything",
          p.private()["task_started_at"] != "2099-01-01T00:00:00Z"
          and st["status"] == "BLOCKED" and "spend ceiling" in st["blocked_reason"],
          "seeded=%s status=%s reason=%.60s"
          % (p.private().get("task_started_at"), st["status"], st["blocked_reason"]))
    return p


@case("a window dated in the past is taken as written: it only charges more")
def _():
    # The other direction is not symmetrical and must not be treated as such. An
    # early start widens the window and charges this task with spend that was
    # not its own — too strict, never too lax — and it is also the honest case:
    # the run really did begin before the hook first saw it.
    p = Project(tasks="- [ ] T1 open", started="2026-01-01T00:00:00Z",
                spend_max=10_000_000)
    p.write_transcript([("claude-opus-5", {"input_tokens": 200_000, "output_tokens": 0},
                         "2026-01-02T00:00:00Z")])
    p.invoke()
    check("a window dated in the past is taken as written: it only charges more",
          p.private()["task_started_at"] == "2026-01-01T00:00:00Z"
          and int(p.state()["task_spend_micro_usd"]) == 1_000_000,
          "seeded=%s spend=%s" % (p.private().get("task_started_at"),
                                  p.state().get("task_spend_micro_usd")))
    return p


# ── 5. the stall guard ───────────────────────────────────────────────────────
# Every case here exists because of one measured failure: 12 blocks on the same
# task, its work finished, the box never ticked, and the last continuations spent
# narrating the counter. Nothing noticed.

@case("the block reason tells the model to CLOSE the finished task")
def _():
    p = Project(tasks="- [ ] T1 open")
    code, out = p.invoke()
    reason = out.get("reason", "")
    check("the block reason tells the model to CLOSE the finished task",
          "- [x]" in reason and "## Log" in reason and "current_task" in reason
          and "belong to the hook" in reason,
          "reason lacked the closing instructions: %.160s" % reason)
    return p


@case("the block reason forbids status reporting outright")
def _():
    p = Project(tasks="- [ ] T1 open")
    code, out = p.invoke()
    reason = out.get("reason", "").lower()
    check("the block reason forbids status reporting outright",
          "do not summarise" in reason and "counters" in reason,
          "reason: %.120s" % reason)
    return p


@case("handing back the same task counts as a stall")
def _():
    p = Project(tasks="- [ ] T1 open")
    p.invoke()
    first = int(p.state()["same_task_blocks"])
    p.invoke()
    second = int(p.state()["same_task_blocks"])
    check("handing back the same task counts as a stall",
          first == 0 and second == 1, "first=%s second=%s" % (first, second))
    return p


@case("closing a task resets the stall counter")
def _():
    p = Project(tasks="- [ ] T1 open\n- [ ] T2 open")
    p.invoke()
    p.invoke()
    stalled = int(p.state()["same_task_blocks"])
    text = p.raw().replace("- [ ] T1 open", "- [x] T1 open")
    open(p.run_path, "w").write(text)
    p.invoke()
    check("closing a task resets the stall counter",
          stalled == 1 and int(p.state()["same_task_blocks"]) == 0,
          "was %s, now %s" % (stalled, p.state()["same_task_blocks"]))
    return p


@case("the wording escalates once the stall is visible")
def _():
    p = Project(tasks="- [ ] T1 open")
    out = {}
    for _ in range(4):
        _c, out = p.invoke()
    check("the wording escalates once the stall is visible",
          "ATTENTION" in out.get("reason", ""),
          "reason: %.140s" % out.get("reason", ""))
    return p


def stall_until_stopped(p, limit=12, between=None):
    """Block `p` until the run stops itself. Returns the block number it fell on.

    The number is the point of the test, not a detail of it: the platform's own
    anti-stall cap honours 8 blocks before overriding the ninth (§ 3), and this
    guard is only the one the developer reads if it fires first. `between` runs
    after each block, for cases about what the model does in the meantime.
    """
    for n in range(1, limit + 1):
        p.invoke()
        if p.state()["status"] == "BLOCKED":
            return n
        if between:
            between(p)
    return 0


@case("a run that never advances stops itself, two blocks inside the platform cap")
def _():
    p = Project(tasks="- [ ] T1 open")
    fired = stall_until_stopped(p)
    st = p.state()
    # 6, and the margin matters as much as the fact: the platform honours 8
    # blocks without a tool call before overriding the ninth, so this guard
    # reaching its ceiling at 6 is what puts OUR reason in front of the
    # developer instead of the platform's silent override. Raise STALL_STOP
    # past 7 and the run still stops — but nobody is told why.
    check("a run that never advances stops itself, two blocks inside the platform cap",
          fired == 6 and "advancing" in st["blocked_reason"],
          "stopped at block %s, reason=%.80s" % (fired or "never", st["blocked_reason"]))
    return p


@case("alternating current_task cannot keep a stalled run alive")
def _():
    # The block reason tells the model to move `current_task` when a task is
    # done. A model that moves it WITHOUT closing anything — confusion, not
    # evasion — used to reset this guard on every block, and the run was then
    # bounded only by continuations_max, forty blocks away. Progress is a task
    # closing, and nothing else.
    def flip(p):
        now = p.state()["current_task"]
        nxt = "T2" if now == "T1" else "T1"
        # Read before opening for write: `open(..., "w")` truncates first.
        text = p.raw().replace("current_task: " + now, "current_task: " + nxt)
        open(p.run_path, "w").write(text)

    p = Project(tasks="- [ ] T1 open\n- [ ] T2 open")
    fired = stall_until_stopped(p, between=flip)
    check("alternating current_task cannot keep a stalled run alive",
          fired == 6, "stopped at block %s" % (fired or "never"))
    return p


# ── 6. custody: the model cannot reach the hook's state ──────────────────────
# Every case here reproduces a real failure. On this framework's second run the
# model was told to update `current_task`, rewrote the whole frontmatter, and
# dropped every key it did not recognise — resetting the stall counter to zero
# and erasing two others. Not evasion: it simply did not know they mattered.

@case("rewriting the run file's frontmatter cannot reset the stall counter")
def _():
    p = Project(tasks="- [ ] T1 open")
    p.invoke()
    p.invoke()
    stalled = p.private()["same_task_blocks"]
    # Exactly what the model did: keep the keys it recognises, drop the rest.
    text = p.raw()
    head, _, body = text.partition("---\n")[2].partition("---\n")
    kept = [l for l in head.split("\n")
            if l.split(":", 1)[0] in ("status", "gate", "current_task", "blocked_reason")]
    open(p.run_path, "w").write("---\n" + "\n".join(kept) + "\n---\n" + body)
    p.invoke()
    # Two separate protections, and the second was added later. The counter is
    # not reset by the rewrite, because it does not live in the file. And the
    # run now stops outright, because the keys the model dropped include its
    # ceilings — deleting your own ceiling is the most complete way of extending
    # a run, so it is the last thing that may be allowed to pass quietly.
    st = p.state()
    check("rewriting the run file's frontmatter cannot reset the stall counter",
          stalled == 1
          and p.private()["same_task_blocks"] >= 1
          and st["status"] == "BLOCKED"
          and "ceiling" in (st.get("blocked_reason") or ""),
          "was %s, now %s, status=%s reason=%.60s"
          % (stalled, p.private().get("same_task_blocks"), st["status"], st.get("blocked_reason")))
    return p


@case("a run file that never declared its ceilings does not run at all")
def _():
    # The defect this replaced: the spend guard only executes when spend_max > 0,
    # so a run file with no ceiling skipped the guard AND the fail-closed branch
    # inside it, and the run went ahead unbounded in silence. Measured on a real
    # run — three tasks executed with both ceilings at 0, and the only symptom
    # was a report minutes later that could not say what anything had cost.
    front = ("status: ACTIVE\ngate: \ncurrent_task: T1\n"
             "task_started_at: 2000-01-01T00:00:00Z\nblocked_reason:\n")
    p = Project(frontmatter="---\n" + front + "---\n\n## Tasks\n- [ ] T1 open\n\n## Log\n")
    p.invoke()
    st = p.state()
    check("a run file that never declared its ceilings does not run at all",
          st["status"] == "BLOCKED"
          and "task_spend_max_micro_usd" in (st.get("blocked_reason") or "")
          and "continuations_max" in (st.get("blocked_reason") or ""),
          "status=%s reason=%.90s" % (st["status"], st.get("blocked_reason")))
    return p


@case("a ceiling someone deliberately set to zero is still honoured")
def _():
    # The distinction the guard turns on: an absent key is an incomplete run
    # file, a zero is a decision a developer approved at plan time. Collapsing
    # the two would make the guard either useless or unusable.
    p = Project(tasks="- [ ] T1 open", spend_max=0)
    p.invoke()
    st = p.state()
    check("a ceiling someone deliberately set to zero is still honoured",
          st["status"] == "ACTIVE",
          "status=%s reason=%.60s" % (st["status"], st.get("blocked_reason")))
    return p


@case("a ceiling set to zero is announced on every continuation, not left implicit")
def _():
    # Honouring the decision is half of it. The other half is that the developer
    # reading the transcript afterwards should not have to infer an unbounded run
    # from the absence of a number.
    p = Project(tasks="- [ ] T1 open", spend_max=0)
    _code, out = p.invoke()
    reason = out.get("reason", "") if isinstance(out, dict) else str(out)
    check("a ceiling set to zero is announced on every continuation, not left implicit",
          "no spend ceiling" in reason,
          "the continuation note said: %.100s" % " ".join(reason.split()))
    return p


@case("a gate wrapped in quotes still runs, instead of reading as a red gate")
def _():
    # The frontmatter is parsed by hand, and for a long time the quotes came with
    # the value: `gate: "pytest -q"` reached the shell as a command whose name was
    # the whole quoted string. A missing command exits 127, which is
    # indistinguishable from a failing suite, so the run did not report an
    # unrunnable gate — it reported a red one and spent its repair attempts fixing
    # code that was never broken. The quoted form is what templates/efficiency.md
    # ships, so this is the default path and not an edge.
    #
    # Two things about this case are deliberate, and both were got wrong first.
    #
    # The gate must take ARGUMENTS. `sh -c '"true"'` succeeds, because the shell
    # strips the quotes around a single word itself — a one-word gate cannot
    # detect the defect at all. A real gate looks like `python3 -m compileall -q
    # src`, and quoted it becomes the name of a five-word command that no shell
    # can find.
    #
    # The observable must be `gate_retries`, not `status`. A red gate is retried
    # before it blocks, so the run is still ACTIVE either way and an assertion on
    # status passes with the defect fully present.
    results = {}
    p = None
    for label, gate in (("double", '"test 1 = 1"'), ("single", "'test 1 = 1'"), ("bare", "test 1 = 1")):
        p = Project(tasks="- [ ] T1 open", gate=gate)
        p.invoke()
        results[label] = p.private().get("gate_retries")
    check("a gate wrapped in quotes still runs, instead of reading as a red gate",
          all(v == 0 for v in results.values()),
          "gate_retries by quoting: %s — anything above 0 means the gate never ran" % results)
    return p


@case("a gate that genuinely fails is still caught once the quotes are gone")
def _():
    # The other half: stripping the quotes must not make every gate look green.
    p = Project(tasks="- [ ] T1 open", gate='"test 1 = 2"')
    p.invoke()
    check("a gate that genuinely fails is still caught once the quotes are gone",
          p.private().get("gate_retries", 0) > 0,
          "gate_retries=%s" % p.private().get("gate_retries"))
    return p


@case("raising continuations_max in the run file buys nothing")
def _():
    p = Project(tasks="- [ ] T1 open").seed_private(continuations_used=5, continuations_max=5)
    text = p.raw().replace("continuations_max: 40", "continuations_max: 9999")
    open(p.run_path, "w").write(text)
    code, out = p.invoke()
    st = p.state()
    check("raising continuations_max in the run file buys nothing",
          "decision" not in out and st["status"] == "BLOCKED" and "5" in st["blocked_reason"],
          "status=%s reason=%.70s" % (st["status"], st["blocked_reason"]))
    return p


@case("a model the cost table does not know is named, not silently absorbed")
def _():
    # The fallback is the most expensive row on purpose: a ceiling must never be
    # raised by a model nobody priced. But it used to be silent, and a real run
    # routed to three ids that had all moved a generation — every one priced as
    # the fallback, and the report read out a confident per-model split that was
    # three different models at one wrong price. The cheap implementer looked
    # like the expensive one, which is the exact claim routing exists to make.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10**9)
    p.write_transcript([("claude-not-a-real-model-9",
                         {"input_tokens": 1000, "output_tokens": 1000}, "2026-01-01T00:00:00Z")])
    p.invoke()
    named = p.state().get("task_spend_unpriced_models", "")
    check("a model the cost table does not know is named, not silently absorbed",
          "claude-not-a-real-model-9" in named,
          "task_spend_unpriced_models=%r" % named)
    return p


@case("raising the spend ceiling in the run file buys nothing")
def _():
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=1000)
    text = p.raw().replace("task_spend_max_micro_usd: 0",
                           "task_spend_max_micro_usd: 999999999")
    open(p.run_path, "w").write(text)
    p.write_transcript([("claude-opus-5",
                         {"input_tokens": 100000, "output_tokens": 100000}, "2026-01-01T00:00:00Z")])
    code, out = p.invoke()
    check("raising the spend ceiling in the run file buys nothing",
          p.state()["status"] == "BLOCKED" and "ceiling" in p.state()["blocked_reason"],
          "status=%s" % p.state()["status"])
    return p


@case("setting status back to ACTIVE does not resume a stopped run")
def _():
    p = Project(tasks="- [ ] T1 open").seed_private(
        blocked=True, blocked_reason="stopped by a guard in an earlier session")
    text = p.raw().replace("status: BLOCKED", "status: ACTIVE")
    open(p.run_path, "w").write(text)
    code, out = p.invoke()
    st = p.state()
    check("setting status back to ACTIVE does not resume a stopped run",
          "decision" not in out and st["status"] == "BLOCKED"
          and "delete" in out.get("systemMessage", ""),
          "status=%s msg=%.80s" % (st["status"], out.get("systemMessage")))
    return p


@case("re-planning the task list is the legitimate way to start over")
def _():
    p = Project(tasks="- [ ] T1 open").seed_private(
        continuations_used=40, continuations_max=40, blocked=True,
        blocked_reason="continuations exhausted")
    text = p.raw().replace("- [ ] T1 open", "- [ ] T1 a different piece of work")
    text = text.replace("status: BLOCKED", "status: ACTIVE")
    open(p.run_path, "w").write(text)
    code, out = p.invoke()
    check("re-planning the task list is the legitimate way to start over",
          out.get("decision") == "block" and p.private()["continuations_used"] == 1
          and p.private()["blocked"] is False,
          "used=%s blocked=%s" % (p.private().get("continuations_used"),
                                  p.private().get("blocked")))
    return p


@case("the hook owns the spend window, and CLOSING a task opens a fresh one")
def _():
    # spend_max=0 so the ceiling is out of the way: the window is opened before
    # the guard that reads it, and this case is about the window alone.
    p = Project(tasks="- [ ] T1 open\n- [ ] T2 open").seed_private(
        task_started_at="2000-01-01T00:00:00Z", spend_max=0)
    p.invoke()
    carried = p.private()["task_started_at"]
    text = p.raw().replace("- [ ] T1 open", "- [x] T1 open")
    open(p.run_path, "w").write(text)
    p.invoke()
    check("the hook owns the spend window, and CLOSING a task opens a fresh one",
          carried == "2000-01-01T00:00:00Z"
          and p.private()["task_started_at"] != "2000-01-01T00:00:00Z",
          "carried=%s then=%s" % (carried, p.private().get("task_started_at")))
    return p


@case("alternating current_task cannot buy a second spend ceiling")
def _():
    # The sibling of the stall case above, and the one that costs money. Until
    # 0.18.2 the spend window reopened whenever `current_task` changed — the
    # field the block reason tells the model to rewrite — so a model alternating
    # between two open tasks restarted the window on every block and could spend
    # the whole ceiling again each time. Every turn before the restart then fell
    # outside the new window and was measured as nothing.
    #
    # Here the run spends $0.50 per block against a $1.20 ceiling. Keyed on the
    # open tasks, the window holds all of it and the guard fires on the third.
    # Keyed on `current_task`, every block measured 0 and this ran forever.
    spent = []

    def flip_and_spend(p):
        now = p.state()["current_task"]
        text = p.raw().replace("current_task: " + now,
                               "current_task: " + ("T2" if now == "T1" else "T1"))
        open(p.run_path, "w").write(text)
        spent.append(("claude-opus-5", {"input_tokens": 100_000, "output_tokens": 0},
                      "2026-01-01T00:00:%02dZ" % len(spent)))
        p.write_transcript(spent)

    p = Project(tasks="- [ ] T1 open\n- [ ] T2 open").seed_private(
        task_started_at="2000-01-01T00:00:00Z", spend_max=1_200_000)
    flip_and_spend(p)
    fired = stall_until_stopped(p, limit=5, between=flip_and_spend)
    reason = p.state()["blocked_reason"]
    check("alternating current_task cannot buy a second spend ceiling",
          fired == 3 and "spend ceiling" in reason,
          "stopped at block %s, reason=%.90s" % (fired or "never", reason))
    return p


# ── 6b. fast mode: the spend window belongs to the wave ──────────────────────
# In a fast run a whole wave of tasks is worked at once, one subagent each, and
# every one of them is billed to this session's transcript. A per-task window
# measured all of them against one task's ceiling, and reopened on every
# closure — erasing the spend of the tasks still running. These cases pin the
# per-wave window, and that nothing the model can edit widens it.

WAVE3 = ("- [ ] T1 [standard] first  model=sonnet files=a.py\n"
         "- [ ] T2 [standard] second  model=sonnet files=b.py\n"
         "- [ ] T3 [standard] third  model=sonnet files=c.py\n"
         "- [ ] T4 [mechanical] last  model=haiku after=T1,T2,T3 files=d.py")


# `supervisor: off` in the policies of the ceiling cases: they test the hard
# stop, which is what a project gets with the supervisor switched off. The
# checkpoints have cases of their own, in section 6d.
PARALLEL = ("---\nparallel:\n  default_mode: auto\n  min_wave: 3\n  max_agents: %d\n"
            "budget:\n  supervisor: off\n---\n")


def fast_run(tasks=WAVE3, mode="fast", max_agents=10):
    """A fresh run, $1.00 per task, that the hook has not seen yet."""
    p = Project(tasks=tasks, spend_max=1_000_000)
    if max_agents is not None:
        p.write_policy(PARALLEL % max_agents)
    if mode:
        text = p.raw().replace("status: ACTIVE\n", "status: ACTIVE\nmode: %s\n" % mode, 1)
        open(p.run_path, "w").write(text)
    return p


def spend(p, micro, ts="2026-01-01T00:00:00Z"):
    """One Opus turn costing exactly `micro` ($5/MTok input)."""
    p.write_transcript([("claude-opus-5", {"input_tokens": micro // 5, "output_tokens": 0}, ts)])


def tick(p, *ids):
    text = p.raw()
    for i in ids:
        text = text.replace("- [ ] %s " % i, "- [x] %s " % i)
    open(p.run_path, "w").write(text)


@case("fast mode: a wave of 3 runs on 3x the per-task ceiling, and stops above it")
def _():
    p = fast_run()
    spend(p, 2_500_000)
    p.invoke()
    under = p.state()["status"]
    priv = p.private()
    spend(p, 3_500_000)
    p.invoke()
    st = p.state()
    check("fast mode: a wave of 3 runs on 3x the per-task ceiling, and stops above it",
          under == "ACTIVE" and priv.get("wave") == ["T1", "T2", "T3"]
          and priv.get("spend_max") == 3_000_000
          and st["status"] == "BLOCKED" and "spend ceiling" in st["blocked_reason"]
          and "T1, T2, T3" in st["blocked_reason"],
          "at $2.50: %s, wave=%s max=%s; at $3.50: %s %.80s"
          % (under, priv.get("wave"), priv.get("spend_max"), st["status"],
             st["blocked_reason"]))
    return p


@case("fast mode: closing one task of the wave does NOT reset its window")
def _():
    p = fast_run()
    spend(p, 2_500_000)
    p.invoke()
    tick(p, "T1")
    p.invoke()
    kept = p.private().get("task_started_at")
    spend(p, 3_500_000)
    p.invoke()
    st = p.state()
    check("fast mode: closing one task of the wave does NOT reset its window",
          kept == "2000-01-01T00:00:00Z" and st["status"] == "BLOCKED"
          and "spend ceiling" in st["blocked_reason"],
          "window=%s status=%s — a closure erased the open tasks' spend"
          % (kept, st["status"]))
    return p


@case("fast mode: the window resets when the whole wave closes, at the next width")
def _():
    p = fast_run()
    spend(p, 2_500_000)
    p.invoke()
    tick(p, "T1", "T2", "T3")
    p.invoke()
    priv = p.private()
    history = priv.get("wave_history") or [{}]
    # T4 is mechanical, and a policy with no `tier_multiplier` gets the
    # shipped 0.5: its one-task wave is held at $0.50.
    reopened = (priv.get("wave") == ["T4"] and priv.get("spend_max") == 500_000
                and history[-1].get("wave") == ["T1", "T2", "T3"]
                and history[-1].get("spent") == 2_500_000
                and p.state().get("wave_spend_micro_usd") == "T1,T2,T3=2500000"
                and priv.get("task_started_at") != "2000-01-01T00:00:00Z"
                and p.state()["status"] == "ACTIVE")
    # The next wave is one task wide, so $1.50 inside its window is over.
    spend(p, 1_500_000, ts="2099-01-01T00:00:00Z")
    p.invoke()
    st = p.state()
    check("fast mode: the window resets when the whole wave closes, at the next width",
          reopened and st["status"] == "BLOCKED" and "T4" in st["blocked_reason"],
          "wave=%s max=%s window=%s history=%s; then %s %.80s"
          % (priv.get("wave"), priv.get("spend_max"), priv.get("task_started_at"),
             priv.get("wave_history"),
             st["status"], st["blocked_reason"]))
    return p


@case("fast mode: flipping `mode:` to fast mid-run does not raise the ceiling")
def _():
    p = fast_run(mode=None)
    spend(p, 500_000)
    p.invoke()
    text = p.raw().replace("status: ACTIVE\n", "status: ACTIVE\nmode: fast\n", 1)
    open(p.run_path, "w").write(text)
    spend(p, 2_500_000)
    p.invoke()
    st = p.state()
    check("fast mode: flipping `mode:` to fast mid-run does not raise the ceiling",
          p.private().get("mode") == "economy" and st["status"] == "BLOCKED"
          and "spend ceiling" in st["blocked_reason"],
          "mode=%s status=%s" % (p.private().get("mode"), st["status"]))
    return p


@case("fast mode: deleting `after=` mid-run neither widens the next wave nor re-plans")
def _():
    # The edit only matters once a wave closes and the next one is computed, so
    # that is what this case does. Read live, the edited file would make the
    # next wave T2, T3, T4 at $3.00; captured, it is T2, T3 at $2.00.
    chain = ("- [ ] T1 [standard] first  model=sonnet files=a.py\n"
             "- [ ] T2 [standard] second  model=sonnet after=T1 files=b.py\n"
             "- [ ] T3 [standard] third  model=sonnet after=T1 files=c.py\n"
             "- [ ] T4 [standard] fourth  model=sonnet after=T2 files=d.py")
    p = fast_run(tasks=chain)
    spend(p, 500_000)
    p.invoke()
    before = p.private()
    text = p.raw().replace(" after=T1", "").replace(" after=T2", "")
    open(p.run_path, "w").write(text)
    tick(p, "T1")
    p.invoke()
    after = p.private()
    spend(p, 2_500_000, ts="2099-01-01T00:00:00Z")
    p.invoke()
    st = p.state()
    check("fast mode: deleting `after=` mid-run neither widens the next wave nor re-plans",
          before.get("wave") == ["T1"] and after.get("wave") == ["T2", "T3"]
          and after.get("spend_max") == 2_000_000
          and after.get("fingerprint") == before.get("fingerprint")
          and st["status"] == "BLOCKED" and "spend ceiling" in st["blocked_reason"],
          "wave %s -> %s at %s, same run=%s, status=%s"
          % (before.get("wave"), after.get("wave"), after.get("spend_max"),
             after.get("fingerprint") == before.get("fingerprint"), st["status"]))
    return p


@case("a run file without `mode:` keeps the per-task window, unchanged")
def _():
    import hashlib
    p = fast_run(tasks="- [ ] T1 open\n- [ ] T2 open\n- [ ] T3 open", mode=None)
    spend(p, 2_500_000)
    p.invoke()
    st = p.state()
    priv = p.private()
    # Old run files must also fingerprint exactly as they did, or every state
    # file in flight would read as a re-plan on upgrade and reset its counters.
    old = hashlib.sha256("T1 open\nT2 open\nT3 open".encode()).hexdigest()
    check("a run file without `mode:` keeps the per-task window, unchanged",
          priv.get("mode") == "economy" and priv.get("spend_max") == 1_000_000
          and priv.get("fingerprint") == old and st["status"] == "BLOCKED"
          and st["blocked_reason"].startswith("T1 reached its spend ceiling"),
          "mode=%s max=%s same-fingerprint=%s status=%s %.60s"
          % (priv.get("mode"), priv.get("spend_max"), priv.get("fingerprint") == old,
             st["status"], st["blocked_reason"]))
    return p


@case("fast mode: the mid-turn guard holds the wave's ceiling, not one task's")
def _():
    p = fast_run()
    spend(p, 100_000)
    p.invoke()
    spend(p, 2_500_000)
    _, under = p.invoke_pretool()
    spend(p, 3_500_000)
    # Same byte length as the $2.50 transcript, so the mid-turn cache would
    # answer for it; that cache is not what this case is about.
    os.unlink(os.path.join(p.dir, ".efficiency", "midturn-cache.json"))
    _, over = p.invoke_pretool()
    check("fast mode: the mid-turn guard holds the wave's ceiling, not one task's",
          p.decision(under) is None and p.decision(over) == "deny",
          "at $2.50: %s, at $3.50: %s" % (p.decision(under), p.decision(over)))
    return p


@case("fast mode: the first turn, before the Stop hook has seen the run, is held at 3x")
def _():
    # Nothing is captured yet, so the mid-turn guard sizes the first window from
    # the run file and the policy. In a fast run that turn dispatches the whole
    # first wave: held at one task's ceiling, it would refuse its own dispatch.
    p = fast_run()
    spend(p, 2_500_000)
    _, under = p.invoke_pretool()
    os.unlink(os.path.join(p.dir, ".efficiency", "midturn-cache.json"))
    spend(p, 3_500_000)
    _, over = p.invoke_pretool()
    e = fast_run(mode=None)
    spend(e, 1_500_000)
    _, economy = e.invoke_pretool()
    e.close()
    check("fast mode: the first turn, before the Stop hook has seen the run, is held at 3x",
          not p.private() and p.decision(under) is None and p.decision(over) == "deny"
          and p.decision(economy) == "deny",
          "fast at $2.50: %s, at $3.50: %s; economy at $1.50: %s"
          % (p.decision(under), p.decision(over), p.decision(economy)))
    return p

@case("fast mode: a task with no `files=` runs alone, so its window is 1x")
def _():
    tasks = ("- [ ] T1 [standard] touches anything  model=sonnet\n"
             + "".join("- [ ] T%d [standard] free  model=sonnet files=f%d.py\n" % (i, i)
                       for i in range(2, 6)))
    p = fast_run(tasks=tasks)
    spend(p, 1_500_000)
    p.invoke()
    priv = p.private()
    st = p.state()
    check("fast mode: a task with no `files=` runs alone, so its window is 1x",
          priv.get("wave") == ["T1"] and priv.get("spend_max") == 1_000_000
          and st["status"] == "BLOCKED" and "spend ceiling" in st["blocked_reason"],
          "wave=%s max=%s status=%s" % (priv.get("wave"), priv.get("spend_max"), st["status"]))
    return p


@case("fast mode: overlapping `files=` split the wave, globs included")
def _():
    tasks = ("- [ ] T1 [standard] a  model=sonnet files=src/**\n"
             "- [ ] T2 [standard] b  model=sonnet files=src/x/a.py\n"
             "- [ ] T3 [standard] c  model=sonnet files=docs/b.md")
    p = fast_run(tasks=tasks)
    spend(p, 2_500_000)
    p.invoke()
    priv = p.private()
    st = p.state()
    check("fast mode: overlapping `files=` split the wave, globs included",
          priv.get("wave") == ["T1", "T3"] and priv.get("spend_max") == 2_000_000
          and st["status"] == "BLOCKED",
          "wave=%s max=%s status=%s" % (priv.get("wave"), priv.get("spend_max"), st["status"]))
    return p


@case("fast mode: max_agents caps the wave, and raising it mid-run buys nothing")
def _():
    # Five free tasks, two at a time. After the policy is raised to 10 and the
    # first wave closes, a live read would make the next wave T3, T4, T5 at
    # $3.00; the captured cap keeps it at T3, T4 and $2.00.
    tasks = "".join("- [ ] T%d [standard] free  model=sonnet files=f%d.py\n" % (i, i)
                    for i in range(1, 6))
    p = fast_run(tasks=tasks, max_agents=2)
    spend(p, 500_000)
    p.invoke()
    capped = p.private().get("wave")
    p.write_policy(PARALLEL % 10)
    tick(p, "T1", "T2")
    p.invoke()
    nxt = p.private()
    spend(p, 2_500_000, ts="2099-01-01T00:00:00Z")
    p.invoke()
    st = p.state()
    check("fast mode: max_agents caps the wave, and raising it mid-run buys nothing",
          capped == ["T1", "T2"] and nxt.get("wave") == ["T3", "T4"]
          and nxt.get("spend_max") == 2_000_000
          and st["status"] == "BLOCKED" and "spend ceiling" in st["blocked_reason"],
          "wave %s -> %s at %s, status=%s"
          % (capped, nxt.get("wave"), nxt.get("spend_max"), st["status"]))
    return p


@case("fast mode: a policy that cannot be read caps every wave at one task")
def _():
    p = fast_run(max_agents=None)
    spend(p, 1_500_000)
    p.invoke()
    st = p.state()
    check("fast mode: a policy that cannot be read caps every wave at one task",
          p.private().get("wave") == ["T1"] and st["status"] == "BLOCKED",
          "wave=%s status=%s" % (p.private().get("wave"), st["status"]))
    return p


def first_wave(tasks, policy=PARALLEL % 10):
    """The wave the Stop hook captures for a fresh fast run, and its ceiling."""
    p = fast_run(tasks=tasks, max_agents=None)
    if policy is not None:
        p.write_policy(policy)
    spend(p, 100_000)
    p.invoke()
    priv = p.private()
    p.close()
    return priv.get("wave"), priv.get("spend_max")


@case("fast mode: a policy from before 0.21, with no `parallel:` block, gets 10")
def _():
    tasks = "".join("- [ ] T%d [standard] free  model=sonnet files=f%d.py\n" % (i, i)
                    for i in range(1, 13))
    wave, ceiling = first_wave(tasks, policy="---\ngate: \"make check\"\n---\n\n# Defaults\n")
    check("fast mode: a policy from before 0.21, with no `parallel:` block, gets 10",
          wave == ["T%d" % i for i in range(1, 11)] and ceiling == 10_000_000,
          "wave=%s max=%s" % (wave, ceiling))


@case("fast mode: a policy that exists but cannot be parsed caps every wave at one")
def _():
    results = {}
    for name, policy in (("no frontmatter", "parallel:\n  max_agents: 10\n"),
                         ("unclosed", "---\nparallel:\n  max_agents: 10\n"),
                         ("not a number", "---\nparallel:\n  max_agents: ten\n---\n")):
        results[name] = first_wave(WAVE3, policy=policy)
    check("fast mode: a policy that exists but cannot be parsed caps every wave at one",
          all(r == (["T1"], 1_000_000) for r in results.values()), "got %s" % results)


@case("fast mode: a task with no `files=` further down waits for a wave of its own")
def _():
    wave, ceiling = first_wave("- [ ] T1 [standard] a  model=sonnet files=a.py\n"
                               "- [ ] T2 [standard] b  model=sonnet\n"
                               "- [ ] T3 [standard] c  model=sonnet files=c.py")
    check("fast mode: a task with no `files=` further down waits for a wave of its own",
          wave == ["T1", "T3"] and ceiling == 2_000_000, "wave=%s max=%s" % (wave, ceiling))


# Each spelling is tested against `src/a.py` and must land in a separate wave.
# The last two are the branches fnmatch alone misses: a literal stem shared
# with a pattern it cannot parse, and a directory that contains the file.
OVERLAPS = (
    ("./src/a.py", "a leading ./"),
    ("/abs/src/a.py", "an absolute path ending with the relative one"),
    ("src/{a,b}.py", "a brace pattern"),
    ("SRC/a.py", "a different case"),
    ("src", "a directory containing it"),
)


@case("fast mode: overlapping spellings of one path never share a wave")
def _():
    for other, why in OVERLAPS:
        wave, _ceiling = first_wave(
            "- [ ] T1 [standard] a  model=sonnet files=src/a.py\n"
            "- [ ] T2 [standard] b  model=sonnet files=%s\n"
            "- [ ] T3 [standard] c  model=sonnet files=z.py" % other)
        check("fast mode: %s overlaps src/a.py (%s)" % (other, why),
              wave == ["T1", "T3"], "wave=%s" % wave)
    # The stem branch: a pattern whose literal stem the other starts with,
    # where neither fnmatch direction matches.
    wave, _ceiling = first_wave(
        "- [ ] T1 [standard] a  model=sonnet files=src/a*\n"
        "- [ ] T2 [standard] b  model=sonnet files=src/[a]x.py\n"
        "- [ ] T3 [standard] c  model=sonnet files=z.py")
    check("fast mode: src/a* overlaps src/[a]x.py by their stems, not by fnmatch",
          wave == ["T1", "T3"], "wave=%s" % wave)
    # And a path that is really elsewhere still shares the wave.
    wave, _ceiling = first_wave(
        "- [ ] T1 [standard] a  model=sonnet files=src/a.py\n"
        "- [ ] T2 [standard] b  model=sonnet files=/abs/lib/b.py\n"
        "- [ ] T3 [standard] c  model=sonnet files=z.py")
    check("fast mode: unrelated absolute and relative paths still share a wave",
          wave == ["T1", "T2", "T3"], "wave=%s" % wave)


@case("rule 2: a hand-edited state file in the wrong shapes does not crash the hook")
def _():
    p = fast_run()
    spend(p, 100_000)
    p.invoke()
    tick(p, "T1", "T2", "T3")
    state = p.private()
    state.update(deps={"T2": 5, "T4": 5}, files={"T4": 7},
                 wave_history=[{"wave": [1], "spent": 3}, "junk"])
    with open(os.path.join(p.dir, ".efficiency", "autopilot.json"), "w") as fh:
        json.dump(state, fh)
    code, out = p.invoke()
    check("rule 2: a hand-edited state file in the wrong shapes does not crash the hook",
          code == 0 and out and p.private().get("wave") == []
          and p.state().get("wave_spend_micro_usd", "").startswith("1=3; T1,T2,T3="),
          "code=%s out=%.80s wave=%s spend=%s" % (code, out, p.private().get("wave"),
                                                 p.state().get("wave_spend_micro_usd")))
    return p


# ── 6c. the ceiling scales by the task's tier ────────────────────────────────
# One flat per-task figure either strangles critical work or lets a mechanical
# task loop for a long time. Each task's ceiling is the base times its tier's
# multiplier — captured on first sight, like everything else that sizes a
# ceiling, so neither a relabel nor a policy edit mid-run buys anything.

NO_BUDGET = "---\ngate: \"make check\"\nbudget:\n  supervisor: off\n---\n"
BUDGET = "---\nbudget:\n  task_usd: 1.00\n  tier_multiplier: %s\n  supervisor: off\n---\n"


def tier_run(tasks, policy=NO_BUDGET, mode=None):
    """A fresh run at $1.00 per task, with the policy given."""
    p = fast_run(tasks=tasks, mode=mode, max_agents=None)
    if policy is not None:
        p.write_policy(policy)
    return p


def held_at(p, under, over, ts="2026-01-01T00:00:00Z"):
    """(status after spending `under`, status after spending `over`)."""
    spend(p, under, ts=ts)
    p.invoke()
    first = p.state()["status"]
    spend(p, over, ts=ts)
    p.invoke()
    return first, p.state()["status"]


@case("tiers: a critical task is held at 4x the per-task ceiling, and not below")
def _():
    p = tier_run("- [ ] T1 [critical] risky  model=sonnet")
    under, over = held_at(p, 3_900_000, 4_100_000)
    check("tiers: a critical task is held at 4x the per-task ceiling, and not below",
          under == "ACTIVE" and over == "BLOCKED" and p.private().get("spend_max") == 4_000_000
          and "spend ceiling" in p.state()["blocked_reason"],
          "at $3.90: %s, at $4.10: %s, max=%s" % (under, over, p.private().get("spend_max")))
    return p


@case("tiers: a mechanical task is held at 0.5x")
def _():
    p = tier_run("- [ ] T1 [mechanical] rename  model=haiku")
    under, over = held_at(p, 400_000, 600_000)
    check("tiers: a mechanical task is held at 0.5x",
          under == "ACTIVE" and over == "BLOCKED" and p.private().get("spend_max") == 500_000,
          "at $0.40: %s, at $0.60: %s, max=%s" % (under, over, p.private().get("spend_max")))
    return p


@case("tiers: relabelling a task [critical] mid-run, or raising the policy, buys nothing")
def _():
    # The relabel only matters once T2's window opens, so T1 closes first and
    # the next window is computed. Read live, T2 would get $4.00 — or $10.00
    # from the edited policy; captured, it is a standard task at $1.00.
    p = tier_run("- [ ] T1 [standard] first  model=sonnet\n"
                 "- [ ] T2 [standard] second  model=sonnet")
    spend(p, 100_000)
    p.invoke()
    before = p.private()
    text = p.raw().replace("T2 [standard]", "T2 [critical]")
    open(p.run_path, "w").write(text)
    p.write_policy(BUDGET % "{ critical: 10 }")
    tick(p, "T1")
    p.invoke()
    after = p.private()
    spend(p, 1_500_000, ts="2099-01-01T00:00:00Z")
    p.invoke()
    st = p.state()
    check("tiers: relabelling a task [critical] mid-run, or raising the policy, buys nothing",
          after.get("fingerprint") == before.get("fingerprint")
          and after.get("task_started_at") != before.get("task_started_at")
          and after.get("spend_max") == 1_000_000
          and after.get("tiers", {}).get("T2") == "standard"
          and st["status"] == "BLOCKED" and "spend ceiling" in st["blocked_reason"],
          "same run=%s, window moved=%s, max=%s, tier=%s, status=%s"
          % (after.get("fingerprint") == before.get("fingerprint"),
             after.get("task_started_at") != before.get("task_started_at"),
             after.get("spend_max"), after.get("tiers"), st["status"]))
    return p


@case("tiers: closing a task moves the economy window to the next task's tier")
def _():
    p = tier_run("- [ ] T1 [standard] first  model=sonnet\n"
                 "- [ ] T2 [critical] second  model=sonnet")
    spend(p, 100_000)
    p.invoke()
    first = p.private().get("spend_max")
    tick(p, "T1")
    p.invoke()
    nxt = p.private().get("spend_max")
    under, over = held_at(p, 3_900_000, 4_100_000, ts="2099-01-01T00:00:00Z")
    check("tiers: closing a task moves the economy window to the next task's tier",
          first == 1_000_000 and nxt == 4_000_000 and under == "ACTIVE" and over == "BLOCKED",
          "max %s -> %s; at $3.90: %s, at $4.10: %s" % (first, nxt, under, over))
    return p


@case("tiers: a fast wave of [critical, mechanical] is held at 4.5x, mid-turn too")
def _():
    tasks = ("- [ ] T1 [critical] a  model=sonnet files=a.py\n"
             "- [ ] T2 [mechanical] b  model=haiku files=b.py")
    p = tier_run(tasks, policy=NO_BUDGET + "\n", mode="fast")
    p.write_policy(PARALLEL % 10)
    # The first turn, before the Stop hook has captured anything.
    spend(p, 4_400_000)
    _, first_under = p.invoke_pretool()
    os.unlink(os.path.join(p.dir, ".efficiency", "midturn-cache.json"))
    spend(p, 4_600_000)
    _, first_over = p.invoke_pretool()
    under, over = held_at(p, 4_400_000, 4_600_000)
    priv = p.private()
    check("tiers: a fast wave of [critical, mechanical] is held at 4.5x, mid-turn too",
          p.decision(first_under) is None and p.decision(first_over) == "deny"
          and priv.get("wave") == ["T1", "T2"] and priv.get("spend_max") == 4_500_000
          and under == "ACTIVE" and over == "BLOCKED",
          "first turn %s/%s; wave=%s max=%s; at $4.40: %s, at $4.60: %s"
          % (p.decision(first_under), p.decision(first_over), priv.get("wave"),
             priv.get("spend_max"), under, over))
    return p


@case("tiers: the mid-turn guard holds a critical task's first turn at 4x")
def _():
    p = tier_run("- [ ] T1 [critical] risky  model=sonnet")
    spend(p, 3_900_000)
    _, under = p.invoke_pretool()
    os.unlink(os.path.join(p.dir, ".efficiency", "midturn-cache.json"))
    spend(p, 4_100_000)
    _, over = p.invoke_pretool()
    check("tiers: the mid-turn guard holds a critical task's first turn at 4x",
          not p.private() and p.decision(under) is None and p.decision(over) == "deny",
          "at $3.90: %s, at $4.10: %s" % (p.decision(under), p.decision(over)))
    return p


def captured_multipliers(policy):
    p = tier_run("- [ ] T1 [critical] x  model=sonnet", policy=policy)
    spend(p, 100_000)
    p.invoke()
    priv = p.private()
    p.close()
    return priv.get("multipliers"), priv.get("spend_max")


# The hook's own fallback, not a restatement of it: whether those numbers are
# the ones the shipped policy documents carry is the next case's question.
DEFAULTS = dict(HOOK_MODULE.DEFAULT_TIER_MULTIPLIER)


def shipped_policies():
    """{label: policy text} for every policy this plugin hands a project.

    The template, and the skeleton `init` writes out inline because a session
    cannot read the plugin's own files. Either one drifting from the hook's
    fallback means a pre-0.21 policy and a fresh one run under different numbers.
    """
    template = open(os.path.join(PLUGIN, "templates", "efficiency.md")).read()
    skill = open(os.path.join(PLUGIN, "skills", "init", "SKILL.md")).read()
    fence = "````markdown\n"
    start = skill.index(fence) + len(fence)
    skeleton = skill[start:skill.index("\n````", start)]
    return {"templates/efficiency.md": template, "skills/init/SKILL.md": skeleton}


def shipped_defaults_drift(policies):
    """[(label, what, read, hook default)] wherever a shipped policy disagrees."""
    drift = []
    for label, text in sorted(policies.items()):
        p = Project(run_file=False).write_policy(text)
        try:
            tiers = HOOK_MODULE.policy_tier_multipliers(p.dir)
            agents = HOOK_MODULE.policy_max_agents(p.dir)
        finally:
            p.close()
        if tiers != HOOK_MODULE.DEFAULT_TIER_MULTIPLIER:
            drift.append((label, "tier_multiplier", tiers,
                          HOOK_MODULE.DEFAULT_TIER_MULTIPLIER))
        if agents != HOOK_MODULE.DEFAULT_MAX_AGENTS:
            drift.append((label, "max_agents", agents, HOOK_MODULE.DEFAULT_MAX_AGENTS))
    return drift


@case("tiers: the hook's fallbacks are the values the shipped policies write")
def _():
    # The hook falls back to DEFAULT_TIER_MULTIPLIER and DEFAULT_MAX_AGENTS for a
    # policy that predates the keys; the template and init's skeleton write them
    # out for a policy that does not. Three copies of one fact, and until this
    # case nothing compared them. The mutated copy proves the comparison bites.
    policies = shipped_policies()
    drift = shipped_defaults_drift(policies)
    mutated = shipped_defaults_drift({
        "mutated template": policies["templates/efficiency.md"]
        .replace("critical: 4 }", "critical: 3 }", 1)
        .replace("max_agents: 10", "max_agents: 9", 1)})
    check("tiers: the hook's fallbacks are the values the shipped policies write",
          not drift and [d[1] for d in mutated] == ["tier_multiplier", "max_agents"],
          "drift: %s; mutated copy caught: %s" % (drift, mutated))


@case("tiers: a policy with no tier_multiplier gets the shipped defaults")
def _():
    results = {
        "no budget block": captured_multipliers(NO_BUDGET),
        "budget without the key": captured_multipliers(
            "---\nbudget:\n  task_usd: 5.00\n  continuations: 40\nrouting:\n"
            "  tier_multiplier: { critical: 9 }\n---\n"),
    }
    check("tiers: a policy with no tier_multiplier gets the shipped defaults",
          all(r == (DEFAULTS, int(DEFAULTS["critical"] * 1_000_000)) for r in results.values()), "got %s" % results)


@case("tiers: a tier_multiplier that cannot be parsed scales by 1")
def _():
    flat = dict((t, 1.0) for t in DEFAULTS)
    results = {
        "not a map": captured_multipliers(BUDGET % "lots"),
        "no colon": captured_multipliers(BUDGET % "{ critical 4 }"),
        "empty block": captured_multipliers("---\nbudget:\n  tier_multiplier:\n---\n"),
        "no frontmatter": captured_multipliers("budget:\n  tier_multiplier: { critical: 4 }\n"),
        "no policy": captured_multipliers(None),
    }
    bad = {"negative": captured_multipliers(BUDGET % "{ mechanical: 0.5, critical: -4 }"),
           "text": captured_multipliers(BUDGET % "{ mechanical: 0.5, critical: four }"),
           "nan": captured_multipliers(BUDGET % "{ mechanical: 0.5, critical: nan }"),
           "absent": captured_multipliers(BUDGET % "{ mechanical: 0.5 }")}
    one_off = dict(flat, mechanical=0.5)
    check("tiers: a tier_multiplier that cannot be parsed scales by 1",
          all(r == (flat, 1_000_000) for r in results.values())
          and all(r == (one_off, 1_000_000) for r in bad.values()),
          "whole map: %s; one tier: %s" % (results, bad))


@case("tiers: a multiplier of 1000 is capped at 10, in either form")
def _():
    flow = captured_multipliers(BUDGET % "{ critical: 1000 }")
    block = captured_multipliers("---\nbudget:\n  task_usd: 1.00\n  tier_multiplier:\n"
                                 "    mechanical: 0.25   # cheap\n    critical: 1000\n"
                                 "gate: \"\"\n---\n")
    check("tiers: a multiplier of 1000 is capped at 10, in either form",
          flow[1] == 10_000_000 and block[1] == 10_000_000
          and block[0].get("mechanical") == 0.25,
          "flow=%s block=%s" % (flow, block))


@case("tiers: an untagged task, or an unknown tier, scales by 1")
def _():
    results = {}
    for tasks in ("- [ ] T1 untagged  model=sonnet", "- [ ] T1 [urgent] x  model=sonnet"):
        p = tier_run(tasks)
        spend(p, 100_000)
        p.invoke()
        results[tasks] = p.private().get("spend_max")
        p.close()
    check("tiers: an untagged task, or an unknown tier, scales by 1",
          all(v == 1_000_000 for v in results.values()), "got %s" % results)


@case("tiers: a state file from before tiers keeps its counters and its ceiling")
def _():
    # Its fingerprint included the tag. Read as a re-plan, the upgrade would
    # zero every counter of a run in flight and hand it a fresh window at 4x.
    import hashlib
    p = tier_run("- [ ] T1 [critical] x  model=sonnet")
    legacy = hashlib.sha256("T1 [critical] x  model=sonnet".encode()).hexdigest()
    state = {"fingerprint": legacy, "task_key": legacy, "open_tasks_sig": legacy,
             "continuations_used": 7, "continuations_max": 40, "gate_retries": 0,
             "gate_retries_max": 2, "spend_max": 1_000_000,
             "task_started_at": "2000-01-01T00:00:00Z", "same_task_blocks": 2,
             "blocked": False, "blocked_reason": ""}
    with open(os.path.join(p.dir, ".efficiency", "autopilot.json"), "w") as fh:
        json.dump(state, fh)
    spend(p, 1_500_000)
    p.invoke()
    priv = p.private()
    st = p.state()
    check("tiers: a state file from before tiers keeps its counters and its ceiling",
          priv.get("continuations_used") == 7 and priv.get("spend_max") == 1_000_000
          and priv.get("task_started_at") == "2000-01-01T00:00:00Z"
          and st["status"] == "BLOCKED" and "spend ceiling" in st["blocked_reason"],
          "used=%s max=%s window=%s status=%s"
          % (priv.get("continuations_used"), priv.get("spend_max"),
             priv.get("task_started_at"), st["status"]))
    return p


@case("rule 2: captured tiers edited into the wrong shapes scale by 1, no crash")
def _():
    p = tier_run("- [ ] T1 [critical] a  model=sonnet\n- [ ] T2 [critical] b  model=sonnet")
    spend(p, 100_000)
    p.invoke()
    state = p.private()
    state.update(tiers={"T2": 5}, multipliers={"critical": "x"}, order="T2")
    with open(os.path.join(p.dir, ".efficiency", "autopilot.json"), "w") as fh:
        json.dump(state, fh)
    tick(p, "T1")
    code, out = p.invoke()
    check("rule 2: captured tiers edited into the wrong shapes scale by 1, no crash",
          code == 0 and out and p.private().get("spend_max") == 1_000_000,
          "code=%s out=%.80s max=%s" % (code, out, p.private().get("spend_max")))
    return p


# ── 6d. checkpoints: the supervisor decides, the hook keeps the leash ────────
# A ceiling used to stop a run whether it was converging or looping. With a
# supervisor captured, each count-based guard holds a checkpoint instead: the
# fake `claude` on PATH plays the supervisor, and these cases prove both what
# it can grant and what it cannot override.

SUP = "---\nbudget:\n  supervisor: sonnet\n---\n"


def sup_run(tasks="- [ ] T1 do a thing\n- [ ] T2 then another", spend_max=1_000_000,
            used_max=40, policy=SUP):
    p = Project(tasks=tasks, spend_max=spend_max, used_max=used_max)
    p.write_policy(policy)
    return p


def verdict(p, word, why="the diff adds the parser the task asks for", cost=0.01):
    with open(os.path.join(p.bin, "reply.json"), "w") as fh:
        json.dump({"total_cost_usd": cost,
                   "structured_output": {"verdict": word, "why": why}}, fh)


def calls(p):
    try:
        return int(open(os.path.join(p.bin, "calls")).read().strip())
    except (OSError, ValueError):
        return 0


def git_repo(p):
    """Make the project a repository whose only work is what a case writes."""
    for cmd in (["git", "init", "-q"], ["git", "config", "user.email", "t@t"],
                ["git", "config", "user.name", "t"]):
        subprocess.run(cmd, cwd=p.dir, check=True, capture_output=True)
    with open(os.path.join(p.dir, ".git", "info", "exclude"), "a") as fh:
        fh.write("bin/\ntranscript.jsonl\ntranscript/\n.claude/\n")
    open(os.path.join(p.dir, "a.py"), "w").write("x = 1\n")
    subprocess.run(["git", "add", "a.py"], cwd=p.dir, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=p.dir, check=True, capture_output=True)


@case("checkpoint: a converging verdict at the spend ceiling grants one more tranche")
def _():
    p = sup_run()
    verdict(p, "converging")
    spend(p, 1_200_000)
    code, out = p.invoke()
    priv, st = p.private(), p.state()
    check("checkpoint: a converging verdict at the spend ceiling grants one more tranche",
          code == 0 and out.get("decision") == "block" and st["status"] == "ACTIVE"
          and calls(p) == 1 and priv.get("spend_max") == 2_200_000
          and "Supervisor checkpoint" in out.get("reason", "")
          and "the diff adds the parser" in out.get("reason", ""),
          "status=%s calls=%s max=%s reason=%r" % (st["status"], calls(p),
                                                   priv.get("spend_max"), out.get("reason", "")[-300:]))
    return p


@case("checkpoint: the supervisor's own cost is charged to the run and to the window")
def _():
    p = sup_run()
    verdict(p, "converging", cost=0.25)
    spend(p, 1_200_000)
    p.invoke()
    priv, st = p.private(), p.state()
    # The window was extended to $2.20. The transcript now says $2.00, under it;
    # with the $0.25 verdict added the window holds $2.25, over it.
    spend(p, 2_000_000)
    p.invoke()
    reason = p.state()["blocked_reason"]
    check("checkpoint: the supervisor's own cost is charged to the run and to the window",
          priv.get("supervisor_spend_micro") == 250_000
          and st.get("supervisor_spend_micro_usd") == "250000"
          and "$2.25 of $2.20" in reason,
          "charged=%s mirrored=%s then %s" % (priv.get("supervisor_spend_micro"),
                                              st.get("supervisor_spend_micro_usd"), reason))
    return p


@case("checkpoint: a looping verdict stops the run, with the supervisor's reason")
def _():
    p = sup_run()
    verdict(p, "looping", why="the same test edit is made and reverted three times")
    spend(p, 1_200_000)
    p.invoke()
    st = p.state()
    check("checkpoint: a looping verdict stops the run, with the supervisor's reason",
          st["status"] == "BLOCKED" and "looping" in st["blocked_reason"]
          and "made and reverted" in st["blocked_reason"]
          and p.private().get("spend_max") == 1_000_000,
          "status=%s reason=%s" % (st["status"], st["blocked_reason"]))
    return p


@case("checkpoint: a supervisor that cannot answer stops the run — fail closed")
def _():
    p = sup_run()               # no reply.json: the fake exits 1 with no output
    spend(p, 1_200_000)
    p.invoke()
    first = p.state()
    q = sup_run()
    with open(os.path.join(q.bin, "reply.json"), "w") as fh:
        json.dump({"total_cost_usd": 0.02, "is_error": True}, fh)
    spend(q, 1_200_000)
    q.invoke()
    second = q.state()
    check("checkpoint: a supervisor that cannot answer stops the run — fail closed",
          first["status"] == "BLOCKED" and "no cost" in first["blocked_reason"]
          and second["status"] == "BLOCKED" and "without a verdict" in second["blocked_reason"]
          and q.private().get("supervisor_spend_micro") == 20_000,
          "no reply: %s / %s · no verdict: %s / %s, charged %s"
          % (first["status"], first["blocked_reason"], second["status"],
             second["blocked_reason"], q.private().get("supervisor_spend_micro")))
    q.close()
    return p


@case("checkpoint: spend without progress asks the supervisor before the ceiling")
def _():
    p = sup_run()
    verdict(p, "looping", why="nothing in the tree has changed")
    spend(p, 600_000)           # 60% of the window, no task closed, no repository
    p.invoke()
    st = p.state()
    check("checkpoint: spend without progress asks the supervisor before the ceiling",
          calls(p) == 1 and st["status"] == "BLOCKED"
          and "spend without progress" in st["blocked_reason"],
          "calls=%s status=%s reason=%s" % (calls(p), st["status"], st["blocked_reason"]))
    return p


@case("checkpoint: under the idle share, the supervisor is not asked at all")
def _():
    p = sup_run()
    verdict(p, "looping")
    spend(p, 400_000)
    code, out = p.invoke()
    check("checkpoint: under the idle share, the supervisor is not asked at all",
          calls(p) == 0 and p.state()["status"] == "ACTIVE" and out.get("decision") == "block",
          "calls=%s status=%s" % (calls(p), p.state()["status"]))
    return p


@case("checkpoint: two checkpoints with no progress between them stop without asking")
def _():
    # The stall guard as a checkpoint: block 6 asks and the verdict is
    # converging, so the counter resets; nothing closes and nothing changes on
    # disk, so the next checkpoint, five blocks on, has no work to show and stops
    # the run without spending on a second verdict. Still inside the platform's
    # cap on blocks without a tool call, which a real session resets anyway.
    p = sup_run(spend_max=0)
    verdict(p, "converging")
    stopped = stall_until_stopped(p, limit=20)
    st = p.state()
    check("checkpoint: two checkpoints with no progress between them stop without asking",
          stopped == 11 and calls(p) == 1 and "no new change" in st["blocked_reason"],
          "stopped at %s, calls=%s, reason=%s" % (stopped, calls(p), st["blocked_reason"]))
    return p


@case("checkpoint: progress between checkpoints earns the next verdict")
def _():
    p = sup_run()
    git_repo(p)
    verdict(p, "converging")
    spend(p, 1_200_000)
    p.invoke()
    open(os.path.join(p.dir, "b.py"), "w").write("def parse():\n    return 1\n")
    spend(p, 2_300_000)
    p.invoke()
    st = p.state()
    check("checkpoint: progress between checkpoints earns the next verdict",
          calls(p) == 2 and st["status"] == "ACTIVE"
          and p.private().get("barren_checkpoints") == 0,
          "calls=%s status=%s barren=%s reason=%s" % (calls(p), st["status"],
                                                      p.private().get("barren_checkpoints"),
                                                      st.get("blocked_reason")))
    return p


@case("checkpoint: an edit undone and redone is not progress twice")
def _():
    p = sup_run()
    git_repo(p)
    path = os.path.join(p.dir, "a.py")
    spend(p, 100_000)                           # a measurable window, well under idle
    p.invoke()                                  # capture: the base state is seen
    open(path, "w").write("x = 2\n")
    p.invoke()
    moved = p.private().get("progress_since_checkpoint")
    p.seed_private(**dict(p.private(), progress_since_checkpoint=False))
    open(path, "w").write("x = 1\n")            # back to the base
    p.invoke()
    back = p.private().get("progress_since_checkpoint")
    open(path, "w").write("x = 2\n")            # and forward again
    p.invoke()
    again = p.private().get("progress_since_checkpoint")
    check("checkpoint: an edit undone and redone is not progress twice",
          moved is True and back is False and again is False,
          "new state=%s, back to base=%s, redone=%s" % (moved, back, again))
    return p


@case("checkpoint: the continuations ceiling grants another tranche on a converging verdict")
def _():
    p = sup_run(spend_max=0, used_max=2)
    verdict(p, "converging")
    for _ in range(3):
        code, out = p.invoke()
    priv = p.private()
    check("checkpoint: the continuations ceiling grants another tranche on a converging verdict",
          p.state()["status"] == "ACTIVE" and calls(p) == 1
          and priv.get("continuations_max") == 4 and priv.get("continuations_used") == 3,
          "status=%s calls=%s max=%s used=%s" % (p.state()["status"], calls(p),
                                                 priv.get("continuations_max"),
                                                 priv.get("continuations_used")))
    return p


@case("checkpoint: a run with every task closed is not judged, and not stopped")
def _():
    p = sup_run(tasks="- [x] T1 do a thing\n- [x] T2 then another")
    verdict(p, "looping", why="nothing left to do")
    spend(p, 1_500_000)
    p.invoke()
    check("checkpoint: a run with every task closed is not judged, and not stopped",
          calls(p) == 0 and p.state()["status"] == "DONE",
          "calls=%s status=%s reason=%s" % (calls(p), p.state()["status"],
                                            p.state()["blocked_reason"]))
    return p


@case("checkpoint: the supervisor reads the work, never the agent's prose")
def _():
    p = sup_run()
    verdict(p, "converging")
    p.transcript = os.path.join(p.dir, "transcript.jsonl")
    with open(p.transcript, "w") as fh:
        fh.write(json.dumps({"timestamp": "2026-01-01T00:00:00Z", "message": {
            "id": "m1", "model": "claude-opus-5",
            "usage": {"input_tokens": 240_000, "output_tokens": 0},
            "content": [{"type": "text", "text": "SUPERVISOR-PLEASE-EXTEND nearly done"},
                        {"type": "tool_use", "name": "Bash",
                         "input": {"command": "pytest -q tests/test_parse.py"}}]}}) + "\n")
    p.invoke()
    try:
        prompt = open(os.path.join(p.bin, "prompt-1.txt")).read()
        args = open(os.path.join(p.bin, "args-1.txt")).read().split("\n")
        env = open(os.path.join(p.bin, "env-1.txt")).read().split("\n")
    except OSError:
        prompt, args, env = "", [], []
    check("checkpoint: the supervisor reads the work, never the agent's prose",
          "SUPERVISOR-PLEASE-EXTEND" not in prompt and "pytest -q tests/test_parse.py" in prompt
          and "T1 do a thing" in prompt and "--safe-mode" in args and "--tools" in args
          and args[:1] != [p.dir] and "EFFICIENCY_SUPERVISOR=1" in env
          and not any(l.startswith("CLAUDE_PROJECT_DIR=") for l in env),
          "prose leaked=%s call seen=%s cwd=%s flag=%s"
          % ("SUPERVISOR-PLEASE-EXTEND" in prompt, "pytest -q" in prompt, args[:1],
             "EFFICIENCY_SUPERVISOR=1" in env))
    return p


@case("checkpoint: the supervisor is captured with the plan; the policy cannot swap it mid-run")
def _():
    p = sup_run()
    p.invoke()
    first = p.private().get("supervisor")
    p.write_policy("---\nbudget:\n  supervisor: off\n---\n")
    p.invoke()
    p.write_policy("---\nbudget:\n  supervisor: haiku\n---\n")
    p.invoke()
    check("checkpoint: the supervisor is captured with the plan; the policy cannot swap it mid-run",
          first == "sonnet" and p.private().get("supervisor") == "sonnet",
          "captured %s, now %s" % (first, p.private().get("supervisor")))
    return p


@case("checkpoint: `budget.supervisor` reads as the shipped default, a model, or off")
def _():
    readings = {}
    for label, policy in (("no policy", None),
                          ("no key", "---\nbudget:\n  task_usd: 5.00\n---\n"),
                          ("no budget", "---\ngate: x\n---\n"),
                          ("off", "---\nbudget:\n  supervisor: off\n---\n"),
                          ("haiku", "---\nbudget:\n  supervisor: \"haiku\"  # cheap\n---\n"),
                          ("garbage", "---\nbudget:\n  supervisor: rm -rf /\n---\n")):
        p = Project()
        if policy is not None:
            p.write_policy(policy)
        readings[label] = HOOK_MODULE.policy_supervisor(p.dir)
        p.close()
    check("checkpoint: `budget.supervisor` reads as the shipped default, a model, or off",
          readings == {"no policy": "", "no key": "sonnet", "no budget": "sonnet",
                       "off": "", "haiku": "haiku", "garbage": ""},
          str(readings))


@case("checkpoint: inside the supervisor's own session, both autopilot hooks stand aside")
def _():
    p = sup_run()
    code, out = p.invoke(extra_env={"EFFICIENCY_SUPERVISOR": "1"})
    check("checkpoint: inside the supervisor's own session, both autopilot hooks stand aside",
          code == 0 and out == {} and p.private() == {},
          "code=%s out=%s state=%s" % (code, out, p.private()))
    return p


# ── 7. what reaches a session ────────────────────────────────────────────────
# The charter was injected from the first release; the policy was not, and that
# hole was measured rather than reasoned about: asked which paths this project
# declares critical, a session answered "NOT IN MY INSTRUCTIONS". The charter had
# been pointing at a file nobody told the model to read.

@case("a project without a policy gets nothing injected at all")
def _():
    p = Project(run_file=False)
    code, text = p.invoke_session_start()
    check("a project without a policy gets nothing injected at all",
          code == 0 and text == "", "got %d chars" % len(text))
    return p


@case("an adopting project gets the charter")
def _():
    p = Project(run_file=False).write_policy()
    code, text = p.invoke_session_start()
    check("an adopting project gets the charter",
          "autonomy charter" in text.lower(), "got %.60s" % text)
    return p


@case("and its own policy — tiers, gate and declared defaults")
def _():
    p = Project(run_file=False).write_policy()
    code, text = p.invoke_session_start()
    check("and its own policy — tiers, gate and declared defaults",
          "src/auth/**" in text and "make check" in text
          and "prefer extending an existing type" in text,
          "policy did not arrive: %.80s" % text[-200:])
    return p


@case("frontmatter comments are stripped, body headings survive")
def _():
    p = Project(run_file=False).write_policy()
    code, text = p.invoke_session_start()
    check("frontmatter comments are stripped, body headings survive",
          "teaching comment" not in text and "another comment" not in text
          and "# Declared defaults" in text,
          "stripping went wrong")
    return p


@case("an unreadable policy still ships the charter")
def _():
    p = Project(run_file=False).write_policy()
    os.chmod(os.path.join(p.dir, ".efficiency", "policy.md"), 0o000)
    try:
        code, text = p.invoke_session_start()
        check("an unreadable policy still ships the charter",
              code == 0 and "autonomy charter" in text.lower(),
              "charter lost with the policy")
    finally:
        os.chmod(os.path.join(p.dir, ".efficiency", "policy.md"), 0o644)
    return p


@case("an active run is announced, a blocked one hands back to the developer")
def _():
    p = Project(tasks="- [ ] T1 open", status="BLOCKED").write_policy()
    text = p.raw().replace("blocked_reason:", "blocked_reason: it hit its ceiling")
    open(p.run_path, "w").write(text)
    _c, out = p.invoke_session_start()
    check("an active run is announced, a blocked one hands back to the developer",
          "BLOCKED" in out and "it hit its ceiling" in out,
          "blocked run not surfaced: %.80s" % out[-160:])
    return p


@case("a pre-0.4.0 install is reported loudly instead of going inert")
def _():
    # The worst failure this framework can have: upgrade across the path move,
    # the policy stays where 0.3.x put it, the plugin looks elsewhere, and
    # everything stops with no charter, no guards and no error.
    p = Project(run_file=False)
    with open(os.path.join(p.dir, ".claude", "efficiency.md"), "w") as fh:
        fh.write("---\ngate: \"make check\"\n---\n")
    code, text = p.invoke_session_start()
    check("a pre-0.4.0 install is reported loudly instead of going inert",
          code == 0 and "INERT after an upgrade" in text
          and ".claude/efficiency.md` → `.efficiency/policy.md" in text
          and "without asking" in flat(text),
          "stale install not surfaced: %.70s" % text)
    return p


@case("a current install is not mistaken for a stale one")
def _():
    p = Project(run_file=False).write_policy()
    with open(os.path.join(p.dir, ".claude", "efficiency.md"), "w") as fh:
        fh.write("a leftover nobody cleaned up\n")
    _c, text = p.invoke_session_start()
    check("a current install is not mistaken for a stale one",
          "INERT after an upgrade" not in text and "autonomy charter" in text.lower(),
          "a leftover file hijacked a working install")
    return p


@case("no backlog file: nothing is announced")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("no backlog file: nothing is announced",
          "backlog item" not in text, "announced a backlog that does not exist")
    return p


@case("open backlog items are announced first, before the charter")
def _():
    p = Project(run_file=False).write_policy().write_backlog(
        "# Backlog\n\n## Open\n\n- [ ] 2026-10-10 - fix the thing - found while: elsewhere\n")
    _c, text = p.invoke_session_start()
    check("open backlog items are announced first, before the charter",
          text.lstrip().startswith("# \u26a0 1 open backlog item")
          and "fix the thing" in text,
          "starts with: %.70s" % text.lstrip())
    return p


@case("a closed entry is not counted as outstanding")
def _():
    p = Project(run_file=False).write_policy().write_backlog(
        "# Backlog\n\n## Open\n\n- [ ] one open\n\n## Closed\n\n- [x] 2026-01-01 - done\n")
    _c, text = p.invoke_session_start()
    check("a closed entry is not counted as outstanding",
          "1 open backlog item" in text, "miscounted")
    return p


@case("the format example inside a code fence is not counted")
def _():
    # The shipped template documents the entry format with a real-looking line
    # inside a fence. Counting it reported a phantom item on day one, in the one
    # file whose job is to be trusted about how much is outstanding.
    p = Project(run_file=False).write_policy().write_backlog(
        "# Backlog\n\n```text\n- [ ] 2026-10-10 - EXAMPLE - found while: EXAMPLE\n```\n\n"
        "## Open\n\n- [ ] the only real one\n")
    _c, text = p.invoke_session_start()
    check("the format example inside a code fence is not counted",
          "1 open backlog item" in text and "EXAMPLE" not in text,
          "the fenced example leaked in")
    return p


@case("the model is told to mention the backlog but not to start on it")
def _():
    p = Project(run_file=False).write_policy().write_backlog(
        "# Backlog\n\n## Open\n\n- [ ] something deferred\n")
    _c, text = p.invoke_session_start()
    check("the model is told to mention the backlog but not to start on it",
          "in your first reply" in flat(text) and "unless they ask" in flat(text),
          "the surfacing instruction is incomplete")
    return p


@case("the charter draws the boundary at done, and names the backlog")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("the charter draws the boundary at done, and names the backlog",
          "Finishing is a boundary" in flat(text) and ".efficiency/backlog.md" in text
          and "found while:" in text,
          "the scope rule is not in the charter")
    return p


@case("the charter defines done, and says unverified is not done")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("the charter defines done, and says unverified is not done",
          "Unverified is not done" in flat(text) and "the gate is green, and you ran it" in flat(text),
          "the done-rule is not in the charter")
    return p


@case("the done-rule refuses the small-change exception")
def _():
    # Measured: a session reported DONE while saying it had skipped the gate
    # because the change was one line. That is exactly the reasonable-sounding
    # exception that erodes the rule, so the charter now names it.
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("the done-rule refuses the small-change exception",
          "no exception for a small change" in flat(text) and "costs seconds" in flat(text),
          "the exception is not closed off")
    return p


@case("the charter demands a verdict on the first line")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("the charter demands a verdict on the first line",
          "**DONE**" in text and "**NOT DONE**" in text and "**BLOCKED**" in text
          and "stops after the first line" in flat(text),
          "the verdict contract is not in the charter")
    return p


@case("a completed run is told to report with a verdict")
def _():
    p = Project(tasks="- [x] T1 done").seed_private()
    _c, out = p.invoke()
    msg = out.get("systemMessage", "")
    check("a completed run is told to report with a verdict",
          p.state()["status"] == "DONE" and "NOT DONE" in msg and "verdict" in msg,
          "DONE message: %.90s" % msg)
    return p


def wait_for(path, limit=20.0):
    """Poll for a file a detached process is writing; True once it is there."""
    end = time.time() + limit
    while time.time() < end:
        if os.path.exists(path):
            return True
        time.sleep(0.2)
    return False


def slow_tool_path(p, name="pandoc", seconds=30):
    """A PATH holding one fake tool that hangs on any flag, ahead of the system's own.

    The system directories only, so the real detection does not reach the
    heavy tools of whichever machine runs the test.
    """
    fake = os.path.join(p.dir, "fakebin")
    os.makedirs(fake, exist_ok=True)
    tool = os.path.join(fake, name)
    with open(tool, "w") as fh:
        fh.write("#!/bin/sh\nsleep %d\n" % seconds)
    os.chmod(tool, 0o755)
    return fake + os.pathsep + "/usr/bin:/bin"


@case("a missing inventory is written by the hook, not left to the adopter")
def _():
    # It used to be the adopter's job, via a script in the plugin's directory —
    # which a session can neither read nor locate. The hook has neither limit.
    # Detached since 0.22.1, so it lands after the hook has returned.
    p = Project(run_file=False).write_policy()
    path = os.path.join(p.dir, ".efficiency", "tools.md")
    p.invoke_session_start(inventory=False, path=slow_tool_path(p, seconds=1))
    written = wait_for(path)
    check("a missing inventory is written by the hook, not left to the adopter",
          written and "Operational tools" in open(path).read(),
          "written=%s" % written)
    return p


@case("session start does not wait for the inventory, and a hanging tool is capped")
def _():
    # A tool that hangs on --version made the detection outlast the hook's
    # 15 s timeout, so the hook was killed and the inventory never written.
    # Two guards: the hook does not wait, and the detection gives up on a tool.
    p = Project(run_file=False).write_policy()
    path = os.path.join(p.dir, ".efficiency", "tools.md")
    started = time.time()
    p.invoke_session_start(inventory=False, path=slow_tool_path(p, seconds=30))
    returned = time.time() - started
    written = wait_for(path, limit=25)
    listed = written and "`pandoc`" in open(path).read().split("## Not installed")[0]
    check("session start does not wait for the inventory, and a hanging tool is capped",
          returned < 5 and listed,
          "hook returned after %.1fs; inventory written=%s, hanging tool listed=%s"
          % (returned, written, listed))
    return p


@case("a fresh inventory is not rewritten on every session")
def _():
    p = Project(run_file=False).write_policy().write_tools()
    path = os.path.join(p.dir, ".efficiency", "tools.md")
    before = os.path.getmtime(path)
    os.utime(path, None)
    p.invoke_session_start()
    check("a fresh inventory is not rewritten on every session",
          "pandoc" in open(path).read(),
          "the fixture inventory was overwritten despite being fresh")
    return p


@case("the session is told where the plugin lives, and that it cannot read it")
def _():
    # The model is never given CLAUDE_PLUGIN_ROOT and cannot reach it anyway, so
    # every skill instruction naming that path was one nobody could follow. The
    # path is published for the developer to use, not the session.
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("the session is told where the plugin lives, and that it cannot read it",
          "Where this plugin lives" in text
          and "cannot read or execute anything in there" in flat(text).lower()
          and "check-install.sh" in text,
          "the plugin path block is missing or incomplete")
    return p


@case("available tools are injected, with their purpose")
def _():
    p = Project(run_file=False).write_policy().write_tools()
    _c, text = p.invoke_session_start()
    check("available tools are injected, with their purpose",
          "`pandoc` — convert between document formats" in text and "`jq`" in text,
          "the inventory did not arrive")
    return p


@case("versions and not-installed tools are left out of the injection")
def _():
    # Both belong in the file and neither is worth paying for at the start of
    # every session: a version matters when something misbehaves, and an absence
    # matters when something needs it.
    p = Project(run_file=False).write_policy().write_tools()
    _c, text = p.invoke_session_start()
    section = text[text.find("# Operational tools"):]
    check("versions and not-installed tools are left out of the injection",
          "pandoc 3.1.2" not in section and "ffmpeg" not in section,
          "section carried versions or absences")
    return p


@case("the charter says to reach for the tool before writing the script")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("the charter says to reach for the tool before writing the script",
          "before writing code to do something" in flat(text).lower()
          and "offer to install it once" in flat(text),
          "the tool-first rule is not in the charter")
    return p


@case("the charter forbids updating a tool mid-task")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("the charter forbids updating a tool mid-task",
          "Never update in the middle of a task" in flat(text)
          and "once per tool per session" in flat(text),
          "the update rule is missing or unscoped")
    return p


@case("the charter warns that a tool missing from CI bites later")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("the charter warns that a tool missing from CI bites later",
          "absent from CI is a difference that bites later" in flat(text),
          "the CI-parity warning is missing")
    return p


@case("the charter tells the model to arm on a plain keep-going instruction")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("the charter tells the model to arm on a plain keep-going instruction",
          "efficiency:autopilot" in text and "is an approval" in text,
          "the natural-language path is not in the charter")
    return p


# ── 7b. the dialogue language ───────────────────────────────────────────────
# A session reads mostly English and drifts into answering in it. The hooks
# state the OS language at session start, above everything, and on every
# prompt. Each source is exercised with the host's own language shut out.

@case("language: macOS's AppleLanguages names it when no locale variable is set")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start(apple="it-IT")
    check("language: macOS's AppleLanguages names it when no locale variable is set",
          sys.platform != "darwin" or text.startswith("# Dialogue language: Italian"),
          "starts with: %.80s" % text)
    return p


@case("language: LANG names it, LC_ALL overrides it, the policy overrides both")
def _():
    p = Project(run_file=False).write_policy()
    _c, by_lang = p.invoke_session_start(locale={"LANG": "fr_FR.UTF-8"})
    _c, by_all = p.invoke_session_start(locale={"LANG": "fr_FR.UTF-8", "LC_ALL": "de_DE.UTF-8"},
                                        apple="it-IT")
    p.write_policy("---\nlanguage: es\n---\n")
    _c, by_policy = p.invoke_session_start(locale={"LC_ALL": "de_DE.UTF-8"}, apple="it-IT")
    p.write_policy("---\nlanguage: \"italiano\"  # as the team writes it\n---\n")
    _c, by_name = p.invoke_session_start(locale={"LC_ALL": "de_DE.UTF-8"})
    check("language: LANG names it, LC_ALL overrides it, the policy overrides both",
          by_lang.startswith("# Dialogue language: French")
          and by_all.startswith("# Dialogue language: German")
          and by_policy.startswith("# Dialogue language: Spanish")
          and by_name.startswith("# Dialogue language: italiano"),
          "LANG=%.40s | LC_ALL=%.40s | policy=%.40s | name=%.40s"
          % (by_lang, by_all, by_policy, by_name))
    return p


@case("language: nothing to go on means nothing said — C is not a language")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start(locale={"LANG": "C.UTF-8", "LC_ALL": "POSIX"})
    line = p.invoke_prompt(locale={"LANG": "C"})
    check("language: nothing to go on means nothing said — C is not a language",
          "Dialogue language" not in text and "Reply in" not in line,
          "session=%.60s prompt=%.60s" % (text, line))
    return p


@case("language: the line opens the injection, above even the backlog")
def _():
    p = Project(run_file=False).write_policy().write_backlog(
        "# Backlog\n\n## Open\n\n- [ ] 2026-10-10 - fix the thing - found while: elsewhere\n")
    _c, text = p.invoke_session_start(locale={"LANG": "it_IT.UTF-8"})
    check("language: the line opens the injection, above even the backlog",
          text.startswith("# Dialogue language: Italian")
          and text.index("Dialogue language") < text.index("open backlog item"),
          "starts with: %.80s" % text)
    return p


@case("language: every prompt carries it, armed or not, and only where adopted")
def _():
    p = Project().write_policy()
    armed = p.invoke_prompt(locale={"LANG": "it_IT.UTF-8"})
    q = Project(run_file=False).write_policy()
    idle = q.invoke_prompt(locale={"LANG": "it_IT.UTF-8"})
    r = Project(run_file=False)
    bare = r.invoke_prompt(locale={"LANG": "it_IT.UTF-8"})
    check("language: every prompt carries it, armed or not, and only where adopted",
          "Reply in Italian" in armed and "arm the autopilot" not in armed
          and "Reply in Italian" in idle and "arm the autopilot" in idle and bare == "",
          "armed=%r idle=%.80r bare=%r" % (armed, idle, bare))
    q.close()
    r.close()
    return p


# ── 8. confinement ───────────────────────────────────────────────────────────

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
    victim = os.path.join(outside, "run.md")
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


@case("--by-model splits spend by model, not just a total")
def _():
    import subprocess as sp
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10_000_000)
    p.write_transcript([
        ("claude-opus-5", {"input_tokens": 1_000_000, "output_tokens": 0}, "2026-01-01T00:00:00Z"),
        ("claude-haiku-4-5", {"input_tokens": 1_000_000, "output_tokens": 0}, "2026-01-01T00:00:01Z"),
    ])
    done = sp.run([sys.executable, os.path.join(HERE, "lib", "spend.py"),
                   p.transcript, "2000-01-01T00:00:00Z",
                   os.path.join(HERE, "lib", "model-costs.json"), "--by-model"],
                  capture_output=True, text=True, timeout=60)
    try:
        d = json.loads(done.stdout)
    except ValueError:
        check("--by-model splits spend by model, not just a total", False,
              "not JSON: %.80s" % done.stdout)
        return p
    by = d.get("by_model", {})
    # A million input tokens: $5.00 on Opus, $1.00 on Haiku.
    check("--by-model splits spend by model, not just a total",
          d.get("total_micro_usd", 0) == 6_000_000
          and by.get("claude-opus-5") == 5_000_000
          and by.get("claude-haiku-4-5") == 1_000_000,
          "got %s" % json.dumps(d))
    return p


@case("a dated model id is priced as itself, not as the expensive fallback")
def _():
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10_000_000)
    p.write_transcript([("claude-haiku-4-5-20251001",
                         {"input_tokens": 1_000_000, "output_tokens": 0}, "2026-01-01T00:00:00Z")])
    p.invoke()
    spent = int(p.state()["task_spend_micro_usd"])
    # A million input tokens of Haiku is $1.00. Priced as the fallback it would
    # be $10.00 — a tenfold lie, in the direction that stops a run early.
    check("a dated model id is priced as itself, not as the expensive fallback",
          900_000 <= spent <= 1_100_000, "measured %s micro-usd, expected ~1000000" % spent)
    return p


# ── 9. the status line: the backlog, permanently visible ─────────────────────
#
# The one surface that is re-rendered under the prompt on every conversation
# update, so it is also the one the developer cannot miss and cannot escape.
# Measured properties it depends on are in docs/verified-platform-behaviour.md
# § 12; these cases cover what this repo controls.

BACKLOG_FIXTURE = """# Backlog

```text
- [ ] 2020-01-01 · the documented example, which is not an item · found while: writing the template
```

## Open

- [ ] 2026-02-01 · the first thing worth reporting: with evidence after a colon · found while: elsewhere
- [ ] 2026-01-01 · the second thing, which is older than the first · found while: elsewhere
- [ ] 2026-03-01 · the third thing, stated at length. And then a detail · found while: elsewhere
- [ ] 2026-04-01 · the fourth thing, below the fold · found while: elsewhere

## Closed

- [x] 2025-01-01 · closed, and must not be counted · found while: elsewhere
"""


@case("a project that never adopted gets no status line at all")
def _():
    p = Project(run_file=False).write_backlog(BACKLOG_FIXTURE)
    code, out = p.invoke_statusline()
    check("a project that never adopted gets no status line at all",
          code == 0 and out == "", "code=%s out=%r" % (code, out))
    return p


@case("the status line prints the count and the top three items")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    _c, out = p.invoke_statusline()
    lines = out.rstrip("\n").split("\n")
    check("the status line prints the count and the top three items",
          len(lines) == 4
          and "4 open" in lines[0]
          and lines[1].strip().startswith("1. the first thing")
          and lines[2].strip().startswith("2. the second thing")
          and lines[3].strip().startswith("3. the third thing"),
          "got %r" % (lines,))
    return p


@case("entries are cut to their headline: no evidence, no 'found while'")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    _c, out = p.invoke_statusline()
    body = "\n".join(out.split("\n")[1:])
    check("entries are cut to their headline: no evidence, no 'found while'",
          "found while" not in body
          and "with evidence" not in body
          and "And then a detail" not in body,
          "got %r" % (body,))
    return p


@case("the fenced example in the template is not counted as an item")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    _c, out = p.invoke_statusline()
    # The status line and the session-start announcement read the same file with
    # the same rules. If they ever disagree, neither number is believed again.
    _c2, text = p.invoke_session_start()
    check("the fenced example in the template is not counted as an item",
          "4 open" in out.split("\n")[0] and "4 open backlog item(s)" in text,
          "status line said %r; session start said %r"
          % (out.split("\n")[0], flat(text)[:120]))
    return p


@case("the oldest date is the oldest, not the first line")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    _c, out = p.invoke_statusline()
    check("the oldest date is the oldest, not the first line",
          "oldest 2026-01-01" in out.split("\n")[0], "got %r" % out.split("\n")[0])
    return p


@case("an empty backlog still prints, so a blank line means broken")
def _():
    p = Project(run_file=False).write_policy().write_backlog("# Backlog\n\n## Open\n\n## Closed\n")
    _c, out = p.invoke_statusline()
    check("an empty backlog still prints, so a blank line means broken",
          "backlog clear" in out, "got %r" % out)
    return p


# The fields Claude Code sends a status line, as measured in § 12.
SESSION_PAYLOAD = {
    "model": {"display_name": "Opus 5.5"},
    "context_window": {"used_percentage": 42.4},
    "cost": {"total_cost_usd": 1.234, "total_duration_ms": 25 * 60000},
    "rate_limits": {"five_hour": {"used_percentage": 61}},
}


@case("the session line comes first, above the backlog, never on its line")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    _c, out = p.invoke_statusline(session=SESSION_PAYLOAD)
    lines = out.rstrip("\n").split("\n")
    check("the session line comes first, above the backlog, never on its line",
          len(lines) == 5
          and all(s in lines[0] for s in ("Opus 5.5", "42%", "$1.23", "⏱ 25m", "5h 61%"))
          and "backlog" not in lines[0]
          and "4 open" in lines[1],
          "got %r" % (lines,))
    return p


@case("a payload without session fields prints no session line")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    _c, out = p.invoke_statusline(session={"model": {}})
    check("a payload without session fields prints no session line",
          out.split("\n")[0].startswith("⚠ backlog: 4 open"), "got %r" % out.split("\n")[0])
    return p


@case("the branch is read from .git/HEAD, a worktree's pointer and a detached head")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    gitdir = os.path.join(p.dir, ".git")
    os.makedirs(gitdir, exist_ok=True)
    with open(os.path.join(gitdir, "HEAD"), "w") as fh:
        fh.write("ref: refs/heads/feature/statusline\n")
    _c, normal = p.invoke_statusline(session=SESSION_PAYLOAD)
    with open(os.path.join(gitdir, "HEAD"), "w") as fh:
        fh.write("0123456789abcdef0123456789abcdef01234567\n")
    _c, detached = p.invoke_statusline(session=SESSION_PAYLOAD)
    real = os.path.join(p.dir, "elsewhere")
    os.rename(gitdir, real)
    with open(gitdir, "w") as fh:
        fh.write("gitdir: elsewhere\n")
    with open(os.path.join(real, "HEAD"), "w") as fh:
        fh.write("ref: refs/heads/in-a-worktree\n")
    _c, worktree = p.invoke_statusline(session=SESSION_PAYLOAD)
    check("the branch is read from .git/HEAD, a worktree's pointer and a detached head",
          "⎇ feature/statusline" in normal and "⎇ 0123456" in detached
          and "⎇ in-a-worktree" in worktree,
          "got %r / %r / %r" % (normal.split("\n")[0], detached.split("\n")[0],
                                worktree.split("\n")[0]))
    return p


@case("a narrow terminal drops session parts from the least useful end, gauge last")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    _c, out = p.invoke_statusline(columns="44", session=SESSION_PAYLOAD)
    head = out.split("\n")[0]
    check("a narrow terminal drops session parts from the least useful end, gauge last",
          len(head) <= 40 and "42%" in head and "Opus 5.5" in head
          and "⏱" not in head,
          "got %r (%d chars)" % (head, len(head)))
    return p


@case("NO_COLOR is honoured on the session line, and colour is emitted without it")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    _c, plain = p.invoke_statusline(session=SESSION_PAYLOAD)
    _c, coloured = p.invoke_statusline(session=SESSION_PAYLOAD, colour=True)
    check("NO_COLOR is honoured on the session line, and colour is emitted without it",
          "\033[" not in plain and "\033[" in coloured.split("\n")[0],
          "plain=%r coloured=%r" % (plain.split("\n")[0], coloured.split("\n")[0]))
    return p


@case("a narrow terminal keeps the count and the command, and drops the rest")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    _c, out = p.invoke_statusline(columns="52")
    head = out.split("\n")[0]
    check("a narrow terminal keeps the count and the command, and drops the rest",
          len(head) <= 52 and "4 open" in head and "/efficiency:backlog" in head
          and "oldest" not in head,
          "got %r (%d chars)" % (head, len(head)))
    return p


@case("a corrupt backlog cannot take the status line down")
def _():
    p = Project(run_file=False).write_policy()
    with open(os.path.join(p.dir, ".efficiency", "backlog.md"), "wb") as fh:
        fh.write(b"\xff\xfe not text at all \x00\x00 - [ ] \xc3\x28")
    code, out = p.invoke_statusline()
    check("a corrupt backlog cannot take the status line down",
          code == 0 and "Traceback" not in out, "code=%s out=%r" % (code, out))
    return p


@case("SessionStart deploys the status line script into the project")
def _():
    p = Project(run_file=False).write_policy().write_backlog(BACKLOG_FIXTURE)
    p.invoke_session_start()
    deployed = os.path.join(p.dir, ".efficiency", "statusline.py")
    same = (os.path.exists(deployed)
            and open(deployed, "rb").read() == open(STATUSLINE, "rb").read())
    # And the deployed copy must work from where it landed: the command Claude
    # Code runs names that path, not this repo's.
    code, out = (p.invoke_statusline(script=deployed) if same else (1, ""))
    check("SessionStart deploys the status line script into the project",
          same and code == 0 and "4 open" in out,
          "deployed=%s code=%s out=%r" % (same, code, out))
    return p


@case("a project with no statusLine is offered one, with the block to paste")
def _():
    p = Project(run_file=False).write_policy()
    _c, text = p.invoke_session_start()
    check("a project with no statusLine is offered one, with the block to paste",
          "statusLine" in text and ".efficiency/statusline.py" in text
          and "Offer it once" in flat(text),
          "the offer is missing from the injection")
    return p


@case("a statusLine the developer already has is never mentioned")
def _():
    p = Project(run_file=False).write_policy().write_settings(
        {"statusLine": {"type": "command", "command": "my-own-thing"}})
    _c, text = p.invoke_session_start()
    check("a statusLine the developer already has is never mentioned",
          "statusLine" not in text, "the hook offered to replace an existing one")
    return p


@case("statusline: off in the policy silences the offer for good")
def _():
    p = Project(run_file=False).write_policy(
        "---\ngate: \"make check\"\nstatusline: off\n---\n\n# Declared defaults\n\n- none\n")
    _c, text = p.invoke_session_start()
    check("statusline: off in the policy silences the offer for good",
          "statusLine" not in text, "the opt-out did not silence it")
    return p



@case("the status line command is written identically everywhere it is shipped")
def _():
    # One fact, one place — and when it cannot be one place, a test. The command
    # a developer pastes is given by the SessionStart injection and again by
    # skills/init/SKILL.md, and a drift between them installs a status line that
    # points at nothing in whichever project followed the stale one.
    # Matched as a plain substring, not a regex: one file quotes it for JSON
    # inside a Python string and the other writes it in a fenced block, so the
    # backslashes differ by design. The path is the part that must not drift.
    wanted = "$CLAUDE_PROJECT_DIR/.efficiency/statusline.py"
    found = {}
    for name in (SESSION_START,
                 os.path.join(os.path.dirname(HERE), "skills", "init", "SKILL.md")):
        found[os.path.basename(name)] = open(name, errors="replace").read().count(wanted)
    check("the status line command is written identically everywhere it is shipped",
          all(n == 1 for n in found.values()), "occurrences: %s" % found)



# ── 9. the ceiling inside the turn, not only at its end ──────────────────────
#
# Everything above is read at a turn boundary. A turn has no length limit, so
# until 0.19.0 the spend ceiling was unenforced for exactly the interval in
# which it could be exceeded. These cases cover the PreToolUse half, and the
# three that matter most are the refusal, the fail-OPEN, and the one proving
# this hook cannot touch the counters the other one owns.

OVER_CEILING = [("claude-opus-5", {"input_tokens": 100000, "output_tokens": 100000},
                 "2026-01-01T00:00:00Z")]


@case("mid-turn: no run file, permits in silence")
def _():
    # The fast path, taken by every tool call of every session in every project
    # that merely has the plugin installed. It must be silent and it must not
    # even reach the Stop hook's code.
    p = Project(run_file=False)
    code, out = p.invoke_pretool()
    check("mid-turn: no run file, permits in silence", code == 0 and out == {},
          "code=%s out=%s" % (code, out))
    return p


@case("mid-turn: under the ceiling, permits in silence")
def _():
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=10**9)
    p.write_transcript(OVER_CEILING)
    code, out = p.invoke_pretool()
    check("mid-turn: under the ceiling, permits in silence", code == 0 and out == {},
          "code=%s out=%s" % (code, out))
    return p


@case("mid-turn: over the ceiling, REFUSES the tool call")
def _():
    # The whole point. Without this the ceiling is a number read once the
    # spending has already happened.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=1000)
    p.write_transcript(OVER_CEILING)
    code, out = p.invoke_pretool()
    reason = out.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
    check("mid-turn: over the ceiling, REFUSES the tool call",
          code == 0 and p.decision(out) == "deny" and "ceiling" in reason,
          "code=%s decision=%s reason=%.70s" % (code, p.decision(out), reason))
    return p


@case("mid-turn: blind, fails OPEN where the Stop hook fails closed")
def _():
    # The one place this framework deliberately inverts rule 2, and the reason
    # is in the asymmetry of the two refusals: the Stop hook stopping a run
    # still ends the turn, whereas refusing every tool call mid-turn would leave
    # a session in which nothing works. So an unmeasurable transcript permits
    # here — and the case directly above, on the same project, shows the Stop
    # hook still stopping the run at the boundary. Nothing is enforced less.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=1000)
    p.transcript = os.path.join(p.dir, "does-not-exist.jsonl")
    code, out = p.invoke_pretool()
    permitted = code == 0 and out == {}
    p.invoke()                      # now let the Stop hook see the same run
    st = p.state()
    check("mid-turn: blind, fails OPEN where the Stop hook fails closed",
          permitted and st["status"] == "BLOCKED" and "measured" in st["blocked_reason"],
          "mid-turn out=%s · at the boundary status=%s reason=%.50s"
          % (out, st["status"], st.get("blocked_reason")))
    return p


@case("mid-turn: raising the ceiling in the run file buys nothing")
def _():
    # Rule 3, at the one event where a model could plausibly benefit from it:
    # rewrite the frontmatter mid-turn and keep spending. The captured ceiling
    # wins, exactly as it does at the boundary.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=1000)
    p.write_transcript(OVER_CEILING)
    # Two steps, not one: `open(path, "w")` truncates before the argument that
    # reads it is evaluated, so the one-liner silently rewrites the run file to
    # nothing and the case passes against a hook that does no such thing.
    raised = p.raw().replace("task_spend_max_micro_usd: 0",
                             "task_spend_max_micro_usd: 999999999")
    open(p.run_path, "w").write(raised)
    code, out = p.invoke_pretool()
    check("mid-turn: raising the ceiling in the run file buys nothing",
          p.decision(out) == "deny",
          "decision=%s — the run file's number was believed over the captured one"
          % p.decision(out))
    return p


@case("mid-turn: the first turn of a run is bounded too")
def _():
    # Before the Stop hook has ever seen a run there is no captured ceiling, and
    # standing aside would have left the longest turn of most runs — the one
    # that starts it — as the only unbounded one. There is no loophole in
    # reading the run file here: nothing has been captured yet to be overridden,
    # and the developer approved these numbers minutes ago.
    p = Project(tasks="- [ ] T1 open", spend_max=1000)
    p.write_transcript(OVER_CEILING)
    code, out = p.invoke_pretool()
    check("mid-turn: the first turn of a run is bounded too",
          p.decision(out) == "deny", "decision=%s" % p.decision(out))
    return p


@case("mid-turn: a run already stopped is not refused again")
def _():
    # Once a guard has stopped the run the developer is very likely driving by
    # hand. Refusing their tool calls would be this hook enforcing a verdict
    # that has already been delivered, in the one way rule 2 forbids.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=1000, blocked=True,
                                                    blocked_reason="stopped earlier")
    p.write_transcript(OVER_CEILING)
    code, out = p.invoke_pretool()
    check("mid-turn: a run already stopped is not refused again",
          code == 0 and out == {}, "out=%s" % (out,))
    return p


@case("mid-turn: a subagent's spend counts toward the ceiling")
def _():
    # The expensive half of a routed run is the delegated half — 17% of real
    # spend on the session that produced this framework, and the measurement
    # reads both transcripts for that reason. A mid-turn guard that priced only
    # the main session would be a ceiling on the cheap work, and § 17 measured
    # that a subagent's own tool calls arrive here carrying the parent's
    # transcript_path, so there is something to refuse.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=1000)
    p.write_transcript([("claude-haiku-4-5",
                         {"input_tokens": 1, "output_tokens": 1},
                         "2026-01-01T00:00:00Z")])
    p.subagent_transcript(OVER_CEILING)
    code, out = p.invoke_pretool()
    check("mid-turn: a subagent's spend counts toward the ceiling",
          p.decision(out) == "deny",
          "decision=%s — the main transcript alone is under the ceiling" % p.decision(out))
    return p


@case("mid-turn: a cached measurement dated in the future is not believed")
def _():
    # The cache exists so that the transcript is not re-parsed in front of every
    # single tool call. It is also the one thing here a model could write. A
    # future timestamp is the shape that bites: it never expires, so a single
    # forged line would retire the guard for the rest of the run. This framework
    # has already been bitten by exactly that, in `task_started_at`.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=1000)
    p.write_transcript(OVER_CEILING)
    p.write_midturn_cache(window="2000-01-01T00:00:00Z",
                          size=os.path.getsize(p.transcript),
                          spent=0, at=time.time() + 86400)
    code, out = p.invoke_pretool()
    check("mid-turn: a cached measurement dated in the future is not believed",
          p.decision(out) == "deny",
          "decision=%s — a forged cache line silenced the ceiling" % p.decision(out))
    return p


@case("mid-turn: the guard writes no counter and no ceiling of its own")
def _():
    # It runs concurrently with itself — several tool calls can be in flight —
    # and it has no business holding the leash. If it ever writes autopilot.json
    # it can clobber the counters the Stop hook owns, and the Stop hook is the
    # only thing authorised to move them.
    p = Project(tasks="- [ ] T1 open").seed_private(spend_max=1000)
    p.write_transcript(OVER_CEILING)
    before = json.dumps(p.private(), sort_keys=True)
    p.invoke_pretool()
    p.invoke_pretool()
    after = json.dumps(p.private(), sort_keys=True)
    check("mid-turn: the guard writes no counter and no ceiling of its own",
          before == after, "private state changed under a hook that must only read it")
    return p


# ── auto-allow ───────────────────────────────────────────────────────────────
#
# The PreToolUse hook also answers "allow" for Bash commands that cannot destroy
# anything, so a session stops pausing to ask about `git commit`. Its whole risk
# is a wrong yes, so most of these cases are commands that must NOT be allowed —
# each one a way a safe-looking line runs something else.

def _safe_command():
    sys.path.insert(0, os.path.join(HERE, "lib"))
    import safe_command
    return safe_command


ALLOWED = [
    "git status", "git diff --stat", "git log --oneline -5 HEAD~3",
    "git add -A && git commit -m 'fix: one; two'",
    "git commit -m \"$(cat <<'EOF'\nfeat: a `b` $c\n\nCo-Authored-By: X\nEOF\n)\"",
    "git push", "git push -u origin feature", "git fetch origin", "git pull",
    "git checkout -b feature", "git switch main", "git stash", "git tag v1",
    "git -C sub status", "cd sub && git diff", "ls -la | grep foo",
    "grep -rn foo src 2>/dev/null", "ls *.md", "find . -name '*.py'",
]

ASKED = [
    # outward-facing and destructive git
    "git push --force", "git push -f origin main", "git push --force-with-lease",
    "git push origin +main", "git push origin :main", "git push origin main --delete",
    "git reset --hard", "git clean -fd", "git branch -D x", "git checkout .",
    "git checkout main", "git restore x", "git rebase main", "git stash drop",
    # something else riding along
    "git status; rm -rf x", "git status && rm x", "git status | sh",
    "echo $(rm x)", "echo `rm x`", "git diff > p.txt", "git status &", "(git status)",
    "FOO=1 git status", "git -c core.pager=sh status", "git log --output=x",
    "find . -delete", "find . -exec rm {} ;", "find * -name x", "rg --pre=sh foo",
    "git status # rm x", "npm test", "python3 x.py",
    # a heredoc whose body closes a quote, or is not the first terminator
    "echo '$(cat <<'EOF'\n'; rm -rf x; echo '\nEOF\n)'",
    "git commit -m \"$(cat <<'EOF'\nx\nEOF\n; rm -rf y\nEOF\n)\"",
    "git commit -m \"$(cat <<EOF\n$(rm x)\nEOF\n)\"",
]


@case("auto-allow: every safe command classifies as safe")
def _():
    sc = _safe_command()
    missed = [c for c in ALLOWED if not sc.classify(c)]
    check("auto-allow: every safe command classifies as safe", not missed,
          "asked about: %r" % missed)


@case("auto-allow: no destructive or smuggled command classifies as safe")
def _():
    sc = _safe_command()
    leaked = [c for c in ASKED if sc.classify(c)]
    check("auto-allow: no destructive or smuggled command classifies as safe", not leaked,
          "would run unasked: %r" % leaked)


@case("auto-allow: an adopted project gets git commit allowed")
def _():
    p = Project(run_file=False).write_policy()
    code, out = p.invoke_pretool(command="git commit -m 'x'", mode="default")
    check("auto-allow: an adopted project gets git commit allowed",
          code == 0 and p.decision(out) == "allow", "code=%s out=%s" % (code, out))
    return p


@case("auto-allow: an unsafe command gets silence, never a decision")
def _():
    # Silence is what leaves the platform's own prompt in charge. A deny here
    # would block the developer's yes as well.
    p = Project(run_file=False).write_policy()
    code, out = p.invoke_pretool(command="git push --force", mode="default")
    check("auto-allow: an unsafe command gets silence, never a decision",
          code == 0 and out == {}, "code=%s out=%s" % (code, out))
    return p


@case("auto-allow: silent in a project that never adopted the framework")
def _():
    p = Project(run_file=False)
    code, out = p.invoke_pretool(command="git status", mode="default")
    check("auto-allow: silent in a project that never adopted the framework",
          code == 0 and out == {}, "code=%s out=%s" % (code, out))
    return p


@case("auto-allow: silent in plan mode")
def _():
    p = Project(run_file=False).write_policy()
    code, out = p.invoke_pretool(command="git commit -m x", mode="plan")
    check("auto-allow: silent in plan mode", code == 0 and out == {},
          "code=%s out=%s" % (code, out))
    return p


@case("auto-allow: `auto_allow: off` in the policy switches it off")
def _():
    p = Project(run_file=False).write_policy("---\ngate: \"make check\"\nauto_allow: off\n---\n")
    code, out = p.invoke_pretool(command="git status", mode="default")
    check("auto-allow: `auto_allow: off` in the policy switches it off",
          code == 0 and out == {}, "code=%s out=%s" % (code, out))
    return p


@case("auto-allow: the spend ceiling still refuses a safe command")
def _():
    p = Project(tasks="- [ ] T1 open").write_policy().seed_private(spend_max=1000)
    p.write_transcript(OVER_CEILING)
    code, out = p.invoke_pretool(command="git status", mode="default")
    check("auto-allow: the spend ceiling still refuses a safe command",
          code == 0 and p.decision(out) == "deny", "code=%s out=%s" % (code, out))
    return p


def run():
    print("autopilot selftest")
    print("hooks: %s\n       %s" % (HOOK, PRETOOL))
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
