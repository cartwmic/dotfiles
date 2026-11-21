#!/usr/bin/env python3
"""The two steps of an extend pass that read a shipped GUIDE.md (references/extend.md): the index the Part 1 writer tags from, and the slices of only the lines the pass wrote.

usage: extend.py index GUIDE.md <repo>
       extend.py diff OLD.md NEW.md <repo> --out DIR [--max-claims N] [--todo coverage-LABEL.json]

index   prints every appendix line of GUIDE.md as `A4.3f9a | sentences` (the id the line carries, citations taken out), as `assemble.py --index` does for a work folder.
        An extend pass has no work folder of section files: the shipped guide is the only copy.
diff    compares NEW.md with OLD.md, the guide as the earlier pass shipped it, and cuts into slices (as `slice.py --ids` does, and `score.py --slices DIR` reads) the claims a
        checker must look at, and no others: a line the pass added or edited, a Part 1 sentence it added or changed, and the claims whose judgment can change with them.
        A claim is picked for one of these reasons, all written to DIR/context.txt, one a line, as `N.k | reason | sentence`:
          new line / edited line   an appendix line whose id is not in OLD, or is in OLD with other words;
          changed                  any other claim `slice.py --was` finds changed: reworded, retagged, recited, split, or moved;
          line before a changed    the claim just before a changed claim, in the same part of the guide: the checker brief lets a condition sit on the next line, and that line is new;
          Part 1, tagged line      a Part 1 sentence tagged to an appendix line that was added or edited: it may now say more than that line shows.
        Writes DIR/changed.txt (the ids, for `final_recheck.py` and `slice.py --ids`), DIR/context.txt, and slice-K.claims.txt, slice-K.flags.txt and slices.json as slice.py does.
        Prints the slices, then `unchanged N, checked M (new A, edited E, ...)`, and one `REMOVED A4.3f9a | sentence` row for each old appendix line the new guide lacks.
--todo  the `coverage-<label>.json` the pass worked from: an old appendix line the pass edited that the to-do did not name (a PARTIAL fact's line) is printed as
        `NOT IN THE TO-DO A4.3f9a | sentence` and the exit code is 1 (the slices are written first). Run it right after the writers: a repair edit later is a different edit.
Exit 2 on bad usage. Stdlib only.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import TAG, appendix_index, claim_ids  # noqa: E402
from slice import MAX_CLAIMS, changed_since, cut_ids, emit, part1_lines  # noqa: E402


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def tags_of(sentence):
    return [t.strip("[]") for t in TAG.findall(sentence)]


def pick(old_text, text, repo):
    """(claims, {claim id: reason}, removed): the claims of `text`, the reason each one a checker must look at is picked, and the old appendix ids the new guide lacks."""
    claims = claim_ids(text, repo)
    old_index, index = appendix_index(old_text, repo), appendix_index(text, repo)
    p1 = part1_lines(text)
    in_p1 = lambda c: p1[0] <= c[1] < p1[1]
    moved = changed_since(old_text, claims, text, repo)
    touched = {i for i, (_, sentence, _) in index.items() if i not in old_index or old_index[i][1] != sentence}
    why = {}
    for c in claims:
        tags = tags_of(c[2])
        if not in_p1(c) and tags and tags[0] in touched:
            why[c[0]] = "new line" if tags[0] not in old_index else "edited line"
        elif c[0] in moved:
            why[c[0]] = "changed"
        elif in_p1(c) and any(t in touched for t in tags):
            why[c[0]] = "Part 1, tagged line"
    for prev, c in zip(claims, claims[1:]):
        if c[0] in why and why[c[0]] != "Part 1, tagged line" and prev[0] not in why and in_p1(prev) == in_p1(c):
            why[prev[0]] = "line before a changed"
    removed = [(i, old_index[i][1]) for i in old_index if i not in index]
    return claims, why, removed


def unlisted_edits(old_text, text, repo, todo_path):
    """[(id, sentence)]: old appendix lines the pass edited in place that the to-do (its listed PARTIAL rows) did not name."""
    named = {r["line_id"] for r in json.loads(read(todo_path))["rows"] if r.get("listed") and r["state"] == "PARTIAL" and r.get("line_id")}
    old_index, index = appendix_index(old_text, repo), appendix_index(text, repo)
    return [(i, index[i][1]) for i in index if i in old_index and old_index[i][1] != index[i][1] and i not in named]


def diff(argv):
    args, opts, it = [], {}, iter(argv)
    for a in it:
        if a in ("--out", "--max-claims", "--todo"):
            opts[a] = next(it, None)
        else:
            args.append(a)
    limit = opts.get("--max-claims", str(MAX_CLAIMS))
    if len(args) != 3 or not all(os.path.isfile(a) for a in args[:2]) or not os.path.isdir(args[2]) or not opts.get("--out") or not limit.isdigit() or not 0 < int(limit) <= MAX_CLAIMS \
            or ("--todo" in opts and not (opts["--todo"] and os.path.isfile(opts["--todo"]))):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    old_path, doc, repo = args[0], args[1], os.path.realpath(args[2])
    old_text, text = read(old_path), read(doc)
    claims, why, removed = pick(old_text, text, repo)
    chosen = [c for c in claims if c[0] in why]
    p1 = part1_lines(text)
    emit(cut_ids(chosen, p1, int(limit)), chosen, p1, doc, repo, True, opts["--out"])
    with open(os.path.join(opts["--out"], "changed.txt"), "w", encoding="utf-8") as f:
        f.write("".join(c[0] + "\n" for c in chosen))
    with open(os.path.join(opts["--out"], "context.txt"), "w", encoding="utf-8") as f:
        f.write("".join("%s | %s | %s\n" % (c[0], why[c[0]], c[2]) for c in chosen))
    reasons = {}
    for r in why.values():
        reasons[r] = reasons.get(r, 0) + 1
    print("unchanged %d, checked %d (%s)" % (len(claims) - len(chosen), len(chosen), ", ".join("%s %d" % (r, n) for r, n in sorted(reasons.items())) or "nothing changed"))
    for i, sentence in removed:
        print("REMOVED %s | %s" % (i, re.sub(r"\s+", " ", sentence)))
    status = 0
    if "--todo" in opts:
        for i, sentence in unlisted_edits(old_text, text, repo, opts["--todo"]):
            print("NOT IN THE TO-DO %s | %s" % (i, sentence))
            status = 1
    return status


def index(argv):
    if len(argv) != 2 or not os.path.isfile(argv[0]) or not os.path.isdir(argv[1]):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    for tag, (_, sentence, _) in appendix_index(read(argv[0]), os.path.realpath(argv[1])).items():
        print("%s | %s" % (tag, sentence))
    return 0


def main(argv):
    if len(argv) < 2 or argv[1] not in ("index", "diff"):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    return (index if argv[1] == "index" else diff)(argv[2:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
