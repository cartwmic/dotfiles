"""mistakes-report on tiny fixtures: a review log with two rounds and an escape, session files with a failed and a duplicated tool result.

The model call and the page host are replaced: a function that labels by a marker word, and a local fake of the shartifacts API
(create, read, update with base_version and a 409). Nothing here touches the real logs, the real state or the real page.
Run: python3 -m unittest discover -s tests/mistakes-report
"""
import html as htmllib
import http.server
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "dot_local/share/mistakes-report"))
import mistakes_report as mr  # noqa: E402

NOW = datetime(2026, 11, 15, 8, 0, 0, tzinfo=timezone.utc)
ISO = lambda d: d.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
DAY = timedelta(days=1)
CONFIG = json.loads((REPO / "dot_local/share/mistakes-report/classes.json").read_text())


def jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def finding(i, round_, at, text, severity="blocking"):
    return {"event": "finding", "at": ISO(at), "id": i, "round": round_, "severity": severity, "effective": severity, "text": text,
            "obligation": "approved intent"}


def review_log(root):
    """item x#1: round 1 has a journey finding (this week), a note, and a logic finding last week; round 2 one more this week; plus an escape."""
    jsonl(root / "x#1/findings.jsonl", [
        finding("r1.f1", 1, NOW - 2 * DAY, "journey 171 fails on main, the PR run left it out"),
        finding("r1.n1", 1, NOW - 2 * DAY, "journey note, not blocking", "note"),
        finding("r1.f2", 1, NOW - 9 * DAY, "wrong count in the logic"),
        finding("r2.f1", 2, NOW - 1 * DAY, "wrong order in the logic"),
        {"event": "escape", "at": ISO(NOW - 3 * DAY), "item": "x#1", "head": "abc", "round": 2, "found_by": "main run 1",
         "text": "journey 301 failed after merge"},
    ])


def fake_model(prompt, model):
    """Labels every numbered entry: a journey class when the entry says journey, else logic-bug."""
    entries = [l for l in prompt.splitlines() if l[:1].isdigit() and ". " in l[:4]]
    FAKE.calls.append(len(entries))
    out = {str(i): ("journey-missed-after-merge" if "journey" in e else "logic-bug") for i, e in enumerate(entries, 1)}
    return {"text": json.dumps(out), "input_tokens": 100 * len(entries), "output_tokens": 10, "cost_usd": 0.001}


class Fake:
    calls = []


FAKE = Fake()


class Shartifacts(http.server.BaseHTTPRequestHandler):
    store = {}
    conflicts = 0           # answer the next PUTs with 409 this many times
    log = []

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def do_POST(self):
        b = self._body()
        Shartifacts.store["id1"] = [b["content"]]
        Shartifacts.log.append(("POST", b["title"]))
        self._send(200, {"id": "id1"})

    def do_GET(self):
        revs = Shartifacts.store[self.path.rsplit("/", 1)[1]]
        self._send(200, {"revisions": [{"version": i + 1} for i in range(len(revs))]})

    def do_PUT(self):
        b = self._body()
        aid = self.path.rsplit("/", 1)[1]
        Shartifacts.log.append(("PUT", b["base_version"]))
        if Shartifacts.conflicts:
            Shartifacts.conflicts -= 1
            Shartifacts.store[aid].append("someone else")      # a version landed between our GET and PUT
            return self._send(409, {"error": "conflict"})
        if b["base_version"] != len(Shartifacts.store[aid]):
            return self._send(409, {"error": "stale"})
        Shartifacts.store[aid].append(b["content"])
        self._send(200, {"id": aid})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.review, self.sessions, self.state = t / "review", t / "sessions", t / "state"
        review_log(self.review)
        jsonl(self.sessions / "p/s1.jsonl", [])
        Shartifacts.store, Shartifacts.conflicts, Shartifacts.log = {}, 0, []
        FAKE.calls = []
        self.server = http.server.HTTPServer(("127.0.0.1", 0), Shartifacts)
        threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = "http://127.0.0.1:%d" % self.server.server_port

    def args(self, *extra):
        return mr.parser().parse_args(["--review-dir", str(self.review), "--sessions-dir", str(self.sessions), "--state-dir", str(self.state),
                                       "--shartifacts", self.url, *extra])

    def run_at(self, now, model=fake_model, *extra):
        return mr.run(self.args(*extra), model_fn=model, now=now)


