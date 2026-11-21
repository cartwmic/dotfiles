"""Launching the agent Chrome and driving it must never change the frontmost app (macOS only).

The frontmost-app steal is a macOS behavior: a directly exec'd Chrome (or open -g -n with a startup window)
becomes the frontmost app, and CDP activation calls raise its window. This journey launches the real
agent-chrome script on a scratch port and profile (AGENT_CHROME_PROFILE), then drives background tabs over
CDP (Target.createTarget with background:true) to a local HTTP server. A sampler thread reads the frontmost
app every ~50 ms from before the launch until after the last step, so a steal that comes and goes (the
launcher hands the front back within seconds) is still caught: the journey fails on any change and reports
when it happened and how long it lasted. It skips off macOS, without Chrome, or when AGENT_CHROME_APP points
at the fake (/nonexistent), like the other journeys.

Set AGENT_CHROME_LAUNCHER to run this same journey against another launcher script.
"""
import base64
import json
import os
import shutil
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


@unittest.skipUnless(sys.platform == "darwin", "macOS only: the frontmost-app steal is a macOS behavior")
@unittest.skipIf(not os.access(CHROME_APP, os.X_OK), "needs Chrome at %s" % CHROME_APP)
class NoFocusSteal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sampler = FrontSampler()
        cls.sampler.start()  # before the launch: a launch-time steal must show up as a change from the baseline sample
        cls.scratch = tempfile.mkdtemp(prefix="agent-chrome-focus-")
        cls.port = free_port()
        cls.env = dict(os.environ,
                       AGENT_CHROME_PORT=str(cls.port),
                       AGENT_CHROME_PROFILE=cls.scratch + "/profile",
                       AGENT_CHROME_WAIT="30",
                       XDG_STATE_HOME=cls.scratch + "/state")
        r = subprocess.run([str(LAUNCHER)], env=cls.env, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise AssertionError("agent-chrome did not start: " + (r.stdout + r.stderr).strip())
        cls.cdp = "http://127.0.0.1:%s" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.sampler.stop()
        subprocess.run([str(LAUNCHER), "--stop"], env=cls.env, capture_output=True, text=True, timeout=60)
        shutil.rmtree(cls.scratch, ignore_errors=True)

    def setUp(self):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("content-type", "text/html")
                self.end_headers()
                self.wfile.write(PAGE)

            def log_message(self, *a):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d/" % self.http.server_address[1]

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()

    def same_frontmost(self, step):
        self.sampler.assert_unchanged(step)

    def test_launch_and_background_tabs_keep_the_frontmost_app(self):
        self.same_frontmost("launching the agent Chrome")
        self.assertGreaterEqual(len(tabs(self.cdp)), 1)  # default form b creates the first window over CDP
        cdp_call(self.cdp, "Target.createTarget", {"url": self.base + "?page=one", "background": True})
        self.same_frontmost("first background tab")
        cdp_call(self.cdp, "Target.createTarget", {"url": self.base + "?page=two", "background": True})
        self.same_frontmost("second background tab")
        urls = [t["url"] for t in tabs(self.cdp)]
        self.assertIn(self.base + "?page=two", urls)  # the driving really reached the agent Chrome
        time.sleep(2)  # settle: an asynchronous raise landing after the last call returns would slip past an immediate re-read
        self.same_frontmost("final re-read after the journey settled")
