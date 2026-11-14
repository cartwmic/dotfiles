"""Seeding the Connect token (dot_local/user_scripts/executable_seed_op_connect_token.sh).

    python3 -m unittest discover -s tests/seed-op-connect-token -v

Black-box: the real script runs under sh with a fake op first on PATH. Nothing reaches 1Password. The fake op records each
call (HOME, the token and Connect-variable state, its arguments), never a raw value, and prints a stand-in value for the
Connect token item. The script must never print that value; each failure test checks it. The default token path is the
HOME file the shim reads, so these tests use it and never set OP_CONNECT_TOKEN_FILE. The last test runs the shim on the
seeded file: that proves the bytes the seed writes are the bytes the shim reads. The passwd-home lookup the shim does in
production is proved only by the live check, not here.
"""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "dot_local/user_scripts/executable_seed_op_connect_token.sh"
SHIM = REPO / ".chezmoitemplates/op-shim-connect"
CONNECT_REF = "op://developer/y3x5tr3p2calmede76mmkfdele/credential"
FAKE_SA = "ops_fake-service-token-for-the-seed-tests"  # a stand-in service-account token; never a real one
FAKE_CONNECT = "fake-connect-value-for-the-seed-tests"  # a stand-in Connect token; never a real one
# The tools the script needs. Symlinked into their own directory, so a PATH of only this directory has no op.
UTILS = ["basename", "cat", "chmod", "dirname", "head", "mkdir", "mktemp", "mv", "rm", "tr"]

FAKE_OP = r"""#!/bin/sh
{
  echo call
  printf 'HOME=%s\n' "$HOME"
  if [ "${OP_SERVICE_ACCOUNT_TOKEN-unset}" = unset ]; then echo token=unset
  elif [ "$OP_SERVICE_ACCOUNT_TOKEN" = "$FAKE_SA_EXPECTED" ]; then echo token=match
  else echo token=other; fi
  if [ "${OP_CONNECT_TOKEN-unset}" = unset ]; then echo connect=unset
  elif [ "$OP_CONNECT_TOKEN" = "$FAKE_CONNECT_VALUE" ]; then echo connect=match
  else echo connect=other; fi
  for a in "$@"; do printf 'arg=%s\n' "$a"; done
} >> "$FAKE_OP_LOG"
case "${FAKE_READ_MODE:-ok}" in
  ok) printf '%s' "$FAKE_CONNECT_VALUE" ;;
  empty) ;;
  fail) echo "[ERROR] item not found" >&2; exit 1 ;;
esac
"""


