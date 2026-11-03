"""Tests for the memory watchdog: dot_local/bin/executable_heavy-gate-watchdog (the daemon) and heavy-gate's report of its stop.

HEAVY_GATE_WATCHDOG_SCRIPT points the suite at a mutated copy of the daemon (see test_mutation_*).

Real processes throughout: real heavy-gate jobs (real process trees, real `ps`), and the daemon's real loop run directly, not through
launchd. Only the host's memory figure is scripted: memory_pressure (and sysctl, uname) are small fakes first on PATH that print what
the test wrote to files. `ps` is faked only to make it fail.
"""
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_heavy_gate import FAKES, QUIET, SCRIPT

REPO = Path(__file__).resolve().parents[2]
DAEMON = Path(os.environ.get("HEAVY_GATE_WATCHDOG_SCRIPT") or REPO / "dot_local/bin/executable_heavy-gate-watchdog")

# mp_seq, when a test writes it, scripts the readings: one line per call, the last repeating; FAIL exits 1, EMPTY prints nothing
MEMORY_PRESSURE = '''if [ -f "$FAKE/mp_seq" ]; then
  line=$(head -n 1 "$FAKE/mp_seq")
  if [ $(wc -l < "$FAKE/mp_seq") -gt 1 ]; then sed 1d "$FAKE/mp_seq" > "$FAKE/mp_seq.tmp"; mv "$FAKE/mp_seq.tmp" "$FAKE/mp_seq"; fi
  case $line in FAIL) exit 1 ;; EMPTY) ;; *) echo "$line" ;; esac
else cat "$FAKE/memory_pressure"; fi'''
FAILING_PS = '''if [ -f "$FAKE/ps_fail" ]; then echo "ps: boom" >&2; exit 1; fi
exec /bin/ps "$@"'''

# about 80 MB resident, so its tree is far bigger than a sleeping shell's
BIG = f"exec {sys.executable} -c \"import time; x = b'x' * (80 * 1024 * 1024); open('ready.big', 'w').close(); time.sleep(120)\""
SMALL = "exec sleep 120"


