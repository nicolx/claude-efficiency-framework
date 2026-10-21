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
Added: **2026-10-11** · Claude Code **2.1.296** — § 17, stopping a turn from the inside.
Re-measured: **2026-10-11** · Claude Code **2.1.296** — § 2 **re-run against the real autopilot** and
extended, § 3 row A2 and § 4 confirmed. The probe the original measurement never committed now exists.
Re-measured: **2026-10-18** · Claude Code **2.1.302** — every headless probe re-run with the developer's
`~/.claude/settings.json` shut out by `--setting-sources project,local`, which until then had reached
every session but two. §§ 2, 3, 7, 15, 16, 17 unchanged; § 9 two `Bash` cells moved; § 14 re-measured;
§ 19 added, the first run of `efficiency:fanout`. Later the same day §§ 1, 4 and 5 were re-run, as
the first version-keyed staleness check asked: unchanged, except a new `effort` key in the `Stop`
payload. § 20 added: where fanning out starts to save wall time.
Added: **2026-10-21** · Claude Code **2.1.305** — § 21, a hook granting a permission.
Added: **2026-10-21** · Claude Code **2.1.306** — § 22, a hook asking a second model for a verdict.
Added: **2026-10-21** · Claude Code **2.1.306** — § 23, checkpoints end to end.
Added: **2026-10-21** · Claude Code **2.1.306** — § 24, the dialogue language.

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
  "session_crons": [],
  "effort": "…"
}
```

**`transcript_path` is present.** The official hook reference does not list it for `Stop`, but it
arrives. This is what makes per-task spend measurement possible without any API call.

`last_assistant_message`, `prompt_id`, `background_tasks` and `session_crons` are also undocumented
for this event.

*Measured 2026-09-05 on Claude Code 2.1.261 (`276a29e`). Re-measured 2026-10-18 on 2.1.302 by
`scripts/probes/stop-cap.sh`, which now prints the keys of the first payload it receives: every key
above is still there, `transcript_path` included, and one has been added — `effort`.*

*Re-measured 2026-10-19 on 2.1.303 by `scripts/probes/stop-cap.sh`, all five runs: the same eleven
keys, `transcript_path` and `effort` included. Unchanged.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/stop-cap.sh`

## 2. `stop_hook_active`, and whether a project's own Stop hook coexists

`false` on the first invocation of a turn chain, `true` on every one after it. It marks "a Stop hook
has already blocked in this chain", and it is shared across all registered `Stop` hooks — it is not
per-hook state. With two hooks registered, both read the identical series, invocation for
invocation: `False,True,True,True,True,True,True,True,True`.

**But sharing the flag does not mean the hooks interfere.** Measured with two hooks registered on
the same event, both always blocking: each was invoked on every single turn, and neither was skipped
because the other had already blocked. The flag is information, not a lock. A hook that treats
`stop_hook_active: true` as "stand down" disables itself as soon as any other Stop hook exists —
which is why this framework's autopilot deliberately ignores it and bounds itself with counters it
owns instead.

**Re-measured against the real autopilot, not two stand-ins.** The September run registered two
identical always-blocking hooks, which proves the platform's behaviour and nothing about this
framework's. The 2026-10-11 run drives the *shipped* `autopilot-stop.py` against an unfinishable run
with a project quality-gate hook blocking beside it on every turn:

| | measured |
|---|---|
| invocations, autopilot / neighbour | **10 / 10**, in lockstep |
| guard 4 stopped the run at | **block 6** — the same number as with no neighbour (§ 3) |
| `continuations_used` in `.efficiency/autopilot.json` | 1, 2, 3, 4, 5 — **once per turn, not twice** |

The private-state rewrite did not change the picture. That third row is the one the rewrite put in
question: the counters moved out of the run file, and a neighbour invoking the Stop event alongside
us could plausibly have double-counted the budget. It does not.

**Both reasons reach the model, and both are acted on.** The neighbour's block reason asks for one
observable act. It was carried out on 9 of the 10 turns — while the run went on being worked, and
while guard 4 counted to exactly 5. A competing instruction from a project's own hook does not
displace the autopilot's, which matters because the block reason is the only instruction the model
reliably reads on a continuation.

**But stopping a run does not end a session.** After guard 4 stopped the run at block 6 the autopilot
stood down — `status: BLOCKED`, counter frozen at 5, no further blocks from it — and the session
carried on for four more turns, because the neighbour was still blocking. It ended on `--max-turns`,
**not** on the platform's cap: the model made a tool call each turn carrying out the neighbour's
instruction, and any tool call resets the cap's counter (§ 3). In an adopting project that is the
neighbour's loop to break and not the autopilot's — a hook cannot un-block another hook, and trying
would be the wedging that rule 2 forbids — but it is worth knowing that `status: BLOCKED` in the run
file does not mean the session has stopped. The developer does get the stop reason, so the tail is
not silent; it is simply not bounded by anything of ours. The whole 25-turn session cost $0.0141,
which is the only reason this is a note rather than a defect.

*Measured 2026-09-05 on Claude Code 2.1.261 (`276a29e`), extended the same day by the two-hook
coexistence run in `dfa61e0` — which committed no probe, so for five weeks the claim could not be
re-derived. Re-measured 2026-10-11 on Claude Code 2.1.296 by
`bash scripts/probes/stop-coexistence.sh`, which is that missing probe: `cap` mode reproduces the
September figure of 9 invocations each, `autopilot` mode is the table above, run twice with identical
numbers.*

*Re-measured 2026-10-18 on Claude Code 2.1.302 by `scripts/probes/stop-coexistence.sh both`, with
every session isolated by `--setting-sources project,local`: 9 invocations each in cap mode, guard 4
at block 6 beside a blocking project gate. Unchanged.*

