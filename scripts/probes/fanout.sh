#!/bin/bash
# fanout.sh — does /efficiency:fanout actually fan out, and does it refuse when it should?
#
# Until 2026-10-18 the fanout skill had never been run by anyone, once. Its whole
# contribution is a claim about behaviour — independent items go to subagents in
# batches, routed by the policy, with the gate run after each batch — and a skill
# that is only text is a claim nobody has checked.
#
#   bash scripts/probes/fanout.sh                 # both cases
#   bash scripts/probes/fanout.sh parallel        # only the fan-out
#   DRIVER=opus bash scripts/probes/fanout.sh
#   KEEP=1 bash scripts/probes/fanout.sh no-gate  # keep the projects and streams
#
# Costs real money, about a dollar: a Sonnet driver and four Haiku subagents.
# Bounded by --max-budget-usd. Writes nothing outside its own temporary
# directories, and keeps the streams there until it exits.
#
# Two cases, because the skill makes two promises:
#
#   parallel  four stub functions in four files, each with its own unittest, in a
#             project whose policy declares a gate. The skill is invoked by name —
#             whether a plain request reaches it is § 14's question, not this
#             one's. Read from the stream: which subagents were started, how many
#             in the same assistant message (one message with four tool calls is
#             a batch; four messages with one each is a sequential run wearing a
#             fan-out's name), whether the gate ran after them, and whether every
#             test is green at the end.
#   no-gate   the same request in the same project with `gate: ""`. The skill
#             says to refuse and explain. Zero delegations and zero edits under
#             src/ is the pass.
#
# The sessions run with `--setting-sources project,local`, like every probe here.

set -uo pipefail

cd "$(dirname "$0")/../.." || exit 2
PLUGIN=$(pwd)

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

MODE=${1:-both}
DRIVER=${DRIVER:-sonnet}
BUDGET=${BUDGET:-3.00}

case "$MODE" in parallel|no-gate|both) ;; *) echo "usage: $0 [parallel|no-gate|both]" >&2; exit 2 ;; esac

echo "claude: $(claude --version 2>/dev/null | head -1)"
echo "driver: $DRIVER   budget ceiling per case: \$$BUDGET"
echo

DIRS=()
# shellcheck disable=SC2329  # invoked by the trap below
cleanup() {
    if [ -n "${KEEP:-}" ]; then echo "kept: ${DIRS[*]:-}"; return; fi
    for d in "${DIRS[@]:-}"; do [ -n "$d" ] && rm -rf "$d"; done
}
trap cleanup EXIT

GATE_CMD="python3 -m unittest discover -s tests -q"
REQUEST="/efficiency:fanout Implement the four stub functions in src/alpha.py, src/beta.py, src/gamma.py and src/delta.py. Each has its own test in tests/, and none of them touches another's files."

