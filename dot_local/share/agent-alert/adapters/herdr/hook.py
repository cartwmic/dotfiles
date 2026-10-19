#!/usr/bin/env python3
"""Herdr source adapter for agent-alert: one hook script for four Herdr events.

Herdr runs this script for pane.agent_status_changed, pane.agent_detected,
pane.exited and pane.closed (see herdr-plugin.toml) and passes the event in the
environment (HERDR_PLUGIN_EVENT_JSON and friends). The script turns the event
into at most one `agent-alert emit` call, with a worker (the pane id), a kind
and a context (workspace id, workspace label, agent name). It sends no message
text:

    status blocked        -> kind blocked, unless a Pi async subagent is the cause (below)
    status idle or done   -> kind question if the pane's last lines hold a line
                             starting with AWAITING-OWNER: (and not a filler such as
                             "none yet"); else nothing while a subagent still runs in
                             the pane (below); else kind finished
    status working/other  -> nothing (the pane is still noted as having an agent)
    pane exited or closed -> kind exited, only if this pane was seen with an agent

Pi's subagent extension publishes the pane's running subagents as Herdr pane state
labels ("⏳ 2 subagents (scout, worker)", with a trailing "⚠" while one of them needs
attention, which includes a subagent waiting on contact_supervisor). Herdr puts those
labels in the event (state_labels) and fires a new status event whenever they change
or expire. That is the whole subagent signal; no pane text is searched for it.

* A finished event whose pane still shows a running subagent is held, that is, not
  emitted. Herdr fires another status event when the label clears; that one has no
  running subagent and emits the finished. No timer or process is needed.
* A blocked event whose pane shows a running subagent is dropped when the subagent
  is flagged for attention (the worker answers those itself). The flag follows the
  blocked report by a moment, so the hook looks at the pane again for up to
  BLOCKED_SETTLE_SECONDS. Any other blocked event is emitted.
* A question is never held or dropped, whatever the labels say.

The places it looks at a pane are the marker check and, for a blocked event with a
subagent running, the label recheck. The marker check (a worker whose turn ends waiting
on the owner prints a line starting with AWAITING-OWNER:) reads the last lines of the
pane with `herdr pane read`, searches them for a marker line that is not a filler and
keeps only the yes or no: no pane text is stored, logged, put in the inbox or sent. If
the read fails the event is a plain finished.

It decides from the event's own status only and keeps no ordering state, so a
hook that runs late or out of order cannot make it skip a completion; the price
is an occasional duplicate or late finished event (see the Herdr section of
README.md). The only state is a presence marker per pane, kept in
HERDR_PLUGIN_STATE_DIR/panes, which is what lets an exit event know that the pane
had an agent.

Every error is written to stderr (Herdr keeps it in the plugin log, shown by
`herdr plugin log list`) and the script exits 0, so a failure here can never
fail the event or hold up another plugin. It never retries and never emits
errored.

Python 3 standard library only. The core is found relative to this file:
../../core/agent-alert.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

CORE = Path(__file__).resolve().parents[2] / "core" / "agent-alert"

EMIT_TIMEOUT_SECONDS = 30

# A worker whose turn ends waiting on the owner prints a line that starts with this
# marker (after at most a few decoration characters such as a bullet or a box edge).
# Only the marker is matched; whatever follows it is never read out.
# What follows the marker is looked at only to tell a real question from a status filler
# ("AWAITING-OWNER: none yet"); it is never kept.
QUESTION_MARKER = re.compile(r"^[^\w\n]{0,8}AWAITING-OWNER:[ \t]*(.*)$", re.MULTILINE)
QUESTION_FILLER = re.compile(r"[\W_]*none(?:\s+yet)?[\W_]*", re.IGNORECASE)
PANE_READ_LINES = 30
PANE_READ_TIMEOUT_SECONDS = 5
PANE_GET_TIMEOUT_SECONDS = 5

# Pane state labels from Pi's subagent extension: "⏳ N subagent(s) ..." while any runs,
# ending in "⚠" while one needs attention.
SUBAGENT_LABEL = re.compile(r"^\u23f3 \d+ subagents?\b")
ATTENTION_MARK = "\u26a0"
# How long a blocked event with a subagent running waits for the attention flag to appear.
BLOCKED_SETTLE_SECONDS = 3.0
BLOCKED_SETTLE_POLL_SECONDS = 0.5

STATUS_EVENT = "pane.agent_status_changed"
DETECTED_EVENT = "pane.agent_detected"
GONE_EVENTS = ("pane.exited", "pane.closed")
STATUS_TO_KIND = {"blocked": "blocked", "idle": "finished", "done": "finished"}


def note(message):
    sys.stderr.write("agent-alert herdr hook: %s\n" % message)
    sys.stderr.flush()


def read_event(environment):
    raw = environment.get("HERDR_PLUGIN_EVENT_JSON")
    if not raw:
        raise ValueError("HERDR_PLUGIN_EVENT_JSON is not set")
    payload = json.loads(raw)
    data = payload.get("data") or {}
    name = environment.get("HERDR_PLUGIN_EVENT") or str(payload.get("event", "")).replace("_", ".", 1)
    pane = data.get("pane_id") or environment.get("HERDR_PANE_ID")
    if not pane or not isinstance(pane, str):
        raise ValueError("event has no pane id")
    return name, pane, data


def marker_path(environment, pane):
    state_dir = environment.get("HERDR_PLUGIN_STATE_DIR")
    if not state_dir:
        raise ValueError("HERDR_PLUGIN_STATE_DIR is not set")
    return Path(state_dir) / "panes" / quote(pane, safe="")


def record_presence(environment, pane, agent):
    path = marker_path(environment, pane)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(agent, encoding="utf-8")


def take_presence(environment, pane):
    """Delete the pane's marker. Returns the agent name it held, or None if there was none."""
    path = marker_path(environment, pane)
    try:
        agent = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        path.unlink()
    except FileNotFoundError:
        return None  # another hook for this pane took it first
    return agent


