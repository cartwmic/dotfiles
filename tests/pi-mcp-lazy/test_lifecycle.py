import os
import signal
import subprocess
import sys
import time
import unittest

from harness import Env, Session, STANDIN, pid_alive, procs, text_of, wait_until, write_copy


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.cleanup)
        write_copy(self.e.state, "fake", self.e.key("--grandchild"))

    def sess(self, idle=2, *a, **k):
        s = Session(self.e, "fake", idle, "--grandchild", *a, **k)
        self.addCleanup(s.close)
        s.initialize()
        return s

    def test_idle_stop_kills_server_and_grandchild_then_restarts(self):
        s = self.sess(2)
        self.assertEqual(text_of(s.call("echo", {"text": "1"})), "echo:1")
        first = self.e.server_pid()
        self.assertEqual(len(procs(self.e.marker)), 2, procs(self.e.marker))
        self.assertTrue(wait_until(lambda: procs(self.e.marker) == [], timeout=12), procs(self.e.marker))
        self.assertTrue(wait_until(lambda: not pid_alive(first), timeout=5), "server process not reaped")
        self.assertEqual(text_of(s.call("echo", {"text": "2"})), "echo:2")
        self.assertEqual(self.e.starts(), 2)
        self.assertNotEqual(self.e.server_pid(), first)
        self.assertEqual(len(procs(self.e.marker)), 2)

    def test_server_keepalive_pings_do_not_hold_the_server_up(self):
        write_copy(self.e.state, "fake", self.e.key("--grandchild", "--ping-every", "0.4"))
        s = Session(self.e, "fake", 3, "--grandchild", "--ping-every", "0.4")
        self.addCleanup(s.close)
        s.initialize()
        self.assertEqual(text_of(s.call("echo", {"text": "p"})), "echo:p")
        self.assertEqual(len(procs(self.e.marker)), 2)
        self.assertTrue(wait_until(lambda: procs(self.e.marker) == [], timeout=15), procs(self.e.marker))

    def test_long_call_is_never_interrupted(self):
        s = self.sess(1)
        t0 = time.time()
        r = s.call("slow", {"seconds": 4}, timeout=30)
        self.assertEqual(text_of(r), "slow-done")
        self.assertGreaterEqual(time.time() - t0, 3.9)
        self.assertEqual(self.e.starts(), 1)
        self.assertTrue(procs(self.e.marker))
        self.assertTrue(wait_until(lambda: procs(self.e.marker) == [], timeout=12))

    def _send_hang_call(self, s):
        s.n += 1
        rid = s.n
        s.send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": "hang", "arguments": {"seconds": 0.3}}})
        return rid

    def test_cancelled_call_with_no_reply_does_not_keep_the_server_up(self):
        # Pi cancels on abort and timeout; a server such as rea then sends no reply at all
        s = self.sess(2)
        rid = self._send_hang_call(s)
        self.assertTrue(wait_until(lambda: len(procs(self.e.marker)) == 2, timeout=10))
        time.sleep(0.6)  # the server has finished its work and will never answer
        s.send({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": rid, "reason": "Aborted"}})
        self.assertTrue(wait_until(lambda: procs(self.e.marker) == [], timeout=15), "server kept up after a cancelled call: %r" % procs(self.e.marker))
        self.assertEqual(text_of(s.call("echo", {"text": "again"})), "echo:again")
        self.assertEqual(self.e.starts(), 2)

    def test_uncancelled_call_with_no_reply_is_still_protected(self):
        # without the cancel the request is still in flight: never stopped under it
        s = self.sess(2)
        self._send_hang_call(s)
        self.assertTrue(wait_until(lambda: len(procs(self.e.marker)) == 2, timeout=10))
        time.sleep(5)
        self.assertEqual(len(procs(self.e.marker)), 2, "stopped under a request still in flight")

    def test_idle_clock_counts_from_last_activity(self):
        s = self.sess(3)
        s.call("echo", {"text": "a"})
        time.sleep(2)
        s.call("echo", {"text": "b"})
        time.sleep(2)
        self.assertTrue(procs(self.e.marker), "stopped 2s after the last call although idle period is 3s")
        self.assertEqual(self.e.starts(), 1)
        self.assertTrue(wait_until(lambda: procs(self.e.marker) == [], timeout=12))

    def _exit_leaves_nothing(self, how):
        s = self.sess(600)
        s.call("echo", {"text": "x"})
        self.assertEqual(len(procs(self.e.marker)), 2)
        how(s)
        s.p.wait(timeout=15)
        self.assertTrue(wait_until(lambda: procs(self.e.marker) == [], timeout=10), procs(self.e.marker))

    def _pi_style_exit(self, send_sigterm):
        """Exit the way Pi 1.2.0 does: close stdin; SIGTERM the stand-in 0.5 s later; SIGKILL its group at 2.5 s. The real
        server and its helper ignore SIGTERM and run in their own group, so only the stand-in's own escalation can stop them.
        Production default grace (PI_MCP_LAZY_GRACE removed)."""
        write_copy(self.e.state, "fake", self.e.key("--grandchild", "--ignore-term"))
        s = Session(self.e, "fake", 600, "--grandchild", "--ignore-term", extra_env={"PI_MCP_LAZY_GRACE": None})
        self.addCleanup(s.close)
        s.initialize()
        self.assertEqual(text_of(s.call("echo", {"text": "x"})), "echo:x")
        self.assertEqual(len(procs(self.e.marker)), 2)
        t0 = time.time()
        s.p.stdin.close()
        if send_sigterm:
            time.sleep(0.5)
            s.p.send_signal(signal.SIGTERM)
        s.p.wait(timeout=15)
        left = procs(self.e.marker)
        took = time.time() - t0
        # Pi would SIGKILL the stand-in at 2.5 s; cleanup of the separate group must already be done by then
        self.assertEqual(left, [], "SIGTERM-ignoring server survived the stand-in's exit (%.1fs): %r" % (took, left))
        self.assertLess(took, 2.4, "stand-in took %.1fs to exit; Pi kills it at 2.5s" % took)

    def test_sigterm_ignoring_server_is_gone_within_pis_deadline_after_stdin_close(self):
        self._pi_style_exit(send_sigterm=False)

    def test_sigterm_ignoring_server_is_gone_within_pis_deadline_with_pis_sigterm(self):
        self._pi_style_exit(send_sigterm=True)

    def _signal_during_cleanup(self, s, started):
        """Wait until the real server has been sent its SIGTERM (cleanup under way), then do what Pi does on exit: SIGTERM the
        stand-in. The server ignores SIGTERM, so only the stand-in's own SIGKILL can stop it. Production grace."""
        term_seen = self.e.fdir / "term.seen"
        self.assertTrue(wait_until(term_seen.exists, timeout=20), "cleanup never started")
        t0 = time.time()
        s.p.send_signal(signal.SIGTERM)
        s.p.wait(timeout=10)
        took = time.time() - t0
        left = procs(self.e.marker)
        self.assertEqual(left, [], "SIGTERM-ignoring server survived a stand-in exit during %s: %r" % (started, left))
        self.assertLess(took, 1.0, "stand-in waited %.1fs for the cleanup already under way" % took)

    def test_exit_during_failed_start_cleanup_still_kills_a_sigterm_ignoring_server(self):
        # the server never answers initialize (start-delay) and ignores SIGTERM: the start fails after the timeout and the
        # cleanup of the failed child is in its grace period when Pi's SIGTERM arrives
        write_copy(self.e.state, "fake", self.e.key("--ignore-term", "--start-delay", "60"))
        s = Session(self.e, "fake", 600, "--ignore-term", "--start-delay", "60",
                    extra_env={"PI_MCP_LAZY_GRACE": None, "PI_MCP_LAZY_START_TIMEOUT": "2"})
        self.addCleanup(s.close)
        s.initialize()
        s.n += 1
        s.send({"jsonrpc": "2.0", "id": s.n, "method": "tools/call", "params": {"name": "echo", "arguments": {}}})
        self._signal_during_cleanup(s, "failed-start cleanup")

    def test_exit_during_idle_stop_still_kills_a_sigterm_ignoring_server(self):
        write_copy(self.e.state, "fake", self.e.key("--grandchild", "--ignore-term"))
        s = Session(self.e, "fake", 1, "--grandchild", "--ignore-term", extra_env={"PI_MCP_LAZY_GRACE": None})
        self.addCleanup(s.close)
        s.initialize()
        self.assertEqual(text_of(s.call("echo", {"text": "x"})), "echo:x")
        self.assertEqual(len(procs(self.e.marker)), 2)
        self._signal_during_cleanup(s, "idle stop")

    def test_exit_between_spawn_and_registration_still_kills_the_server(self):
        # test hook: the stand-in pauses right after spawning the server, before anything could have registered it; Pi's
        # SIGTERM arrives in that window. The server ignores SIGTERM and has its own process group.
        write_copy(self.e.state, "fake", self.e.key("--ignore-term", "--start-delay", "60"))
        s = Session(self.e, "fake", 600, "--ignore-term", "--start-delay", "60",
                    extra_env={"PI_MCP_LAZY_GRACE": None, "PI_MCP_LAZY_TEST_PAUSE_AFTER_SPAWN": "0.4"})
        self.addCleanup(s.close)
        s.initialize()
        s.n += 1
        s.send({"jsonrpc": "2.0", "id": s.n, "method": "tools/call", "params": {"name": "echo", "arguments": {}}})
        self.assertTrue(wait_until(lambda: len(procs(self.e.marker)) >= 1, timeout=10), "server was not spawned")
        t0 = time.time()
        s.p.send_signal(signal.SIGTERM)
        s.p.wait(timeout=10)
        took = time.time() - t0
        left = procs(self.e.marker)
        self.assertEqual(left, [], "server spawned just before the signal survived: %r" % left)
        self.assertLess(took, 2.4, "exit took %.1fs; Pi kills the stand-in at 2.5s" % took)

    def test_second_stop_still_reaches_a_helper_reparented_by_the_first(self):
        # the server exits on SIGTERM; its helper (own session) ignores it and is re-parented. Pi's SIGTERM arrives while the
        # first stop is in its grace period: the second stop must still find that helper.
        write_copy(self.e.state, "fake", self.e.key("--escaped-helper"))
        s = Session(self.e, "fake", 1, "--escaped-helper", extra_env={"PI_MCP_LAZY_GRACE": None})
        self.addCleanup(s.close)
        s.initialize()
        self.assertEqual(text_of(s.call("echo", {"text": "x"})), "echo:x")
        self.assertTrue(wait_until(lambda: (self.e.fdir / "helper.pid").exists(), timeout=10))
        self._signal_during_cleanup(s, "idle stop with an escaped helper")

    def test_interrupted_refresh_does_not_leave_the_server_running(self):
        cmd = [sys.executable, STANDIN, "--refresh", "fake", "--"] + self.e.fake_cmd("--ignore-term", "--start-delay", "60")
        p = subprocess.Popen(cmd, env=self.e.env(PI_MCP_LAZY_GRACE=None), stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.addCleanup(lambda: p.poll() is None and p.kill())
        self.assertTrue(wait_until(lambda: len(procs(self.e.marker)) >= 1, timeout=15), "refresh did not start the server")
        time.sleep(0.5)
        t0 = time.time()
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=10)
        left = procs(self.e.marker)
        self.assertEqual(left, [], "refresh interrupted by SIGTERM left the server running: %r" % left)
        self.assertLess(time.time() - t0, 2.4)

    def test_stdin_close_leaves_nothing(self):
        self._exit_leaves_nothing(lambda s: s.p.stdin.close())

    def test_sigterm_leaves_nothing(self):
        self._exit_leaves_nothing(lambda s: s.p.send_signal(signal.SIGTERM))

    def test_sighup_leaves_nothing(self):
        self._exit_leaves_nothing(lambda s: s.p.send_signal(signal.SIGHUP))

    def test_sigkill_observation(self):
        """Stated limit: SIGKILL gives the stand-in no chance to clean up. Record what happens."""
        s = self.sess(600)
        s.call("echo", {"text": "x"})
        s.p.kill()
        s.p.wait(timeout=10)
        time.sleep(1.5)
        left = procs(self.e.marker)
        print("\nSIGKILL observation: %d marker process(es) remain after the stand-in is killed: %s"
              % (len(left), [l.split(None, 1)[0] for l in left]))
        for l in left:
            try:
                os.kill(int(l.split()[0]), signal.SIGKILL)
            except Exception:
                pass

    def test_unexpected_server_exit_errors_inflight_and_restarts(self):
        s = self.sess(600)
        s.call("echo", {"text": "x"})
        pid = self.e.server_pid()
        s.n += 1
        rid = s.n
        s.send({"jsonrpc": "2.0", "id": rid, "method": "tools/call", "params": {"name": "slow", "arguments": {"seconds": 30}}})
        time.sleep(0.5)
        os.kill(pid, signal.SIGKILL)
        r = None
        end = time.time() + 15
        while time.time() < end and r is None:
            try:
                m = s.q.get(timeout=0.5)
                if m.get("id") == rid:
                    r = m
            except Exception:
                pass
        self.assertIsNotNone(r)
        self.assertIn("exited unexpectedly", r["error"]["message"])
        self.assertEqual(text_of(s.call("echo", {"text": "after"})), "echo:after")


if __name__ == "__main__":
    unittest.main()
