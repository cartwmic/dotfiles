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

# A fake Chrome as a real .app bundle: open(1) launches the bundle's executable and does not pass the caller's
# environment, so this one records its argv next to itself instead of through FAKE_ARGV.
FAKE_BUNDLE_CHROME = """#!%s
import base64, hashlib, http.server, json, pathlib, socketserver, sys
pathlib.Path(__file__).resolve().parent.joinpath("argv.log").write_text(json.dumps(sys.argv[1:]))
port = int([a for a in sys.argv if a.startswith("--remote-debugging-port=")][0].split("=")[1])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":   # the launcher's Target.createTarget call (launch forms b and c)
            if self.path != "/devtools/browser/fake":   # real Chrome requires the leading slash on the request-target
                self.send_response(400); self.end_headers()
                return
            key = self.headers.get("Sec-WebSocket-Key", "")
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            frame = self.connection.recv(65536)   # one client frame; client frames are always masked
            length = frame[1] & 0x7F
            mask = frame[2:6]
            call = json.loads(bytes(b ^ mask[i %% 4] for i, b in enumerate(frame[6:6 + length])))
            pathlib.Path(__file__).resolve().parent.joinpath("cdp.log").write_text(json.dumps(call))
            reply = json.dumps({"id": call.get("id", 1), "result": {"targetId": "fake-target"}}).encode()
            self.connection.sendall(bytes([0x81, len(reply)]) + reply)
            return
        self.send_response(200); self.end_headers()
        if self.path == "/json/version":
            self.wfile.write(json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:%%d/devtools/browser/fake" %% port}).encode())
        else:
            self.wfile.write(b"{}")
    def log_message(self, *a): pass
class S(socketserver.TCPServer):
    allow_reuse_address = True   # the test relaunches on the same port after --stop
S(("127.0.0.1", port), H).serve_forever()
""" % sys.executable

# A fake open that records its arguments and spawns the bundle's executable at once, like the real one.
FAKE_OPEN = """#!%s
import json, os, subprocess, sys
args = sys.argv[1:]
open(os.environ["FAKE_ARGV"] + ".open", "a").write(json.dumps(args) + "\\n")
bundle = args[args.index("-a") + 1]
subprocess.Popen([os.path.join(bundle, "Contents/MacOS/fake-chrome")] + args[args.index("--args") + 1:],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
""" % sys.executable