*Re-measured 2026-10-19 on 2.1.303 by `scripts/probes/stop-coexistence.sh both`: 9 invocations each
in cap mode, the same `False,True,…` series for both hooks; guard 4 at block 6 beside the blocking
gate, `continuations_used` 1 to 5 once per turn, 11 invocations each in lockstep, and the session
ended on `--max-turns` at 25 turns for $0.013. Unchanged.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/stop-coexistence.sh`

## 3. The block cap — and the condition that governs it

This is the finding that decides how much autonomy is actually available, and the documented
"8 consecutive blocks" is only half of the story.

| Probe | What the model did between blocks | Hook invocations | What stopped it |
|---|---|---|---|
| A | Replied with text only, no tool calls | **9** | the platform cap |
| A2 | Same, but with **two** blocking hooks registered | **9 each** | the platform cap, shared |
| A2' | A2 re-run on 2.1.296, 2026-10-11 | **9 each** | unchanged |
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
without dividing the budget between them. **Re-measured 2026-10-11 on 2.1.296 and unchanged** — by
`scripts/probes/stop-coexistence.sh`, which is also where the coexistence evidence now lives (§ 2).
Until that date row A2 rested on an uncommitted September run while sitting under this section's
2026-10-10 provenance line, which covered the stall and read modes only.

**Consequence for this framework.** The platform will not cut a working autopilot short, so the
limits that matter are our own — the per-task spend ceiling, the gate retry limit, and the
continuation budget. `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` exists but should be left alone: raising it
only buys more spinning in the one situation where stopping is correct.

### Which anti-stall guard fires first

Both mechanisms watch the same event and neither knows about the other, so only the one that fires
first produces a reason anybody reads — the platform's override is silent.

| | fires at | the developer is told |
|---|---|---|
| this framework's guard 4 (`STALL_STOP = 5`) | **block 6** | the run file's `blocked_reason`, naming the open tasks |
| the platform's cap | block 9, overriding the 8th block | nothing |

Measured twice, because the two halves cannot be measured the same way. Offline, `hooks/selftest.py`
drives the hook as a subprocess and asserts the block number rather than just the outcome. Live,
`scripts/probes/stall-ordering.sh` runs the *shipped* hook against a Haiku session on a run that
cannot be finished — its one task reads a file that does not exist — and the run stopped at block 6
with the framework's reason, matching the offline number exactly.

**Two blocks of margin, and they are the whole point.** Raise `STALL_STOP` past 7 and a stalled run
still stops, but the platform gets there first and stops it without saying why.

**The margin was measured with one hook registered, and it survives a second.** If the cap ever
started counting blocks rather than turns, a project's own Stop hook blocking alongside the autopilot
would halve the margin and the platform would stop the run first, silently. It does not: with a
neighbour blocking on every turn, guard 4 still fires at block 6 (§ 2).

**The margin only holds if the counter cannot be reset by the model.** Until 0.18.1 guard 4 also
required `current_task` to have stayed put — a field the model writes, and which the block reason
explicitly tells it to write when a task is done. A model moving it *without* closing anything reset
the guard on every block: measured at 12 blocks and still going, bounded only by `continuations_max`
at 40. Progress is now a task closing and nothing else.

The same lever reached further than guard 4. Until 0.18.2 the **per-task spend window** also reopened
on `current_task`, so the same alternation bought a fresh ceiling on every block — the one guard that
is deliberately fail-closed, reset by the field the block reason asks the model to rewrite. Both now
key off the same signature of the open-task set, computed once. Offline: the run below spends $0.50 a
block against a $1.20 ceiling while flipping `current_task`, and stops on the third block rather than
never.

*Measured 2026-10-10 on Claude Code 2.1.296. Offline half: `python3 hooks/autopilot-stop.py
--selftest`. Live half: `bash scripts/probes/stall-ordering.sh`.*

*Re-measured 2026-10-18 on Claude Code 2.1.302, with every session isolated by `--setting-sources
project,local`: `stop-cap.sh` 9 / 6 / 6 in stall, read and write modes, `stall-ordering.sh` stopped
by the framework at block 6. Unchanged. Run again the same afternoon, `stall` gave 16 once and then 9
three times in a row. The probe keeps no transcript, so the 16 is unexplained; one tool call in the
middle of the run would reset the counter and produce exactly that shape, but nothing recorded that.*

*Re-measured 2026-10-19 on Claude Code 2.1.303: `stop-cap.sh` 6 / 6 in read and write modes,
`stall-ordering.sh` stopped by the framework at block 6, `stop-coexistence.sh` 9 each with two
hooks. Unchanged. `stall` gave 16 once more, then 9 twice — and this time the session's transcript was
still in `~/.claude/projects`, where the probe's own temporary directory does not reach, so the 16 is
explained: after the seventh block Haiku called `Read` on the probe's hook script to see why it kept
being blocked, and nine more invocations followed. 7 + 9 = 16, the cap counter reset by one tool call
exactly as the table above says. The 16 of 2026-10-18 is almost certainly the same shape. It is a
finding about the model, not the platform: a stalled model sometimes investigates its leash, and that
investigation is progress as far as the cap can tell.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/stop-cap.sh`
`scripts/probes/stall-ordering.sh` `scripts/probes/stop-coexistence.sh`

## 4. Blocking contract

Confirmed by the probes: a `Stop` hook blocks by printing to stdout

```json
{"decision": "block", "reason": "…"}
```

and exiting **0**. The `reason` reaches the model and the turn continues.

*Measured 2026-09-05 on Claude Code 2.1.261 (`276a29e`). Still true on 2.1.296 (2026-10-11): both
hooks in `scripts/probes/stop-coexistence.sh` block through this contract, and the neighbour's reason
was demonstrably acted on — which is the only way to show the reason arrived, rather than assuming
it from the turn continuing.*

*Re-measured 2026-10-18 on 2.1.302 by `scripts/probes/stop-coexistence.sh both`: the neighbouring
hook's reason was obeyed on all 10 turns it blocked, beside the autopilot's own.*

*Re-measured 2026-10-19 on 2.1.303 by the same probe: both hooks blocked through this contract, and
the neighbour's reason was obeyed on 10 of the 11 turns it blocked. Unchanged.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/stop-coexistence.sh`

## 5. Spend and turn limits

`--max-budget-usd` and `--max-turns` are documented as print-mode flags, and the probes confirm
`--max-turns` binds there. Neither is available to an interactive session, which is why this
framework carries its own ceilings rather than delegating to the platform.

*Measured 2026-09-05 on Claude Code 2.1.261 (`276a29e`). Re-measured 2026-10-18 on 2.1.302 by
`scripts/probes/stop-cap.sh read 12` and `write 12`: both ended on `--max-turns` at 6 invocations.
`--max-budget-usd` is passed by every probe and was not exercised to its limit.*