class WatchdogBase(unittest.TestCase):
    LOW = "System-wide memory free percentage: 4%"
    OK = "System-wide memory free percentage: 62%"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = self.root / "fake"
        self.fake.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.psbin = self.root / "psbin"
        self.psbin.mkdir()
        for name, body in {**FAKES, "memory_pressure": MEMORY_PRESSURE}.items():
            (self.bin / name).write_text(f"#!/bin/sh\n{body}\n")
            (self.bin / name).chmod(0o755)
        (self.psbin / "ps").write_text(f"#!/bin/sh\n{FAILING_PS}\n")
        (self.psbin / "ps").chmod(0o755)
        self.set(**QUIET)
        host_path = [d for d in os.environ["PATH"].split(":") if not (Path(d) / "workstream-rank").exists()]
        env = {k: v for k, v in os.environ.items() if not k.startswith("HEAVY_GATE_") and k not in ("HERDR_PANE_ID", "WORKSTREAM_RANK_FILE")}
        self.env = {**env, "PATH": ":".join([str(self.bin), *host_path]), "FAKE": str(self.fake), "HEAVY_GATE_LOCK": str(self.root / "heavy-gate.lock"),
                    "HEAVY_GATE_CHECK_WINDOW": "1", "HEAVY_GATE_POLL": "1", "HEAVY_GATE_PRIORITIES": str(self.root / "priorities"),
                    "HEAVY_GATE_SLOTS_FILE": str(self.root / "slots"), "WORKSTREAM_RANK_FILE": str(self.root / "rank"),
                    "HEAVY_GATE_WATCH_POLL": "1", "HEAVY_GATE_STOP_GRACE": "3"}
        self.lock = self.root / "heavy-gate.lock"
        self.procs = []
        self.addCleanup(self.reap)

    def set(self, **figures):
        for key, value in figures.items():
            (self.fake / key).write_text(value + "\n")

    def readings(self, *lines):
        """From now on the fake memory_pressure prints these, one per call, the last one repeating."""
        new = self.fake / "mp_seq.new"
        new.write_text("\n".join(lines) + "\n")
        new.rename(self.fake / "mp_seq")

    def reap(self):
        """A failed test must leave nothing running: KILL every process group and pid the test started or its jobs named."""
        for proc in self.procs:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            if proc.poll() is None:
                proc.kill()
            proc.wait()
        for path in self.root.glob("pid*"):
            self.kill_quietly(path)
        for path in self.root.glob("child*"):
            self.kill_quietly(path)
        for path in self.root.glob("bystander*"):
            self.kill_quietly(path)

    @staticmethod
    def kill_quietly(path):
        try:
            os.kill(int(path.read_text()), signal.SIGKILL)
        except (OSError, ValueError):
            pass

    def wait_for(self, condition, seconds=10):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if condition():
                return True
            time.sleep(0.05)
        return False

    @staticmethod
    def alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def gone_soon(self, *pids, seconds=20):
        for pid in pids:
            self.assertTrue(self.wait_for(lambda: not self.alive(pid), seconds), f"pid {pid} is gone")

    def pid_of(self, name):
        path = self.root / name
        self.assertTrue(self.wait_for(lambda: path.exists() and path.read_text().strip() != ""), f"{name} was written")
        return int(path.read_text())

    # --- heavy-gate jobs ---
    def gate(self, name, body):
        """A heavy-gate job (a real process tree under a real heavy-gate) running `body`; returns once it is running."""
        job_file = self.root / f"job.{name}.sh"
        job_file.write_text(f"cd {self.root}\ntouch started.{name}\n{body}\n")
        err = open(self.root / f"{name}.err", "w")
        self.addCleanup(err.close)
        proc = subprocess.Popen(["sh", str(SCRIPT), "--", "sh", str(job_file)], env=self.env, stdout=subprocess.DEVNULL, stderr=err, start_new_session=True)
        self.procs.append(proc)
        self.assertTrue(self.wait_for(lambda: (self.root / f"started.{name}").exists(), 20), f"{name} is running")
        return proc

    def err(self, name):
        return (self.root / f"{name}.err").read_text()

    # --- the daemon ---
    def daemon(self, env=None, **popen):
        log = open(self.root / "daemon.log", "a")
        self.addCleanup(log.close)
        popen.setdefault("stdout", log)
        popen.setdefault("stderr", log)
        proc = subprocess.Popen(["sh", str(DAEMON)], env={**self.env, **(env or {})}, start_new_session=True, **popen)
        self.procs.append(proc)
        return proc

    def daemon_log(self):
        return (self.root / "daemon.log").read_text()


