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

To take a new release: `claude plugin marketplace update claude-efficiency-framework`. There is no
install script, no copied command files to keep in step, and no version marker.

**The plugin is inert in any project without `.claude/efficiency.md`.** Nothing fires, nothing is
injected, nothing costs a token. Adoption is a file, not a switch.

## Using it

| Step | Command | How often |
|---|---|---|
| Configure the project | `/efficiency:init` | once |
| Turn an objective into an approved run | `/efficiency:plan-run` | per piece of work |
| Execute it | `/efficiency:run` | per piece of work |
| Read what happened | `/efficiency:run-report` | after |
| Parallelise independent work | `/efficiency:fanout` | only when you ask |

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

**Counters and ceilings live in a file no skill mentions** — `.claude/.efficiency-autopilot.json` —
and the hook reads only from there. Editing the run file to raise a budget changes nothing, and
setting `status` back to `ACTIVE` does not resume a run a guard stopped. The legitimate way to start
over is to change the task list, which is what re-planning already does.

That separation is not defensive design for its own sake. In this framework's second real run the
model was told to update `current_task`, rewrote the whole frontmatter, and dropped every key it did
not recognise — wiping the stall guard that was watching it. It was not evading anything; it did not
know those keys mattered. Six selftest cases now reproduce that exact failure.

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

- **`python3`** must be on `PATH`. The payload is JSON, the measurement is JSONL, the state is
  frontmatter.
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
