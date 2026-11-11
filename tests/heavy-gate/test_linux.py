"""heavy-gate and its watchdog on Linux (the macOS tests are test_heavy_gate.py and test_watchdog.py; they stay as they are).

Same shape as those: the real scripts run as real processes; only the host's figures are scripted. On Linux the figures are files, so
HEAVY_GATE_PROC points at a fake /proc (meminfo, loadavg) and `uname` is a fake that says Linux. sysctl and memory_pressure are fakes that
fail the test if they are ever called: the Linux branch must not read the macOS figures. `df` and `ps` are the real ones for ps, a fake for df.
"""
import configparser
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_heavy_gate as macos
import test_watchdog as macos_watchdog
from test_heavy_gate import SCRIPT

TOTAL_KB = 16_000_000
DF_HEADER = "Filesystem     1K-blocks      Used Available Use% Mounted on"
POISON = 'echo "called $0 $*" >> "$FAKE/macos_figure_calls"; exit 99'
LINUX_FAKES = {
    "uname": "echo Linux",
    "df": macos.FAKES["df"],
    "sysctl": POISON,
    "memory_pressure": POISON,
}


def meminfo(free_pct, total_kb=TOTAL_KB):
    avail = total_kb * free_pct // 100
    return (f"MemTotal:       {total_kb} kB\nMemFree:         1234567 kB\nMemAvailable:   {avail} kB\nBuffers:           12345 kB\n"
            "Cached:          2345678 kB\n")


def df_output(free_gb, mount="/"):
    """What `df -k $HOME` prints on Linux for a volume with this much free space (GiB; the volume is 1 TiB)."""
    kb = int(free_gb * 1048576)
    total = 1024 * 1048576
    return f"{DF_HEADER}\n/dev/nvme0n1p5 {total} {total - kb} {kb}  99% {mount}"


def loadavg(one, five, fifteen="1.00"):
    return f"{one} {five} {fifteen} 3/1234 56789\n"


class LinuxBase(unittest.TestCase):
    """Fakes first on PATH, a fake /proc, and the same temp-dir environment the macOS tests use."""

    def build(self, root, env):
        fake = root / "fake"
        fake.mkdir(exist_ok=True)
        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        for name, body in LINUX_FAKES.items():
            (bin_dir / name).write_text(f"#!/bin/sh\n{body}\n")
            (bin_dir / name).chmod(0o755)
        proc = root / "proc"
        proc.mkdir(exist_ok=True)
        self.proc = proc
        self.fake = fake
        self.set_memory(62)
        self.set_load("2.10", "3.00")
        (fake / "df").write_text(df_output(500) + "\n")
        env = dict(env, PATH=":".join([str(bin_dir), *[d for d in env["PATH"].split(":") if d != str(root / "bin")]]), HEAVY_GATE_PROC=str(proc), FAKE=str(fake))
        return env

    def set_memory(self, free_pct):
        tmp = self.proc / "meminfo.new"
        tmp.write_text(meminfo(free_pct))
        os.replace(tmp, self.proc / "meminfo")

    def set_load(self, one, five):
        tmp = self.proc / "loadavg.new"
        tmp.write_text(loadavg(one, five))
        os.replace(tmp, self.proc / "loadavg")

    def set_free(self, free_gb, mount="/"):
        tmp = self.fake / "df.new"
        tmp.write_text(df_output(free_gb, mount) + "\n")
        os.replace(tmp, self.fake / "df")

    def no_macos_figure_was_read(self):
        calls = self.fake / "macos_figure_calls"
        self.assertFalse(calls.exists(), calls.read_text() if calls.exists() else "")


