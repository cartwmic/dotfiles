#!/usr/bin/env python3
"""Intercept declared synthetic axis calls; delegate every real consensus call."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

CONTROLLED_MODEL = "intent-calibration/controlled-axis-v1"
AXIS = re.compile(r"^AXIS: ([a-z-]+)\.$", re.M)


def die(message: str) -> "None":
    print(f"intent judge wrapper: {message}", file=sys.stderr)
    raise SystemExit(64)


def one_value(argv: list[str], flag: str) -> str:
    positions = [i for i, value in enumerate(argv) if value == flag]
    if len(positions) != 1 or positions[0] + 1 >= len(argv):
        die(f"expected exactly one {flag} with a value")
    return argv[positions[0] + 1]


def append_route(kind: str, model: str, axis: str | None = None) -> None:
    raw = os.environ.get("SC_INTENT_ROUTE_LOG")
    if not raw: die("SC_INTENT_ROUTE_LOG is not set")
    record = json.dumps({"pid": os.getpid(), "route": kind, "model": model, "axis": axis}, separators=(",", ":")) + "\n"
    fd = os.open(raw, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try: os.write(fd, record.encode())
    finally: os.close(fd)


def load_control() -> dict:
    raw = os.environ.get("SC_INTENT_CHALLENGE")
    if not raw: die("SC_INTENT_CHALLENGE is not set")
    try: value = json.loads(Path(raw).read_text())
    except Exception as error: die(f"cannot read challenge {raw}: {error}")
    return value


def main(argv: list[str]) -> int:
    model = one_value(argv, "--model")
    system_prompt = one_value(argv, "--system-prompt")
    real_model = os.environ.get("SC_INTENT_REAL_CONSENSUS_MODEL")
    if not real_model: die("SC_INTENT_REAL_CONSENSUS_MODEL is not set")
    if real_model == CONTROLLED_MODEL: die("real consensus model equals controlled axis model")

    if model == CONTROLLED_MODEL:
        if "DECIDING judge for a software-change INTENT" in system_prompt:
            die("refusing to intercept consensus-shaped prompt")
        matches = AXIS.findall(system_prompt)
        if len(matches) != 1: die(f"controlled prompt has {len(matches)} AXIS headers")
        axis = matches[0]
        control = load_control()
        if control.get("axis_model") != CONTROLLED_MODEL: die("challenge declares wrong controlled model")
        mode = os.environ.get("SC_INTENT_MODE")
        section = {"targeted": "targeted", "all_axes": "all_axes"}.get(mode or "")
        if not section: die("SC_INTENT_MODE must be targeted or all_axes")
        response = control.get(section, {}).get(axis)
        if not isinstance(response, dict) or set(response) != {"verdict", "reason"}:
            die(f"no declared {section} response for axis {axis}")
        append_route("intercepted", model, axis)
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        return 0

    if model == real_model:
        if "DECIDING judge for a software-change INTENT" not in system_prompt:
            die("real consensus model received non-consensus prompt")
        try: command = json.loads(os.environ.get("SC_INTENT_REAL_COMMAND_JSON", ""))
        except json.JSONDecodeError as error: die(f"SC_INTENT_REAL_COMMAND_JSON is invalid: {error}")
        if not isinstance(command, list) or not command or not all(isinstance(x, str) and x for x in command):
            die("SC_INTENT_REAL_COMMAND_JSON must be a nonempty string array")
        wrapper = Path(__file__).resolve()
        try: target = Path(command[0]).resolve()
        except OSError: target = Path(command[0])
        if target == wrapper: die("real command resolves to wrapper (recursion)")
        append_route("delegated", model)
        os.execvp(command[0], command + argv)
        die("exec returned unexpectedly")

    die(f"undeclared model route {model!r}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
