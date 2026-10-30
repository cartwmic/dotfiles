"""Black-box tests for dot_local/bin/executable_run-and-wake.

The real script runs as a real process and its job really detaches. Only herdr is scripted: a fake `herdr` first on PATH
answers `agent get` from files the test writes (one file per live pane, holding the session it shows), records every call,
and records each `agent prompt` it accepts. Everything is checked from outside: the launcher's output and exit code, the
prompts herdr received, and the job log, read back as the replay of each job.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("RUN_AND_WAKE_SCRIPT") or ROOT / "dot_local/bin/executable_run-and-wake")
HEAVY_GATE = ROOT / "dot_local/bin/executable_heavy-gate"
sys.path.insert(0, str(ROOT / "tests/heavy-gate"))
from test_heavy_gate import FAKES as GATE_FAKES, QUIET as GATE_QUIET  # noqa: E402  (the gate's scripted host figures)

PANE = "w1A:p5"
SESSION = "/sessions/launching.jsonl"

FAKE_HERDR = r'''#!/usr/bin/env python3
import json, os, sys, time
fake = os.environ["FAKE"]
args = sys.argv[1:]
with open(os.path.join(fake, "calls"), "a") as f:
    f.write(json.dumps(args) + "\n")
def fail(code, message):
    print(json.dumps({"error": {"code": code, "message": message}, "id": "cli:agent:" + args[1]}), file=sys.stderr)
    sys.exit(1)
verb, pane = args[1], args[2]
panefile = os.path.join(fake, "panes", pane)
if not os.path.exists(panefile):
    fail("agent_not_found", f"agent target {pane} not found")
status_file = os.path.join(fake, "status")
if verb == "get":
    status = open(status_file).read().strip() if os.path.exists(status_file) else "idle"
    session = open(panefile).read().strip()
    print(json.dumps({"id": "cli:agent:get", "result": {"type": "agent_info", "agent": {
        "pane_id": pane, "agent": "pi", "agent_status": status,
        "agent_session": {"agent": "pi", "kind": "path", "source": "herdr:pi", "value": session}}}}))
elif verb == "wait":
    if os.path.exists(os.path.join(fake, "wait_error")):
        fail("server_unavailable", "herdr server went away")
    time.sleep(0.5)  # the dialog closes
    open(status_file, "w").write("idle\n")
    print(json.dumps({"id": "cli:agent:wait", "result": {"type": "agent_status", "status": "idle"}}))
elif verb == "prompt":
    if os.path.exists(os.path.join(fake, "prompt_error")):
        fail("agent_blocked", "agent is blocked")
    with open(os.path.join(fake, "prompts"), "a") as f:
        f.write(json.dumps({"pane": pane, "text": args[3]}) + "\n")
    swap = os.path.join(fake, "swap_on_prompt")  # /new lands between the check and the send
    if os.path.exists(swap):
        open(panefile, "w").write(open(swap).read())
    print(json.dumps({"id": "cli:agent:prompt", "result": {"type": "ok"}}))
'''


class RunAndWake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.root = root
        self.fake = root / "fake"
        (self.fake / "panes").mkdir(parents=True)
        self.bin = root / "bin"
        self.bin.mkdir()
        (self.bin / "herdr").write_text(FAKE_HERDR)
        (self.bin / "herdr").chmod(0o755)
        self.state = root / "state"
        self.log = self.state / "run-and-wake/log.jsonl"
        env = {k: v for k, v in os.environ.items() if k not in ("HERDR_PANE_ID", "PI_SESSION_FILE", "PI_SESSION_ID") and not k.startswith("HEAVY_GATE_")}
        self.env = {**env, "PATH": f"{self.bin}:{env['PATH']}", "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
                    "HERDR_PANE_ID": PANE, "PI_SESSION_FILE": SESSION}
        self.show(PANE, SESSION)

    # --- the scripted herdr ---
    def show(self, pane, session):
        (self.fake / "panes" / pane).write_text(session + "\n")

    def close_pane(self, pane):
        (self.fake / "panes" / pane).unlink()

    def prompts(self):
        path = self.fake / "prompts"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def calls(self):
        path = self.fake / "calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    # --- the script ---
    def launch(self, *cmd, env=None):
        started = time.monotonic()
        result = subprocess.run([sys.executable, str(SCRIPT), *cmd], env={**self.env, **(env or {})}, cwd=self.root,
                                text=True, capture_output=True, timeout=20)
        result.seconds = time.monotonic() - started
        return result

    def job_id(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        line = next(line for line in result.stdout.splitlines() if " job " in line)
        return line.split(" job ")[1].split()[0]

    def replay(self, job, timeout=20):
        """The job's records from the log alone, once it has a final wake or skip record."""
        mine = []
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            records = [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []
            mine = [r for r in records if r["job"] == job]
            if mine and mine[-1]["event"] in ("wake", "skip"):
                return mine
            time.sleep(0.05)
        self.fail(f"job {job} has no final record: {mine}")

    def held_job(self, name="release"):
        """A job that runs until the test releases it."""
        release = self.root / name
        return ["sh", "-c", f"while [ ! -f {release} ]; do sleep 0.05; done; echo released"], release

    def assertReplay(self, records, *events):
        self.assertEqual([r["event"] for r in records], list(events))
        for r in records:
            self.assertRegex(r["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$", "UTC time on every record")

    # --- the journey ---
    def test_returns_at_once_then_wakes_the_launching_session_once(self):
        result = self.launch("--", "sh", "-c", "sleep 2; echo job-output; exit 7")
        self.assertLess(result.seconds, 1.5, "the launching call returns at once, while the job still runs")
        job = self.job_id(result)
        self.assertIn(f"tagged [run-and-wake k:{job}]; you can end your turn", result.stdout)
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        start, end, wake = records
        self.assertEqual(start["cmd"], ["sh", "-c", "sleep 2; echo job-output; exit 7"])
        self.assertEqual([start["pane"], start["session"], start["cwd"]], [PANE, SESSION, os.path.realpath(self.root)])
        self.assertIsInstance(start["pid"], int)
        self.assertEqual([end["exit"], end["signal"]], [7, None])
        self.assertGreaterEqual(end["duration_s"], 2)
        self.assertEqual(wake["result"], "sent")
        self.assertEqual(Path(start["output"]).read_text(), "job-output\n", "the job's output is in its output file")
        prompts = self.prompts()
        self.assertEqual(len(prompts), 1, "exactly one prompt")
        self.assertEqual(prompts[0]["pane"], PANE)
        text = prompts[0]["text"]
        self.assertTrue(text.startswith(f"[run-and-wake k:{job}] job finished: exit 7 after 2s: "), text)
        self.assertIn("sh -c 'sleep 2; echo job-output; exit 7'", text)
        self.assertIn(f"Output: {start['output']}", text)
        self.assertNotIn("\n", text, "one line, so it is submitted whole")
        time.sleep(1)
        self.assertEqual(len(self.prompts()), 1, "and never a second one")

    def test_exit_statuses_reach_the_session(self):
        cases = [(["true"], "exit 0", {"exit": 0, "signal": None}),
                 (["sh", "-c", "exit 75"], "exit 75", {"exit": 75, "signal": None}),
                 (["no-such-command-xyz"], "could not start", {"exit": 127})]
        for cmd, said, end in cases:
            with self.subTest(cmd=cmd):
                job = self.job_id(self.launch("--", *cmd))
                records = self.replay(job)
                self.assertReplay(records, "start", "end", "wake")
                self.assertEqual({k: records[1][k] for k in end}, end)
                text = next(p["text"] for p in self.prompts() if f"k:{job}]" in p["text"])
                self.assertIn(f"job finished: {said}", text)

    def test_a_killed_job_still_wakes(self):
        cmd, _ = self.held_job()
        result = self.launch("--", *cmd)
        job = self.job_id(result)
        pid = int(result.stdout.split(", pid ")[1].split(",")[0])
        os.kill(pid, signal.SIGTERM)
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[1]["exit"], records[1]["signal"]], [None, "SIGTERM"])
        self.assertIn("job finished: killed by SIGTERM", self.prompts()[0]["text"])

    def test_the_job_outlives_the_launching_process_group(self):
        # Pi ends a bash call by SIGKILLing its process group; the job must not die with it.
        cmd, release = self.held_job()
        shell = subprocess.Popen(["sh", "-c", f'{sys.executable} "$0" "$@"; sleep 60', str(SCRIPT), "--", *cmd], env=self.env, cwd=self.root,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.addCleanup(shell.wait)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (self.log.exists() and self.log.read_text()):
            time.sleep(0.05)
        job = json.loads(self.log.read_text().splitlines()[0])["job"]
        os.killpg(shell.pid, signal.SIGKILL)
        release.write_text("")
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual(records[1]["exit"], 0, "the job ran to its end after the launcher's group was killed")

    # --- seeded faults ---
    def test_pane_gone(self):
        cmd, release = self.held_job()
        job = self.job_id(self.launch("--", *cmd))
        self.close_pane(PANE)
        release.write_text("")
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "skip")
        self.assertEqual(records[-1]["reason"], "pane-gone")
        self.assertEqual(self.prompts(), [], "nothing is sent")

    def test_session_changed(self):
        cmd, release = self.held_job()
        job = self.job_id(self.launch("--", *cmd))
        self.show(PANE, "/sessions/after-new.jsonl")  # /new or a resume in the same pane
        release.write_text("")
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "skip")
        self.assertEqual([records[-1]["reason"], records[-1]["detail"]], ["session-changed", "/sessions/after-new.jsonl"])
        self.assertEqual(self.prompts(), [], "nothing is sent")

    def test_no_pane_says_so_at_launch_and_calls_no_herdr(self):
        result = self.launch("--", "true", env={"HERDR_PANE_ID": ""})
        self.assertIn("WARN: no HERDR_PANE_ID: nothing will wake you", result.stdout)
        records = self.replay(self.job_id(result))
        self.assertEqual(records[-1]["reason"], "no-pane")
        self.assertEqual(self.calls(), [])

    def test_no_pi_session_says_so_at_launch(self):
        result = self.launch("--", "true", env={"PI_SESSION_FILE": ""})
        self.assertIn("WARN: no PI_SESSION_FILE: nothing will wake you", result.stdout)
        self.assertEqual(self.replay(self.job_id(result))[-1]["reason"], "no-session")
        self.assertEqual(self.calls(), [])

    def test_blocked_pane_is_waited_out_then_sent_once(self):
        (self.fake / "status").write_text("blocked\n")
        records = self.replay(self.job_id(self.launch("--", "true")))
        self.assertReplay(records, "start", "end", "blocked", "wake")
        self.assertEqual(records[-1]["result"], "sent")
        calls = self.calls()
        self.assertEqual([c[1] for c in calls], ["get", "wait", "get", "prompt", "get"])
        self.assertNotIn("blocked", calls[1], "the wait ends on any state but blocked")
        self.assertEqual(len(self.prompts()), 1)

    def test_a_failed_wait_ends_the_wake_with_its_error(self):
        (self.fake / "status").write_text("blocked\n")
        (self.fake / "wait_error").write_text("")
        records = self.replay(self.job_id(self.launch("--", "true")))
        self.assertReplay(records, "start", "end", "blocked", "skip")
        self.assertEqual([records[-1]["reason"], records[-1]["detail"]], ["herdr-error", "server_unavailable: herdr server went away"])
        time.sleep(1)
        self.assertEqual([c[1] for c in self.calls()], ["get", "wait"], "no retry loop, no prompt")

    def test_a_session_swapped_during_the_send_shows_in_the_log(self):
        # herdr's prompt names a pane, not a session; a /new between the check and the send cannot be refused, only seen
        (self.fake / "swap_on_prompt").write_text("/sessions/after-new.jsonl\n")
        records = self.replay(self.job_id(self.launch("--", "true")))
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[-1]["result"], records[-1]["session_after"]], ["sent", "/sessions/after-new.jsonl"])

    def test_a_normal_send_logs_no_session_after(self):
        records = self.replay(self.job_id(self.launch("--", "true")))
        self.assertNotIn("session_after", records[-1])

    def test_the_watcher_survives_the_launcher_dying_before_it_reports(self):
        # The watcher tells the launcher the job's pid. If Pi has already killed the launcher's process group, that report
        # fails; the job must still be watched to its end and woken. The log is a FIFO so the watcher is held at its first
        # record, before the report, until the launcher is dead.
        self.log.parent.mkdir(parents=True)
        os.mkfifo(self.log)
        cmd, release = self.held_job()
        launcher = subprocess.Popen([sys.executable, str(SCRIPT), "--", *cmd], env=self.env, cwd=self.root,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1)
        self.assertIsNone(launcher.poll(), "the launcher is still waiting for the report")
        os.killpg(launcher.pid, signal.SIGKILL)
        launcher.wait()
        release.write_text("")
        records = []
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not (records and records[-1]["event"] in ("wake", "skip")):
            fd = os.open(self.log, os.O_RDONLY | os.O_NONBLOCK)
            with os.fdopen(fd) as fifo:
                time.sleep(0.1)
                records += [json.loads(line) for line in fifo.read().splitlines()]
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual(records[1]["exit"], 0)
        self.assertEqual(len(self.prompts()), 1)

    def test_a_refused_prompt_is_logged_and_not_retried(self):
        (self.fake / "prompt_error").write_text("")
        records = self.replay(self.job_id(self.launch("--", "true")))
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[-1]["result"], records[-1]["error"]], ["failed", "agent_blocked: agent is blocked"])
        time.sleep(1)
        self.assertEqual([c[1] for c in self.calls()].count("prompt"), 1, "one attempt per job")

    def test_composes_with_heavy_gate_and_its_give_up_status(self):
        for name, body in GATE_FAKES.items():
            (self.bin / name).write_text(f"#!/bin/sh\n{body}\n")
            (self.bin / name).chmod(0o755)
        (self.bin / "heavy-gate").symlink_to(HEAVY_GATE)
        for key, value in {**GATE_QUIET, "pressure": "2"}.items():  # memory pressure stays up: the gate gives up
            (self.fake / key).write_text(value + "\n")
        gate_env = {"HEAVY_GATE_LOCK": str(self.root / "gate.lock"), "HEAVY_GATE_PRIORITIES": str(self.root / "priorities"),
                    "HEAVY_GATE_SLOTS_FILE": str(self.root / "slots"), "HEAVY_GATE_CHECK_WINDOW": "1", "HEAVY_GATE_POLL": "1",
                    "WORKSTREAM_RANK_FILE": str(self.root / "rank")}
        result = self.launch("--", "heavy-gate", "--wait", "1", "--", "echo", "never-runs", env=gate_env)
        self.assertLess(result.seconds, 1.5)
        records = self.replay(self.job_id(result), timeout=60)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual(records[1]["exit"], 75)
        self.assertIn("job finished: exit 75", self.prompts()[0]["text"])
        output = Path(records[0]["output"]).read_text()
        self.assertIn("[heavy-gate] WARN: still refused", output, "the gate's own messages are in the job output")
        self.assertNotIn("never-runs", output.splitlines(), "the gated command never ran")

    def test_usage(self):
        for args in ([], ["--"], ["--log", "x", "--", "true"]):
            with self.subTest(args=args):
                result = self.launch(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Usage: run-and-wake", result.stderr)
        self.assertFalse(self.log.exists(), "no job was started")


if __name__ == "__main__":
    unittest.main()