class ClassifyTest(Base):
    def test_counts_by_class_and_week_with_examples(self):
        r = self.run_at(NOW)["model"]
        self.assertEqual(r["findings"]["journey-missed-after-merge"], {"this": 1, "last": 0, "all": 1})
        self.assertEqual(r["findings"]["logic-bug"], {"this": 1, "last": 1, "all": 2})      # r2.f1 this week, r1.f2 nine days ago
        self.assertEqual(r["escapes"]["journey-missed-after-merge"], {"this": 1, "last": 0, "all": 1})
        self.assertEqual(r["examples"]["finding"]["logic-bug"][0]["quote"], "wrong order in the logic")    # newest first
        self.assertEqual(r["examples"]["finding"]["logic-bug"][0]["round"], 2)
        self.assertEqual(r["examples"]["escape"]["journey-missed-after-merge"][0]["item"], "x#1")

    def test_notes_are_not_counted(self):
        self.assertEqual(sum(v["all"] for v in self.run_at(NOW)["model"]["findings"].values()), 3)

    def test_the_page_names_the_classes_and_prints_tokens_and_cost(self):
        html = htmllib.unescape(Path(self.run_at(NOW)["page_html"]).read_text())
        self.assertIn("A journey test failed after merge and the change's own test run did not catch it", html)
        self.assertIn("1 of 1", html)       # the escapes' all-records column
        self.assertIn("4 new items sorted in 1 call, 400 input tokens and 10 output tokens, list-price cost $0.0010", html)

    def test_a_rerun_costs_nothing(self):
        self.run_at(NOW)
        self.assertEqual(FAKE.calls, [4])
        r = self.run_at(NOW + timedelta(hours=1))
        self.assertEqual(FAKE.calls, [4])      # no new model call
        self.assertEqual(r["record"]["calls"], 0)
        self.assertEqual(r["record"]["cost_usd"], 0)
        self.assertIn("0 new items sorted in 0 calls", Path(r["page_html"]).read_text())

    def test_a_new_item_is_classified_alone(self):
        self.run_at(NOW)
        with open(self.review / "x#1/findings.jsonl", "a") as fh:
            fh.write(json.dumps(finding("r3.f1", 3, NOW, "another journey gap")) + "\n")
        self.run_at(NOW + timedelta(hours=1))
        self.assertEqual(FAKE.calls, [4, 1])

    def test_changing_the_class_list_reclassifies_everything(self):
        self.run_at(NOW)
        classes = Path(self.tmp.name) / "classes.json"
        classes.write_text(json.dumps(dict(CONFIG, classes=CONFIG["classes"][:-2] + [{"id": "other", "name": "x", "description": "y"}])))
        self.run_at(NOW + timedelta(hours=1), fake_model, "--classes", str(classes))
        self.assertEqual(FAKE.calls, [4, 4])

    def test_a_reply_with_a_wrong_class_or_number_is_asked_again_then_fails_closed(self):
        def bad(prompt, model):
            return {"text": '{"1": "not-a-class", "9": "logic-bug"}', "input_tokens": 1, "output_tokens": 1, "cost_usd": 0}
        with self.assertRaises(RuntimeError):
            self.run_at(NOW, bad)
        self.assertEqual(Shartifacts.log, [])      # nothing published
        self.assertEqual(json.loads((self.state / "classifications.json").read_text())["labels"], {})

    def test_a_failed_call_loses_only_its_own_batch(self):
        with open(self.review / "x#1/findings.jsonl", "a") as fh:
            for i in range(3):
                fh.write(json.dumps(finding("r9.f%d" % i, 9, NOW, "second batch item %d" % i)) + "\n")

        def flaky(prompt, model):
            if "second batch" in prompt:
                raise RuntimeError("claude did not answer within 600 seconds")
            return fake_model(prompt, model)
        old, mr.BATCH = mr.BATCH, 4
        self.addCleanup(setattr, mr, "BATCH", old)
        with self.assertRaises(RuntimeError) as cm:
            self.run_at(NOW, flaky)
        self.assertIn("did not answer within 600 seconds", str(cm.exception))
        self.assertEqual(len(json.loads((self.state / "classifications.json").read_text())["labels"]), 4)   # the first batch is kept
        self.assertEqual(Shartifacts.log, [])
        self.run_at(NOW + timedelta(hours=1))                                                                # the rerun pays only for the rest
        self.assertEqual(FAKE.calls, [4, 3])

    def test_a_timeout_is_one_plain_line(self):
        import subprocess
        from unittest import mock
        with mock.patch.object(mr.subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 600)):
            with self.assertRaises(RuntimeError) as cm:
                mr.call_claude("p", "m")
        self.assertEqual(str(cm.exception), "claude did not answer within 600 seconds")

    def test_main_prints_a_failure_as_one_line_and_exits_1(self):
        import contextlib
        import io
        from unittest import mock
        err = io.StringIO()
        with mock.patch.object(mr, "call_claude", side_effect=RuntimeError("boom")), contextlib.redirect_stderr(err):
            code = mr.main(["--review-dir", str(self.review), "--sessions-dir", str(self.sessions), "--state-dir", str(self.state), "--shartifacts", self.url])
        self.assertEqual(code, 1)
        self.assertEqual(err.getvalue().count("\n"), 1)
        self.assertIn("boom", err.getvalue())

    def test_parse_reply_keeps_only_valid_entries(self):
        ids = {"a", "b"}
        self.assertEqual(mr.parse_reply('noise {"1": "a", "2": "zzz", "5": "b", "x": "a"} noise', 2, ids), {1: "a"})
        self.assertEqual(mr.parse_reply("no json", 2, ids), {})


