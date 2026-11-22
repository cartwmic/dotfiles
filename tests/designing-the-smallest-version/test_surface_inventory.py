"""repo_facts.py takes its surface list from deriving-readable-docs/scripts/surfaces.py.
Run: python3 -I tests/designing-the-smallest-version/test_surface_inventory.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills"
REPO_FACTS = SKILLS / "designing-the-smallest-version/scripts/repo_facts.py"
SURFACES = SKILLS / "deriving-readable-docs/scripts/surfaces.py"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

FILES = {
    "pyproject.toml": '[project]\nname = "x"\n\n[project.scripts]\nxcli = "x.cli:main"\n',
    "src/x/cli.py": 'import argparse, os\np = argparse.ArgumentParser()\np.add_argument("--verbose")\nhome = os.environ.get("X_HOME")\nif __name__ == "__main__":\n    main()\n',
    "web/cli.js": 'program.command("build");\napp.get("/ping", (req, res) => {});\nconst k = process.env.API_KEY;\n',
    "README.md": "# x\n",
}


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True, env=ENV).stdout.strip()


def make_repo(root, files):
    root.mkdir(parents=True)
    git(str(root), "init", "-q", "-b", "main")
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    git(str(root), "add", "-A")
    git(str(root), "commit", "-q", "-m", "fixture")


def run_facts(script, repo, *args):
    return subprocess.run([sys.executable, "-B", str(script), str(repo), *args], capture_output=True, text=True)


class SurfaceInventoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="surface_inventory-"))
        cls.repo = cls.tmp / "fixture"
        make_repo(cls.repo, FILES)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_surface_list_equals_surfaces_py_output(self):
        res = run_facts(REPO_FACTS, self.repo)
        self.assertEqual(res.returncode, 0, res.stderr)
        expected = json.loads(subprocess.run([sys.executable, "-I", str(SURFACES), str(self.repo), "--json"],
                                             capture_output=True, text=True, check=True).stdout)
        self.assertEqual(json.loads(res.stdout)["surfaces"], expected)
        kinds = {r["kind"] for r in expected}
        self.assertTrue({"command", "flag", "route", "env", "entry"} <= kinds, kinds)

    def test_surface_list_is_the_tree_at_the_rev_not_the_working_tree(self):
        (self.repo / "late.py").write_text('import os\nos.getenv("LATE_ONLY")\n')  # untracked, never committed
        try:
            res = run_facts(REPO_FACTS, self.repo)
        finally:
            (self.repo / "late.py").unlink()
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("LATE_ONLY", [r["name"] for r in json.loads(res.stdout)["surfaces"]])

    def test_missing_surfaces_py_gives_a_clear_error(self):
        skills = self.tmp / "skills-without-codemap"
        script = skills / "designing-the-smallest-version/scripts/repo_facts.py"
        script.parent.mkdir(parents=True)
        shutil.copy(REPO_FACTS, script)
        res = run_facts(script, self.repo)
        self.assertEqual(res.returncode, 2)
        self.assertEqual(len(res.stderr.strip().splitlines()), 1)
        self.assertIn("surfaces.py not found", res.stderr)
        self.assertIn("deriving-readable-docs", res.stderr)

    def test_works_through_a_skill_symlink_the_apply_makes(self):
        # The apply links a whole skill folder (ln -s canonical/skills/<name> ~/.<harness>/skills/<name>); the sibling skill is
        # found from the file's real location, not from the link.
        link_dir = self.tmp / "harness-skills"
        link_dir.mkdir()
        os.symlink(REPO_FACTS.parents[1], link_dir / "designing-the-smallest-version")
        res = run_facts(link_dir / "designing-the-smallest-version/scripts/repo_facts.py", self.repo)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(json.loads(res.stdout)["surfaces"])

    def test_summary_lists_surfaces_as_one_array_line(self):
        res = run_facts(REPO_FACTS, self.repo, "--summary")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue([l for l in res.stdout.splitlines() if l.startswith("surfaces ") and " array " in l])


if __name__ == "__main__":
    unittest.main()
