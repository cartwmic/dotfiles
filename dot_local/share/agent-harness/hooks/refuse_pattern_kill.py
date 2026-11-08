#!/usr/bin/env python3
"""Refuse `pkill` and `killall` in an agent's shell command.

A pattern kill can hit another agent's jobs (three incidents in two days). This is the one classifier; the harness adapters call it:
  Claude Code  PreToolUse hook on Bash:  python3 refuse_pattern_kill.py        (reads the hook JSON on stdin)
  Pi           extension refuse-pattern-kill, which runs this script the same way
  Codex        a static rules file instead (dot_codex/rules/agent-guard.rules): Codex's own exec policy, no script

Input: JSON on stdin with the command at tool_input.command (Claude's and Pi's shape), or `--command TEXT`.
Output: exit 2 and the reason on stderr when a simple command in the text is pkill or killall, else exit 0 and nothing.
It fails open: input it cannot read is allowed, so a bug never stops an agent from working.

What counts: the command position of any simple command, found through quotes, `;`, `&&`, `||`, `|`, `&`, newlines, `( )`, `$( )`,
backticks, `sh -c '...'` (and bash, zsh, dash, ksh; also `-lc`), `eval`, heredocs fed to a shell, and wrappers such as `sudo`, `env`,
`nohup`, `time`, `xargs`, `find -exec`. A path (/usr/bin/pkill) counts. The word merely appearing as an argument (`grep pkill x`,
`git commit -m "..pkill.."`, `echo killall`) does not. Not covered: a command built at run time (`$cmd`), a script file, `python -c`.
"""
import json
import os
import re
import sys

REFUSED = ("pkill", "killall")
MESSAGE = (
    "{name} is refused in agent sessions: a pattern kill can hit another agent's jobs. "
    "Kill only a process you started, by exact PID (kill <pid>; take the PID from $! or from the command that started it). "
    "For a kgate job use `kgate cancel <id>`."
)
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "ash"}
# Wrappers run the command that follows them. Value: the options that take an argument (skipped with it) and how many leading
# plain arguments precede the command (timeout DURATION, nice -n N is an option).
WRAPPERS = {
    "env": ({"-u", "-C", "--unset", "--chdir"}, 0), "sudo": ({"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-T", "-U", "--user", "--group",
        "--chdir", "--host", "--prompt", "--role", "--type", "--other-user", "--close-from", "--command-timeout"}, 0),
    "doas": ({"-u", "-C"}, 0), "command": (set(), 0), "exec": ({"-a"}, 0), "nohup": (set(), 0), "nice": ({"-n", "--adjustment"}, 0),
    "ionice": ({"-c", "-n", "-p", "--class", "--classdata"}, 0), "time": ({"-f", "-o"}, 0), "timeout": ({"-s", "-k", "--signal", "--kill-after"}, 1),
    "stdbuf": ({"-i", "-o", "-e"}, 0), "setsid": (set(), 0), "caffeinate": ({"-t", "-w"}, 0), "builtin": (set(), 0),
    "xargs": ({"-n", "-I", "-P", "-L", "-d", "-s", "-E", "-a", "-J", "-R", "-S", "--max-args", "--max-procs", "--delimiter", "--max-lines",
        "--arg-file", "--eof", "--max-chars"}, 0),
    "unbuffer": (set(), 0), "chronic": (set(), 0), "watch": ({"-n", "-d", "--interval"}, 0), "arch": ({"-arch"}, 0), "script": ({"-t"}, 1),
    "run-and-wake": (set(), 0), "heavy-gate": ({"--wait"}, 0),
}
# Options whose argument is itself a command string (env -S "pkill x").
STRING_OPTIONS = {"-S", "--split-string"}
# `sudo -l` and friends only report; they run nothing.
NO_COMMAND_FLAGS = {"sudo": {"-l", "-ll", "-V", "--list", "--version"}, "doas": set()}
SKIP = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}", "case", "esac", "fi", "done", "for", "function"}
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")
REDIRECT = re.compile(r"^[0-9]*[<>]")
HEREDOC = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|\\?([A-Za-z0-9_.\-]+))")