class WeeklyTest(Base):
    def test_last_week_comes_from_the_saved_snapshot_not_the_logs(self):
        self.run_at(NOW)
        (self.review / "x#1/findings.jsonl").unlink()                        # the logs are gone; only the snapshot knows
        r = self.run_at(NOW + 7 * DAY)["model"]
        self.assertIn("snapshot saved on 2026-11-15", r["last_source"])
        self.assertEqual(r["findings"]["logic-bug"]["last"], 1)              # this week's count from the run before
        self.assertEqual(r["findings"]["journey-missed-after-merge"]["last"], 1)

    def test_a_same_day_rerun_does_not_take_its_own_snapshot_as_last_week(self):
        self.run_at(NOW)
        r = self.run_at(NOW + timedelta(hours=2))["model"]
        self.assertIn("No saved snapshot", r["last_source"])
        self.assertEqual(r["findings"]["logic-bug"]["last"], 1)             # counted from the logs, nine days ago

    def test_a_snapshot_made_with_another_class_list_is_not_used(self):
        self.run_at(NOW)
        classes = Path(self.tmp.name) / "classes.json"
        classes.write_text(json.dumps(dict(CONFIG, classes=CONFIG["classes"][:-2] + [{"id": "other", "name": "x", "description": "y"}])))
        r = self.run_at(NOW + 7 * DAY, fake_model, "--classes", str(classes))["model"]
        self.assertIn("No saved snapshot", r["last_source"])

    def test_the_page_is_created_once_then_updated_in_place(self):
        a = self.run_at(NOW)
        b = self.run_at(NOW + 7 * DAY)
        self.assertEqual((a["page_id"], a["created"], a["version_after"]), ("id1", True, 1))
        self.assertEqual((b["page_id"], b["created"], b["version_before"], b["version_after"]), ("id1", False, 1, 2))
        self.assertEqual([m for m, _ in Shartifacts.log], ["POST", "PUT"])
        self.assertEqual(b["url"], self.url + "/view/id1")

    def test_a_preview_does_not_replace_the_snapshot(self):
        self.run_at(NOW)
        snap = self.state / "snapshots/2026-11-15.json"
        before = snap.read_text()
        with open(self.review / "x#1/findings.jsonl", "a") as fh:
            fh.write(json.dumps(finding("r4.f1", 4, NOW, "journey again")) + "\n")
        self.run_at(NOW + timedelta(hours=1), fake_model, "--no-publish")
        self.assertEqual(snap.read_text(), before)
        self.assertEqual(len(Shartifacts.log), 1)

    def test_a_run_record_is_appended(self):
        self.run_at(NOW)
        self.run_at(NOW + timedelta(hours=1))
        rows = [json.loads(l) for l in (self.state / "runs.jsonl").read_text().splitlines()]
        self.assertEqual([r["calls"] for r in rows], [1, 0])
        self.assertEqual(rows[0]["page_id"], "id1")
        self.assertEqual(rows[0]["input_tokens"], 400)


class PublishTest(Base):
    def test_one_409_is_retried_and_three_fail(self):
        mr.publish(self.url, self.state, "<p>1</p>")
        Shartifacts.conflicts = 1
        aid, before, after, created = mr.publish(self.url, self.state, "<p>2</p>")
        self.assertEqual((before, after, created), (2, 3, False))            # the first PUT met a version that landed after our GET; the retry read v2
        Shartifacts.conflicts = 3
        with self.assertRaises(RuntimeError):
            mr.publish(self.url, self.state, "<p>3</p>")


