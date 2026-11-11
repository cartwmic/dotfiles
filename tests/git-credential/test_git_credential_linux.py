"""run_onchange_after_76_git_credential_linux.sh: the portable GitHub credential helper, in a private HOME with the real git.

The script is plain sh (no template), so it runs as it ships. Nothing here reads or writes the real git config.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "run_onchange_after_76_git_credential_linux.sh"
HOSTS = ("github.com", "gist.github.com")
PORTABLE = ["", "!gh auth git-credential"]


@unittest.skipUnless(shutil.which("git"), "git is required")
class GitCredentialLinux(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1", "XDG_CONFIG_HOME": str(self.home / ".config")}

    def run_script(self, **extra):
        return subprocess.run(["/bin/sh", str(SCRIPT)], env={**self.env, **extra}, capture_output=True, text=True, timeout=60)

    def git(self, *args):
        return subprocess.run(["git", *args], env=self.env, capture_output=True, text=True)

    def values(self, host):
        r = self.git("config", "--global", "--get-all", f"credential.https://{host}.helper")
        return r.stdout.split("\n")[:-1] if r.returncode == 0 else None

    def test_a_fresh_home_gets_the_portable_pair_for_both_hosts(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        for host in HOSTS:
            self.assertEqual(self.values(host), PORTABLE, host)

    def test_a_version_pinned_gh_path_is_replaced_and_other_keys_stay(self):
        pinned = "!/home/x/.local/share/mise/installs/gh/2.103.3/gh_2.103.3_linux_arm64/bin/gh auth git-credential"
        for host in HOSTS:
            self.git("config", "--global", "--add", f"credential.https://{host}.helper", "")
            self.git("config", "--global", "--add", f"credential.https://{host}.helper", pinned)
        self.git("config", "--global", "alias.st", "status")
        self.git("config", "--global", "credential.https://example.com.helper", "store")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        for host in HOSTS:
            self.assertEqual(self.values(host), PORTABLE, host)
        self.assertEqual(self.git("config", "--global", "alias.st").stdout.strip(), "status")
        self.assertEqual(self.git("config", "--global", "credential.https://example.com.helper").stdout.strip(), "store")

    def test_a_second_run_writes_nothing(self):
        self.run_script()
        config = next(p for p in (self.home / ".gitconfig", self.home / ".config/git/config") if p.exists())
        before = (config.read_bytes(), config.stat().st_mtime_ns)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout + r.stderr, "")
        self.assertEqual((config.read_bytes(), config.stat().st_mtime_ns), before)

    def test_it_writes_to_the_config_git_already_uses(self):
        (self.home / ".config/git").mkdir(parents=True)
        (self.home / ".config/git/config").write_text("[alias]\n\tco = checkout\n")
        self.run_script()
        self.assertIn("credential", (self.home / ".config/git/config").read_text())
        self.assertFalse((self.home / ".gitconfig").exists())

    def test_one_host_out_of_date_is_fixed_and_only_that_one_is_reported(self):
        self.run_script()
        self.git("config", "--global", "--replace-all", "credential.https://gist.github.com.helper", "store")
        r = self.run_script()
        self.assertEqual(self.values("gist.github.com"), PORTABLE)
        self.assertIn("set credential.https://gist.github.com.helper", r.stdout)
        self.assertNotIn("set credential.https://github.com.helper", r.stdout)

    def test_the_helper_runs_gh_by_name(self):
        self.run_script()
        for host in HOSTS:
            self.assertNotIn("/", self.values(host)[1].split(" auth")[0].lstrip("!"))

    def test_no_git_is_a_notice_and_a_clean_exit(self):
        only_uname = Path(self.tmp.name) / "only-uname"
        only_uname.mkdir()
        (only_uname / "uname").symlink_to(shutil.which("uname"))
        r = self.run_script(PATH=str(only_uname))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("git is not installed", r.stdout)

    def test_the_undo_line_in_the_header_removes_both(self):
        self.run_script()
        for host in HOSTS:
            self.git("config", "--global", "--unset-all", f"credential.https://{host}.helper")
            self.assertIsNone(self.values(host))


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
    NAME = "76_git_credential_linux.sh"

    def test_only_personal_linux_runs_it(self):
        self.assertNotIn(self.NAME, ignored("personal", "linux"))
        for profile, chezmoi_os in (("personal", "darwin"), ("axon-work-computer", "darwin"), ("axon-work-computer", "linux"), ("termux", "android")):
            with self.subTest(profile, os=chezmoi_os):
                self.assertIn(self.NAME, ignored(profile, chezmoi_os))


if __name__ == "__main__":
    unittest.main()
