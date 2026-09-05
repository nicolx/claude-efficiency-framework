---
name: init
description: Set up the efficiency framework in this project — detect the stack, propose the quality gate, the criticality patterns and the declared defaults, then write .claude/efficiency.md and the permission fence. Run once per project. Use when the user asks to set up, configure, or adopt the efficiency framework.
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
- five to ten **declared defaults**, each actionable without context
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

**`.claude/efficiency.md`** — from `${CLAUDE_PLUGIN_ROOT}/templates/efficiency.md`,
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

**`.gitignore`** — add `.claude/efficiency.local.md` and
`.claude/.efficiency-autopilot.json` if they are not already covered. The policy
travels with the repo; the run state and the hook's own counters do not.

## 4. Say what happens next

Three things, briefly:

- **Hooks load at session start**, so the autopilot is inert until Claude Code
  is restarted. Say this explicitly — a run that silently does not continue looks
  like a broken framework rather than an unrestarted session.
- Verify the plumbing with
  `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/autopilot-stop.py" --selftest`.
- The next step is `/efficiency:plan-run`, and that is where their attention gets
  spent: approving a list once, instead of confirming it repeatedly.
