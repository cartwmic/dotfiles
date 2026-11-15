"""c10: the G14 command hands each action to a scheduled task and waits for the answer.

Under PowerShell 7 on Linux, with a stub ScheduledTasks module standing in for the real one:
  * a bad call exits 2, prints the usage naming all eight actions and `ui`, and writes no request;
  * a good call writes a request, starts the task, prints the answer and exits with the answer's exit code (0 and 3);
  * no answer in time: exit 1 with a message, and the request is withdrawn so a late task run cannot act on it;
  * no task registered: exit 69;
  * the whole chain: the stub's Start-ScheduledTask runs the action that install.ps1 registered, in a clean environment and
    another folder, as the real task does. That proves the lock check, `ui` through the task, the shared run id in the log,
    and that `type` logs only its length, on both sides of the task.
`shot`, `windows`, `focus`, `move`, `click`, `type` and `key` call user32 and .NET drawing, which exist only on Windows, so
their effect on a screen is for the live run on the G14 (the worker's failure message on Linux is all these tests see).
Run: mise exec aqua:PowerShell/PowerShell@7.7.0 -- python3 -m unittest discover -s tests/agent-desktop -p test_windows_bridge.py
"""
import json
import os
import re
import time
import unittest

import windows_testlib as wt
from windows_testlib import EIGHT, WINDOWS, Sandbox, WindowsTestCase

SCRIPT = WINDOWS / "agent-desktop.ps1"
LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ run=(\S+) elapsed=\d+s (.+)$")

BAD_CALLS = [
    [], ["frobnicate"], ["shot"], ["shot", "a.png", "1,2 3x4", "extra"], ["shot", "a.png", "not a region"], ["shot", ""],
    ["windows", "extra"], ["focus"], ["focus", ""], ["focus", "a", "b"],
    ["move", "1"], ["move", "x", "2"], ["move", "1", "2.5"], ["move", "1", "2", "3"],
    ["click"], ["click", "1"], ["click", "1", "2", "wheel"], ["click", "a", "2"], ["click", "1", "2", "left", "extra"],
    ["type"], ["type", "a", "b"],
    ["key"], ["key", "bad word!"], ["key", "comma", "ct rl"], ["key", "nosuchkeyname"], ["key", "comma", "nosuchmodifier"],
    ["cursor", "extra"], ["ui"],
]


class BridgeBase(WindowsTestCase):
    def setUp(self):
        super().setUp()
        self.box = Sandbox(self)

    def call(self, *args, mode="answer", cwd=None, **extra):
        env = self.box.env(AD_STUB_MODE=mode, **extra)
        return self.box.run(self.script, *args, env=env, cwd=cwd)

    script = SCRIPT

    def request_files(self):
        return [n for n in self.box.state_files() if n.startswith("request-")]


class BadCallTest(BridgeBase):
    def test_a_bad_call_exits_2_prints_the_usage_and_writes_no_request(self):
        for argv in BAD_CALLS:
            with self.subTest(argv=argv):
                r = self.call(*argv)
                self.assertEqual(r.returncode, 2, (r.stdout, r.stderr))
                self.assertIn("usage:", r.stderr)
                for action in EIGHT + ("ui",):
                    self.assertIn(action, r.stderr, "usage must name %s" % action)
                self.assertEqual(self.box.state_files(), [], "no request, answer or log may be written")
                self.assertEqual(self.box.calls(), [], "the task must not be started")

    def test_a_bad_timeout_setting_exits_2(self):
        r = self.call("cursor", AGENT_DESKTOP_TIMEOUT="soon")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("AGENT_DESKTOP_TIMEOUT", r.stderr)


