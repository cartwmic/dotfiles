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
