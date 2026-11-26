"""Every script of distilling-requirements leaves one JSON line per run in the skill's log (runlog.py, design principle 14): the same log the sibling skills keep.
Each test runs the script as the skill does (python3 -I, on files) with the state folder pointed at a scratch folder, then reads the line back.
Run: python3 -m unittest discover -s tests/distilling-requirements"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_requirements_v2 as T


class RunLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = Path(self.tmp, "state")
        self.env = dict(os.environ, XDG_STATE_HOME=str(self.state))
        self.repo = Path(self.tmp, "repo")
        self.repo.mkdir()
        T.git(self.repo, "init", "-q", "-b", "main")
        self.sha = T.commit(self.repo, {"a.py": "x\n"}, "fix: a crash")

    def lines(self):
        path = self.state / "distilling-requirements" / "log.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def run_one(self, name, *args):
        T.script(name, *args, env=self.env)
        got = self.lines()
        self.assertEqual(len(got), 1, got)
        self.assertEqual(got[0]["script"], name)
        self.assertRegex(got[0]["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn("duration_s", got[0])
        return got[0]

    def register(self, **kw):
        path = Path(self.tmp, "R.md")
        path.write_text(T.doc([T.row(1, kind="inferred", evidence=kw.get("evidence", "a.py:1"))], {"commit": self.sha, "snapshot": "2026-11-26 at " + self.sha, "history": self.sha}).replace(T.LINE, T.LINE.replace("aaaaaaa", self.sha[:7])))
        return path

    def test_history_signals_logs_its_counts_and_a_refusal(self):
        rec = self.run_one("history_signals.py", self.repo, "--no-gh")
        self.assertEqual((rec["action"], rec["outcome"], rec["exit"], rec["signal_commits"]), ("history-signals", "ok", 0, 1))
        shutil.rmtree(self.state)
        rec = self.run_one("history_signals.py", self.repo, "--rev", "nope")
        self.assertEqual((rec["outcome"], rec["exit"]), ("refused", 2))

    def test_history_signals_logs_a_folder_with_no_git(self):
        rec = self.run_one("history_signals.py", self.tmp)
        self.assertEqual((rec["outcome"], rec["no_git"]), ("ok", True))

    def test_check_history_refs_logs_ok_and_failed(self):
        rec = self.run_one("check_history_refs.py", self.register(evidence="commit:" + self.sha[:9]), self.repo)
        self.assertEqual((rec["action"], rec["outcome"], rec["resolved_rows"], rec["unresolved"]), ("check-history-refs", "ok", 1, 0))
        shutil.rmtree(self.state)
        rec = self.run_one("check_history_refs.py", self.register(evidence="commit:deadbeef0"), self.repo)
        self.assertEqual((rec["outcome"], rec["exit"], rec["unresolved"]), ("failed", 1, 1))

    def test_check_shape_logs_ok_failed_and_a_refusal(self):
        rec = self.run_one("check_shape.py", self.register())
        self.assertEqual((rec["action"], rec["outcome"], rec["problems"], rec["rows"]), ("check-shape", "ok", 0, 1))
        shutil.rmtree(self.state)
        Path(self.tmp, "bad.md").write_text(self.register().read_text().replace("a.py:1", "docs/snapshots/x/R.md:1"))
        rec = self.run_one("check_shape.py", Path(self.tmp, "bad.md"))
        self.assertEqual((rec["outcome"], rec["exit"], rec["problems"]), ("failed", 1, 1))
        shutil.rmtree(self.state)
        Path(self.tmp, "old.md").write_text(self.register().read_text().replace("requirements/2", "requirements/1"))
        rec = self.run_one("check_shape.py", Path(self.tmp, "old.md"))
        self.assertEqual((rec["outcome"], rec["reason"]), ("refused", "old shape requirements/1"))

    def test_surface_coverage_logs_its_counts_and_a_refusal(self):
        rec = self.run_one("surface_coverage.py", self.register(), self.repo)
        self.assertEqual((rec["action"], rec["outcome"], rec["exit"]), ("surface-coverage", "ok", 0))
        shutil.rmtree(self.state)
        rec = self.run_one("surface_coverage.py", self.register())
        self.assertEqual((rec["outcome"], rec["reason"]), ("refused", "usage"))

    def test_check_truth_logs_prepare(self):
        rec = self.run_one("check_truth.py", "prepare", self.register(), "--out", Path(self.tmp, "out"))
        self.assertEqual((rec["action"], rec["step"], rec["outcome"]), ("check-truth", "prepare", "ok"))

    def test_a_log_that_cannot_be_written_never_changes_the_exit_code(self):
        Path(self.tmp, "blocked").write_text("a file, not a folder")
        env = dict(self.env, XDG_STATE_HOME=str(Path(self.tmp, "blocked")))
        code, out, _ = T.script("history_signals.py", self.repo, "--no-gh", env=env)
        self.assertEqual(code, 0)
        self.assertIn("Signal commits", out)

    def test_the_skill_keeps_the_same_helper_as_its_siblings(self):
        skills = T.SKILLS
        copies = {p.read_text() for p in skills.glob("*/scripts/runlog.py")}
        self.assertEqual(len(copies), 1)
        self.assertTrue((skills / "distilling-requirements/scripts/runlog.py").exists())


if __name__ == "__main__":
    unittest.main()
