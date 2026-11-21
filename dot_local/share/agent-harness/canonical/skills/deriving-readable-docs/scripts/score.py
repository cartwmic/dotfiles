#!/usr/bin/env python3
"""Score a round of checker reports, a lab draft, or a reader's answers. Reads files only; the arithmetic is the script's, not the lead's.

usage:
  score.py [NAME=]REPORTS... [--doc GUIDE.md ...] [--repo DIR] [--slices DIR] [--out FILE.json]
  score.py --lab BEHAVIOURS.txt DRAFT.md REPO [--out FILE.json]
  score.py --reader GUIDE.md [--answers ANSWERS.md]
  score.py --pool GROUP=SCORE.json,LAB.json [GROUP=SCORE.json,LAB.json ...]

Score. Each REPORTS is one repo: a folder of checker reports (every .md and .txt file in it, not below it) or one report file.
NAME= labels it (default: the folder or file name). A report ends with the line `Counts: claims checked N; HOLDS N; WRONG N;
OVERSTATED N; UNSUPPORTED N.` (references/check-brief.md) and has one finding line per error:
`claim id (N.k) | WRONG|OVERSTATED|UNSUPPORTED | CAUSE | ...` (a bare doc line N also counts), CAUSE one of MISSING_CONDITION, NAME, COUNT, KIND, OTHER. A finding with no cause
(a version 4 report) is counted as UNTAGGED. A report whose file name starts with `part1` is Part 1; every other report is the appendix.
Exit 1, naming the file, when a report has no Counts line or two, when HOLDS+WRONG+OVERSTATED+UNSUPPORTED is not claims checked,
or when its finding lines are not as many as WRONG+OVERSTATED+UNSUPPORTED. Nothing found for a repo is an error too.
The depth floor (check brief version 8). A report also holds one row for each claim it was given: `read | <claim id> | <verdict> | <path:line>`, the line the
checker actually opened (`outside` for a glossary entry with no tag or a table header row, which has no line). Exit 1 when it has no such rows (a report in the old format cannot be
judged), a row names no path:line (a HOLDS row too), the rows are not as many as claims checked or do not add up to the Counts line, or two rows share an id.
With --slices, a report that read fewer than one distinct line for every three claims also prints a depth warning (it never changes the exit code); the report records the
lines read, not the tool calls, so tool calls are not judged. With --repo, a path:line must be a line of a file in the repo. With --slices DIR (the folder slice.py wrote), the report's line `Slice: slice-K` names
DIR/slice-K.claims.txt, and the report must hold a row for every id of that file and for no other; `outside` is for the entries marked outside only.
Prints per repo, and pooled over all repos: claims, the four verdicts, errors, the rate (errors / claims) for all, the appendix and Part 1,
and claims by cause. With --doc (repeatable) and --repo it adds words, errors per 1,000 words and words per claim, counted as
check_citations.py counts them. With --out FILE.json it writes the numbers there and the printed text beside it as FILE.txt (a path, never a folder: a folder or a name that does not end in .json is a usage error).
When --slices names a folder that holds fewer claims than the guide (a fix round), the words, the words per claim and the errors per 1,000 words are those of the
re-checked sentences, not of the whole guide, so the counts compared are alike. The rates use the checkers' claim count. When the script counts the doc's sentences differently, the output adds
`claim count: checkers N, script M, difference +K`, so the two are never mixed up. Words per claim divides by the script's sentences.

--lab. BEHAVIOURS.txt is the scoper's list, one behaviour a line: `ID | path:line | cond, cond, ...` where path:line is the primary line a
sentence must cite and the conditions are the lines (path:line or path:start-end) a correct sentence must state; the conditions may be empty.
Prints behaviours kept (their primary line is inside some citation of the draft), condition lines cited (inside some citation), and conditional words
(when, if, unless, only, except, otherwise, falls back) per 1,000 words of the draft's claims. Lines starting with # are skipped.

--pool. Pools the drafts of a lab or a round. Each argument is GROUP=SCORE.json,LAB.json: the score.json of one draft (from the score run with
--doc, --repo and --out) and its lab.json (from --lab with --out). Arguments with the same GROUP are pooled; each group prints one row: words,
claims checked, errors, rate, errors and MISSING_CONDITION per 1,000 words, words per claim (pooled, and the mean of the drafts), behaviours kept,
condition lines cited, conditional words per 1,000, and the claim-count difference. Reads files only; it applies no pass or stop rule.

--reader. Without --answers: prints the reader's brief (the five questions of references/reader-check.md and Part 1 with its tags removed,
nothing else). With --answers: checks the reader's answers file (`## Q1` to `## Q5`, each with `> quoted sentence` lines): every quote must be a sentence
of Part 1 (tags removed, spaces collapsed), and every answer needs a quote or the words NOT IN TEXT. Exit 1 on a quote not in Part 1. It also prints the
words the reader listed under `## Unknown words` (`unknown words: N (a, b)`); that list is for the report and never fails the check.
Part 1 is the text from the heading `Part 1` to the heading `Part 2`.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import TAG, doc_lines, line_items, part1_slice, prose_sentences, split_lines, word_count, words_of  # noqa: E402

COUNTS = re.compile(r"^\W*Counts:\s+claims checked\s+(\d+);\s*HOLDS\s+(\d+);\s*WRONG\s+(\d+);\s*OVERSTATED\s+(\d+);\s*UNSUPPORTED\s+(\d+)\s*\.?\s*$", re.M)
FINDING = re.compile(r"^\s*(?:[-*]\s*)?(?:[^|\s]*?:)?(?:\d+(?:\.\d+)?|A\d+\.\w+)\s*\|\s*(WRONG|OVERSTATED|UNSUPPORTED)\s*\|(?:\s*(MISSING_CONDITION|NAME|COUNT|KIND|OTHER)\s*\|)?", re.M)
READ_ROW = re.compile(r"^\s*(?:[-*]\s*)?read\s*\|(.*)$", re.M | re.I)
SLICE_LINE = re.compile(r"^\W*Slice:\s*(\S+)\s*$", re.M)
EVIDENCE = re.compile(r"^(\S+?):(\d+)(?:-(\d+))?$")
VERDICTS = ("HOLDS", "WRONG", "OVERSTATED", "UNSUPPORTED")
CAUSES = ("MISSING_CONDITION", "NAME", "COUNT", "KIND", "OTHER", "UNTAGGED")
CONDITIONAL = re.compile(r"(?<![\w-])(when|if|unless|only|except|otherwise|falls? back)(?![\w-])", re.I)
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ScoreError(Exception):
    pass


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def parse_rows(path, text):
    """[(claim id, verdict, evidence)] for the `read | id | verdict | path:line` rows of a report. A row with no path:line (or `outside`) is an error."""
    rows, seen = [], set()
    for m in READ_ROW.finditer(text):
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 3 or not re.fullmatch(r"\d+\.\d+", cells[0]) or cells[1].upper() not in VERDICTS:
            raise ScoreError("%s: a row `read |%s` is not `read | <claim id N.k> | HOLDS, WRONG, OVERSTATED or UNSUPPORTED | <path:line>`" % (path, m.group(1).rstrip()))
        if not (EVIDENCE.match(cells[2]) or cells[2] == "outside"):
            raise ScoreError("%s: row %s names no path:line (the line the checker read; HOLDS too): `%s`" % (path, cells[0], cells[2]))
        if cells[0] in seen:
            raise ScoreError("%s: two rows for claim %s" % (path, cells[0]))
        seen.add(cells[0])
        rows.append((cells[0], cells[1].upper(), cells[2]))
    return rows


def check_rows(path, text, rows, counts, ctx):
    claims, tallies = counts[0], dict(zip(VERDICTS, counts[1:]))
    if not rows:
        raise ScoreError("%s: no `read | <claim id> | <verdict> | <path:line>` rows: check brief version 8 asks for one row for each claim, so a report in the old "
                         "format (a verdict count and no line read) cannot be judged" % path)
    shown = {v: sum(1 for r in rows if r[1] == v) for v in VERDICTS}
    if len(rows) != claims or shown != tallies:
        raise ScoreError("%s: the %d read rows show %s, but the Counts line says %d claims, %s" % (
            path, len(rows), ", ".join("%s %d" % kv for kv in shown.items()), claims, ", ".join("%s %d" % kv for kv in tallies.items())))
    if ctx.get("repo"):
        cache = {}
        for cid, _, ev in rows:
            m = EVIDENCE.match(ev)
            if not m:
                continue
            full = os.path.realpath(os.path.join(ctx["repo"], m.group(1)))
            if not (full.startswith(ctx["repo"] + os.sep) and os.path.isfile(full)):
                raise ScoreError("%s: row %s reads %s, which is not a file of the repo" % (path, cid, ev))
            if full not in cache:
                cache[full] = len(split_lines(read(full)))
            if int(m.group(2)) > cache[full] or int(m.group(3) or m.group(2)) > cache[full]:
                raise ScoreError("%s: row %s reads %s, but the file has %d lines" % (path, cid, ev, cache[full]))
    if ctx.get("slices"):
        name = SLICE_LINE.search(text)
        if not name or not re.fullmatch(r"[\w.-]+", name.group(1)):
            raise ScoreError("%s: no line `Slice: slice-K` naming the claims file it was given" % path)
        claims_file = os.path.join(ctx["slices"], name.group(1) + ".claims.txt")
        if not os.path.isfile(claims_file):
            raise ScoreError("%s: Slice %s has no %s" % (path, name.group(1), claims_file))
        given = {}
        for l in read(claims_file).splitlines():
            parts = [p.strip() for p in l.split("|", 2)]
            if len(parts) == 3:
                given[parts[0]] = parts[1]
        missing = [i for i in given if i not in {r[0] for r in rows}]
        extra = [r[0] for r in rows if r[0] not in given]
        if missing or extra:
            raise ScoreError("%s: no read row for claim %s of its slice%s" % (path, ", ".join(missing[:8]) + (" and %d more" % (len(missing) - 8) if len(missing) > 8 else ""),
                                                                             "; rows for claims not in it: " + ", ".join(extra[:8]) if extra else "") if missing else
                             "%s: rows for claims that are not in its slice: %s" % (path, ", ".join(extra[:8])))
        for cid, _, ev in rows:
            if (given[cid] == "outside") != (ev == "outside"):
                raise ScoreError("%s: row %s: `outside` is for an untagged glossary entry or a table header row only, and such a row takes `read | N.k | HOLDS | outside`, not a line" % (path, cid))


def parse_report(path, ctx=None):
    """{"file", "part1", "claims", "holds", "wrong", "overstated", "unsupported", "causes"} for one checker report."""
    text = read(path)
    found = COUNTS.findall(text)
    if len(found) != 1:
        raise ScoreError("%s: %s" % (path, "no `Counts: claims checked N; HOLDS N; WRONG N; OVERSTATED N; UNSUPPORTED N.` line" if not found else "%d Counts lines, expected one" % len(found)))
    claims, holds, wrong, over, unsup = map(int, found[0])
    if holds + wrong + over + unsup != claims:
        raise ScoreError("%s: HOLDS %d + WRONG %d + OVERSTATED %d + UNSUPPORTED %d is %d, not the %d claims checked" % (path, holds, wrong, over, unsup, holds + wrong + over + unsup, claims))
    rows = FINDING.findall(text)
    if len(rows) != wrong + over + unsup:
        raise ScoreError("%s: %d finding lines (`claim id | verdict | CAUSE | ...`), but WRONG+OVERSTATED+UNSUPPORTED is %d" % (path, len(rows), wrong + over + unsup))
    read_rows = parse_rows(path, text)
    check_rows(path, text, read_rows, (claims, holds, wrong, over, unsup), ctx or {})
    causes = dict.fromkeys(CAUSES, 0)
    for _, cause in rows:
        causes[cause or "UNTAGGED"] += 1
    distinct = {ev for _, _, ev in read_rows if ev != "outside"}
    warnings = []
    if (ctx or {}).get("slices") and claims and len(distinct) * 3 < claims:
        warnings.append("depth: %s read %d distinct lines for %d claims, below one in three" % (os.path.basename(path), len(distinct), claims))
    name = SLICE_LINE.search(text)
    return {"file": os.path.basename(path), "part1": os.path.basename(path).lower().startswith("part1"), "claims": claims, "holds": holds,
            "wrong": wrong, "overstated": over, "unsupported": unsup, "causes": causes, "warnings": warnings, "slice": name.group(1) if name else None}


def report_files(spec):
    if os.path.isdir(spec):
        files = sorted(os.path.join(spec, f) for f in os.listdir(spec) if f.endswith((".md", ".txt")) and os.path.isfile(os.path.join(spec, f)))
    elif os.path.isfile(spec):
        files = [spec]
    else:
        raise ScoreError("%s: no such file or folder" % spec)
    if not files:
        raise ScoreError("%s: no .md or .txt report found" % spec)
    return files


def totals(reports):
    t = {"claims": 0, "holds": 0, "wrong": 0, "overstated": 0, "unsupported": 0, "causes": dict.fromkeys(CAUSES, 0)}
    for r in reports:
        for k in ("claims", "holds", "wrong", "overstated", "unsupported"):
            t[k] += r[k]
        for c, n in r["causes"].items():
            t["causes"][c] += n
    t["errors"] = t["wrong"] + t["overstated"] + t["unsupported"]
    t["rate"] = t["errors"] / t["claims"] if t["claims"] else None
    return t


def slice_claims(slices):
    """The number of claims the slices folder holds (the sum of slices.json), or None when it has no slices.json."""
    path = os.path.join(slices, "slices.json")
    return sum(s["claims"] for s in json.loads(read(path))) if os.path.isfile(path) else None


def slice_sentences(slices, reports):
    """The sentences of the claims files that the reports name (`Slice: slice-K`), tags taken out: the claims a round re-checked."""
    out = []
    for r in reports:
        path = os.path.join(slices, "%s.claims.txt" % r["slice"]) if r["slice"] else ""
        if os.path.isfile(path):
            out += [TAG.sub(" ", l.split("|", 2)[2]).strip() for l in read(path).splitlines() if l.count("|") >= 2]
    return out


def score_repo(name, specs, docs, repo, slices=None):
    reports = [parse_report(f, {"repo": os.path.realpath(repo) if repo else None, "slices": slices}) for s in specs for f in report_files(s)]
    out = totals(reports)
    out["name"] = name
    out["warnings"] = [w for r in reports for w in r["warnings"]]
    out["reports"] = [r["file"] for r in reports]
    out["appendix"] = totals([r for r in reports if not r["part1"]])
    out["part1"] = totals([r for r in reports if r["part1"]])
    if docs:
        repo = os.path.realpath(repo)
        out["words"] = sum(word_count(read(d), repo) for d in docs)
        prose = [s for d in docs for _, s in prose_sentences(read(d), repo)]
        rechecked = slice_sentences(slices, reports) if slices and slice_claims(slices) not in (None, len(prose)) else None
        if rechecked is not None:  # a fix round re-checks some sentences: compare them with their own words, not with the whole guide's
            out["fix_round"] = (len(rechecked), len(prose))
            out["words"] = sum(len(words_of(x)) for x in rechecked)
            prose = rechecked
        claim_words = sum(len(words_of(s)) for s in prose)
        out["script_claims"] = len(prose)
        out["words_per_claim"] = claim_words / len(prose) if prose else None
        out["errors_per_1000_words"] = 1000 * out["errors"] / out["words"] if out["words"] else None
    return out


def pct(x):
    return "n/a" if x is None else "%.1f%%" % (100 * x)


def claim_count_note(checkers, script):
    return "claim count: checkers %d, script %d, difference %+d" % (checkers, script, script - checkers)


def render_repo(r):
    lines = ["repo %s (%d reports: %s)" % (r["name"], len(r["reports"]), ", ".join(r["reports"])),
             "claims checked: %d" % r["claims"], "HOLDS: %d" % r["holds"], "WRONG: %d" % r["wrong"], "OVERSTATED: %d" % r["overstated"],
             "UNSUPPORTED: %d" % r["unsupported"],
             "errors: %d out of %d claims" % (r["errors"], r["claims"]),
             "rate (W+O+U)/claims: %s  (%d/%d)" % (pct(r["rate"]), r["errors"], r["claims"]),
             "appendix rate: %s  (%d/%d)" % (pct(r["appendix"]["rate"]), r["appendix"]["errors"], r["appendix"]["claims"]),
             "part 1 rate: %s  (%d/%d)" % (pct(r["part1"]["rate"]), r["part1"]["errors"], r["part1"]["claims"]),
             "causes: " + ", ".join("%s %d" % (c, n) for c, n in r["causes"].items() if n) if r["errors"] else "causes: none"]
    if "words" in r:
        lines.append("words: %d; errors per 1,000 words: %s; script claims: %d; words per claim: %s" % (
            r["words"], "n/a" if r["errors_per_1000_words"] is None else "%.2f" % r["errors_per_1000_words"], r["script_claims"],
            "n/a" if r["words_per_claim"] is None else "%.1f" % r["words_per_claim"]))
        if "fix_round" in r:
            lines.append("fix round: %d of the guide's %d claims were re-checked; the words and the words per claim are those of the re-checked sentences" % r["fix_round"])
        if r["script_claims"] != r["claims"]:
            lines.append(claim_count_note(r["claims"], r["script_claims"]))
    for w in r.get("warnings", []):
        lines.append("warning %s (the report records the lines read, not the tool calls: those are not judged)" % w)
    return lines


def check_out_path(path):
    """--out names a file that ends in .json (the text, when there is one, goes beside it as .txt); a folder or any other name is a usage error."""
    if path is not None and (os.path.isdir(path) or not path.endswith(".json")):
        raise ScoreError("usage: --out takes a file path that ends in .json, not a folder (got %s)" % path)


def write_out(path, data, text=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data)
    if text is not None:
        with open(path[:-len(".json")] + ".txt", "w", encoding="utf-8") as f:
            f.write(text)


def cmd_score(argv):
    docs, repo, out_path, specs, slices = [], None, None, [], None
    it = iter(argv)
    for a in it:
        if a == "--doc":
            docs.append(next(it, None))
        elif a == "--slices":
            slices = next(it, None)
        elif a == "--repo":
            repo = next(it, None)
        elif a == "--out":
            out_path = next(it, None)
        elif a.startswith("--"):
            raise ScoreError("unknown option %s" % a)
        else:
            specs.append(a)
    if not specs or None in docs or (docs and not repo) or (slices is not None and not os.path.isdir(slices)):
        raise ScoreError("usage: score.py [NAME=]REPORTS... [--doc GUIDE.md ... --repo DIR] [--slices DIR] [--out FILE.json]")
    check_out_path(out_path)
    repos = []
    for spec in specs:
        name, _, path = spec.partition("=") if "=" in spec else (os.path.basename(os.path.normpath(spec)), "", spec)
        repos.append(score_repo(name, [path], docs if len(specs) == 1 else [], repo, slices))
    lines = []
    for r in repos:
        lines += render_repo(r) + [""]
    result = {"repos": repos}
    if len(repos) > 1:
        pooled = totals(repos)
        pooled["name"], pooled["reports"] = "all", [r["name"] for r in repos]
        pooled["appendix"] = totals([r["appendix"] for r in repos])
        pooled["part1"] = totals([r["part1"] for r in repos])
        lines += ["pooled over %d repos" % len(repos)] + render_repo(pooled)[1:]
        result["pooled"] = pooled
    print("\n".join(lines).rstrip())
    if out_path:
        write_out(out_path, json.dumps(result, indent=2), "\n".join(lines).rstrip() + "\n")
    return 0


# --- --lab ---------------------------------------------------------------------------------------------------
LOC = re.compile(r"^\s*(\S+?):(\d+)(?:-(\d+))?\s*$")


def parse_locs(text):
    out = []
    for part in [p for p in text.split(",") if p.strip()]:
        m = LOC.match(part)
        if not m:
            raise ScoreError("not a path:line or path:start-end: %r" % part.strip())
        out.append((m.group(1), int(m.group(2)), int(m.group(3) or m.group(2))))
    return out


def read_behaviours(path):
    rows = []
    for n, line in enumerate(read(path).splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2 or not parts[0]:
            raise ScoreError("%s:%d: expected `ID | path:line | cond, cond`" % (path, n))
        primary = parse_locs(parts[1])
        if len(primary) != 1:
            raise ScoreError("%s:%d: one primary path:line, not %d" % (path, n, len(primary)))
        rows.append((parts[0], primary[0], parse_locs(parts[2]) if len(parts) > 2 else []))
    if not rows:
        raise ScoreError("%s: no behaviours listed" % path)
    return rows


def covered(loc, cites):
    return any(c[0] == loc[0] and c[1] <= loc[1] <= c[2] for c in cites)


def cmd_lab(argv):
    out_path = None
    if "--out" in argv:
        i = argv.index("--out")
        out_path = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 3 or not os.path.isfile(argv[0]) or not os.path.isfile(argv[1]) or not os.path.isdir(argv[2]):
        raise ScoreError("usage: score.py --lab BEHAVIOURS.txt DRAFT.md REPO [--out FILE.json]")
    check_out_path(out_path)
    behaviours, draft, repo = read_behaviours(argv[0]), read(argv[1]), os.path.realpath(argv[2])
    cites = [c for _, line, _, _ in doc_lines(draft) for _, _, cs, _ in line_items(line, repo) for c in cs]
    kept = [b for b in behaviours if covered(b[1], cites)]
    conds = [(b[0], c) for b in behaviours for c in b[2]]
    # a condition given as a range is cited when its first line is inside a citation
    conds_cited = [x for x in conds if covered((x[1][0], x[1][1], x[1][2]), cites)]
    prose = [s for _, s in prose_sentences(draft, repo)]
    words = sum(len(words_of(s)) for s in prose)
    cond_words = sum(len(CONDITIONAL.findall(re.sub(r"`[^`]*`", " ", s))) for s in prose)
    result = {"behaviours": len(behaviours), "behaviours_kept": len(kept), "missed": [b[0] for b in behaviours if b not in kept],
              "condition_lines": len(conds), "condition_lines_cited": len(conds_cited),
              "conditions_not_cited": ["%s %s:%d" % (i, c[0], c[1]) for i, c in conds if (i, c) not in conds_cited],
              "claims": len(prose), "words": words, "words_per_claim": words / len(prose) if prose else None,
              "conditional_words": cond_words, "conditional_words_per_1000": 1000 * cond_words / words if words else None}
    lines = ["behaviours kept: %d of %d (%s)" % (len(kept), len(behaviours), pct(len(kept) / len(behaviours))),
             "condition lines cited: %d of %d (%s)" % (len(conds_cited), len(conds), pct(len(conds_cited) / len(conds) if conds else None)),
             "conditional words per 1,000 words: %.1f  (%d in %d)" % (result["conditional_words_per_1000"] or 0, cond_words, words),
             "claims: %d; words per claim: %.1f" % (len(prose), result["words_per_claim"] or 0)]
    if result["missed"]:
        lines.append("behaviours not cited: " + ", ".join(result["missed"]))
    if result["conditions_not_cited"]:
        lines.append("condition lines not cited: " + "; ".join(result["conditions_not_cited"]))
    print("\n".join(lines))
    if out_path:
        write_out(out_path, json.dumps(result, indent=2))
    return 0


# --- --pool --------------------------------------------------------------------------------------------------
def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise ScoreError("%s (%s): %s" % (path, what, e))


def pool_draft(score_path, lab_path):
    """The numbers of one draft: the checkers' side from its score.json, the script's side from its lab.json."""
    score, lab = load_json(score_path, "score.json"), load_json(lab_path, "lab.json")
    repos = score.get("repos") or []
    if not repos or any("words" not in r for r in repos):
        raise ScoreError("%s: no `words` (run the score with --doc and --repo, and --out)" % score_path)
    try:
        return {"words": sum(r["words"] for r in repos), "claims": sum(r["claims"] for r in repos), "errors": sum(r["errors"] for r in repos),
                "mc": sum(r["causes"]["MISSING_CONDITION"] for r in repos), "script_claims": sum(r["script_claims"] for r in repos),
                "beh": lab["behaviours"], "kept": lab["behaviours_kept"], "cond": lab["condition_lines"], "cond_cited": lab["condition_lines_cited"],
                "lab_claims": lab["claims"], "lab_words": lab["words"], "condw": lab["conditional_words"]}
    except KeyError as e:
        raise ScoreError("%s or %s: missing %s" % (score_path, lab_path, e))


def ratio(a, b):
    return a / b if b else 0.0


def render_pool(name, drafts):
    t = {k: sum(d[k] for d in drafts) for k in drafts[0]}
    mean_wpc = sum(ratio(d["lab_words"], d["lab_claims"]) for d in drafts) / len(drafts)
    line = ("%-22s drafts words %4d claims %3d(checked) errors %2d rate %.1f%%  err/1000w %.2f  MC/1000w %.2f  words/claim %.1f (mean of drafts %.1f)  "
            "behaviours %d/%d %.1f%%  cond lines %d/%d %.1f%%  conditional w/1000w %.1f" % (
                name, t["words"], t["claims"], t["errors"], 100 * ratio(t["errors"], t["claims"]), 1000 * ratio(t["errors"], t["words"]), 1000 * ratio(t["mc"], t["words"]),
                ratio(t["lab_words"], t["lab_claims"]), mean_wpc, t["kept"], t["beh"], 100 * ratio(t["kept"], t["beh"]), t["cond_cited"], t["cond"],
                100 * ratio(t["cond_cited"], t["cond"]), 1000 * ratio(t["condw"], t["lab_words"])))
    if t["script_claims"] != t["claims"]:
        line += "  " + claim_count_note(t["claims"], t["script_claims"])
    return line


def cmd_pool(argv):
    groups = {}
    for a in argv:
        name, eq, files = a.partition("=")
        score_path, comma, lab_path = files.partition(",")
        if not (name and eq and comma and score_path and lab_path):
            raise ScoreError("usage: score.py --pool GROUP=SCORE.json,LAB.json [GROUP=SCORE.json,LAB.json ...]")
        groups.setdefault(name, []).append(pool_draft(score_path, lab_path))
    if not groups:
        raise ScoreError("usage: score.py --pool GROUP=SCORE.json,LAB.json [GROUP=SCORE.json,LAB.json ...]")
    print("\n".join(render_pool(name, drafts) for name, drafts in groups.items()))
    return 0


# --- --reader ------------------------------------------------------------------------------------------------
def part1_text(guide):
    """Part 1 of a guide with its tags removed: what the reader gets."""
    part1 = part1_slice(guide)
    if not part1:
        raise ScoreError("no heading `Part 1` in the guide")
    lines = [re.sub(r"[ \t]+", " ", TAG.sub("", l)).rstrip() for l in part1.split("\n")]
    return "\n".join(l for l in lines if l is not None).strip()


def questions():
    text = read(os.path.join(SKILL, "references", "reader-check.md"))
    m = re.search(r"^## Questions\s*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    qs = re.findall(r"^\d+\.\s+(.+)$", m.group(1), re.M) if m else []
    if len(qs) != 5:
        raise ScoreError("references/reader-check.md has %d numbered questions under `## Questions`, expected 5" % len(qs))
    return qs


def squash_text(text):
    return " ".join(re.sub(r"[*_]", "", TAG.sub("", text)).split())


def cmd_reader(argv):
    answers = None
    if "--answers" in argv:
        i = argv.index("--answers")
        answers = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 1 or not os.path.isfile(argv[0]) or (answers is not None and not os.path.isfile(answers)):
        raise ScoreError("usage: score.py --reader GUIDE.md [--answers ANSWERS.md]")
    part1 = part1_text(read(argv[0]))
    if answers is None:
        qs = questions()
        print("You are a fresh reader. You have only the text below; do not look anything else up. Answer in a file with a heading `## Q1` to `## Q5`, "
              "each with your answer, then under it the sentence of the text you used, copied exactly, on a line starting with `> `. If the text does not say, "
              "write NOT IN TEXT. End with `## Unknown words`: every word or phrase you did not understand, one a line. Do not list a word the text itself defines "
              "where it first uses it.\n")
        print("\n".join("%d. %s" % (i, q) for i, q in enumerate(qs, 1)))
        print("\n---\n\n" + part1)
        return 0
    have, bad, quotes, section, per_q, unknown = squash_text(part1), [], 0, None, {}, []
    for n, line in enumerate(read(answers).splitlines(), 1):
        if re.match(r"#+\s+Unknown words\b", line, re.I):
            section = "unknown"
            continue
        if section == "unknown" and not re.match(r"#+\s", line):
            word = re.sub(r"^\s*(?:[-*]\s+)?", "", line).strip()
            if word:
                unknown.append(word)
            continue
        h = re.match(r"#+\s+(Q\d)\b", line)
        if h:
            section = h.group(1)
            per_q[section] = {"quote": False, "not_in_text": False}
            continue
        if re.match(r"#+\s", line):
            section = None
        if section and re.search(r"NOT IN TEXT", line):
            per_q[section]["not_in_text"] = True
        if section and line.startswith(">"):
            quote = squash_text(line.lstrip("> ").strip().strip("\"'“”"))
            quotes += 1
            per_q[section]["quote"] = True
            if quote not in have:
                bad.append((n, quote))
    for n, quote in bad:
        print("%s:%d: quote is not in Part 1: %s" % (answers, n, quote))
    missing = [q for q in ("Q1", "Q2", "Q3", "Q4", "Q5") if q not in per_q or not (per_q[q]["quote"] or per_q[q]["not_in_text"])]
    for q in missing:
        print("%s: %s has no quote and no NOT IN TEXT" % (answers, q))
    print("%d quotes, %d not in Part 1; %d answers without a quote" % (quotes, len(bad), len(missing)))
    print("unknown words: %d%s" % (len(unknown), " (%s)" % ", ".join(unknown) if unknown else ""))
    return 1 if bad or missing else 0


def main(argv):
    try:
        if argv[1:2] == ["--lab"]:
            return cmd_lab(argv[2:])
        if argv[1:2] == ["--pool"]:
            return cmd_pool(argv[2:])
        if argv[1:2] == ["--reader"]:
            return cmd_reader(argv[2:])
        return cmd_score(argv[1:])
    except ScoreError as e:
        print(e, file=sys.stderr)
        return 1 if "usage:" not in str(e) else 2
    except OSError as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
