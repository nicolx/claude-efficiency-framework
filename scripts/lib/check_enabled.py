#!/usr/bin/env python3
"""Is this plugin actually enabled for the given project?

The check that was missing from the first validator, and the one that makes every
other check mean something: a perfect `.efficiency/` in a project where nothing is
enabled is a project where nothing happens.

Prints one line: `enabled:<why>` or `disabled:<why>`. Reads only; no network.

Enablement needs BOTH halves, measured by removing each in turn:

  * a settings file saying so — the project's own `.claude/settings.json` (what
    `--scope project` writes and what you commit), or the user's for every
    project on the machine;
  * a matching entry in `~/.claude/plugins/installed_plugins.json`, the registry
    the CLI keeps, which also records the installed VERSION.

| settings | registry | loads? |
|---|---|---|
| yes | yes | **yes** |
| yes | no  | no |
| no  | yes | no |

That is why committing `enabledPlugins` is not enough on its own: a cloned
repository declares the intent, and `claude plugin install` on each machine is
the consent. A repository that could enable a hook-running plugin by itself would
be one that runs code the moment you clone it.
"""

import json
import os
import sys

PLUGIN_KEY_SUFFIX = "@claude-efficiency-framework"


def load(path):
    try:
        with open(path, errors="replace") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def enabled_in(settings):
    """The enabled plugin key from one settings file, if any."""
    plugins = settings.get("enabledPlugins")
    if not isinstance(plugins, dict):
        return None
    for key, on in plugins.items():
        if on and key.endswith(PLUGIN_KEY_SUFFIX):
            return key
    return None


def main():
    root = os.path.realpath(os.environ.get("ROOT", "."))
    home = os.path.expanduser("~")

    project_key = enabled_in(load(os.path.join(root, ".claude", "settings.json")))
    user_key = enabled_in(load(os.path.join(home, ".claude", "settings.json")))

    # The registry carries the version, and one entry per project path.
    # EFFICIENCY_REGISTRY overrides its location so the validator's own tests can
    # point at a fixture instead of the machine's real registry — a test that
    # mutated that file would be a test nobody dares run twice.
    version, scope = None, None
    registry_path = os.environ.get("EFFICIENCY_REGISTRY") or os.path.join(
        home, ".claude", "plugins", "installed_plugins.json")
    registry = load(registry_path)
    for name, entries in (registry.get("plugins") or {}).items():
        if not name.endswith(PLUGIN_KEY_SUFFIX) or not isinstance(entries, list):
            continue
        for e in entries:
            if not isinstance(e, dict):
                continue
            path = e.get("projectPath")
            if e.get("scope") == "user" or (path and os.path.realpath(path) == root):
                version, scope = e.get("version"), e.get("scope")
                break

    declared = project_key or user_key
    where = ("committed in .claude/settings.json" if project_key
             else "user scope, every project on this machine")

    if declared and version:
        print("enabled:%s; installed version %s, scope %s" % (where, version, scope))
        return 0

    # Each half alone is a different mistake with a different fix, so they are
    # reported apart rather than as one vague "not enabled".
    if declared and not version:
        print("disabled:a settings file enables it (%s) but this machine has no install — "
              "committed settings declare intent, `claude plugin install` is the consent" % where)
        return 0

    if version and not declared:
        print("disabled:the CLI has it installed (version %s, scope %s) but no settings file "
              "enables it" % (version, scope))
        return 0

    print("disabled:the plugin is not enabled for this project, so none of its hooks run here")
    return 0


if __name__ == "__main__":
    sys.exit(main())
