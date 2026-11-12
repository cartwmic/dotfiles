"""run_onchange_after_77_git_identity_linux.sh: the global git identity, in a private HOME with the real git."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "run_onchange_after_77_git_identity_linux.sh"
EMAIL = "45673987+cartwmic@users.noreply.github.com"


@unittest.skipUnless(shutil.which("git"), "git is required")
class GitIdentityLinux(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1", "XDG_CONFIG_HOME": str(self.home / ".config")}

    def run_script(self):
        return subprocess.run(["/bin/sh", str(SCRIPT)], env=self.env, capture_output=True, text=True, timeout=60)

    def git(self, *args):
        return subprocess.run(["git", *args], env=self.env, capture_output=True, text=True)

    def test_a_fresh_home_gets_the_identity_and_can_commit_with_no_overrides(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.git("config", "--global", "user.name").stdout.strip(), "Michael Cartwright")
        self.assertEqual(self.git("config", "--global", "user.email").stdout.strip(), EMAIL)
        repo = self.home / "repo"
        self.git("init", "-q", str(repo))
        c = subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "x"], env=self.env, capture_output=True, text=True)
        self.assertEqual(c.returncode, 0, c.stderr)

    def test_an_existing_identity_is_kept_and_nothing_is_reported(self):
        self.git("config", "--global", "user.name", "Someone Else")
        self.git("config", "--global", "user.email", "else@example.com")
        r = self.run_script()
        self.assertEqual(r.stdout + r.stderr, "")
        self.assertEqual(self.git("config", "--global", "user.name").stdout.strip(), "Someone Else")
        self.assertEqual(self.git("config", "--global", "user.email").stdout.strip(), "else@example.com")

    def test_a_second_run_writes_nothing(self):
        self.run_script()
        r = self.run_script()
        self.assertEqual(r.stdout + r.stderr, "")


def ignored(profile, chezmoi_os):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("{}\n")
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "execute-template", "--override-data",
                            json.dumps({"profile": profile, "chezmoi": {"os": chezmoi_os}})],
                           input=(ROOT / ".chezmoiignore").read_text(), capture_output=True, text=True, timeout=120, env={**os.environ, "HOME": tmp})
    assert r.returncode == 0, r.stderr
    return {line.strip() for line in r.stdout.splitlines() if line.strip() and not line.startswith("#")}


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class Deployment(unittest.TestCase):
    NAME = "77_git_identity_linux.sh"

    def test_only_personal_linux_runs_it(self):
        self.assertNotIn(self.NAME, ignored("personal", "linux"))
        for profile, chezmoi_os in (("personal", "darwin"), ("axon-work-computer", "darwin"), ("axon-work-computer", "linux"), ("termux", "android")):
            with self.subTest(profile, os=chezmoi_os):
                self.assertIn(self.NAME, ignored(profile, chezmoi_os))


if __name__ == "__main__":
    unittest.main()
