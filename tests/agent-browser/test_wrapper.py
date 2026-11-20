"""~/.local/bin/browse (dot_local/bin/executable_browse): the real wrapper in a scratch HOME with a fake mise shim.
The last case is the gap it closes: a non-interactive `bash -c` started from a zsh that has only what ~/.zshenv gives it (the Mac agent shell: ~/.local/bin,
no mise shims, no mise install directory) must find `browse`. It uses the real ~/.zshenv from this source."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "dot_local/bin/executable_browse"
ZSHENV = ROOT / "dot_zshenv"
SHIM = '#!/bin/sh\necho "shim $*"\n[ "$1" = --version ] && echo 0.1.0\nenv | grep -q "^BROWSE_PATH_WRAPPER=" && echo guard-set\nexit 7\n'
BARE_PATH = "/usr/local/bin:/usr/bin:/bin"   # no mise anywhere on it


class WrapperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="browse-wrapper-test-")
        self.home = Path(self.tmp.name)
        (self.home / ".local/bin").mkdir(parents=True)
        self.wrapper = self.home / ".local/bin/browse"
        self.wrapper.write_text(WRAPPER.read_text())
        self.wrapper.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def shim(self, body=SHIM):
        p = self.home / ".local/share/mise/shims/browse"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
        p.chmod(0o755)

    def env(self, **extra):
        return dict({"HOME": str(self.home), "PATH": BARE_PATH}, **extra)

    def test_it_runs_the_shim_with_the_same_arguments_and_exit_code(self):
        self.shim()
        r = subprocess.run([str(self.wrapper), "pair", "--wait-seconds", "5"], env=self.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout.splitlines()[0]), (7, "shim pair --wait-seconds 5"), r.stderr)

    def test_a_missing_shim_exits_127_and_names_the_fix(self):
        r = subprocess.run([str(self.wrapper), "--version"], env=self.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 127)
        self.assertIn("mise install", r.stderr)

    def test_a_shim_that_lands_back_on_the_wrapper_stops_instead_of_looping(self):
        # mise's shim searches PATH when it cannot resolve the tool, and finds ~/.local/bin/browse again.
        self.shim('#!/bin/sh\nexec "$HOME/.local/bin/browse" "$@"\n')
        r = subprocess.run([str(self.wrapper), "--version"], env=self.env(), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 127, r.stdout + r.stderr)
        self.assertIn("mise did not resolve browse", r.stderr)

    def test_a_non_interactive_bash_started_from_zsh_with_only_zshenv_finds_browse(self):
        self.shim()
        (self.home / ".zshenv").write_text(ZSHENV.read_text())
        r = subprocess.run(["zsh", "-c", "bash -c 'browse --version'"], env={"HOME": str(self.home), "PATH": BARE_PATH, "ZDOTDIR": str(self.home)},
                           capture_output=True, text=True, timeout=60)
        self.assertIn("0.1.0", r.stdout.splitlines(), r.stdout + r.stderr)

    def test_without_the_wrapper_that_same_shell_cannot_find_browse(self):   # the failure the wrapper fixes, so the case above can fail
        self.shim()
        self.wrapper.unlink()
        (self.home / ".zshenv").write_text(ZSHENV.read_text())
        only = self.home / "only-zsh-and-bash"   # a PATH that holds nothing but the two shells, so no `browse` on the host can be found
        only.mkdir()
        for tool in ("zsh", "bash"):
            (only / tool).symlink_to(shutil.which(tool))
        r = subprocess.run([str(only / "zsh"), "-c", "bash -c 'browse --version'"], env={"HOME": str(self.home), "PATH": str(only), "ZDOTDIR": str(self.home)},
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 127, r.stdout + r.stderr)
        self.assertIn("browse", r.stderr)   # the shell names the command it could not find
        self.assertNotIn("0.1.0", r.stdout)


if __name__ == "__main__":
    unittest.main()