# open as it behaves on the GitHub macOS runner: Chrome starts, but open itself never returns (dotfiles#695).
FAKE_OPEN_NEVER_RETURNS = FAKE_OPEN + "import time\ntime.sleep(60)\n"
# open that fails without starting anything.
FAKE_OPEN_FAILS = "#!/bin/sh\necho 'open: no such application' >&2\nexit 1\n"


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

    def run_script(self, app, wait="10", args=None, bin_dir=None, **extra):
        path = os.environ["PATH"] if bin_dir is None else str(bin_dir) + os.pathsep + os.environ["PATH"]
        env = {"PATH": path, "HOME": str(self.home), "AGENT_CHROME_APP": str(app), "AGENT_CHROME_OS": "Darwin",
               "AGENT_CHROME_PORT": str(self.port), "AGENT_CHROME_WAIT": wait, "FAKE_ARGV": str(self.argv),
               "AGENT_CHROME_FOCUS_WAIT": "1"}   # the macOS bundle path watches for Chrome's self-activation; keep the tests fast
        env.update(extra)
        return subprocess.run(["sh", str(SCRIPT)] + (args or []), env=env, capture_output=True, text=True, timeout=60)

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

    @unittest.skipUnless(Path("/proc").is_dir(), "session.sh decides liveness from /proc")
    def test_linux_without_wayland_display_uses_the_live_hyprland_instances_display(self):
        import shutil, socket
        lib = self.home / ".local/share/agent-desktop"
        lib.mkdir(parents=True)
        shutil.copy(ROOT / "dot_local/share/agent-desktop/session.sh", lib / "session.sh")
        runtime = self.root / "run"
        (runtime / "hypr" / "aaa_2000_1").mkdir(parents=True)
        socks = []
        for name in ("wayland-1", "wayland-2"):   # wayland-1 would be the first-match answer; the live instance owns wayland-2
            sock = socket.socket(socket.AF_UNIX)
            sock.bind(str(runtime / name))
            socks.append(sock)
        (runtime / "hypr" / "aaa_2000_1" / "hyprland.lock").write_text("%d\nwayland-2\n" % os.getpid())
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(str(runtime / "hypr" / "aaa_2000_1" / ".socket.sock"))
        socks.append(sock)
        try:
            r = self.run_script(self.fake(), AGENT_CHROME_OS="Linux", XDG_RUNTIME_DIR=str(runtime))
        finally:
            for sock in socks:
                sock.close()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.env_seen(), [{"WAYLAND_DISPLAY": "wayland-2"}])

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

    def install_fake_open(self, body=FAKE_OPEN):
        self.bin = self.root / "bin"
        self.bin.mkdir(exist_ok=True)
        tool = self.bin / "open"
        tool.write_text(body)
        tool.chmod(0o755)
        return self.bin

    def open_calls(self):
        path = Path(str(self.argv) + ".open")
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def cdp_calls(self, exe):
        """The CDP calls the bundle fake saw over WebSocket (its cdp.log, one JSON call)."""
        path = exe.parent / "cdp.log"
        return [json.loads(path.read_text())] if path.exists() else []

    def bundle(self):
        """A fake Chrome as a minimal .app bundle; returns (bundle, executable, argv log) paths."""
        bundle = self.root / "Fake.app"
        (bundle / "Contents/MacOS").mkdir(parents=True)
        (bundle / "Contents/Info.plist").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
            '<key>CFBundleExecutable</key><string>fake-chrome</string>'
            '<key>CFBundleIdentifier</key><string>local.fake-chrome</string>'
            '<key>CFBundlePackageType</key><string>APPL</string></dict></plist>')
        exe = bundle / "Contents/MacOS/fake-chrome"
        exe.write_text(FAKE_BUNDLE_CHROME)
        exe.chmod(0o755)
        return bundle, exe, exe.parent / "argv.log"

    @unittest.skipUnless(sys.platform == "darwin", "open -g is the macOS launch path")
    def test_macos_app_bundle_launches_through_open_g_not_a_direct_exec(self):
        """A .app AGENT_CHROME_APP goes through open -g -n with --no-startup-window (default form b); the args still reach Chrome."""
        bundle, exe, argv_log = self.bundle()
        for app in (exe, bundle):   # the binary inside the bundle (the real default) and the bundle itself both work
            r = self.run_script(app)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(json.loads(argv_log.read_text()), [
                "--remote-debugging-port=%d" % self.port, "--user-data-dir=%s" % (self.home / ".local/share/agent-chrome-profile"),
                *BASE_ARGS, "--no-startup-window", "about:blank"])
            self.assertEqual(self.calls(), [])   # the direct-exec fake was never run: open launched the bundle instead
            self.assertIn("INFO: Chrome started", self.record()[-1])
            argv_log.unlink()
            r = self.run_script(app, args=["--stop"])   # the fake keeps serving the port; end it before the next launch
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "open is the macOS launch path")
    def test_launch_form_plain_keeps_plain_open_flags(self):
        """Form plain: open -g -n, no --no-startup-window, no CDP window creation."""
        bundle, exe, argv_log = self.bundle()
        bin_dir = self.install_fake_open()
        r = self.run_script(bundle, bin_dir=bin_dir, AGENT_CHROME_LAUNCH_FORM="plain")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.open_calls()[0][:4], ["-g", "-n", "-a", str(bundle)])
        self.assertNotIn("--no-startup-window", json.loads(argv_log.read_text()))
        self.assertEqual(self.cdp_calls(exe), [])

    @unittest.skipUnless(sys.platform == "darwin", "open is the macOS launch path")
    def test_launch_form_a_launches_hidden(self):
        """Form a: open -g -j -n (hidden launch); the Chrome args are unchanged and no window is created over CDP."""
        bundle, exe, argv_log = self.bundle()
        bin_dir = self.install_fake_open()
        r = self.run_script(bundle, bin_dir=bin_dir, AGENT_CHROME_LAUNCH_FORM="a")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.open_calls()[0][:5], ["-g", "-j", "-n", "-a", str(bundle)])
        self.assertNotIn("--no-startup-window", json.loads(argv_log.read_text()))
        self.assertEqual(self.cdp_calls(exe), [])

    @unittest.skipUnless(sys.platform == "darwin", "open is the macOS launch path")
    def test_launch_form_b_is_default_and_creates_first_window_over_cdp(self):
        """Default (form b): open -g -n with --no-startup-window; once the port answers, the first window is created
        over CDP with Target.createTarget and background:true, so nothing raises it."""
        bundle, exe, argv_log = self.bundle()
        bin_dir = self.install_fake_open()
        r = self.run_script(bundle, bin_dir=bin_dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.open_calls()[0][:4], ["-g", "-n", "-a", str(bundle)])
        self.assertIn("--deliberately-wrong-flag", json.loads(argv_log.read_text()))
        self.assertEqual(self.cdp_calls(exe),
                         [{"id": 1, "method": "Target.createTarget", "params": {"url": "about:blank", "background": True}}])
        self.assertTrue(any("created the first window over CDP in the background" in l for l in self.record()), self.record())

    @unittest.skipUnless(sys.platform == "darwin", "open is the macOS launch path")
    def test_launch_form_c_combines_hidden_and_no_startup_window(self):
        """Form c: open -g -j -n and --no-startup-window together, plus the background CDP window."""
        bundle, exe, argv_log = self.bundle()
        bin_dir = self.install_fake_open()
        r = self.run_script(bundle, bin_dir=bin_dir, AGENT_CHROME_LAUNCH_FORM="c")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.open_calls()[0][:5], ["-g", "-j", "-n", "-a", str(bundle)])
        self.assertIn("--no-startup-window", json.loads(argv_log.read_text()))
        self.assertEqual(len(self.cdp_calls(exe)), 1)

    def test_an_open_that_never_returns_does_not_hold_the_launch(self):
        """Chrome answers on the port while open is still running (the GitHub macOS runner): the launcher exits 0 at
        once, with open's output kept off its own stdout, and stops the leftover open. Runs on Linux too (fake open)."""
        bundle, exe, argv_log = self.bundle()
        bin_dir = self.install_fake_open(FAKE_OPEN_NEVER_RETURNS)
        started = time.monotonic()
        r = self.run_script(bundle, bin_dir=bin_dir)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertLess(time.monotonic() - started, 30)
        self.assertTrue(any("open had not returned" in l for l in self.record()), self.record())
        started_line = [l for l in self.record() if "INFO: Chrome started" in l]
        self.assertTrue(started_line, self.record())
        # open's argv carries the profile flag too: the pid the launcher records (and hands the front back by) is Chrome's, not open's
        pid = started_line[0].split("(pid ")[1].split(")")[0]
        command = subprocess.run(["ps", "-p", pid, "-o", "command="], capture_output=True, text=True).stdout
        self.assertIn("fake-chrome", command)

    def test_an_open_that_fails_fails_the_launch_and_says_so(self):
        bundle, exe, argv_log = self.bundle()
        bin_dir = self.install_fake_open(FAKE_OPEN_FAILS)
        r = self.run_script(bundle, bin_dir=bin_dir, wait="10")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("open could not launch", r.stderr)

    def test_launch_form_rejects_an_unknown_value(self):
        r = self.run_script(self.fake(), AGENT_CHROME_LAUNCH_FORM="d")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not one of plain|a|b|c", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_the_default_app_is_per_os(self):
        text = SCRIPT.read_text()
        self.assertIn("DEFAULT_APP=/usr/bin/google-chrome-stable", text)
        self.assertIn('DEFAULT_APP="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"', text)


if __name__ == "__main__":
    unittest.main()
