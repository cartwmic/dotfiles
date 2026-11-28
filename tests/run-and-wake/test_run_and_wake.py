"""Black-box tests for dot_local/bin/executable_run-and-wake.

The real script runs as a real process and its job really detaches. Only T3 is scripted: a fake `t3` first on PATH records each
`thread send` (argv and stdin) and can say the server is down or refuses the thread. Everything is checked from outside: the launcher's
output and exit code, the messages the fake `t3` received, and the job log, read back as the replay of each job.
"""
import fcntl
import importlib.machinery
import importlib.util
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
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("RUN_AND_WAKE_SCRIPT") or ROOT / "dot_local/bin/executable_run-and-wake")
HEAVY_GATE = ROOT / "dot_local/bin/executable_heavy-gate"
HOOK = ROOT / "dot_local/share/agent-harness/hooks/stop_running_jobs.py"  # the builder Stop hook, whose wait_hint the launcher's message must match
sys.path.insert(0, str(ROOT / "tests/heavy-gate"))
from test_heavy_gate import FAKES as GATE_FAKES, QUIET as GATE_QUIET  # noqa: E402  (the gate's scripted host figures)

FAKE_T3 = r'''#!/usr/bin/env python3
import json, os, sys
fake = os.environ["FAKE"]
if sys.argv[1:3] == ["thread", "show"]:
    # `thread show --json` is what the watcher asks before it wakes a thread: is it in a turn? Recorded apart from the sends. Answers, by file:
    # t3_show_fail (exit 1), t3_show_raw (printed as it is), t3_show_busy ("all", or how many more answers say a run is active), else idle.
    with open(os.path.join(fake, "t3_shows"), "a") as f:
        f.write(json.dumps(sys.argv[1:]) + "\n")
    if os.path.exists(os.path.join(fake, "t3_show_fail")):
        print("Could not reach the T3 Code server at http://127.0.0.1:3773. fetch failed", file=sys.stderr)
        sys.exit(1)
    if os.path.exists(os.path.join(fake, "t3_show_raw")):
        sys.stdout.write(open(os.path.join(fake, "t3_show_raw")).read())
        sys.exit(0)
    busy = os.path.join(fake, "t3_show_busy")
    left = open(busy).read().strip() if os.path.exists(busy) else "0"
    if left not in ("0", "all"):
        open(busy, "w").write(str(int(left) - 1))
    run = "run:thread:t:ordinal:1" if left != "0" else None
    print(json.dumps({"thread": {"threadId": sys.argv[-1], "status": "running" if run else "completed", "activeRunId": run, "latestRunId": "run:thread:t:ordinal:1"}, "messages": []}))
    sys.exit(0)
with open(os.path.join(fake, "t3_sends"), "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": sys.stdin.read()}) + "\n")
# The two answers the real CLI gives (probed 2026-11-15, t3 0.1.10-nightly.20261113.4643), both exit 1:
# no server (down: the file holds how many more calls fail, "all" until it is removed) and a server that refuses (t3_error: thread unknown).
down = os.path.join(fake, "t3_down")
if os.path.exists(down):
    left = open(down).read().strip()
    if left != "all":
        if int(left) <= 1:
            os.unlink(down)
        else:
            open(down, "w").write(str(int(left) - 1))
    print("Could not reach the T3 Code server at http://127.0.0.1:3773. fetch failed", file=sys.stderr)
    sys.exit(1)
if os.path.exists(os.path.join(fake, "t3_error")):
    print(f"Thread {sys.argv[3]} was not found.", file=sys.stderr)
    sys.exit(1)
'''

THREAD = "thread-7f3a"
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
assert "--expand-environment=no" in args, "without it systemd-run expands $VAR in the command (254-257, and always before 258 outside --scope)"
rest = args[args.index("--") + 1:]
if rest == ["true"]:
    sys.exit(0)
