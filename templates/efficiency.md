---
# The routing policy. Committed, because it is meant to travel with the repo —
# that is the whole point: routing stops being a choice you re-make every
# session and becomes a property of the project.
#
# Written by /efficiency:init, and edited by hand thereafter. The run STATE is a
# different file (.efficiency/run.md) and is gitignored.

# ── The oracle ───────────────────────────────────────────────────────────────
# The command a developer would run before committing. It is what makes autonomy
# safe rather than reckless, so /efficiency:run refuses to start without it.
# Prefer one scoped to the diff: it runs at the end of every turn that changed
# source. Its output on failure goes back to Claude, so prefer a gate that names
# files and lines.
gate: ""

# ── The ceilings ─────────────────────────────────────────────────────────────
budget:
  # Automatic continuations for the whole run.
  continuations: 40

  # Repair attempts on the same red gate before the run stops and asks.
  gate_retries: 2

  # Spend ceiling for a SINGLE task — the guard that catches a task which keeps
  # looking productive and never closes. Measured from the session transcript,
  # subagents included, in US dollars at API list prices. That figure is a proxy
  # for plan allowance, not a bill: it is the only common unit a hook can
  # compute, and it moves in proportion to what the allowance is charged.
  #
  # basket: what a period of your usage is worth in the same unit. Leave 0 until
  # you have measured one: /efficiency:run-report reports real spend, so set
  # this from a measurement rather than a guess.
  basket_usd: 0

  # The ceiling as a share of the basket, once the basket is known.
  task_pct: 20

  # The ceiling for a STANDARD task, in dollars, used while basket_usd is 0.
  # Other tiers scale it by tier_multiplier below. Shipped switched ON, so a run
  # is protected from the first day rather than from the day you get around to
  # calibrating.
  task_usd: 5.00

  # The ceiling exists to stop a task that loops while looking productive, not
  # to save money: the saving comes from routing. So it scales with the tier.
  # One flat figure either strangles critical work, which reads more and is
  # reviewed by opus, or lets a mechanical task loop for a long time before
  # anything notices. Each task's ceiling is the base above times its tier's
  # multiplier. The hook caps every multiplier at 10, a policy without this key
  # gets these defaults, and the multipliers are fixed when a run starts.
  tier_multiplier: { mechanical: 0.5, standard: 1, sensitive: 2, critical: 4 }

  # The ceilings above are checkpoints, not stops. When a task reaches its spend
  # ceiling, the run its continuation budget, a task its fifth continuation
  # without closing — or half a window is spent with nothing closed and nothing
  # changed on disk — this model reads the diff and the tool calls and decides
  # whether the work is converging. Converging buys one more tranche of the same
  # size, with no limit on how many; anything else stops the run with its reason.
  # Two checkpoints in a row with no progress between them stop it without
  # asking. A verdict costs a cent or less and is charged to the run.
  # `off` restores the hard stops. Fixed when a run starts.
  supervisor: sonnet

# ── Criticality ──────────────────────────────────────────────────────────────
# Declared path patterns decide the tier. Where they are silent, Claude
# classifies, says so in one line, and proposes the pattern that would have
# decided it — so this map gets built by using it, not at a desk.
#
# Everything not matched here is "standard". List only the exceptions.
tiers:
  critical: []
    # things where being wrong is expensive and slow to discover, e.g.
    #   - "**/security/**"
    #   - "**/migrations/**"
    #   - "config/prod/**"
  sensitive: []
    # things with a contract someone else depends on, e.g.
    #   - "**/api/**"
    #   - "**/*Repository*"

# ── Routing ──────────────────────────────────────────────────────────────────
# Match the model to the task, and put the expensive model where judgement is
# needed rather than where typing is.
routing:
  mechanical: { implement: haiku,  review: none, ask: never }
  standard:   { implement: sonnet, review: none, ask: never }
  sensitive:  { implement: sonnet, review: opus, ask: on_review_blocked }
  critical:   { design: opus, implement: sonnet, review: opus, ask: before_done }

# ── Parallelism ──────────────────────────────────────────────────────────────
# Routing picks the model; this picks how many run at once. Fast mode buys the
# developer's time with money: every task of a wave gets its own subagent, so
# you wait for the longest task instead of the sum — and pay each subagent's
# context on top. Economy keeps the work in one session.
parallel:
  # auto: decided per piece of work, by its length and its widest wave.
  # economy / fast: the project has already decided, so do not re-judge it.
  # A verbal "go fast" or "save money" overrides this either way.
  default_mode: auto

  # Fast mode needs both: the widest wave holds at least min_wave tasks, AND the
  # work would take this session at least min_serial_minutes, as estimated
  # before starting. Estimate the waiting, not the typing: fully specified items
  # are written in one batch in seconds, however many there are, while items
  # that need turns (unfamiliar code, slow tests, failures to iterate on) cost
  # real minutes each and repay a subagent from the second one. Duration
  # separates the two cases far more than width does. The measurements behind
  # both values are in the plugin repo's docs/verified-platform-behaviour.md,
  # section 20.
  min_wave: 2
  min_serial_minutes: 2

  # The most subagents in one wave; a wider wave is split. It bounds how much a
  # single wave can spend at once. Set it to 1 to opt out of parallelism
  # entirely: every wave is then one task, and fast mode cannot happen.
  max_agents: 10

# ── Permission prompts ───────────────────────────────────────────────────────
# The plugin's PreToolUse hook answers "allow" for Bash commands that cannot
# destroy anything — git status/diff/log, add, commit, push without force,
# fetch, switch, branch and tag creation, read-only shell commands, and chains
# of them — so a session stops pausing to ask. Force-push, reset, clean, rm,
# substitution and redirection to a file still ask. Your own deny rules in
# .claude/settings.json still win. The list lives in the plugin, so editing this
# file can only switch it off, never widen it.
auto_allow: on

# ── The only legitimate interruptions ────────────────────────────────────────
# Anything not on this list is a confirmation, not a decision, and the charter
# forbids asking for it.
stop_for:
  - irreversible_or_outward_facing
  - critical_tier_gate
  - undeclared_decision_that_changes_the_deliverable
  - gate_red_after_retries
  - missing_secret_or_access
---

# Declared defaults

The answers to questions you would otherwise be asked mid-run. This is the
largest and least obvious source of interruptions: most questions are not
decisions, they are defaults nobody ever wrote down.

A default earns its place here only if it is **actionable without context**.
"Prefer extending an existing type over adding a parallel one" is a default.
"Write clean code" is not.

`/efficiency:init` proposes a starting set by reading what this repo already
does, and every run proposes another whenever it has to decide something this
list does not cover.

<!-- - example: new behaviour ships with a test at the level of the code it touches -->
