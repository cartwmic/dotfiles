#!/usr/bin/env python3
"""agent-alert sink: ring a Claude cloud session.

The core starts this program with one event line on standard input. It runs

    claude --safe-mode --no-session-persistence -p "agent-alert: <worker> <kind> #<seq>" --cloud <session-id>

which queues one short message into the cloud session and exits. --safe-mode
skips CLAUDE.md, skills, plugins, hooks and MCP servers (login still works);
the command runs from a neutral directory that holds no CLAUDE.md.

A ring is sent at most once every 30 seconds. An event that arrives inside the
window is held, not dropped: the doorbell records it (worker, kind and seq only)
and starts one short-lived detached process, which waits for the window to end
and then sends one combined ring for everything held ("agent-alert: 2 events:
...", see combined_message). That process lives in its own session so the core's
kill of the sink does not reach it, ends as soon as nothing is held, and at the
latest after FLUSHER_MAX_SECONDS. Only one exists at a time. The inbox still has
every event; a ring that fails is logged and not retried.

Every failure is appended to the operator log and the exit status is still 0.

A finished event whose context says awaiting=none (the source saw the worker end its turn with
"AWAITING-OWNER: none") is not rung and not held: it is skipped before anything else, and the
inbox still has it. Every other event rings, including a question and a blocked.

The session id is read on every ring from ~/.config/agent-alert/claude-doorbell.json
({"session_id": "..."}, or the path in AGENT_ALERT_DOORBELL_CONFIG), or from
AGENT_ALERT_DOORBELL_SESSION. It is never stored in the repository.

Python 3 standard library only.
"""

import contextlib
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
# The detached flusher: it ends at the latest after this many seconds (rings are 30 s apart,
# so this is about ten windows; measured on the monotonic clock) and is never alive when nothing is held.
FLUSHER_MAX_SECONDS = 300
# How long past its planned ring a registered flusher is still believed alive.
FLUSHER_SLACK_SECONDS = 10
# A combined ring names this many events, then says how many more there were.
MAX_LISTED = 4
FIELD_LIMIT = 32
# A finished event with this context member and value is a turn that ended needing nothing from the owner.
QUIET_KEY = "awaiting"
QUIET_VALUE = "none"


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


def state_path():
    return os.path.expanduser(os.environ.get("AGENT_ALERT_DOORBELL_STATE") or os.path.join(state_dir(), "claude-doorbell.last"))


# --------------------------------------------------------------------------
# State: the time of the last ring, the events held, and the flusher, in one
# file read and rewritten under an exclusive lock.
# --------------------------------------------------------------------------


def empty_state():
    return {"last": 0.0, "held": [], "more": 0, "latest": None, "flusher": None}


def parse_state(text):
    """The state in the file; an old file holds only the last ring time, and junk means no state."""
    state = empty_state()
    try:
        stored = json.loads(text) if text.strip() else None
    except ValueError:
        return state
    if isinstance(stored, (int, float)) and not isinstance(stored, bool):
        state["last"] = float(stored)
    elif isinstance(stored, dict):
        if isinstance(stored.get("last"), (int, float)) and not isinstance(stored.get("last"), bool):
            state["last"] = float(stored["last"])
        held = stored.get("held")
        if isinstance(held, list):
            state["held"] = [item for item in held if isinstance(item, list) and len(item) == 3][:MAX_LISTED]
        if isinstance(stored.get("more"), int) and stored["more"] > 0:
            state["more"] = stored["more"]
        state["latest"] = stored.get("latest")
        flusher = stored.get("flusher")
        if isinstance(flusher, dict) and isinstance(flusher.get("pid"), int) and isinstance(flusher.get("until"), (int, float)):
            state["flusher"] = flusher
    return state


@contextlib.contextmanager
def locked_state():
    """Yield the state under an exclusive lock and write it back when the block ends normally.

    Raises OSError if the file cannot be opened or locked.
    """
    path = state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        state = parse_state(handle.read())
        yield state
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps(state))


def field(value):
    return str(value)[:FIELD_LIMIT]


def hold(state, event):
    """Add an event to what is held (worker, kind and seq only; at most MAX_LISTED are kept by name)."""
    if len(state["held"]) < MAX_LISTED:
        state["held"].append([field(event.get("worker")), field(event.get("kind")), field(event.get("seq"))])
    else:
        state["more"] += 1
    state["latest"] = field(event.get("seq"))


def take_held(state):
    """Remove and return (events, more, latest) held in the state."""
    taken = (state["held"], state["more"], state["latest"])
    state["held"], state["more"], state["latest"] = [], 0, None
    return taken