# (call, step text the log must hold). Each is a valid call: the client must accept it and hand it to the task unchanged.
GOOD_CALLS = [
    (["shot", "out.png"], "request shot out.png region=full"),
    (["shot", "out.png", "10,20 300x400"], "request shot out.png region=10,20 300x400"),
    (["shot", "out.png", "-5,-5 10x10"], "request shot out.png region=-5,-5 10x10"),
    (["windows"], "request windows"),
    (["focus", "notepad.exe"], "request focus notepad.exe"),
    (["focus", "Untitled - Notepad"], "request focus Untitled - Notepad"),
    (["move", "0", "0"], "request move 0 0"),
    (["move", "-3", "1079"], "request move -3 1079"),
    (["click", "1", "2"], "request click 1 2 left"),
    (["click", "1", "2", "right"], "request click 1 2 right"),
    (["click", "1", "2", "middle"], "request click 1 2 middle"),
    (["type", ""], "request type length=0"),
    (["type", "two words\nand a line"], "request type length=20"),
    (["key", "comma", "ctrl"], "request key comma mods=ctrl"),
    (["key", "Return"], "request key Return mods=none"),
    (["key", "F5", "shift", "alt"], "request key F5 mods=shift,alt"),
    (["key", "Page_Up"], "request key Page_Up mods=none"),
    (["key", "a", "super"], "request key a mods=super"),
    (["key", "7", "Control"], "request key 7 mods=Control"),
    (["cursor"], "request cursor"),
]


class RequestAnswerTest(BridgeBase):
    def test_every_valid_call_is_accepted_and_reaches_the_task_unchanged(self):
        for argv, step in GOOD_CALLS:
            with self.subTest(argv=argv):
                r = self.call(*argv, AD_STUB_STDOUT="")
                self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
                req = json.loads((self.box.state / "seen-request.json").read_text())
                self.assertEqual((req["action"], req["argv"]), (argv[0], argv[1:]))
                self.assertTrue(any(l.endswith(" " + step) for l in self.box.log_lines()), (step, self.box.log_lines()[-3:]))

    def test_ui_with_arguments_is_accepted(self):
        r = self.call("ui", "snapshot", "-i", "--compact", AGENT_DESKTOP_UI_BIN=str(self.box.ui_exe))
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertTrue(any(l.endswith(" request ui sub=snapshot argc=3") for l in self.box.log_lines()), self.box.log_lines())

    def test_the_answer_is_printed_and_its_exit_code_is_passed_through(self):
        for code in (0, 3):
            with self.subTest(code=code):
                r = self.call("move", "10", "-20", AD_STUB_EXIT=str(code), AD_STUB_STDOUT="5 6\n", AD_STUB_STDERR="warn\n")
                self.assertEqual(r.returncode, code, (r.stdout, r.stderr))
                self.assertEqual(r.stdout, "5 6\n")
                self.assertEqual(r.stderr, "warn\n")

    def test_the_request_names_the_action_its_arguments_and_the_callers_folder(self):
        self.call("shot", "out.png", "1,2 30x40", AD_STUB_STDOUT="out.png\n")
        req = json.loads((self.box.state / "seen-request.json").read_text())
        self.assertEqual(req["action"], "shot")
        self.assertEqual(req["argv"], ["out.png", "1,2 30x40"])
        self.assertEqual(os.path.realpath(req["cwd"]), os.path.realpath(self.box.work), "a relative FILE is resolved by the worker against this")
        self.assertRegex(req["id"], r"^\d{8}T\d{6}Z-\d+$")

    def test_ui_arguments_and_the_callers_tool_path_travel_in_the_request(self):
        self.call("ui", "snapshot", "-i", "two words", AGENT_DESKTOP_UI_BIN=str(self.box.ui_exe))
        req = json.loads((self.box.state / "seen-request.json").read_text())
        self.assertEqual(req["action"], "ui")
        self.assertEqual(req["argv"], ["snapshot", "-i", "two words"])
        self.assertEqual(req["ui_bin"], str(self.box.ui_exe), "the task does not see the caller's environment")

    def test_ui_with_no_tool_installed_exits_69_before_any_request(self):
        r = self.call("ui", "snapshot")
        self.assertEqual(r.returncode, 69, r.stderr)
        self.assertIn("install.ps1", r.stderr)
        self.assertEqual(self.box.state_files(), [])

    def test_a_finished_call_leaves_only_the_log(self):
        self.call("cursor", AD_STUB_STDOUT="1 2\n")
        self.assertEqual(self.box.state_files(), ["agent-desktop.log"])

    def test_no_answer_in_time_exits_1_with_a_message_and_withdraws_the_request(self):
        started = time.monotonic()
        r = self.call("cursor", mode="none", AGENT_DESKTOP_TIMEOUT="1")
        elapsed = time.monotonic() - started
        self.assertEqual(r.returncode, 1, (r.stdout, r.stderr))
        self.assertRegex(r.stderr, r"(?i)no answer")
        self.assertEqual(r.stdout, "")
        self.assertLess(elapsed, 20, "the wait must end at the time limit")
        self.assertEqual(self.request_files(), [], "a late task run must find nothing to do")
        self.assertTrue(any("FAIL" in l and "timeout" in l for l in self.box.log_lines()), self.box.log_lines())

    def test_no_task_registered_exits_69_and_names_the_install_script(self):
        r = self.call("cursor", mode="absent")
        self.assertEqual(r.returncode, 69, (r.stdout, r.stderr))
        self.assertIn("install.ps1", r.stderr)
        self.assertEqual(self.request_files(), [])

    def test_every_client_line_is_in_the_log_format_with_one_run_id_and_type_logs_only_its_length(self):
        secret = "hunter2-SECRET"
        r = self.call("type", secret, AD_STUB_EXIT="0")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = self.box.log_lines()
        self.assertGreaterEqual(len(lines), 2, lines)
        ids = set()
        for l in lines:
            m = LOG_LINE.match(l)
            self.assertIsNotNone(m, "log line out of format: %r" % l)
            ids.add(m.group(1))
        self.assertEqual(len(ids), 1, "one call, one run id: %s" % ids)
        self.assertTrue(any("type length=%d" % len(secret) in l for l in lines), lines)
        self.assertFalse(any(secret in l for l in lines), "the typed text must not be in the log")


