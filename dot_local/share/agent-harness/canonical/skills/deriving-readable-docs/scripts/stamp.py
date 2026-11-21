#!/usr/bin/env python3
"""Give each prose line of an appendix section file an id, so a Part 1 sentence and a guard on the condition sheet can name it.

usage: stamp.py [--guide] <A4.md> [<A5.md> ...]

Each prose line without an id gets `[A4.3f9a]` at its end: the section number from the file's `## A<n>` heading, a dot and four hex digits that differ from
every id already in the file. A line that has an id keeps it, so an id stays with its line when the line is edited, split or moved, and is never reused.
Headings, fenced code, printed blocks and table rows are left alone. Run it on a draft before its audit, and again after any edit that adds a line.
A line holds one sentence: an id stands for one claim, and a Part 1 tag points at a line. A line with two or more sentences, stamped or not, is not stamped; the
message names the line (`A4.md:3: 2 sentences on one line: ...`), and the fix is to write each sentence on its own line, then run stamp.py again.
--guide: each file is a whole GUIDE.md (an extend pass puts new lines straight into the guide): the header and Part 1 before the first `## A<n>` heading are left alone.
Prints `file: N lines stamped, M already had an id`. Exit 1 when a file has prose before its first `## A<n>` heading or a line of more than one sentence;
2 on bad usage. Stdlib only.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import TAG, multi_sentence_lines, stamp_text  # noqa: E402


def main(argv):
    guide = "--guide" in argv[1:]
    files = [a for a in argv[1:] if a != "--guide"]
    if not files or not all(os.path.isfile(f) for f in files):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    status = 0
    for f in files:
        with open(f, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        many = multi_sentence_lines(text)
        if many:
            for n, count in many:
                print("%s:%d: %d sentences on one line: write one sentence on each line (a sentence has its own id), then run stamp.py again" % (f, n, count))
            status = 1
            continue
        try:
            new, stamped = stamp_text(text, guide)
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