def subagent_state(labels):
    """(running, needs_attention) from a pane's state_labels (a dict of status -> text, or anything)."""
    running = attention = False
    if isinstance(labels, dict):
        for value in labels.values():
            if isinstance(value, str) and SUBAGENT_LABEL.match(value):
                running = True
                attention = attention or value.rstrip().endswith(ATTENTION_MARK)
    return running, attention


def herdr_pane_labels(environment, pane):
    """The pane's current state_labels from `herdr pane get`. Raises on any failure."""
    herdr = environment.get("HERDR_BIN_PATH") or "herdr"
    result = subprocess.run(
        [herdr, "pane", "get", pane],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=PANE_GET_TIMEOUT_SECONDS,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError("herdr pane get exited %d" % result.returncode)
    return json.loads(result.stdout.decode("utf-8", "replace"))["result"]["pane"].get("state_labels")


def subagent_needs_attention(environment, pane):
    """True once the pane shows a running subagent flagged for attention, within the settle time.

    False as soon as the pane shows no running subagent, when the time is up, or if the pane cannot be read.
    """
    deadline = time.monotonic() + BLOCKED_SETTLE_SECONDS
    while True:
        try:
            running, attention = subagent_state(herdr_pane_labels(environment, pane))
        except Exception as error:  # noqa: BLE001 - unsure means the blocked event is sent
            note("cannot recheck pane %s for a subagent (%s); sending blocked" % (pane, type(error).__name__))
            return False
        if attention:
            return True
        if not running or time.monotonic() >= deadline:
            return False
        time.sleep(BLOCKED_SETTLE_POLL_SECONDS)


def pane_awaits_owner(environment, pane):
    """True if the last lines of the pane hold a question marker line. Raises on any failure to read."""
    herdr = environment.get("HERDR_BIN_PATH") or "herdr"
    result = subprocess.run(
        [herdr, "pane", "read", pane, "--source", "recent-unwrapped", "--lines", str(PANE_READ_LINES)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=PANE_READ_TIMEOUT_SECONDS,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError("herdr pane read exited %d" % result.returncode)
    text = result.stdout.decode("utf-8", "replace")
    return any(not QUESTION_FILLER.fullmatch(match.group(1)) for match in QUESTION_MARKER.finditer(text))


def build_context(environment, data, agent):
    context = {}
    workspace_id = data.get("workspace_id") or environment.get("HERDR_WORKSPACE_ID")
    if isinstance(workspace_id, str) and workspace_id:
        context["workspace_id"] = workspace_id
    try:
        label = json.loads(environment.get("HERDR_PLUGIN_CONTEXT_JSON") or "{}").get("workspace_label")
    except (ValueError, AttributeError):
        label = None
    if isinstance(label, str) and label:
        context["workspace_label"] = label
    if agent:
        context["agent"] = agent
    return context


def emit(environment, pane, kind, context):
    if not CORE.is_file():
        raise RuntimeError("cannot find the core at %s" % CORE)
    result = subprocess.run(
        [sys.executable, str(CORE), "emit", "--worker", pane, "--kind", kind, "--context-json", json.dumps(context)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=EMIT_TIMEOUT_SECONDS,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "agent-alert emit (pane %s, kind %s) exited %d and the event was not delivered: %s"
            % (pane, kind, result.returncode, result.stderr.decode("utf-8", "replace").strip())
        )


def handle(environment):
    name, pane, data = read_event(environment)
    agent = data.get("agent") if isinstance(data.get("agent"), str) else ""
    if name == STATUS_EVENT:
        if not agent:
            return
        try:
            record_presence(environment, pane, agent)
        except Exception as error:  # noqa: BLE001 - presence must not stop the alert
            note("cannot record presence of pane %s: %s" % (pane, error))
        kind = STATUS_TO_KIND.get(data.get("agent_status"))
        running, attention = subagent_state(data.get("state_labels"))
        if kind == "finished":
            asking = None  # None: could not tell, which is never a reason to hold
            try:
                asking = pane_awaits_owner(environment, pane)
            except Exception as error:  # noqa: BLE001 - the marker is a refinement: keep finished
                note("cannot check pane %s for the question marker (%s); sending finished" % (pane, type(error).__name__))
            if asking:
                kind = "question"
            elif asking is False and running:
                kind = None  # held: Herdr fires another status event when the subagent label clears
        elif kind == "blocked" and running:
            if attention or subagent_needs_attention(environment, pane):
                kind = None  # a subagent is waiting on its supervisor, which is this worker
        if kind:
            emit(environment, pane, kind, build_context(environment, data, agent))
    elif name == DETECTED_EVENT:
        # A released agent (the pane's agent is going away) is not presence.
        if agent and not data.get("released"):
            record_presence(environment, pane, agent)
    elif name in GONE_EVENTS:
        known_agent = take_presence(environment, pane)
        if known_agent is not None:
            emit(environment, pane, "exited", build_context(environment, data, known_agent))


def main():
    try:
        handle(dict(os.environ))
    except Exception as error:  # noqa: BLE001 - containment: nothing may escape the hook
        note("%s: %s" % (type(error).__name__, error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
