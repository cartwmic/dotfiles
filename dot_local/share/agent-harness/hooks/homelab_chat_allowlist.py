#!/usr/bin/env python3
"""PreToolUse hook of the homelab-chat seat (T3 instance seat-homelab-chat): allow only the tool calls on the list below, deny everything else.

Michael's requirement (ledger asks #1228, decisions #3439-#3441): the agent that answers #homelab has a fixed, small tool set, held by configuration
and not by its prompt. The seat's settings file (~/.claude/fleet/seat-homelab-chat.json) runs this script before every tool call; a denied call does not run.

Input:  the hook JSON on stdin (tool_name, tool_input, ...).
Output: exit 0 to allow; exit 2 and the reason on stderr to deny. It fails closed: input it cannot read, or any error inside it, denies. (The settings
        file's command adds the same for a missing script or python3, because in Claude Code only exit 2 blocks a call.)
Log:    one JSON line per decision to ~/.local/state/homelab-chat/hook.jsonl ({ts, tool, decision, reason}); HOMELAB_CHAT_HOOK_LOG overrides the path.
        The line never holds the command, the arguments or a message text: the tool name, and a rule name or fixed refusal text. A log that cannot be written is reported on stderr and does not change the decision.

Allowed:
  Bash    one command and nothing else, in one of two forms:
            [HOMELAB_BOT_EVENT_ID=<digits>] python3 <homelab_bot.py> <verb ...>      verbs: BOT_VERBS below
            [COORDINATOR_EVENT_ID=<token>] coordinator lead post HomelabChat [--key K] [--text T]   (--key=K / --text=T also)
          <homelab_bot.py> is the absolute path or the literal ~/git/... form.
          The command is read as zsh reads it (zsh runs the Bash tool): outside single quotes `$`, a backtick, a backslash and a newline are refused; outside
          any quotes only letters, digits and `_ . / : + % , = - @` are accepted (and a leading `~`), so `; | & < > ( ) { } * ? [ ] ! # ^` and command substitution cannot occur; inside single quotes
          every character but the closing quote is literal and passes (a multi-line chat text with `$` in it); inside double quotes `; | & < >` pass, `$`, backtick, backslash and newline do not.
  WebSearch, WebFetch, ToolSearch
  mcp__hindsight__recall, mcp__hindsight__reflect, mcp__hindsight__retain
  mcp__t3-code__t3_thread_send, only to a thread in COORDINATOR_THREADS, with no environmentId, mode "restart" or freshContext true
Not allowed, by omission: Read (the lead's brief is inlined in its first message), Edit, Write, Agent, Grep, Glob, Skill, every other MCP tool and every other T3 tool.
"""
import json
import os
import re
import shlex
import sys
import time

COORDINATOR_THREADS = ("mcp:5496141f-7b8c-4f3c-afd1-d87a70d69c56",)
SEND_TOOL = "mcp__t3-code__t3_thread_send"
SIMPLE_TOOLS = ("WebSearch", "WebFetch", "ToolSearch", "mcp__hindsight__recall", "mcp__hindsight__reflect", "mcp__hindsight__retain")
BOT_SCRIPT = "git/cartwmic-homelab-v2/scripts/homelab-bot/homelab_bot.py"
BOT_PATHS = ("~/" + BOT_SCRIPT, "/home/cartwmic/" + BOT_SCRIPT)
# verb words -> the actions allowed after them (None: the verb has no action word). Anything not here is refused: board add, tracker, files, sonarr rolling, arr preferences.
BOT_VERBS = {
    "sonarr": ("lookup", "add", "monitor", "episodes", "episode-search"),
    "radarr": ("lookup", "add", "monitor"),
    "readarr": ("lookup", "add", "kindle"),
    "queue": None,
    "download": ("status",),
    "jellyfin": ("search",),
    "kube": ("get", "describe", "logs", "top", "events"),
    "yamtrack": ("lookup", "add", "status"),
}
LEAD = "HomelabChat"
POST_FLAGS = ("--key", "--text")
BOT_PREFIX = re.compile(r"HOMELAB_BOT_EVENT_ID=[0-9]+")
COORD_PREFIX = re.compile(r"COORDINATOR_EVENT_ID=[A-Za-z0-9_.:-]+")
BARE = re.compile(r"[A-Za-z0-9_./:+@%,=-]")  # a character outside quotes; `~` is also accepted as the first character of a word
UNQUOTED_REFUSED = "$`\\\n\r\0"  # also refused inside double quotes
LOG_REASON_MAX = 120


class Deny(Exception):
    pass


