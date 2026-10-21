"""safe_command.py — is this Bash command one nobody needs to be asked about?

Used by hooks/autopilot-pretool.py to answer `permissionDecision: "allow"` for
commands that cannot destroy anything, so a session stops pausing for a
confirmation of `git commit` or `ls`. scripts/probes/hook-allow.sh measured that
such an allow is honoured, that a deny rule still beats it, and that it works in
a directory nobody has trusted — the gap a static allowlist cannot close.

── The one rule that shapes everything here ─────────────────────────────────

IT ERRS ONLY TOWARDS ASKING. `classify` returns a reason to allow, or None. None
is not a refusal: it is silence, and the platform's normal permission prompt
decides. So a command this module fails to understand costs one prompt, and a
command it wrongly understands costs whatever the command does. Every branch
below picks the first failure.

Concretely:

  * a chain (`&&`, `||`, `;`, `|`, newline) is allowed only if EVERY segment is.
    Chaining is not what makes a command dangerous; an unsafe segment is.
  * command substitution, backticks, variable expansion, redirection to a file,
    subshells, background jobs, and env-var prefixes are never allowed: each one
    can run or write something the words on the line do not show. The single
    exception is the quoted heredoc Claude Code writes commit messages with,
    `"$(cat <<'EOF' … EOF)"`, whose body the shell does not expand.
  * a command is judged by an explicit list of what it may do, never by a list
    of what it may not. An unknown command, subcommand or `git` global option
    is not allowed.

The list lives in the plugin, not the project, on purpose: the model can edit
`.efficiency/policy.md`, and a list it could extend would be the model holding
its own leash. A project can only switch the whole thing off (`auto_allow: off`).
"""

import re

# The commit-message idiom: a substitution whose only content is a heredoc with a
# QUOTED delimiter, which the shell passes through verbatim. Removed before the
# scan so backticks and `$` in a message body do not force a prompt per commit.
HEREDOC_HEAD = re.compile(r"""\$\(\s*cat\s+<<(-?)\s*(['"])(\w+)\2[ \t]*\n""")

# Redirections that write nowhere a developer would miss.
HARMLESS_REDIRECT = re.compile(r"(?:\s|^)(?:[12]?>\s*/dev/null|2>&1|[12]>&[12])(?=\s|$)")

# Commands that only read, whatever their arguments — with the flags that would
# make an exception listed per command.
READ_ONLY = {
    "ls": (), "cat": (), "head": (), "tail": (), "wc": (), "pwd": (), "which": (),
    "echo": (), "grep": (), "egrep": (), "fgrep": (),
    "stat": (), "du": (), "df": (), "diff": (), "cut": (), "tr": (),
    "basename": (), "dirname": (), "realpath": (),
    "whoami": (), "uname": (), "true": (), "cd": (), "jq": (),
    "find": ("-delete", "-exec", "-execdir", "-ok", "-okdir",
             "-fprint", "-fprint0", "-fprintf", "-fls"),
    "rg": ("--pre",),
}

# Where a glob may expand: only where no flag is dangerous. Not `find`, `rg` or
# `git`, where a file named `-delete`, `--pre=…` or `-D` would arrive as a flag the
# words on the line never showed.
GLOB_OK = set(c for c, banned in READ_ONLY.items() if not banned) - {"cd"}

# git global options allowed before the subcommand, and whether each takes a value.
# `-c` is absent on purpose: a config override can name a program to run.
GIT_GLOBAL = {"-C": True, "--no-pager": False, "--no-optional-locks": False}

# Flags that make any git subcommand write a file of the caller's choosing.
GIT_WRITES_FILE = ("--output",)


def _flags(args):
    """Every short flag letter and every long flag, from an argument list."""
    short, long_ = set(), set()
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            long_.add(a.split("=", 1)[0])
        elif a.startswith("-") and len(a) > 1:
            short.update(a[1:])
    return short, long_


