"""Black-box tests for scripts/check-untested-hunks.py (the check for a fix whose changed lines no test depends on, dotfiles#641).

Each test builds a scratch git repo with a script and its unittest file, commits a change, and runs the real script over the pull request.

    python3 -m unittest discover -s tests/untested-hunks-check
"""

import subprocess
import sys
import tempfile
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


class CheckUntestedHunks(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
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

    def run_check(self, base, head="HEAD"):
        done = subprocess.run([sys.executable, str(SCRIPT), base, head], cwd=self.repo, capture_output=True, text=True)
        return done.returncode, done.stdout + done.stderr

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

    def test_a_new_script_and_a_deleted_script_are_not_blamed(self):
        base = self.pr({"scripts/other.py": "x = 1\n"})
        self.assertEqual(self.run_check(base)[0], 0)
        (self.repo / "scripts/other.py").unlink()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "drop it")
        self.assertEqual(self.run_check(base)[0], 0)

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
        self.assertIn("fail before anything was undone", out)

    def test_tests_that_all_skip_are_not_checked(self):
        skipping = HEADER + "    @unittest.skip('needs a thing this runner lacks')\n    def test_it(self):\n        self.assertTrue(tool.counts(1, 5, 3))\n\n"
        base = self.pr({CODE: TOOL_FIXED}, first={CODE: TOOL, TEST: skipping})
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("all skip", out)

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

    def test_a_python_script_without_py_is_read_and_found_by_its_name_without_chezmoi_prefixes(self):
        script = "dot_local/bin/executable_tool"
        loads = (
            "import importlib.util\nimport unittest\nfrom importlib.machinery import SourceFileLoader\nfrom pathlib import Path\n\n"
            "loader = SourceFileLoader('tool', str(Path(__file__).resolve().parents[2] / '%s'))\n"
            "tool = importlib.util.module_from_spec(importlib.util.spec_from_loader('tool', loader))\nloader.exec_module(tool)\n\n\n"
            "class ToolTest(unittest.TestCase):\n" % script
        )
        base = self.commit({script: "#!/usr/bin/env python3\n" + TOOL, TEST: loads + INSIDE}, "base")
        self.commit({script: "#!/usr/bin/env python3\n" + TOOL.replace("start < line", "start <= line")}, "fix")
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertIn(script + " changes at line 3", out)
        self.assertIn(TEST, out)

    def test_a_shell_script_is_not_read(self):
        base = self.commit({"scripts/run.sh": "#!/bin/sh\necho a\n", TEST: TESTS}, "base")
        self.commit({"scripts/run.sh": "#!/bin/sh\necho b\n"}, "fix")
        self.assertEqual(self.run_check(base)[0], 0)

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
