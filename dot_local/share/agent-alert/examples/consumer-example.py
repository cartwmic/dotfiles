#!/usr/bin/env python3
"""Worked consumer: print one line per event of `agent-alert tail` read on stdin.

    agent-alert tail --since 0 | python3 consumer-example.py
"""
import json
import sys

KNOWN_KINDS = {"finished", "blocked", "errored", "exited"}

for line in sys.stdin:
    try:
        event = json.loads(line)
        seq = event["seq"]
        if type(seq) is not int:
            raise ValueError("seq is not an integer")
    except (ValueError, KeyError, TypeError):
        continue  # a line that is not an event: skip it and keep reading
    kind = event.get("kind")
    note = "" if str(kind) in KNOWN_KINDS else " (kind unknown to this reader, shown anyway)"
    print("%d %s %s%s" % (seq, event.get("worker"), kind, note))
