# claude-efficiency-framework

A Claude Code plugin for two things that turn out to be the same thing: **routing each task to the
right model**, and **not being asked to confirm what you already approved**.

## The reframing this is built on

The goal is not "never interrupt me". A tool that never interrupts you is a tool you switch off
after the first incident.

The goal is to **separate decisions from confirmations, and eliminate the confirmations** — and that
gives a test anyone can apply: *every remaining interruption should be a choice only you could make.*

Six things interrupt a session. Only one of them is genuinely yours:

| Cause | Yours? | What removes it |
|---|---|---|
| A permission prompt on a tool | never | the auto-allow hook, and the permission fence |
| "Shall I proceed?" halfway through an approved list | no | the autonomy charter |
| The turn simply ending after a task | no | the autopilot `Stop` hook |
| The model stuck on an ambiguity | **almost never** — it is an undeclared default | the declared defaults |
| An irreversible or outward-facing action | **yes** | kept, and reinforced |
| A red gate | no | repair, with a retry budget |

The fourth row is the largest and the least obvious. Most questions you get asked are not decisions,
they are defaults nobody ever wrote down: *extend the existing type or add a parallel one? unit or
integration test? break the signature or add an overload?* Declare them once and they stop costing
anything, forever.

## What you already get for free

Worth saying before anything is claimed for this repo:

- **`/model opusplan`** — Opus plans, Sonnet executes. That is the advisor strategy, natively, at no
  cost.
- **`model:` in agent and skill frontmatter** — pin any subagent to `haiku`, `sonnet`, `opus` or
  `fable`.
- **Prompt caching**, automatic, 1-hour TTL on a subscription. `/usage` reports the hit rate.

Of the four ideas that inspired this, two are not actionable inside Claude Code at all, and saying
so is part of the product:

| Idea | Inside Claude Code | Actionable |
|---|---|---|
| Cache repeated context | automatic, nothing to switch on | **as hygiene only** — see below |
| Batch large jobs | the Batch API is not exposed | **by analogy**: subagent fan-out, and **no discount** |
| Match the model to the task | `model:` in frontmatter | **yes**, and it is the heart |
| Advisor strategy | an API beta, absent here | **by analogy** — and `opusplan` already does it |

The caching hygiene that *is* real, and that nobody writes down: what **breaks** the cache — switching
model mid-session, changing effort, editing `CLAUDE.md` while you work, enabling or disabling plugins.

**So what does this repo add?** One thing: **the policy**. A map, written once, that turns routing
from a choice you re-make every session into a property of the repository. Everything else here is
plumbing for that.

## Is it done? The question every report must answer

The charter carries a rule that costs nothing and changes what you read: **the first line of any
hand-back is a verdict** — DONE, NOT DONE, or BLOCKED — and then the detail.

With a definition of done that refuses the comfortable answers:

- the gate must be **green and run**. **Unverified is not done**, it is unknown;
- nothing left deliberately failing, nothing kept "for later", no problem found and not fixed;
- a green gate does not make a task done when something outside the gate was left broken.

And a reporting shape that keeps three things apart — what was delivered, what is still open and who
it waits on, and what was found along the way. **A finding is not a deliverable:** three problems
found and one fixed is *one fixed, two open*, never "three addressed".

This exists because of a real report — dense, accurate, full of genuine findings, and impossible to
answer *"is this finished?"* from without reading to the end.

## When it's done, it's done — and the rest goes to the backlog

A session that keeps widening becomes one nobody can review. The second thing is always done with
worse attention than the first: the context is full, the original goal is far behind, and nobody
decided the new work was worth doing.

So the charter draws a boundary at *finished*, and sorts what you run into:

| What came up | Where it goes |
|---|---|
| It **blocks** the task | Now. It was part of the task, you just didn't know yet. |
| You **broke** something that worked | Now. You caused it. |
| **Anything else you noticed** | `.efficiency/backlog.md`. Not this session. |

The third row is the one that feels wrong to obey, and it is the one that matters — a clear, real
improvement spotted mid-task is exactly what quietly doubles a diff nobody agreed to.

**Open items are put in front of you at the start of every session**, by the same hook that carries
the charter, with instructions to mention them once and **not** to start on them. Picking one up
because it is in front of you is the same scope creep, one session later.

