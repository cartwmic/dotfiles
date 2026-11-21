"""Launching the agent Chrome and driving it must never change the frontmost app (macOS only).

The frontmost-app steal is a macOS behavior: a directly exec'd Chrome (or open -g -n with a startup window)
becomes the frontmost app, and CDP activation calls raise its window. This journey launches the real
agent-chrome script on a scratch port and profile (AGENT_CHROME_PROFILE), then drives background tabs over
CDP (Target.createTarget with background:true) to a local HTTP server. A sampler thread reads the frontmost
app every ~50 ms from before the launch until after the last step, so a steal that comes and goes (the
launcher hands the front back within seconds) is still caught: the journey fails on any change and reports
when it happened and how long it lasted. It skips off macOS, without Chrome, or when AGENT_CHROME_APP points
at the fake (/nonexistent), like the other journeys. On a GitHub Actions runner only the "front never changes"
test is skipped (setfront changes nothing there); the launch and hand-back-attempt tests still run.

Set AGENT_CHROME_LAUNCHER to run this same journey against another launcher script.
"""
import base64
import contextlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from front_sampler import FrontSampler

SCRIPT = Path(__file__).resolve().parents[2] / "dot_local/bin/executable_agent-chrome"
LAUNCHER = Path(os.environ.get("AGENT_CHROME_LAUNCHER") or SCRIPT)  # override: run the journey against another launcher
CHROME_APP = os.environ.get("AGENT_CHROME_APP") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# True on a GitHub Actions runner. The runner is not a desktop: `open` starts Chrome stopped and never returns, and
# `lsappinfo setfront` returns 0 and changes nothing (dotfiles#695), so the front-app assertion cannot be judged there.
ON_RUNNER = os.environ.get("GITHUB_ACTIONS") == "true"
PAGE = b"<!doctype html><title>focus-test</title><h1>ok</h1>"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def tabs(cdp):
    return [t for t in json.load(urllib.request.urlopen(cdp + "/json/list", timeout=5)) if t.get("type") == "page"]


