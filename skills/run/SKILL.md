---
name: run
description: Start or resume an approved run — execute the task list to the end, routing each task to its model, running the gate, and logging every autonomous decision. Use when the user wants execution to begin, or wants a stopped run picked back up — "start the run", "go ahead with the plan", "resume where it stopped", "riprendi da dove si era fermato".
---

# run

Execute the approved run in `.efficiency/run.md` to the end.

The autopilot hook keeps the turn from ending while tasks remain open, so your
job is not to remember to continue — it is to do each task properly and leave
the state honest.

## Before starting

**Refuse to start without a gate.** If `gate` in `.efficiency/policy.md` is
empty, stop and say so: autonomy without an executable oracle is unsupervised
drift, and this is the one refusal the framework makes on purpose.

**If the run is BLOCKED**, do not silently resume it. Show the developer
`blocked_reason` and what you propose. Setting `status` back to `ACTIVE` does
nothing — the hook keeps the verdict in its own state and will stop the run
again. Resuming is either a re-plan of the task list, or the developer deleting
`.efficiency/autopilot.json` themselves. Both are deliberate, which is
the point.

**If there is no run file**, say so and point at `/efficiency:plan-run`. Do not
improvise a run: an unapproved list executed autonomously is the failure this
whole design is arranged to prevent.

**Read `mode` from the frontmatter.** It was decided and approved in the plan;
do not re-decide it here. A run file without `mode` — older ones, or one armed
by `autopilot` without it — is economy.

## Economy mode: each task, in order

1. **Mark it started.** Set `current_task` to this task's id — and nothing else in
   the frontmatter. It names the task in everything the hook reports; it does not
   move any counter. The hook owns the spend window and opens a fresh one when a
   task is **closed**, so the window for this task is everything spent since the
   previous one was ticked.
2. **Route it.** Read the tier and the model from the task line, and delegate
   accordingly:
   - `haiku` → the `efficiency:implementer-fast` agent, for work that is fully specified
   - `sonnet` → do it in this session unless the policy says otherwise
   - `design: opus` on a critical task → the `efficiency:architect` agent first, then
     implement its plan
   Route by what the policy says. Do not upgrade a task to a more expensive model
   because it feels harder, or downgrade one because it feels easy — that is the
   choice the policy exists to have already made.
3. **Do the work**, against the acceptance criteria written for that task.
4. **Review, if the task calls for it.** Delegate to the `efficiency:reviewer` agent with
   the diff and the task's acceptance criteria.
   - **PASS** → continue.
   - **CHANGES REQUESTED** → fix and re-review, once. If the second review still
     asks for changes, that is `ask: on_review_blocked`: stop and hand it over.
   - **NEEDS A HUMAN** → stop. This is a legitimate interruption.
5. **Close it, immediately.** Change `- [ ]` to `- [x]`, append the log line, and
   set `current_task` to the next id. Do all three as soon as the acceptance
   criteria are met and the gate is green — not at the end of the run.

   **An unticked box is indistinguishable from unfinished work**, so the autopilot
   will hand the same task back forever while you believe you already did it. That
   is measured, not hypothetical: it is how this framework's first real run burned
   twelve continuations on one task. The stall guard now catches it, but the guard
   stopping your run is a worse outcome than closing the task.

   A task marked done that is *not* done is the opposite failure and it is worse:
   it is the one lie that makes the whole log untrustworthy.

## Fast mode: wave by wave

The trade was approved with the plan: more spend, in exchange for waiting on the
longest task of each wave instead of the sum of them all. Repeat until no task is
open:

1. **Compute the wave.** The open tasks whose `after=` ids are all closed, minus
   file conflicts — two tasks whose `files=` overlap never share a wave, and a
   task with no `files=` runs alone — capped at `parallel.max_agents`. Take them
   in list order. Set `current_task` to the wave's first id; as in economy mode,
   it names, it does not count.
2. **A wave of one runs in this session**, exactly as an economy task. There is
   no speed to gain from a subagent, only its cost.
3. **Design first, where routed.** For the wave's critical tasks with
   `design: opus`, start one `efficiency:architect` per task, all in one message,
   and wait for their plans.
4. **Dispatch the wave in one message** — one subagent per task, every call in
   the same assistant message. Calls spread over several messages run one after
   another, and the wave becomes a slower, dearer economy run. Route each by its
   model: `haiku` → `efficiency:implementer-fast`; `sonnet` → a general-purpose
   subagent on `sonnet`. In fast mode `sonnet` tasks become subagents too — that
   is where the time comes from. Give each a precise brief: the statement, its
   acceptance criteria, the architect's plan if there is one, and its `files=`
   as the only files it may touch. Tell it not to edit `.efficiency/run.md` —
   the run file has one writer, this session. **A subagent that discovers it
   needs a decision must hand back rather than improvise**: with a wave running
   at once, improvised decisions are unreviewable.
5. **Wait for the whole wave**, then review where the task calls for it — one
   `efficiency:reviewer` per task, again in one message. The review rules are
   economy mode's step 4, per task.
6. **Run the gate once for the wave.** Red is repaired in this session, and the
   retry limit counts consecutive red gates, as it always has, whatever the wave.
7. **Close the wave's tasks.** Tick each one whose criteria are met, with its log
   line. A task handed back is not ticked: answer it from the declared defaults
   and log the answer, then do it in this session; if nothing covers it, it is a
   `stop_for` reason. Then **one line for the wave**: its ids and the gate
   result. Its spend is recorded by the hook, not by you.

The hook's spend ceiling covers the whole wave, not each subagent: the window
opens with the wave and closes when every task in it does. The arithmetic lives
in the hook and the policy, not here.

## Reporting back

Whenever you hand work back — at the end, or when a guard stops the run — **open with the verdict**:
DONE, NOT DONE, or BLOCKED, on its own first line, then the detail. The charter has the rule and the
reader has the question: *is this finished?* It must be answerable without reading to the end.

Unverified is not done. A gate you could not run, a task closed whose criteria you cannot confirm,
anything left deliberately failing — each makes the honest verdict NOT DONE, whatever else was
achieved.

## The log is the deal

Every decision you take without asking goes in the `## Log` section, one line:
what you decided, and why.

This is not bookkeeping. It is the consideration the developer gets in exchange
for not watching: they read the log instead of supervising in real time. **A
decision missing from the log was never really delegated** — it was just taken
unobserved.

Also append, as you go:

- **a proposed default**, whenever you had to decide something
  `.efficiency/policy.md` does not cover. The question you just answered is a
  default nobody wrote down; offer it so it never costs anything again.
- **a proposed tier pattern**, whenever you classified a task by judgement.

## When to stop, and when not to

Stop only for a reason in `stop_for`. The autonomy charter has the list and the
reasoning; it is loaded into this session already.

Never stop to ask whether to proceed, never confirm something already in the
approved list, and never summarise progress and wait. The list was approved:
finish it.

When a guard stops the run — the spend ceiling, the retry limit, the
continuation budget, the stall guard — the hook writes `blocked_reason` and the
turn ends. Report that plainly, with the number that caused it, and say what you
would do next. Do not try to clear the block: you cannot, and attempting it
wastes a turn.
