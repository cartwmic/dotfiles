#!/usr/bin/env python3
"""Check the `path:line` citations in a derived doc: the line exists, and the cited text backs the sentence.

usage: check_citations.py <doc.md> <repo> [--max-words N] [--max-sentence-words N] [--audit audit.md [--guards-file F] [--evidence-file F]] [--sheet | --guards]
       check_citations.py --show path:START-END <repo>

A citation is a backticked `path:LINE` or `path:START-END` (paths relative to <repo>; a space after the colon is
read; several may share one backtick span, separated by commas or semicolons (`src/a.ts:12, 40-45` is two ranges of one file); one inside a span with other
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
            parts": two..twelve, dozen), whose citations are all test, journey or doc files (README, docs/, *.md). A test proves the cases it
            runs, not a set. Not these: a word inside a hyphenated one ("read-only"), "each other", and "each" that
            spreads over a listed set ("A and B each", "once each", "one commit each"; an "and" after a comma does
            not close a list: ", and the message names each problem" FAILs). Cite the code that defines
            the set, or word the sentence to the test's case ("in the test", "in this case", "the test shows",
            "the test puts" and other "the test <verb>", "for example", "such as", "at least", "e.g."), or label it
            inferred or "from your list". A bare "the test" does not clear it. A file is a test when its path says
            so (tests/, .test., _test, journey, e2e, spec, conformance ...).
  uncited   a sentence after the doc header with no citation, source label ("(README)", "(code comment)"), or
            "inferred" / "from your list" in it, that holds a word of the overreach list below or a count of
            things in digits or words.
Listed too, whatever the citations, because a script cannot judge them (the check pass, references/check-brief.md, takes the list):
  overreach  every, each, all, always, never, only, next, none, any, no <noun> (and every/any + thing, one, where, body)
  count      a count of things: "three parts", "6 words" (a count in words also FAILs under overreach above)
  comment    every cited range is comment lines, and the sentence does not say it is from a comment, header or doc
  sentence-length  with --max-sentence-words N, FAIL each sentence of more than N words. A sentence is cut after . ! or ? and is
            measured whole, with its citations taken out, so a citation in the middle does not cut it. It prints the claims (every
            sentence, bullet and table row of the prose, headings and the header excluded), their words and the words per claim on every run.
  budget    with --max-words N, FAIL when the doc holds more than N words. The words are all of the doc's text, the header
            above the first `## ` heading and the headings and backticked names included; citations, fenced code, printed blocks
            (what assemble.py prints, such as the header) and bare list marks are not words.
            A budget is kept by dropping behaviours, not by joining them. The word count prints on every run.
The last checks, with --audit FILE (the writer's own pass; run on a section draft, not on the whole guide):
  audit     FAIL when FILE is missing (the FAIL names the path), and FAIL a claim (a sentence with citations, above the first `## ` heading too) that has no audit row in FILE:
            `N | assert: path:line "<text>" | exits: ... | callers: ... | found: ... | result: HOLDS|narrowed to "..."|cut`, where N is the
            doc line (as --sheet prints it), path:line is one of the claim's own citations and the quoted text is on
            that line. A summary ("1, 4-6 HOLDS") is not a row. A claim on a line that is not in the audit has not been audited. The quote runs to the quote mark
            before ` | exits:`, so a line that holds ` | ` is copied as it is.
  choice    FAIL when choice.md (beside FILE) is missing or empty: stage 0 of references/drafting.md lists the behaviours kept there.
  guards    FAIL when the condition sheet is missing or a guard on it is unmarked. The sheet is the output of --guards, saved as guards.md beside FILE (or
            --guards-file): one row `guard | path:line | kind | source | covered:` for each early exit above a cited line (the exits --sheet lists). Each row ends
            `covered: <id>` (the id of a draft line that cites the same file and states the condition) or `covered: not relevant: <reason of three words or more>`.
            A guard the sheet leaves out, or an id the draft does not carry, fails. A file the exits cannot be read from has no rows: read the function by hand.
  evidence  FAIL when the evidence file (evidence.md beside FILE, or --evidence-file) is missing or a cited range has no row in it: a row is
            `path:line "the line, copied"` (or `path:START-END "..."`) with a line inside the range and the whole quoted text on that line (on one line of
            the row's range), so each cited line was opened and read. The quote closes at the first quote mark followed by ` | ` or the end of the row, so a
            line that holds ` | ` (a type union, an `||`) or a quote mark is copied whole with no escape. The one gap: a line that itself holds a quote mark and then
            ` | ` ends the quote there.
  uncited   FAIL a sentence with no citation unless it says "inferred" or "from your list": a README label alone is not a citation.
--guards prints the condition sheet to save and mark (see guards above), each source line as written (`||` stays `||`); the checks above are skipped.
--show path:START-END prints those lines of a file in the repo, numbered as `cat -n` and the Read tool number them (newlines only: a form feed does not
          start a line), in the form --sheet uses. Exit 1 when the file or a line of the range is not there. A writer takes its line numbers from this.
--sheet prints every claim with the cited lines under it (the self-check read), and the checks above are skipped.
          Under a cited range inside a function (Python, TS/JS) it also lists the function's early exits above the
          range's last line (return, throw, continue, break, process.exit), marking those inside the range: the other
          paths a sentence about the function must state or leave out. A continue or break counts when its loop
          overlaps the range. When the range starts in another function, that function's exits above the last line
          (or above its own end) are listed too, since they sit inside the range. See early_exits.py;
          "no early exits" and "not listed" print differently.
Exit 0: all good. 1: a bad citation or a failed claim. 2: usage error, or no citations at all. Listed
sentences never change the exit code. The last lines count the failed checks by name, as `2 failed checks (number 1, string 1)`. Stdlib only.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
import early_exits  # noqa: E402
from claims import (SAYS_SOURCE, SPAN, TAG, claims, doc_lines, line_items, prose_sentences, says_source, sentences, split_lines, strip_code, word_count, words_of)  # noqa: E402

WINDOW = 5  # lines each side of a cited range (sweep in the commit message)


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
# A test path by its name.
# A doc file is the repo's own words, not the code that defines a set: a sentence that cites only tests or docs proves no more than they say.
DOC_PATH = re.compile(r"\.(md|mdx|rst|txt|adoc)$|(^|/)docs?/", re.I)
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|proof|journeys?|e2e|smoke|specs?|conformance|support)(/|\.)|\.(test|spec|journey)\.|_test\.|(^|/)test_|-journey|\.bats$", re.I)
# A count of things: "three parts", "6 words". Not a time ("45 minutes") or a bare status code ("409 and").
COUNT = re.compile(r"(?<![\w.])(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen|\d+)\s+(?!(?:is|was|has|does|as|this|its|his|yes)\b)(?:[a-z-]+\s+)?(?!(?:seconds?|minutes?|hours?|days?|weeks?|bytes?|times?|chars?|characters?)\b)[a-z-]+s\b", re.I)
TIME_SCALE = {"second": (1000,), "minute": (60, 60000), "hour": (60, 3600, 3600000), "day": (24, 86400, 86400000)}
TIME_UNIT = re.compile(r"^[\s-]*(second|minute|hour|day)s?\b", re.I)
APPROX = re.compile(r"(about|around|roughly|nearly|~)\s*$", re.I)
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
    found = {m.group(0) for m in NUMBER.finditer(text)} | {m.group(0).lstrip("0") or "0" for m in NUMBER.finditer(text) if m.group(0).isdigit()}  # 05 is 5
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


def read_lines(cache, repo, path):
    if path not in cache:
        with open(os.path.join(repo, path), "rb") as f:
            cache[path] = split_lines(f.read().decode("utf-8", errors="replace"))
    return cache[path]


def check_claim(c, repo, cache):
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
            ok |= {tok.lstrip("0") or "0"} if tok.isdigit() else set()
            if not ok & have_nums:
                fails.append((n, "number", "%s is not in the cited lines" % tok))
        for tok in strings_in(c["text"], repo):
            if not string_in(tok, have_sq):
                fails.append((n, "string", "%r is not in the cited lines" % tok))
        says = SAYS_SOURCE.search(c["text"] + " " + c["label"])
        if not says and all(comment_only(read_lines(cache, repo, p)[lo - 1:hi], p) for p, lo, hi, _ in ranges):
            flags.append((n, "comment", "%s are only comment lines and the sentence does not say so" % ", ".join("%s:%d-%d" % r[:3] for r in ranges)))
    testonly = bool(c["cites"]) and all(bool(DOC_PATH.search(p)) or bool(TEST_PATH.search(p)) for p, _, _ in c["cites"])  # a test is found by its path name
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
            if kind == "uncited" and not scoped and not says_source(raw, c.get("part1", False)):
                fails.append((n, "uncited", detail))
            elif kind == "overreach" and testonly and not scoped and (quantifiers(sent) or (count and not count.group(0)[0].isdigit())):
                fails.append((n, "overreach", detail))
    return fails, flags


def line_count(full):
    with open(full, "rb") as f:
        data = f.read()
    return len(split_lines(data.decode("utf-8", errors="replace")))


def check(doc_text, repo):
    """Return (checked, bad, fails, flags). bad is [(doc_line, citation, reason)]; fails and flags are
    [(doc_line, kind, detail)]. Claims are only judged when all their citations are good."""
    repo = os.path.realpath(repo)
    checked, bad, fails, flags, cache = 0, [], [], [], {}
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
            f, g = check_claim(c, repo, cache)
            fails += f
            flags += g
    return checked, bad, sorted(set(fails)), flags


def exit_sets(cache, repo, path, lo, hi):
    """[(found, cut)] for a cited range: the function that holds its last line, and, when the range starts in another function, that function too
    (its exits above its own end sit inside the range). found is what early_exits.early_exits returns; cut is the line the exits are listed above."""
    lines = read_lines(cache, repo, path)
    text, ext = "\n".join(lines), os.path.splitext(path)[1]
    found = [(early_exits.early_exits(text, ext, hi, first=lo), hi)]
    if lo != hi:
        first_fn = early_exits.early_exits(text, ext, lo, upto=hi)
        if first_fn and not first_fn.get("unreadable") and (not found[0][0] or found[0][0].get("unreadable") or first_fn["fn_line"] != found[0][0]["fn_line"]):
            found.insert(0, (first_fn, min(hi, first_fn["fn_end"])))  # its exits cannot skip lines past its own end
    return lines, found


def exits_note(cache, repo, path, lo, hi):
    """The early-exit text for a cited range: the exits above its last line in the function that holds it, and, when
    the range starts in another function, that function's exits above its last line, or above its own end if that comes
    first, too (they sit inside the range). A continue or break counts when its loop overlaps the range. None when there is nothing to say."""
    try:
        lines, found = exit_sets(cache, repo, path, lo, hi)
        notes = [early_exits.render(f, lines, cut, lo) for f, cut in found]
        return "\n".join(n for n in notes if n) or None
    except (OSError, RecursionError):
        return None


GUARD_HEAD = ("# guards: each early exit above a cited line (return, throw, continue, break, exit). Save this as guards.md beside the audit.\n"
              "# End every row with `covered: <id>` (an id of a draft line that cites the same file and states the condition) or `covered: not relevant: <reason>`.")
GUARD_ROW = re.compile(r"^\s*guard\s*\|\s*([^\s|]+?):(\d+)\s*\|(.*)\|\s*covered:(.*)$")
EVIDENCE_CITE = re.compile(r"([\w./@+-]+):(\d+)(?:-(\d+))?")
OPEN_QUOTE, CLOSE_QUOTE = re.compile(r"[\"\u201c`]"), re.compile(r"[\"\u201d`]")


def guards(doc_text, repo):
    """{(path, line): (kind, source text, doc_line)}: each early exit above a cited range, with the first doc line that cites it."""
    cache, out = {}, {}
    for c in claims(doc_text, repo):
        if c.get("heading") or not c["cites"]:
            continue
        for path, lo, hi in c["cites"]:
            try:
                lines, found = exit_sets(cache, repo, path, lo, hi)
            except (OSError, RecursionError):
                continue
            for f, _ in found:
                for e in (f.get("exits", []) if f and not f.get("unreadable") else []):
                    out.setdefault((path, e["line"]), (e["kind"], lines[e["line"] - 1].strip(), c["line"]))
    return out


def print_guards(doc_text, repo):
    print(GUARD_HEAD)
    for (path, line), (kind, text, _) in sorted(guards(doc_text, repo).items()):
        print("guard | %s:%d | %s | %s | covered:" % (path, line, kind, text[:110]))


def ids_citing(doc_text, repo):
    """{id: {cited paths}} for each id of a line of the doc that holds citations."""
    out, raw = {}, split_lines(doc_text)
    for n, line, _, heading in doc_lines(doc_text):
        if heading:
            continue
        paths = {p for _, _, cites, _ in line_items(raw[n - 1], repo) for p, _, _ in cites}
        for t in TAG.findall(raw[n - 1]):
            out.setdefault(t.strip("[]"), set()).update(paths)
    return out


def guard_fails(doc_text, repo, sheet_text, where):
    """[(doc_line, "guards", detail)]: the sheet at `where` is missing (sheet_text None), or a guard is not on it, not marked, or marked with a reason
    that is too short or an id the draft does not carry for that file."""
    if sheet_text is None:
        return [(1, "guards", "no condition sheet at %s: run --guards, save the output there and mark every guard" % where)]
    marks = {}
    for raw in sheet_text.splitlines():
        m = GUARD_ROW.match(raw)
        if m:
            marks[(m.group(1), int(m.group(2)))] = m.group(4).strip()
    known, fails = ids_citing(doc_text, repo), []
    for (path, line), (kind, text, n) in sorted(guards(doc_text, repo).items()):
        where_ = "%s:%d" % (path, line)
        mark = next((v for (p, l), v in marks.items() if l == line and (p == path or p.endswith("/" + path) or path.endswith("/" + p))), None)
        if mark is None:
            fails.append((n, "guards", "guard %s (%s) is not in the sheet: run --guards again and mark it" % (where_, kind)))
        elif not mark:
            fails.append((n, "guards", "guard %s (%s) is unmarked: end its row with `covered: <id>` or `covered: not relevant: <reason>`" % (where_, kind)))
        elif mark.lower().startswith("not relevant"):
            if len(words_of(mark.split(":", 1)[1] if ":" in mark else "")) < 3:
                fails.append((n, "guards", "guard %s says `not relevant` with no reason of three words or more" % where_))
        else:
            ids = re.findall(r"A\d+\.\w+", mark)
            if not ids:
                fails.append((n, "guards", "guard %s is marked with neither an id nor `not relevant: <reason>`" % where_))
            for i in ids:
                if i not in known:
                    fails.append((n, "guards", "guard %s is covered by %s, which no line of the draft carries" % (where_, i)))
                elif not any(p == path or p.endswith("/" + path) or path.endswith("/" + p) for p in known[i]):
                    fails.append((n, "guards", "guard %s is covered by %s, which does not cite %s" % (where_, i, path)))
    return fails


def quote_close(row, start):
    """Where the quote that opens just before `start` closes: the first quote mark followed by optional spaces and then ` | ` or the end of the row, so a line that holds
    ` | ` (a type union, an `||`) or quote marks is copied whole and needs no escape. A row with no such quote mark ends its quote at the last one before its next ` | `. None when
    the row has no closing quote. The one gap: a code line that itself holds a quote mark and then ` | ` ends the quote there, and the row is read as far as that."""
    marks = list(CLOSE_QUOTE.finditer(row, start))
    for m in marks:
        if re.match(r"\s*(?:\||$)", row[m.end():]):
            return m.start()
    end = row.find(" | ", start)
    cell = [m for m in marks if end < 0 or m.start() < end]
    return cell[-1].start() if cell else None


def evidence_rows(evidence_text):
    """[(path, first, last, [parts])] for each row of an evidence file: its citation, then the text it quotes (see quote_close for where the quote ends).
    Parts are the text around its ellipses (`...` or the ellipsis character), each squashed."""
    rows = []
    for l in evidence_text.split("\n"):
        m = EVIDENCE_CITE.search(l)
        opener = OPEN_QUOTE.search(l, m.end() + (l[m.end():m.end() + 1] == "`")) if m else None  # the backtick that closes the citation is not a quote
        if not opener:
            continue
        closer = quote_close(l, opener.end())
        if closer is None:
            continue
        parts = [squash(q) for q in re.split(r"\u2026|\.\.\.", l[opener.end():closer]) if squash(q)]
        if parts:
            rows.append((m.group(1), int(m.group(2)), int(m.group(3) or m.group(2)), parts))
    return rows


def evidence_fails(doc_text, repo, evidence_text, where):
    """[(doc_line, "evidence", detail)]: the evidence file is missing, or a cited range has no row that overlaps it and whose whole quoted text is on a line of the row's range."""
    if evidence_text is None:
        return [(1, "evidence", "no evidence file at %s: write one row `path:line \"the line, copied\"` for each cited range" % where)]
    rows = evidence_rows(evidence_text)
    cache, fails = {}, []
    for c in claims(doc_text, repo):
        if c.get("heading"):
            continue
        for path, lo, hi in c["cites"]:
            ok = False
            for p, first, last, parts in rows:
                if (p == path or p.endswith("/" + path) or path.endswith("/" + p)) and first <= hi and lo <= last:
                    try:
                        have = [squash(l) for l in read_lines(cache, repo, path)[first - 1:last]]
                    except OSError:
                        continue
                    ok = ok or any(all(q in line for q in parts) for line in have)
            if not ok:
                fails.append((c["line"], "evidence", "no evidence row for %s:%d%s: copy the line you read, as `path:line \"text\"`" % (path, lo, "-%d" % hi if hi != lo else "")))
    return fails


