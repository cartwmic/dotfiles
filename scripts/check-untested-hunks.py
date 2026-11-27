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
depends on the hunk, and the check fails. A script the pull request adds is one hunk, the whole file: it is undone by emptying it, so a new
script that no test that names it depends on fails the check (dotfiles#908 added a 536-line script and the check said "0 changed code
hunks"). A new script that no test file names at all fails too, unless it is declared. A hunk that changes only comments, docstrings or
layout is skipped: the syntax tree is the same with or without it. It judges the pull request as it stands, so a later commit that adds
the test clears an earlier commit's hunk.

A hunk that no test can see on purpose (a refactor, a rename) is declared in the message of a commit of the pull request (first
parents only), in any paragraph, with the script's path (or its file name) before the reason:

    Untested-change: <path of the script>: <why no test can see it, in one line>

The declaration excuses the hunks that commit already holds, not later changes to the script: a later hunk needs its own line. A
declared hunk passes and is printed, so the CI log and the reviewer see each one.

A Python script is a .py file or a file whose first line is a python shebang. Tests are chosen by name: the test files (test_*.py,
*_test.py) that mention the script's file name as a whole word, with or without chezmoi's source prefixes and without ".tmpl" or ".py"
(`kgate` or `executable_kgate.tmpl`).
A changed script that no test mentions, or whose tests fail, all skip or hang (see TIMEOUT) before anything is undone, prints NOT CHECKED
and never fails; those are other mistakes. (A new script that no test mentions is the exception above.) Only Python is read, and only
unittest-style files (python3 -m unittest). Hunks that depend on each other (a changed signature and its callers) count as seen when
undoing one breaks the tests; the check names a hunk only when the tests pass without it.

Time: a test file's run is killed after TIMEOUT (600 s, UNTESTED_HUNKS_TIMEOUT); a hang after a hunk is undone counts as caught. The
whole run stops at BUDGET (1500 s, UNTESTED_HUNKS_BUDGET), under the CI step's 30 minutes. A test run still going then is killed, and
each hunk not yet checked prints NOT CHECKED with the reason "time budget". The run ends with its exit code as usual. SIGTERM kills the
test runs the same way and removes the scratch worktrees.

Exit 0 clean, 1 an undeclared hunk, 2 BASE or HEAD does not resolve (a shallow checkout: fetch the history first).

Record: every run appends one JSON line (ts in UTC, script, action, outcome ok, failed, refused or error, exit, duration_ms, range, the
counts hunks, scripts, fail, not_checked and declared, and the paths behind them: fail_paths, declared_paths, and not_checked_paths as
{path, reason}) to the file ${XDG_STATE_HOME:-~/.local/state}/check-untested-hunks/log.jsonl on the machine that runs the check. A CI runner
is thrown away, so there the record goes two more places: the CI step sets XDG_STATE_HOME and uploads that file as the workflow artifact
`check-untested-hunks-log` (.github/workflows/ci.yml), and the check appends the line, in a code fence, to the file named by
GITHUB_STEP_SUMMARY when that is set, so it shows on the run's page. A record that cannot be written never changes the verdict.
"""
import ast
import datetime
import json
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
STARTED = time.monotonic()
STATS = {"range": None, "hunks": 0, "scripts": 0, "fail": 0, "not_checked": 0, "declared": 0,
         "fail_paths": [], "not_checked_paths": [], "declared_paths": []}  # what the run's log record counts
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


def python_by_path_or_shebang(rev, path):
    """Is the file at `rev` a Python script: its name ends in .py, or its first line is a python shebang. A path that is not .py has its
    blob read as bytes to get that line; it is never decoded or parsed."""
    if path.endswith(".py"):
        return True
    done = subprocess.run(["git", "cat-file", "blob", "%s:%s" % (rev, path)], capture_output=True)
    return done.returncode == 0 and re.match(rb"#!.*\bpython", done.stdout.split(b"\n", 1)[0]) is not None


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
    """{path: lines} of the Python scripts that `new` adds to `old`. The patch reader skips added files (nothing existing was edited), so
    this reads them whole: a new script is one hunk, the whole file, and undoing it leaves an empty file. Any other added file (an image,
    a font) is not read."""
    out = {}
    for path in git("diff", "--name-only", "--no-renames", "--diff-filter=A", old, new).splitlines():
        try:
            if python_by_path_or_shebang(new, path):
                out[path] = git("show", "%s:%s" % (new, path)).splitlines()
        except RuntimeError:
            continue
    return out


def code_hunks(merge_base, head):
    """(hunks, new): the hunks of the pull request that change what a non-test Python script does, as (path, (removed, added, start,
    count)), and the paths of the scripts it adds. A script the pull request adds counts as one hunk, the whole file: a new script that no
    test depends on is as untested as a changed line."""
    patch = git("diff", "-U0", "--no-renames", "--no-color", merge_base, head)
    after = {}
    out = []
    new = set()
    for path, lines in added_files(merge_base, head).items():
        if is_test_file(path) or not lines:
            continue
        after[path] = "".join(line + "\n" for line in lines)
        if shape(after[path]) != shape(""):
            out.append((path, ([], lines, 1, len(lines))))
            new.add(path)
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
    return out, new


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


def say(line, counter=None, path=None, reason=None):
    """Print one verdict line and count it, with the script's path (and for NOT CHECKED the reason), for the run's record."""
    if counter:
        STATS[counter] += 1
        if counter == "not_checked":
            STATS["not_checked_paths"].append({"path": path, "reason": reason})
        elif path not in STATS[counter + "_paths"]:
            STATS[counter + "_paths"].append(path)
    print(line)


def stop_on_term(signum, frame):
    raise SystemExit(128 + signum)  # unwinds main(): the test runs in flight are killed and the scratch worktrees removed


def log_path():
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "check-untested-hunks", "log.jsonl")


def log_run(outcome, code, **extra):
    """Append one JSON line for this run (design principle 14). A log that cannot be written never changes the verdict."""
    record = {"ts": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "script": "check-untested-hunks.py",
              "action": "check", "outcome": outcome, "exit": code, "duration_ms": round((time.monotonic() - STARTED) * 1000),
              "range": STATS["range"], **{k: STATS[k] for k in ("hunks", "scripts", "fail", "not_checked", "declared",
                                                            "fail_paths", "not_checked_paths", "declared_paths")}, **extra}
    line = json.dumps(record, sort_keys=True)
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # the log is a record, not a dependency of the verdict
    if os.environ.get("GITHUB_STEP_SUMMARY"):  # the run's page on GitHub: the CI runner and its log file are thrown away
        try:
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
                f.write("check-untested-hunks record:\n\n```json\n" + line + "\n```\n")
        except Exception:
            pass


def report_untested(path, hunk, files, found, merge_base, new):
    """Print the verdict for a hunk no test depends on: DECLARED when a commit's message excuses it, else FAIL."""
    removed, added, start, count = hunk
    reason = declared_reason(path, (removed, added), found, merge_base)
    if reason:
        say("DECLARED untested change: %s %s: %s" % (path, where(start, count), reason), "declared", path)
        return
    declare = "  %s: %s: <why no test can see it, in one line>" % (TRAILER, path)
    if new and not files:
        say("FAIL untested change: %s is a new script and no test file names it.\n"
            "  Add a test that depends on it (a test_*.py file that names `%s` and fails when the script is emptied), or, if no test can\n"
            "  see it, add a line to a commit message of the pull request:\n%s" % (path, script_name(path), declare), "fail", path)
        return
    say("FAIL untested change: %s changes at %s and every test that names it still passes with that change undone.\n"
        "    now:    %s\n    before: %s\n"
        "  Add a test that fails when this change is undone (tests that name it: %s); a later commit may add it.\n"
        "  If no test can see it (a refactor), add a line to a commit message of the pull request:\n%s"
        % (path, where(start, count), (added[0].strip() if added else "(nothing: lines were removed)")[:100],
           (removed[0].strip() if removed else "(nothing: lines were added)")[:100], ", ".join(files), declare), "fail", path)


def main(argv):
    global DEADLINE
    if len(argv) != 3:
        print("usage: check-untested-hunks.py BASE HEAD", file=sys.stderr)
        log_run("refused", 2, reason="usage")
        return 2
    STATS["range"] = "%s..%s" % (argv[1], argv[2])
    try:
        head = git("rev-parse", "--verify", "--quiet", argv[2] + "^{commit}").strip()
        merge_base = git("merge-base", argv[1], head).strip()
        changed, new = code_hunks(merge_base, head)
        found = declarations(merge_base, head)
    except RuntimeError as err:
        print("check-untested-hunks: cannot read %s..%s (%s); fetch the full history (fetch-depth: 0)" % (argv[1], argv[2], err), file=sys.stderr)
        log_run("refused", 2, reason="range does not resolve")
        return 2
    DEADLINE = time.monotonic() + BUDGET
    signal.signal(signal.SIGTERM, stop_on_term)
    by_path = {}
    for path, hunk in changed:
        by_path.setdefault(path, []).append(hunk)
    STATS["hunks"], STATS["scripts"] = len(changed), len(by_path)
    print("check-untested-hunks: %d changed code hunks in %d scripts, %s..%s" % (len(changed), len(by_path), merge_base[:8], head[:8]))
    lock = threading.Lock()
    jobs = []
    with tempfile.TemporaryDirectory(prefix="untested-hunks-") as parent, ThreadPoolExecutor(WORKERS) as pool:
        try:
            for path, found_hunks in by_path.items():
                files = tests_for(head, path)
                if not files:
                    if path in new:
                        report_untested(path, found_hunks[0], files, found, merge_base, True)
                    else:
                        say("NOT CHECKED %s: no test file names it" % path, "not_checked", path, "no test file names it")
                    continue
                try:
                    failed_file, ran = baseline(head, parent, lock, files)
                except Hang as hang:
                    reason = "%s ran longer than %d s before anything was undone" % (hang, TIMEOUT)
                    say("NOT CHECKED %s: %s" % (path, reason), "not_checked", path, reason)
                    continue
                except OutOfTime:
                    for hunk in found_hunks:
                        say(not_checked(path, hunk), "not_checked", path, "time budget")
                    continue
                if failed_file or ran == 0:
                    state = "fail in " + failed_file if failed_file else "all skip"
                    reason = "its tests %s before anything was undone (%s)" % (state, ", ".join(files))
                    say("NOT CHECKED %s: %s" % (path, reason), "not_checked", path, reason)
                    continue
                for hunk in found_hunks:
                    jobs.append((path, hunk, files, pool.submit(survives, head, path, hunk, files, parent, lock)))
            for path, hunk, files, future in jobs:
                try:
                    survived = future.result()
                except OutOfTime:
                    say(not_checked(path, hunk), "not_checked", path, "time budget")
                    continue
                if survived:
                    report_untested(path, hunk, files, found, merge_base, False)
        finally:
            # Stop (SIGTERM, a crash, or the end): every run still going is killed at its next check, POLL seconds at most; queued hunks are cancelled.
            DEADLINE = 0.0
            pool.shutdown(wait=True, cancel_futures=True)
    code = 1 if STATS["fail"] else 0
    log_run("failed" if code else "ok", code)
    return code


def run(argv):
    """main(), with the run recorded however it ends: a SIGTERM or a crash writes an error record before it goes on."""
    try:
        return main(argv)
    except SystemExit as stop:
        log_run("error", stop.code, reason="stopped by signal" if isinstance(stop.code, int) and stop.code > 128 else "exit")
        raise
    except BaseException as err:
        log_run("error", 1, reason=type(err).__name__)
        raise


if __name__ == "__main__":
    sys.exit(run(sys.argv))