**And they stay in front of you.** Announced once, a backlog is gone by the third reply — on this
repo that injection reached 18 KB, the harness truncated it to a preview, and the text that did
survive asked for two lines in one reply. So `/efficiency:init` also offers a **status line**: the
open count and the top three items, re-rendered under the prompt on every update, for as long as
they are open.

```text
◆ Opus 5.5 │ ▸ my-project │ ⎇ main │ ████░░░░░░ 38% │ $2.41 │ ⏱ 65m │ 5h 22%
⚠ backlog: 12 open · oldest 2026-10-10 · +9 more · /efficiency:backlog
  1. /efficiency:init cannot write the permission fence
  2. The session that builds a release can never run it
  3. Model routing has never been observed working
```

The first line is the session: model, branch, how full the context is, what has been spent, how close
the five-hour limit is. It is there because a project's `statusLine` overrides your own, so a
backlog-only bar would quietly take away the gauge you decide to compact by.

It reads a few small files per render and runs nothing, not even `git`, because it is re-run every
second or so — measured, along with the fact that all of its lines are shown and that it takes effect
without restarting the session, in § 12 of `docs/verified-platform-behaviour.md`. An existing
`statusLine` is never replaced, and `statusline: off` in the policy frontmatter ends the subject.

**And replies say where you are needed.** `init` also offers the `Signals` output style: every reply
with more than one point opens with the result in a line, then splits into short sections behind
coloured markers — 🟢 outcome, 🔴 problem, 🟡 warning, 🟣 your call, 🔵 next step — with the labels
in your language. The 🟣 section is the point: a decision only you can make never sits in the middle
of a paragraph. It goes in `.claude/settings.local.json` as `efficiency:Signals`, because it is a
personal preference rather than a project rule.

Each entry carries a `found while:` clause, because a fresh session has none of the context that
made the thing obvious — and that is the cheapest way to hand it back.

## Reach for the tool before writing the script

The expensive failure is not a missing tool — it is a **present tool nobody knew about**. Asked to
pull text out of a PDF, a session that doesn't know `pdftotext` is installed writes Python with
pypdf, fights the encodings, and spends thousands of tokens on what one command does in fifty.

So the `SessionStart` hook runs `scripts/detect-tools.sh` itself — nothing for an adopter to
remember, and nothing for a session to reach outside its own project — and every session is handed
the list of operational tools this machine actually has: document conversion, PDF, CSV, media,
search, platform CLIs, with what each is for. It is rewritten whenever it is missing or more than a
week old, so deleting it after an install is how you refresh it.

**Gitignored, because it describes a machine and not a project.** A colleague's laptop is a
different laptop, and a shared list describing someone else's is worse than no list.

When the right tool is genuinely absent, the charter says to name it and offer to install it **once**
— with two things said out loud: whether it will be needed again, and whether the project's CI needs
it too. *A tool present on your machine and absent from CI is a difference that bites later.*

Tools are checked for staleness at most once per session, and **never updated mid-task**: a version
change alters behaviour under work already in progress.

### And one absence the framework now raises by name

Reading a PDF costs **~1,300 tokens per page whatever is printed on it** — measured, and a page
holding seven lines cost slightly *more* than the average full one, because each page is rendered to
an image of fixed size and the bill never looks at the content.

What that does **not** buy you is the obvious conclusion. Converting a densely printed page to text
saved **9%** here: at ~3 characters per token the break-even is around 3,500 characters a page, which
is roughly a page of margin-to-margin prose. Converting is worth doing for a different reason —
converted once **to a file**, a document becomes greppable, and forty pages that would cost ~52,000
tokens to look through become one search and one forty-line slice.

So `init` now checks for a PDF-to-Markdown converter in every project, not just document-shaped ones,
and offers two: **docling** for everyday documents, **marker** for the complex tables and image-heavy
pages where docling comes out visibly wrong. It checks the Python version first, because `pip` will
not — on 3.9 `pip install docling` silently resolves to the last release that supported it.

And the case where converting is simply the wrong move is written into the charter alongside the
rest: when the layout **is** the content — a scan, a signature, how a chart looks — read the page.

## The bargain

Autonomy is bought with two things, not one. Both are conditions of use:

1. **An executable oracle.** Your project declares its gate command. `/efficiency:run` **refuses to
   start without one** — that is structural, not advice. Autonomy without an automatic judge is not
   autonomy, it is unsupervised drift.