def _positional(args):
    return [a for a in args if not a.startswith("-")]


def _git_sub(sub, args):
    """A reason to allow `git <sub> <args>`, or None."""
    short, long_ = _flags(args)
    if any(f in long_ for f in GIT_WRITES_FILE):
        return None

    if sub in ("status", "diff", "log", "show", "blame", "rev-parse", "ls-files",
               "ls-tree", "shortlog", "describe", "grep", "cat-file", "merge-base",
               "rev-list", "show-ref", "name-rev", "check-ignore", "count-objects",
               "show-branch"):
        return "git %s only reads" % sub

    if sub == "reflog":
        pos = _positional(args)
        return "git reflog only reads" if not pos or pos[0] == "show" else None

    if sub == "config":
        reads = {"--get", "--get-all", "--get-regexp", "--list", "--show-origin"}
        return "git config is reading" if (long_ & reads or "l" in short) else None

    if sub == "remote":
        pos = _positional(args)
        return "git remote is listing" if not pos or pos[0] in ("show", "get-url") else None

    if sub == "add":
        return "git add only stages; the index undoes"

    if sub == "commit":
        return "git commit is local; the reflog undoes it"

    if sub == "stash":
        pos = _positional(args)
        if pos and pos[0] in ("drop", "clear"):
            return None
        return "git stash keeps the work"

    if sub == "branch":
        if short & set("dDfMC") or long_ & {"--delete", "--force"}:
            return None
        return "git branch creates or lists"

    if sub == "tag":
        if short & set("df") or long_ & {"--delete", "--force"}:
            return None
        return "git tag creates or lists, locally"

    if sub == "switch":
        if short & set("fC") or long_ & {"--force", "--discard-changes", "--force-create"}:
            return None
        return "git switch refuses to discard work"

    if sub == "checkout":
        # `git checkout <x>` is a branch switch or a discard of local edits, and
        # the two are indistinguishable from the words alone. Only branch creation is.
        if short == {"b"} and not long_ and len(_positional(args)) in (1, 2):
            return "git checkout -b creates a branch"
        return None

    if sub == "fetch":
        if "f" in short or "--force" in long_:
            return None
        return "git fetch only updates remote-tracking refs"

    if sub == "pull":
        if short & set("fr") or long_ & {"--force", "--rebase"}:
            return None
        return "git pull merges, and a merge undoes"

    if sub == "push":
        if short & set("fd") or long_ & {"--force", "--force-with-lease",
                                          "--force-if-includes", "--delete",
                                          "--mirror", "--prune"}:
            return None
        # A refspec can force (`+main`) or delete (`:main`) without any flag.
        if any(p.startswith("+") or ":" in p and p.split(":", 1)[0] == "" or ":+" in p
               for p in _positional(args)):
            return None
        return "git push without force adds to the remote and rewrites nothing"

    return None


def _segment(words, globbed):
    """A reason to allow one simple command, or None."""
    if not words:
        return None
    cmd, args = words[0], words[1:]
    if "=" in cmd:
        return None          # an env prefix: GIT_DIR=…, PAGER=…, LD_PRELOAD=…
    if globbed and cmd not in GLOB_OK:
        return None

    if cmd in READ_ONLY:
        banned = READ_ONLY[cmd]
        if any(a.split("=", 1)[0] in banned for a in args):
            return None
        return "%s only reads" % cmd

    if cmd == "git":
        i = 0
        while i < len(args) and args[i].startswith("-"):
            opt = args[i]
            if opt not in GIT_GLOBAL:
                return None
            i += 2 if GIT_GLOBAL[opt] else 1
        if i >= len(args):
            return None
        return _git_sub(args[i], args[i + 1:])

    return None


