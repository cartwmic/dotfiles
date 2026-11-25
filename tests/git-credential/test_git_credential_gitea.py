"""dot_local/bin/executable_git-credential-gitea-op: the Gitea credential helper, run as shipped with a fake `op` and a private HOME.

No real 1Password and no network. The real op_read_cached.sh is copied into the private HOME where the helper looks for it.
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "dot_local/bin/executable_git-credential-gitea-op"
CACHE_SCRIPT = ROOT / "dot_local/user_scripts/executable_op_read_cached.sh"
SCRIPT_76 = ROOT / "run_onchange_after_76_git_credential_linux.sh"
HOST = "gitea.internal.cartwmic.com"
TOKEN = "gta_fake-token-0123456789"
REF = "op://developer/cartwmic-homelab - Gitea - cartwmic/token 1 - repo perms"


def fake_op(body):
    return "#!/bin/sh\n" + body


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.bin = Path(self.tmp.name) / "bin"
        self.cache = Path(self.tmp.name) / "cache"
        self.count = Path(self.tmp.name) / "op-count"
        self.args = Path(self.tmp.name) / "op-args"
        scripts = self.home / ".local/user_scripts"
        scripts.mkdir(parents=True)
        shutil.copy(CACHE_SCRIPT, scripts / "op_read_cached.sh")
        (scripts / "op_read_cached.sh").chmod(0o755)
        self.bin.mkdir()
        self.set_op(f'echo x >> "{self.count}"\nprintf "%s\\n" "$@" > "{self.args}"\nprintf "%s" "{TOKEN}"\n')
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home), "OP_READ_CACHE_DIR": str(self.cache),
                    "OP_SERVICE_ACCOUNT_TOKEN": "ops_fake", "GIT_CONFIG_NOSYSTEM": "1", "XDG_CONFIG_HOME": str(self.home / ".config")}

    def set_op(self, body):
        op = self.bin / "op"
        op.write_text(fake_op(body))
        op.chmod(op.stat().st_mode | stat.S_IXUSR)

    def op_calls(self):
        return len(self.count.read_text().split()) if self.count.exists() else 0

    def helper(self, action="get", host=HOST, env=None, drop=()):
        e = {**self.env, **(env or {})}
        for k in drop:
            e.pop(k, None)
        return subprocess.run(["/bin/sh", str(HELPER), action], input=f"protocol=https\nhost={host}\n\n", env=e, capture_output=True, text=True, timeout=60)

    def files_with_token_outside_cache(self):
        """Every file under the temp tree that holds the token, except the cache dir and the fake op (which returns it)."""
        found = []
        for p in Path(self.tmp.name).rglob("*"):
            if p.is_file() and not p.is_symlink() and p != self.bin / "op" and self.cache not in p.parents and TOKEN.encode() in p.read_bytes():
                found.append(p)
        return found


class GiteaHelper(Base):
    def test_get_prints_login_and_nothing_else(self):   # c1
        r = self.helper()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"username=cartwmic\npassword={TOKEN}\n")
        self.assertNotIn(TOKEN, r.stderr)
        self.assertEqual(self.files_with_token_outside_cache(), [])   # the cache entry is the only copy on disk
        self.assertEqual(self.args.read_text().splitlines()[:2], ["read", REF])
        self.assertTrue(any(TOKEN in p.read_text() for p in self.cache.rglob("*") if p.is_file()))

    def test_silent_without_service_account_and_clean_on_op_failure(self):   # c2
        r = self.helper(drop=("OP_SERVICE_ACCOUNT_TOKEN",))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(self.op_calls(), 0)
        for body in (f'echo x >> "{self.count}"\necho "denied {TOKEN}" >&2\nexit 1\n', f'echo x >> "{self.count}"\nexit 0\n'):
            shutil.rmtree(self.cache, ignore_errors=True)
            self.count.unlink(missing_ok=True)
            self.set_op(body)
            r = self.helper()
            self.assertEqual((r.returncode, r.stdout), (0, ""), body)
            self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
            self.assertIn("git-credential-gitea-op", r.stderr)
            self.assertNotIn(TOKEN, r.stderr)

    def test_other_actions_and_hosts_are_ignored(self):   # c3
        cases = [("store", HOST), ("erase", HOST), ("get", "github.com"), ("get", HOST + ".evil.example"), ("get", "evil." + HOST), ("get", HOST + ":3000"), ("get", "")]
        for action, host in cases:
            with self.subTest(action=action, host=host):
                r = self.helper(action, host)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        r = subprocess.run(["/bin/sh", str(HELPER)], input=f"host={HOST}\n\n", env=self.env, capture_output=True, text=True, timeout=60)   # no action at all
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(self.op_calls(), 0)
        self.assertFalse(self.cache.exists())

    def test_second_get_does_not_read_1password_again(self):   # c7
        first, second = self.helper(), self.helper()
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(second.stdout, f"username=cartwmic\npassword={TOKEN}\n")
        self.assertEqual(self.op_calls(), 1)

    def test_real_git_credential_fill_uses_the_helper_and_github_is_untouched(self):   # c4
        self.assertTrue(shutil.which("git"), "git is required")
        # `git credential-gitea-op` finds the helper on PATH under the name chezmoi installs it as.
        shutil.copy(HELPER, self.bin / "git-credential-gitea-op")
        gh = self.bin / "gh"
        gh.write_text('#!/bin/sh\necho "$@" >> "%s/gh-args"\nprintf "username=gh-user\\npassword=gh-pass\\n"\n' % self.tmp.name)
        gh.chmod(0o755)
        r = subprocess.run(["/bin/sh", str(SCRIPT_76)], env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        env = {**self.env, "GIT_TERMINAL_PROMPT": "0"}
        fill = lambda url: subprocess.run(["git", "credential", "fill"], input=f"url={url}\n\n", env=env, capture_output=True, text=True, timeout=60)
        r = fill(f"https://{HOST}")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("username=cartwmic\n", r.stdout)
        self.assertIn(f"password={TOKEN}\n", r.stdout)
        self.assertEqual(self.op_calls(), 1)
        self.assertFalse((Path(self.tmp.name) / "gh-args").exists())
        r = fill("https://github.com")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("username=gh-user\n", r.stdout)
        self.assertEqual((Path(self.tmp.name) / "gh-args").read_text().strip(), "auth git-credential get")
        self.assertEqual(self.op_calls(), 1)   # github never reached 1Password


if __name__ == "__main__":
    unittest.main()
