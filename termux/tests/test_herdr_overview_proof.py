"""Keep the phone proof's remote command independent of interactive shell PATH."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
