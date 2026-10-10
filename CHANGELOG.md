# Changelog

All notable changes to this project are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

A consuming project pins this plugin by `ref` or `sha`, so a change to anything under `hooks/`,
`skills/`, `agents/`, `templates/`, or to `AUTONOMY-CHARTER.md`, is a change to their sessions.

- **Major** — a consumer must edit their own `.claude/efficiency.md` or settings to keep working
- **Minor** — a new skill, a new agent, a new policy key with a safe default
- **Patch** — corrections, clarifications, price-table refreshes

## [0.4.0] — 2026-10-10

The release that found out why nothing ever finished.

### Fixed — the defect under the other two

**Claude Code refuses to write into `.claude/`.** Measured under `acceptEdits`: editing an existing
file there is denied, creating one is denied, and it is denied through `Write`, `Edit` and `Bash`
alike. A project `permissions.allow` rule naming the exact path does not lift it. The same writes one
directory up all succeed.

Both of this framework's live files were in there. Every one of them is a file the *model* must
write — ticking a task closed, advancing to the next, appending to the run log, adding a declared
default it had to invent. None of it could happen, and arming the autopilot could not happen at all,
since arming means creating the run file.

That had already been diagnosed twice as something else: as a block reason missing its instructions
(0.2.0), and as a model tidying away keys it did not recognise (0.3.0, retracted in 0.3.1). Both
plausible, both wrong, and both shipped.

### Breaking

Everything the framework writes moved out of `.claude/`:

| Was | Is |
|---|---|
| `.claude/efficiency.md` | `.efficiency/policy.md` (committed) |
| `.claude/efficiency.local.md` | `.efficiency/run.md` (gitignored) |
| `.claude/.efficiency-autopilot.json` | `.efficiency/autopilot.json` (gitignored) |

An existing adopter moves the policy and updates `.gitignore`; `/efficiency:init` does both.

### Added

- **The project's own policy is now injected into every session**, alongside the charter. It was
  missing, and measurably so: asked which paths this project declares critical, a session answered
  *"NOT IN MY INSTRUCTIONS"*. The charter had been pointing at a file nobody told the model to read,
  which left the declared defaults — the design's own largest lever — reaching the model only inside
  `/efficiency:plan-run`. Frontmatter comments are stripped first; the shipped template teaches
  through its comments, which is right on disk and waste in a context window paid for every session.
- **`efficiency:autopilot`** — arms a run from a plain instruction to keep going, in any words and
  any language. The commands remain for work worth planning deliberately.
- **A `UserPromptSubmit` reminder**, one line, only in adopting projects and only when no run is
  armed. The charter already said to arm, and a session could recite the instruction and name the
  skill — then went straight to the work. Knowing is not doing when the instruction was read many
  turns earlier, so the reminder lands with the instruction instead.
- Seven selftest cases for `SessionStart`, which had none. **41 checks, 0 failed.**

### Removed

- `POLICY_FILE` in `autopilot-stop.py`, defined and never used.

### Verified end to end

A plain Italian instruction — *"Sono quattro. Procedi fino a completarli tutti, non fermarti a
chiedermi conferma"* — armed the autopilot, drove four tasks, closed every one and finished `DONE`.
**The first complete run in this project's history**, and nothing about the run machinery had
changed: it had simply never been able to write to its own files.

## [0.3.2] — 2026-10-10

Re-measured everything against Claude Code **2.1.289** (the findings were taken on 2.1.261). This is
the discipline this repo asks for — measure, date it, re-run it — exercised for the first time, and
it paid on the first attempt.

### Changed

- **§ 7 is expired.** A freshly created directory's project settings now fire their hooks normally.
  `SessionStart`, `Stop` and `UserPromptSubmit` all fired where they were silent a month ago. The
  record is kept, dated and marked, because it was true when taken.
- **§ 3 survives unchanged** — 9 invocations in `stall` mode, 6 in `read` with `--max-turns 12`,
  identical to September. The finding the whole design rests on is intact.
- **§ 9 corrected.** `plugin list` prints one entry per project install **with no project path**, so
  two installs of the same plugin look like one plugin reported twice at different versions. Reading
  the first entry and stopping produced a wrong conclusion here twice, including the claim in 0.3.1
  that this repo was still on 0.1.0 — it has been on 0.3.0 since the update was run.
  `~/.claude/plugins/installed_plugins.json` records `projectPath` and is the way to tell them apart.

### Added

- `scripts/probes/settings-trust.sh` — drafted by run three, which then declined to finish the task
  on the grounds that the finding was unreproducible. The probe works; the premise was wrong, as a
  table of five measurements in § 7 now records. Its first real run is what caught § 7 expiring.

### Two traps worth naming