os.execvp(rest[0], rest)
'''
# systemctl, scripted for the slice check only: answers `show app-t3code-agents.slice --property=MemoryMax --value` from the file $FAKE/slice_memory_max.
FAKE_SYSTEMCTL = """#!/bin/sh
cat "$FAKE/slice_memory_max" 2>/dev/null || echo infinity
"""
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


def process_running(pid):
    """True while the process exists and is not a zombie. One that exits between the check and the read is gone: reading its stat then fails, and that is an answer, not an error."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def scope_active(unit):
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", unit]).returncode == 0


class RunAndWake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.wait_for_watchers)  # runs before the folder is removed: no watcher is left writing into it
        root = Path(self.tmp.name)
        self.root = root
        self.fake = root / "fake"
        self.fake.mkdir()
        self.bin = root / "bin"
        self.bin.mkdir()
        (self.bin / "t3").write_text(FAKE_T3)
        (self.bin / "t3").chmod(0o755)
        self.systemd_off = root / "systemd-off"  # first on PATH by default: a host with no user manager, whatever the real one is
        self.systemd_off.mkdir()
        (self.systemd_off / "systemd-run").write_text(FAKE_SYSTEMD_OFF)
        (self.systemd_off / "systemd-run").chmod(0o755)
        self.state = root / "state"
        self.log = self.state / "run-and-wake/log.jsonl"
        env = {k: v for k, v in os.environ.items() if k not in ("T3CODE_THREAD_ID", "T3CODE_CLI_PATH", "OP_SERVICE_ACCOUNT_TOKEN") and not k.startswith("HEAVY_GATE_")}
        self.op_home = root / "op-home"  # HOME with no token file, so the real ~/.config is never read
        self.op_home.mkdir()
        self.path = env["PATH"]
        self.env = {**env, "PATH": f"{self.systemd_off}:{self.bin}:{self.path}", "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
                    "T3CODE_THREAD_ID": THREAD, "T3CODE_CLI_PATH": str(self.bin / "t3"), "HOME": str(self.op_home),
                    "RUN_AND_WAKE_COALESCE": "0"}  # the merge window is off unless a test turns it on, so a lone wake goes out at once

    # --- the scripted t3 ---
    def t3_sends(self):
        path = self.fake / "t3_sends"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def texts(self):
        return [send["stdin"] for send in self.t3_sends()]

    def thread_in_a_turn(self, answer="all"):
        """The scripted thread is in a turn for `answer` more asks ("all": until leave_the_turn)."""
        (self.fake / "t3_show_busy").write_text(str(answer))

    def leave_the_turn(self):
        (self.fake / "t3_show_busy").unlink()

    def t3_shows(self):
        path = self.fake / "t3_shows"
        return path.read_text().splitlines() if path.exists() else []

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

    def wait_for_watchers(self, timeout=20):
        """Returns once no job's watcher is alive. A watcher holds jobs/<job>.lock until it has woken and removed it, and it is detached: the
        launching call returns while it still writes its records and runs the scripted t3. Removing the folder under it fails
        with "Directory not empty". Every test starts jobs, so this is the one place that waits for all of them."""
        end = time.monotonic() + timeout
        jobs = self.state / "run-and-wake/jobs"
        for lock in sorted(jobs.glob("*.lock")) if jobs.is_dir() else []:
            try:
                fd = os.open(lock, os.O_RDONLY)
            except FileNotFoundError:
                continue  # the watcher finished and removed it
            try:
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() > end:
                            self.fail(f"the watcher of {lock.stem} is still running after {timeout}s")
                        time.sleep(0.02)
            finally:
                os.close(fd)

    # --- the journey ---
    def test_returns_at_once_then_wakes_the_launching_session_once(self):
        result = self.launch("--", "sh", "-c", "sleep 2; echo job-output; exit 7")
        self.assertLess(result.seconds, 1.5, "the launching call returns at once, while the job still runs")
        job = self.job_id(result)
        self.assertIn(f"T3 thread {THREAD} gets one message tagged [run-and-wake k:{job}]", result.stdout)
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        start, end, wake = records
        self.assertEqual(start["cmd"], ["sh", "-c", "sleep 2; echo job-output; exit 7"])
        self.assertEqual([start["thread"], start["cwd"]], [THREAD, os.path.realpath(self.root)])
        self.assertNotIn("pane", start, "the start record no longer carries herdr fields")
        self.assertNotIn("session", start)
        self.assertIsInstance(start["pid"], int)
        self.assertEqual([end["exit"], end["signal"]], [7, None])
        self.assertGreaterEqual(end["duration_s"], 2)
        self.assertEqual(wake["result"], "sent")
        self.assertEqual(Path(start["output"]).read_text(), "job-output\n", "the job's output is in its output file")
        sends = self.t3_sends()
        self.assertEqual(len(sends), 1, "exactly one send")
        self.assertEqual(sends[0]["argv"], ["thread", "send", THREAD, "-"], "the message is read from stdin")
        text = sends[0]["stdin"]
        self.assertTrue(text.startswith(f"[run-and-wake k:{job}] job finished: exit 7 after 2s: "), text)
        self.assertIn("sh -c 'sleep 2; echo job-output; exit 7'", text)
        self.assertIn(f"Output: {start['output']}", text)
        self.assertNotIn("\n", text, "one line")
        time.sleep(1)
        self.assertEqual(len(self.t3_sends()), 1, "and never a second one")

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
                text = next(t for t in self.texts() if f"k:{job}]" in t)
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
        self.assertIn("job finished: killed by SIGTERM", self.texts()[0])

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
    NO_TARGET = {"T3CODE_THREAD_ID": ""}

    def test_no_thread_waits_for_the_job_and_prints_its_result(self):
        """A caller nothing can wake (a Pi child T3 runs: no thread) gets the result in the same call, not a lost wake."""
        result = self.launch("--", "sh", "-c", "exit 3", env=self.NO_TARGET)
        self.assertIn("WARN: no T3CODE_THREAD_ID: nothing could wake you", result.stdout)
        self.assertEqual(result.returncode, 3, "the launcher exits with the job's status")
        job = next(line for line in result.stdout.splitlines() if " job " in line).split(" job ")[1].split()[0]
        self.assertIn("[run-and-wake k:%s]" % job, result.stdout, "the line the wake would carry is printed")
        events = [json.loads(l)["event"] for l in self.log.read_text().splitlines() if json.loads(l)["job"] == job]
        self.assertEqual(events[:2], ["start", "end"], "the job had ended when the launcher returned")
        self.assertEqual(sorted(events[2:]), ["read", "skip"], "the watcher's skip and the launcher's read, in either order")
        self.assertEqual([r["reason"] for r in self.records_of(job) if r["event"] == "skip"], ["no-thread"])
        self.assertEqual(self.t3_sends(), [], "nobody is messaged")

    def test_a_waiting_launcher_killed_with_its_process_group_leaves_the_job_running(self):
        """A caller's tool timeout kills the waiting launcher (and its process group): the job must finish anyway, and --wait must still get it."""
        done = self.root / "done"
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "--", "sh", "-c", f"sleep 2; touch {done}"],
                                env={**self.env, **self.NO_TARGET}, cwd=self.root, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        lines = []
        while not any("--wait" in line for line in lines):      # the job id and the --wait command come before the wait starts
            line = proc.stdout.readline()
            self.assertTrue(line, "the launcher printed its job id and the --wait command before waiting")
            lines.append(line)
        job = next(line for line in lines if " job " in line).split(" job ")[1].split()[0]
        self.assertIn("run-and-wake --wait %s" % job, "".join(lines))
        os.killpg(proc.pid, signal.SIGKILL)                     # the whole group the launcher started in
        proc.wait(timeout=10)
        deadline = time.monotonic() + 15
        while not done.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(done.exists(), "the job ran to the end after its launcher's process group was killed")
        waited = subprocess.run([sys.executable, str(SCRIPT), "--wait", job], env={**self.env, **self.NO_TARGET}, cwd=self.root,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(waited.returncode, 0, waited.stderr)
        self.assertIn("[run-and-wake k:%s] job finished: exit 0" % job, waited.stdout)

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
        self.assertEqual(len(self.t3_sends()), 1)

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
        self.assertIn("job finished: exit 75", self.texts()[0])
        output = Path(records[0]["output"]).read_text()
        self.assertIn("[heavy-gate] WARN: still refused", output, "the gate's own messages are in the job output")
        self.assertNotIn("never-runs", output.splitlines(), "the gated command never ran")

    # --- the wake is one `t3 thread send` ---
    def t3_env(self, **extra):
        return {"T3CODE_THREAD_ID": THREAD, "T3CODE_CLI_PATH": str(self.bin / "t3"), **extra}

    def test_a_t3_thread_is_woken_with_the_same_text(self):
        result = self.launch("--", "sh", "-c", "sleep 1; echo job-output; exit 7", env=self.t3_env())
        job = self.job_id(result)
        self.assertIn(f"T3 thread {THREAD} gets one message tagged [run-and-wake k:{job}]", result.stdout)
        self.assertNotIn("WARN", result.stdout)
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual(records[0]["thread"], THREAD)
        spec = importlib.util.spec_from_file_location("stop_running_jobs", HOOK)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        command = hook.run_and_wake_wait_hint(job).split("`")[1]  # the wait the Stop hook names for this job
        self.assertEqual(command, f"run-and-wake --wait {job}")
        self.assertIn(f"wait with `{command}` in Bash", result.stdout, "a builder is told to wait, with the hook's command")
        self.assertIn("t3_background_wait", result.stdout)
        self.assertEqual([records[-1]["target"], records[-1]["result"]], ["t3", "sent"])
        sends = self.t3_sends()
        self.assertEqual(len(sends), 1, "exactly one send")
        self.assertEqual(sends[0]["argv"], ["thread", "send", THREAD, "-"], "the message is read from stdin")
        text = sends[0]["stdin"]
        self.assertTrue(text.startswith(f"[run-and-wake k:{job}] job finished: exit 7 after 1s: "), text)
        self.assertIn("sh -c 'sleep 1; echo job-output; exit 7'", text)
        self.assertIn(f"Output: {records[0]['output']}", text)

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
        self.assertEqual(records[-1]["error"], f"exit 1: Thread {THREAD} was not found.", "the server answered and refused: that is not retried")
        time.sleep(1)
        self.assertEqual(len(self.t3_sends()), 1, "one attempt per job")

    def test_a_missing_t3_cli_is_logged_as_a_failed_wake(self):
        records = self.replay(self.job_id(self.launch("--", "true", env=self.t3_env(T3CODE_CLI_PATH=str(self.root / "nope")))))
        self.assertEqual([records[-1]["target"], records[-1]["result"]], ["t3", "failed"])
        self.assertIn("t3-missing", records[-1]["error"])

    def test_herdr_variables_in_the_environment_change_nothing(self):
        # Before herdr support was removed a pane with its Pi session won over the thread; now the thread is the only wake target.
        job = self.job_id(self.launch("--", "true", env={"HERDR_PANE_ID": "w1A:p5", "PI_SESSION_FILE": "/sessions/launching.jsonl"}))
        records = self.replay(job)
        self.assertEqual([records[-1]["target"], records[-1]["result"]], ["t3", "sent"])
        self.assertEqual([s["argv"][2] for s in self.t3_sends()], [THREAD])

    # --- a job outlives the systemd scope of the session that started it (T3 stops a Claude session's scope, killing its cgroup) ---
    def scope_env(self):
        (self.root / "systemd-scope").mkdir()
        (self.root / "systemd-scope/systemd-run").write_text(FAKE_SYSTEMD_SCOPE)
        (self.root / "systemd-scope/systemd-run").chmod(0o755)
        (self.root / "systemd-scope/systemctl").write_text(FAKE_SYSTEMCTL)
        (self.root / "systemd-scope/systemctl").chmod(0o755)
        (self.fake / "slice_memory_max").write_text("29139927040\n")  # T3 has set its agents slice's limit (the default for these tests)
        return {"PATH": f"{self.root / 'systemd-scope'}:{self.bin}:{self.path}"}

    def systemd_calls(self):
        path = self.fake / "systemd_run"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_with_a_user_manager_the_job_runs_in_its_own_scope(self):
        result = self.launch("--", "sh", "-c", "echo $PWD > seen; echo $T3CODE_THREAD_ID >> seen", env={**self.scope_env(), **self.t3_env()})
        job = self.job_id(result)
        records = self.replay(job)
        probe, scoped = self.systemd_calls()
        head = ["--user", "--scope", "--quiet", "--collect", "--expand-environment=no", "--property=OOMPolicy=continue", "--slice=app-t3code-agents.slice"]
        self.assertEqual(probe, [*head, "--", "true"], "it asks first, as an exec cannot fall back, with the same placement")
        self.assertEqual(scoped[:7], head, "T3's agents slice: its memory limit and CPU weight apply to the job")
        self.assertEqual(scoped[7], f"--unit=run-and-wake-{job}", "the scope is named after the job")
        self.assertEqual(scoped[scoped.index("--") + 3 :], ["--scoped", job, "sh", "-c", "echo $PWD > seen; echo $T3CODE_THREAD_ID >> seen"])  # as typed: systemd-run is told not to expand
        self.assertEqual(records[0]["scope"], f"run-and-wake-{job}.scope", "the start record names the scope")
        self.assertIn("slice", records[0], "and the slice the kernel put it in (read from /proc; the fake systemd-run puts nothing anywhere)")
        self.assertIn(f"scope run-and-wake-{job}.scope in ", result.stdout)
        self.assertEqual((self.root / "seen").read_text().split(), [str(self.root), THREAD], "cwd and environment carry into the scope")
        self.assertEqual(len(self.t3_sends()), 1, "one wake, as before")

    def memory_limit_args(self, args):
        return sorted(a for a in args if a.startswith(("--property=Memory", "--slice")))

    def test_the_scope_goes_in_the_agents_slice_only_when_that_slice_has_a_memory_limit(self):
        env = self.scope_env()
        (self.fake / "slice_memory_max").write_text("infinity\n")  # T3 has not run since boot: the slice is absent or unlimited
        self.replay(self.job_id(self.launch("--", "true", env=env)))
        probe, scoped = self.systemd_calls()
        for call in (probe, scoped):
            limits = self.memory_limit_args(call)
            self.assertEqual([a.rsplit("=", 1)[0] for a in limits], ["--property=MemoryHigh", "--property=MemoryMax"], "no agents slice: the limits go on the scope")
            high, top = (int(a.rsplit("=", 1)[1]) for a in limits)
            self.assertTrue(0 < high <= top < 1 << 50)
        self.assertEqual(self.memory_limit_args(probe), self.memory_limit_args(scoped), "the probe asks for what the exec will use")

    def test_no_systemctl_means_the_scope_carries_the_limits(self):
        env = self.scope_env()
        (self.root / "systemd-scope/systemctl").unlink()
        bare = self.root / "systemd-scope"
        for name in ("python3", "sh", "sleep", "true"):
            (bare / name).symlink_to(shutil.which(name))
        (bare / "t3").symlink_to(self.bin / "t3")
        self.replay(self.job_id(self.launch("--", "true", env={"PATH": str(bare)})))
        self.assertEqual([a.rsplit("=", 1)[0] for a in self.memory_limit_args(self.systemd_calls()[1])], ["--property=MemoryHigh", "--property=MemoryMax"])

    def test_dollars_in_the_job_reach_it_as_typed(self):
        # systemd-run expands $VAR and ${VAR} in the command's arguments (in --scope mode before 258): the launcher turns that off
        seen = self.root / "seen"
        probe = f"import sys; open({str(seen)!r}, 'w').write(repr(sys.argv[1:]))"
        args = ["$HOME", "${NOPE-dflt}", "$$", "a $x b", "100%"]
        self.replay(self.job_id(self.launch("--", sys.executable, "-c", probe, *args, env=self.scope_env())))
        self.assertEqual(seen.read_text(), repr(args))

    @unittest.skipUnless(user_scopes_work(), "needs a systemd user manager (not a CI runner or the work Mac)")
    def test_dollars_in_the_job_reach_it_as_typed_through_the_real_systemd_run(self):
        seen = self.root / "seen"
        probe = f"import sys; open({str(seen)!r}, 'w').write(repr(sys.argv[1:]))"
        args = ["$HOME", "${NOPE-dflt}", "$$", "a $x b", "100%"]
        env = {"PATH": f"{self.bin}:{self.path}"}  # the real systemd-run
        self.replay(self.job_id(self.launch("--", sys.executable, "-c", probe, *args, env=env)))
        self.assertEqual(seen.read_text(), repr(args))

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
        (bare / "t3").symlink_to(self.bin / "t3")
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
        self.assertEqual(len(self.t3_sends()), 1)
        self.assertTrue(records[0]["slice"].endswith(".slice"), "the start record shows the slice the scope landed in")

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
        self.assertIn("job finished: killed by SIGTERM", self.texts()[0])

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

    def test_a_signal_ignored_at_launch_stays_ignored_for_the_job(self):
        # `nohup run-and-wake …`: SIGHUP ignored on the way in is ignored by the job, as before the watcher forwarded signals
        seen = self.root / "seen"
        probe = f"import signal; print(signal.getsignal(signal.SIGHUP) is signal.SIG_IGN, file=open({str(seen)!r}, 'w'))"
        result = subprocess.run([sys.executable, str(SCRIPT), "--", sys.executable, "-c", probe], env=self.env, cwd=self.root, text=True,
                                capture_output=True, timeout=20, preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_IGN))
        self.replay(self.job_id(result))
        self.assertEqual(seen.read_text().strip(), "True")

    def test_a_job_killed_with_sigkill_gets_an_end_record_with_the_signal(self):
        cmd, _ = self.held_job()
        result = self.launch("--", *cmd)
        job = self.job_id(result)
        os.kill(int(result.stdout.split(", pid ")[1].split(",")[0]), signal.SIGKILL)
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[1]["exit"], records[1]["signal"]], [None, "SIGKILL"])
        self.assertIn("job finished: killed by SIGKILL", self.texts()[0])

    # --- a host restart, or T3 down when the job ends: the wake is delivered, once, when T3 is back ---
    def recover(self, **extra):
        return subprocess.run([sys.executable, str(SCRIPT), "--recover"], env={**self.env, **self.t3_env(), "RUN_AND_WAKE_T3_RETRY": "0.05:1", **extra},
                              cwd=self.root, text=True, capture_output=True, timeout=30)

    def seed(self, job, boot, *, end=None, wake=None, thread=THREAD, pane=None, pid=4242, start_ts="2026-11-15T18:05:02.470Z"):
        """Append a job's records as an earlier run of this script left them (a foreign boot id is a host restart). `pane` writes the herdr fields older versions put on `start`."""
        self.log.parent.mkdir(parents=True, exist_ok=True)
        records = [{"ts": start_ts, "job": job, "event": "start", "cmd": ["amz-check.sh", "plus3h"], "cwd": "/w", **({"pane": pane, "session": "/sessions/old.jsonl"} if pane else {}),
                    "thread": thread, "pid": pid, "output": f"/o/{job}.log", "op_token": None, "scope": f"run-and-wake-{job}.scope",
                    "slice": "app-t3code-agents.slice", **({"boot": boot} if boot else {})}]
        if end:
            records.append({"ts": "2026-11-15T19:46:25.454Z", "job": job, "event": "end", "duration_s": 6083.0, "signal": None, "exit": None, **end})
        if wake:
            records.append({"ts": "2026-11-15T19:46:26.705Z", "job": job, "event": "wake", "target": "t3", "duration_s": 1.2, **wake})
        with open(self.log, "a") as f:
            f.writelines(json.dumps(r) + "\n" for r in records)

    def records_of(self, job):
        return [json.loads(line) for line in self.log.read_text().splitlines() if json.loads(line)["job"] == job]

    def boot_started(self):
        btime = next(int(line.split()[1]) for line in Path("/proc/stat").read_text().splitlines() if line.startswith("btime "))
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(btime))

    LINUX_BOOT = unittest.skipUnless(os.path.exists("/proc/sys/kernel/random/boot_id"), "--recover works from the Linux boot id")
    ELSEWHERE = "00000000-0000-0000-0000-000000000000"
    DOWN = "Could not reach the T3 Code server at http://127.0.0.1:3773. fetch failed"

    @LINUX_BOOT
    def test_the_start_record_names_the_boot(self):
        records = self.replay(self.job_id(self.launch("--", "true", env=self.t3_env())))
        self.assertEqual(records[0]["boot"], Path("/proc/sys/kernel/random/boot_id").read_text().strip())

    def test_t3_down_for_a_few_tries_still_gets_one_wake(self):
        (self.fake / "t3_down").write_text("2")  # the first two sends find no server: T3 is restarting
        records = self.replay(self.job_id(self.launch("--", "true", env=self.t3_env(RUN_AND_WAKE_T3_RETRY="0.1:20"))))
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[-1]["result"], records[-1]["attempts"]], ["sent", 3])
        sends = self.t3_sends()
        self.assertEqual(len(sends), 3)
        self.assertEqual(len({s["stdin"] for s in sends}), 1, "the same text each try")

    def test_a_refused_send_is_not_retried_even_with_a_window(self):
        (self.fake / "t3_error").write_text("")
        records = self.replay(self.job_id(self.launch("--", "true", env=self.t3_env(RUN_AND_WAKE_T3_RETRY="0.05:20"))))
        self.assertEqual(records[-1]["result"], "failed")
        time.sleep(0.5)
        self.assertEqual(len(self.t3_sends()), 1)

    @LINUX_BOOT
    def test_t3_down_past_the_window_leaves_a_failed_wake_that_recover_delivers_once(self):
        (self.fake / "t3_down").write_text("all")
        job = self.job_id(self.launch("--", "sh", "-c", "exit 3", env=self.t3_env(RUN_AND_WAKE_T3_RETRY="0.05:0.3")))
        records = self.replay(job)
        self.assertEqual([records[-1]["result"], records[-1]["error"]], ["failed", f"exit 1: {self.DOWN}"])
        self.assertGreater(records[-1]["attempts"], 1)
        before = len(self.t3_sends())
        (self.fake / "t3_down").unlink()  # T3 is back
        done = self.recover()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        sent = self.t3_sends()[before:]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["argv"], ["thread", "send", THREAD, "-"])
        self.assertTrue(sent[0]["stdin"].startswith(f"[run-and-wake k:{job}] job finished: exit 3 after "), sent[0]["stdin"])
        self.assertIn("delivered late", sent[0]["stdin"])
        last = self.records_of(job)[-1]
        self.assertEqual([last["event"], last["result"], last["recover"]], ["wake", "sent", True])
        self.recover()
        self.assertEqual(len(self.t3_sends()), before + 1, "a second recover sends nothing")

    def test_a_stopped_job_makes_one_attempt_and_does_not_hold_a_shutdown_up(self):
        # The shutdown sends ONE SIGTERM, while the job runs. Once the job is gone the watcher must not sit retrying (with a 10 minute window)
        # until the scope's stop timeout kills it: it tries once, records the failure and exits; --recover owes the wake.
        (self.fake / "t3_down").write_text("all")
        cmd, _ = self.held_job()
        result = self.launch("--", *cmd, env=self.t3_env(RUN_AND_WAKE_T3_RETRY="0.2:600"))
        job = self.job_id(result)
        group = os.getpgid(int(result.stdout.split(", pid ")[1].split(",")[0]))
        os.killpg(group, signal.SIGTERM)
        records = self.replay(job, timeout=5)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[-1]["result"], records[-1].get("attempts")], ["failed", None], "one attempt, no waiting")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        os.killpg(group, signal.SIGKILL)
        self.fail("the watcher was still running after its one attempt")

    def test_a_watcher_killed_while_waiting_for_t3_leaves_the_wake_owed(self):
        (self.fake / "t3_down").write_text("all")
        result = self.launch("--", "sh", "-c", "sleep 600 & wait", env=self.t3_env(RUN_AND_WAKE_T3_RETRY="0.2:600"))
        job = self.job_id(result)
        pid = int(result.stdout.split(", pid ")[1].split(",")[0])
        group = os.getpgid(pid)
        os.kill(pid, signal.SIGKILL)  # the job ends by itself; the watcher is retrying a send that cannot succeed
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not any(r["event"] == "end" for r in self.records_of(job)):
            time.sleep(0.05)
        time.sleep(0.5)
        os.killpg(group, signal.SIGTERM)  # a stop now ends the waiting watcher at once (its handlers are back to default)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            os.killpg(group, signal.SIGKILL)
            self.fail("the watcher kept running after SIGTERM")
        self.assertEqual([r["event"] for r in self.records_of(job)], ["start", "end"], "killed mid-wait: no wake record")

    @LINUX_BOOT
    def test_a_job_cut_off_by_a_restart_is_woken_with_the_did_not_finish_text(self):
        # The incident: the host reboots, scope stop sends SIGTERM, the wake finds T3 gone, the host comes back. Seed what that left behind.
        self.seed("20261115T180502Z-57edd4", self.ELSEWHERE, end={"signal": "SIGTERM", "stopped": ["SIGTERM"]},
                  wake={"result": "failed", "error": f"exit 1: {self.DOWN}"})
        self.seed("20261115T200510Z-60a37c", self.ELSEWHERE)  # started, never ended: the watcher was killed too
        done = self.recover()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        texts = {s["stdin"].split("]")[0]: s["stdin"] for s in self.t3_sends()}
        restarted = f"the host restarted at {self.boot_started()} and the job was killed. Rerun it; this is not a result."
        self.assertEqual(sorted(texts), ["[run-and-wake k:20261115T180502Z-57edd4", "[run-and-wake k:20261115T200510Z-60a37c"])
        for job, text in ((j[len("[run-and-wake k:"):], t) for j, t in texts.items()):
            self.assertIn(f"[run-and-wake k:{job}] job did NOT finish: {restarted}", text)
            self.assertNotIn("job finished", text)
            self.assertIn("amz-check.sh plus3h", text)
            self.assertIn(f"Partial output: /o/{job}.log", text)
            self.assertNotIn("\n", text)
        self.assertIn("an end at 2026-11-15T19:46:25.454Z (killed by SIGTERM), is not a result either", texts["[run-and-wake k:20261115T180502Z-57edd4"])
        self.assertNotIn("is not a result either", texts["[run-and-wake k:20261115T200510Z-60a37c"], "no status was written, so none is quoted")
        no_end = self.records_of("20261115T200510Z-60a37c")
        self.assertEqual([r["event"] for r in no_end], ["start", "end", "wake"])
        self.assertEqual([no_end[1]["error"], no_end[1]["recovered"], no_end[1]["exit"]], ["host-restarted", True, None])
        self.assertEqual([no_end[2]["result"], no_end[2]["recover"]], ["sent", True])

    @LINUX_BOOT
    def test_a_shutdown_exit_status_is_never_passed_off_as_a_result(self):
        # f2796c as the log has it (21:02:33.579Z, with the SIGTERM ends at .38): a `bash -c "kgate ...; echo exit $?"` wrapper whose inner job died
        # first, so it exited 0 with no signal and no `stopped`. Its end record says exit 0; the job did not finish.
        self.seed("20261115T204024Z-f2796c", self.ELSEWHERE, end={"exit": 0})
        self.recover()
        (text,) = [s["stdin"] for s in self.t3_sends()]
        self.assertIn("job did NOT finish", text)
        self.assertIn("(exit 0), is not a result either", text)
        self.assertNotIn("job finished", text)

    @LINUX_BOOT
    def test_an_earlier_boot_job_is_never_sent_as_a_result_even_when_its_wake_only_found_t3_down(self):
        self.seed("20261115T170000Z-aaaaaa", self.ELSEWHERE, end={"exit": 0, "duration_s": 61.0}, wake={"result": "failed", "error": f"exit 1: {self.DOWN}"})
        self.recover()
        (text,) = [s["stdin"] for s in self.t3_sends()]
        self.assertIn("job did NOT finish", text)
        self.assertNotIn("job finished", text)

    @LINUX_BOOT
    def test_recover_leaves_alone_what_it_does_not_owe(self):
        here = Path("/proc/sys/kernel/random/boot_id").read_text().strip() if os.path.exists("/proc/sys/kernel/random/boot_id") else self.ELSEWHERE
        self.seed("old-record", None)  # before the boot field: never replayed
        self.seed("pane-job", self.ELSEWHERE, thread=None, pane="w1:p1")  # a Pi pane died with the host
        self.seed("still-running", here)  # this boot, no end: alive
        self.seed("delivered", self.ELSEWHERE, end={"exit": 0}, wake={"result": "sent"})
        self.seed("refused", self.ELSEWHERE, end={"exit": 0}, wake={"result": "failed", "error": f"exit 1: Thread {THREAD} was not found."})
        self.seed("skipped", self.ELSEWHERE, end={"exit": 0})
        with open(self.log, "a") as f:
            f.write(json.dumps({"ts": "2026-11-15T19:46:26.705Z", "job": "skipped", "event": "skip", "reason": "pane-gone"}) + "\n")
        before = self.log.read_text()
        done = self.recover()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.t3_sends(), [])
        self.assertEqual(self.log.read_text(), before, "nothing is written either")

    @LINUX_BOOT
    def test_recover_exits_1_and_keeps_the_debt_when_t3_never_comes_back(self):
        self.seed("20261115T200510Z-60a37c", self.ELSEWHERE)
        (self.fake / "t3_down").write_text("all")
        self.assertEqual(self.recover().returncode, 1)
        (self.fake / "t3_down").unlink()
        self.assertEqual(self.recover().returncode, 0, "the next run delivers it")
        delivered = [r for r in self.records_of("20261115T200510Z-60a37c") if r["event"] == "wake" and r["result"] == "sent"]
        self.assertEqual(len(delivered), 1, "delivered once, after the failed run left it owed")

    @LINUX_BOOT
    def test_the_real_path_a_stopped_job_whose_wake_could_not_be_sent_is_recovered_after_a_restart(self):
        # A real job and watcher; the stop reaches both (as a scope stop does); T3 is down; then "the host restarts" (the boot id on the
        # records changes) and T3 is back: recover tells the thread the job did not finish.
        (self.fake / "t3_down").write_text("all")
        cmd, _ = self.held_job()
        result = self.launch("--", *cmd, env=self.t3_env(RUN_AND_WAKE_T3_RETRY="0.05:0.3"))
        job = self.job_id(result)
        os.killpg(os.getpgid(int(result.stdout.split(", pid ")[1].split(",")[0])), signal.SIGTERM)
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[1]["signal"], records[1]["stopped"]], ["SIGTERM", ["SIGTERM"]])
        self.assertEqual(records[2]["result"], "failed")
        lines = [json.loads(line) for line in self.log.read_text().splitlines()]
        for r in lines:
            if r["event"] == "start" and r["job"] == job:
                r["boot"] = self.ELSEWHERE
        self.log.write_text("".join(json.dumps(r) + "\n" for r in lines))
        (self.fake / "t3_down").unlink()
        before = len(self.t3_sends())
        self.assertEqual(self.recover().returncode, 0)
        (sent,) = self.t3_sends()[before:]
        text = sent["stdin"]
        self.assertIn(f"[run-and-wake k:{job}] job did NOT finish: the host restarted at {self.boot_started()}", text)
        self.assertIn("(killed by SIGTERM), is not a result either", text)

    def test_a_malformed_retry_setting_warns_and_the_default_is_used(self):
        for setting in ("garbage", "5", "x:y", "0:10", "-1:5"):
            with self.subTest(setting=setting):
                result = self.launch("--", "true", env=self.t3_env(RUN_AND_WAKE_T3_RETRY=setting))
                self.assertIn(f"WARN: RUN_AND_WAKE_T3_RETRY={setting!r} is not <interval>:<window>", result.stderr)
                self.assertEqual(self.replay(self.job_id(result))[-1]["result"], "sent", "the job still runs and wakes")

    @LINUX_BOOT
    def test_a_log_line_that_is_json_but_not_a_record_is_skipped_by_recover(self):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.write_text('[1, 2]\n"text"\nnull\n3\n{"job": 7, "event": "start"}\n{"no": "job"}\n{"job": "j", "event": 5}\n')
        self.seed("20261115T200510Z-60a37c", self.ELSEWHERE)
        done = self.recover()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("job did NOT finish", self.t3_sends()[0]["stdin"], "the real record after the odd lines is still recovered")

    # --- wakes that say nothing new: dropped (waited, cancelled) or merged (a burst) ---
    def wait_for(self, job, timeout=20):
        """`--wait` run from the session the T3 jobs were started in (the owner)."""
        return subprocess.run([sys.executable, str(SCRIPT), "--wait", job], env={**self.env, **self.t3_env()}, cwd=self.root, text=True, capture_output=True, timeout=timeout)

    def wait_until_blocked(self, job, timeout=20):
        """Returns once a `--wait` process holds the job's wait lock, the state the watcher reads as "the session already has the result". Release a held job only after this:
        a fixed sleep lets a loaded runner end the job before its waiter has started, and then the wake goes out and no `skip` is written."""
        lock = self.state / f"run-and-wake/jobs/{job}.wait"
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                fd = os.open(lock, os.O_RDONLY)
            except OSError:
                fd = None
            if fd is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    return  # held: the waiter is blocked on the job
                finally:
                    os.close(fd)
            time.sleep(0.05)
        self.fail(f"no --wait took the wait lock of job {job}")

    def final_records(self, job, event, timeout=20):
        """The job's records once one of `event` is in the log."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            mine = [r for r in (json.loads(line) for line in self.log.read_text().splitlines()) if r["job"] == job] if self.log.exists() else []
            if any(r["event"] == event for r in mine):
                return mine
            time.sleep(0.05)
        self.fail(f"job {job} never got a {event} record")

    def test_a_waiter_gets_the_result_and_the_job_sends_no_wake(self):
        job = self.job_id(self.launch("--", "sh", "-c", "sleep 2; echo out; exit 7", env=self.t3_env()))
        waited = self.wait_for(job)
        self.assertEqual(waited.returncode, 7, "the waiter exits with the job's status")
        self.assertTrue(waited.stdout.startswith(f"[run-and-wake k:{job}] job finished: exit 7 after "), waited.stdout)
        self.assertEqual(len(waited.stdout.splitlines()), 1)
        records = self.final_records(job, "skip")
        self.assertEqual(sorted(r["event"] for r in records), ["end", "read", "skip", "start"])
        self.assertEqual(next(r for r in records if r["event"] == "skip")["reason"], "waited")
        time.sleep(0.5)
        self.assertEqual(self.t3_sends(), [], "the result came once, from the waiter")

    def test_a_waiter_that_died_does_not_hide_the_wake(self):
        cmd, release = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        waiter = subprocess.Popen([sys.executable, str(SCRIPT), "--wait", job], env={**self.env, **self.t3_env()}, cwd=self.root, stdout=subprocess.DEVNULL)
        lock = self.state / f"run-and-wake/jobs/{job}.wait"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not lock.exists():
            time.sleep(0.05)
        waiter.kill()
        waiter.wait()
        release.write_text("")
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual(len(self.t3_sends()), 1, "no waiter was alive when the job ended, so the wake goes out")

    def test_waiting_for_a_job_that_already_ended_prints_at_once_and_exits_with_its_status(self):
        job = self.job_id(self.launch("--", "sh", "-c", "exit 3", env=self.t3_env()))
        self.replay(job)
        waited = self.wait_for(job, timeout=5)
        self.assertEqual(waited.returncode, 3)
        self.assertIn("job finished: exit 3 after", waited.stdout)
        self.assertEqual(len(self.t3_sends()), 1, "the wake had already gone; a late waiter does not remove it")

    def test_a_signal_death_is_128_plus_the_signal_for_the_waiter(self):
        cmd, _ = self.held_job()
        result = self.launch("--", *cmd, env=self.t3_env())
        job = self.job_id(result)
        waiter = subprocess.Popen([sys.executable, str(SCRIPT), "--wait", job], env={**self.env, **self.t3_env()}, cwd=self.root, text=True, stdout=subprocess.PIPE)
        time.sleep(0.5)
        os.kill(int(result.stdout.split(", pid ")[1].split(",")[0]), signal.SIGTERM)
        out = waiter.communicate(timeout=10)[0]
        self.assertEqual(waiter.returncode, 128 + signal.SIGTERM)
        self.assertIn("killed by SIGTERM", out)

    def test_waiting_for_an_unknown_job_is_refused(self):
        done = self.wait_for("20261116T000000Z-nojob0", timeout=5)
        self.assertEqual(done.returncode, 64)
        self.assertEqual(self.wait_for("", timeout=5).returncode, 64)
        done = subprocess.run([sys.executable, str(SCRIPT), "--wait"], env=self.env, text=True, capture_output=True, timeout=5)
        self.assertEqual(done.returncode, 2)
        self.assertIn("Usage: run-and-wake", done.stderr)

    @LINUX_BOOT
    def test_waiting_for_a_job_a_restart_cut_off_says_it_did_not_finish(self):
        self.seed("20261115T200510Z-60a37c", self.ELSEWHERE)
        done = self.wait_for("20261115T200510Z-60a37c", timeout=5)
        self.assertEqual(done.returncode, 1)
        self.assertIn("job did NOT finish", done.stdout)

    def test_a_job_the_session_cancelled_itself_sends_no_wake(self):
        line = '{"id": "kgate-1-1", "job": "%s", "exit": 143, "reason": "cancelled by kgate cancel", "cancelled": true}'
        cmd = f'mkdir -p "$XDG_STATE_HOME/kgate"; printf \'{line}\\n\' "$RUN_AND_WAKE_JOB" >> "$XDG_STATE_HOME/kgate/log.jsonl"; exit 143'
        job = self.job_id(self.launch("--", "sh", "-c", cmd, env=self.t3_env()))
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "skip")
        self.assertEqual([records[1]["exit"], records[2]["reason"]], [143, "cancelled"])
        time.sleep(0.5)
        self.assertEqual(self.t3_sends(), [])

    def test_a_kgate_run_that_ended_on_its_own_still_wakes_and_so_does_a_cancel_of_another_job(self):
        ended = '{"id": "kgate-1-1", "job": "%s", "exit": 1, "cancelled": false}'
        other = '{"id": "kgate-2-2", "job": "20261116T000000Z-other0", "exit": 143, "cancelled": true}'
        cmd = f'mkdir -p "$XDG_STATE_HOME/kgate"; printf \'{ended}\\n{other}\\n\' "$RUN_AND_WAKE_JOB" >> "$XDG_STATE_HOME/kgate/log.jsonl"; exit 1'
        job = self.job_id(self.launch("--", "sh", "-c", cmd, env=self.t3_env()))
        self.assertReplay(self.replay(job), "start", "end", "wake")
        self.assertEqual(len(self.t3_sends()), 1)

    def merged(self, **extra):
        return self.t3_env(**{"RUN_AND_WAKE_COALESCE": "1.5", **extra})

    def test_a_burst_of_jobs_ending_together_is_one_message_and_each_job_keeps_its_own_line_and_record(self):
        jobs = [self.job_id(self.launch("--", "sh", "-c", f"exit {n}", env=self.merged())) for n in (0, 1, 2)]
        records = {j: self.replay(j) for j in jobs}
        time.sleep(0.5)
        sends = self.t3_sends()
        self.assertEqual(len(sends), 1, "three jobs, one message")
        self.assertEqual(sends[0]["argv"], ["thread", "send", THREAD, "-"])
        lines = sends[0]["stdin"].splitlines()
        self.assertEqual(len(lines), 3)
        for job, n, line in zip(jobs, (0, 1, 2), lines):
            self.assertTrue(line.startswith(f"[run-and-wake k:{job}] job finished: exit {n} after "), line)
        for j in jobs:
            self.assertReplay(records[j], "start", "end", "wake")
            wake = records[j][-1]
            self.assertEqual([wake["target"], wake["result"]], ["t3", "sent"])
            self.assertEqual(sorted(wake["merged_with"]), sorted(set(jobs) - {j}))

    def test_a_lone_job_is_sent_alone_after_the_window_with_the_text_it_always_had(self):
        result = self.launch("--", "sh", "-c", "exit 7", env=self.merged())
        job = self.job_id(result)
        self.assertEqual(self.t3_sends(), [], "held for the window")
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertNotIn("merged_with", records[-1])
        sends = self.t3_sends()
        self.assertEqual(len(sends), 1)
        self.assertTrue(sends[0]["stdin"].startswith(f"[run-and-wake k:{job}] job finished: exit 7 after "))
        self.assertEqual(len(sends[0]["stdin"].splitlines()), 1)

    def test_jobs_of_two_threads_are_not_merged(self):
        a = self.job_id(self.launch("--", "true", env=self.merged()))
        b = self.job_id(self.launch("--", "true", env=self.merged(T3CODE_THREAD_ID="thread-other")))
        self.replay(a)
        self.replay(b)
        self.assertEqual(sorted(s["argv"][2] for s in self.t3_sends()), sorted([THREAD, "thread-other"]))

    def test_jobs_further_apart_than_the_window_are_two_messages(self):
        a = self.job_id(self.launch("--", "true", env=self.merged()))
        self.replay(a)
        b = self.job_id(self.launch("--", "true", env=self.merged()))
        self.replay(b)
        self.assertEqual(len(self.t3_sends()), 2)

    def test_a_result_read_during_the_window_is_not_sent(self):
        a = self.job_id(self.launch("--", "true", env=self.merged(RUN_AND_WAKE_COALESCE="2")))
        b = self.job_id(self.launch("--", "sh", "-c", "exit 4", env=self.merged(RUN_AND_WAKE_COALESCE="2")))
        self.final_records(a, "end")
        self.assertEqual(self.wait_for(a, timeout=5).returncode, 0)  # the session reads A's result itself, inside the window
        records_b = self.replay(b)
        sends = self.t3_sends()
        self.assertEqual(len(sends), 1)
        self.assertEqual(len(sends[0]["stdin"].splitlines()), 1, "only B is in the message")
        self.assertIn(f"k:{b}]", sends[0]["stdin"])
        self.assertNotIn("merged_with", records_b[-1])
        records_a = self.records_of(a)
        self.assertEqual([r["event"] for r in records_a], ["start", "end", "read", "skip"])
        self.assertEqual(records_a[-1]["reason"], "waited")

    def test_a_stop_signal_during_the_window_sends_at_once(self):
        result = self.launch("--", "sleep", "1", env=self.t3_env(RUN_AND_WAKE_COALESCE="60"))
        job = self.job_id(result)
        group = os.getpgid(int(result.stdout.split(", pid ")[1].split(",")[0]))  # the watcher's group, still there after the job is gone
        self.final_records(job, "end")
        time.sleep(0.3)
        self.assertEqual(self.t3_sends(), [], "held for the window")
        os.killpg(group, signal.SIGTERM)  # the host is going down: do not sit out the window
        records = self.replay(job, timeout=5)
        self.assertEqual([records[-1]["event"], records[-1]["result"]], ["wake", "sent"])
        self.assertEqual(len(self.t3_sends()), 1)

    def test_a_job_that_was_stopped_is_sent_at_once_whatever_the_window(self):
        cmd, _ = self.held_job()
        result = self.launch("--", *cmd, env=self.t3_env(RUN_AND_WAKE_COALESCE="60"))
        job = self.job_id(result)
        os.killpg(os.getpgid(int(result.stdout.split(", pid ")[1].split(",")[0])), signal.SIGTERM)
        records = self.replay(job, timeout=5)
        self.assertEqual(records[-1]["result"], "sent")

    def test_the_merge_window_setting(self):
        spec = importlib.machinery.SourceFileLoader("run_and_wake_mod", str(SCRIPT))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("run_and_wake_mod", spec))
        spec.exec_module(mod)
        for setting, want in ((None, 10.0), ("", 10.0), ("0", 0.0), ("2.5", 2.5), ("abc", 10.0), ("-1", 10.0)):
            with self.subTest(setting=setting):
                old = os.environ.pop("RUN_AND_WAKE_COALESCE", None)
                if setting is not None:
                    os.environ["RUN_AND_WAKE_COALESCE"] = setting
                try:
                    self.assertEqual(mod.coalesce_window(), want)
                finally:
                    os.environ.pop("RUN_AND_WAKE_COALESCE", None)
                    if old is not None:
                        os.environ["RUN_AND_WAKE_COALESCE"] = old
        self.assertEqual(mod.wait_command("20261116T000000Z-abc123"), "run-and-wake --wait 20261116T000000Z-abc123")

    def test_a_wait_from_another_thread_prints_the_result_and_leaves_the_owners_wake(self):
        cmd, release = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env(T3CODE_THREAD_ID="builder-thread")))
        other = subprocess.Popen([sys.executable, str(SCRIPT), "--wait", job], env={**self.env, **self.t3_env(T3CODE_THREAD_ID="lead-thread")},
                                 cwd=self.root, text=True, stdout=subprocess.PIPE)
        time.sleep(0.5)
        release.write_text("")
        out = other.communicate(timeout=10)[0]
        self.assertEqual(other.returncode, 0)
        self.assertIn(f"[run-and-wake k:{job}] job finished: exit 0", out, "the lead gets the result printed")
        self.final_records(job, "read")
        records = self.final_records(job, "wake")  # the waiter's `read` and the owner's `wake` are written by two processes: wait for both, in either order
        self.assertEqual([r["event"] for r in records[:2]], ["start", "end"])
        self.assertEqual(sorted(r["event"] for r in records[2:]), ["read", "wake"])
        sends = self.t3_sends()
        self.assertEqual([s["argv"][2] for s in sends], ["builder-thread"], "the thread that started the job is still woken")
        self.assertEqual([r["owner"] for r in self.records_of(job) if r["event"] == "read"], [False])
        self.assertFalse((self.state / f"run-and-wake/jobs/{job}.read").exists(), "a stranger leaves no marker")

    def test_a_wait_from_the_owners_own_thread_drops_the_wake_and_another_thread_does_not(self):
        cmd, release = self.held_job()
        job = self.job_id(self.launch("--", *cmd))  # started from THREAD
        stranger = {**self.env, "T3CODE_THREAD_ID": "other-thread"}
        mine = subprocess.Popen([sys.executable, str(SCRIPT), "--wait", job], env=self.env, cwd=self.root, text=True, stdout=subprocess.PIPE)
        other = subprocess.Popen([sys.executable, str(SCRIPT), "--wait", job], env=stranger, cwd=self.root, text=True, stdout=subprocess.PIPE)
        self.wait_until_blocked(job)  # the owner's wait must hold its lock before the job ends, or the wake goes out
        release.write_text("")
        mine.communicate(timeout=10)
        other.communicate(timeout=10)
        records = self.final_records(job, "skip")
        self.assertEqual(next(r for r in records if r["event"] == "skip")["reason"], "waited")
        self.assertEqual(self.t3_sends(), [], "the owner's own wait stood in for the wake")
        self.assertEqual(sorted(r["owner"] for r in self.records_of(job) if r["event"] == "read"), [False, True])

    # --- a watcher that is gone (the pod's container restarted, or it was killed): the job still gets an end and its owner a wake ---
    def crash(self, job):
        """What a container restart does: the watcher and the job die together, with no chance to write anything. Returns once both are gone."""
        start = self.records_of(job)[0]
        for pid in (start["watcher"], start["pid"]):
            os.kill(pid, signal.SIGKILL)
        end = time.monotonic() + 10
        while time.monotonic() < end and any(process_running(p) for p in (start["watcher"], start["pid"])):
            time.sleep(0.02)

    def sweep_by_launching(self, **env):
        """Any later call runs the sweep: the next agent that starts a job. Returns its job id."""
        return self.job_id(self.launch("--", "true", env=self.t3_env(**env)))

    def lost_records(self, job):
        return [r for r in self.records_of(job) if r["event"] in ("end", "wake", "skip")]

    def test_a_job_whose_watcher_and_process_were_killed_gets_a_lost_end_and_a_wake_on_the_next_call(self):
        cmd, _ = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        self.assertEqual(self.records_of(job)[0]["pid_start"], Path(f"/proc/{self.records_of(job)[0]['pid']}/stat").read_text().rsplit(")", 1)[1].split()[19] if sys.platform.startswith("linux") else self.records_of(job)[0]["pid_start"])
        self.crash(job)
        self.assertEqual([r["event"] for r in self.records_of(job)], ["start"], "nothing wrote an end: the old behaviour")
        self.sweep_by_launching()
        end, wake = self.lost_records(job)
        self.assertEqual([end["event"], end["error"], end["lost"], end["exit"], end["signal"]], ["end", "lost", True, None, None])
        self.assertEqual([wake["event"], wake["result"], wake["swept"]], ["wake", "sent", True])
        sends = [s for s in self.t3_sends() if f"k:{job}]" in s["stdin"]]
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["argv"], ["thread", "send", THREAD, "-"])
        text = sends[0]["stdin"]
        self.assertIn(f"[run-and-wake k:{job}] job did NOT finish: its watcher is gone and sent no result", text)
        self.assertIn("its status is unknown. Rerun it; this is not a result.", text)
        self.assertNotIn("job finished", text)
        self.assertNotIn("exit None", text)
        self.assertFalse((self.state / f"run-and-wake/jobs/{job}.lock").exists(), "settled: nothing left to sweep")
        self.sweep_by_launching()
        self.assertEqual(len([s for s in self.t3_sends() if f"k:{job}]" in s["stdin"]]), 1, "a second sweep sends nothing again")

    def test_a_job_that_finished_normally_leaves_no_lock_and_a_running_one_is_not_swept(self):
        done = self.job_id(self.launch("--", "true", env=self.t3_env()))
        self.replay(done)
        lock = self.state / f"run-and-wake/jobs/{done}.lock"
        end = time.monotonic() + 10
        while lock.exists() and time.monotonic() < end:  # the watcher removes it once it has woken
            time.sleep(0.02)
        self.assertFalse(lock.exists(), "removed by the watcher itself: no sweep has run since")
        cmd, release = self.held_job()
        running = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        self.assertTrue((self.state / f"run-and-wake/jobs/{running}.lock").exists())
        self.sweep_by_launching()
        self.assertEqual([r["event"] for r in self.records_of(running)], ["start"], "a live watcher holds its lock: no end, no wake")
        release.write_text("go")
        self.replay(running)

    def test_the_job_does_not_inherit_the_watchers_lock(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("reads /proc/<pid>/fd")
        cmd, release = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        start = self.records_of(job)[0]
        held = [os.readlink(f"/proc/{start['pid']}/fd/{fd}") for fd in os.listdir(f"/proc/{start['pid']}/fd") if os.path.exists(f"/proc/{start['pid']}/fd/{fd}")]
        self.assertFalse([h for h in held if h.endswith(f"{job}.lock")], held)
        release.write_text("go")
        self.replay(job)

    def test_a_dead_watcher_with_a_live_job_is_left_alone_until_the_job_is_gone_too(self):
        cmd, _ = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        start = self.records_of(job)[0]
        os.kill(start["watcher"], signal.SIGKILL)
        time.sleep(0.3)
        self.sweep_by_launching()
        self.assertEqual([r["event"] for r in self.records_of(job)], ["start"], "the job still runs: it is not lost")
        os.kill(start["pid"], signal.SIGKILL)
        time.sleep(0.3)
        self.sweep_by_launching()
        self.assertEqual([r["event"] for r in self.lost_records(job)], ["end", "wake"])

    def test_a_recycled_pid_is_not_taken_for_the_job(self):
        cmd, _ = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        self.crash(job)
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        start = next(r for r in records if r["job"] == job)
        start["pid"], start["pid_start"] = os.getpid(), "1"  # a live process now holds the old pid, started at another time
        self.log.write_text("".join(json.dumps(start if r["job"] == job else r) + "\n" for r in records))
        self.sweep_by_launching()
        self.assertEqual([r["event"] for r in self.lost_records(job)], ["end", "wake"])

    def test_recover_ends_and_wakes_a_lost_job_and_waits_for_t3(self):
        cmd, _ = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        self.crash(job)
        (self.fake / "t3_down").write_text("2\n")  # the next two sends find no server: T3 is still starting
        done = self.recover(**{"RUN_AND_WAKE_T3_RETRY": "0.05:5"})
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        events = self.lost_records(job)
        self.assertEqual([e["event"] for e in events], ["end", "wake"])
        self.assertEqual([events[1]["result"], events[1]["attempts"]], ["sent", 3])
        self.assertEqual(len([s for s in self.t3_sends() if f"k:{job}] job did NOT finish" in s["stdin"]]), 3, "two tries found no server, the third was delivered")

    def test_a_sweep_that_finds_t3_down_tries_again_on_the_next_call(self):
        cmd, _ = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        self.crash(job)
        (self.fake / "t3_down").write_text("all\n")
        self.sweep_by_launching()
        first = self.lost_records(job)
        self.assertEqual([e["event"] for e in first], ["end", "wake"])
        self.assertEqual(first[1]["result"], "failed")
        self.assertTrue((self.state / f"run-and-wake/jobs/{job}.lock").exists(), "still owed: kept for the next sweep")
        (self.fake / "t3_down").unlink()
        self.sweep_by_launching()
        events = [(e["event"], e.get("result")) for e in self.lost_records(job)]
        self.assertEqual(events, [("end", None), ("wake", "failed"), ("wake", "sent")])
        self.assertFalse((self.state / f"run-and-wake/jobs/{job}.lock").exists())

    def test_waiting_for_a_lost_job_says_it_did_not_finish_and_the_wake_is_not_repeated(self):
        cmd, _ = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        self.crash(job)
        done = self.wait_for(job, timeout=10)
        self.assertEqual(done.returncode, 1)
        self.assertIn(f"[run-and-wake k:{job}] job did NOT finish", done.stdout)
        self.assertNotIn("exit None", done.stdout)
        self.assertEqual([(e["event"], e.get("reason")) for e in self.lost_records(job)], [("end", None), ("skip", "waited")])
        self.assertEqual([s for s in self.t3_sends() if f"k:{job}]" in s["stdin"]], [], "the owner's own wait stood in for the wake")

    # --- logs written by older versions: a job started from a herdr pane has `pane` and `session` on its `start` and no thread ---
    def old_pane_job(self, name, **kw):
        """An old pane job as this boot's earlier run left it: started in this boot, so only the sweep and --wait can look at it."""
        here = Path("/proc/sys/kernel/random/boot_id").read_text().strip() if os.path.exists("/proc/sys/kernel/random/boot_id") else None
        self.seed(name, here, thread=None, pane="w1A:p5", pid=2**22 + 7, **kw)  # a pid nothing runs as
        return name

    @LINUX_BOOT
    def test_an_old_start_line_with_a_pane_is_read_by_wait(self):
        job = self.old_pane_job("20261115T170000Z-pane01", end={"exit": 7, "duration_s": 3.0})
        done = self.wait_for(job, timeout=10)
        self.assertEqual(done.returncode, 7)
        self.assertIn(f"[run-and-wake k:{job}] job finished: exit 7 after 3s: amz-check.sh plus3h", done.stdout)
        self.assertEqual([r["owner"] for r in self.records_of(job) if r["event"] == "read"], [False], "no thread to be the owner of an old pane job")

    @LINUX_BOOT
    def test_an_old_pane_job_whose_watcher_died_is_ended_and_skipped_not_woken(self):
        job = self.old_pane_job("20261115T170000Z-pane02")
        self.unheld_lock(job)
        self.sweep_by_launching()
        records = [r for r in self.records_of(job) if r["event"] in ("end", "wake", "skip")]
        self.assertEqual([(r["event"], r.get("error"), r.get("reason")) for r in records], [("end", "lost", None), ("skip", None, "no-thread")])
        self.assertEqual([s for s in self.t3_sends() if f"k:{job}]" in s["stdin"]], [], "there is no pane to wake any more")
        self.assertFalse((self.state / f"run-and-wake/jobs/{job}.lock").exists(), "settled: nothing left to sweep")

    def unheld_lock(self, job):
        jobs = self.state / "run-and-wake/jobs"
        jobs.mkdir(parents=True, exist_ok=True)
        (jobs / f"{job}.lock").write_text("")  # a watcher that died: its file is still there and nobody holds it

    def test_a_watcher_that_died_between_the_end_and_the_wake_never_sends_its_status_as_a_result(self):
        job = "20261122T150000Z-aaaaaa"
        self.seed(job, None, end={"exit": 0, "signal": None})  # no boot id (macOS): nothing says it is an earlier boot
        self.log.write_text(self.log.read_text().replace('"pid": 4242', f'"pid": {2**22 + 7}'))
        self.unheld_lock(job)
        self.sweep_by_launching()
        sends = [s["stdin"] for s in self.t3_sends() if f"k:{job}]" in s["stdin"]]
        self.assertEqual(len(sends), 1)
        self.assertIn("job did NOT finish: its watcher is gone and sent no result", sends[0])
        self.assertNotIn("job finished", sends[0])
        self.assertEqual([e["event"] for e in self.records_of(job)], ["start", "end", "wake"], "its own end stays as written; no second end")

    @LINUX_BOOT
    def test_a_shutdown_cut_job_with_a_clean_exit_gets_recovers_text_from_the_sweep_and_not_a_result(self):
        # the reviewer's repro: the host rebooted, the wrapper shell wrote exit 0 as the job inside died, the watcher died before its wake; the lock stayed
        job = "20261115T194000Z-abcdef"
        self.seed(job, self.ELSEWHERE, end={"exit": 0, "signal": None, "stopped": ["SIGTERM"]})
        self.unheld_lock(job)
        self.sweep_by_launching()
        sends = [s["stdin"] for s in self.t3_sends() if f"k:{job}]" in s["stdin"]]
        self.assertEqual(len(sends), 1)
        self.assertIn(f"job did NOT finish: the host restarted at {self.boot_started()} and the job was killed", sends[0])
        self.assertNotIn("job finished", sends[0])
        self.assertEqual([e["event"] for e in self.records_of(job)], ["start", "end", "wake"])
        self.assertTrue(self.records_of(job)[2]["recover"], "recover's wake, the one text for an earlier boot")
        self.sweep_by_launching()
        self.assertEqual(len([s for s in self.t3_sends() if f"k:{job}]" in s["stdin"]]), 1)
        self.assertFalse((self.state / f"run-and-wake/jobs/{job}.lock").exists(), "settled by recover: the next sweep clears the lock")

    @LINUX_BOOT
    def test_the_sweeps_recover_wakes_only_the_swept_jobs_and_not_jobs_from_before_the_lock_existed(self):
        old, swept = "20261118T100000Z-0ld000", "20261115T200510Z-60a37c"
        self.seed(old, self.ELSEWHERE, start_ts="2026-11-18T10:00:00.000Z")  # an earlier boot, no lock file: recover would wake it, the sweep must not
        self.seed(swept, self.ELSEWHERE)
        self.unheld_lock(swept)
        self.sweep_by_launching()
        self.assertEqual(len([s for s in self.t3_sends() if f"k:{swept}]" in s["stdin"]]), 1)
        self.assertEqual([s for s in self.t3_sends() if f"k:{old}]" in s["stdin"]], [], "a job from before the lock existed is left alone")
        self.assertEqual([r["event"] for r in self.records_of(old)], ["start"])

    @LINUX_BOOT
    def test_an_earlier_boot_job_with_no_end_is_left_to_recover_and_told_the_restart_text(self):
        job = "20261115T200510Z-60a37c"  # the pod moved to another node: a new boot id, no systemd to run --recover
        self.seed(job, self.ELSEWHERE)
        self.unheld_lock(job)
        self.sweep_by_launching()
        sends = [s["stdin"] for s in self.t3_sends() if f"k:{job}]" in s["stdin"]]
        self.assertEqual(len(sends), 1)
        self.assertIn("the host restarted at", sends[0])
        records = self.records_of(job)
        self.assertEqual([r["event"] for r in records], ["start", "end", "wake"])
        self.assertEqual([records[1].get("error"), records[1].get("lost")], ["host-restarted", None], "written by recover, not by the sweep")

    @LINUX_BOOT
    def test_recover_does_not_quote_a_lost_end_as_a_status_after_a_reboot(self):
        # swept in an earlier boot, its wake found T3 down, then the host rebooted: recover owes it, and must not print the null exit as "exit None"
        self.seed("20261122T150000Z-cccccc", self.ELSEWHERE, end={"error": "lost", "lost": True}, wake={"result": "failed", "error": f"exit 1: {self.DOWN}"})
        done = self.recover()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        sends = self.t3_sends()
        self.assertEqual(len(sends), 1)
        self.assertIn("job did NOT finish: the host restarted", sends[0]["stdin"])
        self.assertNotIn("is not a result either", sends[0]["stdin"])
        self.assertNotIn("exit None", sends[0]["stdin"])

    def test_a_sweep_that_fails_leaves_an_error_record_and_does_not_stop_the_call(self):
        cmd, _ = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        self.crash(job)
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        for r in records:
            if r["job"] == job and r["event"] == "start":
                r["cmd"] = None  # a record shape the sweep cannot read
        self.log.write_text("".join(json.dumps(r) + "\n" for r in records))
        second = self.launch("--", "true", env=self.t3_env())
        self.assertEqual(second.returncode, 0, second.stderr)
        errors = [r for r in self.records_of(job) if r["event"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["step"], "sweep")
        self.assertIn("TypeError", errors[0]["error"])
        self.assertEqual(self.sweep_failed_elsewhere(), [], "the other jobs are not blocked")

    def sweep_failed_elsewhere(self):
        return [r for r in (json.loads(line) for line in self.log.read_text().splitlines()) if r["event"] == "error" and r["job"] == "run-and-wake"]

    def test_a_sweep_that_cannot_run_at_all_is_logged_too(self):
        (self.state / "run-and-wake/jobs").mkdir(parents=True)
        (self.state / "run-and-wake/jobs/20261122T150000Z-dddddd.lock").write_text("")
        (self.state / "run-and-wake/sweep.lock").mkdir()  # opening it as a file fails: the sweep itself raises
        self.sweep_by_launching()
        errors = [r for r in (json.loads(line) for line in self.log.read_text().splitlines()) if r["event"] == "error"]
        self.assertEqual([(r["job"], r["step"]) for r in errors], [("run-and-wake", "sweep")])

    @LINUX_BOOT
    def test_a_sweep_that_runs_recover_does_not_wait_for_t3(self):
        job = "20261115T200510Z-60a37c"
        self.seed(job, self.ELSEWHERE)
        self.unheld_lock(job)
        (self.fake / "t3_down").write_text("all\n")
        self.addCleanup((self.fake / "t3_down").unlink)  # T3 comes back at the end, so the new job's own watcher, retrying for 30 s, delivers and ends
        started = time.monotonic()
        self.sweep_by_launching(RUN_AND_WAKE_T3_RETRY="1:30")  # a 30 s window the call must not sit through
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual([r["result"] for r in self.records_of(job) if r["event"] == "wake"], ["failed"], "one try; the next call tries again")
        self.assertTrue((self.state / f"run-and-wake/jobs/{job}.lock").exists())

    def test_recover_that_cannot_reach_t3_still_sweeps(self):
        cmd, _ = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.t3_env()))
        self.crash(job)
        self.seed("20261115T200510Z-60a37c", self.ELSEWHERE)  # an earlier-boot job: recover owes it and T3 never answers, so recover itself returns 1
        (self.fake / "t3_down").write_text("all\n")
        done = self.recover()
        self.assertEqual(done.returncode, 1, "T3 never answered")
        self.assertEqual([e["event"] for e in self.lost_records(job)][:1], ["end"], "the end was written all the same")

    def test_a_job_logged_before_the_lock_existed_is_never_swept(self):
        self.seed("20261122T150000Z-bbbbbb", "b00t")
        self.sweep_by_launching()
        self.assertEqual([e["event"] for e in self.records_of("20261122T150000Z-bbbbbb")], ["start"])

    def test_a_process_stamp_is_read_from_ps_where_there_is_no_proc(self):
        spec = importlib.machinery.SourceFileLoader("run_and_wake_mod", str(SCRIPT))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("run_and_wake_mod", spec))
        spec.exec_module(mod)
        fake = self.root / "psbin"
        fake.mkdir()
        (fake / "ps").write_text("#!/bin/sh\n[ \"$4\" = 31337 ] && echo 'Sun Nov 22 12:00:00 2026'\n")
        (fake / "ps").chmod(0o755)
        with unittest.mock.patch.dict(os.environ, {"PATH": f"{fake}:{self.path}"}), unittest.mock.patch("os.path.isdir", return_value=False):
            self.assertEqual(mod.proc_start(31337), "Sun Nov 22 12:00:00 2026")
            self.assertIsNone(mod.proc_start(31338))
        self.assertIsNone(mod.proc_start(2**22 + 5), "no such process on Linux")
        self.assertIsNone(mod.proc_start(0 or 2**22 + 6))

    # --- a wake is sent when the thread can act on it ---
    def busy(self, **extra):
        """The environment of a thread whose turn the test controls; the watcher asks again every 0.2 s."""
        return self.t3_env(RUN_AND_WAKE_BUSY_POLL="0.2", **extra)

    def read_output_after_the_end(self, job):
        """What an agent does with a finished job: read its output file. The access time of a file read now is later than the job's end."""
        self.final_records(job, "end")
        time.sleep(0.05)  # the kernel stamps files with a clock that can trail by a few milliseconds
        (self.state / f"run-and-wake/jobs/{job}.log").read_text()

    def requires_atime(self):
        """The file system updates access times on a read (relatime does, noatime does not): without that no read can be seen and every wake goes out."""
        probe = self.root / "atime-probe"
        probe.write_text("x")
        os.utime(probe, (0, 0))
        probe.read_text()
        if probe.stat().st_atime == 0:
            self.skipTest("this file system keeps no access times, so a read cannot be seen")

    def test_busy_thread_wake_is_dropped_when_the_output_was_read(self):
        # The real case (agent-kit 259): a job that ended in under a second while the child was in a long turn, read by the child a moment later.
        # The old script sent the wake at once; T3 queued it behind the turn and ran it as a new turn that replaced the final report.
        self.requires_atime()
        self.thread_in_a_turn()
        job = self.job_id(self.launch("--", "sh", "-c", "exit 64", env=self.busy()))
        self.read_output_after_the_end(job)
        time.sleep(0.5)
        self.assertEqual(self.t3_sends(), [], "nothing is queued behind the turn")
        self.leave_the_turn()
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "skip")
        self.assertEqual(records[-1]["reason"], "seen")
        self.assertGreater(records[-1]["held_s"], 0, "the wake was held for the turn")
        self.assertEqual(self.t3_sends(), [], "and never sent")

    def test_busy_thread_wake_waits_for_the_turn_to_end_and_is_sent_if_unread(self):
        self.thread_in_a_turn()
        job = self.job_id(self.launch("--", "true", env=self.busy()))
        self.final_records(job, "end")
        time.sleep(0.8)
        self.assertEqual(self.t3_sends(), [], "nothing is sent while the turn runs")
        self.assertGreater(len(self.t3_shows()), 2, "the watcher keeps asking")
        self.assertEqual(self.t3_shows()[0].split()[:3], ['["thread",', '"show",', '"--json",'], "it asks for the JSON")
        self.leave_the_turn()
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "wake")
        self.assertEqual([records[-1]["result"], len(self.t3_sends())], ["sent", 1], "one send, after the turn")
        self.assertGreater(records[-1]["held_s"], 0)

    def test_idle_thread_wake_is_dropped_when_the_output_was_read_inside_the_window(self):
        self.requires_atime()
        job = self.job_id(self.launch("--", "true", env=self.busy(RUN_AND_WAKE_COALESCE="1.5")))
        self.read_output_after_the_end(job)
        records = self.replay(job)
        self.assertReplay(records, "start", "end", "skip")
        self.assertEqual(records[-1]["reason"], "seen")
        self.assertNotIn("held_s", records[-1], "the thread was not in a turn")
        self.assertEqual(self.t3_sends(), [])

    def test_a_burst_sends_the_job_that_was_not_read_and_drops_the_one_that_was(self):
        self.requires_atime()
        env = self.busy(RUN_AND_WAKE_COALESCE="1.5")
        read = self.job_id(self.launch("--", "true", env=env))
        unread = self.job_id(self.launch("--", "sh", "-c", "exit 4", env=env))
        self.read_output_after_the_end(read)
        self.assertEqual(self.replay(read)[-1]["reason"], "seen")
        self.assertEqual(self.replay(unread)[-1]["result"], "sent")
        (text,) = self.texts()
        self.assertIn(f"k:{unread}]", text)
        self.assertNotIn(f"k:{read}]", text)

    def test_stopped_job_on_a_busy_thread_is_dropped_when_read(self):
        # The third real case: the agent stopped its own job (SIGTERM), then read the output; the wake ran 40 minutes later as a stale turn.
        self.requires_atime()
        self.thread_in_a_turn()
        cmd, _ = self.held_job()
        result = self.launch("--", *cmd, env=self.busy(RUN_AND_WAKE_COALESCE="60"))
        job = self.job_id(result)
        os.killpg(os.getpgid(int(result.stdout.split(", pid ")[1].split(",")[0])), signal.SIGTERM)
        self.read_output_after_the_end(job)
        self.assertEqual(self.t3_sends(), [])
        self.leave_the_turn()
        records = self.replay(job)
        self.assertEqual([r["event"] for r in records], ["start", "end", "skip"])
        self.assertEqual(records[1]["stopped"], ["SIGTERM"])
        self.assertEqual(records[-1]["reason"], "seen")

    def test_a_wait_during_the_hold_still_drops_the_wake_as_waited(self):
        self.thread_in_a_turn()
        cmd, release = self.held_job()
        job = self.job_id(self.launch("--", *cmd, env=self.busy()))
        release.write_text("")
        self.final_records(job, "end")
        out = subprocess.run([sys.executable, str(SCRIPT), "--wait", job], env={**self.env, **self.t3_env()}, cwd=self.root, text=True, capture_output=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.leave_the_turn()
        self.assertEqual(self.replay(job)[-1]["reason"], "waited")
        self.assertEqual(self.t3_sends(), [])

    def test_unknown_thread_state_sends_the_wake(self):
        for name, setup in (("show fails", lambda: (self.fake / "t3_show_fail").write_text("")),
                            ("prints nothing", lambda: (self.fake / "t3_show_raw").write_text("")),
                            ("prints text", lambda: (self.fake / "t3_show_raw").write_text("not json")),
                            ("prints another shape", lambda: (self.fake / "t3_show_raw").write_text('{"thread": {}}')),
                            ("no active run", lambda: (self.fake / "t3_show_raw").write_text('{"thread": {"activeRunId": null}}'))):
            with self.subTest(name):
                for stale in ("t3_show_fail", "t3_show_raw"):
                    (self.fake / stale).unlink(missing_ok=True)
                setup()
                before = len(self.t3_sends())
                job = self.job_id(self.launch("--", "true", env=self.busy()))
                records = self.replay(job)
                self.assertEqual([r["event"] for r in records], ["start", "end", "wake"])
                self.assertNotIn("held_s", records[-1])
                self.assertEqual(len(self.t3_sends()), before + 1)

    def test_a_read_before_the_job_ended_does_not_drop_the_wake(self):
        self.requires_atime()
        script = f"echo started; while [ ! -f {self.root}/release ]; do sleep 0.05; done; echo done"
        job = self.job_id(self.launch("--", "sh", "-c", script, env=self.busy()))
        output = self.state / f"run-and-wake/jobs/{job}.log"
        end = time.monotonic() + 10
        while "started" not in (output.read_text() if output.exists() else "") and time.monotonic() < end:
            time.sleep(0.05)
        (self.root / "release").write_text("")  # the agent looked at the running job; the job then ended and nobody read it again
        records = self.replay(job)
        self.assertEqual([records[-1]["event"], records[-1]["result"]], ["wake", "sent"])
        self.assertEqual(len(self.t3_sends()), 1)

    def test_the_busy_poll_setting(self):
        spec = importlib.machinery.SourceFileLoader("run_and_wake_mod", str(SCRIPT))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("run_and_wake_mod", spec))
        spec.exec_module(mod)
        for setting, want in ((None, 30.0), ("", 30.0), ("0.2", 0.2), ("abc", 30.0), ("0", 30.0), ("-1", 30.0)):
            with self.subTest(setting=setting):
                old = os.environ.pop("RUN_AND_WAKE_BUSY_POLL", None)
                if setting is not None:
                    os.environ["RUN_AND_WAKE_BUSY_POLL"] = setting
                try:
                    self.assertEqual(mod.busy_poll(), want)
                finally:
                    os.environ.pop("RUN_AND_WAKE_BUSY_POLL", None)
                    if old is not None:
                        os.environ["RUN_AND_WAKE_BUSY_POLL"] = old

    def test_usage(self):
        for args in ([], ["--"], ["--log", "x", "--", "true"]):
            with self.subTest(args=args):
                result = self.launch(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("Usage: run-and-wake", result.stderr)
        self.assertFalse(self.log.exists(), "no job was started")


if __name__ == "__main__":
    unittest.main()
