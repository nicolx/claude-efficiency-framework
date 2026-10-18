# Changelog

All notable changes to this project are documented here, following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic versioning.

A consuming project pins this plugin by `ref` or `sha`, so a change to anything under `hooks/`,
`skills/`, `agents/`, `templates/`, or to `AUTONOMY-CHARTER.md`, is a change to their sessions.

- **Major** — a consumer must edit their own `.claude/efficiency.md` or settings to keep working
- **Minor** — a new skill, a new agent, a new policy key with a safe default
- **Patch** — corrections, clarifications, price-table refreshes

## [Unreleased]

Work that is committed and not yet inside any tag. `scripts/release.sh` refuses to cut a release
while this section has content, so it can never again describe work consumers already have.

### Fixed — `[0.12.0]` now says it was never released on its own

Repo-internal: `CHANGELOG.md` only.

The changelog has an entry for 0.12.0, but `VERSION` never held that number and git has no tag for
it, so the changelog and the tag list looked inconsistent. A note under the entry now explains this.
Creating a tag after the fact would have made things worse: there is no commit where `VERSION` reads
0.12.0, so `check-release-tag.py` would reject that tag as misplaced.

### Fixed — `[Unreleased]` described work consumers already had

Repo-internal: `scripts/`, `CHANGELOG.md` and `CLAUDE.md` only.

The section had no definition, only a habit. Rule 6 asks for a bump when a **shipped** artefact
changes, so repo-internal work — the gate, the probes, the docs — correctly does not bump. It was
filed under `[Unreleased]` and nothing ever moved it out, because nothing was responsible for moving
it. By 0.19.0 three of that section's four entries were already inside the tag `origin` was serving:
the changelog called pending what consumers had had for a release.

The three are now filed under `[0.19.0]`, under a heading that says why they are there. That is the
tidying, and on its own it would last about a week — the next repo-internal commit followed by a
release puts it straight back, unnoticed. The same shape as the six releases that were announced and
never pushed: a step that exists only in someone's head is a step that is skipped.

So the section gets one checkable meaning — **committed, and not yet inside any tag** — and
`scripts/lib/check-changelog.py` enforces it from the one place it cannot be skipped:
`scripts/release.sh` refuses to cut a tag while `[Unreleased]` has entries. Cutting a release is now
what forces them to be filed under the version they ship in.

Deliberately not a gate check. Between releases a populated `[Unreleased]` is exactly right, and a
gate red on it would be red for most of this repo's life — the kind of red people learn to skip past.
What `scripts/qa.sh` runs is the selftest, which is the part that rots: a guard nobody exercises
until release day is a guard discovered broken on release day.

Five selftest cases, three mutation-tested. The case that earned its place is the one asserting
silence: a check that counted any text under the heading would refuse every release from the moment
the section documented itself — a guard whose first act is to block the thing it was built to protect.

### Added — the coexistence measurement had no probe, for five weeks

Repo-internal: `scripts/probes/` and `docs/` only, so no consumer session behaves differently.

Two claims in `docs/verified-platform-behaviour.md` rested on a single run from 2026-09-05
(`dfa61e0`) — that a project's own `Stop` hook and the autopilot are each invoked on every turn, and
that the platform's cap counts blocked **turns** rather than blocks, so two hooks blocking together
consume one of the eight occasions instead of two. That commit changed `CHANGELOG.md` and the
document. It committed no probe. Rule 1 says a number nobody can re-derive becomes folklore at the
next release; this one had five weeks and a state rewrite to do it in.

The rewrite is why it mattered. The counters moved out of the run file and into
`.efficiency/autopilot.json`, and a neighbouring hook firing on the same event could plausibly have
double-counted the budget. Worse, § 3's margin — guard 4 stops a stalled run at block 6, two inside
the platform's 8 — was measured with **one** hook registered. If the cap had started counting blocks,
an adopter with their own `Stop` hook would lose that margin and the platform would stop their run
first, silently.

`scripts/probes/stop-coexistence.sh` is the missing probe, in two modes: `cap` reproduces the
September setup with two stand-in hooks, and `autopilot` drives the **shipped** hook against an
unfinishable run with a project quality-gate hook blocking beside it on every turn.

Nothing had changed, which is the honest and the expected outcome — the deliverable is that it can
now be re-derived in two minutes and a cent. On 2.1.296: 9 invocations each in `cap` mode, matching
September; 10 / 10 in lockstep in `autopilot` mode; guard 4 still firing at block 6 with a neighbour
present; and `continuations_used` advancing 1, 2, 3, 4, 5 — once per turn, not twice.

Two things the September run did not look at, now recorded in § 2:

- **Both block reasons reach the model and both are acted on.** The neighbour's reason asked for one
  observable act and got it on 9 of 10 turns, while the run went on being worked and guard 4 counted
  to exactly 5. A project's hook does not displace the instruction the autopilot depends on.
- **Stopping a run does not end a session.** After guard 4 stopped the run the autopilot stood down
  — `status: BLOCKED`, counter frozen — and the session carried on four more turns because the
  neighbour kept blocking, ending on `--max-turns` rather than on the platform's cap, since the
  neighbour's instruction was a tool call and any tool call resets that counter. This is the
  neighbour's loop and not the autopilot's: a hook cannot un-block another hook, and trying would be
  the wedging rule 2 forbids. But `status: BLOCKED` in the run file does not mean the session has
  stopped, and that was nowhere written down.

Also corrected: § 3's two-hook row sat under a 2026-10-10 provenance line that covered the stall and
read modes only, so a September figure was reading as a fresh one. It now carries its own date, and
§ 4's blocking contract is confirmed on 2.1.296 by the one evidence that actually shows a `reason`
arrived — the model acting on it — rather than inferring it from the turn continuing.

## [0.19.0] — 2026-10-11

### Added — the spend ceiling now holds inside the turn, not only at its end

The ceiling was read exactly once per turn, as the turn ended, because `Stop` was the only event
this framework knew it could refuse from. A turn has no length limit. So the one guard that stands
between an unattended run and real money was absent for precisely the interval in which it can be
exceeded, and the README called that a limit — which flattered it: a ceiling checked only after the
spending is a record, not a ceiling.

`hooks/autopilot-pretool.py` is the other half. It runs on `PreToolUse` and refuses tool calls once
the ceiling is crossed, so the spending stops where it happens. It delivers no verdict: the `Stop`
hook still stops the run at the boundary, with the reason a human reads, exactly as before. One
guard, two halves — the refusal and the verdict.

Three platform facts were measured before any of it was written, because none is documented and each
one could have ended the idea (`docs/verified-platform-behaviour.md` § 17, three new probes):

- **the transcript is written as the turn runs**, so spend is measurable mid-turn with the meter
  that already exists. A reading trails by one assistant message — the one that issued the call
  being refused has not been written yet — so the ceiling is always a little late and never early.
- **a `PreToolUse` denial is honoured**, and the turn then ends by itself. Measured: two permitted
  calls ran, the third did not, and the model stopped after one further attempt and reported what it
  had finished, quoting the ceiling back.
- **a subagent's own tool calls reach the parent's hook**, carrying the parent's `transcript_path`.
  The expensive half of a routed run is therefore covered with no special handling, and a subagent's
  call can be refused rather than only the delegation that launched it.

Two deliberate design choices, both of which read as violations until the reason is stated:

- **It fails open, where the `Stop` hook fails closed.** Rule 2 says an unmeasured ceiling is not a
  ceiling, and it also says a hook must not stand between a developer and their work. Stopping a run
  at a boundary still ends the turn; refusing every tool call mid-turn leaves a session in which
  nothing works. So when the meter is blind here the call is permitted, and the `Stop` hook stops the
  run at the boundary as it always has. Nothing that was enforced before is enforced less.
