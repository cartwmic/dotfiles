#!/usr/bin/env python3
"""Black-box tests for dot_local/bin/executable_shx-waiting.

A small stdlib HTTP server plays shartifacts: the page list and each page's comments, as the real server answers them
(one flat list per page; a thread's first comment has no `parent`, a reply names it; authors are `you` for the owner and
`agent` for an agent). The command runs against it as a person would run it. Needs node.
Run: python3 -I tests/shx/test_waiting.py
"""
import json
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CMD = os.path.join(ROOT, "dot_local", "bin", "executable_shx-waiting")
NODE = shutil.which("node")

A, B, C, D, E = ("%024x" % n for n in (1, 2, 3, 4, 5))


def his(cid, at, body="what about this?", **kw):
    return {"id": cid, "author": "you", "body": body, "version": 1, "created_at": at, **kw}


def agents(cid, at, parent, body="done"):
    return {"id": cid, "author": "agent", "body": body, "version": 1, "created_at": at, "parent": parent}


def his_reply(cid, at, parent, body="and another thing"):
    return {"id": cid, "author": "you", "body": body, "version": 1, "created_at": at, "parent": parent}


class Fixture(ThreadingHTTPServer):
    def __init__(self, pages):
        super().__init__(("127.0.0.1", 0), Handler)
        self.pages, self.requests = pages, []  # pages: id -> (title, comments | int status | raw JSON value)
        self.archived = set()  # ids of pages the default list leaves out; ?archived=include lists them
        threading.Thread(target=self.serve_forever, args=(0.02,), daemon=True).start()

    @property
    def base(self):
        return "http://127.0.0.1:%d" % self.server_address[1]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.server.requests.append(("GET", self.path))
        url = urlparse(self.path)
        parts = url.path.strip("/").split("/")
        if parts == ["api", "artifacts"]:
            mode = parse_qs(url.query).get("archived", ["exclude"])[0]
            return self.reply(200, [{"id": i, "title": t, "kind": "html", "version": 1} for i, (t, _) in self.server.pages.items()
                                    if mode == "include" or i not in self.server.archived])
        if len(parts) >= 3 and parts[:2] == ["api", "artifacts"] and parts[2] in self.server.pages:
            title, comments = self.server.pages[parts[2]]
            if len(parts) == 3:
                return self.reply(200, {"id": parts[2], "title": title, "revisions": [{"version": 1}]})
            if parts[3] == "comments":
                return self.reply(comments, {"error": "boom"}) if isinstance(comments, int) else self.reply(200, comments)
        self.reply(404, {"error": "not found"})

    def do_POST(self):
        self.server.requests.append(("POST", self.path))
        self.reply(200, {})

    do_PUT = do_DELETE = do_POST


def run(server, *args, env=None, cmd=CMD):
    state = tempfile.mkdtemp()
    try:
        r = subprocess.run([cmd, *args], capture_output=True, text=True, timeout=60,
                           env=dict(os.environ, XDG_STATE_HOME=state, SHARTIFACTS_URL=server.base if server else "", **(env or {})))
        log = os.path.join(state, "shx", "waiting.log")
        records = []
        if os.path.exists(log):
            with open(log) as f:
                records = [json.loads(line) for line in f]
        return r, records
    finally:
        shutil.rmtree(state)


