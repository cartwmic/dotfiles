#!/usr/bin/env python3
"""Turn the coverage grades of a guide into a to-do list for the writers, and record the coverage.

usage: coverage.py <facts.txt> <grades.md> <GUIDE.md> <repo> --label NAME --work DIR [--min PERCENT]
       coverage.py --facts <facts.txt> <repo>

facts.txt   the lister's must-know facts, one a line: `F<n> | core|detail | kind | the fact | path:line` (a range `path:START-END` is fine). The cited line is where the code shows it.
            kind is purpose, run, setting, limit, failure, flow or interface. The same file is graded at every label, so the figures compare.
grades.md   the grader's rows, one for each fact: `F<n> | COVERED|PARTIAL|MISSING | "a line of the guide, verbatim" ` (MISSING takes `-` in place of the quote).
GUIDE.md    the guide the grader saw. A COVERED or PARTIAL quote that is not in it (tags, backticks and spacing aside) counts as MISSING, and the to-do says so.
--label     first (after round-1 assembly), repair (the shipped draft, after the fix rounds) or final (after the final re-check); any name of letters, digits and dashes.
            A label already recorded in DIR is refused: the earlier record is never overwritten.
--min       exit 1 when COVERED facts are fewer than this percent of all facts (the files are written first).

--facts     only checks the lister's file (every row well formed, every cited line in the repo, no repeated id) and prints the counts: run it before any grader starts.

Writes to DIR: `coverage-<label>.json` (counts, rates, each fact's grade), `coverage-<label>.todo.md` (what to add) and one row in `coverage.md` (every label, side by side).
The to-do lists each PARTIAL or MISSING fact under the appendix section whose citations name the same file (else A3), then the core ones again as Part 1 candidates with the words
left under the Part 1 cap. Prints one line: label, counts, COVERED percent, Part 1 words.
Exit 1 when a file is malformed (a fact with no row or two rows, a row for no fact, a fact citing a line the repo lacks, a label already recorded) or --min is not met; 2 on bad usage.
Stdlib only.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import TAG, appendix_lines, line_items, part1_slice, split_lines, word_count  # noqa: E402
from lint_main import WORDS_MAX  # noqa: E402

KINDS = ("purpose", "run", "setting", "limit", "failure", "flow", "interface")
STATES = ("COVERED", "PARTIAL", "MISSING")
FACT_ROW = re.compile(r"^(F\d+)\s*\|\s*(core|detail)\s*\|\s*(%s)\s*\|\s*(.+?)\s*\|\s*([^\s|]+:\d+(?:-\d+)?)\s*$" % "|".join(KINDS))
GRADE_ROW = re.compile(r"^(F\d+)\s*\|\s*(COVERED|PARTIAL|MISSING)\s*\|\s*(.*?)\s*$")
CITE = re.compile(r"^(.+):(\d+)(?:-(\d+))?$")
LABEL = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CoverageError(Exception):
    pass


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def read_facts(path, repo):
    """[(id, core, kind, fact, cite)] in file order. Raises CoverageError for a line that is not a fact row (comments and blank lines are skipped), a repeated id, or a cite the repo lacks."""
    out, seen = [], set()
    for n, line in enumerate(read(path).split("\n"), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = FACT_ROW.match(line)
        if not m:
            raise CoverageError("%s:%d: not a fact row (`F1 | core|detail | kind | the fact | path:line`, kind one of %s): %s" % (path, n, ", ".join(KINDS), line[:80]))
        fid, core, kind, fact, cite = m.groups()
        if fid in seen:
            raise CoverageError("%s:%d: %s is on two rows" % (path, n, fid))
        seen.add(fid)
        c = CITE.match(cite)
        lo, hi = int(c.group(2)), int(c.group(3) or c.group(2))
        target = os.path.join(repo, c.group(1))
        if not os.path.isfile(target) or lo < 1 or hi < lo or hi > len(split_lines(read(target))):
            raise CoverageError("%s:%d: %s cites %s, which is not a line of the repo: the lister invented the place" % (path, n, fid, cite))
        out.append((fid, core == "core", kind, fact, cite))
    if not out:
        raise CoverageError("%s holds no fact" % path)
    return out


def read_grades(path, facts):
    """{id: (state, quote)}. Raises CoverageError for a fact with no row or two rows, or a row for an id that is not a fact."""
    known, out = {f[0] for f in facts}, {}
    for n, line in enumerate(read(path).split("\n"), 1):
        m = GRADE_ROW.match(line.strip())
        if not m:
            continue
        fid, state, quote = m.groups()
        if fid not in known:
            raise CoverageError("%s:%d: %s is not in the facts file" % (path, n, fid))
        if fid in out:
            raise CoverageError("%s:%d: %s has two rows" % (path, n, fid))
        out[fid] = (state, quote.strip().strip('"\u201c\u201d').strip())
    missing = [f[0] for f in facts if f[0] not in out]
    if missing:
        raise CoverageError("%s has no row for: %s (the grader skipped them: run it again)" % (path, ", ".join(missing)))
    return out


def squash(text):
    """A text as a quote is compared: tags, backticks, quotation marks and spacing out, lower case."""
    text = TAG.sub(" ", text).replace("`", " ").replace('"', " ").replace("“", " ").replace("”", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def verify(grades, guide):
    """{id: (state, quote, where, why)}: a COVERED or PARTIAL row whose quote is not in the guide (or has none) becomes MISSING and says why; where is "part1", "appendix" or ""."""
    whole, part1 = squash(guide), squash(part1_slice(guide))
    out = {}
    for fid, (state, quote) in grades.items():
        q = squash(quote)
        if state == "MISSING":
            out[fid] = ("MISSING", "", "", "")
        elif not q or q == "-":
            out[fid] = ("MISSING", "", "", "graded %s with no quote" % state)
        elif q not in whole:
            out[fid] = ("MISSING", quote, "", "graded %s but the quote is not in the guide" % state)
        else:
            out[fid] = (state, quote, "part1" if q in part1 else "appendix", "")
    return out


def sections(guide, repo):
    """{file: {section number: lines citing it}} of the appendix, to suggest where a fact belongs."""
    lines, raw = appendix_lines(guide, repo), guide.split("\n")
    by_file = {}
    for l in lines:
        for _, _, cites, _ in line_items(raw[l["line"] - 1], repo):
            for path, _, _ in cites:
                by_file.setdefault(path, {})
                by_file[path][l["section"]] = by_file[path].get(l["section"], 0) + 1
    return by_file


def suggest(cite, by_file):
    """The appendix section to add a fact to: the one with most citations of the fact's file, else A3."""
    counts = by_file.get(CITE.match(cite).group(1), {})
    return "A" + (min(counts, key=lambda s: (-counts[s], int(s))) if counts else "3")


