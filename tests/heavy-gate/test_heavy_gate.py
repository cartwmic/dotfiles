"""Black-box tests for dot_local/bin/executable_heavy-gate.

HEAVY_GATE_SCRIPT points the suite at a mutated copy (see mutate.py).

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

SCRIPT = Path(os.environ.get("HEAVY_GATE_SCRIPT") or Path(__file__).resolve().parents[2] / "dot_local/bin/executable_heavy-gate")
# The central-rank reader the gate calls by name (dotfiles PR #76). Tests put it on PATH as workstream-rank when they want the rank on.
RANK_READER = Path(__file__).resolve().parents[2] / "dot_local/bin/executable_workstream-rank"
# The gate as it was before the second slot (PR #69), frozen: jobs already running when the new version is installed still run it.
OLD_SCRIPT = Path(__file__).resolve().parent / "heavy-gate-v69.sh"

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
        # a workstream-rank installed on this host is not on the test's PATH: tests that want one put it there
        host_path = [d for d in os.environ["PATH"].split(":") if not (Path(d) / "workstream-rank").exists()]
        # nothing from the real shell leaks in: not the gate's settings, not this pane's id or the real rank file
        env = {k: v for k, v in os.environ.items() if not k.startswith("HEAVY_GATE_") and k not in ("HERDR_PANE_ID", "WORKSTREAM_RANK_FILE")}
        self.env = {**env, "PATH": ":".join([str(bin_dir), *host_path]), "FAKE": str(self.fake), "HEAVY_GATE_LOCK": str(root / "heavy-gate.lock"),
                    "HEAVY_GATE_SWAP_WINDOW": "1", "HEAVY_GATE_POLL": "1", "HEAVY_GATE_PRIORITIES": str(root / "priorities"),
                    "HEAVY_GATE_SLOTS_FILE": str(root / "slots"),
                    "WORKSTREAM_RANK_FILE": str(root / "rank")}
        self.bin = bin_dir
        self.rank_file = root / "rank"
        self.lock = root / "heavy-gate.lock"
        self.lock2 = root / "heavy-gate.lock.2"
        self.lock3 = root / "heavy-gate.lock.3"
        self.slots_file = root / "slots"
        self.waiters = root / "heavy-gate.lock.waiters"
        self.priorities = root / "priorities"

    def set(self, **figures):
        for key, value in figures.items():
            (self.fake / key).write_text(value + "\n")

    def gate(self, *args, timeout=30, script=SCRIPT, **extra):
        return subprocess.run(["sh", str(script), *args], env={**self.env, **extra.pop("env", {})}, text=True, capture_output=True, timeout=timeout, **extra)

    def start(self, *args, script=SCRIPT, env=None, cwd=None):
        return subprocess.Popen(["sh", str(script), *args], env={**self.env, **(env or {})}, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)

    def hold(self, name, script=SCRIPT, env=None, cwd=None):
        """A heavy job that runs until released. Returns once it is running (it passed its check and holds a slot)."""
        started = Path(self.tmp.name) / f"{name}.started"
        release = Path(self.tmp.name) / f"{name}.release"
        job = self.start("--wait", "30", "--", "sh", "-c", f"touch {started}; while [ ! -f {release} ]; do sleep 0.1; done", script=script, env=env, cwd=cwd)
        self.addCleanup(self.finish, job, release)
        self.assertTrue(self.wait_for(started.exists, 20), f"{name} is running")
        return job, release

    @staticmethod
    def finish(job, release):
        release.write_text("")
        try:
            job.wait(timeout=30)
        finally:
            if job.poll() is None:
                job.kill()
                job.wait()
            job.stdout.close()
            job.stderr.close()

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
            ({"swapusage": "total = 8192.00M  used = 7693.00M  free = 499.00M  (encrypted)"}, "swap free 499 MB (needs >= 500)"),
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

    def test_swap_is_a_safety_floor_not_a_start_rule(self):
        # 600-999 MB free used to refuse (the old start rule was 1000 MB); now only the 500 MB floor refuses
        for free in ("999.00M", "600.00M", "500.00M"):
            with self.subTest(free):
                self.set(swapusage=f"total = 8192.00M  used = 7000.00M  free = {free}  (encrypted)")
                result = self.gate()
                self.assertEqual(result.returncode, 0, result.stderr)
        for free, shown in (("499.00M", "499"), ("100.00M", "100"), ("0.00M", "0")):
            with self.subTest(free):
                self.set(swapusage=f"total = 8192.00M  used = 7000.00M  free = {free}  (encrypted)")
                result = self.gate()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f"refused: swap free {shown} MB (needs >= 500)", result.stderr)

    def test_the_swap_floor_holds_if_swap_drops_during_the_watch(self):
        (self.fake / "on_vm_stat").write_text('echo "total = 8192.00M  used = 7900.00M  free = 292.00M  (encrypted)" > "$FAKE/swapusage"\n')
        result = self.gate()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("swap free 292 MB", result.stderr)

    def test_a_command_runs_with_swap_between_the_floor_and_the_old_start_rule(self):
        self.set(swapusage="total = 6144.00M  used = 5268.00M  free = 876.00M  (encrypted)")
        marker = Path(self.tmp.name) / "ran"
        result = self.gate("--", "touch", str(marker))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(marker.exists())

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

    def test_a_host_that_turns_bad_during_the_watch_is_refused_on_each_rule(self):
        # each cheap rule is read again after the window; a first reading that was fine is not enough
        cases = [
            ('echo 2 > "$FAKE/pressure"', "memory pressure level 2"),
            ('echo "System-wide memory free percentage: 12%" > "$FAKE/memory_pressure"', "memory free 12%"),
        ]
        for hook, expected in cases:
            with self.subTest(expected):
                self.set(**QUIET)
                (self.fake / "on_vm_stat").write_text(hook + "\n")
                marker = Path(self.tmp.name) / "ran"
                result = self.gate("--", "touch", str(marker))
                self.assertEqual(result.returncode, 75, result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertFalse(marker.exists())
                self.assertFalse(self.lock.is_symlink(), "a refused start gives its slot back")
        (self.fake / "on_vm_stat").unlink()

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
        self.set(swapusage="total = 8.00G  used = 7.75G  free = 0.25G  (encrypted)")
        self.assertIn("swap free 256 MB", self.gate().stderr)
        self.set(swapusage="total = 8.00G  used = 7.50G  free = 0.50G  (encrypted)")
        self.assertEqual(self.gate().returncode, 0)
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
        self.env["HEAVY_GATE_SLOTS"] = "1"
        started = Path(self.tmp.name) / "started"
        release = Path(self.tmp.name) / "release"
        first = self.start("--", "sh", "-c", f"touch {started}; while [ ! -f {release} ]; do sleep 0.1; done")
        try:
            self.assertTrue(self.wait_for(started.exists), "the first job is running")
            self.assertTrue(self.lock.is_symlink(), "the first job holds the gate")
            second = self.gate("--", "true")
            self.assertEqual(second.returncode, 75)
            self.assertIn("all 1 heavy slot(s) are held", second.stderr)
            self.assertIn("all 1 heavy slot(s) are held", self.gate().stderr)
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
        self.env["HEAVY_GATE_SLOTS"] = "1"
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

    # --- three slots by default ---
    def test_three_jobs_hold_the_gate_and_a_fourth_is_refused(self):
        a, release_a = self.hold("a")
        b, release_b = self.hold("b")
        c, release_c = self.hold("c")
        self.assertTrue(self.lock.is_symlink() and self.lock2.is_symlink() and self.lock3.is_symlink(), "slots are <lock>, <lock>.2, <lock>.3")
        fourth = self.gate("--", "true")
        self.assertEqual(fourth.returncode, 75, fourth.stderr)
        self.assertIn("all 3 heavy slot(s) are held", fourth.stderr)
        check = self.gate()
        self.assertEqual(check.returncode, 1)
        self.assertIn("all 3 heavy slot(s) are held", check.stderr)
        self.end(a, release_a)
        self.assertEqual(self.gate("--", "true").returncode, 0, "a slot is free again once a holder is done")
        self.end(b, release_b)
        self.end(c, release_c)
        for leftover in (self.lock, self.lock2, self.lock3, Path(str(self.lock) + ".admit"), Path(str(self.lock) + ".guard")):
            self.assertFalse(leftover.is_symlink() or leftover.exists(), leftover)
        self.assertEqual(list(self.waiters.glob("*")), [])

    def test_the_number_of_slots_is_HEAVY_GATE_SLOTS(self):
        self.env["HEAVY_GATE_SLOTS"] = "2"
        for name in "ab":
            self.hold(name)
        self.assertFalse(self.lock3.is_symlink())
        self.assertEqual(self.gate("--", "true").returncode, 75)
        self.env["HEAVY_GATE_SLOTS"] = "0"
        self.assertEqual(self.gate().returncode, 2)
        self.env["HEAVY_GATE_SLOTS"] = "two"
        self.assertEqual(self.gate().returncode, 2)

    RULE_CASES = [
        ({"loadavg": "{ 12.40 9.00 5.00 }"}, "load1 12.40"),
        ({"swapusage": "total = 8192.00M  used = 7893.00M  free = 299.00M  (encrypted)"}, "swap free 299 MB"),
        ({"pressure": "2"}, "memory pressure level 2"),
        ({"memory_pressure": "System-wide memory free percentage: 20%"}, "memory free 20%"),
        ({"swapouts_step": "40"}, "Swapouts rose"),
    ]

    def assert_rules_refuse_a_start(self, slot):
        for figures, expected in self.RULE_CASES:
            with self.subTest(expected):
                self.set(**QUIET)
                (self.fake / "swapouts_step").unlink(missing_ok=True)
                self.set(**figures)
                marker = Path(self.tmp.name) / "ran"
                result = self.gate("--", "touch", str(marker))
                self.assertEqual(result.returncode, 75, result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertFalse(marker.exists(), "a refused start must not run")
                self.assertFalse(slot.is_symlink(), "a refused start gives its slot back")

    def test_every_rule_still_refuses_a_second_start(self):
        self.hold("a")
        self.assert_rules_refuse_a_start(self.lock2)

    def test_a_third_start_is_refused_if_the_host_turns_bad_during_its_watch(self):
        # the figures are read again after the Swapouts window for a start on slot 3 too
        self.hold("a")
        self.hold("b")
        cases = [
            ('echo 2 > "$FAKE/pressure"', "memory pressure level 2"),
            ('echo "System-wide memory free percentage: 12%" > "$FAKE/memory_pressure"', "memory free 12%"),
            ('echo "{ 30.00 20.00 10.00 }" > "$FAKE/loadavg"', "load1 30.00"),
        ]
        for hook, expected in cases:
            with self.subTest(expected):
                self.set(**QUIET)
                (self.fake / "on_vm_stat").write_text(hook + "\n")
                marker = Path(self.tmp.name) / "ran"
                result = self.gate("--", "touch", str(marker))
                self.assertEqual(result.returncode, 75, result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertFalse(marker.exists())
                self.assertFalse(self.lock3.is_symlink(), "a refused start gives its slot back")
        (self.fake / "on_vm_stat").unlink()

    # --- the slot limit, in a file ---
    def end(self, job, release):
        release.write_text("")
        job.wait(timeout=20)

    def slots_out(self, **extra):
        result = self.gate("slots", **extra)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_the_slots_file_can_lower_the_limit_below_the_default(self):
        self.slots_file.write_text("# how many\n\n2\n")
        for name in "ab":
            self.hold(name)
        third = self.gate("--", "true")
        self.assertEqual(third.returncode, 75, third.stderr)
        self.assertIn("all 2 heavy slot(s) are held", third.stderr)
        self.assertFalse(self.lock3.is_symlink())

    def test_the_slots_file_can_raise_the_limit_above_the_default(self):
        self.slots_file.write_text("4\n")
        for name in "abcd":
            self.hold(name)
        self.assertTrue(Path(str(self.lock) + ".4").is_symlink(), "a fourth job holds slot 4")
        fifth = self.gate("--", "true")
        self.assertEqual(fifth.returncode, 75, fifth.stderr)
        self.assertIn("all 4 heavy slot(s) are held", fifth.stderr)

    def test_a_limit_of_one_in_the_file_allows_one_job(self):
        self.slots_file.write_text("1\n")
        self.hold("a")
        second = self.gate("--", "true")
        self.assertEqual(second.returncode, 75, second.stderr)
        self.assertIn("all 1 heavy slot(s) are held", second.stderr)
        self.assertFalse(self.lock2.is_symlink())

    def test_every_rule_still_refuses_a_third_start(self):
        self.hold("a")
        self.hold("b")
        self.assert_rules_refuse_a_start(self.lock3)

    def test_the_environment_beats_the_file_and_the_file_beats_the_default(self):
        self.assertIn("slots: 3\nfrom: the default", self.slots_out())
        self.slots_file.write_text("4\n")
        self.assertIn("slots: 4\nfrom: the file " + str(self.slots_file), self.slots_out())
        out = self.slots_out(env={"HEAVY_GATE_SLOTS": "2"})
        self.assertIn("slots: 2\nfrom: HEAVY_GATE_SLOTS in the environment", out)
        # in action: a job with the variable is held to 1 although the file says 4
        self.hold("a")
        refused = self.gate("--", "true", env={"HEAVY_GATE_SLOTS": "1"})
        self.assertEqual(refused.returncode, 75, refused.stderr)
        self.assertIn("all 1 heavy slot(s) are held", refused.stderr)
        self.assertEqual(self.gate("--", "true").returncode, 0, "without the variable the file's 4 applies")

    def test_an_edit_reaches_a_waiting_job_without_a_restart(self):
        self.slots_file.write_text("1\n")
        self.hold("a")
        marker = Path(self.tmp.name) / "ran"
        waiter = self.start("--wait", "60", "--", "touch", str(marker))
        self.addCleanup(lambda: (waiter.kill(), waiter.wait(), waiter.stdout.close(), waiter.stderr.close()))
        self.assertTrue(self.wait_for(lambda: (self.waiters / str(waiter.pid)).exists()), "the job is waiting")
        time.sleep(2.5)
        self.assertIsNone(waiter.poll(), "one slot, held: still waiting")
        self.assertFalse(marker.exists())
        self.slots_file.write_text("2\n")
        self.assertTrue(self.wait_for(marker.exists, 30), "the waiting job took the new second slot on its next try")
        waiter.communicate(timeout=20)
        self.assertEqual(waiter.returncode, 0)

    def test_lowering_the_limit_stops_nothing_and_admits_nobody_until_the_holders_are_below_it(self):
        self.slots_file.write_text("3\n")
        a, release_a = self.hold("a")
        b, release_b = self.hold("b")
        c, release_c = self.hold("c")
        self.slots_file.write_text("2\n")
        time.sleep(0.5)
        for job in (a, b, c):
            self.assertIsNone(job.poll(), "a running job is not stopped")
        third = self.gate("--", "true")
        self.assertEqual(third.returncode, 75, third.stderr)
        self.assertIn("all 2 heavy slot(s) are held", third.stderr)
        self.end(a, release_a)
        self.assertEqual(self.gate("--", "true").returncode, 75, "two still hold the gate, and the limit is 2")
        self.end(b, release_b)
        self.assertEqual(self.gate("--", "true").returncode, 0, "one holds it: below the limit")
        # the last holder sits on slot 3, above a limit of 1: it still counts
        self.slots_file.write_text("1\n")
        self.assertTrue(self.lock3.is_symlink() and not self.lock.is_symlink() and not self.lock2.is_symlink())
        again = self.gate("--", "true")
        self.assertEqual(again.returncode, 75, again.stderr)
        self.assertIn("all 1 heavy slot(s) are held", again.stderr)
        self.assertEqual(self.gate().returncode, 1, "a plain check says the same")
        self.end(c, release_c)
        self.assertEqual(self.gate("--", "true").returncode, 0)
        for leftover in (self.lock, self.lock2, self.lock3):
            self.assertFalse(leftover.is_symlink(), leftover)
        self.assertEqual(list(self.waiters.glob("*")), [])

    def test_a_missing_empty_or_comment_only_file_means_three_without_a_warning(self):
        for text in (None, "", "\n\n", "# 5\n# only comments\n", "   \n"):
            with self.subTest(text):
                self.slots_file.unlink(missing_ok=True)
                if text is not None:
                    self.slots_file.write_text(text)
                out = self.slots_out()
                self.assertIn("slots: 3\nfrom: the default", out)
                self.assertNotIn("note:", out)
                check = self.gate()
                self.assertEqual(check.returncode, 0, check.stderr)
                self.assertNotIn("slots:", check.stderr)

    def test_a_bad_value_falls_back_to_three_and_says_so(self):
        for text in ("abc", "0", "000", "-1", "2.5", "3 jobs", "0x3", "1;2"):
            with self.subTest(text):
                self.slots_file.write_text(f"# comment\n{text}\n")
                out = self.slots_out()
                self.assertIn("slots: 3\nfrom: the default", out)
                self.assertIn("note: the slots file is", out)
                check = self.gate()
                self.assertEqual(check.returncode, 0, check.stderr)
                self.assertIn("WARN: slots: ", check.stderr)
                self.assertIn("using 3", check.stderr)
        # and it is a real limit of three, not zero and not unlimited
        self.slots_file.write_text("0\n")
        for name in "abc":
            self.hold(name)
        fourth = self.gate("--", "true")
        self.assertEqual(fourth.returncode, 75, fourth.stderr)
        self.assertIn("all 3 heavy slot(s) are held", fourth.stderr)

    def test_a_huge_value_counts_as_eight_and_leading_zeros_are_plain_decimal(self):
        for text, shown in (("8", "8"), ("9", "8"), ("100", "8"), ("99999999999999999999999999", "8"), ("0000000000000009", "8"),
                            ("007", "7"), ("08", "8"), ("0003", "3")):
            with self.subTest(text):
                self.slots_file.write_text(text + "\n")
                self.assertIn(f"slots: {shown}\nfrom: the file", self.slots_out())
        self.slots_file.write_text("100\n")
        self.assertIn("note: the slots file is 100, above the largest limit", self.slots_out())
        out = self.slots_out(env={"HEAVY_GATE_SLOTS": "99999999999999999999"})
        self.assertIn("slots: 8\nfrom: HEAVY_GATE_SLOTS in the environment", out)
        self.assertEqual(self.gate(env={"HEAVY_GATE_SLOTS": "9999"}).returncode, 0)

    def test_the_first_number_in_the_file_is_the_one_used(self):
        for text in ("# 5\n\n  3  \n7\n", "3\r\n7\r\n", "\t3\n"):
            with self.subTest(text):
                self.slots_file.write_text(text)
                self.assertIn("slots: 3\n", self.slots_out())

    def test_a_file_with_windows_line_endings_is_read_and_written_like_any_other(self):
        for number in ("1", "4"):
            with self.subTest(number):
                self.slots_file.write_bytes(f"# comment\r\n\r\n{number}\r\n".encode())
                self.assertIn(f"slots: {number}\nfrom: the file", self.slots_out())
        self.slots_file.write_bytes(b"# comment\r\n\r\n1\r\n# tail\r\n")
        self.assertEqual(self.gate("slots", "5").returncode, 0)
        self.assertEqual(self.slots_file.read_bytes(), b"# comment\r\n\r\n5\n# tail\r\n", "the number replaces the number, not a blank line")

    def fake_readlink(self, plan):
        """A readlink that does what the real one does, then does something else after its Nth call: an older heavy-gate (which knows
        only slot 1) taking or giving up slot 1 at an exact point of a new start. plan: {call number: shell command}. The first eight
        calls are the start's count of the slots; the ninth is its read of the slot it failed to claim."""
        real = "/usr/bin/readlink" if os.path.exists("/usr/bin/readlink") else "/bin/readlink"
        fake = Path(self.tmp.name) / "bin/readlink"
        cases = "\n".join(f"  {n}) {command} ;;" for n, command in plan.items())
        fake.write_text(f'''#!/bin/sh
n=$(cat "$FAKE/readlinks" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "$FAKE/readlinks"
{real} "$@"; rc=$?
case $n in
{cases}
esac
exit $rc
''')
        fake.chmod(0o755)

    def plant(self, name):
        sleeper = self.sleeper()
        (self.fake / name).write_text(f"{sleeper.pid}\n")
        return f'ln -s "$(cat "$FAKE/{name}")" "$HEAVY_GATE_LOCK"'

    def test_a_job_that_takes_the_free_slot_during_a_start_does_not_push_it_past_the_limit(self):
        # An older heavy-gate takes slot 1 right after this start's count. With a limit of 1 the start must not move on to slot 2.
        self.fake_readlink({8: self.plant("holder_a")})
        self.slots_file.write_text("1\n")
        marker = Path(self.tmp.name) / "ran"
        result = self.gate("--", "touch", str(marker))
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn("all 1 heavy slot(s) are held", result.stderr)
        self.assertFalse(marker.exists())
        self.assertTrue(self.lock.is_symlink(), "the planted holder is there")
        self.assertFalse(self.lock2.is_symlink(), "and the start did not take slot 2 behind its back")

    def test_a_holder_that_comes_and_goes_during_a_start_does_not_push_it_past_the_limit(self):
        # Older job A takes slot 1 after the count and is gone again by the time the start looks (call 9 removes it); older job B
        # takes slot 1 after that. A start that counted again and then went on to slot 2 would run next to B with a limit of 1.
        self.fake_readlink({8: self.plant("holder_a"), 9: 'rm -f "$HEAVY_GATE_LOCK"', 17: self.plant("holder_b")})
        self.slots_file.write_text("1\n")
        marker = Path(self.tmp.name) / "ran"
        result = self.gate("--", "touch", str(marker))
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn("slot 1 was just taken by another job", result.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse(self.lock2.is_symlink(), "the start did not take slot 2")

    def test_a_bad_environment_value_is_a_usage_error_but_slots_still_reports(self):
        for value in ("0", "two", "-1", "1.5"):
            with self.subTest(value):
                self.assertEqual(self.gate(env={"HEAVY_GATE_SLOTS": value}).returncode, 2)
                self.assertEqual(self.gate("--", "true", env={"HEAVY_GATE_SLOTS": value}).returncode, 2)
                self.slots_file.write_text("3\n")
                out = self.slots_out(env={"HEAVY_GATE_SLOTS": value})
                self.assertIn("slots: 3\nfrom: the file", out)
                self.assertIn("note: HEAVY_GATE_SLOTS is", out)

    def test_the_slots_command_sets_the_number_and_keeps_the_comments(self):
        nested = Path(self.tmp.name) / "config/heavy-gate/slots"
        self.env["HEAVY_GATE_SLOTS_FILE"] = str(nested)
        result = self.gate("slots", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"slots 3 ({nested})", result.stdout)
        self.assertEqual(nested.read_text(), "3\n", "the file and its directory are created")
        nested.write_text("# header\n# more\n\n2\n# tail\n7\n")
        self.assertEqual(self.gate("slots", "4").returncode, 0)
        self.assertEqual(nested.read_text(), "# header\n# more\n\n4\n# tail\n7\n", "the first number is replaced in place")
        nested.write_text("# only comments\n")
        self.assertEqual(self.gate("slots", "5").returncode, 0)
        self.assertEqual(nested.read_text(), "# only comments\n5\n")
        self.assertEqual(self.gate("slots", "007").returncode, 0)
        self.assertEqual(nested.read_text(), "# only comments\n7\n")
        self.assertIn("slots: 7\n", self.slots_out())
        warned = self.gate("slots", "2", env={"HEAVY_GATE_SLOTS": "6"})
        self.assertIn("HEAVY_GATE_SLOTS=6 is set", warned.stdout)

    def test_the_slots_command_rejects_bad_arguments(self):
        for args in (("0",), ("9",), ("abc",), ("-1",), ("",), ("2.5",), ("1000",), ("99999999999999999999",), ("1", "2")):
            with self.subTest(args):
                self.assertEqual(self.gate("slots", *args).returncode, 2)
        self.assertFalse(self.slots_file.exists(), "a rejected command writes nothing")
        self.slots_file.write_text("3\n")
        self.assertEqual(self.gate("slots", "9").returncode, 2)
        self.assertEqual(self.slots_file.read_text(), "3\n")

    def test_slots_reports_the_holders_and_priorities_shows_the_limit(self):
        self.slots_file.write_text("3\n")
        self.hold("a")
        self.assertIn("holding the gate now: 1", self.slots_out())
        out = self.gate("priorities").stdout
        self.assertIn("slots: 3 (from the file", out)

    def test_starts_do_not_share_a_check_window(self):
        # vm_stat is read at the start and the end of each job's Swapouts watch; the log says which job read it
        self.env["HEAVY_GATE_SWAP_WINDOW"] = "2"
        (self.fake / "on_vm_stat").write_text('echo "$TAG" >> "$FAKE/vm_log"\n')
        jobs = [self.start("--wait", "90", "--", "sleep", "1", env={"TAG": tag}) for tag in "ABC"]
        for job in jobs:
            job.communicate(timeout=90)
            self.assertEqual(job.returncode, 0)
        log = (self.fake / "vm_log").read_text().split()
        self.assertEqual(len(log), 6, log)
        for first, second in ((0, 1), (2, 3), (4, 5)):
            self.assertEqual(log[first], log[second], f"each start was alone in its window: {log}")
        self.assertEqual(len(set(log)), 3, f"three starts, three separate windows: {log}")

    def test_nothing_is_left_behind(self):
        self.assertEqual(self.gate("--", "true").returncode, 0)
        for leftover in (self.lock, self.lock2, self.lock3, Path(str(self.lock) + ".admit"), Path(str(self.lock) + ".guard")):
            self.assertFalse(leftover.is_symlink() or leftover.exists(), leftover)
        self.assertEqual(list(self.waiters.glob("*")) if self.waiters.exists() else [], [])

    # --- old and new gate side by side ---
    def test_an_old_holder_and_new_jobs_run_together_on_the_other_slots(self):
        old, _ = self.hold("old", script=OLD_SCRIPT)
        self.assertEqual(self.lock.readlink().as_posix(), str(old.pid), "the old gate holds slot 1 as it always did")
        self.assertFalse(self.lock2.exists())
        new, _ = self.hold("new")
        self.assertEqual(self.lock2.readlink().as_posix(), str(new.pid), "the new gate takes slot 2")
        newer, _ = self.hold("newer")
        self.assertEqual(self.lock3.readlink().as_posix(), str(newer.pid), "and slot 3")
        self.assertIsNone(old.poll())
        fourth = self.gate("--", "true")
        self.assertEqual(fourth.returncode, 75, "three are running; a fourth new job is refused")
        self.assertIn("all 3 heavy slot(s) are held", fourth.stderr)
        old_waiter = self.gate("--", "true", script=OLD_SCRIPT)
        self.assertEqual(old_waiter.returncode, 75, "an old job still sees slot 1 held")
        self.assertIn("another heavy job holds the gate", old_waiter.stderr)

    def test_a_new_holder_on_slot_1_keeps_an_old_job_out(self):
        new, release = self.hold("new")
        self.assertEqual(self.lock.readlink().as_posix(), str(new.pid), "a new job takes slot 1 first")
        old = self.gate("--", "true", script=OLD_SCRIPT)
        self.assertEqual(old.returncode, 75, old.stderr)
        self.assertIn("another heavy job holds the gate", old.stderr)
        release.write_text("")
        new.wait(timeout=20)
        self.assertEqual(self.gate("--", "true", script=OLD_SCRIPT).returncode, 0, "the old gate runs once slot 1 is free")

    # --- priority ---
    def sleeper(self):
        process = subprocess.Popen(["sleep", "120"])
        self.addCleanup(lambda: (process.kill(), process.wait()))
        return process

    def entry(self, pid, number, state="waiting"):
        self.waiters.mkdir(exist_ok=True)
        (self.waiters / str(pid)).write_text(f"{number}\n{state}\n/somewhere\nsome command\n")

    def test_a_live_waiter_with_a_lower_number_defers_a_try(self):
        waiter = self.sleeper()
        marker = Path(self.tmp.name) / "ran"
        self.entry(waiter.pid, 1)
        result = self.gate("--wait", "1", "--", "touch", str(marker))
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn(f"deferring to the waiting job pid {waiter.pid}, priority 1 (this one is 5)", result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.gate().returncode, 0, "a plain check does not wait, so it does not defer")

    def test_the_same_or_a_higher_number_or_a_running_job_does_not_defer(self):
        waiter = self.sleeper()
        for number, state in ((5, "waiting"), (9, "waiting"), (1, "running")):
            with self.subTest(f"{number} {state}"):
                self.entry(waiter.pid, number, state)
                self.assertEqual(self.gate("--", "true").returncode, 0)

    def test_a_stale_waiter_is_ignored(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.entry(dead.pid, 1)
        self.assertEqual(self.gate("--", "true").returncode, 0)

    def full_house_order(self, d_env=None, d_command="sh", before_release=None):
        """Two jobs hold both slots (the limit is 2 here); C (no priority) waits first, then D. A slot frees. Returns the order in which C and D ran."""
        self.env["HEAVY_GATE_SLOTS"] = "2"
        a, release_a = self.hold("a")
        self.hold("b")
        order = Path(self.tmp.name) / "order"
        c = self.start("--wait", "90", "--", "sh", "-c", f"echo C >> {order}; sleep 3")
        time.sleep(0.5)
        d = self.start("--wait", "90", "--", d_command, "-c", f"echo D >> {order}; sleep 3", env=d_env)
        self.addCleanup(lambda: [(j.kill() if j.poll() is None else None, j.wait(), j.stdout.close(), j.stderr.close()) for j in (c, d)])
        self.assertTrue(self.wait_for(lambda: (self.waiters / str(d.pid)).exists() and (self.waiters / str(c.pid)).exists()), "both are waiting")
        time.sleep(1.5)
        self.assertFalse(order.exists(), "both slots are held, nobody runs yet")
        if before_release:
            before_release(d)
        release_a.write_text("")
        self.assertTrue(self.wait_for(order.exists, 30), "a freed slot is taken")
        first = order.read_text().split()
        for job in (c, d):
            job.communicate(timeout=60)
            self.assertEqual(job.returncode, 0)
        self.assertEqual(first, order.read_text().split()[:1])
        return order.read_text().split()

    def test_a_waiter_with_a_lower_number_is_admitted_first(self):
        self.assertEqual(self.full_house_order(d_env={"HEAVY_GATE_PRIORITY": "1"}), ["D", "C"])

    def test_a_rule_set_while_jobs_wait_reaches_them(self):
        def set_rule(d):
            result = self.gate("priority", "echo D", "1")
            self.assertEqual(result.returncode, 0, result.stderr)
            # the waiting job reads the file on its next try (within the poll) and registers the new number
            self.assertTrue(self.wait_for(lambda: (self.waiters / str(d.pid)).read_text().startswith("1\n")), "D picked up the rule without a restart")
        self.assertEqual(self.full_house_order(before_release=set_rule), ["D", "C"])

    # --- central rank ---
    def use_rank(self, *rows, header="#workstream-rank v1\n", link=True):
        """Put the real workstream-rank reader on PATH and write a rank file with rows (rank, name, pane)."""
        (self.bin / "workstream-rank").unlink(missing_ok=True)
        if link:
            (self.bin / "workstream-rank").symlink_to(RANK_READER)
        self.rank_file.write_text(header + "".join(f"{rank}\t{name}\t{pane}\n" for rank, name, pane in rows))

    def stub_reader(self, body):
        (self.bin / "workstream-rank").unlink(missing_ok=True)
        (self.bin / "workstream-rank").write_text(f"#!/bin/sh\n{body}\n")
        (self.bin / "workstream-rank").chmod(0o755)

    def waiting_number(self, env=None, cwd=None):
        """The number a job registers while it waits: it defers to a waiter of number 0, so it stays a waiter and its entry shows its number."""
        blocker = self.sleeper()
        self.entry(blocker.pid, 0)
        job = self.start("--wait", "60", "--", "sh", "-c", "echo D", env=env, cwd=cwd)
        self.addCleanup(lambda: (job.kill(), job.wait(), job.stdout.close(), job.stderr.close()))
        entry = self.waiters / str(job.pid)
        self.assertTrue(self.wait_for(lambda: entry.exists() and entry.read_text().count("\n") >= 4), "the job registered")
        return entry.read_text().split("\n")[0]

    RANKED = (("1", "first", "w:p1"), ("3", "third", "w:p3"), ("7", "seventh", "w:p7"))

    def test_a_job_in_a_workstream_pane_takes_the_workstreams_rank(self):
        self.use_rank(*self.RANKED)
        for pane, number in (("w:p1", "1"), ("w:p3", "3"), ("w:p7", "7")):
            with self.subTest(pane):
                self.assertEqual(self.waiting_number(env={"HERDR_PANE_ID": pane}), number)

    def test_the_rank_beats_the_rules_and_the_environment_beats_the_rank(self):
        self.use_rank(*self.RANKED)
        self.priorities.write_text("1  echo D\n")
        self.assertEqual(self.waiting_number(env={"HERDR_PANE_ID": "w:p7"}), "7", "a rule does not lower a ranked job")
        self.assertEqual(self.waiting_number(env={"HERDR_PANE_ID": "w:p7", "HEAVY_GATE_PRIORITY": "2"}), "2")

    def test_a_job_with_no_workstream_goes_after_the_whole_stack_and_the_rules_still_order_it(self):
        self.use_rank(*self.RANKED)
        for label, env in (("unknown pane", {"HERDR_PANE_ID": "w:other"}), ("no pane at all", {}), ("empty pane", {"HERDR_PANE_ID": ""})):
            with self.subTest(label):
                self.assertEqual(self.waiting_number(env=env), "1005", "the default 5, after the stack")
        self.priorities.write_text("2  echo D\n08  nothing-matches-this\n")
        self.assertEqual(self.waiting_number(env={"HERDR_PANE_ID": "w:other"}), "1002", "the rule's number, after the stack")
        self.priorities.write_text("08  echo D\n")
        self.assertEqual(self.waiting_number(), "1008", "a leading zero is plain decimal, not octal")
        self.priorities.write_text("999999  echo D\n")
        self.assertEqual(self.waiting_number(), "999999", "capped like every other number")

    def test_without_a_usable_rank_nothing_changes(self):
        self.priorities.write_text("2  echo D\n")
        cases = {
            "no reader on PATH, no file": lambda: None,
            "no reader on PATH, a file": lambda: self.use_rank(*self.RANKED, link=False),
            "reader, no file": lambda: (self.use_rank(*self.RANKED), self.rank_file.unlink()),
            "wrong header": lambda: self.use_rank(*self.RANKED, header="#workstream-rank v2\n"),
            "no header": lambda: self.use_rank(*self.RANKED, header=""),
            "header only": lambda: self.use_rank(),
            "garbage rows": lambda: self.use_rank(("soon", "x", "w:p1"), ("-1", "y", "w:p1")),
            "file is a directory": lambda: (self.use_rank(*self.RANKED), self.rank_file.unlink(), self.rank_file.mkdir()),
        }
        for label, setup in cases.items():
            with self.subTest(label):
                (self.bin / "workstream-rank").unlink(missing_ok=True)
                if self.rank_file.is_dir():
                    self.rank_file.rmdir()
                setup()
                self.assertEqual(self.waiting_number(env={"HERDR_PANE_ID": "w:p1"}), "2", "the rule, on the old 1-to-5 scale")
        self.priorities.unlink()
        (self.bin / "workstream-rank").unlink(missing_ok=True)
        self.assertEqual(self.waiting_number(env={"HERDR_PANE_ID": "w:p1"}), "5")

    def test_a_reader_that_fails_or_prints_nonsense_is_ignored(self):
        # (reader stub body, number of a job in w:p1 with the rule 2). A reader whose show fails, or prints nothing, leaves the rank off: the plain rule.
        # A reader whose show works but whose of fails or prints no number is a rank on and a job with no workstream: the rule plus 1000.
        self.priorities.write_text("2  echo D\n")
        stubs = (("exit 2", "exit 2", "2"),
                 ("nothing", "exit 0", "2"),
                 ("show prints a row, then fails", 'case "$1" in show) echo x; exit 1 ;; of) echo 1 ;; esac', "2"),
                 ("show fails", 'case "$1" in of) echo 4 ;; *) exit 1 ;; esac', "2"),
                 ("of prints words", 'case "$1" in show) echo x ;; of) echo high ;; esac', "1002"),
                 ("of prints a negative", 'case "$1" in show) echo x ;; of) echo -3 ;; esac', "1002"),
                 ("of fails", 'case "$1" in show) echo x ;; of) exit 1 ;; esac', "1002"),
                 ("of prints a rank, then fails", 'case "$1" in show) echo x ;; of) echo 4; exit 1 ;; esac', "1002"),
                 ("of prints nothing", 'case "$1" in show) echo x ;; esac', "1002"),
                 ("of prints a huge number", 'case "$1" in show) echo x ;; of) echo 99999999999999999999 ;; esac', "1002"))
        for label, body, expected in stubs:
            with self.subTest(label):
                self.stub_reader(body)
                self.assertEqual(self.waiting_number(env={"HERDR_PANE_ID": "w:p1"}), expected)

    def test_a_slow_reader_never_holds_the_gate_up(self):
        self.priorities.write_text("2  echo D\n")
        for label, body, expected in (("both calls hang", "sleep 60", "2"),
                                      ("of hangs", 'case "$1" in show) echo x ;; of) sleep 60 ;; esac', "1002"),
                                      ("a child of the reader hangs, holding its output", 'case "$1" in show) echo x ;; of) sleep 60 & wait ;; esac', "1002")):
            with self.subTest(label):
                self.stub_reader(body)
                env = {"HERDR_PANE_ID": "w:p1", "HEAVY_GATE_RANK_TIMEOUT": "1"}
                started = time.monotonic()
                self.assertEqual(self.waiting_number(env=env), expected)
                self.assertLess(time.monotonic() - started, 15, "the reader was cut off, not waited for")

    def test_a_hanging_reader_does_not_hold_up_a_job_or_its_deadline(self):
        self.priorities.write_text("2  echo D\n")
        self.stub_reader("sleep 60")
        for timeout in ("1", "soon", "0", ""):   # a bad value, or 0, means the default, 2 seconds
            with self.subTest(timeout):
                marker = Path(self.tmp.name) / f"ran{timeout}"
                started = time.monotonic()
                result = self.gate("--wait", "1", "--", "touch", str(marker), env={"HEAVY_GATE_RANK_TIMEOUT": timeout})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertLess(time.monotonic() - started, 20, "the job ran; --wait and the deadline are not held by the reader")
                self.assertTrue(marker.exists())
                self.assertNotIn("Killed", result.stderr, "the shell's report of the killed reader is not shown")

    def test_the_readers_warnings_are_not_repeated_by_the_gate(self):
        self.stub_reader('echo "noise on stderr" >&2; case "$1" in show) echo x ;; of) echo 4 ;; esac')
        marker = Path(self.tmp.name) / "ran"
        result = self.gate("--", "touch", str(marker), env={"HERDR_PANE_ID": "w:p1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("noise", result.stderr, "the reader would warn at every try")
        self.assertTrue(marker.exists())

    def test_a_new_rank_reaches_a_job_that_is_already_waiting(self):
        self.use_rank(*self.RANKED)
        blocker = self.sleeper()
        self.entry(blocker.pid, 0)
        job = self.start("--wait", "60", "--", "sh", "-c", "echo D", env={"HERDR_PANE_ID": "w:p3"})
        self.addCleanup(lambda: (job.kill(), job.wait(), job.stdout.close(), job.stderr.close()))
        entry = self.waiters / str(job.pid)
        self.assertTrue(self.wait_for(lambda: entry.exists() and entry.read_text().startswith("3\n")))
        self.use_rank(("1", "third", "w:p3"), ("2", "first", "w:p1"))
        self.assertTrue(self.wait_for(lambda: entry.read_text().startswith("1\n"), 20), "the next try registers the new rank")
        self.rank_file.unlink()
        self.assertTrue(self.wait_for(lambda: entry.read_text().startswith("5\n"), 20), "and deleting the file goes back to the rules")

    def test_a_ranked_job_is_admitted_before_one_with_no_workstream(self):
        self.use_rank(*self.RANKED)
        self.assertEqual(self.full_house_order(d_env={"HERDR_PANE_ID": "w:p7"}), ["D", "C"], "even the worst rank beats a job with no workstream")

    def test_a_worse_rank_waits_for_a_better_one(self):
        self.use_rank(*self.RANKED)
        waiter = self.sleeper()
        self.entry(waiter.pid, 3)
        marker = Path(self.tmp.name) / "ran"
        result = self.gate("--wait", "1", "--", "touch", str(marker), env={"HERDR_PANE_ID": "w:p7"})
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertIn(f"deferring to the waiting job pid {waiter.pid}, priority 3 (this one is 7)", result.stderr)
        self.assertEqual(self.gate("--", "touch", str(marker), env={"HERDR_PANE_ID": "w:p1"}).returncode, 0, "a better rank does not defer")

    def test_a_waiter_from_the_older_version_is_ordered_by_its_own_1_to_5_number(self):
        # A waiter that started before this version is installed registers its rule number (1 to 5) and never reads the rank.
        self.use_rank(*self.RANKED)
        waiter = self.sleeper()
        self.entry(waiter.pid, 5)
        marker = Path(self.tmp.name) / "ran"
        self.assertEqual(self.gate("--wait", "1", "--", "touch", str(marker), env={"HERDR_PANE_ID": "w:p7"}).returncode, 75, "rank 7 waits for the old 5")
        self.assertEqual(self.gate("--wait", "1", "--", "touch", str(marker)).returncode, 75, "no workstream (1005) waits for the old 5")
        self.assertEqual(self.gate("--", "touch", str(marker), env={"HERDR_PANE_ID": "w:p3"}).returncode, 0, "rank 3 goes first")

    def test_priorities_says_whether_the_central_rank_is_on(self):
        self.assertIn("central rank: off", self.gate("priorities").stdout)
        self.use_rank(*self.RANKED)
        self.assertIn("central rank: on", self.gate("priorities").stdout)
        self.use_rank()
        self.assertIn("central rank: off", self.gate("priorities").stdout)

    def test_priorities_prints_the_file_and_the_holders_and_waiters_with_their_numbers(self):
        self.priorities.write_text("# a comment\n\n2  pibolt-x\n7 a.started\n  1 \tcoordinator\n")
        self.env["HEAVY_GATE_SLOTS"] = "4"
        (Path(self.tmp.name) / "pibolt-x").mkdir()
        jobs = {
            "dir": self.hold("a", cwd=Path(self.tmp.name) / "pibolt-x"),    # directory matches rule 1; the command matches rule 2: first wins
            "command": self.hold("coordinator"),                             # the command matches the last rule
            "none": self.hold("plain"),                                      # no rule: the default
            "env": self.hold("envjob", env={"HEAVY_GATE_PRIORITY": "9"}),    # the environment beats every rule
        }
        waiter = self.start("--wait", "60", "--", "true", env={"HEAVY_GATE_PRIORITY": "4"})
        self.addCleanup(lambda: (waiter.kill(), waiter.wait(), waiter.stdout.close(), waiter.stderr.close()))
        self.assertTrue(self.wait_for(lambda: (self.waiters / str(waiter.pid)).exists()))
        out = self.gate("priorities").stdout
        self.assertIn(f"priorities file: {self.priorities}", out)
        self.assertIn("# a comment", out)
        found = {}
        for line in out.splitlines():
            parts = line.split()
            if "pid" in parts and "priority" in parts:
                found[int(parts[parts.index("pid") + 1])] = parts[parts.index("priority") + 1]
        self.assertEqual(found[jobs["dir"][0].pid], "2")
        self.assertEqual(found[jobs["command"][0].pid], "1")
        self.assertEqual(found[jobs["none"][0].pid], "5")
        self.assertEqual(found[jobs["env"][0].pid], "9")
        self.assertEqual(found[waiter.pid], "4")
        self.assertIn(f"slot 1  pid {jobs['dir'][0].pid}", out)
        self.assertLess(out.index("holders:"), out.index(f"pid {waiter.pid}"))
        self.assertGreater(out.index("waiting:"), out.index(f"pid {jobs['env'][0].pid}"))
        self.assertLess(out.index("waiting:"), out.index(f"pid {waiter.pid}"))

    def test_priorities_without_a_file(self):
        result = self.gate("priorities")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("absent", result.stdout)

    def test_the_priority_command_sets_updates_and_puts_a_new_rule_first(self):
        self.env["HEAVY_GATE_PRIORITIES"] = str(Path(self.tmp.name) / "config/heavy-gate/priorities")
        file = Path(self.env["HEAVY_GATE_PRIORITIES"])
        self.assertEqual(self.gate("priority", "coordinator", "1").returncode, 0)
        self.assertEqual(file.read_text(), "1  coordinator\n", "the file and its directory are created")
        file.write_text("# header\n#\n# 1  example\n\n3  pibolt\n4  other\n")
        self.assertEqual(self.gate("priority", "pi bolt", "2").returncode, 0)
        self.assertEqual(file.read_text(), "# header\n#\n# 1  example\n\n2  pi bolt\n3  pibolt\n4  other\n", "a new rule goes before the others; comments stay")
        self.assertEqual(self.gate("priority", "pibolt", "1").returncode, 0)
        self.assertEqual(file.read_text(), "# header\n#\n# 1  example\n\n2  pi bolt\n1  pibolt\n4  other\n", "the same pattern is updated in place")
        self.assertEqual(self.gate("priority", "  other  ", "6").returncode, 0)
        self.assertIn("\n6  other\n", file.read_text())
        file.write_text("# only comments\n")
        self.assertEqual(self.gate("priority", "x", "8").returncode, 0)
        self.assertEqual(file.read_text(), "# only comments\n8  x\n")

    def test_the_priority_command_rejects_bad_arguments(self):
        for args in (("x",), ("x", "soon"), ("x", "-1"), ("x", ""), ("  ", "1"), ("", "1"), ("x", "1", "2")):
            with self.subTest(args):
                self.assertEqual(self.gate("priority", *args).returncode, 2)
        self.assertFalse(self.priorities.exists(), "a rejected command writes nothing")
        self.assertEqual(self.gate("priorities", "extra").returncode, 2)

    def test_a_huge_number_still_ranks_below_a_lower_one(self):
        waiter = self.sleeper()
        self.entry(waiter.pid, 1)
        self.priorities.write_text("99999999999999999999999999  big\n")
        result = self.gate("--wait", "1", "--", "echo", "big")
        self.assertEqual(result.returncode, 75, "a 26-digit number does not slip past a priority-1 waiter")
        self.assertIn("deferring to the waiting job", result.stderr)
        self.assertEqual(self.gate("priority", "x", "1000000").returncode, 2)

    def test_a_bad_priority_in_the_environment_is_a_usage_error(self):
        for value in ("high", "-1", "1.5", "1234567"):
            with self.subTest(value):
                self.assertEqual(self.gate(env={"HEAVY_GATE_PRIORITY": value}).returncode, 2)

    def test_the_usage_text_covers_the_new_parts(self):
        result = self.gate("--help")
        self.assertEqual(result.returncode, 2)
        for expected in ("HEAVY_GATE_SLOTS", "HEAVY_GATE_SLOTS_FILE", "heavy-gate slots", "heavy-gate slots N", "Slots:", "heavy-gate priorities", "heavy-gate priority PATTERN NUMBER", "HEAVY_GATE_PRIORITY", "slot 2"):
            self.assertIn(expected, result.stderr)
        self.assertNotIn("set -eu", result.stderr)

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
