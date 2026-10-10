#!/usr/bin/env python3
"""Is this plugin actually enabled for the given project?

The check that was missing from the first validator, and the one that makes every
other check mean something: a perfect `.efficiency/` in a project where nothing is
enabled is a project where nothing happens.

Prints one line: `enabled:<why>` or `disabled:<why>`. Reads only; no network.

Enablement can come from three places, and any one of them is enough:

  * the project's own `.claude/settings.json` — `enabledPlugins`, committed, which
    is what `--scope project` writes;
  * the user's `~/.claude/settings.json` — the default scope, covering every
    project on the machine;
  * `~/.claude/plugins/installed_plugins.json`, the registry the CLI keeps, whose
    per-project entries are the only place the installed VERSION is recorded.
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
    version, scope = None, None
    registry = load(os.path.join(home, ".claude", "plugins", "installed_plugins.json"))
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

    detail = []
    if project_key:
        detail.append("enabled for this project (committed in .claude/settings.json)")
    elif user_key:
        detail.append("enabled for every project on this machine (user scope)")
    if version:
        detail.append("installed version %s, scope %s" % (version, scope))

    if project_key or user_key:
        print("enabled:" + "; ".join(detail))
        return 0

    if version:
        # Registered but not switched on: the CLI recorded an install and no
        # settings file enables it. Worth distinguishing — the fix is different.
        print("disabled:the CLI has it installed (version %s, scope %s) but no settings file "
              "enables it" % (version, scope))
        return 0

    print("disabled:the plugin is not enabled for this project, so none of its hooks run here")
    return 0


if __name__ == "__main__":
    sys.exit(main())