class LinuxGate(LinuxBase):
    def setUp(self):
        macos.HeavyGate.setUp(self)           # the temp dir, the lock and priority files, the env, the macOS fakes
        self.env = self.build(Path(self.tmp.name), self.env)

    set = macos.HeavyGate.set
    gate = macos.HeavyGate.gate
    start = macos.HeavyGate.start
    hold = macos.HeavyGate.hold
    finish = staticmethod(macos.HeavyGate.finish)
    wait_for = macos.HeavyGate.wait_for

    def test_quiet_linux_host_is_allowed_without_reading_a_macos_figure(self):
        result = self.gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[heavy-gate] INFO: allowed", result.stderr)
        self.no_macos_figure_was_read()

    def test_the_check_line_does_not_promise_a_pressure_level_on_linux(self):
        result = self.gate()
        self.assertIn("memory free >= 30%", result.stderr)
        self.assertNotIn("level 1 to", result.stderr)

    def test_memory_free_is_the_rule_and_30_percent_is_the_edge(self):
        for free, rc in ((62, 0), (31, 0), (30, 0), (29, 1), (4, 1)):
            with self.subTest(free):
                self.set_memory(free)
                result = self.gate()
                self.assertEqual(result.returncode, rc, result.stderr)
                if rc:
                    self.assertIn(f"refused: memory free {free}% (needs >= 30%)", result.stderr)
        self.no_macos_figure_was_read()

    def test_an_unreadable_meminfo_refuses(self):
        (self.proc / "meminfo").unlink()
        result = self.gate()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("refused: memory free unreadable% (needs >= 30%)", result.stderr)

    def test_the_load_rule_reads_the_5_minute_figure(self):
        self.set_load("40.00", "3.00")           # a spike in the 1-minute figure does not refuse
        self.assertEqual(self.gate().returncode, 0)
        self.set_load("1.00", "14.20")
        result = self.gate()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertRegex(result.stderr, r"refused: 5-minute load average 14\.20 is above the 12 limit \(\d+ cores\); no new heavy job starts until it falls")
        self.no_macos_figure_was_read()

    def test_an_unreadable_loadavg_refuses(self):
        (self.proc / "loadavg").unlink()
        result = self.gate()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("5-minute load average is unreadable", result.stderr)

    def test_the_disk_floor_reads_linux_df(self):
        self.set_free(10)
        result = self.gate()
        self.assertEqual(result.returncode, 76, result.stderr)
        self.assertIn("REFUSED: 10.0 GB free on /, under the 15 GB floor", result.stderr)
        self.set_free(15)
        self.assertEqual(self.gate().returncode, 0)

    def test_a_job_runs_with_its_exit_status_and_holds_a_slot(self):
        result = self.gate("--", "sh", "-c", "exit 7")
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("allowed; running: sh -c exit 7", result.stderr)
        job, release = self.hold("a")
        self.assertTrue(self.lock.is_symlink(), "the job holds slot 1")
        self.assertEqual(os.readlink(self.lock), str(job.pid))
        release.write_text("")
        job.wait(timeout=30)
        self.assertFalse(self.lock.is_symlink(), "the slot is released at exit")

    def test_waiting_for_memory_runs_the_job_once_it_is_free(self):
        self.set_memory(10)
        job = self.start("--wait", "30", "--", "sh", "-c", "echo ran")
        self.assertTrue(self.wait_for(lambda: self.waiters.exists(), 10), "the job is waiting")
        self.set_memory(60)
        out, err = job.communicate(timeout=30)
        self.assertEqual(job.returncode, 0, err)
        self.assertIn("ran", out)

    def test_an_os_that_is_neither_is_refused(self):
        (self.bin / "uname").write_text("#!/bin/sh\necho FreeBSD\n")
        result = self.gate()
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("macOS and Linux only", result.stderr)


class LinuxWatchdog(LinuxBase, macos_watchdog.WatchdogBase):
    """The daemon on Linux: the same stop-the-biggest-tree behaviour, reading MemAvailable instead of memory_pressure."""

    def setUp(self):
        macos_watchdog.WatchdogBase.setUp(self)
        self.env = self.build(self.root, self.env)

    gate = macos_watchdog.WatchdogBase.gate
    err = macos_watchdog.WatchdogBase.err
    daemon = macos_watchdog.WatchdogBase.daemon
    daemon_log = macos_watchdog.WatchdogBase.daemon_log

    def test_low_memory_stops_the_biggest_job_with_137_and_a_reason(self):
        small = self.gate("small", macos_watchdog.SMALL)
        big = self.gate("big", macos_watchdog.BIG)
        self.assertTrue(self.wait_for((self.root / "ready.big").exists, 20), "the big job has its memory")
        self.daemon()
        self.set_memory(4)
        big.wait(timeout=30)
        self.assertEqual(big.returncode, 137, self.err("big"))
        self.assertIn("[heavy-gate] ERROR: the memory watchdog (heavy-gate-watchdog) stopped this job; exit 137 is not a failure of the job itself: free memory 4% (floor 10%)", self.err("big"))
        self.assertIsNone(small.poll(), "the smaller job is still alive")
        self.assertTrue(any("heavy-gate-watchdog stopped pid" in line and "free memory 4%" in line for line in self.daemon_log().splitlines()), self.daemon_log())
        self.no_macos_figure_was_read()

    def test_healthy_memory_stops_nothing(self):
        job = self.gate("a", "sleep 3\nexit 5")
        self.daemon()
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 5, self.err("a"))
        self.assertNotIn("stopped pid", self.daemon_log())

    def test_a_meminfo_it_cannot_read_counts_as_not_low(self):
        job = self.gate("a", "sleep 3\nexit 5")
        (self.proc / "meminfo").unlink()
        self.daemon()
        job.wait(timeout=30)
        self.assertEqual(job.returncode, 5, self.err("a"))
        self.assertNotIn("stopped pid", self.daemon_log())


