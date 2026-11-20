#!/usr/bin/env python3
"""Cut a doc into slices of at most 100 claims, at headings, and build each slice's flag list for a fresh checker.

usage: slice.py <doc.md> <repo> [--max-claims N] [--out DIR]

A claim is a sentence, bullet or table row of the prose (headings, the header, fenced code and printed blocks are not): the count the check prints.
A slice is whole sections: the lines from one heading to the line before the heading that starts the next slice. A section of more than N claims is a slice of its own and is
marked `over`. Runs check_citations.py on the doc to get its flagged sentences, and gives each slice those flags whose doc line is inside it.
Prints one line a slice: `slice K: lines A-B, C claims, F flags`. With --out DIR it writes slice-K.flags.txt for each slice and slices.json
(`[{n, first_line, last_line, claims, flags, over}]`); the checker brief takes the line range and the flag list. Exit 2 on bad usage. Stdlib only.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import doc_lines, prose_sentences  # noqa: E402

FLAG = re.compile(r"^.*?:(\d+): flag ")


def sections(text, repo):
    """[(first_line, claims)] for each block that starts at a heading (the first block starts at line 1)."""
    per_line = {}
    for n, _ in prose_sentences(text, repo):
        per_line[n] = per_line.get(n, 0) + 1
    starts = [1] + [n for n, _, _, heading in doc_lines(text) if heading and n != 1]
    total = len(text.splitlines())
    bounds = starts + [total + 1]
    return [(bounds[i], sum(c for n, c in per_line.items() if bounds[i] <= n < bounds[i + 1])) for i in range(len(starts))]


def cut(secs, total_lines, limit):
    slices, cur = [], None
    for first, claims in secs:
        if cur and cur["claims"] + claims <= limit:
            cur["claims"] += claims
            continue
        if cur:
            slices.append(cur)
        cur = {"first_line": first, "claims": claims}
    if cur:
        slices.append(cur)
    for i, s in enumerate(slices):
        s["n"] = i + 1
        s["last_line"] = slices[i + 1]["first_line"] - 1 if i + 1 < len(slices) else total_lines
        s["over"] = s["claims"] > limit
    return slices


def flags_of(doc, repo):
    here = os.path.dirname(os.path.abspath(__file__))
    r = subprocess.run([sys.executable, "-I", os.path.join(here, "check_citations.py"), doc, repo], capture_output=True, text=True)
    return [(int(FLAG.match(l).group(1)), l) for l in r.stdout.splitlines() if FLAG.match(l)]


def main(argv):
    args, limit, out, it = [], 100, None, iter(argv[1:])
    for a in it:
        if a == "--max-claims":
            v = next(it, "")
            limit = int(v) if v.isdigit() and int(v) > 0 else None
        elif a == "--out":
            out = next(it, None)
        else:
            args.append(a)
    if len(args) != 2 or not os.path.isfile(args[0]) or not os.path.isdir(args[1]) or limit is None or (out is not None and not out):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    doc, repo = args[0], os.path.realpath(args[1])
    with open(doc, encoding="utf-8", errors="replace") as f:
        text = f.read()
    slices = cut(sections(text, repo), len(text.splitlines()), limit)
    flags = flags_of(doc, repo)
    for s in slices:
        s["flag_lines"] = [l for n, l in flags if s["first_line"] <= n <= s["last_line"]]
        s["flags"] = len(s["flag_lines"])
        print("slice %d: lines %d-%d, %d claims, %d flags%s" % (s["n"], s["first_line"], s["last_line"], s["claims"], s["flags"], ", over" if s["over"] else ""))
    if out:
        os.makedirs(out, exist_ok=True)
        for s in slices:
            with open(os.path.join(out, "slice-%d.flags.txt" % s["n"]), "w", encoding="utf-8") as f:
                f.write("\n".join(s["flag_lines"]) + ("\n" if s["flag_lines"] else ""))
        with open(os.path.join(out, "slices.json"), "w", encoding="utf-8") as f:
            json.dump([{k: v for k, v in s.items() if k != "flag_lines"} for s in slices], f, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
