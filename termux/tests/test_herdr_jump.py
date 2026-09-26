"""Drive the phone-owned jump script through its CLI with a fake SSH transport."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "bin/executable_herdr-jump"


class HerdrJumpTest(unittest.TestCase):
    def test_work_and_personal_routes_and_fail_closed_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "timeout").write_text("#!/bin/sh\nshift\nexec \"$@\"\n")
            (bin_dir / "ssh").write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$SSH_ARGS\"\nexit \"${SSH_STATUS:-0}\"\n")
            for script in bin_dir.iterdir():
                script.chmod(0o700)
            args_file = root / "args"
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"], SSH_ARGS=str(args_file))

            def run(*args, status="0"):
                args_file.unlink(missing_ok=True)
                return subprocess.run(["/bin/sh", str(SCRIPT), *args], capture_output=True,
                                      text=True, env=dict(env, SSH_STATUS=status), timeout=5)

            work = run("term_abcd", "mac-kvm")
            self.assertEqual(work.returncode, 0, work.stderr)
            arguments = args_file.read_text().splitlines()
            self.assertEqual(arguments[-2:], ["mac-kvm", "herdr-jump term_abcd"])
            self.assertIn("-T", arguments)
            self.assertIn("RequestTTY=no", arguments)
            self.assertEqual(run("term_abcd", "mac-kvm", status="9").returncode, 9)

            personal = run("term_abcd", "macbook")
            self.assertEqual(personal.returncode, 0, personal.stderr)
            self.assertEqual(args_file.read_text().splitlines()[-2], "macbook")
            self.assertIn("herdr-agent-jump 'term_abcd'", args_file.read_text())
            self.assertEqual(run("term_abcd").returncode, 0)
            self.assertEqual(args_file.read_text().splitlines()[-2], "remote")
            for bad in (("term_ABCD", "mac-kvm"), ("term_abcd", "-oProxyCommand"),
                        ("term_abcd", "host.example"), ("term_" + "a" * 65, "mac-kvm")):
                self.assertNotEqual(run(*bad).returncode, 0, bad)
                self.assertFalse(args_file.exists(), bad)


if __name__ == "__main__":
    unittest.main()
