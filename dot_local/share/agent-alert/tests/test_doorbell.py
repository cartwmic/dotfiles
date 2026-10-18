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

EVENT_LINE = (
    '{"version":1,"seq":7,"time":"2026-10-17T12:30:05.123Z","worker":"pane-3",'
    '"kind":"finished","summary":"done"}\n'
)
UNKNOWN_KIND_LINE = (
    '{"version":1,"seq":9,"time":"2026-10-17T12:30:05.123Z","worker":"pane-4",'
    '"kind":"paused","summary":"","extra":{"a":1},"future_member":[1,2]}\n'
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

    def doorbell_log_lines(self):
        return [line for line in self.scratch.log_text().splitlines() if " claude-doorbell: " in line]

    def assert_rang_with(self, worker, kind, seq=None):
        arguments = self.recorded_arguments()
        self.assertIsNotNone(arguments, "claude was not run")
        self.assertEqual(len(arguments), 4, arguments)
        self.assertEqual(arguments[0], "-p")
        self.assertEqual(arguments[2], "--cloud")
        self.assertEqual(arguments[3], SCRATCH_SESSION_ID)
        message = arguments[1]
        self.assertIn(worker, message)
        self.assertIn(kind, message)
        if seq is not None:
            self.assertIn(str(seq), message)
        self.assertIn("inbox", message)
        return message


class DeployedFileTests(DoorbellTestCase):
    def test_deployed_doorbell_is_executable_and_has_readme(self):
        self.assertTrue(self.doorbell.is_file())
        self.assertTrue(os.access(self.doorbell, os.X_OK))
        self.assertTrue((self.doorbell.parent / "README.md").is_file())


class DirectSinkTests(DoorbellTestCase):
    def test_success_runs_claude_with_p_message_and_cloud_id(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell()
        self.assertEqual(result.returncode, 0, result.stderr)
        message = self.assert_rang_with("pane-3", "finished", seq=7)
        self.assertNotIn("\n", message)
        self.assertEqual(self.doorbell_log_lines(), [])

    def test_nonzero_exit_is_logged_with_cause_and_exits_zero(self):
        self.install_fake_claude('echo "Not logged in. Please run /login" >&2\nexit 1\n')
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_rang_with("pane-3", "finished")
        log = self.doorbell_log_lines()
        self.assertEqual(len(log), 1, log)
        self.assertIn("exited with status 1", log[0])
        self.assertIn("Not logged in", log[0])
        self.assertIn("login", log[0])

    def test_claude_not_found_is_logged_and_exits_zero(self):
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell(path=str(self.empty_bin))
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.doorbell_log_lines()
        self.assertEqual(len(log), 1, log)
        self.assertIn("claude command not found", log[0])
        self.assertIsNone(self.recorded_arguments())

    def test_no_session_id_configured_is_logged_and_claude_is_not_run(self):
        self.install_fake_claude("exit 0\n")
        # No doorbell config file at all.
        result = self.run_doorbell()
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.doorbell_log_lines()
        self.assertEqual(len(log), 1, log)
        self.assertIn("no session id configured", log[0])
        self.assertIsNone(self.recorded_arguments())

    def test_blank_session_id_counts_as_none(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id="   ")
        result = self.run_doorbell()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no session id configured", "".join(self.doorbell_log_lines()))
        self.assertIsNone(self.recorded_arguments())

    def test_claude_that_sleeps_past_the_limit_is_killed_logged_and_exit_is_zero(self):
        pids = self.root / "pids.txt"
        self.install_fake_claude('echo $$ > "%s"\nsleep 30 &\necho $! >> "%s"\nwait\n' % (pids, pids))
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID, timeout_seconds=1)
        result = self.run_doorbell()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.elapsed, 10)
        self.assert_rang_with("pane-3", "finished")
        log = self.doorbell_log_lines()
        self.assertEqual(len(log), 1, log)
        self.assertIn("timed out after 1 seconds", log[0])
        for pid in pids.read_text().split():
            self.assertTrue(self.process_gone(int(pid)), "process %s survived the kill" % pid)

    def test_event_of_a_kind_this_version_does_not_define(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell(line=UNKNOWN_KIND_LINE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_rang_with("pane-4", "paused", seq=9)
        self.assertEqual(self.doorbell_log_lines(), [])

    def test_unknown_kind_with_no_claude_still_exits_zero_and_logs(self):
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell(line=UNKNOWN_KIND_LINE, path=str(self.empty_bin))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("claude command not found", "".join(self.doorbell_log_lines()))

    def test_line_that_is_not_a_json_object_gets_a_generic_nudge(self):
        for text in ("not json at all\n", "[1,2]\n", "", '{"worker": 5, "kind": null}\n'):
            with self.subTest(text=text):
                self.record.unlink(missing_ok=True)
                self.install_fake_claude("exit 0\n")
                self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
                result = self.run_doorbell(line=text)
                self.assertEqual(result.returncode, 0, result.stderr)
                arguments = self.recorded_arguments()
                self.assertEqual(arguments[0], "-p")
                self.assertEqual(arguments[2:], ["--cloud", SCRATCH_SESSION_ID])
                self.assertEqual(len(arguments), 4)

    def test_hostile_worker_text_stays_one_line_and_short(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        line = json.dumps({"seq": 1, "worker": "a\nb\u2028c" + "x" * 500, "kind": "finished"}) + "\n"
        result = self.run_doorbell(line=line)
        self.assertEqual(result.returncode, 0, result.stderr)
        arguments = self.recorded_arguments()
        self.assertEqual(len(arguments), 4, arguments)
        self.assertLess(len(arguments[1]), 200)

    def test_environment_session_id_overrides_the_file(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id="id-from-file")
        result = self.run_doorbell(AGENT_ALERT_DOORBELL_SESSION=SCRATCH_SESSION_ID)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_rang_with("pane-3", "finished")

    def test_bad_doorbell_config_file_is_logged_and_treated_as_empty(self):
        self.install_fake_claude("exit 0\n")
        self.doorbell_config.write_text("{not json")
        result = self.run_doorbell()
        self.assertEqual(result.returncode, 0, result.stderr)
        text = "".join(self.doorbell_log_lines())
        self.assertIn("cannot use config file", text)
        self.assertIn("no session id configured", text)
        self.assertIsNone(self.recorded_arguments())

    def test_claude_reading_standard_input_does_not_hang(self):
        self.install_fake_claude("cat > /dev/null\nexit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        result = self.run_doorbell(timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.elapsed, 3)
        self.assertEqual(self.doorbell_log_lines(), [])

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
        self.scratch.write_config(sinks=[str(self.doorbell)], sink_timeout_seconds=sink_timeout_seconds)

    def emit(self, kind="finished", worker="pane-3", env=None):
        started = time.monotonic()
        result = self.scratch.emit(worker=worker, kind=kind, summary="all done", env=env or self.env())
        result.elapsed = time.monotonic() - started
        return result

    def test_event_is_in_inbox_and_claude_is_rung_with_the_configured_id(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.configure_core()
        result = self.emit()
        self.assertEqual(result.returncode, 0, result.stderr)
        events = self.scratch.events()
        self.assertEqual([e["worker"] for e in events], ["pane-3"])
        self.assert_rang_with("pane-3", "finished", seq=1)
        self.assertEqual(self.scratch.log_text(), "")

    def test_every_kind_rings(self):
        self.install_fake_claude("exit 0\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID)
        self.configure_core()
        for kind in ("finished", "blocked", "errored", "exited"):
            with self.subTest(kind=kind):
                self.record.unlink(missing_ok=True)
                self.assertEqual(self.emit(kind=kind).returncode, 0)
                self.assert_rang_with("pane-3", kind)

    def test_sleeping_claude_does_not_delay_emit_beyond_the_bound_and_event_is_kept(self):
        self.install_fake_claude("sleep 30 &\nwait\n")
        self.write_doorbell_config(session_id=SCRATCH_SESSION_ID, timeout_seconds=1)
        self.configure_core(sink_timeout_seconds=3)
        result = self.emit()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(result.elapsed, 3 + 3)
        self.assertEqual(len(self.scratch.events()), 1)
        self.assert_rang_with("pane-3", "finished")
        self.assertIn("claude-doorbell: claude timed out after 1 seconds", self.scratch.log_text())

    def test_nonzero_claude_and_missing_claude_and_no_id_leave_the_event_and_exit_zero(self):
        cases = {
            "nonzero": dict(body="echo expired >&2\nexit 7\n", config={"session_id": SCRATCH_SESSION_ID},
                            path=None, cause="exited with status 7"),
            "not found": dict(body=None, config={"session_id": SCRATCH_SESSION_ID},
                              path="EMPTY", cause="claude command not found"),
            "no id": dict(body="exit 0\n", config={}, path=None, cause="no session id configured"),
        }
        for name, case in cases.items():
            with self.subTest(name):
                self.setUp_fresh()
                if case["body"] is not None:
                    self.install_fake_claude(case["body"])
                self.write_doorbell_config(**case["config"])
                self.configure_core()
                path = str(self.empty_bin) if case["path"] == "EMPTY" else None
                result = self.emit(env=self.env(path=path))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(len(self.scratch.events()), 1)
                self.assertIn(case["cause"], self.scratch.log_text())

    def setUp_fresh(self):
        """Reset the scratch state between sub-cases of one test."""
        self.scratch.cleanup()
        self.setUp()


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
