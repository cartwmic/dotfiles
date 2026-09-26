"""Keep the phone proof's remote command independent of interactive shell PATH."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "bin/executable_herdr-overview-proof"


class HerdrOverviewProofTest(unittest.TestCase):
    def test_remote_phone_client_uses_desktop_mise_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_ssh = root / "ssh"
            fake_ssh.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$SSH_ARGS"\nexit 1\n')
            fake_ssh.chmod(0o700)
            args_path = root / "ssh-args"
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"], SSH_ARGS=str(args_path))
            result = subprocess.run(
                ["/bin/sh", str(SCRIPT), "a" * 16, "macbook"],
                env=env, text=True, capture_output=True, timeout=5,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn('"status":"BLOCKED"', result.stdout)
            command = args_path.read_text().splitlines()[-1]
            self.assertIn('PATH="$HOME/.local/share/mise/shims:$PATH"', command)
            self.assertIn('"$HOME/.local/share/mise/shims/python3"', command)
            self.assertIn("phone-client --run-id " + "a" * 16, command)

    def test_adb_types_absolute_phone_helper_with_android_space_encoding(self):
        driver = Path(__file__).resolve().parents[2] / "tests/herdr-overview/proof.py"
        spec = importlib.util.spec_from_file_location("herdr_overview_proof", driver)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        commands = []

        def fake_run_process(command, **_kwargs):
            commands.append(command)
            if command[-1] == "get-state":
                return subprocess.CompletedProcess(command, 0, "device\n", "")
            if "pm" in command:
                return subprocess.CompletedProcess(command, 0, "package:/termux.apk\n", "")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(module.shutil, "which", return_value="/usr/bin/adb"), \
             patch.object(module, "run_process", side_effect=fake_run_process), \
             patch.object(module.time, "sleep"):
            module.maybe_start_adb("emulator-5580", "a" * 16)
        self.assertEqual(commands[-2], [
            "/usr/bin/adb", "-s", "emulator-5580", "shell", "input", "text",
            "/data/data/com.termux/files/home/bin/herdr-overview-proof%s" + "a" * 16 + "%smacbook",
        ])
        self.assertEqual(commands[-1][-2:], ["keyevent", "66"])


if __name__ == "__main__":
    unittest.main()
