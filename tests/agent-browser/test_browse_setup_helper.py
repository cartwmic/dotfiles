"""agent-browse-setup: the real script against fakes, in a scratch HOME. It never touches a real Chrome, the real relay or the real agent profile.
Fakes: `agent-chrome` and `browse` (scripts first on PATH) and a Chrome debug port (an HTTP server in this process that serves /json/list and records
the PUT /json/new calls that open pages). A thread plays the person: it waits for the pairing code file, reads it, and "types" it (the fake `browse pair` ends
connected), or installs the extension when the Web Store page is opened.
Every test bounds each wait the helper can reach (--wait-seconds, a short settle, a fake `browse pair` that gives up after 5 s), so a regression fails in
seconds with the helper's output, and a helper that still hangs is killed with everything it started (own process group), never left behind."""
import http.server
import json
import os
import signal
import socketserver
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_agent-browse-setup"
EXT = "mfnicocicmmlkpjnaffgihfjhdgjkdjg"
STORE = "https://chromewebstore.google.com/detail/" + EXT
SETTINGS = "chrome-extension://%s/settings.html" % EXT
CODE = "PAIRCODE-7741-QXZ"   # what the fake `browse pair` prints; no output of the helper may contain it
HELPER_TIMEOUT = 30   # a run that is still going after this is a bug: it is killed with its children and the test fails
PAIR_CAP = 5          # the fake `browse pair` gives up after this many seconds whatever --wait-seconds says

FAKE_AGENT_CHROME = "#!/bin/sh\necho agent-chrome >> \"$FAKE_DIR/calls.log\"\n[ -z \"$FAKE_CHROME_FAIL\" ] || { echo 'chrome is broken' >&2; exit 1; }\nexit 0\n"
FAKE_BROWSE = """#!@PY@
import json, os, stat, sys, time
d = os.environ["FAKE_DIR"]
def flag(name): return os.path.exists(os.path.join(d, name))
open(os.path.join(d, "calls.log"), "a").write("browse " + " ".join(sys.argv[1:]) + "\\n")
if sys.argv[1:] == ["status", "--json"]:
    # browse 0.1.0 with no relay running: no `connected` key, only `relay` and `setup`. Any tool call (here: any command but status and pair) starts the relay.
    print(json.dumps({"connected": flag("connected")} if flag("relay-up") else {"relay": {"running": False}, "setup": {"installed": True}}))
elif sys.argv[1:] == ["status"]:
    print("Extension: " + ("connected" if flag("connected") else "not connected"))
elif sys.argv[1] != "pair":
    open(os.path.join(d, "relay-up"), "w").close()
    print(json.dumps({"tabs": []}))
else:
    open(os.path.join(d, "relay-up"), "w").close()   # `browse pair` serves a relay too
    open(os.path.join(d, "pair-out-mode"), "w").write(oct(stat.S_IMODE(os.fstat(1).st_mode)))
    print("Pairing code: %s" % os.environ["FAKE_CODE"]); print("Waiting for the browser that redeems it..."); sys.stdout.flush()
    deadline = time.time() + min(int(sys.argv[3]), @CAP@)
    while time.time() < deadline:
        if flag("redeemed"):
            open(os.path.join(d, "connected"), "w").close(); sys.exit(0)
        time.sleep(0.1)
    sys.exit(1)
""".replace("@PY@", sys.executable).replace("@CAP@", str(PAIR_CAP))


