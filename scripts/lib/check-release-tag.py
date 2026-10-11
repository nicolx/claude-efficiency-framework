#!/usr/bin/env python3
"""A released version must have the tag its catalogue pins, and the tag must exist.

`scripts/qa.sh` already holds `VERSION`, `plugin.json`, the marketplace `ref`, the
marketplace `version` field and the changelog heading together. All five live in
the working tree, so all five can agree with each other while saying nothing
about whether the release exists — and they did. Measured 2026-10-11: six
consecutive versions, 0.14.0 through 0.18.1, had been committed with changelog
entries announcing them and were never tagged, never pushed. The gate was green
on every one of them, and `origin` still served 0.13.0, because nothing in the
gate ever asked git a question.

The README said the opposite in so many words — "the gate refuses to let a
release ship whose tag, VERSION and changelog entry disagree" — which is how a
missing step stays missing: it was written down as already solved.

So this check asks git, not JSON:

  * **a version `VERSION` once held, but which has no tag, is a defect.** The
    release was committed and its manifest published; the thing consumers
    resolve was never created. Red.
  * **a tag that exists but points somewhere else is a defect.** `git show
    vX:VERSION` must read X, and the tag must be an ancestor of HEAD. A tag on
    a detached experiment is worse than no tag: it resolves, and it ships the
    wrong tree. Red.
  * **the version currently in flight being untagged is normal.** The commit
    that bumps to X cannot already carry a tag pointing at itself. Amber, with
    the command that cuts it.

The in-flight exemption leaves exactly one release's worth of hole: bump to X,
never tag, and nothing complains until the bump to Y. `scripts/release.sh`
closes it at the only moment that matters, and the next bump catches it anyway.

`--remote` additionally asks the origin whether the tag was pushed, which is the
failure that actually happened: three tags existed locally and none had left the
machine. It needs the network, so it is opt-in — the gate stays runnable offline
and `release.sh` passes it.

Exit codes, for `scripts/qa.sh`: 0 every released version tagged and placed,
1 a tag is missing or misplaced, 3 nothing is wrong but something went
unchecked — no git, or only the in-flight version is untagged.
"""

import json
import os
import re
import subprocess
import sys

RELEASE = re.compile(r"^\d+\.\d+\.\d+$")
MARKETPLACE = os.path.join(".claude-plugin", "marketplace.json")


