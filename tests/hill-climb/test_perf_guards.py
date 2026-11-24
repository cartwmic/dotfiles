# Tests for the perf guards in climb.py: --perf, --errors and --work. They sit in their own file so the
# vendored upstream tests stay as vendored. A step that scores better but raises the error count or lowers
# the work count is undone. Each test drives climb.main() on a real throwaway git repo, like test_hill_climb.py.
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/hill-climb/scripts"
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("climb_perf", SCRIPTS / "executable_climb.py")
climb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(climb)

ERRORS = "errors: (\\d+)"
WORK = "processed: (\\d+)"
# The toy "program" is three files: time.txt is the score (lower is faster), items.txt is how many items it
# processed, errors.txt is how many failed. The check prints the counts, then the time as its last line.
CHECK = 'echo "processed: $(cat items.txt)"\necho "errors: $(cat errors.txt)"\ncat time.txt\n'


def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


class PerfGuardTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name) / "repo"
        self.repo.mkdir()
        environment = mock.patch.dict(os.environ, {"HILL_CLIMB_HOME": temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        previous = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, previous)
        git("init", "-q", "-b", "main")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        Path("time.txt").write_text("100\n")
        Path("items.txt").write_text("50\n")
        Path("errors.txt").write_text("0\n")
        Path("check.sh").write_text(CHECK)
        git("add", ".")
        git("commit", "-q", "-m", "start")

    def run_climb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = climb.main(list(args))
        return code, out.getvalue() + err.getvalue()

    def start(self, *extra):
        code, output = self.run_climb(
            "init", "speed", "--goal", "faster", "--check", "sh check.sh", "--direction", "min",
            "--lock", "check.sh", "--perf", "--errors", ERRORS, "--work", WORK, *extra,
        )
        self.assertEqual(code, 0, output)
        return output

    def edit(self, time, items=None, errors=None):
        Path("time.txt").write_text(f"{time}\n")
        if items is not None:
            Path("items.txt").write_text(f"{items}\n")
        if errors is not None:
            Path("errors.txt").write_text(f"{errors}\n")

    def card(self):
        return json.loads(Path(".hill-climb/speed/card.json").read_text())

    def log(self):
        return [json.loads(line) for line in Path(".hill-climb/speed/log.jsonl").read_text().splitlines()]

    def last_step(self):
        return self.log()[-1]

    def test_perf_climb_needs_both_counters(self):
        for extra in (["--errors", ERRORS], ["--work", WORK], []):
            code, output = self.run_climb(
                "init", "speed", "--goal", "faster", "--check", "sh check.sh", "--direction", "min", "--perf", *extra)
            self.assertEqual(code, 1)
            self.assertIn("--perf needs --errors and --work", output)
        self.assertFalse(Path(".hill-climb/speed/card.json").exists())
        refusals = self.log()
        self.assertEqual([row["kind"] for row in refusals], ["refused"] * 3)
        self.assertTrue(all(row["why"].startswith("--perf needs --errors and --work") for row in refusals))

    def test_baseline_counters_are_read_and_shown(self):
        output = self.start()
        self.assertIn("Counters errors 0, work 50", output)
        self.assertEqual(self.card()["counts"], {"errors": 0, "work": 50})
        baseline = json.loads(Path(".hill-climb/speed/log.jsonl").read_text().splitlines()[0])
        self.assertEqual((baseline["kind"], baseline["errors"], baseline["work"]), ("baseline", 0, 50))
        self.assertIn("Counters at best: errors 0, work 50", self.run_climb("status")[1])

    def test_a_counter_that_matches_nothing_stops_init(self):
        Path("check.sh").write_text('echo "errors: 0"\ncat time.txt\n')
        git("commit", "-qam", "no work count")
        code, output = self.run_climb(
            "init", "speed", "--goal", "faster", "--check", "sh check.sh", "--direction", "min",
            "--perf", "--errors", ERRORS, "--work", WORK)
        self.assertEqual(code, 1)
        self.assertIn("--work matched nothing", output)
        self.assertEqual(self.last_step()["kind"], "refused")
        self.assertIn("--work matched nothing in the output of: sh check.sh", self.last_step()["why"])

    def test_faster_by_skipping_work_is_undone(self):
        self.start()
        self.edit(time=40, items=20)
        code, output = self.run_climb("try", "skip the slow half")
        self.assertIn("undone", output)
        self.assertIn("work fell 50 -> 20", output)
        self.assertEqual(Path("time.txt").read_text(), "100\n")
        self.assertEqual(Path("items.txt").read_text(), "50\n")
        self.assertEqual(self.last_step()["why"], "guard failed: work fell 50 -> 20")
        self.assertEqual((self.last_step()["errors"], self.last_step()["work"]), (0, 20))
        self.assertEqual(self.card()["best"]["score"], 100)

    def test_faster_by_failing_more_is_undone(self):
        self.start()
        self.edit(time=40, errors=3)
        code, output = self.run_climb("try", "give up on slow requests")
        self.assertIn("undone", output)
        self.assertIn("errors rose 0 -> 3", output)
        self.assertEqual(Path("errors.txt").read_text(), "0\n")
        self.assertEqual(self.last_step()["why"], "guard failed: errors rose 0 -> 3")

    def test_a_real_speedup_is_kept_and_sets_the_new_bar(self):
        self.start()
        self.edit(time=60)
        code, output = self.run_climb("try", "cache the lookup")
        self.assertIn("kept", output)
        self.assertEqual(Path("time.txt").read_text(), "60\n")
        self.edit(time=30, errors=1)
        self.assertIn("errors rose", self.run_climb("try", "faster but one failure")[1])
        # Doing more work than the baseline is fine, and raises the bar for the next step.
        self.edit(time=30, items=80)
        self.assertIn("kept", self.run_climb("try", "process more in less time")[1])
        self.assertEqual(self.card()["counts"], {"errors": 0, "work": 80})
        self.edit(time=20, items=60)
        self.assertIn("work fell 80 -> 60", self.run_climb("try", "fall back below the best")[1])

    def test_a_check_that_crashes_before_printing_counts_is_not_zero_errors(self):
        Path("check.sh").write_text(
            'if [ -f crash ]; then cat time.txt; exit 0; fi\n' + CHECK)
        git("commit", "-qam", "check can crash")
        self.start()
        Path("crash").write_text("x\n")
        self.edit(time=10)
        code, output = self.run_climb("try", "crash early")
        self.assertIn("broke", output)
        self.assertIn("--errors matched nothing", output)
        self.assertFalse(Path("crash").exists())
        self.assertEqual(self.last_step()["result"], "broke")

    def test_every_check_must_print_the_counts(self):
        Path("other.sh").write_text('echo "processed: 5"\ncat time.txt\n')
        git("add", ".")
        git("commit", "-qm", "second check")
        code, output = self.run_climb(
            "init", "speed", "--goal", "faster", "--check", "sh check.sh", "--check", "sh other.sh", "--direction", "min",
            "--score", "^(\\d+)$", "--perf", "--errors", ERRORS, "--work", WORK)
        self.assertEqual(code, 1)
        self.assertIn("--errors matched nothing in the output of: sh other.sh", output)

    def test_counts_from_several_checks_add_up(self):
        Path("other.sh").write_text('echo "processed: 5"\necho "errors: 2"\ncat time.txt\n')
        git("add", ".")
        git("commit", "-qm", "second check")
        code, output = self.run_climb(
            "init", "speed", "--goal", "faster", "--check", "sh check.sh", "--check", "sh other.sh", "--direction", "min",
            "--score", "^(\\d+)$", "--perf", "--errors", ERRORS, "--work", WORK)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.card()["counts"], {"errors": 2, "work": 55})

    def test_worst_scored_run_counts_and_the_warm_up_does_not(self):
        # Runs 2, 3 and 4 are scored. Run 3, in the middle, is the worst: neither the first nor the last scored
        # run would find it. Run 1 is the warm-up, and its 7 errors must not count.
        Path("check.sh").write_text(
            "n=$(( $(cat .hill-climb/runs 2>/dev/null || echo 0) + 1 )); echo $n > .hill-climb/runs\n"
            'case $n in 1) e=7;; 3) e=1;; *) e=0;; esac\n'
            'case $n in 3) w=8;; *) w=10;; esac\n'
            'echo "processed: $w"\necho "errors: $e"\ncat time.txt\n')
        git("commit", "-qam", "flaky counts")
        self.start("--runs", "3")
        self.assertEqual(self.card()["counts"], {"errors": 1, "work": 8})

    def test_paired_step_is_judged_on_the_new_code_counts(self):
        self.start("--runs", "2", "--paired")
        self.edit(time=40, errors=2)
        code, output = self.run_climb("try", "faster with errors")
        self.assertIn("errors rose 0 -> 2", output)
        self.edit(time=40)
        self.assertIn("kept", self.run_climb("try", "faster")[1])

    def test_paired_leaves_out_the_counts_of_the_old_code(self):
        # The init check takes runs 1 to 3. From run 4 on, the old code (time 100) prints 4 errors; the new code never does.
        Path("check.sh").write_text(
            "n=$(( $(cat .hill-climb/runs 2>/dev/null || echo 0) + 1 )); echo $n > .hill-climb/runs\n"
            'if [ "$n" -ge 4 ] && [ "$(cat time.txt)" = 100 ]; then e=4; else e=0; fi\n'
            'echo "processed: $(cat items.txt)"\necho "errors: $e"\ncat time.txt\n')
        git("commit", "-qam", "old code errs late")
        self.start("--runs", "2", "--paired")
        self.assertEqual(self.card()["counts"]["errors"], 0)
        self.edit(time=40)
        code, output = self.run_climb("try", "faster, no errors of its own")
        self.assertIn("kept", output)
        self.assertEqual(self.last_step()["errors"], 0)

    def test_kit_reuse_prints_the_perf_flags(self):
        self.start()
        other = self.repo.parent / "other"
        other.mkdir()
        os.chdir(other)
        git("init", "-q", "-b", "main")
        code, output = self.run_climb("reuse", "speed")
        self.assertEqual(code, 0, output)
        self.assertIn("--perf", output)
        self.assertIn("--errors 'errors: (\\d+)'", output)
        self.assertIn("--work 'processed: (\\d+)'", output)

    def test_relock_measures_the_counters_again(self):
        self.start()
        Path("check.sh").write_text(CHECK.replace("cat items.txt", "echo 500"))
        code, output = self.run_climb("relock", "--why", "the old check counted the wrong thing")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.card()["counts"], {"errors": 0, "work": 500})
        row = self.last_step()
        self.assertEqual((row["kind"], row["errors"], row["work"]), ("relock", 0, 500))

    def test_without_counters_nothing_changes(self):
        code, output = self.run_climb(
            "init", "speed", "--goal", "faster", "--check", "sh check.sh", "--direction", "min", "--score", "^(\\d+)$")
        self.assertEqual(code, 0, output)
        self.assertNotIn("Counters", output)
        self.edit(time=40, items=1, errors=9)
        self.assertIn("kept", self.run_climb("try", "no counters named")[1])


if __name__ == "__main__":
    unittest.main()