# ── the project ──────────────────────────────────────────────────────────────
scaffold() {
    local dir="$1" gate="$2"
    mkdir -p "$dir/src" "$dir/tests" "$dir/.efficiency" || return 1
    ( cd "$dir" && git init -q . ) || return 1
    echo stream.json >> "$dir/.git/info/exclude"
    : > "$dir/src/__init__.py"

    printf 'def double(x):\n    raise NotImplementedError\n'          > "$dir/src/alpha.py"
    printf 'def is_even(n):\n    raise NotImplementedError\n'         > "$dir/src/beta.py"
    printf 'def reverse_words(s):\n    raise NotImplementedError\n'   > "$dir/src/gamma.py"
    printf 'def clamp(x, lo, hi):\n    raise NotImplementedError\n'   > "$dir/src/delta.py"

    cat > "$dir/tests/test_alpha.py" <<'EOF'
import unittest
from src.alpha import double
class T(unittest.TestCase):
    def test(self):
        self.assertEqual(double(3), 6)
        self.assertEqual(double(-2), -4)
EOF
    cat > "$dir/tests/test_beta.py" <<'EOF'
import unittest
from src.beta import is_even
class T(unittest.TestCase):
    def test(self):
        self.assertTrue(is_even(4))
        self.assertFalse(is_even(7))
EOF
    cat > "$dir/tests/test_gamma.py" <<'EOF'
import unittest
from src.gamma import reverse_words
class T(unittest.TestCase):
    def test(self):
        self.assertEqual(reverse_words("a b c"), "c b a")
EOF
    cat > "$dir/tests/test_delta.py" <<'EOF'
import unittest
from src.delta import clamp
class T(unittest.TestCase):
    def test(self):
        self.assertEqual(clamp(5, 0, 3), 3)
        self.assertEqual(clamp(-1, 0, 3), 0)
        self.assertEqual(clamp(2, 0, 3), 2)
EOF

    cat > "$dir/.efficiency/policy.md" <<EOF
---
gate: "$gate"

budget:
  continuations: 40
  gate_retries: 2
  task_usd: 2.00

tiers:
  routine: haiku
  sensitive: sonnet
  critical: opus

critical: []
sensitive: []

stop_for:
  - a public interface changing shape
---

# Declared defaults

- none
EOF
    ( cd "$dir" && git add -A && git -c user.email=probe@local -c user.name=probe commit -qm fixture ) || return 1
}

