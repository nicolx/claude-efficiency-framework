---
gate: "bash scripts/qa.sh"

budget:
  continuations: 40
  gate_retries: 2
  basket_usd: 0
  task_pct: 20
  task_usd: 5.00

tiers:
  critical:
    # The autopilot decides when a run keeps going and when it stops. A defect
    # here spends money unattended or wedges a session, and neither shows up
    # until it has already happened.
    - "hooks/autopilot-stop.py"
    - "hooks/lib/spend.py"
    - "hooks/hooks.json"
  sensitive:
    # Contracts other projects depend on: prices the ceiling is computed from,
    # scaffolding a consumer owns after first write, and text injected into
    # every adopting session.
    - "hooks/lib/model-costs.json"
    - "templates/**"
    - "AUTONOMY-CHARTER.md"
    - "hooks/session-start.py"

routing:
  mechanical: { implement: haiku,  review: none, ask: never }
  standard:   { implement: sonnet, review: none, ask: never }
  sensitive:  { implement: sonnet, review: opus, ask: on_review_blocked }
  critical:   { design: opus, implement: sonnet, review: opus, ask: before_done }

stop_for:
  - irreversible_or_outward_facing
  - critical_tier_gate
  - undeclared_decision_that_changes_the_deliverable
  - gate_red_after_retries
  - missing_secret_or_access
---

# Declared defaults

Read from what this repo already does, so the same question does not get asked
twice.

- **Measure the platform, never cite it.** Before relying on a Claude Code
  behaviour, write a probe under `scripts/probes/`, run it, and record the
  result in `docs/verified-platform-behaviour.md` with its date and method.
- **A new guard needs a case that shows it firing.** Add it to
  `hooks/selftest.py`, which invokes the hook as a real subprocess against a
  throwaway project. A guard without such a case is decorative.
- **A check that cannot fail is not a check.** When adding one to
  `scripts/qa.sh`, prove it red once before leaving it green.
- **The hook is never fatal for its own defects** — report and exit 0. The sole
  exception is a blind guard, which fails closed and stops the run.
- **Nothing a model can edit may extend a run.** Counters belong to the hook.
- **Shipped documents are in English**, whatever language the conversation uses.
- **Python only, standard library only.** No package to install.
- **Version and changelog move in the same commit** as any change under
  `hooks/`, `skills/`, `agents/`, `templates/`, or to `AUTONOMY-CHARTER.md`.
- **Prefer extending an existing file over adding a parallel one**, and match the
  comment density and idiom already in it.
