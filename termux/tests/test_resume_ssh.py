"""Drive the phone-owned resume-ssh script with a fake `am` (Android activity manager)."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "bin/executable_resume-ssh"


class ResumeSshTest(unittest.TestCase):
    def test_each_tab_opens_a_plain_ssh_login_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "pidof").write_text("#!/bin/sh\nexit 0\n")  # sshd is already running
            (bin_dir / "am").write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$AM_LOG\"\n")
            for script in bin_dir.iterdir():
                script.chmod(0o700)
            log = root / "am.log"
            env = {**os.environ, "HOME": str(root), "PATH": f"{bin_dir}:{os.environ['PATH']}", "AM_LOG": str(log)}
            done = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            calls = log.read_text().splitlines()
            self.assertEqual(len(calls), 2)
            for call, host in zip(calls, ("macbook", "mac-kvm")):
                # The ssh argument list is just the host: no remote command, so ssh opens a login shell.
                self.assertIn(f"--esa com.termux.RUN_COMMAND_ARGUMENTS {host} ", call + " ")
                self.assertIn(f"--es com.termux.RUN_COMMAND_SHELL_NAME {host} ", call)
                self.assertNotIn("herdr", call)

    def test_arguments_are_refused(self):
        done = subprocess.run(["sh", str(SCRIPT), "x"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
