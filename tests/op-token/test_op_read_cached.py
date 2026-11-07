"""Black-box tests for dot_local/user_scripts/executable_op_read_cached.sh: the 1Password token guard.

The real script runs as a real process with a fake `op` first on PATH. The fake logs its arguments and answers only when the
token in its environment is the expected one. Checked from outside: exit status, stdout, stderr, and whether op ran at all.
Run: python3 -m unittest discover -s tests/op-token -v
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/user_scripts/executable_op_read_cached.sh"
REF = "op://developer/item/password"
TOKEN = "ops_fake-token-for-tests-only"  # a stand-in service-account token; never a real one
NO_TOKEN = "1Password service account token not set; refusing to use the desktop app (playbook 78819cbd)"
FAKE_OP = '''#!/bin/sh
echo "$*" >> "$FAKE_CALLS"
[ "${OP_SERVICE_ACCOUNT_TOKEN-}" = "$EXPECT_TOKEN" ] || { echo "fake op: not the service account token" >&2; exit 1; }
printf 'secret-value'
'''


class OpReadCached(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="op-token-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin, self.home = self.tmp / "bin", self.tmp / "home"
        self.bin.mkdir()
        self.home.mkdir()
        self.calls = self.tmp / "op-calls"
        (self.bin / "op").write_text(FAKE_OP)
        (self.bin / "op").chmod(0o755)

    def run_script(self, *args, token_env=None, token_file=None):
        """token_env: the OP_SERVICE_ACCOUNT_TOKEN value to set (None: unset). token_file: the token file's text, if any."""
        if token_file is not None:
            (self.home / ".config/agent-harness").mkdir(parents=True, exist_ok=True)
            (self.home / ".config/agent-harness/op-service-token").write_text(token_file)
        env = {"PATH": "%s:/usr/bin:/bin" % self.bin, "HOME": str(self.home), "OP_READ_CACHE_DIR": str(self.tmp / "cache"),
               "XDG_STATE_HOME": str(self.tmp / "state"), "FAKE_CALLS": str(self.calls), "EXPECT_TOKEN": TOKEN}
        if token_env is not None:
            env["OP_SERVICE_ACCOUNT_TOKEN"] = token_env
        return subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)

    def op_calls(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def test_no_token_refuses_with_the_exact_message_and_op_never_runs(self):
        done = self.run_script(REF)
        self.assertEqual(done.returncode, 69, done.stderr)
        self.assertEqual(done.stdout, "")
        self.assertIn(NO_TOKEN, done.stderr)
        self.assertEqual(self.op_calls(), [], "op was never run, so it could not fall back to the desktop app")

    def test_no_token_refuses_an_empty_environment_variable_too(self):
        done = self.run_script(REF, token_env="")
        self.assertEqual(done.returncode, 69, done.stderr)
        self.assertEqual(self.op_calls(), [])

    def test_the_token_in_the_environment_is_used(self):
        done = self.run_script(REF, token_env=TOKEN)
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertEqual(self.op_calls(), ["read %s --no-newline" % REF])

    def test_the_token_from_the_file_is_used_when_the_environment_has_none(self):
        done = self.run_script(REF, token_env="", token_file=TOKEN + "\n")
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertEqual(self.op_calls(), ["read %s --no-newline" % REF])
        self.assertNotIn(TOKEN, done.stdout + done.stderr)

    def test_no_token_serves_a_stale_cached_value_and_still_never_calls_op(self):
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)  # a miss: caches the value
        cache = next((self.tmp / "cache").iterdir())
        old = os.stat(cache).st_mtime - 3 * 24 * 3600  # three days old: past the 12 h TTL, so a miss
        os.utime(cache, (old, old))
        self.calls.unlink()
        done = self.run_script(REF, token_env="")
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertIn(NO_TOKEN, done.stderr)
        self.assertEqual(self.op_calls(), [], "op was not run")

    def records(self):
        path = self.tmp / "state/agent-harness/op-read-cached.jsonl"
        return path.read_text().splitlines() if path.exists() else []

    def test_a_refusal_is_recorded_with_the_reference_and_no_value(self):
        done = self.run_script(REF)
        self.assertEqual(done.returncode, 69)
        lines = self.records()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn('"event":"refused"', lines[0])
        self.assertIn('"ref":"%s"' % REF, lines[0])
        self.assertNotIn("secret-value", lines[0])

    def test_a_stale_serve_is_recorded_as_stale_served(self):
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)
        cache = next((self.tmp / "cache").iterdir())
        old = os.stat(cache).st_mtime - 3 * 24 * 3600
        os.utime(cache, (old, old))
        self.assertEqual(self.run_script(REF, token_env="").returncode, 0)
        self.assertEqual([l for l in self.records() if "stale-served" in l].__len__(), 1, self.records())
        self.assertNotIn("secret-value", "\n".join(self.records()))

    def test_a_fresh_cache_hit_needs_no_op_and_no_token(self):
        self.assertEqual(self.run_script(REF, token_env=TOKEN).returncode, 0)  # a miss: reads and caches the value
        done = self.run_script(REF, token_env="")
        self.assertEqual((done.returncode, done.stdout), (0, "secret-value"), done.stderr)
        self.assertEqual(len(self.op_calls()), 1, "the hit did not call op again")


if __name__ == "__main__":
    unittest.main()
