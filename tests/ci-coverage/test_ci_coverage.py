"""Black-box tests for scripts/check-ci-coverage.py: every test file is run by CI or named in scripts/ci-not-run.txt.

The first test runs the script on this repository: it is the guard. The rest build a small scratch repository (a runner, a workflow, a list
and some test files) and run the real script over it, so each rule fails when its code is broken.

    python3 -m unittest discover -s tests/ci-coverage
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check-ci-coverage.py"

CI_LINUX = """\
node --test tests/js/run.test.mjs
node --experimental-strip-types --test ext/a/index.test.ts ext/a/other.test.ts
node --test \\
  ext/c/first.test.mjs \\
  ext/c/second.test.mjs
python3 scripts/ci-par.py \\
  --per-test tests/slow \\
  tests/alpha \\
  'tests/beta:check_*.py' \\
  tests/pkg || status=1
python3 -m unittest discover -s tests/tail -v
python3 scripts/ci-par.py --shards 4 tests/sharded --hold-file tests/sharded/held.txt || status=1
"""
WORKFLOW = """\
      - name: macOS suite
        run: python3 -m unittest discover -s tests/mac -v
      - name: macOS suite with a pattern
        run: python3 -m unittest discover -s tests/mac2 -p 'mac_*.py' -v
"""
RUN = [
    "tests/js/run.test.mjs", "ext/a/index.test.ts", "ext/a/other.test.ts", "ext/c/first.test.mjs", "ext/c/second.test.mjs", "tests/slow/test_x.py", "tests/alpha/test_a.py",
    "tests/pkg/sub/test_deep.py", "tests/tail/test_t.py", "tests/mac/test_m.py", "tests/sharded/test_s.py",
]


class CheckCiCoverage(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.write("scripts/ci-linux.sh", CI_LINUX)
        self.write(".github/workflows/ci.yml", WORKFLOW)
        self.write("scripts/ci-not-run.txt", "# test files CI cannot run\n")
        for path in RUN:
            self.write(path, "")
        self.write("tests/beta/check_b.py", "")  # run through the pattern
        self.write("tests/pkg/__init__.py", "")
        self.write("tests/pkg/sub/__init__.py", "")
        self.write("tests/mac2/mac_one.py", "")  # not a test file by name: ignored
        self.write("tests/alpha/helper.py", "")  # not a test file by name: ignored

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def run_script(self, root=None):
        r = subprocess.run([sys.executable, str(SCRIPT), str(root or self.root)], capture_output=True, text=True)
        return r.returncode, r.stdout + r.stderr

    def test_every_test_file_of_this_repository_is_run_or_named(self):
        code, out = self.run_script(ROOT)
        self.assertEqual(code, 0, out)

    def test_a_scratch_repository_where_everything_is_run_passes(self):
        code, out = self.run_script()
        self.assertEqual(code, 0, out)

    def test_each_kind_of_runner_line_counts_as_running_its_files(self):
        # Removing a file from the scratch repository would hide a runner line the script failed to read; so add a file under each and expect no complaint.
        for path in ("tests/alpha/test_more.py", "tests/slow/test_more.py", "tests/tail/test_more.py", "tests/mac/test_more.py", "tests/sharded/test_more.py", "tests/pkg/test_top.py"):
            self.write(path, "")
        code, out = self.run_script()
        self.assertEqual(code, 0, out)

    def test_a_python_test_file_in_a_folder_the_runner_does_not_name_fails_and_names_the_file(self):
        self.write("tests/orphan/test_o.py", "")
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/orphan/test_o.py", out)
        self.assertIn("scripts/ci-linux.sh", out)
        self.assertIn("scripts/ci-not-run.txt", out)

    def test_a_node_test_file_the_runner_does_not_name_fails(self):
        self.write("ext/b/index.test.ts", "")
        self.write("ext/b/util.test.mjs", "")
        self.write("ext/b/old.spec.js", "")
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        for name in ("ext/b/index.test.ts", "ext/b/util.test.mjs", "ext/b/old.spec.js"):
            self.assertIn(name, out)

    def test_a_python_file_the_suite_pattern_does_not_match_fails(self):
        self.write("tests/beta/test_not_matched.py", "")  # the beta suite runs check_*.py only
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/beta/test_not_matched.py", out)

    def test_a_test_file_in_a_subfolder_that_is_not_a_package_is_not_run_by_discover(self):
        self.write("tests/alpha/nested/test_n.py", "")  # no __init__.py: unittest discover does not enter it
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/alpha/nested/test_n.py", out)

    def test_a_file_named_with_a_reason_in_the_list_passes(self):
        self.write("tests/orphan/test_o.py", "")
        self.write("scripts/ci-not-run.txt", "tests/orphan/test_o.py: needs a desktop session, which the runner lacks\n")
        code, out = self.run_script()
        self.assertEqual(code, 0, out)

    def test_a_folder_in_the_list_covers_every_test_file_under_it(self):
        self.write("tests/orphan/test_o.py", "")
        self.write("tests/orphan/deep/test_d.py", "")
        self.write("scripts/ci-not-run.txt", "tests/orphan: drives a real phone\n")
        code, out = self.run_script()
        self.assertEqual(code, 0, out)

    def test_an_entry_with_no_reason_fails(self):
        self.write("tests/orphan/test_o.py", "")
        self.write("scripts/ci-not-run.txt", "tests/orphan/test_o.py\n")
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("no reason", out)
        self.assertIn("tests/orphan/test_o.py", out)  # and the file is still unlisted

    def test_an_entry_for_a_path_that_does_not_exist_fails(self):
        self.write("scripts/ci-not-run.txt", "tests/gone/test_g.py: needs a desktop\n")
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/gone/test_g.py", out)
        self.assertIn("does not exist", out)

    def test_an_entry_for_a_file_that_is_run_fails(self):
        self.write("scripts/ci-not-run.txt", "tests/alpha/test_a.py: left out by mistake\n")
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("is run by CI", out)

    def test_an_entry_for_a_folder_with_no_test_file_fails(self):
        self.write("docs/readme.md", "")
        self.write("scripts/ci-not-run.txt", "docs: nothing to run here\n")
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("holds no test file", out)

    def test_a_missing_list_fails_and_says_where_it_goes(self):
        (self.root / "scripts/ci-not-run.txt").unlink()
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("scripts/ci-not-run.txt is missing", out)

    def test_a_runner_the_script_cannot_read_fails_with_exit_2(self):
        self.write("scripts/ci-linux.sh", "echo nothing runs here\n")
        code, out = self.run_script()
        self.assertEqual(code, 2, out)
        self.assertIn("cannot read the runner", out)

    def test_a_node_line_that_is_commented_out_runs_nothing(self):
        self.write("scripts/ci-linux.sh", CI_LINUX.replace("node --test tests/js/run.test.mjs", "# node --test tests/js/run.test.mjs"))
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/js/run.test.mjs", out)

    def test_a_file_on_a_continued_node_line_is_not_run_when_that_line_is_commented_out(self):
        self.write("scripts/ci-linux.sh", CI_LINUX.replace("  ext/c/second.test.mjs\n", "  # ext/c/second.test.mjs\n"))
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("ext/c/second.test.mjs", out)
        self.assertNotIn("ext/c/first.test.mjs", out)

    def test_a_suite_line_that_is_commented_out_runs_nothing(self):
        self.write("scripts/ci-linux.sh", CI_LINUX.replace("  tests/alpha \\\n", "  # tests/alpha \\\n"))
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/alpha/test_a.py", out)

    def test_a_workflow_step_that_is_commented_out_runs_nothing(self):
        self.write(".github/workflows/ci.yml", WORKFLOW.replace("        run: python3 -m unittest discover -s tests/mac -v", "        # run: python3 -m unittest discover -s tests/mac -v"))
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/mac/test_m.py", out)

    def test_a_trailing_comment_does_not_hide_the_command_before_it(self):
        self.write("scripts/ci-linux.sh", CI_LINUX.replace("tests/tail -v\n", "tests/tail -v  # the tail suite\n"))
        code, out = self.run_script()
        self.assertEqual(code, 0, out)

    def test_a_test_file_whose_name_is_not_an_importable_module_is_not_run_by_discover(self):
        self.write("tests/alpha/test_with-hyphen.py", "")  # discover matches the pattern, then skips the name: it loads no tests from it
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/alpha/test_with-hyphen.py", out)

    def test_a_hyphenated_test_file_the_default_pattern_matches_is_found_and_not_run_by_discover(self):
        self.write("tests/alpha/test-x.py", "")  # test*.py matches it, discover skips it as unimportable: a test file CI never runs
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("tests/alpha/test-x.py", out)

    def test_it_prints_the_counts_it_found(self):
        self.write("tests/orphan/test_o.py", "")
        self.write("scripts/ci-not-run.txt", "tests/orphan/test_o.py: needs a desktop\n")
        self.write("tests/orphan2/test_p.py", "")
        code, out = self.run_script()
        self.assertEqual(code, 1, out)
        self.assertIn("13 test files: 11 run by CI, 1 named in scripts/ci-not-run.txt, 1 neither", out)  # the 11 files in RUN, plus the listed one and the orphan
        self.assertIn("a test file is test_*.py, test-*.py, *_test.py, *.test.{ts,tsx,mjs,js,cjs} or *.spec.{ts,tsx,mjs,js,cjs}", out)

    def test_git_and_node_modules_are_not_searched(self):
        self.write(".git/hooks/test_x.py", "")
        self.write("node_modules/pkg/index.test.js", "")
        code, out = self.run_script()
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