2. **A written record.** Every decision taken without asking goes into the run log. You stop
   supervising in real time and read the log afterwards. That is the trade. A decision missing from
   the log was never really delegated.

## Install

Two steps, and they live in different places on purpose.

### 1. Add the marketplace — once per machine

```bash
claude plugin marketplace add nicolx/claude-efficiency-framework
```

This lands in **user** settings and does not travel with any repo. That is the right boundary:
trusting a marketplace is the machine owner's decision, and a repository that could make it for you
would be one that runs arbitrary hooks the moment you cloned it. (`--scope project` exists and writes
`extraKnownMarketplaces` into a project, but measured: it is honoured only where the marketplace is
*already* known to the machine. A project cannot cause a first-time fetch.)

### 2. Enable the plugin — and pick the scope deliberately

> ⚠ **`--scope` defaults to `user`.** Omitting it enables the plugin for every project on your
> machine. That is often what you want — see below — but it should be a choice, not a surprise.

```bash
# Everywhere on this machine. Nothing travels with any repo.
claude plugin install efficiency@claude-efficiency-framework

# Just this project, and committed so the team gets it.
claude plugin install efficiency@claude-efficiency-framework --scope project
```

Then **restart Claude Code** — hooks load at session start.

### Which scope

| | `--scope user` (default) | `--scope project` |
|---|---|---|
| Install | once, ever | once per project |
| Travels with the repo | no | **the intent does** — `enabledPlugins` is written into `.claude/settings.json`, which you commit |
| A colleague who clones | runs both commands | runs both commands, and the project's choice is already recorded |

**Committing `enabledPlugins` is not enough on its own.** Measured, by removing each half in turn:
the plugin loads only when a settings file enables it **and** this machine has an install recorded in
`~/.claude/plugins/installed_plugins.json`. Either alone does nothing.

So a teammate who clones still runs both commands. That is the right design rather than a gap: the
committed setting is the project's *intent*, and `claude plugin install` on each machine is the
*consent*. A repository that could enable a hook-running plugin by itself would be a repository that
runs code the moment you clone it.

**User scope is safer than it sounds, because the plugin is inert without `.efficiency/policy.md`.**
Nothing fires, nothing is injected, nothing costs a token in a project that has not adopted it. So
installing once for everything is not invasive — adoption stays a file, not a switch.

**Recommendation:** `user` for your own projects — install once, then run `/efficiency:init` wherever
you actually want it. **`project`** for shared repositories, so that cloning is enough.

### Updating

You never uninstall. Two commands, and the first alone does nothing:

```bash
claude plugin marketplace update claude-efficiency-framework      # refreshes the catalogue only
claude plugin update efficiency@claude-efficiency-framework       # updates YOUR install
```

Then **restart Claude Code**. Check what you are actually on with `claude plugin list`.

**Three traps, all measured here:**

- `marketplace update` reports success while the plugin you are running stays exactly where it was.
  It moves the catalogue, not your install.
- `plugin update` auto-detects the scope in current versions, but against a project-scope install an
  older one failed with *"not installed at scope user"* — which reads like the plugin is missing
  rather than like a scope mismatch. Pass `--scope project` if it does.
- **`claude plugin list` prints one entry per project install with no project path**, so two
  installs look like one plugin listed twice at different versions.
  `~/.claude/plugins/installed_plugins.json` records `projectPath` and disambiguates. Three test runs
  of this framework silently executed 0.1.0 because of exactly that misreading.

### Is the upgrade safe?

Partly, and it is worth being precise about which part.

**What is guaranteed.** The catalogue pins a release tag rather than tracking `main`, so you get a
version that was deliberately published and never the middle of someone's refactor. The repo's own
gate refuses to let a release ship whose `VERSION`, manifests and changelog entry disagree, and
refuses to let one ship whose tag was never cut at all. That last half is new, and it is here
because the sentence used to claim it when it was not true: the gate compared the ref written in
`marketplace.json` to `VERSION` and never asked git whether anything of that name existed. Six
versions, 0.14.0 through 0.18.1, were committed and announced without ever being tagged or pushed
while this paragraph read as a guarantee.

**What is not.** There is no `--version` flag on install or update: you get what the catalogue
currently pins, and there is no supported rollback to an earlier release. If one bites you, the
recourse is `claude plugin uninstall` and reinstalling from a marketplace you pin yourself.

