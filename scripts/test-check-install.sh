#!/bin/bash
# test-check-install.sh — prove the validator can fail.
#
# A validator that cannot report a problem is worse than none: it tells you the
# install is fine about nothing at all. The first version of check-install.sh did
# exactly that — it reported CONFORMANT for a project where the plugin was not
# installed, because it only ever looked at the project's own files.
#
# Each case builds a throwaway project, runs the validator, and asserts on the
# verdict and on the line that should have produced it. Nothing outside mktemp is
# touched and no model is called.

set -uo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
VALIDATOR="$HERE/check-install.sh"
FAILED=0
RAN=0

# Enablement needs BOTH a settings file and a registry entry — measured by
# removing each in turn. A fixture that writes only settings describes a project
# where the plugin does not actually load, which is how these tests used to pass
# on a false premise.
enable_in() {
    mkdir -p "$1/.claude"
    printf '{"enabledPlugins":{"efficiency@claude-efficiency-framework":true}}' \
        > "$1/.claude/settings.json"
    REGISTRY="$1/registry.json" PROJECT="$1" python3 - <<'PY'
import json, os
json.dump({"version": 2, "plugins": {"efficiency@claude-efficiency-framework": [
    {"scope": "project", "projectPath": os.path.realpath(os.environ["PROJECT"]),
     "version": "0.0.0-test"}]}}, open(os.environ["REGISTRY"], "w"))
PY
}

new_project() {
    local d
    d=$(mktemp -d) || return 1
    git -C "$d" init -q
    mkdir -p "$d/.efficiency"
    printf '.efficiency/run.md\n.efficiency/autopilot.json\n.efficiency/tools.md\n' > "$d/.gitignore"
    printf '%s' "$d"
}

good_policy() {
    cat > "$1/.efficiency/policy.md" <<'POLICY'
---
gate: "bash gate.sh"
budget: { continuations: 20 }
tiers: { critical: [] }
routing: { standard: { implement: sonnet } }
stop_for: [irreversible_or_outward_facing]
---

# Declared defaults

- a default that is actionable without context
POLICY
    printf '#!/bin/bash\nexit 0\n' > "$1/gate.sh"
    chmod +x "$1/gate.sh"
}

# check <name> <expected-verdict 0|1> <grep pattern> <project dir>
check() {
    local name="$1" want="$2" pattern="$3" dir="$4" out code
    RAN=$((RAN + 1))
    # Point the validator at the fixture's registry when it has one, so these
    # tests never read — or need — the machine's real plugin state.
    if [ -f "$dir/registry.json" ]; then
        out=$(EFFICIENCY_REGISTRY="$dir/registry.json" "$VALIDATOR" "$dir" 2>&1); code=$?
    else
        out=$(EFFICIENCY_REGISTRY="$dir/absent.json" "$VALIDATOR" "$dir" 2>&1); code=$?
    fi
    if [ "$code" != "$want" ]; then
        printf '  FAIL  %s\n        expected exit %s, got %s\n' "$name" "$want" "$code"
        FAILED=$((FAILED + 1))
    elif ! printf '%s' "$out" | grep -q "$pattern"; then
        printf '  FAIL  %s\n        exit was right but no line matched: %s\n' "$name" "$pattern"
        FAILED=$((FAILED + 1))
    else
        printf '  ok    %s\n' "$name"
    fi
    rm -rf "$dir"
}

printf '\ncheck-install validator tests\n\n'

# A fully correct install must pass, or every failure below proves nothing.
D=$(new_project); enable_in "$D"; good_policy "$D"
( cd "$D" && git add -A && git -c user.email=t@t -c user.name=t commit -qm init )
check "a correct install is conformant" 0 "CONFORMANT" "$D"

# The case the first validator got wrong.
D=$(new_project); good_policy "$D"
check "perfect files but the plugin is not enabled" 1 "not enabled for this project" "$D"

# Each half alone is a different mistake, and each has a different fix.
D=$(new_project); good_policy "$D"
mkdir -p "$D/.claude"
printf '{"enabledPlugins":{"efficiency@claude-efficiency-framework":true}}' > "$D/.claude/settings.json"
check "settings enable it but this machine has no install" 1 "no install" "$D"

D=$(new_project); enable_in "$D"; good_policy "$D"
rm -f "$D/gate.sh"
check "the gate points at a script that does not exist" 1 "does not exist" "$D"

D=$(new_project); enable_in "$D"
printf -- '---\nbudget: {}\n---\n' > "$D/.efficiency/policy.md"
check "no gate declared" 1 "no gate declared" "$D"

D=$(new_project); enable_in "$D"
printf 'no frontmatter at all\n' > "$D/.efficiency/policy.md"
check "policy without frontmatter" 1 "no frontmatter" "$D"

D=$(new_project); enable_in "$D"; good_policy "$D"
mkdir -p "$D/.claude"; printf -- '---\ngate: "x"\n---\n' > "$D/.claude/efficiency.md"
check "a leftover legacy file does not hijack a working install" 0 "CONFORMANT" "$D"

D=$(new_project); enable_in "$D"
mkdir -p "$D/.claude"; printf -- '---\ngate: "make check"\n---\n' > "$D/.claude/efficiency.md"
check "a pre-0.4.0 install is reported, not passed" 1 "predates 0.4.0" "$D"

D=$(new_project); enable_in "$D"; good_policy "$D"
printf '' > "$D/.gitignore"
check "run state that would be committed" 1 "is not gitignored" "$D"

D=$(mktemp -d)
check "a project that never adopted is not a failure" 0 "has not adopted" "$D"

printf '\n%d checks, %d failed\n\n' "$RAN" "$FAILED"
[ "$FAILED" -eq 0 ] || exit 1
