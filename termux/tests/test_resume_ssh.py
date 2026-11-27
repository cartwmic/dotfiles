"""Drive the phone-owned resume-ssh script with a fake `am` (Android activity manager)."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "bin/executable_resume-ssh"


def run(root, *args, am_status=0):
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "pidof").write_text("#!/bin/sh\nexit 0\n")  # sshd is already running
    (bin_dir / "am").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$AM_LOG\"\nexit {am_status}\n")
    for script in bin_dir.iterdir():
        script.chmod(0o700)
    env = {**os.environ, "HOME": str(root), "PATH": f"{bin_dir}:{os.environ['PATH']}", "AM_LOG": str(root / "am.log")}
    env.pop("XDG_STATE_HOME", None)
    return subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def records(root):
    return [json.loads(line) for line in (root / ".local/state/resume-ssh/log.jsonl").read_text().splitlines()]


class ResumeSshTest(unittest.TestCase):
    def test_each_tab_opens_a_plain_ssh_login_shell_and_is_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            done = run(root)
            self.assertEqual(done.returncode, 0, done.stderr)
            calls = (root / "am.log").read_text().splitlines()
            self.assertEqual(len(calls), 2)
            for call, host in zip(calls, ("macbook", "mac-kvm")):
                # The ssh argument list is just the host: no remote command, so ssh opens a login shell.
                self.assertIn(f"--esa com.termux.RUN_COMMAND_ARGUMENTS {host} ", call + " ")
                self.assertIn(f"--es com.termux.RUN_COMMAND_SHELL_NAME {host} ", call)
                self.assertNotIn("herdr", call)
            log = records(root)
            self.assertEqual([(r["action"], r["detail"], r["exit"]) for r in log],
                             [("resume-ssh.tab", "ssh macbook", 0), ("resume-ssh.tab", "ssh mac-kvm", 0)])

    def test_a_failed_tab_stops_the_run_and_the_log_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            done = run(root, am_status=7)
            self.assertEqual(done.returncode, 7)
            self.assertEqual(len((root / "am.log").read_text().splitlines()), 1)
            self.assertEqual([(r["detail"], r["exit"]) for r in records(root)], [("ssh macbook", 7)])

    def test_arguments_are_refused_and_logged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            done = run(root, "x")
            self.assertEqual(done.returncode, 2)
            self.assertFalse((root / "am.log").exists())
            self.assertEqual([(r["action"], r["exit"]) for r in records(root)], [("resume-ssh.refused", 2)])


if __name__ == "__main__":
    unittest.main()
