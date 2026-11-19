#!/usr/bin/env python3
"""Check the `path:line` citations in a derived doc: the line exists, and the cited text backs the sentence.

usage: check_citations.py <doc.md> <repo> [--points points.json [--left-out left-out.txt]] [--sheet]

A citation is a backticked `path:LINE` or `path:START-END` (paths relative to <repo>; a space after the colon is
read; several may share one backtick span, separated by commas or semicolons; one inside a span with other
words is read too if its path has a slash or an extension). Fenced code blocks are skipped. A URL, a clock
time, an IPv4 address or `host.com:8080` is ignored. A whole-span `Name:5` with no dot or slash is checked as a
file, so write a port or a key such as `status:200` without backticks.
Prints the number checked and each bad citation as `doc:line: citation: reason`.

Then it reads what the cited lines say. A claim is the words just before a citation, or before a run of citations
joined by commas or "and". These checks FAIL a claim, because a miss is a fact the cited lines do not show:
  number    every digit number in the claim (not in a citation; "about N" is skipped; 15 seconds also matches
            15000 and 15 * 1000) must appear in a cited range, widened by WINDOW lines each side, or in a cited
            path (journey 111). The words one..twenty in the cited text count as digits.
  string    every `backticked` or "double-quoted" string in the claim (a repo path that exists is exempt) must
            appear there. A one-word string must appear as written; a longer one needs each of its words.
  overreach a sentence with one of the words every, each, all, always, never, only, or a count in words ("three
            parts": two..twelve, dozen), whose citations are all test or journey files. A test proves the cases it
            runs, not a set. Not these: a word inside a hyphenated one ("read-only"), "each other", and "each" that
            spreads over a listed set ("A and B each", "once each", "one commit each"; an "and" after a comma does
            not close a list: ", and the message names each problem" FAILs). Cite the code that defines
            the set, or word the sentence to the test's case ("in the test", "in this case", "the test shows",
            "the test puts" and other "the test <verb>", "for example", "such as", "at least", "e.g."), or label it
            inferred or "from your list". A bare "the test" does not clear it. In a "Not backed" section a sentence
            that reports the search or what the tests do ("I grepped ... and found no match", "no test asserts it", "the
            only hits are in x.ts") is not judged here; not-backed below checks the entry. With --points a file is a test when the harvest lists it; without, when its
            path says so (tests/, .test., _test, journey, e2e, spec, conformance ...).
  uncited   a sentence after the doc header with no citation, source label ("(README)", "(code comment)"), or
            "inferred" / "from your list" in it, that holds a word of the overreach list below or a count of
            things in digits or words.
Listed too, whatever the citations, because a script cannot judge them (the check pass, references/check-brief.md, takes the list):
  overreach  every, each, all, always, never, only, next, none, any, no <noun> (and every/any + thing, one, where, body)
  count      a count of things: "three parts", "6 words" (a count in words also FAILs under overreach above)
  comment    every cited range is comment lines, and the sentence does not say it is from a comment, header or doc
With --points (the raw harvest, points.json), two more checks run:
  counts     the doc header's numbers for harvested, left out, used, read by name only and not cited must equal
             the numbers computed from the harvest and this doc's citations. A point is used when a citation of
             the doc overlaps its body (its start line up to the next point of the file); read by name only when
             every such citation is in a sentence that says inferred; left out when --left-out lists its id
             (`P12`) or its file (a path, or a folder ending in /), one per line. It prints the computed line,
             `Counts: harvested N; left out N; used N; read by name only N; not cited N.`, for the header.
  not-backed a string in a "Not backed" section that a test file of the harvest also contains, at a line the entry
             does not cite: the entry is wrong, or it cites that test.
--sheet prints every claim with the cited lines under it (the self-check read), and the checks above are skipped.
          Under a cited range inside a function (Python, TS/JS) it also lists the function's early exits above the
          range (return, throw, continue, break, process.exit): the other paths a sentence about the function must
          state or leave out. See early_exits.py; "no early exits" and "not listed" print differently.
Exit 0: all good. 1: a bad citation or a failed claim. 2: usage error, or no citations at all. Listed
sentences never change the exit code. Stdlib only.
"""
import bisect
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
import early_exits  # noqa: E402