- **It writes no counter.** It reads the ceiling the `Stop` hook captured and never writes
  `.efficiency/autopilot.json` — a `PreToolUse` hook runs concurrently with itself, and a careless
  write would clobber the counters the other hook owns. Its own throttle cache lives elsewhere, and
  the worst a corrupt one can do is cost a redundant measurement or postpone one by seconds.

It costs what starting `python3` costs on a project with no run — one `stat` and nothing more. On an
active run the measurement is linear in the size of the session, about 25 ms per megabyte, so the
last reading is reused for a few seconds rather than re-parsing a growing transcript in front of
every action. That window is the real resolution of the ceiling, and the README says so in place of
the limit it replaces.

Ten selftest cases, five mutation-tested: the refusal never firing, the ceiling being read from the
run file the model writes, a cache dated in the future being believed, the first turn of a run left
unbounded, and the guard writing to the counters it must only read.

### Repo-internal — gate and release machinery

No consumer session behaves differently for any of the three below: between them they change
`scripts/`, `docs/`, `CLAUDE.md` and `README.md`, and nothing a consumer receives. They are filed
here rather than under `[Unreleased]` because this is the tag they shipped in — `VERSION` did not
move for them, so nothing ever moved them out of `[Unreleased]`, and for one release the changelog
described as pending what `origin` was already serving.

### Fixed — the install check validated a disk no consumer has

`scripts/check-install.sh` validates the whole chain — policy, enablement,
install, hooks, status line — against the plugin **as it sits on the developer's
disk**. A consumer never sees that disk. They resolve the `ref` in
`marketplace.json` and receive the tree at that tag, and nothing compared the
two. The gate could be green on a plugin that, as published, was missing a file.

The failure that opens is the one this repo keeps meeting: silence. A shipped
file that is untracked or gitignored works perfectly in development and is
simply absent at the tag. Claude Code runs the hooks it finds; the missing one
does not error, does not warn, and leaves no trace.

`scripts/lib/check-published-tree.py` asks three questions about trees rather
than about files on disk:

- **is everything we ship committed?** Every file under the shipped roots that
  exists on disk must exist in `HEAD` — checked against `HEAD` and not only
  against the tag, so the answer arrives at the commit that introduces the
  problem rather than one release later.
- **is the published tree wired to itself?** Every `${CLAUDE_PLUGIN_ROOT}/…`
  path named in that tree's own `hooks/hooks.json` must exist *in that tree*.
- **does it know its own version?** The `plugin.json` inside the tag must say
  what the tag says.

`--remote` adds the fourth, which `scripts/release.sh` now runs after pushing:
the tag object `origin` serves must be the one that was validated. A force-pushed
tag is the one way a ref can resolve for a consumer and still be something nobody
checked.

Four selftest cases, the three red ones mutation-tested. The fourth — the case
where nothing is wrong — earned its place immediately: the first draft scanned
`hooks.json` as raw text and read the backslash of an escaped `\"` as part of the
path, so all three hooks reported missing. A guard inventing three failures
rather than finding one, caught by the only case that asserts silence.

### Fixed — six releases were announced and never actually released

What this one changes is whether a release reaches anyone at all.

Rule 6 said to bump `VERSION`, `plugin.json` and `CHANGELOG.md` in the same commit, and stopped
there. So that is exactly what happened, six times: **0.14.0 through 0.18.1 were bumped, announced
and committed, and not one of them was ever tagged or pushed.** Consumers resolve a `ref`, so
`origin` went on serving 0.13.0 while the changelog described work nobody could install. No script
in the repo had ever run `git tag`; the step existed only in someone's head, and a step that lives
only in someone's head is a step that gets skipped.

The gate was green throughout, and the reason is the interesting part. Its version section compared
five things — `VERSION`, `plugin.json`, the marketplace `ref`, the marketplace `version` field, the
changelog heading — **all five of which live in the working tree**. They can agree perfectly with
each other while saying nothing about whether the release exists. That is rule 1 turned inward: a
load-bearing claim about the outside world, validated only against a copy of itself.

- **`scripts/lib/check-release-tag.py`** asks git instead of JSON. Every version `VERSION` has ever
  held must have a tag, pointing at a tree whose `VERSION` agrees, and an ancestor of `HEAD` — a tag
  on a detached experiment is worse than a missing one, because it resolves and ships the wrong
  tree. The version currently in flight is exempt and reported amber: the commit that bumps to X
  cannot already carry a tag pointing at itself. `--remote` additionally asks `origin` whether the
  tag was pushed, which is the half that actually failed here; it needs the network, so the gate
  stays offline-runnable and `release.sh` passes it.
- **`scripts/release.sh`** is now the only supported way to cut a release: refuse a dirty tree, run
  the gate, cut the annotated tag, push the branch *then* the tag, and verify against `origin` that
  the ref a consumer resolves actually resolves.
- **Rule 6 gained its second half**, and the README lost a guarantee it was not making.
- The six missing tags are **backfilled** at their release commits, dated to those commits and
  saying in the tag message that they were cut retroactively.

Four selftest cases; the missing-tag and misplaced-tag cases were mutation-tested against the
restored defect.

### Fixed — the alias-to-id mapping expired on the wrong clock

The framework routes by alias and the meter prices by id, and the gate holds the two together by
checking a mapping the probe measured. That mapping was aged on a 90-day calendar — but what
falsifies it is a **Claude Code release**, not the passage of time. An upgrade that moved what
`haiku` resolves to would have left the gate green for up to three months while every run routed
there was measured at the fallback rate.

`scripts/lib/check-priced-models.py` now reads `claude --version` — a local subprocess, no session,
no network, so it still runs anywhere the rest of the gate does — and compares it with
`resolved.claude_code_version`. A mismatch reports the mapping **unverified** rather than wrong:
exit 3, which `scripts/qa.sh` already renders as a skip. Amber and not red, because a release *can*
move an alias without certainly having done so, and a gate that goes red on every upgrade is one
people learn to skip. Where `claude` is absent — CI — the comparison is skipped and the output says
so, rather than passing silently. The calendar stays behind it, for a mapping that moves server-side
under a client that never did.

## [0.18.2] — 2026-10-10

### Fixed — the spend ceiling could be reopened by the model, one line at a time

0.18.1 took `current_task` out of the anti-stall guard and deliberately left it in the spend window,
where following the task is what the window is *for*. That was the wrong call, and the reason is the
same one: the window opened afresh whenever `current_task` changed, and `current_task` is a line of
frontmatter the model writes — on the instruction of the block reason itself.

So the ceiling the plan calls "per task" was really "per edit of one line". A model alternating
between two open tasks — the confusion already measured for guard 4 — restarted the window on every
block, and every turn before the restart then fell outside it and was measured as nothing. This is
the one guard that is deliberately fail-closed, the only one that stands between an unattended run
and real money, and it had a reset the model was being told to press.

The window now opens on the **set of open tasks changing** — the same signature as the stall guard,
computed once and used by both. A task closing is the only progress signal the model cannot send
without making progress. The cost is that the window also holds the tail of the turn in which the
previous task closed: a ceiling that charges slightly too much, which is the safe direction for a
ceiling.

### Fixed — a run file could declare a spend window that never contained anything

