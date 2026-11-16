"""c10: the G14 command hands each action to a scheduled task and waits for the answer.

Under PowerShell 7 on Linux, with a stub schtasks.exe (and a stub ScheduledTasks module for install.ps1) standing in for the real ones:
  * a bad call exits 2, prints the usage naming all eight actions and `ui`, and writes no request;
  * a good call writes a request, makes sure the task is running, prints the answer and exits with the answer's exit code (0 and 3);
  * the task is one long-lived worker: many calls start it once, a dead worker is replaced by the next call, and a worker whose
    script was replaced gives way to a new one. The client uses schtasks.exe and never the ScheduledTasks module (over a second
    to load on the G14, and the cause of the 3.6 s per call the first live run measured);
  * no answer in time: exit 1 with a message, the task is ended, and the request is withdrawn so a late run cannot act on it;
  * no task registered: exit 69;
  * the whole chain: the stub's `schtasks /Run` starts the action that install.ps1 registered, in a clean environment and
    another folder, as the real task does. That proves the lock check on every call, `ui` through the task, the shared run id in
    the log, and that `type` logs only its length, on both sides of the task.
`shot`, `windows`, `focus`, `move`, `click`, `type` and `key` call user32 and .NET drawing, which exist only on Windows, so
their effect on a screen is for the live run on the G14 (the worker's failure message on Linux is all these tests see).
Run: mise exec aqua:PowerShell/PowerShell@7.7.0 -- python3 -m unittest discover -s tests/agent-desktop -p test_windows_bridge.py
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import types
import unittest

import windows_testlib as wt
from windows_testlib import EIGHT, WINDOWS, Sandbox, WindowsTestCase

SCRIPT = WINDOWS / "agent-desktop.ps1"


def setUpModule():
    # Without the Windows script every bridge test would wait out its answer timeout one by one; fail once, at once.
    if not SCRIPT.is_file():
        raise RuntimeError(f"{SCRIPT} is missing: the Windows back end is not in this tree")
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

    exe_client = False   # True: the call goes through the compiled client (agent-desktop-client.cs) instead of agent-desktop.ps1

    def call(self, *args, mode="answer", cwd=None, **extra):
        script = self.script
        if self.exe_client:
            extra["AD_CLIENT_DLL"] = str(wt.client_dll())
            script = self.box.client_shim()
        env = self.box.env(AD_STUB_MODE=mode, **extra)
        return self.box.run(script, *args, env=env, cwd=cwd)

    script = SCRIPT

    def request_files(self):
        return [n for n in self.box.state_files() if n.startswith("request-")]

    def module_calls(self):
        return [c for c in self.box.calls() if c.startswith("module ")]


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

    def test_awkward_text_survives_the_request_and_the_answer(self):
        # the client writes and reads these files without ConvertTo-Json/ConvertFrom-Json (30 to 50 ms each on first use)
        awkward = 'q"uote back\\slash \\n tab\there\nline two \u00e9\u4e2d <>&\' \x01 end'
        r = self.call("type", awkward, AD_STUB_STDOUT=awkward + "\n", AD_STUB_STDERR="err " + awkward)
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        req = json.loads((self.box.state / "seen-request.json").read_text())
        self.assertEqual(req["argv"], [awkward])
        self.assertEqual(r.stdout, awkward + "\n")
        self.assertEqual(r.stderr, "err " + awkward)

    def test_a_large_answer_comes_back_whole(self):
        big = ("line of output with \"quotes\" and \\ slashes\n" * 2000)
        r = self.call("windows", AD_STUB_STDOUT=big)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, big)

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
        self.assertGreaterEqual(self.box.count_calls("schtasks /Run"), 1, "the task is started while the request waits")
        self.assertEqual(self.box.count_calls("schtasks /End"), 1, "a stuck worker is ended so the next call starts a fresh one")

    def test_no_task_registered_exits_69_and_names_the_install_script(self):
        r = self.call("cursor", mode="absent")
        self.assertEqual(r.returncode, 69, (r.stdout, r.stderr))
        self.assertIn("install.ps1", r.stderr)
        self.assertEqual(self.request_files(), [])

    def test_the_client_never_loads_the_scheduled_tasks_module(self):
        for mode in ("answer", "none", "absent"):
            self.call("cursor", mode=mode, AGENT_DESKTOP_TIMEOUT="1", AD_STUB_STDOUT="1 2\n")
        self.assertEqual(self.module_calls(), [], "the module takes over a second to load on the G14; schtasks.exe takes 40 ms")

    def test_the_task_is_started_when_the_request_is_not_taken_and_not_otherwise(self):
        self.call("cursor", mode="answer", AD_STUB_STDOUT="1 2\n")
        self.assertEqual(self.box.count_calls("schtasks /Run"), 1)

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
        lines = [l for l in self.box.log_lines() if not re.search(r" worker (started|native tools|exits|not started)", l)]   # the worker's own life is not part of a call
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
        self.assertEqual(self.box.state_files(), ["agent-desktop.log", "worker.lock"], "no request or answer may be left behind")

    def test_a_call_with_no_desktop_tools_exits_1_and_says_what_failed(self):
        r = self.chain("cursor")
        self.assertEqual(r.returncode, 1, (r.stdout, r.stderr))
        self.assertTrue(r.stderr.strip(), "the failure must come with a message")
        self.assertEqual(r.stdout, "")


    def ui(self):
        return self.chain("ui", "snapshot", AGENT_DESKTOP_UI_BIN=str(self.box.ui_exe))

    def test_many_calls_start_the_task_once_and_the_worker_stays_for_the_next_ones(self):
        installed_with = self.module_calls()   # install.ps1 may use the module; calls must not
        r = self.ui()
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        runs_after_first = self.box.count_calls("schtasks /Run")
        self.assertEqual(len(self.box.worker_pids()), 1)
        for n in range(4):
            r = self.ui()
            self.assertEqual(r.returncode, 0, (n, r.stdout, r.stderr))
        self.assertEqual(len(self.box.ui_argv_lines()), 5)
        self.assertEqual(self.box.count_calls("schtasks /Run"), runs_after_first, "a call that finds a running worker must not start the task")
        self.assertEqual(len(self.box.worker_pids()), 1, "one worker answered all five calls")
        self.assertEqual(self.module_calls(), installed_with, "no call may load the ScheduledTasks module")

    def test_the_worker_logs_how_long_each_request_waited_and_took_and_the_priority_it_runs_at(self):
        # the live N5 run needs this split to say where a slow click spent its time
        self.assertEqual(self.ui().returncode, 0)
        lines = self.box.log_lines()
        self.assertTrue(any(re.search(r" worker started pid=\d+ priority=\S+", l) for l in lines), lines)
        timing = [l for l in lines if re.search(r" worker timing queued=\d+ms action=\d+ms$", l)]
        self.assertEqual(len(timing), 1, lines)

    def test_a_dead_worker_is_replaced_by_the_next_call(self):
        self.assertEqual(self.ui().returncode, 0)
        for pid in self.box.live_workers():
            os.kill(pid, 9)
        self.box.wait_for("the worker to die", lambda: not self.box.live_workers())
        r = self.ui()
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertEqual(len(self.box.worker_pids()), 2, "the second call started a second worker")
        self.assertEqual(len(self.box.live_workers()), 1)

    def test_a_worker_whose_script_was_replaced_gives_way_to_a_new_one(self):
        self.assertEqual(self.ui().returncode, 0)
        old = self.box.live_workers()
        self.assertEqual(len(old), 1)
        with open(self.script, "a") as f:
            f.write("\n# a later version\n")
        r = self.ui()
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertEqual(len(self.box.worker_pids()), 2, "old code must never answer a call made after the script changed")
        self.box.wait_for("the old worker to be gone", lambda: old[0] not in self.box.live_workers())
        self.assertEqual(len(self.box.live_workers()), 1)

    def test_a_second_worker_exits_at_once_while_one_is_running(self):
        self.assertEqual(self.ui().returncode, 0)
        started = time.monotonic()
        r = self.box.run(self.script, "--worker", env=self.box.env(), timeout=60)
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertLess(time.monotonic() - started, 30)
        self.assertEqual(len(self.box.live_workers()), 1, "the first worker is untouched")
        self.assertEqual(self.ui().returncode, 0, "and still answers")


# The same calls through the compiled client: it is the command agents run, so it must do exactly what the PowerShell client does.
class BadCallExeTest(BadCallTest):
    exe_client = True


class RequestAnswerExeTest(RequestAnswerTest):
    exe_client = True

    def test_the_client_never_loads_the_scheduled_tasks_module(self):
        super().test_the_client_never_loads_the_scheduled_tasks_module()


class ChainExeTest(ChainTest):
    exe_client = True


class WorkerTest(BridgeBase):
    """The worker alone: started by hand in the background, as the task starts it, then given request files."""

    def setUp(self):
        super().setUp()
        wt.release_files(self.box.release)
        self.box.install()
        self.script = self.box.bin / "agent-desktop.ps1"
        self.dir = self.box.local / "agent-desktop"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.worker = None

    def start_worker(self):
        self.worker = subprocess.Popen([wt.pwsh(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(self.script), "--worker"],
                                       env=self.box.env(), cwd=str(self.box.elsewhere), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.box.processes.append(self.worker)
        self.box.wait_for("the worker to say it started", lambda: any("worker started" in l for l in self.box.log_lines()))
        return self.worker

    def put_request(self, name, expires_in_seconds, action="ui", argv=("snapshot",)):
        ticks = 621355968000000000 + int((time.time() + expires_in_seconds) * 10_000_000)   # .NET ticks since year 1
        req = dict(id=name, action=action, argv=list(argv), cwd=str(self.box.work), ui_bin=str(self.box.ui_exe), expires=ticks)
        tmp = self.dir / ("request-%s.tmp" % name)
        tmp.write_text(json.dumps(req))
        tmp.rename(self.dir / ("request-%s.json" % name))

    def answer(self, name, timeout=30):
        path = self.dir / ("answer-%s.json" % name)
        self.box.wait_for("the answer to " + name, path.exists, timeout)
        return json.loads(path.read_text())

    def test_the_worker_answers_a_live_request_and_stays_to_answer_the_next(self):
        w = self.start_worker()
        self.put_request("20260101T000000Z-1", 60)
        a = self.answer("20260101T000000Z-1")
        self.assertEqual((a["exit"], a["stdout"], a["stderr"]), (0, "stub ui out\n", "stub ui err\n"))
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith("request-")], [], "the request is consumed")
        self.assertIsNone(w.poll(), "the worker keeps running")
        self.put_request("20260101T000000Z-2", 60)
        self.answer("20260101T000000Z-2")
        self.assertEqual(len(self.box.ui_argv_lines()), 2)

    def test_the_worker_takes_a_request_that_arrived_before_it_started(self):
        self.put_request("20260101T000000Z-3", 60)
        self.start_worker()
        self.answer("20260101T000000Z-3")

    def test_the_worker_picks_up_a_request_quickly_while_idle(self):
        self.start_worker()
        time.sleep(1.5)   # idle: no request, no answer, no exit
        self.assertIsNone(self.worker.poll())
        started = time.monotonic()
        self.put_request("20260101T000000Z-4", 60)
        self.answer("20260101T000000Z-4")
        self.assertLess(time.monotonic() - started, 5, "an idle worker must answer within moments")

    def test_the_worker_drops_a_request_whose_client_has_given_up(self):
        self.start_worker()
        self.put_request("20260101T000000Z-5", -5)
        self.box.wait_for("the old request to be taken", lambda: not [n for n in os.listdir(self.dir) if n.startswith("request-")])
        self.put_request("20260101T000000Z-6", 60)   # a later live request proves the worker got past the old one
        self.answer("20260101T000000Z-6")
        self.assertEqual(len(self.box.ui_argv_lines()), 1, "an old request must never act")
        self.assertFalse((self.dir / "answer-20260101T000000Z-5.json").exists())


class LockAfterRowsTest(WindowsTestCase):
    """After the rows the driver locks the G14 with a one-off interactive task and keeps the proof (the lead's g14-lock.sh steps).
    The lock script runs here under PowerShell 7 with the stub ScheduledTasks module and a stub tasklist."""

    def setUp(self):
        super().setUp()
        self.box = Sandbox(self)
        spec = importlib.util.spec_from_file_location("live_run_for_lock", wt.REPO / "tests" / "agent-desktop" / "live_run.py")
        self.live = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.live)
        self.out = self.box.tmp / "proof"
        box = self.box

        class Dev:
            def ps(self_, script, timeout=120):
                f = box.tmp / "lock.ps1"
                f.write_text(script)
                r = box.run(f, env=box.env(AD_STUB_TASKLIST=box.tasklist_line), timeout=timeout)
                return types.SimpleNamespace(exit=r.returncode, out=r.stdout + r.stderr)

        self.dev = Dev()
        self.rec = types.SimpleNamespace(out=self.out)
        self.out.mkdir()
        self.box.tasklist_line = ""

    def lock(self, tasklist_line):
        self.box.tasklist_line = tasklist_line
        return self.live.g14_lock(self.rec, self.dev)

    def module_lines(self):
        return [c for c in self.box.calls() if c.startswith("module ") or c.startswith("Register-")]

    def test_it_runs_lockworkstation_in_a_one_off_interactive_task_and_removes_the_task(self):
        self.assertTrue(self.lock("LogonUI.exe                   1234 Console                    1     20,000 K"))
        self.assertEqual(self.module_lines(), ["Register-ScheduledTask rad-lock-once", "module Start-ScheduledTask rad-lock-once", "module Unregister-ScheduledTask rad-lock-once"])
        task = self.box.task()
        self.assertEqual(task["Actions"][0]["Execute"], "rundll32.exe")
        self.assertEqual(task["Actions"][0]["Arguments"], "user32.dll,LockWorkStation")
        self.assertEqual(str(task["Principal"]["LogonType"]), "Interactive", "it must run in the desktop session, not in the ssh session")
        self.assertEqual(task["Principal"]["UserId"], "G14\\michael")

    def test_the_proof_is_saved_in_the_output_folder(self):
        self.lock("LogonUI.exe                   1234 Console                    1     20,000 K")
        proof = (self.out / "lock-after-rows.txt").read_text()
        self.assertIn("LogonUI.exe", proof)
        self.assertIn("locked: LogonUI.exe is running in session 1", proof)

    def test_a_logonui_in_session_0_or_no_logonui_is_not_a_lock(self):
        for line, word in (("LogonUI.exe                   1234 Services                   0     20,000 K", "session 0"), ("", "no LogonUI")):
            with self.subTest(line=line):
                self.assertFalse(self.lock(line))
                self.assertIn("NOT LOCKED", (self.out / "lock-after-rows.txt").read_text())
                self.assertIn(word, (self.out / "lock-after-rows.txt").read_text())

    def test_the_dry_run_plan_names_the_lock_step(self):
        r = subprocess.run([sys.executable, "-I", str(wt.REPO / "tests" / "agent-desktop" / "live_run.py"), "g14", "--dry-run"], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("lock_after_rows", r.stdout)


if __name__ == "__main__":
    unittest.main()
