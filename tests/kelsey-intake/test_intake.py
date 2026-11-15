"""kelsey_intake.py against a fake shartifacts /mcp server and a fake board CLI (real script, real subprocess, real HTTP on localhost).
Run: python3 -m unittest discover -s tests/kelsey-intake
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/user_scripts/executable_kelsey_intake.py"

# A board CLI stand-in: `add` appends the note to a file and prints the real kit's answer; `show --json` prints what was added.
FAKE_BOARD = r'''
import json, os, sys
state = os.environ["FAKE_BOARD_STATE"]
items = json.load(open(state)) if os.path.exists(state) else []
verb = sys.argv[1]
if os.environ.get("FAKE_BOARD_FAIL") and verb == "add":
    sys.stderr.write("board is dirty"); sys.exit(1)
if verb == "show":
    print(json.dumps(items))
elif verb == "add":
    a = sys.argv
    item = {"ref": "BD %d" % (100 + len(items)), "title": a[a.index("--title") + 1], "note": "[agent] " + a[a.index("--note") + 1],
            "args": a[2:]}
    items.append(item); json.dump(items, open(state, "w"))
    print("add: %s (event %s)" % (item["ref"], a[a.index("--event") + 1]))
'''


class Fake(BaseHTTPRequestHandler):
    docs = {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        call = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["params"]["arguments"]
        if call["op"] == "query":
            # The server applies only the filters the script sends (== on a field), like the real one: no hard-coded status check here.
            keep = lambda v: all(v.get(f) == value for f, op, value in call.get("where") or [] if op == "==")
            out = {"docs": [{"id": k, "data": v} for k, v in self.docs.items() if keep(v)]}
        else:
            self.docs[call["path"].split("/")[1]].update(call["data"])
            out = {"ok": True}
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"structuredContent": out}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class IntakeTest(unittest.TestCase):
    def setUp(self):
        Fake.docs = {}
        self.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        (tmp / "board.py").write_text(FAKE_BOARD)
        self.state = tmp / "state.json"
        self.env = dict(os.environ, SHARTIFACTS_URL=f"http://127.0.0.1:{self.server.server_port}", KELSEY_PAGE_ID="page", KELSEY_NODE=sys.executable,
                        BOARD_CLI=str(tmp / "board.py"), BOARD_DIR=str(tmp), FAKE_BOARD_STATE=str(self.state))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def run_script(self, **extra):
        return subprocess.run([sys.executable, str(SCRIPT)], env=dict(self.env, **extra), capture_output=True, text=True)

    def board(self):
        return json.loads(self.state.read_text()) if self.state.exists() else []

    def test_files_a_submission_once_and_marks_it_picked_up(self):
        Fake.docs["s1"] = {"text": "a link | and\na note", "ask": "worth it?", "status": "new", "created": 1}
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        (item,) = self.board()
        self.assertEqual(item["args"][item["args"].index("--tag") + 1], "agent")
        self.assertIn("submission s1:", item["note"])
        self.assertIn("a link / and a note", item["note"])     # no ' | ' and no line break survive into a board note
        self.assertIn("she wants to know: worth it?", item["note"])
        self.assertIn("to answer, set status answered and answer on submissions/s1 of page page", item["note"])   # how the answerer reaches her page
        self.assertIn("kelsey-intake/README.md", item["note"])
        self.assertEqual(Fake.docs["s1"]["status"], "picked_up")
        self.assertEqual(Fake.docs["s1"]["board_ref"], "BD 100")
        self.assertIn("filed on the board as BD 100", r.stdout)
        self.assertEqual(self.run_script().returncode, 0)       # a second tick has nothing new
        self.assertEqual(len(self.board()), 1)

    def test_only_new_submissions_are_filed_and_the_rest_are_left_alone(self):
        Fake.docs["old1"] = {"text": "x", "ask": "", "status": "picked_up", "created": 1, "board_ref": "BD 5"}
        Fake.docs["old2"] = {"text": "y", "ask": "", "status": "answered", "created": 2, "answer": "done"}
        Fake.docs["s1"] = {"text": "z", "ask": "", "status": "new", "created": 3}
        self.assertEqual(self.run_script().returncode, 0)
        (item,) = self.board()
        self.assertIn("submission s1:", item["note"])
        self.assertEqual(Fake.docs["old2"]["status"], "answered")
        self.assertEqual(Fake.docs["old1"]["status"], "picked_up")
        self.assertEqual(Fake.docs["old1"]["board_ref"], "BD 5")

    def test_a_failed_board_add_leaves_the_submission_new_and_exits_1(self):
        Fake.docs["s1"] = {"text": "x", "ask": "", "status": "new", "created": 1}
        r = self.run_script(FAKE_BOARD_FAIL="1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(Fake.docs["s1"]["status"], "new")
        self.assertIn("ERROR", r.stdout)

    def test_a_run_that_added_the_line_but_not_the_mark_finishes_without_a_second_line(self):
        Fake.docs["s1"] = {"text": "x", "ask": "", "status": "new", "created": 1}
        self.state.write_text(json.dumps([{"ref": "BD 7", "title": "t", "note": "[agent] from Kelsey via her shartifacts page, submission s1: x"}]))
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(len(self.board()), 1)
        self.assertEqual(Fake.docs["s1"]["board_ref"], "BD 7")
        self.assertEqual(Fake.docs["s1"]["status"], "picked_up")


if __name__ == "__main__":
    unittest.main()