class FakeChrome:
    def __init__(self, extension_installed, on_open=None):
        self.opened = []
        self.workers = [{"type": "service_worker", "url": "chrome-extension://%s/service_worker.js" % EXT}] if extension_installed else []
        chrome = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps(chrome.workers + [{"type": "page", "url": "about:blank"}]).encode())

            def do_PUT(self):
                assert self.path.startswith("/json/new?"), self.path
                url = unquote(self.path.split("?", 1)[1])
                chrome.opened.append(url)
                if on_open:
                    on_open(chrome, url)
                self.send_response(200); self.end_headers(); self.wfile.write(b"{}")

            def log_message(self, *a):
                pass
        self.server = socketserver.TCPServer(("127.0.0.1", 0), H)   # not HTTPServer: its server_bind can stall on getfqdn()
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class SetupHelperTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agent-browse-setup-test-")
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.fake = self.root / "fake"
        self.fake.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name, body in (("agent-chrome", FAKE_AGENT_CHROME), ("browse", FAKE_BROWSE)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        self.state = self.home / ".local/state/agent-browse-setup"
        self.code_file = self.state / "pairing-code"
        self.chromes = []
        self.seen = {}   # what the person-thread observed

    def tearDown(self):
        for c in self.chromes:
            c.close()
        self.tmp.cleanup()

    def chrome(self, **kw):
        c = FakeChrome(**kw)
        self.chromes.append(c)
        return c

    def flag(self, name):
        (self.fake / name).write_text("")

    def install_extension_folder(self, version="0.1.5_0", manifest=True):
        """What Chrome leaves in the agent profile for an installed extension."""
        d = self.home / ".local/share/agent-chrome-profile/Default/Extensions" / EXT / version
        d.mkdir(parents=True)
        if manifest:
            (d / "manifest.json").write_text("{}")

    def calls(self):
        p = self.fake / "calls.log"
        return p.read_text().splitlines() if p.exists() else []

    def person_redeems(self):
        """Waits for the code file, reads it like an agent would (cat), and 'types' it."""
        def run():
            end = time.time() + 20
            while time.time() < end:
                if self.code_file.exists():
                    self.seen["mode"] = stat.S_IMODE(self.code_file.stat().st_mode)
                    self.seen["code"] = self.code_file.read_text()
                    if self.seen["code"]:
                        self.flag("redeemed")
                        return
                time.sleep(0.05)
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t

    def run_helper(self, chrome, *args, **extra):
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.home), "AGENT_CHROME_PORT": str(chrome.port),
               "FAKE_DIR": str(self.fake), "FAKE_CODE": CODE, "XDG_STATE_HOME": str(self.home / ".local/state"), "AGENT_BROWSE_SETUP_SETTLE": "1"}
        env.update(extra)
        proc = subprocess.Popen(["sh", str(SCRIPT), *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            out, err = proc.communicate(timeout=HELPER_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.kill_group(proc)
            out, err = proc.communicate()
            self.fail("the helper was still running after %ss (killed with its children)\nstdout:\n%s\nstderr:\n%s" % (HELPER_TIMEOUT, out, err))
        finally:
            self.kill_group(proc)   # a fake `browse pair` the helper left behind
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

    @staticmethod
    def kill_group(proc):
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def log(self):
        return (self.state / "agent-browse-setup.log").read_text()

    def assert_code_not_leaked(self, r):
        self.assertNotIn(CODE, r.stdout)
        self.assertNotIn(CODE, r.stderr)
        self.assertNotIn(CODE, self.log())

    def test_a_paired_profile_with_no_relay_running_is_connected_once_the_helper_starts_the_relay(self):
        chrome = self.chrome(extension_installed=True)
        self.flag("connected")   # paired: but `browse status --json` shows it only while a relay runs, and nothing has started one
        r = self.run_helper(chrome, "--wait-seconds", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(chrome.opened, [])
        self.assertEqual([c for c in self.calls() if c.startswith("browse pair")], [])
        self.assertEqual(r.stdout.splitlines()[-1], "Extension: connected")

    def test_a_relay_that_is_already_running_and_connected_prints_the_status_and_changes_nothing(self):
        chrome = self.chrome(extension_installed=True)
        self.flag("relay-up")
        self.flag("connected")
        r = self.run_helper(chrome, "--wait-seconds", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(chrome.opened, [])
        self.assertEqual([c for c in self.calls() if c.startswith("browse pair")], [])
        self.assertEqual(r.stdout.splitlines()[-1], "Extension: connected")

    def test_a_paired_profile_that_reads_connected_a_moment_after_chrome_starts_is_left_alone(self):
        chrome = self.chrome(extension_installed=False)   # the service worker is not up yet either
        self.flag("relay-up")
        threading.Timer(1.0, lambda: (self.flag("connected"), chrome.workers.append({"type": "service_worker", "url": "chrome-extension://%s/sw.js" % EXT}))).start()
        r = self.run_helper(chrome, "--wait-seconds", "2", AGENT_BROWSE_SETUP_SETTLE="4")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(chrome.opened, [])
        self.assertEqual([c for c in self.calls() if c.startswith("browse pair")], [])

    def test_extension_present_opens_the_settings_page_pairs_and_ends_connected(self):
        chrome = self.chrome(extension_installed=True)
        person = self.person_redeems()
        r = self.run_helper(chrome)
        person.join(timeout=5)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(chrome.opened, [SETTINGS])   # the Store page is not opened when the extension is there
        self.assertIn("browse pair --wait-seconds 180", self.calls())
        self.assertEqual(self.calls()[0], "agent-chrome")   # Chrome first
        self.assertEqual((self.seen["mode"], self.seen["code"]), (0o600, CODE + "\n"))   # the code file, as the person read it: the code alone
        self.assertEqual(oct(int((self.fake / "pair-out-mode").read_text(), 8)), "0o600")   # and the file `browse pair` wrote into
        self.assert_code_not_leaked(r)
        self.assertFalse(self.code_file.exists(), "the code file is removed at the end")
        for left in ('"Pair with a code"', 'agent-desktop type "$(cat %s)"' % self.code_file, '"Pairing code"', '"Connect"'):
            self.assertIn(left, r.stdout)
        self.assertNotIn("\ncat ", r.stdout)   # the instruction never has the agent print the file
        self.assertFalse((self.state / "pair-output").exists())
        self.assertIn("connected.", self.log())   # one persisted line per outcome, with the run id
        self.assertEqual(r.stdout.splitlines()[-1], "[agent-browse-setup] connected.")
        self.assertIn("Extension: connected", r.stdout)   # `browse status` was run before the last line

    def test_extension_missing_opens_the_store_waits_for_the_click_then_carries_on(self):
        def install_when_store_opens(chrome, url):
            if url == STORE:
                threading.Timer(1.0, lambda: chrome.workers.append({"type": "service_worker", "url": "chrome-extension://%s/sw.js" % EXT})).start()
        chrome = self.chrome(extension_installed=False, on_open=install_when_store_opens)
        person = self.person_redeems()
        r = self.run_helper(chrome, "--wait-seconds", "8")
        person.join(timeout=5)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(chrome.opened, [STORE, SETTINGS])
        self.assertIn('click "Add to Chrome"', r.stdout)
        self.assert_code_not_leaked(r)

    def test_extension_never_installed_fails_naming_the_store_page_and_never_pairs(self):
        chrome = self.chrome(extension_installed=False)
        r = self.run_helper(chrome, "--wait-seconds", "1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(chrome.opened, [STORE])
        self.assertIn(STORE, r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith("browse pair")], [])
        self.assertIn("ERROR: the extension did not appear", self.log())

    def test_an_extension_folder_in_the_profile_counts_as_installed_when_chrome_lists_no_service_worker(self):
        chrome = self.chrome(extension_installed=False)   # an idle worker is not listed
        self.install_extension_folder()
        person = self.person_redeems()
        r = self.run_helper(chrome, "--wait-seconds", "5")
        person.join(timeout=5)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(chrome.opened, [SETTINGS])   # no Store page
        self.assertIn("browse pair --wait-seconds 5", self.calls())
        self.assert_code_not_leaked(r)

    def test_an_extension_folder_with_no_version_inside_is_not_an_install(self):
        chrome = self.chrome(extension_installed=False)
        (self.home / ".local/share/agent-chrome-profile/Default/Extensions" / EXT).mkdir(parents=True)
        r = self.run_helper(chrome, "--wait-seconds", "1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(chrome.opened, [STORE])
        self.assertEqual([c for c in self.calls() if c.startswith("browse pair")], [])

    def test_a_version_folder_with_no_manifest_is_not_an_install(self):
        chrome = self.chrome(extension_installed=False)
        self.install_extension_folder(manifest=False)
        r = self.run_helper(chrome, "--wait-seconds", "1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(chrome.opened, [STORE])

    def test_an_extension_folder_that_appears_while_the_helper_waits_after_the_store_page_carries_it_on(self):
        chrome = self.chrome(extension_installed=False, on_open=lambda c, url: url == STORE and threading.Timer(1.0, self.install_extension_folder).start())
        person = self.person_redeems()
        r = self.run_helper(chrome, "--wait-seconds", "8")
        person.join(timeout=5)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(chrome.opened, [STORE, SETTINGS])
        self.assert_code_not_leaked(r)

    def test_the_helper_looks_in_the_profile_agent_chrome_starts(self):
        line = 'PROFILE="$HOME/.local/share/agent-chrome-profile"'
        for script in (SCRIPT, SCRIPT.with_name("executable_agent-chrome")):
            with self.subTest(script=script.name):
                self.assertIn(line, script.read_text().splitlines())

    def test_a_code_nobody_types_fails_and_still_ends_with_the_status(self):
        chrome = self.chrome(extension_installed=True)
        r = self.run_helper(chrome, "--wait-seconds", "2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("browse pair --wait-seconds 2", self.calls())
        self.assertIn("Extension: not connected", r.stdout)
        self.assertIn("not connected", r.stderr)
        self.assert_code_not_leaked(r)
        self.assertFalse(self.code_file.exists())

    def test_chrome_that_will_not_start_stops_everything(self):
        chrome = self.chrome(extension_installed=True)
        r = self.run_helper(chrome, FAKE_CHROME_FAIL="1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(chrome.opened, [])
        self.assertEqual(self.calls(), ["agent-chrome"])

    def test_a_bad_argument_is_a_usage_error(self):
        chrome = self.chrome(extension_installed=True)
        for args in (("--wait-seconds", "soon"), ("--wait-seconds",), ("--bogus",)):
            with self.subTest(args=args):
                r = self.run_helper(chrome, *args)
                self.assertEqual(r.returncode, 2)
                self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
