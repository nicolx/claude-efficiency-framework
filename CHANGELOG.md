# Changelog

All notable changes to this project are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

A consuming project pins this plugin by `ref` or `sha`, so a change to anything under `hooks/`,
`skills/`, `agents/`, `templates/`, or to `AUTONOMY-CHARTER.md`, is a change to their sessions.

- **Major** — a consumer must edit their own `.claude/efficiency.md` or settings to keep working
- **Minor** — a new skill, a new agent, a new policy key with a safe default
- **Patch** — corrections, clarifications, price-table refreshes

## [0.7.1] — 2026-10-10

### Changed

- **The install section leads with the scope.** `claude plugin install` defaults to **`--scope
  user`**, which enables the plugin for every project on the machine — the README showed only
  `--scope project` and never said what omitting it does. It now shows both, warns about the
  default, and gives the rule for choosing: `user` for your own projects, because the plugin is inert
  without `.efficiency/policy.md` and installing once costs nothing where it has not been adopted;
  `project` for shared repositories, where `enabledPlugins` is committed so cloning is enough.
- The marketplace and the plugin are now clearly two steps in two places, with the reason — trusting
  a marketplace is the machine owner's decision, not a cloned repository's.
- The update trap and the `plugin list` ambiguity moved into the install section, where someone
  hitting them will actually be reading.

## [0.7.0] — 2026-10-10

### Added — use the tool, don't rebuild it

The expensive failure is not a missing tool, it is a **present tool nobody knew about**. This machine
has `pdftotext`, `sqlite3`, `gh`, `glab` and `docker`, and no session knew. Asked to pull text from a
PDF, a session that does not know `pdftotext` is there writes Python with pypdf, fights the
encodings, and spends thousands of tokens on what one command does in fifty.

- **`scripts/detect-tools.sh`** — writes `.efficiency/tools.md`: which of 25 operational CLIs are
  present, with what each is for. Document conversion, PDF, CSV, media, search, platform. No network,
  installs nothing, only looks. **Gitignored**, because it describes a machine and not a project.
- **The inventory is injected into every session**, purposes kept and versions dropped — a version
  matters when something misbehaves, and it is in the file when anyone wants it.
- **A charter rule**: check for a tool before writing code to do something operational. When one is
  genuinely absent, name it and offer to install it **once**, saying whether it will be needed again
  and whether CI needs it too — *a tool present here and absent from CI is a difference that bites
  later*. Re-run the detection after any install, or the next session goes back to writing the
  script.
- **Staleness, scoped so it does not become its own waste**: check at most once per tool per session
  and only for a tool about to be leaned on, never before every `jq`. And **never update mid-task** —
  a version change alters behaviour under work already in progress, turning a green task into a
  puzzle. Finish first, then offer.

### What was deliberately not built

A prompt at install time asking whether to install office tooling. At setup you do not know what the
project will need, so you would be guessing — and the framework's first act would be asking for a
permission nothing needs yet, which is exactly the interruption without added value this project
exists to remove. The offer belongs at the moment of need, where it has a visible cost and benefit.

### Fixed

- Version detection rejects error output. `pdftotext` treats `--version` as a filename and answers
  `I/O Error: Couldn't open file '--version'`; `unzip` answers a flag warning. Both were being
  printed into the inventory — noise in the one file whose job is to be believed. It now tries
  `--version`, `-version`, `-V`, `-v` and discards anything that reads as a complaint.
- Prose assertions in the selftest normalise whitespace. A sentence crossing the 100-column wrap
  broke a literal check twice while nothing about the content changed; assertions test meaning now,
  not line width.

### Verified

Given a PDF and no instruction about how, a session ran `pdftotext` and wrote **no script at all** —
and volunteered that the file was malformed, which it was. **57 checks, 0 failed.**

## [0.6.0] — 2026-10-10

### Added — the boundary at "done", and somewhere for the rest to go

Finishing is a boundary, not a pause. A session that keeps widening becomes one nobody can review,
and the second thing is always done with worse attention than the first: the context is full, the
original goal is far behind, and nobody decided the new work was worth doing.

