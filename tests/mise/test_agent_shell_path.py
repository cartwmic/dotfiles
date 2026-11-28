"""The PATH an agent harness keeps from `zsh -ilc` names shims, not versioned install folders, and keeps the op shim and the gh wrapper first.

The harness reads PATH from a login shell once, when it starts, and gives it to every session. A PATH that names `installs/<tool>/<version>` goes
stale at the next pin bump; one that names the shims folder does not, because a shim finds the pinned version when it runs.

Fresh zsh processes in a throwaway HOME, with the repository's own dot_zshenv and dot_zprofile, the mise block of the zshrc template, the repository's
op-shim mise file and the real mise. The "installed" tools are fake scripts under a scratch mise data directory, so nothing is downloaded. The tests are
skipped where zsh or mise is missing.
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MISE = shutil.which("mise")
ZSH = shutil.which("zsh")


def mise_block():
    """The `if command -v mise ... fi` block of the zshrc template, as the file has it."""
    text = (ROOT / "private_dot_zshrc.tmpl").read_text()
    start = text.index("if command -v mise")
    end = text.index("\nfi\n", start) + len("\nfi\n")
    block = text[start:end]
    assert "mise activate zsh" in block
    return block


def write_exe(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(0o755)


@unittest.skipUnless(ZSH and MISE, "needs zsh and mise")
class AgentShellPath(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="asp-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.zdot = self.tmp / "zdot"
        self.data = self.tmp / "data"
        self.cfg = self.home / ".config" / "mise"
        for d in (self.home, self.zdot, self.cfg / "conf.d"):
            d.mkdir(parents=True)
        shutil.copy(ROOT / "dot_zshenv", self.zdot / ".zshenv")
        shutil.copy(ROOT / "dot_zprofile", self.zdot / ".zprofile")
        (self.zdot / ".zshrc").write_text(mise_block())
        shutil.copy(ROOT / "dot_config" / "mise" / "conf.d" / "op-shim.toml", self.cfg / "conf.d" / "op-shim.toml")
        # the guard shim and the gh wrapper, as the dotfiles put them
        write_exe(self.home / ".local/share/op-shim/op", "echo guard-op")
        write_exe(self.home / ".local/share/gh-wrapper/bin/gh", "echo wrapper-gh")
        # two installed versions of one fake tool; each ships a real-looking op, gh and tool
        for version in ("1.0.0", "2.0.0"):
            bin_dir = self.data / "installs" / "node" / version / "bin"
            for name in ("node", "op", "gh"):
                write_exe(bin_dir / name, "echo real-%s-%s" % (name, version))
        self.pin("1.0.0")
        subprocess.run([MISE, "reshim"], env=self.mise_env(), capture_output=True, check=True, timeout=60)

    def pin(self, version):
        (self.cfg / "config.toml").write_text('[tools]\nnode = "%s"\n' % version)

    def mise_env(self, path=None):
        return {"HOME": str(self.home), "USER": os.environ.get("USER", "u"), "TERM": "xterm", "ZDOTDIR": str(self.zdot),
                "PATH": path or "%s:/usr/bin:/bin:/usr/sbin:/sbin" % Path(MISE).parent, "MISE_DATA_DIR": str(self.data),
                "XDG_CONFIG_HOME": str(self.home / ".config"), "XDG_DATA_HOME": str(self.tmp / "xdg-data"), "XDG_STATE_HOME": str(self.tmp / "xdg-state"),
                "MISE_IGNORED_CONFIG_PATHS": os.path.expanduser("~/.config/mise"),   # the machine's own mise config must not leak in
                
                "MISE_TRUSTED_CONFIG_PATHS": str(self.tmp), "MISE_STATE_DIR": str(self.tmp / "state"), "MISE_CACHE_DIR": str(self.tmp / "cache")}

    def snapshot(self):
        """What the agent harness does: `zsh -ilc` with a command that prints PATH. Returns the entries."""
        done = subprocess.run([ZSH, "-ilc", "print -r -- $PATH"], capture_output=True, text=True, env=self.mise_env(), timeout=60, cwd=str(self.tmp))
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip().splitlines()[-1].split(":")

    def terminal(self):
        """A person's terminal: interactive, no command string. The commands arrive on stdin, which is how a test has no tty."""
        done = subprocess.run([ZSH, "-i"], input="print -r -- $PATH\nexit\n", capture_output=True, text=True, env=self.mise_env(), timeout=60, cwd=str(self.tmp))
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = [line for line in done.stdout.splitlines() if "/" in line and ":" in line]
        return lines[-1].split(":")

    def run_with(self, path_entries, command):
        done = subprocess.run(["/bin/sh", "-c", command], capture_output=True, text=True, timeout=60, cwd=str(self.tmp),
                              env={"HOME": str(self.home), "PATH": ":".join(path_entries) + ":/usr/bin:/bin", "MISE_DATA_DIR": str(self.data),
                                   "XDG_CONFIG_HOME": str(self.home / ".config"), "XDG_STATE_HOME": str(self.tmp / "xdg-state"),
                                   
                                   "MISE_STATE_DIR": str(self.tmp / "state"), "MISE_CACHE_DIR": str(self.tmp / "cache")})
        return done.stdout.strip()

    def test_the_snapshot_holds_the_shims_folder_and_no_versioned_install_folder(self):
        entries = self.snapshot()
        self.assertIn(str(self.data / "shims"), entries)
        self.assertEqual([e for e in entries if "/installs/" in e], [])

    def test_the_op_shim_and_the_gh_wrapper_are_ahead_of_the_shims_in_the_snapshot(self):
        entries = self.snapshot()
        shims = entries.index(str(self.data / "shims"))
        self.assertLess(entries.index(str(self.home / ".local/share/op-shim")), shims)
        self.assertLess(entries.index(str(self.home / ".local/share/gh-wrapper/bin")), shims)
        self.assertEqual(self.run_with(entries, "op"), "guard-op")
        self.assertEqual(self.run_with(entries, "gh"), "wrapper-gh")

    def test_a_snapshot_taken_before_a_pin_bump_runs_the_new_version_after_it(self):
        entries = self.snapshot()
        self.assertEqual(self.run_with(entries, "node"), "real-node-1.0.0")
        self.pin("2.0.0")
        self.assertEqual(self.run_with(entries, "node"), "real-node-2.0.0")

    def test_a_persons_terminal_keeps_full_activation_with_the_op_shim_first(self):
        entries = self.terminal()
        install = str(self.data / "installs" / "node" / "1.0.0" / "bin")
        self.assertIn(install, entries)   # full activation: the versioned folder is on PATH
        self.assertLess(entries.index(str(self.home / ".local/share/op-shim")), entries.index(install))
        self.assertEqual(self.run_with(entries, "op"), "guard-op")
        self.assertEqual(self.run_with(entries, "node"), "real-node-1.0.0")


if __name__ == "__main__":
    unittest.main()