class Scan:
    """Splits shell text into simple commands (lists of words, quotes removed) and the nested texts found inside it."""

    def __init__(self, text):
        self.text = text
        self.commands = []   # list of word lists
        self.nested = []     # texts of $( ), backticks, <( ), >( ) to scan on their own
        self.heredocs = []   # (delimiter, strip_tabs, index of the command that owns it)
        self.bodies = {}     # command index -> heredoc body text
        self._run()

    def _balanced(self, i, open_c, close_c):
        """Index just past the close that matches an open at i-1, honouring quotes; returns (inner_text, next_index)."""
        depth, j, n, t = 1, i, len(self.text), self.text
        while j < n and depth:
            c = t[j]
            if c == "\\":
                j += 2
                continue
            if c == "'":
                k = t.find("'", j + 1)
                j = n if k < 0 else k + 1
                continue
            if c == '"':
                j += 1
                while j < n and t[j] != '"':
                    j += 2 if t[j] == "\\" else 1
                j += 1
                continue
            if c == open_c:
                depth += 1
            elif c == close_c:
                depth -= 1
            j += 1
        return t[i:j - 1] if depth == 0 else t[i:j], j

    def _run(self):
        t, n = self.text, len(self.text)
        words, cur, in_word = [], [], False
        i = 0

        def end_word():
            nonlocal cur, in_word
            if in_word:
                words.append("".join(cur))
            cur, in_word = [], False

        def end_command():
            nonlocal words
            end_word()
            if words:
                self.commands.append(words)
            words = []

        while i < n:
            c = t[i]
            if c == "\\":
                if i + 1 < n:
                    if t[i + 1] != "\n":
                        cur.append(t[i + 1])
                        in_word = True
                    i += 2
                else:
                    i += 1
                continue
            if c == "'":
                k = t.find("'", i + 1)
                k = n if k < 0 else k
                cur.append(t[i + 1:k])
                in_word = True
                i = k + 1
                continue
            if c == '"':
                in_word = True
                i += 1
                while i < n and t[i] != '"':
                    if t[i] == "\\" and i + 1 < n:
                        cur.append(t[i + 1])
                        i += 2
                    elif t[i] == "$" and t[i + 1:i + 2] == "(":
                        inner, i = self._balanced(i + 2, "(", ")")
                        self.nested.append(inner)
                    elif t[i] == "`":
                        k = t.find("`", i + 1)
                        k = n if k < 0 else k
                        self.nested.append(t[i + 1:k])
                        i = k + 1
                    else:
                        cur.append(t[i])
                        i += 1
                i += 1
                continue
            if c == "$" and t[i + 1:i + 2] == "(":
                inner, i = self._balanced(i + 2, "(", ")")
                self.nested.append(inner)
                cur.append("$(...)")
                in_word = True
                continue
            if c == "`":
                k = t.find("`", i + 1)
                k = n if k < 0 else k
                self.nested.append(t[i + 1:k])
                cur.append("`...`")
                in_word = True
                i = k + 1
                continue
            if c in "<>" and t[i + 1:i + 2] == "(":
                inner, i = self._balanced(i + 2, "(", ")")
                self.nested.append(inner)
                cur.append("<(...)")
                in_word = True
                continue
            if c == "#" and not in_word:
                k = t.find("\n", i)
                i = n if k < 0 else k
                continue
            if c in " \t":
                end_word()
                i += 1
                continue
            if c == "\n":
                end_command()
                i = self._take_heredocs(i + 1)
                continue
            if c in "<>":
                m = HEREDOC.match(t, i) if t.startswith("<<", i) and not t.startswith("<<<", i) else None
                if m:
                    delim = m.group(2) or m.group(3) or m.group(4)
                    self.heredocs.append((delim, m.group(1) == "-", len(self.commands)))
                    end_word()
                    words.append("<<")
                    i = m.end()
                    continue
                cur.append(c)
                in_word = True
                i += 1
                continue
            if c == "&" and (t[i - 1:i] in "<>" or t[i + 1:i + 2] == ">"):
                cur.append(c)  # part of a redirect such as 2>&1 or &>
                in_word = True
                i += 1
                continue
            if c in ";&|()":
                end_command()
                i += 1
                continue
            cur.append(c)
            in_word = True
            i += 1
        end_command()

    def _take_heredocs(self, i):
        t, n = self.text, len(self.text)
        while self.heredocs and i <= n:
            delim, strip_tabs, owner = self.heredocs.pop(0)
            lines = []
            while i < n:
                k = t.find("\n", i)
                line = t[i:] if k < 0 else t[i:k]
                i = n if k < 0 else k + 1
                if (line.lstrip("\t") if strip_tabs else line) == delim:
                    break
                lines.append(line)
            self.bodies[owner] = self.bodies.get(owner, "") + "\n".join(lines) + "\n"
        return i


def _base(word):
    return os.path.basename(word)


def _command_words(words):
    """The words from the command position: leading assignments, redirects and shell keywords dropped."""
    i = 0
    while i < len(words):
        w = words[i]
        if ASSIGN.match(w) or w in SKIP:
            i += 1
        elif REDIRECT.match(w):
            i += 2 if w in (">", ">>", "<", "<<", "<<<") or re.fullmatch(r"[0-9]*[<>]{1,2}", w) else 1
        else:
            break
    return words[i:]


