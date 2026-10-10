# Verified platform behaviour

Every claim here was **measured on this machine**, not read in documentation. Each entry carries the
date, the Claude Code version, and the method, so it can be re-run when a release moves the ground.

Re-measure before trusting any of it after a Claude Code upgrade. The probes live in
`scripts/probes/` and take a couple of minutes and a few cents of Haiku.

First measured: **2026-09-05** · Claude Code **2.1.261** · macOS 23.3.0
Re-measured: **2026-10-10** · Claude Code **2.1.289** — § 3 unchanged, § 7 **expired**, § 9 corrected.
Added: **2026-10-10** · Claude Code **2.1.296** — § 12, the status line.
Corrected: **2026-10-10** · Claude Code **2.1.296** — § 9 **rewritten**: the refusal is real, but it
is governed by the permission mode, not by the tool, and it does not hold in all four.

The re-measurement is the point of the exercise, and it earned its keep on the first attempt: one
finding had quietly stopped being true, and only running the probe again revealed it.

---

## 1. The `Stop` hook payload

Captured by a hook that logged its stdin verbatim. The fields that actually arrive:

```json
{
  "session_id": "…",
  "transcript_path": "/Users/…/.claude/projects/<slug>/<session>.jsonl",
  "cwd": "/path/to/project",
  "prompt_id": "…",
  "permission_mode": "dontAsk",
  "hook_event_name": "Stop",
  "stop_hook_active": false,
  "last_assistant_message": "ok",
  "background_tasks": [],
  "session_crons": []
}
```

**`transcript_path` is present.** The official hook reference does not list it for `Stop`, but it
arrives. This is what makes per-task spend measurement possible without any API call.

`last_assistant_message`, `prompt_id`, `background_tasks` and `session_crons` are also undocumented
for this event.

*Measured 2026-09-05 on Claude Code 2.1.261 (`276a29e`). Not re-measured since.*

## 2. `stop_hook_active`

`false` on the first invocation of a turn chain, `true` on every one after it. It marks "a Stop hook
has already blocked in this chain", and it is shared across all registered `Stop` hooks — it is not
per-hook state.

**But sharing the flag does not mean the hooks interfere.** Measured with two hooks registered on
the same event, both always blocking: each was invoked on every single turn, and neither was skipped
because the other had already blocked. The flag is information, not a lock. A hook that treats
`stop_hook_active: true` as "stand down" disables itself as soon as any other Stop hook exists —
which is why this framework's autopilot deliberately ignores it and bounds itself with counters it
owns instead.

*Measured 2026-09-05 on Claude Code 2.1.261 (`276a29e`), and extended the same day by the
two-hook coexistence run in `dfa61e0`. Not re-measured since — see the backlog.*

## 3. The block cap — and the condition that governs it

This is the finding that decides how much autonomy is actually available, and the documented
"8 consecutive blocks" is only half of the story.

| Probe | What the model did between blocks | Hook invocations | What stopped it |
|---|---|---|---|
| A | Replied with text only, no tool calls | **9** | the platform cap |
| A2 | Same, but with **two** blocking hooks registered | **9 each** | the platform cap, shared |
| B | Wrote one file per turn | **20** | our own `--max-turns 40` |
| C | Wrote one file per turn | **6** | our own `--max-turns 12` |
| D | Ran one read-only `echo` per turn | **20** | our own `--max-turns 40` |

Read together:

- **The cap counts consecutive blocks with no progress.** Probe A stalls at 9 invocations — eight
  blocks honoured, the ninth overridden.
- **Any tool call resets the counter.** B and C scale exactly with `--max-turns` (12 turns → 6
  cycles, 40 → 20), which means the cap never bound them. D shows a *read-only* call is enough: no
  file has to change.
- Therefore the cap is not a ceiling on autonomy. It is a free **anti-stall guard**, and it fires on
  precisely the case that deserves it: a model looping without doing anything.

