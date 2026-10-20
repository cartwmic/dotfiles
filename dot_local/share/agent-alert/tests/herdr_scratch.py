"""A scratch Herdr 0.9.1 server for the agent-alert tests that need a real pane.

Used only by test_docs.py (the README's pane procedure). Everything lives in a scratch HOME and
sockets under /tmp; the live Herdr is never addressed.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import common

HERDR_REQUIRED = shutil.which("herdr") is not None


def adapter_copy():
    """The deployed-layout copy of the tree (adapters/ kept)."""
    return common.deployed_copy(delete_adapters=False)


class ScratchHerdr:
    """One real Herdr 0.9.1 server with its own HOME, config path and sockets.

    Everything lives under a short directory in /tmp (socket paths have a
    length limit). The environment is built from scratch values and never
    carries a HERDR_* variable from the caller, so the live server is never
    addressed; start() refuses to go on unless the server reports our socket.
    """

    def __init__(self, test_case):
        self.test_case = test_case
        self.root = Path(tempfile.mkdtemp(prefix="t2h-", dir="/tmp")).resolve()
        self.home = self.root / "home"
        (self.home / ".config" / "herdr").mkdir(parents=True)
        self.socket = self.root / "s.sock"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR_", "AGENT_ALERT_"))}
        self.env.update(
            HOME=str(self.home),
            XDG_CONFIG_HOME=str(self.home / ".config"),
            XDG_STATE_HOME=str(self.home / ".local" / "state"),
            LANG="en_US.UTF-8",
            HERDR_CONFIG_PATH=str(self.home / ".config" / "herdr" / "config.toml"),
            HERDR_SOCKET_PATH=str(self.socket),
            HERDR_CLIENT_SOCKET_PATH=str(self.root / "c.sock"),
        )
        for name in ("HERDR_CONFIG_PATH", "HERDR_SOCKET_PATH", "HERDR_CLIENT_SOCKET_PATH"):
            assert self.env[name].startswith(str(self.root) + os.sep), name
        self.process = None
        test_case.addCleanup(self.stop)

    # ---- lifecycle

    def herdr(self, *args, check=True, timeout=30):
        result = subprocess.run(
            ["herdr"] + [str(a) for a in args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            timeout=timeout,
            text=True,
            encoding="utf-8",
        )
        if check and result.returncode != 0:
            raise AssertionError("herdr %s failed: %s %s" % (" ".join(map(str, args)), result.stdout, result.stderr))
        return result

    def api(self, *args):
        return json.loads(self.herdr(*args).stdout)["result"]

    def start(self):
        with open(self.root / "server.out", "wb") as server_output:
            self.process = subprocess.Popen(
                ["herdr", "server"],
                stdin=subprocess.DEVNULL,
                stdout=server_output,
                stderr=subprocess.STDOUT,
                env=self.env,
                start_new_session=True,
            )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = self.herdr("status", "server", check=False)
            found = re.search(r"version: (\S+)", status.stdout)
            # The server can say "running" a moment before it prints its version: keep polling.
            if status.returncode == 0 and "running" in status.stdout and found:
                if "socket: %s" % self.socket not in status.stdout:
                    self.stop()
                    raise AssertionError("scratch server reports a socket that is not ours: " + status.stdout)
                self.version = found.group(1)
                return
            time.sleep(0.2)
        raise AssertionError("scratch Herdr server did not start")

    def stop(self):
        """Stop our server, kill what our panes left behind, and remove the scratch directory."""
        if self.process is not None:
            if self.process.poll() is None:
                self.herdr("server", "stop", check=False, timeout=20)
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
            self.test_case.assertIsNotNone(self.process.poll())
            with self.test_case.assertRaises(ProcessLookupError):
                os.kill(self.process.pid, 0)
            self.process = None
        leftovers = self.leftover_pids()
        deadline = time.monotonic() + 5
        while leftovers and time.monotonic() < deadline:
            time.sleep(0.2)
            leftovers = self.leftover_pids()
        for pid in leftovers:
            os.kill(pid, signal.SIGKILL)
        shutil.rmtree(self.root, ignore_errors=True)
        self.test_case.assertEqual(leftovers, [], "processes of the scratch server survived its stop")

    def leftover_pids(self):
        found = subprocess.run(["pgrep", "-f", str(self.root)], stdout=subprocess.PIPE, text=True)
        return [int(pid) for pid in found.stdout.split()]

    # ---- panes

    def new_pane(self, label):
        result = self.api("workspace", "create", "--cwd", self.root, "--label", label, "--no-focus")
        return result["root_pane"]["pane_id"], result["workspace"]["workspace_id"]
