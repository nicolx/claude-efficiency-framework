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
| A permission prompt on a tool | never | the permission fence |
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

Each entry carries a `found while:` clause, because a fresh session has none of the context that
made the thing obvious — and that is the cheapest way to hand it back.

## Reach for the tool before writing the script

The expensive failure is not a missing tool — it is a **present tool nobody knew about**. Asked to
pull text out of a PDF, a session that doesn't know `pdftotext` is installed writes Python with
pypdf, fights the encodings, and spends thousands of tokens on what one command does in fifty.

So `init` runs `scripts/detect-tools.sh`, and every session afterwards is handed the list of
operational tools this machine actually has — document conversion, PDF, CSV, media, search,
platform CLIs — with what each is for.

**Gitignored, because it describes a machine and not a project.** A colleague's laptop is a
different laptop, and a shared list describing someone else's is worse than no list.

When the right tool is genuinely absent, the charter says to name it and offer to install it **once**
— with two things said out loud: whether it will be needed again, and whether the project's CI needs
it too. *A tool present on your machine and absent from CI is a difference that bites later.*

Tools are checked for staleness at most once per session, and **never updated mid-task**: a version
change alters behaviour under work already in progress.

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

**Once per machine** — add the marketplace:

```bash
claude plugin marketplace add nicolx/claude-efficiency-framework
```

**Once per project** — enable the plugin and commit that choice:

```bash
claude plugin install efficiency@claude-efficiency-framework --scope project
```

That writes exactly one thing into the project's `.claude/settings.json`, which you commit:

```json
{ "enabledPlugins": { "efficiency@claude-efficiency-framework": true } }
```

Then **restart Claude Code** — hooks load at session start.

**Why the marketplace step is separate, and stays yours.** `plugin install --scope project` writes
only `enabledPlugins` into the project. The marketplace goes to *user* settings by default, and a
teammate who clones runs that one command themselves. That is the right boundary: adding a
marketplace is a trust decision, and a repository that could make it on your behalf could run
arbitrary hooks the moment you cloned it.

`marketplace add --scope project` does exist, and writes `extraKnownMarketplaces` into the project
instead. With the marketplace already on the machine that declaration is honoured. Whether a project
declaring an **unknown** marketplace causes a first-time fetch could not be reproduced here — a
project carrying only the hand-written keys stayed empty — so treat the two commands above as the
path that is verified, and this as a convenience for machines that already trust the marketplace.

### Updating — the trap that cost three runs

Two commands, and the first one alone does nothing:

```bash
claude plugin marketplace update claude-efficiency-framework      # refreshes the catalogue
claude plugin update efficiency@claude-efficiency-framework \
    --scope project                                               # updates YOUR install
```

`marketplace update` refreshes the catalogue and reports success; the plugin you are running stays
at the version you installed. Worse, `plugin update` defaults to **user** scope, so against a
`--scope project` install it fails with *"not installed at scope user"* — pass the scope you
installed with. Then restart Claude Code.

Measured the hard way: three consecutive test runs of this framework silently executed **0.1.0**
while two releases sat in the refreshed catalogue, and the conclusions drawn from those runs had to
be retracted. `claude plugin list` shows the version actually installed — check it before believing
a test result.

There is otherwise no install script, no copied command files to keep in step, and no version
marker.

**Everything this framework writes lives in `.efficiency/` at the project root** — the policy
(committed), the run, and the hook's counters (both gitignored). Not in `.claude/`: Claude Code
refuses writes there, across every tool and regardless of permission rules, so files the model has
to update cannot live in it. That one fact is why the autopilot can arm itself at all.

**The plugin is inert in any project without `.efficiency/policy.md`.** Nothing fires, nothing is
injected, nothing costs a token. Adoption is a file, not a switch.

**In a project that has adopted it, every session is handed four things** by one `SessionStart`
hook: any open backlog items, the autonomy charter, the project's own policy — tiers, routing,
`stop_for`, declared defaults — and the list of operational tools this machine has. Around 3,000
tokens, with nothing to `@`-include and no copy in your `CLAUDE.md` to keep in step.

## Using it

| Step | Command | How often |
|---|---|---|
| Configure the project | `/efficiency:init` | once |
| Turn an objective into an approved run | `/efficiency:plan-run` | per piece of work |
| Execute it | `/efficiency:run` | per piece of work |
| Read what happened | `/efficiency:run-report` | after |
| Parallelise independent work | `/efficiency:fanout` | only when you ask |

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

The per-task ceiling ships at **$5.00** and is switched on from the first day. Once `run-report` has
shown you what a task really costs, put that period's worth in `basket_usd` and the ceiling becomes
20% of a measurement instead of 20% of a guess.

**`plan-run` is where your attention goes.** You approve a list once: each task with its criticality
tier, its model, and acceptance criteria a reviewer can check. Everything after that is a
consequence of that approval.

Criticality is assigned **by declared path pattern first**. Where the patterns are silent the model
classifies, says so in one line, and proposes the pattern that would have decided it — so the map
gets built by using it rather than at a desk.

## The five guards

The autopilot refuses to end a turn while the approved run has work left. Five things stop it, in
this order:

1. **The per-task spend ceiling.** Default 20% of your declared basket, measured from the session
   transcript in dollars at API list prices — **subagents included**, since delegating review to an
   expensive model is the point. It catches the case the others miss: one task that keeps looking
   productive and never closes. It stops that task and asks you, and the session stays alive.
2. **The gate retry budget.** Repair attempts on the same red gate.
3. **The continuation budget.** For the run as a whole.
4. **The stall guard.** If the same task is handed back repeatedly with nothing closing, the wording
   escalates and then the run stops. This one exists because the framework's first real run on its
   own repository failed exactly that way: 12 continuations, the work of one task done, its checkbox
   never ticked, and the last restarts spent narrating the counter instead of working.
5. **The platform.** Claude Code overrides any `Stop` hook after 8 consecutive blocks **without
   progress** — and it counts blocked *turns*, so a project's own `Stop` hook shares that budget
   rather than halving it. Ours must fire first, because the first four write a reason you can read
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
- **Subagent turns are not in the main transcript.** `isSidechain` is in the schema and reads like a
  promise, but they live in `<session>/subagents/agent-*.jsonl`. On the session that built this
  framework they were **17% of real spend** — and a ceiling blind to them is a ceiling on the cheap
  work only.

## Requirements and limits

- **`python3 >= 3.7`** must be on `PATH` (uses `datetime.fromisoformat()` from 3.7, in
  `hooks/lib/spend.py`). The payload is JSON, the measurement is JSONL, the state is frontmatter.
- **Permission rules cannot ship in a plugin** — a plugin's `settings.json` accepts only `agent` and
  `subagentStatusLine` — so `/efficiency:init` writes them into your project and reports every line
  it touched. It is the only invasive write the framework makes.
- **The spend ceiling is checked at turn boundaries**, not mid-turn. One very long turn can overshoot
  before it is stopped. This is a net against a wasted night, not a meter accurate to the cent.
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
hooks/            the autopilot Stop hook, the SessionStart charter, the spend meter
templates/        the policy and permission scaffolding a project owns
scripts/          this repo's own gate, and the platform probes
docs/             what was measured, and how to measure it again
```

## Developing this repo

`bash scripts/qa.sh` before every commit. It reports what it could **not** run rather than passing
silently, and exits 2 for "passed what could run".

The hook has its own suite: `python3 hooks/autopilot-stop.py --selftest`.
