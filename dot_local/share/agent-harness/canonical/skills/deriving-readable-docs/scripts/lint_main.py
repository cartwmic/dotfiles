#!/usr/bin/env python3
"""Check Part 1 of a GUIDE.md reads as plain English and says nothing the appendix does not.

usage: lint_main.py <GUIDE.md> <repo> --surfaces surfaces.json [--jargon references/jargon.txt] [--fixed fixed-ids.txt] [--max-words N]

Part 1 is the text from the heading `Part 1` to the heading `Part 2`. Prints `doc:line: FAIL kind: detail` (or `warn`), then the Part 1 word count (`Part 1: N words (limit 1000)`) and a count; exit 1 on any FAIL.
  part1-words       over 1,000 words (or --max-words N: the halved budget of a small repo) fails, at any step, fix rounds included (headings and backticked names count; citations, printed blocks and tags do not)
  sentence-length   a sentence of more than 18 words fails, and so does an average above 14
  heading-depth     a heading deeper than two levels (###) fails
  tag               every sentence ends in a tag such as [A4.3f9a] and every tag must name an appendix line (the id that line carries at its end)
  condition         a sentence whose tagged appendix lines hold a condition word (CONDITION below) must name a condition too. "By default" passes only when
                    the tagged appendix sentence itself states a default. The very next sentence with the same tag may carry the condition.
                    In the appendix line, `without` and `otherwise` count only where they open a clause (at its start or after , ; : ( or a dash), and a
                    word inside quotation marks or a backticked name is not the sentence's own condition
  label             a sentence whose tagged appendix line says its source (README, a file such as CONTRACT.md, a code comment, help text) must say a source too. A `.md`,
                    `.rst` or `.txt` name is a source only when the repo holds a file of that name (a file the product writes, such as notes.md, is not)
  absolute          a Part 1 sentence that uses any, anything, every, all, only, always, never, nothing, none or unless fails unless at least one tagged appendix sentence
                    uses the same word (a whole word; a word inside quotation marks or a backticked name does not count on either side)
  who-for           Part 1 states who uses the product: a `Who it is for` line or section, each sentence tagged to an appendix line (which may say the repo does not say)
  how-to-start      Part 1 needs a `## How to start` section with at least one sentence, and each sentence must rest on a cited appendix line
  glossary          an optional `## Glossary` at the end, each entry `term: definition`, any number. An entry with no tag defines a term from outside the
                    repo and makes no claim about it: it holds no backticked name and no --flag. An entry about the repo carries a tag like any sentence
  fixed             with --fixed (the file `slice.py --record-fixed` writes), a warning when a Part 1 sentence a checker already fixed was reworded; a row recorded as `cut` is skipped
  citation          a `path:line` in Part 1 fails: the code belongs in the appendix
  backticks         more than 8 distinct backticked names fails, and so does one that is not a surface name (a row of surfaces.json, or its first word)
  flags             more than 3 distinct `--flag` tokens fails (the same flag twice is one)
  jargon            more than 4 hits per 1,000 words of references/jargon.txt fails; a term counts with a common ending (-s, -es, -ed, -d, -ing), once for each span
  appendix-match    a number, a "quoted" string or a backticked name in a sentence must also be in one of the appendix sentences its tags name
Log: each run appends one JSON line (runlog.py: script, action `lint-part1`, outcome ok or failed, part1_words, words_limit, fails, warns).
Stdlib only. Exit 2 on a usage error.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import SPAN, TAG, appendix_index, doc_lines, line_items, part1_slice, prose_sentences, strip_code, word_count, words_of  # noqa: E402
from runlog import log_run  # noqa: E402

WORDS_MAX, SENTENCE_MAX, SENTENCE_AVG, NAMES_MAX, FLAGS_MAX, JARGON_PER_1000 = 1000, 18, 14, 8, 3, 4
# The words that make an appendix sentence conditional, and let a Part 1 sentence say so: one list, used on both sides.
CONDITION = re.compile(r"(?<![\w-])(?:if|unless|only|when|whenever|except|until|without|otherwise|while|once|other than|as long as|apart from)(?![\w-])", re.I)
CLAUSE_ONLY = {"without", "otherwise"}  # in an appendix sentence these count only where they open a clause
CLAUSE_START = re.compile(r"(?:^|[.!?,;:(\u2014\u2013])\s*$")
BY_DEFAULT = re.compile(r"(?<![\w-])(?:by default|in the default setup)(?![\w-])", re.I)
A_DEFAULT = re.compile(r"(?<![\w-])defaults?(?:ed|s)?(?![\w-])", re.I)
# Words that say "the whole set" or "no exception": a Part 1 sentence may use one only when a tagged appendix sentence does.
ABSOLUTE = re.compile(r"(?<![\w-])(?:any|anything|every|all|only|always|never|nothing|none|unless)(?![\w-])", re.I)
WHO_FOR = re.compile(r"^\W*who it is for\b", re.I)
# A source an appendix sentence names for itself: the README, a file such as CONTRACT.md, a code comment, help text, a test title, the docs.
SOURCE_LABEL = re.compile(r"(?<![\w-])(?:README|[\w-]+\.(?:md|rst|txt)|code comments?|help text|test titles?|docs|documentation)(?![\w-])", re.I)
CUT = "cut"  # the sentence slot of a fixed-ids row for a sentence that did not hold on its re-check
FILE_LABEL = re.compile(r"^[\w-]+\.(?:md|rst|txt)$", re.I)  # a source named by a file; it counts only when the repo holds a file of that name
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}
_REPO_NAMES = {}
SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")
FLAG = re.compile(r"(?<![\w-])--[a-z][\w-]*")


def squash(text):
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def repo_file_names(repo):
    """The names and relative paths of the files of a repo (cached): what a `*.md` source label is checked against."""
    if repo not in _REPO_NAMES:
        found = set()
        for root, dirs, files in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                found.update((f.lower(), os.path.relpath(os.path.join(root, f), repo).lower()))
        _REPO_NAMES[repo] = found
    return _REPO_NAMES[repo]


def source_labels(text, repo):
    """The sources a text names: README, a code comment, help text, a test title, the docs, or a `NAME.md`-style file that is in the repo. A file name that is not in the
    repo (a file the product writes, such as notes.md) is not a source."""
    return [m.group(0) for m in SOURCE_LABEL.finditer(text) if not FILE_LABEL.match(m.group(0)) or m.group(0).lower() in repo_file_names(repo)]


def surface_names(rows):
    names = set()
    for r in rows:
        names.add(r["name"])
        names.update(r["name"].split())
        names.update(p for p in re.split(r"[/\s]+", r["name"]) if p)
    return names


def absolute_words(text):
    """The absolute words (ABSOLUTE) a sentence uses, lowercase. A word inside quotation marks or a backticked name is not the sentence's own."""
    plain = re.sub(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d', " ", SPAN.sub(" ", TAG.sub(" ", text)))
    return {m.group(0).lower() for m in ABSOLUTE.finditer(plain)}


def appendix_conditions(text):
    """The condition words an appendix sentence holds. A word inside quotation marks or a backticked name is not the sentence's own; `without` and `otherwise` count
    only where they open a clause, so "fails with a 401 without a token" holds none."""
    plain = re.sub(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d', " ", SPAN.sub(" ", text))
    found = set()
    for m in CONDITION.finditer(plain):
        word = m.group(0).lower()
        if word not in CLAUSE_ONLY or CLAUSE_START.search(plain[:m.start()]):
            found.add(word)
    return sorted(found)


def names_condition(bare, appendix_text):
    """Does a Part 1 sentence (its tags taken out) name a condition? Any condition word does. "By default" does only when the appendix sentence states a default."""
    return bool(CONDITION.search(bare)) or (bool(BY_DEFAULT.search(bare)) and bool(A_DEFAULT.search(appendix_text)))


def read_fixed(path):
    """{tags: sentence} from a file of `A4.3f9a [A4.77b0] | the sentence` rows."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for l in f:
            tags, bar, sentence = l.partition("|")
            if bar and tags.strip() and sentence.strip() != CUT:  # a sentence recorded as cut may be reworded or gone
                out[" ".join(sorted(tags.split()))] = sentence.strip()
    return out


def jargon_pattern(terms):
    """One pattern for the whole list: each term whole, or with a common ending on its last word (-s, -es, -ed, -d, -ing; a final e drops before -ing), longest term first so a
    span is counted once ("endpoints" is one hit, not two)."""
    alts = []
    for t in sorted({t.lower() for t in terms}, key=len, reverse=True):
        stem = re.escape(t)
        alts.append(stem + r"(?:s|es|ed|d|ing)?" + (r"|" + re.escape(t[:-1]) + "ing" if t.endswith("e") else ""))
    return re.compile(r"(?<![\w-])(?:" + "|".join(alts) + r")(?![\w-])", re.I) if alts else None


def jargon_hits(text, terms):
    pattern = jargon_pattern(terms)
    return len(pattern.findall(text)) if pattern else 0


def section_lines(part1):
    """{lowercase heading text: (first_line, last_line)} of the `#`/`##` sections of Part 1; the lines a section holds are the ones after its heading."""
    heads = [(n, re.sub(r"^#+\s+", "", l).strip().lower()) for n, l in enumerate(part1.splitlines(), 1) if re.match(r"#{1,2}\s", l)]
    total = len(part1.splitlines())
    return {name: (n + 1, (heads[i + 1][0] - 1) if i + 1 < len(heads) else total) for i, (n, name) in enumerate(heads)}


def lint(guide, repo, rows, terms, fixed=None, words_max=WORDS_MAX):
    """Return (fails, warns, words): the first two as [(doc_line, kind, detail)], then the Part 1 word count. `fixed` is {tags: sentence}: Part 1 sentences a checker already fixed."""
    fails, warns = [], []
    part1 = part1_slice(guide)
    if not part1:
        return [(1, "part1", "no heading `Part 1`")], warns, 0
    index = appendix_index(guide, repo)
    words = word_count(part1, repo)
    if words > words_max:
        fails.append((1, "part1-words", "%d words, limit %d at every step: shorten or merge sentences a fix narrowed first; never cut How to start or the who-it-is-for sentence" % (words, words_max)))
    sents = prose_sentences(part1, repo)
    sections = section_lines(part1)
    gloss = next((v for k, v in sections.items() if k.startswith("glossary")), None)
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
    flag_count = len(set(FLAG.findall("\n".join(text_lines))))
    if flag_count > FLAGS_MAX:
        fails.append((1, "flags", "%d --flag tokens, limit %d" % (flag_count, FLAGS_MAX)))
    prose_text = "\n".join(strip_code(l) for l in text_lines)
    if words and jargon_hits(prose_text, terms) * 1000 / words > JARGON_PER_1000:
        fails.append((1, "jargon", "%d hits in %d words, limit %d per 1,000" % (jargon_hits(prose_text, terms), words, JARGON_PER_1000)))
    for i, (n, s) in enumerate(sents):
        tags = TAG.findall(s)
        if not tags:
            if not (gloss and gloss[0] <= n <= gloss[1]):  # a glossary entry may define an outside term and carry no tag
                fails.append((n, "tag", "no [A#.#] tag | %s" % s))
            continue
        backed = [index[t.strip("[]")][1] for t in tags if t.strip("[]") in index]
        for t in tags:
            if t.strip("[]") not in index:
                fails.append((n, "tag", "%s names no appendix line | %s" % (t, s)))
        if not backed:
            continue
        bare = TAG.sub(" ", s)
        for t in tags:
            text = index.get(t.strip("[]"), (0, ""))[1]
            conditions = appendix_conditions(text)
            nxt = sents[i + 1][1] if i + 1 < len(sents) else ""
            carried = t in TAG.findall(nxt) and names_condition(TAG.sub(" ", nxt), text)  # the very next sentence with the same tag carries it
            if conditions and not names_condition(bare, text) and not carried:
                fails.append((n, "condition", "%s holds %s and the sentence names no condition: state it (\"by default\" counts only when the line states a default) | %s" % (t, ", ".join("\"%s\"" % w for w in conditions), s)))
            labels = sorted(set(source_labels(text, repo)))
            if labels and not source_labels(bare, repo):
                fails.append((n, "label", "%s says its source (%s) and the sentence drops it | %s" % (t, ", ".join(labels), s)))
        stretched = sorted(absolute_words(bare) - set().union(*(absolute_words(b) for b in backed)))
        if stretched:
            fails.append((n, "absolute", "%s: no tagged appendix sentence uses %s, so Part 1 says more than it shows: drop the word or state the case | %s" % (
                ", ".join(stretched), "it" if len(stretched) == 1 else "them", s)))
        have, have_sq = " ".join(backed), squash(" ".join(backed))
        nums = {x.replace(",", "") for x in NUMBER.findall(have.replace(",", ""))} | set(NUMBER.findall(have))
        for num in NUMBER.findall(strip_code(bare)):
            if num.replace(",", "") not in nums and num not in nums:
                fails.append((n, "appendix-match", "number %s is not in %s | %s" % (num, ", ".join(tags), s)))
        quoted = re.findall(r'"([^"\n]+)"|“([^”\n]+)”', strip_code(bare))
        for tok in [a or b for a, b in quoted] + [m.group(1) for m in SPAN.finditer(bare)]:
            if squash(tok) and squash(tok) not in have_sq:
                fails.append((n, "appendix-match", "%r is not in %s | %s" % (tok, ", ".join(tags), s)))
    start = next((v for k, v in sections.items() if k.startswith("how to start")), None)
    steps = [(n, t) for n, t in sents if start and start[0] <= n <= start[1]]
    if not steps:
        fails.append((1, "how-to-start", "Part 1 needs a `## How to start` section with the first install or run step, each step a sentence"))
    if not any(WHO_FOR.match(TAG.sub(" ", t)) for _, t in sents) and not next((v for k, v in sections.items() if k.startswith("who it is for") and any(v[0] <= n <= v[1] for n, _ in sents)), None):
        fails.append((1, "who-for", "Part 1 needs a `Who it is for` line or section: who uses the product (README or docs), or a tagged sentence that says the repo does not say"))
    for n, t in steps:
        for tag in TAG.findall(t):
            if tag.strip("[]") in index and not index[tag.strip("[]")][2]:
                fails.append((n, "how-to-start", "the step rests on %s, an appendix line with no citation: cite it there | %s" % (tag, t)))
    for n, t in [(n, t) for n, t in sents if gloss and gloss[0] <= n <= gloss[1]]:
        if not re.match(r"\s*(?:[-*]\s+)?\**([^:]+?)\**\s*:\s+\S", TAG.sub(" ", t)):
            fails.append((n, "glossary", "an entry reads `term: definition` | %s" % t))
        elif not TAG.search(t) and (SPAN.search(t) or FLAG.search(t)):
            fails.append((n, "glossary", "an entry with no tag defines a term from outside the repo and names nothing of it (no `name`, no --flag): tag it to an appendix line | %s" % t))
    by_tags = {}
    for n, t in sents:
        by_tags.setdefault(" ".join(sorted(TAG.findall(t))).replace("[", "").replace("]", ""), []).append(squash(TAG.sub(" ", t)))
    for tags, was in (fixed or {}).items():
        now = by_tags.get(tags)
        if now and squash(was) not in now:
            warns.append((1, "fixed", "a sentence a checker already fixed was reworded (%s): was \"%s\" | now \"%s\"" % (tags, was, next(t for n, t in sents if " ".join(sorted(TAG.findall(t))).replace("[", "").replace("]", "") == tags and squash(TAG.sub(" ", t)) == now[0]).replace("\n", " ").strip())))
    return sorted(set(fails)), warns, words


def main(argv):
    args, opts, it = [], {}, iter(argv[1:])
    for a in it:
        if a in ("--surfaces", "--jargon", "--fixed", "--max-words"):
            opts[a] = next(it, None)
        else:
            args.append(a)
    if len(args) != 2 or not os.path.isfile(args[0]) or not os.path.isdir(args[1]) or not opts.get("--surfaces") or not os.path.isfile(opts["--surfaces"]) \
            or (opts.get("--jargon") and not os.path.isfile(opts["--jargon"])) or (opts.get("--fixed") and not os.path.isfile(opts["--fixed"])) \
            or None in opts.values() or (opts.get("--max-words") is not None and not opts["--max-words"].isdigit()):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    jargon = opts.get("--jargon") or os.path.join(SKILL, "references", "jargon.txt")
    with open(opts["--surfaces"], encoding="utf-8") as f:
        rows = json.load(f)
    with open(jargon, encoding="utf-8") as f:
        terms = [l.strip() for l in f if l.strip() and not l.startswith("#")]
    with open(args[0], encoding="utf-8", errors="replace") as f:
        guide = f.read()
    words_max = int(opts["--max-words"]) if "--max-words" in opts else WORDS_MAX
    fails, warns, words = lint(guide, os.path.realpath(args[1]), rows, terms, read_fixed(opts["--fixed"]) if opts.get("--fixed") else None, words_max)
    for n, kind, detail in warns:
        print("%s:%d: warn %s: %s" % (args[0], n, kind, detail))
    for n, kind, detail in fails:
        print("%s:%d: FAIL %s: %s" % (args[0], n, kind, detail))
    print("Part 1: %d words (limit %d)" % (words, words_max))
    print("%d failed checks, %d warnings" % (len(fails), len(warns)))
    log_run("lint_main.py", "lint-part1", "failed" if fails else "ok", part1_words=words, words_limit=words_max, fails=len(fails), warns=len(warns))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
