#!/usr/bin/env python3
"""statusline.py — keep the backlog in front of the developer, permanently.

The backlog was already announced at `SessionStart`, and that was not enough.
Measured on this repo: the charter and the backlog together came to ~18 KB, the
harness truncated the injection to a file with a 2 KB preview, and the text the
model did read told it to mention the backlog *once, in no more than two lines*.
So deferred work was announced once, abbreviated, in the first reply of a
session — and then disappeared for hours.

A status line has the one property that fixes this: it is **re-rendered under
the prompt on every conversation update**, so it cannot scroll away. Measured
with `scripts/probes/statusline.sh` on 2.1.296 — see § 12 of
`docs/verified-platform-behaviour.md`:

  * all five lines a command prints are rendered, not just the first;
  * it is re-run every 0.3-2.5s, on conversation updates rather than per turn,
    so this must stay a single small file read and nothing else;
  * `CLAUDE_PROJECT_DIR` and `COLUMNS` are both set in its environment;
  * a settings change takes effect **live**, without restarting the session —
    unlike a hook, which is bound at session start.

It used to be only about the backlog, on the argument that a status line saying
four things says nothing. That held until it met a real developer: a project's
`statusLine` overrides the one in ~/.claude/settings.json, so adopting the
framework silently took away whatever bar the developer already had — on this
repo's own author, the context gauge they used to decide when to compact. How
full the context is, what the session has spent and how close the five-hour
limit is are efficiency signals, which is this framework's whole subject.

So the first line is the session, the lines below it are the backlog, and the
two never share a line. The session line is printed only when the payload
carries those fields, and it is cut from the least useful end on a narrow
terminal. Nothing here shells out: the branch is read from `.git/HEAD`, and the
dirty marker a `git status` would give is deliberately absent, because it walks
the whole tree on every render.

Never fatal, and never noisy: any failure prints nothing and exits 0, and a
project that never adopted the framework gets no line at all.
"""

import json
import os
import re
import sys

POLICY = os.path.join(".efficiency", "policy.md")
BACKLOG = os.path.join(".efficiency", "backlog.md")

SHOWN = 3
DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*·\s*")
FOUND_WHILE = re.compile(r"\s*·\s*found while:.*$", re.IGNORECASE)

# Where a one-line entry stops being a headline and starts being detail. The
# shipped format is `<what> · found while: <context>`, and in practice the
# `<what>` half carries its own evidence after a colon or a full stop — which is
# exactly the part a permanent reminder must not spend its width on.
BREAK = re.compile(r"(?<=[.:;])\s+|\s+—\s+")
MIN_HEADLINE = 24


# Palette for the session line. Truecolor when the terminal says it renders it,
# the plain eight-colour equivalents otherwise.
PALETTE = {
    "violet": ("#bb9af7", "35"), "blue": ("#7aa2f7", "34"), "cyan": ("#7dcfff", "36"),
    "green": ("#9ece6a", "32"), "yellow": ("#e0af68", "33"), "red": ("#f7768e", "31"),
    "grey": ("#565f89", "2"),
}


def colour_off():
    return bool(os.environ.get("NO_COLOR")) or os.environ.get("TERM", "") == "dumb"


def paint(name, text):
    """`text` in the palette colour `name`, or bare when colour is off."""
    if colour_off():
        return text
    hexa, basic = PALETTE[name]
    if os.environ.get("COLORTERM", "") in ("truecolor", "24bit"):
        code = "38;2;%d;%d;%d" % tuple(int(hexa[i:i + 2], 16) for i in (1, 3, 5))
    else:
        code = basic
    return "\033[%sm%s\033[0m" % (code, text)


def get(payload, *keys):
    for key in keys:
        if not isinstance(payload, dict):
            return None
        payload = payload.get(key)
    return payload


def branch(project):
    """The checked-out branch, read from the file rather than from `git`.

    A worktree's `.git` is a file pointing at the real git dir. A detached HEAD
    shows the short hash.
    """
    gitdir = os.path.join(project, ".git")
    try:
        if os.path.isfile(gitdir):
            with open(gitdir) as fh:
                ref = fh.read().strip()
            if not ref.startswith("gitdir:"):
                return ""
            gitdir = os.path.join(project, ref[len("gitdir:"):].strip())
        with open(os.path.join(gitdir, "HEAD")) as fh:
            head = fh.read().strip()
    except OSError:
        return ""
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/"):]
    return head[:7]