The same guard, two lines above, and found while fixing the first. The hook cannot see a run before
the first turn boundary, so the first window's start comes from `task_started_at` in the run file —
frontmatter again. A date in the *future* costs nothing to write and leaves the window empty for the
rest of the run: spend measures 0 every time, the ceiling never fires, and nothing says so. Rule 2
says an unmeasured ceiling is not a ceiling; this was worse, because it measured and reported zero.

A declared start is now accepted only if it parses and is not ahead of now; anything else falls back
to the hook's own clock. A date in the *past* is still taken as written — it widens the window and
charges the task with more than its own spend, which is wrong in the safe direction, and it is also
the honest case: the run really did begin before the hook first saw it.

Four selftest cases, each mutation-tested against the restored defect. § 3 of
`docs/verified-platform-behaviour.md` records the first.

## [0.18.1] — 2026-10-10

### Fixed — the anti-stall guard hung off a field the model writes

The autopilot stops a run that has stopped advancing. It decided "advancing" from two things: the
number of open tasks, and `current_task` — which the model writes, and which the block reason
*explicitly instructs it to write* when a task is done.

So a model that moved `current_task` without closing anything reset the guard on every single block.
Not evasion, just confusion between two open tasks; the effect is the same either way. Measured at
12 consecutive blocks with no task closed and no stop, bounded only by `continuations_max` forty
blocks away. CLAUDE.md rule 3 says nothing the model can edit may extend a run, and this was the
counter-example.

Progress is now one thing: **the set of open tasks changing**. `current_task` stays in the reason,
because it is what makes the message readable, and is out of the condition, because it is not a
signal the model can be trusted to send about itself.

### Measured — which anti-stall guard fires first

Two mechanisms watch the same `Stop` event and neither knows about the other. The platform honours
8 consecutive blocks without progress and overrides the 9th, silently. This framework's guard stops
after 5 continuations that closed no task. Only the one that fires first produces a reason anyone
reads — and until now, which one that was had never been tested.

It is ours, at **block 6**, with two blocks of margin. Measured both ways: `hooks/selftest.py` now
asserts the block number rather than just the outcome, and the new `scripts/probes/stall-ordering.sh`
drives the shipped hook through a real Haiku session on a run that cannot be finished, which stopped
at block 6 with the framework's reason — the same number. Recorded in § 3 of
`docs/verified-platform-behaviour.md` with both methods.

The margin is the finding: raise `STALL_STOP` past 7 and a stalled run still stops, but the platform
gets there first and stops it without saying why.

## [0.18.0] — 2026-10-10

### Fixed — the cheap model was unpriced, so the cheap model was never cheap

`haiku` resolves to `claude-haiku-5-5`, measured. The cost table did not hold it, so every run that
routed there was priced at the fallback — deliberately the most expensive row, because an unknown
model must never quietly raise a ceiling. Safe for a guard, backwards for a report: the model the
framework recommends *because* it is cheap was the one being billed at top-tier rates.

It is priced now, and it is the first model where one id is not one price. Claude Haiku 5.5 charges
by prompt length — about 5× over 100,000 prompt tokens, on every line, each request on its own. A
model may carry a second rate card under `long_prompt`, and `hooks/lib/spend.py` picks per message.
The threshold counts every input token of the request, **cache reads included**: on a Claude Code
turn `input_tokens` is a handful and the rest of the prompt is a cache read, so counting only
`input_tokens` would under-report a long turn fivefold.

### Fixed — two cache-read prices, wrong since they were written

`claude-mythos-5-1` was priced at $1.00 per million cache-read tokens where it is $0.25, and
`claude-sonnet-5-5` at $0.20 where it is $0.10. Both had been written as 0.1× input, which is the
usual ratio and wrong for those two models.

Found by re-reading the pricing page rather than by any check, and that is not fixable: cache reads
have no single ratio (0.1× on most models, 0.05× on Opus 5.5 and Sonnet 5.5, 0.025× on Fable 5.1 and
Mythos 5.1), so a wrong one is perfectly self-consistent. The `verified` date and its staleness
warning are the only guard this class of error has, which is now written down beside the prices.

### Added — the gate can tell the table is missing the models in use

The framework routes by **alias**; the meter prices by **id**; Claude Code decides what an alias
means, and nothing in the plugin changes when that answer moves a generation. Section 2 of the gate
compared the table with itself and was green throughout the failure above.

- `scripts/probes/model-ids.sh` resolves each alias with one near-empty session, reading the id out
  of the `stream-json` init event, and says which are unpriced. It reads the alias list from
  `agents/*.md` and `templates/efficiency.md`, so a new agent is covered the day it lands.
- The mapping it measures is recorded in `hooks/lib/model-costs.json` under `resolved`, beside the
  prices it selects.
- `scripts/lib/check-priced-models.py` is the free half: every routed alias has a measured id, every
  measured id has a price, and the mapping is not older than 90 days.

### Fixed — the marketplace catalogue had been declaring 0.13.0 since 0.13.0

`marketplace.json` carries the version twice: as the `ref` consumers pin, and as a field beside the
description. Only the ref was checked, so the field sat four releases behind. Corrected, and the gate
now reads both copies.

### Measured

`docs/verified-platform-behaviour.md` § 16 — what `haiku`, `sonnet` and `opus` resolved to on
2.1.296, why nothing in the repo could have noticed, and which half of the check has to stay a probe
because resolving an alias costs money.

## [0.17.0] — 2026-10-10

### Fixed — a run file with no ceilings had no ceilings, and said nothing

The spend guard only executed when `spend_max > 0`. A run file that never named
`task_spend_max_micro_usd` therefore skipped the guard **and the fail-closed branch inside it** —
the one that exists because rule 2 of this project says an unmeasured ceiling is not a ceiling. Same
for `continuations_max`. The run went ahead unbounded, in silence, and the only symptom arrived
minutes later and somewhere else: a report that could not say what anything had cost.

Measured on a real run, which executed three tasks that way.

The fix turns on a distinction the code never drew: **absent is not zero**.

- **A ceiling that was never written stops the run**, with a reason naming the missing key and
  pointing at `/efficiency:plan-run`, which writes both from the policy's `budget`. This is the same
  doctrine as refusing to start without a gate.
- **A ceiling someone wrote as `0` is honoured** — it is a decision, and a developer approved the
  plan that contains it — **but it is announced on every continuation**: *"Running with no spend
  ceiling — set in the run file as 0. Nothing will stop this run on that count."*

A model that rewrites the frontmatter and drops the keys it does not recognise now stops the run
rather than continuing without limits. Deleting your own ceiling is the most complete way of
extending a run, so it is the last thing that may pass quietly.

**If a run stops on this**, the run file predates this version or was written by hand. Re-plan with
`/efficiency:plan-run`; nothing in the policy changes.

Three selftest cases, each confirmed to fail with the guard removed. The existing case that proved a
frontmatter rewrite cannot reset the stall counter was superseded rather than deleted — it now
asserts both the old protection and the stronger new one.

The guard list is stated in two places, `README.md` and the hook's own header, and both were updated.

## [0.16.0] — 2026-10-10

### Fixed — a quoted gate never ran, and the framework read that as failing tests

`gate: "pytest -q"` is the form `templates/efficiency.md` ships. The run file is parsed by hand, and
that parser kept the quotes, so the shell received a command whose *name* was the whole quoted
string. A missing command exits 127, which is indistinguishable from a suite that failed — so the run
did not report an unrunnable gate. It reported a red one, and spent its repair attempts fixing code
that was never broken.

Found by running a real run and reading its log, not by review. One layer of matching quotes is now
stripped, and two selftest cases hold it: the passing case uses a gate **with arguments**, because
`sh -c '"true"'` succeeds — the shell strips quotes around a single word itself, so a one-word gate
cannot detect the defect at all. The first version of the test used `"true"` and passed with the bug
fully present.

