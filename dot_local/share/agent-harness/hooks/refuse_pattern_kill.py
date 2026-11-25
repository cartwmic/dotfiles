#!/usr/bin/env python3
"""Refuse `pkill` and `killall` in an agent's shell command, then run the eleven checks of bash_rules.py (sleep-poll, heredoc, kube context, merge, PR body, issue body, local docker, heavy jobs in the agent host pod, git stash, git in the live coordinator checkout, credential config).

A pattern kill can hit another agent's jobs (three incidents in two days). This is the one classifier; the harness adapters call it:
  Claude Code  PreToolUse hook on Bash (and Monitor):  python3 refuse_pattern_kill.py        (reads the hook JSON on stdin)
  Pi           extension refuse-pattern-kill, which runs this script the same way
  Codex        PreToolUse hook on its Bash tool (dot_codex/modify_hooks.json.tmpl), which runs this script the same way; a rules file
               (dot_codex/rules/agent-guard.rules) is the backup while the hook is untrusted

Input: JSON on stdin with the command at tool_input.command (Claude's and Pi's shape; tool_name and cwd are used when sent), or `--command TEXT`.
Output: exit 2 and the reason on stderr when a simple command in the text is pkill or killall, or a bash_rules check refuses it, else exit 0.
It fails open: input it cannot read is allowed, and an error inside bash_rules allows the command, so a bug never stops an agent from working.
The bash_rules checks that depend on the profile read AGENT_HARNESS_PROFILE, else the file `profile` beside this script (rendered by chezmoi).
The heavy-job check runs only in the agent host pod: AGENT_HARNESS_CONTAINER=true, else the file `container` beside this script reads `true` (rendered by chezmoi from container mode).
Every bash_rules refusal is also written as one JSON line ({ts, action, rule, tool, cwd, matched}; `matched` is the command name the rule found, from its fixed list such as `npx vitest`, else null; never the command text, which can hold a token) to ~/.local/state/agent-harness/guard.jsonl (AGENT_HARNESS_GUARD_LOG overrides the path); a write that fails is ignored.

What counts: the command position of any simple command, found through quotes, `;`, `&&`, `||`, `|`, `&`, newlines, `( )`, `$( )`,
backticks, `sh -c '...'` (and bash, zsh, dash, ksh; also `-lc`), `eval`, heredocs fed to a shell, and wrappers such as `sudo`, `env`,
`nohup`, `time`, `xargs`, `find -exec`. A path (/usr/bin/pkill) counts. The word merely appearing as an argument (`grep pkill x`,
`git commit -m "..pkill.."`, `echo killall`) does not. Not covered: a command built at run time (`$cmd`), a script file, `python -c`.
"""
import datetime
import json
import os
import re
import subprocess
import sys

REFUSED = ("pkill", "killall")
MESSAGE = (
    "{name} is refused in agent sessions: a pattern kill can hit another agent's jobs. "
    "Use `kill-mine '<pattern>'` (Linux; signals only processes your own session started; `-9` for KILL, `--dry-run` to look first), "
    "or kill the exact PID (kill <pid>; take the PID from $! or from the command that started it; on macOS this is the way). "
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
HEREDOC = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|(\\?)([A-Za-z0-9_.\-]+))")


