"""Black-box tests for the 1Password token export in dot_zshenv.

    python3 -m unittest discover -s tests/zshenv-op-token -v

Each test runs a real non-interactive `zsh -c`, the kind of shell T3, Claude Code and launchd jobs
start, with HOME set to a temporary directory holding dot_zshenv as ~/.zshenv. No real token or
1Password account is used.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ZSHENV = ROOT / "dot_zshenv"
ZPROFILE = ROOT / "dot_zprofile"
SHIM = ROOT / ".chezmoitemplates/op-shim-connect"
FAKE_TOKEN = "ops_fake-token-for-the-zshenv-test"
ZSH = shutil.which("zsh")


@unittest.skipUnless(ZSH, "zsh is not installed")
class ZshenvOpToken(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="zshenv-op-"))
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        shutil.copy(ZSHENV, self.home / ".zshenv")
        self.token_file = self.home / ".config/agent-harness/op-service-token"
        self.token_file.parent.mkdir(parents=True)

    def token_in_shell(self, inherited=None):
        env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        if inherited is not None:
            env["OP_SERVICE_ACCOUNT_TOKEN"] = inherited
        out = subprocess.run(
            [ZSH, "-c", 'printf %s "${OP_SERVICE_ACCOUNT_TOKEN-unset}"'],
            env=env, capture_output=True, text=True, check=True, timeout=30,
        )
        return out.stdout

    def test_non_interactive_shell_gets_the_token_from_the_file(self):
        self.token_file.write_text(FAKE_TOKEN)
        self.assertEqual(self.token_in_shell(), FAKE_TOKEN)

    def test_the_file_wins_over_an_inherited_stale_token(self):
        self.token_file.write_text(FAKE_TOKEN)
        self.assertEqual(self.token_in_shell(inherited="ops_stale"), FAKE_TOKEN)

    def test_no_file_leaves_the_environment_alone(self):
        self.assertEqual(self.token_in_shell(), "unset")
        self.assertEqual(self.token_in_shell(inherited="ops_inherited"), "ops_inherited")


@unittest.skipUnless(ZSH, "zsh is not installed")
class ZshenvOpShim(unittest.TestCase):
    """A fresh non-interactive zsh finds the op shim before any other op, even Homebrew's.

    What the shim does with HOME and the token is tested in tests/pi-op-shim.
    """

    def test_fresh_zsh_resolves_op_to_the_shim_symlink(self):
        home = Path(tempfile.mkdtemp(prefix="zshenv-opshim-"))
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        shutil.copy(ZSHENV, home / ".zshenv")
        shutil.copy(ZPROFILE, home / ".zprofile")
        # As chezmoi deploys it: the shim at ~/.pi/agent/bin/op and the symlink ~/.local/share/op-shim/op.
        (home / ".pi/agent/bin").mkdir(parents=True)
        shutil.copy(SHIM, home / ".pi/agent/bin/op")
        (home / ".pi/agent/bin/op").chmod(0o755)
        link = home / ".local/share/op-shim/op"
        link.parent.mkdir(parents=True)
        link.symlink_to((ROOT / "dot_local/share/op-shim/symlink_op").read_text().strip())
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
        out = subprocess.run([ZSH, "-c", "command -v op"], env=env, capture_output=True, text=True, check=True, timeout=30)
        self.assertEqual(out.stdout.strip(), str(link))
        # Login shells (Claude Code, Codex): on macOS /etc/zprofile's path_helper reorders PATH after .zshenv.
        out = subprocess.run([ZSH, "-lc", "command -v op"], env=env, capture_output=True, text=True, check=True, timeout=30)
        self.assertEqual(out.stdout.strip(), str(link))
        self.assertTrue(link.resolve().samefile(home / ".pi/agent/bin/op"))


if __name__ == "__main__":
    unittest.main()