*Re-measured 2026-10-19 on 2.1.303 by the same two runs: both ended on `--max-turns` at 6
invocations. Unchanged.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/stop-cap.sh`

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

*Measured 2026-09-05 on Claude Code 2.1.261 (`276a29e`), manually on a real session with subagents.
The sibling `subagents/` directory was seen again on 2026-10-18 on 2.1.302 by the `--live` run
below; `isSidechain` and the two id shapes were not re-checked.*

### One row per content block, not one per message

A transcript does not write one row per assistant message. It writes one row per **content block**
— a thinking block, a text block and two tool calls are four rows — and every row carries the whole
message's `usage`. The rows share `message.id`, and `requestId` with it. Summed row by row, which is
what `hooks/lib/spend.py` did until this was found, every message is charged once per block.

| Session | Rows with usage | Messages | Rows summed | Per message | `total_cost_usd` |
|---|---|---|---|---|---|
| `--live` probe, Haiku, one subagent | 10 | 6 | $0.0090 | $0.0050 | $0.0050 |
| `--live` probe, Haiku, no subagent | 5 | 2 | $0.0075 | $0.0029 | $0.0029 |
| a 12-subagent fan-out session | 114 | 50 | $0.8899 | $0.2241 | $0.22 |

Across a dozen other sessions on this machine the row sum ran 1.3x to 4.0x the per-message figure —
higher the more blocks a message has, so higher on tool-heavy and thinking-heavy work.

The rows of one message do not all say the same thing, and which one is kept matters:

- **input and cache fields** (`input_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`, `cache_creation`) were identical on every row of every message;
- **`output_tokens`** was identical across a main session's rows, but in a **subagent** transcript it
  grows as the message streams — 3, 3, then 3,513 on one message — and `iterations` and
  `server_tool_use` appear only on the last row.

So `spend.py` keeps, per message, the row with the largest `output_tokens`. Keeping the first would
have undercounted subagent output, the direction a ceiling must never err in. A row with neither id
is still counted on its own.

*Measured 2026-10-18 on Claude Code 2.1.302 (`claude --version`): `transcript-shape.sh` on existing
transcripts for the row shape, and `transcript-shape.sh --live` for the comparison with the
session's own `total_cost_usd`, the only figure here not computed from the transcript.*

*Note, 2026-10-18 — figures recorded before this fix came from the row sum.* Absolute dollar figures
measured by `spend.py` before this fix are inflated by roughly 1.3–4x; the per-task figure in § 15
($1.76 for three trivial edits) is one of them, on top of the fallback pricing that section already
explains. **Shares** of spend move much less, because both halves of a session are inflated by
similar factors: on the surviving transcript of the three-subagent session this section was written
from, the subagent share is 4.9% summed by row and 4.7% by message, up to the end of 2026-09-05. The
17% above could not be re-derived from that transcript under today's price table by either method;
it is left as recorded.

*Re-measured 2026-10-19 on 2.1.303 by `transcript-shape.sh --live`: the subagent transcript is in the
sibling `subagents/` directory; 9 rows with usage made 5 messages, input and cache usage identical
across each message's rows; every row summed $0.0105, `spend.py` per message $0.0047, against a
`total_cost_usd` of $0.0047 — 2.24x and 1.00x. Unchanged. No message in this short run had
`output_tokens` differing between its rows, so the streaming-subagent case was not exercised again.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/transcript-shape.sh`

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

*Re-measured 2026-10-18 on Claude Code 2.1.302 by `scripts/probes/settings-trust.sh`, with every
session isolated by `--setting-sources project,local`: a fresh directory's project hook fires, as
does the same hook through `--settings`. The expiry stands.*

*Re-measured 2026-10-19 on 2.1.303 by the same probe: both hooks fired. The expiry stands.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/settings-trust.sh`

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

Verified: 2026-09-05 · Claude Code 2.1.261 · manual

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

**Re-measured 2026-10-18 on 2.1.302**, with the developer's settings shut out by
`--setting-sources project,local`. `Write` and `Edit` are unchanged in all four modes. Two `Bash` cells
moved, and both moved at the control, not at the path:

- **`dontAsk` · `Bash`:** nothing written anywhere, in 3 of 3 sessions with and without the flag.
  The mode now refuses the tool outright even though `--allowedTools` names it — a refusal of `Bash`,
  which says nothing about `.claude/`.
- **`auto` · `Bash`:** wrote both places in 1 session of 6, and nowhere in the other five; the
  auto-mode classifier declined the command before the path came into it. The one that wrote ran with
  the developer's own settings, but so did one that did not, so the flag is not shown to be the cause.

Neither touches what the layout rests on: `Write` and `Edit` into `.claude/` are refused under
`acceptEdits` and `dontAsk`, and allowed under `auto` and `bypassPermissions`.

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

*Re-measured 2026-10-19 on Claude Code 2.1.303 by `scripts/probes/dot-claude-writes.sh`, run twice.
`Write` and `Edit` are unchanged in all four modes, in both runs: refused into `.claude/` under
`acceptEdits` and `dontAsk`, allowed under `auto` and `bypassPermissions`, the root control landing
every time. `acceptEdits` · `Bash` and `bypassPermissions` · `Bash` are unchanged too. `auto` · `Bash`
wrote nothing in either run, the classifier declining the command, as on 2.1.302.*

**One cell moved, and it is one the layout does not rest on.** `dontAsk` · `Bash` wrote both
places in one run of two — `.claude/` included — where 2.1.296 refused `.claude/` with the root
landing and 2.1.302 refused the tool outright in 3 of 3. The transcripts kept in
`~/.claude/projects` show what differed between the two runs: the session that wrote opened its
command with `cd "<project>" || exit 1` and was let through; the one that did not chained
`printf … > file && echo …` and was refused with "denied because Claude Code is running in don't
ask mode", `--allowedTools Bash` notwithstanding. So under `dontAsk` on 2.1.303 whether `Bash` runs
at all appears to depend on the command, and when it runs a shell redirect into `.claude/` is not
stopped. One observation, recorded as such. It does not weaken the layout: on 2.1.303 the
`.claude/` refusal is shown only for `Write` and `Edit`, and a layout that depended on a model
choosing `Bash` would depend on the shape of a command.

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/dot-claude-writes.sh`

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

Verified: 2026-10-10 · Claude Code unknown · manual

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

Verified: 2026-09-05 · Claude Code 2.1.261 · manual

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
`model.id`, `transcript_path`, `session_id` and `workspace.repo`. Since 0.20.0 the first line of
the status line uses the model, context, cost, duration and five-hour fields — because a project's
`statusLine` overrides the developer's own, and a backlog-only bar took their context gauge away.

One inconsistency worth knowing: the payload reported `version: 2.1.289` while `claude --version`
said `2.1.296` on the same machine, at the same moment. Do not use the payload's `version` to decide
anything.

Verified: 2026-10-10 · Claude Code 2.1.296 · manual (`scripts/probes/statusline.sh` needs an
interactive session)

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

Verified: 2026-10-10 · Claude Code 2.1.296 · manual (`scripts/probes/pdf-token-cost.sh` needs a
session to read the PDF)

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

### Re-measured 2026-10-18 on 2.1.302, with and without the developer's settings

The table above was taken with the author's `~/.claude/settings.json` reaching every session — a
personal output style among it. Re-run the same day on the same version in two arms: isolated by
`--setting-sources project,local`, as the probe now always is, and with the settings let back in.
Six trials per cell in each arm. Only the three skills that were not 3/3 are shown; the other four
and both controls did not move.

