---
name: run-report
description: Report what a run actually did — tasks closed, decisions taken autonomously, spend by model and by tier, and what still needs a human. Also used to calibrate the spend ceiling from a real measurement. Use after a run finishes or stops.
---

# run-report

Report what the run did, so the developer can read it instead of having watched
it.

## Open with the verdict, on its own line

Before anything else, answer the question the reader actually has:

| Verdict | When |
|---|---|
| **DONE** | Every task closed, every acceptance criterion observably met, gate green and run. |
| **NOT DONE** | Anything remains. The next lines are the list of what, and nothing else. |
| **BLOCKED** | A guard stopped the run, or it needs a decision only the developer can make. |

A task you marked closed but cannot confirm from the diff makes the run **NOT DONE**. So does a gate
you could not run: unverified is unknown, not finished.

Everything below the verdict is detail for someone who wants it. Nothing in it may contradict the
first line.

## What to gather

**From `.efficiency/run.md`:** the task list and its marks, the log,
`status`, `blocked_reason`, the counters, and any proposed policy additions.

**Real spend**, already measured for you. The autopilot writes two frontmatter
keys into the run file every time it checks the ceiling:

- `task_spend_micro_usd` — the total since the current task opened;
- `task_spend_by_model` — the same split per model, as `model=micro_usd` pairs.

Divide by 1000000 for dollars. Both come from the session transcript, **subagent
transcripts included** — those live in a sibling directory and are usually the
expensive half, so a figure that ignored them would flatter the routing exactly
where it costs most.

Do not try to run the measuring script yourself. It lives in the plugin's own
directory, and **nothing outside this project is reachable from a session** —
that is the platform's rule, not a missing permission. Everything you need is put
inside the project by the hooks.

## What to report

**Tasks.** Closed, open, and any marked done whose acceptance criteria you cannot
confirm from the diff. That last category matters most: it is where the log stops
being trustworthy.

**Decisions taken autonomously**, straight from the log. This is the part the
developer is actually reading. Do not summarise it away — if there were eleven
decisions, show eleven lines.

**Spend, by model.** Report dollars, and say what the figure is: what this work
would cost at API list prices, a proxy for plan allowance rather than a bill.
Where the split is interesting — an expensive reviewer taking most of the spend,
or a cheap implementer taking more than expected — say so. That is the evidence
that the routing policy is or is not earning its keep.

**Why it stopped.** If `status` is BLOCKED, give `blocked_reason` and the number
behind it. If DONE, say the gate was green and every task closed.

**What needs a human**, as a short list of actual decisions, not a summary.

**Findings go to the backlog, not into the next run.** Anything the run noticed
that was not the work belongs in `.efficiency/backlog.md`, one line with its
`found while:` clause. Say how many you filed; do not propose starting on them.

**Keep deliverables, open items and findings apart.** A finding is not a
deliverable: three problems found and one fixed is *one fixed, two open*, never
"three addressed". A mistake made during the run belongs in the open list while
it is unresolved, not only in the narrative.

## Calibrating the ceiling

The first few reports have a second job: turning `basket_usd` from a guess into
a measurement.

Show the developer what this run cost per task, and what the ceiling was. Then:

- if `basket_usd` is still 0, they now have a real per-task figure to size it
  from — offer the arithmetic rather than a number they have to derive
- if a guard stopped the run, say whether the ceiling looks too tight for the
  work or the work genuinely ran away. Those need opposite fixes, and the
  difference is visible in whether the task was still making progress

## Policy additions

End with the proposed defaults and tier patterns the run accumulated, ready to
paste into `.efficiency/policy.md`.

Every one of them is an interruption that will not happen again. That is the
metric this framework is judged on, so it belongs at the end of every report
rather than buried in the run file.