### Fixed — the cheap model was being priced as the most expensive one

A real run routed to `claude-sonnet-5-5`, `claude-haiku-5-5` and `claude-opus-5-5`. **None was in the
cost table.** All three were charged at the fallback, which is deliberately the most expensive row so
that an unknown model can never quietly raise a ceiling — safe for a guard, backwards for a report.
A Haiku subagent priced at top-tier rates reads as about five times what it cost, which erases the
exact saving routing exists to demonstrate.

`claude-opus-5-5` and `claude-sonnet-5-5` are now priced from the `claude-api` skill's table. More
importantly the fallback is no longer silent: `hooks/lib/spend.py` returns the ids it could not
price, the hook writes them to a new `task_spend_unpriced_models` key, and `/efficiency:run-report`
must say so before showing any spend table. `claude-haiku-5-5` is still unpriced, because this repo's
source does not list it and inventing a number to make the figure look finished is the thing the
measurement discipline exists to prevent.

### Added — routing has been watched working

`scripts/probes/run-routing.sh` drives a real run end to end and reads which `Task` calls it made.
Measured: `implementer-fast` → `reviewer` → `implementer-fast`, three tasks closed, gate green,
`run-report` opening with `DONE`. The framework's headline claim is no longer only a design.

Section 15 of `docs/verified-platform-behaviour.md` has the method, the numbers and why the dollar
figure from that run is an upper bound rather than a cost.

## [0.15.0] — 2026-10-10

### Added — the headline assumption, measured at last: skills are reached by what they do

The framework's premise is that a developer never has to remember a command name. That had been seen
work once, for one skill, and assumed for the other six.

`scripts/probes/skill-auto-invoke.sh` measures it: seven skills, a plain request in English and in
Italian, three trials each, 48 headless sessions in a scaffolded project. It reads the `Skill` call
the model chose, and two negative controls check the opposite failure.

| skill | English | Italian |
|---|---|---|
| `backlog`, `init`, `run`, `run-report` | 3/3 | 3/3 |
| `plan-run` | 1/3 | 2/3 |
| `fanout` | **0/3** | 2/3 |
| `autopilot` | **0/3** | **0/3** |

No skill was ever chosen in place of another, and neither control ever fired.

**Naming the trigger phrases turns out to be necessary, not sufficient.** All seven descriptions do
it, in both languages, since 0.14.0. The four reached every time ask for something the model has no
other way to do. The three that are missed ask for something it will simply do instead — the
transcripts show it finishing the TODO list rather than arming the autopilot, adding four docstrings
in sequence rather than fanning out, drafting the plan rather than invoking the planner.

The autopilot's 0/6 is not its production number: a real session gets a `UserPromptSubmit` line
naming it, and that hook never fires under `-p`. Which also means the framework's most important
skill is currently carried by a hook rather than by its own description. Filed.

### Added — two guards for the thing this repo keeps getting wrong: knowing what is still true

**`scripts/lib/check-measurement-age.py`.** `docs/verified-platform-behaviour.md` promises every
entry carries its date, its version and its method. Eight of thirteen carried none, which is how § 7
stayed wrong for a month. Undated now fails the gate; older than 90 days reports as a skip, the way
the price table already does. All eight have been backfilled with provenance read out of the git
history rather than guessed — and § 10, whose version the history cannot settle, says so.

**`scripts/lib/check-probe-flags.py`.** `--max-turns` left `claude --help` on 2.1.296 while staying
accepted, and four probes bound themselves with it. The guard reads the flags out of the probes
themselves and checks each against the installed `claude`, free and with no API call.

Both ship with a `--selftest` that `scripts/qa.sh` runs before the check itself.

## [0.14.0] — 2026-10-10

### Fixed — `.claude/` is not refused, it is refused in two permission modes out of four

Section 9 of `docs/verified-platform-behaviour.md` said Claude Code refuses every write into
`.claude/`. It was measured once, under `acceptEdits`, and stated as a blanket rule. A later session
on 2.1.296 wrote `.claude/settings.json` repeatedly without a refusal — the exact opposite — and the
contradiction sat in the backlog as an unexplained anomaly.

`scripts/probes/dot-claude-writes.sh` settles it. Twelve headless sessions, four permission modes by
three tools, each asked to write into the project root first and `.claude/` second so the root write
is a control:

| permission mode | `Write` | `Edit` | `Bash` |
|---|---|---|---|
| `acceptEdits` | refused | refused | refused |
| `dontAsk` | refused | refused | refused |
| `auto` | allowed | allowed | allowed |
| `bypassPermissions` | allowed | allowed | allowed |

Both observations were right. The variable nobody controlled for was the **permission mode**, and the
tool turns out not to matter at all.

**The layout does not change.** `.efficiency/` at the project root stays, because a plugin cannot know
which mode a consumer runs in and a layout that works in half of them breaks for half its users with
no diagnostic.

**The advice changes.** `/efficiency:init` could never install the permission fence, and reported that
as a graceful degradation — which reads as a broken framework. It now tries the write and, when it is
refused, says which constraint it hit: the snippet to paste, *and* that re-running in `auto` mode
installs it without the paste.

### Added — the gate now catches a skill that can never be auto-invoked

A skill's description is the entire input to the model's decision to invoke it. One that says what the
skill does but never the words a developer would actually say fails in the way nobody notices: it
simply never fires, and the session does the work the long way round.

`scripts/lib/check-skill-triggers.py` requires each description to carry a "use when" clause, at least
two quoted trigger phrases, and a length that can hold both. It ships with its own `--selftest`, which
`scripts/qa.sh` runs first — a trigger check nobody has watched reject a vague description is worth
exactly as much as no check at all.

It caught **five of the seven shipped skills**. `fanout`, `init`, `plan-run`, `run` and `run-report`
now name their triggers the way `autopilot` already did, in English and Italian — so a plain request
can reach them.

Whether quoted phrases actually change how often a skill fires is a house rule, not a measurement.
Confirming it is in the backlog.

## [0.13.0] — 2026-10-10

### Added — documents get converted once, and the reason is not the one you would assume

A session handed a PDF reads it as page images. Measured on 2.1.296 with the new
`scripts/probes/pdf-token-cost.sh`, which builds a five-page document whose last page holds seven
lines on an otherwise empty sheet:

| What was read | Tokens | Per page |
|---|---|---|
| The PDF, `pages="1-5"` | 6,402 | **1,280** |
| The last page alone — seven lines | 1,390 | **1,390** |
| The same five pages as text | 5,838 | 1,168 |

**The near-empty page cost more than the average full one.** Each page becomes an image of fixed
size, so the bill follows the page count and never looks at the content.

And the comfortable conclusion is wrong: converting that dense document to text saved **9%**, not an
order of magnitude. At ~3 characters per token the break-even is around 3,500 characters a page —
roughly a page of margin-to-margin prose. What converting actually buys is that text is
**addressable**: done once, to a file, forty pages that would cost ~52,000 tokens to look through
become one `grep` and one forty-line slice. The framework says that, rather than the easier claim.

- **`AUTONOMY-CHARTER.md`** carries the rule: convert once to a file, then read the slice;
  `pdftotext` when plain text is enough, `docling` when tables and figures matter, `marker_single`
  for the complex and image-heavy cases where docling comes out visibly wrong — and **read the page
  image when the layout is the content**, a scan or a signature, where converting is strictly worse.
- **`scripts/detect-tools.sh`** recognises `docling`, `marker_single`, `marker`, `mineru` and
  `markitdown`, so a converter that is already installed stops being invisible.