| skill | isolated en · it | with user settings en · it | together |
|---|---|---|---|
| `autopilot` | 0/6 · 3/6 | 1/6 · 0/6 | 3/12 against 1/12 |
| `fanout` | 2/6 · 6/6 | 0/6 · 5/6 | 8/12 against 5/12 |
| `plan-run` | 6/6 · 4/6 | 4/6 · 3/6 | 10/12 against 7/12 |

**The arm with user settings reproduces the October table; the isolated arm is higher on all three.**
21/36 against 13/36, every skill moving the same way. That is a consistent direction, not a proof:
each cell alone is within what six trials can do by chance. What it does establish is that the
October numbers were a measurement of one configured machine as much as of the descriptions, and
that the three "unreachable" skills are less unreachable than they looked. The pattern above —
reached by what they do, missed when the model would rather do the task itself — survives:
the autopilot in English is still 0/6 isolated.

**A headless session can outlive `--max-turns`.** One `run` trial launched its reviewer in the
background and called `ScheduleWakeup` to wait for it, then scheduled another wakeup thirty minutes
out. Under `-p` the process stays alive until a scheduled wakeup fires, so the probe sat behind that
one session until it was killed. `--max-turns` bounds turns, not wall-clock time. The probe now
withholds `ScheduleWakeup` and `CronCreate`.

### Decided 2026-10-18: an honest limit, not a wording problem

The three misses are left as they are, each for its own reason, and no description is reworded to
chase them — the table above is the evidence that wording is not what moves them.

- **`fanout`** missing a plain request is the behaviour it asks for. It spends money and enlarges
  the diff, and its description says never to start one unasked. A skill that fired whenever the
  model saw four similar edits would be the defect.
- **`plan-run`** at 10/12 isolated is reached often enough, and the one place it is missed — the
  model drafts the plan itself — still produces a plan for the developer to read.
- **`autopilot`** is carried by the `UserPromptSubmit` hook, and that is the design, not a
  stopgap. Arming it is the one action whose absence costs the developer a run, so it is not left
  to a description the model can reasonably decline: the hook names it on every prompt in an
  adopting project. What this section does not measure is that hook — under `-p` it never fires.

**Measured on Haiku**, because a probe has to be cheap enough to re-run. `MODEL=sonnet TRIALS=5`
re-measures it against a larger model; whether selection behaves the same there is not known.

*Measured 2026-10-10 on Claude Code 2.1.296. It took four rounds to get an instrument worth
believing: the first scored skills with a reader that crashed on an event shape it did not expect and
returned silence, which read as "never fired"; the second charged descriptions for requests that had
no referent in an empty fixture; the third mistook `--max-turns 3` running out for a decision; the
fourth ran under a permission mode that denied the writes the skills exist to perform. Every change
fixed a defect named in a transcript. None of them was a nudge to make a number look better — which
is the only thing separating a probe from a wish.*

*Re-measured 2026-10-19 on Claude Code 2.1.303 by `scripts/probes/skill-auto-invoke.sh`, isolated,
three trials per cell: `backlog`, `init`, `run`, `run-report` 3/3 in both languages and both controls
silent, as before. `plan-run` 3/3 · 3/3, `fanout` 0/3 · 3/3, `autopilot` 0/3 · 2/3 — the same shape as
the isolated arm of 2026-10-18, English the language that misses, and no skill chosen in place of
another. The first-trial transcripts say what they said before: the model did the TODO list itself and
added the four docstrings itself. Unchanged; the decision above stands.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/skill-auto-invoke.sh`

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

*Re-measured 2026-10-18 on Claude Code 2.1.302 by `scripts/probes/run-routing.sh`, with every
session isolated by `--setting-sources project,local`: implementer-fast, reviewer, implementer-fast,
three tasks closed, gate green. Unchanged.*

*Note, 2026-10-18: the $1.76 was also summed row by row, and a transcript writes one row per content
block (§ 6), so it is inflated a second time, by roughly 1.3–4x, independently of the pricing. The
routing claim is unaffected; the dollar figure was never a cost.*

*Re-measured 2026-10-19 on Claude Code 2.1.303 by `scripts/probes/run-routing.sh`: implementer-fast,
reviewer, implementer-fast, three tasks closed, gate green, and the fresh report session opened with
its verdict and spend by model, no unpriced model flagged. Unchanged.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/run-routing.sh`

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

### A measured mapping expires on a release, not on a date

The mapping above is true of **2.1.296**. What makes it false is an upgrade, and the first version of
the gate aged it on a 90-day calendar — so an upgrade that moved what `haiku` means would have left
the gate green for up to three months while every run that routed there was measured at the fallback
rate. The clock was attached to the wrong thing.

`claude --version` is a local subprocess: free, no session, no network. The gate now compares it with
`resolved.claude_code_version` and reports the mapping as **unverified** when they differ, which is
the honest reading — a release *can* move an alias, and nobody has looked since. It is amber rather
than red, because red on every upgrade is a gate people learn to skip. The calendar stays behind it,
for a mapping that moves server-side under a client that never did.

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

*Re-measured 2026-10-18 on Claude Code 2.1.302 by `scripts/probes/model-ids.sh`, with every session
isolated by `--setting-sources project,local`: the same three ids, all priced. `resolved` in the
cost table still records 2.1.296, so the gate reports the mapping unverified until it is updated —
that is a change to a shipped file and waits for the next release.*

