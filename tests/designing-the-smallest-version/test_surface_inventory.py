"""repo_facts.py takes its surface list from deriving-readable-docs/scripts/surfaces.py.
Run: python3 -I tests/designing-the-smallest-version/test_surface_inventory.py"""
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

    def test_notes_say_where_the_surface_rows_come_from(self):
        note = json.loads(run_facts(REPO_FACTS, self.repo).stdout)["notes"]["surfaces"]
        self.assertIn("surfaces.py --json", note)
        self.assertIn("tree extracted at REV", note)
        self.assertIn("--scope does not narrow it", note)

    def test_surface_list_is_the_tree_at_the_pinned_rev_not_the_checkout(self):
        # OLD_ENV exists at HEAD~1 only (HEAD removed it, NEW_ENV is added), and the checkout is HEAD. A run that reads the
        # checkout instead of the rev would list NEW_ENV and miss OLD_ENV.
        repo = self.tmp / "two-commits"
        make_repo(repo, {"a.py": 'import os\nos.environ.get("OLD_ENV")\n'})
        (repo / "a.py").write_text('import os\nos.environ.get("NEW_ENV")\n')
        git(str(repo), "commit", "-q", "-am", "swap env var")
        old = run_facts(REPO_FACTS, repo, "--rev", "HEAD~1")
        self.assertEqual(old.returncode, 0, old.stderr)
        self.assertEqual([r["name"] for r in json.loads(old.stdout)["surfaces"]], ["OLD_ENV"])
        new = run_facts(REPO_FACTS, repo)
        self.assertEqual([r["name"] for r in json.loads(new.stdout)["surfaces"]], ["NEW_ENV"])

    def test_docs_found_skips_docs_snapshots_because_a_snapshot_is_never_evidence(self):
        repo = self.tmp / "with-snapshot"
        make_repo(repo, {"a.py": "x = 1\n", "docs/PRD.md": "# prd\n", "docs/snapshots/2026-01-01-aaaaaaa/REQUIREMENTS.md": "# old\n", "docs/snapshots/2026-01-01-aaaaaaa/DESIGN.md": "# old\n"})
        res = run_facts(REPO_FACTS, repo)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual([d["path"] for d in json.loads(res.stdout)["docs_found"]], ["docs/PRD.md"])

    def test_missing_surfaces_py_gives_a_clear_error(self):
        skills = self.tmp / "skills-without-codemap"
        script = skills / "designing-the-smallest-version/scripts/repo_facts.py"
        script.parent.mkdir(parents=True)
        shutil.copy(REPO_FACTS, script)
        shutil.copy(REPO_FACTS.with_name("runlog.py"), script.with_name("runlog.py"))  # the script logs each run through it
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
