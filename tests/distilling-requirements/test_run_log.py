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
    @classmethod
    def setUpClass(cls):
        cls.template, cls.sha = T.build_fixture_repo(lambda repo: T.commit(repo, {"a.py": "x\n"}, "fix: a crash"))

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = Path(self.tmp, "state")
        self.env = dict(os.environ, XDG_STATE_HOME=str(self.state))
        self.repo = T.copy_fixture_repo(self.template, self.tmp)

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
        shutil.rmtree(self.state)
        Path(self.tmp, "nofence.md").write_text("# no header fence\n")
        rec = self.run_one("check_shape.py", Path(self.tmp, "nofence.md"))
        self.assertEqual((rec["outcome"], rec["exit"], rec["reason"]), ("refused", 1, "no header fence"))
        shutil.rmtree(self.state)
        rec = self.run_one("check_shape.py")
        self.assertEqual((rec["outcome"], rec["exit"], rec["reason"]), ("refused", 2, "usage"))

    def test_surface_coverage_logs_its_counts_and_a_refusal(self):
        rec = self.run_one("surface_coverage.py", self.register(), self.repo)
        self.assertEqual((rec["action"], rec["outcome"], rec["exit"]), ("surface-coverage", "ok", 0))
        shutil.rmtree(self.state)
        rec = self.run_one("surface_coverage.py", self.register())
        self.assertEqual((rec["outcome"], rec["reason"]), ("refused", "usage"))

    def test_surface_coverage_logs_how_many_surfaces_it_found_and_left_uncited(self):
        rec = self.run_one("surface_coverage.py", self.register(), self.repo)
        self.assertEqual((rec["surfaces"], rec["uncovered"], rec["rows"], rec["scoped"]), (0, 0, 1, False))
        shutil.rmtree(self.state)
        T.commit(self.repo, {"cli.py": "import argparse\nimport sys\n\n\ndef main():\n    p = argparse.ArgumentParser()\n    p.add_argument('--flag')\n\n\nif __name__ == '__main__':\n    main()\n"}, "add a cli")
        rec = self.run_one("surface_coverage.py", self.register(), self.repo)
        self.assertGreater(rec["surfaces"], 0)
        self.assertEqual(rec["uncovered"], rec["surfaces"])

    def skill_copy(self, surfaces_text):
        """A copy of the skills folder with deriving-readable-docs/scripts/surfaces.py replaced by `surfaces_text` (None: removed)."""
        skills = Path(tempfile.mkdtemp(dir=self.tmp), "skills")
        for name in ("distilling-requirements", "deriving-readable-docs"):
            shutil.copytree(T.SKILLS / name, skills / name, ignore=shutil.ignore_patterns("__pycache__"))
        surfaces = skills / "deriving-readable-docs/scripts/surfaces.py"
        surfaces.unlink()
        if surfaces_text is not None:
            surfaces.write_text(surfaces_text)
        return skills / "distilling-requirements/scripts/surface_coverage.py"

    def run_copy(self, path, *args):
        code, _, err = (lambda r: (r.returncode, r.stdout, r.stderr))(subprocess.run([sys.executable, "-I", str(path), *map(str, args)], capture_output=True, text=True, env=self.env))
        return code, err

    def test_surface_coverage_refuses_and_logs_when_surfaces_py_is_missing_or_fails(self):
        path = self.skill_copy(None)
        code, err = self.run_copy(path, self.register(), self.repo)
        self.assertEqual(code, 2)
        self.assertIn("surfaces.py not found", err)
        rec = self.lines()[-1]
        self.assertEqual((rec["outcome"], rec["exit"]), ("refused", 2))
        self.assertIn("surfaces.py not found", rec["reason"])
        shutil.rmtree(self.state)
        path = self.skill_copy("import sys\nprint('boom', file=sys.stderr)\nsys.exit(3)\n")
        code, err = self.run_copy(path, self.register(), self.repo)
        self.assertEqual(code, 2)
        self.assertIn("surfaces.py failed: boom", err)
        rec = self.lines()[-1]
        self.assertEqual((rec["outcome"], rec["exit"], rec["reason"]), ("refused", 2, "surfaces.py failed: boom"))

    def test_check_truth_logs_prepare_with_its_counts(self):
        rec = self.run_one("check_truth.py", "prepare", self.register(), "--out", Path(self.tmp, "out"))
        self.assertEqual((rec["action"], rec["step"], rec["outcome"]), ("check-truth", "prepare", "ok"))
        self.assertEqual((rec["rows"], rec["not_checked"], rec["failed"]), (1, 0, 0))

    def test_check_truth_prepare_logs_the_reason_when_the_register_has_no_rows(self):
        Path(self.tmp, "empty.md").write_text("# nothing here\n")
        rec = self.run_one("check_truth.py", "prepare", Path(self.tmp, "empty.md"), "--out", Path(self.tmp, "out"))
        self.assertEqual((rec["step"], rec["outcome"], rec["exit"], rec["reason"]), ("prepare", "refused", 1, "no register rows"))

    def test_check_truth_logs_verdicts_with_its_counts(self):
        out = Path(self.tmp, "out")
        self.run_one("check_truth.py", "prepare", self.register(), "--out", out)
        shutil.rmtree(self.state)
        reports = Path(self.tmp, "reports")
        reports.mkdir()
        rec = self.run_one("check_truth.py", "verdicts", out, reports)  # no checker report: the one row has no verdict
        self.assertEqual((rec["step"], rec["outcome"], rec["exit"]), ("verdicts", "failed", 1))
        self.assertEqual((rec["rows"], rec["holding"], rec["not_checked"], rec["failed"]), (1, 0, 0, 0))

    def test_check_truth_logs_usage_as_a_refusal(self):
        rec = self.run_one("check_truth.py", "bogus")
        self.assertEqual((rec["outcome"], rec["exit"], rec["reason"]), ("refused", 2, "usage"))

    def test_a_script_that_raises_still_leaves_a_line_and_the_error_goes_on(self):
        code, _, err = T.script("check_shape.py", Path(self.tmp, "missing.md"), env=self.env)
        self.assertEqual(code, 1)
        self.assertIn("FileNotFoundError", err)
        got = self.lines()
        self.assertEqual(len(got), 1, got)
        self.assertEqual((got[0]["script"], got[0]["outcome"], got[0]["exit"], got[0]["error"]), ("check_shape.py", "crashed", 1, "FileNotFoundError"))

    def test_a_bare_sys_exit_in_a_script_is_logged_with_its_code_and_still_exits(self):
        sys.path.insert(0, str(T.SCRIPTS))
        self.addCleanup(sys.path.remove, str(T.SCRIPTS))
        import logged
        os.environ["XDG_STATE_HOME"] = str(self.state)
        self.addCleanup(os.environ.pop, "XDG_STATE_HOME")
        def cli(argv, stats):
            sys.exit(2)
        with self.assertRaises(SystemExit) as caught:
            logged.logged("x.py", "x", cli, [])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual((self.lines()[0]["outcome"], self.lines()[0]["exit"]), ("refused", 2))

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
