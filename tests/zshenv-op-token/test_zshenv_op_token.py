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

ZSHENV = Path(__file__).resolve().parents[2] / "dot_zshenv"
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


if __name__ == "__main__":
    unittest.main()