**Still true on 2.1.289** (re-measured 2026-10-10): 9 invocations in `stall` mode, 6 in `read` mode
with `--max-turns 12`. The finding the whole design rests on survived the upgrade unchanged.

**The cap counts blocked turns, not blocks.** With two hooks both blocking on every turn, each was
invoked **9 times** — the same total as one hook alone. Two hooks blocking together therefore consume
*one* of the eight occasions, not two. A project's own quality gate and this autopilot can coexist
without dividing the budget between them.

**Consequence for this framework.** The platform will not cut a working autopilot short, so the
limits that matter are our own — the per-task spend ceiling, the gate retry limit, and the
continuation budget. `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` exists but should be left alone: raising it
only buys more spinning in the one situation where stopping is correct.

## 4. Blocking contract

Confirmed by the probes: a `Stop` hook blocks by printing to stdout

```json
{"decision": "block", "reason": "…"}
```

and exiting **0**. The `reason` reaches the model and the turn continues.

*Measured 2026-09-05 on Claude Code 2.1.261 (`276a29e`). Not re-measured since.*

## 5. Spend and turn limits

`--max-budget-usd` and `--max-turns` are documented as print-mode flags, and the probes confirm
`--max-turns` binds there. Neither is available to an interactive session, which is why this
framework carries its own ceilings rather than delegating to the platform.

*Measured 2026-09-05 on Claude Code 2.1.261 (`276a29e`). Not re-measured since.*

## 6. Subagent turns are in separate transcripts — and this one bit

The main transcript carries `isSidechain` in its schema, which reads like a promise that subagent
turns are in the same file. **They are not.** A session that spawned three subagents had
`isSidechain: true` on zero rows, and no recent session on this machine had any.

Subagent transcripts live in a sibling directory named after the session:

```text
<project-dir>/<session-id>.jsonl                        the main transcript
<project-dir>/<session-id>/subagents/agent-<id>.jsonl   one per subagent
```

Same row shape — `message.model`, `message.usage`, `timestamp` — so they sum the same way, but a
measurement that reads only `transcript_path` misses them entirely. On the session that produced
this framework the subagents were **17% of the real spend**, and they are the expensive half by
design: delegating review to a costly model is the whole point of routing. A spend ceiling blind to
subagents is a ceiling on the cheap work only.

Two shapes of model id appear, and neither matches a price table written from the docs:

| Where | Example | Trap |
|---|---|---|
| Main session | `claude-opus-5[1m]` | context-window suffix |
| Subagents | `claude-haiku-4-5-20251001` | dated snapshot |

Both must be normalised before a price lookup. An unmatched id falls to whatever default the table
declares — here deliberately the most expensive model, so an unknown id stops a run early rather
than late, but for a *known* model priced as the fallback that is a tenfold error.

*Measured 2026-09-05 on Claude Code 2.1.261 (`276a29e`). Not re-measured since.*

## 7. Project settings in an untrusted directory — EXPIRED on 2.1.289

> **This no longer reproduces.** On **2.1.289** a freshly created directory's project settings fire
> their hooks normally. Verified 2026-10-10 with `scripts/probes/settings-trust.sh` and confirmed
> across four hook events — `SessionStart`, `Stop` and `UserPromptSubmit` all fired where they were
> silent on 2.1.261.
>
> The record below is kept because it was true when measured, and because it is the reason
> `stop-cap.sh` passes its configuration with `--settings`. That remains good practice — it makes a
> probe independent of whatever the trust rules happen to be — but it is no longer a necessity.
>
> **Permission rules are still gated by trust, and 2.1.289 now says so.** An untrusted workspace
> prints `Ignoring 1 permissions.allow entry from .claude/settings.json: this workspace has not been
> trusted`, and names the fix — accept the dialog interactively once, or set
> `projects["<path>"].hasTrustDialogAccepted: true` in `~/.claude.json`. On 2.1.261 the same thing
> happened in silence. So trust has not stopped mattering; it stopped gating *hooks*, and it stopped
> being invisible.
>
> One trap found while confirming this: `PreToolUse` appeared not to fire, which looked like trust
> gating and was not. It simply had no tool call to intercept. Given a prompt that actually runs a
> command, it fires. **A hook that never had its trigger is indistinguishable from a hook that was
> suppressed** — rule out the mundane explanation before recording a platform finding.