def build(facts, grades, guide, repo):
    checked = verify(grades, guide)
    by_file = sections(guide, repo)
    rows = []
    for fid, core, kind, fact, cite in facts:
        state, quote, where, why = checked[fid]
        rows.append({"id": fid, "core": core, "kind": kind, "fact": fact, "cite": cite, "state": state, "quote": quote, "where": where, "why": why, "section": suggest(cite, by_file)})
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in STATES}
    total = len(rows)
    words = word_count(part1_slice(guide), repo)
    return {"facts": total, **{s.lower(): counts[s] for s in STATES},
            "covered_percent": round(100.0 * counts["COVERED"] / total, 1), "covered_or_partial_percent": round(100.0 * (counts["COVERED"] + counts["PARTIAL"]) / total, 1),
            "core": sum(1 for r in rows if r["core"]), "core_covered": sum(1 for r in rows if r["core"] and r["state"] == "COVERED"),
            "part1_words": words, "part1_room": WORDS_MAX - words, "rows": rows}


def todo_text(label, rec):
    todo = [r for r in rec["rows"] if r["state"] != "COVERED"]
    out = ["# Coverage to-do (%s): %d of %d facts to add" % (label, len(todo), rec["facts"]), "",
           "Add each fact to the appendix as one cited sentence on its own line (`references/drafting.md`): the value, default, limit, unit and failure result the code has.",
           "A PARTIAL fact keeps its line and gains what it lacks. Then run stamp.py on the section file and check_citations.py on it.", ""]
    for sec in sorted({r["section"] for r in todo}, key=lambda s: int(s[1:])):
        out.append("## %s" % sec)
        for r in (r for r in todo if r["section"] == sec):
            has = r["why"] or ("guide has: \"%s\"" % r["quote"] if r["state"] == "PARTIAL" else "guide has no line for it")
            out.append("- %s %s %s | %s | code: `%s` | %s" % (r["id"], r["state"], "core" if r["core"] else "detail", r["fact"], r["cite"], has))
        out.append("")
    core = [r for r in todo if r["core"]]
    out += ["## Part 1 (core facts)", "",
            "Part 1 holds %d of %d words: room %d. Add one plain sentence of at most 18 words for a core fact below, tagged to its new appendix line, while room lasts and `lint_main.py` passes;" % (rec["part1_words"], WORDS_MAX, rec["part1_room"]),
            "a fact that does not fit stays in the appendix only. Never cut How to start or the Who it is for sentence.", ""]
    out += ["- %s | %s" % (r["id"], r["fact"]) for r in core] or ["- none: every core fact is covered"]
    return "\n".join(out) + "\n"


