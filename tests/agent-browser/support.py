"""Shared pieces of the agent-browser journeys: a scratch Chrome of their own, a minimal MCP client over stdio, and a local page that
logs every mouse event it receives (isTrusted included).

The Chrome is started here on a port Chrome picks, with a throw-away profile; the agent Chrome (127.0.0.1:9333) and its profile are never
touched. It needs a real, visible Chrome: Chrome drops input to a hidden tab only when the window really is one, so a headless Chrome
cannot show the faults these tests guard against. A journey skips (with the reason) where there is no Chrome to start, no display, or no uvx.
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "dot_local/share/browser-harness-mcp/server.py"
PAGE = (Path(__file__).parent / "fixtures" / "click.html").read_bytes()
FROM = ["uvx", "--from", "browser-use==1.0.2"]   # the pin servers.json.tmpl uses; the launcher's own check refuses any other

MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LINUX_CHROME = "/usr/bin/google-chrome-stable"


def chrome_app():
    return os.environ.get("AGENT_CHROME_APP") or (MAC_CHROME if sys.platform == "darwin" else LINUX_CHROME)


def wayland_socket():
    """The Wayland display an agent shell may lack (t3code.service sets none): the first wayland-* socket of the user runtime dir."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return os.environ["WAYLAND_DISPLAY"]
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid())
    for sock in sorted(runtime.glob("wayland-*")):
        if sock.is_socket():
            return sock.name
    return None


def skip_reason():
    if not shutil.which("uvx"):
        return "needs uvx"
    if not os.access(chrome_app(), os.X_OK):
        return "needs Chrome at %s" % chrome_app()
    if sys.platform.startswith("linux") and not wayland_socket():
        return "needs a Wayland display for a visible Chrome"
    return None


class ScratchChrome:
    """One Chrome per test process, started on first use and stopped at exit. cdp is its http://127.0.0.1:<port> address."""

    started = None

    def __init__(self):
        self.profile = tempfile.mkdtemp(prefix="agent-browser-test-")
        # The harness keeps its daemons' sockets and pid files in a runtime dir; the tests get one of their own (short path: unix socket limit).
        self.harness = tempfile.mkdtemp(prefix="bh-", dir="/tmp")
        self.env = {"BH_HOME": self.harness + "/home", "BH_RUNTIME_DIR": self.harness + "/rt", "BH_TMP_DIR": self.harness + "/tmp",
                    "BH_RUNTIME_DIR_SHARED": "1", "BH_TMP_DIR_SHARED": "1"}   # SHARED: files named by daemon name, as the launcher's own process sets it
        cmd = [chrome_app(), "--remote-debugging-port=0", "--user-data-dir=" + self.profile, "--no-first-run", "--no-default-browser-check",
               "--disable-search-engine-choice-screen", "about:blank"]
        env = dict(os.environ)
        if sys.platform.startswith("linux"):
            cmd.insert(1, "--ozone-platform=wayland")
            env["WAYLAND_DISPLAY"] = wayland_socket()
        self.p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        port_file = Path(self.profile) / "DevToolsActivePort"   # Chrome writes the port it picked as the first line
        deadline = time.time() + 30
        while time.time() < deadline:
            if port_file.exists() and port_file.read_text().strip():
                self.cdp = "http://127.0.0.1:%s" % port_file.read_text().split()[0]
                try:
                    get(self.cdp + "/json/version")
                    return
                except OSError:
                    pass
            time.sleep(0.1)
        self.stop()
        raise RuntimeError("scratch Chrome did not answer within 30s")

    def stop(self):
        self.p.terminate()
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
        shutil.rmtree(self.profile, ignore_errors=True)
        shutil.rmtree(self.harness, ignore_errors=True)

    @classmethod
    def get(cls):
        if cls.started is None:
            cls.started = cls()
            atexit.register(cls.started.stop)
        return cls.started