**The failure worth knowing about, because it is silent.** 0.4.0 moved every file this framework
writes out of `.claude/` — Claude Code refuses writes there, which meant the model could never tick a
task closed or arm the autopilot at all. A project upgraded across that move keeps its policy where
0.3.x left it while the plugin looks in the new place, and **everything stops: no charter, no policy,
no guards, and no error**.

Two things now catch it. Any session in such a project is told, in the first thing it reads, that the
install is inert and why. And:

```bash
bash scripts/check-install.sh                 # read-only: does this project's install work?
```

### The validator

It checks the **chain**, not the files — because files that look right in a project where nothing is
enabled is a project where nothing happens, and an earlier version of this script cheerfully reported
CONFORMANT for exactly that.

| | |
|---|---|
| Prerequisites | `python3` present, and 3.7 or newer |
| Reachability | the plugin is actually enabled here — project scope, user scope, or neither — and at which version |
| Project files | policy present and in the right place; frontmatter parses; `budget`, `tiers`, `routing`, `stop_for` declared; defaults written |
| The gate | declared, its runner on `PATH`, and its target actually existing — a gate pointing at a renamed script fails on every turn |
| Hooks, actually run | all three are invoked and their output checked; this is the difference between *looks right* and *works* |
| Hygiene | run state and inventory gitignored, policy and backlog tracked |
| State | a run left `ACTIVE` or `BLOCKED` |

Exit `0` conformant, `1` not, `2` cannot tell. Read-only, no network, and it never runs your gate —
a validator that executes a test suite is one nobody runs.

`scripts/test-check-install.sh` proves it can fail, across nine scenarios, and both run in this
repo's own gate. A validator that cannot report a problem is worse than none: it says the install is
fine about nothing at all.

`/efficiency:init` performs the migration; nothing moves a developer's files unasked.

**After any upgrade, the honest check is one line**: run `check-install.sh`, or simply start a
session and see whether the charter arrives.

### Configure a project

```text
/efficiency:init
```

Nothing happens in a project until this has run. There is otherwise no install script, no copied
command files to keep in step, and no version marker.

**Everything this framework writes lives in `.efficiency/` at the project root** — the policy
(committed), the run, and the hook's counters (both gitignored). Not in `.claude/`: Claude Code
refuses writes there under the permission modes an unattended run actually uses — `acceptEdits` and
`dontAsk` — across every tool, and no allow rule lifts it. Files the model has to update cannot live
somewhere it may not be allowed to write. That one fact is why the autopilot can arm itself at all.

**The plugin is inert in any project without `.efficiency/policy.md`.** Nothing fires, nothing is
injected, nothing costs a token. Adoption is a file, not a switch.

**In a project that has adopted it, every session is handed four things** by one `SessionStart`
hook: any open backlog items, the autonomy charter, the project's own policy — tiers, routing,
`stop_for`, declared defaults — and the list of operational tools this machine has. Around 3,000
tokens, with nothing to `@`-include and no copy in your `CLAUDE.md` to keep in step.

The same hook writes `.efficiency/statusline.py` into the project, because the status line command
is not told where the plugin lives — measured. It is gitignored: it is a copy of plugin code, and it
is refreshed whenever the plugin changes.

## Using it

| Step | Command | How often |
|---|---|---|
| Configure the project | `/efficiency:init` | once |
| Turn an objective into an approved run | `/efficiency:plan-run` | per piece of work |
| Execute it | `/efficiency:run` | per piece of work |
| Read what happened | `/efficiency:run-report` | after |
| Parallelise a batch outside a run | `/efficiency:fanout` | only when you ask |

### You do not have to use the commands

Telling Claude to carry work through to the end — *"keep going until it's done"*, *"don't check in
with me"*, in any words and any language — arms the same machinery. The charter loaded into every
session treats that as the approval it is, and `efficiency:autopilot` does the arming.

This matters more than it sounds. The `Stop` hook is the part that actually removes the
interruption, and it only engages while a run file exists. Without this path you say "carry on until
it's finished", the model agrees, does one task, and the turn ends anyway — the intent was real and
nothing was listening.

The commands remain for work worth planning deliberately. Both paths get the same guards.

### The three things you have to supply

`init` proposes all three by reading the repo, and you correct them. They are what decides whether
the benefits are real or decorative:

1. **The gate command.** Mandatory — `run` **refuses to start without one**. Whatever you would run
   before committing: `bin/qa`, `composer qa`, `npm run check`, `make check`. It is the only thing
   that makes autonomy supervised rather than drift.
