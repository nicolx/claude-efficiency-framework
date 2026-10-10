---
name: init
description: Set up the efficiency framework in this project — detect the stack, propose the quality gate, the criticality patterns and the declared defaults, then write .efficiency/policy.md and the permission fence. Run once per project. Use when the user asks to set up, configure, or adopt the efficiency framework.
---

# init

Configure this project so routing and autonomy become properties of the repo
rather than choices someone re-makes every session.

You are writing two things into the project: a policy it will own and edit, and
permission rules it will keep. Both are the developer's files afterwards. Propose,
show, then write — never write first and report second.

## 0. Is this a migration?

If `.claude/efficiency.md` exists and `.efficiency/policy.md` does not, this
project was set up before 0.4.0 and **the framework is currently inert** — the
files moved because Claude Code refuses writes into `.claude/`, which had meant
the model could never tick a task closed or arm the autopilot at all.

Migrate before anything else, and say what you moved:

| From | To |
|---|---|
| `.claude/efficiency.md` | `.efficiency/policy.md` |
| `.claude/efficiency.local.md` | `.efficiency/run.md` |
| `.claude/.efficiency-autopilot.json` | `.efficiency/autopilot.json` |

Update `.gitignore` for the new paths, remove the old entries, then continue
below — the policy's content is still good, only its home changed.

## 1. Read the repo before asking anything

The point is to arrive with proposals, not a questionnaire. Find out for
yourself:

- **The gate.** Look for `package.json` scripts, `composer.json` scripts, a
  `Makefile`, `pyproject.toml`, `Justfile`, `bin/` or `scripts/` entry points,
  and the CI workflow — CI is the most honest statement of what this project
  considers "green", because it is what actually blocks a merge. Prefer a single
  command that already exists over a chain you invent.
- **What the code treats as dangerous.** Directories named for security, auth,
  permissions, payments, billing, migrations; production configuration; anything
  the CI treats specially. These become the `critical` patterns.
- **What has a contract.** Public API surfaces, repositories, published
  interfaces, serialisation formats. These become `sensitive`.
- **Defaults the code already reveals.** Read a few recent, non-trivial commits
  and a couple of representative modules. Where the codebase consistently does
  something one way, that consistency is a default worth declaring — it is a
  question you will otherwise be asked mid-run.
- **The irreversible levers.** Deploy and rollback scripts, anything that writes
  to production, destructive data commands. These become `deny` candidates.

## 2. Propose, in one pass

Show the developer, compactly:

- the gate command you propose, and why that one
- the `critical` and `sensitive` patterns, each with the reason it qualifies
- five to ten **declared defaults**, each actionable without context. These are
  the single biggest lever in the whole framework — most questions a developer
  gets asked are not decisions, they are defaults nobody wrote down — and they
  are also what a developer would never sit down and write unprompted. Propose
  them from what the code already does, concretely enough to act on
- the `deny` rules you found, named as the commands they block
- the spend ceiling: `task_usd` stays at its shipped value until a run has been
  measured — say so rather than inventing a number

Ask for corrections **once**, in a single exchange. If the developer confirms or
says nothing needs changing, proceed. Do not walk them through the file field by
field: that is the interruption this framework exists to remove, and doing it
during setup sets the wrong expectation for everything after.

**A gate you cannot find is the one thing worth blocking on.** Without it
`/efficiency:run` refuses to start, by design. If the project genuinely has no
gate command, say plainly that autonomy is unavailable until it has one, and
offer to help write the smallest real one — a type check, or the test command
that already exists.

## 3. Write

**`.efficiency/policy.md`** — write it from the skeleton below, with your
proposals filled in. If it already exists, **do not overwrite it**: show a diff of
what you would change and let the developer choose. This file is theirs.

The skeleton is written out here rather than copied from the plugin's own
`templates/` on purpose. **A session cannot read anything outside the project it
is working in**, and is never told where the plugin lives — so an instruction to
copy a template from there is one nobody could follow. Measured, on the first
adopter who tried.

````markdown
---
gate: "<the command a developer runs before committing>"

