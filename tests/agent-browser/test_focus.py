"""agent-chrome focus: the real launcher script against a fake Chrome debug port (an HTTP server in this process that serves /json/list
and records /json/activate/ID calls) and a scratch HOME. Never touches a real Chrome."""
import http.server
import json
import os
import socketserver
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_agent-chrome"


def page(id, url, type="page"):
    return {"id": id, "type": type, "url": url, "title": id}


class FakeChrome:
    def __init__(self, targets, activate_status=200):
        activated = self.activated = []
        listing = json.dumps(targets).encode()

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/json/list":
                    self.send_response(200); self.end_headers(); self.wfile.write(listing)
                elif self.path.startswith("/json/activate/"):
                    activated.append(self.path.rsplit("/", 1)[1])
                    self.send_response(activate_status); self.end_headers(); self.wfile.write(b"Target activated")
                else:
                    self.send_response(404); self.end_headers()

            def log_message(self, *a):
                pass
        # TCPServer, not HTTPServer: HTTPServer.server_bind calls getfqdn(), which can stall for many seconds on CI runners.
        self.server = socketserver.TCPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class FocusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agent-chrome-focus-test-")
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def focus(self, chrome, *args, port=None):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "AGENT_CHROME_PORT": str(port or chrome.port), "AGENT_CHROME_OS": "Darwin"}
        return subprocess.run(["sh", str(SCRIPT), "focus", *args], env=env, capture_output=True, text=True, timeout=30)

    def serve(self, targets, **kw):
        chrome = FakeChrome(targets, **kw)
        self.addCleanup(chrome.close)
        return chrome

    def test_one_match_activates_that_page_and_prints_its_url(self):
        chrome = self.serve([page("A1", "https://example.com/"), page("B2", "https://github.com/login"), page("C3", "https://news.example.org/")])
        r = self.focus(chrome, "github.com")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(chrome.activated, ["B2"])
        self.assertIn("https://github.com/login", r.stdout)

    def test_no_match_exits_1_activates_nothing_and_lists_the_open_pages(self):
        chrome = self.serve([page("A1", "https://example.com/"), page("B2", "https://news.example.org/")])
        r = self.focus(chrome, "github.com")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(chrome.activated, [])
        self.assertIn("0 pages contain", r.stderr)
        self.assertIn("https://example.com/", r.stderr)
        self.assertIn("https://news.example.org/", r.stderr)

    def test_several_matches_exit_1_activate_nothing_and_list_the_candidates(self):
        chrome = self.serve([page("A1", "https://github.com/one"), page("B2", "https://github.com/two"), page("C3", "https://example.com/")])
        r = self.focus(chrome, "github.com")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(chrome.activated, [])
        self.assertIn("2 pages contain", r.stderr)
        self.assertIn("https://github.com/one", r.stderr)
        self.assertIn("https://github.com/two", r.stderr)

    def test_a_service_worker_or_extension_background_target_is_not_a_page(self):
        chrome = self.serve([page("S1", "https://github.com/sw.js", type="service_worker"), page("B2", "https://github.com/login")])
        r = self.focus(chrome, "github.com")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(chrome.activated, ["B2"])

    def test_the_extension_settings_page_can_be_focused_by_its_id(self):   # the pairing steps use this
        url = "chrome-extension://mfnicocicmmlkpjnaffgihfjhdgjkdjg/settings.html"
        chrome = self.serve([page("A1", "https://example.com/"), page("E5", url)])
        self.assertEqual(self.focus(chrome, "mfnicocicmmlkpjnaffgihfjhdgjkdjg").returncode, 0)
        self.assertEqual(chrome.activated, ["E5"])

    def test_chrome_refusing_the_activation_exits_1(self):
        chrome = self.serve([page("B2", "https://github.com/login")], activate_status=500)
        r = self.focus(chrome, "github.com")
        self.assertEqual(r.returncode, 1)
        self.assertIn("refused to activate", r.stderr)

    def test_nothing_on_the_port_exits_1_and_says_to_start_chrome(self):
        import socket
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        r = self.focus(None, "github.com", port=port)
        self.assertEqual(r.returncode, 1)
        self.assertIn("run agent-chrome first", r.stderr)

    def test_no_url_part_exits_2_and_says_how_to_call_it(self):
        chrome = self.serve([])
        r = self.focus(chrome)
        self.assertEqual(r.returncode, 2)
        self.assertIn("agent-chrome focus URLPART", r.stderr)

    def test_the_outcome_is_logged_with_the_launchers_record(self):
        chrome = self.serve([page("B2", "https://github.com/login")])
        self.focus(chrome, "github.com")
        self.focus(chrome, "nowhere.example")
        log = (self.home / ".local/state/agent-chrome/agent-chrome.log").read_text().splitlines()
        self.assertEqual(len(log), 2)
        self.assertRegex(log[0], r"^\d{4}-\d\d-\d\dT[\d:]+Z run=\S+ elapsed=\d+s \[agent-chrome\] INFO: activated https://github.com/login \(id B2\)$")
        self.assertIn("ERROR: 0 pages contain", log[1])


if __name__ == "__main__":
    unittest.main()