2. **The criticality patterns.** Which paths are `critical` and which are `sensitive`. Where they are
   silent the model classifies and proposes the missing pattern, so the map completes itself as you
   use it.
3. **The declared defaults.** The largest source of interruptions, because most questions you get
   asked are not decisions — they are defaults nobody wrote down. Every run proposes new ones.

### Calibrate the ceiling after a run or two

The per-task ceiling ships at **$5.00** for a standard task and is switched on from the first day;
`tier_multiplier` scales it for the other tiers, from half for mechanical work to four times for
critical. Once `run-report` has shown you what a task really costs, put that period's worth in
`basket_usd` and the base becomes 20% of a measurement instead of 20% of a guess.

**`plan-run` is where your attention goes.** You approve a list once: each task with its criticality
tier, its model, and acceptance criteria a reviewer can check. Everything after that is a
consequence of that approval.

Criticality is assigned **by declared path pattern first**. Where the patterns are silent the model
classifies, says so in one line, and proposes the pattern that would have decided it — so the map
gets built by using it rather than at a desk.

**Economy or fast is decided in the plan, too.** Each task names the files it touches and what it
waits for, and that groups the list into waves of tasks that cannot collide. Economy works them one
after another in one session, the cheap way. Fast gives every task of a wave its own subagent, so you
wait for the longest task instead of the sum, and pay each subagent's context on top. The policy's
`parallel` block says when that trade is worth proposing — wide waves *and* long serial work — and
you can override it in a word either way. Approving the plan approves the mode, and its cost.

## The six guards

The autopilot refuses to end a turn while the approved run has work left. Six things stop it, in
this order:

1. **Declared ceilings.** A run file that never names `task_spend_max_micro_usd` or
   `continuations_max` does not run at all. The guard below only executes when a ceiling is set, so a
   run file without one used to skip the ceiling *and* its fail-closed branch together and proceed
   unbounded in silence — measured on a real run that executed three tasks that way. A ceiling
   someone deliberately set to `0` is a decision and is honoured, but it is named in every
   continuation rather than left to be inferred.
2. **The per-task spend ceiling.** Default 20% of your declared basket for a standard task, scaled
   by the task's tier — `tier_multiplier`, read once when the run starts and capped at 10 by the
   hook, so a policy edited mid-run cannot widen it. Measured from the session transcript in dollars
   at API list prices — **subagents included**, since delegating review to an expensive model is
   the point. It catches the case the others miss: one task that keeps looking productive and never
   closes. It stops that task and asks you, and the session stays alive. The window it measures
   opens when a task is *closed*, not when `current_task` is rewritten: the model writes that line,
   and a ceiling it can reopen is not a ceiling. In fast mode the window belongs to the whole wave:
   its ceiling is the sum of its tasks' scaled ceilings, and it closes only when every task in the
   wave has.
   It is the one guard that also acts **inside** a turn: a second hook refuses tool calls once the
   ceiling is crossed, instead of waiting for a turn that has no length limit to end. The refusal
   stops the spending; the stop above still delivers the verdict, at the boundary, as it always did.
3. **The gate retry budget.** Repair attempts on the same red gate.
4. **The continuation budget.** For the run as a whole.
5. **The stall guard.** If the same task is handed back repeatedly with nothing closing, the wording
   escalates and then the run stops. This one exists because the framework's first real run on its
   own repository failed exactly that way: 12 continuations, the work of one task done, its checkbox
   never ticked, and the last restarts spent narrating the counter instead of working.
6. **The platform.** Claude Code overrides any `Stop` hook after 8 consecutive blocks **without
   progress** — and it counts blocked *turns*, so a project's own `Stop` hook shares that budget
   rather than halving it. Ours must fire first, because the first five write a reason you can read
   and this one does not.

If spend cannot be measured, the run **stops**. An unmeasured ceiling is not a ceiling.

**Counters and ceilings live in a file no skill mentions** — `.efficiency/autopilot.json` —
and the hook reads only from there. Editing the run file to raise a budget changes nothing, and
setting `status` back to `ACTIVE` does not resume a run a guard stopped. The legitimate way to start
over is to change the task list, which is what re-planning already does.