### What was true on 2.1.261

A freshly created directory was not a trusted workspace. Its `.claude/settings.json` is **silently
ignored** — no warning, no error, the hook simply never fires and every counter reads zero. The
failure is indistinguishable from "the platform changed its behaviour", which is the expensive part.

Measured on 2.1.261, with an always-blocking `Stop` hook declared in project settings:

| Where the project lived | Hook invocations |
|---|---|
| A fresh `mktemp -d`, hook referenced by absolute path | **0** |
| The same, hook referenced via `$CLAUDE_PROJECT_DIR` | **0** |
| A fresh subdirectory **inside an already-trusted repo** | **0** |
| The session's own scratchpad directory | fires normally |
| Any directory, config passed with `--settings` | fires normally |

The third row is the one worth knowing: **trust is not inherited from an ancestor.** A new directory
under a repo you work in every day is as untrusted as one in `/tmp`. And the second row rules out the
obvious confounder — it is not a variable that fails to expand.

The consequence that outlived the finding: **confirm a hook actually ran before concluding anything
about what it did.** A clean zero is produced by a suppressed hook, a hook with no trigger, and a
broken probe alike, and only one of those is a platform finding.

## 8. How a plugin actually reaches a project

Measured, because the shape that looks obvious is wrong.

| What | Where it lands | Travels with the repo? |
|---|---|---|
| `claude plugin marketplace add <owner/repo>` | **user** settings | no |
| `claude plugin install <p>@<m> --scope project` | the project's `.claude/settings.json`, as `enabledPlugins` | **yes** |

Writing `extraKnownMarketplaces` into a project's `.claude/settings.json` by hand did **not**
register the marketplace — the plugin stayed invisible, with or without `--settings`, so this is not
the untrusted-directory problem from section 7.

Read as a design rather than a limitation, it is the correct split: enabling a known plugin is a
project's business, while trusting a new marketplace is the machine owner's. A repository that could
add a marketplace for you would be a repository that runs arbitrary hooks the moment it is cloned.

Verified afterwards: with `enabledPlugins` committed and the marketplace known, a print-mode session
in that project listed all eight components as `efficiency:*`.

*Measured 2026-09-05 on Claude Code 2.1.261 (`4550b61`). Not re-measured since.*

## 9. Writes into `.claude/` are governed by the permission mode

The finding that decided this framework's layout. It was measured once, under one permission mode,
stated as a blanket refusal — and a later session saw the exact opposite. Both observations were
correct. The variable nobody had controlled for was the mode.

Measured on **2026-10-10**, Claude Code **2.1.296**, by `scripts/probes/dot-claude-writes.sh`: twelve
headless sessions, four permission modes by three tools. Each session was asked to write in two
places — the project root first, then `.claude/` inside it — and the filesystem was read afterwards
rather than the session's own account of what it did. The root write is the control: when it lands
and the `.claude/` write does not, the path is the reason and nothing else can be.

| permission mode | `Write` | `Edit` | `Bash` |
|---|---|---|---|
| `acceptEdits` | refused | refused | refused |
| `dontAsk` | refused | refused | refused |
| `auto` | allowed | allowed | allowed |
| `bypassPermissions` | allowed | allowed | allowed |

Twelve cells, no inconclusive ones: in every cell the control write into the project root succeeded,
so every refusal above is attributable to the path.

**The tool is not the variable.** `Write`, `Edit` and `Bash` behave identically within a mode, which
rules out the obvious explanation that one tool has a path guard the others lack.

