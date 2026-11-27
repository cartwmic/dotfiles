#!/usr/bin/env python3
"""List the surfaces of a repo that no requirement row cites: a coverage check of a REQUIREMENTS.md against surfaces.py.

usage: surface_coverage.py REQUIREMENTS.md REPO [--all] [--scope PATH]...

Runs deriving-readable-docs/scripts/surfaces.py (the sibling skill, called by path) on REPO and prints `kind | name | path:line`
for each surface that no R-row covers. Default kinds: entry, command, flag, route, event, env, config; --all adds manifest,
export, doc and ci. A surface is covered when an R-row's evidence cites its file and its line (a `path:12-20` range covers
every line in it), or, failing that, when the row's requirement or note text holds its name as a whole word. The first
is the real test; the name fallback only saves a row that cites the surface's neighbour line.
Evidence lines are valid at the register's `commit:`. If REPO's HEAD is a different commit, one warning line is printed first
and every moved line will show here as not covered. Exit 0 whatever is listed (it is a reading aid, not a gate); exit 2 on bad
usage or a missing surfaces.py. With --scope (repeatable, or comma-separated; `.` is the whole repo; an absolute path inside the repo is accepted), only surfaces in those files or folders are listed (a scoped run answers only for its scope). It checks citation, not truth: it cannot tell that a row is right.
Log: each run appends one JSON line (runlog.py: script, action `surface-coverage`, outcome ok or refused; surfaces, uncovered, rows).
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folders are deployed; leave no __pycache__ in them
from check_shape import evidence_parts  # noqa: E402
from logged import logged  # noqa: E402
from scopes import parse_scopes  # noqa: E402

SURFACES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))),
                        "deriving-readable-docs", "scripts", "surfaces.py")
PRODUCT = {"entry", "command", "flag", "route", "event", "env", "config"}
R_ROW = re.compile(r"^\s*\|\s*R-\d+\s*\|")
CITE = re.compile(r"^(.+?):(\d+)(?:-(\d+))?$")


def refuse(stats, msg):
    print("surface_coverage: " + msg, file=sys.stderr)
    stats["reason"] = msg
    return 2


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
    for kind, item in evidence_parts(evidence):
        m = CITE.match(item) if kind == "cite" else None  # a `pr:12` or `commit:1234567` is a history ref, not line 12 of a file called pr
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


def cli(argv, stats):
    args, raw, it = [], [], iter(argv[1:])
    for a in it:
        if a == "--scope":
            raw.append(next(it, ""))
        elif a != "--all":
            args.append(a)
    scope = parse_scopes(args[1], raw) if len(args) == 2 and os.path.isdir(args[1]) else None
    if len(args) != 2 or not os.path.isfile(args[0]) or scope is None:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        stats["reason"] = "usage"
        return 2
    if not os.path.isfile(SURFACES):
        return refuse(stats, "surfaces.py not found at %s: install the deriving-readable-docs skill next to distilling-requirements" % SURFACES)
    text = open(args[0], encoding="utf-8").read()
    proc = subprocess.run([sys.executable, "-I", SURFACES, args[1], "--json"], capture_output=True, text=True)
    if proc.returncode:
        return refuse(stats, "surfaces.py failed: " + (proc.stderr.strip() or "exit %d" % proc.returncode))
    commit = re.search(r"^commit:\s*(\w+)", text, re.M)
    head = subprocess.run(["git", "-C", args[1], "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if commit and head and not head.startswith(commit.group(1)) and not commit.group(1).startswith(head):
        print("warning: the register is at %s but %s is at %s; moved lines show as not covered" % (commit.group(1)[:12], args[1], head[:12]))
    kinds = None if "--all" in argv else PRODUCT
    surfaces = json.loads(proc.stdout)
    if scope:
        surfaces = [s for s in surfaces if any(s["file"] == p or s["file"].startswith(p + "/") for p in scope)]
    rows = r_rows(text)
    miss = uncovered(rows, surfaces, kinds or {s["kind"] for s in surfaces})
    print("# %d of %d surfaces not cited by any R-row (%d rows)" % (len(miss), sum(1 for s in surfaces if kinds is None or s["kind"] in kinds), len(rows)))
    for s in miss:
        print("%s | %s | %s:%d" % (s["kind"], s["name"], s["file"], s["line"]))
    stats.update(surfaces=len(surfaces), uncovered=len(miss), rows=len(rows), scoped=bool(scope))
    return 0


if __name__ == "__main__":
    sys.exit(logged("surface_coverage.py", "surface-coverage", cli, sys.argv))
