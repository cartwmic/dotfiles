#!/usr/bin/env python3
"""List the surfaces of a repo that no requirement row cites: a coverage check of a REQUIREMENTS.md against surfaces.py.

usage: surface_coverage.py REQUIREMENTS.md REPO [--all]

Runs deriving-readable-docs/scripts/surfaces.py (the sibling skill, called by path) on REPO and prints `kind | name | path:line`
for each surface that no R-row covers. Default kinds: entry, command, flag, route, event, env, config; --all adds manifest,
export, doc and ci. A surface is covered when an R-row's evidence cites its file and its line (a `path:12-20` range covers
every line in it), or, failing that, when the row's requirement or note text holds its name as a whole word. The first
is the real test; the name fallback only saves a row that cites the surface's neighbour line.
Evidence lines are valid at the register's `commit:`. If REPO's HEAD is a different commit, one warning line is printed first
and every moved line will show here as not covered. Exit 0 whatever is listed (it is a reading aid, not a gate); exit 2 on bad
usage or a missing surfaces.py. It checks citation, not truth: it cannot tell that a row is right.
"""
import json
import os
import re
import subprocess
import sys

SURFACES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
                        "deriving-readable-docs", "scripts", "surfaces.py")
PRODUCT = {"entry", "command", "flag", "route", "event", "env", "config"}
R_ROW = re.compile(r"^\s*\|\s*R-\d+\s*\|")
CITE = re.compile(r"^(.+?):(\d+)(?:-(\d+))?$")


def die(msg):
    print("surface_coverage: " + msg, file=sys.stderr)
    sys.exit(2)


def r_rows(text):
    """[(requirement, evidence, note)] of every register row (id, lens, kind, durability, status, requirement, evidence, check, fit, enforced, note)."""
    out = []
    for line in text.splitlines():
        if R_ROW.match(line):
            c = [x.strip() for x in line.strip().strip("|").split("|")]
            if len(c) >= 11:
                out.append((c[5], c[6], c[10]))
    return out


def cited(evidence):
    """{(file, first, last)} for the `path:line` and `path:a-b` items of one evidence cell."""
    out = set()
    for item in evidence.split(";"):
        m = CITE.match(item.strip().strip("`"))
        if m:
            out.add((m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))))
    return out


def uncovered(rows, surfaces, kinds):
    cites = [(cited(ev), "%s %s" % (req, note)) for req, ev, note in rows]
    out = []
    for s in surfaces:
        if s["kind"] not in kinds:
            continue
        word = re.compile(r"(?<![\w-])" + re.escape(s["name"]) + r"(?![\w-])")
        if any(any(f == s["file"] and a <= s["line"] <= b for f, a, b in c) or word.search(t) for c, t in cites):
            continue
        out.append(s)
    return out


def main(argv):
    args = [a for a in argv[1:] if a != "--all"]
    if len(args) != 2 or not os.path.isfile(args[0]) or not os.path.isdir(args[1]):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    if not os.path.isfile(SURFACES):
        die("surfaces.py not found at %s: install the deriving-readable-docs skill next to distilling-requirements" % SURFACES)
    text = open(args[0], encoding="utf-8").read()
    proc = subprocess.run([sys.executable, "-I", SURFACES, args[1], "--json"], capture_output=True, text=True)
    if proc.returncode:
        die("surfaces.py failed: " + (proc.stderr.strip() or "exit %d" % proc.returncode))
    commit = re.search(r"^commit:\s*(\w+)", text, re.M)
    head = subprocess.run(["git", "-C", args[1], "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if commit and head and not head.startswith(commit.group(1)) and not commit.group(1).startswith(head):
        print("warning: the register is at %s but %s is at %s; moved lines show as not covered" % (commit.group(1)[:12], args[1], head[:12]))
    kinds = None if "--all" in argv else PRODUCT
    surfaces = json.loads(proc.stdout)
    rows = r_rows(text)
    miss = uncovered(rows, surfaces, kinds or {s["kind"] for s in surfaces})
    print("# %d of %d surfaces not cited by any R-row (%d rows)" % (len(miss), sum(1 for s in surfaces if kinds is None or s["kind"] in kinds), len(rows)))
    for s in miss:
        print("%s | %s | %s:%d" % (s["kind"], s["name"], s["file"], s["line"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
