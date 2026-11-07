"""resolve_secret in dot_local/user_scripts/executable_apply_harness_config.sh: the service-account token guard.

The apply script does its work at top level, so this seam test takes its two functions (log_error and resolve_secret) from
the file as text and runs them in sh, with a fake op first on PATH that records each call. Checked: the return status, what
went to stdout, what went to stderr, and whether op ran. The helper's real run (chezmoi apply) is not exercised here.
Run: python3 -m unittest discover -s tests/op-token -v
"""
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLY = ROOT / "dot_local/user_scripts/executable_apply_harness_config.sh"
REF = "op://developer/item/password"
TOKEN = "ops_fake-token-for-tests-only"  # a stand-in service-account token; never a real one
NO_TOKEN = "1Password service account token not set; refusing to use the desktop app (playbook 78819cbd)"
FAKE_OP = '''#!/bin/sh
echo "$*" >> "$FAKE_CALLS"
[ "${OP_SERVICE_ACCOUNT_TOKEN-}" = "$EXPECT_TOKEN" ] || { echo "fake op: no service account token" >&2; exit 1; }
printf 'secret-value'
'''


def function_text(name):
    text = APPLY.read_text()
    m = re.search(r"^%s\(\) \{\n.*?^\}\n" % re.escape(name), text, re.S | re.M)
    assert m, "function %s not found in the script" % name
    return m.group(0)


class ResolveSecret(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="apply-secret-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin, self.home = self.tmp / "bin", self.tmp / "home"
        self.bin.mkdir()
        self.home.mkdir()
        (self.bin / "op").write_text(FAKE_OP)
        (self.bin / "op").chmod(0o755)
        self.calls = self.tmp / "op-calls"
        self.harness = self.tmp / "harness.sh"
        self.harness.write_text('SCRIPT_NAME=apply_harness_config\n' + function_text("log_error") + function_text("resolve_secret")
                                + 'resolve_secret "$1"\n')

    def run_resolve(self, token_env=None, token_file=None):
        if token_file is not None:
            (self.home / ".config/agent-harness").mkdir(parents=True, exist_ok=True)
            (self.home / ".config/agent-harness/op-service-token").write_text(token_file)
        env = {"PATH": "%s:/usr/bin:/bin" % self.bin, "HOME": str(self.home), "FAKE_CALLS": str(self.calls), "EXPECT_TOKEN": TOKEN}
        if token_env is not None:
            env["OP_SERVICE_ACCOUNT_TOKEN"] = token_env
        return subprocess.run(["sh", str(self.harness), REF], env=env, capture_output=True, text=True, timeout=30)

    def test_no_token_refuses_with_the_message_and_never_calls_op(self):
        done = self.run_resolve()
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertIn(NO_TOKEN, done.stderr)
        self.assertFalse(self.calls.exists(), "op was never run, so it could not fall back to the desktop app")

    def test_an_empty_token_variable_with_no_file_refuses_too(self):
        done = self.run_resolve(token_env="")
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertFalse(self.calls.exists())

    def test_the_token_in_the_environment_reads_the_secret(self):
        done = self.run_resolve(token_env=TOKEN)
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertEqual(self.calls.read_text(), "read %s --no-newline\n" % REF)

    def test_the_token_from_the_file_reads_the_secret(self):
        done = self.run_resolve(token_env="", token_file=TOKEN + "\n")
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertNotIn(TOKEN, done.stdout + done.stderr)


if __name__ == "__main__":
    unittest.main()
