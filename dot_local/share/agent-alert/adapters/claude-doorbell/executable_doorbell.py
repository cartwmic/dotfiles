#!/usr/bin/env python3
"""agent-alert sink: ring a Claude cloud session.

The core starts this program with one event line on standard input. It runs

    claude --safe-mode --no-session-persistence -p "<worker> <kind> #<seq>" --cloud <session-id>

which queues one short message into the cloud session and exits. --safe-mode
skips CLAUDE.md, skills, plugins, hooks and MCP servers (login still works);
the command runs from a neutral directory that holds no CLAUDE.md. A ring is
sent at most once every 30 seconds: an event that arrives inside the window is
not rung (the inbox has it). Every failure is appended to the operator log and
the exit status is still 0.

The session id is read on every ring from ~/.config/agent-alert/claude-doorbell.json
({"session_id": "..."}, or the path in AGENT_ALERT_DOORBELL_CONFIG), or from
AGENT_ALERT_DOORBELL_SESSION. It is never stored in the repository.

Python 3 standard library only.
"""

import datetime
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time

DEFAULT_CONFIG = "~/.config/agent-alert/claude-doorbell.json"
DEFAULT_LOG = "~/.local/state/agent-alert/agent-alert.log"
# Below the core's default sink bound (5 seconds), so this sink logs its own timeout.
TIMEOUT_SECONDS = 4
# At most one ring per this many seconds (leading edge: the first event rings).
THROTTLE_SECONDS = 30


def log_problem(message):
    path = os.path.expanduser(os.environ.get("AGENT_ALERT_LOG") or DEFAULT_LOG)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as log:
            log.write("%s claude-doorbell: %s\n" % (stamp, message))
    except OSError:
        pass


def state_dir():
    """The directory of the operator log: holds the throttle file and is claude's neutral cwd."""
    log = os.path.expanduser(os.environ.get("AGENT_ALERT_LOG") or DEFAULT_LOG)
    return os.path.dirname(log)


def claim_ring():
    """True if this event may ring now. Records the time under a lock so parallel doorbells cannot both ring."""
    path = os.path.expanduser(os.environ.get("AGENT_ALERT_DOORBELL_STATE") or os.path.join(state_dir(), "claude-doorbell.last"))
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.seek(0)
            try:
                last = float(handle.read().strip() or 0)
            except ValueError:
                last = 0.0
            now = time.time()
            if 0 <= now - last < THROTTLE_SECONDS:
                return False
            handle.seek(0)
            handle.truncate()
            handle.write(repr(now))
            return True
    except OSError:
        return True  # cannot keep the state: ring rather than stay silent


def neutral_cwd():
    directory = state_dir()
    try:
        os.makedirs(directory, exist_ok=True)
        return directory
    except OSError:
        return tempfile.gettempdir()


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
    if not claim_ring():
        return  # inside the throttle window; the inbox has the event
    message = "agent-alert: %s %s #%s" % (event.get("worker"), event.get("kind"), event.get("seq"))
    try:
        result = subprocess.run(["claude", "--safe-mode", "--no-session-persistence", "-p", message, "--cloud", session],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=TIMEOUT_SECONDS,
                                cwd=neutral_cwd())
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