class ChainTest(BridgeBase):
    """install.ps1 registers the task; the stub runs that task's action for real as the worker."""

    def setUp(self):
        super().setUp()
        wt.release_files(self.box.release)
        r = self.box.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.script = self.box.bin / "agent-desktop.ps1"

    def chain(self, *args, **extra):
        return self.call(*args, mode="registered", **extra)

    def test_ui_goes_through_the_task_with_the_arguments_exit_code_and_output_unchanged(self):
        awkward = ["snapshot", "-i", "two words", "C:\\dir with space\\", 'q"uote', ""]
        self.box.set_ui_exit(3)
        r = self.chain("ui", *awkward, AGENT_DESKTOP_UI_BIN=str(self.box.ui_exe))
        self.assertEqual(r.returncode, 3, (r.stdout, r.stderr))
        self.assertEqual(r.stdout, "stub ui out\n")
        self.assertEqual(r.stderr, "stub ui err\n")
        self.assertEqual(self.box.ui_argv_lines(), [" " + " ".join("[%s]" % a for a in awkward)])

    def test_a_locked_screen_exits_1_with_a_message_and_never_an_empty_result(self):
        lock = self.box.start_fake_lock_screen()
        out = self.box.work / "out.png"
        for argv in (["shot", "out.png"], ["windows"], ["cursor"], ["move", "1", "2"], ["type", "abc"],
                     ["ui", "snapshot"]):
            with self.subTest(argv=argv):
                r = self.chain(*argv, AGENT_DESKTOP_UI_BIN=str(self.box.ui_exe))
                self.assertEqual(r.returncode, 1, (r.stdout, r.stderr))
                self.assertRegex(r.stderr, r"(?i)screen is locked")
                self.assertEqual(r.stdout, "", "a locked screen must print no blank result")
        self.assertFalse(out.exists() or (self.box.elsewhere / "out.png").exists(), "no screenshot file may be written")
        self.assertEqual(self.box.ui_argv_lines(), [], "Vercel's tool must not run on a locked screen")
        self.assertTrue(any("locked" in l for l in self.box.log_lines()))
        lock.kill()
        lock.wait()
        r = self.chain("ui", "snapshot", AGENT_DESKTOP_UI_BIN=str(self.box.ui_exe))
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertEqual(len(self.box.ui_argv_lines()), 1, "the same call works once the screen is unlocked")

    def test_both_sides_of_the_task_log_one_line_per_step_with_the_same_run_id(self):
        self.chain("ui", "snapshot", AGENT_DESKTOP_UI_BIN=str(self.box.ui_exe))
        lines = self.box.log_lines()
        parsed = [LOG_LINE.match(l) for l in lines]
        self.assertTrue(all(parsed), lines)
        self.assertEqual(len({m.group(1) for m in parsed}), 1, "client and worker share the run id: %s" % lines)
        steps = [m.group(2) for m in parsed]
        self.assertTrue(any(s.startswith("worker ") for s in steps), "the worker side logs: %s" % steps)
        self.assertTrue(any(not s.startswith("worker ") for s in steps), "the client side logs: %s" % steps)
        self.assertFalse(any("snapshot" in s and "[" in s for s in steps), "ui arguments may carry typed text and are not logged")

    def test_type_logs_only_its_length_on_both_sides_and_the_text_is_nowhere_else(self):
        secret = "hunter2-SECRET"
        r = self.chain("type", secret)
        self.assertEqual(r.returncode, 1, "user32 does not exist on Linux, so the worker reports a failure")
        lines = self.box.log_lines()
        marker = "type length=%d" % len(secret)
        self.assertTrue(any(marker in l and " worker " in l for l in lines), "worker side: %s" % lines)
        self.assertTrue(any(marker in l and " worker " not in l for l in lines), "client side: %s" % lines)
        everything = "\n".join(lines) + r.stdout + r.stderr
        self.assertNotIn(secret, everything)
        self.assertEqual(self.box.state_files(), ["agent-desktop.log"], "no request or answer may be left behind")

    def test_a_call_with_no_desktop_tools_exits_1_and_says_what_failed(self):
        r = self.chain("cursor")
        self.assertEqual(r.returncode, 1, (r.stdout, r.stderr))
        self.assertTrue(r.stderr.strip(), "the failure must come with a message")
        self.assertEqual(r.stdout, "")


