"""Black-box tests of the Claude doorbell sink.

Run (from the repository root):

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s dot_local/share/agent-alert/tests -p 'test_doorbell.py'

The real claude is never called. Every test puts a scripted `claude` (a small
shell script that records its arguments) on PATH, or no claude at all, and runs
the real adapters/claude-doorbell/doorbell.py from a deployed-layout copy that
chezmoi archived with adapters/ kept, in a scratch HOME. The session id used is
a scratch value, not a real one.
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

    @staticmethod
    def process_gone(pid):
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.1)
        return False


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
