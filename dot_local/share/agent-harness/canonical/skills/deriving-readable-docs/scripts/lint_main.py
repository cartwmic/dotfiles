#!/usr/bin/env python3
"""Check Part 1 of a GUIDE.md reads as plain English and says nothing the appendix does not.

usage: lint_main.py <GUIDE.md> <repo> --surfaces surfaces.json [--jargon references/jargon.txt]

Part 1 is the text from the heading `Part 1` to the heading `Part 2`. Prints `doc:line: FAIL kind: detail` (or `warn`), then a count; exit 1 on any FAIL.
  part1-words       over 1,000 words warns, over 1,200 fails (headings and backticked names count; citations, printed blocks and tags do not)
  sentence-length   a sentence of more than 18 words fails, and so does an average above 14
  heading-depth     a heading deeper than two levels (###) fails
  tag               every sentence ends in a tag such as [A4.2] and every tag must name an appendix sentence (the 2nd sentence of section A4)
  citation          a `path:line` in Part 1 fails: the code belongs in the appendix
  backticks         more than 8 distinct backticked names fails, and so does one that is not a surface name (a row of surfaces.json, or its first word)
  flags             more than 3 `--flag` tokens fails
  jargon            more than 4 hits per 1,000 words of references/jargon.txt fails
  appendix-match    a number, a "quoted" string or a backticked name in a sentence must also be in one of the appendix sentences its tags name
Stdlib only. Exit 2 on a usage error.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import SPAN, TAG, appendix_index, doc_lines, line_items, part1_slice, prose_sentences, strip_code, word_count, words_of  # noqa: E402

WORDS_WARN, WORDS_FAIL, SENTENCE_MAX, SENTENCE_AVG, NAMES_MAX, FLAGS_MAX, JARGON_PER_1000 = 1000, 1200, 18, 14, 8, 3, 4
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")
FLAG = re.compile(r"(?<![\w-])--[a-z][\w-]*")


def squash(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def surface_names(rows):
    names = set()
    for r in rows:
        names.add(r["name"])
        names.update(r["name"].split())
        names.update(p for p in re.split(r"[/\s]+", r["name"]) if p)
    return names


def jargon_hits(text, terms):
    return sum(len(re.findall(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", text, re.I)) for t in terms)


def lint(guide, repo, rows, terms):
    """Return (fails, warns) as [(doc_line, kind, detail)]."""
    fails, warns = [], []
    part1 = part1_slice(guide)
    if not part1:
        return [(1, "part1", "no heading `Part 1`")], warns
    index = appendix_index(guide, repo)
    words = word_count(part1, repo)
    if words > WORDS_FAIL:
        fails.append((1, "part1-words", "%d words, hard limit %d" % (words, WORDS_FAIL)))
    elif words > WORDS_WARN:
        warns.append((1, "part1-words", "%d words, budget %d" % (words, WORDS_WARN)))
    sents = prose_sentences(part1, repo)
    lengths = [len(words_of(s)) for _, s in sents]
    for (n, s), k in zip(sents, lengths):
        if k > SENTENCE_MAX:
            fails.append((n, "sentence-length", "%d words, limit %d | %s" % (k, SENTENCE_MAX, s)))
    if lengths and sum(lengths) / len(lengths) > SENTENCE_AVG:
        fails.append((1, "sentence-length", "average %.1f words, limit %d" % (sum(lengths) / len(lengths), SENTENCE_AVG)))
    names, flag_count, text_lines = set(), 0, []
    for n, line, _, heading in doc_lines(part1):
        if heading and re.match(r"#{3,}\s", line):
            fails.append((n, "heading-depth", "a heading deeper than two levels | %s" % line.strip()))
        if heading:
            continue
        text_lines.append(line)
        for start, end, cites, span in line_items(line, repo):
            if cites:
                fails.append((n, "citation", "`%s` in Part 1: cite in the appendix" % span))
            else:
                names.add(span.strip())
    ok_names = surface_names(rows)
    if len(names) > NAMES_MAX:
        fails.append((1, "backticks", "%d distinct backticked names, limit %d" % (len(names), NAMES_MAX)))
    for name in sorted(names - ok_names):
        fails.append((1, "backticks", "`%s` is not a surface name (surfaces.json)" % name))
    flag_count = len(FLAG.findall("\n".join(text_lines)))
    if flag_count > FLAGS_MAX:
        fails.append((1, "flags", "%d --flag tokens, limit %d" % (flag_count, FLAGS_MAX)))
    prose_text = "\n".join(strip_code(l) for l in text_lines)
    if words and jargon_hits(prose_text, terms) * 1000 / words > JARGON_PER_1000:
        fails.append((1, "jargon", "%d hits in %d words, limit %d per 1,000" % (jargon_hits(prose_text, terms), words, JARGON_PER_1000)))
    for n, s in sents:
        tags = TAG.findall(s)
        if not tags:
            fails.append((n, "tag", "no [A#.#] tag | %s" % s))
            continue
        backed = [index[t.strip("[]")][1] for t in tags if t.strip("[]") in index]
        for t in tags:
            if t.strip("[]") not in index:
                fails.append((n, "tag", "%s names no appendix sentence | %s" % (t, s)))
        if not backed:
            continue
        have, have_sq = " ".join(backed), squash(" ".join(backed))
        nums = {x.replace(",", "") for x in NUMBER.findall(have.replace(",", ""))} | set(NUMBER.findall(have))
        bare = TAG.sub(" ", s)
        for num in NUMBER.findall(strip_code(bare)):
            if num.replace(",", "") not in nums and num not in nums:
                fails.append((n, "appendix-match", "number %s is not in %s | %s" % (num, ", ".join(tags), s)))
        quoted = re.findall(r'"([^"\n]+)"|“([^”\n]+)”', strip_code(bare))
        for tok in [a or b for a, b in quoted] + [m.group(1) for m in SPAN.finditer(bare)]:
            if squash(tok) and squash(tok) not in have_sq:
                fails.append((n, "appendix-match", "%r is not in %s | %s" % (tok, ", ".join(tags), s)))
    return sorted(set(fails)), warns


def main(argv):
    args, opts, it = [], {}, iter(argv[1:])
    for a in it:
        if a in ("--surfaces", "--jargon"):
            opts[a] = next(it, None)
        else:
            args.append(a)
    if len(args) != 2 or not os.path.isfile(args[0]) or not os.path.isdir(args[1]) or not opts.get("--surfaces") or not os.path.isfile(opts["--surfaces"]) \
            or (opts.get("--jargon") and not os.path.isfile(opts["--jargon"])):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    jargon = opts.get("--jargon") or os.path.join(SKILL, "references", "jargon.txt")
    with open(opts["--surfaces"], encoding="utf-8") as f:
        rows = json.load(f)
    with open(jargon, encoding="utf-8") as f:
        terms = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    with open(args[0], encoding="utf-8", errors="replace") as f:
        guide = f.read()
    fails, warns = lint(guide, os.path.realpath(args[1]), rows, terms)
    for n, kind, detail in warns:
        print("%s:%d: warn %s: %s" % (args[0], n, kind, detail))
    for n, kind, detail in fails:
        print("%s:%d: FAIL %s: %s" % (args[0], n, kind, detail))
    print("%d failed checks, %d warnings" % (len(fails), len(warns)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