def cdp_call(cdp, method, params):
    ver = json.load(urllib.request.urlopen(cdp + "/json/version", timeout=5))
    ws = ver["webSocketDebuggerUrl"]
    hostport, _, path = ws[5:].partition("/")
    host, _, sport = hostport.partition(":")
    sock = socket.create_connection((host, int(sport or 80)), timeout=10)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n") % (path, hostport, key)
        sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("websocket closed during handshake")
            head += chunk
        if head.split(b"\r\n", 1)[0].split()[1] != b"101":
            raise RuntimeError("websocket handshake refused: " + head.split(b"\r\n", 1)[0].decode("ascii", "replace"))
        payload = json.dumps({"id": 1, "method": method, "params": params}).encode()
        mask = os.urandom(4)
        hdr = struct.pack("!BB", 0x81, 0x80 | (126 if len(payload) > 125 else len(payload)))
        if len(payload) > 125:
            hdr += struct.pack("!H", len(payload))
        sock.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

        def recv_exact(n):
            buf = b""
            while len(buf) < n:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    raise RuntimeError("websocket closed before reply")
                buf += chunk
            return buf

        frame = recv_exact(2)
        length = frame[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", recv_exact(8))[0]
        reply = json.loads(recv_exact(length))
        if "error" in reply or "result" not in reply:
            raise RuntimeError("%s failed: %s" % (method, reply))
        return reply["result"]
    finally:
        sock.close()


@contextlib.contextmanager
def resume_stopped_chrome(profile):
    """Send SIGCONT to any agent-profile process that is stopped, while the launch runs.

    On the GitHub macOS runner (macos-15) `open` starts Chrome in the stopped state (ps stat T) and never resumes
    it, so `open` and the launcher wait for a port that never answers; the same Chrome run directly answers in
    about 3 s, and a SIGCONT after `open` makes it answer too (measured in CI, dotfiles#695). On a normal desktop
    nothing is ever stopped and this does nothing. It is here, not in the launcher, because it works around the
    runner and the launcher must not carry it.
    """
    done = threading.Event()

    def run():
        while not done.wait(0.25):
            out = subprocess.run(["ps", "-axo", "pid=,stat=,command="], capture_output=True, text=True).stdout
            for line in out.splitlines():
                pid, _, rest = line.strip().partition(" ")
                stat, _, command = rest.strip().partition(" ")
                if stat.startswith("T") and "--user-data-dir=" + profile in command:
                    try:
                        os.kill(int(pid), signal.SIGCONT)
                    except OSError:
                        pass

    t = threading.Thread(target=run, daemon=True, name="resume-stopped-chrome")
    t.start()
    try:
        yield
    finally:
        done.set()
        t.join(timeout=5)


@unittest.skipUnless(sys.platform == "darwin", "macOS only: the frontmost-app steal is a macOS behavior")
@unittest.skipIf(not os.access(CHROME_APP, os.X_OK), "needs Chrome at %s" % CHROME_APP)
class NoFocusSteal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sampler = FrontSampler()
        cls.t0 = time.monotonic()
        cls.sampler.start()  # before the launch: a launch-time steal must show up as a change from the baseline sample
        cls.scratch = tempfile.mkdtemp(prefix="agent-chrome-focus-")
        cls.port = free_port()
        cls.env = dict(os.environ,
                       AGENT_CHROME_PORT=str(cls.port),
                       AGENT_CHROME_PROFILE=cls.scratch + "/profile",
                       AGENT_CHROME_WAIT="30",
                       XDG_STATE_HOME=cls.scratch + "/state")
        cls.cdp = "http://127.0.0.1:%s" % cls.port
        try:
            # runner only: on a real desktop nothing is stopped, and the launcher must not carry this
            with (resume_stopped_chrome(cls.scratch + "/profile") if ON_RUNNER else contextlib.nullcontext()):
                r = subprocess.run([str(LAUNCHER)], env=cls.env, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise AssertionError("agent-chrome did not start: " + (r.stdout + r.stderr).strip())
            cls.drive()
        except Exception as err:
            # unittest skips tearDownClass when setUpClass raises: stop the sampler and Chrome here, and put the
            # launcher's own logs in the failure so a CI run explains itself.
            report = cls.launch_report()
            cls.tearDownClass()
            raise AssertionError("agent-chrome did not start (%s: %s)\n%s" % (type(err).__name__, err, report)) from err

    @classmethod
    def drive(cls):
        """The journey: two background tabs over CDP to a local page, then a settle. The sampler runs throughout."""
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("content-type", "text/html")
                self.end_headers()
                self.wfile.write(PAGE)

            def log_message(self, *a):
                pass

        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:%d/" % cls.http.server_address[1]
        # Evidence that the launch itself made the first window (form b creates it over CDP), taken before the first
        # createTarget below: after that the tab count says nothing about the launcher.
        cls.tabs_after_launch = len(tabs(cls.cdp))
        cls.marks = [("launch done", cls.sampler_age())]
        cdp_call(cls.cdp, "Target.createTarget", {"url": cls.base + "?page=one", "background": True})
        cls.marks.append(("first background tab", cls.sampler_age()))
        cdp_call(cls.cdp, "Target.createTarget", {"url": cls.base + "?page=two", "background": True})
        cls.marks.append(("second background tab", cls.sampler_age()))
        time.sleep(2)  # settle: an asynchronous raise landing after the last call returns would slip past an immediate re-read
        cls.marks.append(("settled", cls.sampler_age()))

    @classmethod
    def sampler_age(cls):
        return time.monotonic() - cls.t0

    @classmethod
    def launch_report(cls):
        parts = []
        for name in ("agent-chrome.log", "chrome.log"):
            f = Path(cls.scratch) / "state" / "agent-chrome" / name
            parts.append("--- %s\n%s" % (name, f.read_text(errors="replace")[-3000:] if f.exists() else "(missing)"))
        ps = subprocess.run(["ps", "-axo", "pid,ppid,stat,etime,command"], capture_output=True, text=True).stdout
        parts.append("--- processes on the scratch profile (stat T = stopped)\n" +
                     "\n".join(l[:160] for l in ps.splitlines() if cls.scratch in l))
        return "\n".join(parts)

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "http", None):
            cls.http.shutdown()
            cls.http.server_close()
        cls.sampler.stop()
        subprocess.run([str(LAUNCHER), "--stop"], env=cls.env, capture_output=True, text=True, timeout=60)
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def test_launch_creates_the_first_window_and_background_tabs_reach_the_agent_chrome(self):
        # default form b creates the first window over CDP; the launcher exits 0 even when that step fails, so check both
        # its own log and the tab count taken right after the launch (before the journey made any tab of its own)
        log = (Path(self.scratch) / "state/agent-chrome/agent-chrome.log").read_text()
        self.assertIn("created the first window over CDP", log, self.launch_report())
        self.assertGreaterEqual(self.tabs_after_launch, 1, self.launch_report())
        urls = [t["url"] for t in tabs(self.cdp)]
        self.assertIn(self.base + "?page=one", urls)  # the driving really reached the agent Chrome
        self.assertIn(self.base + "?page=two", urls)

    def test_a_steal_at_launch_is_met_with_a_hand_back_attempt(self):
        """If the agent Chrome took the front at all, the launcher must have tried to give it back (it logs the attempt).
        Runs everywhere, the runner included: it checks the launcher, not whether macOS honoured the request."""
        if not self.sampler.excursions():
            self.skipTest("the agent Chrome never took the front, so there was nothing to hand back")  # the log shows which case ran
        log = (Path(self.scratch) / "state/agent-chrome/agent-chrome.log").read_text()
        self.assertIn("took the front at launch", log, self.launch_report())

    @unittest.skipIf(ON_RUNNER, "GitHub runner: lsappinfo setfront returns 0 and changes nothing there, so a hand-back "
                                "cannot work; proven on a real Mac instead (dotfiles#695)")
    def test_the_frontmost_app_never_changes_across_launch_and_background_tabs(self):
        try:
            self.sampler.assert_unchanged("the journey (steps at %s)" % ", ".join(
                "%s +%.1fs" % (name, at) for name, at in self.marks))
        except AssertionError as err:
            raise AssertionError("%s\n%s" % (err, self.launch_report())) from None   # the launcher's log says whether it handed the front back
