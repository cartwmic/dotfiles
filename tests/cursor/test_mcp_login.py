"""cursor-mcp-login signs in Cursor MCP servers for one folder, one at a time, and prints each server's state.

A stub `cursor-agent` on PATH stands in for the real one. `mcp list --workspace DIR` prints `name: state` for every server in
the stub's state file; `mcp login NAME --workspace DIR` acts by server name: `good-*` becomes ready, `hang-*` hangs, `bad-*`
exits 1, `quiet-*` exits 0 and changes nothing, `late-*` becomes ready and then exits 1. Every test runs the real script.

    python3 -m unittest discover -s tests/cursor -p 'test_mcp_login.py' -v
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_cursor-mcp-login"
SECRET = "SECRET-VALUE-do-not-print"

STUB = """#!/usr/bin/env python3
import json, os, sys, time
args = sys.argv[1:]
with open(os.environ["STUB_LOG"], "a") as handle:
    handle.write(" ".join(args) + "\\n")
state_path = os.environ["STUB_STATE"]
states = json.load(open(state_path))
if args[:2] == ["mcp", "list"]:
    assert args[2] == "--workspace", args
    mode = os.environ.get("STUB_LIST", "")
    if mode == "hang":
        time.sleep(120)
    if mode == "fail":
        sys.exit(1)
    for name, state in states.items():
        print(name + ": " + state)
    print("noise line without a state delimiter " + "%s")
    sys.exit(0)
assert args[:2] == ["mcp", "login"] and args[3] == "--workspace", args
name = args[2]
def become_ready():
    states[name] = "ready"
    json.dump(states, open(state_path, "w"))
if name.startswith("hang-"):
    open(os.environ["STUB_PID"], "w").write(str(os.getpid()))
    time.sleep(120)
if name.startswith("bad-"):
    print("stub: login failed for " + name)
    sys.exit(1)
if name.startswith("quiet-"):
    sys.exit(0)
become_ready()
if name.startswith("late-"):
    sys.exit(1)
