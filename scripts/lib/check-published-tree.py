#!/usr/bin/env python3
"""What a consumer receives must be what was validated.

`scripts/check-install.sh` validates the chain — policy, enablement, install,
hooks, status line — against the plugin **as it sits on this disk**. A consumer
never sees this disk. They resolve the `ref` in `.claude-plugin/marketplace.json`
and receive the tree at that tag, and nothing until now compared the two.

The gap is not theoretical, it is the shape of every expensive failure this repo
has had: silence. A shipped file that is untracked or gitignored works perfectly
here and is simply absent there. The hook it belongs to does not error — Claude
Code runs the ones it finds, and the missing one leaves no trace at all. The same
goes for a hook wired in `hooks/hooks.json` to a path that was never committed.

So this asks three questions about trees rather than about files on disk:

  * **is everything we ship committed?** Every file under the shipped roots that
    exists on disk must exist in `HEAD`. Checked against `HEAD` and not only
    against the tag, so the answer arrives at the commit that introduces the
    problem rather than one release later.
  * **is the published tree wired to itself?** Every `${CLAUDE_PLUGIN_ROOT}/…`
    path named in that tree's own `hooks/hooks.json` must exist *in that tree*.
    A manifest is a promise about a directory the consumer will have.
  * **does the published tree know its own version?** The `plugin.json` inside
    the tag must say what the tag says. A tag moved by hand fails here.

`--remote` adds the fourth: the tag object `origin` serves for that ref must be
the one we have. A force-pushed tag is the one way the ref can resolve for a
consumer and still not be what was validated.

Exit codes, for `scripts/qa.sh`: 0 the published tree is what was checked, 1 it
is not, 3 nothing could be compared — no git, or the pinned tag does not exist
yet because the release is in flight.
"""

import json
import os
import re
import subprocess
import sys

# The shipped roots, as `CLAUDE.md`'s table defines them: everything a consumer
# session loads. `scripts/`, `docs/` and `CLAUDE.md` are deliberately absent —
# they never travel.
SHIPPED = ("AUTONOMY-CHARTER.md", "agents", "skills", "hooks", "templates", ".claude-plugin")

# Build artefacts and editor droppings are not shipped files that went missing.
JUNK = re.compile(r"(^|/)(__pycache__|\.DS_Store)(/|$)|\.pyc$")

PLUGIN_ROOT = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"'\s]+)")
MARKETPLACE = ".claude-plugin/marketplace.json"