- **The charter sorts what comes up.** Blocks the task → now, it was part of it. You broke something
  → now, you caused it. **Anything else you noticed → the backlog, not this session.** The third row
  is the one that feels wrong to obey and the one that matters: a clear, real improvement spotted
  mid-task is exactly what quietly doubles a diff nobody agreed to.
- **`.efficiency/backlog.md`** — committed, because it is shared knowledge that outlives the session
  that filled it. Each entry is one line with a `found while:` clause, which is not decoration: a
  fresh session has none of the context that made the thing obvious, and that half-sentence is the
  cheapest way to give it back.
- **Open items are surfaced at the top of every session**, ahead of the charter, by the same hook —
  with instructions to mention them once, in two lines, and **not** to start on them. A deferral
  nobody is reminded of is a deletion with extra steps; and picking one up because it is in front of
  you is the same scope creep, one session later.
- **`efficiency:backlog`** — file one, review what is outstanding, or pick one up as a new task.

### Fixed

- **The done-rule refuses the small-change exception.** A session reported `DONE` while admitting it
  had skipped the gate because the change was one line. That is the reasonable-sounding exception
  that erodes a rule, so the charter names it: judgements about the size of one's own change are the
  unreliable part, running the gate costs seconds, and deciding it was unnecessary is the thing being
  checked.
- **The backlog counter skips fenced code blocks.** The shipped template documents the entry format
  with a real-looking example inside a fence, and counting it reported a phantom item on day one — in
  the one file whose job is to be trusted about how much is outstanding.

### Verified

Given a task plus a deliberate nudge toward something else — *"e già che ci sei, nota che
src/legacy.sh ha un problema di sicurezza"* — a session surfaced the backlog in one line, did the
actual task, ran the gate, left `legacy.sh` untouched, filed no duplicate, and reported `DONE` with
the security issue listed as still open in the backlog. It also volunteered that the project's gate
was weak and therefore proved little. **51 checks, 0 failed.**

## [0.5.0] — 2026-10-10

### Added — the question a report must answer

**Is it done?** A report the reader has to decode is not a report, and nothing in this framework had
ever said so. The charter now carries three things, and they reach every session:

- **What done means.** Every acceptance criterion observably met, the gate green *and run*, nothing
  left that was intended. And what it does not mean: **unverified is not done, it is unknown.**
  Neither is something left deliberately red, anything kept "for later", or a problem found and not
  fixed. A green gate does not make a task done when something outside the gate was left failing —
  those are two questions and only one of them is the gate's.
- **Lead with the verdict.** The first line of any hand-back is exactly one of **DONE**, **NOT
  DONE**, **BLOCKED**, in the language of the conversation, then the detail. A reader who stops after
  the first line must not be misled.
- **Keep three kinds of thing apart**: what was delivered, what is still open and who it waits on,
  and what was found along the way. A finding is not a deliverable — three problems found and one
  fixed is *one fixed, two open*, not "three addressed". An unresolved mistake belongs in the open
  list, not only in the narrative.

`run`, `run-report` and `autopilot` all carry the same rule, and the hook's own completion message
now asks for the verdict — it is the last thing the model reads before writing the report.

### Why

From a real report: dense, accurate, full of genuine findings, and impossible to answer *"is this
finished?"* from. It ended with "gate green" while elsewhere noting that something stays red by
design, that cases still need writing, and that a broken CI configuration meant two commits never
ran — which means unverified, which means not done. All true, none of it decidable without reading
to the end.

### Verified

All three verdicts observed, used discriminately: **DONE** on completed and gate-verified work,
**NOT DONE** when the gate could not run, **BLOCKED** when a command needed approval the session
could not get. Each opened the report, with delivered and open items separated beneath. 44 checks,
0 failed.

### Also recorded

`docs/verified-platform-behaviour.md` § 7: permission rules are still gated by workspace trust, and
2.1.289 now **says so** instead of ignoring them in silence — it names the entry it dropped and how
to grant trust. Trust did not stop mattering; it stopped gating hooks, and it stopped being
invisible.

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
