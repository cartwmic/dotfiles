"""Black-box tests for scripts/check-test-edits.py (the check for a test edited so it passes, dotfiles#629 commit 236a1ce).

Each test builds a scratch git repo, commits a test and then an edit to it, and runs the real script over the range.

    python3 -m unittest discover -s tests/test-edit-check
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check-test-edits.py"

# The real pair from dotfiles#629: the test as added (a69986ed) and as weakened (236a1ce).
SEARCH = "- The hub image is built from `images/hub/Dockerfile`. I searched the test files for \"Dockerfile\""
TEST_AS_ADDED = "    def test_a_file_the_writer_left_out_is_not_a_test_file(self):\n        entry = '%s and found no match.'\n" % SEARCH
TEST_WEAKENED = "    def test_a_file_the_writer_left_out_is_not_a_test_file(self):\n        entry = '%s.'\n" % SEARCH
TEST = "tests/deriving-readable-docs/test_deriving_readable_docs.py"
CODE = "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts/check_citations.py"


class CheckTestEdits(unittest.TestCase):
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

    def pr(self, first, second, message="fix the check"):
        """A base commit, then the PR's first commit (adds the test) and its second (the edit under test)."""
        base = self.commit({"README": "x\n"}, "base")
        self.commit(first, "add the test")
        self.commit(second, message)
        return base

    def test_the_real_629_edit_fails_and_names_the_commit_the_file_and_the_fix(self):
        base = self.pr({TEST: TEST_AS_ADDED, CODE: "SCOPED = 1\n"}, {TEST: TEST_WEAKENED, CODE: "SCOPED = 2\n"})
        code, out = self.run_check(base)
        self.assertEqual(code, 1, out)
        self.assertIn(self.git("rev-parse", "--short=8", "HEAD"), out)
        self.assertIn(TEST, out)
        self.assertIn("Test-edit: <why the removed text was wrong", out)
        self.assertIn("Fix the code so the original test passes", out)

    def test_the_same_edit_with_a_trailer_passes_and_prints_the_reason(self):
        message = "fix the check\n\nTest-edit: the sentence is a search report, which the skill requires; the old text was not a claim"
        base = self.pr({TEST: TEST_AS_ADDED}, {TEST: TEST_WEAKENED}, message)
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("DECLARED test-edit", out)
        self.assertIn("the old text was not a claim", out)

    def test_it_walks_each_commit_not_the_whole_diff(self):
        base = self.pr({TEST: TEST_AS_ADDED}, {TEST: TEST_WEAKENED})
        # Against the PR's own first commit the test is new, so a whole-diff check sees only an addition.
        self.assertEqual(self.run_check(self.git("rev-parse", "HEAD~2"), "HEAD~1")[0], 0)
        self.assertEqual(self.run_check(base)[0], 1)

    def test_a_removed_assertion_fails(self):
        base = self.pr({TEST: "a\nself.assertEqual(x, 1)\nself.assertEqual(y, 2)\n"}, {TEST: "a\nself.assertEqual(x, 1)\n"})
        self.assertEqual(self.run_check(base)[0], 1)

    def test_a_deleted_test_file_fails(self):
        base = self.commit({"README": "x\n"}, "base")
        self.commit({TEST: TEST_AS_ADDED}, "add")
        (self.repo / TEST).unlink()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "drop it")
        self.assertEqual(self.run_check(base)[0], 1)

    def test_adding_to_a_test_passes(self):
        base = self.pr({TEST: TEST_AS_ADDED}, {TEST: TEST_AS_ADDED + "        self.assertEqual(1, 1)\n"})
        self.assertEqual(self.run_check(base)[0], 0)

    def test_changing_a_line_to_longer_different_text_passes(self):
        base = self.pr({TEST: "self.assertEqual(x, 1)\n"}, {TEST: "self.assertEqual(x, 10, 'ten')\n"})
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_dedent_alone_is_not_a_shortening(self):
        base = self.pr({TEST: "    x = 1\n"}, {TEST: "x = 1\n"})
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_removed_line_that_starts_with_dashes_is_read_as_text_not_a_file_header(self):
        base = self.pr({TEST: "-- a comment\nkeep\n"}, {TEST: "keep\n"})
        self.assertEqual(self.run_check(base)[0], 1)

    def test_removing_text_from_a_file_that_is_not_a_test_passes(self):
        base = self.pr({"scripts/tool.py": "a = 1  # note\n"}, {"scripts/tool.py": "a = 1\n"})
        self.assertEqual(self.run_check(base)[0], 0)

    def test_a_pytest_style_test_file_outside_tests_counts(self):
        base = self.pr({"pkg/test_thing.py": "a\nb\n"}, {"pkg/test_thing.py": "a\n"})
        self.assertEqual(self.run_check(base)[0], 1)

    def test_it_reports_the_commits_it_walked(self):
        base = self.pr({TEST: TEST_AS_ADDED}, {TEST: TEST_AS_ADDED + "# more\n"})
        self.assertIn("walked 2 commits", self.run_check(base)[1])

    def test_a_base_that_does_not_resolve_fails_closed(self):
        self.commit({"README": "x\n"}, "base")
        code, out = self.run_check("0" * 40)
        self.assertEqual(code, 2, out)
        self.assertIn("fetch-depth: 0", out)

    def test_a_test_edit_line_in_its_own_paragraph_above_co_authored_by_passes(self):
        message = (
            "fix the check\n\nTest-edit: the sentence is a search report; the old text was not a claim\n\n"
            "Co-Authored-By: Claude Haiku 5.5 <noreply@anthropic.com>"
        )
        base = self.pr({TEST: TEST_AS_ADDED}, {TEST: TEST_WEAKENED}, message)
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("the old text was not a claim", out)

    def test_a_main_merged_into_the_pr_with_a_test_cut_is_not_blamed(self):
        base = self.commit({TEST: TEST_AS_ADDED, "README": "x\n"}, "base")
        self.git("checkout", "-q", "-b", "pr")
        self.commit({"pr1.txt": "pr\n"}, "pr adds a file")
        self.commit({"pr2.txt": "pr\n"}, "pr adds another file")
        self.git("checkout", "-q", "main")
        self.commit({TEST: TEST_WEAKENED}, "main cuts the test without a trailer")
        self.git("checkout", "-q", "pr")
        self.git("merge", "-q", "--no-edit", "main")
        code, out = self.run_check(base)
        self.assertEqual(code, 0, out)
        self.assertIn("walked 2 commits", out)


if __name__ == "__main__":
    unittest.main()