def git(*args, timeout=10):
    try:
        out = subprocess.run(("git",) + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def tree_files(ref):
    """Every path in `ref`, as the consumer would receive it."""
    listing = git("ls-tree", "-r", "--name-only", ref)
    return None if listing is None else set(listing.splitlines())


def disk_files():
    """Every shipped file present on this disk, junk excluded."""
    found = set()
    for root in SHIPPED:
        if os.path.isfile(root):
            found.add(root)
            continue
        for here, _, names in os.walk(root):
            for name in names:
                path = os.path.join(here, name).replace(os.sep, "/")
                if not JUNK.search(path):
                    found.add(path)
    return found


def wired_paths(ref):
    """The plugin-root-relative paths `ref`'s own hooks.json names, and why not.

    The JSON is decoded rather than scanned as text. Scanning the raw file reads
    the backslash of an escaped `\\"` as part of the command, so every path came
    back with a trailing backslash and every hook looked missing — a guard
    inventing three failures rather than finding one. Caught by case 4 below,
    which is why the passing case is a case.
    """
    raw = git("show", "%s:hooks/hooks.json" % ref)
    if raw is None:
        return None, "has no hooks/hooks.json, so none of its hooks are wired"
    try:
        doc = json.loads(raw)
    except ValueError as exc:
        return None, "has a hooks/hooks.json that is not valid JSON (%s)" % exc

    found = set()

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            found.update(PLUGIN_ROOT.findall(node))

    walk(doc)
    return found, None


def pinned_ref():
    try:
        with open(MARKETPLACE) as handle:
            source = json.load(handle)["plugins"][0]["source"]
    except (OSError, ValueError, KeyError, IndexError):
        return None
    return source.get("ref") if isinstance(source, dict) else None


def check(remote=False):
    if git("rev-parse", "--git-dir") is None:
        print("not a git checkout, so no published tree can be compared")
        return 3

    problems = []

    # ── 1. everything we ship is committed ──────────────────────────────────
    head = tree_files("HEAD")
    if head is None:
        print("git could not read HEAD, so nothing was compared")
        return 3
    uncommitted = sorted(disk_files() - head)
    for path in uncommitted:
        problems.append("%s is shipped but absent from HEAD — a consumer would not receive it"
                        % path)

    # ── 2 and 3, against the tree a consumer actually resolves ──────────────
    ref = pinned_ref()
    if not ref:
        print("%s pins no ref, so there is no published tree to compare" % MARKETPLACE)
        return 3

    published = tree_files(ref)
    if published is None:
        if problems:
            return report(problems)
        print("%s is pinned but not yet cut, so only HEAD could be compared; "
              "%d shipped file(s) all committed" % (ref, len(disk_files())))
        return 3

    wired, why = wired_paths(ref)
    if wired is None:
        problems.append("%s %s" % (ref, why))
    else:
        for path in sorted(wired):
            if path not in published:
                problems.append("%s wires %s, which is not in that tree — the hook would be "
                                "silently absent" % (ref, path))

    declared = git("show", "%s:.claude-plugin/plugin.json" % ref)
    if declared is None:
        problems.append("%s has no .claude-plugin/plugin.json" % ref)
    else:
        try:
            version = json.loads(declared).get("version")
        except ValueError:
            version = None
        want = ref[1:] if ref.startswith("v") else ref
        if version != want:
            problems.append("%s contains a plugin.json declaring %s — the tag and the tree "
                            "disagree about which release this is" % (ref, version or "nothing"))

    # ── 4. the remote serves the tag we verified ────────────────────────────
    if remote and not problems:
        mine = git("rev-parse", ref)
        theirs = git("ls-remote", "origin", "refs/tags/" + ref, timeout=30)
        if theirs is None or mine is None:
            print("%s verified locally; origin could not be reached, so whether it serves the "
                  "same tag is unknown" % ref)
            return 3
        if not theirs:
            problems.append("origin serves no %s, so the catalogue points at nothing" % ref)
        elif theirs.split()[0] != mine:
            problems.append("origin serves a different %s (%s) than this checkout has (%s) — "
                            "the ref resolves, to something nobody validated"
                            % (ref, theirs.split()[0][:7], mine[:7]))

    if problems:
        return report(problems)

    print("%s is complete: %d shipped file(s) committed, %d wired path(s) present, and its "
          "plugin.json agrees with the tag%s"
          % (ref, len(disk_files()), len(wired or ()), ", as served by origin" if remote else ""))
    return 0


def report(problems):
    print("the tree a consumer resolves is not the tree that was validated:", file=sys.stderr)
    for line in problems:
        print("  " + line, file=sys.stderr)
    print("check-install.sh validates this disk; consumers get the pinned ref. They must match.",
          file=sys.stderr)
    return 1


# ── selftest ─────────────────────────────────────────────────────────────────

def _run(*args, cwd=None):
    subprocess.run(("git",) + args, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


HOOKS = json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command",
         "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/autopilot-stop.py"'}]}]}})


def _plugin(tmp, version="0.1.0", hooks=HOOKS):
    """A minimal but complete shipped layout, committed and tagged."""
    for rel, body in (("hooks/hooks.json", hooks),
                      ("hooks/autopilot-stop.py", "#\n"),
                      ("agents/reviewer.md", "x\n"),
                      ("skills/run/SKILL.md", "x\n"),
                      ("templates/efficiency.md", "x\n"),
                      ("AUTONOMY-CHARTER.md", "x\n"),
                      (".claude-plugin/plugin.json", json.dumps({"version": version})),
                      (MARKETPLACE, json.dumps(
                          {"plugins": [{"source": {"ref": "v" + version}}]}))):
        full = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as handle:
            handle.write(body)
    _run("init", "-q", "-b", "main", cwd=tmp)
    _run("config", "user.email", "t@t", cwd=tmp)
    _run("config", "user.name", "t", cwd=tmp)
    _run("add", "-A", cwd=tmp)
    _run("commit", "-qm", "release", cwd=tmp)
    _run("tag", "-a", "v" + version, "-m", "x", cwd=tmp)


def _verdict(tmp):
    import contextlib
    import io
    here = os.getcwd()
    try:
        os.chdir(tmp)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            return check(remote=False)
    finally:
        os.chdir(here)


def selftest():
    import shutil
    import tempfile
    failures, cases = [], []

    # 1. a shipped file that never reached the tree — gitignored, which is how
    #    it happens: it works perfectly here and does not exist there.
    tmp = tempfile.mkdtemp()
    _plugin(tmp)
    with open(os.path.join(tmp, ".gitignore"), "w") as handle:
        handle.write("hooks/statusline.py\n")
    with open(os.path.join(tmp, "hooks", "statusline.py"), "w") as handle:
        handle.write("#\n")
    _run("add", "-A", cwd=tmp)
    _run("commit", "-qm", "ignore it", cwd=tmp)
    cases.append(("a shipped file that is gitignored", tmp, 1))

    # 2. a hook wired to a path the published tree does not contain.
    tmp = tempfile.mkdtemp()
    _plugin(tmp, hooks=json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command",
            "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/never-committed.py"'}]}]}}))
    cases.append(("a hook wired to a path not in the tree", tmp, 1))

    # 3. the tag and the tree disagreeing about which release this is.
    tmp = tempfile.mkdtemp()
    _plugin(tmp, version="0.1.0")
    with open(os.path.join(tmp, MARKETPLACE), "w") as handle:
        json.dump({"plugins": [{"source": {"ref": "v0.2.0"}}]}, handle)
    _run("add", "-A", cwd=tmp)
    _run("commit", "-qm", "pin 0.2.0", cwd=tmp)
    _run("tag", "-a", "v0.2.0", "-m", "x", cwd=tmp)
    cases.append(("a tag whose tree declares another version", tmp, 1))

    # 4. complete and consistent.
    tmp = tempfile.mkdtemp()
    _plugin(tmp)
    cases.append(("a published tree that matches the disk", tmp, 0))

    for name, path, want in cases:
        got = _verdict(path)
        if got != want:
            failures.append("%s: expected exit %d, got %d" % (name, want, got))
        shutil.rmtree(path, ignore_errors=True)

    if failures:
        for line in failures:
            print("selftest FAIL " + line, file=sys.stderr)
        return 1
    print("selftest: %d case(s) — an uncommitted artefact, a dangling hook path and a "
          "mislabelled tree each stop the gate" % len(cases))
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--selftest" in sys.argv[1:]:
        return selftest()
    if args and os.path.isdir(args[0]):
        os.chdir(args[0])
    return check(remote="--remote" in sys.argv[1:])


if __name__ == "__main__":
    sys.exit(main())