def uncited_fails(doc_text, repo):
    """[(doc_line, "uncited", detail)]: a sentence of a draft with no citation that does not say "inferred" or "from your list"."""
    out = []
    for c in claims(doc_text, repo):
        if c.get("heading") or c["header"] or c.get("part1") or not c["uncited"].strip():
            continue
        for raw in sentences(c["uncited"]):
            if words_of(raw) and not re.search(r"\binferred\b|\bfrom your list\b", raw, re.I):
                out.append((c["line"], "uncited", "no citation and no \"inferred\" label: cite the line that shows it, or label it inferred | %s" % raw.strip()))
    return out


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


AUDIT_ROW = re.compile(r'^\s*(?:[-*]\s*)?(\d+)\s*\|\s*assert:\s*(\S+?):(\d+)\s+["\u201c](.+)["\u201d]\s*\|\s*exits:\s*(\S.*?)\s*\|\s*callers:\s*(\S.*?)\s*\|\s*found:\s*(\S.*?)\s*\|\s*result:\s*(HOLDS|narrowed|cut)\b', re.I)


def audit_rows(audit_text):
    """The well-formed rows of an audit file, as (doc line, path, line, quoted text)."""
    rows = []
    for raw in audit_text.splitlines():
        m = AUDIT_ROW.match(raw)
        if m:
            rows.append((int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)))
    return rows