class WorkerTest(BridgeBase):
    """The worker side alone: what it does with a request file it finds."""

    def setUp(self):
        super().setUp()
        wt.release_files(self.box.release)
        self.box.install()
        self.script = self.box.bin / "agent-desktop.ps1"
        self.dir = self.box.local / "agent-desktop"
        self.dir.mkdir(parents=True, exist_ok=True)

    def put_request(self, name, expires_in_seconds, action="ui", argv=("snapshot",)):
        ticks = 621355968000000000 + int((time.time() + expires_in_seconds) * 10_000_000)   # .NET ticks since year 1
        req = dict(id=name, action=action, argv=list(argv), cwd=str(self.box.work), ui_bin=str(self.box.ui_exe), expires=ticks)
        (self.dir / ("request-%s.json" % name)).write_text(json.dumps(req))

    def work(self):
        return self.box.run(self.script, "--worker", env=self.box.env())

    def test_the_worker_runs_a_live_request_and_writes_the_answer_the_client_reads(self):
        self.put_request("20260101T000000Z-1", 60)
        r = self.work()
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        answer = json.loads((self.dir / "answer-20260101T000000Z-1.json").read_text())
        self.assertEqual(answer["exit"], 0)
        self.assertEqual(answer["stdout"], "stub ui out\n")
        self.assertEqual(answer["stderr"], "stub ui err\n")
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith("request-")], [], "the request is consumed")

    def test_the_worker_drops_a_request_whose_client_has_given_up(self):
        self.put_request("20260101T000000Z-2", -5)
        r = self.work()
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertEqual(self.box.ui_argv_lines(), [], "an old request must never act")
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith(("request-", "answer-"))], [])

    def test_the_worker_with_nothing_to_do_exits_0(self):
        r = self.work()
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))


if __name__ == "__main__":
    unittest.main()