def git(*args, timeout=10):
    """Return stdout stripped, or None if git failed or is not there."""
    try:
        out = subprocess.run(("git",) + args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def version_at(ref):
    return git("show", "%s:VERSION" % ref)


def released_versions():
    """Every value VERSION has held on the way to HEAD, oldest first.

    A value is 'held' at the commit that introduced it: VERSION reads X there and
    did not in its parent. Pre-release placeholders (`1.0.0-dev`) are not
    releases and are skipped — nobody ever pinned one.
    """
    log = git("log", "--format=%H", "--", "VERSION")
    if log is None:
        return None
    found = []
    seen = set()
    for commit in log.splitlines():
        here = version_at(commit)
        if not here or not RELEASE.match(here) or here in seen:
            continue
        parent = version_at(commit + "^")  # None at the root commit, which counts as a change
        if parent != here:
            seen.add(here)
            found.append((here, commit))
    found.reverse()
    return found


def pinned_ref():
    """The ref the catalogue tells consumers to resolve, or None."""
    try:
        with open(MARKETPLACE) as handle:
            source = json.load(handle)["plugins"][0]["source"]
    except (OSError, ValueError, KeyError, IndexError):
        return None
    return source.get("ref") if isinstance(source, dict) else None


def check(remote=False):
    if git("rev-parse", "--git-dir") is None:
        print("not a git checkout, so no tag can be verified")
        return 3

    try:
        with open("VERSION") as handle:
            current = handle.read().strip()
    except OSError as exc:
        print("cannot read VERSION (%s)" % exc, file=sys.stderr)
        return 1

    history = released_versions()
    if history is None:
        print("git could not read the history of VERSION, so no tag was verified")
        return 3

    local = set(git("tag", "-l").splitlines()) if git("tag", "-l") is not None else set()

    missing, misplaced, checked = [], [], 0
    for version, commit in history:
        tag = "v" + version
        if tag not in local:
            if version == current:
                continue  # in flight: reported below, and not a defect
            missing.append("%s — released in %s, never tagged" % (tag, commit[:7]))
            continue
        at = version_at(tag)
        if at != version:
            misplaced.append("%s points at a tree whose VERSION reads %s" % (tag, at or "nothing"))
        elif git("merge-base", "--is-ancestor", tag + "^{commit}", "HEAD") is None:
            misplaced.append("%s is not an ancestor of HEAD, so it ships a tree this branch "
                             "never had" % tag)
        else:
            checked += 1

    # The catalogue's pin is the one ref a consumer actually resolves, so it is
    # checked by name rather than inferred from VERSION — qa.sh already holds the
    # two together, and a check that trusts that is a check that tests nothing.
    ref = pinned_ref()
    if ref and ref not in local and ref != "v" + current:
        missing.append("%s — pinned by %s, and no such tag exists" % (ref, MARKETPLACE))

    if missing or misplaced:
        print("the catalogue pins tags that do not resolve:", file=sys.stderr)
        for line in missing + misplaced:
            print("  " + line, file=sys.stderr)
        print("a consumer resolves these by name; an absent tag is an install that fails.",
              file=sys.stderr)
        print("cut a past one at its release commit with `git tag -a vX <commit>`; "
              "`bash scripts/release.sh` cuts the current one.", file=sys.stderr)
        return 1

    if remote:
        remote = git("ls-remote", "--tags", "origin", timeout=30)
        if remote is None:
            print("%d tag(s) verified locally; the remote could not be reached, so whether "
                  "they were pushed is unknown" % checked)
            return 3
        pushed = {line.split("refs/tags/")[-1].removesuffix("^{}")
                  for line in remote.splitlines() if "refs/tags/" in line}
        unpushed = [v for v, _ in history if "v" + v in local and "v" + v not in pushed]
        if unpushed:
            print("tag(s) that exist here and nowhere else — a consumer resolves the remote:",
                  file=sys.stderr)
            for version in unpushed:
                print("  v" + version, file=sys.stderr)
            print("push them with: git push origin --tags", file=sys.stderr)
            return 1
        print("%d tag(s) verified, and every one of them is on the remote" % checked)
        return 0

    if "v" + current not in local:
        print("%d released version(s) tagged and placed; %s is in flight and not yet tagged"
              % (checked, current))
        print("cut it with: bash scripts/release.sh")
        return 3

    print("%d released version(s), each tagged at a tree whose VERSION agrees" % checked)
    return 0


# ── selftest ─────────────────────────────────────────────────────────────────
# Rule 4: a guard without a case that shows it firing is decorative. Each case
# below builds a throwaway repository with a real defect in it and asserts the
# verdict, not merely that something was printed.

def _run(*args, cwd=None):
    subprocess.run(("git",) + args, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _repo(tmp, versions):
    """A repository whose VERSION walked through `versions`, one commit each."""
    _run("init", "-q", "-b", "main", cwd=tmp)
    _run("config", "user.email", "t@t", cwd=tmp)
    _run("config", "user.name", "t", cwd=tmp)
    os.makedirs(os.path.join(tmp, ".claude-plugin"), exist_ok=True)
    marks = {}
    for version in versions:
        with open(os.path.join(tmp, "VERSION"), "w") as handle:
            handle.write(version + "\n")
        with open(os.path.join(tmp, MARKETPLACE.replace("/", os.sep)), "w") as handle:
            json.dump({"plugins": [{"source": {"source": "github", "repo": "x/y",
                                               "ref": "v" + version}}]}, handle)
        _run("add", "-A", cwd=tmp)
        _run("commit", "-qm", "release " + version, cwd=tmp)
        marks[version] = subprocess.run(("git", "rev-parse", "HEAD"), cwd=tmp,
                                        capture_output=True, text=True).stdout.strip()
    return marks


def _verdict(tmp):
    here = os.getcwd()
    try:
        os.chdir(tmp)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            return check(remote=False)
    finally:
        os.chdir(here)


def selftest():
    import shutil
    import tempfile
    failures = []

    cases = []

    # 1. a past release with no tag — the defect this guard was written for.
    tmp = tempfile.mkdtemp()
    marks = _repo(tmp, ["0.1.0", "0.2.0", "0.3.0"])
    _run("tag", "-a", "v0.1.0", marks["0.1.0"], "-m", "x", cwd=tmp)
    _run("tag", "-a", "v0.3.0", marks["0.3.0"], "-m", "x", cwd=tmp)
    cases.append(("a released version with no tag", tmp, 1))

    # 2. a tag that exists but ships the wrong tree. Worse than a missing one:
    #    it resolves, so nothing downstream notices.
    tmp = tempfile.mkdtemp()
    marks = _repo(tmp, ["0.1.0", "0.2.0", "0.3.0"])
    _run("tag", "-a", "v0.1.0", marks["0.1.0"], "-m", "x", cwd=tmp)
    _run("tag", "-a", "v0.2.0", marks["0.1.0"], "-m", "x", cwd=tmp)  # wrong commit
    _run("tag", "-a", "v0.3.0", marks["0.3.0"], "-m", "x", cwd=tmp)
    cases.append(("a tag pointing at the wrong tree", tmp, 1))

    # 3. the version in flight, untagged, with nothing after it. Normal, and it
    #    must not be red or every pre-release commit fails the gate.
    tmp = tempfile.mkdtemp()
    marks = _repo(tmp, ["0.1.0", "0.2.0"])
    _run("tag", "-a", "v0.1.0", marks["0.1.0"], "-m", "x", cwd=tmp)
    cases.append(("the version in flight, untagged", tmp, 3))

    # 4. everything cut and placed.
    tmp = tempfile.mkdtemp()
    marks = _repo(tmp, ["0.1.0", "0.2.0"])
    _run("tag", "-a", "v0.1.0", marks["0.1.0"], "-m", "x", cwd=tmp)
    _run("tag", "-a", "v0.2.0", marks["0.2.0"], "-m", "x", cwd=tmp)
    cases.append(("every release tagged and placed", tmp, 0))

    for name, path, want in cases:
        got = _verdict(path)
        if got != want:
            failures.append("%s: expected exit %d, got %d" % (name, want, got))
        shutil.rmtree(path, ignore_errors=True)

    if failures:
        for line in failures:
            print("selftest FAIL " + line, file=sys.stderr)
        return 1
    print("selftest: %d case(s) — a missing tag and a misplaced one both stop the gate, "
          "a release in flight does not" % len(cases))
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