def audit_fails(doc_text, repo, audit_text, where):
    """[(doc_line, "audit", detail)] for each claim with no row that names one of its own citations and quotes the text on that line. The audit file at `where` is
    missing (audit_text None): one FAIL that names the path."""
    if audit_text is None:
        return [(1, "audit", "no audit file at %s: write one row for each sentence (stage 3 of references/drafting.md)" % where)]
    rows, cache, fails = audit_rows(audit_text), {}, []
    for c in claims(doc_text, repo):
        if c.get("heading") or not c["cites"]:
            continue
        ok = False
        for n, path, line, quote in rows:
            if n != c["line"]:
                continue
            for cp, lo, hi in c["cites"]:
                if (cp == path or cp.endswith("/" + path)) and lo <= line <= hi:
                    try:
                        have = squash(read_lines(cache, repo, cp)[line - 1])
                    except (OSError, IndexError):
                        continue
                    parts = [squash(q) for q in re.split(r"\u2026|\.\.\.", quote) if squash(q)]
                    if parts and all(q in have for q in parts):
                        ok = True
        if not ok:
            fails.append((c["line"], "audit", "no audit row for this sentence: `N | assert: path:line \"text\" | exits: .. | callers: .. | found: .. | result: ..` "
                          "with N = this doc line, one of its own citations, and the text on that line"))
    return fails


