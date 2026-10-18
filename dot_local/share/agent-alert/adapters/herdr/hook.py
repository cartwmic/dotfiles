#!/usr/bin/env python3
"""Herdr source adapter for agent-alert: one hook script for four Herdr events.

Herdr runs this script for pane.agent_status_changed, pane.agent_detected,
pane.exited and pane.closed (see herdr-plugin.toml) and passes the event in the
environment (HERDR_PLUGIN_EVENT_JSON and friends). The script turns the event
into one `agent-alert emit` call:

    status blocked        -> kind blocked   (summary: the pane's last message)
    status idle or done   -> kind finished  (summary: the pane's last message)
    status working/other  -> nothing
    pane exited or closed -> kind exited, only if this pane was seen with an agent

It decides from the event's own status only and keeps no ordering state, so a
hook that runs late or out of order cannot make it skip a completion; the price
is an occasional duplicate or late finished event (see README.md). The only
state is a presence marker per pane, kept in HERDR_PLUGIN_STATE_DIR/panes, which
is what lets an exit event know that the pane had an agent.

Every error is written to stderr (Herdr keeps it in the plugin log, shown by
`herdr plugin log list`) and the script exits 0, so a failure here can never
fail the event or hold up another plugin. It never retries.

Python 3 standard library only. The core is found relative to this file:
../../core/agent-alert.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

CORE = Path(__file__).resolve().parents[2] / "core" / "agent-alert"

PLACEHOLDER = "(last message unavailable)"
READ_LINES = 120
MAX_MESSAGE_LINES = 40
READ_TIMEOUT_SECONDS = 10
EMIT_TIMEOUT_SECONDS = 30
CONTEXT_VALUE_LIMIT = 100

STATUS_EVENT = "pane.agent_status_changed"
DETECTED_EVENT = "pane.agent_detected"
GONE_EVENTS = ("pane.exited", "pane.closed")
STATUS_TO_KIND = {"blocked": "blocked", "idle": "finished", "done": "finished"}


# ---------------------------------------------------------------- extractor

ANSI_PATTERN = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[@-Z\\-_]"  # two-character escapes
)
CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
ASCII_RULE_PATTERN = re.compile(r"^[-=_]{10,}$")
PROMPT_MARKERS = ("\u276f", "\u203a")  # heavy right angle, single right angle
FRAME_CHARS = ("\u2502", "\u2503")  # box drawing vertical lines
STATUS_LINE_PATTERNS = (
    re.compile(r"^\s*[\u2800-\u28ff]"),  # spinner (braille) lines
    re.compile(r"^\s*(?:Working|Thinking)\b.*(?:\u2026|\.\.\.)(?:\s*\(.*\))?\s*$"),
    re.compile(r"^\s*(?:Took|Worked for|Elapsed)\s+\d"),  # timing lines
    re.compile(r"^\s*[\u2191\u2193]\s*[\d.]+[kKmM]?\s"),  # token counter footer
)


def strip_escapes(text):
    text = ANSI_PATTERN.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    return CONTROL_PATTERN.sub("", text)


def is_chrome(stripped):
    """Only box-drawing, rule or block characters (U+2500..U+259F), or a long ASCII rule."""
    if not stripped:
        return False
    if ASCII_RULE_PATTERN.match(stripped):
        return True
    return all(c.isspace() or "\u2500" <= c <= "\u259f" for c in stripped)


def is_prompt(stripped):
    return stripped.startswith(PROMPT_MARKERS) or stripped.startswith("$ ") or stripped == "$"


def is_framed(stripped):
    return len(stripped) >= 2 and stripped[0] in FRAME_CHARS and stripped[-1] in FRAME_CHARS


def is_status_line(line):
    return any(pattern.match(line) for pattern in STATUS_LINE_PATTERNS)


def is_boundary(line):
    stripped = line.strip()
    return (
        is_chrome(stripped)
        or is_prompt(stripped)
        or is_framed(stripped)
        or is_status_line(line)
    )


def drop_input_box_footer(lines):
    """Cut everything after the last input box (a prompt line followed by a rule).

    Terminal agents draw their input box, then a footer (directory, token
    counters), below the conversation. Text after that box is footer, not the
    last message. A prompt with no rule after it is not a box.
    """
    for index in range(len(lines) - 1, -1, -1):
        if not is_prompt(lines[index].strip()):
            continue
        for follower in range(index + 1, len(lines)):
            stripped = lines[follower].strip()
            if not stripped:
                continue
            if is_chrome(stripped):
                return lines[: follower + 1]
            break
    return lines


def extract_last_message(text):
    """Return the last message found in terminal text, or "" when none has text.

    The text is split into segments at boundary lines (chrome, prompt, framed,
    status lines) and at runs of two or more blank lines. Boundary lines are
    separators, not deleted content: the last segment that has text is the
    message, so an earlier message behind a boundary never leaks in. A single
    blank line stays inside a segment as a paragraph break. At most the last
    MAX_MESSAGE_LINES lines of the segment are kept.
    """
    lines = [line.rstrip() for line in strip_escapes(text).split("\n")]
    lines = drop_input_box_footer(lines)
    segments = []
    current = []
    blank_run = 0
    for line in lines:
        if is_boundary(line):
            segments.append(current)
            current = []
            blank_run = 0
        elif not line.strip():
            blank_run += 1
            if blank_run == 2:
                segments.append(current)
                current = []
            elif blank_run == 1:
                current.append("")
        else:
            blank_run = 0
            current.append(line)
    segments.append(current)
    for segment in reversed(segments):
        while segment and not segment[0].strip():
            segment.pop(0)
        while segment and not segment[-1].strip():
            segment.pop()
        if segment:
            return "\n".join(segment[-MAX_MESSAGE_LINES:])
    return ""


# -------------------------------------------------------------------- hook


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
    return {key: value[:CONTEXT_VALUE_LIMIT] for key, value in context.items()}


def read_last_message(environment, pane):
    herdr = environment.get("HERDR_BIN_PATH") or "herdr"
    result = subprocess.run(
        [herdr, "agent", "read", pane, "--source", "recent-unwrapped", "--lines", str(READ_LINES)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=READ_TIMEOUT_SECONDS,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError("herdr agent read exited %d: %s" % (result.returncode, result.stderr.decode("utf-8", "replace").strip()))
    return extract_last_message(result.stdout.decode("utf-8", "replace"))


def summary_for(environment, pane):
    try:
        message = read_last_message(environment, pane)
    except Exception as error:  # noqa: BLE001 - any read failure only degrades the summary
        note("cannot read the last message of pane %s: %s" % (pane, error))
        return PLACEHOLDER
    return message or PLACEHOLDER


def emit(environment, pane, kind, summary, context):
    if not CORE.is_file():
        raise RuntimeError("cannot find the core at %s" % CORE)
    result = subprocess.run(
        [sys.executable, str(CORE), "emit", "--worker", pane, "--kind", kind, "--summary", "-", "--context-json", json.dumps(context)],
        input=summary.encode("utf-8"),
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
        if kind:
            emit(environment, pane, kind, summary_for(environment, pane), build_context(environment, data, agent))
    elif name == DETECTED_EVENT:
        # A released agent (the pane's agent is going away) is not presence.
        if agent and not data.get("released"):
            record_presence(environment, pane, agent)
    elif name in GONE_EVENTS:
        known_agent = take_presence(environment, pane)
        if known_agent is not None:
            emit(environment, pane, "exited", "", build_context(environment, data, known_agent))


def main():
    try:
        handle(dict(os.environ))
    except Exception as error:  # noqa: BLE001 - containment: nothing may escape the hook
        note("%s: %s" % (type(error).__name__, error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
