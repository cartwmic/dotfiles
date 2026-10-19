"""Black-box tests of the Claude doorbell sink.

Run (from the repository root):

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s dot_local/share/agent-alert/tests -p 'test_doorbell.py'

The real claude is never called. Every test puts a scripted `claude` (a small
shell script that records its arguments) on PATH, or no claude at all, and runs
the real adapters/claude-doorbell/doorbell.py from a deployed-layout copy that
chezmoi archived with adapters/ kept, in a scratch HOME. The session id used is
a scratch value, not a real one.

A held ring is delivered by a short-lived detached process of the doorbell itself, which
waits for the 30-second window to end. The tests never wait 30 seconds: they write a
doorbell state whose last ring is 28 seconds old, so the window ends about two seconds
later. Every test stops the held-ring process it caused before its scratch directory goes.
"""

import json
import os
import re
import stat
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SCRATCH_SESSION_ID = "scratch-session-0000"
SYSTEM_PATH = "/usr/bin:/bin"

EVENT_LINE = '{"version":1,"seq":7,"time":"2026-10-17T12:30:05.123Z","worker":"pane-3","kind":"finished"}\n'
UNKNOWN_KIND_LINE = (
    '{"version":1,"seq":9,"time":"2026-10-17T12:30:05.123Z","worker":"pane-4",'
    '"kind":"paused","extra":{"a":1},"future_member":[1,2]}\n'
)


class DoorbellTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.copy = common.deployed_copy(delete_adapters=False)
        cls.doorbell = cls.copy / "adapters" / "claude-doorbell" / "doorbell.py"
        cls.core = cls.copy / "core" / "agent-alert"

    def setUp(self):
        self.scratch = common.Scratch(cli=self.core)
        self.addCleanup(self.scratch.cleanup)
        self.root = self.scratch.root
        self.fake_bin = self.root / "fakebin"
        self.fake_bin.mkdir()
        self.empty_bin = self.root / "emptybin"
        self.empty_bin.mkdir()
        # The only program on this PATH is python3, so `claude` is not found but the
        # doorbell's own `#!/usr/bin/env python3` line still works.
        (self.empty_bin / "python3").symlink_to(sys.executable)
        self.record = self.root / "claude-record.txt"
        self.doorbell_config = self.root / "claude-doorbell.json"
        # Runs before the scratch directory is removed: a held-ring process must not outlive its test.
        self.addCleanup(self.stop_flusher)

    # -- helpers ---------------------------------------------------------

    def install_fake_claude(self, body):
        """A scripted claude that records its arguments, one per line, then runs body."""
        script = self.fake_bin / "claude"
        script.write_text(
            "#!/bin/sh\n"
            'for argument in "$@"; do printf \'%s\\n\' "$argument" >> "$FAKE_CLAUDE_RECORD"; done\n'
            + body
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)

    def write_doorbell_config(self, **values):
        self.doorbell_config.write_text(json.dumps(values))

    def recorded_arguments(self):
        if not self.record.exists():
            return None
        return self.record.read_text(encoding="utf-8").splitlines()

    def env(self, path=None, **extra):
        environment = self.scratch.env(
            PATH=path if path is not None else "%s:%s" % (self.fake_bin, SYSTEM_PATH),
            AGENT_ALERT_DOORBELL_CONFIG=str(self.doorbell_config),
            FAKE_CLAUDE_RECORD=str(self.record),
        )
        environment.update(extra)
        return environment

    def run_doorbell(self, line=EVENT_LINE, timeout=30, **env_options):
        """Run the real doorbell directly, with the event line on standard input."""
        started = time.monotonic()
        result = subprocess.run(
            [sys.executable, str(self.doorbell)],
            input=line,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env(**env_options),
            timeout=timeout,
            text=True,
            encoding="utf-8",
        )
        result.elapsed = time.monotonic() - started
        return result

    def throttle_file(self):
        self.scratch.log.parent.mkdir(parents=True, exist_ok=True)
        return self.scratch.log.parent / "claude-doorbell.last"

    def age_throttle(self, seconds=31):
        """Make the last ring look `seconds` old, instead of sleeping."""
        path = self.throttle_file()
        path.write_text(repr(time.time() - seconds), encoding="utf-8")

    def read_state(self):
        try:
            stored = json.loads(self.throttle_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return stored if isinstance(stored, dict) else {}

    def write_state(self, seconds_ago, held=None, more=0, latest=None, flusher=None):
        """Write the doorbell state as if the last ring were `seconds_ago` old."""
        state = {"last": time.time() - seconds_ago, "held": held or [], "more": more, "latest": latest, "flusher": flusher}
        self.throttle_file().write_text(json.dumps(state), encoding="utf-8")

    def flusher_pid(self):
        flusher = self.read_state().get("flusher")
        return flusher["pid"] if flusher else None

    def stop_flusher(self):
        pid = self.flusher_pid()
        if pid:
            try:
                os.kill(pid, 9)
            except OSError:
                pass

    def rings(self):
        """The message of every claude call so far (one call records six arguments)."""
        lines = self.recorded_arguments() or []
        return lines[3::6]

    def wait_for_rings(self, count, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.rings()) >= count:
                return self.rings()
            time.sleep(0.1)
        self.fail("expected %d rings, saw %r" % (count, self.rings()))

    def wait_until(self, condition, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if condition():
                return True
            time.sleep(0.1)
        return False

    @staticmethod
    def pid_alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True

    @staticmethod
    def process_gone(pid):
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.1)
        return False

    @staticmethod
    def event_line(seq, worker, kind="finished", **extra):
        event = {"version": 1, "seq": seq, "time": "2026-10-17T12:30:05.123Z", "worker": worker, "kind": kind}
        event.update(extra)
        return json.dumps(event, separators=(",", ":")) + "\n"

    def doorbell_log_lines(self):
        return [line for line in self.scratch.log_text().splitlines() if " claude-doorbell: " in line]

    def assert_rang_with(self, worker, kind, seq=None, session=None):
        arguments = self.recorded_arguments()
        self.assertIsNotNone(arguments, "claude was not run")
        self.assertEqual(arguments[:3], ["--safe-mode", "--no-session-persistence", "-p"], arguments)
        self.assertEqual(len(arguments), 6, arguments)
        self.assertEqual(arguments[4], "--cloud")
        self.assertEqual(arguments[5], session or SCRATCH_SESSION_ID)
        message = arguments[3]
        self.assertIn(worker, message)
        self.assertIn(kind, message)
        if seq is not None:
            self.assertIn("#%s" % seq, message)
        self.assertLessEqual(len(message.encode("utf-8")), 48, message)
        return message


class DeployedFileTests(DoorbellTestCase):
    def test_deployed_doorbell_is_executable(self):
        self.assertTrue(self.doorbell.is_file())
        self.assertTrue(os.access(self.doorbell, os.X_OK))


class DirectSinkTests(DoorbellTestCase):
    def test_success_runs_claude_with_p_message_and_cloud_id(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell()
        self.assertEqual(result.returncode, 0, result.stderr)
        message = self.assert_rang_with("pane-3", "finished", seq=7)
        self.assertNotIn("\n", message)
        self.assertEqual(self.doorbell_log_lines(), [])

    def test_environment_session_id_overrides_the_file(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id="id-from-file")
        result = self.run_doorbell(AGENT_ALERT_DOORBELL_SESSION=SCRATCH_SESSION_ID)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_rang_with("pane-3", "finished")

    def test_session_id_is_read_fresh_on_every_ring(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id="first-session")
        self.assertEqual(self.run_doorbell().returncode, 0)
        self.assert_rang_with("pane-3", "finished", session="first-session")
        self.record.unlink()
        self.age_throttle()
        self.write_doorbell_config(session_id="second-session")  # changed between rings, no restart
        self.assertEqual(self.run_doorbell().returncode, 0)
        self.assert_rang_with("pane-3", "finished", session="second-session")

    def test_nonzero_exit_is_logged_with_cause_and_exits_zero(self):
        self.install_fake_claude("exit 1\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_rang_with("pane-3", "finished")
        log = self.doorbell_log_lines()
        self.assertEqual(len(log), 1, log)
        self.assertIn("exited with status 1", log[0])

    def test_claude_not_found_is_logged_and_exits_zero(self):
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell(path=str(self.empty_bin))
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.doorbell_log_lines()
        self.assertEqual(len(log), 1, log)
        self.assertIn("claude command not found", log[0])

    def test_no_session_id_is_logged_and_claude_is_not_run(self):
        self.install_fake_claude("exit 0\n")
        # No doorbell config file at all.
        result = self.run_doorbell()
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.doorbell_log_lines()
        self.assertEqual(len(log), 1, log)
        self.assertIn("no session id configured", log[0])
        self.assertIsNone(self.recorded_arguments())

    def test_claude_that_sleeps_past_the_limit_is_killed_logged_and_exit_is_zero(self):
        pid_file = self.root / "pid.txt"
        self.install_fake_claude('echo $$ > "%s"\nexec sleep 30\n' % pid_file)
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.elapsed, 10)
        log = self.doorbell_log_lines()
        self.assertEqual(len(log), 1, log)
        self.assertIn("timed out after 4 seconds", log[0])
        self.assertTrue(self.process_gone(int(pid_file.read_text())), "claude survived the kill")

    def test_message_is_short_and_names_worker_kind_and_seq(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.assertEqual(self.run_doorbell().returncode, 0)
        self.assertEqual(self.assert_rang_with("pane-3", "finished", seq=7), "agent-alert: pane-3 finished #7")

    def test_claude_runs_lean_from_a_neutral_directory_without_claude_md(self):
        cwd_file = self.root / "claude-cwd.txt"
        self.install_fake_claude('pwd -P >> "%s"\nexit 0\n' % cwd_file)
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.assertEqual(self.run_doorbell().returncode, 0)
        cwd = Path(cwd_file.read_text().strip())
        self.assertEqual(cwd, self.scratch.log.parent.resolve())
        for name in ("CLAUDE.md", "AGENTS.md", ".claude", ".mcp.json"):
            self.assertFalse((cwd / name).exists(), name)

    def test_second_event_inside_the_window_is_not_rung_and_nothing_is_logged(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.assertEqual(self.run_doorbell().returncode, 0)
        first = self.recorded_arguments()
        second = self.run_doorbell(line=UNKNOWN_KIND_LINE)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.recorded_arguments(), first, "a second ring was sent inside the window")
        self.assertEqual(self.doorbell_log_lines(), [])

    def test_event_after_the_window_rings_again(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.assertEqual(self.run_doorbell().returncode, 0)
        self.record.unlink()
        self.age_throttle(31)
        self.assertEqual(self.run_doorbell(line=UNKNOWN_KIND_LINE).returncode, 0)
        self.assert_rang_with("pane-4", "paused", seq=9)

    def test_event_just_inside_the_window_is_still_held_back(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.age_throttle(20)
        self.assertEqual(self.run_doorbell().returncode, 0)
        self.assertIsNone(self.recorded_arguments())

    def test_six_doorbells_started_together_ring_exactly_once(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        processes = [
            subprocess.Popen([sys.executable, str(self.doorbell)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env=self.env(), text=True)
            for _ in range(6)
        ]
        for process in processes:
            process.communicate(EVENT_LINE, timeout=30)
            self.assertEqual(process.returncode, 0)
        arguments = self.recorded_arguments()
        self.assertEqual(len(arguments), 6, arguments)  # one claude call = six recorded arguments

    def test_unreadable_throttle_state_still_rings(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.throttle_file().write_text("not a number", encoding="utf-8")
        self.assertEqual(self.run_doorbell().returncode, 0)
        self.assert_rang_with("pane-3", "finished", seq=7)

    def test_a_ring_that_fails_still_opens_the_window(self):
        self.install_fake_claude("exit 1\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.assertEqual(self.run_doorbell().returncode, 0)
        self.assertEqual(len(self.doorbell_log_lines()), 1)
        self.assertEqual(self.run_doorbell().returncode, 0)
        self.assertEqual(len(self.doorbell_log_lines()), 1, "the second event rang inside the window")

    def test_hand_written_event_of_an_unknown_kind_is_rung(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell(line=UNKNOWN_KIND_LINE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_rang_with("pane-4", "paused", seq=9)
        self.assertEqual(self.doorbell_log_lines(), [])

    def test_line_that_is_not_a_json_object_is_logged_and_not_rung(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        for text in ("not json at all\n", "[1,2]\n", ""):
            with self.subTest(text=text):
                self.scratch.log.unlink(missing_ok=True)
                result = self.run_doorbell(line=text)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsNone(self.recorded_arguments())
                self.assertIn("not a JSON object", "".join(self.doorbell_log_lines()))



class HeldRingTests(DoorbellTestCase):
    """An event inside the window is held and rung once, combined, when the window ends."""

    def setUp(self):
        super().setUp()
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)

    def window_ends_soon(self, **state):
        self.write_state(28, **state)

    def run_held(self, line):
        result = self.run_doorbell(line=line)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.elapsed, 3, "the doorbell waited for the window instead of detaching")
        return result

    def test_single_event_rings_at_once_and_holds_nothing(self):
        self.run_held(EVENT_LINE)
        self.assertEqual(self.rings(), ["agent-alert: pane-3 finished #7"])
        state = self.read_state()
        self.assertEqual((state["held"], state["more"], state["flusher"]), ([], 0, None))
        self.assertEqual(self.doorbell_log_lines(), [])

    def test_second_event_inside_the_window_is_rung_after_the_window(self):
        self.run_held(EVENT_LINE)
        self.assertEqual(len(self.rings()), 1)
        self.window_ends_soon()
        self.run_held(self.event_line(8, "pane-4"))
        self.assertEqual(len(self.rings()), 1, "the held event was rung inside the window")
        self.assertEqual(self.read_state()["held"], [["pane-4", "finished", "8"]])
        pid = self.flusher_pid()
        self.assertIsNotNone(pid)
        self.assertEqual(self.wait_for_rings(2)[1], "agent-alert: pane-4 finished #8")
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(pid)), "the held-ring process did not end")
        state = self.read_state()
        self.assertEqual((state["held"], state["flusher"]), ([], None))
        self.assertEqual(self.doorbell_log_lines(), [])
        # the delivery opened a new window: a third event is held again, not rung
        self.run_held(self.event_line(9, "pane-5"))
        self.assertEqual(len(self.rings()), 2)

    def test_two_held_events_arrive_as_one_combined_ring_with_one_process(self):
        self.run_held(EVENT_LINE)
        self.window_ends_soon()
        self.run_held(self.event_line(134, "w15:p3V"))
        pid = self.flusher_pid()
        self.run_held(self.event_line(133, "w19:p1", kind="question"))
        self.assertEqual(self.flusher_pid(), pid, "a second held-ring process was started")
        rings = self.wait_for_rings(2)
        self.assertEqual(rings[1], "agent-alert: 2 events: w15:p3V finished #134, w19:p1 question #133")
        time.sleep(1)
        self.assertEqual(len(self.rings()), 2, "the held events were rung more than once")

    def test_many_held_events_are_coalesced_into_one_short_ring(self):
        self.run_held(EVENT_LINE)
        self.window_ends_soon()
        pids = set()
        for seq in range(10, 20):
            self.run_held(self.event_line(seq, "w1:p%d" % seq))
            pids.add(self.flusher_pid())
        self.assertEqual(len(pids), 1, pids)
        rings = self.wait_for_rings(2)
        self.assertEqual(
            rings[1],
            "agent-alert: 10 events: w1:p10 finished #10, w1:p11 finished #11, w1:p12 finished #12, "
            "w1:p13 finished #13, +6 more (latest #19)",
        )
        self.assertLess(len(rings[1].encode("utf-8")), 200)
        time.sleep(1)
        self.assertEqual(len(self.rings()), 2)
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(next(iter(pids)))))

    def test_held_state_names_only_worker_kind_and_seq_never_message_text(self):
        self.run_held(EVENT_LINE)
        self.window_ends_soon()
        line = self.event_line(8, "pane-4", context={"workspace_label": "SECRET-LABEL"}, summary="SECRET-TEXT")
        self.run_held(line)
        stored = self.throttle_file().read_text(encoding="utf-8")
        self.assertNotIn("SECRET", stored)
        self.assertEqual(self.read_state()["held"], [["pane-4", "finished", "8"]])
        self.assertEqual(self.wait_for_rings(2)[1], "agent-alert: pane-4 finished #8")
        self.assertNotIn("SECRET", self.record.read_text(encoding="utf-8"))

    def test_failing_claude_for_a_held_ring_is_logged_once_and_not_retried(self):
        self.install_fake_claude("exit 1\n")
        self.window_ends_soon()
        self.run_held(self.event_line(8, "pane-4"))
        self.run_held(self.event_line(9, "pane-5"))
        pid = self.flusher_pid()
        self.assertEqual(self.wait_for_rings(1)[0], "agent-alert: 2 events: pane-4 finished #8, pane-5 finished #9")
        self.assertTrue(self.wait_until(lambda: len(self.doorbell_log_lines()) == 1))
        self.assertIn("exited with status 1", self.doorbell_log_lines()[0])
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(pid)))
        time.sleep(1)
        self.assertEqual(len(self.rings()), 1, "a failed held ring was retried")
        state = self.read_state()
        self.assertEqual((state["held"], state["flusher"]), ([], None))
        self.assertLess(time.time() - state["last"], 10)  # the failed ring still opened a new window

    def test_missing_claude_for_a_held_ring_is_logged_and_the_process_still_ends(self):
        self.window_ends_soon()
        result = self.run_doorbell(line=self.event_line(8, "pane-4"), path=str(self.empty_bin))
        self.assertEqual(result.returncode, 0, result.stderr)
        pid = self.flusher_pid()
        self.assertTrue(self.wait_until(lambda: any("claude command not found" in line for line in self.doorbell_log_lines())))
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(pid)))

    def test_hanging_claude_for_a_held_ring_is_killed_at_four_seconds(self):
        pid_file = self.root / "pid.txt"
        self.install_fake_claude('echo $$ > "%s"\nexec sleep 30\n' % pid_file)
        self.window_ends_soon()
        self.run_held(self.event_line(8, "pane-4"))
        flusher = self.flusher_pid()
        self.assertTrue(self.wait_until(lambda: any("timed out after 4 seconds" in line for line in self.doorbell_log_lines())))
        self.assertTrue(self.process_gone(int(pid_file.read_text())), "claude survived the kill")
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(flusher)))

    def test_no_session_id_for_a_held_ring_is_logged_and_nothing_is_rung(self):
        self.window_ends_soon()
        self.run_held(self.event_line(8, "pane-4"))
        self.doorbell_config.unlink()  # the id went away between the hold and the delivery
        pid = self.flusher_pid()
        self.assertTrue(self.wait_until(lambda: any("no session id configured" in line for line in self.doorbell_log_lines())))
        self.assertTrue(self.wait_until(lambda: not self.pid_alive(pid)))
        self.assertIsNone(self.recorded_arguments())

    def test_events_left_held_by_a_dead_process_ride_with_the_next_ring(self):
        self.write_state(100, held=[["pane-1", "finished", "1"]], latest="1")
        self.run_held(EVENT_LINE)
        self.assertEqual(self.rings(), ["agent-alert: 2 events: pane-1 finished #1, pane-3 finished #7"])
        self.assertEqual(self.read_state()["held"], [])

    def test_a_registered_process_that_is_gone_is_replaced(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.write_state(28, held=[["pane-1", "finished", "1"]], latest="1",
                         flusher={"pid": dead.pid, "until": time.time() + 40})
        self.run_held(self.event_line(8, "pane-4"))
        pid = self.flusher_pid()
        self.assertNotEqual(pid, dead.pid)
        self.assertEqual(self.wait_for_rings(1)[0], "agent-alert: 2 events: pane-1 finished #1, pane-4 finished #8")

    def test_an_old_plain_number_state_file_still_means_the_last_ring_time(self):
        self.age_throttle(20)  # the format earlier doorbells wrote
        self.run_held(EVENT_LINE)
        self.assertIsNone(self.recorded_arguments())
        self.assertEqual(self.read_state()["held"], [["pane-3", "finished", "7"]])

    def load_doorbell(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("doorbell_under_test", str(self.doorbell))
        spec = importlib.util.spec_from_loader("doorbell_under_test", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module

    def with_doorbell_env(self):
        saved = dict(os.environ)
        os.environ.update(self.env())
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))

    def test_a_flusher_with_nothing_held_clears_its_registration_in_the_same_locked_step(self):
        # The interleaving that stranded events: the flusher sees nothing held, an event then arrives
        # and finds the flusher still registered. Retirement must clear the registration at once, so
        # the arriving event starts a replacement instead.
        doorbell = self.load_doorbell()
        self.with_doorbell_env()
        self.write_state(28, flusher={"pid": os.getpid(), "until": time.time() + 40})
        doorbell.flush_held()  # as that flusher: nothing is held, so it retires
        self.assertIsNone(self.read_state()["flusher"])
        # an event arriving now sees no live flusher and starts one for its held ring
        self.run_held(self.event_line(8, "pane-4"))
        self.assertIsNotNone(self.flusher_pid())
        self.assertNotEqual(self.flusher_pid(), os.getpid())
        self.assertEqual(self.wait_for_rings(1)[0], "agent-alert: pane-4 finished #8")

    def test_a_flusher_does_not_clear_a_replacements_registration(self):
        doorbell = self.load_doorbell()
        self.with_doorbell_env()
        other = subprocess.Popen(["sleep", "30"])
        self.addCleanup(lambda: (other.kill(), other.wait()))
        self.write_state(10, flusher={"pid": other.pid, "until": time.time() + 40})
        doorbell.flush_held()  # another live flusher is registered: leave it alone
        self.assertEqual(self.flusher_pid(), other.pid)

    def test_a_flusher_stops_rather_than_cross_its_lifetime_bound(self):
        doorbell = self.load_doorbell()
        self.with_doorbell_env()
        doorbell.FLUSHER_MAX_SECONDS = 2
        self.write_state(0, held=[["pane-4", "finished", "8"]], latest="8", flusher={"pid": os.getpid(), "until": time.time() + 40})
        started = time.monotonic()
        doorbell.flush_held()  # the window ends in 30 s, far past the 2 s budget
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsNone(self.recorded_arguments())
        state = self.read_state()
        self.assertEqual((state["held"], state["flusher"]), ([["pane-4", "finished", "8"]], None))
        # the held event rides with the next ring
        held = self.read_state()["held"]
        self.write_state(31, held=held, latest="8")
        self.run_held(self.event_line(9, "pane-5"))
        self.assertEqual(self.rings(), ["agent-alert: 2 events: pane-4 finished #8, pane-5 finished #9"])

    def test_held_ring_process_is_detached_and_leaves_no_pipe_open(self):
        # subprocess.run waits for end-of-file on the pipes; if the held-ring process kept them
        # open this would take until the window ended.
        self.run_held(EVENT_LINE)
        self.window_ends_soon()
        result = self.run_held(self.event_line(8, "pane-4"))
        self.assertEqual((result.stdout, result.stderr), ("", ""))
        self.assertIsNotNone(self.flusher_pid())


class ThroughCoreTests(DoorbellTestCase):
    """The doorbell started by the real core's sink runner."""

    def configure_core(self, sink_timeout_seconds=5):
        self.scratch.write_config(sink=[str(self.doorbell)], sink_timeout_seconds=sink_timeout_seconds)

    def emit(self, kind="finished", worker="pane-3"):
        started = time.monotonic()
        result = self.scratch.emit(worker=worker, kind=kind, env=self.env())
        result.elapsed = time.monotonic() - started
        return result

    def test_event_is_in_inbox_and_claude_is_rung_with_the_configured_id(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.configure_core()
        result = self.emit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([e["worker"] for e in self.scratch.events()], ["pane-3"])
        self.assert_rang_with("pane-3", "finished", seq=1)
        self.assertEqual(self.scratch.log_text(), "")

    def test_sleeping_claude_does_not_hold_emit_past_the_bound_and_event_is_kept(self):
        self.install_fake_claude("exec sleep 30\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.configure_core()
        result = self.emit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.elapsed, 5 + 3)
        self.assertEqual(len(self.scratch.events()), 1)
        self.assertIn("claude-doorbell: claude timed out", self.scratch.log_text())

    def test_held_ring_survives_the_core_killing_the_sink_group(self):
        # A sink wrapper that starts the real doorbell and then outlives the core's bound, so the
        # core really kills its process group. The held-ring process is in its own session.
        wrapper = self.root / "wrapper.sh"
        wrapper.write_text('#!/bin/sh\n"%s" || true\nexec sleep 30\n' % self.doorbell)
        wrapper.chmod(0o755)
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.scratch.write_config(sink=[str(wrapper)], sink_timeout_seconds=1)
        self.assertEqual(self.emit(worker="w15:p3V").returncode, 0)
        self.assertEqual(self.rings(), ["agent-alert: w15:p3V finished #1"])
        self.write_state(28)
        second = self.emit(worker="w19:p1", kind="finished")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertLess(second.elapsed, 4)  # emit did not wait for the window
        self.assertIn("timed out after 1 seconds and was killed", self.scratch.log_text())  # the group kill happened
        self.assertEqual(len(self.rings()), 1)
        self.assertEqual(self.wait_for_rings(2)[1], "agent-alert: w19:p1 finished #2")
        self.assertEqual([e["worker"] for e in self.scratch.events()], ["w15:p3V", "w19:p1"])


class SourceTreeTests(unittest.TestCase):
    SESSION_SHAPES = [
        re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
        re.compile(r"\bsession_[A-Za-z0-9]{10,}"),
        re.compile(r"\bcse_[A-Za-z0-9]{8,}"),
        re.compile(r"claude\.ai/code/[A-Za-z0-9_-]{8,}"),
    ]

    def test_source_tree_holds_no_session_id_shape(self):
        tree = common.TOOL_SOURCE_DIR
        checked = 0
        for path in sorted(tree.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            checked += 1
            for shape in self.SESSION_SHAPES:
                self.assertIsNone(shape.search(text), "%s looks like it holds a session id" % path)
        self.assertGreater(checked, 3)


if __name__ == "__main__":
    unittest.main()
