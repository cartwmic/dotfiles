#!/usr/bin/env python3
"""check-untested-hunks.py BASE HEAD: fail when a pull request changes what a Python script does and no test notices.

The mistake: a fix for a review finding changes a script's behaviour, adds a test for the case the finding named, and not one for
the line it rewrote. The next review round finds a regression there (dotfiles#641: 5af9ab94 and 6b44e819 changed the loop rule of
early_exits.py, which decides when a continue/break counts as an exit; both commits added tests, none about that rule; round 2
found that the rule dropped exits the old one listed). A check that only asks "did the change touch a test file?" passes both
commits. This one asks it of every changed hunk.

It takes the pull request's own change (BASE's merge-base with HEAD, to HEAD) and, for each hunk that changes the code of a
Python script (not a test file), undoes that one hunk in a copy of HEAD. It runs the test files that name the script: the script's own
folder (tests/<script name>/) first, then the others. The first file that fails catches the hunk. If they all still pass, no test
depends on the hunk, and the check fails. A script the pull request adds is one hunk, the whole file: it is undone by emptying it, so a new script that no test that names it
depends on fails the check (dotfiles#908 added a 536-line script and the check said "0 changed code hunks"). A hunk that changes only comments, docstrings or layout is skipped: the
syntax tree is the same with or without it. It judges the pull request as it stands, so a later commit that adds the test clears an
earlier commit's hunk.

A hunk that no test can see on purpose (a refactor, a rename) is declared in the message of a commit of the pull request (first
parents only), in any paragraph, with the script's path (or its file name) before the reason:

    Untested-change: <path of the script>: <why no test can see it, in one line>

The declaration excuses the hunks that commit already holds, not later changes to the script: a later hunk needs its own line. A
declared hunk passes and is printed, so the CI log and the reviewer see each one.

A Python script is a .py file or a file whose first line is a python shebang. Tests are chosen by name: the test files (test_*.py,
*_test.py) that mention the script's file name as a whole word, with or without chezmoi's source prefixes and without ".tmpl" or ".py"
(`kgate` or `executable_kgate.tmpl`).
A script that no test mentions, or whose tests fail, all skip or hang (see TIMEOUT) before anything is undone, prints NOT CHECKED and never fails;
those are other mistakes. Only Python is read, and only unittest-style files (python3 -m unittest). Hunks that depend on each other
(a changed signature and its callers) count as seen when undoing one breaks the tests; the check names a hunk only when the tests
pass without it.

Time: a test file's run is killed after TIMEOUT (600 s, UNTESTED_HUNKS_TIMEOUT); a hang after a hunk is undone counts as caught. The
whole run stops at BUDGET (1500 s, UNTESTED_HUNKS_BUDGET), under the CI step's 30 minutes. A test run still going then is killed, and
each hunk not yet checked prints NOT CHECKED with the reason "time budget". The run ends with its exit code as usual. SIGTERM kills the
test runs the same way and removes the scratch worktrees.

Exit 0 clean, 1 an undeclared hunk, 2 BASE or HEAD does not resolve (a shallow checkout: fetch the history first).
"""
import ast
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from commit_range import git, hunks, is_test_file

TRAILER = "Untested-change"
WORKERS = min(8, os.cpu_count() or 2)
# The whole run. The CI step that runs this has timeout-minutes: 30, so the budget ends the run with a verdict before the step is killed.
BUDGET = int(os.environ.get("UNTESTED_HUNKS_BUDGET", "1500"))
# One test file's run. A hang is an outside limit, not a judgement: undoing a hunk may bring one back (that counts as caught: the tests
# noticed); a hang before anything is undone prints NOT CHECKED. A suite slower than this (tests/heavy-gate) is not checked either.
TIMEOUT = int(os.environ.get("UNTESTED_HUNKS_TIMEOUT", "600"))
POLL = 0.5  # how often a running test file is checked against the budget and TIMEOUT
DEADLINE = float("inf")  # monotonic time the run stops at. main() sets it; the end of main() sets it to 0, so every run stops at its next check