HEAD = ["| label | facts | covered | partial | missing | covered % | covered or partial % | core covered | Part 1 words |", "|---|---|---|---|---|---|---|---|---|"]


def log_row(label, rec):
    return "| %s | %d | %d | %d | %d | %s | %s | %d of %d | %d |" % (label, rec["facts"], rec["covered"], rec["partial"], rec["missing"], rec["covered_percent"],
                                                                 rec["covered_or_partial_percent"], rec["core_covered"], rec["core"], rec["part1_words"])


def record(work, label, rec):
    """Write the label's three files; refuse a label that was recorded already."""
    paths = [os.path.join(work, "coverage-%s.json" % label), os.path.join(work, "coverage-%s.todo.md" % label)]
    if any(os.path.exists(p) for p in paths):
        raise CoverageError("label %s is already recorded in %s: use another label; an earlier record is never overwritten" % (label, work))
    with open(paths[0], "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=2)
    with open(paths[1], "w", encoding="utf-8") as f:
        f.write(todo_text(label, rec))
    log = os.path.join(work, "coverage.md")
    lines = read(log).rstrip("\n").split("\n") if os.path.isfile(log) else HEAD
    with open(log, "w", encoding="utf-8") as f:
        f.write("\n".join(lines + [log_row(label, rec)]) + "\n")


def main(argv):
    if "--facts" in argv:
        rest = [a for a in argv[1:] if a != "--facts"]
        if len(rest) != 2 or not os.path.isfile(rest[0]) or not os.path.isdir(rest[1]):
            print(__doc__.split("\n\n")[0], file=sys.stderr)
            return 2
        try:
            facts = read_facts(rest[0], os.path.realpath(rest[1]))
        except CoverageError as e:
            print(e, file=sys.stderr)
            return 1
        print("%d facts, %d core" % (len(facts), sum(1 for f in facts if f[1])))
        return 0
    args, opts, it = [], {}, iter(argv[1:])
    for a in it:
        if a in ("--label", "--work", "--min"):
            opts[a] = next(it, None)
        else:
            args.append(a)
    low = opts.get("--min")
    bad_min = low is not None and not re.fullmatch(r"\d+(?:\.\d+)?", low)
    if len(args) != 4 or not all(os.path.isfile(a) for a in args[:3]) or not os.path.isdir(args[3]) or not LABEL.match(opts.get("--label") or "") \
            or not opts.get("--work") or not os.path.isdir(opts["--work"]) or bad_min:
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    facts_path, grades_path, guide_path, repo = args[0], args[1], args[2], os.path.realpath(args[3])
    try:
        facts = read_facts(facts_path, repo)
        rec = build(facts, read_grades(grades_path, facts), read(guide_path), repo)
        record(opts["--work"], opts["--label"], rec)
    except CoverageError as e:
        print(e, file=sys.stderr)
        return 1
    print("%s: %d facts, covered %d, partial %d, missing %d: %s%% covered, %s%% covered or partial; core %d of %d covered; Part 1 %d of %d words" % (
        opts["--label"], rec["facts"], rec["covered"], rec["partial"], rec["missing"], rec["covered_percent"], rec["covered_or_partial_percent"],
        rec["core_covered"], rec["core"], rec["part1_words"], WORDS_MAX))
    if low is not None and rec["covered_percent"] < float(low):
        print("BELOW %s%%: %d facts are still not covered (coverage-%s.todo.md)" % (low, rec["partial"] + rec["missing"], opts["--label"]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
