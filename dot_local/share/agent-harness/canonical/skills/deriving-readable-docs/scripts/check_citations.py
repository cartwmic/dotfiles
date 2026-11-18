#!/usr/bin/env python3
"""Check the `path:line` citations in a derived doc: the line exists, and the cited text backs the sentence.

usage: check_citations.py <doc.md> <repo>

A citation is a backticked `path:LINE` or `path:START-END` (paths relative to <repo>; a space after the colon is
read; several may share one backtick span, separated by commas or semicolons; one inside a span with other
words is read too if its path has a slash or an extension). Fenced code blocks are skipped. A URL, a clock
time, an IPv4 address or `host.com:8080` is ignored. A whole-span `Name:5` with no dot or slash is checked as a
file, so write a port or a key such as `status:200` without backticks.
Prints the number checked and each bad citation as `doc:line: citation: reason`.

Then it reads what the cited lines say. A claim is the words just before a citation, or before a run of citations
joined by commas or "and". Two checks FAIL a claim, because a miss is a fact the cited lines do not show:
  number  every digit number in the claim (not in a citation; "about N" is skipped; 15 seconds also matches
          15000 and 15 * 1000) must appear in a cited range, widened by WINDOW lines each side, or in a cited
          path (journey 111). The words one..twenty in the cited text count as digits.
  string  every `backticked` or "double-quoted" string in the claim (a repo path that exists is exempt) must
          appear there. A one-word string must appear as written; a longer one needs each of its words.
Four checks only LIST a sentence, because a script cannot judge them. The check pass (references/check-brief.md)
takes the list:
  overreach  every, all, always, never, only, none, any, no <noun> (and every/any + thing, one, where, body)
  count      a count of things: "three parts", "6 words"
  comment    every cited range is comment lines, and the sentence does not say it is from a comment, header or doc
  uncited    the first two, in a sentence after the doc header that carries no citation
Exit 0: all good. 1: a bad citation or a failed claim. 2: usage error, or no citations at all. Listed
sentences never change the exit code. Stdlib only.
"""
import os
import re
import sys

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
    """Yield (doc_line_no, line, in_header) for each prose line; fenced code blocks and headings are skipped.
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
        if line.startswith("#") or not line.strip():
            continue
        yield n, line, header


LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
JOIN = re.compile(r"^(?:[\s,;&]|and)*$")
LABEL = re.compile(r"^\s*\(([^)]*)\)")


def claims(text, repo):
    """Yield one dict per claim: line, text (the words before the citation group), cites, label (a parenthetical
    right after the group, such as "code comment"), and uncited (words after the last group, or a whole line with none)."""
    for n, line, header in doc_lines(text):
        items = line_items(line, repo)
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
                   "uncited": "", "header": header}
            prev = end + (label.end() if label else 0)
        if not header and line[prev:].strip():
            yield {"line": n, "text": "", "cites": [], "label": "", "uncited": line[prev:], "header": header}


# --- text that a script can compare ---------------------------------------------------------------------------
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
WORDS = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
QUOTED = re.compile(r'"([^"\n]+)"|\u201c([^\u201d\n]+)\u201d')
OVERREACH = re.compile(r"\b(every(?:thing|one|where|body)?|all|always|never|only|none|any(?:thing|one|where|body)?|no(?=\s+(?!longer\b)[a-z]))\b", re.I)
# A count of things: "three parts", "6 words". Not a time ("45 minutes") or a bare status code ("409 and").
COUNT = re.compile(r"(?<![\w.])(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|dozen|\d+)\s+(?:[a-z-]+\s+)?(?!(?:seconds?|minutes?|hours?|days?|weeks?|bytes?|times?|chars?|characters?)\b)[a-z-]+s\b", re.I)
TIME_SCALE = {"second": (1000,), "minute": (60, 60000), "hour": (60, 3600, 3600000), "day": (24, 86400, 86400000)}
TIME_UNIT = re.compile(r"^[\s-]*(second|minute|hour|day)s?\b", re.I)
APPROX = re.compile(r"(about|around|roughly|nearly|~)\s*$", re.I)
SAYS_SOURCE = re.compile(r"comment|header|readme|docs?\b|documentation|stated|says|source text|prd|agents\.md", re.I)
COMMENT_START = {
    "//": {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs", ".go", ".java", ".kt", ".c", ".h", ".cc", ".cpp", ".cs", ".swift", ".scala"},
    "#": {".py", ".sh", ".bash", ".zsh", ".rb", ".yml", ".yaml", ".toml", ".ex", ".exs", ".bats", ".tmpl"},
    "--": {".sql", ".lua", ".hs"},
}


def norm_number(tok):
    return tok.replace(",", "").replace("_", "")


def numbers_in(text):
    """The set of numbers in cited text: digits (2,000 = 2000 = 2_000) and the number words one..twenty."""
    text = re.sub(r"(?<=\d)[,_](?=\d{3}\b)", "", text)
    found = {norm_number(m.group(0)) for m in NUMBER.finditer(text)}
    for w in re.findall(r"[a-z]+", text.lower()):
        if w in WORDS:
            found.add(str(WORDS.index(w)))
    return found


def squash(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def strings_in(claim_text, repo):
    """Backticked and double-quoted strings in a claim (not citations). A backticked repo path that exists is skipped."""
    out = [m.group(1) for m in SPAN.finditer(claim_text)] + [a or b for a, b in QUOTED.findall(claim_text)]
    return [t for t in out if len(squash(t)) > 1 and not os.path.exists(os.path.join(repo, t.strip()))]


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


def check_claim(c, repo, window, cache):
    """Return (failures, flags) for one claim; each is a list of (doc_line, kind, detail)."""
    fails, flags = [], []
    n = c["line"]
    prose = strip_code(c["text"])
    ranges = []
    for path, lo, hi in c["cites"]:
        lines = read_lines(cache, repo, path)
        ranges.append((path, lo, hi, lines[max(0, lo - 1 - window):hi + window]))
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
    for kind_text in () if c["header"] else (prose, strip_code(c["uncited"])):  # the header describes the doc
        for sent in sentences(kind_text):
            hits = sorted({m.group(1).lower() for m in OVERREACH.finditer(sent)})
            if hits:
                flags.append((n, "overreach", "%s | %s" % (", ".join(hits), sent.strip())))
            count = COUNT.search(sent)
            if count:
                flags.append((n, "count", "%s | %s" % (count.group(0).strip(), sent.strip())))
    return fails, flags


def line_count(full):
    with open(full, "rb") as f:
        data = f.read()
    return len(data.decode("utf-8", errors="replace").splitlines())


def check(doc_text, repo, window=WINDOW):
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
        if len(bad) == before:  # judge the words only when every citation under them is real
            f, g = check_claim(c, repo, window, cache)
            fails += f
            flags += g
    return checked, bad, sorted(set(fails)), flags


def main(argv):
    if len(argv) != 3 or not os.path.isfile(argv[1]) or not os.path.isdir(argv[2]):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    doc = argv[1]
    with open(doc, encoding="utf-8", errors="replace") as f:
        checked, bad, fails, flags = check(f.read(), argv[2])
    for n, cite, reason in bad:
        print("%s:%d: %s: %s" % (doc, n, cite, reason))
    for n, kind, detail in fails:
        print("%s:%d: FAIL %s: %s" % (doc, n, kind, detail))
    for n, kind, detail in flags:
        print("%s:%d: flag %s: %s" % (doc, n, kind, detail))
    print("checked %d citations, %d bad" % (checked, len(bad)))
    print("%d failed checks, %d flagged sentences (list them for the check pass)" % (len(fails), len(flags)))
    if not checked:
        print("no citations found: an uncited doc cannot be checked", file=sys.stderr)
        return 2
    return 1 if bad or fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
