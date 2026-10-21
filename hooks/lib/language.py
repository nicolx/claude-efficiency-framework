"""The dialogue language: what the developer reads replies in.

Every shipped document here is English, and so is most of what a session reads:
code, tool output, the charter itself. Left alone, a model answers in the
language of what it has been reading, and after a long stretch of English work
it drifts into English with a developer who writes to it in Italian. Observed on
this framework's own repository, and the developer's call is that the dialogue
follows the operating system, not the material.

So the hooks state the language explicitly: once at session start, at the very
top of the injection, and again in one line on every prompt, where the drift
happens — late, deep into English work, long after a session-start line was
read. Measured in scripts/probes/dialogue-language.sh (§ 24).

Where the language comes from, first match wins:

  1. `language:` in the policy frontmatter — a project's declaration, so a team
     can fix one language for everyone whatever their machines say;
  2. LC_ALL, then LC_MESSAGES — deliberate overrides when someone set them;
  3. on macOS, the first of AppleLanguages — the language the OS is shown in,
     and the only signal left when the app was not started from a shell:
     measured, a session launched without LANG gives its hooks no locale
     variable at all, while `defaults` still answers;
  4. LANG.

"C" and "POSIX" are not languages and are skipped. When nothing answers, the
hooks say nothing about language and the session behaves as it always did.
"""

import os
import re
import subprocess
import sys

NAMES = {
    "ar": "Arabic", "ca": "Catalan", "cs": "Czech", "da": "Danish", "de": "German",
    "el": "Greek", "en": "English", "es": "Spanish", "fi": "Finnish", "fr": "French",
    "he": "Hebrew", "hi": "Hindi", "hu": "Hungarian", "id": "Indonesian", "it": "Italian",
    "ja": "Japanese", "ko": "Korean", "nb": "Norwegian", "nl": "Dutch", "no": "Norwegian",
    "pl": "Polish", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian", "sk": "Slovak",
    "sv": "Swedish", "th": "Thai", "tr": "Turkish", "uk": "Ukrainian", "vi": "Vietnamese",
    "zh": "Chinese",
}

CODE_RE = re.compile(r"^([A-Za-z]{2,3})(?:[-_][A-Za-z0-9]+)*(?:\.[\w-]+)?(?:@\w+)?$")
NAME_RE = re.compile(r"^[^\W\d_][^\W\d_ ()'-]*(?:[ ()'-][^\W\d_]+\)?)*$", re.UNICODE)


def _name(value):
    """A language name for a locale or code, or None when it is not one."""
    value = (value or "").strip().strip("\"'")
    if not value or value.upper() == "POSIX":   # "C" and "C.UTF-8" fail CODE_RE
        return None
    m = CODE_RE.match(value)
    if m:
        code = m.group(1).lower()
        return NAMES.get(code) or ("the language with code `%s`" % code)
    return None


def _policy(project):
    """`language:` from the policy frontmatter: a code or a plain name, or None."""
    try:
        with open(os.path.join(project, ".efficiency", "policy.md"), errors="replace") as fh:
            if fh.readline().strip() != "---":
                return None
            for line in fh:
                if line.strip() == "---":
                    return None
                key, _, value = line.partition(":")
                if key.strip() == "language" and not line[:1].isspace():
                    value = value.split("#", 1)[0].strip().strip("\"'")
                    if not value:
                        return None
                    by_code = _name(value)
                    if by_code and not by_code.startswith("the language"):
                        return by_code
                    # A plain name — "Italian", "italiano", "Português" — is
                    # taken as written, within reason.
                    if len(value) <= 40 and NAME_RE.match(value):
                        return value
                    return by_code
    except OSError:
        return None
    return None


def _apple_languages():
    if sys.platform != "darwin":
        return None
    try:
        done = subprocess.run(["defaults", "read", "-g", "AppleLanguages"],
                              capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    found = re.search(r'"?([A-Za-z]{2,3}(?:[-_][A-Za-z0-9]+)*)"?', done.stdout.strip("( \n)"))
    return found.group(1) if found else None


def detect(project, env=None):
    """(language name, where it came from), or (None, None)."""
    env = os.environ if env is None else env
    declared = _policy(project)
    if declared:
        return declared, "the project's policy"
    for var in ("LC_ALL", "LC_MESSAGES"):
        name = _name(env.get(var))
        if name:
            return name, var
    apple = _apple_languages()
    if apple and _name(apple):
        return _name(apple), "the OS language (%s)" % apple
    name = _name(env.get("LANG"))
    if name:
        return name, "LANG"
    return None, None


def session_line(project):
    """The paragraph that opens the SessionStart injection, or ""."""
    name, source = detect(project)
    if not name:
        return ""
    return ("# Dialogue language: %s\n\n"
            "Write **every reply to the developer in %s** — answers, reports, plans, questions, "
            "the labels of an output style — whatever language the prompt, the code, the tool "
            "output or this charter is in. Code, commit messages and the repository's own "
            "documents keep the language they are written in. From %s; `language:` in "
            "`.efficiency/policy.md` overrides it.\n\n---\n\n" % (name, name, source))


def prompt_line(project):
    """One line for every prompt, or ""."""
    name, _source = detect(project)
    if not name:
        return ""
    return ("[efficiency] Reply in %s, however much English you have just read or written. "
            "Code and repository documents keep their own language." % name)
