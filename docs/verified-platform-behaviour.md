# Verified platform behaviour

Every claim here was **measured on this machine**, not read in documentation. Each entry carries the
date, the Claude Code version, and the method, so it can be re-run when a release moves the ground.

Re-measure before trusting any of it after a Claude Code upgrade. The probes live in
`scripts/probes/` and take a couple of minutes and a few cents of Haiku.

First measured: **2026-09-05** · Claude Code **2.1.261** · macOS 23.3.0
Re-measured: **2026-10-10** · Claude Code **2.1.289** — § 3 unchanged, § 7 **expired**, § 9 corrected.
Added: **2026-10-10** · Claude Code **2.1.296** — § 12, the status line.
§ 9 may have expired too; see the note under it.

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

## 5. Spend and turn limits

`--max-budget-usd` and `--max-turns` are documented as print-mode flags, and the probes confirm
`--max-turns` binds there. Neither is available to an interactive session, which is why this
framework carries its own ceilings rather than delegating to the platform.

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

## 9. Claude Code refuses to write into `.claude/`

The finding that decided this framework's layout, and it was invisible for three releases.

Measured on 2.1.289 under `--permission-mode acceptEdits`, four writes in one session:

| Write | Result |
|---|---|
| Edit an existing file **inside** `.claude/` | **denied** |
| Create a new file **inside** `.claude/` | **denied** |
| Edit an existing file one directory up | succeeded |
| Create a new file one directory up | succeeded |

Denied across tools: `Write`, `Edit` and `Bash` alike. Project `permissions.allow` rules naming the
exact path did not lift it — `Write(.claude/…)`, `Edit(.claude/…)` and an absolute-path form were all
tried. A session explained the refusal in its own words: *"denied as a sensitive file"*.

**Why it mattered here.** This framework kept its run state at `.claude/efficiency.local.md` and its
policy at `.claude/efficiency.md`. Both are files the *model* is expected to write: ticking a task
closed, advancing to the next one, appending to the run log, and adding a declared default it had to
invent. None of that could happen. The autopilot could not even arm itself, because arming means
creating the run file.

That had been diagnosed twice as something else — once as a block reason missing its instructions,
once as a model tidying away keys it did not recognise. Both plausible, both wrong.

Everything the model writes now lives in `.efficiency/` at the project root:

```text
.efficiency/policy.md      committed — tiers, routing, stop_for, declared defaults
.efficiency/run.md         gitignored — the run, its tasks and its log
.efficiency/autopilot.json gitignored — the hook's own counters
```

With that one move, a plain instruction — *"procedi fino a completarli tutti, non fermarti a
chiedermi conferma"* — armed the autopilot, drove four tasks and finished `DONE`. The first complete
run in the project's history, and nothing about the mechanism had changed.

**The general lesson:** a tool that writes nothing where you expected it to is not necessarily
disobeying. Check whether it is allowed to write there at all, before concluding anything about its
judgement.

### Possibly no longer true on 2.1.296 — UNVERIFIED

On **2026-10-10**, while building the status line, a session on 2.1.296 wrote `.claude/settings.json`
through `Bash` repeatedly, and created and deleted a new file inside `.claude/`, without a single
refusal. That is the opposite of the table above.

It is recorded here as an **anomaly, not a correction**: it was one session, in one permission mode
(this machine's "auto" mode, not the `acceptEdits` the table was measured under), and the table's
claim was load-bearing enough that replacing it on a single uncontrolled observation would be
exactly the folklore this document exists to prevent. There is no probe for § 9 yet — writing one,
across the permission modes, is in the backlog.

Until then, assume the refusal still happens: the framework's layout survives either way, and a skill
that *tries* the write and prints the snippet when it fails is correct under both.

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

## Re-running these measurements

```bash
bash scripts/probes/stop-cap.sh stall 40   # expect ~9 invocations, platform cap
bash scripts/probes/stop-cap.sh read  12   # expect 6, bound by --max-turns, cap never fires
bash scripts/probes/stop-cap.sh write 12   # expect 6, same
bash scripts/probes/transcript-shape.sh <path-to-transcript.jsonl>  # show subagents directory and usage keys present
bash scripts/probes/statusline.sh install   # then start a session, look at the bottom, and `show`
bash scripts/probes/pdf-token-cost.sh make # build the test PDF; read it in a session, then `measure <transcript>`
```

The probes print verdicts rather than raw numbers to interpret. `stop-cap.sh` says loudly when the hook
never fired at all — because that failure is most likely to be misread as a platform change.
`transcript-shape.sh` verifies that subagent transcripts are where they should be and shows which usage
keys appear in actual spend data.
