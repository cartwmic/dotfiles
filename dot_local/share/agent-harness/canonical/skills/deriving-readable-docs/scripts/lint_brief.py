#!/usr/bin/env python3
"""Check that a writer's brief names only files the repo has.

usage: lint_brief.py <brief.md> <repo>

A section or frame writer's brief lists the files its code sits in under a line `Files:`: one repo-relative path a line (a `-` mark and backticks are
read; several paths on a line may be split by commas or spaces; a folder may end in `/`). The list ends at the first blank line or heading.
Prints `brief:N: FAIL file: path` for a path that is not in the repo (or is outside it) and `FAIL files` for a brief with no `Files:` list or an empty one,
then a count. Exit 1 on any FAIL, 2 on a usage error. A writer who is told to read a file that is not there makes up what it holds, so the lead runs this
before it sends the brief. Stdlib only.
"""
import os
import re
import sys

HEADER = re.compile(r"^\W*files\s*:(.*)$", re.I)


def listed_paths(text):
    """[(brief_line, path)] under the `Files:` line, or None when the brief has no such line."""
    lines, out, inside = text.split("\n"), [], False
    for n, line in enumerate(lines, 1):
        m = HEADER.match(line) if not inside else None
        if m:
            inside, rest = True, m.group(1)
        elif inside:
            if not line.strip() or line.startswith("#"):
                break
            rest = line
        else:
            continue
        rest = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", rest.strip())
        out += [(n, p) for p in re.split(r"[,\s]+", rest.replace("`", "")) if p and p != "(none)"]
    return out if inside else None


def lint(text, repo):
    paths = listed_paths(text)
    if not paths:
        return [(1, "files", "the brief has no `Files:` list with at least one path: name the files the writer's code sits in")]
    fails = []
    for n, p in paths:
        full = os.path.realpath(os.path.join(repo, p))
        if not (full == repo or full.startswith(repo + os.sep)):
            fails.append((n, "file", "%s is outside the repo" % p))
        elif not os.path.exists(full):
            fails.append((n, "file", "%s does not exist in the repo" % p))
    return fails


def main(argv):
    if len(argv) != 3 or not os.path.isfile(argv[1]) or not os.path.isdir(argv[2]):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    with open(argv[1], encoding="utf-8", errors="replace") as f:
        text = f.read()
    fails = lint(text, os.path.realpath(argv[2]))
    for n, kind, detail in fails:
        print("%s:%d: FAIL %s: %s" % (argv[1], n, kind, detail))
    print("%d failed checks" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
