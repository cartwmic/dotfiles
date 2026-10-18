#!/usr/bin/env python3
"""Worked source: stands in for an adapter to some other multiplexer.

Reads "PANE STATE" lines on stdin (STATE is idle, waiting, failed or closed) and
emits one event per line: a worker and a kind, no message text.
"""
import subprocess
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent / "core" / "agent-alert"  # found relative to this file
KINDS = {"idle": "finished", "waiting": "blocked", "failed": "errored", "closed": "exited"}

for line in sys.stdin:
    parts = line.split()
    if len(parts) != 2 or parts[1] not in KINDS:
        print("skipped: " + line.strip(), file=sys.stderr)
        continue
    result = subprocess.run([str(CORE), "emit", "--worker", parts[0], "--kind", KINDS[parts[1]]],
                            capture_output=True, text=True)
    if result.returncode != 0:  # the event was not recorded: say so, keep going
        print("not recorded (%d): %s" % (result.returncode, result.stderr.strip()), file=sys.stderr)
