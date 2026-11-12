"""Black-box tests for dot_local/bin/executable_run-and-wake.

The real script runs as a real process and its job really detaches. Only herdr is scripted: a fake `herdr` first on PATH
answers `agent get` from files the test writes (one file per live pane, holding the session it shows), records every call,
and records each `agent prompt` it accepts. A fake `t3` does the same for `thread send` (argv and stdin). Everything is checked from outside: the launcher's output and exit code, the
prompts herdr received, and the job log, read back as the replay of each job.
"""
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
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


FAKE_T3 = r'''#!/usr/bin/env python3
import json, os, sys
fake = os.environ["FAKE"]
with open(os.path.join(fake, "t3_sends"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read()}) + "\n")
if os.path.exists(os.path.join(fake, "t3_error")):
    print("thread not found", file=sys.stderr)
    sys.exit(1)
'''

THREAD = "thread-7f3a"
CHILD = "thread:delegated-task:6c1e0a"  # a delegated child's thread: its wake also asks it to message its lead
CHILD_LINE = ("If this wake finishes your task or your next turn ends it, send your lead a short message (the thread id in your brief) "
              "before you end the turn: T3 does not notify a lead for runs woken this way (pingdotgg/t3code#33432; remove this line once that is fixed).")
# systemd-run, scripted. Off: no user manager (a CI runner, a kgate pod), so every call fails. Recording: logs argv, answers the
# probe, and does what `--scope` does (runs the command in place of itself).
FAKE_SYSTEMD_OFF = """#!/bin/sh
echo "systemd-run: Failed to connect to bus: No medium found" >&2
exit 1
"""
FAKE_SYSTEMD_SCOPE = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.path.join(os.environ["FAKE"], "systemd_run"), "a") as f:
    f.write(json.dumps(args) + "\n")
rest = args[args.index("--") + 1:]
if rest == ["true"]:
    sys.exit(0)
