---
name: autopilot
description: Arm the autopilot from a plain instruction to keep working — "carry on until it's done", "don't check in with me", "work through the whole list", "procedi fino a completare", "non fermarti a chiedere", "finish this without asking". Use it whenever the developer signals they want work carried to completion without confirmations, instead of waiting for them to run /efficiency:plan-run. Also use it to disarm, when they say to stop the autopilot or that they want to be asked again.
---

# autopilot

Turn "keep going until it's done" into something the machinery actually honours.

## Why this exists

The `Stop` hook is what removes the structural interruption, and it only engages
while `.efficiency/run.md` exists. Without that file the developer says
"carry on until it's finished", the model agrees, does one task, and the turn
ends anyway — the intent was real and nothing was listening.

So treat the instruction as what it is: an approval. `plan-run` is the ceremony
for work worth planning carefully; this is the same arming without the ceremony,
because the guards are what make a run safe, not the ritual.

## Recognising the intent

Arm when the developer asks for work to be carried to completion without
check-ins. The wording varies and the language varies — the signal is *finish it,
stop asking me*, not any particular phrase.

**Do not** arm for an ordinary instruction to do something. "Fix this bug" is a
task, not a request for autonomy. Arming on every instruction would put a ceiling
and a counter around every exchange, which is noise.

When unsure, arm and say so in one line. The developer can tell you to stop, and
every guard still applies — an unwanted run costs one line of text, while a
missed one costs exactly the interruption this framework exists to remove.

## Before arming: two refusals

**No policy** (`.efficiency/policy.md` absent) — say the project has not adopted
the framework and offer `/efficiency:init`. Do not invent a policy.

**No gate** (`gate:` empty in the policy) — refuse, and say why in one sentence:
the autopilot would keep restarting with nothing checking the work, which is
drift rather than autonomy. Offer to help declare the gate. **This refusal is not
negotiable**, and it is the same one `/efficiency:run` makes.

## Arming

Write `.efficiency/run.md` from the work at hand:

```markdown
---
status: ACTIVE
gate: <the gate command from the policy>
continuations_used: 0
continuations_max: <budget.continuations from the policy>
gate_retries: 0
gate_retries_max: <budget.gate_retries from the policy>
current_task: T1
task_started_at: <now, ISO-8601 UTC>
task_spend_micro_usd: 0
task_spend_max_micro_usd: <the per-task ceiling, in micro-dollars>
blocked_reason:
mode: <economy | fast>
mode_reason: <one line>
---

## Tasks
- [ ] T1 [<tier>] <statement>    model=<model> files=<paths or globs>
- [ ] T2 [<tier>] <statement>    model=<model> after=T1 files=<paths or globs>

## Acceptance criteria
### T1
- <what makes this task done, observably>

## Log
- armed from a plain instruction to keep going, <timestamp>
- mode <economy | fast>: <why>
```

The figure written there is the **base**, a standard task's ceiling:
`basket_usd × task_pct / 100` when `basket_usd` is set, otherwise `task_usd`,
times 1000000. Never a tier's figure: the hook scales it by each task's
`budget.tier_multiplier`, and in fast mode sums the scaled figures over the wave,
whose window closes only when the whole wave does.

Four rules carry over from `plan-run` and are not optional here:

- **Assign tiers from the policy's declared path patterns**, and where they are
  silent classify, say so in one line, and propose the missing pattern.
- **Write acceptance criteria that are observable.** Without them nothing can
  judge the work done, and the autopilot will hand the same task back until a
  guard stops it. This is the failure mode this framework has actually
  experienced, not a hypothetical.
- **Split the work into tasks with one outcome each**, in an order that leaves
  the gate green at every boundary, each with the `files=` it will touch and,
  where order matters beyond files, the `after=` it waits for.
- **Resolve the mode** in the charter's order: the developer's override, then
  `parallel.default_mode`, then `min_wave` and `min_serial_minutes` against
  the widest wave and the serial estimate, as `plan-run` defines it. Nobody
  approves a plan
  here, so the choice goes in the log instead, with its reason: that line is
  the only place the developer sees the trade was made.

## Say what you armed, in one line

Name the ceiling and the continuation budget, because those decide how long the
run can go before it stops and asks. The ceiling you name is the effective one —
the base scaled by tier — never the base alone as if it were the ceiling:

> Autopilot armed: 3 tasks, economy, $5.00 base, $20.00 for the critical task,
> 40 continuations. It will stop on its own and tell you why.

In fast mode, name the waves and the widest one too, and give the ceiling as the
widest wave's figure, the sum of its tasks' scaled ceilings: it is the extra
spend the developer did not see in a plan.

Then start working. Do not wait for confirmation — the instruction to keep going
was the confirmation.

## When the work ends

Open with the verdict — **DONE**, **NOT DONE** or **BLOCKED** — on its own line, then the detail.
That is the charter's rule and it applies here exactly as in a planned run: the developer armed this
instead of watching, so the one thing they need first is whether it finished.

## Disarming

When the developer says to stop, or that they want to be asked again, set
`status: DONE` in the run file and say it is disarmed. Leave the log: it is the
record of what was decided while you were not being watched.

Deleting `.efficiency/autopilot.json` is the developer's call, never
yours — it is what makes a guard's verdict stick.
