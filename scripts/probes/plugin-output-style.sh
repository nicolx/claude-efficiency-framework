#!/bin/bash
# plugin-output-style.sh — can a plugin ship an output style, under what name is
# it selected, and does `--setting-sources` keep the developer's own style out?
#
# docs/verified-platform-behaviour.md § 18 rests on this. The framework ships
# `output-styles/signals.md`, and `/efficiency:init` offers to select it — which
# is only worth doing if the name it writes is one the platform resolves.
#
#   bash scripts/probes/plugin-output-style.sh
#   TRIALS=3 bash scripts/probes/plugin-output-style.sh
#
# Method: a throwaway plugin `canaryplug` ships one style, `Canary`, whose only
# instruction is to end every reply with a token no model writes by accident.
# Each case selects it a different way and asks a one-line arithmetic question;
# the verdict is whether the token appears in the reply. The behaviour is the
# evidence, because the `init` event is not: its `output_style` field echoes
# whatever name it was given, including one that resolves to nothing — seen on
# the first exploratory run of this probe, `NoSuchStyle` reported as is.
#
# Every session runs with `--setting-sources project,local`, so the developer's
# own `outputStyle` in ~/.claude/settings.json is out of the measurement. That
# exclusion is itself measured: the `control` case must report `default`.
#
# Costs a few cents of Haiku. Writes nothing outside its own temporary directory.

set -uo pipefail

command -v claude  >/dev/null 2>&1 || { echo "claude not on PATH" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 not on PATH" >&2; exit 2; }

TRIALS=${TRIALS:-2}
MODEL=${MODEL:-haiku}
TOKEN="OSTYLE-CANARY-7731"

echo "claude: $(claude --version 2>/dev/null | head -1)"
echo "model:  $MODEL   trials per case: $TRIALS"
echo

ROOT=$(mktemp -d) || exit 2
trap 'rm -rf "$ROOT"' EXIT

PLUGIN="$ROOT/canaryplug"
mkdir -p "$PLUGIN/.claude-plugin" "$PLUGIN/output-styles" || exit 2
cat > "$PLUGIN/.claude-plugin/plugin.json" <<'EOF'
{ "name": "canaryplug", "version": "0.0.1", "description": "probe fixture" }
EOF
cat > "$PLUGIN/output-styles/canary.md" <<EOF
---
name: Canary
description: probe fixture
keep-coding-instructions: true
---

End every reply, without exception, with the exact token $TOKEN on a line of its own.
EOF

# key ~ how the style is selected ~ expectation for the verdict line
CASES=$(cat <<'EOF'
control ~ nothing selected ~ absent
flag-bare ~ --settings outputStyle "Canary" ~ ?
flag-prefixed ~ --settings outputStyle "canaryplug:Canary" ~ ?
project-file ~ .claude/settings.json outputStyle "canaryplug:Canary" ~ ?
local-file ~ .claude/settings.local.json outputStyle "canaryplug:Canary" ~ ?
EOF
)

# style reported by `init` | plugin loaded (yes/no) | token in the reply (yes/no)
read_stream() {
    python3 - "$1" "$TOKEN" <<'PY'
import json, sys
style, loaded, reply = "?", "no", ""
for line in open(sys.argv[1], errors="replace"):
    try:
        ev = json.loads(line)
    except ValueError:
        continue
    if ev.get("subtype") == "init":
        style = ev.get("output_style")
        loaded = "yes" if any(p.get("name") == "canaryplug" for p in ev.get("plugins") or []) else "no"
    if ev.get("type") == "result":
        reply = ev.get("result") or ""
print(f"{style}|{loaded}|{'yes' if sys.argv[2] in reply else 'no'}")
PY
}

run_case() {
    local key="$1" dir="$2"
    # bash 3.2 treats an empty array as unbound under set -u, hence the +-guard below
    local extra=()
    mkdir -p "$dir/.claude" || return 1
    ( cd "$dir" && git init -q . ) >/dev/null 2>&1
    case "$key" in
        flag-bare)     extra=(--settings '{"outputStyle":"Canary"}') ;;
        flag-prefixed) extra=(--settings '{"outputStyle":"canaryplug:Canary"}') ;;
        project-file)  echo '{"outputStyle":"canaryplug:Canary"}' > "$dir/.claude/settings.json" ;;
        local-file)    echo '{"outputStyle":"canaryplug:Canary"}' > "$dir/.claude/settings.local.json" ;;
    esac
    ( cd "$dir" && claude -p "What is 6 times 7? Reply in one line." \
        --model "$MODEL" --max-turns 1 --max-budget-usd 0.05 \
        --setting-sources project,local \
        --plugin-dir "$PLUGIN" ${extra[@]+"${extra[@]}"} \
        --output-format stream-json --verbose </dev/null >"$dir/stream.json" 2>&1 )
}

echo "| case | selected by | init reports | plugin loaded | token in reply |"
echo "|---|---|---|---|---|"
FAILED=0
CONTROL_LEAK=0
while IFS='~' read -r key how _; do
    key=$(echo "$key" | xargs); how=$(echo "$how" | sed 's/^ *//;s/ *$//')
    [ -n "$key" ] || continue
    hits=0; styles=""; loaded=""
    t=1
    while [ "$t" -le "$TRIALS" ]; do
        dir="$ROOT/$key-t$t"
        run_case "$key" "$dir" || { echo "could not set up $key — the probe failed, not the platform" >&2; exit 2; }
        IFS='|' read -r st ld tk <<< "$(read_stream "$dir/stream.json")"
        [ "$tk" = yes ] && hits=$((hits + 1))
        case " $styles " in *" $st "*) ;; *) styles="$styles $st" ;; esac
        case " $loaded " in *" $ld "*) ;; *) loaded="$loaded $ld" ;; esac
        t=$((t + 1))
    done
    echo "| $key | $how |${styles} |${loaded} | $hits/$TRIALS |"
    if [ "$key" = control ]; then
        [ "$hits" -eq 0 ] || CONTROL_LEAK=1
        [ "${styles# }" = default ] || CONTROL_LEAK=1
    fi
    case "$loaded" in *no*) FAILED=1 ;; esac
done <<< "$CASES"

echo
if [ "$FAILED" -ne 0 ]; then
    echo "verdict: INCONCLUSIVE — the fixture plugin was not loaded in every session"
    exit 2
fi
if [ "$CONTROL_LEAK" -ne 0 ]; then
    echo "verdict: CONTAMINATED — the control saw a style. --setting-sources did not keep"
    echo "         the developer's own outputStyle out, so no row above can be trusted."
    exit 1
fi
echo "verdict: read the table. A row at $TRIALS/$TRIALS is a name the platform resolves;"
echo "         0/$TRIALS beside a name the init event still echoes is a name it does not."
