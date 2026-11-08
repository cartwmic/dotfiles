"""Journey: two agents drive the agent Chrome through the real browser-harness MCP launcher (server.py), each in its own tab,
and each click reaches the page the agent opened.

Before the launcher, one shared daemon kept one current tab (the second agent's tab took the first agent's click) and Chrome dropped
clicks to a background tab with no error. A local page logs every mouse event it receives (isTrusted included).

Needs macOS, uvx, and the agent Chrome answering on 127.0.0.1:9333 (`agent-chrome`); otherwise it skips. It only opens two tabs of its own and closes them.
"""
import json
import os
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "dot_local/share/browser-harness-mcp/server.py"
PAGE = (Path(__file__).parent / "fixtures" / "click.html").read_bytes()
CDP = "http://127.0.0.1:9333"


def chrome_up():
    try:
        urllib.request.urlopen(CDP + "/json/version", timeout=2).read()
        return True
    except Exception:
        return False


class Mcp:
    """A minimal MCP client over the server's stdio (newline-delimited JSON-RPC)."""

    def __init__(self):
        env = dict(os.environ, BU_CDP_URL=CDP)
        env.pop("BU_NAME", None)
        self.p = subprocess.Popen(["uvx", "--from", "browser-harness[mcp]==0.1.13", "python", "-I", str(LAUNCHER)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env, cwd="/tmp")
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
        msg = self.call_raw("tools/call", {"name": name, "arguments": args})
        text = "".join(c.get("text", "") for c in msg["result"]["content"])
        data = json.loads(text) if text else None
        if isinstance(data, dict) and "error" in data:
            raise AssertionError("%s: %s" % (name, data["error"]))
        return data

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=30)
        except Exception:
            self.p.kill()


@unittest.skipUnless(sys.platform == "darwin" and chrome_up(), "needs macOS and the agent Chrome on 127.0.0.1:9333")
class ClickJourney(unittest.TestCase):
    def setUp(self):
        self.events = []

        events = self.events

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

    def tearDown(self):
        for s in self.sessions:
            s.close()
        self.http.shutdown()

    def wait_until(self, condition, what, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return
            time.sleep(0.1)
        self.fail("timed out waiting for %s: %s" % (what, self.events))

    def events_of(self, page, ev):
        return [e for e in self.events if e.get("page") == page and e.get("ev") == ev]

    def clicks(self, page):
        return [e for e in self.events if e.get("page") == page and e.get("ev") == "click"]

    def test_each_agent_clicks_its_own_tab(self):
        a, b = Mcp(), Mcp()
        self.sessions += [a, b]
        tab_a = a.tool("browser_new_tab", url=self.base + "?page=A")["targetId"]
        tab_b = b.tool("browser_new_tab", url=self.base + "?page=B")["targetId"]  # moves a shared daemon's current tab; must not move A's
        self.assertNotEqual(tab_a, tab_b)
        self.assertEqual(a.tool("browser_ensure_real_tab")["targetId"], tab_a)  # stock switches to Chrome's first real page
        self.wait_until(lambda: self.events_of("A", "load") and self.events_of("B", "load"), "both pages to load")
        a.tool("browser_click", x=200, y=140)
        b.tool("browser_click", x=200, y=140)
        self.wait_until(lambda: self.clicks("A") and self.clicks("B"), "a click on each page")
        time.sleep(0.5)  # a stray second click on either page would show up here
        self.assertEqual(len(self.clicks("A")), 1, self.events)
        self.assertEqual(len(self.clicks("B")), 1, self.events)
        for page in ("A", "B"):
            self.assertTrue(self.clicks(page)[0]["isTrusted"])
        for s, tab in ((a, tab_a), (b, tab_b)):
            s.tool("browser_close_tab", target=tab)


if __name__ == "__main__":
    unittest.main()
