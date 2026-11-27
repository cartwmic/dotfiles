#!/usr/bin/env python3
"""check-ci-coverage.py [ROOT]: fail when a test file exists that CI neither runs nor names in scripts/ci-not-run.txt.

The mistake: a test file is added (or a directory of them) and nobody lists it in the runner, so it never runs and can fail for months
without anyone seeing it (the inspect-prompt tests: one failed on main for two months). A test file is one of
  test_*.py and *_test.py       (Python unittest)
  *.test.{ts,tsx,mjs,js,cjs} and *.spec.{ts,tsx,mjs,js,cjs}   (node's test runner)
anywhere under ROOT (default: the repository root), apart from .git, node_modules and __pycache__.

What CI runs is read from the runner itself, not from a second list:
  scripts/ci-linux.sh      the `scripts/ci-par.py` arguments (SUITE[:PATTERN] and --per-test DIR), every
                           `python3 -m unittest discover -s DIR [-p PATTERN]`, and every file named on a `node ... --test FILE ...` line
  .github/workflows/ci.yml every `python3 -m unittest discover -s DIR [-p PATTERN]` (the macOS job)
A suite runs the files `unittest discover` finds there: PATTERN (default test*.py) in DIR and in each package below it (a folder with an
__init__.py), the way unittest finds them (a file whose name is not an importable module name, such as test-x.py, is not found). A command that is
commented out runs nothing.

What CI cannot run is named in scripts/ci-not-run.txt, one entry per line, `PATH: reason` (PATH is a file or a folder; a folder covers every
test file under it; the reason says why it cannot run on the CI machines, or the tracking issue). Blank lines and lines starting with # are ignored.

Fails, naming the file or the entry, when:
  - a test file is neither run nor listed;
  - an entry has no reason, names a path that does not exist, or names a test file that CI does run (remove the entry);
  - the runner's lists cannot be read (the format changed: fix this script with it).

Exit 0 clean, 1 a problem, 2 the root has no runner to read.
"""
import fnmatch
import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", "__pycache__"}
PY_TEST = re.compile(r"^(test_.*|.*_test)\.py$")
JS_TEST = re.compile(r"^.*\.(test|spec)\.(ts|tsx|mjs|js|cjs)$")
MODULE_FILE = re.compile(r"^[_a-z]\w*\.py$", re.I)  # unittest discover skips a file whose name is not an importable module name (test-x.py)
LIST = "scripts/ci-not-run.txt"


def test_files(root):
    found = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if PY_TEST.match(name) or JS_TEST.match(name):
                found.append(os.path.relpath(os.path.join(folder, name), root))
    return found


def discover(root, suite, pattern):
    """The files `python3 -m unittest discover -s SUITE -p PATTERN` loads: PATTERN in SUITE and in each package (folder with __init__.py) below it."""
    found = set()

    def walk(rel):
        here = os.path.join(root, rel)
        if not os.path.isdir(here):
            return
        for name in sorted(os.listdir(here)):
            path = os.path.join(here, name)
            if os.path.isfile(path) and MODULE_FILE.match(name) and fnmatch.fnmatch(name, pattern):
                found.add(os.path.normpath(os.path.join(rel, name)))
            elif os.path.isdir(path) and os.path.isfile(os.path.join(path, "__init__.py")):
                walk(os.path.join(rel, name))

    walk(suite)
    return found


def uncommented(text):
    """The text without its comments: a command that is commented out (the usual way to switch a flaky test off) runs nothing."""
    return "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())


def runner_specs(root):
    """([(suite, pattern)], [node test files]) that scripts/ci-linux.sh and the workflow run; raises ValueError when the lists cannot be read."""
    with open(os.path.join(root, "scripts/ci-linux.sh"), encoding="utf-8") as f:
        sh = uncommented(f.read())
    with open(os.path.join(root, ".github/workflows/ci.yml"), encoding="utf-8") as f:
        yml = uncommented(f.read())
    specs = []
    block = re.search(r"python3 scripts/ci-par\.py(.*?)\|\| status=1", sh, re.S)
    if not block:
        raise ValueError("scripts/ci-linux.sh has no `python3 scripts/ci-par.py ... || status=1` command")
    tokens = [t.strip("'\"") for t in block.group(1).replace("\\\n", " ").split()]
    for token in tokens:  # `--per-test DIR` runs DIR's tests too, so DIR is read as a suite like the others
        if token != "--per-test":
            suite, _, pattern = token.partition(":")
            specs.append((suite, pattern or "test*.py"))
    if not specs:
        raise ValueError("the ci-par.py command in scripts/ci-linux.sh names no suite")
    for text in (sh, yml):
        for m in re.finditer(r"unittest discover -s (\S+)(?: -p (\S+))?", text):
            specs.append((m.group(1), m.group(2) or "test*.py"))
    nodes = []
    for line in sh.replace("\\\n", " ").splitlines():  # a command continued with a backslash is one line
        if re.search(r"\bnode\b.*--test\b", line):
            nodes += [t for t in line.split() if JS_TEST.match(os.path.basename(t))]
    return specs, nodes


def read_list(root):
    """[(path, reason, line number)] from scripts/ci-not-run.txt, plus the problems found reading it."""
    entries, problems = [], []
    path = os.path.join(root, LIST)
    if not os.path.isfile(path):
        return entries, ["%s is missing: it names the test files CI cannot run (an empty file if there are none)" % LIST]
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            where, sep, reason = line.partition(": ")
            where, reason = where.strip(), reason.strip()
            if not sep or not reason:
                problems.append("%s:%d: `%s` has no reason; write `PATH: why CI cannot run it`" % (LIST, n, line))
                continue
            entries.append((where.rstrip("/"), reason, n))
    return entries, problems


def check(root):
    """The list of problems (strings); empty when every test file is run or named."""
    specs, nodes = runner_specs(root)
    run = set()
    for suite, pattern in specs:
        run |= discover(root, suite, pattern)
    run |= {os.path.normpath(n) for n in nodes}
    entries, problems = read_list(root)
    named = {}
    for where, reason, n in entries:
        if not os.path.exists(os.path.join(root, where)):
            problems.append("%s:%d: `%s` does not exist: remove the entry" % (LIST, n, where))
            continue
        named[where] = n
    files = test_files(root)
    for f in files:
        listed = [w for w in named if f == w or f.startswith(w + "/")]
        if f in run and listed:
            problems.append("%s:%d: `%s` is run by CI (%s): remove the entry" % (LIST, named[listed[0]], listed[0], f))
        elif f not in run and not listed:
            problems.append("%s is a test file that CI does not run: add it to scripts/ci-linux.sh (its suite's folder in the ci-par.py list, or a "
                            "`node --test` line), or add `%s: <why CI cannot run it>` to %s" % (f, f, LIST))
    for w, n in named.items():
        if not any(f == w or f.startswith(w + "/") for f in files):
            problems.append("%s:%d: `%s` holds no test file: remove the entry" % (LIST, n, w))
    return problems


def main(argv):
    root = argv[1] if len(argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        problems = check(root)
    except (OSError, ValueError) as err:
        print("check-ci-coverage: cannot read the runner under %s: %s" % (root, err), file=sys.stderr)
        return 2
    for p in problems:
        print("check-ci-coverage: " + p)
    if not problems:
        print("check-ci-coverage: every test file is run by CI or named in %s" % LIST)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