**A generic tool allow rule does not lift it.** Every session was run with `--allowedTools` naming
the tool it was using, and the refusals above happened anyway. The earlier measurement additionally
tried project `permissions.allow` rules naming the exact path, in `Write(.claude/…)`, `Edit(.claude/…)`
and absolute-path forms, and none of them lifted it either. A session explained the refusal in its own
words: *"denied as a sensitive file"*.

### What it changes, and what it does not

**The layout stands.** This framework used to keep its run state at `.claude/efficiency.local.md` and
its policy at `.claude/efficiency.md` — files the *model* is expected to write: ticking a task closed,
advancing to the next one, appending to the run log. The autopilot could not even arm itself, because
arming means creating the run file. That had been diagnosed twice as something else — once as a block
reason missing its instructions, once as a model tidying away keys it did not recognise. Both
plausible, both wrong.

Everything the model writes now lives in `.efficiency/` at the project root:

```text
.efficiency/policy.md      committed — tiers, routing, stop_for, declared defaults
.efficiency/run.md         gitignored — the run, its tasks and its log
.efficiency/autopilot.json gitignored — the hook's own counters
```

With that one move, a plain instruction — *"procedi fino a completarli tutti, non fermarti a
chiedermi conferma"* — armed the autopilot, drove four tasks and finished `DONE`. The first complete
run in the project's history, and nothing about the mechanism had changed.

Knowing the refusal is mode-dependent does **not** argue for moving back. A plugin cannot know which
mode a consumer runs in, two of the four refuse, and a layout that works in half of them is a layout
that breaks for half of its users with no diagnostic. `.efficiency/` works in all four.

**What it does change is the advice.** A write into `.claude/` that fails is not a framework defect
and not the model declining: it is the session's permission mode, and the developer can lift it by
choosing another one. That is the difference between "the permission fence could not be installed"
and "re-run this in `auto` mode and it will install" — see `skills/init/SKILL.md`, which now says so.

**The general lesson, restated.** The first version of this section drew a blanket conclusion from a
single uncontrolled cell, and was half wrong for three releases. A tool that writes nothing where you
expected it to is not necessarily disobeying — but neither is one observation a rule. Vary the one
thing you did not think was a variable.

## 10. Enabling a plugin takes two halves, and committing one is not enough

Measured by removing each in turn, in real sessions:

| `enabledPlugins` in a settings file | entry in `installed_plugins.json` | plugin loads? |
|---|---|---|
| yes | yes | **yes** |
| yes | no | no |
| no | yes | no |

The settings file and the registry are both required. Writing `enabledPlugins` by hand — byte-identical
to what `claude plugin install --scope project` produces — does **not** load the plugin; the install
command also records an entry in `~/.claude/plugins/installed_plugins.json`, and that entry is what
makes the difference.

Read as design rather than as a gap, the split is right: a committed setting is the project's
*intent*, and running the install on each machine is that machine's *consent*. A repository able to
enable a hook-running plugin on its own would be a repository that runs code the moment it is cloned.

**Consequence for anyone distributing a plugin:** "commit `enabledPlugins` and your team gets it" is
false. They each run `marketplace add` and `plugin install`. This framework's README claimed the
easier version until it was measured.

*Recorded 2026-10-10 (`22ee95b`). The Claude Code version was not noted at the time, and the
history places the commit between 2.1.289 and 2.1.296 without settling which — so this entry is due
a re-measurement whatever its age, and the date below is when it was written down, not a version it
was checked against.*

## 11. Refreshing a marketplace does not update an installed plugin

The most expensive finding here, because it invalidated three test runs and the conclusions drawn
from them.

```bash
claude plugin marketplace update <marketplace>   # refreshes the catalogue. Your install is untouched.
claude plugin update <plugin>@<marketplace> --scope project   # updates the install.
```

`marketplace update` prints a success message, and the marketplace cache on disk really does move to
the new version — `cat ~/.claude/plugins/marketplaces/<name>/VERSION` shows it. The **installed**
plugin does not move, and nothing says so.

Two more edges:

- `plugin update` defaults to **user** scope. Against a `--scope project` install it fails with
  *"Plugin is not installed at scope user"*, which reads like the plugin is missing rather than like
  a scope mismatch.