class Scan:
    """Splits shell text into simple commands (lists of words, quotes removed) and the nested texts found inside it."""

    def __init__(self, text):
        self.text = text
        self.commands = []   # list of word lists
        self.nested = []     # texts of $( ), backticks, <( ), >( ) to scan on their own
        self.nested_at = []  # for each nested text, the index of the command it sits in (len(commands) when that command is last)
        self.heredocs = []   # (delimiter, strip_tabs, index of the command that owns it, delimiter was quoted)
        self.bodies = {}     # command index -> heredoc body text
        self.documents = []  # (delimiter was quoted, body text) of every heredoc, in order
        self.joins = []      # for each command, the operators between it and the one before (`&&`, `;`, `|`, ...)
        self._run()

    def _nest(self, inner):
        self.nested.append(inner)
        self.nested_at.append(len(self.commands))

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
        ops = ""
        i = 0

        def end_word():
            nonlocal cur, in_word
            if in_word:
                words.append("".join(cur))
            cur, in_word = [], False

        def end_command():
            nonlocal words, ops
            end_word()
            if words:
                self.commands.append(words)
                self.joins.append(ops)
                ops = ""
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
                        self._nest(inner)
                    elif t[i] == "`":
                        k = t.find("`", i + 1)
                        k = n if k < 0 else k
                        self._nest(t[i + 1:k])
                        i = k + 1
                    else:
                        cur.append(t[i])
                        i += 1
                i += 1
                continue
            if c == "$" and t[i + 1:i + 2] == "(":
                inner, i = self._balanced(i + 2, "(", ")")
                self._nest(inner)
                cur.append("$(...)")
                in_word = True
                continue
            if c == "`":
                k = t.find("`", i + 1)
                k = n if k < 0 else k
                self._nest(t[i + 1:k])
                cur.append("`...`")
                in_word = True
                i = k + 1
                continue
            if c in "<>" and t[i + 1:i + 2] == "(":
                inner, i = self._balanced(i + 2, "(", ")")
                self._nest(inner)
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
                ops += "\n"
                i = self._take_heredocs(i + 1)
                continue
            if c in "<>":
                m = HEREDOC.match(t, i) if t.startswith("<<", i) and not t.startswith("<<<", i) else None
                if m:
                    delim = m.group(2) or m.group(3) or m.group(5)
                    quoted = m.group(2) is not None or m.group(3) is not None or bool(m.group(4))
                    self.heredocs.append((delim, m.group(1) == "-", len(self.commands), quoted))
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
                ops += c
                i += 1
                continue
            cur.append(c)
            in_word = True
            i += 1
        end_command()

    def _take_heredocs(self, i):
        t, n = self.text, len(self.text)
        while self.heredocs and i <= n:
            delim, strip_tabs, owner, quoted = self.heredocs.pop(0)
            lines = []
            while i < n:
                k = t.find("\n", i)
                line = t[i:] if k < 0 else t[i:k]
                i = n if k < 0 else k + 1
                if (line.lstrip("\t") if strip_tabs else line) == delim:
                    break
                lines.append(line)
            self.bodies[owner] = self.bodies.get(owner, "") + "\n".join(lines) + "\n"
            self.documents.append((quoted, "\n".join(lines) + "\n"))
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


def unwrap(wrapper, rest):
    """What a wrapper runs: (the command words after its options and leading plain arguments, the command strings given by `env -S`)."""
    takes_arg, plain = WRAPPERS[wrapper]
    short_with_arg = {o[1] for o in takes_arg if len(o) == 2}
    no_command = NO_COMMAND_FLAGS.get(wrapper, ())
    strings = []
    if wrapper == "command" and rest and rest[0] in ("-v", "-V"):
        return [], strings  # `command -v pkill` only looks the name up
    i = 0
    while i < len(rest):
        w = rest[i]
        if w in no_command:
            return [], strings  # `sudo -l` and friends only report; only the wrapper's own options are looked at here
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
            strings.append(text)
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
    return rest[i:], strings


def _wrapped(wrapper, rest, depth):
    """Look at the command a wrapper runs (see unwrap) and test it."""
    command, strings = unwrap(wrapper, rest)
    for text in strings:
        hit = find_refused(text, depth + 1)
        if hit:
            return hit
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


def shell_script(words):
    """The script text of `sh -c TEXT` / `bash -lc TEXT` (also after a wrapper such as sudo), else None."""
    for k, w in enumerate(words):
        if _base(w) in SHELLS:
            for j in range(k + 1, len(words)):
                flag = words[j]
                if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", flag) and j + 1 < len(words):
                    return words[j + 1]
                if not flag.startswith("-"):
                    break
    return None


def _shell_text(words, depth):
    text = shell_script(words)
    return find_refused(text, depth + 1) if text is not None else None


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


