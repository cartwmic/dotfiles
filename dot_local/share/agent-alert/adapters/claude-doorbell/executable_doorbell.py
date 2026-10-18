#!/usr/bin/env python3
"""agent-alert sink: ring a Claude cloud session with `claude -p <message> --cloud <session-id>`.

The core starts this program with one event line on standard input. It sends a
one-line nudge naming the worker, kind and sequence number, with a time limit.
Every failure is appended to the operator log and the exit status is still 0.
The session id comes from ~/.config/agent-alert/claude-doorbell.json
({"session_id": "..."}, or the path in AGENT_ALERT_DOORBELL_CONFIG), or from
AGENT_ALERT_DOORBELL_SESSION. It is never stored in the repository.

Python 3 standard library only.
"""

import datetime
import json
import os
import subprocess
import sys

DEFAULT_CONFIG = "~/.config/agent-alert/claude-doorbell.json"
DEFAULT_LOG = "~/.local/state/agent-alert/agent-alert.log"
# Below the core's default sink bound (5 seconds), so this sink logs its own timeout.
TIMEOUT_SECONDS = 4


def log_problem(message):
    path = os.path.expanduser(os.environ.get("AGENT_ALERT_LOG") or DEFAULT_LOG)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as log:
            log.write("%s claude-doorbell: %s\n" % (stamp, message))
    except OSError:
        pass


def session_id():
    path = os.path.expanduser(os.environ.get("AGENT_ALERT_DOORBELL_CONFIG") or DEFAULT_CONFIG)
    try:
        with open(path, encoding="utf-8") as handle:
            from_file = json.load(handle).get("session_id")
    except (OSError, ValueError, AttributeError):
        from_file = None
    return os.environ.get("AGENT_ALERT_DOORBELL_SESSION") or from_file


def main():
    try:
        event = json.loads(sys.stdin.readline())
    except ValueError:
        event = None
    if not isinstance(event, dict):
        log_problem("event line is not a JSON object; skipped")
        return
    session = session_id()
    if not session:
        log_problem("no session id configured; no nudge sent")
        return
    message = "agent-alert: worker %s %s (event %s). Check the inbox." % (
        event.get("worker"), event.get("kind"), event.get("seq"))
    try:
        result = subprocess.run(["claude", "-p", message, "--cloud", session],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=TIMEOUT_SECONDS)
    except FileNotFoundError:
        log_problem("claude command not found on PATH; no nudge sent")
    except subprocess.TimeoutExpired:
        log_problem("claude timed out after %d seconds and was killed" % TIMEOUT_SECONDS)
    except OSError as error:
        log_problem("cannot start claude: %s" % error)
    else:
        if result.returncode != 0:
            log_problem("claude exited with status %d" % result.returncode)


if __name__ == "__main__":
    main()
