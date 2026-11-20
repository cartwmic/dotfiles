#!/usr/bin/env python3
"""Give each prose line of an appendix section file an id, so a Part 1 sentence and a guard on the condition sheet can name it.

usage: stamp.py <A4.md> [<A5.md> ...]

Each prose line without an id gets `[A4.3f9a]` at its end: the section number from the file's `## A<n>` heading, a dot and four hex digits that differ from
every id already in the file. A line that has an id keeps it, so an id stays with its line when the line is edited, split or moved, and is never reused.
Headings, fenced code, printed blocks and table rows are left alone. Run it on a draft before its audit, and again after any edit that adds a line.
Prints `file: N lines stamped, M already had an id`. Exit 1 when a file has prose before its first `## A<n>` heading; 2 on bad usage. Stdlib only.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import TAG, stamp_text  # noqa: E402


def main(argv):
    files = argv[1:]
    if not files or not all(os.path.isfile(f) for f in files):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    status = 0
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        try:
            new, stamped = stamp_text(text)
        except ValueError as e:
            print("%s: %s" % (f, e))
            status = 1
            continue
        if new != text:
            with open(f, "w", encoding="utf-8") as fh:
                fh.write(new)
        print("%s: %d lines stamped, %d already had an id" % (f, stamped, len(set(TAG.findall(text)))))
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv))
