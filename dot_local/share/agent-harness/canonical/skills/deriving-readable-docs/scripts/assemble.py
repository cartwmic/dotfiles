#!/usr/bin/env python3
"""Join the parts of a guide into one GUIDE.md, print its header and evidence block, and list the appendix sentences for the front writer.

usage: assemble.py <work> <repo> [-o GUIDE.md] [--clean] [--index] [--date YYYY-MM-DD]

<work> holds the parts, by name:
  part1.md          the front writer's text: `## ` sections only; assemble adds the `# Part 1: In plain English` heading
  A3.md, A4.md ...  the frame and the section writers, each starting `## A<n> <title>`; the numbers run from 3 with no gap
  surfaces.json     from `surfaces.py <repo> --json`
  points.json       from `harvest_points.py <repo>` (optional: without it the evidence block says no tests were found)
  scout.resolved    from `surfaces.py <repo> --resolve scout.txt` (optional)
  not-read.txt      one path or folder a line that nobody read (optional); each must exist in <repo>
Writes GUIDE.md (default <work>/GUIDE.md): the header, Part 1, then Part 2 with A1 Surfaces and A2 Evidence (both printed from the files above), A3, A4 and on,
and A-last Not read. Everything a script printed sits between `<!-- printed -->` and `<!-- /printed -->`: check_citations.py and lint_main.py do not
read it as claims or count it as words.
  header    repo, commit (git rev-parse HEAD, else "no git"), date, surface counts by kind, test cases and files, surfaces named in tests
  A2        a surface of kind command, flag, route, event or env is named in tests when its name (first word, at least 3 characters) is in the text of a test file of
            points.json; the ones never named are listed
--clean also writes the guide without tags and printed markers, next to -o as GUIDE.clean.md.
--index prints every appendix sentence as `A4.2 | sentence` (section A4, second sentence) and writes nothing: it is what the front writer tags from.
Exit 1 when a part is missing or misnumbered, or a not-read path does not exist; 2 on bad usage. Stdlib only.
"""
import datetime
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # python3 -I leaves the script's folder off the path
sys.dont_write_bytecode = True  # the skill folder is deployed; leave no __pycache__ in it
from claims import PRINTED_BEGIN, PRINTED_END, TAG, appendix_index  # noqa: E402

SECTION_FILE = re.compile(r"^A(\d+)\.md$")
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


def sections(work):
    found = {}
    for name in os.listdir(work):
        m = SECTION_FILE.match(name)
        if m:
            found[int(m.group(1))] = name
    if not found or sorted(found) != list(range(3, 3 + len(found))):
        raise AssembleError("%s: need A3.md, then A4.md and on with no gap; found %s" % (work, ", ".join(sorted(found.values())) or "none"))
    out = []
    for n in sorted(found):
        text = read(os.path.join(work, found[n])).strip()
        if not re.match(r"## A%d\b" % n, text):
            raise AssembleError("%s must start with a `## A%d <title>` heading" % (found[n], n))
        out.append(text)
    return out


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
    scout_found = [l for l in scout if not l.endswith("| NOT FOUND")]
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
        "Counts: %d surfaces (%s); %d scout names found, %d not found and dropped; %d test cases in %d files; %d of %d named surfaces appear in tests."
        % (len(rows), ", ".join("%s %d" % (k, per[k]) for k in KINDS if per[k]) or "none", len(scout_found), len(scout) - len(scout_found),
           len(points), len(test_files), len(named), len(named) + len(never)),
        "Evidence: code and the repo's own words first; tests where the repo has them (A2).")
    a1 = ["## A1 Surfaces", "", printed(*([row(r) for r in rows] + ["scout | %s" % l for l in scout_found] or ["none found"]))]
    a2 = ["## A2 Evidence", "", printed("tests found: %d cases in %d files" % (len(points), len(test_files)),
                                       "surfaces named in tests: %d of %d (command, flag, route, event and env rows)" % (len(named), len(named) + len(never)),
                                       "never named in tests:", *([row(r) for r in never] or ["none"]))]
    last = ["## A-last Not read", "", printed(*(not_read or ["none"]))]
    parts = [header, "# Part 1: In plain English", part1, "# Part 2: Appendix: technical detail", "\n".join(a1), "\n".join(a2), *secs, "\n".join(last)]
    return "\n\n".join(p for p in parts if p) + "\n"


def clean(text):
    text = "\n".join(l for l in text.splitlines() if l.strip() not in (PRINTED_BEGIN, PRINTED_END))
    return re.sub(r"[ \t]*" + TAG.pattern, "", text) + "\n"


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
        for tag, (_, sentence) in appendix_index(text, repo).items():
            print("%s | %s" % (tag, sentence))
        return 0
    out = out or os.path.join(work, "GUIDE.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print("wrote %s" % out)
    if "--clean" in flags:
        clean_path = re.sub(r"(\.md)?$", ".clean.md", out, count=1)
        with open(clean_path, "w", encoding="utf-8") as f:
            f.write(clean(text))
        print("wrote %s" % clean_path)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