*Re-measured 2026-10-19 on Claude Code 2.1.303 by `scripts/probes/model-ids.sh`: the same three ids,
all priced. `resolved` in the cost table updated to 2.1.303; no alias moved.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/model-ids.sh`

## 17. A turn can be stopped from the inside, and its spend can be read while it runs

Measured **2026-10-11** on **2.1.296**, with three probes written for this question:
`scripts/probes/midturn-transcript.sh`, `midturn-deny.sh` and `midturn-subagent.sh`.

Until this was measured the spend ceiling was read exactly once per turn, as the turn ended, because
`Stop` was the only event this framework knew it could refuse from. A turn has no length limit, so
the ceiling was absent for precisely the interval in which it can be exceeded. Three facts had to
hold before a mid-turn guard was worth writing, and none of them is documented.

### The transcript is written as the turn runs

A `PostToolUse` hook counted the transcript on every tool call of a single turn that made three:

| when | rows | rows with `message.usage` |
|---|---|---|
| after tool call 1 | 18 | 0 |
| after tool call 2 | 26 | 1 |
| after tool call 3 | 32 | 2 |
| at `Stop` | 36 | 3 |

So spend **is** measurable mid-turn — `hooks/lib/spend.py` needs nothing it does not already have.
`transcript_path` arrives on `PostToolUse` and on `PreToolUse`, undocumented for both, exactly as it
is for `Stop` (§ 1).

The lag is the part worth writing down: a reading taken during tool call *n* sees the usage of
assistant message *n-1*. The message that issued the call being refused has not been written yet. A
mid-turn ceiling therefore always trails reality by one assistant message, and can only ever be a
little late — never early, which is the safe direction for a ceiling.

### A `PreToolUse` denial is honoured, and the turn then ends by itself

A hook permitted the first two tool calls of a turn and denied the rest, with the reason a spend
guard would give. The model had been asked for eight.

Two calls ran. The third was refused and did **not** execute — `PostToolUse` fired twice, never
three times, which is the only trustworthy evidence that a denial stopped anything. The model then
stopped, explained that a hook had reported a spend ceiling, and ended its turn without being bound
by `--max-turns`. It attempted **one** further call after the first refusal, not a stream of them.

The decision that works is the documented shape, emitted on stdout with exit 0:

```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": "…"}}
```

The reason reaches the model intact: it quoted the ceiling back in its closing report. That matters
more than it sounds — a refusal the model cannot read is one it narrates as a tool failure and tries
to work around.

### A subagent's own tool calls reach the hook, carrying the parent's transcript

This is what decides whether a mid-turn ceiling covers the expensive half of a routed run. It does.
A session was asked to delegate one command to a subagent; the subagent's `Bash` call arrived at the
parent's `PreToolUse` hook, carrying the parent's `transcript_path` and the parent's `session_id`.
Nothing has to be mapped or merged: the payload is the one `Stop` already receives, so the same
measurement — which reads the sibling subagent transcripts of § 6 — applies unchanged, and a
subagent's call can be refused rather than only the delegation that launched it.

Two incidental findings came out of the same probe, both of which had already broken a draft of it:

- the delegation tool is named **`Agent`** on 2.1.296, not `Task`. A probe matching only `Task`
  reports "the session never delegated" for a session that delegated perfectly well.
- **the delegation returns as soon as the subagent is launched.** `PostToolUse` for it fires before
  the subagent has called anything, so bracketing "calls made while the delegation was outstanding"
  identifies nothing. The probe distinguishes the two sides by a marker word only the subagent is
  ever told to run.

### What this costs, and why the guard caches

A hook on `PreToolUse` runs in front of every tool call, so its own cost is a tax on everything.
Measured on this machine, against transcripts of three sizes:

| transcript | measuring | reusing a measurement |
|---|---|---|
| 0.7 MB | 65 ms | 27 ms |
| 3.3 MB | 131 ms | 29 ms |
| 9.8 MB | 263 ms | 26 ms |

The measurement is linear in the size of the session — about 25 ms per megabyte — while reusing one
is flat, and roughly the cost of starting `python3` at all. A long session is exactly where a spend
ceiling matters, so `hooks/autopilot-pretool.py` caches its last reading for a few seconds rather
than parsing a growing transcript before every action. The cache window is the real resolution of
the ceiling: a run can overshoot by whatever it spends inside it.

*Measured 2026-10-11 on Claude Code 2.1.296. The `midturn-subagent.sh` verdict was wrong twice before
it was right — once on the tool's name and once on the asynchrony above — and both times it reported
a confident negative. A probe that can only fail by saying "nothing happened" is one to distrust.*

*Re-measured 2026-10-18 on Claude Code 2.1.302, with every session isolated by `--setting-sources
project,local`: the transcript is incremental (1 → 1 → 3 usage rows, Stop saw 4), denials are
honoured with one refused call of overshoot, and a subagent's own tool call reaches the hook
carrying the parent's transcript. Unchanged.*

*Re-measured 2026-10-19 on Claude Code 2.1.303: the transcript is incremental (1 → 1 → 4 usage rows,
Stop saw 4, so this time the last mid-turn reading trailed by nothing); two permitted calls ran, the
third was denied and did not execute, and the model ended the turn quoting the ceiling; the
subagent's marked `Bash` call reached `PreToolUse` with the parent's `transcript_path` and
`session_id`, the delegation still named `Agent`. Unchanged.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/midturn-transcript.sh`
`scripts/probes/midturn-deny.sh` `scripts/probes/midturn-subagent.sh`

## 18. A plugin can ship an output style, and only its prefixed name reaches it

Measured **2026-10-18** on **2.1.302** with `scripts/probes/plugin-output-style.sh`: a throwaway
plugin ships one style whose only instruction is to end every reply with a token no model writes by
accident, and each case selects it a different way. Two Haiku sessions per case.

| Selected by | `init` reports | Token in the reply |
|---|---|---|
| nothing (control) | `default` | 0/2 |
| `--settings` `outputStyle: "Canary"` | `Canary` | **0/2** |
| `--settings` `outputStyle: "canaryplug:Canary"` | `canaryplug:Canary` | 2/2 |
| `.claude/settings.json` `outputStyle: "canaryplug:Canary"` | `canaryplug:Canary` | 2/2 |
| `.claude/settings.local.json` `outputStyle: "canaryplug:Canary"` | `canaryplug:Canary` | 2/2 |

Three findings, two of which would have been guessed wrong:

- **The name is `<plugin>:<Name>`.** The bare name falls back to the default with no warning. So
  `/efficiency:init` writes `efficiency:Signals`, and nothing else would work.
- **The `init` event is not evidence.** Its `output_style` field echoes whatever it was given — on
  the exploratory run it reported `NoSuchStyle` as is. Only the model's behaviour says whether a
  style took, which is why the probe uses a canary rather than reading the field.
- **`--setting-sources project,local` keeps the developer's own style out.** The control ran
  `default` on a machine whose `~/.claude/settings.json` selects a personal style. That style had
  been reaching every probe session until now, measured in the init events of a
  `skill-auto-invoke.sh` run the same day, so that probe now passes the flag.

The plugin needs no manifest entry: an `output-styles/` directory beside `.claude-plugin/` is found
on its own.

