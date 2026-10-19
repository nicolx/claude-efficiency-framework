---
name: run-report
description: Report what a run actually did — tasks closed, decisions taken autonomously, spend by model and by tier, and what still needs a human. Also used to calibrate the spend ceiling from a real measurement. Use after a run finishes or stops, and whenever the user asks how it went or what it cost — "how did that run go", "what did it cost", "what still needs me", "quanto e costato quel run".
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
`status`, `blocked_reason`, the counters, `mode` and `mode_reason`, and any
proposed policy additions. A run file without `mode` was economy.

**Real spend**, already measured for you. The autopilot writes two frontmatter
keys into the run file every time it checks the ceiling:

- `task_spend_micro_usd` — the total since the current task opened;
- `task_spend_by_model` — the same split per model, as `model=micro_usd` pairs.

A third key appears only when something went wrong with the measurement:

- `task_spend_unpriced_models` — ids the cost table did not know, which were
  therefore charged at the fallback rate. The fallback is the most expensive row
  in the table, chosen so a ceiling is never raised by accident. For a *report*
  that is the wrong direction: a Haiku subagent priced as the top model reads as
  five times what it cost, which makes routing look like it achieved nothing.
  **If that key is present, say so before the table**, give the total as an upper
  bound rather than a figure, and name the ids — the fix is a line in the cost
  table, and nobody can make it if the report hides the problem.

In fast mode the window those keys measure is a **wave**, not a task, and it
resets when the wave closes — so they only ever hold the wave in flight. The
finished waves are in a fourth key, written by the hook as each one closes:

- `wave_spend_micro_usd` — `T1,T2,T3=2500000; T4=900000`, in wave order. A value
  of `unmeasured` means the hook could not read that wave's spend: report it as
  unknown, never as zero.

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

**Mode.** Say which it was and why, from `mode_reason`. In fast mode, give the
spend **per wave**, with its width: that is the premium the developer approved,
and the evidence for whether the trade was worth it.

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

Show the developer what this run cost per task, grouped by tier, against that
tier's ceiling — the base × the tier's `tier_multiplier`. A single average
across tiers hides exactly what the multipliers are for: a critical task near
its ceiling and a mechanical one far under it. In fast mode, per task is a
wave's spend divided by its width — an average, and say so; a mixed-tier wave
compares against the sum of its tasks' ceilings. Then:

- if `basket_usd` is still 0, they now have a real per-task figure to size it
  from — offer the arithmetic rather than a number they have to derive
- if one tier keeps landing near its ceiling, or far below it, that tier's
  multiplier is the number to change, not the base
- if a guard stopped the run, say whether the ceiling looks too tight for the
  work or the work genuinely ran away. Those need opposite fixes, and the
  difference is visible in whether the task was still making progress

## Policy additions

End with the proposed defaults and tier patterns the run accumulated, ready to
paste into `.efficiency/policy.md`.

Every one of them is an interruption that will not happen again. That is the
metric this framework is judged on, so it belongs at the end of every report
rather than buried in the run file.