""" % SECRET


class Login(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.work = self.tmp / "ws"
        self.work.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        stub = self.bin / "cursor-agent"
        stub.write_text(STUB)
        stub.chmod(0o755)
        self.log = self.tmp / "stub.log"
        self.pidfile = self.tmp / "stub.pid"
        self.state = self.tmp / "state.json"

    def servers(self, **states):
        self.state.write_text(json.dumps(states))

    def env(self, extra_path=True, **more):
        env = dict(os.environ, HOME=str(self.home), STUB_LOG=str(self.log), STUB_PID=str(self.pidfile), STUB_STATE=str(self.state),
                   PATH=(str(self.bin) + os.pathsep if extra_path else "") + os.environ["PATH"], **more)
        for name in ("STUB_LIST", "CURSOR_MCP_LOGIN_LIST_TIMEOUT"):
            if name not in more:
                env.pop(name, None)
        return env

    def run_script(self, *args, extra_path=True, **more):
        return subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.work), *args], env=self.env(extra_path, **more),
                              capture_output=True, text=True, timeout=60)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def logins(self):
        return [line.split()[2] for line in self.calls() if line.startswith("mcp login")]

    def table(self, out):
        rows = out.split("SERVER", 1)[1].split("\n\n")[0].splitlines()[1:]  # the table ends at the first blank line
        return {line.split()[0]: " ".join(line.split()[1:]) for line in rows if line.strip()}

    def test_only_servers_needing_sign_in_are_picked(self):
        self.servers(**{"good-a": "requires_authentication", "ready-b": "ready", "good-c": "requires_authentication",
                        "err-d": "Error: Connection failed"})
        out = self.run_script()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual(self.logins(), ["good-a", "good-c"])
        self.assertEqual(self.table(out.stdout), {"good-a": "ready", "ready-b": "ready", "good-c": "ready", "err-d": "Error: Connection failed"})

    def test_servers_that_need_no_sign_in_make_nothing_to_do(self):
        self.servers(**{"ready-a": "ready", "ready-b": "ready"})
        out = self.run_script()
        self.assertEqual(out.returncode, 0)
        self.assertEqual(self.logins(), [])
        self.assertIn("nothing to sign in", out.stdout)

    def test_names_take_only_those_servers(self):
        self.servers(**{"good-a": "requires_authentication", "good-b": "requires_authentication", "ready-c": "ready"})
        out = self.run_script("good-b", "ready-c")
        self.assertEqual(self.logins(), ["good-b", "ready-c"])
        self.assertEqual(out.returncode, 0)

    def test_a_name_cursor_agent_does_not_list_is_refused(self):
        self.servers(**{"good-a": "requires_authentication"})
        out = self.run_script("nope")
        self.assertEqual(out.returncode, 2)
        self.assertEqual(self.logins(), [])
        self.assertIn("nope", out.stderr)

    def test_the_state_comes_from_the_same_folder_the_login_uses(self):
        self.servers(**{"good-a": "requires_authentication"})
        self.run_script()
        want = "--workspace " + str(self.work)
        self.assertEqual(self.calls(), ["mcp list " + want, "mcp login good-a " + want, "mcp list " + want])

    def test_a_hang_times_out_and_the_loop_goes_on(self):
        self.servers(**{"hang-a": "requires_authentication", "ok-b": "requires_authentication"})
        out = self.run_script("--timeout", "2")
        self.assertEqual(out.returncode, 1)
        self.assertIn("-> hang-a: TIMED OUT after 2s", out.stdout)
        self.assertEqual(self.logins(), ["hang-a", "ok-b"])
        self.assertEqual(self.table(out.stdout), {"hang-a": "requires_authentication", "ok-b": "ready"})
        with self.assertRaises(ProcessLookupError):  # the hung login was killed, not left holding a port
            os.kill(int(self.pidfile.read_text()), 0)

    def test_a_failure_is_reported_and_the_loop_goes_on(self):
        self.servers(**{"bad-a": "requires_authentication", "good-b": "requires_authentication"})
        out = self.run_script()
        self.assertEqual(out.returncode, 1)
        self.assertIn("-> bad-a: FAILED (exit 1)", out.stdout)
        self.assertEqual(self.logins(), ["bad-a", "good-b"])
        self.assertEqual(self.table(out.stdout), {"bad-a": "requires_authentication", "good-b": "ready"})

    def test_the_final_state_decides_not_the_exit_code(self):
        self.servers(**{"quiet-a": "requires_authentication", "late-b": "requires_authentication"})
        out = self.run_script()
        self.assertIn("-> quiet-a: login finished", out.stdout)  # exit 0, but nothing was saved
        self.assertIn("-> late-b: FAILED (exit 1)", out.stdout)  # exit 1, but it is signed in
        self.assertEqual(self.table(out.stdout), {"quiet-a": "requires_authentication", "late-b": "ready"})
        self.assertEqual(out.returncode, 1)

    def test_check_runs_no_login(self):
        self.servers(**{"good-a": "requires_authentication", "ready-b": "ready"})
        out = self.run_script("--check")
        self.assertEqual(self.calls(), ["mcp list --workspace " + str(self.work)])  # one read, no login
        self.assertEqual(self.table(out.stdout), {"good-a": "requires_authentication", "ready-b": "ready"})
        self.assertEqual(out.returncode, 1)

    def test_restart_line_only_after_a_sign_in(self):
        restart = "T3 must be restarted before its Cursor sessions see the new sign-ins."
        self.servers(**{"good-a": "requires_authentication", "bad-b": "requires_authentication"})
        self.assertIn(restart, self.run_script().stdout)  # good-a signed in, bad-b did not
        self.servers(**{"bad-a": "requires_authentication", "quiet-b": "requires_authentication"})
        self.assertNotIn(restart, self.run_script().stdout)  # nothing signed in
        self.servers(**{"ready-a": "ready"})
        self.assertNotIn(restart, self.run_script().stdout)  # nothing to do
        self.assertNotIn(restart, self.run_script("ready-a").stdout)  # named, but already ready
        self.servers(**{"good-a": "requires_authentication"})
        self.assertNotIn(restart, self.run_script("--check").stdout)

    def test_check_says_the_table_is_the_file_on_disk(self):
        self.servers(**{"good-a": "requires_authentication"})
        out = self.run_script("--check")
        self.assertIn("The table shows what is on disk. T3's Cursor sessions see it only after T3 restarts.", out.stdout)
        self.assertNotIn("on disk", self.run_script().stdout)

    def test_exit_codes(self):
        self.servers(**{"ready-a": "ready", "err-b": "Error: Connection failed", "good-c": "requires_authentication"})
        self.assertEqual(self.run_script("--check", "ready-a").returncode, 0)
        self.assertEqual(self.run_script("--check", "err-b").returncode, 1)  # named and not ready
        self.assertEqual(self.run_script("--check").returncode, 1)  # good-c is picked and not ready
        self.servers(**{"ready-a": "ready", "err-b": "Error: Connection failed"})
        self.assertEqual(self.run_script("--check").returncode, 0)  # an error state that was not picked does not fail the run

    def test_mcp_list_failure_or_hang_exits_2(self):
        self.servers(**{"good-a": "requires_authentication"})
        for mode in ({"STUB_LIST": "fail"}, {"STUB_LIST": "hang", "CURSOR_MCP_LOGIN_LIST_TIMEOUT": "2"}):
            out = self.run_script(**mode)
            self.assertEqual(out.returncode, 2, mode)
            self.assertIn("failed or did not finish", out.stderr)
            self.assertEqual(self.logins(), [])

    def test_no_cursor_agent_exits_2(self):
        out = subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.work), "--check"],
                             env=dict(os.environ, HOME=str(self.home), PATH=str(self.tmp / "nowhere")), capture_output=True, text=True,
                             timeout=60)
        self.assertEqual(out.returncode, 2)
        self.assertIn("cursor-agent is not on PATH", out.stderr)

    def test_only_name_and_state_lines_are_printed(self):
        self.servers(**{"good-a": "requires_authentication", "ready-b": "ready"})
        for args in ((), ("--check",), ("good-a", "ready-b")):
            out = self.run_script(*args)
            self.assertNotIn(SECRET, out.stdout + out.stderr)  # the stub's list output carries an unrecognised line with a value

    def test_ctrl_c_stops_the_login(self):
        self.servers(**{"hang-a": "requires_authentication", "ok-b": "requires_authentication"})
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "--workspace", str(self.work)], env=self.env(), stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, text=True)
        self.addCleanup(proc.kill)
        deadline = time.time() + 30
        while not self.pidfile.exists() and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.pidfile.exists(), "the stub login never started")
        time.sleep(0.2)  # the stub writes its pid, then sleeps
        pid = int(self.pidfile.read_text())
        proc.send_signal(signal.SIGINT)
        err = proc.communicate(timeout=30)[1]
        self.assertEqual(proc.returncode, 130)
        self.assertNotIn("Traceback", err)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with self.assertRaises(ProcessLookupError):  # no login left holding the OAuth callback port
            os.kill(pid, 0)
        self.assertEqual(self.logins(), ["hang-a"])  # and no later server was started

    def test_timeout_must_be_positive(self):
        self.servers(**{"good-a": "requires_authentication"})
        out = self.run_script("--timeout", "0")
        self.assertEqual(out.returncode, 2)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
