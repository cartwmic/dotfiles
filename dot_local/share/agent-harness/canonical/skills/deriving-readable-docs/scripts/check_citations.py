#!/usr/bin/env python3
"""Check that every `path:line` citation in a derived doc points at a real file and an in-range line.

usage: check_citations.py <doc.md> <repo>

A citation is a backticked `path:LINE` or `path:START-END` (paths relative to <repo>; a space after the colon is
read; several may share one backtick span, separated by commas or semicolons; one inside a span with other
words is read too if its path has a slash or an extension). Fenced code blocks are skipped. A URL, a clock
time, an IPv4 address or `host.com:8080` is ignored. A whole-span `Name:5` with no dot or slash is checked as a
file, so write a port or a key such as `status:200` without backticks.
Prints the number checked and each bad citation as `doc:line: citation: reason`.
Exit 0: all good. 1: at least one bad citation. 2: usage error, or no citations at all (an uncited doc is not checked).
Stdlib only.
"""
import os
import re
import sys

SPAN = re.compile(r"`([^`\n]+)`")
PART = re.compile(r"^([^\s:`]+)\s*:\s*(\d+)(?:\s*-\s*(\d+))?$")
# A citation-shaped token inside a span that also holds other words, such as `see src/a.rs:2`.
EMBEDDED = re.compile(r"(?<![\w/.:@+-])([\w.@+/-]+)\s*:\s*(\d+)(?:-(\d+))?")
HOST_SUFFIXES = {"com", "org", "net", "io", "dev", "app", "internal", "local", "lan", "home"}
IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")


def is_path(repo, path, strict):
    """Should this token be checked as a file citation? Skip clock times, hosts and ports. A whole-span
    token such as `Makefile:5` is checked even with no dot or slash, so a missing file is reported."""
    if os.path.exists(os.path.join(repo, path)):
        return True
    if path == "localhost" or IPV4.match(path):
        return False
    if "/" in path:
        return True
    ext = path.rsplit(".", 1)
    if len(ext) == 2:
        return ext[1].lower() not in HOST_SUFFIXES
    return strict and path[0].isalpha()


def candidates(text, repo):
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
            if parts and all(matches):
                found, strict = matches, True
            else:
                found, strict = list(EMBEDDED.finditer(span)), False
            for m in found:
                if not is_path(repo, m.group(1), strict):
                    continue
                start = int(m.group(2))
                end = int(m.group(3)) if m.group(3) else start
                yield n, m.group(1), start, end


def line_count(full):
    with open(full, "rb") as f:
        data = f.read()
    return len(data.decode("utf-8", errors="replace").splitlines())


def check(doc_text, repo):
    """Return (checked, bad) where bad is a list of (doc_line, citation, reason)."""
    repo = os.path.realpath(repo)
    checked, bad = 0, []
    for n, path, start, end in candidates(doc_text, repo):
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
