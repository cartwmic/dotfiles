#!/usr/bin/env python3
"""Deterministic stdin/stdout backend for session-recap outside-in tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


mode = sys.argv[1] if len(sys.argv) > 1 else "success"
mode_file = os.environ.get("FAKE_RECAP_MODE_FILE")
if mode_file:
    mode = Path(mode_file).read_text(encoding="utf-8").strip()
prompt = sys.stdin.buffer.read()
capture_path = os.environ.get("FAKE_RECAP_CAPTURE")
if capture_path:
    Path(capture_path).write_bytes(prompt)
capture_log = os.environ.get("FAKE_RECAP_CAPTURE_LOG")
if capture_log:
    with Path(capture_log).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"mode": mode, "prompt": prompt.decode("utf-8")}) + "\n")

if mode == "success":
    sys.stdout.write("Recent work is complete. Present state: ready for the next step.\n")
elif mode == "blank":
    sys.stdout.write(" \n\t")
elif mode == "nonzero":
    sys.stderr.write("scripted backend failure\n")
    raise SystemExit(7)
else:
    sys.stderr.write(f"unknown fake backend mode: {mode}\n")
    raise SystemExit(64)
