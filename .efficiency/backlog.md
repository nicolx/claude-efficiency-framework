# Backlog

Things found while doing something else. **Each entry is work for a fresh session**, not for the one
that found it — that is the whole point of writing it here instead of acting on it.

Committed, so it is shared and survives the session that noticed.

## Format

One line per entry. Open items use `- [ ]`, closed ones `- [x]`.

```text
- [ ] 2026-10-10 · <what, in one line> · found while: <what you were doing at the time>
```

The *found while* half matters more than it looks: a fresh session reading this has none of the
context that made the thing obvious, and "found while" is the cheapest way to give it back.

## Open

- [ ] 2026-10-10 · /efficiency:init cannot write the permission fence: skills/init/SKILL.md tells it to merge allow/deny rules into .claude/settings.json, and Claude Code refuses writes there. It degrades gracefully by printing the snippet for the developer to paste, but the fence is never installed automatically — so cause (a) of the six interruption causes, permission prompts, is the one the framework does not actually remove · found while: running init from scratch in a fresh adopter project for the first time
- [ ] 2026-10-10 · The session that builds a release can never run it: hooks load at session start, so every version that adds a rule is written by a session that cannot load it. Decide whether that is acceptable or whether releases need a verification session of their own · found while: discovering I had written the verdict rule three hours earlier and opened every reply since with prose
- [ ] 2026-10-10 · Model routing has never been observed working. skills/run/SKILL.md delegates to efficiency:implementer-fast and efficiency:reviewer by tier, and no test has ever watched a run actually route to either — it is the framework's headline contribution and the least exercised part · found while: listing what the four runs so far did and did not prove
- [ ] 2026-10-10 · efficiency:fanout has never been run, by anyone, once. No test, no real use, and its subagent batching is the only skill with no evidence behind it at all · found while: the same inventory
- [ ] 2026-10-10 · /efficiency:run-report has never been run on a real run. The one run that reached DONE (four scripts, armed from a plain instruction) was never reported on, so the spend-by-model output and the basket calibration advice are untested in anger · found while: the same inventory
- [ ] 2026-10-10 · Only efficiency:autopilot has been shown to auto-invoke from natural language. backlog, run-report and fanout have never been observed triggering from a plain request, and a description too vague to match would fail silently · found while: testing that "procedi fino a completare" armed the autopilot, and realising it was the only skill I had checked
- [ ] 2026-10-10 · Stop-hook coexistence was measured in September against 0.1.0, before the private-state rewrite. Whether a project's own Stop hook still coexists with the autopilot now that counters live in .efficiency/autopilot.json has not been re-tested · found while: re-reading docs/verified-platform-behaviour.md section 2 after moving the state out of the run file
- [ ] 2026-10-10 · The platform's 8-block cap and the framework's own ceilings have never been tested together. continuations_max ships at 40 and STALL_STOP is 5, but a genuinely stalled run hits the platform's cap at 8 blocks without progress — so which guard actually fires first, and whether its reason is the readable one, is unknown · found while: writing the five-guards section of the README
- [ ] 2026-10-10 · CI never runs the probes in scripts/probes/. They cost money and call the API, so CI only shellchecks them — which means a platform change is caught only when a human remembers to re-run them. Last time that took a month, and section 7 had expired · found while: re-measuring against 2.1.289 and finding a documented behaviour had quietly stopped being true
- [ ] 2026-10-10 · scripts/qa.sh has no check that every skill's description names its trigger phrases · found while: adding the autopilot skill and noticing nothing would catch a description too vague to be auto-invoked
- [ ] 2026-10-10 · the spend ceiling is checked only at turn boundaries, so one very long turn can overshoot · found while: writing the README's limits section
- [ ] 2026-10-10 · Section 9 of docs/verified-platform-behaviour.md — Claude Code refuses writes into .claude/ — did not reproduce on 2.1.296: a session wrote .claude/settings.json through Bash repeatedly, unrefused. It is an anomaly, not a correction, because it was one session in one permission mode and the claim decides the whole file layout. Write the probe that is missing: Write, Edit and Bash, across permission modes · found while: building the status line, which had to edit settings.json to install itself

## Closed

<!-- move entries here when done, with the date -->
