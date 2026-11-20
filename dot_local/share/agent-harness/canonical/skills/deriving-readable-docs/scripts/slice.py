#!/usr/bin/env python3
"""Cut a doc into slices of at most 60 claims and build each slice's claim list and flag list for a fresh checker.

usage: slice.py <doc.md> <repo> [--max-claims N] [--out DIR] [--ids FILE [--record-fixed FILE]]

A claim is a sentence, bullet or table row of the prose (headings, the header, fenced code and printed blocks are not): the count the check prints.
Each claim has an id `N.k`: doc line N, sentence k of that line. A slice is whole sections: the lines from one heading to the line before the heading that
starts the next slice. The heading `Part 2` always starts a new slice, so Part 1 is never mixed with the appendix. A section that does not fit is cut
between lines. N is at most 60 (the default): a slice never holds more, except one line that holds more claims alone, which is marked `over`.
Runs check_citations.py on the doc to get its flagged sentences, and gives each slice those flags whose doc line is inside it.
Prints one line a slice: `slice K: lines A-B, C claims, F flags`. With --out DIR it writes, for each slice, slice-K.flags.txt and slice-K.claims.txt
(one claim a line: `N.k | claim | the sentence, with its tags`; the kind is `outside` for a glossary entry with no tag, which defines an outside term and has
no line to read), and slices.json (`[{n, first_line, last_line, claims, flags, over, part1}]`). The checker brief takes the claims file and the flag list.
--ids FILE re-checks only the sentences it lists, one id a line or separated by commas or spaces (a # starts a comment): a doc line `N`, a claim id `N.k`,
or an id of an appendix line (`A4.3f9a`). The slices then hold those claims only, cut at 60 and apart for Part 1 and the appendix. An id that is
nowhere in the doc is an error (exit 1).
--record-fixed FILE (with --ids) writes the Part 1 sentences of that list to FILE as `tags | sentence`, one row for each set of tags, replacing the row with
the same tags. lint_main.py --fixed FILE then warns when a later fix reworded one of them. Exit 2 on bad usage. Stdlib only.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import TAG, appendix_index, claim_ids, doc_lines, split_lines  # noqa: E402

FLAG = re.compile(r"^.*?:(\d+): flag ")
MAX_CLAIMS = 60
ID_TOKEN = re.compile(r"^(?:\d+|\d+\.\d+|A\d+\.\w+)$")


class SliceError(Exception):
    pass


def sections(text, per_line):
    """[(first_line, claims, hard, lines)] for each block that starts at a heading (the first block starts at line 1). hard marks the block that starts at the
    heading `Part 2`. lines is {doc line: claims} for the lines of the block that hold claims."""
    lines = split_lines(text)
    starts = [1] + [n for n, _, _, heading in doc_lines(text) if heading and n != 1]
    bounds = starts + [len(lines) + 1]
    out = []
    for i in range(len(starts)):
        held = {n: c for n, c in per_line.items() if bounds[i] <= n < bounds[i + 1]}
        out.append((bounds[i], sum(held.values()), bool(re.match(r"#+\s+Part 2\b", lines[bounds[i] - 1])), held))
    return out


def split_section(first, held, limit):
    """[(first_line, claims)] for a section of more claims than the limit: cut between lines, each piece as full as the limit allows."""
    pieces, cur, start = [], 0, first
    for n in sorted(held):
        if cur and cur + held[n] > limit:
            pieces.append((start, cur))
            cur, start = 0, n
        cur += held[n]
    pieces.append((start, cur))
    return pieces


def cut(secs, total_lines, limit):
    units = []
    for first, claims, hard, held in secs:
        if claims > limit and len(held) > 1:
            units += [(f, c, hard and k == 0) for k, (f, c) in enumerate(split_section(first, held, limit))]
        else:
            units.append((first, claims, hard))
    slices, cur = [], None
    for first, claims, hard in units:
        if cur and not hard and cur["claims"] + claims <= limit:
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


def cut_ids(chosen, part1_range, limit):
    """Slices of the chosen claims [(id, line, sentence, kind)] only: Part 1 first, then the rest, each cut at the limit."""
    slices = []
    inside = [c for c in chosen if part1_range[0] <= c[1] < part1_range[1]]
    for group in (inside, [c for c in chosen if c not in inside]):
        for i in range(0, len(group), limit):
            part = group[i:i + limit]
            slices.append({"first_line": part[0][1], "last_line": part[-1][1], "claims": len(part), "over": False, "ids": [c[0] for c in part]})
    for i, s in enumerate(slices):
        s["n"] = i + 1
    return slices


def flags_of(doc, repo):
    here = os.path.dirname(os.path.abspath(__file__))
    r = subprocess.run([sys.executable, "-I", os.path.join(here, "check_citations.py"), doc, repo], capture_output=True, text=True)
    return [(int(FLAG.match(l).group(1)), l) for l in r.stdout.splitlines() if FLAG.match(l)]


def part1_lines(text):
    """(first, after_last): the doc lines of Part 1, from its heading to the heading `Part 2` (no heading: an empty range)."""
    first = after = None
    for n, line in enumerate(split_lines(text), 1):
        if first is None and re.match(r"#+\s+Part 1\b", line):
            first = n
        elif first is not None and re.match(r"#+\s+Part 2\b", line):
            after = n
            break
    if first is None:
        return (0, 0)
    return (first, after or len(split_lines(text)) + 2)


def read_ids(path, claims, text, repo):
    """The claims an ids file names, in doc order. Raises SliceError for an id the doc does not hold."""
    index = appendix_index(text, repo)
    with open(path, encoding="utf-8", errors="replace") as f:
        body = "\n".join(l.split("#", 1)[0] for l in f.read().split("\n"))
    tokens = [t for t in re.split(r"[\s,]+", body) if t]
    bad = [t for t in tokens if not ID_TOKEN.match(t)]
    if bad:
        raise SliceError("not a doc line, a claim id N.k or an appendix id: %s" % ", ".join(bad))
    chosen, missing = set(), []
    for t in tokens:
        if t.startswith("A"):
            hit = {c[0] for c in claims if t in index and c[1] == index[t][0]}
        elif "." in t:
            hit = {c[0] for c in claims if c[0] == t}
        else:
            hit = {c[0] for c in claims if c[1] == int(t)}
        chosen |= hit
        if not hit:
            missing.append(t)
    if missing:
        raise SliceError("no claim in the doc for: %s" % ", ".join(missing))
    return [c for c in claims if c[0] in chosen]


def record_fixed(path, chosen, part1_range):
    """Write the Part 1 claims of `chosen` to the fixed-ids file: `tags | sentence`, replacing the row that has the same tags."""
    rows = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for l in f:
                tags, bar, sentence = l.partition("|")
                if bar and tags.strip():
                    rows[" ".join(sorted(tags.split()))] = sentence.strip()
    for _, n, sentence, kind in chosen:
        tags = sorted(t.strip("[]") for t in TAG.findall(sentence))
        if kind == "claim" and tags and part1_range[0] <= n < part1_range[1]:
            rows[" ".join(tags)] = re.sub(r"\s+", " ", TAG.sub("", sentence)).strip()
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join("%s | %s\n" % kv for kv in rows.items()))


def main(argv):
    args, limit, out, ids, fixed, it = [], MAX_CLAIMS, None, None, None, iter(argv[1:])
    for a in it:
        if a == "--max-claims":
            v = next(it, "")
            limit = int(v) if v.isdigit() and 0 < int(v) <= MAX_CLAIMS else None
        elif a == "--out":
            out = next(it, None)
        elif a == "--ids":
            ids = next(it, None)
        elif a == "--record-fixed":
            fixed = next(it, None)
        else:
            args.append(a)
    if len(args) != 2 or not os.path.isfile(args[0]) or not os.path.isdir(args[1]) or limit is None or (out is not None and not out) \
            or (ids is not None and not os.path.isfile(ids)) or (fixed is not None and (not fixed or ids is None)):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    doc, repo = args[0], os.path.realpath(args[1])
    with open(doc, encoding="utf-8", errors="replace") as f:
        text = f.read()
    claims = claim_ids(text, repo)
    p1 = part1_lines(text)
    if ids:
        try:
            chosen = read_ids(ids, claims, text, repo)
        except SliceError as e:
            print(e, file=sys.stderr)
            return 1
        slices = cut_ids(chosen, p1, limit)
    else:
        chosen = claims
        per_line = {}
        for c in claims:
            per_line[c[1]] = per_line.get(c[1], 0) + 1
        slices = cut(sections(text, per_line), len(split_lines(text)), limit)
    flags = flags_of(doc, repo)
    for s in slices:
        mine = [c for c in chosen if s["first_line"] <= c[1] <= s["last_line"] and (s.get("ids") is None or c[0] in s["ids"])]
        s["claim_lines"] = ["%s | %s | %s" % (c[0], c[3], c[2]) for c in mine]
        s["part1"] = any(p1[0] <= c[1] < p1[1] for c in mine)
        s["flag_lines"] = [l for n, l in flags if n in {c[1] for c in mine}] if ids else [l for n, l in flags if s["first_line"] <= n <= s["last_line"]]
        s["flags"] = len(s["flag_lines"])
        print("slice %d: lines %d-%d, %d claims, %d flags%s" % (s["n"], s["first_line"], s["last_line"], s["claims"], s["flags"], ", over" if s["over"] else ""))
    if out:
        os.makedirs(out, exist_ok=True)
        for s in slices:
            with open(os.path.join(out, "slice-%d.flags.txt" % s["n"]), "w", encoding="utf-8") as f:
                f.write("\n".join(s["flag_lines"]) + ("\n" if s["flag_lines"] else ""))
            with open(os.path.join(out, "slice-%d.claims.txt" % s["n"]), "w", encoding="utf-8") as f:
                f.write("\n".join(s["claim_lines"]) + ("\n" if s["claim_lines"] else ""))
        with open(os.path.join(out, "slices.json"), "w", encoding="utf-8") as f:
            json.dump([{k: v for k, v in s.items() if k not in ("flag_lines", "claim_lines", "ids")} for s in slices], f, indent=2)
    if fixed:
        record_fixed(fixed, chosen, p1)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
