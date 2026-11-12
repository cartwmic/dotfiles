"""The T3 pi-lead wrapper (dot_local/user_scripts/executable_pi_lead.sh), run with a stub `pi` on PATH in a scratch HOME.

    python3 -m unittest discover -s tests/pi-lead -v
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

WRAPPER = Path(os.environ.get("PI_LEAD_UNDER_TEST") or Path(__file__).resolve().parents[2] / "dot_local/user_scripts/executable_pi_lead.sh")
STUB = '#!/bin/sh\nprintf "path=%s\\nstate=%s\\nwhich=%s\\n" "$PATH" "${COORDINATOR_STATE_DIR-unset}" "$0"\nfor a in "$@"; do printf "arg=<%s>\\n" "$a"; done\n'


class WrapperTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home"
        (self.home / ".local/share/coordinator/pane-bin").mkdir(parents=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()

    def stub(self, directory, body=STUB):
        directory.mkdir(parents=True, exist_ok=True)
        f = directory / "pi"
        f.write_text(body)
        f.chmod(0o755)
        return f

    def run_wrapper(self, *args, path=None, extra_env=None):
        env = {"HOME": str(self.home), "PATH": path if path is not None else "%s:/usr/bin:/bin" % self.bin, **(extra_env or {})}
        return subprocess.run(["/bin/sh", str(WRAPPER), *args], capture_output=True, text=True, env=env, timeout=30)

    def test_args_pass_unchanged_and_the_environment_is_set(self):
        self.stub(self.bin)
        args = ["--mode", "rpc", "--no-session", "--offline", "--extension", "/a b/ext.js", "", "x'y", "$HOME"]
        r = self.run_wrapper(*args)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual([l for l in lines if l.startswith("arg=")], ["arg=<%s>" % a for a in args])
        state = self.home / ".local/share/coordinator"
        self.assertIn("state=%s" % state, lines)
        path = next(l for l in lines if l.startswith("path="))[len("path="):]
        self.assertTrue(path.startswith("%s/pane-bin:%s:" % (state, self.bin)), path)

    def test_the_real_pi_is_the_one_on_the_inherited_path(self):
        """A pi in pane-bin must not shadow the real one; the wrapper runs the first pi on the PATH it was given."""
        self.stub(self.bin)
        self.stub(self.home / ".local/share/coordinator/pane-bin", "#!/bin/sh\necho shadow\n")
        r = self.run_wrapper("--version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("which=%s" % (self.bin / "pi"), r.stdout.splitlines())
        self.assertNotIn("shadow", r.stdout)

    def test_pane_bin_commands_resolve_for_the_agent(self):
        self.stub(self.bin, '#!/bin/sh\ncommand -v ledger\n')
        ledger = self.home / ".local/share/coordinator/pane-bin/ledger"
        ledger.write_text("#!/bin/sh\n")
        ledger.chmod(0o755)
        r = self.run_wrapper()
        self.assertEqual(r.stdout.strip(), str(ledger))

    def test_exit_status_comes_from_pi(self):
        self.stub(self.bin, "#!/bin/sh\nexit 7\n")
        self.assertEqual(self.run_wrapper().returncode, 7)

    def test_missing_pi_is_127_with_a_message(self):
        r = self.run_wrapper(path=str(self.tmp / "empty"))
        self.assertEqual(r.returncode, 127)
        self.assertIn("pi not found", r.stderr)


if __name__ == "__main__":
    unittest.main()