- **`/efficiency:init` raises the absence by name in every project**, not only document-shaped ones,
  and offers both tools: docling for everyday documents, marker for the hard ones. It checks the
  interpreter first, **because `pip` will not** — both need Python 3.10+, and on 3.9 the install does
  not fail, it silently resolves to the last release that still supported it (`pip3 download docling
  --no-deps` returns `docling-2.69.1`, verified).
- **`scripts/probes/pdf-token-cost.sh`** and **§ 13 of `docs/verified-platform-behaviour.md`** record
  the measurement and how to take it again.

### Fixed — two instructions that named something the reader cannot reach

- The charter told sessions to re-run `scripts/detect-tools.sh` after installing a tool. That script
  lives in the plugin, and **nothing outside the project is reachable from a session** — the same
  defect fixed for skills in 0.11.0, left behind in the one sentence that most needed it, and now
  about to be followed much more often. It now says to delete `.efficiency/tools.md`, which the
  `SessionStart` hook rewrites.
- The README still credited `init` with running the detection. The hook has done it since 0.11.0.

## [0.12.0] — 2026-10-10

> **Never released on its own.** `VERSION` went from 0.11.0 straight to 0.13.0 in `0b5e8be`, which
> shipped this entry and 0.13.0's together, so there is no `v0.12.0` tag and none is missing. To get
> this work, pin `v0.13.0` or later.

### Added — the backlog is now permanently visible, not announced once

A backlog announced at session start is gone by the third reply. Measured on this repo: the
`SessionStart` injection had grown to **18 KB**, the harness truncated it to a 2 KB preview, and the
part that survived instructed the session to mention the backlog *once, in no more than two lines*.
Work deliberately deferred was therefore visible for one reply out of a session.

A **status line** fixes exactly that, and nothing else fixes it: it is the only surface in Claude
Code re-rendered under the prompt on every conversation update.

```text
⚠ backlog: 12 open · oldest 2026-10-10 · +9 more · /efficiency:backlog
  1. /efficiency:init cannot write the permission fence
  2. The session that builds a release can never run it
  3. Model routing has never been observed working
```

- **`hooks/statusline.py`** — the count, the oldest date, and the top three entries cut to their
  headline. One file read per render, because it is re-run every second or so.
- **`hooks/session-start.py` deploys it** to `.efficiency/statusline.py` and refreshes it whenever
  the plugin changes. The status line command is **not** given `CLAUDE_PLUGIN_ROOT` — measured — so
  it cannot name the plugin, and a plugin's install path is not stable enough to hard-code.
- **`/efficiency:init` offers it**, never installs it over an existing `statusLine`, and
  `statusline: off` in the policy frontmatter ends the subject permanently.
- **`scripts/check-install.sh`** reports a half-wired status line as a problem: a settings file that
  names a script that is not there paints a blank line, and a blank line is how this framework fails
  worst — silently, looking fine.
- **Twelve selftest cases**, including the ones that prove it stays quiet: no policy, no line at all;
  an existing status line is never mentioned; the opt-out silences the offer; a corrupt backlog
  cannot take it down.

### Measured — `docs/verified-platform-behaviour.md` § 12, the status line

New probe, `scripts/probes/statusline.sh`. Three results decided the design and all three would have
been guessed wrong: **every line printed is rendered** (not just the first), **`CLAUDE_PLUGIN_ROOT`
is absent** from its environment while `CLAUDE_PROJECT_DIR` and `COLUMNS` are present, and **a
settings change is live without restarting the session** — unlike a hook, which is bound at session
start. Its payload also carries `cost.total_cost_usd`, `rate_limits` and `context_window`; none of
it is used, because a status line that says four things says nothing.

### Noted — § 9 may have expired, and is not being rewritten on one observation

"Claude Code refuses writes into `.claude/`" did not reproduce on 2.1.296: this session wrote
`.claude/settings.json` through `Bash` repeatedly, unrefused. Recorded as an **anomaly** under § 9
and filed in the backlog, because it was one session in one permission mode and that claim decides
the framework's whole file layout. There is still no probe for it; writing one is the backlog entry.

## [0.11.0] — 2026-10-10

### Fixed — every skill instruction that pointed into the plugin was unfollowable

Running `/efficiency:init` in a genuinely fresh project for the first time, it stopped and said so:
it could not read the policy template, because **nothing outside the project a session is working in
is reachable from that session** — `Read` asks for a permission that is not granted, `Bash` is
blocked — and the model is never told `CLAUDE_PLUGIN_ROOT` either. Both measured.

Seven instructions across `init` and `run-report` named that path. None of them could be followed by
anyone. The first thing a new adopter does did not work.

The rule the fix follows: **anything the model needs must be inside the project, put there by a
hook** — hooks have neither limitation.

- **The tool inventory writes itself.** `SessionStart` runs the detection when `.efficiency/tools.md`
  is missing or older than a week. No adopter step, and it cannot go stale unnoticed.
- **`init` carries the policy and backlog skeletons inline**, so it writes them without reading
  anything.
- **The per-model spend split is written into the run file** by the autopilot, as
  `task_spend_by_model`, because `run-report` cannot execute `spend.py` any more than `init` could
  read a template.
- **`SessionStart` publishes the plugin's path** with a plain statement that the session cannot read
  it — so the two operator commands can be handed to the developer, who can.

### Also found

`claude plugin marketplace remove` **rewrites project settings**, including committed ones. Removing
the marketplace emptied `enabledPlugins` from this repo's tracked `.claude/settings.json` and left an
unexplained `git diff`. Worth knowing before anyone does it on a shared repository.

**62 selftest checks, 10 validator checks, 0 failed.**

## [0.10.0] — 2026-10-10

Found by testing the previous release's own feature rather than trusting it.

### Verified — the inert-install detection works

A project left in the pre-0.4.0 state, opened as a real session: the first thing the model read was
`# ⚠ This project's efficiency framework is INERT after an upgrade`, and it could quote it back. The
silent failure that cost two misdiagnoses now announces itself.

### Fixed — enabling a plugin takes two halves

While building that test, three sessions failed to load the plugin from a `.claude/settings.json`
written by hand — byte-identical to what `claude plugin install --scope project` produces. Isolated
by removing each half in turn:

| `enabledPlugins` | registry entry | loads? |
|---|---|---|
| yes | yes | **yes** |
| yes | no | no |
| no | yes | no |

**Both are required.** The install command also records an entry in
`~/.claude/plugins/installed_plugins.json`, and that entry is what makes the difference.

Three things were wrong because of it:

- **The README promised team adoption that does not work.** "Commit `enabledPlugins` and a colleague
  who clones gets it" is false — they each run `marketplace add` and `plugin install`. Read as design
  this is right, and the README now says why: the committed setting is the project's *intent*, the
  local install is that machine's *consent*, and a repository able to enable a hook-running plugin by
  itself would run code the moment you cloned it.
- **`check_enabled.py` reported enabled from settings alone**, so the validator would have called a
  project conformant where the plugin does not load — the exact bug class it exists to catch, inside
  itself. It now requires both halves and reports each missing one separately, because the fixes
  differ.
- **The validator's own tests enabled the plugin by writing settings only**, so every "correct
  install" case was passing on a false premise. The fixture writes both now, against a registry
  fixture reached through `EFFICIENCY_REGISTRY` — a test that mutated the machine's real plugin state
  would be one nobody dares run twice.

**10 validator checks, 59 selftest checks, 0 failed.**

## [0.9.0] — 2026-10-10

### Changed — the validator now checks the chain, not the files