def hook_fields(raw):
    """(tool_name, cwd) from the hook JSON; either is None when the harness does not send it (Pi sends neither)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None, None
    if not isinstance(data, dict):
        return None, None
    tool, cwd = data.get("tool_name"), data.get("cwd")
    return tool if isinstance(tool, str) else None, cwd if isinstance(cwd, str) else None


def hook_session(raw):
    """(run id, adapter) from the hook JSON: the harness session id (`session_id`, Cursor's `conversation_id`) and the adapter (`adapter` when the caller names it: the Pi extension does; Cursor's payload carries `conversation_id`; else claude).
    ("", "claude") when the harness sends none: Pi sent no session before the door rule, so its extension adds one."""
    try:
        data = json.loads(raw)
    except ValueError:
        return "", "claude"
    if not isinstance(data, dict):
        return "", "claude"
    run = next((data[k] for k in ("session_id", "conversation_id", "sessionId") if isinstance(data.get(k), str) and data[k]), "")
    adapter = data.get("adapter") if data.get("adapter") in ("claude", "cursor", "pi", "codex") else ("cursor" if "conversation_id" in data else "claude")
    return run, adapter


class DoorSource:
    """The coordinator's renderer, as the `door_rule` of bash_rules.py asks it (see there). Configured by `door.json` beside this script (chezmoi renders it per profile) or the file
    named by AGENT_HARNESS_DOOR: {"enabled": bool, "command": [argv of `hook.ts --door`], "state": <the coordinator state dir>}; COORDINATOR_STATE_DIR in the environment wins for `state`.
    The index of command prefixes is `<state>/t3-hook/door-index.json`, written by the renderer at each session start (and by `hook.ts --door-index`); a missing index means no door: the command runs."""

    def __init__(self, config, env, run, adapter):
        self.command = config.get("command")
        self.state = env.get("COORDINATOR_STATE_DIR") or config.get("state")
        self.run, self.adapter, self.env = run, adapter, env

    def cmds(self):
        try:
            with open(os.path.join(self.state, "t3-hook", "door-index.json")) as handle:
                cmds = json.load(handle).get("cmds")
            return [c for c in cmds if isinstance(c, str)] if isinstance(cmds, list) else []
        except FileNotFoundError:
            return []  # no index yet: no door
        except (OSError, ValueError, TypeError, AttributeError) as error:
            log_door_failure(self.env, "the door index could not be read (%s)" % type(error).__name__, self.run, self.adapter)
            return []

    def render(self, command_text):
        """The refusal text for this command, or None (nothing to tell, or the renderer could not run: the command runs). A renderer that could not run, or answered with something unreadable, is one `door-failed` line in the guard log,
        so rules that stop arriving can be traced. The line names the failure, never the command."""
        try:
            run = subprocess.run(self.command, input=json.dumps({"run": self.run, "kind": "cmd", "value": command_text, "adapter": self.adapter}),
                                 capture_output=True, text=True, timeout=15, env=dict(self.env, COORDINATOR_STATE_DIR=self.state))
        except subprocess.TimeoutExpired:
            return self.failed("the renderer timed out after 15 s")
        except Exception as error:
            return self.failed("the renderer could not start (%s)" % type(error).__name__)
        stderr = (run.stderr or "").strip().splitlines()
        if run.returncode != 0:
            return self.failed("the renderer exited %s%s" % (run.returncode, ": " + stderr[0] if stderr else ""))
        if not run.stdout.strip():
            # Nothing to tell is normal and silent. The renderer says why on stderr when it failed open itself (an unreadable playbook), and that is a failure to record.
            return self.failed("the renderer said: " + stderr[0]) if stderr else None
        try:
            text = json.loads(run.stdout).get("text")
        except (ValueError, AttributeError):
            return self.failed("the renderer's answer was not readable")
        return text if isinstance(text, str) and text else None

    def failed(self, reason):
        log_door_failure(self.env, reason, self.run, self.adapter)
        return None


def load_door(env, directory, run, adapter):
    """A DoorSource, or None when door delivery is not configured here: no config file (the door is off by design), `enabled` false, no command or state, or no session id.
    A config file that is there and cannot be read or is not a usable config is one `door-failed` line in the guard log, so a broken file is found."""
    path = env.get("AGENT_HARNESS_DOOR") or os.path.join(directory, "door.json")
    try:
        with open(path) as handle:
            config = json.load(handle)
    except FileNotFoundError:
        return None
    except Exception as error:
        log_door_failure(env, "door.json could not be read (%s)" % type(error).__name__, run, adapter)
        return None
    if not isinstance(config, dict):
        log_door_failure(env, "door.json is not a JSON object", run, adapter)
        return None
    if config.get("enabled") is False or not run:
        return None
    if not isinstance(config.get("command"), list):
        log_door_failure(env, "door.json has no command list", run, adapter)
        return None
    door = DoorSource(config, env, run, adapter)
    if not door.state:
        log_door_failure(env, "door.json has no state directory", run, adapter)
        return None
    return door


def load_profile(env, directory):
    """The chezmoi profile: AGENT_HARNESS_PROFILE, else the `profile` file beside this script; None when neither is there."""
    if env.get("AGENT_HARNESS_PROFILE"):
        return env["AGENT_HARNESS_PROFILE"].strip()
    try:
        with open(os.path.join(directory, "profile")) as handle:
            return handle.read().strip() or None
    except (OSError, ValueError):
        return None


def load_coordinator_repo(env, directory):
    """This profile's coordinator checkout: AGENT_HARNESS_COORDINATOR_REPO, else line 1 of the `coordinator-instance` file one level up (chezmoi renders it per profile); None when neither is there."""
    if env.get("AGENT_HARNESS_COORDINATOR_REPO"):
        return env["AGENT_HARNESS_COORDINATOR_REPO"].strip()
    try:
        with open(os.path.join(os.path.dirname(directory), "coordinator-instance")) as handle:
            return handle.readline().strip() or None
    except (OSError, ValueError):
        return None