def scan(command):
    """Refuse the command unless every character is one the shell treats as a plain word character, a space, or inside quotes as described in the module text."""
    if not command.strip():
        raise Deny("empty command")
    state, at_word_start = None, True
    for ch in command:
        if state == "'":
            if ch == "'":
                state = None
            continue
        if ch in UNQUOTED_REFUSED:
            raise Deny("a $, backtick, backslash or newline outside single quotes")
        if state == '"':
            if ch == '"':
                state = None
            continue
        if ch in " \t":
            at_word_start = True
            continue
        if ch in "'\"":
            state = ch
        elif ch == "~" and at_word_start:
            pass
        elif not BARE.match(ch):
            raise Deny("a shell character outside quotes (one command only: no ; | & < > ( ) { } * ? [ ] ! # ^ or substitution)")
        at_word_start = False
    if state:
        raise Deny("an unterminated quote")


def words_of(command):
    scan(command)
    try:
        return shlex.split(command, posix=True)
    except ValueError as err:
        raise Deny("the command does not parse (%s)" % err)


def bot_rule(words):
    if len(words) < 2 or words[0] != "python3" or words[1] not in BOT_PATHS:
        raise Deny("not `python3 <homelab_bot.py>`")
    rest = words[2:]
    if not rest or rest[0] not in BOT_VERBS:
        raise Deny("the homelab_bot.py verb is not on the list")
    actions = BOT_VERBS[rest[0]]
    if actions is not None and (len(rest) < 2 or rest[1] not in actions):
        raise Deny("the homelab_bot.py action is not on the list for %s" % rest[0])
    return "bot:" + " ".join(rest[: 1 if actions is None else 2])


def post_rule(words):
    if words[:4] != ["coordinator", "lead", "post", LEAD]:
        raise Deny("not `coordinator lead post %s`" % LEAD)
    rest, seen, i = words[4:], set(), 0
    while i < len(rest):
        flag, eq, value = rest[i].partition("=")
        if flag not in POST_FLAGS or flag in seen:
            raise Deny("coordinator lead post takes only --key and --text, once each")
        seen.add(flag)
        if eq:
            i += 1
            continue
        if i + 1 >= len(rest):
            raise Deny("%s has no value" % flag)
        i += 2
    return "post:" + LEAD


def bash_rule(command):
    words = words_of(command)
    if words and BOT_PREFIX.fullmatch(words[0]):
        return bot_rule(words[1:])
    if words and COORD_PREFIX.fullmatch(words[0]):
        return post_rule(words[1:])
    if words[:1] == ["python3"]:
        return bot_rule(words)
    if words[:1] == ["coordinator"]:
        return post_rule(words)
    raise Deny("Bash runs only homelab_bot.py calls and `coordinator lead post %s`" % LEAD)


def send_rule(args):
    if args.get("threadId") not in COORDINATOR_THREADS:
        raise Deny("t3_thread_send goes to the coordinator thread only")
    if args.get("environmentId"):
        raise Deny("t3_thread_send with an environmentId")
    if args.get("mode") == "restart" or args.get("freshContext"):
        raise Deny("t3_thread_send with mode restart or freshContext")
    return "send:coordinator"


def decide(payload):
    """(tool name, rule that allowed it); raises Deny with the reason."""
    tool, args = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(args, dict):
        raise Deny("the hook input has no tool_name and tool_input")
    if tool in SIMPLE_TOOLS:
        return tool, "tool:" + tool
    if tool == SEND_TOOL:
        return tool, send_rule(args)
    if tool == "Bash":
        command = args.get("command")
        if not isinstance(command, str):
            raise Deny("Bash without a command")
        return tool, bash_rule(command)
    raise Deny("this tool is not on the homelab-chat tool list")


def log(tool, decision, reason):
    path = os.environ.get("HOMELAB_CHAT_HOOK_LOG") or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "homelab-chat", "hook.jsonl")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tool": str(tool)[:80], "decision": decision, "reason": reason[:LOG_REASON_MAX]})
        with open(path, "a") as out:
            out.write(line + "\n")
    except OSError as err:
        print("homelab-chat hook: log not written: %s" % err, file=sys.stderr)


def main():
    tool = "?"
    try:
        payload = json.load(sys.stdin)
        tool = payload.get("tool_name", "?") if isinstance(payload, dict) else "?"
        tool, rule = decide(payload)
    except Deny as err:
        reason = str(err)
    except Exception as err:  # fail closed
        reason = "hook error: %s" % type(err).__name__
    else:
        log(tool, "allowed", rule)
        return 0
    log(tool, "denied", reason)
    print("homelab-chat tool list: denied. %s." % reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
