"""Tests for scripts/commit_range.py, the git, commit-walk and hunk reading that check-test-edits.py and check-untested-hunks.py share.

    python3 -m unittest discover -s tests/untested-hunks-check
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import commit_range  # noqa: E402


class IsTestFile(unittest.TestCase):
    def test_test_files_are_found_by_folder_and_by_name(self):
        for path in ("tests/x/helper.py", "a/fixtures/data.json", "test_a.py", "pkg/b_test.py", "ui/a.test.ts", "ui/a.spec.js", "e2e/a.journey.ts"):
            self.assertTrue(commit_range.is_test_file(path), path)

    def test_scripts_are_not(self):
        for path in ("scripts/tool.py", "dot_local/bin/executable_kgate.tmpl", "docs/tests.md", "contest.py"):
            self.assertFalse(commit_range.is_test_file(path), path)


class Hunks(unittest.TestCase):
    PATCH = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        "@@ -2 +2 @@\n-old\n+new\n"
        "@@ -5,2 +5,0 @@\n-gone1\n-gone2\n"
        "@@ -9,0 +8,2 @@\n+add1\n+add2\n"
        "diff --git a/b.py b/b.py\nnew file mode 100644\n--- /dev/null\n+++ b/b.py\n@@ -0,0 +1 @@\n+fresh\n"
    ).replace("\\\n", "\n")

    def test_it_reads_each_hunk_with_its_place_after_the_change(self):
        found = list(commit_range.hunks(self.PATCH))
        self.assertEqual(found[0], ("a.py", ["old"], ["new"], 2, 1))
        self.assertEqual(found[1], ("a.py", ["gone1", "gone2"], [], 5, 0))  # a deletion: the line above it
        self.assertEqual(found[2], ("a.py", [], ["add1", "add2"], 8, 2))

    def test_a_new_file_has_no_path_so_nothing_existing_is_read(self):
        self.assertEqual(list(commit_range.hunks(self.PATCH))[3][0], None)

    def test_a_removed_line_that_starts_with_dashes_is_text_not_a_header(self):
        patch = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +0,0 @@\n--- not a header\n"
        self.assertEqual(list(commit_range.hunks(patch)), [("a.py", ["-- not a header"], [], 0, 0)])


class History(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@example.invalid"), ("config", "user.name", "t")):
            self.git(*args)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.repo)  # commit_range runs git in the current directory, as the checks do

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, name, message):
        (self.repo / name).write_text(name)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def test_walk_lists_the_commits_oldest_first_and_skips_a_merged_main(self):
        base = self.commit("base", "base")
        self.git("checkout", "-q", "-b", "pr")
        first = self.commit("one", "one")
        self.git("checkout", "-q", "main")
        self.commit("main-side", "main")
        self.git("checkout", "-q", "pr")
        self.git("merge", "-q", "--no-edit", "main")
        second = self.commit("two", "two")
        _, head, commits = commit_range.walk(base, "pr")
        self.assertEqual(head, second)
        self.assertEqual(commits, [first, second])

    def test_walk_raises_for_a_rev_that_does_not_resolve(self):
        self.commit("base", "base")
        with self.assertRaises(RuntimeError):
            commit_range.walk("0" * 40, "HEAD")

    def test_declared_reads_a_line_in_any_paragraph_and_ignores_empty_reasons(self):
        head = self.commit("a", "subject\n\nbody\n\nTest-edit: the old text was wrong\n\nTest-edit:\n\nCo-Authored-By: x")
        self.assertEqual(commit_range.declared(head, "Test-edit"), ["the old text was wrong"])
        self.assertEqual(commit_range.declared(head, "Untested-change"), [])


if __name__ == "__main__":
    unittest.main()