class Hang(Exception):
    pass


class OutOfTime(Exception):
    """The budget is spent, or the run was stopped, before this test file or hunk was checked."""


def strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                node.body = node.body[1:]
    return tree


def shape(text):
    """The syntax tree of Python text without docstrings, as a string; None when it does not parse."""
    try:
        return ast.dump(strip_docstrings(ast.parse(text)))
    except (SyntaxError, ValueError, RecursionError):
        return None


def undo(text, removed, added, start, count):
    """`text` (the file after the commit) with one hunk put back as it was before."""
    lines = text.splitlines(keepends=True)
    first = start if count == 0 else start - 1  # a pure deletion's start is the line above it
    return "".join(lines[:first] + [line + "\n" for line in removed] + lines[first + count:])


PREFIX = r"(?:(?:executable|private|readonly|dot)_)"


def script_name(path):
    """What tests call a script: its file name without chezmoi's source prefixes, ".tmpl" and ".py" (executable_kgate.tmpl: kgate)."""
    return re.sub(r"^" + PREFIX + "+", "", Path(path).name).removesuffix(".tmpl").removesuffix(".py")


def name_pattern(path):
    """Matches the script's name as a whole word, with or without its chezmoi source prefixes (`kgate`, `executable_kgate.tmpl`), and
    not inside a longer name (`my-kgate`, `kgate_helper`)."""
    return re.compile(r"(?<![A-Za-z0-9_-])" + PREFIX + "*" + re.escape(script_name(path)) + r"(?![A-Za-z0-9_-])")


def is_python(path, text):
    return path.endswith(".py") or re.match(r"#!.*\bpython", text) is not None


def tests_naming(commit, path):
    """The test files of the commit's tree that mention the script by name."""
    pattern = name_pattern(path)
    found = []
    for name in git("ls-tree", "-r", "--name-only", commit).splitlines():
        if name.endswith(".py") and is_test_file(name) and re.match(r"(test_.*|.*_test)\.py$", Path(name).name):
            if pattern.search(git("show", "%s:%s" % (commit, name))):
                found.append(name)
    return found


def tests_for(commit, path):
    """tests_naming, with the script's own folder (tests/<script name>/) first: a hunk that its own suite catches stops there."""
    own = "tests/%s/" % script_name(path)
    return sorted(tests_naming(commit, path), key=lambda name: not name.startswith(own))


def wait_for_run(proc, name):
    """The run's stderr. Raises Hang when the run passes TIMEOUT, OutOfTime when the budget ends first. Whatever stops the wait (a SIGTERM
    too), the run's process group is killed and reaped before the exception goes on. A run that starts after the budget ends is stopped
    at its first check, POLL seconds in."""
    started = time.monotonic()
    try:
        while True:
            try:
                return proc.communicate(timeout=POLL)[1]
            except subprocess.TimeoutExpired:
                if time.monotonic() >= DEADLINE:
                    raise OutOfTime(name)
                if time.monotonic() - started >= TIMEOUT:
                    raise Hang(name)
    except BaseException:
        os.killpg(proc.pid, signal.SIGKILL)  # the whole group: a test may have started children
        proc.communicate()
        raise


def run_tests(root, files):
    """(failed, ran): the first test file whose unittest run failed (None when all passed), and how many tests ran and did not skip, summed."""
    ran = 0
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for name in files:
        proc = subprocess.Popen([sys.executable, "-m", "unittest", "discover", "-s", str(Path(name).parent), "-p", Path(name).name],
                                cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, start_new_session=True)
        stderr = wait_for_run(proc, name)
        done = subprocess.CompletedProcess(proc.args, proc.returncode, "", stderr)
        total = re.search(r"^Ran (\d+) tests?", done.stderr, re.MULTILINE)
        skipped = re.search(r"skipped=(\d+)", done.stderr)
        ran += int(total.group(1)) - int(skipped.group(1) if skipped else 0) if total else 0
        if done.returncode != 0:
            first = re.search(r"^((?:FAIL|ERROR): \S+)", stderr, re.MULTILINE)
            return name + (" (" + first.group(1) + ")" if first else ""), ran
    return None, ran


