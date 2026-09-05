# Working ON claude-efficiency-framework

Instructions for Claude Code when the task is **developing this plugin**, not using it.

If you are in a project that has *adopted* the framework, this file is not what applies: read
`.claude/efficiency.md` for the policy and let the `SessionStart` hook supply the charter.

## What this repo is

A Claude Code **plugin**, distributed through its own marketplace manifest. It ships documents,
skills, agents and three Python hooks — no application code.

| Path | Audience | Role |
|---|---|---|
| `AUTONOMY-CHARTER.md` | consumers | Injected into every adopting session by `hooks/session-start.py`. Loaded constantly, so every line is paid for repeatedly. |
| `agents/*.md` | consumers | Pinned-model subagents. The `model:` field is the framework's whole premise. |
| `skills/*/SKILL.md` | consumers | Invoked as `/efficiency:<name>`. |
| `hooks/` | consumers | The autopilot, the charter carrier, the spend meter. The only executable code here. |
| `templates/` | consumers | Scaffolding the **project** owns once written. Never overwritten. |
| `docs/verified-platform-behaviour.md` | this repo | The measured facts the design rests on. |
| `scripts/probes/` | this repo | How to measure them again. |
| `CLAUDE.md` | this repo | This file. It never travels into a consumer session. |

## Rules

### 1. Measure the platform, do not cite it

Every load-bearing claim about Claude Code in this repo was measured on a real session, and the
probe that measured it is committed. The documentation was wrong or silent on three facts that
decide the design — the block cap's progress condition, `transcript_path` on `Stop`, and where
subagent turns live.

So: before building on a platform behaviour, probe it. Then record the result in
`docs/verified-platform-behaviour.md` **with its date and method**, and add the probe to
`scripts/probes/`. A number nobody can re-derive becomes folklore at the next release.

### 2. The hook is never fatal for its own defects

A broken hook must not stand between a developer and their work. On any internal failure it reports
and exits 0. The single thing that authorises it to block is a live run with work left.

The one deliberate exception is **fail-closed on a blind guard**: if spend cannot be measured, the
run stops. An unmeasured ceiling is not a ceiling. Note that stopping a run is not the same as
wedging a session — the turn still ends.

### 3. The model does not hold its own leash

Counters are read, incremented and written by `hooks/autopilot-stop.py`. Nothing that a model can
edit may extend a run. If a change would let the model raise its own budget, it is wrong however
convenient.

### 4. Every guard needs a test that proves it stops something

`hooks/selftest.py` invokes the hook as a real subprocess against a throwaway project and asserts on
what it printed *and* what it wrote back. A new guard without a case that shows it firing is
decorative — and the two worst bugs found so far (subagent spend invisible, dated model ids priced
as the fallback) were both caught by a case, not by reading.

### 5. This is not a quality framework

It answers *who does the work, on which model, and when is the human needed*. It does not define
what good code is. If a proposal is review doctrine or a coding principle, it belongs in whatever
standards document a project declares, not here. `agents/reviewer.md` measures one thing: does the
diff do what the task said, and only that.

### 6. Version every change to a shipped artefact

Bump `VERSION` **and** `.claude-plugin/plugin.json` **and** add a `CHANGELOG.md` entry in the same
commit. `scripts/qa.sh` fails when those three disagree, because a consumer pins by ref and a silent
change is a change to their sessions.

### 7. One fact, one place

A path written in prose is a live reference. A statement duplicated in two files will be wrong in
one of them after the next change. `scripts/lib/check-paths.py` catches the paths; the rest is
discipline.

## Gate

```bash
bash scripts/qa.sh
```

Green before every commit. It exits **2** for "passed what could run" rather than 0, because a check
that did not run looks exactly like a check that passed.

## Conventions

- **Language:** every shipped document is in English, whatever language the conversation is in.
- **Commits:** Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `refactor:`).
- **Dependencies:** `python3` only. No packages to install.
- **Dogfooding:** this repo should be able to adopt its own framework. Where it cannot, that is a
  finding about the framework.