0.8.0 shipped `check-install.sh`, and re-reading it against the question *"does this install actually
work?"* it did not answer it: it inspected the project's own files and never asked whether the plugin
was reachable at all. Given a project with a perfect `.efficiency/` and the plugin **not installed**,
it reported **CONFORMANT**. A validator that says the install is fine about nothing is worse than no
validator.

It now walks the whole chain:

- **Prerequisites** — `python3` present and 3.7 or newer, the version the hooks need.
- **Reachability** — is the plugin enabled for *this* project: project scope, user scope, or neither,
  and at which version. Distinguishes "the CLI installed it but no settings file enables it" from
  "never installed", because the fix differs.
- **Policy shape** — frontmatter parses and closes; `budget`, `tiers`, `routing` and `stop_for` are
  declared; defaults are written. A policy missing a section does not fail loudly at runtime — the
  model simply never sees that part, which is the same silent degradation this script exists for.
- **The gate** — not only declared but **resolvable**: its runner on `PATH` and its target actually
  existing. A gate pointing at a renamed script fails on every turn. It is never executed: a
  validator that runs your test suite is one nobody runs.
- **Hooks, actually run** — all three invoked and their output checked. This is the difference
  between *looks right* and *works*.
- Hygiene and run state as before.

### Added

- **`scripts/test-check-install.sh`** — nine scenarios proving the validator can fail, including the
  one 0.8.0 got wrong. Both it and the validator run in this repo's own gate.

### Fixed, found while building it

- A project that had never adopted the framework was being reported as a failure, because the
  enablement check ran before anything knew whether adoption had happened. Adoption is settled first
  now, and "not enabled" is a note rather than a problem where nothing has been adopted.
- Two shellcheck findings in the new code: a redundant environment assignment the forked process
  could not see, and a captured hook output that was never shown — it is now printed when the hook
  misbehaves, which is the only time anyone wants it.

**59 selftest checks and 9 validator checks, 0 failed.**

## [0.8.0] — 2026-10-10

Upgrading was not safe, and the way it failed was silence.

### Fixed — the silent-inertness upgrade

0.4.0 moved every file this framework writes out of `.claude/`, and nothing was left to notice a
project that upgraded across the move. Its policy stays where 0.3.x left it, the plugin looks in the
new place, and **everything stops: no charter, no policy, no guards, and no error**. Reproduced on a
simulated adopter: the hook printed nothing at all.

- **`SessionStart` now reports it**, in the first thing a session reads: which files are in the old
  place, where they belong, and that `/efficiency:init` migrates them. It does **not** move them —
  moving a developer's files unasked is the invasive act this framework avoids.
- **`/efficiency:init` migrates**, as step 0, before anything else.

### Added

- **`scripts/check-install.sh`** — read-only, no network: is this project's install actually working?
  Catches the stale layout, a missing gate, run state that would be committed, a missing tool
  inventory, and a run left mid-flight. Exit 0 conformant, 1 not, 2 cannot tell. It runs in this
  repo's own gate, because this repo is a project like any other.
- **The catalogue pins a release tag** instead of tracking `main`, so a consumer gets a version that
  was deliberately published rather than whatever the default branch held this morning. The gate
  fails a release whose tag, `VERSION` and changelog entry disagree.
- A README section on upgrading that says what is **not** guaranteed: no `--version` on install or
  update, so no supported rollback; the recourse is uninstall and reinstall from a catalogue you pin
  yourself.

### Changed

- The three update traps now sit together in the install section: `marketplace update` moves the
  catalogue and not your install; `plugin update` can report a scope mismatch as a missing plugin;
  and `plugin list` prints one entry per project install **with no project path**, which is what made
  three test runs here silently execute 0.1.0.

### On "do we uninstall and reinstall each time?"

No. `marketplace update` then `plugin update`, then restart. Uninstalling is only the fallback for
the thing that has no first-class support — going *back* to an earlier release.

**59 checks, 0 failed.**

## [0.7.1] — 2026-10-10

### Changed

- **The install section leads with the scope.** `claude plugin install` defaults to **`--scope
  user`**, which enables the plugin for every project on the machine — the README showed only
  `--scope project` and never said what omitting it does. It now shows both, warns about the
  default, and gives the rule for choosing: `user` for your own projects, because the plugin is inert
  without `.efficiency/policy.md` and installing once costs nothing where it has not been adopted;
  `project` for shared repositories, where `enabledPlugins` is committed so cloning is enough.
- The marketplace and the plugin are now clearly two steps in two places, with the reason — trusting
  a marketplace is the machine owner's decision, not a cloned repository's.
- The update trap and the `plugin list` ambiguity moved into the install section, where someone
  hitting them will actually be reading.

## [0.7.0] — 2026-10-10

### Added — use the tool, don't rebuild it

The expensive failure is not a missing tool, it is a **present tool nobody knew about**. This machine
has `pdftotext`, `sqlite3`, `gh`, `glab` and `docker`, and no session knew. Asked to pull text from a
PDF, a session that does not know `pdftotext` is there writes Python with pypdf, fights the
encodings, and spends thousands of tokens on what one command does in fifty.

- **`scripts/detect-tools.sh`** — writes `.efficiency/tools.md`: which of 25 operational CLIs are
  present, with what each is for. Document conversion, PDF, CSV, media, search, platform. No network,
  installs nothing, only looks. **Gitignored**, because it describes a machine and not a project.
- **The inventory is injected into every session**, purposes kept and versions dropped — a version
  matters when something misbehaves, and it is in the file when anyone wants it.
- **A charter rule**: check for a tool before writing code to do something operational. When one is
  genuinely absent, name it and offer to install it **once**, saying whether it will be needed again
  and whether CI needs it too — *a tool present here and absent from CI is a difference that bites
  later*. Re-run the detection after any install, or the next session goes back to writing the
  script.
- **Staleness, scoped so it does not become its own waste**: check at most once per tool per session
  and only for a tool about to be leaned on, never before every `jq`. And **never update mid-task** —
  a version change alters behaviour under work already in progress, turning a green task into a
  puzzle. Finish first, then offer.

### What was deliberately not built

A prompt at install time asking whether to install office tooling. At setup you do not know what the
project will need, so you would be guessing — and the framework's first act would be asking for a
permission nothing needs yet, which is exactly the interruption without added value this project
exists to remove. The offer belongs at the moment of need, where it has a visible cost and benefit.

### Fixed

- Version detection rejects error output. `pdftotext` treats `--version` as a filename and answers
  `I/O Error: Couldn't open file '--version'`; `unzip` answers a flag warning. Both were being
  printed into the inventory — noise in the one file whose job is to be believed. It now tries
  `--version`, `-version`, `-V`, `-v` and discards anything that reads as a complaint.
- Prose assertions in the selftest normalise whitespace. A sentence crossing the 100-column wrap
  broke a literal check twice while nothing about the content changed; assertions test meaning now,
  not line width.

### Verified

Given a PDF and no instruction about how, a session ran `pdftotext` and wrote **no script at all** —
and volunteered that the file was malformed, which it was. **57 checks, 0 failed.**

## [0.6.0] — 2026-10-10

### Added — the boundary at "done", and somewhere for the rest to go

Finishing is a boundary, not a pause. A session that keeps widening becomes one nobody can review,
and the second thing is always done with worse attention than the first: the context is full, the
original goal is far behind, and nobody decided the new work was worth doing.

- **The charter sorts what comes up.** Blocks the task → now, it was part of it. You broke something
  → now, you caused it. **Anything else you noticed → the backlog, not this session.** The third row
  is the one that feels wrong to obey and the one that matters: a clear, real improvement spotted
  mid-task is exactly what quietly doubles a diff nobody agreed to.
