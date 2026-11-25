"""Tests for `kgate report` (docs/kgate.md, "Report").

The pure functions run over a small fixture log (tests/kgate/fixtures/report-log.jsonl) with a fixed clock, so every
expected number here is worked out by hand from the fixture. The command also runs as a real process against a copy of
the fixture in a scratch XDG_STATE_HOME, and its output is checked from outside.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_kgate as T  # the module under test: test_kgate's copy of the rendered kgate script

K = T.K
# test_kgate deletes its rendered script when its own module ends, which can come before this module runs, so render a copy here.
_SCRIPT_DIR = tempfile.mkdtemp(prefix="kgate-report-script-")
SCRIPT = Path(_SCRIPT_DIR) / "kgate"
SCRIPT.write_text(T.render_script("personal"))
SCRIPT.chmod(0o755)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "report-log.jsonl"
NOW = datetime.datetime(2026, 11, 19, 12, 0, tzinfo=datetime.timezone.utc)
GIB = 2**30


def fixture_records():
    return [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]


def quick(cmd, repo, node, wall, day="18"):
    return {"id": "q-%s-%s" % (repo, cmd), "start": "2026-11-%sT10:00:00Z" % day, "cmd": cmd, "repo": repo, "node": node,
            "exit": 0, "ran": True, "pod_start_s": 10.0, "duration_s": wall + 10.0}


def row_for(rows, repo, cmd, node):
    hits = [r for r in rows if (r["repo"], r["cmd"], r["node"]) == (repo, cmd, node)]
    assert len(hits) == 1, [(r["repo"], r["cmd"], r["node"]) for r in rows]
    return hits[0]


class ReportRows(unittest.TestCase):
    def test_gate_row_numbers(self):
        rows = K.report_rows(fixture_records(), NOW, 7)
        r = row_for(rows, "gate-repo", "scripts/gate.sh", "g14")
        self.assertEqual(r["runs"], 3)  # fx-001, fx-002, fx-003; fx-008 is outside the window
        self.assertEqual(r["not_run"], 1)  # fx-003 was killed (143): it is not timed
        self.assertEqual(r["timed_runs"], 2)
        self.assertEqual(r["wall_median_s"], 1150.0)  # walls 1000 and 1300: duration minus pod start
        self.assertEqual(r["wall_p90_s"], 1300.0)
        self.assertEqual(r["total_wall_s"], 2300.0)
        self.assertEqual(r["cpu_median_s"], 1725.0)  # cpu_usec 1500 and 1950 CPU-s; the killed job's 9e12 is left out
        self.assertEqual(r["cores_used"], 1.5)  # 3450 CPU-s over 2300 run-s
        self.assertEqual(r["cores_asked_median"], 1)
        self.assertEqual(r["peak_max_bytes"], GIB)  # the killed job's 2 GiB peak is left out
        self.assertEqual(r["limit_max_bytes"], GIB)
        self.assertEqual(r["peak_pct_of_limit_max"], 100.0)
        self.assertTrue(r["slow"])

    def test_other_node_row_has_no_cpu_data(self):
        rows = K.report_rows(fixture_records(), NOW, 7)
        r = row_for(rows, "gate-repo", "scripts/gate.sh", "other")
        self.assertEqual((r["runs"], r["not_run"], r["timed_runs"]), (3, 1, 2))  # fx-007 was lost before it ran
        self.assertEqual(r["wall_median_s"], 1900.0)  # walls 1800 and 2000
        self.assertEqual(r["wall_p90_s"], 2000.0)
        self.assertEqual(r["total_wall_s"], 3800.0)
        self.assertIsNone(r["cpu_median_s"])  # these records predate cpu_usec
        self.assertIsNone(r["cores_used"])
        self.assertEqual(r["cores_asked_median"], 4)
        self.assertEqual(r["peak_max_bytes"], 3 * GIB)
        self.assertEqual(r["limit_max_bytes"], 4 * GIB)
        self.assertEqual(r["peak_pct_of_limit_max"], 75.0)  # 3 GiB of 4 GiB is the worst job
        self.assertTrue(r["slow"])

    def test_job_that_never_got_a_node_is_its_own_row(self):
        rows = K.report_rows(fixture_records(), NOW, 7)
        r = row_for(rows, "gate-repo", "scripts/gate.sh", "unplaced")
        self.assertEqual((r["runs"], r["not_run"], r["timed_runs"]), (1, 1, 0))
        self.assertIsNone(r["wall_median_s"])
        self.assertFalse(r["slow"])

    def test_slow_rows_come_first_then_most_total_wall(self):
        rows = K.report_rows(fixture_records(), NOW, 7)
        self.assertEqual([(r["node"], r["slow"]) for r in rows],
                         [("other", True), ("g14", True), ("unplaced", False)])

    def test_slow_rows_outrank_a_quick_row_with_more_total_wall(self):
        records = fixture_records() + [quick("npm test", "other-repo", "cartwmic-g14-wsl", 200.0) for _ in range(15)]  # 3000 s total
        rows = K.report_rows(records, NOW, 7)
        names = [(r["repo"], r["cmd"], r["node"]) for r in rows]
        self.assertGreater(names.index(("other-repo", "npm test", "g14")), names.index(("gate-repo", "scripts/gate.sh", "g14")))
        self.assertFalse(row_for(rows, "other-repo", "npm test", "g14")["slow"])

    def test_window_leaves_out_older_jobs(self):
        self.assertFalse(any(r["cmd"] == "old thing" for r in K.report_rows(fixture_records(), NOW, 7)))
        self.assertTrue(any(r["cmd"] == "old thing" for r in K.report_rows(fixture_records(), NOW, 36500)))

    def test_repo_filter(self):
        rows = K.report_rows(fixture_records(), NOW, 7, repo="gate-repo")
        self.assertTrue(rows and all(r["repo"] == "gate-repo" for r in rows))
        self.assertEqual(K.report_rows(fixture_records(), NOW, 7, repo="no-such-repo"), [])

    def test_unreadable_records_are_skipped_not_counted(self):
        junk = ["not a dict", 7, {"cmd": "no start time", "repo": "gate-repo", "node": None, "exit": 0}]
        rows = K.report_rows(fixture_records() + junk, NOW, 7)
        self.assertEqual(sum(r["runs"] for r in rows), 7)


class ReportHelpers(unittest.TestCase):
    def test_p90_is_nearest_rank(self):
        self.assertEqual(K.report_p90(list(range(1, 11))), 9)  # nine runs in ten finish within 9
        self.assertEqual(K.report_p90(list(range(1, 21))), 18)
        self.assertEqual(K.report_p90([1, 2]), 2)
        self.assertEqual(K.report_p90([7]), 7)
        self.assertIsNone(K.report_p90([]))

    def test_command_drops_leading_env_words_only(self):
        self.assertEqual(K.report_command("env KGATE_RUNS=30 KGATE_ARGS='a b' scripts/gate.sh"), "scripts/gate.sh")
        self.assertEqual(K.report_command("FOO=1 BAR=2 python3 -I x.py --flag=1"), "python3 -I x.py --flag=1")
        self.assertEqual(K.report_command("sh -c 'npm ci && npm test'"), "sh -c 'npm ci && npm test'")
        self.assertEqual(K.report_command("env"), "env")
        self.assertEqual(K.report_command("echo FOO=1"), "echo FOO=1")


class ReportCommand(unittest.TestCase):
    """The command as a real process, against a scratch state folder holding the log it is given."""

    def run_report(self, log_text=None, args=()):
        tmp = tempfile.mkdtemp(prefix="kgate-report-")
        self.addCleanup(shutil.rmtree, tmp, True)
        state = Path(tmp) / "state" / "kgate"
        state.mkdir(parents=True)
        if log_text is not None:
            (state / "log.jsonl").write_text(log_text)
        env = dict(os.environ, XDG_STATE_HOME=str(Path(tmp) / "state"), XDG_CACHE_HOME=tmp)
        return subprocess.run([sys.executable, str(SCRIPT), "report", *args], capture_output=True, text=True, env=env, timeout=120)

    def test_json_has_the_fixture_numbers(self):
        r = self.run_report(FIXTURE.read_text(), ["--days", "36500", "--json"])
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual(d["jobs"], 8)
        self.assertEqual(d["unreadable_lines"], 0)
        self.assertEqual(d["slow_wall_s"], 300)
        gate = row_for(d["rows"], "gate-repo", "scripts/gate.sh", "g14")
        self.assertEqual((gate["runs"], gate["not_run"], gate["wall_median_s"], gate["wall_p90_s"]), (3, 1, 1150.0, 1300.0))

    def test_text_table_and_legend(self):
        r = self.run_report(FIXTURE.read_text(), ["--days", "36500"])
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(lines[0].startswith("kgate report: 8 jobs"), lines[0])
        gate = [line for line in lines if "scripts/gate.sh" in line and "g14" in line]
        self.assertEqual(len(gate), 1)
        self.assertTrue(gate[0].startswith("SLOW"))
        self.assertIn("1150", gate[0])
        self.assertIn("not run: exit 69 or 75, or killed (137, 143).", r.stdout)
        self.assertIn("peak max GiB and limit GiB are each the row's highest value", r.stdout)

    def test_no_log_is_an_empty_report(self):
        r = self.run_report(None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 jobs", r.stdout)
        self.assertIn("no jobs in this window", r.stdout)

    def test_unreadable_line_is_counted_and_skipped(self):
        r = self.run_report(FIXTURE.read_text() + "this is not json\n", ["--days", "36500", "--json"])
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual((d["jobs"], d["unreadable_lines"]), (8, 1))

    def test_a_line_of_nul_bytes_is_counted_as_unreadable(self):
        r = self.run_report(FIXTURE.read_text() + "\0" * 2992 + "\n", ["--days", "36500", "--json"])
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        self.assertEqual((d["jobs"], d["unreadable_lines"]), (8, 1))

    def test_bad_arguments_exit_64(self):
        for args in (["--days", "0"], ["--bogus"]):
            r = self.run_report(FIXTURE.read_text(), args)
            self.assertEqual(r.returncode, 64, args)
            self.assertIn("usage: kgate", r.stderr)

    def test_text_shows_30_rows_unless_all(self):
        lines = [json.dumps(quick("make step%02d" % i, "many", "cartwmic-g14-wsl", 50.0 + i)) for i in range(35)]
        default = self.run_report("\n".join(lines) + "\n", ["--days", "36500"])
        self.assertEqual(default.returncode, 0, default.stderr)
        self.assertEqual(sum("make step" in line for line in default.stdout.splitlines()), 30)
        self.assertIn("5 more rows not shown; --all lists every row", default.stdout)
        every = self.run_report("\n".join(lines) + "\n", ["--days", "36500", "--all"])
        self.assertEqual(sum("make step" in line for line in every.stdout.splitlines()), 35)
        self.assertNotIn("more rows not shown", every.stdout)


def tearDownModule():
    shutil.rmtree(_SCRIPT_DIR, True)


if __name__ == "__main__":
    unittest.main()