# Delegations grouped by the assistant message that made them, plus the gate
# runs and whether either came before the other. One line of JSON.
read_stream() {
    python3 - "$1" "$GATE_CMD" <<'PY'
import json, sys
path, gate = sys.argv[1], sys.argv[2]
batches, order, kinds, skill, cost = {}, [], [], False, None
seq = 0
for line in open(path, errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("type") == "result":
        cost = ev.get("total_cost_usd")
    # Under -p a slash command's expansion never appears in the stream — not as
    # a Skill call, not as a user message — so all the stream can say is that the
    # skill was on offer. Whether its text reached the model is read from
    # behaviour: the no-gate refusal is a rule that exists only in SKILL.md.
    if ev.get("type") == "system" and ev.get("subtype") == "init":
        skill = "efficiency:fanout" in (ev.get("slash_commands") or [])
    msg = ev.get("message")
    if not isinstance(msg, dict) or not isinstance(msg.get("content"), list):
        continue
    if ev.get("parent_tool_use_id"):
        continue            # a subagent's own calls, not the driver's decisions
    for b in msg["content"]:
        if not isinstance(b, dict):
            continue
        if b.get("type") != "tool_use":
            continue
        seq += 1
        name, inp = b.get("name"), b.get("input") or {}
        if name in ("Task", "Agent"):
            mid = msg.get("id") or "seq%d" % seq
            batches.setdefault(mid, 0)
            batches[mid] += 1
            kinds.append(inp.get("subagent_type") or "(none given)")
            order.append(("delegate", seq))
        if name == "Bash" and "unittest" in str(inp.get("command", "")):
            order.append(("gate", seq))
last_delegate = max([s for k, s in order if k == "delegate"], default=None)
gate_after = any(k == "gate" and last_delegate is not None and s > last_delegate for k, s in order)
print(json.dumps({"skill": skill, "batches": list(batches.values()), "kinds": kinds,
                  "gate_runs": sum(1 for k, _ in order if k == "gate"),
                  "gate_after_last_batch": gate_after, "cost": cost}))
PY
}

run_session() {
    local dir="$1"
    ( cd "$dir" && claude -p "$REQUEST" \
        --setting-sources project,local \
        --model "$DRIVER" --max-turns 40 --max-budget-usd "$BUDGET" \
        --permission-mode bypassPermissions \
        --plugin-dir "$PLUGIN" \
        --output-format stream-json --verbose </dev/null > "$dir/stream.json" 2>&1 )
}

field() { python3 -c 'import json,sys; v=json.loads(sys.argv[1])[sys.argv[2]]; print(v if not isinstance(v,(list,bool)) else json.dumps(v))' "$1" "$2"; }

VERDICT=0

if [ "$MODE" = parallel ] || [ "$MODE" = both ]; then
    DIR=$(mktemp -d) || exit 2; DIRS+=("$DIR")
    scaffold "$DIR" "$GATE_CMD" || { echo "could not scaffold — the probe failed, not the platform" >&2; exit 2; }
    echo "── case: parallel ── four independent items, gate declared"
    run_session "$DIR"
    R=$(read_stream "$DIR/stream.json") || { echo "cannot read the stream — the probe failed" >&2; exit 2; }

    GREEN=0
    for t in alpha beta gamma delta; do
        ( cd "$DIR" && python3 -m unittest -q "tests.test_$t" >/dev/null 2>&1 ) && GREEN=$((GREEN + 1))
    done
    TOUCHED=$(cd "$DIR" && git status --porcelain | awk '{print $2}' | grep -v '^src/\|^tests/__pycache__/\|^\.' | tr '\n' ' ')
    BIGGEST=$(python3 -c 'import json,sys; b=json.loads(sys.argv[1])["batches"]; print(max(b) if b else 0)' "$R")

    echo "| claim | expected | observed |"
    echo "|---|---|---|"
    echo "| the skill was listed at init | true | $(field "$R" skill) |"
    echo "| delegations per assistant message | one message with several | $(field "$R" batches) |"
    echo "| subagent types | efficiency:implementer-fast (routine → haiku) | $(field "$R" kinds) |"
    echo "| the gate ran after the last batch | true | $(field "$R" gate_after_last_batch) ($(field "$R" gate_runs) gate run(s)) |"
    echo "| tests green at the end | 4/4 | $GREEN/4 |"
    echo "| files changed outside src/ | none | ${TOUCHED:-none} |"
    echo "| driver-reported cost | — | \$$(field "$R" cost) |"
    echo

    [ "$BIGGEST" -ge 2 ] || { echo "verdict: NOT A FAN-OUT — no assistant message started more than one subagent"; VERDICT=1; }
    [ "$GREEN" -eq 4 ]   || { echo "verdict: the fan-out left $((4 - GREEN)) item(s) red"; VERDICT=1; }
fi

if [ "$MODE" = no-gate ] || [ "$MODE" = both ]; then
    DIR=$(mktemp -d) || exit 2; DIRS+=("$DIR")
    scaffold "$DIR" "" || { echo "could not scaffold — the probe failed, not the platform" >&2; exit 2; }
    echo "── case: no-gate ── the same request, gate empty"
    run_session "$DIR"
    R=$(read_stream "$DIR/stream.json") || { echo "cannot read the stream — the probe failed" >&2; exit 2; }
    EDITED=$(cd "$DIR" && git status --porcelain -- src | grep -vc '__pycache__')
    REPLY=$(python3 -c '
import json,sys
r=""
for l in open(sys.argv[1],errors="replace"):
    try: e=json.loads(l)
    except ValueError: continue
    if e.get("type")=="result": r=e.get("result") or ""
print(r.replace("\n"," ")[:300])' "$DIR/stream.json")

    echo "| claim | expected | observed |"
    echo "|---|---|---|"
    echo "| the skill was listed at init | true | $(field "$R" skill) |"
    echo "| delegations | none | $(field "$R" kinds) |"
    echo "| files edited under src/ | 0 | $EDITED |"
    echo "| driver-reported cost | — | \$$(field "$R" cost) |"
    echo "reply: $REPLY"
    echo

    [ "$(field "$R" kinds)" = "[]" ] && [ "$EDITED" -eq 0 ] \
        || { echo "verdict: DID NOT REFUSE — the skill fanned out or edited with no gate declared"; VERDICT=1; }
fi

[ "$VERDICT" -eq 0 ] && echo "verdict: OK"
exit "$VERDICT"
