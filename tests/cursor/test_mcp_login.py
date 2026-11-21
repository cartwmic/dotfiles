"""cursor-mcp-login signs in Cursor MCP servers for one folder, one at a time, and prints who is signed in.

A stub `cursor-agent` on PATH stands in for the real one: by server name it writes tokens (`good-*`), hangs (`hang-*`), or exits 1
(`bad-*`). Every test runs the real script in a scratch HOME.

    python3 -m unittest discover -s tests/cursor -p 'test_mcp_login.py' -v
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_cursor-mcp-login"
SECRET = "SECRET-TOKEN-VALUE-do-not-print"
CLIENT_SECRET = "SECRET-CLIENT-INFO-do-not-print"

STUB = """#!/usr/bin/env python3
import json, os, sys, time
# cursor-agent mcp login NAME --workspace DIR
log = os.environ["STUB_LOG"]
args = sys.argv[1:]
with open(log, "a") as handle:
    handle.write(" ".join(args) + "\\n")
assert args[:2] == ["mcp", "login"] and args[3] == "--workspace", args
name = args[2]
if name.startswith("hang-"):
    open(os.environ["STUB_PID"], "w").write(str(os.getpid()))
    time.sleep(120)
if name.startswith("bad-"):
    print("stub: login failed for " + name)
    sys.exit(1)
if name.startswith("quiet-"):  # exits 0 and saves nothing
    sys.exit(0)
path = os.environ["STUB_AUTH"]
try:
    data = json.load(open(path))
except (OSError, ValueError):
    data = {}
data[name] = {"clientInfo": {"client_secret": "%s"}, "tokens": {"access_token": "%s"}}
json.dump(data, open(path, "w"))
if name.startswith("late-"):  # saves tokens, then fails
    sys.exit(1)
