---
name: plan-run
description: Turn an objective into an approved run — a task list where every item carries its criticality tier, its model, and observable acceptance criteria. This is the one place the developer's attention is spent. Use when the user wants to plan work for autonomous execution.
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

## 2. Assign the tier — patterns first

Read `tiers` in `.claude/efficiency.md`. For each task, work out which files it
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

From `budget` in `.claude/efficiency.md`:

- `continuations_max` — the run's budget for automatic restarts.
- `gate_retries_max` — repair attempts on the same red gate.
- The per-task spend ceiling: `basket_usd × task_pct / 100` when `basket_usd` is
  set, otherwise `task_usd`. Convert to micro-dollars for the run file
  (`× 1000000`), because the hook does integer arithmetic.

State the ceiling in dollars when you present the list. It is the number that
decides how long a run can chase one problem before it stops and asks, and the
developer should see it before approving.

## 5. Present it, and get one approval

Show a compact table: task, tier, model, review, acceptance criteria in brief.
Underneath it, three lines: the gate command, the per-task ceiling, and the
continuation budget.

Then ask for approval **once**. Say plainly what approval means: the run will
execute to the end and stop only for a reason in `stop_for`, and every autonomous
decision will be written to the run log.

## 6. Write the run file

Write `.claude/efficiency.local.md`:

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
---

## Tasks
- [ ] T1 [standard] <statement>    model=sonnet
- [ ] T2 [critical] <statement>    model=sonnet review=opus

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
  its own copy in `.claude/.efficiency-autopilot.json`, captures the ceilings there
  on first sight of the run, and reads only from there. Editing the frontmatter to
  buy more continuations or a bigger ceiling changes nothing — and the run file's
  `status` cannot resume a run a guard stopped either. The legitimate way to start
  over is to change the task list, which is what re-planning already does.

Finish by saying that `/efficiency:run` starts it, and that the autopilot needs
the hooks to have been loaded at session start.
