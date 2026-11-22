"""Shared by check_citations.py, lint_main.py, slice.py, score.py and assemble.py: read a derived doc into lines, citations,
claims, sentences and words. Stdlib only; imported, never run.

A doc line is skipped when it is inside a fenced code block or inside a printed block (`<!-- printed -->` ... `<!-- /printed -->`,
which assemble.py writes around rows a script printed: they are not claims and not words).
A citation is a backticked `path:LINE` or `path:START-END`; see line_items. A sentence is the text of a line with its
citations taken out, split after . ! or ? when a capital letter, digit, quote or bracket follows. A tag such as [A4.2] is not a word.

An id is a tag at the end of an appendix line, `[A4.3f9a]`: the section, a dot and a short name that stays with the line when the line is edited, split
or moved and is never reused. A Part 1 sentence ends with the ids of the appendix lines it restates. `stamp_text` gives each prose line of a section file an id.
"""
import hashlib
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
ID = r"A\d+\.\w+"  # section, a dot, the line's own name
TAG = re.compile(r"\[%s\]" % ID)  # an id at the end of an appendix line, or a Part 1 sentence's pointer to one
SAYS_SOURCE = re.compile(r"comment|header|readme|docs?\b|documentation|stated|says|source text|prd|agents\.md", re.I)  # a tag is not a source: only a Part 1 tag is, see says_source
PRINTED_BEGIN, PRINTED_END = "<!-- printed -->", "<!-- /printed -->"
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9`\"'(\[*_])")
TAG_AFTER_STOP = re.compile(r"([.!?])((?:\s*\[%s\])+)" % ID)


def split_lines(text):
    """The lines of a text numbered as `cat -n` and the Read tool number them: cut at "\\n" only. str.splitlines() also cuts at a form feed, a vertical tab and
    a few other marks, which shifts every number after one (khoj.el has eleven form feeds)."""
    lines = [l[:-1] if l.endswith("\r") else l for l in text.split("\n")]
    return lines[:-1] if lines and lines[-1] == "" else lines


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
    fenced, printed, header = False, False, any(l.startswith("## ") for l in split_lines(text))
    for n, line in enumerate(split_lines(text), 1):
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
    right after the group, such as "code comment") and uncited (words after the last group, or a whole line with none; an id after
    the last group is no words). part1 is true inside Part 1, where a tag is a sentence's source (see says_source)."""
    part1 = False
    for n, line, header, heading in doc_lines(text):
        items = line_items(line, repo)
        if heading:
            if re.match(r"#+\s+Part 1\b", line):
                part1 = True
            elif re.match(r"#+\s+Part 2\b", line):
                part1 = False
            for _, _, cites, _ in items:
                if cites:
                    yield {"line": n, "text": "", "cites": cites, "label": "", "uncited": "", "header": header, "heading": True, "part1": part1}
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
                   "uncited": "", "header": header, "part1": part1}
            prev = end + (label.end() if label else 0)
        if not header and TAG.sub("", line[prev:]).strip():
            yield {"line": n, "text": "", "cites": [], "label": "", "uncited": line[prev:] if part1 else TAG.sub("", line[prev:]), "header": header, "part1": part1}


def says_source(text, part1=False):
    """Does the text name its source? A word such as README or "code comment" does. Inside Part 1 a tag does too: it points at the appendix sentence
    the sentence restates. An id at the end of an appendix line names nothing."""
    return bool(SAYS_SOURCE.search(text)) or (part1 and bool(TAG.search(text)))


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


def without_citations(line, repo):
    """The line with its citations taken out. Citations joined by commas, `;`, `&` or "and" (the way `claims` groups them) go as one, so no `, ,` is left where they stood."""
    spans = []  # [start, end] of each group of citations
    for start, end, cites, _ in line_items(line, repo):
        if not cites:
            continue
        if spans and JOIN.match(line[spans[-1][1]:start]):
            spans[-1][1] = end
        else:
            spans.append([start, end])
    for start, end in reversed(spans):
        line = line[:start] + " " + line[end:]
    return line


def prose_sentences(text, repo):
    """Every sentence of the prose of a doc, as (doc_line, sentence): headings, the header above the first `## ` heading, fenced
    code, printed blocks and citations are left out. A table row is one sentence. This is what the check calls a claim
    when it counts claims and words per claim, and where a sentence is cut at its whole length, so a citation in the middle
    of a sentence does not cut it in two."""
    out = []
    for n, line, header, heading in doc_lines(text):
        if heading or header:
            continue
        line = LIST_MARK.sub("", without_citations(line, repo)).strip()
        parts = [line] if line.startswith("|") else split_sentences(tags_before_stop(re.sub(r"\s+", " ", line)))
        out += [(n, p.strip()) for p in parts if words_of(p)]
    return out


def split_sentences(line):
    """The sentences of one line of prose, cut after . ! or ? when a capital letter, digit, quote or bracket follows. A stop inside a
    double-quoted message ("Unable to create. Ensure it is not there.") does not end the sentence: the checkers count it once, so the script does.
    A quote inside a backtick span is code and opens nothing."""
    out = []
    for piece in SENTENCE_END.split(line):
        text = SPAN.sub("", out[-1]) if out else ""
        if out and (text.count('"') % 2 == 1 or text.count("\u201c") > text.count("\u201d")):
            out[-1] += " " + piece
        else:
            out.append(piece)
    return out


def word_count(doc_text, repo, headings=True):
    """Words of the whole doc: citations and fenced code are left out, and so is a bare mark ("-", "1.", "##"). The text
    above the first `## ` heading, the headings and the backticked names are counted; with headings=False the headings are not. Printed blocks (what assemble.py prints,
    its header among them) are never counted."""
    total = 0
    for _, line, _, heading in doc_lines(doc_text):
        if heading and not headings:
            continue
        for start, end, cites, _ in reversed(line_items(line, repo)):
            if cites:
                line = line[:start] + " " + line[end:]
        total += len(words_of(LIST_MARK.sub("", line)))
    return total


def appendix_lines(text, repo):
    """The prose lines of the appendix sections, as dicts {line, section, ids, text, cited}: the line's doc number, its section number (`## A4 ...` is "4"),
    the ids it carries (`[A4.3f9a]`), its sentences joined with ids and citations taken out, and whether it holds a citation.
    A heading `## A<n> ...` starts a section; a deeper heading (`###`) stays inside it; any other heading, such as `# Part 2` or `## A-last`, ends it.
    Table rows are not lines of the appendix: they carry no id."""
    by_line, out, sec = {}, [], None
    for n, s in prose_sentences(text, repo):
        by_line.setdefault(n, []).append(s)
    raw = split_lines(text)
    for n, line, header, heading in doc_lines(text):
        if heading:
            m = re.match(r"(#+)\s+A(\d+)\b", line)
            if m:
                sec = m.group(2)
            elif len(re.match(r"#+", line).group(0)) <= 2:
                sec = None
            continue
        if sec is None or header or line.lstrip().startswith("|") or n not in by_line:
            continue
        body = " ".join(by_line[n])
        out.append({"line": n, "section": sec, "ids": [t.strip("[]") for t in TAG.findall(raw[n - 1])], "text": re.sub(r"\s+([.,;:!?])(?=\s|$)", r"\1", re.sub(r"([.!?])\s*[,;]+(?=\s|$)", r"\1", re.sub(r"\s+", " ", TAG.sub("", body)))).strip(),
                    "cited": any(cites for _, _, cites, _ in line_items(raw[n - 1], repo))})
    return out


def appendix_index(text, repo):
    """{"A4.3f9a": (doc_line, sentences, cited)}: each id of an appendix line (see appendix_lines) with the line's sentences and whether it is cited. A Part 1
    tag [A4.3f9a] points at it. An id is not a position: cutting or splitting a line does not change the other ids."""
    return {i: (l["line"], l["text"], l["cited"]) for l in appendix_lines(text, repo) for i in l["ids"]}


def appendix_problems(text, repo):
    """(unstamped, duplicates): the appendix lines with no id as [(doc_line, text)], and ids carried by two lines as [(id, first_line, second_line)]."""
    unstamped, seen, dups = [], {}, []
    for l in appendix_lines(text, repo):
        if not l["ids"]:
            unstamped.append((l["line"], l["text"]))
        for i in l["ids"]:
            if i in seen and seen[i] != l["line"]:
                dups.append((i, seen[i], l["line"]))
            seen.setdefault(i, l["line"])
    return unstamped, dups


def stamp_text(text, guide=False, skip=()):
    """(new_text, stamped): give each prose line of a section file that has no id one, at its end: `[A4.3f9a]`, the section number from the nearest `## A<n>`
    heading, then four hex digits taken from the line, moved on until they differ from every id already in the file. Lines that have an id are left alone;
    headings, fenced code, printed blocks and table rows are not prose lines. Raises ValueError when prose comes before the first `## A<n>` heading, unless `guide` is true:
    the text is a whole GUIDE.md, and what comes before its first appendix heading (the header and Part 1) is left alone. A line whose number is in `skip` is left without an id."""
    lines, taken, sec, stamped = split_lines(text), set(TAG.findall(text)), None, 0
    for n, line, header, heading in doc_lines(text):
        if heading:
            m = re.match(r"#+\s+A(\d+)\b", line)
            if m:
                sec = m.group(1)
            continue
        if header or line.lstrip().startswith("|") or TAG.search(line) or n in skip:
            continue
        if sec is None:
            if guide:
                continue
            raise ValueError("line %d comes before the first `## A<n>` heading" % n)
        salt = 0
        while True:
            tag = "[A%s.%s]" % (sec, hashlib.sha1(("%s|%s|%d" % (sec, line.strip(), salt)).encode("utf-8")).hexdigest()[:4])
            if tag not in taken:
                break
            salt += 1
        taken.add(tag)
        lines[n - 1] = line.rstrip() + " " + tag
        stamped += 1
    return "\n".join(lines) + ("\n" if text.endswith("\n") else ""), stamped


def sentence_count(line):
    """How many sentences one prose line holds. Backtick spans (citations, code names), ids and a list mark are left out first."""
    text = re.sub(r"\s+", " ", SPAN.sub(" ", TAG.sub(" ", LIST_MARK.sub("", line)))).strip()
    return len([p for p in split_sentences(text) if words_of(p)])


def multi_sentence_lines(text):
    """[(doc_line, sentences)] for each prose line of the appendix sections that holds more than one sentence. An id sits at the end of a line and a Part 1
    tag points at a line, so a line with two sentences has one id for two claims: the sentences stay one a line."""
    out, sec = [], None
    for n, line, header, heading in doc_lines(text):
        if heading:
            m = re.match(r"#+\s+A(\d+)\b", line)
            if m:
                sec = m.group(1)
            elif len(re.match(r"#+", line).group(0)) <= 2:
                sec = None
            continue
        if sec is None or header or line.lstrip().startswith("|"):
            continue
        if sentence_count(line) > 1:
            out.append((n, sentence_count(line)))
    return out


def untagged_glossary_lines(text):
    """The doc lines of the Part 1 `## Glossary` section that carry no tag: each defines a term from outside the repo and makes no claim about it."""
    out, part1, gloss = set(), False, False
    for n, line, header, heading in doc_lines(text):
        if heading:
            if re.match(r"#+\s+Part 1\b", line):
                part1, gloss = True, False
            elif re.match(r"#+\s+Part 2\b", line):
                part1, gloss = False, False
            elif len(re.match(r"#+", line).group(0)) <= 2:
                gloss = part1 and bool(re.match(r"#+\s+glossary\b", line, re.I))
            continue
        if gloss and not TAG.search(line):
            out.add(n)
    return out


def claim_ids(text, repo):
    """[(id, doc_line, sentence, kind)] for every claim of the doc, in order. An id is `N.k`: doc line N, sentence k of that line (k is 1 on a line of one
    sentence). kind is "claim", or "outside" for an untagged glossary entry. The sentence has its citations taken out, and its tags put back at its end."""
    out, seen, outside = [], {}, untagged_glossary_lines(text)
    for n, s in prose_sentences(text, repo):
        seen[n] = seen.get(n, 0) + 1
        tags = "".join(TAG.findall(s))
        plain = re.sub(r"\s+([.!?])", r"\1", re.sub(r"\s+", " ", TAG.sub("", s))).strip()
        out.append(("%d.%d" % (n, seen[n]), n, plain + (" " + tags if tags else ""), "outside" if n in outside else "claim"))
    return out


def part1_slice(guide):
    """The guide with every line outside Part 1 blanked, so line numbers stay the same. Part 1 runs from the heading `Part 1` to the
    heading `Part 2`; printed blocks inside it are blanked too. A guide with no `Part 1` heading gives "" (and no Part 2 heading means to the end)."""
    out, inside, printed = [], False, False
    for line in split_lines(guide):
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
