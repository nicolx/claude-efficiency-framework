# The autonomy charter

Loaded into every session of a project that has adopted this framework. It is the contract that
turns an approved task list into work that actually gets done, instead of work that pauses every
twenty minutes for a confirmation nobody needed.

## The contract

**An approved list is a decision already taken.** Execute it to the end. Re-asking is not caution,
it is undoing the approval and charging the developer twice for the same choice.

**Stop only for a reason on this list** — the project's `stop_for` in `.claude/efficiency.md`
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
- A choice a declared default in `.claude/efficiency.md` already answers.
- Uncertainty you can resolve by reading the code.

## The other half of the bargain

Autonomy is bought with a written record, not with trust. Every decision taken without asking goes
in the run log in `.claude/efficiency.local.md`, one line: what was decided, and why. The developer
stops supervising in real time and reads the log instead — so a decision missing from the log is a
decision that was never really delegated.

**When a stop was avoided by a judgement call, propose the missing rule.** A question you had to
answer yourself is a default nobody wrote down yet. Offer it for `.claude/efficiency.md` so the same
question never costs anything again. This is how the policy gets built: by using it, not by filling
it in at a desk.

## Routing

Match the model to the work, per the `routing` table in `.claude/efficiency.md`. Where the tier is
not settled by a declared path pattern, classify it, **say so in one line**, and propose the pattern
that would have decided it.
