"""Black-box tests of the agent-alert core CLI.

Run (from the repository root):

    python3 -m unittest discover -s dot_local/share/agent-alert/tests -p 'test_core.py'

Every test runs the real core/agent-alert from a deployed-layout copy that
chezmoi archived (adapters/ and examples/ deleted) with a scratch HOME.
The core writes no message text: an event is only a nudge.
"""

import json
import os
import re
import stat
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

TIME_PATTERN = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.scratch = common.Scratch()
        self.addCleanup(self.scratch.cleanup)

    def emit_ok(self, **kwargs):
        result = self.scratch.emit(**kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def write_script(self, name, body):
        path = self.scratch.root / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path


class DeployedLayoutTests(CoreTestCase):
    def test_copy_has_no_adapters_and_core_names_no_adapter(self):
        copy = common.deployed_copy()
        self.assertFalse((copy / "adapters").exists())
        self.assertTrue(os.access(copy / "core" / "agent-alert", os.X_OK))
        forbidden = re.compile(r"\b(herdr|pi|claude|tmux|zellij)\b", re.IGNORECASE)
        checked = 0
        for path in (copy / "core").rglob("*"):
            if path.is_file():
                checked += 1
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertIsNone(forbidden.search(text), str(path))
        self.assertGreater(checked, 0)

    def test_exactly_three_commands(self):
        helped = self.scratch.run("--help")
        self.assertEqual(helped.returncode, 0)
        self.assertIn("{emit,tail,ack}", helped.stdout)
        for name in ("follow", "watch", "list"):
            self.assertEqual(self.scratch.run(name).returncode, 2)


class EmitFormatTests(CoreTestCase):
    def test_all_five_kinds_are_valid_lines_with_consecutive_seq(self):
        for kind in ("finished", "question", "blocked", "errored", "exited"):
            self.emit_ok(worker="pane-" + kind, kind=kind)
        events = self.scratch.events()
        self.assertEqual([e["seq"] for e in events], [1, 2, 3, 4, 5])
        self.assertEqual([e["kind"] for e in events], ["finished", "question", "blocked", "errored", "exited"])
        for event in events:
            self.assertEqual(list(event), ["version", "seq", "time", "worker", "kind"])
            self.assertEqual(event["version"], 1)
            self.assertRegex(event["time"], TIME_PATTERN)
            self.assertTrue(event["worker"])
        first_line = self.scratch.inbox_bytes().splitlines()[0]
        self.assertTrue(first_line.startswith(b'{"version":1,"seq":1,"time":"'), first_line)
        self.assertTrue(first_line.endswith(b'","kind":"finished"}'), first_line)

    def test_default_inbox_and_config_locations_under_home(self):
        environment = {"HOME": str(self.scratch.home), "PATH": os.environ["PATH"]}
        result = self.scratch.run("emit", "--worker", "w", "--kind", "finished", env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        default_inbox = self.scratch.home / ".local" / "share" / "coordinator" / "inbox.jsonl"
        self.assertEqual(json.loads(default_inbox.read_text())["seq"], 1)

        config_dir = self.scratch.home / ".config" / "agent-alert"
        config_dir.mkdir(parents=True)
        moved = self.scratch.root / "moved.jsonl"
        (config_dir / "config.json").write_text(json.dumps({"inbox_path": str(moved)}))
        result = self.scratch.run("emit", "--worker", "w", "--kind", "finished", env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(moved.read_text())["seq"], 1)

    def test_environment_overrides_config_file(self):
        configured = self.scratch.root / "from-config.jsonl"
        self.scratch.write_config(inbox_path=str(configured))
        self.emit_ok()
        self.assertTrue(self.scratch.inbox.exists())
        self.assertFalse(configured.exists())

    def test_context_is_last_and_stored_as_given(self):
        self.emit_ok()  # seq 1, no context
        result = self.scratch.run(
            "emit", "--worker", "w1", "--kind", "blocked", "--context", "workspace=main label", "--context-json", '{"agent":"x"}'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        event = self.scratch.events()[1]
        self.assertEqual(list(event), ["version", "seq", "time", "worker", "kind", "context"])
        self.assertEqual(event["context"], {"agent": "x", "workspace": "main label"})

    def test_no_message_member_in_any_line_and_no_summary_option(self):
        self.emit_ok()
        self.scratch.run("emit", "--worker", "w2", "--kind", "finished", "--context", "k=v")
        before = self.scratch.inbox_bytes()
        for args in (("--summary", "some text"), ("--summary", "-")):
            result = self.scratch.run("emit", "--worker", "w3", "--kind", "finished", *args, stdin="text on stdin")
            self.assertEqual(result.returncode, 2, args)
            self.assertIn("--summary", result.stderr)
        self.assertEqual(self.scratch.inbox_bytes(), before)
        for event in self.scratch.events():
            for member in ("summary", "message", "text"):
                self.assertNotIn(member, event)
            self.assertLessEqual(set(event), {"version", "seq", "time", "worker", "kind", "context"})

    def test_worker_and_context_are_stored_as_given_without_limits_or_masking(self):
        worker = "sk-abcdefghijklmnop " + "w" * 500 + " \u00e9\u4e2d\t\u2028end"
        value = "password=hunter2hunter2 " + "v" * 500
        key = "k" * 100
        self.assertEqual(self.scratch.run("emit", "--worker", worker, "--kind", "finished", "--context", key + "=" + value).returncode, 0)
        event = self.scratch.events()[0]
        self.assertEqual(event["worker"], worker)
        self.assertEqual(event["context"], {key: value})
        many = {"k%d" % i: "v" for i in range(20)}
        self.assertEqual(self.scratch.run("emit", "--worker", "w", "--kind", "finished", "--context-json", json.dumps(many)).returncode, 0)
        self.assertEqual(self.scratch.events()[1]["context"], many)


class EmitConcurrencyTests(CoreTestCase):
    def burst(self, count, kind="finished"):
        barrier = threading.Barrier(count)
        results = [None] * count

        def worker(index):
            barrier.wait()
            results[index] = self.scratch.emit(worker="burst-%d" % index, kind=kind)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_six_simultaneous_emits_are_intact_with_consecutive_seq(self):
        self.burst(6)
        events = self.scratch.events()
        self.assertEqual([e["seq"] for e in events], list(range(1, 7)), "file order must follow seq")
        self.assertEqual(sorted(e["worker"] for e in events), sorted("burst-%d" % i for i in range(6)))
        self.burst(6, kind="blocked")
        events = self.scratch.events()
        self.assertEqual([e["seq"] for e in events], list(range(1, 13)), "seq continues across runs")

    def test_two_rapid_emits_same_worker_and_kind_give_two_lines(self):
        self.emit_ok(worker="same", kind="finished")
        self.emit_ok(worker="same", kind="finished")
        events = self.scratch.events()
        self.assertEqual([(e["seq"], e["worker"], e["kind"]) for e in events], [(1, "same", "finished"), (2, "same", "finished")])


class EmitRefusalTests(CoreTestCase):
    def test_unwritable_inbox_exits_nonzero_with_nothing_written(self):
        blocker = self.scratch.root / "blocked"
        blocker.write_text("a file where a directory is needed")
        env = self.scratch.env(AGENT_ALERT_INBOX=str(blocker / "inbox.jsonl"))
        result = self.scratch.emit(env=env)
        self.assertEqual(result.returncode, 3)
        self.assertIn("agent-alert:", result.stderr)
        self.assertEqual(blocker.read_text(), "a file where a directory is needed")
        self.assertIn("emit failed", self.scratch.log_text())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores directory modes")
    def test_read_only_inbox_directory_exits_nonzero_with_nothing_written(self):
        directory = self.scratch.root / "readonly"
        directory.mkdir()
        directory.chmod(0o500)
        self.addCleanup(directory.chmod, 0o700)
        env = self.scratch.env(AGENT_ALERT_INBOX=str(directory / "inbox.jsonl"))
        result = self.scratch.emit(env=env)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(os.listdir(directory), [])

    def assert_rejected(self, *args):
        self.emit_ok()
        before = self.scratch.inbox_bytes()
        result = self.scratch.run("emit", *args)
        self.assertNotEqual(result.returncode, 0, args)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("agent-alert", result.stderr)
        self.assertEqual(self.scratch.inbox_bytes(), before)

    def test_unknown_kind_is_rejected(self):
        self.assert_rejected("--worker", "w1", "--kind", "paused")

    def test_empty_or_blank_worker_is_rejected(self):
        self.assert_rejected("--worker", "", "--kind", "finished")
        self.assert_rejected("--worker", "   ", "--kind", "finished")

    def test_missing_worker_is_rejected(self):
        self.assert_rejected("--kind", "finished")

    def test_non_string_context_value_is_rejected(self):
        self.assert_rejected("--worker", "w1", "--kind", "finished", "--context-json", '{"count": 3}')
        self.assert_rejected("--worker", "w1", "--kind", "finished", "--context-json", '{"nested": {"a": "b"}}')
        self.assert_rejected("--worker", "w1", "--kind", "finished", "--context-json", '["a"]')
        self.assert_rejected("--worker", "w1", "--kind", "finished", "--context-json", "not json")

    def test_bad_configuration_is_rejected_before_writing(self):
        self.scratch.config.write_text("{not json")
        result = self.scratch.emit()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.scratch.inbox_bytes(), b"")


class FragmentTests(CoreTestCase):
    def test_hand_made_fragment_then_emit_gives_own_line_and_next_seq(self):
        self.emit_ok()
        fragment = b'{"version":1,"seq":2,"time":"2026-01-01T00:00:00.000Z","wor'
        with open(self.scratch.inbox, "ab") as handle:
            handle.write(fragment)
        before = self.scratch.inbox_bytes()
        # tail and ack skip the fragment
        tailed = self.scratch.run("tail", "--since", "0")
        self.assertEqual(tailed.returncode, 0)
        self.assertEqual([json.loads(l)["seq"] for l in tailed.stdout.splitlines()], [1])
        self.assertEqual(self.scratch.run("ack", "1").returncode, 0)
        self.assertEqual(self.scratch.run("ack", "2").returncode, 2)
        self.assertEqual(self.scratch.inbox_bytes(), before)

        self.emit_ok(worker="after-fragment")
        after = self.scratch.inbox_bytes()
        self.assertTrue(after.startswith(before + b"\n"), "emit must first end the fragment with a newline")
        new_line = after[len(before) + 1:]
        self.assertTrue(new_line.endswith(b"\n"))
        decoded = json.loads(new_line)
        self.assertEqual(decoded["seq"], 2)
        self.assertEqual(decoded["worker"], "after-fragment")
        tailed = self.scratch.run("tail", "--since", "0")
        self.assertEqual([json.loads(l)["seq"] for l in tailed.stdout.splitlines()], [1, 2])

    def file_size_limit_bytes(self):
        """What `ulimit -f 1` allows on this system (the unit of ulimit -f differs by shell)."""
        probe = self.scratch.root / "limit-probe"
        script = "import os; fd = os.open(%r, os.O_WRONLY | os.O_CREAT); os.write(fd, bytes(65536))" % str(probe)
        subprocess.run(["sh", "-c", 'ulimit -f 1; exec "$@"', "sh", sys.executable, "-c", script], stderr=subprocess.DEVNULL)
        return probe.stat().st_size

    def test_short_write_under_file_size_limit_leaves_next_emit_intact(self):
        limit = self.file_size_limit_bytes()
        self.assertGreater(limit, 0)
        self.emit_ok()
        first_size = len(self.scratch.inbox_bytes())
        with open(self.scratch.inbox, "ab") as handle:
            handle.write(b"x" * (limit - first_size - 100) + b"\n")  # not an event: readers skip it
        before = self.scratch.inbox_bytes()
        self.assertLess(len(before), limit)
        result = self.scratch.emit(worker="y" * 150, wrapper="ulimit -f 1;")
        self.assertNotEqual(result.returncode, 0)
        partial = self.scratch.inbox_bytes()
        self.assertGreater(len(partial), len(before), "the limit should have cut the write short")
        self.assertTrue(partial.startswith(before))
        self.assertFalse(partial.endswith(b"\n"))

        self.emit_ok(worker="w3")
        final = self.scratch.inbox_bytes()
        self.assertTrue(final.startswith(partial + b"\n"))
        last = json.loads(final[len(partial) + 1:])
        self.assertEqual((last["seq"], last["worker"]), (2, "w3"))
        tailed = self.scratch.run("tail", "--since", "0")
        self.assertEqual([json.loads(l)["seq"] for l in tailed.stdout.splitlines()], [1, 2])


class ReadAndAckTests(CoreTestCase):
    def seqs(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line)["seq"] for line in result.stdout.splitlines()]

    def test_tail_since_ack_and_lower_ack(self):
        for index in range(5):
            self.emit_ok(worker="w%d" % index)
        raw_lines = self.scratch.inbox_bytes().decode("utf-8").splitlines()

        self.assertEqual(self.seqs(self.scratch.run("tail", "--since", "0")), [1, 2, 3, 4, 5])
        self.assertEqual(self.scratch.run("tail", "--since", "0").stdout.splitlines(), raw_lines)
        self.assertEqual(self.seqs(self.scratch.run("tail", "--since", "2")), [3, 4, 5])
        self.assertEqual(self.scratch.run("tail", "--since", "3").stdout.splitlines(), raw_lines[3:])
        self.assertEqual(self.seqs(self.scratch.run("tail", "--since", "5")), [])
        self.assertEqual(self.seqs(self.scratch.run("tail", "--since", "99")), [])
        self.assertEqual(self.seqs(self.scratch.run("tail")), [1, 2, 3, 4, 5], "no ack yet")

        before = self.scratch.inbox_bytes()
        self.assertEqual(self.scratch.run("ack", "3").returncode, 0)
        self.assertEqual(self.scratch.inbox_bytes(), before, "ack must not touch the inbox")
        self.assertEqual(self.seqs(self.scratch.run("tail")), [4, 5])

        self.assertEqual(self.scratch.run("ack", "2").returncode, 0)
        self.assertEqual(self.scratch.inbox_bytes(), before)
        self.assertEqual(self.seqs(self.scratch.run("tail")), [4, 5], "a lower ack must not move the ack back")

        self.assertEqual(self.scratch.run("ack", "5").returncode, 0)
        self.assertEqual(self.seqs(self.scratch.run("tail")), [])
        self.assertEqual(self.seqs(self.scratch.run("tail", "--since", "0")), [1, 2, 3, 4, 5])

        beyond = self.scratch.run("ack", "6")
        self.assertEqual(beyond.returncode, 2)
        self.assertEqual(self.scratch.inbox_bytes(), before)
        self.assertEqual(self.scratch.run("tail", "--since", "-1").returncode, 2)

    def test_tail_without_inbox_exits_zero(self):
        result = self.scratch.run("tail", "--since", "0")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertFalse(self.scratch.inbox.exists())

    def test_unknown_kind_line_passes_through_tail_unchanged(self):
        self.emit_ok()
        hand_written = '{"version":2,"seq":2,"time":"2030-01-01T00:00:00Z","worker":"w9","kind":"paused","extra":[1,2]}'
        with open(self.scratch.inbox, "ab") as handle:
            handle.write(b"not json at all\n[1,2]\n" + b'{"no":"seq"}\n' + hand_written.encode() + b"\n")
        tailed = self.scratch.run("tail", "--since", "1")
        self.assertEqual(tailed.stdout.splitlines(), [hand_written])
        self.assertEqual(self.scratch.run("ack", "2").returncode, 0)
        # emit continues from the last parseable line
        self.emit_ok(worker="after")
        self.assertEqual(json.loads(self.scratch.inbox_bytes().splitlines()[-1])["seq"], 3)


class SinkTests(CoreTestCase):
    def setUp(self):
        super().setUp()
        self.received = self.scratch.root / "received.jsonl"
        self.ok_sink = self.write_script(
            "sink-ok.sh",
            'cat >> "%s"\necho "log=$AGENT_ALERT_LOG inbox=$AGENT_ALERT_INBOX" >> "%s.env"\n' % (self.received, self.received),
        )
        self.failing_sink = self.write_script("sink-fail.sh", "cat >/dev/null\nexit 3\n")
        self.pid_file = self.scratch.root / "sleeper.pid"
        self.child_pid_file = self.scratch.root / "sleeper-child.pid"
        self.sleeping_sink = self.write_script(
            "sink-sleep.sh",
            'echo $$ > "%s"\nsleep 30 &\necho $! > "%s"\nwait\n' % (self.pid_file, self.child_pid_file),
        )
        self.missing_sink = self.scratch.root / "no-such-sink"

    def assert_event_kept(self, kind="finished"):
        events = self.scratch.events()
        self.assertEqual(events[-1]["kind"], kind)

    def run_timed(self, **kwargs):
        started = time.monotonic()
        result = self.scratch.emit(**kwargs)
        return result, time.monotonic() - started

    def test_ok_sink_receives_every_kind_once_with_the_line_on_stdin(self):
        self.scratch.write_config(sink=[str(self.ok_sink)])
        for kind in ("finished", "question", "blocked", "errored", "exited"):
            self.emit_ok(kind=kind)
        received = self.received.read_bytes()
        self.assertEqual(received, self.scratch.inbox_bytes(), "the exact bytes appended, once per event")
        self.assertEqual([json.loads(line)["kind"] for line in received.splitlines()], ["finished", "question", "blocked", "errored", "exited"])
        environment = self.received.with_name("received.jsonl.env").read_text().splitlines()[0]
        self.assertEqual(environment, "log=%s inbox=%s" % (self.scratch.log, self.scratch.inbox))
        self.assertEqual(self.scratch.log_text(), "")

    def test_no_sink_configured_is_fine(self):
        self.emit_ok()
        self.assertEqual(self.scratch.log_text(), "")

    def test_sink_argument_list_and_environment_override(self):
        self.scratch.write_config(sink=["sh", "-c", 'cat > "$1"', "sh", str(self.received)])
        self.emit_ok()
        self.assertEqual(json.loads(self.received.read_text())["seq"], 1)
        other = self.scratch.root / "other.jsonl"
        env = self.scratch.env(AGENT_ALERT_SINK=json.dumps(["sh", "-c", 'cat > "$1"', "sh", str(other)]))
        self.emit_ok(env=env)
        self.assertEqual(json.loads(other.read_text())["seq"], 2)
        self.assertEqual(json.loads(self.received.read_text())["seq"], 1, "the override replaces the configured sink")

    def test_nonzero_sink_is_logged_and_event_kept(self):
        self.scratch.write_config(sink=[str(self.failing_sink)])
        result, _ = self.run_timed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_event_kept()
        self.assertIn("exited with status 3", self.scratch.log_text())
        self.assertIn(str(self.failing_sink), self.scratch.log_text())

    def test_missing_sink_is_logged_and_event_kept(self):
        self.scratch.write_config(sink=[str(self.missing_sink)])
        result, _ = self.run_timed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_event_kept()
        self.assertIn("cannot start", self.scratch.log_text())
        self.assertIn("no-such-sink", self.scratch.log_text())

    def wait_gone(self, pid):
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        self.fail("process %d is still running" % pid)

    def test_sink_sleeping_past_the_bound_is_killed_with_its_group(self):
        self.scratch.write_config(sink=[str(self.sleeping_sink)], sink_timeout_seconds=1)
        result, elapsed = self.run_timed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 4.0)
        self.assert_event_kept()
        self.assertIn("timed out after 1 seconds", self.scratch.log_text())
        self.wait_gone(int(self.pid_file.read_text()))
        self.wait_gone(int(self.child_pid_file.read_text()))

    def test_sink_that_ignores_its_stdin_still_lets_emit_finish(self):
        quiet = self.write_script("sink-quiet.sh", "exit 0\n")
        self.scratch.write_config(sink=[str(quiet)])
        result, _ = self.run_timed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.scratch.log_text(), "")

    def test_unusable_sink_timeout_is_rejected_before_writing(self):
        for value in (0, -1, "5", True):
            with self.subTest(value=value):
                self.scratch.write_config(sink_timeout_seconds=value)
                result = self.scratch.emit()
                self.assertEqual(result.returncode, 2)
                self.assertEqual(self.scratch.inbox_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
