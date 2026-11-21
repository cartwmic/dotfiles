#!/usr/bin/env python3
"""Join the parts of a guide into one GUIDE.md, print its header and evidence block, and list the appendix sentences for the front writer.

usage: assemble.py <work> <repo> [-o GUIDE.md] [--clean] [--index] [--date YYYY-MM-DD]

<work> holds the parts, by name:
  part1.md          the front writer's text: `## ` sections only; assemble adds the `# Part 1: In plain English` heading
  A3.md, A4.md ...  the frame and the section writers, each starting `## A<n> <title>`; the numbers run from 3 with no gap; every prose line and every data row of
                    a table ends in an id (`stamp.py A4.md` gives them), and no id is on two lines. A file may hold the blocks `### Defaults and limits`
                    (a table: Setting or behaviour, Value, Unit, Cited) and `### When things fail` (Case, What happens, Cited): assemble moves the rows of every file
                    into two sections of their own, numbered after the last file (a row keeps its id), and refuses a block with another header or with prose in it
  surfaces.json     from `surfaces.py <repo> --json`
  points.json       from `harvest_points.py <repo>` (optional: without it the evidence block says no tests were found)
  scout.resolved    from `surfaces.py <repo> --resolve scout.txt` (optional); a NOT FOUND or WEAK MATCH row is counted in the header and left out of A1
  not-read.txt      one path or folder a line that nobody read (optional); each must exist in <repo>
Writes GUIDE.md (default <work>/GUIDE.md): the header, Part 1, then Part 2 with A1 Surfaces and A2 Evidence (both printed from the files above), A3, A4 and on,
and A-last Not read. Everything a script printed sits between `<!-- printed -->` and `<!-- /printed -->`: check_citations.py and lint_main.py do not
read it as claims or count it as words.
  header    repo, commit (git rev-parse HEAD, else "no git"), date, surface counts by kind, test cases and files, surfaces named in tests
  A2        a surface of kind command, flag, route, event or env is named in tests when its name (first word, at least 3 characters) is in the text of a test file of
            points.json; the ones never named are listed
--clean also writes the guide without tags and printed markers, next to -o as GUIDE.clean.md.
--index prints every appendix line as `A4.3f9a | sentences` (the id the line carries, citations taken out with the space before a stop or comma) and writes nothing: it is what the front writer tags from.
Exit 1 when a part is missing or misnumbered, a prose line has no id or an id is on two lines, or a not-read path does not exist; 2 on bad usage. Stdlib only.
"""
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import PRINTED_BEGIN, PRINTED_END, TABLE_SEPARATOR, TAG, appendix_index, appendix_lines, appendix_problems, multi_sentence_lines  # noqa: E402

SECTION_FILE = re.compile(r"^A(\d+)\.md$")
# The two tables every section writer may add as `###` blocks; assemble gathers them into two sections after the last one: title, header cells.
TABLES = (("Defaults and limits", ("Setting or behaviour", "Value", "Unit", "Cited")), ("When things fail", ("Case", "What happens", "Cited")))
BLOCK_HEAD = re.compile(r"^###\s+(.+?)\s*$")
NAMED_KINDS = ("command", "flag", "route", "event", "env")
KINDS = ("entry", "command", "flag", "route", "event", "env", "config", "manifest", "export", "doc", "ci")


class AssembleError(Exception):
    pass


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def commit_of(repo):
    r = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "no git"


def printed(*lines):
    return "\n".join([PRINTED_BEGIN, *lines, PRINTED_END])


def row(r):
    return "%s | %s | %s:%d" % (r["kind"], r["name"], r["file"], r["line"])


def named_in_tests(repo, rows, test_files):
    """Split the surface rows of the user-visible kinds into those whose name is in the text of a test file, and those never named."""
    text = "\n".join(read(os.path.join(repo, f)) for f in test_files if os.path.isfile(os.path.join(repo, f)))
    named, never = [], []
    for r in rows:
        if r["kind"] not in NAMED_KINDS:
            continue
        word = r["name"].split()[0] if r["name"].split() else ""
        (named if len(word) >= 3 and word in text else never).append(r)
    return named, never


def cells(row):
    return tuple(c.strip() for c in row.strip().strip("|").split("|"))


