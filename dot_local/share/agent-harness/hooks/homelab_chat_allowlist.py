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
  Bash    one command and nothing else, in one of these forms:
            [HOMELAB_BOT_EVENT_ID=<digits>] python3 <homelab_bot.py> <verb ...>      verbs: BOT_VERBS below
            [COORDINATOR_EVENT_ID=<token>] coordinator lead post HomelabChat [--key K] [--text T]   (--key=K / --text=T also)
          and the seat's own schedules (ledger grant 37, ask #1115: "anything that we schedule!"), made the way the rest of the fleet makes them, as coordinator kit jobs
          that wake this lead (not T3's schedule_task, which stays refused). Every job id starts with JOB_PREFIX, so the seat can approve and remove only its own wakes (`jobs list` shows every job in the store):
            coordinator jobs wake HomelabChat --at <UTC ISO> --text T --id <JOB_PREFIX...> [--words W]
            coordinator jobs wake HomelabChat --cron C --zone Z --text T --id <JOB_PREFIX...> [--words W]
            coordinator jobs list
            coordinator jobs remove <JOB_PREFIX...> --words W
            <ledger> approve-schedule <JOB_PREFIX...> --cron C --zone Z --grant 37 --why W      (<ledger> is <state dir>/pane-bin/ledger, in the literal ~ form or under $HOME)
          <homelab_bot.py> is the literal ~/git/... form, or the same path under the real home directory ($HOME: /home/agent on the pod, /home/cartwmic on omarchy).
          The command is read as zsh reads it (zsh runs the Bash tool): outside single quotes `$`, a backtick, a backslash and a newline are refused; outside
          any quotes only letters, digits and `_ . / : + % , = - @` are accepted (and a leading `~`), so `; | & < > ( ) { } * ? [ ] ! # ^` and command substitution cannot occur; inside single quotes
          every character but the closing quote is literal and passes (a multi-line chat text with `$` in it); inside double quotes `; | & < >` pass, `$`, backtick, backslash and newline do not.
  WebSearch, WebFetch, ToolSearch
  mcp__hindsight__recall, mcp__hindsight__reflect, mcp__hindsight__retain
  mcp__t3-code__t3_thread_send, only to a thread in COORDINATOR_THREADS, with no environmentId, mode "restart" or freshContext true
Not allowed, by omission: Read (the lead's brief is inlined in its first message), Edit, Write, Agent, Grep, Glob, Skill, every other MCP tool and every other T3 tool (schedule_task and run_scheduled_task_now too).
"""
import json
import os
import re
import shlex
import sys
import time

COORDINATOR_THREADS = ("mcp:5496141f-7b8c-4f3c-afd1-d87a70d69c56", "mcp:c9a80a51-19d4-475c-99bb-117660fc88de")  # omarchy's coordinator, then the agent-host pod's
SEND_TOOL = "mcp__t3-code__t3_thread_send"
SIMPLE_TOOLS = ("WebSearch", "WebFetch", "ToolSearch", "mcp__hindsight__recall", "mcp__hindsight__reflect", "mcp__hindsight__retain")
BOT_SCRIPT = "git/cartwmic-homelab-v2/scripts/homelab-bot/homelab_bot.py"
BOT_PATHS = ("~/" + BOT_SCRIPT, os.path.join(os.path.expanduser("~"), BOT_SCRIPT))  # the absolute form under HOME, read when the hook runs
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
JOB_PREFIX = "wake-" + LEAD + "-"  # the id `coordinator jobs wake` itself gives a one-off wake of this lead; the Homelab lead's own wakes start `wake-Homelab-`
JOB_ID = re.compile(re.escape(JOB_PREFIX) + r"[A-Za-z0-9_.-]+")
GRANT = "37"  # Michael's standing grant for the schedules the family sets up through this lead (ledger ask #1115)
WAKE_FLAGS = ("--at", "--cron", "--zone", "--text", "--id", "--words")
APPROVE_FLAGS = ("--cron", "--zone", "--grant", "--why")
STATE_DIRS = (".local/share/coordinator", ".local/share/coordinator-work")  # the personal coordinator's state dir, and the work Mac's (this file lands on both profiles; the seat runs on personal only)
LEDGER_SCRIPT = "pane-bin/ledger"  # not on PATH: <state dir>/pane-bin/ledger, in the ~ form or under HOME (read when the hook runs), like BOT_PATHS
LEDGER_PATHS = tuple(root + d + "/" + LEDGER_SCRIPT for d in STATE_DIRS for root in ("~/", os.path.expanduser("~") + "/"))
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


def flags_of(rest, allowed, shape):
    """The {flag: value} of `--flag value` / `--flag=value` pairs; each flag at most once, none but `allowed`, no stray word."""
    got, i = {}, 0
    while i < len(rest):
        flag, eq, value = rest[i].partition("=")
        if flag not in allowed or flag in got:
            raise Deny("%s takes only %s, once each" % (shape, " and ".join(allowed)))
        if not eq:
            if i + 1 >= len(rest):
                raise Deny("%s has no value" % flag)
            i, value = i + 1, rest[i + 1]
            if value.startswith("-") and len(value) > 1:  # `--flag --other` is a missing value, not a value; the CLIs refuse it too (`--flag=-x` is how a value starting with `-` is written)
                raise Deny("%s has no value (the next word starts with -)" % flag)
        got[flag] = value
        i += 1
    return got


def post_rule(words):
    if words[:4] != ["coordinator", "lead", "post", LEAD]:
        raise Deny("not `coordinator lead post %s`" % LEAD)
    flags_of(words[4:], POST_FLAGS, "coordinator lead post")
    return "post:" + LEAD


def job_id(value, shape):
    if value is None or not JOB_ID.fullmatch(value):
        raise Deny("%s: the job id must start with %s (this seat's own wakes only)" % (shape, JOB_PREFIX))


def wake_rule(rest):
    shape = "coordinator jobs wake %s (--at ISO | --cron C --zone Z) --text T --id %s... [--words W]" % (LEAD, JOB_PREFIX)
    if rest[:1] != [LEAD]:
        raise Deny("%s: the wake target must be exactly %s, no other lead or thread" % (shape, LEAD))
    got = flags_of(rest[1:], WAKE_FLAGS, "coordinator jobs wake")
    once, recurring = "--at" in got, "--cron" in got or "--zone" in got
    if once == recurring or (recurring and not ("--cron" in got and "--zone" in got)) or "--text" not in got:
        raise Deny("not the shape: " + shape)
    job_id(got.get("--id"), shape)
    return "jobs:wake"


def jobs_rule(rest):
    """`coordinator jobs ...` after the words `coordinator jobs`."""
    if rest == ["list"]:
        return "jobs:list"
    if rest[:1] == ["wake"]:
        return wake_rule(rest[1:])
    if rest[:1] == ["remove"] and len(rest) >= 2:
        shape = "coordinator jobs remove %s... --words W" % JOB_PREFIX
        job_id(rest[1], shape)
        if set(flags_of(rest[2:], ("--words",), "coordinator jobs remove")) != {"--words"}:
            raise Deny("not the shape: " + shape)
        return "jobs:remove"
    raise Deny("coordinator jobs allows only: list; wake %s ...; remove %s... --words W" % (LEAD, JOB_PREFIX))


def approve_rule(rest):
    shape = "ledger approve-schedule %s... --cron C --zone Z --grant %s --why W" % (JOB_PREFIX, GRANT)
    if not rest:
        raise Deny("not the shape: " + shape)
    job_id(rest[0], shape)
    got = flags_of(rest[1:], APPROVE_FLAGS, "ledger approve-schedule")
    if set(got) != set(APPROVE_FLAGS) or got["--grant"] != GRANT:
        raise Deny("not the shape: " + shape)
    return "approve:" + GRANT


def bash_rule(command):
    words = words_of(command)
    if words and BOT_PREFIX.fullmatch(words[0]):
        return bot_rule(words[1:])
    if words and COORD_PREFIX.fullmatch(words[0]):
        return post_rule(words[1:])
    if words[:1] == ["python3"]:
        return bot_rule(words)
    if words[:2] == ["coordinator", "jobs"]:
        return jobs_rule(words[2:])
    if words[:1] == ["coordinator"]:
        return post_rule(words)
    if words[:2] and words[0] in LEDGER_PATHS and words[1] == "approve-schedule":
        return approve_rule(words[2:])
    raise Deny("Bash runs only homelab_bot.py calls, `coordinator lead post %s`, `coordinator jobs` and `ledger approve-schedule` for this seat's own wakes" % LEAD)


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