*Re-measured 2026-10-19 on 2.1.303 by the same probe, two trials per case: the identical table — bare
name 0/2, every prefixed selection 2/2, the control `default` and 0/2. Unchanged.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/plugin-output-style.sh`

## 19. `efficiency:fanout` fans out, and refuses without a gate

Until this was measured the skill had never been run, by anyone, once — the only skill with no
evidence behind it at all.

Measured **2026-10-18** on **2.1.302** with `scripts/probes/fanout.sh`, twice, Sonnet driving. A
scaffolded project has four stub functions in four files, each with its own unittest, and a policy
that routes routine work to Haiku. The skill is invoked by name; whether a plain request reaches it is
§ 14's question. Read from the session stream and from the files afterwards:

| claim | run 1 | run 2 |
|---|---|---|
| subagents started by one assistant message | 4 | 4 |
| subagent type | `implementer-fast` ×4 | `implementer-fast` ×4 |
| gate run after the batch | yes | yes |
| tests green at the end | 4/4 | 4/4 |
| `total_cost_usd` in the result event | $0.123 | $0.118 |
| same request, `gate: ""` — delegations, files edited | none, 0 | none, 0 |

**It is a real fan-out, not a sequential run under the name**: all four delegations leave in one
message. They are routed by the policy as the skill says, and the gate runs once the batch is back.

**The refusal is the skill's text at work.** With the gate empty, all three sessions run declined and
said why. The rule that a fan-out needs a gate exists only in `SKILL.md`, and the one transcript kept
shows the session reading the policy and the sources and never the skill file — so it came from the
skill being loaded.

**Under `-p` a slash command's expansion never reaches the stream** — no `Skill` call, no user
message carrying its text. The `init` event lists the skill as available, and that is all the stream
can say. Whether the text reached the model has to be read from what the model then did.

Not measured: more items than one batch holds, so whether it actually batches at ten, and whether it
runs the gate between batches, is still only what the skill says.

*Re-measured 2026-10-19 on Claude Code 2.1.303 by `scripts/probes/fanout.sh`, once: four
`implementer-fast` delegations in one message, one gate run after the batch, 4/4 green, nothing
touched outside `src/`, $0.119; with `gate: ""` no delegation, no edit, and the refusal gave the
skill's reason, $0.055. Unchanged.*

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/fanout.sh`

## 20. Fanning out pays past a minute of serial work; turn-bound work gets there at two

The fast mode trades money for time: one subagent per task of a wave, all in one message. Below
some size the subagents' start-up and the driver's round trips eat the saving. `parallel.min_wave`
and `parallel.min_serial_minutes` are meant to mark that size. They were guesses; this is the
measurement.

Measured with `scripts/probes/parallel-crossover.sh`, Sonnet driving, Haiku
(`efficiency:implementer-fast`) subagents, every session headless under `-p`. Two sessions per
width, on the same throwaway project:

- **economy** — the prompt says do every item in the main session, no subagents.
- **fast** — the prompt says start one subagent per item, all N in one assistant message, then run
  the gate once.

Cost is `total_cost_usd` from the last `result` event, which includes the subagents (§ 6). Wall time
is measured outside the process. Every item was green on every run, every delegation left in one
message, and peak concurrency always equalled N.

### Two workloads

**`WORKLOAD=spec`: fully specified items.** N independent stub modules — an expression evaluator, an
INI parser, a CSV reader and writer, an LRU cache, Dijkstra, Roman numerals both ways, semver, and so
on — each two to four functions with a written spec and eight to twelve unittest cases. Nothing has
to be discovered.

**`WORKLOAD=turns`: turn-bound items, the case the fast mode is for.** Each item is a ~240-line module
nobody has seen, whose conventions live only in the module. Its stub's spec leaves out two
behaviours. Its test sleeps 10 seconds and reveals those behaviours one failure at a time. Making an
item really turn-bound took three tries, and two of them are findings in their own right:

- With the cases in plain base64, Sonnet read the hidden behaviours straight out of the test file and
  was green on its first run.
- Compressed, the cases lasted until the first failure: one `zlib` one-liner later, every item was
  fixed in one batch.
- What holds is a digest of each expected output and a message sealed with the previous case's
  output. Only an implementation that already gets everything before it right can read the next
  message.

### Turn-bound items: fast wins from two items, usually for less money

Measured **2026-10-19** on **2.1.303**, on mains power under `caffeinate -i`. Where a cell has two
values, the first sample looked anomalous and was run once more.

| N | economy s | fast s | wall cut | economy $ | fast $ | premium |
|---|---|---|---|---|---|---|
| 2 | 149 | 79 | +47% | 0.138 | 0.079 | −43% |
| 3 | 203 | 105 | +48% | 0.189 | 0.134 | −29% |
| 4 | 186 | 114 | +39% | 0.112 | 0.111 | −1% |
| 6 | 366 · 154 | 134 | +63% · +13% | 0.160 · 0.150 | 0.183 | +14% · +22% |
| 8 | 201 · 236 | 203 · 150 | −1% · +36% | 0.151 · 0.179 | 0.199 · 0.175 | +32% · −2% |

**The crossover is at or below two items.** Fast was faster in 6 of 7 pairs, by 70 to 100 seconds
up to N = 4. The one exception, a tie at N = 8, was a sample where one Haiku subagent took 106 seconds
against 56 on the rerun. Up to N = 4 fast was also *cheaper*: in the economy arm, Sonnet pays for
every iteration, and in the fast arm Haiku does. From N = 6 the premium is +14% to +32%.

**The economy arm does not grow linearly, because it learns once and applies everywhere.** The
twelve items share a template and a pool of hidden rules. Every economy session read every stub at
once, found a rule on one item, and patched all of them in a single `for f in ...; do sed ...` loop.
So economy took 150 to 240 seconds whatever the width, with one slow sample at 366. Real tasks share
less, so they would likely favour fast more than this workload does.

**The fast arm has a floor that rises with width.** At N = 2 the floor is about 80 seconds: the
longest subagent ran about 47 seconds, plus the driver's dispatch and gate. At N = 8 it is 150 to 200
seconds, because the slowest of eight Haiku subagents is slower than the slowest of two.

### Fully specified items: fast wins only past about a minute of serial work

Re-measured **2026-10-19** on **2.1.303**, run once. The 2.1.302 run (2026-10-18) gave the same
picture: 17/26, 23/35, 33/31 and 58/32 seconds, economy/fast, at the same widths.

| N | economy s | fast s | wall cut | economy $ | fast $ | premium |
|---|---|---|---|---|---|---|
| 2 | 16 | 24 | −50% | 0.088 | 0.075 | −15% |
| 4 | 21 | 26 | −24% | 0.105 | 0.103 | −2% |
| 8 | 36 | 31 | +14% | 0.152 | 0.159 | +5% |
| 12 | 65 | 31 | +52% | 0.206 | 0.206 | 0% |

**The fast arm has a floor of 24 to 31 seconds, whatever the width.** The driver writes N prompts,
the longest subagent runs 15 to 20 seconds, and the driver runs the gate.

**The economy arm is fast here because it batches too.** Asked to do everything itself, Sonnet reads
the stubs in one to three calls and writes every module in one or two `Bash` heredocs, without
opening a test. Each item adds about 3 to 5 seconds of generation, not a round trip. So the crossover
lies between N = 8, a small win, and N = 12, a 52% cut. On 2.1.302, N = 8 was a wash.

### What decides it

**Duration decides, and width does not.** Across both workloads, fast lost every time the economy
session took under ~30 seconds. It won in every pair where the economy session took over a minute,
except the one tie at N = 8. Width alone points the wrong way in both directions. On fully specified
work, twelve items are needed. Turn-bound work clears the threshold with two.

The estimate has to be of the main session's real serial time, not of items × effort. A planner
pricing each fully specified item at "a minute" would predict 8 minutes for N = 8 and get 36
seconds. A main session batches anything it can finish without looking. What it cannot batch is
waiting: a slow test, a failure to read, a file it has not seen.