def take_tables(text, name):
    """(text without the table blocks, {title: [data rows]}): the `### Defaults and limits` and `### When things fail` blocks of one section file. A block holds
    only a table with the header named in TABLES; a block with anything else, or another header, is refused."""
    kept, rows, lines, i = [], {title: [] for title, _ in TABLES}, text.split("\n"), 0
    heads = dict(TABLES)
    while i < len(lines):
        m = BLOCK_HEAD.match(lines[i])
        if not m or m.group(1) not in heads:
            kept.append(lines[i])
            i += 1
            continue
        title, i = m.group(1), i + 1
        block = []
        while i < len(lines) and not lines[i].startswith("#"):
            if lines[i].strip():
                block.append(lines[i].strip())
            i += 1
        want = "| " + " | ".join(heads[title]) + " |"
        if block and (cells(block[0]) != heads[title] or len(block) < 2 or not TABLE_SEPARATOR.match(block[1]) or any(not b.startswith("|") for b in block)):
            raise AssembleError("%s: the `### %s` block holds only a table whose header is `%s` and a `|---|` row, then one row per line" % (name, title, want))
        bare = [b for b in block[2:] if not TAG.search(b)]
        if bare:
            raise AssembleError("%s: %d rows of `### %s` have no id (first: %s): run stamp.py on it" % (name, len(bare), title, bare[0][:50]))
        rows[title] += block[2:]
    return "\n".join(kept), rows


def table_sections(first, gathered):
    """The two gathered sections, numbered from `first`: `## A<n> <title>`, the header and the rows of every section file; a section with no rows says so in a printed block."""
    out = []
    for k, (title, head) in enumerate(TABLES):
        body = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head), *gathered[title]] if gathered[title] else [printed("none listed")]
        out.append("\n".join(["## A%d %s" % (first + k, title), "", *body]))
    return out


def sections(work):
    found = {}
    for name in os.listdir(work):
        m = SECTION_FILE.match(name)
        if m:
            found[int(m.group(1))] = name
    if not found or sorted(found) != list(range(3, 3 + len(found))):
        raise AssembleError("%s: need A3.md, then A4.md and on with no gap; found %s" % (work, ", ".join(sorted(found.values())) or "none"))
    out, gathered = [], {title: [] for title, _ in TABLES}
    for n in sorted(found):
        text = read(os.path.join(work, found[n])).strip()
        if not re.match(r"## A%d\b" % n, text):
            raise AssembleError("%s must start with a `## A%d <title>` heading" % (found[n], n))
        text, rows = take_tables(text, found[n])
        for title in rows:
            gathered[title] += rows[title]
        out.append(text.strip())
    return out + table_sections(3 + len(found), gathered)