os.execvp(rest[0], rest)
'''
FAKE_TOKEN = "ops_fake-token-for-tests-only"  # a stand-in service-account token; never a real one


def user_scopes_work():
    """True where `systemd-run --user --scope` really starts a scope (the Linux desktop), as the script's own probe asks."""
    run = shutil.which("systemd-run")
    if not run or not sys.platform.startswith("linux"):
        return False
    try:
        return subprocess.run([run, "--user", "--scope", "--quiet", "--collect", "--", "true"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def scope_active(unit):
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit]).returncode == 0


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
        (self.bin / "t3").write_text(FAKE_T3)
        (self.bin / "t3").chmod(0o755)
        self.systemd_off = root / "systemd-off"  # first on PATH by default: a host with no user manager, whatever the real one is
        self.systemd_off.mkdir()
        (self.systemd_off / "systemd-run").write_text(FAKE_SYSTEMD_OFF)
        (self.systemd_off / "systemd-run").chmod(0o755)
        self.state = root / "state"
        self.log = self.state / "run-and-wake/log.jsonl"
        env = {k: v for k, v in os.environ.items() if k not in ("HERDR_PANE_ID", "PI_SESSION_FILE", "PI_SESSION_ID", "T3CODE_THREAD_ID", "T3CODE_CLI_PATH", "OP_SERVICE_ACCOUNT_TOKEN") and not k.startswith("HEAVY_GATE_")}
        self.op_home = root / "op-home"  # HOME with no token file, so the real ~/.config is never read
        self.op_home.mkdir()
        self.path = env["PATH"]
        self.env = {**env, "PATH": f"{self.systemd_off}:{self.bin}:{self.path}", "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
                    "HERDR_PANE_ID": PANE, "PI_SESSION_FILE": SESSION, "HOME": str(self.op_home)}
        self.show(PANE, SESSION)

    # --- the scripted herdr ---
    def show(self, pane, session):
        (self.fake / "panes" / pane).write_text(session + "\n")

    def close_pane(self, pane):
        (self.fake / "panes" / pane).unlink()

    def prompts(self):
        path = self.fake / "prompts"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def t3_sends(self):
        path = self.fake / "t3_sends"
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

    def token_file(self, token):
        path = self.op_home / ".config/agent-harness/op-service-token"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token + "\n")

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

    def test_the_job_gets_the_token_from_its_file_when_this_process_has_none(self):
        self.token_file(FAKE_TOKEN)
        probe = self.root / "probe"  # the job writes the token here: not to its output, so the job log holds none of it
        result = self.launch("--", "sh", "-c", f'printf %s "$OP_SERVICE_ACCOUNT_TOKEN" > {probe}')
        records = self.replay(self.job_id(result))
        self.assertEqual(probe.read_text(), FAKE_TOKEN)
        self.assertEqual(records[0]["op_token"], "file", "the replay says where the token came from, never its value")
        for text in (result.stdout, result.stderr, self.log.read_text(), Path(records[0]["output"]).read_text(), json.dumps(records)):
            self.assertNotIn(FAKE_TOKEN, text)

    def test_a_token_in_this_environment_is_passed_on_and_the_file_is_not_used(self):
        self.token_file(FAKE_TOKEN)
        probe = self.root / "probe"
        records = self.replay(self.job_id(self.launch("--", "sh", "-c", f'printf %s "$OP_SERVICE_ACCOUNT_TOKEN" > {probe}',
                                                       env={"OP_SERVICE_ACCOUNT_TOKEN": "ops_from-the-environment"})))
        self.assertEqual(probe.read_text(), "ops_from-the-environment")
        self.assertEqual(records[0]["op_token"], "env")
        self.assertNotIn(FAKE_TOKEN, json.dumps(records))

    def test_no_token_in_the_environment_or_the_file_means_the_job_has_none(self):
        probe = self.root / "probe"
        records = self.replay(self.job_id(self.launch("--", "sh", "-c", f'printf %s "${{OP_SERVICE_ACCOUNT_TOKEN-unset}}" > {probe}')))
        self.assertEqual(probe.read_text(), "unset")
        self.assertIsNone(records[0]["op_token"])
        self.assertEqual(records[-1]["event"], "wake")

    def test_the_job_sees_its_own_id_in_RUN_AND_WAKE_JOB(self):
        # kgate keys its record by it, so a record can be joined to this log by id
        out = self.root / "seen-id"
        job = self.job_id(self.launch("--", "sh", "-c", f'printf %s "$RUN_AND_WAKE_JOB" > {out}'))
        self.replay(job)
        self.assertEqual(out.read_text(), job)

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

    def test_a_session_swapped_at_the_send_is_logged_after_it(self):
        # This checks post-send logging only, not delivery isolation: the fake accepts the prompt, then swaps the pane's
        # session. Which session a check/send-race message lands in is not tested and not prevented: herdr's prompt names a
        # pane, not a session, and Michael accepted that window (ask #347).
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
        # record (the start record, written after the job starts and before the report) until the launcher is dead.
        self.log.parent.mkdir(parents=True)
        os.mkfifo(self.log)
        started, release = self.root / "started", self.root / "release"
        cmd = ["sh", "-c", f"touch {started}; while [ ! -f {release} ]; do sleep 0.05; done"]
        launcher = subprocess.Popen([sys.executable, str(SCRIPT), "--", *cmd], env=self.env, cwd=self.root,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        # Ready: the job runs, so the watcher has forked, left the launcher's session and started it. Its next step is the
        # start record, which blocks on the FIFO until a reader opens it; the report comes after that.
        deadline = time.monotonic() + 20
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(started.exists(), "the job started")
        self.assertIsNone(launcher.poll(), "the launcher is still waiting for the report")
        os.killpg(launcher.pid, signal.SIGKILL)
        launcher.wait()
        release.write_text("")
        records = []

        def drain():  # each record is one open, write, close by the watcher: read each to EOF, whole lines only
            while not (records and records[-1]["event"] in ("wake", "skip")):
                with open(self.log) as fifo:  # blocks until the watcher opens it for its next record
                    records.extend(json.loads(line) for line in fifo.read().splitlines())

        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        reader.join(20)
        self.assertFalse(reader.is_alive(), f"the watcher wrote a final record: {records}")
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
        for key, value in {**GATE_QUIET, "pressure": "4"}.items():  # memory pressure stays critical: the gate gives up
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

    # --- a T3 Code thread: no pane, the wake is one `t3 thread send` ---
    def t3_env(self, **extra):
        return {"HERDR_PANE_ID": "", "PI_SESSION_FILE": "", "T3CODE_THREAD_ID": THREAD, "T3CODE_CLI_PATH": str(self.bin / "t3"), **extra}

    def test_a_t3_thread_is_woken_with_the_same_text(self):
        result = self.launch("--", "sh", "-c", "sleep 1; echo job-output; exit 7", env=self.t3_env())
        job = self.job_id(result)
        self.assertIn(f"T3 thread {THREAD} gets one message tagged [run-and-wake k:{job}]", result.stdout)
        self.assertNotIn("WARN", result.stdout)
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[0]["thread"], records[0]["pane"]], [THREAD, None])
        self.assertEqual([records[-1]["target"], records[-1]["result"]], ["t3", "sent"])
        sends = self.t3_sends()
        self.assertEqual(len(sends), 1, "exactly one send")
        self.assertEqual(sends[0]["argv"], ["thread", "send", THREAD, "-"], "the message is read from stdin")
        text = sends[0]["stdin"]
        self.assertTrue(text.startswith(f"[run-and-wake k:{job}] job finished: exit 7 after 1s: "), text)
        self.assertIn("sh -c 'sleep 1; echo job-output; exit 7'", text)
        self.assertIn(f"Output: {records[0]['output']}", text)
        self.assertEqual(self.calls(), [], "herdr is not called")

    def test_the_t3_cli_defaults_to_the_one_in_home(self):
        home = self.root / "home"
        (home / ".t3/bin").mkdir(parents=True)
        (home / ".t3/bin/t3").symlink_to(self.bin / "t3")
        env = self.t3_env(HOME=str(home), T3CODE_CLI_PATH="")
        records = self.replay(self.job_id(self.launch("--", "true", env=env)))
        self.assertEqual([records[-1]["target"], records[-1]["result"]], ["t3", "sent"])
        self.assertEqual(len(self.t3_sends()), 1)

    def test_a_failed_t3_send_is_logged_and_not_retried(self):
        (self.fake / "t3_error").write_text("")
        records = self.replay(self.job_id(self.launch("--", "true", env=self.t3_env())))
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[-1]["target"], records[-1]["result"]], ["t3", "failed"])
        self.assertEqual(records[-1]["error"], "exit 1: thread not found")
        time.sleep(1)
        self.assertEqual(len(self.t3_sends()), 1, "one attempt per job")

    def test_a_missing_t3_cli_is_logged_as_a_failed_wake(self):
        records = self.replay(self.job_id(self.launch("--", "true", env=self.t3_env(T3CODE_CLI_PATH=str(self.root / "nope")))))
        self.assertEqual([records[-1]["target"], records[-1]["result"]], ["t3", "failed"])
        self.assertIn("t3-missing", records[-1]["error"])

    def test_a_pane_with_its_pi_session_wins_over_a_thread(self):
        # Pi sets the pane and session on each bash call; the thread id may only be inherited from the app that started the shell.
        job = self.job_id(self.launch("--", "true", env={"T3CODE_THREAD_ID": THREAD, "T3CODE_CLI_PATH": str(self.bin / "t3")}))
        records = self.replay(job)
        self.assertEqual([records[-1]["target"], records[-1]["result"]], ["herdr", "sent"])
        self.assertEqual(len(self.prompts()), 1)
        self.assertEqual(self.t3_sends(), [], "the thread is not messaged as well")

    def test_a_pane_without_a_pi_session_does_not_hide_the_thread(self):
        records = self.replay(self.job_id(self.launch("--", "true", env=self.t3_env(HERDR_PANE_ID=PANE))))
        self.assertEqual([records[-1]["target"], records[-1]["result"]], ["t3", "sent"])
        self.assertEqual(self.calls(), [])

    def test_a_delegated_child_thread_is_asked_to_message_its_lead(self):
        # T3 does not notify a lead when a child's run is woken by `t3 thread send` (pingdotgg/t3code#33432): the wake asks the child to.
        records = self.replay(self.job_id(self.launch("--", "true", env=self.t3_env(T3CODE_THREAD_ID=CHILD))))
        self.assertEqual([records[0]["thread"], records[-1]["target"], records[-1]["result"]], [CHILD, "t3", "sent"])
        sends = self.t3_sends()
        self.assertEqual([s["argv"] for s in sends], [["thread", "send", CHILD, "-"]])
        job = records[0]["job"]
        wake_text = f"[run-and-wake k:{job}] job finished: exit 0 after 0s: true. Output: {records[0]['output']}"
        self.assertEqual(sends[0]["stdin"], f"{wake_text}\n{CHILD_LINE}", "the same wake text, then one line asking the child to message its lead")

    def test_any_other_thread_gets_the_wake_text_unchanged(self):
        records = self.replay(self.job_id(self.launch("--", "true", env=self.t3_env())))
        job = records[0]["job"]
        self.assertEqual([s["stdin"] for s in self.t3_sends()],
                         [f"[run-and-wake k:{job}] job finished: exit 0 after 0s: true. Output: {records[0]['output']}"])

    def test_the_pi_path_is_unchanged_for_a_delegated_child(self):
        # a pane with its Pi session wins over the thread, so the child line must not reach herdr either
        env = {"T3CODE_THREAD_ID": CHILD, "T3CODE_CLI_PATH": str(self.bin / "t3")}
        records = self.replay(self.job_id(self.launch("--", "true", env=env)))
        self.assertEqual([records[-1]["target"], records[-1]["result"]], ["herdr", "sent"])
        job = records[0]["job"]
        self.assertEqual([p["text"] for p in self.prompts()],
                         [f"[run-and-wake k:{job}] job finished: exit 0 after 0s: true. Output: {records[0]['output']}"])
        self.assertEqual(self.t3_sends(), [], "the thread is not messaged")

    # --- a job outlives the systemd scope of the session that started it (T3 stops a Claude session's scope, killing its cgroup) ---
    def scope_env(self):
        (self.root / "systemd-scope").mkdir()
        (self.root / "systemd-scope/systemd-run").write_text(FAKE_SYSTEMD_SCOPE)
        (self.root / "systemd-scope/systemd-run").chmod(0o755)
        return {"PATH": f"{self.root / 'systemd-scope'}:{self.bin}:{self.path}"}

    def systemd_calls(self):
        path = self.fake / "systemd_run"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_with_a_user_manager_the_job_runs_in_its_own_scope(self):
        result = self.launch("--", "sh", "-c", "echo $PWD > seen; echo $T3CODE_THREAD_ID >> seen", env={**self.scope_env(), **self.t3_env()})
        job = self.job_id(result)
        records = self.replay(job)
        probe, scoped = self.systemd_calls()
        self.assertEqual(probe, ["--user", "--scope", "--quiet", "--collect", "--", "true"], "it asks first, as an exec cannot fall back")
        self.assertEqual(scoped[:4], ["--user", "--scope", "--quiet", "--collect"])
        self.assertEqual(scoped[4], f"--unit=run-and-wake-{job}", "the scope is named after the job")
        self.assertEqual(scoped[scoped.index("--") + 3 :], ["--scoped", job, "sh", "-c", "echo $PWD > seen; echo $T3CODE_THREAD_ID >> seen"])
        self.assertEqual(records[0]["scope"], f"run-and-wake-{job}.scope", "the start record names the scope")
        self.assertIn(f"scope run-and-wake-{job}.scope", result.stdout)
        self.assertEqual((self.root / "seen").read_text().split(), [str(self.root), THREAD], "cwd and environment carry into the scope")
        self.assertEqual(len(self.t3_sends()), 1, "one wake, as before")

    def test_a_scoped_launch_is_one_launch_with_one_job_id(self):
        job = self.job_id(self.launch("--", "true", env=self.scope_env()))
        self.replay(job)
        self.assertEqual(len([line for line in self.log.read_text().splitlines() if '"start"' in line]), 1)

    def test_without_a_user_manager_the_job_runs_as_before(self):
        # systemd-run exists but cannot start a scope (a CI runner, a kgate pod): the probe fails and nothing is exec'd
        job = self.job_id(self.launch("--", "true"))
        records = self.replay(job)
        self.assertIsNone(records[0]["scope"])
        self.assertEqual([r["event"] for r in records], ["start", "end", "wake"])

    def test_without_systemd_run_the_job_runs_as_before(self):
        # the work Mac: no systemd-run on PATH at all
        bare = self.root / "bare"
        bare.mkdir()
        for name in ("python3", "sh", "sleep", "true"):
            (bare / name).symlink_to(shutil.which(name))
        for name in ("herdr", "t3"):
            (bare / name).symlink_to(self.bin / name)
        result = self.launch("--", "true", env={"PATH": str(bare)})
        records = self.replay(self.job_id(result))
        self.assertIsNone(records[0]["scope"])
        self.assertNotIn("scope run-and-wake", result.stdout)
        self.assertEqual([r["event"] for r in records], ["start", "end", "wake"])

    @unittest.skipUnless(user_scopes_work(), "needs a systemd user manager (not a CI runner or the work Mac); the live proof covers it")
    def test_the_job_finishes_and_wakes_after_the_session_scope_is_stopped(self):
        # The real thing, with a scope of our own standing in for T3's t3code-claude-<id>.scope. A holder keeps it populated
        # so the stop has something to kill, as T3's does.
        outer = f"raw-test-outer-{secrets.token_hex(3)}"
        cmd, release = self.held_job()
        inner = ["python3", str(SCRIPT), "--", *cmd]
        env = {**self.env, "PATH": f"{self.bin}:{self.path}"}  # the real systemd-run
        holder = subprocess.Popen(["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit={outer}", "--", "sh", "-c",
                                   'python3 "$0" "$@"; exec sleep 600', str(SCRIPT), "--", *cmd],
                                  env=env, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.addCleanup(lambda: subprocess.run(["systemctl", "--user", "stop", f"{outer}.scope"], capture_output=True))
        self.addCleanup(holder.wait)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (self.log.exists() and self.log.read_text()):
            time.sleep(0.05)
        self.assertTrue(self.log.exists(), "the job started")
        job = json.loads(self.log.read_text().splitlines()[0])["job"]
        self.addCleanup(lambda: (release.write_text(""), subprocess.run(["systemctl", "--user", "stop", f"run-and-wake-{job}.scope"], capture_output=True)))
        self.assertTrue(scope_active(f"{outer}.scope"))
        subprocess.run(["systemctl", "--user", "stop", f"{outer}.scope"], check=True)  # what T3 does when it releases the session
        self.assertFalse(scope_active(f"{outer}.scope"), "the session's scope is gone")
        release.write_text("")
        records = self.replay(job, timeout=8)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual(records[1]["exit"], 0, "the job ran to its end after the session's scope was stopped")
        self.assertEqual(len(self.prompts()), 1)

    # --- a stop that signals the watcher as well as the job ---
    def watcher_of(self, result):
        pid = int(result.stdout.split(", pid ")[1].split(",")[0])
        with open(f"/proc/{pid}/stat") as stat:
            return pid, int(stat.read().rsplit(")", 1)[1].split()[1])  # the job's parent is the watcher

    @unittest.skipUnless(os.path.isdir("/proc"), "reads the watcher's pid from /proc")
    def test_a_signal_to_the_whole_group_still_ends_in_an_end_record_and_a_wake(self):
        cmd, _ = self.held_job()
        result = self.launch("--", *cmd)
        job = self.job_id(result)
        _, watcher = self.watcher_of(result)
        os.killpg(watcher, signal.SIGTERM)  # the watcher is its session's leader: this is the job and the watcher together
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[1]["exit"], records[1]["signal"]], [None, "SIGTERM"])
        self.assertIn("job finished: killed by SIGTERM", self.prompts()[0]["text"])

    @unittest.skipUnless(os.path.isdir("/proc"), "reads the watcher's pid from /proc")
    def test_a_signal_to_the_watcher_alone_is_passed_to_the_job(self):
        cmd, _ = self.held_job()
        result = self.launch("--", *cmd)
        job = self.job_id(result)
        _, watcher = self.watcher_of(result)
        os.kill(watcher, signal.SIGHUP)
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[1]["exit"], records[1]["signal"]], [None, "SIGHUP"])

    def test_the_job_does_not_inherit_the_watchers_signal_handling(self):
        # the watcher must not ignore TERM/HUP/INT for its job (SIG_IGN would survive exec)
        seen = self.root / "seen"
        probe = ("import signal; print([signal.getsignal(s) is signal.SIG_IGN for s in "
                 f"(signal.SIGTERM, signal.SIGHUP, signal.SIGINT)], file=open({str(seen)!r}, 'w'))")
        job = self.job_id(self.launch("--", sys.executable, "-c", probe))
        self.replay(job)
        self.assertEqual(seen.read_text().strip(), "[False, False, False]")

    def test_a_job_killed_with_sigkill_gets_an_end_record_with_the_signal(self):
        cmd, _ = self.held_job()
        result = self.launch("--", *cmd)
        job = self.job_id(result)
        os.kill(int(result.stdout.split(", pid ")[1].split(",")[0]), signal.SIGKILL)
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[1]["exit"], records[1]["signal"]], [None, "SIGKILL"])
        self.assertIn("job finished: killed by SIGKILL", self.prompts()[0]["text"])

    def test_usage(self):
        for args in ([], ["--"], ["--log", "x", "--", "true"]):
            with self.subTest(args=args):
                result = self.launch(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Usage: run-and-wake", result.stderr)
        self.assertFalse(self.log.exists(), "no job was started")


if __name__ == "__main__":
    unittest.main()