**`hooks/lib/spend.py` now agrees with `total_cost_usd`.** On 2.1.302 it overcounted two to four
times, because it summed the full `usage` on every content-block row of a message. On every cell of
this run, it matched the `result` event to within $0.001, subagents included.

**Under `-p`, delegations come back asynchronously.** A fast session emits one `result` event per
subagent that finishes, each with the cumulative cost so far. Only the last one is the session's
total. A reader that takes the first `result` under-reports.

**The probe's clock was broken, and nothing showed it until the clock read zero.** The previous
attempts timed each cell by subtracting `time.monotonic()` values taken by two separate `python3 -c`
processes. On macOS's Python 3.9, that clock counts from the process's own start, so every cell
measured 0 seconds. The probe now uses `CLOCK_UPTIME_RAW`, which is system-wide and stops while the
machine sleeps, and it prints wall-clock time beside it. A gap of more than 2 seconds flags the cell
`DOZE`. None did. A sentinel sampled both clocks every 2 seconds for the whole run, and every 10 s
test sleep took 10.1 s of wall time. The two invalid runs of 2026-10-18 and 19 were on battery, and
their 10 s sleeps took 15 to 23 s.

Not measured: subagents on Sonnet or Opus, where the premium will be larger, since each pays its own
context; widths above 12; Opus as the driver; heterogeneous turn-bound items, which economy could not
batch the way it batched these; and anything outside a headless `-p` session. Each cell ran at most
twice, so every crossover here is a range, not a number.

Verified: 2026-10-19 · Claude Code 2.1.303 · `scripts/probes/parallel-crossover.sh`

## 21. A hook can grant a permission, and a deny rule still beats it

Measured **2026-10-21** on **2.1.305** with `scripts/probes/hook-allow.sh`: one headless session
under `--permission-mode default`, where any Bash call no rule allows is refused because nobody is
there to ask, told to run three `touch` commands in a fresh, never-trusted `mktemp` directory. A
`PreToolUse` hook answered `permissionDecision: "allow"` for two of them; a `permissions.deny` rule
in `--settings` named one of those two.

| Command | Hook | Rule | Ran? |
|---|---|---|---|
| `touch allowed` | allow | — | **yes** |
| `touch control` | silent | — | no — the baseline: the mode refuses |
| `touch denied` | allow | deny | **no** |

Three conclusions, and the design of the auto-allow rests on each:

- **The allow is honoured.** A hook can lift a prompt the permission mode would raise. The session
  reported the control as "needed approval", the allowed one as simply run.
- **A deny rule wins over it.** So a project's own fence keeps its meaning without the classifier
  reading it, and the hook cannot be the thing that bypasses a deliberate deny.
- **It works where a static allowlist does not.** § 7: `permissions.allow` in an untrusted
  workspace's project settings is ignored, while hooks run. The hook is therefore the only carrier
  of "don't ask about this" that reaches a project before anyone has accepted the trust dialog —
  and the only one that needs no write into `.claude/` (§ 9).

Not measured: whether a deny rule in an *untrusted* project's own `.claude/settings.json` still
beats the hook — § 7 suggests that file's permission rules are ignored there, deny included. The
classifier allows nothing a deny list would plausibly hold, so the gap is narrow, but it exists.

Verified: 2026-10-21 · Claude Code 2.1.305 · `scripts/probes/hook-allow.sh`

## 22. A Stop hook can ask a second model for a verdict — and only one way keeps the verdict ours

Measured **2026-10-21** on **2.1.306** with `scripts/probes/supervisor-call.sh`, one headless Haiku
session per mode in a fresh `mktemp` directory, settings passed with `--settings`. The question is
whether the spend ceiling can become a checkpoint: at the ceiling, a cheaper model judges whether
the work is converging, and the run continues or stops on that verdict.

**`nested` — a command `Stop` hook runs `claude -p` itself.** The call was
`claude -p … --safe-mode --setting-sources project,local --model haiku --tools ""
--no-session-persistence --output-format json --json-schema <verdict schema> --max-budget-usd 0.05`.

| Question | Measured |
|---|---|
| Does it run from inside the hook? | **yes**, exit 0, under the parent's `CLAUDECODE=1` environment |
| How long? | **2.9–3.3 s** for a one-paragraph verdict, over two runs |
| What did it cost? | **$0.0002–$0.0007**, reported as `total_cost_usd` in its own JSON |
| Is the verdict machine-readable? | **yes**: `structured_output` held `{"verdict": "converging", "why": …}` against the schema |
| Did it re-fire the parent's hooks? | **no**: the `SessionStart` marker counted 1, the parent's own |
| Did its spend reach the parent transcript? | **no**: one transcript in the project, holding only the parent's turn |

**`prompt` — the platform's own `type: "prompt"` `Stop` hook.**

| Question | Measured |
|---|---|
| `"model": "haiku"` | **refused**: `unrecognized_model`, reported as a *non-blocking* hook error, and the turn ended normally |
| `"model": "claude-haiku-5-5"` | **works**: it refused the first stop, its reason reached the model as `Stop hook feedback`, the model complied, the second stop was allowed |

What the design takes from it:

- **The supervisor is a nested call, not a prompt hook.** The prompt hook is the platform's
  judgement, not ours: its verdict never passes through `autopilot-stop.py`, so it cannot be
  bounded by the run's counters (rule 3), and its own failure **fails open** — a model id it does
  not know simply lets the turn end, the opposite of rule 2's fail-closed guard. The nested call
  hands the verdict back to the hook as data, and the hook decides what it is worth.
- **Its cost is invisible to `spend.py`, so the hook must add it.** `--no-session-persistence`
  leaves no transcript, and none would be the parent's anyway. `total_cost_usd` from its JSON is
  the figure to charge to the run, and a missing one is a blind guard.
- **Aliases are not portable across call sites.** `--model haiku` resolves; the prompt hook's
  `model` field does not. § 16 again, in a new place.
- **The latency fits the `Stop` hook, not `PreToolUse`.** 3 s against the Stop hook's
  timeout (1200 s since 0.23.0) is nothing; against `autopilot-pretool.py`'s 20 s, on every
  tool call, it is not. The verdict is taken at the boundary and the in-turn guard only reads it.

Not measured: whether `--safe-mode` also keeps an *installed plugin's* hooks out of the nested
session — the marker was a `--settings` hook. The help text says it does; a supervisor should still
set an environment flag its own hooks no-op on, rather than rest the recursion question on one line
of help.

Verified: 2026-10-21 · Claude Code 2.1.306 · `scripts/probes/supervisor-call.sh`

## 23. A checkpoint lets a long task through and stops an impossible one