- **`.efficiency/backlog.md`** — committed, because it is shared knowledge that outlives the session
  that filled it. Each entry is one line with a `found while:` clause, which is not decoration: a
  fresh session has none of the context that made the thing obvious, and that half-sentence is the
  cheapest way to give it back.
- **Open items are surfaced at the top of every session**, ahead of the charter, by the same hook —
  with instructions to mention them once, in two lines, and **not** to start on them. A deferral
  nobody is reminded of is a deletion with extra steps; and picking one up because it is in front of
  you is the same scope creep, one session later.
- **`efficiency:backlog`** — file one, review what is outstanding, or pick one up as a new task.

### Fixed

- **The done-rule refuses the small-change exception.** A session reported `DONE` while admitting it
  had skipped the gate because the change was one line. That is the reasonable-sounding exception
  that erodes a rule, so the charter names it: judgements about the size of one's own change are the
  unreliable part, running the gate costs seconds, and deciding it was unnecessary is the thing being
  checked.
- **The backlog counter skips fenced code blocks.** The shipped template documents the entry format
  with a real-looking example inside a fence, and counting it reported a phantom item on day one — in
  the one file whose job is to be trusted about how much is outstanding.

### Verified

Given a task plus a deliberate nudge toward something else — *"e già che ci sei, nota che
src/legacy.sh ha un problema di sicurezza"* — a session surfaced the backlog in one line, did the
actual task, ran the gate, left `legacy.sh` untouched, filed no duplicate, and reported `DONE` with
the security issue listed as still open in the backlog. It also volunteered that the project's gate
was weak and therefore proved little. **51 checks, 0 failed.**

## [0.5.0] — 2026-10-10

### Added — the question a report must answer

**Is it done?** A report the reader has to decode is not a report, and nothing in this framework had
ever said so. The charter now carries three things, and they reach every session:

- **What done means.** Every acceptance criterion observably met, the gate green *and run*, nothing
  left that was intended. And what it does not mean: **unverified is not done, it is unknown.**
  Neither is something left deliberately red, anything kept "for later", or a problem found and not
  fixed. A green gate does not make a task done when something outside the gate was left failing —
  those are two questions and only one of them is the gate's.
- **Lead with the verdict.** The first line of any hand-back is exactly one of **DONE**, **NOT
  DONE**, **BLOCKED**, in the language of the conversation, then the detail. A reader who stops after
  the first line must not be misled.
- **Keep three kinds of thing apart**: what was delivered, what is still open and who it waits on,
  and what was found along the way. A finding is not a deliverable — three problems found and one
  fixed is *one fixed, two open*, not "three addressed". An unresolved mistake belongs in the open
  list, not only in the narrative.

`run`, `run-report` and `autopilot` all carry the same rule, and the hook's own completion message
now asks for the verdict — it is the last thing the model reads before writing the report.

### Why

From a real report: dense, accurate, full of genuine findings, and impossible to answer *"is this
finished?"* from. It ended with "gate green" while elsewhere noting that something stays red by
design, that cases still need writing, and that a broken CI configuration meant two commits never
ran — which means unverified, which means not done. All true, none of it decidable without reading
to the end.

### Verified

All three verdicts observed, used discriminately: **DONE** on completed and gate-verified work,
**NOT DONE** when the gate could not run, **BLOCKED** when a command needed approval the session
could not get. Each opened the report, with delivered and open items separated beneath. 44 checks,
0 failed.

### Also recorded

`docs/verified-platform-behaviour.md` § 7: permission rules are still gated by workspace trust, and
2.1.289 now **says so** instead of ignoring them in silence — it names the entry it dropped and how
to grant trust. Trust did not stop mattering; it stopped gating hooks, and it stopped being
invisible.

## [0.4.0] — 2026-10-10

The release that found out why nothing ever finished.

### Fixed — the defect under the other two

**Claude Code refuses to write into `.claude/`.** Measured under `acceptEdits`: editing an existing
file there is denied, creating one is denied, and it is denied through `Write`, `Edit` and `Bash`
alike. A project `permissions.allow` rule naming the exact path does not lift it. The same writes one
directory up all succeed.

Both of this framework's live files were in there. Every one of them is a file the *model* must
write — ticking a task closed, advancing to the next, appending to the run log, adding a declared
default it had to invent. None of it could happen, and arming the autopilot could not happen at all,
since arming means creating the run file.

That had already been diagnosed twice as something else: as a block reason missing its instructions
(0.2.0), and as a model tidying away keys it did not recognise (0.3.0, retracted in 0.3.1). Both
plausible, both wrong, and both shipped.

### Breaking

Everything the framework writes moved out of `.claude/`:

| Was | Is |
|---|---|
| `.claude/efficiency.md` | `.efficiency/policy.md` (committed) |
| `.claude/efficiency.local.md` | `.efficiency/run.md` (gitignored) |
| `.claude/.efficiency-autopilot.json` | `.efficiency/autopilot.json` (gitignored) |

An existing adopter moves the policy and updates `.gitignore`; `/efficiency:init` does both.

### Added

- **The project's own policy is now injected into every session**, alongside the charter. It was
  missing, and measurably so: asked which paths this project declares critical, a session answered
  *"NOT IN MY INSTRUCTIONS"*. The charter had been pointing at a file nobody told the model to read,
  which left the declared defaults — the design's own largest lever — reaching the model only inside
  `/efficiency:plan-run`. Frontmatter comments are stripped first; the shipped template teaches
  through its comments, which is right on disk and waste in a context window paid for every session.
- **`efficiency:autopilot`** — arms a run from a plain instruction to keep going, in any words and
  any language. The commands remain for work worth planning deliberately.
- **A `UserPromptSubmit` reminder**, one line, only in adopting projects and only when no run is
  armed. The charter already said to arm, and a session could recite the instruction and name the
  skill — then went straight to the work. Knowing is not doing when the instruction was read many
  turns earlier, so the reminder lands with the instruction instead.
- Seven selftest cases for `SessionStart`, which had none. **41 checks, 0 failed.**

### Removed

- `POLICY_FILE` in `autopilot-stop.py`, defined and never used.

### Verified end to end

A plain Italian instruction — *"Sono quattro. Procedi fino a completarli tutti, non fermarti a
chiedermi conferma"* — armed the autopilot, drove four tasks, closed every one and finished `DONE`.
**The first complete run in this project's history**, and nothing about the run machinery had
changed: it had simply never been able to write to its own files.

## [0.3.2] — 2026-10-10

Re-measured everything against Claude Code **2.1.289** (the findings were taken on 2.1.261). This is
the discipline this repo asks for — measure, date it, re-run it — exercised for the first time, and
it paid on the first attempt.

### Changed

- **§ 7 is expired.** A freshly created directory's project settings now fire their hooks normally.
  `SessionStart`, `Stop` and `UserPromptSubmit` all fired where they were silent a month ago. The
  record is kept, dated and marked, because it was true when taken.
- **§ 3 survives unchanged** — 9 invocations in `stall` mode, 6 in `read` with `--max-turns 12`,
  identical to September. The finding the whole design rests on is intact.
- **§ 9 corrected.** `plugin list` prints one entry per project install **with no project path**, so
  two installs of the same plugin look like one plugin reported twice at different versions. Reading
  the first entry and stopping produced a wrong conclusion here twice, including the claim in 0.3.1
  that this repo was still on 0.1.0 — it has been on 0.3.0 since the update was run.
  `~/.claude/plugins/installed_plugins.json` records `projectPath` and is the way to tell them apart.