class Checkout:
    """A scratch copy of one commit's tree; closing it removes it."""

    def __init__(self, commit, parent):
        self.root = tempfile.mkdtemp(prefix="untested-hunks-", dir=parent)
        git("worktree", "add", "--detach", "--force", self.root, commit)

    def close(self):
        git("worktree", "remove", "--force", self.root)
        shutil.rmtree(self.root, ignore_errors=True)


def baseline(head, parent, lock, files):
    """run_tests on an unchanged copy of HEAD."""
    with lock:
        base = Checkout(head, parent)
    try:
        return run_tests(base.root, files)
    finally:
        with lock:
            base.close()


def survives(commit, path, hunk, files, parent, lock):
    """True when the tests still pass with this one hunk undone in a fresh copy of the tree. A hang counts as caught. Raises OutOfTime
    when the budget ends while it runs."""
    with lock:
        copy = Checkout(commit, parent)
    try:
        target = Path(copy.root) / path
        target.write_text(undo(target.read_text(), *hunk))
        return run_tests(copy.root, files)[0] is None
    except Hang:
        return False
    finally:
        with lock:
            copy.close()


def added_files(old, new):
    """{path: lines} of the files that `new` adds to `old`. The patch reader skips them (nothing existing was edited), so this reads
    them whole: a new script is one hunk, the whole file, and undoing it leaves an empty file."""
    out = {}
    for path in git("diff", "--name-only", "--no-renames", "--diff-filter=A", old, new).splitlines():
        try:
            out[path] = git("show", "%s:%s" % (new, path)).splitlines()
        except RuntimeError:
            continue
    return out


def code_hunks(merge_base, head):
    """The hunks of the pull request that change what a non-test Python script does, as (path, (removed, added, start, count)). A script
    the pull request adds counts as one hunk, the whole file: a new script that no test depends on is as untested as a changed line."""
    patch = git("diff", "-U0", "--no-renames", "--no-color", merge_base, head)
    after = {}
    out = []
    for path, lines in added_files(merge_base, head).items():
        if is_test_file(path) or not lines:
            continue
        after[path] = "".join(line + "\n" for line in lines)
        if is_python(path, after[path]) and shape(after[path]) != shape(""):
            out.append((path, ([], lines, 1, len(lines))))
    for path, removed, added, start, count in hunks(patch):
        if not path or is_test_file(path):
            continue
        try:
            after.setdefault(path, git("show", "%s:%s" % (head, path)))
        except RuntimeError:
            continue  # the file is gone at HEAD
        if not is_python(path, after[path]):
            continue
        hunk = (removed, added, start, count)
        before = shape(undo(after[path], *hunk))
        if before is None or before != shape(after[path]):
            out.append((path, hunk))
    return out


def declarations(merge_base, head):
    """[(script, reason, commit)] from every `Untested-change: <script>: <why>` line in the messages of the pull request's own commits
    (first parents only: a main merged in brings no declarations)."""
    found = []
    for entry in git("log", "--first-parent", "--format=%H%x01%B%x00", merge_base + ".." + head).split("\0"):
        commit, _, message = entry.strip().partition("\x01")
        for m in re.finditer(r"^" + TRAILER + r":\s*(\S+?):\s*(\S.*)$", message, re.MULTILINE | re.IGNORECASE):
            found.append((m.group(1), m.group(2).strip(), commit))
    return found


def declared_reason(path, hunk, found, merge_base):
    """The reasons that excuse this hunk: from declarations naming the script, in a commit whose own change already holds the same hunk.
    A later change to the script is a different hunk and needs its own declaration."""
    removed, added = hunk[0], hunk[1]
    reasons = []
    for script, why, commit in found:
        if path == script or path.endswith("/" + script):
            seen = [(r, a) for p, r, a, _start, _count in hunks(git("diff", "-U0", "--no-renames", "--no-color", merge_base, commit)) if p == path]
            seen += [([], lines) for new, lines in added_files(merge_base, commit).items() if new == path]
            if (removed, added) in seen:
                reasons.append(why)
    return "; ".join(reasons)


