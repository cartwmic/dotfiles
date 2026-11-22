#!/usr/bin/env python3
"""Turn the coverage grades of a guide into a to-do list for the writers, and record the coverage.

usage: coverage.py <facts.txt> <grades.md> <GUIDE.md> <repo> --label NAME --work DIR (--grow WORDS | --budget WORDS) [--words-per-fact N] [--min PERCENT]
       coverage.py --facts <facts.txt> <repo>

facts.txt   the lister's must-know facts, one a line: `F<n> | core|detail | kind | the fact | path:line` (a range `path:START-END` is fine). The cited line is where the code shows it.
            kind is purpose, run, setting, limit, failure, flow or interface. The same file is graded at every label, so the figures compare.
grades.md   the grader's rows, one for each fact: `F<n> | COVERED|PARTIAL|MISSING | "a line of the guide, verbatim"` (MISSING takes `-` in place of the quote). A fact that
            several lines state together carries one quote for each line, `"line one" | "line two"`; every quote must be in the guide.
GUIDE.md    the guide the grader saw. A quote that is not in it (tags, backticks and spacing aside) is dropped: a row left with no quote counts as MISSING, a COVERED row that lost
            a quote counts as PARTIAL, and the to-do says so.
--label     the name of this grade: letters, digits and dashes (`extend`, `pass2`). A label already recorded in DIR is refused: the earlier record is never overwritten.
--grow      the words the guide may grow by now (1,500 for an extend pass). The room for the to-do is that figure.
--budget    the whole-guide word budget instead (7,000, or 3,500 under 30k lines): the room is that budget less the words the guide has now, counted as
            `check_citations.py --max-words` counts them. Give one of --grow and --budget.
--words-per-fact  the words one to-do row is estimated to cost (default 25). The to-do lists as many rows as the room holds at that figure, in this order: core facts first,
            then MISSING before PARTIAL, then fact number. The rest go in `coverage.md` under `## Did not fit (<label>)` and at the end of the to-do: no writer works them.
--min       exit 1 when COVERED facts are fewer than this percent of all facts (the files are written first).

--facts     only checks the lister's file (every row well formed, every cited line in the repo, no repeated id, at most 100 facts) and prints the counts: run it before any grader starts.

Writes to DIR: `coverage-<label>.json` (counts, rates, each fact's grade, the room and the `--max-words` figure the check should use: the guide's words now plus the room),
`coverage-<label>.todo.md` (what to edit and add) and one row in `coverage.md` (every label, side by side).
A PARTIAL fact is routed to the guide line that holds its quote (`edit line A4.3f9a`): the line id to edit in place. A Part 1 quote is routed to the appendix line its tag
points at. A MISSING fact goes under the appendix section whose citations name the same file (else the one whose cited files share the longest folder prefix with its file, else A3), with the nearest line of that section that cites the file (`add next to A4.3f9a`).
The core facts that fit are listed again as Part 1 candidates with the words left under the Part 1 cap. Prints one line: label, counts, COVERED percent, Part 1 words, the room.
Exit 1 when a file is malformed (a fact with no row or two rows, a row for no fact, a fact citing a line the repo lacks, more than 100 facts, a label already recorded) or --min is not met; 2 on bad usage.
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

MAX_FACTS = 100  # the lister's cap: a longer list is more than a guide's word room holds
WORDS_PER_FACT = 25  # the words one to-do row is estimated to cost when no --words-per-fact is given
KINDS = ("purpose", "run", "setting", "limit", "failure", "flow", "interface")
STATES = ("COVERED", "PARTIAL", "MISSING")
FACT_ROW = re.compile(r"^(F\d+)\s*\|\s*(core|detail)\s*\|\s*(%s)\s*\|\s*(.+?)\s*\|\s*([^\s|]+:\d+(?:-\d+)?)\s*$" % "|".join(KINDS))
GRADE_ROW = re.compile(r"^(F\d+)\s*\|\s*(COVERED|PARTIAL|MISSING)\s*\|\s*(.*?)\s*$")
OPEN_QUOTES, CLOSE_QUOTES = '"\u201c', '"\u201d'
# A citation span: a backticked `path:line` or `path:start-end`; a run of them split by commas or semicolons is one.
_ONE = r"`[^`\n]*[\w/.@+-]:\d+[^`\n]*`"
CITATION_SPAN = re.compile(_ONE + r"(?:\s*[,;]\s*" + _ONE + r")*")
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
    if len(out) > MAX_FACTS:
        raise CoverageError("%s holds %d facts, over the cap of %d: send it back to the lister to keep the %d that matter most (core first)" % (path, len(out), MAX_FACTS, MAX_FACTS))
    return out


def read_grades(path, facts):
    """{id: (state, [quote])}. Raises CoverageError for a fact with no row or two rows, or a row for an id that is not a fact."""
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
        out[fid] = (state, quotes_of(quote))
    missing = [f[0] for f in facts if f[0] not in out]
    if missing:
        raise CoverageError("%s has no row for: %s (the grader skipped them: run it again)" % (path, ", ".join(missing)))
    return out


QUOTE_GAP = re.compile('["\u201d]\\s*\\|\\s*["\u201c]')


def quotes_of(cell):
    """The quotes of a grade row's last cell: the text between its first quote mark and its last (a note after the closing mark, `(value differs)`, is not part of it),
    split where one quote closes and the next opens with a bar between (`"line one" | "line two"`); a cell with no quote marks is taken whole, as one quote."""
    cell = cell.strip()
    if cell and cell[0] in OPEN_QUOTES:
        close = max(cell.rfind(q) for q in CLOSE_QUOTES)
        if close > 0:
            return [q.strip() for q in QUOTE_GAP.split(cell[1:close])]
    return [cell]


def squash(text):
    """A text as a quote is compared: tags, citations, backticks, quotation marks and spacing out, no space before a mark of punctuation, lower case."""
    text = CITATION_SPAN.sub(" ", TAG.sub(" ", text)).replace("`", " ").replace('"', " ").replace("\u201c", " ").replace("\u201d", " ")
    return re.sub(r"\s+([.,;:!?])", r"\1", re.sub(r"\s+", " ", text)).strip().lower()


def verify(grades, guide):
    """{id: (state, [quotes], where, why)}: a quote that is not in the guide is dropped. A row left with no quote becomes MISSING; a COVERED row that lost a quote becomes PARTIAL.
    The row says why when it changed. where is "part1" (every quote is in Part 1), "appendix" or ""."""
    whole, part1 = squash(guide), squash(part1_slice(guide))
    out = {}
    for fid, (state, quotes) in grades.items():
        if state == "MISSING":
            out[fid] = ("MISSING", [], "", "")
            continue
        kept = [q for q in quotes if squash(q) not in ("", "-") and squash(q) in whole]
        if not kept:
            blank = all(squash(q) in ("", "-") for q in quotes)
            out[fid] = ("MISSING", [] if blank else quotes, "", "graded %s with no quote" % state if blank else "graded %s but the quote is not in the guide" % state)
            continue
        why = ""
        if len(kept) < len(quotes):
            why = "graded %s but a quote is not in the guide" % state
            state = "PARTIAL"
        out[fid] = (state, kept, "part1" if all(squash(q) in part1 for q in kept) else "appendix", why)
    return out


def sections(guide, repo):
    """{file: {section number: lines citing it}} of the appendix, to suggest where a fact belongs. A line counts for the section file its id names (`A4.3f9a` is A4's),
    not the section it sits in: assemble.py gathers the table rows of every file into sections of their own that have no file."""
    lines, raw = appendix_lines(guide, repo), guide.split("\n")
    by_file = {}
    for l in lines:
        home = l["ids"][0].split(".")[0][1:] if l["ids"] else l["section"]
        for _, _, cites, _ in line_items(raw[l["line"] - 1], repo):
            for path, _, _ in cites:
                by_file.setdefault(path, {})
                by_file[path][home] = by_file[path].get(home, 0) + 1
    return by_file


def shared_folders(a, b):
    """How many leading folders two repo paths share (`src/net/tcp.py` and `src/net/retry.py` share two)."""
    n = 0
    for x, y in zip(a.split("/")[:-1], b.split("/")[:-1]):
        if x != y:
            break
        n += 1
    return n


def suggest(cite, by_file):
    """The appendix section to add a fact to: the one with most citations of the fact's file; else the one whose cited files share the longest folder prefix with it
    (the lowest section number on a tie); else A3, because the fact row names no section."""
    path = CITE.match(cite).group(1)
    counts = by_file.get(path, {})
    if counts:
        return "A" + min(counts, key=lambda s: (-counts[s], int(s)))
    near = {}
    for other, secs in by_file.items():
        depth = shared_folders(path, other)
        for sec in secs:
            near[sec] = max(near.get(sec, 0), depth)
    best = max(near.values(), default=0)
    return "A" + (min((s for s in near if near[s] == best), key=int) if best else "3")


def guide_lines(guide, repo):
    """[{id, ids, home, squashed, cites, line}] for each appendix line of the guide: its first id, the section its id names (the file that holds it), its text as a quote is compared,
    the (path, lo, hi) it cites, and its doc line."""
    raw, out = guide.split("\n"), []
    for l in appendix_lines(guide, repo):
        text = raw[l["line"] - 1]
        cites = [c for _, _, cs, _ in line_items(text, repo) for c in cs]
        out.append({"id": l["ids"][0] if l["ids"] else None, "ids": l["ids"], "home": l["ids"][0].split(".")[0][1:] if l["ids"] else l["section"], "squashed": squash(text),
                    "cites": cites, "line": l["line"]})
    return out


def distance(cites, path, lo, hi):
    """How far the nearest range of `cites` in `path` lies from lines lo-hi (0 when they overlap); None when none is in that file."""
    near = [max(0, a - hi, lo - b) for p, a, b in cites if p == path]
    return min(near) if near else None


def route_partial(row, lines, guide, repo):
    """(section number, line id, how) for a PARTIAL row: the line to edit in place. The guide line that holds a quote (the one citing the fact's file when several do); a quote of Part 1
    goes to the appendix line the sentence is tagged with. How: "edit", "edit via Part 1", or "guess" when no one line holds a quote."""
    path = CITE.match(row["cite"]).group(1)
    qs = [squash(q) for q in row["quotes"]]
    by_id = {i: l for l in lines for i in l["ids"]}
    holders = [l for l in lines if l["id"] and any(q and q in l["squashed"] for q in qs)]
    holders.sort(key=lambda l: (distance(l["cites"], path, 0, 10 ** 9) is None, l["line"]))
    if holders:
        return holders[0]["home"], holders[0]["id"], "edit"
    if row["where"] == "part1":
        for text in part1_slice(guide).split("\n"):
            if any(q and q in squash(text) for q in qs):
                tags = [t.strip("[]") for t in TAG.findall(text) if t.strip("[]") in by_id]
                tags.sort(key=lambda t: distance(by_id[t]["cites"], path, 0, 10 ** 9) is None)
                if tags:
                    return by_id[tags[0]]["home"], tags[0], "edit via Part 1"
    return None, None, "guess"


def route_missing(row, lines, section):
    """The nearest line of `section` (by the lines of the fact's file it cites) to add the new line next to: (id, cite text), or None when no line of it cites the file."""
    c = CITE.match(row["cite"])
    path, lo, hi = c.group(1), int(c.group(2)), int(c.group(3) or c.group(2))
    best = None
    for l in lines:
        if l["home"] != section[1:] or not l["id"]:
            continue
        d = distance(l["cites"], path, lo, hi)
        if d is not None and (best is None or d < best[0]):
            best = (d, l)
    if not best:
        return None
    l = best[1]
    near = min((c for c in l["cites"] if c[0] == path), key=lambda c: max(0, c[1] - hi, lo - c[2]))
    return l["id"], "%s:%d%s" % (near[0], near[1], "-%d" % near[2] if near[2] != near[1] else "")


def rank(rows):
    """The to-do order: core first, then MISSING before PARTIAL, then fact number."""
    return sorted((r for r in rows if r["state"] != "COVERED"), key=lambda r: (not r["core"], r["state"] != "MISSING", int(r["id"][1:])))


def build(facts, grades, guide, repo, budget=None, words_per_fact=WORDS_PER_FACT, grow=None):
    """The record of one grade. The room for the to-do is `grow` words, or `budget` less the words the guide has now; give one of them."""
    checked = verify(grades, guide)
    by_file, lines = sections(guide, repo), guide_lines(guide, repo)
    rows = []
    for fid, core, kind, fact, cite in facts:
        state, quotes, where, why = checked[fid]
        r = {"id": fid, "core": core, "kind": kind, "fact": fact, "cite": cite, "state": state, "quotes": quotes, "where": where, "why": why, "section": suggest(cite, by_file),
             "line_id": None, "route": "", "near": None}
        if state == "PARTIAL":
            sec, lid, how = route_partial(r, lines, guide, repo)
            r["route"], r["line_id"] = how, lid
            if lid:
                r["section"] = "A" + sec
        elif state == "MISSING":
            r["route"] = "add"
            near = route_missing(r, lines, r["section"])
            r["near"] = list(near) if near else None
        rows.append(r)
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in STATES}
    total = len(rows)
    words, guide_words = word_count(part1_slice(guide), repo), word_count(guide, repo)
    budget = guide_words + grow if grow is not None else budget
    room = budget - guide_words
    fit = max(0, room // words_per_fact)
    order = rank(rows)
    listed = {r["id"] for r in order[:fit]}
    for r in rows:
        r["listed"] = r["id"] in listed
    return {"facts": total, **{s.lower(): counts[s] for s in STATES},
            "covered_percent": round(100.0 * counts["COVERED"] / total, 1), "covered_or_partial_percent": round(100.0 * (counts["COVERED"] + counts["PARTIAL"]) / total, 1),
            "core": sum(1 for r in rows if r["core"]), "core_covered": sum(1 for r in rows if r["core"] and r["state"] == "COVERED"),
            "part1_words": words, "part1_room": WORDS_MAX - words,
            "guide_words": guide_words, "budget": budget, "room": room, "words_per_fact": words_per_fact, "fit": fit,
            "todo": [r["id"] for r in order[:fit]], "did_not_fit": [r["id"] for r in order[fit:]], "rows": rows}


def row_line(r):
    has = " | ".join(x for x in (r["why"], "guide has: %s" % " | ".join('"%s"' % q for q in r["quotes"]) if r["state"] == "PARTIAL" else "") if x) or "guide has no line for it"
    out = "- %s %s %s | %s | code: `%s` | %s" % (r["id"], r["state"], "core" if r["core"] else "detail", r["fact"], r["cite"], has)
    if r["state"] == "PARTIAL":
        if r["route"] == "guess":
            return out + " | edit the line that says it (no one line holds the quote: the section is a guess)"
        return out + " | edit line %s in place%s" % (r["line_id"], " (the Part 1 sentence is tagged to it)" if r["route"] == "edit via Part 1" else "")
    if r["near"]:
        return out + " | add next to %s (cites `%s`)" % (r["near"][0], r["near"][1])
    return out + " | add after the last prose line of its section (no line of it cites this file)"


def todo_text(label, rec):
    rows = {r["id"]: r for r in rec["rows"]}
    todo = [rows[i] for i in rec["todo"]]
    left = [rows[i] for i in rec["did_not_fit"]]
    out = ["# Coverage to-do (%s): %d of %d facts to work, %d did not fit" % (label, len(todo), rec["facts"], len(left)), "",
           "Room: %d words left of the %d-word budget (the guide has %d), at %d words a fact: %d facts listed, ranked core first, then MISSING before PARTIAL." % (
               rec["room"], rec["budget"], rec["guide_words"], rec["words_per_fact"], rec["fit"]),
           "A PARTIAL fact is an edit: change the line it names in place, keeping its id, and say what it lacked. A MISSING fact is a new cited sentence on its own line, placed next to the line it names",
           "(`references/drafting.md`): the value, default, limit, unit and failure result the code has. The writer drafts the new and changed lines in `cov-A<n>.md` and audits that file (`references/extend.md`).", ""]
    for sec in sorted({r["section"] for r in todo}, key=lambda s: int(s[1:])):
        out.append("## %s" % sec)
        out.append("Files: " + ", ".join(sorted({CITE.match(r["cite"]).group(1) for r in todo if r["section"] == sec})))
        out += [row_line(r) for r in todo if r["section"] == sec]
        out.append("")
    core = [r for r in todo if r["core"]]
    out += ["## Part 1 (core facts)", "",
            "Part 1 holds %d of %d words: room %d. Add one plain sentence of at most 18 words for a core fact below, tagged to its new or edited appendix line, while room lasts and `lint_main.py` passes;" % (rec["part1_words"], WORDS_MAX, rec["part1_room"]),
            "a fact that does not fit stays in the appendix only. Never cut How to start or the Who it is for sentence.", ""]
    out += ["- %s | %s" % (r["id"], r["fact"]) for r in core] or ["- none: no core fact is left to add"]
    if left:
        out += ["", "## Did not fit (no writer works these)", ""] + ["- %s %s %s | %s | code: `%s`" % (r["id"], r["state"], "core" if r["core"] else "detail", r["fact"], r["cite"]) for r in left]
    return "\n".join(out) + "\n"


HEAD = ["| label | facts | covered | partial | missing | covered % | covered or partial % | core covered | Part 1 words |", "|---|---|---|---|---|---|---|---|---|"]


def log_row(label, rec):
    return "| %s | %d | %d | %d | %d | %s | %s | %d of %d | %d |" % (label, rec["facts"], rec["covered"], rec["partial"], rec["missing"], rec["covered_percent"],
                                                                 rec["covered_or_partial_percent"], rec["core_covered"], rec["core"], rec["part1_words"])


def log_text(old, label, rec):
    """coverage.md with this label's row at the end of the table (the table is the lines that start with `|`) and, when facts did not fit, its list after what is there."""
    lines = old.rstrip("\n").split("\n") if old and old.strip() else list(HEAD)
    k = 0
    while k < len(lines) and lines[k].startswith("|"):
        k += 1
    rows = {r["id"]: r for r in rec["rows"]}
    out = lines[:k] + [log_row(label, rec)] + lines[k:]
    if rec["did_not_fit"]:
        out += ["", "## Did not fit (%s)" % label, "", "Room %d words at %d a fact: %d facts listed, %d did not fit." % (rec["room"], rec["words_per_fact"], len(rec["todo"]), len(rec["did_not_fit"])), ""]
        out += ["- %s %s %s | %s | code: `%s`" % (i, rows[i]["state"], "core" if rows[i]["core"] else "detail", rows[i]["fact"], rows[i]["cite"]) for i in rec["did_not_fit"]]
    return "\n".join(out) + "\n"


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
    text = log_text(read(log) if os.path.isfile(log) else "", label, rec)  # read before open() empties the file
    with open(log, "w", encoding="utf-8") as f:
        f.write(text)


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
        if a in ("--label", "--work", "--min", "--budget", "--grow", "--words-per-fact"):
            opts[a] = next(it, None)
        else:
            args.append(a)
    low = opts.get("--min")
    bad_min = low is not None and not re.fullmatch(r"\d+(?:\.\d+)?", low)
    if len(args) != 4 or not all(os.path.isfile(a) for a in args[:3]) or not os.path.isdir(args[3]) or not LABEL.match(opts.get("--label") or "") \
            or not opts.get("--work") or not os.path.isdir(opts["--work"]) or bad_min \
            or ("--budget" in opts) == ("--grow" in opts) or not re.fullmatch(r"[1-9]\d*", opts.get("--budget") or opts.get("--grow") or "") \
            or not re.fullmatch(r"[1-9]\d*", opts.get("--words-per-fact") or str(WORDS_PER_FACT)):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    facts_path, grades_path, guide_path, repo = args[0], args[1], args[2], os.path.realpath(args[3])
    try:
        facts = read_facts(facts_path, repo)
        rec = build(facts, read_grades(grades_path, facts), read(guide_path), repo, int(opts["--budget"]) if "--budget" in opts else None,
                    int(opts.get("--words-per-fact") or WORDS_PER_FACT), int(opts["--grow"]) if "--grow" in opts else None)
        record(opts["--work"], opts["--label"], rec)
    except CoverageError as e:
        print(e, file=sys.stderr)
        return 1
    print("%s: %d facts, covered %d, partial %d, missing %d: %s%% covered, %s%% covered or partial; core %d of %d covered; Part 1 %d of %d words; to-do %d facts, %d did not fit (room %d words; check_citations --max-words %d)" % (
        opts["--label"], rec["facts"], rec["covered"], rec["partial"], rec["missing"], rec["covered_percent"], rec["covered_or_partial_percent"],
        rec["core_covered"], rec["core"], rec["part1_words"], WORDS_MAX, len(rec["todo"]), len(rec["did_not_fit"]), rec["room"], rec["budget"]))
    if low is not None and rec["covered_percent"] < float(low):
        print("BELOW %s%%: %d facts are still not covered (coverage-%s.todo.md)" % (low, rec["partial"] + rec["missing"], opts["--label"]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
