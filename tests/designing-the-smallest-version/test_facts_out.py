"""repo_facts.py --out never replaces a file that is already there unless --force is given.
Run: python3 -I tests/designing-the-smallest-version/test_facts_out.py"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = tempfile.mkdtemp(prefix="state-")  # the script logs each run (runlog.py): keep these runs out of the real log
os.environ["XDG_STATE_HOME"] = STATE
atexit.register(shutil.rmtree, STATE, True)

SKILLS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills"
REPO_FACTS = SKILLS / "designing-the-smallest-version/scripts/repo_facts.py"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def run(repo, *args):
    return subprocess.run([sys.executable, "-B", str(REPO_FACTS), str(repo), *args], capture_output=True, text=True)


class OutNeverLosesABlock(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="facts_out-"))
        cls.repo = cls.tmp / "repo"
        (cls.repo / "src").mkdir(parents=True)
        (cls.repo / "src/a.py").write_text("x = 1\n")
        cls.parts = cls.tmp / "parts.tsv"
        cls.parts.write_text("src/**\tsrc part\n")
        for cmd in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "-m", "c")):
            subprocess.run(["git", "-C", str(cls.repo), *cmd], check=True, capture_output=True, env=ENV)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def out(self, name):
        return self.tmp / name

    def test_an_existing_file_is_refused_and_survives_whatever_the_options(self):
        f = self.out("a.json")
        self.assertEqual(run(self.repo, "--parts", str(self.parts), "--out", str(f)).returncode, 0)
        before = f.read_text()
        for opts in (("--summary",), (), ("--parts", str(self.parts)), ("--scope", "src/**"), ("--scope", "lib/**", "--summary")):
            done = run(self.repo, *opts, "--out", str(f))
            self.assertEqual(done.returncode, 2, (opts, done.stdout))
            self.assertIn("already exists", done.stderr)
            self.assertEqual(f.read_text(), before)

    def test_the_refusal_comes_before_any_analysis(self):
        f = self.out("b.json")
        f.write_text("keep")
        done = run(self.tmp / "no-such-repo", "--out", str(f))  # a path that is no git repo would fail with its own message if the analysis ran first
        self.assertEqual(done.returncode, 2)
        self.assertIn("already exists", done.stderr)
        self.assertEqual(f.read_text(), "keep")

    def test_force_replaces_the_file(self):
        f = self.out("c.json")
        self.assertEqual(run(self.repo, "--scope", "src/**", "--out", str(f)).returncode, 0)
        self.assertEqual(run(self.repo, "--force", "--out", str(f)).returncode, 0)
        self.assertNotIn("scope", json.loads(f.read_text()))

    def test_a_new_file_is_free_and_a_summary_with_no_out_writes_no_file(self):
        self.assertEqual(run(self.repo, "--summary", "--out", str(self.out("fresh.json"))).returncode, 0)
        before = set(self.tmp.iterdir())
        self.assertEqual(run(self.repo, "--summary").returncode, 0)
        self.assertEqual(set(self.tmp.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
