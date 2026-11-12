"""scripts/ci-par.py: passing suites exit 0; a failing suite or per-test id exits 1 and prints its output; empty dirs fail."""
import importlib.util
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



def load_runner():
    spec = importlib.util.spec_from_file_location("ci_par", RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AvailableCpusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cg = self.tmp.name
        self.mod = load_runner()
        self.base = min(self.mod.os.cpu_count() or 1, len(os.sched_getaffinity(0)))

    def tearDown(self):
        self.tmp.cleanup()

    def cpu_max(self, text):
        Path(self.cg, "cpu.max").write_text(text)

    def test_a_cgroup_v2_quota_below_the_cpu_count_caps_the_pool(self):
        self.cpu_max("100000 100000\n")
        self.assertEqual(self.mod.available_cpus(self.cg), 1)

    def test_a_fractional_quota_rounds_up(self):
        self.cpu_max("150000 100000\n")
        self.assertEqual(self.mod.available_cpus(self.cg), min(2, self.base))

    def test_a_quota_above_the_cpu_count_does_not_raise_it(self):
        self.cpu_max("%d 100000\n" % (self.base * 100000 * 4))
        self.assertEqual(self.mod.available_cpus(self.cg), self.base)

    def test_max_means_no_cap(self):
        self.cpu_max("max 100000\n")
        self.assertEqual(self.mod.available_cpus(self.cg), self.base)

    def test_cgroup_v1_quota(self):
        (Path(self.cg) / "cpu").mkdir()
        (Path(self.cg) / "cpu/cpu.cfs_quota_us").write_text("100000\n")
        (Path(self.cg) / "cpu/cpu.cfs_period_us").write_text("100000\n")
        self.assertEqual(self.mod.available_cpus(self.cg), 1)

    def test_no_cgroup_files_falls_back_to_the_cpu_count(self):
        self.assertEqual(self.mod.available_cpus(self.cg), self.base)

    def test_the_pool_uses_it(self):
        self.assertEqual(self.mod.SUITE_PROCESSES, self.mod.available_cpus())

if __name__ == "__main__":
    unittest.main()
