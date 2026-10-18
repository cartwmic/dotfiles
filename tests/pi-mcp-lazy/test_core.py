import json
import subprocess
import sys
import unittest

from harness import Env, Session, STANDIN, procs, read_saved, text_of, wait_until, write_copy


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.sessions = []
        self.addCleanup(self.e.cleanup)

    def sess(self, *a, **k):
        s = Session(self.e, "fake", k.pop("idle", 600), *a, **k)
        self.sessions.append(s)
        self.addCleanup(s.close)
        return s

    def test_state_copy_answers_without_starting_server(self):
        write_copy(self.e.state, "fake", self.e.key())
        s = self.sess()
        r = s.initialize()
        self.assertEqual(r["result"]["serverInfo"]["name"], "fake")
        tl = s.request("tools/list")
        self.assertEqual([t["name"] for t in tl["result"]["tools"]], ["echo", "slow", "roots"])
        self.assertEqual(s.request("ping")["result"], {})
        self.assertEqual(procs(self.e.marker), [])
        self.assertEqual(self.e.starts(), 0)

    def test_seed_used_when_no_state_copy(self):
        write_copy(self.e.seed, "fake", self.e.key())
        s = self.sess()
        self.assertIn("result", s.initialize())
        self.assertEqual(len(s.request("tools/list")["result"]["tools"]), 3)
        self.assertEqual(procs(self.e.marker), [])

    def test_stale_key_still_served(self):
        write_copy(self.e.state, "fake", "some other command line")
        s = self.sess()
        self.assertIn("result", s.initialize())
        self.assertEqual(len(s.request("tools/list")["result"]["tools"]), 3)
        self.assertEqual(procs(self.e.marker), [])
        self.assertTrue(wait_until(lambda: "stale" in s.stderr_text()))

    def test_no_copy_at_all_fails_connect_naming_server_and_repair(self):
        s = self.sess()
        r = s.initialize()
        self.assertIn("error", r)
        self.assertIn("'fake'", r["error"]["message"])
        self.assertIn("--refresh fake", r["error"]["message"])
        self.assertEqual(procs(self.e.marker), [])
        self.assertEqual(self.e.starts(), 0)

    def test_tool_call_starts_server_and_returns_real_result(self):
        write_copy(self.e.state, "fake", self.e.key())
        s = self.sess()
        s.initialize()
        self.assertEqual(procs(self.e.marker), [])
        r = s.call("echo", {"text": "hi"})
        self.assertEqual(text_of(r), "echo:hi")
        self.assertEqual(self.e.starts(), 1)
        self.assertTrue(procs(self.e.marker))
        self.assertEqual(text_of(s.call("echo", {"text": "again"})), "echo:again")
        self.assertEqual(self.e.starts(), 1)

    def test_resource_request_forwarded(self):
        write_copy(self.e.state, "fake", self.e.key("--resources"))
        s = self.sess("--resources")
        s.initialize()
        r = s.request("resources/read", {"uri": "x://y"})
        self.assertEqual(r["result"]["contents"][0]["text"], "resource-text")

    def test_server_request_roots_forwarded_both_ways(self):
        write_copy(self.e.state, "fake", self.e.key())
        s = self.sess(roots=[{"uri": "file:///work", "name": "work"}])
        s.initialize()
        r = s.call("roots")
        self.assertIn("file:///work", text_of(r))

    def test_changed_tool_list_rewrites_copy_and_notifies(self):
        write_copy(self.e.state, "fake", self.e.key("--toolset", "b"), tools=("echo", "slow", "roots"))
        s = self.sess("--toolset", "b")
        s.initialize()
        self.assertEqual(len(s.request("tools/list")["result"]["tools"]), 3)
        s.call("echo", {"text": "x"})
        self.assertIn("notifications/tools/list_changed", s.notes)
        saved = read_saved(self.e.state / "fake.json")
        self.assertEqual(len(saved["tools"]), 4)
        self.assertEqual(saved["key"], self.e.key("--toolset", "b"))
        self.assertEqual(len(s.request("tools/list")["result"]["tools"]), 4)

    def test_unchanged_tool_list_matches_saved_hash_and_does_not_rewrite_or_notify(self):
        # refresh once to get the real hash, then a session start must find the list unchanged
        subprocess.run([sys.executable, STANDIN, "--refresh", "fake", "--"] + self.e.fake_cmd(), capture_output=True, text=True,
                       env=self.e.env(), timeout=60, check=True)
        before = (self.e.state / "fake.json").read_bytes()
        self.assertIsNotNone(read_saved(self.e.state / "fake.json")["tools_sha"])
        s = self.sess()
        s.initialize()
        self.assertEqual(text_of(s.call("echo", {"text": "u"})), "echo:u")
        self.assertNotIn("notifications/tools/list_changed", s.notes)
        self.assertEqual((self.e.state / "fake.json").read_bytes(), before)

    def test_tool_list_reply_is_served_verbatim_from_the_copy(self):
        write_copy(self.e.state, "fake", self.e.key())
        s = self.sess()
        s.initialize()
        r = s.request("tools/list")
        self.assertEqual([t["name"] for t in r["result"]["tools"]], ["echo", "slow", "roots"])
        self.assertEqual(r["id"], s.n)

    def test_start_failure_is_named_with_stderr_tail_and_retried(self):
        crash = self.e.tmp / "crash"
        crash.write_text("x")
        write_copy(self.e.state, "fake", self.e.key("--crash-file", str(crash)))
        s = self.sess("--crash-file", str(crash))
        s.initialize()
        r = s.call("echo", {"text": "a"})
        self.assertIn("error", r)
        self.assertIn("'fake'", r["error"]["message"])
        self.assertIn("boom: cannot start", r["error"]["message"])
        self.assertIsNone(s.p.poll())
        self.assertIn("error", s.call("echo", {"text": "b"}))
        crash.unlink()
        self.assertEqual(text_of(s.call("echo", {"text": "c"})), "echo:c")
        self.assertIsNone(s.p.poll())

    def test_missing_command_is_a_named_error(self):
        write_copy(self.e.state, "fake", "k")
        cmd = [sys.executable, STANDIN, "fake", "600", "--", "/nonexistent/server-binary"]
        import subprocess as sp
        from harness import Session as S
        p = sp.Popen(cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.PIPE, env=self.e.env())
        p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "x"}}) + "\n").encode())
        p.stdin.flush()
        resp = json.loads(p.stdout.readline())
        self.assertIn("command not found", resp["error"]["message"])
        self.assertIn("'fake'", resp["error"]["message"])
        self.assertIsNone(p.poll())
        p.stdin.close()
        p.wait(timeout=10)

    def test_refresh_mode_saves_copy_and_leaves_no_server(self):
        r = subprocess.run([sys.executable, STANDIN, "--refresh", "fake", "--"] + self.e.fake_cmd("--grandchild"),
                           capture_output=True, text=True, env=self.e.env(), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        saved = read_saved(self.e.state / "fake.json")
        self.assertEqual([t["name"] for t in saved["tools"]], ["echo", "slow", "roots"])
        self.assertEqual(saved["key"], self.e.key("--grandchild"))
        self.assertTrue(wait_until(lambda: procs(self.e.marker) == []), procs(self.e.marker))

    def test_refresh_writes_state_copy_even_when_seed_is_identical(self):
        write_copy(self.e.seed, "fake", self.e.key())  # a seed that already matches what the server will report
        r = subprocess.run([sys.executable, STANDIN, "--refresh", "fake", "--"] + self.e.fake_cmd(),
                           capture_output=True, text=True, env=self.e.env(), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.e.state / "fake.json").exists(), "refresh must always write the state copy")

    def test_refresh_failure_reports_and_exits_nonzero(self):
        crash = self.e.tmp / "crash"
        crash.write_text("x")
        r = subprocess.run([sys.executable, STANDIN, "--refresh", "fake", "--"] + self.e.fake_cmd("--crash-file", str(crash)),
                           capture_output=True, text=True, env=self.e.env(), timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("boom", r.stderr)
        self.assertFalse((self.e.state / "fake.json").exists())


if __name__ == "__main__":
    unittest.main()