- After a successful update it says *"Restart to apply changes"*, and `claude plugin list` keeps
  reporting the old version until then.

### And `plugin list` is harder to read than it looks

It prints **one entry per project install**, and the entries carry no project path:

```text
  ❯ efficiency@claude-efficiency-framework
    Version: 0.1.0          <- a throwaway test project, long deleted
    Scope: project
  ❯ efficiency@claude-efficiency-framework
    Version: 0.3.0          <- the repo you are actually standing in
    Scope: project
```

Reading the first one and stopping cost a wrong conclusion here, twice. The file that disambiguates
is `~/.claude/plugins/installed_plugins.json`, which does record `projectPath` per entry:

```bash
python3 -c "import json;[print(e['version'], e.get('projectPath'))
  for e in json.load(open('$HOME/.claude/plugins/installed_plugins.json'))['plugins'][
    '<plugin>@<marketplace>']]"
```

**Three consecutive runs of this framework executed 0.1.0** while two releases sat in a refreshed
catalogue, and the failures those runs appeared to demonstrate were attributed to the newer code.
Check which version a project is actually on — by path, not by the first line of output — before
believing any test result about a plugin.

*Measured 2026-09-05 on Claude Code 2.1.261 (`fd43dee`). Not re-measured since.*

## 12. The status line — the only continuously visible surface

Measured **2026-10-10** on **2.1.296** with `scripts/probes/statusline.sh`, which installs a
recorder as the project's `statusLine`, logs every invocation, and prints five numbered lines so the
render can be counted by eye.

| Question | Measured |
|---|---|
| How many printed lines are rendered? | **All five.** It is a block, not a line. |
| How often is the command re-run? | Every **0.3–2.5s** — on conversation updates, not once per turn |
| Does a settings change need a restart? | **No.** It is read live, unlike a hook |
| `CLAUDE_PROJECT_DIR` in its environment? | **Set** |
| `CLAUDE_PLUGIN_ROOT` in its environment? | **Not set** |
| Is `$CLAUDE_PROJECT_DIR` expanded inside `command`? | **Yes** — verified with a marker file written by a probe reachable only through the expansion |
| `COLUMNS` / `TERM`? | Both set (`238`, `xterm-256color`) — so width and colour can be decided honestly |
| Working directory | the project root |

Three of those decide the design, and each one would have been guessed wrong:

- **Multi-line is real**, so the backlog can show a count *and* its top entries. A one-line budget
  would have forced the items into a run of separators nobody reads.
- **No `CLAUDE_PLUGIN_ROOT`**, so the command cannot name the plugin — and a plugin's install path
  is not stable enough to hard-code. `hooks/session-start.py` copies `hooks/statusline.py` into
  `.efficiency/statusline.py` instead, the same move the tool inventory made in 0.11.0.
- **Re-run every second or so**, so it must stay one small file read. Anything that shells out, or
  walks a tree, runs hundreds of times an hour on a developer's machine.

The payload is the richest of any surface in this framework. It carries `cost.total_cost_usd` for
the whole session, `rate_limits.five_hour.used_percentage`, `context_window.used_percentage`,
`model.id`, `transcript_path`, `session_id` and `workspace.repo`. None of it is used yet: a status
line that says four things says nothing.

One inconsistency worth knowing: the payload reported `version: 2.1.289` while `claude --version`
said `2.1.296` on the same machine, at the same moment. Do not use the payload's `version` to decide
anything.

## 13. What a PDF costs to read, and when converting it is worth anything

Measured **2026-10-10** on **2.1.296**, Opus 5, with `scripts/probes/pdf-token-cost.sh` — which
builds a five-page document whose last page holds seven lines on an otherwise empty sheet, and then
recovers the cost of each tool result from the session transcript.

