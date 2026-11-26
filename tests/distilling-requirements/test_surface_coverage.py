"""surface_coverage.py lists the surfaces (from surfaces.py) that no R-row of a REQUIREMENTS.md cites.
Run: python3 -I tests/distilling-requirements/test_surface_coverage.py"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills"
COVERAGE = SKILLS / "distilling-requirements/scripts/surface_coverage.py"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

CLI = ('import argparse, os\n'                       # 1
       'p = argparse.ArgumentParser()\n'             # 2
       'p.add_argument("--verbose")\n'               # 3  cited by exact line
       'p.add_argument("--quiet")\n'                 # 4  cited by a range
       'p.add_argument("--dry-run")\n'               # 5  cited by a range
       'p.add_argument("--forgotten")\n'             # 6  cited by nothing
       'home = os.environ.get("X_HOME")\n'           # 7  cited by name in the requirement text
       )
ROW = "| %s | product | explicit | enduring | proposed | %s | %s | none | none | no | %s |"


def register(commit, rows):
    head = "```text\nshape: requirements/2\nrepo: fixture\ncommit: %s\nscope: whole repo\ndate: 2026-11-21\nnot-read: none\n```\n" % commit
    cols = "| id | lens | kind | durability | status | requirement | evidence | check | fit | enforced | note |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
    return head + "\n## 1. Requirements register\n\n" + cols + "\n".join(rows) + "\n"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=ENV).stdout.strip()


class SurfaceCoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="surface_coverage-"))
        cls.repo = cls.tmp / "fixture"
        (cls.repo / "src").mkdir(parents=True)
        (cls.repo / "src/cli.py").write_text(CLI)
        git(cls.repo, "init", "-q", "-b", "main")
        git(cls.repo, "add", "-A")
        git(cls.repo, "commit", "-q", "-m", "fixture")
        cls.head = git(cls.repo, "rev-parse", "HEAD")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_cov(self, text, *args):
        md = self.tmp / "REQUIREMENTS.md"
        md.write_text(text)
        return subprocess.run([sys.executable, "-I", str(COVERAGE), str(md), str(self.repo), *args], capture_output=True, text=True)

    def test_only_the_surface_no_row_cites_is_listed(self):
        rows = [ROW % ("R-1", "The tool shall print more.", "src/cli.py:3", "-"),
                ROW % ("R-2", "The tool shall be quiet and dry on request.", "src/cli.py:4-5", "-"),
                ROW % ("R-3", "The tool shall read X_HOME.", "src/cli.py:1", "-")]
        res = self.run_cov(register(self.head, rows))
        self.assertEqual(res.returncode, 0, res.stderr)
        listed = [l for l in res.stdout.splitlines() if " | " in l]
        self.assertEqual(listed, ["flag | --forgotten | src/cli.py:6"], res.stdout)
        self.assertTrue(res.stdout.startswith("# 1 of "), res.stdout)

    def test_a_cited_line_in_another_file_does_not_cover_it(self):
        rows = [ROW % ("R-1", "The tool shall print more.", "src/other.py:3", "-")]
        res = self.run_cov(register(self.head, rows))
        self.assertIn("flag | --verbose | src/cli.py:3", res.stdout)

    def test_no_rows_lists_every_product_surface(self):
        res = self.run_cov(register(self.head, []))
        self.assertEqual(res.returncode, 0, res.stderr)
        for name in ("--verbose", "--quiet", "--dry-run", "--forgotten", "X_HOME"):
            self.assertIn(name, res.stdout)

    def test_warns_when_the_register_commit_is_not_the_repo_head(self):
        res = self.run_cov(register("0" * 40, []))
        self.assertTrue(res.stdout.startswith("warning: the register is at 000000000000"), res.stdout)
        self.assertNotIn("warning", self.run_cov(register(self.head, [])).stdout)

    def test_missing_surfaces_py_gives_a_clear_error(self):
        script = self.tmp / "skills/distilling-requirements/scripts/surface_coverage.py"
        script.parent.mkdir(parents=True)
        shutil.copy(COVERAGE, script)
        shutil.copy(COVERAGE.parent / "check_shape.py", script.parent / "check_shape.py")  # surface_coverage.py reads evidence cells through it
        shutil.copy(COVERAGE.parent / "scopes.py", script.parent / "scopes.py")  # and reads --scope through scopes.py
        md = self.tmp / "R.md"
        md.write_text(register(self.head, []))
        res = subprocess.run([sys.executable, "-I", str(script), str(md), str(self.repo)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)
        self.assertIn("surfaces.py not found", res.stderr)

    def test_bad_usage_exits_2(self):
        res = subprocess.run([sys.executable, "-I", str(COVERAGE)], capture_output=True, text=True)
        self.assertEqual(res.returncode, 2)


if __name__ == "__main__":
    unittest.main()