SPAN = re.compile(r"`([^`\n]+)`")
PART = re.compile(r"^([^\s:`]+)\s*:\s*(\d+)(?:\s*-\s*(\d+))?$")
# A citation-shaped token inside a span that also holds other words, such as `see src/a.rs:2`.
EMBEDDED = re.compile(r"(?<![\w/.:@+-])([\w.@+/-]+)\s*:\s*(\d+)(?:-(\d+))?")
HOST_SUFFIXES = {"com", "org", "net", "io", "dev", "app", "internal", "local", "lan", "home"}
IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
WINDOW = 5  # lines each side of a cited range (sweep in the commit message)


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


def line_items(line, repo):
    """Return the backtick spans of one doc line as (start, end, cites, text); cites is [(path, start, end)],
    empty for a span that is not a citation."""
    items = []
    for m in SPAN.finditer(line):
        span = m.group(1)
        parts = [p.strip() for p in re.split(r"[;,]\s*", span.strip()) if p.strip()]
        matches = [PART.match(p) for p in parts]
        if parts and all(matches):
            found, strict = matches, True
        else:
            found, strict = list(EMBEDDED.finditer(span)), False
        cites = []
        for c in found:
            if is_path(repo, c.group(1), strict):
                lo = int(c.group(2))
                cites.append((c.group(1), lo, int(c.group(3)) if c.group(3) else lo))
        items.append((m.start(), m.end(), cites, span))
    return items


def doc_lines(text):
    """Yield (doc_line_no, line, in_header, is_heading) for each line outside fenced code blocks. A heading's
    citations are checked, but its words are not judged as a claim.
    The header is everything before the first `## ` heading (a doc with none has no header)."""
    fenced, header = False, any(l.startswith("## ") for l in text.splitlines())
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith("## "):
            header = False
        if not line.strip():
            continue
        yield n, line, header, line.startswith("#")


LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
JOIN = re.compile(r"^(?:[\s,;&]|and)*$")
LABEL = re.compile(r"^\s*\(([^)]*)\)")


def claims(text, repo):
    """Yield one dict per claim: line, text (the words before the citation group), cites, label (a parenthetical
    right after the group, such as "code comment"), uncited (words after the last group, or a whole line with none), and
    not_backed (the claim sits under a "Not backed" heading)."""
    section = False
    for n, line, header, heading in doc_lines(text):
        items = line_items(line, repo)
        if heading:
            section = bool(re.match(r"#+\s.*not backed", line, re.I))
            for _, _, cites, _ in items:
                if cites:
                    yield {"line": n, "text": "", "cites": cites, "label": "", "uncited": "", "header": header, "heading": True, "not_backed": section}
            continue
        groups = []  # [first_start, last_end, cites]
        for start, end, cites, _ in items:
            if not cites:
                continue
            if groups and JOIN.match(line[groups[-1][1]:start]):
                groups[-1][1] = end
                groups[-1][2].extend(cites)
            else:
                groups.append([start, end, list(cites)])
        prev = 0
        for start, end, cites in groups:
            label = LABEL.match(line[end:])
            if label and not SAYS_SOURCE.search(label.group(1)):
                label = None  # a parenthetical that is not a source label is a sentence: it is listed as uncited text
            yield {"line": n, "text": line[prev:start] if prev else LIST_MARK.sub("", line[:start]), "cites": cites, "label": label.group(1) if label else "",
                   "uncited": "", "header": header, "not_backed": section}
            prev = end + (label.end() if label else 0)
        if not header and line[prev:].strip():
            yield {"line": n, "text": "", "cites": [], "label": "", "uncited": line[prev:], "header": header, "not_backed": section}