class Watchdog(WatchdogBase):
    # --- which job is stopped, and when ---
    def test_only_the_largest_tree_stops_while_memory_stays_low(self):
        # the small job is first (slot 1): picking "the first tree" would stop it first
        small = self.gate("small", SMALL)
        big = self.gate("big", BIG)
        self.assertTrue(self.wait_for((self.root / "ready.big").exists, 20), "the big job has its memory")
        self.daemon()
        self.set(memory_pressure=self.LOW)
        big.wait(timeout=30)
        stopped_big = time.monotonic()
        self.assertEqual(big.returncode, 137, self.err("big"))
        time.sleep(1.2)  # one poll later
        self.assertIsNone(small.poll(), "the smaller job is still alive one poll later")
        small.wait(timeout=30)
        self.assertEqual(small.returncode, 137, self.err("small"))
        self.assertGreater(time.monotonic() - stopped_big, 1.0, "it took two more low readings")
        lines = [l for l in self.daemon_log().splitlines() if "stopped pid" in l]
        self.assertEqual(len(lines), 2, self.daemon_log())
        self.assertIn(f"(heavy-gate {big.pid}): free memory 4%, tree RSS ", lines[0])
        self.assertIn(f"(heavy-gate {small.pid}): free memory 4%, tree RSS ", lines[1])
        self.assertRegex(lines[0], r"heavy-gate-watchdog stopped pid \d+ \(heavy-gate \d+\): free memory 4%, tree RSS \d+ MB: sh .*job\.big\.sh")
        self.assertFalse(list(self.root.glob("heavy-gate.lock.stopped.*")), "no marker is left behind")

    def test_heavy_gate_says_the_watchdog_stopped_the_job_and_exits_137(self):
        job = self.gate("big", BIG)
        self.assertTrue(self.wait_for((self.root / "ready.big").exists, 20))
        self.daemon()
        self.set(memory_pressure=self.LOW)
        job.wait(timeout=30)
        err = self.err("big")
        self.assertEqual(job.returncode, 137, err)
        self.assertEqual(err.count("the memory watchdog"), 1, err)
        self.assertIn("[heavy-gate] ERROR: the memory watchdog (heavy-gate-watchdog) stopped this job; exit 137 is not a failure of the job itself: free memory 4% (floor 10%), tree RSS ", err)

    def test_a_single_low_reading_does_nothing(self):
        job = self.gate("a", "sleep 6\nexit 5")
        self.daemon()
        self.readings(self.LOW, self.OK)
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 5, self.err("a"))
        self.assertNotIn("stopped pid", self.daemon_log())
        self.assertNotIn("the memory watchdog", self.err("a"))

    def test_low_readings_that_are_not_in_a_row_do_nothing(self):
        job = self.gate("a", "sleep 7\nexit 5")
        self.daemon()
        self.readings(self.LOW, self.OK, self.LOW, self.OK, self.LOW, self.OK)
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 5, self.err("a"))
        self.assertNotIn("stopped pid", self.daemon_log())

    def test_an_unreadable_reading_does_nothing_and_breaks_a_run_of_low_ones(self):
        job = self.gate("a", "sleep 8\nexit 6")
        d = self.daemon()
        self.readings("FAIL", "EMPTY", "System-wide memory free percentage: lots%", self.LOW, "FAIL", self.LOW, "EMPTY", self.OK)
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 6, self.err("a"))
        self.assertIsNone(d.poll(), "the daemon is still running")
        self.assertNotIn("stopped pid", self.daemon_log())

    def test_nothing_is_stopped_while_no_job_holds_the_gate(self):
        bystander = subprocess.Popen(["sleep", "300"], start_new_session=True)
        self.procs.append(bystander)
        d = self.daemon()
        self.set(memory_pressure=self.LOW)
        time.sleep(4.5)
        self.assertIsNone(bystander.poll(), "a process that is not under a holder is left alone")
        self.assertIsNone(d.poll())
        self.assertNotIn("stopped pid", self.daemon_log())

    def test_processes_that_are_not_under_a_holder_are_left_alone_even_if_bigger(self):
        bystander = subprocess.Popen([sys.executable, "-c", "import time; x = b'x' * (200 * 1024 * 1024); time.sleep(300)"], start_new_session=True)
        self.procs.append(bystander)
        small = self.gate("small", SMALL)
        time.sleep(1)
        self.daemon()
        self.set(memory_pressure=self.LOW)
        small.wait(timeout=30)
        self.assertEqual(small.returncode, 137, self.err("small"))
        time.sleep(3)  # two more polls with memory still low and no holder left
        self.assertIsNone(bystander.poll(), "the bigger process outside the gate was not touched")

    # --- how it stops a tree ---
    def test_a_job_that_handles_term_runs_its_trap(self):
        marker = self.root / "trapped"
        job = self.gate("a", f"trap 'echo trapped > {marker}; exit 0' TERM\nwhile :; do sleep 0.1; done")
        self.daemon(env={"HEAVY_GATE_STOP_GRACE": "10"})
        self.set(memory_pressure=self.LOW)
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 137, "exit 137 whatever the trap's status")
        self.assertEqual(marker.read_text().strip(), "trapped")

    def test_a_process_that_ignores_term_is_killed_after_the_grace_period(self):
        job = self.gate("a", "trap '' TERM\necho $$ > pid.a\n(trap '' TERM; exec sleep 300) &\necho $! > child.a\nwait")
        pid, child = self.pid_of("pid.a"), self.pid_of("child.a")
        self.daemon()
        began = time.monotonic()
        self.set(memory_pressure=self.LOW)
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 137, self.err("a"))
        self.assertGreaterEqual(time.monotonic() - began, 4.5, "two readings (about 2 s) plus the 3 s grace period")
        self.gone_soon(pid, child)

    def test_a_child_whose_parent_died_on_term_is_still_killed(self):
        # the parent exits on TERM, so the child is re-parented to launchd (no longer under the holder), and it ignores TERM
        job = self.gate("a", "(trap '' TERM; exec sleep 300) &\necho $! > child.a\ntrap 'exit 0' TERM\nwait")
        child = self.pid_of("child.a")
        self.daemon()
        self.set(memory_pressure=self.LOW)
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 137, self.err("a"))
        self.gone_soon(child, seconds=10)

    # --- the daemon survives its own trouble ---
    def stop_one_job(self, d, name="a"):
        self.set(memory_pressure=self.OK)  # a start needs memory free
        job = self.gate(name, SMALL)
        self.set(memory_pressure=self.LOW)
        job.wait(timeout=30)
        return job

    def test_the_daemon_survives_a_closed_pipe_on_stdout_and_stderr(self):
        d = self.daemon(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        d.stdout.close()
        d.stderr.close()
        job = self.stop_one_job(d)
        self.assertEqual(job.returncode, 137, self.err("a"))
        self.assertIn("free memory 4%", self.err("a"), "the marker was written even though the log line could not be")
        self.assertIsNone(d.poll(), "the daemon is still running")
        job = self.stop_one_job(d, "b")
        self.assertEqual(job.returncode, 137, "and it stops the next job too")

    def test_the_daemon_survives_closed_stdout_and_stderr_descriptors(self):
        proc = subprocess.Popen(["sh", "-c", 'exec sh "$0" >&- 2>&-', str(DAEMON)], env=self.env, start_new_session=True, stdin=subprocess.DEVNULL)
        self.procs.append(proc)
        job = self.stop_one_job(proc)
        self.assertEqual(job.returncode, 137, self.err("a"))
        self.assertIn("free memory 4%", self.err("a"))
        self.assertIsNone(proc.poll())

    def test_a_failing_ps_does_nothing_and_the_daemon_carries_on(self):
        job = self.gate("a", SMALL)
        d = self.daemon(env={"PATH": f"{self.psbin}:{self.env['PATH']}"})
        (self.fake / "ps_fail").write_text("")
        self.set(memory_pressure=self.LOW)
        time.sleep(5)
        self.assertIsNone(job.poll(), "the job was not touched while ps failed")
        self.assertIsNone(d.poll(), "the daemon survived")
        (self.fake / "ps_fail").unlink()
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 137, self.err("a"))

    def test_the_settings_must_be_whole_numbers(self):
        for var, value in (("WATCH_POLL", "fast"), ("WATCH_POLL", "0"), ("WATCH_POLL", "1.5"), ("STOP_FREE_PCT", "ten"), ("STOP_GRACE", "-1"), ("STOP_GRACE", "1234567")):
            with self.subTest(var, value=value):
                r = subprocess.run(["sh", str(DAEMON)], env={**self.env, f"HEAVY_GATE_{var}": value}, capture_output=True, text=True, timeout=20)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn(f"HEAVY_GATE_{var} must be", r.stderr)
        d = self.daemon(env={"HEAVY_GATE_WATCH_POLL": "01", "HEAVY_GATE_STOP_FREE_PCT": "08", "HEAVY_GATE_STOP_GRACE": "09"})
        time.sleep(1.5)
        self.assertIsNone(d.poll(), "leading zeros are decimal, not octal")

    # --- heavy-gate's side ---
    def test_heavy_gate_reports_a_stop_by_the_watchdog_and_exits_137(self):
        # the daemon's marker, written by the job for its parent (heavy-gate) just before it dies of TERM
        job = self.gate("a", f"echo 'free memory 4% (floor 10%), tree RSS 80 MB, pid 1' > {self.root}/heavy-gate.lock.stopped.$PPID\nkill -TERM $$")
        job.wait(timeout=30)
        err = self.err("a")
        self.assertEqual(job.returncode, 137, err)
        self.assertIn("[heavy-gate] ERROR: the memory watchdog (heavy-gate-watchdog) stopped this job; exit 137 is not a failure of the job itself: free memory 4% (floor 10%), tree RSS 80 MB, pid 1", err)
        self.assertFalse(list(self.root.glob("heavy-gate.lock.stopped.*")), "heavy-gate removes the marker")

    def test_without_the_marker_heavy_gate_exits_with_the_jobs_own_status(self):
        job = self.gate("a", "kill -TERM $$")
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 143, self.err("a"))
        self.assertNotIn("memory watchdog", self.err("a"))
        job = self.gate("b", "exit 3")
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 3)

    def test_a_group_sigkill_of_the_caller_still_kills_the_job(self):
        # Pi's process.kill(-pid, SIGKILL): the job is in the caller's process group, as on main
        job = self.gate("a", "echo $$ > pid.a\n(exec sleep 300) &\necho $! > child.a\nwait")
        pid, child = self.pid_of("pid.a"), self.pid_of("child.a")
        os.killpg(job.pid, signal.SIGKILL)
        job.wait(timeout=10)
        self.gone_soon(pid, child, seconds=10)

    # --- the suite catches a daemon that picks wrongly ---
    def test_mutation_always_picking_the_first_tree_is_caught(self):
        src = DAEMON.read_text()
        old = 'if (best == "" || total > bestrss) {'
        self.assertIn(old, src, "the selection line the mutation replaces")
        mutant = self.root / "mutant"
        mutant.write_text(src.replace(old, 'if (best == "") {'))
        r = subprocess.run([sys.executable, "-m", "unittest", "test_watchdog.Watchdog.test_only_the_largest_tree_stops_while_memory_stays_low"],
                           cwd=Path(__file__).parent, env={**os.environ, "HEAVY_GATE_WATCHDOG_SCRIPT": str(mutant)}, capture_output=True, text=True, timeout=180)
        self.assertNotEqual(r.returncode, 0, "the mutant passed the largest-tree test:\n" + r.stderr)
        self.assertIn("FAILED", r.stderr)