def combined_message(events, more, latest):
    """The one ring line: a single event keeps the plain form; several are listed and counted."""
    if len(events) == 1 and not more:
        return "agent-alert: %s %s #%s" % tuple(events[0])
    listed = ", ".join("%s %s #%s" % tuple(item) for item in events)
    extra = ", +%d more (latest #%s)" % (more, latest) if more else ""
    return "agent-alert: %d events: %s%s" % (len(events) + more, listed, extra)


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists, but not ours to signal
    return True


def flusher_alive(state, now):
    flusher = state["flusher"]
    return bool(flusher) and flusher["until"] > now and pid_alive(flusher["pid"])


def start_flusher(state, now):
    """Start the one detached flusher and record it in the state. Returns False if it could not start."""
    try:
        child = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--flush"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 close_fds=True, start_new_session=True, cwd=neutral_cwd())
    except OSError as error:
        log_problem("cannot start the held-ring process: %s" % error)
        return False
    state["flusher"] = {"pid": child.pid, "until": now + THROTTLE_SECONDS + TIMEOUT_SECONDS + FLUSHER_SLACK_SECONDS}
    return True


def is_quiet(event):
    """True for a finished event that says its worker needs nothing from the owner (not rung, not held)."""
    context = event.get("context")
    return event.get("kind") == "finished" and isinstance(context, dict) and context.get(QUIET_KEY) == QUIET_VALUE


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


def ring(session, message):
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


def claim(event):
    """Decide what this event does. Returns the ring to send now as (events, more, latest), or None.

    Inside the window the event is held and a flusher is made sure of. Outside it, this event and
    anything left held (by a flusher that died) are rung together. The window starts at the claim, so
    a ring that then fails also opens it. If the state file cannot be used, ring rather than stay silent.
    """
    try:
        with locked_state() as state:
            now = time.time()
            if 0 <= now - state["last"] < THROTTLE_SECONDS:
                hold(state, event)
                if not flusher_alive(state, now):
                    start_flusher(state, now)
                return None
            hold(state, event)
            state["last"] = now
            return take_held(state)
    except OSError:
        return ([[field(event.get("worker")), field(event.get("kind")), field(event.get("seq"))]], 0, None)


def flush_held():
    """The detached flusher: wait for each window to end, ring what is held, stop when nothing is.

    It ends by itself at the latest FLUSHER_MAX_SECONDS after it starts (monotonic clock): it neither
    sleeps nor starts a ring that would cross that bound. Retiring (nothing held) and clearing its
    registration happen in one locked step, so an event cannot be left held behind a flusher that is
    already leaving.
    """
    deadline = time.monotonic() + FLUSHER_MAX_SECONDS
    me = os.getpid()
    try:
        while True:
            claimed = None
            wait = 0.0
            remaining = deadline - time.monotonic()
            with locked_state() as state:
                now = time.time()
                flusher = state["flusher"]
                if flusher and flusher["pid"] != me and flusher_alive(state, now):
                    return  # another flusher is registered: leave the work to it
                if not state["held"]:
                    state["flusher"] = None  # retire in the same locked step as the empty check
                    return
                wait = state["last"] + THROTTLE_SECONDS - now
                if wait > THROTTLE_SECONDS:  # the clock moved back: do not wait for it
                    wait = 0.0
                if wait + TIMEOUT_SECONDS > remaining:
                    state["flusher"] = None  # out of time: what is held rides with the next event
                    return
                if wait <= 0:
                    state["last"] = now
                    claimed = take_held(state)
                state["flusher"] = {"pid": me, "until": now + max(wait, 0) + TIMEOUT_SECONDS + FLUSHER_SLACK_SECONDS}
            if claimed is None:
                time.sleep(wait)
                continue
            session = session_id()
            if not session:
                log_problem("no session id configured; no nudge sent")
                continue
            ring(session, combined_message(*claimed))
    except OSError as error:
        log_problem("held-ring process stopped: %s" % error)
        with contextlib.suppress(OSError):
            with locked_state() as state:
                if state["flusher"] and state["flusher"]["pid"] == me:
                    state["flusher"] = None


def main():
    if sys.argv[1:] == ["--flush"]:
        flush_held()
        return
    try:
        event = json.loads(sys.stdin.readline())
    except ValueError:
        event = None
    if not isinstance(event, dict):
        log_problem("event line is not a JSON object; skipped")
        return
    if is_quiet(event):
        return
    session = session_id()
    if not session:
        log_problem("no session id configured; no nudge sent")
        return
    claimed = claim(event)
    if claimed is not None:
        ring(session, combined_message(*claimed))


if __name__ == "__main__":
    main()
