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

**`.efficiency/policy.md`** — from `${CLAUDE_PLUGIN_ROOT}/templates/efficiency.md`,
with your proposals filled in. If it already exists, **do not overwrite it**:
show a diff of what you would change and let the developer choose. This file is
theirs.

**`.claude/settings.json`** — merge in the permission rules. This is the only
invasive write the framework makes, so treat it that way:

- read the existing file first; never clobber it
- add only; never remove or rewrite an existing rule
- report every rule you added, one per line, with the reason
- if the file has rules that conflict with what you would add, say so and let
  the developer resolve it

**`.efficiency/tools.md`** — run
`bash "${CLAUDE_PLUGIN_ROOT}/scripts/detect-tools.sh" .` to write it. It lists the
operational tools this machine already has, and every session afterwards is told
to use them instead of writing a script. **Gitignored**: it describes a machine,
not a project, and a shared list describing someone else's laptop is worse than
no list.

Mention what it found. If something obviously useful for this project's stack is
missing — a document pipeline without `pandoc`, media work without `ffmpeg` —
say so once and offer to install it. Do not install anything unasked.

**`.efficiency/backlog.md`** — from
`${CLAUDE_PLUGIN_ROOT}/templates/backlog.md`, if it does not already exist. It is
**committed**: a backlog is shared knowledge, and it outlives the session that
filled it.

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
- Verify the plumbing with
  `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/autopilot-stop.py" --selftest`.
- **Work found along the way goes to `.efficiency/backlog.md`**, not into the
  session that found it, and open items are surfaced at the start of every
  session afterwards. Say this: it is the habit that keeps a session reviewable.
- **They do not have to learn the commands.** Telling Claude to carry work
  through to the end — in any words, in any language — arms the same machinery
  that `/efficiency:plan-run` does. The commands are there for work worth
  planning deliberately.