def where(start, count):
    return "after line %d" % start if count == 0 else "line %d" % start if count == 1 else "lines %d-%d" % (start, start + count - 1)


def not_checked(path, hunk):
    return "NOT CHECKED %s %s: time budget (%d s) ran out before this change was checked" % (path, where(hunk[2], hunk[3]), BUDGET)


def stop_on_term(signum, frame):
    raise SystemExit(128 + signum)  # unwinds main(): the test runs in flight are killed and the scratch worktrees removed


def main(argv):
    global DEADLINE
    if len(argv) != 3:
        print("usage: check-untested-hunks.py BASE HEAD", file=sys.stderr)
        return 2
    try:
        head = git("rev-parse", "--verify", "--quiet", argv[2] + "^{commit}").strip()
        merge_base = git("merge-base", argv[1], head).strip()
        changed = code_hunks(merge_base, head)
        found = declarations(merge_base, head)
    except RuntimeError as err:
        print("check-untested-hunks: cannot read %s..%s (%s); fetch the full history (fetch-depth: 0)" % (argv[1], argv[2], err), file=sys.stderr)
        return 2
    DEADLINE = time.monotonic() + BUDGET
    signal.signal(signal.SIGTERM, stop_on_term)
    by_path = {}
    for path, hunk in changed:
        by_path.setdefault(path, []).append(hunk)
    print("check-untested-hunks: %d changed code hunks in %d scripts, %s..%s" % (len(changed), len(by_path), merge_base[:8], head[:8]))
    lock = threading.Lock()
    jobs = []
    failed = 0
    with tempfile.TemporaryDirectory(prefix="untested-hunks-") as parent, ThreadPoolExecutor(WORKERS) as pool:
        try:
            for path, found_hunks in by_path.items():
                files = tests_for(head, path)
                if not files:
                    print("NOT CHECKED %s: no test file names it" % path)
                    continue
                try:
                    failed_file, ran = baseline(head, parent, lock, files)
                except Hang as hang:
                    print("NOT CHECKED %s: %s ran longer than %d s before anything was undone" % (path, hang, TIMEOUT))
                    continue
                except OutOfTime:
                    for hunk in found_hunks:
                        print(not_checked(path, hunk))
                    continue
                if failed_file or ran == 0:
                    print("NOT CHECKED %s: its tests %s before anything was undone (%s)" % (path, "fail in " + failed_file if failed_file else "all skip", ", ".join(files)))
                    continue
                for hunk in found_hunks:
                    jobs.append((path, hunk, files, pool.submit(survives, head, path, hunk, files, parent, lock)))
            for path, hunk, files, future in jobs:
                removed, added, start, count = hunk
                try:
                    survived = future.result()
                except OutOfTime:
                    print(not_checked(path, hunk))
                    continue
                if not survived:
                    continue
                reason = declared_reason(path, (removed, added), found, merge_base)
                if reason:
                    print("DECLARED untested change: %s %s: %s" % (path, where(start, count), reason))
                    continue
                failed += 1
                print(
                    "FAIL untested change: %s changes at %s and every test that names it still passes with that change undone.\n"
                    "    now:    %s\n    before: %s\n"
                    "  Add a test that fails when this change is undone (tests that name it: %s); a later commit may add it.\n"
                    "  If no test can see it (a refactor), add a line to a commit message of the pull request:\n"
                    "  %s: %s: <why no test can see it, in one line>"
                    % (path, where(start, count), (added[0].strip() if added else "(nothing: lines were removed)")[:100],
                       (removed[0].strip() if removed else "(nothing: lines were added)")[:100], ", ".join(files), TRAILER, path)
                )
        finally:
            # Stop (SIGTERM, a crash, or the end): every run still going is killed at its next check, POLL seconds at most; queued hunks are cancelled.
            DEADLINE = 0.0
            pool.shutdown(wait=True, cancel_futures=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
