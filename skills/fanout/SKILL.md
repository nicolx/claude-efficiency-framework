---
name: fanout
description: Run genuinely independent work in parallel across subagents, in batches, with one objective test per item. The nearest thing Claude Code has to the Batch API. Never start one unasked — it costs real money and it enlarges the diff. Use only when the user explicitly asks to parallelise a batch of independent work.
---

# fanout

Do a lot of independent work at once.

This is the analogue of the Batch API, and the analogy is worth stating honestly:
there is **no 50% discount** here. The Batch API is not exposed to Claude Code.
What a fan-out buys is wall-clock time and a clean main context — the subagents
burn their own — not a lower price. Run twelve items in parallel and you pay for
twelve items.

## Never start one on your own initiative

Two reasons, and both are about the developer, not the model:

1. **It costs real money in one go**, and the person paying should choose to.
2. **It enlarges the diff.** More work in parallel means more to review, and
   review capacity is the actual bottleneck. A fan-out without a working gate
   makes supervision *worse*, not better.

So: fan out only when asked, and refuse when `gate` in `.claude/efficiency.md`
is empty. Say why rather than just declining.

## The test that decides whether the work qualifies

**Are the items genuinely independent?** If item 3 changes a file item 7 also
touches, they are not, and running them in parallel produces conflicts a
sequential run would never have had.

**Does each item have its own objective test?** A fan-out without a per-item
oracle produces a pile of plausible work nobody can verify. That is not
throughput, it is debt with a timestamp.

If either answer is no, say so and propose the sequential run instead. That is a
better outcome than a fast pile of unverifiable diffs.

## How to run it

**In batches, not all at once.** Ten at a time is a reasonable default. All
thirty simultaneously means a failure pattern common to all of them is
discovered thirty times instead of once, and paid for thirty times.

**Route each item by the policy**, exactly as a normal run would — cheap model
for specified work, expensive review where the tier calls for it. A fan-out is
not a licence to skip routing.

**One item, one subagent, one scope.** Give each a precise statement, its
acceptance criteria, and the files it may touch. An item that discovers it needs
a decision must hand back rather than improvise: with ten running at once, ten
improvised decisions are unreviewable.

**Run the gate after each batch**, not only at the end. A batch that broke the
gate should be found before the next ten are launched.

## Reporting

Per item: done, failed, or handed back with the decision it needs. Then the gate
result for the batch, and the measured spend.

Say plainly which items you could **not** verify. An unverified item in a
fan-out report is the thing most likely to be read as done — and the reason
review capacity, not model capacity, is what limits how much of this is worth
doing.