def _heredoc_end(command, i):
    """Where a quoted-heredoc substitution starting at `command[i]` ends, or None.

    Called only at a `$` the shell would expand — never inside single quotes —
    which is what makes discarding the body sound: recognised anywhere else, a
    body could close a quote and run. The terminator is found the way the shell
    finds it, the FIRST line that is exactly the delimiter (leading tabs
    stripped under `<<-`), and what follows must be nothing but the closing
    parenthesis. Anything that does not fit exactly is None, and the `$` refuses.
    """
    m = HEREDOC_HEAD.match(command, i)
    if not m:
        return None
    dash, delim = m.group(1), m.group(3)
    j = m.end()
    while True:
        nl = command.find("\n", j)
        line = command[j:] if nl < 0 else command[j:nl]
        if (line.lstrip("\t") if dash else line) == delim:
            after = len(command) if nl < 0 else nl + 1
            close = re.match(r"\s*\)", command[after:])
            return after + close.end() if close else None
        if nl < 0:
            return None
        j = nl + 1


def _split(command):
    """The command as (words, globbed) per simple command, or None if any part is unsafe.

    A character-level scan with quote state, because the danger signs mean
    different things inside and outside quotes: a `;` in a commit message is
    text, a `$(` in double quotes runs.
    """
    segments, current, word = [], [], []
    state = {"quote": None, "in_word": False, "globbed": False}
    i, n = 0, len(command)

    def end_word():
        if state["in_word"]:
            current.append("".join(word))
            word.clear()
            state["in_word"] = False

    def end_segment():
        end_word()
        if not current:
            return False         # an empty segment: `&& &&`, a leading `|`
        segments.append((list(current), state["globbed"]))
        current.clear()
        state["globbed"] = False
        return True

    while i < n:
        c = command[i]
        quote = state["quote"]
        if quote == "'":
            if c == "'":
                state["quote"] = None
            else:
                word.append(c)
            i += 1
            continue
        if c == "$":
            end = _heredoc_end(command, i)
            if end is None:
                return None      # substitution or expansion, quoted or not
            word.append("MESSAGE")
            state["in_word"] = True
            i = end
            continue
        if c == "`":
            return None
        if quote == '"':
            if c == '"':
                state["quote"] = None
            elif c == "\\" and i + 1 < n and command[i + 1] in '"\\':
                word.append(command[i + 1])
                i += 1
            else:
                word.append(c)
            i += 1
            continue
        # unquoted
        if c in "'\"":
            state["quote"] = c
            state["in_word"] = True
        elif c == "\\":
            if i + 1 < n and command[i + 1] != "\n":
                word.append(command[i + 1])
                state["in_word"] = True
            i += 1               # an escaped newline is a line continuation
        elif c in " \t":
            end_word()
        elif c in "\n;":
            if (current or state["in_word"]) and not end_segment():
                return None
        elif c == "|":
            if i + 1 < n and command[i + 1] == "|":
                i += 1
            if not end_segment():
                return None
        elif c == "&":
            if i + 1 < n and command[i + 1] == "&":
                i += 1
                if not end_segment():
                    return None
            else:
                return None      # a background job
        elif c in "<>(){}":
            return None          # redirection, subshell, brace group
        elif c == "#" and not state["in_word"]:
            return None          # a comment hides the rest of the line from this scan
        else:
            if c in "*?[":
                state["globbed"] = True
            word.append(c)
            state["in_word"] = True
        i += 1

    if state["quote"]:
        return None
    end_word()
    if current:
        segments.append((list(current), state["globbed"]))
    return segments or None


def classify(command):
    """A short reason this command can run unasked, or None to let the platform ask."""
    if not isinstance(command, str) or not command.strip() or len(command) > 20000:
        return None
    text = HARMLESS_REDIRECT.sub(" ", command)
    segments = _split(text)
    if not segments:
        return None
    reasons = []
    for words, globbed in segments:
        reason = _segment(words, globbed)
        if reason is None:
            return None
        reasons.append(reason)
    return "; ".join(dict.fromkeys(reasons))
