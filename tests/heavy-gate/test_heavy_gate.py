"""Black-box tests for dot_local/bin/executable_heavy-gate.

The real script runs as a real process. Only the host's figures are scripted: sysctl, memory_pressure, vm_stat and uname are
small fakes first on PATH that print whatever the test wrote to files, so a busy or quiet Mac can be simulated on any machine.
"""
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "dot_local/bin/executable_heavy-gate"

FAKES = {
    "uname": 'echo Darwin',
    "sysctl": '''case "$2" in
  vm.loadavg) cat "$FAKE/loadavg" ;;
  vm.swapusage) cat "$FAKE/swapusage" ;;
  kern.memorystatus_vm_pressure_level) v=$(cat "$FAKE/pressure"); echo "$v"; echo read >> "$FAKE/pressure_reads" ;;
esac''',
    "memory_pressure": 'cat "$FAKE/memory_pressure"',
    "vm_stat": '''[ -f "$FAKE/on_vm_stat" ] && sh "$FAKE/on_vm_stat"
n=$(cat "$FAKE/swapouts")
[ -f "$FAKE/swapouts_step" ] && echo $((n + $(cat "$FAKE/swapouts_step"))) > "$FAKE/swapouts"
echo "Swapouts:      $n."''',
}

QUIET = {
    "loadavg": "{ 2.10 3.00 4.00 }",
    "swapusage": "total = 8192.00M  used = 1000.00M  free = 7192.00M  (encrypted)",
    "pressure": "1",
    "memory_pressure": "System-wide memory free percentage: 62%",
    "swapouts": "5000",
}


class HeavyGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.fake = root / "fake"
        self.fake.mkdir()
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for name, body in FAKES.items():
            (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
            (bin_dir / name).chmod(0o755)
        self.set(**QUIET)
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE": str(self.fake), "HEAVY_GATE_LOCK": str(root / "heavy-gate.lock"),
                    "HEAVY_GATE_SWAP_WINDOW": "1", "HEAVY_GATE_POLL": "1"}
        self.lock = root / "heavy-gate.lock"

    def set(self, **figures):
        for key, value in figures.items():
            (self.fake / key).write_text(value + "\n")

    def gate(self, *args, timeout=30):
        return subprocess.run(["sh", str(SCRIPT), *args], env=self.env, text=True, capture_output=True, timeout=timeout)

    def start(self, *args):
        return subprocess.Popen(["sh", str(SCRIPT), *args], env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)

    def wait_for(self, condition, seconds=10):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if condition():
                return True
            time.sleep(0.05)
        return False

    # --- one check ---
    def test_quiet_host_is_allowed(self):
        result = self.gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[heavy-gate] INFO: allowed", result.stderr)

    def test_each_rule_refuses_on_its_own(self):
        cases = [
            ({"loadavg": "{ 12.40 9.00 5.00 }"}, "load1 12.40 (needs < 8)"),
            ({"loadavg": "{ 8.00 1.00 1.00 }"}, "load1 8.00 (needs < 8)"),
            ({"swapusage": "total = 8192.00M  used = 7692.00M  free = 500.00M  (encrypted)"}, "swap free 500 MB"),
            ({"pressure": "2"}, "memory pressure level 2"),
            ({"memory_pressure": "System-wide memory free percentage: 20%"}, "memory free 20%"),
            ({"loadavg": ""}, "load1 unreadable"),
            ({"memory_pressure": ""}, "memory free unreadable"),
            ({"loadavg": "{ nonsense 1 1 }"}, "load1 nonsense"),
            ({"memory_pressure": "System-wide memory free percentage: lots%"}, "memory free lots%"),
            ({"swapusage": "total = 1M  used = 1M  free = lots  (encrypted)"}, "swap free"),
            ({"swapusage": "total = 9000M  used = 1M  free = 2000oops  (encrypted)"}, "swap free unreadable"),
        ]
        for figures, expected in cases:
            with self.subTest(expected):
                self.set(**QUIET)
                self.set(**figures)
                result = self.gate()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f"refused: {expected}", result.stderr)

    def test_swapouts_rising_refuses_and_flat_allows(self):
        self.set(swapouts="5000")
        (self.fake / "swapouts_step").write_text("40\n")
        result = self.gate()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Swapouts rose", result.stderr)
        (self.fake / "swapouts_step").unlink()
        self.assertEqual(self.gate().returncode, 0)

    def test_malformed_swapouts_refuse(self):
        for value in ("", "many", "5x", "5.0"):
            with self.subTest(value):
                self.set(swapouts=value)
                result = self.gate()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("Swapouts unreadable", result.stderr)

    def test_a_host_that_gets_busy_during_the_watch_is_refused(self):
        # the cheap rules are read again after the Swapouts window: a host that was quiet a minute ago is not enough
        (self.fake / "on_vm_stat").write_text('echo "{ 30.00 20.00 10.00 }" > "$FAKE/loadavg"\n')
        result = self.gate()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("load1 30.00", result.stderr)

    def test_a_bad_window_or_poll_is_a_usage_error(self):
        for name in ("HEAVY_GATE_SWAP_WINDOW", "HEAVY_GATE_POLL"):
            with self.subTest(name):
                self.env[name] = "soon"
                result = self.gate()
                self.assertEqual(result.returncode, 2, result.stderr)
                self.env[name] = "1"

    def test_every_broken_rule_is_reported(self):
        self.set(loadavg="{ 40.00 20.00 10.00 }", pressure="4", memory_pressure="System-wide memory free percentage: 5%")
        result = self.gate()
        self.assertEqual(result.returncode, 1)
        for expected in ("load1 40.00", "memory pressure level 4", "memory free 5%"):
            self.assertIn(expected, result.stderr)

    def test_swap_free_is_read_in_gigabytes_too(self):
        self.set(swapusage="total = 8.00G  used = 7.50G  free = 0.50G  (encrypted)")
        self.assertIn("swap free 512 MB", self.gate().stderr)
        self.set(swapusage="total = 8.00G  used = 6.00G  free = 2.00G  (encrypted)")
        self.assertEqual(self.gate().returncode, 0)

    # --- running a command ---
    def test_runs_the_command_on_a_quiet_host_and_passes_its_status_through(self):
        marker = Path(self.tmp.name) / "ran"
        result = self.gate("--", "sh", "-c", f"echo heavy > {marker}; echo out; exit 7")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertEqual(marker.read_text().strip(), "heavy")
        self.assertIn("out", result.stdout)
        self.assertFalse(self.lock.is_symlink(), "the gate is released when the command ends")

    def test_does_not_run_the_command_on_a_busy_host(self):
        self.set(loadavg="{ 30.00 20.00 10.00 }")
        marker = Path(self.tmp.name) / "ran"
        result = self.gate("--", "touch", str(marker))
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertFalse(marker.exists(), "a refused job must not start")
        self.assertIn("load1 30.00", result.stderr)

    def test_waits_for_the_host_to_quiet_down_then_runs(self):
        self.set(loadavg="{ 30.00 20.00 10.00 }")
        marker = Path(self.tmp.name) / "ran"
        job = self.start("--wait", "20", "--", "touch", str(marker))
        time.sleep(2.5)
        self.assertIsNone(job.poll(), "still waiting while the host is busy")
        self.assertFalse(marker.exists())
        self.set(loadavg="{ 1.00 5.00 9.00 }")
        job.communicate(timeout=20)
        self.assertEqual(job.returncode, 0)
        self.assertTrue(marker.exists())

    def test_gives_up_after_the_wait(self):
        self.set(pressure="4")
        started = time.monotonic()
        result = self.gate("--wait", "2", "--", "true")
        self.assertEqual(result.returncode, 75)
        self.assertGreaterEqual(time.monotonic() - started, 1)  # the deadline is in whole seconds
        self.assertIn("still refused after 2s", result.stderr)

    # --- one at a time ---
    def test_only_one_heavy_job_at_a_time(self):
        started = Path(self.tmp.name) / "started"
        release = Path(self.tmp.name) / "release"
        first = self.start("--", "sh", "-c", f"touch {started}; while [ ! -f {release} ]; do sleep 0.1; done")
        try:
            self.assertTrue(self.wait_for(started.exists), "the first job is running")
            self.assertTrue(self.lock.is_symlink(), "the first job holds the gate")
            second = self.gate("--", "true")
            self.assertEqual(second.returncode, 75)
            self.assertIn("another heavy job holds the gate", second.stderr)
            self.assertIn("another heavy job holds the gate", self.gate().stderr)
        finally:
            release.write_text("")
            first.communicate(timeout=20)
        self.assertEqual(self.gate("--", "true").returncode, 0, "the gate is free once the first job is done")

    def test_a_dead_holders_lock_is_cleared(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        os.symlink(str(dead.pid), self.lock)
        self.assertEqual(self.gate("--", "true").returncode, 0)

    def test_two_jobs_racing_for_a_dead_holders_lock_never_overlap(self):
        # both read the same dead pid; only one may clear it and take the gate
        self.env["HEAVY_GATE_SWAP_WINDOW"] = "0"
        self.env["HEAVY_GATE_POLL"] = "1"
        log = Path(self.tmp.name) / "log"
        job = f"echo start >> {log}; sleep 0.4; echo end >> {log}"
        for _ in range(8):
            log.write_text("")
            dead = subprocess.Popen(["true"])
            dead.wait()
            if self.lock.is_symlink():
                self.lock.unlink()
            os.symlink(str(dead.pid), self.lock)
            jobs = [self.start("--wait", "20", "--", "sh", "-c", job) for _ in range(2)]
            for j in jobs:
                j.communicate(timeout=30)
                self.assertEqual(j.returncode, 0)
            self.assertEqual(log.read_text().split(), ["start", "end", "start", "end"], "the two jobs ran one after the other")

    def test_a_left_over_guard_is_refused_with_a_hint_and_nothing_runs(self):
        guard = Path(str(self.lock) + ".guard")
        guard.mkdir()
        marker = Path(self.tmp.name) / "ran"
        result = self.gate("--", "touch", str(marker))
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn("could not get the gate guard", result.stderr)
        self.assertFalse(marker.exists())
        self.assertTrue(guard.is_dir(), "a guard this run did not make is left alone")

    def test_the_guard_is_not_left_behind(self):
        self.assertEqual(self.gate("--", "true").returncode, 0)
        self.assertFalse(Path(str(self.lock) + ".guard").exists())

    def test_no_new_try_starts_at_the_deadline(self):
        # one try fails; the host is quiet again by the time the nap ends, but the deadline has passed, so nothing runs
        self.env["HEAVY_GATE_POLL"] = "5"
        self.set(pressure="4")
        marker = Path(self.tmp.name) / "ran"
        job = self.start("--wait", "2", "--", "touch", str(marker))
        try:
            self.assertTrue(self.wait_for(lambda: (self.fake / "pressure_reads").exists()), "the first try has read the busy host")
            self.set(pressure="1")
            job.communicate(timeout=30)
        finally:
            if job.poll() is None:
                job.kill()
                job.communicate()
        self.assertEqual(job.returncode, 75)
        self.assertFalse(marker.exists())

    def test_the_gate_is_released_when_the_job_is_killed(self):
        pidfile = Path(self.tmp.name) / "pid"
        job = self.start("--", "sh", "-c", f"echo $$ > {pidfile}; sleep 30")
        self.assertTrue(self.wait_for(pidfile.exists), "the heavy command started")
        self.assertTrue(self.wait_for(lambda: pidfile.read_text().strip() != ""))
        command = int(pidfile.read_text())
        self.assertTrue(self.lock.is_symlink())
        os.killpg(job.pid, signal.SIGTERM)  # what Pi's process-tree kill does: the wrapper and everything under it
        job.communicate(timeout=20)
        self.assertEqual(job.returncode, 143)
        self.assertFalse(self.wait_for(lambda: self._alive(command), 1), "the heavy command is gone")
        self.assertFalse(self.lock.is_symlink(), "the gate is released")

    @staticmethod
    def _alive(pid):
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False

    # --- usage ---
    def test_bad_arguments_exit_2(self):
        self.assertEqual(self.gate("--wait").returncode, 2)
        self.assertEqual(self.gate("--wait", "soon", "--", "true").returncode, 2)
        self.assertEqual(self.gate("--nope").returncode, 2)

    def test_refuses_off_macos(self):
        (Path(self.tmp.name) / "bin/uname").write_text("#!/bin/sh\necho Linux\n")
        result = self.gate()
        self.assertEqual(result.returncode, 2)
        self.assertIn("macOS only", result.stderr)


if __name__ == "__main__":
    unittest.main()