REPO = Path(__file__).resolve().parents[2]


def ignored(profile, chezmoi_os):
    """The destination patterns .chezmoiignore lists for this profile and OS (a render with the OS overridden)."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("{}\n")
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "execute-template", "--override-data",
                            json.dumps({"profile": profile, "chezmoi": {"os": chezmoi_os}})],
                           input=(REPO / ".chezmoiignore").read_text(), capture_output=True, text=True, timeout=120, env={**os.environ, "HOME": tmp})
    assert r.returncode == 0, r.stderr
    return {line.strip() for line in r.stdout.splitlines() if line.strip() and not line.startswith("#")}


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class LinuxInstall(unittest.TestCase):
    UNIT = REPO / "dot_config/systemd/user/heavy-gate-watchdog.service"
    LOAD = REPO / "run_onchange_after_73_heavy_gate_watchdog_systemd.sh.tmpl"
    DAEMON = ".local/bin/heavy-gate-watchdog"
    UNIT_DEST = ".config/systemd/user/heavy-gate-watchdog.service"
    PLIST_DEST = "Library/LaunchAgents/local.heavy-gate-watchdog.plist"

    def test_the_unit_runs_the_daemon_forever(self):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        parser.read_string(self.UNIT.read_text())
        self.assertEqual(parser["Service"]["ExecStart"], "/bin/sh %h/.local/bin/heavy-gate-watchdog")
        self.assertEqual(parser["Service"]["Restart"], "always")
        self.assertEqual(parser["Install"]["WantedBy"], "default.target")
        self.assertNotIn("Nice", parser["Service"], "no Nice: it has to run exactly when memory is short")

    def test_the_loader_is_valid_sh_and_reruns_when_the_unit_or_the_daemon_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "chezmoi.yaml"
            cfg.write_text("{}\n")
            r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "execute-template", "--override-data", json.dumps({"profile": "personal"})],
                               input=self.LOAD.read_text(), capture_output=True, text=True, timeout=60, env={**os.environ, "HOME": tmp})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(subprocess.run(["sh", "-n"], input=r.stdout, text=True, capture_output=True).returncode, 0)
        for source in (self.UNIT, REPO / "dot_local/bin/executable_heavy-gate-watchdog"):
            self.assertIn(hashlib.sha256(source.read_bytes()).hexdigest(), r.stdout, source.name)

    def test_the_loader_is_a_clean_notice_when_there_is_no_user_manager(self):
        with tempfile.TemporaryDirectory() as tmp:
            stub = Path(tmp) / "bin"
            stub.mkdir()
            (stub / "systemctl").write_text("#!/bin/sh\nexit 1\n")
            (stub / "systemctl").chmod(0o755)
            script = Path(tmp) / "load.sh"
            script.write_text("".join(line for line in self.LOAD.read_text().splitlines(True) if "{{" not in line))   # the two hash comments are the only template lines
            r = subprocess.run(["sh", str(script)], capture_output=True, text=True, env={"PATH": f"{stub}:/usr/bin:/bin", "HOME": tmp})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no systemd user manager here", r.stdout)

    def test_each_os_deploys_its_own_watchdog_pieces_and_no_other(self):
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile, os="linux"):
                ig = ignored(profile, "linux")
                self.assertNotIn(self.DAEMON, ig)
                self.assertNotIn(self.UNIT_DEST, ig)
                self.assertNotIn("73_heavy_gate_watchdog_systemd.sh", ig)
                self.assertIn(self.PLIST_DEST, ig)
                self.assertIn("72_heavy_gate_watchdog_launchd.sh", ig)
            with self.subTest(profile, os="darwin"):
                ig = ignored(profile, "darwin")
                self.assertNotIn(self.DAEMON, ig)
                self.assertNotIn(self.PLIST_DEST, ig)
                self.assertNotIn("72_heavy_gate_watchdog_launchd.sh", ig)
                self.assertIn(self.UNIT_DEST, ig)
                self.assertIn("73_heavy_gate_watchdog_systemd.sh", ig)
        with self.subTest("termux"):
            ig = ignored("termux", "android")
            for name in (self.DAEMON, self.UNIT_DEST, "73_heavy_gate_watchdog_systemd.sh", self.PLIST_DEST):
                self.assertIn(name, ig)


if __name__ == "__main__":
    unittest.main()
