---
# The routing policy. Committed, because it is meant to travel with the repo —
# that is the whole point: routing stops being a choice you re-make every
# session and becomes a property of the project.
#
# Written by /efficiency:init, and edited by hand thereafter. The run STATE is a
# different file (.claude/efficiency.local.md) and is gitignored.

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

  # The fallback ceiling in dollars, used while basket_usd is 0. Shipped switched
  # ON, so a run is protected from the first day rather than from the day you get
  # around to calibrating.
  task_usd: 5.00

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
