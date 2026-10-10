---
name: backlog
description: File something for a later session, or review what is already filed. Use it when you notice work that is not the task at hand — "that should be refactored", "there's a bug over there", "this could be faster" — and when the developer asks what is outstanding, what was deferred, or wants to pick an item up and start on it.
---

# backlog

`.efficiency/backlog.md` holds work found while doing something else. Every entry
is for a **fresh session**, which is the entire reason it is written down instead
of acted on.

## Filing something

One line, appended under `## Open`:

```text
- [ ] 2026-10-10 · <what, in one line> · found while: <what you were doing>
```

Then say in one line that you filed it, and go back to the task.

**Write it so a stranger can act on it**, because that is what a fresh session is.
Name the file or the symbol. "Refactor the parser" is not an entry; "`parse_line`
in `hooks/lib/spend.py` silently drops a malformed row — decide whether that
should be loud" is.

The **found while** clause is not decoration. The reader has none of the context
that made the thing obvious to you, and that half-sentence is the cheapest way to
give it back.

## What belongs here, and what does not

| | |
|---|---|
| It **blocks** the current task | **Not** the backlog. It is part of the task; do it. |
| You **broke** something that worked | **Not** the backlog. You caused it; fix it. |
| Anything else you noticed | The backlog. |

The third row is the one that feels wrong to obey, and it is the one that matters:
a clear, real improvement spotted mid-task is exactly the thing that quietly
doubles a diff nobody agreed to.

## Reviewing

When the developer asks what is outstanding, read the file and give them the open
entries, oldest first — age is information, and something filed three months ago
and never picked up is either not worth doing or genuinely blocked.

Group them if there are many, by the file or area they touch. Do not editorialise
about which matter: the point of the backlog is that the decision belongs to the
person with a clear head, not to the session that happened to notice.

## Picking one up

When they choose one, that is a **new task** — treat it as one. Read the entry,
re-establish the context it names (it may be stale: the code moves and an entry
does not), and confirm it is still real before working on it.

Close it by moving the line to `## Closed`, flipping `- [ ]` to `- [x]`, and
appending the date. Keep closed entries: they are the record of what was deferred
and then actually done, which is the only evidence that filing things here is not
the same as discarding them.

## Never start on an entry uninvited

Including at the start of a session, when the backlog is shown to you. Those items
were set aside on purpose. Picking one up because it is in front of you is exactly
the scope creep the deferral existed to prevent — the same mistake, one session
later.
