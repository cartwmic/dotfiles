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
  kern.memorystatus_vm_pressure_level) cat "$FAKE/pressure" ;;
esac''',
    "memory_pressure": 'cat "$FAKE/memory_pressure"',
    "vm_stat": '''n=$(cat "$FAKE/swapouts")
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
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE": str(self.fake), "TMPDIR": self.tmp.name,
                    "HEAVY_GATE_SWAP_WINDOW": "1", "HEAVY_GATE_POLL": "1"}
        self.lock = root / "heavy-gate.lock"

    def set(self, **figures):
        for key, value in figures.items():
            (self.fake / key).write_text(value + "\n")

    def gate(self, *args, timeout=30):
        return subprocess.run(["sh", str(SCRIPT), *args], env=self.env, text=True, capture_output=True, timeout=timeout)

    def start(self, *args):
        return subprocess.Popen(["sh", str(SCRIPT), *args], env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # --- one check ---
    def test_quiet_host_is_allowed(self):
        result = self.gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("allowed", result.stderr)

    def test_each_rule_refuses_on_its_own(self):
        cases = [
            ({"loadavg": "{ 12.40 9.00 5.00 }"}, "load1 12.40 (needs < 8)"),
            ({"loadavg": "{ 8.00 1.00 1.00 }"}, "load1 8.00 (needs < 8)"),
            ({"swapusage": "total = 8192.00M  used = 7692.00M  free = 500.00M  (encrypted)"}, "swap free 500 MB"),
            ({"pressure": "2"}, "memory pressure level 2"),
            ({"memory_pressure": "System-wide memory free percentage: 20%"}, "memory free 20%"),
            ({"loadavg": ""}, "load1 unreadable"),
            ({"memory_pressure": ""}, "memory free unreadable"),
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
        first = self.start("--", "sleep", "6")
        for _ in range(40):
            if self.lock.is_symlink():
                break
            time.sleep(0.1)
        self.assertTrue(self.lock.is_symlink(), "the first job holds the gate")
        second = self.gate("--", "true")
        self.assertEqual(second.returncode, 75)
        self.assertIn("another heavy job holds the gate", second.stderr)
        self.assertIn("another heavy job holds the gate", self.gate().stderr)
        first.communicate(timeout=20)
        self.assertEqual(self.gate("--", "true").returncode, 0, "the gate is free once the first job is done")

    def test_a_dead_holders_lock_is_cleared(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        os.symlink(str(dead.pid), self.lock)
        self.assertEqual(self.gate("--", "true").returncode, 0)

    def test_the_gate_is_released_when_the_job_is_killed(self):
        job = self.start("--", "sleep", "30")
        for _ in range(40):
            if self.lock.is_symlink():
                break
            time.sleep(0.1)
        os.killpg(os.getpgid(job.pid), 0)  # the group exists
        job.send_signal(signal.SIGTERM)
        subprocess.run(["pkill", "-TERM", "-P", str(job.pid)])  # what Pi's process-tree kill does to the children
        job.communicate(timeout=20)
        self.assertFalse(self.lock.is_symlink())

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
