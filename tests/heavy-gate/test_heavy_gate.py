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
        env = {k: v for k, v in os.environ.items() if not k.startswith("HEAVY_GATE_")}  # nothing from the real shell leaks in
        self.env = {**env, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE": str(self.fake), "HEAVY_GATE_LOCK": str(root / "heavy-gate.lock"),
                    "HEAVY_GATE_SWAP_WINDOW": "1", "HEAVY_GATE_POLL": "1", "HEAVY_GATE_PRIORITIES": str(root / "priorities")}
        self.lock = root / "heavy-gate.lock"
        self.lock2 = root / "heavy-gate.lock.2"
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

    # --- two slots ---
    def test_two_jobs_hold_the_gate_and_a_third_is_refused(self):
        a, release_a = self.hold("a")
        b, release_b = self.hold("b")
        self.assertTrue(self.lock.is_symlink() and self.lock2.is_symlink(), "slot 1 is the lock path, slot 2 is <lock>.2")
        third = self.gate("--", "true")
        self.assertEqual(third.returncode, 75, third.stderr)
        self.assertIn("all 2 heavy slot(s) are held", third.stderr)
        check = self.gate()
        self.assertEqual(check.returncode, 1)
        self.assertIn("all 2 heavy slot(s) are held", check.stderr)
        release_a.write_text("")
        a.wait(timeout=20)
        self.assertEqual(self.gate("--", "true").returncode, 0, "a slot is free again once a holder is done")

    def test_the_number_of_slots_is_HEAVY_GATE_SLOTS(self):
        self.env["HEAVY_GATE_SLOTS"] = "3"
        for name in "abc":
            self.hold(name)
        self.assertEqual(self.gate("--", "true").returncode, 75)
        self.env["HEAVY_GATE_SLOTS"] = "0"
        self.assertEqual(self.gate().returncode, 2)
        self.env["HEAVY_GATE_SLOTS"] = "two"
        self.assertEqual(self.gate().returncode, 2)

    def test_every_rule_still_refuses_a_second_start(self):
        self.hold("a")
        cases = [
            ({"loadavg": "{ 12.40 9.00 5.00 }"}, "load1 12.40"),
            ({"swapusage": "total = 8192.00M  used = 7893.00M  free = 299.00M  (encrypted)"}, "swap free 299 MB"),
            ({"pressure": "2"}, "memory pressure level 2"),
            ({"memory_pressure": "System-wide memory free percentage: 20%"}, "memory free 20%"),
            ({"swapouts_step": "40"}, "Swapouts rose"),
        ]
        for figures, expected in cases:
            with self.subTest(expected):
                self.set(**QUIET)
                (self.fake / "swapouts_step").unlink(missing_ok=True)
                self.set(**figures)
                marker = Path(self.tmp.name) / "ran"
                result = self.gate("--", "touch", str(marker))
                self.assertEqual(result.returncode, 75, result.stderr)
                self.assertIn(expected, result.stderr)
                self.assertFalse(marker.exists(), "a refused second start must not run")
                self.assertFalse(self.lock2.is_symlink(), "a refused start gives its slot back")

    def test_two_starts_do_not_share_a_check_window(self):
        # vm_stat is read at the start and the end of each job's Swapouts watch; the log says which job read it
        self.env["HEAVY_GATE_SWAP_WINDOW"] = "2"
        (self.fake / "on_vm_stat").write_text('echo "$TAG" >> "$FAKE/vm_log"\n')
        jobs = [self.start("--wait", "60", "--", "sleep", "1", env={"TAG": tag}) for tag in "AB"]
        for job in jobs:
            job.communicate(timeout=60)
            self.assertEqual(job.returncode, 0)
        log = (self.fake / "vm_log").read_text().split()
        self.assertEqual(len(log), 4, log)
        self.assertEqual(log[0], log[1], f"the first start was alone in its window: {log}")
        self.assertEqual(log[2], log[3], f"the second start waited for it: {log}")
        self.assertNotEqual(log[0], log[2])

    def test_nothing_is_left_behind(self):
        self.assertEqual(self.gate("--", "true").returncode, 0)
        for leftover in (self.lock, self.lock2, Path(str(self.lock) + ".admit"), Path(str(self.lock) + ".guard")):
            self.assertFalse(leftover.is_symlink() or leftover.exists(), leftover)
        self.assertEqual(list(self.waiters.glob("*")) if self.waiters.exists() else [], [])

    # --- old and new gate side by side ---
    def test_an_old_holder_and_a_new_job_run_together_on_the_two_slots(self):
        old, _ = self.hold("old", script=OLD_SCRIPT)
        self.assertEqual(self.lock.readlink().as_posix(), str(old.pid), "the old gate holds slot 1 as it always did")
        self.assertFalse(self.lock2.exists())
        new, _ = self.hold("new")
        self.assertEqual(self.lock2.readlink().as_posix(), str(new.pid), "the new gate takes slot 2")
        self.assertIsNone(old.poll())
        third = self.gate("--", "true")
        self.assertEqual(third.returncode, 75, "two are running; a third new job is refused")
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
        """Two jobs hold both slots; C (no priority) waits first, then D. A slot frees. Returns the order in which C and D ran."""
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

    def test_a_bad_priority_in_the_environment_is_a_usage_error(self):
        for value in ("high", "-1", "1.5"):
            with self.subTest(value):
                self.assertEqual(self.gate(env={"HEAVY_GATE_PRIORITY": value}).returncode, 2)

    def test_the_usage_text_covers_the_new_parts(self):
        result = self.gate("--help")
        self.assertEqual(result.returncode, 2)
        for expected in ("HEAVY_GATE_SLOTS", "heavy-gate priorities", "heavy-gate priority PATTERN NUMBER", "HEAVY_GATE_PRIORITY", "slot 2"):
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
