"""sync_harness_skills.sh deploys canonical skills through chezmoi, not by raw copy.

Runs the real script against a throwaway chezmoi source and HOME (no chezmoi
config, so no hooks). Needs chezmoi on PATH.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "dot_local/user_scripts/executable_sync_harness_skills.sh"
SKILLS = ".local/share/agent-harness/canonical/skills"


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not on PATH")
class SyncHarnessSkillsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "home"
        self.src = self.tmp / "src"
        s = self.src / "dot_local/share/agent-harness/canonical/skills"
        (s / "alpha/scripts").mkdir(parents=True)
        (s / "alpha/SKILL.md").write_text("alpha v2\n")
        (s / "alpha/scripts/executable_run.sh").write_text("#!/bin/sh\necho run\n")
        (s / "beta").mkdir()
        (s / "beta/SKILL.md.tmpl").write_text('{{ "rendered" }}\n')
        (s / "gamma").mkdir()
        (s / "gamma/SKILL.md").write_text("gamma\n")

        d = self.deployed = self.home / SKILLS
        (d / "alpha/scripts").mkdir(parents=True)
        (d / "alpha/SKILL.md").write_text("alpha v1\n")
        # What the old raw-copy sync left behind.
        (d / "alpha/scripts/executable_run.sh").write_text("#!/bin/sh\necho run\n")
        (d / "gamma").mkdir()
        (d / "gamma/SKILL.md").write_text("gamma\n")
        (d / "old").mkdir()
        (d / "old/SKILL.md").write_text("orphan\n")

    def run_sync(self, *args):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home),
               "XDG_CONFIG_HOME": str(self.home / ".config"),
               "XDG_CACHE_HOME": str(self.home / ".cache"),
               "CHEZMOI_SOURCE_DIR": str(self.src), "NO_COLOR": "1"}
        r = subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def files(self):
        return sorted(str(p.relative_to(self.deployed)) for p in self.deployed.rglob("*") if p.is_file())

    def test_preview_changes_nothing(self):
        before = self.files()
        out = self.run_sync("--dry-run")
        self.assertIn("+\x1b[0m beta", out)
        self.assertIn("~\x1b[0m alpha", out)
        self.assertIn("· gamma", out)
        self.assertIn("old/ (orphan skill)", out)
        self.assertIn("alpha/scripts/executable_run.sh", out)
        self.assertIn("+alpha v2", out)  # chezmoi diff of the rendered target
        self.assertIn("+rendered", out)
        self.assertIn("Dry run", out)
        self.assertEqual(self.files(), before)

    def test_apply_renders_names_and_contents(self):
        self.run_sync("--yes")
        d = self.deployed
        self.assertEqual((d / "alpha/SKILL.md").read_text(), "alpha v2\n")
        run = d / "alpha/scripts/run.sh"
        self.assertTrue(os.access(run, os.X_OK))
        self.assertEqual((d / "beta/SKILL.md").read_text(), "rendered\n")
        self.assertFalse((d / "beta/SKILL.md.tmpl").exists())
        # Without --prune, unmanaged entries stay, and only they carry source prefixes.
        self.assertTrue((d / "old/SKILL.md").exists())
        prefixed = [f for f in self.files() if "executable_" in f or f.endswith(".tmpl")]
        self.assertEqual(prefixed, ["alpha/scripts/executable_run.sh"])
        out = self.run_sync("--dry-run")
        self.assertIn("Everything is in sync", out)
        self.assertIn("--prune", out)

    def test_prune_removes_unmanaged(self):
        self.run_sync("--yes", "--prune")
        self.assertEqual(self.files(), ["alpha/SKILL.md", "alpha/scripts/run.sh",
                                        "beta/SKILL.md", "gamma/SKILL.md"])
        self.assertFalse((self.deployed / "old").exists())
        out = self.run_sync("--dry-run", "--prune")
        self.assertIn("Everything is in sync", out)
        self.assertNotIn("Not managed", out)

    def test_prune_handles_spaces_in_names(self):
        # A whitespace-split list would read "alpha/SKILL.md" and "backup" here.
        (self.deployed / "alpha/SKILL.md backup").write_text("bak\n")
        (self.deployed / "my old skill").mkdir()
        (self.deployed / "my old skill/SKILL.md").write_text("orphan\n")
        out = self.run_sync("--dry-run", "--prune")
        self.assertIn("alpha/SKILL.md backup", out)
        self.assertIn("my old skill/ (orphan skill)", out)
        self.run_sync("--yes", "--prune")
        self.assertEqual(self.files(), ["alpha/SKILL.md", "alpha/scripts/run.sh",
                                        "beta/SKILL.md", "gamma/SKILL.md"])

    def test_first_deploy_into_empty_home(self):
        shutil.rmtree(self.home)
        out = self.run_sync("--dry-run")
        for skill in ("alpha", "beta", "gamma"):
            self.assertIn(f"+\x1b[0m {skill}", out)
        self.run_sync("--yes")
        self.assertEqual(self.files(), ["alpha/SKILL.md", "alpha/scripts/run.sh",
                                        "beta/SKILL.md", "gamma/SKILL.md"])

    def test_chezmoiremove_entry_is_deleted(self):
        (self.src / ".chezmoiremove").write_text(SKILLS + "/old\n")
        out = self.run_sync("--dry-run")
        self.assertIn("−\x1b[0m old", out)
        self.assertTrue((self.deployed / "old").exists())
        self.run_sync("--yes")
        self.assertFalse((self.deployed / "old").exists())


if __name__ == "__main__":
    unittest.main()
