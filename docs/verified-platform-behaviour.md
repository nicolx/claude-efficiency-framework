# Verified platform behaviour

Every claim here was **measured on this machine**, not read in documentation. Each entry carries the
date, the Claude Code version, and the method, so it can be re-run when a release moves the ground.

Re-measure before trusting any of it after a Claude Code upgrade. The probes live in
`scripts/probes/` and take a couple of minutes and a few cents of Haiku.

Measured: **2026-09-05** · Claude Code **2.1.261** · macOS 23.3.0

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

## 3. The block cap — and the condition that governs it

This is the finding that decides how much autonomy is actually available, and the documented
"8 consecutive blocks" is only half of the story.

| Probe | What the model did between blocks | Hook invocations | What stopped it |
|---|---|---|---|
| A | Replied with text only, no tool calls | **9** | the platform cap |
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

## 7. Project settings are ignored in an untrusted directory

Measured while building the probe, and worth knowing before debugging a hook that "does not run".

A freshly created directory is not a trusted workspace. Its `.claude/settings.json` is **silently
ignored** — no warning, no error, the hook simply never fires and every counter reads zero. The
failure is indistinguishable from "the platform changed its behaviour", which is the expensive part.

Two consequences:

- Test hooks with `claude --settings <file>`, which bypasses workspace trust, rather than by writing
  a project settings file into a scratch directory.
- A consuming project that has never been trusted gets no hooks from its own settings. Plugin hooks
  are a separate path, but the same lesson applies: confirm the hook actually ran before concluding
  anything about what it did.

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

## Re-running these measurements

```bash
bash scripts/probes/stop-cap.sh stall 40   # expect ~9 invocations, platform cap
bash scripts/probes/stop-cap.sh read  12   # expect 6, bound by --max-turns, cap never fires
bash scripts/probes/stop-cap.sh write 12   # expect 6, same
```

The probe prints a verdict rather than a number to interpret, and says so loudly when the hook never
fired at all — because that is the failure most likely to be misread as a platform change.