def show(repo, spec):
    """Print `spec` (path:START-END) as --sheet prints a cited range. 0, or 1 when the file or a line of the range is not there."""
    m = re.fullmatch(r"(.+?):(\d+)(?:-(\d+))?", spec)
    if not m:
        print("%s: not path:START-END" % spec)
        return 1
    path, lo = m.group(1), int(m.group(2))
    hi = int(m.group(3) or lo)
    full = os.path.realpath(os.path.join(repo, path))
    if not (full.startswith(repo + os.sep) and os.path.isfile(full)):
        print("%s: no such file in the repo" % path)
        return 1
    lines = read_lines({}, repo, path)
    if lo < 1 or hi < lo or hi > len(lines):
        print("%s:%d-%d: line out of range (file has %d lines)" % (path, lo, hi, len(lines)))
        return 1
    print("-- %s:%d-%d" % (path, lo, hi))
    for i, text in enumerate(lines[lo - 1:hi], lo):
        print("%6d  %s" % (i, text))
    return 0


def main(argv):
    args, opts = [], {}
    it = iter(argv[1:])
    for a in it:
        if a in ("--max-words", "--max-sentence-words", "--audit", "--guards-file", "--evidence-file", "--show"):
            opts[a] = next(it, None)
        elif a in ("--sheet", "--guards"):
            opts[a] = True
        else:
            args.append(a)
    if "--show" in opts and opts["--show"] and len(opts) == 1 and len(args) == 1 and os.path.isdir(args[0]):
        return show(os.path.realpath(args[0]), opts["--show"])
    if len(args) != 2 or not os.path.isfile(args[0]) or not os.path.isdir(args[1]) or "--show" in opts \
            or any(opts.get(k) is None for k in opts) \
            or (("--guards-file" in opts or "--evidence-file" in opts) and "--audit" not in opts) \
            or any(opts.get(k) is not None and not opts[k].isdigit() for k in ("--max-words", "--max-sentence-words")):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    doc, repo = args
    with open(doc, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if opts.get("--sheet"):
        sheet(text, os.path.realpath(repo))
        return 0
    if opts.get("--guards"):
        print_guards(text, os.path.realpath(repo))
        return 0
    checked, bad, fails, flags = check(text, repo)
    words = word_count(text, os.path.realpath(repo))
    if opts.get("--audit"):
        real = os.path.realpath(repo)
        folder = os.path.dirname(os.path.abspath(opts["--audit"]))
        extra = []
        if not bad:
            audit_body = open(opts["--audit"], encoding="utf-8", errors="replace").read() if os.path.isfile(opts["--audit"]) else None
            extra += audit_fails(text, real, audit_body, opts["--audit"])
            choice = os.path.join(folder, "choice.md")
            choice_body = open(choice, encoding="utf-8", errors="replace").read() if os.path.isfile(choice) else None
            if not (choice_body or "").strip():
                extra.append((1, "choice", "no choice file at %s: stage 0 of references/drafting.md lists the behaviours kept, one line each" % choice))
        for key, name, check_files in (("--guards-file", "guards.md", guard_fails), ("--evidence-file", "evidence.md", evidence_fails)):
            where = opts.get(key) or os.path.join(folder, name)
            body = open(where, encoding="utf-8", errors="replace").read() if os.path.isfile(where) else None
            extra += check_files(text, real, body, where) if not bad else []
        extra += uncited_fails(text, real) if not bad else []
        have = {(n, k) for n, k, _ in fails}
        fails = sorted(set(fails + [e for e in extra if (e[0], e[1]) not in have or e[1] not in ("uncited",)]))
    if "--max-words" in opts and words > int(opts["--max-words"]):
        fails = sorted(set(fails + [(1, "budget", "%d words, budget %s: drop behaviours, do not join them" % (words, opts["--max-words"]))]))
    prose = prose_sentences(text, os.path.realpath(repo))
    if "--max-sentence-words" in opts:
        limit = int(opts["--max-sentence-words"])
        fails = sorted(set(fails + [(n, "sentence-length", "%d words, limit %d: split it and keep the condition in each part | %s" % (len(words_of(s)), limit, s))
                                    for n, s in prose if len(words_of(s)) > limit]))
    for n, cite, reason in bad:
        print("%s:%d: %s: %s" % (doc, n, cite, reason))
    for n, kind, detail in fails:
        print("%s:%d: FAIL %s: %s" % (doc, n, kind, detail))
    for n, kind, detail in flags:
        print("%s:%d: flag %s: %s" % (doc, n, kind, detail))
    print("checked %d citations, %d bad, %d words" % (checked, len(bad), words))
    claim_words = sum(len(words_of(s)) for _, s in prose)
    print("%d claims, %d words in them, %.1f words per claim" % (len(prose), claim_words, claim_words / len(prose) if prose else 0))
    names = {}
    for _, kind, _ in fails:
        names[kind] = names.get(kind, 0) + 1
    if bad:
        names["citation"] = len(bad)
    print("%d failed checks%s, %d flagged sentences (list them for the check pass)" % (len(fails) + len(bad), " (%s)" % ", ".join("%s %d" % kv for kv in sorted(names.items())) if names else "", len(flags)))
    if not checked:
        print("no citations found: an uncited doc cannot be checked", file=sys.stderr)
        return 2
    return 1 if bad or fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