| What was read | Result bytes | Tokens | Per page |
|---|---|---|---|
| The PDF, `pages="1-5"` | 1,263,085 | **6,402** | **1,280** |
| The last page alone — seven lines of text | 52,725 | **1,390** | **1,390** |
| The same five pages as text, via `pdftotext` | 15,700 | **5,838** | 1,168 |
| A markdown document, for the prose ratio | 25,265 | 8,240 | 3.07 chars/token |

Three things follow, and the second is the one that was assumed wrong here before it was measured.

- **A page costs what a page costs.** The nearly-empty sheet cost *more* than the average full one.
  Each page is rendered to an image of fixed dimensions, so the bill follows the page count and is
  blind to whether anything is printed on it. A forty-page report of charts and white space costs
  the same as forty pages of solid prose.

- **Converting a dense page to text saves almost nothing — about 9% here.** At roughly 2.7–3.1
  characters per token, the break-even is **3,400–3,900 characters per page**: a page of margin-to-
  margin text is already at the crossing point, and a denser one is genuinely cheaper read as pixels.
  The intuition that converting is a large per-page saving is false, and the framework must not be
  built on it.

- **The saving is in the pages you then do not read.** Converted once, a document is greppable:
  forty pages that would cost ~52,000 tokens to look through become one search and one 40-line
  slice, for a few hundred. That is the real multiple, and it is a property of text being
  addressable, not of text being smaller. It also means the conversion has to happen **once**, to a
  file on disk — a conversion whose output is piped straight into the session has thrown away the
  only part that was worth having.

And the limit worth stating with them: when what matters is the *layout* — a scan, a signature, a
figure whose appearance is the content — the page image is the correct thing to read, and converting
first is strictly worse. Fidelity, not frugality, decides that one.

## 14. A skill is reached by what it does, not by how its description is worded

The framework assumes a developer never has to remember a command name: they say
what they want and the right skill is chosen from its description. That had been
observed once, for one skill, and assumed for the rest.

Measured **2026-10-10** on **2.1.296** with `scripts/probes/skill-auto-invoke.sh`: seven skills, a
plain request in English and in Italian, three trials each, forty-eight headless sessions in a
scaffolded throwaway project with the plugin loaded through `--plugin-dir`. What is read is the
`Skill` tool call the model chose — not what it said it would do. Two negative controls check the
other failure: a description that claims everything interrupts as surely as one that claims nothing.

| skill | English | Italian |
|---|---|---|
| `backlog` | 3/3 | 3/3 |
| `init` | 3/3 | 3/3 |
| `run` | 3/3 | 3/3 |
| `run-report` | 3/3 | 3/3 |
| `plan-run` | 1/3 | 2/3 |
| `fanout` | **0/3** | 2/3 |
| `autopilot` | **0/3** | **0/3** |

Both controls stayed silent in every trial, and no skill was ever chosen in place of another.

**The pattern is not about wording.** All seven descriptions name their trigger phrases verbatim, in
both languages — that was made true at 0.14.0 and the gate enforces it. The four that are reached
every time ask for something the model has no other way to do: file this, set this up, execute the
approved run, report on it. The three that are missed ask for something the model will simply *do*
instead, and the transcripts say so in its own words — it finished the TODO items rather than arming
the autopilot, added the four docstrings one after another rather than fanning out, drafted the plan
rather than invoking the planner.

**So naming the trigger phrases is necessary, not sufficient.** The check added at 0.14.0 catches a
description nobody could ever match; it cannot catch a skill whose task the model would rather
perform than delegate. Nothing measured here says quoted phrases change how often a skill fires.

**The autopilot's 0/6 is not the production number.** In a real session the `UserPromptSubmit` hook
injects a line naming the autopilot outright, and that is what arms it. These sessions had no such
help: measured in every retained transcript, `UserPromptSubmit` never fires under `-p`, and
`SessionStart` runs but emits nothing in a project that has not adopted the framework. The probe
therefore tests a description stripped of every aid — a harder test than production, and the reason
a miss here is not automatically a miss there. It also means the framework's most important skill is
currently carried by a hook rather than by its description.