# --- text that a script can compare ---------------------------------------------------------------------------
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
QUOTED = re.compile(r'"([^"\n]+)"|\u201c([^\u201d\n]+)\u201d')
# A whole word: not inside a hyphenated one ("read-only", "ask-only"), and not "each other".
OVERREACH = re.compile(r"(?<![\w-])(every(?:thing|one|where|body)?|each(?!\s+other\b)|all|always|never|only|next|none|any(?:thing|one|where|body)?|no(?=\s+(?!longer\b)[a-z]))(?![\w-])", re.I)
# The words the overreach FAIL is made of; a count of things ("three parts", "6 words") is COUNT below.
QUANT = re.compile(r"(?<![\w-])(every(?:thing|one|where|body)?|each(?!\s+other\b)|all|always|never|only)(?![\w-])", re.I)
# "each" that hands a verb or a number to a set the sentence lists: "A, B and C each give", "once each", "one commit each".
NUMBERISH = set(WORDS) | {"once", "twice", "thrice", "dozen"}
NOT_SUBJECT = {"on", "in", "of", "for", "to", "at", "by", "with", "from", "per", "into", "than", "and", "or", "but", "if", "when", "that", "the", "a", "an", "is", "are"}
# A sentence worded to the cases a test runs, or labelled as inferred or from the caller's list, is not an overreach.
# "the test" then a verb: the explicit list, or any word ending in -s that is not a noun or "is/was/has" ("the test puts").
TEST_VERB = r"(?:shows?|runs?|uses?|feeds?|sends?|asserts?|checks?|compares?|(?!(?:is|was|has|as|its|this|files|cases|suites|names|results|titles|paths|lines|ids|fixtures|helpers|scripts|inputs|outputs|steps|sources|tests|journeys)\b)(?![a-z]*ss\b)[a-z]+s)"
SCOPED = re.compile(r"\bin (?:the|this) (?:tests?|journeys?|fixtures?|case)\b|\bthe (?:tests?|journeys?) " + TEST_VERB + r"\b|\bthe (?:test|journey)'s\b|\bfor example\b|\bsuch as\b|\bat least\b|\be\.g\.|\binferred\b|\bfrom your list\b", re.I)
# In a "Not backed" section, a sentence that reports the search or what the tests do ("I grepped the tests for X and found
# no match", "no test asserts it", "the only hits are in pr.ts", "the tests only check the main file") says what was
# looked for; not_backed() checks the entry against the harvest.
SEARCH = re.compile(r"\b(?:grepp?ed|searched|searches|search|hits?|found|finds?|none|tests?|journeys?|match)\b", re.I)
# A test path by its name; used only when no harvest is given (--points), which decides it otherwise.
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|proof|journeys?|e2e|smoke|specs?|conformance|support)(/|\.)|\.(test|spec|journey)\.|_test\.|(^|/)test_|-journey|\.bats$", re.I)
# A count of things: "three parts", "6 words". Not a time ("45 minutes") or a bare status code ("409 and").
COUNT = re.compile(r"(?<![\w.])(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen|\d+)\s+(?!(?:is|was|has|does|as|this|its|his|yes)\b)(?:[a-z-]+\s+)?(?!(?:seconds?|minutes?|hours?|days?|weeks?|bytes?|times?|chars?|characters?)\b)[a-z-]+s\b", re.I)
TIME_SCALE = {"second": (1000,), "minute": (60, 60000), "hour": (60, 3600, 3600000), "day": (24, 86400, 86400000)}
TIME_UNIT = re.compile(r"^[\s-]*(second|minute|hour|day)s?\b", re.I)
APPROX = re.compile(r"(about|around|roughly|nearly|~)\s*$", re.I)
SAYS_SOURCE = re.compile(r"comment|header|readme|docs?\b|documentation|stated|says|source text|prd|agents\.md", re.I)
COMMENT_START = {
    "//": {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs", ".go", ".java", ".kt", ".c", ".h", ".cc", ".cpp", ".cs", ".swift", ".scala"},
    "#": {".py", ".sh", ".bash", ".zsh", ".rb", ".yml", ".yaml", ".toml", ".ex", ".exs", ".bats", ".tmpl"},
    "--": {".sql", ".lua", ".hs"},
}


def closes_list(before):
    """True if an "and" within the three words before "each" closes a list ("A, B and C each give"). An "and" that
    follows a comma joins two clauses (", and the message names each problem"), so it does not."""
    words = list(re.finditer(r"[\w'-]+", before))
    for w in words[-4:-1]:
        if w.group(0).lower() == "and" and not before[:w.start()].rstrip().endswith(","):
            return True
    return False


def quantifiers(sent):
    """The quantifier words of a sentence that a test cannot prove: QUANT without an "each" that spreads a verb or a
    number over a set the sentence lists ("A, B and C each give", "once each", "one commit each")."""
    out = []
    for m in QUANT.finditer(sent):
        if m.group(1).lower() == "each":
            before = re.findall(r"[\w'-]+", sent[:m.start()].lower())
            prev = before[-1] if before else ""
            counted = prev in NUMBERISH or prev.isdigit() or (len(before) > 1 and (before[-2] in NUMBERISH or before[-2].isdigit()) and prev not in NOT_SUBJECT)
            listed = prev not in NOT_SUBJECT and closes_list(sent[:m.start()])
            if counted or listed:
                continue
        out.append(m.group(1).lower())
    return out


def numbers_in(text):
    """The set of numbers in cited text: digits (2,000 = 2000 = 2_000) and the number words one..twenty."""
    text = re.sub(r"(?<=\d)[,_](?=\d{3}\b)", "", text)
    found = {m.group(0) for m in NUMBER.finditer(text)}
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in WORDS:
            found.add(str(WORDS.index(w)))
    return found


def squash(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def strings_in(claim_text, repo):
    """Backticked and double-quoted strings in a claim (not citations; quotes inside backticks are code). A repo path that exists is skipped."""
    out = [m.group(1) for m in SPAN.finditer(claim_text)] + [a or b for a, b in QUOTED.findall(strip_code(claim_text))]
    return [t for t in out if len(squash(t)) > 1 and not repo_file(repo, t.strip())]


def repo_file(repo, rel):
    full = os.path.realpath(os.path.join(repo, rel))
    return (full == repo or full.startswith(repo + os.sep)) and os.path.exists(full)


def string_in(tok, have):
    """A one-word string must appear as written; a longer one (a command, a message) may be split over tokens, so
    every word of it must appear."""
    words = [w for w in squash(re.sub(r"<[^>]*>|\.\.\.|\([^)]*\)", " ", tok)).split() if len(w) > 1]  # skip <placeholders>, ... and (N)
    if not words:
        return True
    if len(words) == 1:
        return words[0] in have
    present = set(have.split())
    return all(w in present for w in words)


def comment_only(lines, path):
    """True if every non-blank line of the range is a comment line in a code file."""
    ext = os.path.splitext(path)[1].lower()
    starts = [k for k, exts in COMMENT_START.items() if ext in exts]
    if not starts:
        return False
    body = [l.strip() for l in lines if l.strip()]
    marks = tuple(starts) + (("/*", "*", "*/") if "//" in starts else ())
    return bool(body) and all(l.startswith(marks) for l in body)


def sentences(text):
    return [s for s in re.split(r"(?<=[.!?;])\s+", text) if s.strip()]


def strip_code(text):
    return SPAN.sub(" ", text)


def read_lines(cache, repo, path):
    if path not in cache:
        with open(os.path.join(repo, path), "rb") as f:
            cache[path] = f.read().decode("utf-8", errors="replace").splitlines()
    return cache[path]


def check_claim(c, repo, cache, test_files=None):
    """Return (failures, flags) for one claim; each is a list of (doc_line, kind, detail)."""
    fails, flags = [], []
    n = c["line"]
    prose = strip_code(c["text"])
    ranges = []
    for path, lo, hi in c["cites"]:
        lines = read_lines(cache, repo, path)
        ranges.append((path, lo, hi, lines[max(0, lo - 1 - WINDOW):hi + WINDOW]))
    if ranges:
        have_text = "\n".join(["\n".join(r[3]) for r in ranges] + [r[0] for r in ranges])  # a journey's number is in its path
        have_nums, have_sq = numbers_in(have_text), squash(have_text)
        flat = re.sub(r"(?<=\d)[,_](?=\d{3}\b)", "", prose)
        for m in NUMBER.finditer(flat):
            tok = m.group(0)
            if APPROX.search(flat[max(0, m.start() - 8):m.start()]):
                continue  # "about 6,600" is a computed figure, not a quote
            unit = TIME_UNIT.match(flat[m.end():m.end() + 12])
            ok = {tok} | {str(int(tok) * k) for k in TIME_SCALE[unit.group(1).lower()]} if unit and tok.isdigit() else {tok}
            if not ok & have_nums:
                fails.append((n, "number", "%s is not in the cited lines" % tok))
        for tok in strings_in(c["text"], repo):
            if not string_in(tok, have_sq):
                fails.append((n, "string", "%r is not in the cited lines" % tok))
        says = SAYS_SOURCE.search(c["text"] + " " + c["label"])
        if not says and all(comment_only(read_lines(cache, repo, p)[lo - 1:hi], p) for p, lo, hi, _ in ranges):
            flags.append((n, "comment", "%s are only comment lines and the sentence does not say so" % ", ".join("%s:%d-%d" % r[:3] for r in ranges)))
    # with a harvest, only its files are tests (a defining file under conformance/ or support/ is not); without one, the path name decides
    testonly = bool(c["cites"]) and all((p in test_files) if test_files is not None else bool(TEST_PATH.search(p)) for p, _, _ in c["cites"])
    labelled = SAYS_SOURCE.search(c["label"] or "")
    for kind, kind_text in () if c["header"] else (("overreach", c["text"]), ("uncited", c["uncited"])):  # the header describes the doc
        for raw in sentences(kind_text):
            sent = strip_code(raw)
            hits = sorted({m.group(1).lower() for m in OVERREACH.finditer(sent)})
            count = COUNT.search(sent)
            if not (hits or count):
                continue
            what = ", ".join(hits + ([count.group(0).strip()] if count else []))
            detail = "%s | %s" % (what, raw.strip())
            flags.append((n, kind if kind == "uncited" else ("count" if count and not hits else "overreach"), detail))
            scoped = labelled or SCOPED.search(kind_text)  # a clause after a semicolon is still the case the sentence names
            scoped = scoped or (c.get("not_backed") and SEARCH.search(sent))  # a search report in a "Not backed" section
            if kind == "uncited" and not scoped and not SAYS_SOURCE.search(raw):
                fails.append((n, "uncited", detail))
            elif kind == "overreach" and testonly and not scoped and (quantifiers(sent) or (count and not count.group(0)[0].isdigit())):
                fails.append((n, "overreach", detail))
    return fails, flags


def is_left_out(point, left_out):
    """left_out holds point ids (P12), file paths and folders (a path ending in /)."""
    return any(point["id"] == e or point["file"] == e or (e.endswith("/") and point["file"].startswith(e)) for e in left_out)


COUNT_KEYS = (("harvested", r"harvested"), ("left out", r"left out"), ("used", r"\bused\b"),
              ("read by name only", r"read by name only"), ("not cited", r"not cited"))


def point_counts(points, left_out, cited):
    """Return {key: number} for the five header counts. A citation overlaps a point when it reaches a line of
    its body: from its start line up to the line before the next point of the same file."""
    starts = {}
    for p in points:
        starts.setdefault(p["file"], []).append(p["line"])
    for v in starts.values():
        v.sort()
    used, named = set(), set()
    for path, lo, hi, inferred in cited:
        lines = starts.get(path)
        if not lines:
            continue
        first = max(bisect.bisect_right(lines, lo) - 1, 0)  # the point that holds line lo, or the first one after it
        for i in range(first, len(lines)):
            if lines[i] > hi:
                break
            end = lines[i + 1] - 1 if i + 1 < len(lines) else float("inf")
            if end >= lo:
                (named if inferred else used).add((path, lines[i]))
    live = {(p["file"], p["line"]) for p in points if not is_left_out(p, left_out)}
    used &= live
    named = (named & live) - used
    return {"harvested": len(points), "left out": len(points) - len(live), "used": len(used),
            "read by name only": len(named), "not cited": len(live) - len(used) - len(named)}


def header_counts(doc_text, want):
    """FAIL each header number that differs from the computed one (want), and each of the five that the header lacks."""
    header = [(n, line) for n, line, in_header, heading in doc_lines(doc_text) if in_header and not heading]
    fails = []
    for key, pat in COUNT_KEYS:
        for n, line in header:
            m = re.search(r"(?i)" + pat + r"[^0-9\n]{0,90}?(\d[\d,]*)", line)
            if m:
                got = int(m.group(1).replace(",", ""))
                if got != want[key]:
                    fails.append((n, "counts", "header says %s %d; the harvest and this doc's citations give %d" % (key, got, want[key])))
                break
        else:
            fails.append((header[0][0] if header else 1, "counts", "header has no `%s N` (the harvest and this doc's citations give %d)" % (key, want[key])))
    return fails


def not_backed(doc_text, repo, points, cache):
    """FAIL a string of a "Not backed" entry that a test file of the harvest holds at a line the entry does not cite."""
    fails, section, tests = [], False, sorted({p["file"] for p in points})
    for n, line, _, heading in doc_lines(doc_text):
        if heading:
            section = bool(re.match(r"#+\s.*not backed", line, re.I))
            continue
        if not section:
            continue
        items = line_items(line, repo)
        cites = [c for _, _, cs, _ in items for c in cs]
        text = line
        for start, end, cs, _ in reversed(items):  # a citation is not a string of the entry
            if cs:
                text = text[:start] + " " + text[end:]
        quoted = {x or y for x, y in QUOTED.findall(strip_code(text))}
        for tok in strings_in(text, repo):
            # a search term the entry quotes, or a flag, message or path-like name in code font; not a bare word such as `false`
            if len(tok) < (5 if tok in quoted else 8) or (tok not in quoted and not re.search(r"[\s\-_/.]", tok)):
                continue
            for path in tests:
                try:
                    lines = read_lines(cache, repo, path)
                except OSError:
                    continue
                hit = next((i for i, l in enumerate(lines, 1) if tok in l), None)
                if hit and not any(c[0] == path and c[1] <= hit <= c[2] for c in cites):
                    fails.append((n, "not-backed", "`%s` is in a test file, %s:%d; cite it or drop the entry | %s" % (tok, path, hit, line.strip())))
                    break
    return fails


def line_count(full):
    with open(full, "rb") as f:
        data = f.read()
    return len(data.decode("utf-8", errors="replace").splitlines())


def check(doc_text, repo, points=None, left_out=()):
    """Return (checked, bad, fails, flags, counts). bad is [(doc_line, citation, reason)]; fails and flags are
    [(doc_line, kind, detail)]; counts is the header's five numbers (None without points or with a bad citation). Claims are only judged when all their citations are good. points is the
    harvest (a list of dicts) and left_out its ids and paths; with them the header counts and the
    "Not backed" strings are checked too."""
    repo = os.path.realpath(repo)
    checked, bad, fails, flags, cache = 0, [], [], [], {}
    kept = [p for p in points or [] if not is_left_out(p, left_out)]
    test_files = frozenset(p["file"] for p in kept) if points is not None else None
    cited = []  # (path, start, end, inferred) of every citation whose claim is judged
    for c in claims(doc_text, repo):
        before = len(bad)
        for path, start, end in c["cites"]:
            checked += 1
            cite = "%s:%d%s" % (path, start, "-%d" % end if end != start else "")
            full = os.path.realpath(os.path.join(repo, path))
            if full != repo and not full.startswith(repo + os.sep):
                bad.append((c["line"], cite, "path is outside the repo"))
            elif not os.path.isfile(full):
                bad.append((c["line"], cite, "no such file"))
            elif start < 1 or end < start:
                bad.append((c["line"], cite, "bad line range"))
            else:
                total = line_count(full)
                if end > total:
                    bad.append((c["line"], cite, "line out of range (file has %d lines)" % total))
        if len(bad) == before and not c.get("heading"):  # judge the words only when every citation under them is real
            f, g = check_claim(c, repo, cache, test_files)
            fails += f
            flags += g
            inferred = bool(re.search(r"\binferred\b", c["text"] + " " + c["label"], re.I))
            cited += [(p, lo, hi, inferred) for p, lo, hi in c["cites"]]
    counts = None
    if points is not None and not bad:
        counts = point_counts(points, left_out, cited)
        fails += header_counts(doc_text, counts)
        fails += not_backed(doc_text, repo, kept, cache)
    return checked, bad, sorted(set(fails)), flags, counts


def exits_note(cache, repo, path, lo, hi):
    """The early-exit text for a cited range: the exits above its last line in the function that holds it, and, when
    the range starts in another function, the exits above its first line there. None when there is nothing to say."""
    try:
        lines = read_lines(cache, repo, path)
        text, ext = "\n".join(lines), os.path.splitext(path)[1]
        found = [(early_exits.early_exits(text, ext, hi), hi)]
        if lo != hi:
            low = early_exits.early_exits(text, ext, lo)
            if low and not low.get("unreadable") and (not found[0][0] or found[0][0].get("unreadable") or low["fn_line"] != found[0][0]["fn_line"]):
                found.insert(0, (low, lo))
        notes = [early_exits.render(f, lines, cut, lo) for f, cut in found]
        return "\n".join(n for n in notes if n) or None
    except (OSError, RecursionError):
        return None


def sheet(doc_text, repo):
    """Print each claim with the lines it cites, and the early exits above each range, for the writer's own read
    before the check pass."""
    cache = {}
    for c in claims(doc_text, repo):
        if c.get("heading") or not c["cites"]:
            continue
        print("\n== doc line %d: %s" % (c["line"], c["text"].strip()))
        for path, lo, hi in c["cites"]:
            print("-- %s:%d-%d" % (path, lo, hi))
            try:
                for i, text in enumerate(read_lines(cache, repo, path)[lo - 1:hi], lo):
                    print("%6d  %s" % (i, text))
            except OSError:
                print("       (cannot read the file)")
                continue
            note = exits_note(cache, repo, path, lo, hi)
            if note:
                print(note)


def main(argv):
    args, opts = [], {}
    it = iter(argv[1:])
    for a in it:
        if a in ("--points", "--left-out"):
            opts[a] = next(it, None)
        elif a == "--sheet":
            opts[a] = True
        else:
            args.append(a)
    if len(args) != 2 or not os.path.isfile(args[0]) or not os.path.isdir(args[1]) or (opts.get("--left-out") and "--points" not in opts) \
            or any(opts.get(k) is None or (k != "--sheet" and not os.path.isfile(opts[k])) for k in opts):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    doc, repo = args
    with open(doc, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if opts.get("--sheet"):
        sheet(text, os.path.realpath(repo))
        return 0
    points = left_out = None
    if "--points" in opts:
        with open(opts["--points"], encoding="utf-8") as f:
            points = json.load(f)
        left_out = []
        if opts.get("--left-out"):
            with open(opts["--left-out"], encoding="utf-8") as f:
                left_out = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    checked, bad, fails, flags, counts = check(text, repo, points, left_out or ())
    for n, cite, reason in bad:
        print("%s:%d: %s: %s" % (doc, n, cite, reason))
    for n, kind, detail in fails:
        print("%s:%d: FAIL %s: %s" % (doc, n, kind, detail))
    for n, kind, detail in flags:
        print("%s:%d: flag %s: %s" % (doc, n, kind, detail))
    print("checked %d citations, %d bad" % (checked, len(bad)))
    if counts:
        print("Counts: " + "; ".join("%s %d" % (k, counts[k]) for k, _ in COUNT_KEYS) + ".")  # the line the header carries
    print("%d failed checks, %d flagged sentences (list them for the check pass)" % (len(fails), len(flags)))
    if not checked:
        print("no citations found: an uncited doc cannot be checked", file=sys.stderr)
        return 2
    return 1 if bad or fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