- **A hook with no trigger looks exactly like a suppressed hook.** `PreToolUse` appeared not to fire
  in an untrusted directory; it simply had no tool call to intercept. Given a prompt that runs a
  command, it fires. Rule out the mundane explanation before recording a platform finding.
- **A clean zero proves nothing on its own** — it is produced by a suppressed hook, a hook that never
  triggered, and a broken probe alike. Only one of those is worth writing down.

### Still not validated

The 0.2.0 and 0.3.0 fixes remain unexercised by a real run. The timeline is now pinned: run three
finished at 15:04 UTC on 2026-09-05 and the upgrade to 0.3.0 landed at 15:05 — one minute later.

## [0.3.1] — 2026-09-05

### Fixed

- **Retracted the reasoning published with 0.3.0**, in the changelog, the README and the autonomy
  charter. The claim that a model had erased the stall guard's counters was wrong.

### The finding that caused it

`claude plugin marketplace update` refreshes the catalogue and reports success. **It does not update
an installed plugin.** Nothing says so, and `claude plugin list` keeps reporting the installed
version — which is the only honest answer to "what am I running".

Three consecutive dogfooding runs of this framework therefore executed **0.1.0** while 0.2.0 and
0.3.0 sat in a refreshed catalogue. `open_tasks_seen` was missing from run two's state file because
0.1.0 never wrote that key, not because anything deleted it. The stall guard was not neutralised; it
was never loaded.

Two related edges, both now in `docs/verified-platform-behaviour.md` § 9: `plugin update` defaults to
**user** scope and fails against a `--scope project` install with a message that reads like the
plugin is missing; and after updating it says *"Restart to apply changes"* while `plugin list` still
shows the old version.

### Consequences to be honest about

- **The fixes in 0.2.0 and 0.3.0 remain unvalidated on real work.** They are sound as design and
  green under 34 selftest cases, but no run has exercised them.
- Run one's diagnosis stands: 0.1.0's block reason genuinely lacked the closing instructions, which
  is what it was measured against.
- Run three, also on 0.1.0, **closed a task in a single turn with no continuation at all**, and
  stopped for a legitimate `stop_for` reason with a precise account of why the next task could not be
  built as specified. That premise was itself wrong — the finding it disputed reproduces, as § 7 now
  records with a table — but stopping instead of guessing is exactly the behaviour asked for.

### Added

- `docs/verified-platform-behaviour.md` § 7 now carries the measured trust table. **Trust is not
  inherited from an ancestor**: a fresh subdirectory inside a repo you work in daily is as untrusted
  as one in `/tmp`, and its project settings are ignored just as silently.
- § 9 documents the update trap above, and the README's install section leads with it.

## [0.3.0] — 2026-09-05

### Fixed

- **The hook's counters and ceilings moved out of the run file** into
  `.claude/.efficiency-autopilot.json`, which no skill mentions and the charter forbids touching.
  The hook captures the ceilings there on first sight of a run and reads only from there.
- **A stopped run stays stopped.** The blocked verdict is private too, so setting `status: ACTIVE`
  in the run file no longer resumes a run a guard halted. Starting over means changing the task
  list — which is what re-planning already does — or deleting the state file deliberately.
- **The hook owns the spend window.** It opens a fresh one when `current_task` changes, so the
  model signals progress with one field instead of maintaining a timestamp it could also reset.
- A green gate now mirrors `gate_retries: 0` into the run file unconditionally. A stale retry count
  in the file a human reads is a small lie with no upside.

### Why

> **Retracted in 0.3.1.** This release was justified by a claim that turned out to be false: that a
> model had rewritten the run file's frontmatter and wiped the stall guard's counters. It had not.
> The keys were absent because the plugin actually running was 0.1.0, which never wrote them. See
> 0.3.1 for what really happened.

The change itself stands on its own reasoning: a guard whose counters live in a file the model is
asked to edit depends on the model preserving keys nobody told it were load-bearing, and a design
that needs that has a hole in it. Moving them out is a precaution, not a post-mortem. It is not a
security boundary either, and the docs say so — anything with a shell can delete that file.

Six selftest cases hold the separation in place: raising `continuations_max`, raising the spend
ceiling, flipping `status` back to `ACTIVE`, and rewriting the frontmatter the way a tidy editor
would. 34 checks, 0 failed.

### Also verified, on real work

- **The spend ceiling fires on a real run.** Run two stopped itself at *"T1 reached its spend
  ceiling ($5.06 of $5.00) without closing. It needs a human opinion before more is spent on it."*
  Nine continuations, a readable reason, and the session left alive. This is the guard the framework
  was asked for, and it works.

## [0.2.0] — 2026-09-05

### Added

- **A fifth guard: the stall guard.** The hook now tracks whether a run is actually advancing, and
  when the same task is handed back with nothing closing it escalates the wording, then stops the
  run. Six selftest cases cover it.

