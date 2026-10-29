#!/usr/bin/env python3
"""Black-box proof that a real Pi runs the op shim: the installed Pi (RPC mode) with a scripted model, a scratch HOME and agent dir.

The shim is installed as <agent dir>/bin/op, where chezmoi puts it (~/.pi/agent/bin/op). A fake op sits on Pi's own PATH;
it records each call's HOME, arguments and whether it got the test's fake token. No real op, token or 1Password account is
used; nothing under ~/.pi is read or written. Needs `pi` on PATH; takes about 10 seconds.

    python3 tests/pi-op-shim/proof.py

Checks, each from what the fake op recorded:
  1. the model's bash tool: with the token file, op runs with an empty HOME and the service-account token;
  2. a user `!` command (RPC "bash", the same path as `!` in the TUI): the same;
  3. without the token file, both paths run op unchanged (the real HOME, no token);
  4. Pi's own process PATH (what a terminal outside Pi has) resolves op to the fake, not the shim.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHIM = HERE.parents[1] / "dot_pi/private_agent/bin/executable_op"
PROVIDER = HERE / "scripted_provider.ts"
FAKE_TOKEN = "ops_fake-token-for-the-shim-proof"

FAKE_OP = """#!/bin/sh
if [ "${OP_SERVICE_ACCOUNT_TOKEN-unset}" = unset ]; then t=unset
elif [ "$OP_SERVICE_ACCOUNT_TOKEN" = "$FAKE_TOKEN_EXPECTED" ]; then t=the-test-token
else t=other; fi
printf '%s\t%s\t%s\n' "$1" "$HOME" "$t" >> "$FAKE_OP_OUT"
echo "fake op ran: $1"
"""


class Pi:
    """One RPC-mode Pi process; send() writes a command and returns its response, collecting events on the way."""

    def __init__(self, work: Path, env: dict):
        self.proc = subprocess.Popen(
            ["pi", "--no-extensions", "-e", str(PROVIDER), "--provider", "scripted", "--model", "scripted-1",
             "--no-approve", "--no-session", "--mode", "rpc"],
            cwd=work, env=env, text=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.next_id = 0

    def read(self) -> dict:
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise SystemExit("pi exited early")
            if line.startswith("{"):
                return json.loads(line)

    def send(self, command: dict) -> dict:
        self.next_id += 1
        command = {"id": str(self.next_id), **command}
        self.proc.stdin.write(json.dumps(command) + "\n")
        self.proc.stdin.flush()
        while True:
            event = self.read()
            if event.get("type") == "response" and event.get("id") == command["id"]:
                assert event.get("success"), event
                return event

    def prompt(self, text: str) -> None:
        self.send({"type": "prompt", "message": text})
        while self.read().get("type") != "agent_end":
            pass

    def close(self) -> None:
        self.proc.stdin.close()
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="pi-op-shim-proof-"))
    pi = None
    try:
        home = work / "home"
        agent_dir = home / ".pi/agent"
        (agent_dir / "bin").mkdir(parents=True)
        shutil.copy(SHIM, agent_dir / "bin/op")
        (agent_dir / "bin/op").chmod(0o755)
        token = home / ".config/agent-harness/op-service-token"
        token.parent.mkdir(parents=True)
        token.write_text(FAKE_TOKEN + "\n")
        token.chmod(0o600)
        fake_dir = work / "fake-bin"
        fake_dir.mkdir()
        (fake_dir / "op").write_text(FAKE_OP)
        (fake_dir / "op").chmod(0o755)
        out = work / "op-calls.tsv"
        tmpdir = work / "tmp"
        tmpdir.mkdir()
        script = work / "script.json"
        env = {k: v for k, v in os.environ.items() if not k.startswith("OP_")}
        env.update({"HOME": str(home), "TMPDIR": str(tmpdir), "PATH": f"{fake_dir}{os.pathsep}{os.environ['PATH']}",
                    "PI_CODING_AGENT_DIR": str(agent_dir), "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1",
                    "PI_TELEMETRY": "0", "SCRIPTED_MODEL_SCRIPT": str(script),
                    "FAKE_OP_OUT": str(out), "FAKE_TOKEN_EXPECTED": FAKE_TOKEN})

        outside = subprocess.run(["sh", "-c", "command -v op"], env=env, text=True, capture_output=True).stdout.strip()
        assert outside == str(fake_dir / "op"), f"Pi's own PATH should not reach the shim: {outside}"

        for phase in ("with-token", "without-token"):
            if phase == "without-token":
                token.unlink()
            script.write_text(json.dumps({"turns": [
                {"call": {"name": "bash", "arguments": {"command": f"op tool-call-{phase}"}}}, {"text": "done"}]}))
            pi = Pi(work, env)
            pi.prompt("go")
            bang = pi.send({"type": "bash", "command": f"op bang-{phase}"})
            assert f"fake op ran: bang-{phase}" in bang["data"]["output"], bang
            pi.close()

        calls = {name: (h, t) for name, h, t in (line.split("\t") for line in out.read_text().splitlines())}
        assert set(calls) == {"tool-call-with-token", "bang-with-token", "tool-call-without-token", "bang-without-token"}, calls
        for name in ("tool-call-with-token", "bang-with-token"):
            op_home, got = calls[name]
            assert got == "the-test-token" and op_home != str(home), (name, calls[name])
            assert Path(op_home).parent == tmpdir and not any(Path(op_home).iterdir()), (name, op_home)
        print("ok 1: the model's bash tool ran op through the shim: empty HOME, service-account token")
        print("ok 2: a user ! command ran op through the shim: empty HOME, service-account token")
        for name in ("tool-call-without-token", "bang-without-token"):
            assert calls[name] == (str(home), "unset"), (name, calls[name])
        print("ok 3: without the token file both ran op unchanged (real HOME, no token)")
        print("ok 4: Pi's own PATH (a terminal outside Pi) resolves op to the real one, not the shim")
        print("PASS")
        return 0
    finally:
        if pi and pi.proc.poll() is None:
            pi.proc.kill()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
