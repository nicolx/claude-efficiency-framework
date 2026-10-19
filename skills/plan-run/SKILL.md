---
name: plan-run
description: Turn an objective into an approved run — a task list where every item carries its criticality tier, its model, and observable acceptance criteria. This is the one place the developer's attention is spent. Use when the user wants work planned before it is executed autonomously — "plan this out before we start", "turn this into a task list", "what would the run look like", "prepariamo il piano prima di partire".
---

# plan-run

Turn an objective into a list the autopilot can execute without asking anything.

**This is the only place the developer's attention is spent.** Everything the
framework does afterwards is a consequence of what gets agreed here, so the list
has to be good enough to be worth approving once — and specific enough that
executing it needs no further decisions.

## 1. Understand the objective, then decompose it

Read enough of the code to size the work honestly. A list built without reading
is a list that discovers its real shape halfway through, which is exactly when
interruptions happen.

Split the objective into tasks that each have **one observable outcome**. A task
that cannot be judged done or not done is not a task. Prefer fewer, larger tasks
over many trivial ones: every task boundary is a place the run can stall, and a
task too small to have acceptance criteria is administration, not work.

Order them so that each one leaves the gate green. A task that can only be
verified together with the next one should be one task.

For each task, also write down:

- **`files=`** — the paths, or globs, it will touch. You need them for the tier
  anyway; writing them down is what lets the run know which tasks can share a
  wave. A task left without `files=` is treated as touching everything, and runs
  alone.
- **`after=`** — the ids of the tasks that must be closed before it starts, when
  the order matters for more than files. Leave it out when it does not.

The order of the list still matters: it is the order of a run in economy mode,
and within a wave it is the order tasks are read. `after=` and `files=` do not
replace the rule above — every task, whichever wave it lands in, still leaves the
gate green.

## 2. Assign the tier — patterns first

Read `tiers` in `.efficiency/policy.md`. For each task, work out which files it
will touch:

- **A declared pattern matches** → that tier. No judgement, no discussion.
- **No pattern matches** → classify it yourself, state the tier **in one line
  with the reason**, and **propose the pattern that would have decided it**. Add
  the proposal to the run so it is not lost.

That last step is the whole mechanism: the map gets built by using it. A run that
classifies three tasks by judgement and proposes no patterns has quietly kept the
decision in the model instead of moving it into the repo.

Then read `routing` to get the model for each task, and whether a review gate
applies. Do not invent routing that the policy does not describe.

## 3. Write acceptance criteria that a reviewer can check

Each task needs criteria that are **observable**: a behaviour, a test that
passes, a value that appears, an error that is raised. These are what
`efficiency:reviewer` measures the diff against, so vagueness here is what makes a review
gate useless later.

"Handles errors properly" is not a criterion. "A malformed payload is rejected
before anything is written, and the existing test suite still passes" is.

For a `critical` task, delegate the design to the `efficiency:architect` agent first and
take the acceptance criteria from its plan.

## 4. Compute the ceilings

From `budget` in `.efficiency/policy.md`:

- `continuations_max` — the run's budget for automatic restarts.
- `gate_retries_max` — repair attempts on the same red gate.
- The base spend ceiling, a standard task's: `basket_usd × task_pct / 100` when
  `basket_usd` is set, otherwise `task_usd`. Convert to micro-dollars for the
  run file (`× 1000000`), because the hook does integer arithmetic. Write the
  base, not a tier's figure: the hook does the scaling.
- Each task's ceiling: the base × its tier's `tier_multiplier`. The multipliers
  are read once, when the run starts, so a policy edited mid-run cannot widen a
  run already approved. A policy without the key gets the defaults `init`
  writes.
- In fast mode, a wave's ceiling is the sum of its tasks' ceilings.

State the ceilings in dollars when you present the list — the base, and each
tier's where the plan uses more than one. They decide how long a run can chase
one problem before it stops and asks, and the developer should see them before
approving.

## 5. Group the waves and resolve the mode