### Added

- `scripts/probes/settings-trust.sh` — drafted by run three, which then declined to finish the task
  on the grounds that the finding was unreproducible. The probe works; the premise was wrong, as a
  table of five measurements in § 7 now records. Its first real run is what caught § 7 expiring.

### Two traps worth naming

- **A hook with no trigger looks exactly like a suppressed hook.** `PreToolUse` appeared not to fire
  in an untrusted directory; it simply had no tool call to intercept. Given a prompt that runs a
  command, it fires. Rule out the mundane explanation before recording a platform finding.
- **A clean zero proves nothing on its own** — it is produced by a suppressed hook, a hook that never
  triggered, and a broken probe alike. Only one of those is worth writing down.

### Still not validated

The 0.2.0 and 0.3.0 fixes remain unexercised by a real run. The timeline is now pinned: run three
finished at 15:04 UTC on 2026-09-05 and the upgrade to 0.3.0 landed at 15:05 — one minute later.

## [0.3.1] — 2026-09-05

### Fixed

- **Retracted the reasoning published with 0.3.0**, in the changelog, the README and the autonomy
  charter. The claim that a model had erased the stall guard's counters was wrong.

### The finding that caused it

`claude plugin marketplace update` refreshes the catalogue and reports success. **It does not update
an installed plugin.** Nothing says so, and `claude plugin list` keeps reporting the installed
version — which is the only honest answer to "what am I running".

Three consecutive dogfooding runs of this framework therefore executed **0.1.0** while 0.2.0 and
0.3.0 sat in a refreshed catalogue. `open_tasks_seen` was missing from run two's state file because
0.1.0 never wrote that key, not because anything deleted it. The stall guard was not neutralised; it
was never loaded.

Two related edges, both now in `docs/verified-platform-behaviour.md` § 9: `plugin update` defaults to
**user** scope and fails against a `--scope project` install with a message that reads like the
plugin is missing; and after updating it says *"Restart to apply changes"* while `plugin list` still
shows the old version.

### Consequences to be honest about

- **The fixes in 0.2.0 and 0.3.0 remain unvalidated on real work.** They are sound as design and
  green under 34 selftest cases, but no run has exercised them.
- Run one's diagnosis stands: 0.1.0's block reason genuinely lacked the closing instructions, which
  is what it was measured against.
- Run three, also on 0.1.0, **closed a task in a single turn with no continuation at all**, and
  stopped for a legitimate `stop_for` reason with a precise account of why the next task could not be
  built as specified. That premise was itself wrong — the finding it disputed reproduces, as § 7 now
  records with a table — but stopping instead of guessing is exactly the behaviour asked for.

### Added

- `docs/verified-platform-behaviour.md` § 7 now carries the measured trust table. **Trust is not
  inherited from an ancestor**: a fresh subdirectory inside a repo you work in daily is as untrusted
  as one in `/tmp`, and its project settings are ignored just as silently.
- § 9 documents the update trap above, and the README's install section leads with it.

## [0.3.0] — 2026-09-05

### Fixed

- **The hook's counters and ceilings moved out of the run file** into
  `.claude/.efficiency-autopilot.json`, which no skill mentions and the charter forbids touching.
  The hook captures the ceilings there on first sight of a run and reads only from there.
- **A stopped run stays stopped.** The blocked verdict is private too, so setting `status: ACTIVE`
  in the run file no longer resumes a run a guard halted. Starting over means changing the task
  list — which is what re-planning already does — or deleting the state file deliberately.
- **The hook owns the spend window.** It opens a fresh one when `current_task` changes, so the
  model signals progress with one field instead of maintaining a timestamp it could also reset.
- A green gate now mirrors `gate_retries: 0` into the run file unconditionally. A stale retry count
  in the file a human reads is a small lie with no upside.

### Why

> **Retracted in 0.3.1.** This release was justified by a claim that turned out to be false: that a
> model had rewritten the run file's frontmatter and wiped the stall guard's counters. It had not.
> The keys were absent because the plugin actually running was 0.1.0, which never wrote them. See
> 0.3.1 for what really happened.

The change itself stands on its own reasoning: a guard whose counters live in a file the model is
asked to edit depends on the model preserving keys nobody told it were load-bearing, and a design
that needs that has a hole in it. Moving them out is a precaution, not a post-mortem. It is not a
security boundary either, and the docs say so — anything with a shell can delete that file.

Six selftest cases hold the separation in place: raising `continuations_max`, raising the spend
ceiling, flipping `status` back to `ACTIVE`, and rewriting the frontmatter the way a tidy editor
would. 34 checks, 0 failed.

### Also verified, on real work

- **The spend ceiling fires on a real run.** Run two stopped itself at *"T1 reached its spend
  ceiling ($5.06 of $5.00) without closing. It needs a human opinion before more is spent on it."*
  Nine continuations, a readable reason, and the session left alive. This is the guard the framework
  was asked for, and it works.

## [0.2.0] — 2026-09-05

### Added

- **A fifth guard: the stall guard.** The hook now tracks whether a run is actually advancing, and
  when the same task is handed back with nothing closing it escalates the wording, then stops the
  run. Six selftest cases cover it.

### Changed

- **The block reason now carries the state transitions**, imperatively and in order: tick the box,
  write the log line, move `current_task`, reset `task_started_at`, then work. It also forbids
  status reporting outright.

### Why

The framework failed its first real run, on its own repository, and the failure was in the design
rather than the code. Twelve continuations, $2.78, and the work of exactly one task — produced
correctly, then never closed. The last restarts were spent describing the counter: the driving
session's final line was *"Holding for that."*

The root cause: the `run` skill was read once, several turns earlier, while the **block reason is
the only instruction a model reliably reads on a continuation**. Putting the state transitions in
the skill and not in the block reason meant they did not happen — and nothing was watching for a run
that produced work without ever advancing.

Three lessons, all now enforced rather than written down: instructions belong where they will be
read; an unticked box is indistinguishable from unfinished work; and every guard needs a symptom it
can detect, not just a limit it can count to.

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

### Verified end to end

- **The plugin loads and its components are addressable.** `claude --plugin-dir .` exposes all eight
  as `efficiency:*` — three agents and five skills — which is also why the skills refer to agents by
  their namespaced names rather than their bare ones.
- **Adoption works, but not the way it first looked.** A `--scope project` install writes only
  `enabledPlugins` into the project; the marketplace stays in user settings, and committing
  `extraKnownMarketplaces` into a project does not register it. That split is right — trusting a
  marketplace is the machine owner's decision, not a cloned repo's — and the README now documents
  the measured path rather than the assumed one.
- **A project's own `Stop` hook coexists with the autopilot.** Both fire on every turn — 15
  invocations each in a real run — and neither is skipped because the other blocked first. And the
  platform's cap counts blocked *turns*, not blocks: with two hooks always blocking, each was
  invoked 9 times, the same total as one hook alone. They share the budget rather than halving it.
  This is also why the autopilot deliberately ignores `stop_hook_active`: a hook that stands down on
  that flag disables itself the moment any other Stop hook exists.
- **The autopilot blocks in a real session.** A throwaway project with two open tasks, a green gate
  and `continuations_max: 2`: the hook blocked twice, incremented the counter itself, then stopped
  the run with a reason naming both open tasks. The guard is real, not a diagram.

### Not yet verified

- The measurement that actually matters: a real run of ten tasks with every interruption counted and
  classified against the six causes. That number is the metric this framework is judged on, and
  until it exists the framework is a hypothesis with tests.