**Measured on Haiku**, because a probe has to be cheap enough to re-run. `MODEL=sonnet TRIALS=5`
re-measures it against a larger model; whether selection behaves the same there is not known.

*Measured 2026-10-10 on Claude Code 2.1.296. It took four rounds to get an instrument worth
believing: the first scored skills with a reader that crashed on an event shape it did not expect and
returned silence, which read as "never fired"; the second charged descriptions for requests that had
no referent in an empty fixture; the third mistook `--max-turns 3` running out for a decision; the
fourth ran under a permission mode that denied the writes the skills exist to perform. Every change
fixed a defect named in a transcript. None of them was a nudge to make a number look better — which
is the only thing separating a probe from a wish.*

## 15. A run really does route, and what that costs is harder to know than it looks

Model routing is this framework's headline contribution and had never been watched working.
Measured **2026-10-10** on **2.1.296** with `scripts/probes/run-routing.sh`: a scaffolded project,
three tasks across two tiers, a real gate, driven headlessly end to end.

The session delegated, in order:

```text
efficiency:implementer-fast     task 1 — routine, haiku
efficiency:reviewer             task 2 — sensitive, reviewed
efficiency:implementer-fast     task 3 — routine, haiku
```

Three tasks closed, gate green, the run file left honest, and `/efficiency:run-report` opened with
`DONE` and listed each autonomous decision. The claim holds.

### The spend figure from that run is an upper bound, not a cost

The run recorded `task_spend_micro_usd: 1760614` — $1.76, 88% of its $2.00 ceiling, for three
trivial edits. That number is wrong, and the way it was wrong matters more than the number.

The transcripts named `claude-sonnet-5-5`, `claude-haiku-5-5` and `claude-opus-5-5`. **None of the
three was in the cost table**, so all three were priced at the fallback — which is deliberately the
most expensive row, so that an unknown model can never quietly raise a ceiling. Safe for a guard;
backwards for a report. A Haiku subagent charged at top-tier rates reads as roughly five times what
it cost, and the per-model split that `run-report` printed so confidently was three different models
at one wrong price.

The sting is where it lands: the framework's whole argument is that routing cheap work to a cheap
model saves money. Mis-pricing the cheap model as the expensive one erases exactly the saving it
exists to demonstrate. `CLAUDE.md` already names this failure — dated ids priced as the fallback —
as one of the two worst bugs found in this project. It came back, because the table knew nothing of
the 5-5 generation, and `scripts/qa.sh` could not see it: the table was internally consistent and
recently dated, which is all the gate ever checked.

Two things changed as a result. `claude-opus-5-5` and `claude-sonnet-5-5` are now priced. And the
fallback is no longer silent — `hooks/lib/spend.py` returns the ids it could not price, the hook
writes them to `task_spend_unpriced_models`, and `skills/run-report/SKILL.md` requires the report to
say so before showing any table.

`claude-haiku-5-5` was left unpriced at the time, because the pricing source this repo was reading
did not list it, and inventing a number to make a figure look finished is the thing this document
exists to prevent. It is priced now — section 16, which also measured why nothing here could have
noticed.

*Measured 2026-10-10 on Claude Code 2.1.296. The first attempt measured nothing: the run file was
hand-written without `task_spend_max_micro_usd`, so `spend_max` seeded to 0 and the entire spend
guard — including its fail-closed branch — never executed. A run file missing its ceilings has no
ceilings, silently, and the symptom surfaces minutes later and somewhere else.*

## 16. `haiku`, `sonnet` and `opus` are not model ids, and nobody was checking what they meant

Measured **2026-10-10** on **2.1.296** with `scripts/probes/model-ids.sh`: one near-empty session per
alias, reading the resolved id out of the `init` event that opens a `--output-format stream-json`
session.

| alias | resolves to | in the cost table before this |
|---|---|---|
| `haiku` | `claude-haiku-5-5` | no |
| `sonnet` | `claude-sonnet-5-5` | yes, added the day before |
| `opus` | `claude-opus-5-5` | yes, added the day before |