### Changed

- **The block reason now carries the state transitions**, imperatively and in order: tick the box,
  write the log line, move `current_task`, reset `task_started_at`, then work. It also forbids
  status reporting outright.

### Why

The framework failed its first real run, on its own repository, and the failure was in the design
rather than the code. Twelve continuations, $2.78, and the work of exactly one task — produced
correctly, then never closed. The last restarts were spent describing the counter: the driving
session's final line was *"Holding for that."*

The root cause: the `run` skill was read once, several turns earlier, while the **block reason is
the only instruction a model reliably reads on a continuation**. Putting the state transitions in
the skill and not in the block reason meant they did not happen — and nothing was watching for a run
that produced work without ever advancing.

Three lessons, all now enforced rather than written down: instructions belong where they will be
read; an unticked box is indistinguishable from unfinished work; and every guard needs a symptom it
can detect, not just a limit it can count to.

## [0.1.0] — 2026-09-05

First release. Deliberately not 1.0.0: the mechanism is measured and self-tested, but three things
in the plan's verification list have not happened yet, and calling it 1.0.0 would claim they had.

### Added

- **The autopilot `Stop` hook** (`hooks/autopilot-stop.py`) — refuses to end a turn while an
  approved run has open tasks and the gate is green. Inert unless `.claude/efficiency.local.md`
  exists, which is Claude Code's documented conditional-activation pattern and removes the need for
  a switch anyone could forget.
- **Four nested guards**: a per-task spend ceiling measured from the session transcript, a gate
  retry budget, a run-wide continuation budget, and the platform's own anti-stall cap. An
  unmeasurable ceiling fails closed and stops the run.
- **The spend meter** (`hooks/lib/spend.py`) — weighted token cost per model from the transcript,
  including subagent transcripts, with a dated price table (`hooks/lib/model-costs.json`).
- **The autonomy charter** (`AUTONOMY-CHARTER.md`), carried into adopting projects by a
  `SessionStart` hook and versioned with the plugin rather than copied into each project.
- **Three agents with pinned models**: `implementer-fast` (haiku), `architect` (opus, read-only),
  `reviewer` (opus, read-only).
- **Five skills**: `init`, `plan-run`, `run`, `fanout`, `run-report`.
- **The policy scaffolding** a project owns: `templates/efficiency.md` and
  `templates/settings.permissions.json`.
- **`docs/verified-platform-behaviour.md`** — every platform fact the design rests on, measured with
  its method and date, re-runnable via `scripts/probes/stop-cap.sh`.
- **`scripts/qa.sh`** — this repo's gate, which reports what it could not run rather than passing
  silently.

### Measured, not assumed

- The `Stop` block cap counts consecutive blocks **without progress**; any tool call resets it, a
  read-only one included. The cap is an anti-stall guard, not a ceiling on autonomy.
- `transcript_path` is present in the `Stop` payload although the hook reference does not list it
  for that event.
- Subagent turns are **not** in the main transcript despite `isSidechain` existing in its schema.
  They were 17% of spend on the session that built this, and the expensive half by design.
- A freshly created directory is untrusted, and its project settings are ignored in silence — the
  failure most easily misread as a platform change.

### Verified end to end

- **The plugin loads and its components are addressable.** `claude --plugin-dir .` exposes all eight
  as `efficiency:*` — three agents and five skills — which is also why the skills refer to agents by
  their namespaced names rather than their bare ones.
- **Adoption works, but not the way it first looked.** A `--scope project` install writes only
  `enabledPlugins` into the project; the marketplace stays in user settings, and committing
  `extraKnownMarketplaces` into a project does not register it. That split is right — trusting a
  marketplace is the machine owner's decision, not a cloned repo's — and the README now documents
  the measured path rather than the assumed one.
- **A project's own `Stop` hook coexists with the autopilot.** Both fire on every turn — 15
  invocations each in a real run — and neither is skipped because the other blocked first. And the
  platform's cap counts blocked *turns*, not blocks: with two hooks always blocking, each was
  invoked 9 times, the same total as one hook alone. They share the budget rather than halving it.
  This is also why the autopilot deliberately ignores `stop_hook_active`: a hook that stands down on
  that flag disables itself the moment any other Stop hook exists.
- **The autopilot blocks in a real session.** A throwaway project with two open tasks, a green gate
  and `continuations_max: 2`: the hook blocked twice, incremented the counter itself, then stopped
  the run with a reason naming both open tasks. The guard is real, not a diagram.

### Not yet verified

- The measurement that actually matters: a real run of ten tasks with every interruption counted and
  classified against the six causes. That number is the metric this framework is judged on, and
  until it exists the framework is a hypothesis with tests.