class Mcp:
    """A minimal MCP client over the server's stdio (newline-delimited JSON-RPC)."""

    def __init__(self, chrome, command=None, env=None):
        self.cdp = chrome.cdp
        base = dict(os.environ, BU_CDP_URL=chrome.cdp, **chrome.env)
        base.pop("BU_NAME", None)   # the launcher gives each process its own; only a test that wants a name sets one
        env = {**base, **(env or {})}
        self.p = subprocess.Popen(command or FROM + ["python", "-I", str(LAUNCHER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, env=env, cwd="/tmp")
        self.n = 0
        self.call_raw("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "journey", "version": "0"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()

    def call_raw(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise AssertionError("MCP server closed its output")
            msg = json.loads(line)
            if msg.get("id") == self.n:
                return msg

    def tool(self, name, **args):
        """Call a tool. Returns (is_error, text of the result)."""
        msg = self.call_raw("tools/call", {"name": name, "arguments": args})
        result = msg["result"]
        return bool(result.get("isError")), "".join(c.get("text", "") for c in result["content"] if c.get("type") == "text")

    def run(self, code):
        """browser_exec; a failed cell raises AssertionError carrying its traceback, so a refusal is assertRaises-able. Returns the printed text."""
        failed, text = self.tool("browser_exec", code=code)
        if failed:
            raise AssertionError(text)
        return text

    def new_tab(self, url):
        return self.run("print('TID=' + new_tab(%r))" % url).split("TID=")[1].split()[0]

    def current_tab(self):
        return self.run("print('TID=' + current_tab()['targetId'])").split("TID=")[1].split()[0]

    def click(self, x=200, y=140):
        self.run("click_at_xy(%d, %d)" % (x, y))

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=30)
        except Exception:
            self.p.kill()
        self.p.stdout.close()


class StockMcp(Mcp):
    """The unmodified `browser-use --cli-mcp`: the red control. With a name it has a daemon of its own; without, the daemon "default" that
    every stock server on the machine shares (here: every one of this test run's Chrome)."""

    def __init__(self, chrome, name=None):
        self.chrome, self.name = chrome, name
        super().__init__(chrome, command=FROM + ["browser-use", "--cli-mcp"], env={"BU_NAME": name} if name else {})

    def close(self):
        super().close()
        subprocess.run(FROM + ["python", "-I", "-c", "from browser_harness.admin import restart_daemon; restart_daemon(%r)" % self.name],
                       env=dict(os.environ, BU_CDP_URL=self.cdp, **self.chrome.env), capture_output=True, timeout=60, cwd="/tmp")


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read()


def tabs(cdp):
    return [t for t in json.loads(get(cdp + "/json/list")) if t["type"] == "page"]


def close_from_outside(cdp, target_id):
    """Chrome's own /json/close/<exact id>; waits until Chrome no longer lists it."""
    get("%s/json/close/%s" % (cdp, target_id))
    deadline = time.time() + 10
    while time.time() < deadline:
        if all(t["id"] != target_id for t in tabs(cdp)):
            return
        time.sleep(0.1)
    raise AssertionError("tab %s did not close" % target_id)


@unittest.skipIf(skip_reason(), skip_reason() or "")
class JourneyCase(unittest.TestCase):
    """A local page that logs every mouse event it receives (self.events), a scratch Chrome (self.cdp) and the MCP sessions a test opens."""

    @classmethod
    def setUpClass(cls):
        cls.chrome = ScratchChrome.get()
        cls.cdp = cls.chrome.cdp

    def setUp(self):
        self.events = events = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("content-type", "text/html")
                self.end_headers()
                self.wfile.write(PAGE)

            def do_POST(self):
                events.append(json.loads(self.rfile.read(int(self.headers.get("content-length", 0)))))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d/" % self.http.server_address[1]
        self.sessions = []
        self.opened = []

    def tearDown(self):
        for s in self.sessions:
            s.close()
        for tab in self.opened:   # each tab this test opened, by its exact id
            try:
                get("%s/json/close/%s" % (self.cdp, tab))
            except Exception:
                pass
        self.http.shutdown()

    def mcp(self, **kw):
        s = Mcp(self.chrome, **kw)
        self.sessions.append(s)
        return s

    def open_page(self, server, name):
        tab = server.new_tab(self.base + "?page=" + name)
        self.opened.append(tab)
        self.wait_until(lambda: self.events_of(name, "load"), "page %s to load" % name)
        return tab

    def wait_until(self, condition, what, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return
            time.sleep(0.05)
        self.fail("timed out waiting for %s: %s" % (what, self.events))

    def events_of(self, page, ev):
        return [e for e in self.events if e.get("page") == page and e.get("ev") == ev]

    def clicks(self, page):
        return self.events_of(page, "click")