@unittest.skipUnless(NODE, "needs node")
class WaitingTest(unittest.TestCase):
    def serve(self, pages):
        server = Fixture(pages)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server

    def test_only_his_comment_is_waiting(self):
        s = self.serve({A: ("Plan page", [his("c1", "2026-11-20T10:00:00.5Z", "is this still needed?", quote="The other is the workflow",
                                              anchor="p", element="<p>")])})
        r, _ = run(s)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("page %s (Plan page)" % A, r.stdout)
        self.assertIn("  link   %s/view/%s" % (s.base, A), r.stdout)
        self.assertIn("thread c1  waiting since 2026-11-20T10:00:00.5Z", r.stdout)
        self.assertIn("  on     The other is the workflow", r.stdout)
        self.assertIn("  he wrote: is this still needed?", r.stdout)
        self.assertTrue(r.stdout.rstrip().endswith("1 thread waiting on 1 page (1 page read, archived pages included)"), r.stdout)

    def test_his_comment_then_an_agent_reply_is_not_waiting(self):
        s = self.serve({A: ("P", [his("c1", "2026-11-20T10:00:00Z"), agents("r1", "2026-11-20T11:00:00Z", "c1")])})
        r, _ = run(s)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "none waiting (1 page read, archived pages included)")

    def test_his_comment_agent_reply_then_his_again_is_waiting(self):
        s = self.serve({A: ("P", [his("c1", "2026-11-20T10:00:00Z", "first"), agents("r1", "2026-11-20T11:00:00Z", "c1"),
                                  his_reply("r2", "2026-11-21T09:00:00Z", "c1", "second")])})
        r, _ = run(s)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("waiting since 2026-11-21T09:00:00Z", r.stdout)  # since his first message after the agent's reply
        self.assertIn("he wrote: second", r.stdout)
        self.assertNotIn("first", r.stdout)
        self.assertNotIn("done", r.stdout)  # an agent's reply is never shown as his comment

    def test_an_agent_reply_alone_in_the_list_is_not_his_comment(self):
        # The stop-gap listed every entry of the flat list as a thread, so an agent's reply looked like his comment.
        s = self.serve({A: ("P", [his("c1", "2026-11-20T10:00:00Z"), agents("r1", "2026-11-20T11:00:00Z", "c1", "I changed it")])})
        r, _ = run(s)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("I changed it", r.stdout)

    def test_a_resolved_thread_is_not_waiting(self):
        s = self.serve({A: ("P", [his("c1", "2026-11-20T10:00:00Z", resolved=True)])})
        r, _ = run(s)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "none waiting (1 page read, archived pages included)"))

    def test_a_page_with_no_comments(self):
        s = self.serve({A: ("P", [])})
        r, _ = run(s)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "none waiting (1 page read, archived pages included)"))

    def test_time_order_not_list_order_and_fractions_of_any_length(self):
        # created_at fractions differ in length, so a text compare puts ".4423Z" after ".44231Z": his later message must still win.
        late = [his("c1", "2026-11-20T10:00:00.4423Z"), agents("r1", "2026-11-20T10:00:00.44231Z", "c1")]
        s = self.serve({A: ("Agent last", late), B: ("He last", list(reversed([his("c2", "2026-11-20T10:00:00.4Z"),
                        agents("r2", "2026-11-20T10:00:00.40001Z", "c2"), his_reply("r3", "2026-11-20T10:00:00.401Z", "c2")])))})
        r, _ = run(s)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("thread c2", r.stdout)
        self.assertNotIn("thread c1", r.stdout)

    def test_all_pages_oldest_first_and_count_line(self):
        s = self.serve({A: ("New", [his("n1", "2026-11-25T10:00:00Z")]), B: ("Quiet", []),
                        C: ("Old", [his("o1", "2026-11-01T10:00:00Z"), his("o2", "2026-11-02T10:00:00Z")]),
                        D: ("Answered", [his("a1", "2026-11-03T10:00:00Z"), agents("a2", "2026-11-03T11:00:00Z", "a1")])})
        r, records = run(s)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual([l.split()[1] for l in r.stdout.splitlines() if l.startswith("  thread")], ["o1", "o2", "n1"])
        self.assertTrue(r.stdout.rstrip().endswith("3 threads waiting on 2 pages (4 pages read, archived pages included)"), r.stdout)
        self.assertEqual([m for m, _ in s.requests if m != "GET"], [])  # it changes nothing on the server
        self.assertEqual(len(records), 1)
        self.assertEqual({k: records[0][k] for k in ("command", "scope", "pages", "waiting", "error")},
                         {"command": "waiting", "scope": "all", "pages": 4, "waiting": 3, "error": None})

    def test_an_archived_page_is_read_too(self):
        # The default page list leaves archived pages out; a comment on one is still a comment.
        s = self.serve({A: ("Live", []), B: ("Archived", [his("c1", "2026-11-20T10:00:00Z")])})
        s.archived.add(B)
        r, _ = run(s)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("page %s (Archived)" % B, r.stdout)
        self.assertTrue(r.stdout.rstrip().endswith("(2 pages read, archived pages included)"), r.stdout)

    def test_his_reply_on_a_thread_an_agent_started_is_waiting(self):
        s = self.serve({A: ("P", [{"id": "c1", "author": "agent", "body": "a question for you", "version": 1, "created_at": "2026-11-20T10:00:00Z"},
                                  his_reply("r1", "2026-11-20T11:00:00Z", "c1", "my answer")])})
        r, _ = run(s)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("he wrote: my answer", r.stdout)

    def test_the_log_says_which_pages_were_read_and_which_threads_were_shown(self):
        s = self.serve({A: ("One", [his("c1", "2026-11-20T10:00:00Z")]), B: ("Two", [])})
        r, records = run(s, B, A)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual({k: records[0][k] for k in ("scope", "page_ids", "threads")},
                         {"scope": "ids", "page_ids": [B, A], "threads": [{"page": A, "thread": "c1"}]})
        r, records = run(s)
        self.assertEqual({k: records[0][k] for k in ("scope", "page_ids", "pages", "threads")},
                         {"scope": "all", "page_ids": None, "pages": 2, "threads": [{"page": A, "thread": "c1"}]})

    def test_many_pages(self):
        pages = {"%024x" % (100 + n): ("P%d" % n, [his("c%d" % n, "2026-11-20T10:00:00Z")] if n == 37 else []) for n in range(80)}
        r, _ = run(self.serve(pages))
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(r.stdout.rstrip().endswith("1 thread waiting on 1 page (80 pages read, archived pages included)"), r.stdout)

    def test_page_ids_and_a_file_of_ids(self):
        s = self.serve({A: ("One", [his("c1", "2026-11-20T10:00:00Z")]), B: ("Two", []), C: ("Three", [his("c3", "2026-11-20T10:00:00Z")])})
        with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as f:
            f.write("01-one\t%s\tDesign sweep one\n02-two\t%s\tTwo\nnot an id 0123456789abcdef\n" % (A, B))
        self.addCleanup(os.unlink, f.name)
        r, _ = run(s, "--file", f.name)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertTrue(r.stdout.rstrip().endswith("1 thread waiting on 1 page (2 pages read)"), r.stdout)
        self.assertNotIn(C, r.stdout)
        r, records = run(s, C, B, C)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("page %s (Three)" % C, r.stdout)
        self.assertTrue(r.stdout.rstrip().endswith("(2 pages read)"), r.stdout)
        self.assertEqual(records[0]["scope"], "ids")

    def test_base_url_argument(self):
        s = self.serve({A: ("P", [his("c1", "2026-11-20T10:00:00Z")])})
        r, _ = run(None, s.base + "/", A)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("link   %s/view/%s" % (s.base, A), r.stdout)

    # Not 1: "could not read" must never look like "something waits", nor like "nothing waits".
    def test_a_server_error_is_not_exit_1_or_0(self):
        s = self.serve({A: ("Fine", []), B: ("Broken", 500)})
        r, records = run(s)
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertIn("page %s" % B, r.stderr)
        self.assertIn("answered 500", r.stderr)
        self.assertEqual(records[0]["error"]["code"], "request_failed")

    def test_an_unknown_page_is_a_read_failure(self):
        r, _ = run(self.serve({A: ("P", [])}), B)
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertIn("answered 404", r.stderr)

    def test_an_unreachable_server(self):
        s = Fixture({})
        base = s.base
        s.shutdown()
        s.server_close()
        r, _ = run(None, base, A)
        self.assertEqual(r.returncode, 5, r.stderr)
        self.assertNotIn(r.returncode, (0, 1))

    def test_answers_that_are_not_comments_are_read_failures(self):
        for bad in ({"error": "x"}, "text", [{"body": "no id or author"}], [{"id": "c", "author": "you", "created_at": "yesterday"}]):
            with self.subTest(bad=bad):
                r, _ = run(self.serve({A: ("P", bad)}))
                self.assertEqual(r.returncode, 5, r.stderr)
                self.assertEqual(r.stdout, "")

    def test_bad_usage(self):
        s = self.serve({A: ("P", [])})
        for args in (("--nope",), ("--file",), ("--file", "/nonexistent/ids.txt"), ("--file", os.devnull)):
            with self.subTest(args=args):
                r, _ = run(s, *args)
                self.assertEqual(r.returncode, 2, r.stderr)

    def test_a_broken_install_is_not_exit_1(self):
        # Node ends an uncaught error, a missing module or a syntax error in a loaded file with 1, the code for "waiting".
        # Each file of the install, in turn, missing or unparsable: the answer is 3.
        files = ("waiting.mjs", "core/waiting.mjs", "core/domain.mjs", "adapters/shartifacts_http.mjs", "adapters/fs_store.mjs")
        for name in files:
            for how in ("missing", "syntax error"):
                with self.subTest(file=name, how=how), tempfile.TemporaryDirectory() as tmp:
                    shutil.copytree(os.path.join(ROOT, "dot_local", "share", "shx"), os.path.join(tmp, "share", "shx"))
                    os.makedirs(os.path.join(tmp, "bin"))
                    shutil.copy(CMD, os.path.join(tmp, "bin", "shx-waiting"))
                    target = os.path.join(tmp, "share", "shx", *name.split("/"))
                    if how == "missing":
                        os.remove(target)
                    else:
                        with open(target, "a") as f:
                            f.write("\nexport const x = ;\n")
                    r, _ = run(None, "http://127.0.0.1:9", A, cmd=os.path.join(tmp, "bin", "shx-waiting"))
                    self.assertEqual(r.returncode, 3, r.stderr)

    def test_no_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(shutil.which("dirname"), os.path.join(tmp, "dirname"))  # the wrapper needs dirname, not node
            r = subprocess.run(["/bin/sh", CMD], capture_output=True, text=True, env={"PATH": tmp})
        self.assertEqual(r.returncode, 4, r.stderr)


if __name__ == "__main__":
    unittest.main()