def session_line(payload, project, cols):
    """Model, folder, branch, context, spend, duration, five-hour limit.

    None when the payload carries none of the session fields, so a caller that
    sends a bare payload gets the backlog alone, exactly as before. Each part
    is (priority, plain, painted); on a narrow terminal the lowest priority
    goes first, so the context gauge is the last thing to be dropped.
    """
    parts = []
    model = get(payload, "model", "display_name")
    if model:
        parts.append((2, "◆ " + model, paint("violet", "◆ " + model)))
    folder = os.path.basename(project.rstrip("/"))
    if folder:
        parts.append((6, "▸ " + folder, paint("blue", "▸ " + folder)))
    name = branch(project)
    if name:
        parts.append((5, "⎇ " + name, paint("green", "⎇ " + name)))
    pct = get(payload, "context_window", "used_percentage")
    if pct is not None:
        pct = float(pct)
        tone = "green" if pct < 50 else "yellow" if pct < 80 else "red"
        filled = min(10, max(0, int(round(pct / 10))))
        bar = "█" * filled + "░" * (10 - filled)
        label = "%.0f%%" % pct
        parts.append((1, bar + " " + label,
                      paint(tone, "█" * filled) + paint("grey", "░" * (10 - filled))
                      + " " + paint(tone, label)))
    cost = get(payload, "cost", "total_cost_usd")
    if cost is not None:
        text = "$%.2f" % float(cost)
        parts.append((3, text, paint("cyan", text)))
    ms = get(payload, "cost", "total_duration_ms")
    if ms:
        text = "⏱ %dm" % (int(ms) // 60000)
        parts.append((7, text, paint("grey", text)))
    limit = get(payload, "rate_limits", "five_hour", "used_percentage")
    if limit is not None:
        limit = float(limit)
        text = "5h %.0f%%" % limit
        parts.append((4, text, paint("red" if limit >= 80 else "yellow" if limit >= 50
                                     else "grey", text)))

    # Without any session field this is not a session line, just a folder name.
    if not any(p for p, _, _ in parts if p in (1, 2, 3, 4)):
        return None
    sep = " │ "
    while len(parts) > 1 and len(sep.join(t for _, t, _ in parts)) > cols:
        parts.remove(max(parts, key=lambda part: part[0]))
    return paint("grey", sep).join(painted for _, _, painted in parts)


def colours():
    """ANSI codes, or empty strings when the terminal says not to."""
    if colour_off():
        return "", "", ""
    return "\033[1;33m", "\033[2m", "\033[0m"


def width():
    """Usable columns. COLUMNS is set for this command (measured); 80 if not."""
    try:
        return max(40, int(os.environ.get("COLUMNS", "80")) - 4)
    except ValueError:
        return 76


def open_items(path):
    """(date, headline) for each unclosed entry, in file order.

    Fenced blocks are skipped: the shipped backlog template documents the entry
    format with a real-looking example inside a fence, and counting it reported a
    phantom item on day one. `hooks/session-start.py` skips them for the same
    reason — the two counts have to agree or neither is believed.
    """
    items, fenced = [], False
    with open(path, errors="replace") as fh:
        for line in fh:
            stripped = line.strip()
            if stripped.startswith("```"):
                fenced = not fenced
                continue
            if fenced or not stripped.startswith("- [ ]"):
                continue
            text = stripped[5:].strip()
            match = DATE.match(text)
            date = match.group(1) if match else ""
            if match:
                text = text[match.end():]
            items.append((date, headline(text)))
    return items


def headline(text):
    """The first clause of an entry: what it is, without the evidence for it."""
    text = " ".join(FOUND_WHILE.sub("", text).split())
    for part in BREAK.split(text):
        if part and len(part) >= MIN_HEADLINE:
            return part.rstrip(" .,:;")
        # Too short to stand alone — that colon was inside a path or a skill
        # name, not a sentence boundary. Keep the whole line instead.
        if part:
            return text.rstrip(" .,:;")
    return text


def fit(text, limit):
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}

    project = (os.environ.get("CLAUDE_PROJECT_DIR")
               or payload.get("workspace", {}).get("project_dir")
               or payload.get("cwd") or "")
    if not project or not os.path.isdir(project):
        return 0
    if not os.path.exists(os.path.join(project, POLICY)):
        return 0  # not an adopting project: say nothing at all

    backlog = os.path.join(project, BACKLOG)
    try:
        items = open_items(backlog)
    except OSError:
        return 0

    warn, dim, off = colours()
    cols = width()

    line = session_line(payload, project, cols)
    if line:
        print(line)

    # An empty backlog prints a line too. A status line that goes blank when
    # there is nothing to report is indistinguishable from one that has broken,
    # and this is the surface the developer is being asked to trust continuously.
    if not items:
        print("%s✓ backlog clear%s" % (dim, off))
        return 0

    # The header is assembled rather than formatted, because on a narrow
    # terminal a single `fit()` would amputate the right-hand end — which is
    # where the only actionable thing on the line lives. The count and the
    # command survive; the extras are dropped, least useful first.
    dates = sorted(d for d, _ in items if d)
    head, tail = "⚠ backlog: %d open" % len(items), "/efficiency:backlog"
    extras = []
    if dates:
        extras.append("oldest %s" % dates[0])
    if len(items) > SHOWN:
        extras.append("+%d more" % (len(items) - SHOWN))
    while extras and len(" · ".join([head] + extras + [tail])) > cols:
        extras.pop()
    print("%s%s%s" % (warn, fit(" · ".join([head] + extras + [tail]), cols), off))

    for n, (_, text) in enumerate(items[:SHOWN], 1):
        print("%s  %d. %s%s" % (dim, n, fit(text, cols - 5), off))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
