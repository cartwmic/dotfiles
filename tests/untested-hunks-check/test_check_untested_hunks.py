"""Black-box tests for scripts/check-untested-hunks.py (the check for a fix whose changed lines no test depends on, dotfiles#641).

Each test builds a scratch git repo with a script and its unittest file, commits a change, and runs the real script over the pull request.
The budget and SIGTERM tests use fake slow tests (SLOW_SECONDS) that outlast the budget. A budget test's fast path gets a 10 s budget,
so it does not depend on how fast the machine is; the file runs in about half a minute.

    python3 -m unittest discover -s tests/untested-hunks-check
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check-untested-hunks.py"

CODE = "scripts/tool.py"
TEST = "tests/tool/test_tool.py"

# The #641 shape in small: `counts` is the loop rule (does the loop around `line` matter), `label` is the new case the fix is about.
TOOL = "def counts(start, end, line):\n    return start < line <= end\n\n\ndef label(kind):\n    return kind\n"
TOOL_FIXED = "def counts(start, end, line):\n    return start <= line <= end\n\n\ndef label(kind):\n    return 'exit: ' + kind\n"
HEADER = "import sys\nimport unittest\nfrom pathlib import Path\n\nsys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))\nimport tool\n\n\nclass ToolTest(unittest.TestCase):\n"
INSIDE = "    def test_a_line_inside_the_loop_counts(self):\n        self.assertTrue(tool.counts(1, 5, 3))\n\n"
LABEL = "    def test_label_is_the_kind(self):\n        self.assertEqual(tool.label('a'), 'a')\n\n"
NEW_LABEL = "    def test_label_says_exit(self):\n        self.assertEqual(tool.label('a'), 'exit: a')\n\n"
EDGE = "    def test_the_first_line_of_the_loop_counts(self):\n        self.assertTrue(tool.counts(1, 5, 1))\n\n"
TESTS = HEADER + INSIDE + LABEL
TESTS_FOR_LABEL = HEADER + INSIDE + NEW_LABEL  # the fix's test: the case its finding named, nothing about `counts`
TESTS_FOR_BOTH = HEADER + INSIDE + NEW_LABEL + EDGE

# The budget and SIGTERM tests. PACE is the switch: the fake slow test sleeps only while PACE is 'slow', so one hunk (the one that sets
# PACE back to 'slow' when undone) is slow and the others are quick. The hunks sit on lines 2 (label) and 5 (PACE), so the quick one
# is checked first, even with one worker. The budget covers the unchanged run and the quick hunk, which took 0.6-0.7 s with 8 suites
# looping on this machine and 1.1-2.0 s with 16 (whole test runs, so upper bounds). The budget is 10 s and the slow test sleeps 60 s,
# so the slow run is still in flight when the budget ends.
SLOW_SECONDS = 60
PACED_BASE = "def label(kind):\n    return kind\n\n\nPACE = 'slow'\n"
PACED_FIXED = "def label(kind):\n    return 'exit: ' + kind\n\n\nPACE = 'fast'\n"
PACE_ONLY_FIXED = "def label(kind):\n    return kind\n\n\nPACE = 'fast'\n"
PACE_FAST_BASE = "def label(kind):\n    return kind\n\n\nPACE = 'fast'\n"
PACE_FAST_LABEL = "def label(kind):\n    return 'exit: ' + kind\n\n\nPACE = 'fast'\n"
OWN_LOADS = HEADER + "    def test_loads(self):\n        self.assertTrue(tool)\n\n"
OWN_PACE_IS_FAST = HEADER + "    def test_pace_is_fast(self):\n        self.assertEqual(tool.PACE, 'fast')\n\n"
ELSEWHERE = "tests/elsewhere/test_slow.py"  # sorts before tests/tool/, so a run in name order reaches it first
SLOW_WHEN_SLOW = HEADER + (
    "    def test_slow_while_paced_slow(self):\n        import os, time\n        if tool.PACE == 'slow':\n"
    "            if os.environ.get('UNTESTED_TEST_MARK'):\n"
    "                Path(os.environ['UNTESTED_TEST_MARK']).write_text(str(os.getpid()))\n"
    f"            time.sleep({SLOW_SECONDS})\n\n"
)
ALWAYS_SLOW = HEADER + f"    def test_slow(self):\n        import time\n        time.sleep({SLOW_SECONDS})\n\n"
ALWAYS_SLOW_MARKED = HEADER + (
    "    def test_slow(self):\n        import os, time\n        Path(os.environ['UNTESTED_TEST_MARK']).write_text(str(os.getpid()))\n"
    f"        time.sleep({SLOW_SECONDS})\n\n"
)


class CheckUntestedHunks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        self.state = Path(self._tmp.name) / "state"  # the check's log goes here, not into the real ~/.local/state
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.invalid")
        self.git("config", "user.name", "t")

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, files, message="change"):
        for path, text in files.items():
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def run_check(self, base, head="HEAD", timeout="600", budget="1500"):
        done = subprocess.run([sys.executable, str(SCRIPT), base, head], cwd=self.repo, capture_output=True, text=True,
                              env=dict(os.environ, UNTESTED_HUNKS_TIMEOUT=timeout, UNTESTED_HUNKS_BUDGET=budget, XDG_STATE_HOME=str(self.state)))
        return done.returncode, done.stdout + done.stderr

    def sigterm_run(self, base):
        """Start the checker on base..HEAD, wait until a test run has written its pid (its test is slow), then send SIGTERM.
        Returns (exit code, pid of that test run, the scratch directory, output, seconds from SIGTERM to exit)."""
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        mark = Path(scratch.name) / "pid"
        env = dict(os.environ, UNTESTED_HUNKS_BUDGET="1500", XDG_STATE_HOME=str(self.state), TMPDIR=scratch.name, UNTESTED_TEST_MARK=str(mark))
        proc = subprocess.Popen([sys.executable, str(SCRIPT), base, "HEAD"], cwd=self.repo, env=env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        waited = time.monotonic()
        while not (mark.exists() and mark.read_text().strip()):
            if proc.poll() is not None or time.monotonic() - waited > 60:
                out, err = proc.communicate()
                self.fail("no test run started (exit %s): %s%s" % (proc.returncode, out, err))
            time.sleep(0.05)
        sent = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        out, err = proc.communicate(timeout=60)
        return proc.returncode, int(mark.read_text()), Path(scratch.name), out + err, time.monotonic() - sent

    def assert_stopped_clean(self, code, pid, scratch, out, seconds):
        self.assertEqual(code, 143, out)  # 128 + SIGTERM: the checker's own exit
        self.assertLess(seconds, SLOW_SECONDS - 2, out)  # the test run was stopped, not left to finish its sleep
        self.assertEqual(self.git("worktree", "list").count("\n"), 0, out)
        self.assertEqual([p.name for p in scratch.iterdir() if p.name.startswith("untested-hunks-")], [], out)
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)  # the test run is gone: killed and reaped

    def pr(self, second, message="fix the finding", first=None):
        """A base commit holding the script and its tests, then the commit under test; returns the base."""
        base = self.commit(first or {CODE: TOOL, TEST: TESTS}, "base")
        self.commit(second, message)
        return base

    def test_a_fix_whose_new_test_does_not_cover_the_rewritten_rule_fails_and_names_the_hunk(self):
        base = self.pr({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL})
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertIn(CODE + " changes at line 2", out)
        self.assertIn("now:    return start <= line <= end", out)
        self.assertIn("before: return start < line <= end", out)
        self.assertIn(TEST, out)
        self.assertIn("Untested-change: %s: <why no test can see it" % CODE, out)
        self.assertNotIn("at line 6", out)  # the label hunk has its own test

    def test_the_same_fix_with_a_test_for_the_rule_passes(self):
        base = self.pr({CODE: TOOL_FIXED, TEST: TESTS_FOR_BOTH})
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertNotIn("FAIL", out)

    def test_a_fix_that_touches_no_test_file_fails(self):
        base = self.pr({CODE: TOOL.replace("start < line", "start <= line")})
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertEqual(out.count("FAIL untested change"), 1, out)
        self.assertIn("at line 2", out)

    def test_a_declared_untested_change_passes_and_prints_the_reason(self):
        message = "fix the finding\n\nUntested-change: scripts/tool.py: the rule moved, it returns the same value for every input that exists\n\nCo-Authored-By: x"
        base = self.pr({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL}, message)
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("DECLARED untested change", out)
        self.assertIn("returns the same value for every input", out)

    def test_a_declaration_may_name_the_file_only_and_may_sit_in_any_commit_of_the_pull_request(self):
        base = self.pr({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL})
        self.commit({"README.md": "x\n"}, "docs\n\nUntested-change: tool.py: the rule moved, same value for every input")
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_declaration_for_another_script_does_not_excuse_this_one(self):
        base = self.pr({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL}, "fix\n\nUntested-change: scripts/other.py: unrelated")
        self.assertEqual(self.run_check(base)[0], 1)

    def test_a_later_commit_adding_the_test_clears_the_earlier_one(self):
        base = self.pr({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL})
        self.assertEqual(self.run_check(base)[0], 1)
        self.commit({TEST: TESTS_FOR_BOTH}, "add the missing test")
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_change_a_later_commit_takes_back_is_not_a_change(self):
        base = self.pr({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL})
        self.commit({CODE: TOOL, TEST: TESTS}, "revert")
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_main_merged_into_the_pull_request_is_not_blamed_for_the_scripts_main_changed(self):
        self.commit({CODE: TOOL, TEST: TESTS}, "base")
        self.git("checkout", "-q", "-b", "pr")
        self.commit({"pr.txt": "pr\n"}, "pr adds a file")
        self.git("checkout", "-q", "main")
        main_tip = self.commit({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL}, "main changes the script; its test is elsewhere")
        self.git("checkout", "-q", "pr")
        self.git("merge", "-q", "--no-edit", "main")
        code, out = self.run_check(main_tip)
        self.assertEqual(code, 0, out)

    def test_a_comment_docstring_or_layout_change_is_not_a_change(self):
        loud = TOOL.replace("    return start < line <= end", '    """Is the line inside the loop?"""\n    # the end is included\n    return (start < line  <=  end)')
        base = self.pr({CODE: loud})
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)

    def test_a_docs_only_commit_passes(self):
        base = self.pr({"README.md": "words\n", "docs/notes.md": "more words\n"})
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_commit_that_only_changes_tests_passes(self):
        base = self.pr({TEST: TESTS_FOR_BOTH})
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_deleted_script_is_not_blamed(self):
        base = self.pr({"scripts/other.py": "x = 1\n"})
        (self.repo / "scripts/other.py").unlink()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "drop it")
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_new_script_with_no_test_that_depends_on_it_fails(self):
        # The #908 shape: a script added in the range, a test file that names it but does not need it.
        base = self.commit({CODE: TOOL, TEST: TESTS}, "base")
        self.commit({"scripts/matrix.py": "def build(n):\n    return [n] * 3\n", TEST: TESTS + "    def test_names_it(self):\n        self.assertTrue('matrix.py')\n\n"}, "add matrix")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertIn("1 changed code hunks in 1 scripts", out)
        self.assertIn("scripts/matrix.py changes at lines 1-2", out)

    def test_a_new_script_a_test_depends_on_passes(self):
        base = self.commit({CODE: TOOL, TEST: TESTS}, "base")
        needs = TESTS + "    def test_build(self):\n        import matrix\n        self.assertEqual(matrix.build(1), [1, 1, 1])\n\n"
        self.commit({"scripts/matrix.py": "def build(n):\n    return [n] * 3\n", TEST: needs}, "add matrix")
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_new_script_in_a_commit_range_is_cleared_by_a_later_commit_that_tests_it(self):
        base = self.commit({CODE: TOOL, TEST: TESTS}, "base")
        self.commit({"scripts/matrix.py": "def build(n):\n    return [n] * 3\n", TEST: TESTS + "    def test_names_it(self):\n        self.assertTrue('matrix.py')\n\n"}, "add matrix")
        needs = TESTS + "    def test_build(self):\n        import matrix\n        self.assertEqual(matrix.build(1), [1, 1, 1])\n\n"
        self.commit({TEST: needs}, "test it")
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_declaration_excuses_a_new_script(self):
        base = self.commit({CODE: TOOL, TEST: TESTS}, "base")
        self.commit({"scripts/matrix.py": "def build(n):\n    return [n] * 3\n", TEST: TESTS + "    def test_names_it(self):\n        self.assertTrue('matrix.py')\n\n"},
                    "add matrix\n\nUntested-change: scripts/matrix.py: run by hand only")
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("DECLARED untested change: scripts/matrix.py", out)

    def test_a_new_script_no_test_names_fails_and_says_what_to_do(self):
        base = self.pr({"scripts/other.py": "x = 1\n"})
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL untested change: scripts/other.py is a new script and no test file names it", out)
        self.assertIn("Add a test that depends on it", out)
        self.assertIn("Untested-change: scripts/other.py: <why", out)

    def test_a_declaration_excuses_a_new_script_no_test_names(self):
        base = self.pr({"scripts/other.py": "x = 1\n"}, "add other\n\nUntested-change: scripts/other.py: run by hand only")
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("DECLARED untested change: scripts/other.py", out)

    def test_a_new_python_script_found_by_its_shebang_that_no_test_names_fails(self):
        base = self.pr({"bin/executable_tool2": "#!/usr/bin/env python3\nx = 1\n"})
        self.assertEqual(self.run_check(base)[0], 1)

    def test_a_range_that_adds_a_binary_file_passes_without_a_traceback(self):
        base = self.pr({"README.md": "x\n"})
        (self.repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
        (self.repo / "notes.txt").write_bytes(b"caf\xe9\n")  # latin-1: not UTF-8
        (self.repo / "scripts").mkdir(exist_ok=True)
        (self.repo / "scripts/latin.py").write_bytes(b"# caf\xe9\nx = 1\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add binaries")
        code, out = self.run_check(base)
        self.assertNotIn("Traceback", out)
        self.assertNotIn("UnicodeDecodeError", out)
        self.assertEqual(code, 1, out)  # only the new latin-1 script is judged, and no test names it
        self.assertIn("scripts/latin.py", out)
        self.assertNotIn("logo.png", out)

    def test_a_range_that_adds_only_a_binary_file_passes(self):
        base = self.pr({"README.md": "x\n"})
        (self.repo / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add image")
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("0 changed code hunks", out)

    def log_lines(self):
        return [json.loads(line) for line in (self.state / "check-untested-hunks" / "log.jsonl").read_text().splitlines()]

    def test_a_run_writes_one_json_line_with_its_outcome_and_counts(self):
        base = self.pr({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL})
        self.assertEqual(self.run_check(base)[0], 1)
        (line,) = self.log_lines()
        self.assertEqual((line["action"], line["outcome"], line["exit"]), ("check", "failed", 1))
        self.assertEqual((line["hunks"], line["scripts"], line["fail"], line["not_checked"], line["declared"]), (2, 1, 1, 0, 0))
        self.assertTrue(line["range"].startswith(base), line)
        self.assertRegex(line["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIsInstance(line["duration_ms"], int)

    def test_a_clean_run_logs_ok_and_a_refusal_logs_refused(self):
        base = self.pr({"README.md": "x\n"})
        self.assertEqual(self.run_check(base)[0], 0)
        self.assertEqual(self.run_check("0" * 40)[0], 2)
        ok, refused = self.log_lines()
        self.assertEqual(ok["outcome"], "ok")
        self.assertEqual((refused["outcome"], refused["exit"], refused["reason"]), ("refused", 2, "range does not resolve"))

    def test_a_declared_run_counts_the_declaration(self):
        base = self.pr({"scripts/other.py": "x = 1\n"}, "add other\n\nUntested-change: scripts/other.py: run by hand only")
        self.run_check(base)
        (line,) = self.log_lines()
        self.assertEqual((line["outcome"], line["declared"], line["fail"]), ("ok", 1, 0))

    def test_a_call_with_the_wrong_arguments_logs_refused(self):
        done = subprocess.run([sys.executable, str(SCRIPT)], cwd=self.repo, capture_output=True, text=True, env=dict(os.environ, XDG_STATE_HOME=str(self.state)))
        self.assertEqual(done.returncode, 2, done.stderr)
        (line,) = self.log_lines()
        self.assertEqual((line["outcome"], line["reason"]), ("refused", "usage"))

    def test_a_test_file_that_is_not_utf8_and_names_the_script_does_not_crash_the_check(self):
        latin = ("# -*- coding: latin-1 -*-\n" + TESTS_FOR_LABEL + "    # caf\xe9 tool.py\n").encode("latin-1")
        base = self.commit({CODE: TOOL}, "base")
        (self.repo / TEST).parent.mkdir(parents=True)
        (self.repo / TEST).write_bytes(latin)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "add the test")
        self.commit({CODE: TOOL_FIXED}, "fix")
        code, out = self.run_check(base)
        self.assertNotIn("Traceback", out)
        self.assertEqual(code, 1, out)

    def test_a_log_that_cannot_be_written_does_not_change_the_verdict(self):
        base = self.pr({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL})
        self.state.write_text("a file where the log folder should be\n")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertNotIn("Traceback", out)

    def test_a_script_no_test_names_is_not_checked_and_does_not_fail(self):
        base = self.pr({"scripts/lonely.py": "x = 2\n"}, first={CODE: TOOL, TEST: TESTS, "scripts/lonely.py": "x = 1\n"})
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("NOT CHECKED", out)
        self.assertIn("no test file names it", out)

    def test_tests_that_fail_before_anything_is_undone_are_not_checked(self):
        broken = TESTS + "    def test_red(self):\n        self.fail('red already')\n\n"
        base = self.pr({CODE: TOOL_FIXED, TEST: broken + NEW_LABEL}, first={CODE: TOOL, TEST: broken})
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("fail in %s (FAIL: test_" % TEST, out)
        self.assertIn("before anything was undone", out)
        self.assertEqual(self.log_lines()[-1]["not_checked"], 1)

    def test_tests_that_all_skip_are_not_checked(self):
        skipping = HEADER + "    @unittest.skip('needs a thing this runner lacks')\n    def test_it(self):\n        self.assertTrue(tool.counts(1, 5, 3))\n\n"
        base = self.pr({CODE: TOOL_FIXED}, first={CODE: TOOL, TEST: skipping})
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("all skip", out)
        self.assertEqual(self.log_lines()[-1]["not_checked"], 1)

    def test_a_deleted_guard_no_test_reads_fails_and_one_a_test_reads_passes(self):
        guarded = "def counts(start, end, line):\n    if end < start:\n        return 'empty'\n    return start < line <= end\n"
        unguarded = "def counts(start, end, line):\n    return start < line <= end\n"
        base = self.commit({CODE: guarded, TEST: HEADER + INSIDE}, "base")
        self.commit({CODE: unguarded}, "drop the guard")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertIn("nothing: lines were removed", out)
        reads = HEADER + INSIDE + "    def test_an_empty_loop_is_false(self):\n        self.assertEqual(tool.counts(5, 1, 3), False)\n\n"
        self.git("reset", "-q", "--hard", base)
        self.commit({CODE: unguarded, TEST: reads}, "drop the guard, say what is returned instead")
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_signature_and_its_caller_changed_together_are_seen_by_the_tests_that_call_it(self):
        old = "def total(a):\n    return a\n\n\ndef twice(a):\n    return total(a) * 2\n"
        new = "def total(a, extra=0):\n    return a + extra\n\n\ndef twice(a):\n    return total(a, 1) * 2\n"
        tests = HEADER + "    def test_twice(self):\n        self.assertEqual(tool.twice(2), 6)\n\n"
        base = self.commit({CODE: old, TEST: HEADER + "    def test_twice(self):\n        self.assertEqual(tool.twice(2), 4)\n\n"}, "base")
        self.commit({CODE: new, TEST: tests}, "extra")
        self.assertEqual(self.run_check(base)[0], 0)

    def source_named_test(self, script):
        """A unittest file that names the script only by its source path (no bare script word anywhere): loads it by that path."""
        return (
            "import importlib.util\nimport unittest\nfrom importlib.machinery import SourceFileLoader\nfrom pathlib import Path\n\n"
            "loader = SourceFileLoader('m', str(Path(__file__).resolve().parents[2] / '%s'))\n"
            "mod = importlib.util.module_from_spec(importlib.util.spec_from_loader('m', loader))\nloader.exec_module(mod)\n\n\n"
            "class ModTest(unittest.TestCase):\n    def test_a_line_inside_the_loop_counts(self):\n        self.assertTrue(mod.counts(1, 5, 3))\n" % script
        )

    def assert_found_by_source_path(self, script):
        base = self.commit({script: "#!/usr/bin/env python3\n" + TOOL, TEST: self.source_named_test(script)}, "base")
        self.commit({script: "#!/usr/bin/env python3\n" + TOOL.replace("start < line", "start <= line")}, "fix")
        code, out = self.run_check(base)
        self.assertNotIn("NOT CHECKED", out)
        self.assertEqual(code, 1, out)
        self.assertIn(script + " changes at line 3", out)
        self.assertIn(TEST, out)

    def test_a_script_with_a_chezmoi_name_is_found_by_the_name_a_test_gives_its_source_file(self):
        self.assert_found_by_source_path("dot_local/bin/executable_gadget")

    def test_a_template_source_name_is_found_too(self):
        self.assert_found_by_source_path("dot_local/bin/executable_gadget.tmpl")

    def test_a_py_source_name_with_underscores_is_found(self):
        self.assert_found_by_source_path("dot_local/user_scripts/executable_import_gadget_parts.py")

    def test_a_longer_name_that_only_contains_the_script_name_is_not_a_match(self):
        script = "scripts/gadget.py"
        longer = "import unittest\n\n\nclass T(unittest.TestCase):\n    def test_it(self):\n        self.assertTrue('gadget_helper and my-gadget and executable_gadgets')\n"
        base = self.commit({script: TOOL, TEST: longer}, "base")
        self.commit({script: TOOL.replace("start < line", "start <= line")}, "fix")
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("no test file names it", out)

    def test_a_shell_script_is_not_read(self):
        base = self.commit({"scripts/run.sh": "#!/bin/sh\necho a\n", TEST: TESTS}, "base")
        self.commit({"scripts/run.sh": "#!/bin/sh\necho b\n"}, "fix")
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_declaration_excuses_only_the_hunks_its_commit_holds(self):
        two = TOOL + "\n\ndef later(x):\n    return x\n"
        base = self.commit({CODE: two, TEST: TESTS + "    def test_later(self):\n        self.assertEqual(tool.later(1), 1)\n\n"}, "base")
        self.commit({CODE: two.replace("start < line", "start <= line")}, "refactor\n\nUntested-change: scripts/tool.py: the rule is the same for every input")
        self.assertEqual(self.run_check(base)[0], 0)
        self.commit({CODE: two.replace("start < line", "start <= line").replace("return x", "return x + 0")}, "a later hunk")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertIn("DECLARED untested change: scripts/tool.py line 2", out)
        self.assertIn("FAIL untested change: scripts/tool.py changes at line 10", out)

    def test_a_declaration_on_a_side_branch_merged_into_the_pull_request_is_not_read(self):
        base = self.commit({CODE: TOOL, TEST: TESTS}, "base")
        self.git("checkout", "-q", "-b", "side")
        self.commit({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL}, "side change\n\nUntested-change: scripts/tool.py: said on a branch the pull request merged")
        self.git("checkout", "-q", "main")
        self.git("checkout", "-q", "-b", "pr")
        self.commit({"pr.txt": "pr\n"}, "pr's own commit")
        self.git("merge", "-q", "--no-edit", "side")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertNotIn("DECLARED", out)

    def test_a_hang_before_anything_is_undone_is_not_checked(self):
        hangs = HEADER + "    def test_it(self):\n        import time\n        time.sleep(60)\n\n"
        base = self.pr({CODE: TOOL_FIXED}, first={CODE: TOOL, TEST: hangs})
        code, out = self.run_check(base, timeout="2")
        self.assertEqual(code, 0, out)
        self.assertIn("NOT CHECKED scripts/tool.py: ", out)
        self.assertIn("ran longer than 2 s before anything was undone", out)
        self.assertEqual(self.log_lines()[-1]["not_checked"], 1)

    def test_a_hang_that_undoing_a_hunk_brings_back_counts_as_caught(self):
        looping = "def wait(n):\n    while n:\n        pass\n    return n\n"
        tests = HEADER + "    def test_wait(self):\n        self.assertEqual(tool.wait(0), 0)\n\n"
        fixed = "def wait(n):\n    return n\n"
        base = self.commit({CODE: looping, TEST: tests}, "base")
        self.commit({CODE: fixed, TEST: tests + "    def test_wait_one(self):\n        self.assertEqual(tool.wait(1), 1)\n\n"}, "stop looping")
        code, out = self.run_check(base, timeout="3")
        self.assertEqual(code, 0, out)  # undone, wait(1) never returns: the new test notices (as a timeout)
        self.assertNotIn("NOT CHECKED", out)
        self.assertNotIn("FAIL", out)

    def test_the_budget_stops_a_test_run_in_flight_and_keeps_the_verdicts_it_reached(self):
        base = self.commit({CODE: PACED_BASE, TEST: OWN_LOADS, ELSEWHERE: SLOW_WHEN_SLOW}, "base")
        self.commit({CODE: PACED_FIXED}, "fix")
        started = time.monotonic()
        code, out = self.run_check(base, budget="10")
        self.assertLess(time.monotonic() - started, SLOW_SECONDS - 2, out)
        self.assertEqual(code, 1, out)  # the label hunk is a FAIL, printed before the budget ends
        self.assertIn("FAIL untested change: scripts/tool.py changes at line 2", out)
        self.assertIn("NOT CHECKED scripts/tool.py line 5: time budget", out)  # the PACE hunk was in its slow test when the budget ended
        self.assertEqual((self.log_lines()[-1]["fail"], self.log_lines()[-1]["not_checked"]), (1, 1))
        self.assertEqual(self.git("worktree", "list").count("\n"), 0, out)

    def test_a_budget_spent_before_the_unchanged_run_prints_not_checked_for_each_hunk(self):
        base = self.commit({CODE: TOOL, TEST: ALWAYS_SLOW}, "base")
        self.commit({CODE: TOOL_FIXED}, "fix")
        started = time.monotonic()
        code, out = self.run_check(base, budget="1")
        self.assertLess(time.monotonic() - started, SLOW_SECONDS - 2, out)
        self.assertEqual(code, 0, out)
        self.assertEqual(out.count("NOT CHECKED scripts/tool.py line"), 2, out)
        self.assertEqual(out.count("time budget"), 2, out)
        self.assertEqual(self.log_lines()[-1]["not_checked"], 2)
        self.assertNotIn("FAIL", out)

    def test_the_scripts_own_test_folder_runs_first_so_a_slow_file_elsewhere_is_not_reached(self):
        base = self.commit({CODE: PACED_BASE, TEST: OWN_LOADS, ELSEWHERE: SLOW_WHEN_SLOW}, "base")
        self.commit({CODE: PACE_ONLY_FIXED, TEST: OWN_PACE_IS_FAST}, "fix")
        started = time.monotonic()
        code, out = self.run_check(base, budget="10")
        self.assertLess(time.monotonic() - started, SLOW_SECONDS - 2, out)
        self.assertEqual(code, 0, out)  # the PACE hunk is caught by the own file, so the slow file never runs
        self.assertNotIn("NOT CHECKED", out)

    def test_each_hunk_runs_the_scripts_own_test_folder_before_the_other_files(self):
        base = self.commit({CODE: PACE_FAST_BASE, TEST: OWN_LOADS, ELSEWHERE: SLOW_WHEN_SLOW}, "base")
        self.commit({CODE: PACE_FAST_LABEL}, "fix")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)  # the label hunk survives both files: its FAIL lists them in the order they ran
        self.assertIn("tests that name it: %s, %s)" % (TEST, ELSEWHERE), out)

    def test_sigterm_during_a_hunk_run_kills_it_and_removes_the_scratch_worktrees(self):
        base = self.commit({CODE: PACED_BASE, TEST: OWN_LOADS, ELSEWHERE: SLOW_WHEN_SLOW}, "base")
        self.commit({CODE: PACED_FIXED}, "fix")
        self.assert_stopped_clean(*self.sigterm_run(base))
        self.assertEqual((self.log_lines()[-1]["outcome"], self.log_lines()[-1]["exit"]), ("error", 143))  # a stopped run still leaves its record

    def test_sigterm_during_the_unchanged_run_kills_it_and_removes_the_scratch_worktrees(self):
        base = self.commit({CODE: TOOL, TEST: ALWAYS_SLOW_MARKED}, "base")
        self.commit({CODE: TOOL_FIXED}, "fix")
        self.assert_stopped_clean(*self.sigterm_run(base))

    def test_a_base_that_does_not_resolve_fails_closed(self):
        self.commit({CODE: TOOL}, "base")
        code, out = self.run_check("0" * 40)
        self.assertEqual(code, 2, out)
        self.assertIn("fetch-depth: 0", out)

    def test_it_leaves_no_scratch_worktrees_behind(self):
        base = self.pr({CODE: TOOL_FIXED, TEST: TESTS_FOR_LABEL})
        self.run_check(base)
        self.assertEqual(self.git("worktree", "list").count("\n"), 0)


if __name__ == "__main__":
    unittest.main()
