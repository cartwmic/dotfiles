"""Fix round 1 for the snapshot PR: each test runs the real shape (the doc() helper's own output, the real lint_main.py, a real git repo, the real gh error text).
Run: python3 -m unittest discover -s tests/distilling-requirements"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import runlog_support  # first: keeps the run out of the real log
import test_requirements_v2 as T

SKILL = T.SKILLS / "distilling-requirements"


class SnapshotMarkerTest(unittest.TestCase):
    def check(self, repo, evidence):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "R.md").write_text(T.doc([T.row(1, evidence=evidence)]))
            code, out, _ = T.script("check_shape.py", Path(d, "R.md"), repo)
        return code, out

    def test_a_kept_requirements_file_is_a_snapshot_though_its_marker_is_far_below_line_8(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "notes").mkdir()
            kept = T.doc([T.row(1)])
            Path(d, "notes", "REQUIREMENTS.md").write_text(kept)
            self.assertGreater(kept.splitlines().index(T.LINE), 8)
            code, out = self.check(d, "notes/REQUIREMENTS.md:5")
        self.assertEqual(code, 1)
        self.assertIn("cites a snapshot", out)

    def test_the_marker_in_guide_and_design_shapes_counts_too(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text("```text\nshape: guide/1\n```\n\n# Guide: demo\n\nSnapshot of demo at no-git on 2026-11-26. Not maintained: it records the code at that commit, not today's.\n\nbody\n")
            code, out = self.check(d, "GUIDE.md:9")
        self.assertEqual(code, 1)

    def test_code_that_quotes_the_line_with_placeholders_is_not_a_snapshot(self):
        lint = SKILL.parent / "deriving-readable-docs"
        self.assertIn("Snapshot of <repo> at <sha7> on <date>. Not maintained", (lint / "scripts/lint_main.py").read_text())
        self.assertEqual(self.check(str(lint), "scripts/lint_main.py:60"), (0, "ok\n"))


class HistoryHeaderTest(unittest.TestCase):
    def test_a_file_without_the_history_key_or_with_another_rev_fails(self):
        code, out = T.shape(T.doc([T.row(1)], {"history": None}))
        self.assertEqual((code, "header: missing history" in out), (1, True))
        code, out = T.shape(T.doc([T.row(1)], {"history": "b" * 40}))
        self.assertEqual((code, "history must equal commit" in out), (1, True))
        self.assertIn("history must be", T.shape(T.doc([T.row(1)], {"history": "HEAD"}))[1])
        self.assertEqual(T.shape(T.doc([T.row(1)])), (0, "ok\n"))


class NoCutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template, _ = T.build_fixture_repo(lambda repo: [T.commit(repo, {"a.py": "%d\n" % n}, "fix: bug number %d" % n) for n in range(45)])

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = T.copy_fixture_repo(self.template, self.tmp)
        self.no_gh = T.fake_gh(self.tmp)[1]

    def run_signals(self, *args):
        code, out, err = T.script("history_signals.py", self.repo, *args, path=self.no_gh)
        self.assertEqual(code, 0, err)
        return out

    def test_by_default_every_commit_is_listed_and_nothing_is_cut(self):
        out = self.run_signals()
        self.assertIn("## Signal commits (45)", out)
        self.assertEqual(out.count("fix: bug number"), 45)
        self.assertNotIn("cut by --limit", out)

    def test_limit_0_means_all_and_limit_n_cuts_and_says_so(self):
        self.assertEqual(self.run_signals("--limit", "0").count("fix: bug number"), 45)
        out = self.run_signals("--limit", "5")
        self.assertEqual(out.count("fix: bug number"), 5)
        self.assertIn("(40 more rows cut by --limit)", out)

    def test_out_writes_the_full_report_to_a_file_and_prints_one_line(self):
        dest = Path(self.tmp, "h.md")
        said = self.run_signals("--out", str(dest))
        self.assertEqual(said.count("\n"), 1)
        self.assertIn(str(dest), said)
        self.assertEqual(dest.read_text().count("fix: bug number"), 45)

    def test_it_runs_with_no_sibling_skill_installed(self):
        lone = Path(self.tmp, "skills", "distilling-requirements")
        shutil.copytree(SKILL / "scripts", lone / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
        import subprocess, sys
        p = subprocess.run([sys.executable, "-I", str(lone / "scripts/history_signals.py"), str(self.repo), "--no-gh"], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("## Signal commits (45)", p.stdout)
        self.assertNotIn("repo_facts", (SKILL / "scripts/history_signals.py").read_text())


class NoGitOutTest(unittest.TestCase):
    def test_out_in_a_folder_with_no_git_still_writes_the_file_and_says_no_git(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "src").mkdir()
            dest = Path(d, "h.md")
            code, out, err = T.script("history_signals.py", Path(d, "src"), "--out", dest)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(dest.read_text(), "no git history\n")
            self.assertIn("wrote 1 lines to %s" % dest, out)
            code, out, _ = T.script("history_signals.py", Path(d, "src"))
            self.assertEqual((code, out), (0, "no git history\n"))


class SkillTextTest(unittest.TestCase):
    def text(self, *rel):
        return (SKILL.joinpath(*rel)).read_text(encoding="utf-8")

    def test_the_history_step_says_what_to_do_with_a_cut_and_writes_the_history_key(self):
        for f in (self.text("SKILL.md"), self.text("references", "history.md")):
            self.assertIn("--limit", f)
            self.assertIn("--out", f)
        self.assertIn("history:", self.text("references", "output-shape.md"))
        self.assertIn("counts of unique ids", self.text("references", "output-shape.md"))

    def test_the_interview_reference_covers_pointer_check_partial_answers_and_scope_ownership(self):
        t = self.text("references", "interview.md")
        for phrase in ("open the pointer it cites", "only in part", "belongs to the run that owns that code"):
            self.assertIn(phrase, t)

    def test_a_repo_wide_run_runs_surface_coverage_without_scope(self):
        self.assertIn("without `--scope`", self.text("SKILL.md"))


if __name__ == "__main__":
    unittest.main()
