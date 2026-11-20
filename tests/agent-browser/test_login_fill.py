"""agent-login: the real script against a real headless Chrome (a scratch profile, a port Chrome picks; the agent Chrome is never touched), a
local page that reports what is typed into it, and a fake `op` first on PATH that serves fixture JSON. The fake op can also move the page to
another host while it "reads" the value, which is the window between the lookup and the typing. Skips where there is no Chrome or no node."""
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
from urllib.parse import parse_qs, quote, urlsplit

MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
LINUX_CHROME = "/usr/bin/google-chrome-stable"


def chrome_app():
    return os.environ.get("AGENT_CHROME_APP") or (MAC_CHROME if sys.platform == "darwin" else LINUX_CHROME)


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_agent-login"
SECRET = "s3cr3t-Pa55,with\"odd'chars"
PAGE = b"""<!doctype html><title>login</title>
<input id=user type=text><input id=pw type=password><input id=other type=text><input id=trunc type=text><input id=hop type=text><input id=keep type=text value=keepme><button id=btn>go</button>
<script>
const q = new URLSearchParams(location.search), t = q.get('t');
const post = (path, body) => fetch(path, {method: 'POST', body: JSON.stringify(body)});
/* a typed value is recorded synchronously, inside the input event: Input.insertText returns only after the handler has, so when agent-login
   returns the server already holds the record (a fetch here left the record in flight when the test read it: issue 637) */
const record = (body) => { const x = new XMLHttpRequest(); x.open('POST', '/value', false); x.send(JSON.stringify(body)); };
for (const el of document.querySelectorAll('input')) el.addEventListener('input', () => { if (el.id === 'trunc') el.value = el.value.slice(0, 3);
  /* hop keeps 3 characters and moves focus on */ if (el.id === 'hop') { el.value = el.value.slice(0, 3); document.getElementById('keep').focus(); }
  record({t, host: location.hostname, id: el.id, value: el.value}); });
if (q.get('focus')) document.getElementById(q.get('focus')).focus();
post('/loaded', {t, host: location.hostname});
if (q.has('poll')) setInterval(async () => { const r = await (await fetch('/swap?t=' + t)).json(); if (r.to) location.href = r.to; }, 50);
</script>"""
FAKE_OP = """#!PYTHON
import json, os, sys, urllib.request
d = os.environ["FAKE_OP_DIR"]
args = sys.argv[1:]
open(d + "/calls", "a").write(json.dumps({"argv": args, "env": dict(os.environ)}) + "\\n")
if args[args.index("--vault") + 1] != "developer":
    sys.exit("wrong vault")
if args[:2] == ["item", "list"]:
    assert "--categories" in args and args[args.index("--categories") + 1] == "Login"
    print(open(d + "/items.json").read())
elif args[:2] == ["item", "get"]:
    if os.environ.get("FAKE_OP_TRIGGER"):   # the page moves to another host while the value is being read
        urllib.request.urlopen(os.environ["FAKE_OP_TRIGGER"], timeout=20).read()
    values = json.load(open(d + "/values.json"))[args[2]]
    if "--otp" in args:
        print(values["otp"])
    else:
        field = args[args.index("--fields") + 1]
        value = values[field]
        if value.startswith("RAW:"):   # op answering with something that is not JSON
            print(value)
            sys.exit(0)
        if field == "password" and "--reveal" not in args:   # what the real op prints for a concealed field that was not revealed
            value = "[use 'op item get %s --reveal' to reveal]" % args[2]
        print(json.dumps({"id": field, "value": value}))
else:
    sys.exit("unexpected " + " ".join(args))
""".replace("PYTHON", sys.executable)


def skip_reason():
    if not shutil.which("node"):
        return "needs node"
    if subprocess.run(["node", "-e", "process.exit(typeof WebSocket === 'function' ? 0 : 1)"]).returncode:
        return "needs a node with a global WebSocket (22 or later)"
    if not os.access(chrome_app(), os.X_OK):
        return "needs Chrome at %s" % chrome_app()
    return None


def item(id, title, *urls):
    return {"id": id, "title": title, "category": "LOGIN", "urls": [{"href": u} for u in urls]}