def session_rows():
    ts = ISO(NOW - DAY)
    use = lambda i, name: {"type": "assistant", "timestamp": ts, "message": {"id": "m", "content": [{"type": "tool_use", "id": i, "name": name}]}}  # noqa: E731
    res = lambda i, text, bad: {"type": "user", "timestamp": ts, "message": {"content": [  # noqa: E731
        {"type": "tool_result", "tool_use_id": i, "is_error": bad, "content": text}]}}
    return [use("t1", "bash"), res("t1", "<tool_use_error>Error: No such tool available: bash.\nmore</tool_use_error>", True),
            res("t1", "<tool_use_error>Error: No such tool available: bash.\nmore</tool_use_error>", True),     # the same record repeated
            use("t2", "Read"), res("t2", "fine", False),
            use("t3", "Bash"), res("t3", "Exit code 1\nboom", True),
            use("t4", "Bash"), res("t4", [{"type": "text", "text": "PreToolUse:Bash hook error: [" + "x" * 90 + "]: pkill is refused"}], True),
            use("t5", "Bash"), res("t5", [{"type": "text", "text": "PreToolUse:Bash hook error: [" + "x" * 90 + "]: killall is refused"}], True),
            {"type": "api-request-blob", "message": {"content": [{"type": "tool_result", "tool_use_id": "t9", "is_error": True, "content": "decoy"}]}}]


class ToolErrorTest(Base):
    def setUp(self):
        super().setUp()
        jsonl(self.sessions / "p/s1.jsonl", session_rows())
        jsonl(self.sessions / "q/copy-of-s1.jsonl", session_rows())          # a copied session repeats every id

    def test_failures_count_once_per_tool_use_id(self):
        failures, stats = mr.scan_tool_errors(str(self.sessions))
        self.assertEqual(stats["results"], 5)
        self.assertEqual(sorted((t, m.split(":")[0]) for _, t, m in failures),
                         [("Bash", "Exit code 1"), ("Bash", "PreToolUse"), ("Bash", "PreToolUse"), ("bash", "Error")])   # t1 once, not twice; the decoy and the success not at all

    def test_the_table_groups_by_tool_and_error_start_and_sets_exit_codes_aside(self):
        r = self.run_at(NOW)["model"]
        rows = {(x["tool"]): x for x in r["tools"]}
        self.assertEqual(rows["bash"]["this"], 1)
        self.assertEqual(rows["Bash"]["this"], 2)                           # two hook refusals with different endings are one row
        self.assertEqual(len(r["tools"]), 2)
        self.assertEqual(r["exits"], {"this": 1, "last": 0})

    def test_a_fixed_mistake_stays_in_the_top_ten_with_zero_this_week(self):
        key = ("bash", "Error")
        rows = mr.tool_rows({}, {key: 50, ("a", "b"): 3}, [], top=10)
        self.assertEqual((rows[0]["tool"], rows[0]["this"], rows[0]["last"]), ("bash", 0, 50))

    def test_every_argument_failure_of_one_tool_is_one_row_that_names_the_argument(self):
        ts = ISO(NOW - DAY)
        rows = []
        for n, text in enumerate(["Invalid parameters for tool 'w': Missing key\n  at [\"taskIds\"]\n\nschema...", "Invalid parameters for tool 'w': Missing key\n  at [\"taskIds\"]",
                                  "Invalid parameters for tool 'w': Unknown argument \"taskId\". Accepted arguments: taskIds."]):
            rows += [{"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "id": "w%d" % n, "name": "mcp__w"}]}},
                     {"type": "user", "timestamp": ts, "message": {"content": [{"type": "tool_result", "tool_use_id": "w%d" % n, "is_error": True, "content": text}]}}]
        jsonl(self.sessions / "p/w.jsonl", rows)
        r = self.run_at(NOW)["model"]
        w = [x for x in r["tools"] if x["tool"] == "mcp__w"]
        self.assertEqual(len(w), 1)
        self.assertEqual(w[0]["this"], 3)
        self.assertEqual(w[0]["error"], "Invalid parameters for tool 'w': Missing key at [\"taskIds\"]")
        self.assertEqual(w[0]["variants"], 2)

    def test_a_bash_exit_line_followed_by_output_starting_with_at_stays_an_exit_line(self):
        self.assertEqual(mr.first_line("Exit code 1\nat foo.js:3"), "Exit code 1")

    def test_the_page_shows_the_tool_table(self):
        html = Path(self.run_at(NOW)["page_html"]).read_text()
        self.assertIn("<code>bash</code>", html)
        self.assertIn("No such tool available: bash.", html)


if __name__ == "__main__":
    unittest.main()
