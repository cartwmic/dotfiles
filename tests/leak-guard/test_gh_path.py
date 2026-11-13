"""On the work profile the wrapper is the `gh` that resolves first, in the shells agents use.

Fresh zsh processes (empty environment) in a throwaway HOME: the repository's own dot_zshenv and dot_zprofile, the `mise activate zsh` line of the zshrc
template, the real mise, and the installer's output. A mise-managed gh stands in for "the real gh that mise puts first". The tests are skipped where zsh,
mise or a mise-managed gh is missing.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_gh_installer import DATA, render, run_script

ROOT = Path(__file__).resolve().parents[2]
ACTIVATE = 'eval "$(mise activate zsh)"'
MISE = shutil.which("mise")
ZSH = shutil.which("zsh")


def mise_gh():
    if not MISE:
        return None
    done = subprocess.run([MISE, "which", "gh"], capture_output=True, text=True, timeout=30)
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


@unittest.skipUnless(ZSH and MISE and mise_gh(), "needs zsh, mise and a mise-managed gh")
class GhPath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool_gh = mise_gh()
        cls.real_config = Path(os.path.expanduser("~/.config/mise"))

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="gp-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.zdot = self.tmp / "zdot"
        self.zdot.mkdir()
        shutil.copy(ROOT / "dot_zshenv", self.zdot / ".zshenv")
        shutil.copy(ROOT / "dot_zprofile", self.zdot / ".zprofile")
        self.assertIn(ACTIVATE, (ROOT / "private_dot_zshrc.tmpl").read_text())     # the line this test stands in for
        (self.zdot / ".zshrc").write_text(ACTIVATE + "\n")
        self.mise_cfg = self.home / ".config" / "mise"
        self.mise_cfg.mkdir(parents=True)
        shutil.copy(self.real_config / "config.toml", self.mise_cfg / "config.toml")
        self.wrapper = self.home / ".local" / "share" / "leak-guard" / "bin" / "gh"
        self.proj = self.tmp / "proj"
        (self.proj / "bin").mkdir(parents=True)
        (self.proj / "mise.toml").write_text('[env]\n_.path = ["%s"]\n' % (self.proj / "bin"))

    def install(self):
        ran = run_script(self.tmp, render(self.tmp, DATA, home=self.home).stdout, self.home)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertTrue(self.wrapper.exists())

    def zsh(self, flags, command):
        env = {"HOME": str(self.home), "USER": os.environ.get("USER", "u"), "TERM": "xterm", "ZDOTDIR": str(self.zdot),
               "PATH": "%s:/usr/bin:/bin:/usr/sbin:/sbin" % Path(MISE).parent, "MISE_CONFIG_DIR": str(self.mise_cfg),
               "MISE_DATA_DIR": os.environ.get("MISE_DATA_DIR") or os.path.expanduser("~/.local/share/mise"),
               "MISE_TRUSTED_CONFIG_PATHS": str(self.tmp), "MISE_STATE_DIR": str(self.tmp / "state"), "MISE_CACHE_DIR": str(self.tmp / "cache")}
        done = subprocess.run([ZSH, flags, command], capture_output=True, text=True, env=env, timeout=60, cwd=str(self.tmp))
        return done.stdout.strip().splitlines()[-1] if done.stdout.strip() else ""

    def test_the_wrapper_is_the_gh_that_resolves_first_in_every_shell_agents_use(self):
        self.install()
        hook = 'eval "$(mise hook-env -s zsh)"; command -v gh'
        for flags, command in (("-c", "command -v gh"), ("-lc", "command -v gh"), ("-ic", "command -v gh"), ("-lic", "command -v gh"), ("-ic", hook), ("-lic", hook)):
            with self.subTest(flags=flags, command=command):
                self.assertEqual(self.zsh(flags, command), str(self.wrapper))

    def test_the_wrapper_stays_first_after_a_cd_into_a_directory_whose_mise_toml_changes_path(self):
        self.install()
        for flags in ("-ic", "-lic"):
            with self.subTest(flags):
                got = self.zsh(flags, 'cd %s; eval "$(mise hook-env -s zsh)"; command -v gh' % self.proj)
                self.assertEqual(got, str(self.wrapper))
                got = self.zsh(flags, "cd %s; for f in $precmd_functions; do $f; done; command -v gh" % self.proj)
                self.assertEqual(got, str(self.wrapper))

    def test_without_the_install_the_same_shells_print_the_gh_they_always_did(self):
        for flags in ("-ic", "-lic"):
            with self.subTest(flags):
                self.assertEqual(self.zsh(flags, "command -v gh"), self.tool_gh)
        for flags in ("-c", "-lc"):
            with self.subTest(flags):
                self.assertNotEqual(self.zsh(flags, "command -v gh"), str(self.wrapper))

    def test_the_mise_file_is_what_keeps_it_first_where_mise_is_active(self):
        self.install()
        (self.mise_cfg / "conf.d" / "leak-guard-gh.toml").unlink()
        self.assertEqual(self.zsh("-c", "command -v gh"), str(self.wrapper))      # zshenv alone covers a plain shell
        self.assertEqual(self.zsh("-ic", "command -v gh"), self.tool_gh)          # mise puts its own directories ahead of it without the file


if __name__ == "__main__":
    unittest.main()