class Install(unittest.TestCase):
    PLIST = REPO / "Library/LaunchAgents/local.heavy-gate-watchdog.plist.tmpl"
    LOAD = REPO / "run_onchange_after_72_heavy_gate_watchdog_launchd.sh.tmpl"

    def render(self, path):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "chezmoi.yaml"
            cfg.write_text("data:\n  profile: personal\n")
            r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                               input=path.read_text(), capture_output=True, text=True, timeout=60, env={**os.environ, "HOME": tmp})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
    def test_the_plist_runs_the_daemon_forever_and_logs_to_library_logs(self):
        plist = plistlib.loads(self.render(self.PLIST).encode())
        self.assertEqual(plist["Label"], "local.heavy-gate-watchdog")
        self.assertIs(plist["KeepAlive"], True)
        self.assertIs(plist["RunAtLoad"], True)
        self.assertEqual(plist["ProgramArguments"][0], "/bin/sh")
        self.assertTrue(plist["ProgramArguments"][1].endswith("/.local/bin/heavy-gate-watchdog"), plist["ProgramArguments"])
        for key in ("StandardOutPath", "StandardErrorPath"):
            self.assertIn("/Library/Logs/", plist[key])
        self.assertNotIn("StartInterval", plist)

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
    def test_the_load_script_renders_loads_the_agent_and_reruns_when_the_daemon_changes(self):
        script = self.render(self.LOAD)
        r = subprocess.run(["sh", "-n"], input=script, text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("local.heavy-gate-watchdog", script)
        self.assertIn("launchctl bootstrap", script)
        self.assertIn("launchctl bootout", script)
        # run_onchange: the rendered text must change when the plist or the daemon does
        import hashlib
        for source in (self.PLIST, REPO / "dot_local/bin/executable_heavy-gate-watchdog"):
            self.assertIn(hashlib.sha256(source.read_bytes()).hexdigest(), script, source.name)

    def test_the_daemon_is_not_deployed_off_macos(self):
        ignore = (REPO / ".chezmoiignore").read_text()
        for name in (".local/bin/heavy-gate-watchdog", "Library/LaunchAgents/local.heavy-gate-watchdog.plist", "72_heavy_gate_watchdog_launchd.sh"):
            self.assertIn(name, ignore)


if __name__ == "__main__":
    unittest.main()