budget:
  continuations: 40          # automatic restarts for the whole run
  gate_retries: 2            # repair attempts on the same red gate
  basket_usd: 0              # a period's worth of usage; 0 until measured
  task_pct: 20               # per-task ceiling, as a share of the basket
  task_usd: 5.00             # the fallback ceiling while basket_usd is 0

tiers:                       # only the exceptions; everything else is "standard"
  critical: []               # being wrong here is expensive and slow to discover
  sensitive: []              # has a contract someone else depends on

routing:
  mechanical: { implement: haiku,  review: none, ask: never }
  standard:   { implement: sonnet, review: none, ask: never }
  sensitive:  { implement: sonnet, review: opus, ask: on_review_blocked }
  critical:   { design: opus, implement: sonnet, review: opus, ask: before_done }

stop_for:                    # the ONLY legitimate interruptions
  - irreversible_or_outward_facing
  - critical_tier_gate
  - undeclared_decision_that_changes_the_deliverable
  - gate_red_after_retries
  - missing_secret_or_access
---

# Declared defaults

The answers to questions you would otherwise be asked mid-run. A default earns
its place only if it is **actionable without context**.

- <one per line, read off what this repo already does>
````

**`.claude/settings.json`** — merge in the permission rules. This is the only
invasive write the framework makes, so treat it that way:

- read the existing file first; never clobber it
- add only; never remove or rewrite an existing rule
- report every rule you added, one per line, with the reason
- if the file has rules that conflict with what you would add, say so and let
  the developer resolve it

**`.efficiency/tools.md`** — nothing to do. The `SessionStart` hook writes it
itself, and refreshes it when it ages past a week. It lists the operational tools
this machine has, and every session is told to use them instead of writing a
script. **Gitignored**: it describes a machine, not a project.

It will be there from the next session on. Mention that, and if something
obviously useful for this project's stack is missing — a document pipeline
without `pandoc`, media work without `ffmpeg` — say so once and offer to install
it. Do not install anything unasked.

**`.efficiency/backlog.md`** — write this, if it does not already exist. It is
**committed**: a backlog is shared knowledge that outlives the session that filled
it.

````markdown
# Backlog

Things found while doing something else. **Each entry is work for a fresh
session**, not for the one that found it.

## Open

<!-- - [ ] YYYY-MM-DD · what, in one line · found while: what you were doing -->

## Closed
````

**`.gitignore`** — add `.efficiency/run.md`, `.efficiency/autopilot.json` and
`.efficiency/tools.md`.
The policy travels with the repo; the run state and the hook's own counters do
not.

**Not `.claude/`, and not `CLAUDE.md`.** Everything this framework writes lives
in `.efficiency/` at the project root, because **Claude Code refuses writes into
`.claude/`** — measured, across `Write`, `Edit` and `Bash`, and not liftable by a
permission rule. Files the model has to update cannot live there. And the policy
is injected into every session by the `SessionStart` hook, so there is nothing to
`@`-include and no copy to drift.

## 4. Say what happens next

Four things, briefly:

- **From the next session on, `.efficiency/policy.md` is loaded automatically** —
  the tiers, the routing, the `stop_for` list and the declared defaults all reach
  every session alongside the autonomy charter. Nothing to `@`-include, nothing
  in their `CLAUDE.md` to keep in step. Editing the policy changes the next
  session; it costs roughly 2,000 tokens per session, so keep it lean.
- **Hooks load at session start**, so none of this is live until Claude Code is
  restarted. Say it explicitly — a run that silently fails to continue looks like
  a broken framework rather than an unrestarted session.
- **Offer the two verification commands for the developer to run**, using the
  plugin path given to you at session start — you cannot run them yourself, since
  nothing outside this project is reachable from a session:
  `check-install.sh .` for the install, and `autopilot-stop.py --selftest` for the
  autopilot's plumbing. The second is also what to run after any upgrade, because
  the way this framework breaks is silently.
- **Work found along the way goes to `.efficiency/backlog.md`**, not into the
  session that found it, and open items are surfaced at the start of every
  session afterwards. Say this: it is the habit that keeps a session reviewable.
- **They do not have to learn the commands.** Telling Claude to carry work
  through to the end — in any words, in any language — arms the same machinery
  that `/efficiency:plan-run` does. The commands are there for work worth
  planning deliberately.