# On GitHub's runner a missing Chrome or node is a failure, not a skip: a skipped suite proves nothing.
if os.environ.get("GITHUB_ACTIONS") and skip_reason():
    raise RuntimeError("agent-login tests cannot run on this runner: " + skip_reason())


@unittest.skipIf(skip_reason(), skip_reason() or "")
class LoginFillTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.events, cls.swaps, cls.lock, cls.record_delay = [], {}, threading.Lock(), 0
        outer = cls

        class H(BaseHTTPRequestHandler):
            def reply(self, body=b"", status=200):
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                url = urlsplit(self.path)
                token = parse_qs(url.query).get("t", [""])[0]
                if url.path == "/swap":
                    self.reply(json.dumps({"to": outer.swaps.get(token)}).encode())
                elif url.path == "/trigger":   # from the fake op: send the page to the host in ?host=, then wait until it has loaded there
                    host = parse_qs(url.query)["host"][0]
                    outer.swaps[token] = "http://%s:%d/?t=%s&focus=pw" % (host, outer.port, token)
                    outer.wait_for(lambda: outer.events_of(token, "loaded", host), "the page to load on " + host)
                    self.reply(b"moved")
                else:
                    self.send_response(200)
                    self.send_header("content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(PAGE)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
                if self.path == "/value":
                    time.sleep(outer.record_delay)   # a slow runner: the report of a typed value reaches the server late
                with outer.lock:
                    outer.events.append({"ev": self.path[1:], **body})
                self.reply(status=204)

            def log_message(self, *a):
                pass

        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), H)
        cls.port = cls.http.server_address[1]
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.profile = tempfile.mkdtemp(prefix="agent-login-test-")
        cls.chrome = subprocess.Popen([chrome_app(), "--headless=new", "--disable-extensions", "--remote-debugging-port=0", "--user-data-dir=" + cls.profile, "--no-first-run",
                                       "--no-default-browser-check", "--no-sandbox", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = Path(cls.profile) / "DevToolsActivePort"
        cls.wait_for(lambda: port_file.exists() and port_file.read_text().strip(), "Chrome to write its debug port", timeout=30)
        cls.cdp_port = port_file.read_text().split()[0]
        cls.wait_for(lambda: cls.get("/json/version"), "Chrome to answer", timeout=30)

    @classmethod
    def tearDownClass(cls):
        cls.chrome.terminate()
        try:
            cls.chrome.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.chrome.kill()
        cls.http.shutdown()
        shutil.rmtree(cls.profile, ignore_errors=True)

    @classmethod
    def get(cls, path, method="GET"):
        try:
            with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%s%s" % (cls.cdp_port, path), method=method), timeout=10) as r:
                return r.read()
        except OSError:
            return None

    @classmethod
    def wait_for(cls, condition, what, timeout=20):   # a fact is waited for, not slept on
        deadline = time.time() + timeout
        while time.time() < deadline:
            if condition():
                return
            time.sleep(0.05)
        raise AssertionError("timed out waiting for " + what)

    @classmethod
    def events_of(cls, token, ev, host=None):
        with cls.lock:
            return [e for e in cls.events if e["t"] == token and e["ev"] == ev and (host is None or e["host"] == host)]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agent-login-fake-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "bin").mkdir()
        op = self.tmp / "bin" / "op"
        op.write_text(FAKE_OP)
        op.chmod(0o755)
        self.tabs = []
        self.addCleanup(lambda: [self.get("/json/close/" + t) for t in self.tabs])
        self.n = 0

    def page(self, host="localhost", focus="pw", poll=False):
        """Open a tab on host. Returns the token its URL carries, which is the URL part agent-login is given."""
        self.n += 1
        token = "%s-%d" % (self.id().rsplit(".", 1)[1][:30], self.n)
        url = "http://%s:%d/?t=%s%s%s" % (host, self.port, token, "&focus=" + focus if focus else "", "&poll" if poll else "")
        target = json.loads(self.get("/json/new?" + quote(url, safe=""), method="PUT"))
        self.tabs.append(target["id"])
        self.wait_for(lambda: self.events_of(token, "loaded"), "page %s to load" % token)
        return token

    def login(self, field, part, items, values=None, *extra, trigger=None, raw_items=None):
        (self.tmp / "items.json").write_text(raw_items if raw_items is not None else json.dumps(items))
        (self.tmp / "values.json").write_text(json.dumps(values or {i["id"]: {"username": "u-" + i["id"], "password": SECRET, "otp": "123456"} for i in items}))
        env = {"PATH": "%s:%s" % (self.tmp / "bin", os.environ["PATH"]), "HOME": str(self.tmp), "XDG_STATE_HOME": str(self.tmp / "state"),
               "AGENT_CHROME_PORT": self.cdp_port, "FAKE_OP_DIR": str(self.tmp)}
        if trigger:
            env["FAKE_OP_TRIGGER"] = trigger
        return subprocess.run(["node", str(SCRIPT), field, part, *extra], env=env, capture_output=True, text=True, timeout=60)

    def typed(self, token):
        with self.lock:
            return [(e["id"], e["value"]) for e in self.events if e["t"] == token and e["ev"] == "value"]

    def log(self):
        return (self.tmp / "state/agent-login/agent-login.log").read_text()

    def op_calls(self):
        return [json.loads(line) for line in (self.tmp / "calls").read_text().splitlines()]

    # exact host

    def test_a_login_for_the_pages_exact_host_is_used_and_a_sibling_login_is_not(self):
        token = self.page("localhost")
        r = self.login("username", token, [item("main", "Main", "https://localhost/login"), item("canary", "Canary", "https://canary.localhost/")])
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "typed username for Main on localhost"), r.stderr)
        self.assertEqual(self.typed(token), [("pw", "u-main")])
        self.assertEqual([c["argv"][2] for c in self.op_calls() if c["argv"][:2] == ["item", "get"]], ["main"])

    def test_only_the_hostname_of_a_login_url_counts_and_the_url_is_never_printed(self):
        token = self.page("localhost")
        secret_url = "https://localhost/login?access_token=tok-9f8e7d#frag"
        r = self.login("username", token, [item("main", "Main", secret_url)])
        self.assertEqual(r.returncode, 0, r.stderr)   # path, query and fragment are ignored
        again = self.login("username", "no-such-page-xyz", [item("main", "Main", secret_url)])
        other = self.page("canary.localhost")
        none = self.login("username", other, [item("main", "Main", secret_url), item("twin", "Main", secret_url)])
        for out in (r.stdout + r.stderr, again.stderr, none.stderr, self.log()):
            self.assertNotIn("tok-9f8e7d", out)
        self.assertNotIn("tok-9f8e7d", self.login("username", token, [item("a", "A", secret_url), item("b", "B", secret_url)]).stderr)   # several matches

    def test_a_login_for_the_parent_domain_does_not_fill_a_subdomain_and_a_subdomain_login_does_not_fill_the_parent(self):
        for page_host, login_host in (("canary.localhost", "localhost"), ("localhost", "canary.localhost")):
            with self.subTest(page=page_host, login=login_host):
                token = self.page(page_host)
                r = self.login("username", token, [item("x", "Other host", "https://%s/" % login_host)])
                self.assertEqual(r.returncode, 1)
                self.assertIn("no login for %s" % page_host, r.stderr)
                self.assertEqual(self.typed(token), [])

    # what is typed, and where

    def test_each_field_is_typed_into_the_focused_input(self):
        for field, focus, expected in (("username", "user", "u-main"), ("password", "pw", SECRET), ("otp", "other", "123456")):
            with self.subTest(field=field):
                token = self.page(focus=focus)
                r = self.login(field, token, [item("main", "Main", "https://localhost/")])
                self.assertEqual((r.returncode, r.stdout.strip()), (0, "typed %s for Main on localhost" % field), r.stderr)
                self.assertEqual(self.typed(token)[-1], (focus, expected))

    def test_what_was_typed_is_on_record_when_the_script_returns_however_slow_the_record_is(self):   # issue 637: the report used to race the test's read
        type(self).record_delay = 0.5
        self.addCleanup(setattr, type(self), "record_delay", 0)
        token = self.page(focus="pw")
        r = self.login("password", token, [item("main", "Main", "https://localhost/")])
        self.assertEqual((r.returncode, self.typed(token)), (0, [("pw", SECRET)]), r.stderr)

    def test_a_password_is_refused_into_an_input_that_is_not_a_password_field(self):
        token = self.page(focus="other")
        r = self.login("password", token, [item("main", "Main", "https://localhost/")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("not a password field", r.stderr)
        self.assertEqual(self.typed(token), [])

    def test_nothing_is_typed_when_no_input_has_focus(self):
        token = self.page(focus=None)
        r = self.login("username", token, [item("main", "Main", "https://localhost/")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("no input has focus", r.stderr)
        self.assertEqual(self.typed(token), [])

    def test_a_page_that_moved_to_another_host_between_the_lookup_and_the_typing_gets_nothing(self):
        token = self.page("localhost", poll=True)
        r = self.login("password", token, [item("main", "Main", "https://localhost/")], None, trigger="http://127.0.0.1:%d/trigger?t=%s&host=canary.localhost" % (self.port, token))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("now on canary.localhost, not localhost", r.stderr)
        self.assertEqual(self.typed(token), [])

    # a value that is not the credential, and a field that did not take it

    def refused_value(self, field, value, focus, reason):
        token = self.page(focus=focus)
        r = self.login(field, token, [item("main", "Main", "https://localhost/")], {"main": {"username": "u", "password": "p", "otp": "1", field: value}})
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn(reason, r.stderr)
        self.assertEqual(self.typed(token), [])
        return r

    def test_op_notice_text_in_place_of_the_value_is_refused_before_anything_is_typed(self):
        self.refused_value("password", "[use 'op item get abc --reveal' to reveal]", "pw", "op returned its notice")

    def test_a_password_is_read_revealed_so_op_does_not_answer_with_its_notice(self):   # the fake op answers a non-revealed password with the notice
        token = self.page(focus="pw")
        r = self.login("password", token, [item("main", "Main", "https://localhost/")])
        self.assertEqual((r.returncode, self.typed(token)[-1]), (0, ("pw", SECRET)), r.stderr)
        self.assertIn("--reveal", [c["argv"] for c in self.op_calls() if "--fields" in c["argv"]][0])

    def test_an_empty_value_is_refused(self):
        self.refused_value("username", "", "user", "empty username")

    def test_a_value_with_a_trailing_newline_is_refused_and_op_s_own_line_end_is_not(self):
        self.refused_value("password", "abc\n", "pw", "ends with a newline")
        self.refused_value("otp", "123456\n", "other", "ends with a newline")   # the fake op prints a line end after the value; only that one is stripped
        token = self.page(focus="other")
        r = self.login("otp", token, [item("main", "Main", "https://localhost/")])
        self.assertEqual((r.returncode, self.typed(token)), (0, [("other", "123456")]), r.stderr)

    def test_a_field_that_did_not_take_the_whole_value_is_cleared_and_only_the_two_lengths_are_printed(self):
        token = self.page(focus="trunc")   # this input keeps three characters
        r = self.login("username", token, [item("main", "Main", "https://localhost/")])
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("holds 3 characters after typing 6; it was cleared", r.stderr)
        self.assertNotIn("u-main", r.stderr + r.stdout)
        self.assertEqual(self.typed(token)[-1], ("trunc", ""))   # cleared

    def test_a_clear_acts_on_the_field_that_was_typed_into_not_on_whatever_has_focus_after(self):
        token = self.page(focus="hop")   # keeps 3 characters, then moves focus to a field that holds text
        r = self.login("username", token, [item("main", "Main", "https://localhost/")])
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("it was cleared", r.stderr)
        self.assertEqual(self.typed(token)[-1], ("hop", ""))
        self.assertEqual([e for e in self.typed(token) if e[0] == "keep"], [])   # the other field was not touched

    def test_op_output_that_is_not_json_is_never_quoted_in_the_error_or_the_log(self):
        token = self.page(focus="pw")
        r = self.login("password", token, [item("main", "Main", "https://localhost/")], {"main": {"username": "u", "password": "RAW:" + SECRET, "otp": "1"}})
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("op did not return JSON for the password of Main", r.stderr)
        self.assertEqual(self.typed(token), [])
        self.assertNotIn(SECRET[:8], r.stdout + r.stderr + self.log())

    def test_a_login_list_that_is_not_json_is_never_quoted(self):
        token = self.page(focus="pw")
        r = self.login("username", token, [], raw_items="token=tok-77aa not json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("op did not return JSON for the login list", r.stderr)
        self.assertNotIn("tok-77aa", r.stderr + self.log())

    # which page, which login

    def test_several_logins_for_the_host_are_refused_by_title_until_item_picks_one(self):
        token = self.page(focus="user")
        items = [item("a", "Work account", "https://localhost/"), item("b", "Personal account", "https://localhost/a"), item("c", "Elsewhere", "https://example.com/")]
        r = self.login("username", token, items)
        self.assertEqual(r.returncode, 1)
        self.assertIn("Work account (a), Personal account (b)", r.stderr)
        self.assertNotIn("Elsewhere", r.stderr)
        self.assertEqual(self.typed(token), [])
        for pick, expected in (("b", "u-b"), ("Work account", "u-a")):   # by id and by title
            with self.subTest(pick=pick):
                fresh = self.page(focus="user")   # a new field each time: typing appends
                r = self.login("username", fresh, items, None, "--item", pick)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.typed(fresh), [("user", expected)])
        twins = [item("t1", "Twin", "https://localhost/"), item("t2", "Twin", "https://localhost/")]   # titles are not unique: the id picks
        fresh = self.page(focus="user")
        r = self.login("username", fresh, twins, None, "--item", "Twin")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Twin (t1), Twin (t2)", r.stderr)
        self.assertEqual(self.typed(fresh), [])
        r = self.login("username", fresh, twins, None, "--item", "t2")
        self.assertEqual((r.returncode, self.typed(fresh)), (0, [("user", "u-t2")]), r.stderr)
        fresh = self.page(focus="user")
        r = self.login("username", fresh, items, None, "--item", "Elsewhere")   # a login for another host cannot be picked
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.typed(fresh), [])

    def test_no_login_for_the_host_is_refused_and_says_so(self):
        token = self.page(focus="user")
        r = self.login("username", token, [item("x", "Elsewhere", "https://example.com/")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("no login for localhost in vault developer", r.stderr)
        self.assertEqual(self.typed(token), [])

    def test_the_url_part_must_match_exactly_one_page_and_the_matching_urls_are_listed(self):
        first, second = self.page(), self.page()
        shared = "localhost:%d" % self.port
        r = self.login("username", shared, [item("main", "Main", "https://localhost/")])
        self.assertEqual(r.returncode, 1)
        self.assertIn(first, r.stderr)
        self.assertIn(second, r.stderr)
        self.assertEqual((self.typed(first), self.typed(second)), ([], []))
        r = self.login("username", "no-such-page-xyz", [item("main", "Main", "https://localhost/")])
        self.assertEqual(r.returncode, 1)
        self.assertIn("0 pages contain", r.stderr)

    # the value

    def test_the_value_is_not_in_stdout_stderr_the_log_or_anything_op_was_given(self):
        token = self.page(focus="pw")
        ok = self.login("password", token, [item("main", "Main", "https://localhost/")])
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(self.typed(token)[-1], ("pw", SECRET))   # it was typed, so the checks below are about something that was in hand
        other = self.page(focus="other")
        refused = self.login("password", other, [item("main", "Main", "https://localhost/")])
        self.assertEqual(refused.returncode, 1)
        for name, text in (("stdout", ok.stdout + refused.stdout), ("stderr", ok.stderr + refused.stderr), ("log", self.log()),
                           ("op argv and env", json.dumps(self.op_calls()).replace(str(self.tmp / "values.json"), ""))):
            with self.subTest(where=name):
                self.assertNotIn(SECRET, text)
                self.assertNotIn(json.dumps(SECRET)[1:-1], text)
        self.assertEqual(sorted(p.name for p in (self.tmp / "state/agent-login").iterdir()), ["agent-login.log"])
        self.assertIn("typed field=password host=localhost item=Main", self.log())


if __name__ == "__main__":
    unittest.main()
