"""Shared harness for tests/pi-op-shim/test_op_shim_connect*.py (not a test module itself).

The real shim runs as a process. A fake op is first on PATH after the shim's own directory. For each call it appends a block
to FAKE_OP_LOG: a 'call' line, then key=value lines (HOME, cwd, token, connect, connect_host, stdin), then one arg= line per
argument. The token and Connect token are recorded as match, other or unset, never as a value. FAKE_CONNECT_MODE says what a
call with a Connect token does: ok (print FAKE_CONNECT_OUT), fail (print FAKE_CONNECT_PARTIAL, an error, exit
FAKE_CONNECT_EXIT) or hang (sleep). A call without one prints FAKE_SA_OUT and exits FAKE_SA_EXIT.

Every test points OP_CONNECT_TOKEN_FILE at a file that does not exist unless the test writes one, so the real home's
token file never reaches a test. No real op, token or 1Password account is used.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SHIM = Path(__file__).resolve().parents[2] / "dot_pi/private_agent/bin/executable_op"
FAKE_SA = "ops_fake-service-token-for-the-connect-tests"  # a stand-in service-account token; never a real one
FAKE_CONNECT = "fake-connect-token-for-the-connect-tests"  # a stand-in Connect token; never a real one
DEFAULT_HOST = "https://op-connect.internal.cartwmic.com"

FAKE_OP = r"""#!/bin/sh
{
  echo call
  printf 'HOME=%s\n' "$HOME"
  printf 'pid=%s\n' "$$"
  printf 'cwd=%s\n' "$(pwd -P)"
  if [ "${OP_SERVICE_ACCOUNT_TOKEN-unset}" = unset ]; then echo token=unset
  elif [ "$OP_SERVICE_ACCOUNT_TOKEN" = "$FAKE_SA_EXPECTED" ]; then echo token=match
  else echo token=other; fi
  if [ "${OP_CONNECT_TOKEN-unset}" = unset ]; then echo connect=unset
  elif [ "$OP_CONNECT_TOKEN" = "$FAKE_CONNECT_EXPECTED" ]; then echo connect=match
  else echo connect=other; fi
  printf 'connect_host=%s\n' "${OP_CONNECT_HOST-}"
  for a in "$@"; do printf 'arg=%s\n' "$a"; done
  if [ -n "${FAKE_OP_READ_STDIN-}" ]; then printf 'stdin=%s\n' "$(cat)"; fi
} >> "$FAKE_OP_LOG"
if [ -n "${OP_CONNECT_TOKEN-}" ]; then
  case "${FAKE_CONNECT_MODE:-ok}" in
    ok) printf '%s' "${FAKE_CONNECT_OUT:-from-connect}"; exit 0 ;;
    fail)
      printf '%s' "${FAKE_CONNECT_PARTIAL-}"
      echo "[ERROR] ${FAKE_CONNECT_ERROR:-connection refused}" >&2
      exit "${FAKE_CONNECT_EXIT:-1}" ;;
    hang) exec sleep 30 ;;
  esac
fi
printf '%s' "${FAKE_SA_OUT:-from-service-account}"
exit "${FAKE_SA_EXIT:-0}"
"""


class ShimCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="op-shim-connect-"))
        self.home = self.tmp / "home"
        (self.home / ".config/agent-harness").mkdir(parents=True)
        self.bin = self.home / ".pi/agent/bin"  # the shim as chezmoi deploys it
        self.bin.mkdir(parents=True)
        self.shim = self.bin / "op"
        shutil.copy(SHIM, self.shim)
        self.shim.chmod(0o755)
        self.real_dir = self.tmp / "real-bin"
        self.real_dir.mkdir()
        fake = self.real_dir / "op"
        fake.write_text(FAKE_OP)
        fake.chmod(0o755)
        self.log = self.tmp / "calls.txt"
        self.tmpdir = self.tmp / "tmpdir"
        self.tmpdir.mkdir()
        self.caller = self.tmp / "caller"
        self.caller.mkdir()
        self.absent_connect_file = self.tmp / "no-connect-token-here"
        self.fallback_log = self.tmp / "state" / "connect-fallback.log"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_service_token(self):
        token = self.home / ".config/agent-harness/op-service-token"
        token.write_text(FAKE_SA + "\n")
        token.chmod(0o600)

    def write_connect_file(self, value=FAKE_CONNECT):
        path = self.tmp / "connect-token-file"
        path.write_text(value + "\n")
        path.chmod(0o600)
        return path

    def shim_env(self, env=None):
        base = {
            "HOME": str(self.home),
            "TMPDIR": str(self.tmpdir),
            "PATH": f"{self.bin}:{self.real_dir}:/usr/bin:/bin",  # Pi's order: its bin first, then the fake op
            "FAKE_OP_LOG": str(self.log),
            "FAKE_SA_EXPECTED": FAKE_SA,
            "FAKE_CONNECT_EXPECTED": FAKE_CONNECT,
            "OP_CONNECT_TOKEN_FILE": str(self.absent_connect_file),
            "OP_CONNECT_FALLBACK_LOG": str(self.fallback_log),
        }
        base.update(env or {})
        return base

    def run_shim(self, args, env=None, stdin=None, cwd=None):
        return subprocess.run(["op", *args], env=self.shim_env(env), input=stdin, cwd=cwd, capture_output=True, text=True, timeout=60)

    def calls(self):
        """Each op call the fake recorded, in order, as a dict: its keys and its args list."""
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

    def op_home(self):
        return os.path.realpath(self.tmpdir / f"pi-op-home-{os.getuid()}")

    def assert_no_secret_in_output(self, result):
        self.assertNotIn(FAKE_SA, result.stdout + result.stderr)
        self.assertNotIn(FAKE_CONNECT, result.stdout + result.stderr)