The framework routes by **alias** — `model: haiku` in an agent, `implement: sonnet` in a policy — and
never names an id. `hooks/lib/spend.py` prices **ids**. Claude Code decides, at session start, which
id an alias means, and that decision is invisible from inside this repo: nothing in the plugin
changes on the day `haiku` starts meaning a new generation. Section 15 is what that looks like when
it goes wrong — three models, one wrong price, a green gate throughout.

The gate was green because it was asking the table about itself: internally consistent, recently
dated, default present. Every one of those can be true of a table that holds none of the models in
use. `scripts/lib/check-priced-models.py` asks the other question — reading the aliases out of
`agents/*.md` and `templates/efficiency.md` so a new agent is covered the day it lands, and requiring
each to resolve to an id the table prices. Resolving an alias costs money and needs the network, so
that half stays a probe; the mapping it measures is recorded in `hooks/lib/model-costs.json` under
`resolved`, beside the prices it selects, and the gate holds the two ends together for free.

### One model is no longer one price

Claude Haiku 5.5 is priced by prompt length: over 100,000 prompt tokens it costs about five times as
much, on every line of the bill, and each request is priced on its own. The table held one rate card
per model, so it could only have been wrong in one direction or the other — and `haiku` is precisely
where the framework sends work it is recommending as cheap.

A model may now carry a second card under `long_prompt`, and the meter picks per message. The
threshold counts **every input token of the request, cache reads and cache writes included**, which
is what the pricing page specifies and is not the same as `input_tokens`: on a Claude Code turn
`input_tokens` is usually a handful and the rest of the prompt arrives as a cache read. Reading only
`input_tokens` would price a 400k-token turn at the small-prompt rate and under-report it fivefold —
the direction a ceiling must never be wrong in. Both halves have a selftest case, and both cases were
watched failing with the guard removed.

### What re-checking the rest of the table turned up

Verifying the other twelve rows against the pricing page found two wrong cache-read prices:
`claude-mythos-5-1` at $1.00 where it is $0.25, and `claude-sonnet-5-5` at $0.20 where it is $0.10.
Both had been written as 0.1× input, which is the usual ratio and is wrong for those two models.

That class of error is structurally invisible to this repo's gate, and the fix is to say so rather
than to pretend otherwise. The cache-write ratios are checkable because they are fixed multiples of
input — 1.25× and 2× — so a drifted number contradicts the table itself. Cache reads have no single
ratio: 0.1× on most models, 0.05× on Opus 5.5 and Sonnet 5.5, 0.025× on Fable 5.1 and Mythos 5.1. A
wrong cache-read price is perfectly self-consistent. Nothing short of re-reading the pricing page
catches it, which is what the `verified` date and its 90-day staleness warning exist to force.

*Measured 2026-10-10 on Claude Code 2.1.296. Prices verified the same day against
`platform.claude.com/docs/en/about-claude/pricing`.*

## Re-running these measurements

```bash
bash scripts/probes/stop-cap.sh stall 40   # expect ~9 invocations, platform cap
bash scripts/probes/stop-cap.sh read  12   # expect 6, bound by --max-turns, cap never fires
bash scripts/probes/stop-cap.sh write 12   # expect 6, same
bash scripts/probes/transcript-shape.sh <path-to-transcript.jsonl>  # show subagents directory and usage keys present
bash scripts/probes/model-ids.sh           # which id each routing alias resolves to, and whether it is priced
bash scripts/probes/statusline.sh install   # then start a session, look at the bottom, and `show`
bash scripts/probes/pdf-token-cost.sh make # build the test PDF; read it in a session, then `measure <transcript>`
```

The probes print verdicts rather than raw numbers to interpret. `stop-cap.sh` says loudly when the hook
never fired at all — because that failure is most likely to be misread as a platform change.
`transcript-shape.sh` verifies that subagent transcripts are where they should be and shows which usage
keys appear in actual spend data.