def find_refused(text, depth=0):
    """The name of the first pkill/killall found at a command position in text (nested shells included), else None."""
    if depth > 8 or not text:
        return None
    scan = Scan(text)
    for inner in scan.nested:
        hit = find_refused(inner, depth + 1)
        if hit:
            return hit
    for index, words in enumerate(scan.commands):
        words = _command_words(words)
        if not words:
            continue
        name = _base(words[0])
        if name in REFUSED:
            return name
        rest = words[1:]
        if "kgate" in [_base(w) for w in rest]:
            rest = rest[:[_base(w) for w in rest].index("kgate")]  # what follows runs on the cluster, not on this Mac
        if name == "kgate":
            continue
        if name in WRAPPERS:
            hit = _wrapped(name, rest, depth)
            if hit:
                return hit
        if name in ("find", "fd"):
            for k, w in enumerate(rest):
                if w in ("-exec", "-execdir", "-ok", "-okdir", "-x", "--exec") and k + 1 < len(rest):
                    hit = _wrapped("command", rest[k + 1:], depth)
                    if hit:
                        return hit
        if name in SHELLS:
            hit = _shell_text(words, depth)
            if hit:
                return hit
            if index in scan.bodies:  # heredoc fed to a shell
                hit = find_refused(scan.bodies[index], depth + 1)
                if hit:
                    return hit
        if name == "eval":
            hit = find_refused(" ".join(rest), depth + 1)
            if hit:
                return hit
    return None


def _wrapped(wrapper, rest, depth):
    """Look at the command a wrapper runs: skip its options (and their arguments) and its leading plain arguments, then test that word."""
    takes_arg, plain = WRAPPERS[wrapper]
    short_with_arg = {o[1] for o in takes_arg if len(o) == 2}
    no_command = NO_COMMAND_FLAGS.get(wrapper, ())
    if wrapper == "command" and rest and rest[0] in ("-v", "-V"):
        return None  # `command -v pkill` only looks the name up
    i = 0
    while i < len(rest):
        w = rest[i]
        if w in no_command:
            return None  # `sudo -l` and friends only report; only the wrapper's own options are looked at here
        if w == "--":
            i += 1
            break
        if wrapper == "env" and (w in STRING_OPTIONS or w.startswith("--split-string=") or (w.startswith("-S") and len(w) > 2)):
            if w in STRING_OPTIONS:
                text, step = (rest[i + 1] if i + 1 < len(rest) else ""), 2
            elif w.startswith("--split-string="):
                text, step = w.split("=", 1)[1], 1
            else:
                text, step = w[2:], 1
            hit = find_refused(text, depth + 1)
            if hit:
                return hit
            i += step
        elif w in takes_arg:
            i += 2
        elif w.startswith("--") and "=" in w:
            i += 1
        elif w.startswith("-") and len(w) > 1 and not w.startswith("--"):
            # A short cluster such as -iu: the first letter that takes an argument ends it. Its value is the rest of the cluster
            # (-uroot) or, when nothing follows it, the next word (-iu root).
            letters = w[1:]
            position = next((n for n, c in enumerate(letters) if c in short_with_arg), None)
            i += 2 if position is not None and position == len(letters) - 1 else 1
        elif w.startswith("-") and len(w) > 1:
            i += 1
        elif ASSIGN.match(w):
            i += 1
        elif plain:
            plain -= 1
            i += 1
        else:
            break
    command = rest[i:]
    if not command:
        return None
    if _base(command[0]) in REFUSED:
        return _base(command[0])
    if " " in command[0] or "\n" in command[0]:  # watch "pkill x": the one argument is a whole command line
        hit = find_refused(command[0], depth + 1)
        if hit:
            return hit
    # The wrapped command can itself be a shell, an eval or another wrapper: run the whole check on it.
    return find_refused(" ".join(_quote(w) for w in command), depth + 1)


def _quote(word):
    return "'" + word.replace("'", "'\\''") + "'"


def _shell_text(words, depth):
    """Recurse into the script text of `sh -c TEXT` / `bash -lc TEXT` (also after a wrapper such as sudo)."""
    for k, w in enumerate(words):
        if _base(w) in SHELLS:
            for j in range(k + 1, len(words)):
                flag = words[j]
                if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", flag) and j + 1 < len(words):
                    return find_refused(words[j + 1], depth + 1)
                if not flag.startswith("-"):
                    break
    return None


def command_from_stdin(raw):
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict):
        value = tool_input.get("command", tool_input.get("cmd"))
        if isinstance(value, list):
            value = " ".join(str(v) for v in value)
        return value if isinstance(value, str) else None
    value = data.get("command")
    return value if isinstance(value, str) else None


def main(argv):
    if len(argv) >= 3 and argv[1] == "--command":
        command = argv[2]
    else:
        try:
            command = command_from_stdin(sys.stdin.read())
        except Exception:
            command = None
    if not command:
        return 0
    try:
        hit = find_refused(command)
    except Exception:
        return 0  # fail open
    if hit:
        sys.stderr.write(MESSAGE.format(name=hit) + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