Measured **2026-10-21** on **2.1.306** with `scripts/probes/supervisor-checkpoint.sh`: a real
headless Haiku session in a fresh git repository, under the **shipped** `Stop` and `PreToolUse`
hooks, with `budget.supervisor: haiku` and a per-task ceiling of $0.02 — a few turns' worth, so a
checkpoint is reached in minutes.

| Mode | The run | Checkpoints | Ended |
|---|---|---|---|
| `converging` | one task, twenty files, one file per turn: about four times its ceiling | 3 × no task closing, 1 × spend ceiling — all **converging**, each naming the files so far | **DONE**, 20 of 20 |
| `impossible` | read a key from a file that does not exist | 1 × no task closing — **looping**: "re-reading the same missing file" | **BLOCKED** at block 6 |

Before 0.23.0 the first run stops at its ceiling with the work three-quarters done — the case this
was built for. Supervisor spend: $0.0022 for four verdicts, $0.0006 for one. A direct call to the
shipped default, Sonnet, with the prompt on stdin: 4.4 s, $0.007.

Three defects the probe found that the selftest could not, all fixed before this was written:

- **A run that closed every task inside one turn was judged — and stopped as "looping"**, for having
  nothing left to do. A checkpoint with no open task now grants without asking.
- **The supervisor saw no tool calls.** Progress noted at the top of the invocation moved the start
  of the window it reads calls from past the very turn it was judging. Calls are now read from the
  previous checkpoint onwards.
- **It did not know what its answer did.** Its reasons said the developer would have to raise the
  budget. The prompt now says that `converging` grants another tranche.

Two limits of the measurement. The ceiling is a few cents against real ones of dollars, so the idle
checkpoint (half a window without progress) reacts to a single empty Haiku turn here; at a real
ceiling it is a dozen. And a stall that makes no tool call at all is still overridden by the
platform at its ninth block (§ 3) if a first checkpoint called it converging — the second, at
block 11, would have stopped it, but never runs. A session that calls no tool for nine turns is not
the case a supervisor is for.

Verified: 2026-10-21 · Claude Code 2.1.306 · `scripts/probes/supervisor-checkpoint.sh`

## 24. A hook can know the OS language without LANG, and one injected line holds the dialogue

Measured **2026-10-21** on **2.1.306** with `scripts/probes/dialogue-language.sh`, macOS 23.3.0 with
the system language set to Italian.

**`env` — what reaches a hook.** One headless session per cell; a `SessionStart` and a
`UserPromptSubmit` hook each recorded the locale variables and asked `defaults` for the OS language.

| Launching environment | `LANG` in the hook | `LC_*` | `defaults read -g AppleLanguages` |
|---|---|---|---|
| inherited from a terminal | `it_IT.UTF-8` | unset | `("it-IT")` |
| `LANG` and `LC_*` removed | **unset** | unset | `("it-IT")` |

So a hook sees exactly the environment Claude Code was started with, and a session started without
`LANG` — as an app launched from the Dock or Finder may be — gives it no locale variable at all.
`AppleLanguages` answers either way, from inside the hook, in milliseconds. It is the OS language;
`LANG` is a shell's.

**`drift` — does telling the model hold?** An English task in an English prompt, then a second
English turn via `--continue`, on Haiku; each reply classified by counting Italian and English
stopwords in its prose, code excluded.

| Cell | Turn 1 | Turn 2 |
|---|---|---|
| no language line | English | English |
| line at `SessionStart` only | **Italian** | **Italian** |
| line at `SessionStart` and on every prompt | **Italian** | **Italian** |

One line at session start is enough for two turns: the files it wrote stayed English, the reports
did not. What two turns cannot show is the drift that prompted this — a report in English after
dozens of turns of English tool work, deep into a long context. The per-prompt line is there for
that case, and costs about twenty tokens a turn; its necessity is inferred from the incident, not
measured.

One more fact, found while wiring it: the session-start injection is around 18 KB and the harness
shows it as a **2 KB preview**. The language line therefore goes first, above even the backlog — a
line below the cut may never be read.

Verified: 2026-10-21 · Claude Code 2.1.306 · `scripts/probes/dialogue-language.sh`

## Re-running these measurements

Every numbered section ends with a `Verified:` line — date, Claude Code version, and the probe that
re-derives it, or `manual` when a person has to be in the session. `scripts/lib/check-measurement-age.py`
reads only that line. After a Claude Code upgrade the gate goes amber for every probe-backed section
measured on another version and prints the probes to run; `manual` sections follow the calendar
alone, and the gate names them. Re-run, then update the line in place.

```bash
bash scripts/probes/stop-cap.sh stall 40   # expect ~9 invocations, platform cap
bash scripts/probes/stop-cap.sh read  12   # expect 6, bound by --max-turns, cap never fires
bash scripts/probes/stop-cap.sh write 12   # expect 6, same
bash scripts/probes/transcript-shape.sh <path-to-transcript.jsonl>  # show subagents directory and usage keys present
bash scripts/probes/transcript-shape.sh --live           # rows vs messages, priced against total_cost_usd (cents)
bash scripts/probes/model-ids.sh           # which id each routing alias resolves to, and whether it is priced
bash scripts/probes/statusline.sh install   # then start a session, look at the bottom, and `show`
bash scripts/probes/pdf-token-cost.sh make # build the test PDF; read it in a session, then `measure <transcript>`
bash scripts/probes/plugin-output-style.sh # which name selects a plugin's output style
bash scripts/probes/fanout.sh              # four items in one batch, and a refusal with no gate
bash scripts/probes/parallel-crossover.sh  # wall time and cost, economy vs fast, at N = 2 4 8 12
WORKLOAD=turns bash scripts/probes/parallel-crossover.sh 2 3 4 6 8  # the turn-bound case; mains power, caffeinate -i
bash scripts/probes/hook-allow.sh          # a hook's allow is honoured, a deny rule still wins
bash scripts/probes/supervisor-call.sh nested  # a Stop hook's nested Haiku verdict: cost, latency, no leak
bash scripts/probes/supervisor-call.sh prompt  # the platform's prompt hook: alias refused, full id blocks
bash scripts/probes/supervisor-checkpoint.sh converging  # a long task goes DONE through checkpoints
bash scripts/probes/supervisor-checkpoint.sh impossible  # an impossible one is stopped at the first
bash scripts/probes/dialogue-language.sh env    # which locale signals reach a hook, with and without LANG
bash scripts/probes/dialogue-language.sh drift  # does an injected language line hold over English work
```

The probes print verdicts rather than raw numbers to interpret. `stop-cap.sh` says loudly when the hook
never fired at all — because that failure is most likely to be misread as a platform change.
`transcript-shape.sh` verifies that subagent transcripts are where they should be and shows which usage
keys appear in actual spend data.
