#!/usr/bin/env python3
"""agent-alert sink: ring a Claude cloud session with `claude -p <message> --cloud <session-id>`.

The core starts this program with one event line on standard input (see
../../SPEC.md, "Sink contract"). It builds a one-line nudge naming the worker
and the kind, runs claude with a time limit, and always exits 0. Every failure
cause is appended to the operator log. The session id comes from this sink's own
config file and is never stored in the repository. README.md next to this file
describes the configuration and the failure causes.

Python 3 standard library only.
"""

import datetime
import json
import os
import re
import signal
import subprocess
import sys

COMPONENT = "claude-doorbell"
DEFAULT_CONFIG = "~/.config/agent-alert/claude-doorbell.json"
DEFAULT_LOG = "~/.local/state/agent-alert/agent-alert.log"
# Below the core's default sink bound (5 seconds) so this sink can log its own timeout.
DEFAULT_TIMEOUT_SECONDS = 4.0
OUTPUT_TAIL = 200
FIELD_LIMIT = 64

_UNSAFE = re.compile(r"[\x00-\x1f\x7f\u0085\u2028\u2029]+")


def log_problem(message):
    """Append one line to the operator log. Best effort: never raises."""
    path = os.path.expanduser(os.environ.get("AGENT_ALERT_LOG") or DEFAULT_LOG)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = "%s %s: %s\n" % (stamp, COMPONENT, " ".join(message.split()))
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8", "replace"))
        finally:
            os.close(fd)
    except OSError:
        pass


def load_settings():
    """Return (session_id, timeout_seconds). A bad config file is logged and treated as empty."""
    path = os.path.expanduser(os.environ.get("AGENT_ALERT_DOORBELL_CONFIG") or DEFAULT_CONFIG)
    values = {}
    try:
        with open(path, encoding="utf-8") as handle:
            values = json.load(handle)
        if not isinstance(values, dict):
            raise ValueError("not a JSON object")
    except FileNotFoundError:
        values = {}
    except (OSError, ValueError) as error:
        log_problem("cannot use config file %s: %s" % (path, error))
        values = {}
    session_id = os.environ.get("AGENT_ALERT_DOORBELL_SESSION") or values.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        session_id = None
    timeout = values.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        log_problem("config timeout_seconds must be a number above 0; using %g" % DEFAULT_TIMEOUT_SECONDS)
        timeout = DEFAULT_TIMEOUT_SECONDS
    return (session_id.strip() if session_id else None), float(timeout)


def field(value):
    """One short printable token for the message, whatever the event held."""
    text = _UNSAFE.sub(" ", value if isinstance(value, str) else "").strip()
    return text[:FIELD_LIMIT]


def build_message(raw):
    """A one-line nudge, or None when the line is not a JSON object. Tolerates any kind and extra members."""
    event = None
    try:
        event = json.loads(raw)
    except ValueError:
        pass
    if not isinstance(event, dict):
        return None
    worker = field(event.get("worker")) or "unknown worker"
    kind = field(event.get("kind")) or "unknown kind"
    seq = event.get("seq")
    where = " (event %d)" % seq if isinstance(seq, int) and not isinstance(seq, bool) else ""
    return "agent-alert: worker %s %s%s. Check the inbox." % (worker, kind, where)


def output_tail(data):
    text = " ".join(data.decode("utf-8", "replace").split())
    return text[-OUTPUT_TAIL:]


def ring(message, session_id, timeout):
    command = ["claude", "-p", message, "--cloud", session_id]
    try:
        child = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except FileNotFoundError:
        log_problem("claude command not found on PATH; no nudge sent")
        return
    except OSError as error:
        log_problem("cannot start claude: %s; no nudge sent" % error)
        return
    try:
        output, _ = child.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except OSError:
            pass
        child.communicate()
        log_problem("claude timed out after %g seconds and was killed; the nudge may not have been sent" % timeout)
        return
    if child.returncode != 0:
        log_problem(
            "claude exited with status %d (login missing or expired?): %s"
            % (child.returncode, output_tail(output) or "no output")
        )


def main():
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError) as error:
        log_problem("cannot read the event from standard input: %s" % error)
        return 0
    session_id, timeout = load_settings()
    if session_id is None:
        log_problem("no session id configured (session_id in the doorbell config or AGENT_ALERT_DOORBELL_SESSION); no nudge sent")
        return 0
    message = build_message(raw)
    if message is None:
        log_problem("event line is not a JSON object; skipped, not rung")
        return 0
    ring(message, session_id, timeout)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # a sink fails soft, whatever happens
        log_problem("unexpected failure: %s: %s" % (type(error).__name__, error))
        sys.exit(0)
