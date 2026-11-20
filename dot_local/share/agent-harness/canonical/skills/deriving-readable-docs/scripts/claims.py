"""Shared by check_citations.py, lint_main.py, slice.py, score.py and assemble.py: read a derived doc into lines, citations,
claims, sentences and words. Stdlib only; imported, never run.

A doc line is skipped when it is inside a fenced code block or inside a printed block (`<!-- printed -->` ... `<!-- /printed -->`,
which assemble.py writes around rows a script printed: they are not claims and not words).
A citation is a backticked `path:LINE` or `path:START-END`; see line_items. A sentence is the text of a line with its
citations taken out, split after . ! or ? when a capital letter, digit, quote or bracket follows. A tag such as [A4.2] is not a word.
"""
import os
import re

SPAN = re.compile(r"`([^`\n]+)`")
PART = re.compile(r"^([^\s:`]+)\s*:\s*(\d+)(?:\s*-\s*(\d+))?$")
# A citation-shaped token inside a span that also holds other words, such as `see src/a.rs:2`.
EMBEDDED = re.compile(r"(?<![\w/.:@+-])([\w.@+/-]+)\s*:\s*(\d+)(?:-(\d+))?")
HOST_SUFFIXES = {"com", "org", "net", "io", "dev", "app", "internal", "local", "lan", "home"}
IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
JOIN = re.compile(r"^(?:[\s,;&]|and)*$")
LABEL = re.compile(r"^\s*\(([^)]*)\)")
TAG = re.compile(r"\[A\d+(?:\.\d+)?\]")  # a Part 1 sentence's pointer into the appendix
SAYS_SOURCE = re.compile(r"comment|header|readme|docs?\b|documentation|stated|says|source text|prd|agents\.md|\[A\d+(?:\.\d+)?\]", re.I)
PRINTED_BEGIN, PRINTED_END = "<!-- printed -->", "<!-- /printed -->"
COUNTS_LINE = re.compile(r"(?i)\bcounts:?\**\s+harvested\s+[\d,]+")  # the header line the older flow wrote, bold or not
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(\[*_])")
TAG_AFTER_STOP = re.compile(r"([.!?])((?:\s*\[A\d+(?:\.\d+)?\])+)")


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
        for k in range(1, len(parts)):  # `src/a.ts:12, 40-45` is two ranges of one file: a bare range takes the path before it
            if re.fullmatch(r"\d+(?:\s*-\s*\d+)?", parts[k]) and PART.match(parts[k - 1]):
                parts[k] = PART.match(parts[k - 1]).group(1) + ":" + parts[k]
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
    """Yield (doc_line_no, line, in_header, is_heading) for each line outside fenced code blocks and printed blocks. A heading's
    citations are checked, but its words are not judged as a claim.
    The header is everything before the first `## ` heading (a doc with none has no header)."""
    fenced, printed, header = False, False, any(l.startswith("## ") for l in text.splitlines())
    for n, line in enumerate(text.splitlines(), 1):
        if line.strip() == PRINTED_BEGIN:
            printed = True
            continue
        if line.strip() == PRINTED_END:
            printed = False
            continue
        if printed:
            continue
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


def tags_before_stop(text):
    """"It runs. [A4.2] Next." reads as "It runs [A4.2]. Next.": a tag written after the full stop stays with its sentence."""
    return TAG_AFTER_STOP.sub(lambda m: m.group(2) + m.group(1), text)


def sentences(text):
    """Clauses split after . ! ? or ; (the overreach check judges each clause alone)."""
    return [s for s in re.split(r"(?<=[.!?;])\s+", tags_before_stop(text)) if s.strip()]


def strip_code(text):
    return SPAN.sub(" ", text)


def words_of(text):
    """The words of a text: space-separated tokens with a letter, digit or underscore in them; a [A4.2] tag is not one."""
    return [w for w in TAG.sub(" ", text).split() if re.search(r"\w", w)]


def prose_sentences(text, repo):
    """Every sentence of the prose of a doc, as (doc_line, sentence): headings, the header above the first `## ` heading, fenced
    code, printed blocks and citations are left out. A table row is one sentence. This is what the check calls a claim
    when it counts claims and words per claim, and where a sentence is cut at its whole length, so a citation in the middle
    of a sentence does not cut it in two."""
    out = []
    for n, line, header, heading in doc_lines(text):
        if heading or header:
            continue
        for start, end, cites, _ in reversed(line_items(line, repo)):
            if cites:
                line = line[:start] + " " + line[end:]
        line = LIST_MARK.sub("", line).strip()
        parts = [line] if line.startswith("|") else SENTENCE_END.split(tags_before_stop(re.sub(r"\s+", " ", line)))
        out += [(n, p.strip()) for p in parts if words_of(p)]
    return out


def word_count(doc_text, repo):
    """Words of the whole doc: citations and fenced code are left out, and so is a bare mark ("-", "1.", "##"). The text
    above the first `## ` heading, the headings and the backticked names are counted, except an assembled header: when the
    header holds a Counts line, the whole block above the first heading is left out, because the budget is for the sections.
    Printed blocks are never counted."""
    lines = list(doc_lines(doc_text))
    assembled = any(in_header and COUNTS_LINE.search(line) for _, line, in_header, _ in lines)
    total = 0
    for _, line, in_header, _ in lines:
        if assembled and in_header:
            continue
        for start, end, cites, _ in reversed(line_items(line, repo)):
            if cites:
                line = line[:start] + " " + line[end:]
        total += len(words_of(LIST_MARK.sub("", line)))
    return total


def appendix_index(text, repo):
    """{"A4.2": (doc_line, sentence)}: the sentences of each `## A<n> ...` section of the appendix, numbered from 1 in order.
    A Part 1 tag [A4.2] points at the second sentence of section A4. Sentences above the first A section are not indexed."""
    index, sec, k = {}, None, 0
    by_line = {}
    for n, s in prose_sentences(text, repo):
        by_line.setdefault(n, []).append(s)
    for n, line, header, heading in doc_lines(text):
        if heading:
            m = re.match(r"#+\s+A(\d+)\b", line)
            sec, k = (m.group(1), 0) if m else (None, 0)
            continue
        if sec is None:
            continue
        for s in by_line.get(n, []):
            k += 1
            index["A%s.%d" % (sec, k)] = (n, s)
    return index


def part1_slice(guide):
    """The guide with every line outside Part 1 blanked, so line numbers stay the same. Part 1 runs from the heading `Part 1` to the
    heading `Part 2`; printed blocks inside it are blanked too. A guide with no `Part 1` heading gives "" (and no Part 2 heading means to the end)."""
    out, inside, printed = [], False, False
    for line in guide.splitlines():
        if re.match(r"#+\s+Part 1\b", line):
            inside = True
        elif re.match(r"#+\s+Part 2\b", line):
            inside = False
        if line.strip() == PRINTED_BEGIN:
            printed = True
            out.append("")
            continue
        if line.strip() == PRINTED_END:
            printed = False
            out.append("")
            continue
        out.append(line if inside and not printed else "")
    return "\n".join(out) if any(out) else ""
