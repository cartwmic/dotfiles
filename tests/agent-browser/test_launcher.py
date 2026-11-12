"""agent-chrome: the real launcher script against a fake Chrome (a script that serves /json/version) and a scratch HOME.
Never starts a real Chrome and never touches the real profile directory."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_agent-chrome"

FAKE_CHROME = """#!%s
import http.server, json, os, socketserver, sys
open(os.environ["FAKE_ARGV"], "a").write(json.dumps(sys.argv[1:]) + "\\n")
open(os.environ["FAKE_ARGV"] + ".env", "a").write(json.dumps({"WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY")}) + "\\n")
port = int([a for a in sys.argv if a.startswith("--remote-debugging-port=")][0].split("=")[1])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a): pass
# TCPServer, not HTTPServer: HTTPServer.server_bind calls getfqdn(), which can stall for many seconds on CI runners.
socketserver.TCPServer(("127.0.0.1", port), H).serve_forever()
""" % sys.executable

SILENT_CHROME = "#!/bin/sh\necho \"$@\" >> \"$FAKE_ARGV\"\nsleep 30\n"
BASE_ARGS = ["--no-first-run", "--no-default-browser-check", "--disable-search-engine-choice-screen"]


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agent-chrome-test-")
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.argv = self.root / "argv.log"
        self.port = free_port()

    def tearDown(self):
        subprocess.run(["pkill", "-f", str(self.root)], check=False)
        self.tmp.cleanup()

    def fake(self, body=FAKE_CHROME):
        app = self.root / "Chrome"
        app.write_text(body)
        app.chmod(0o755)
        return app

    def run_script(self, app, wait="10", **extra):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "AGENT_CHROME_APP": str(app), "AGENT_CHROME_OS": "Darwin",
               "AGENT_CHROME_PORT": str(self.port), "AGENT_CHROME_WAIT": wait, "FAKE_ARGV": str(self.argv)}
        env.update(extra)
        return subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)

    def calls(self):
        return [json.loads(l) for l in self.argv.read_text().splitlines()] if self.argv.exists() else []

    def record(self):
        """The persisted launcher log (one line per outcome)."""
        path = self.home / ".local/state/agent-chrome/agent-chrome.log"
        return path.read_text().splitlines() if path.exists() else []

    def test_starts_chrome_with_the_dedicated_profile_and_debug_port(self):   # macOS
        r = self.run_script(self.fake())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.calls()), 1)
        profile = self.home / ".local/share/agent-chrome-profile"
        self.assertEqual(self.calls()[0], [
            "--remote-debugging-port=%d" % self.port, "--user-data-dir=%s" % profile, "--no-first-run",
            "--no-default-browser-check", "--disable-search-engine-choice-screen", "about:blank"])
        self.assertTrue(profile.is_dir())
        log = self.record()
        self.assertEqual(len(log), 2, log)
        self.assertIn("INFO: starting Chrome on port %d" % self.port, log[0])
        self.assertIn("INFO: Chrome started", log[1])
        for line in log:
            self.assertRegex(line, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ run=\S+-\d+ elapsed=\d+s \[agent-chrome\] ")

    def test_does_nothing_when_the_port_already_answers(self):
        app = self.fake()
        self.assertEqual(self.run_script(app).returncode, 0)
        r = self.run_script(app)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("already answers", r.stdout)
        self.assertEqual(len(self.calls()), 1)
        self.assertIn("already answers", self.record()[-1])

    def test_missing_chrome_fails_with_the_install_command(self):
        r = self.run_script(self.root / "nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("brew install --cask google-chrome", r.stderr)
        r = self.run_script(self.root / "nope", AGENT_CHROME_OS="Linux")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("brew", r.stderr)
        self.assertIn("scripts/omarchy-devbox/setup.sh", r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertIn("ERROR: Chrome not found", self.record()[-1])

    def test_chrome_that_never_answers_fails_after_the_wait(self):
        started = time.time()
        r = self.run_script(self.fake(SILENT_CHROME), wait="2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("did not answer", r.stderr)
        # The persisted log alone names the fault: Chrome was started, then never answered.
        log = self.record()
        self.assertIn("INFO: starting Chrome", log[0])
        self.assertIn("ERROR: Chrome (pid", log[-1])
        self.assertIn("did not answer on port %d within 2s" % self.port, log[-1])
        self.assertLess(time.time() - started, 20)


    # Linux (Omarchy, Wayland)
    def env_seen(self):
        return [json.loads(l) for l in (Path(str(self.argv) + ".env")).read_text().splitlines()]

    def test_linux_passes_the_wayland_flag_and_the_macos_flags_unchanged(self):
        r = self.run_script(self.fake(), AGENT_CHROME_OS="Linux", WAYLAND_DISPLAY="wayland-7")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        profile = self.home / ".local/share/agent-chrome-profile"
        self.assertEqual(self.calls()[0], ["--remote-debugging-port=%d" % self.port, "--user-data-dir=%s" % profile, *BASE_ARGS,
                                           "--ozone-platform=wayland", "about:blank"])
        self.assertEqual(self.env_seen(), [{"WAYLAND_DISPLAY": "wayland-7"}])   # a set WAYLAND_DISPLAY is left alone

    def test_linux_without_wayland_display_uses_the_first_wayland_socket_in_xdg_runtime_dir(self):
        import socket
        runtime = self.root / "run"
        runtime.mkdir()
        socks = []
        for name in ("wayland-1", "wayland-2"):
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(runtime / name))
            socks.append(sock)
        (runtime / "wayland-1.lock").write_text("")   # the compositor's lock file is not a socket
        try:
            r = self.run_script(self.fake(), AGENT_CHROME_OS="Linux", XDG_RUNTIME_DIR=str(runtime))
        finally:
            for sock in socks:
                sock.close()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env_seen(), [{"WAYLAND_DISPLAY": "wayland-1"}])

    def test_linux_without_any_socket_still_starts_chrome_and_leaves_wayland_display_unset(self):
        runtime = self.root / "run"
        runtime.mkdir()
        r = self.run_script(self.fake(), AGENT_CHROME_OS="Linux", XDG_RUNTIME_DIR=str(runtime))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env_seen(), [{"WAYLAND_DISPLAY": None}])

    def test_macos_gets_no_wayland_flag_and_no_wayland_display(self):
        r = self.run_script(self.fake(), XDG_RUNTIME_DIR=str(self.root))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("--ozone-platform=wayland", self.calls()[0])
        self.assertEqual(self.env_seen(), [{"WAYLAND_DISPLAY": None}])

    def test_the_default_app_is_per_os(self):
        text = SCRIPT.read_text()
        self.assertIn("DEFAULT_APP=/usr/bin/google-chrome-stable", text)
        self.assertIn('DEFAULT_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"', text)


if __name__ == "__main__":
    unittest.main()