def load_container(env, directory):
    """True in the agent host pod: AGENT_HARNESS_CONTAINER, else the `container` file beside this script (chezmoi renders it `true` in container mode only)."""
    value = env.get("AGENT_HARNESS_CONTAINER")
    if value is None:
        try:
            with open(os.path.join(directory, "container")) as handle:
                value = handle.read()
        except (OSError, ValueError):
            return False
    return value.strip() == "true"


def log_door_failure(env, reason, run, adapter):
    """One JSON line when the door rule could not get an answer from the renderer. Same log as `log_refusal`; a failed write is ignored."""
    try:
        path = env.get("AGENT_HARNESS_GUARD_LOG") or os.path.join(env.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "agent-harness", "guard.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        record = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"), "action": "door-failed", "outcome": "failed", "run": run, "adapter": adapter,
                  "door": "cmd", "reason": reason[:300]}
        with open(path, "a") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:
        pass


def log_refusal(rule, tool, env, cwd=None, matched=None, extra=None):
    """One JSON line per bash_rules refusal, so the logs answer how often each rule refuses. `extra` adds fields a rule chose to log (the gh api body rule's reason and redacted command). A failed write is ignored."""
    try:
        path = env.get("AGENT_HARNESS_GUARD_LOG") or os.path.join(env.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "agent-harness", "guard.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        record = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "action": "refuse", "rule": rule, "tool": tool, "cwd": cwd, "matched": matched}
        record.update(extra or {})
        with open(path, "a") as handle:
            handle.write(json.dumps(record) + "\n")
    except Exception:
        pass


def bash_rules_message(command, raw):
    """The refusal from the bash_rules module (sleep-poll, heredoc, kube context, merge, PR body, local docker, heavy jobs in the pod, git stash, live-checkout git), else None. Any error allows the command."""
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.insert(0, here)
        import bash_rules
        tool, cwd = hook_fields(raw)
        run_id, adapter = hook_session(raw)
        ctx = bash_rules.Context(tool=tool, profile=load_profile(os.environ, here), env=dict(os.environ), cwd=cwd or os.getcwd(),
                                 container=load_container(os.environ, here), coordinator_repo=load_coordinator_repo(os.environ, here),
                                 run=run_id, door=load_door(os.environ, here, run_id, adapter))
        found = bash_rules.refusal(command, ctx)
        if not found:
            return None
        if found[0] != "door":  # the renderer writes the line for the rules it told
            log_refusal(found[0], tool, os.environ, ctx.cwd, found[2], getattr(found[1], "log", None))
        return found[1]
    except Exception:
        return None


def main(argv):
    raw = ""
    if len(argv) >= 3 and argv[1] == "--command":
        command = argv[2]
    else:
        try:
            raw = sys.stdin.read()
            command = command_from_stdin(raw)
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
    message = bash_rules_message(command, raw)
    if message:
        sys.stderr.write(message + "\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