The reason is not that a model was caught cheating. It is that a guard whose counters live in a file
the model is asked to edit depends on the model preserving keys nobody told it were load-bearing.
Six selftest cases hold that separation in place: raising a budget in the run file, flipping `status`
back to `ACTIVE`, and rewriting the frontmatter the way a tidy editor would all change nothing.

## What was measured rather than read

`docs/verified-platform-behaviour.md` records every platform fact this design rests on, with the
method and the date, re-runnable via `scripts/probes/stop-cap.sh`. Three that were not in any
documentation:

- **The 8-block cap counts blocks without progress, and any tool call resets it** — a read-only one
  is enough. So it never truncates a run that is working; it is a free anti-stall guard, not a
  ceiling on autonomy.
- **`transcript_path` arrives in the `Stop` payload**, though the reference does not list it for that
  event. This is what makes spend measurable at all.
- **A status line renders every line its command prints**, is re-run on conversation updates rather
  than once per turn, and takes effect without restarting the session. That is what makes a four-line
  backlog reminder possible at all — and what makes it a few file reads and no subprocess.
- **A plugin can ship an output style, but only by its prefixed name.** `efficiency:Signals` resolves;
  `Signals` silently falls back to the default, while the session's `init` event still reports the
  name it was given — so the only evidence a style took is what the model writes.
- **Subagent turns are not in the main transcript.** `isSidechain` is in the schema and reads like a
  promise, but they live in `<session>/subagents/agent-*.jsonl`. On the session that built this
  framework they were **17% of real spend** — and a ceiling blind to them is a ceiling on the cheap
  work only.
- **A PDF page costs the same whether it is full or nearly empty** — ~1,300 tokens either way — and
  converting a dense page to text saves about 9%, not an order of magnitude. The saving is in the
  pages you then never read, which is why the conversion has to go to a file.

## Requirements and limits

- **`python3 >= 3.7`** must be on `PATH` (uses `datetime.fromisoformat()` from 3.7, in
  `hooks/lib/spend.py`). The payload is JSON, the measurement is JSONL, the state is frontmatter.
- **Permission rules cannot ship in a plugin** — a plugin's `settings.json` accepts only `agent` and
  `subagentStatusLine` — so `/efficiency:init` writes them into your project and reports every line
  it touched. It is the only invasive write the framework makes.
- **Non-destructive Bash runs without a prompt** in a project with a policy: the `PreToolUse` hook
  answers "allow" for `git commit`, `git push` without force, read-only commands and chains of
  them. It errs only towards asking — force-push, `reset`, `clean`, `rm`, substitution and
  redirection to a file still prompt — and your deny rules still win. `auto_allow: off` in the
  policy switches it off; nothing in the project can widen it.
- **The spend ceiling is a net against a wasted night, not a meter accurate to the cent.** It is read
  inside the turn as well as at its end, but not before every single action: the reading is reused
  for a few seconds, and it trails the session by one assistant message, because the message that
  issued the call being refused has not been written to the transcript yet. Both were measured
  (`docs/verified-platform-behaviour.md` § 17), and both make the ceiling a little late — never
  early, which is the safe direction for a ceiling.
- **Dollars are a proxy.** On a subscription you spend plan allowance, not dollars. The figure is the
  only common unit a hook can compute, and it moves in proportion.
- **Model prices go stale.** `hooks/lib/model-costs.json` carries the date it was verified. A stale
  table makes the ceiling lie in whichever direction the price moved.

## This is not a quality framework

It answers *who does the work, on which model, and when do you need to be involved*. It does not
answer *is this any good* — that belongs to whatever coding standard your project declares. The
`reviewer` agent measures one thing only: **does the diff do what the task said, and only that?**
If your project declares a standard, the reviewer applies it too. If not, it still works.

## Layout

```text
.claude-plugin/   plugin and marketplace manifests
agents/           implementer-fast (haiku) · architect (opus) · reviewer (opus)
skills/           init · plan-run · run · fanout · run-report
output-styles/    Signals, the opt-in reply format
hooks/            the autopilot Stop hook and its mid-turn half, the SessionStart charter,
                  the spend meter, the backlog status line
templates/        the policy and permission scaffolding a project owns
scripts/          this repo's own gate, and the platform probes
docs/             what was measured, and how to measure it again
```

## Developing this repo

`bash scripts/qa.sh` before every commit. It reports what it could **not** run rather than passing
silently, and exits 2 for "passed what could run".

The hook has its own suite: `python3 hooks/autopilot-stop.py --selftest`.
