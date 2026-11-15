#!/usr/bin/env python3
"""Check that every `path:line` citation in a derived doc points at a real file and an in-range line.

usage: check_citations.py <doc.md> <repo>

A citation is a backticked `path:LINE` or `path:START-END` (paths relative to <repo>; several may share one
backtick span, separated by commas or semicolons). Fenced code blocks are skipped. A backticked token that
is not shaped like path:line (a URL, a clock time, `host:8080`) is ignored.
Prints the number checked and each bad citation as `doc:line: citation: reason`.
Exit 0: all good. 1: at least one bad citation. 2: usage error, or no citations at all (an uncited doc is not checked).
Stdlib only.
"""
import os
import re
import sys

SPAN = re.compile(r"`([^`\n]+)`")
PART = re.compile(r"^([^\s:`]+):(\d+)(?:-(\d+))?$")
HOST_SUFFIXES = {"com", "org", "net", "io", "dev", "app", "internal", "local", "lan", "home"}


def candidates(text):
    """Yield (doc_line_no, path, start, end) for each citation-shaped token."""
    fenced = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        for span in SPAN.findall(line):
            parts = [p.strip() for p in re.split(r"[;,]\s*", span.strip()) if p.strip()]
            matches = [PART.match(p) for p in parts]
            if not parts or not all(matches):
                continue
            for m in matches:
                start = int(m.group(2))
                end = int(m.group(3)) if m.group(3) else start
                yield n, m.group(1), start, end


def looks_like_path(repo, path):
    if os.path.exists(os.path.join(repo, path)):
        return True
    if "/" in path:
        return True
    base = path.rsplit(".", 1)
    if len(base) == 2 and base[1].lower() in HOST_SUFFIXES:
        return False  # host.example.com:8080
    return "." in path


def line_count(full):
    with open(full, "rb") as f:
        data = f.read()
    return len(data.decode("utf-8", errors="replace").splitlines())


def check(doc_text, repo):
    """Return (checked, bad) where bad is a list of (doc_line, citation, reason)."""
    repo = os.path.realpath(repo)
    checked, bad = 0, []
    for n, path, start, end in candidates(doc_text):
        if not looks_like_path(repo, path):
            continue
        checked += 1
        cite = "%s:%d%s" % (path, start, "-%d" % end if end != start else "")
        full = os.path.realpath(os.path.join(repo, path))
        if full != repo and not full.startswith(repo + os.sep):
            bad.append((n, cite, "path is outside the repo"))
        elif not os.path.isfile(full):
            bad.append((n, cite, "no such file"))
        elif start < 1 or end < start:
            bad.append((n, cite, "bad line range"))
        else:
            total = line_count(full)
            if end > total:
                bad.append((n, cite, "line out of range (file has %d lines)" % total))
    return checked, bad


def main(argv):
    if len(argv) != 3 or not os.path.isfile(argv[1]) or not os.path.isdir(argv[2]):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8", errors="replace") as f:
        checked, bad = check(f.read(), argv[2])
    for n, cite, reason in bad:
        print("%s:%d: %s: %s" % (argv[1], n, cite, reason))
    print("checked %d citations, %d bad" % (checked, len(bad)))
    if not checked:
        print("no citations found: an uncited doc cannot be checked", file=sys.stderr)
        return 2
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
