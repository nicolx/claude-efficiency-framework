# Changelog

All notable changes to this project are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

A consuming project pins this plugin by `ref` or `sha`, so a change to anything under `hooks/`,
`skills/`, `agents/`, `templates/`, or to `AUTONOMY-CHARTER.md`, is a change to their sessions.

- **Major** — a consumer must edit their own `.claude/efficiency.md` or settings to keep working
- **Minor** — a new skill, a new agent, a new policy key with a safe default
- **Patch** — corrections, clarifications, price-table refreshes

## [0.1.0] — 2026-09-05

First release. Deliberately not 1.0.0: the mechanism is measured and self-tested, but three things
in the plan's verification list have not happened yet, and calling it 1.0.0 would claim they had.

### Added

- **The autopilot `Stop` hook** (`hooks/autopilot-stop.py`) — refuses to end a turn while an
  approved run has open tasks and the gate is green. Inert unless `.claude/efficiency.local.md`
  exists, which is Claude Code's documented conditional-activation pattern and removes the need for
  a switch anyone could forget.
- **Four nested guards**: a per-task spend ceiling measured from the session transcript, a gate
  retry budget, a run-wide continuation budget, and the platform's own anti-stall cap. An
  unmeasurable ceiling fails closed and stops the run.
- **The spend meter** (`hooks/lib/spend.py`) — weighted token cost per model from the transcript,
  including subagent transcripts, with a dated price table (`hooks/lib/model-costs.json`).
- **The autonomy charter** (`AUTONOMY-CHARTER.md`), carried into adopting projects by a
  `SessionStart` hook and versioned with the plugin rather than copied into each project.
- **Three agents with pinned models**: `implementer-fast` (haiku), `architect` (opus, read-only),
  `reviewer` (opus, read-only).
- **Five skills**: `init`, `plan-run`, `run`, `fanout`, `run-report`.
- **The policy scaffolding** a project owns: `templates/efficiency.md` and
  `templates/settings.permissions.json`.
- **`docs/verified-platform-behaviour.md`** — every platform fact the design rests on, measured with
  its method and date, re-runnable via `scripts/probes/stop-cap.sh`.
- **`scripts/qa.sh`** — this repo's gate, which reports what it could not run rather than passing
  silently.

### Measured, not assumed

- The `Stop` block cap counts consecutive blocks **without progress**; any tool call resets it, a
  read-only one included. The cap is an anti-stall guard, not a ceiling on autonomy.
- `transcript_path` is present in the `Stop` payload although the hook reference does not list it
  for that event.
- Subagent turns are **not** in the main transcript despite `isSidechain` existing in its schema.
  They were 17% of spend on the session that built this, and the expensive half by design.
- A freshly created directory is untrusted, and its project settings are ignored in silence — the
  failure most easily misread as a platform change.

### Not yet verified

- Installing as a plugin from the published repo, and per-project adoption through
  `extraKnownMarketplaces` + `enabledPlugins`.
- Coexistence with a second `Stop` hook registered by a consuming project, and what that does to
  the shared `stop_hook_active` flag and the eight available blocks.
- The measurement that actually matters: a real run of ten tasks with every interruption counted and
  classified against the six causes.
