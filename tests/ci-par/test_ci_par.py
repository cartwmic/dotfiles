"""scripts/ci-par.py: passing suites exit 0; a failing suite or per-test id exits 1 and prints its output; empty dirs fail."""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / "scripts" / "ci-par.py"

PASS = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
MIXED = textwrap.dedent("""\
    import unittest
    class T(unittest.TestCase):
        def test_ok(self):
            self.assertTrue(True)
        def test_fails_here(self):
            self.assertEqual(1, 2, "marker-from-fail")
    """)


class CiParTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "good").mkdir()
        (self.root / "good" / "test_good.py").write_text(PASS)
        (self.root / "many").mkdir()
        (self.root / "many" / "test_many.py").write_text(MIXED)
        (self.root / "empty").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_runner(self, *args):
        r = subprocess.run([sys.executable, str(RUNNER), *args], cwd=self.root, capture_output=True, text=True, timeout=120)
        return r.returncode, r.stdout

    def test_all_passing_exits_zero_and_reports_wall_time(self):
        rc, out = self.run_runner("--per-test", "good", "good")
        self.assertEqual(rc, 0, out)
        self.assertIn("0 failed", out)
        self.assertIn("wall", out)

    def test_failing_per_test_id_exits_one_and_prints_only_that_failure(self):
        rc, out = self.run_runner("--per-test", "many", "good")
        self.assertEqual(rc, 1, out)
        self.assertIn("FAIL test_many.T.test_fails_here", out)
        self.assertIn("marker-from-fail", out, "the failing test's output is printed")
        self.assertNotIn("FAIL test_many.T.test_ok", out)
        self.assertIn("1 failed", out)

    def test_failing_suite_exits_one_and_prints_its_output(self):
        rc, out = self.run_runner("many")
        self.assertEqual(rc, 1, out)
        self.assertIn("FAIL many", out)
        self.assertIn("marker-from-fail", out)

    def test_empty_per_test_dir_fails_closed(self):
        rc, out = self.run_runner("--per-test", "empty")
        self.assertEqual(rc, 1, out)
        self.assertIn("could not list tests in empty", out)


if __name__ == "__main__":
    unittest.main()