""" % (CLIENT_SECRET, SECRET)


def load_module():
    loader = importlib.machinery.SourceFileLoader("cursor_mcp_login", str(SCRIPT))
    spec = importlib.util.spec_from_loader("cursor_mcp_login", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Slug(unittest.TestCase):
    """The folder name cursor-agent uses under ~/.cursor/projects (read from its 2026.11.19 bundle, and matching the two folders
    on disk there: /home/cartwmic -> home-cartwmic, /tmp -> tmp)."""

    def setUp(self):
        self.mod = load_module()
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def test_sample_folders(self):
        cases = {
            "/home/cartwmic": "home-cartwmic",
            "/tmp": "tmp",
            "/home/cartwmic/.local/share/coordinator-workspace": "home-cartwmic-local-share-coordinator-workspace",
            "/Users/mcartwright/.local/share/coordinator-work-workspace": "Users-mcartwright-local-share-coordinator-work-workspace",
            "/a//b/c_d e/": "a-b-c-d-e",
        }
        for path, want in cases.items():
            self.assertEqual(self.mod.slug(path), want, path)

    def test_long_folder_is_not_shortened_or_hashed(self):
        # cursor-agent has a second path function that cuts paths over 91 characters and adds a hash; the MCP files do not use it
        long_path = "/Users/mcartwright/.local/share/coordinator-work-workspace"
        with unittest.mock.patch.dict(os.environ, {"HOME": "/Users/mcartwright"}):
            os.environ.pop("CURSOR_DATA_DIR", None)
            got = self.mod.auth_file(long_path)
        self.assertGreater(len(got), 91)
        self.assertEqual(got, "/Users/mcartwright/.cursor/projects/Users-mcartwright-local-share-coordinator-work-workspace/mcp-auth.json")

    def test_auth_file_under_cursor_projects(self):
        os.environ.pop("CURSOR_DATA_DIR", None)
        with unittest.mock.patch.dict(os.environ, {"HOME": str(self.dir)}):
            got = self.mod.auth_file("/Users/x/ws")
        self.assertEqual(got, str(self.dir / ".cursor/projects/Users-x-ws/mcp-auth.json"))

    def test_cursor_data_dir_is_honoured(self):
        with unittest.mock.patch.dict(os.environ, {"CURSOR_DATA_DIR": str(self.dir / "data")}):
            self.assertEqual(self.mod.auth_file("/a/b"), str(self.dir / "data/projects/a-b/mcp-auth.json"))

    def test_folder_inside_a_git_repo_uses_the_repo_root(self):
        repo = self.dir / "repo"
        (repo / ".git").mkdir(parents=True)
        (repo / "sub/deeper").mkdir(parents=True)
        self.assertEqual(self.mod.project_root(str(repo / "sub/deeper")), str(repo))
        self.assertEqual(self.mod.project_root(str(self.dir / "plain")), str(self.dir / "plain"))


class Login(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.work = self.tmp / "ws"
        self.work.mkdir()
        (self.home / ".cursor").mkdir(parents=True)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        stub = self.bin / "cursor-agent"
        stub.write_text(STUB)
        stub.chmod(0o755)
        self.log = self.tmp / "stub.log"
        self.pidfile = self.tmp / "stub.pid"
        self.mod = load_module()
        self.auth = Path(self.home / ".cursor/projects" / self.mod.slug(str(self.work)) / "mcp-auth.json")
        self.auth.parent.mkdir(parents=True)

    def servers(self, **specs):
        body = {name: (spec if spec is not None else {"url": "https://example.invalid/" + name}) for name, spec in specs.items()}
        (self.home / ".cursor/mcp.json").write_text(json.dumps({"mcpServers": body}))

    def sign_in_already(self, *names):
        data = {n: {"clientInfo": {"client_secret": CLIENT_SECRET}, "tokens": {"access_token": SECRET}} for n in names}
        self.auth.write_text(json.dumps(data))

    def run_script(self, *args, extra_path=True):
        env = dict(os.environ, HOME=str(self.home), STUB_LOG=str(self.log), STUB_PID=str(self.pidfile), STUB_AUTH=str(self.auth),
                   PATH=(str(self.bin) + os.pathsep if extra_path else "") + os.environ["PATH"])
        env.pop("CURSOR_DATA_DIR", None)
        return subprocess.run([sys.executable, str(SCRIPT), "--workspace", str(self.work), *args], env=env, capture_output=True,
                              text=True, timeout=60)

    def logins(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def states(self, out):
        rows = out.split("SERVER", 1)[1].splitlines()[1:]
        return {line.split()[0]: " ".join(line.split()[1:]) for line in rows if line.strip()}

    def test_only_servers_without_tokens_are_signed_in(self):
        self.servers(**{"good-a": None, "good-b": None, "good-c": None})
        self.sign_in_already("good-b")
        out = self.run_script()
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertEqual([line.split()[2] for line in self.logins()], ["good-a", "good-c"])
        self.assertEqual(self.states(out.stdout), {"good-a": "signed in", "good-b": "signed in", "good-c": "signed in"})

    def test_command_servers_and_header_servers_are_left_out_by_default(self):
        self.servers(**{"good-oauth": None, "stdio": {"command": "true"}, "good-keyed": {"url": "https://x.invalid", "headers": {"K": "v"}}})
        out = self.run_script()
        self.assertEqual([line.split()[2] for line in self.logins()], ["good-oauth"])
        self.assertEqual(list(self.states(out.stdout)), ["good-oauth"])

    def test_all_takes_header_servers_and_names_take_only_those(self):
        self.servers(**{"good-oauth": None, "good-keyed": {"url": "https://x.invalid", "headers": {"K": "v"}}})
        self.run_script("--all")
        self.assertEqual(sorted(line.split()[2] for line in self.logins()), ["good-keyed", "good-oauth"])
        self.log.unlink()
        self.run_script("good-keyed")
        self.assertEqual([line.split()[2] for line in self.logins()], ["good-keyed"])

    def test_login_gets_the_workspace_argument(self):
        self.servers(**{"good-a": None})
        self.run_script()
        self.assertEqual(self.logins(), ["mcp login good-a --workspace " + str(self.work)])

    def test_a_hang_times_out_and_the_loop_goes_on(self):
        self.servers(**{"hang-a": None, "ok-b": None})
        out = self.run_script("--timeout", "2")
        self.assertEqual(out.returncode, 1)
        self.assertIn("-> hang-a: TIMED OUT after 2s", out.stdout)
        self.assertEqual([line.split()[2] for line in self.logins()], ["hang-a", "ok-b"])
        self.assertEqual(self.states(out.stdout), {"hang-a": "not signed in", "ok-b": "signed in"})
        pid = int(self.pidfile.read_text())
        with self.assertRaises(ProcessLookupError):  # the hung login was killed, not left holding a port
            os.kill(pid, 0)

    def test_a_failure_is_reported_and_the_loop_goes_on(self):
        self.servers(**{"bad-a": None, "good-b": None})
        out = self.run_script()
        self.assertEqual(out.returncode, 1)
        self.assertIn("-> bad-a: FAILED (exit 1)", out.stdout)
        self.assertEqual([line.split()[2] for line in self.logins()], ["bad-a", "good-b"])
        self.assertEqual(self.states(out.stdout), {"bad-a": "not signed in", "good-b": "signed in"})

    def test_tokens_not_exit_code_decide_signed_in(self):
        self.servers(**{"quiet-a": None, "late-b": None})
        out = self.run_script()
        self.assertIn("-> quiet-a: finished, but no tokens were saved", out.stdout)
        self.assertIn("-> late-b: signed in", out.stdout)
        self.assertEqual(self.states(out.stdout), {"quiet-a": "not signed in", "late-b": "signed in"})
        self.assertEqual(out.returncode, 1)

    def test_ctrl_c_stops_the_login(self):
        self.servers(**{"hang-a": None, "ok-b": None})
        env = dict(os.environ, HOME=str(self.home), STUB_LOG=str(self.log), STUB_PID=str(self.pidfile), STUB_AUTH=str(self.auth),
                   PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "--workspace", str(self.work)], env=env, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.addCleanup(proc.kill)
        deadline = time.time() + 30
        while not self.pidfile.exists() and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.pidfile.exists(), "the stub login never started")
        time.sleep(0.2)  # the stub writes its pid, then sleeps
        pid = int(self.pidfile.read_text())
        proc.send_signal(signal.SIGINT)
        proc.wait(timeout=30)
        self.assertNotEqual(proc.returncode, 0)
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        with self.assertRaises(ProcessLookupError):  # no login left holding the OAuth callback port
            os.kill(pid, 0)
        self.assertEqual([line.split()[2] for line in self.logins()], ["hang-a"])  # and no later server was started

    def test_timeout_must_be_positive(self):
        self.servers(**{"good-a": None})
        out = self.run_script("--timeout", "0")
        self.assertEqual(out.returncode, 2)
        self.assertEqual(self.logins(), [])

    def test_check_runs_no_login(self):
        self.servers(**{"good-a": None, "good-b": None})
        self.sign_in_already("good-b")
        out = self.run_script("--check", extra_path=False)  # no cursor-agent on PATH at all: check never needs it
        self.assertEqual(self.logins(), [])
        self.assertEqual(self.states(out.stdout), {"good-a": "not signed in", "good-b": "signed in"})
        self.assertEqual(out.returncode, 1)

    def test_exit_codes(self):
        self.servers(**{"good-a": None})
        self.sign_in_already("good-a")
        self.assertEqual(self.run_script("--check").returncode, 0)
        self.assertEqual(self.run_script().returncode, 0)
        self.assertIn("nothing to sign in", self.run_script().stdout)
        self.assertEqual(self.run_script("--check", "nope").returncode, 2)

    def test_no_token_value_is_printed(self):
        self.servers(**{"good-a": None, "good-b": None, "bad-c": None})
        self.sign_in_already("good-b")
        for args in ((), ("--check",), ("--all",), ("good-a", "good-b")):
            out = self.run_script(*args)
            for text in (out.stdout, out.stderr):
                self.assertNotIn(SECRET, text)
                self.assertNotIn(CLIENT_SECRET, text)

    def test_clientinfo_alone_is_not_signed_in(self):
        self.servers(**{"good-a": None})
        self.auth.write_text(json.dumps({"good-a": {"clientInfo": {"client_secret": CLIENT_SECRET}}}))
        out = self.run_script("--check")
        self.assertEqual(self.states(out.stdout), {"good-a": "not signed in"})
        self.assertEqual(out.returncode, 1)


if __name__ == "__main__":
    unittest.main()