class SeedConnectToken(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="seed-op-connect-"))
        self.home = self.tmp / "home"
        (self.home / ".config/agent-harness").mkdir(parents=True)
        self.token_path = self.home / ".config/agent-harness/op-connect-token"
        self.sa_path = self.home / ".config/agent-harness/op-service-token"
        self.write_service_token()
        self.fake_bin = self.tmp / "fake-bin"
        self.fake_bin.mkdir()
        (self.fake_bin / "op").write_text(FAKE_OP)
        (self.fake_bin / "op").chmod(0o755)
        self.utils = self.tmp / "utils"
        self.utils.mkdir()
        for name in UTILS:
            found = shutil.which(name)
            self.assertIsNotNone(found, name)
            (self.utils / name).symlink_to(found)
        self.log = self.tmp / "op-calls.txt"
        self.tmpdir = self.tmp / "tmp"
        self.tmpdir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_service_token(self):
        self.sa_path.write_text(FAKE_SA + "\n")
        self.sa_path.chmod(0o600)

    def base_env(self, path=None):
        env = {
            "HOME": str(self.home),
            "TMPDIR": str(self.tmpdir),
            "PATH": path or f"{self.fake_bin}:{self.utils}",
            "FAKE_OP_LOG": str(self.log),
            "FAKE_SA_EXPECTED": FAKE_SA,
            "FAKE_CONNECT_VALUE": FAKE_CONNECT,
        }
        return env

    def run_seed(self, env=None, path=None, umask=None):
        full = self.base_env(path)
        full.update(env or {})
        return subprocess.run(["/bin/sh", str(SEED)], env=full, capture_output=True, text=True, timeout=60,
                              preexec_fn=(lambda: os.umask(umask)) if umask is not None else None)

    def calls(self):
        out = []
        if not self.log.exists():
            return out
        current = None
        for line in self.log.read_text().splitlines():
            if line == "call":
                current = {"args": []}
                out.append(current)
                continue
            key, _, value = line.partition("=")
            if key == "arg":
                current["args"].append(value)
            else:
                current[key] = value
        return out

    def assert_no_value_printed(self, result):
        self.assertNotIn(FAKE_CONNECT, result.stdout + result.stderr)
        self.assertNotIn(FAKE_SA, result.stdout + result.stderr)

    def temp_files(self):
        return [p.name for p in self.token_path.parent.glob(".op-connect-token.*")]

    def test_seeds_the_home_token_file_at_mode_0600_with_one_service_account_read_of_the_item(self):
        result = self.run_seed(umask=0o022)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.token_path.read_text(), FAKE_CONNECT + "\n")
        self.assertEqual(stat.S_IMODE(os.stat(self.token_path).st_mode), 0o600)
        calls = self.calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["args"], ["read", CONNECT_REF])
        self.assertEqual((calls[0]["token"], calls[0]["connect"]), ("match", "unset"))
        self.assertNotEqual(calls[0]["HOME"], str(self.home), "the read must not see the caller's home")
        self.assertTrue(calls[0]["HOME"].startswith(str(self.tmpdir)), calls[0]["HOME"])
        self.assert_no_value_printed(result)

    def test_the_success_log_names_the_file_and_never_the_value(self):
        result = self.run_seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("wrote", result.stderr)
        self.assertIn(str(self.token_path), result.stderr)
        self.assert_no_value_printed(result)

    def test_an_existing_token_file_is_kept_and_op_is_not_called(self):
        self.token_path.write_text("previous-value\n")
        self.token_path.chmod(0o600)
        result = self.run_seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.token_path.read_text(), "previous-value\n")
        self.assertEqual(self.calls(), [])

    def test_an_empty_token_file_is_seeded(self):
        self.token_path.write_text("")
        result = self.run_seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.token_path.read_text(), FAKE_CONNECT + "\n")
        self.assertEqual(len(self.calls()), 1)

    def test_the_read_gets_no_connect_variables_even_when_the_caller_has_them(self):
        result = self.run_seed(env={"OP_CONNECT_TOKEN": "caller-connect-value", "OP_CONNECT_HOST": "https://x.test"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0]["connect"], "unset")
        self.assertEqual(self.token_path.read_text(), FAKE_CONNECT + "\n")

    def test_a_service_token_in_the_environment_is_used_when_the_token_file_is_absent(self):
        self.sa_path.unlink()
        result = self.run_seed(env={"OP_SERVICE_ACCOUNT_TOKEN": FAKE_SA})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0]["token"], "match")

    def test_no_service_token_warns_exits_0_and_writes_nothing(self):
        self.sa_path.unlink()
        result = self.run_seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARN", result.stderr)
        self.assertIn("Connect token not seeded", result.stderr)
        self.assertFalse(self.token_path.exists())
        self.assertEqual(self.calls(), [])

    def test_no_op_on_path_warns_exits_0_and_writes_nothing(self):
        result = self.run_seed(path=str(self.utils))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WARN", result.stderr)
        self.assertFalse(self.token_path.exists())

    def test_a_failed_read_exits_1_names_the_error_and_writes_nothing(self):
        result = self.run_seed(env={"FAKE_READ_MODE": "fail"})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("WARN", result.stderr)
        self.assertIn("item not found", result.stderr)
        self.assertFalse(self.token_path.exists())
        self.assertEqual(self.temp_files(), [])
        self.assert_no_value_printed(result)

    def test_an_empty_read_exits_1_and_writes_nothing(self):
        result = self.run_seed(env={"FAKE_READ_MODE": "empty"})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("no value", result.stderr)
        self.assertFalse(self.token_path.exists())
        self.assertEqual(self.temp_files(), [])

    def test_a_run_leaves_no_temp_file_or_work_dir_behind(self):
        result = self.run_seed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.temp_files(), [])
        self.assertEqual(list(self.tmpdir.iterdir()), [])

    def test_the_file_it_writes_is_the_file_the_shim_reads_for_connect(self):
        seeded = self.run_seed()
        self.assertEqual(seeded.returncode, 0, seeded.stderr)
        env = self.base_env(path=f"{self.fake_bin}:{self.utils}:/usr/bin:/bin")
        env["OP_CONNECT_TOKEN_FILE"] = str(self.token_path)
        result = subprocess.run(["/bin/sh", str(SHIM), "read", CONNECT_REF], env=env, capture_output=True, text=True,
                                timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, FAKE_CONNECT)
        last = self.calls()[-1]
        self.assertEqual((last["connect"], last["token"]), ("match", "unset"))


if __name__ == "__main__":
    unittest.main()
