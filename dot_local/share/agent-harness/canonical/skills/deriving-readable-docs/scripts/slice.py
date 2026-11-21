#!/usr/bin/env python3
"""Cut a doc into slices of at most 60 claims and build each slice's claim list and flag list for a fresh checker.

usage: slice.py <doc.md> <repo> [--max-claims N] [--out DIR] [--ids FILE [--was OLD.md] [--reports DIR --record-fixed FILE]]

A claim is a sentence, bullet or table row of the prose (headings, the header, fenced code and printed blocks are not): the count the check prints.
Each claim has an id `N.k`: doc line N, sentence k of that line. Part 1 and the appendix are cut apart (the heading `Part 2` starts a slice). Each part goes into
ceil(claims / 60) slices of near-equal size, cut between lines, so 69 claims make two slices of 35 and 34, not 60 and 9. A line is never split: a slice differs
from the others by up to the claims of one line, and a line that holds more claims than the limit alone is marked `over`. N is at most 60 (the default).
Runs check_citations.py on the doc to get its flagged sentences, and gives each slice those flags whose doc line is inside it.
Prints one line a slice: `slice K: lines A-B, C claims, F flags`. With --out DIR it writes, for each slice, slice-K.flags.txt and slice-K.claims.txt
(one claim a line: `N.k | claim | the sentence, with its tags`; the kind is `outside` for a glossary entry with no tag, which defines an outside term and has
no line to read), and slices.json (`[{n, first_line, last_line, claims, flags, over, part1}]`). The checker brief takes the claims file and the flag list.
--ids FILE re-checks only the sentences it lists, one id a line or separated by commas or spaces (a # starts a comment): a doc line `N`, a claim id `N.k`,
or an id of an appendix line (`A4.3f9a`). The slices then hold those claims only, cut the same way and apart for Part 1 and the appendix. An id that is
nowhere in the doc is an error (exit 1).
--was OLD.md (with --ids) is the guide as it stood when the last round was cut: the slices then also hold each claim the fix changed without the ids file saying so, found by
text as well as by id: a claim whose sentence, tags or cited lines are not in OLD.md (a line a fix split in two: the half that got a new id; reworded; retagged; recited), and a claim
whose sentence is in OLD.md but whose neighbour before it is not the one it had, when that old neighbour is still in the guide (a line that moved, so an "earlier case" now
means something else). A neighbour that was edited or cut does not count: the claim after it is as it was.
--record-fixed FILE (with --ids and --reports DIR) is run once the fix round's checkers have reported: DIR holds their reports. It writes the Part 1 sentences of the
list to FILE as `tags | sentence`, one row for each set of tags, replacing the row with the same tags. A sentence its report marks HOLDS is recorded as it stands;
any other verdict, or no row, records `tags | cut`. lint_main.py --fixed FILE then warns when a later fix reworded a recorded sentence, and skips a `cut` row. Exit 2 on bad
usage. Stdlib only.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import TAG, appendix_index, claim_ids, doc_lines, line_items, split_lines  # noqa: E402

squash = lambda sentence: " ".join(re.findall(r"[a-z0-9]+", TAG.sub(" ", sentence).lower()))

FLAG = re.compile(r"^.*?:(\d+): flag ")
MAX_CLAIMS = 60
ID_TOKEN = re.compile(r"^(?:\d+|\d+\.\d+|A\d+\.\w+)$")


class SliceError(Exception):
    pass


def balance(weights, limit):
    """Cut an ordered list of (key, weight) into pieces of near-equal weight: ceil(total/limit) of them, each close to the share of what is left, never above the limit
    (an item heavier than the limit stands alone). Items are never split, so a piece can differ from the others by up to the weight of one item."""
    total = sum(w for _, w in weights)
    count = max(1, -(-total // limit))
    pieces, cur, weight, left = [], [], 0, total
    for key, w in weights:
        target = -(-left // max(1, count - len(pieces)))
        closer = abs(weight + w - target) > abs(weight - target)  # adding this item leaves the piece further from its share
        if cur and (weight + w > limit or (len(pieces) < count - 1 and weight + w > target and closer)):
            pieces.append(cur)
            left -= weight
            cur, weight = [], 0
        cur.append(key)
        weight += w
    pieces.append(cur)
    return pieces


def cut(text, per_line, limit):
    """Slices of the claims of a doc, by doc line: Part 1 and the appendix are cut apart (the heading `Part 2` starts a slice), and each part goes into ceil(claims/limit)
    slices of near-equal size, cut between lines. A line that holds more claims than the limit alone is marked `over`."""
    lines = split_lines(text)
    end = len(lines) + 1
    p2 = next((n for n, l in enumerate(lines, 1) if re.match(r"#+\s+Part 2\b", l)), None)
    slices = []
    for first, after in ((1, p2), (p2, end)) if p2 and p2 > 1 else ((1, end),):
        held = [(n, c) for n, c in sorted(per_line.items()) if first <= n < after]
        for k, piece in enumerate(balance(held, limit) if held else []):
            slices.append({"first_line": first if k == 0 else piece[0], "claims": sum(per_line[n] for n in piece)})
    slices = slices or [{"first_line": 1, "claims": 0}]
    for i, sl in enumerate(slices):
        sl["n"] = i + 1
        sl["last_line"] = slices[i + 1]["first_line"] - 1 if i + 1 < len(slices) else len(lines)
        sl["over"] = sl["claims"] > limit
    return slices


def cut_ids(chosen, part1_range, limit):
    """Slices of the chosen claims [(id, line, sentence, kind)] only: Part 1 first, then the rest, each part in ceil(claims/limit) slices of near-equal size."""
    slices = []
    inside = [c for c in chosen if part1_range[0] <= c[1] < part1_range[1]]
    for group in (inside, [c for c in chosen if c not in inside]):
        by_id = {c[0]: c for c in group}
        for piece in balance([(c[0], 1) for c in group], limit) if group else []:
            part = [by_id[i] for i in piece]
            slices.append({"first_line": part[0][1], "last_line": part[-1][1], "claims": len(part), "over": False, "ids": piece})
    for i, sl in enumerate(slices):
        sl["n"] = i + 1
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


def signatures(text, claims, repo):
    """A claim's identity for change detection: its sentence (tags and citations aside), its tags, and the citations on its doc line. A claim that keeps its words but
    gets another tag or another cited line is a changed claim: the checker judged the words against the old tag or citation."""
    raw = split_lines(text)
    out = []
    for c in claims:
        cites = sorted(cite for _, _, cs, _ in line_items(raw[c[1] - 1], repo) for cite in cs)
        out.append((squash(c[2]), tuple(sorted(TAG.findall(c[2]))), tuple(cites)))
    return out


def changed_since(old_text, claims, text, repo):
    """The ids of the claims changed since the old guide, found by content: a claim whose sentence, tags or cited lines are not in the old guide (split, reworded, retagged
    or recited), or whose content is in it but whose neighbour before it is no longer the one it had while that old neighbour is still in the guide (moved)."""
    old = signatures(old_text, claim_ids(old_text, repo), repo)
    old_set, old_before = set(old), {}
    for prev, cur in zip([None] + old[:-1], old):
        old_before.setdefault(cur, prev)
    sigs = signatures(text, claims, repo)
    now_set, out = set(sigs), set()
    for prev, cur, claim in zip([None] + sigs[:-1], sigs, claims):
        if cur not in old_set:
            out.add(claim[0])
        elif prev != old_before[cur] and old_before[cur] in now_set:
            out.add(claim[0])
    return out


READ_ROW = re.compile(r"^\s*(?:[-*]\s*)?read\s*\|\s*(\d+\.\d+)\s*\|\s*(\w+)\s*\|", re.M | re.I)


def read_verdicts(folder):
    """{claim id: VERDICT} from the `read | N.k | VERDICT | path:line` rows of every .md and .txt report in the folder."""
    out = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith((".md", ".txt")) and os.path.isfile(os.path.join(folder, name)):
            with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as f:
                out.update((m.group(1), m.group(2).upper()) for m in READ_ROW.finditer(f.read()))
    return out


def record_fixed(path, chosen, part1_range, verdicts):
    """Write the Part 1 claims of `chosen` to the fixed-ids file, one row `tags | sentence` for each set of tags, replacing the row with the same tags. A sentence the
    re-check says HOLDS is recorded as it stands; any other verdict (or no row) records `tags | cut`, because the lead cuts or narrows it next and lint_main.py must not
    warn about that."""
    rows = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            for l in f:
                tags, bar, sentence = l.partition("|")
                if bar and tags.strip():
                    rows[" ".join(sorted(tags.split()))] = sentence.strip()
    for cid, n, sentence, kind in chosen:
        tags = sorted(t.strip("[]") for t in TAG.findall(sentence))
        if kind == "claim" and tags and part1_range[0] <= n < part1_range[1]:
            rows[" ".join(tags)] = re.sub(r"\s+", " ", TAG.sub("", sentence)).strip() if verdicts.get(cid) == "HOLDS" else "cut"
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join("%s | %s\n" % kv for kv in rows.items()))


def main(argv):
    args, limit, out, ids, fixed, reports, was, it = [], MAX_CLAIMS, None, None, None, None, None, iter(argv[1:])
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
        elif a == "--reports":
            reports = next(it, None)
        elif a == "--was":
            was = next(it, None)
        else:
            args.append(a)
    if len(args) != 2 or not os.path.isfile(args[0]) or not os.path.isdir(args[1]) or limit is None or (out is not None and not out) \
            or (ids is not None and not os.path.isfile(ids)) or (fixed is not None and (not fixed or ids is None or not reports)) \
            or (reports is not None and (not os.path.isdir(reports) or fixed is None)) or (was is not None and (ids is None or not os.path.isfile(was))):
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
            if was:
                with open(was, encoding="utf-8", errors="replace") as f:
                    moved = changed_since(f.read(), claims, text, repo)
                chosen = [c for c in claims if c in chosen or c[0] in moved]
        except SliceError as e:
            print(e, file=sys.stderr)
            return 1
        slices = cut_ids(chosen, p1, limit)
    else:
        chosen = claims
        per_line = {}
        for c in claims:
            per_line[c[1]] = per_line.get(c[1], 0) + 1
        slices = cut(text, per_line, limit)
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
        record_fixed(fixed, chosen, p1, read_verdicts(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
