#!/usr/bin/env python3
"""Worked source: read "WORKER STATUS free text" lines on stdin, emit one event each.

STATUS is done, waiting, failed or gone. The core masks and shortens the text.
"""
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "core" / "agent-alert"  # found relative to this file
KINDS = {"done": "finished", "waiting": "blocked", "failed": "errored", "gone": "exited"}

for line in sys.stdin:
    parts = line.split(None, 2)
    if len(parts) < 2 or parts[1] not in KINDS:
        print("skipped: " + line.strip(), file=sys.stderr)
        continue
    command = [str(CORE), "emit", "--worker", parts[0], "--kind", KINDS[parts[1]],
               "--context", "source=example", "--summary", "-"]
    result = subprocess.run(command, input=parts[2] if len(parts) > 2 else "",
                            text=True, capture_output=True)
    if result.returncode != 0:  # the event was not recorded: say so, keep going
        print("not recorded (%d): %s" % (result.returncode, result.stderr.strip()), file=sys.stderr)
