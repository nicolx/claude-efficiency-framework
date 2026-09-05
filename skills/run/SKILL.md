---
name: run
description: Start or resume an approved run — execute the task list to the end, routing each task to its model, running the gate, and logging every autonomous decision. Use when the user wants to begin autonomous execution, or to resume a run that stopped.
---

# run

Execute the approved run in `.claude/efficiency.local.md` to the end.

The autopilot hook keeps the turn from ending while tasks remain open, so your
job is not to remember to continue — it is to do each task properly and leave
the state honest.

## Before starting

**Refuse to start without a gate.** If `gate` in `.claude/efficiency.md` is
empty, stop and say so: autonomy without an executable oracle is unsupervised
drift, and this is the one refusal the framework makes on purpose.

**If the run is BLOCKED**, do not silently resume it. Show the developer
`blocked_reason` and what you propose. Resuming means they decided to; clearing
that state yourself would defeat the guard that set it.

**If there is no run file**, say so and point at `/efficiency:plan-run`. Do not
improvise a run: an unapproved list executed autonomously is the failure this
whole design is arranged to prevent.

## For each task, in order

1. **Mark it started.** Set `current_task`, set `task_started_at` to now in
   ISO-8601 UTC, and reset `task_spend_micro_usd` to 0. The spend ceiling is
   measured from that marker, so a stale one means the previous task's spend is
   charged to this one and the run stops early for the wrong reason.
2. **Route it.** Read the tier and the model from the task line, and delegate
   accordingly:
   - `haiku` → the `implementer-fast` agent, for work that is fully specified
   - `sonnet` → do it in this session unless the policy says otherwise
   - `design: opus` on a critical task → the `architect` agent first, then
     implement its plan
   Route by what the policy says. Do not upgrade a task to a more expensive model
   because it feels harder, or downgrade one because it feels easy — that is the
   choice the policy exists to have already made.
3. **Do the work**, against the acceptance criteria written for that task.
4. **Review, if the task calls for it.** Delegate to the `reviewer` agent with
   the diff and the task's acceptance criteria.
   - **PASS** → continue.
   - **CHANGES REQUESTED** → fix and re-review, once. If the second review still
     asks for changes, that is `ask: on_review_blocked`: stop and hand it over.
   - **NEEDS A HUMAN** → stop. This is a legitimate interruption.
5. **Close it.** Change `- [ ]` to `- [x]` only when the acceptance criteria are
   met and the gate is green. A task marked done that is not done is worse than
   a task left open: it is the one lie that makes the whole log untrustworthy.

## The log is the deal

Every decision you take without asking goes in the `## Log` section, one line:
what you decided, and why.

This is not bookkeeping. It is the consideration the developer gets in exchange
for not watching: they read the log instead of supervising in real time. **A
decision missing from the log was never really delegated** — it was just taken
unobserved.

Also append, as you go:

- **a proposed default**, whenever you had to decide something
  `.claude/efficiency.md` does not cover. The question you just answered is a
  default nobody wrote down; offer it so it never costs anything again.
- **a proposed tier pattern**, whenever you classified a task by judgement.

## When to stop, and when not to

Stop only for a reason in `stop_for`. The autonomy charter has the list and the
reasoning; it is loaded into this session already.

Never stop to ask whether to proceed, never confirm something already in the
approved list, and never summarise progress and wait. The list was approved:
finish it.

When a guard stops the run — the spend ceiling, the retry limit, the
continuation budget — the hook writes `blocked_reason` and the turn ends. Report
that plainly, with the number that caused it, and say what you would do next.
Do not clear the block and carry on.