Group the tasks into waves. A wave is the open tasks whose `after=` ids are all
closed, minus file conflicts — two tasks whose `files=` overlap never share one,
and a task with no `files=` runs alone — capped at `parallel.max_agents`. Walk the
list wave by wave as if each closed, and you have the shape of the run: how many
waves, and how wide the widest is.

A policy written before the `parallel` block existed has none. Read that as the
defaults `init` writes, which the hook assumes too, and propose adding the block
under "Proposed policy additions" so the project can see and tune it.

Then resolve the mode, against `parallel` in `.efficiency/policy.md` and the
charter's principle:

- **A verbal override wins.** The developer saying to go fast, or to keep it
  cheap — in any words, any language — decides it, whatever `default_mode` says.
- **Otherwise `default_mode`**, when it is `economy` or `fast`.
- **Otherwise (`auto`) judge it**: **fast** only if the widest wave is at least
  `parallel.min_wave` *and* the serial estimate — how long this session would
  take doing them one after another, counting test runs, iterations and code to
  read, not lines to type — reaches `parallel.min_serial_minutes`;
  **economy** in every other case. Width is countable from the plan; the minutes
  are your estimate from having read the code, made before anything starts. Of
  the two, duration is the stronger signal: fully specified tasks are written
  in a batch by one session faster than subagents can start, while tasks that
  need turns — unfamiliar code, slow tests, failures to iterate on — repay a
  subagent early. Say which one decided.

The run file records `fast` or `economy`, never `auto`: the decision is made here,
where it can be approved, not at execution time.

## 6. Present it, and get one approval

Show a compact table: task, tier, model, review, acceptance criteria in brief —
and in fast mode, the wave each task falls in. Underneath it, four lines: the
gate command, the per-task ceiling, the continuation budget, and the mode:

> Mode: **fast** — wide and long (~2 h serial) · 3 waves · widest 5 · premium: <estimate>

The premium is an estimate and should be called one: no overhead per subagent has
been measured yet, so give your reasoning — each subagent rebuilds context the
main session already holds — rather than a figure that looks measured. It is there
so the developer approves the trade knowingly, not to be precise. For economy, one line
is enough: the mode and the reason — waves and premium say nothing there.

Then ask for approval **once**. Say plainly what approval means: the run will
execute to the end and stop only for a reason in `stop_for`, and every autonomous
decision will be written to the run log. Approving the plan approves the mode —
in fast mode, the extra cost is part of what was agreed.

## 7. Write the run file

Write `.efficiency/run.md`:

```markdown
---
status: ACTIVE
gate: <the gate command from the policy>
continuations_used: 0
continuations_max: <from budget>
gate_retries: 0
gate_retries_max: <from budget>
current_task: T1
task_started_at: <now, ISO-8601 UTC, e.g. 2026-09-05T14:02:11Z>
task_spend_micro_usd: 0
task_spend_max_micro_usd: <the ceiling in micro-dollars>
blocked_reason:
mode: <economy | fast>
mode_reason: <one line — the override, the default, or width and duration>
---

## Tasks
- [ ] T1 [standard] <statement>    model=sonnet files=src/a.py,src/b.py
- [ ] T2 [critical] <statement>    model=sonnet review=opus files=src/auth/**
- [ ] T3 [mechanical] <statement>  model=haiku after=T1 files=src/c.py

## Acceptance criteria
### T1
- <observable criterion>

## Proposed policy additions
- tier pattern: "<glob>" → sensitive, because <reason>

## Log
- run approved <timestamp>
```

Two rules about this file:

- **Write it only after approval.** Its existence is what switches the autopilot
  on: the hook does nothing while it is absent. Writing it early arms an
  unapproved run.
- **The counters in the frontmatter are a mirror, not the source.** The hook keeps
  its own copy in `.efficiency/autopilot.json`, captures the ceilings there
  on first sight of the run, and reads only from there. Editing the frontmatter to
  buy more continuations or a bigger ceiling changes nothing — and the run file's
  `status` cannot resume a run a guard stopped either. The legitimate way to start
  over is to change the task list, which is what re-planning already does.

Finish by saying that `/efficiency:run` starts it, and that the autopilot needs
the hooks to have been loaded at session start.
