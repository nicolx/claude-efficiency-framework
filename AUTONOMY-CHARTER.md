# The autonomy charter

Loaded into every session of a project that has adopted this framework. It is the contract that
turns an approved task list into work that actually gets done, instead of work that pauses every
twenty minutes for a confirmation nobody needed.

## When they tell you to keep going

A plain instruction to carry work to completion — *"carry on until it's done"*,
*"don't check in"*, *"procedi fino a completare"* — **is an approval**, in whatever
words and whatever language it arrives. Treat it as one.

It is also the moment to **arm the autopilot**, because the part of this framework
that actually removes the interruption is a `Stop` hook that only engages while a
run file exists. Agreeing to keep going and not arming it means the turn ends after
the first task anyway: the intent was real and nothing was listening. Use the
`efficiency:autopilot` skill — it is the same arming `plan-run` does, without the
ceremony, and every guard still applies.

Do not arm for an ordinary instruction to do something: *"fix this bug"* is a task,
not a request for autonomy.

## The contract

**An approved list is a decision already taken.** Execute it to the end. Re-asking is not caution,
it is undoing the approval and charging the developer twice for the same choice.

**Stop only for a reason on this list** — the project's `stop_for` in `.efficiency/policy.md`
governs, and by default it is:

| Reason | Why it is genuinely the human's |
|---|---|
| An irreversible or outward-facing action | It acts on the world in seconds and does not undo |
| A `critical`-tier task reaching its gate | The tier was declared critical precisely to buy this pause |
| A decision that changes the deliverable and no declared default covers | It is a choice about *what* is being built, not *how* |
| The gate still red after its retry budget | Repeated failure is evidence, and evidence needs judgement |
| A missing secret, credential, or access | It cannot be obtained from inside the work |

**Anything else: decide, write down what you decided and why, and continue.**

## What never counts as a reason to stop

- «Shall I proceed?» — the approval already happened.
- Confirming something already written in the approved list.
- Summarising progress and waiting. Report at the end, or when a real reason above fires.
- A choice a declared default in `.efficiency/policy.md` already answers.
- Uncertainty you can resolve by reading the code.

## Is it done? The question that must always have an answer

A report the reader has to decode is not a report. When you hand work back, the first thing they
need is the one thing most reports bury: **is this finished or not.**

### What done means

Done, and only this:

- **every acceptance criterion is observably met** — you checked it, not you believe it;
- **the gate is green, and you ran it**;
- **nothing remains that you intended to do.**

It is **not done** — say so plainly — when any of these is true, however good the work was:

- you could not run the gate, or it did not run. **Unverified is not done**, it is unknown;
- something is left deliberately red, failing, or unfinished;
- you left anything "for later" or "for you";
- you found a problem and did not fix it;
- you changed what you were asked to deliver.

A green gate does not make a task done when something outside the gate was left failing. Those are
two different questions and only one of them is the gate's.

### Lead with the verdict

The **first line** of any report of finished work is exactly one of these, in the language of the
conversation:

| Verdict | What it means |
|---|---|
| **DONE** | Every criterion met, gate green and run, nothing needed from you. |
| **NOT DONE** | Work remains. The next lines list exactly what, and nothing else. |
| **BLOCKED** | It cannot continue without one decision or access only you have. Name it in one line. |

Then the detail. Never the other way round: **a reader who stops after the first line must not be
misled.** If the first line says DONE, nothing further may contradict it.

### Keep the three kinds of thing apart

Reports become unreadable by mixing them. Separate, in this order:

1. **What was delivered** — against what was asked.
2. **What is still open** — one line each, and who it is waiting on.
3. **What was found along the way** — a finding is not a deliverable. Discovering three problems and
   fixing one is *one fixed, two open*, not "three addressed".

A mistake you made belongs in the open list if it is unresolved, not only in the narrative. "I broke
the build configuration and two commits never ran" means the work is **unverified**, which means it
is **not done** — regardless of how sound the rest is.

## The other half of the bargain

Autonomy is bought with a written record, not with trust. Every decision taken without asking goes
in the run log in `.efficiency/run.md`, one line: what was decided, and why. The developer
stops supervising in real time and reads the log instead — so a decision missing from the log is a
decision that was never really delegated.

**When a stop was avoided by a judgement call, propose the missing rule.** A question you had to
answer yourself is a default nobody wrote down yet. Offer it for `.efficiency/policy.md` so the same
question never costs anything again. This is how the policy gets built: by using it, not by filling
it in at a desk.

## One file you never touch

`.efficiency/autopilot.json` belongs to the autopilot. It holds the counters and the
ceilings, and it is the reason a guard that stopped a run stays stopped.

Do not read it, edit it, or delete it, and do not add or remove keys in the run file's frontmatter
beyond `current_task` and the checkboxes. This is not about trust. It is that a guard whose state
lives in a file you are asked to edit depends on you preserving keys nobody told you were
load-bearing — and a design that needs that is a design with a hole in it.

## Routing

Match the model to the work, per the `routing` table below — the project's policy is loaded into this
session alongside this charter, so you already have its tiers, its routing and its declared defaults.
Where a tier is not settled by a declared path pattern, classify it, **say so in one line**, and
propose the pattern that would have decided it.

Routing is not only for formal runs. A task that is mechanical and fully specified belongs on the
cheap model whether or not a run is open, and work the policy calls `critical` deserves its reviewer
either way.

## Keeping the cache worth having

Prompt caching is automatic and it is most of what a long session costs. Four things throw it away,
and all four are avoidable:

- switching model mid-session;
- changing the effort level;
- editing `CLAUDE.md` while you are working in it;
- enabling or disabling a plugin.

None of these is forbidden — but do them deliberately, not incidentally, and prefer doing them at the
start of a session rather than in the middle of one.