def build(work, repo, date, need_part1=True):
    secs = sections(work)
    path = os.path.join(work, "surfaces.json")
    if not os.path.isfile(path):
        raise AssembleError("%s has no surfaces.json (surfaces.py <repo> --json)" % work)
    rows = json.loads(read(path))
    points = json.loads(read(os.path.join(work, "points.json"))) if os.path.isfile(os.path.join(work, "points.json")) else []
    test_files = sorted({p["file"] for p in points})
    named, never = named_in_tests(repo, rows, test_files)
    per = {k: sum(1 for r in rows if r["kind"] == k) for k in KINDS}
    scout = [l.strip() for l in read(os.path.join(work, "scout.resolved")).splitlines() if l.strip()] if os.path.isfile(os.path.join(work, "scout.resolved")) else []
    scout_weak = [l for l in scout if "| WEAK MATCH " in l]
    scout_found = [l for l in scout if not l.endswith("| NOT FOUND") and l not in scout_weak]
    part1 = ""
    if need_part1:
        if not os.path.isfile(os.path.join(work, "part1.md")):
            raise AssembleError("%s has no part1.md" % work)
        part1 = read(os.path.join(work, "part1.md")).strip()
    not_read = [l.strip() for l in read(os.path.join(work, "not-read.txt")).splitlines() if l.strip() and not l.startswith("#")] if os.path.isfile(os.path.join(work, "not-read.txt")) else []
    for p in not_read:
        if not os.path.exists(os.path.join(repo, p)):
            raise AssembleError("not-read.txt: %s is not in the repo" % p)
    header = printed(
        "# %s guide" % os.path.basename(repo.rstrip("/")),
        "",
        "Repo: %s. Commit: %s. Date: %s." % (os.path.basename(repo.rstrip("/")), commit_of(repo), date),
        "Counts: %d surfaces (%s); %d scout names found, %d not found and dropped, %d weak matches (only in scripts or tests) dropped; %d test cases in %d files; %d of %d named surfaces appear in tests."
        % (len(rows), ", ".join("%s %d" % (k, per[k]) for k in KINDS if per[k]) or "none", len(scout_found), len(scout) - len(scout_found) - len(scout_weak), len(scout_weak),
           len(points), len(test_files), len(named), len(named) + len(never)),
        "Evidence: code and the repo's own words first; tests where the repo has them (A2).")
    a1 = ["## A1 Surfaces", "", printed(*([row(r) for r in rows] + ["scout | %s" % l for l in scout_found] or ["none found"]))]
    a2 = ["## A2 Evidence", "", printed("tests found: %d cases in %d files" % (len(points), len(test_files)),
                                       "surfaces named in tests: %d of %d (command, flag, route, event and env rows)" % (len(named), len(named) + len(never)),
                                       "never named in tests:", *([row(r) for r in never] or ["none"]))]
    last = ["## A-last Not read", "", printed(*(not_read or ["none"]))]
    parts = [header, "# Part 1: In plain English", part1, "# Part 2: Appendix: technical detail", "\n".join(a1), "\n".join(a2), *secs, "\n".join(last)]
    text = "\n\n".join(p for p in parts if p) + "\n"
    many = multi_sentence_lines(text)
    if many:
        raise AssembleError("; ".join("doc line %d holds %d sentences: write one sentence on each line, then run stamp.py" % m for m in many[:5]) + (" (and %d more lines)" % (len(many) - 5) if len(many) > 5 else ""))
    unstamped, dups = appendix_problems(text, repo)
    if unstamped:
        by_section = {}
        for l in appendix_lines(text, repo):
            if not l["ids"]:
                by_section.setdefault(l["section"], []).append(l["text"])
        raise AssembleError("; ".join("A%s.md has %d lines with no id (first: %s): run stamp.py on it" % (k, len(v), v[0][:50]) for k, v in sorted(by_section.items())))
    if dups:
        raise AssembleError("; ".join("id %s is on two lines (doc lines %d and %d): one line keeps it" % d for d in dups))
    return text


def clean(text):
    text = "\n".join(l for l in text.splitlines() if l.strip() not in (PRINTED_BEGIN, PRINTED_END))
    return re.sub(r"[ \t]*" + TAG.pattern, "", text) + "\n"


def clean_path(out):
    """Where the guide without tags goes: next to the guide, GUIDE.md becoming GUIDE.clean.md."""
    return re.sub(r"(\.md)?$", ".clean.md", out, count=1)


def main(argv):
    args, out, flags, date, it = [], None, set(), datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), iter(argv[1:])
    for a in it:
        if a == "-o":
            out = next(it, None)
        elif a == "--date":
            date = next(it, None)
        elif a in ("--clean", "--index"):
            flags.add(a)
        else:
            args.append(a)
    if len(args) != 2 or not os.path.isdir(args[0]) or not os.path.isdir(args[1]) or (out is not None and not out) or not date or not re.match(r"^\d{4}-\d\d-\d\d$", date):
        print(__doc__.split("\n\n")[0], file=sys.stderr)
        return 2
    work, repo = args[0], os.path.realpath(args[1])
    try:
        text = build(work, repo, date, need_part1="--index" not in flags)
    except AssembleError as e:
        print(e, file=sys.stderr)
        return 1
    if "--index" in flags:
        for tag, (_, sentence, _) in appendix_index(text, repo).items():
            print("%s | %s" % (tag, sentence))
        return 0
    out = out or os.path.join(work, "GUIDE.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s" % out)
    if "--clean" in flags:
        with open(clean_path(out), "w", encoding="utf-8") as f:
            f.write(clean(text))
        print("wrote %s" % clean_path(out))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
