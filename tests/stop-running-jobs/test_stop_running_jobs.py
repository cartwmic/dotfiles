"""The builder seat's Stop hook (dot_local/share/agent-harness/hooks/stop_running_jobs.py) and its place in the seat file.

The hook runs as a process, the way Claude Code runs it, against throwaway run-and-wake and kgate state folders and real child
processes. A job is "running" only while its process is. The seat-file tests render the template through real chezmoi.
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "dot_local/share/agent-harness/hooks/stop_running_jobs.py"
MINE = "thread:me"
OTHER = "thread:someone-else"
LINUX = os.path.isdir("/proc/self")
_spec = importlib.util.spec_from_file_location("stop_running_jobs", HOOK)
MOD = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MOD)


class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.rw = self.tmp / "run-and-wake"
        self.kg = self.tmp / "kgate"
        (self.kg / "active").mkdir(parents=True)
        self.rw.mkdir()
        (self.rw / "log.jsonl").write_text("")
        self.procs = []
        self.addCleanup(self.reap)

    def reap(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()

    def hook(self, thread=MINE, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("T3CODE_THREAD_ID", "STOP_JOBS_THREAD")}
        env.update(RUN_AND_WAKE_STATE=str(self.rw), KGATE_STATE=str(self.kg))
        if thread:
            env["STOP_JOBS_THREAD"] = thread
        return subprocess.run([sys.executable, str(HOOK), *args], input="{}", capture_output=True, text=True, env=env, timeout=30)

    def start_process(self, seconds=120, **env):
        p = subprocess.Popen(["sleep", str(seconds)], env={**os.environ, **env}, start_new_session=True)
        self.procs.append(p)
        if LINUX:   # between fork and exec the child still shows the test runner's command line and environment; record only the settled process
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    settled = Path("/proc/%d/cmdline" % p.pid).read_bytes().startswith(b"sleep\0") and all(
                        ("%s=%s" % kv).encode() in Path("/proc/%d/environ" % p.pid).read_bytes().split(b"\0") for kv in env.items())
                except OSError:
                    settled = False
                if settled:
                    break
                time.sleep(0.01)
            else:
                self.fail("the test process never settled")
        return p

    def log(self, *records):
        with open(self.rw / "log.jsonl", "a") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def rw_job(self, job, thread=MINE, seconds=120, with_env=True, boot=None):
        """A run-and-wake job: a real process (carrying RUN_AND_WAKE_JOB, as the real job does) and its `start` record."""
        p = self.start_process(seconds, **({"RUN_AND_WAKE_JOB": job} if with_env else {}))
        self.log({"ts": "2026-11-16T18:00:00.000Z", "job": job, "event": "start", "cmd": ["heavy-gate", "--", "npm", "test"], "cwd": "/x", "pane": None,
                  "session": None, "thread": thread, "pid": p.pid, "output": "o.log", "boot": boot})
        return p

    def kgate_entry(self, kid, thread=MINE, job=None, pidns="same", tamper=False):
        p = self.start_process()
        if LINUX:
            fields = Path("/proc/%d/stat" % p.pid).read_text().rsplit(")", 1)[1].split()
            start = fields[19]
            cmd = Path("/proc/%d/cmdline" % p.pid).read_bytes().replace(b"\0", b" ").decode().strip()
            ns = os.readlink("/proc/self/ns/pid") if pidns == "same" else pidns
        else:
            start, cmd, ns = "n/a", "sleep", None
        (self.kg / "active" / (kid + ".json")).write_text(json.dumps({
            "id": kid, "job": job, "pid": p.pid, "start": "other" if tamper else start, "proc_cmd": cmd, "pidns": ns, "cwd": "/x", "argv": ["kgate", "--", "x"],
            "cmd": "scripts/gate.sh", "node": "n1", "cluster": "homelab", "pod": kid, "thread": thread}))
        return p

    def stop(self, p):
        p.kill()
        p.wait()

    # -- run-and-wake

    def test_a_running_run_and_wake_job_of_this_thread_refuses_the_stop_and_names_it_and_how_to_wait(self):
        p = self.rw_job("20261116T180000Z-aaaaaa")
        done = self.hook()
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("20261116T180000Z-aaaaaa", done.stderr)
        self.assertIn("heavy-gate -- npm test", done.stderr)
        self.assertIn(MOD.run_and_wake_wait_hint("20261116T180000Z-aaaaaa"), done.stderr)
        self.assertIn("`run-and-wake --wait 20261116T180000Z-aaaaaa`", done.stderr, "the wait that also drops the duplicate wake, not a bare pid wait")
        self.assertNotIn(MOD.wait_hint(p.pid), done.stderr)
        self.assertIn("t3_background_wait", done.stderr)

    def test_the_stop_is_allowed_once_the_job_has_ended(self):
        p = self.rw_job("20261116T180000Z-aaaaaa")
        self.assertEqual(self.hook().returncode, 2)
        self.stop(p)
        self.assertEqual(self.hook().returncode, 0)   # process gone, no end record: a crashed watcher must not trap the session

    def test_an_end_record_releases_the_stop_even_while_the_pid_still_exists(self):
        self.rw_job("20261116T180000Z-aaaaaa")
        self.log({"ts": "2026-11-16T18:05:00.000Z", "job": "20261116T180000Z-aaaaaa", "event": "end", "exit": 0, "signal": None, "duration_s": 300})
        self.assertEqual(self.hook().returncode, 0)

    def test_another_threads_job_is_not_counted(self):
        self.rw_job("20261116T180000Z-bbbbbb", thread=OTHER)
        self.rw_job("20261116T180000Z-cccccc", thread=None)
        self.assertEqual(self.hook().returncode, 0)

    def test_only_this_threads_job_is_named_when_both_run(self):
        self.rw_job("20261116T180000Z-bbbbbb", thread=OTHER)
        self.rw_job("20261116T180000Z-aaaaaa")
        done = self.hook()
        self.assertEqual(done.returncode, 2)
        self.assertIn("aaaaaa", done.stderr)
        self.assertNotIn("bbbbbb", done.stderr)

    @unittest.skipUnless(LINUX, "reads /proc/<pid>/environ")
    def test_a_recycled_pid_is_not_taken_for_the_job(self):
        self.rw_job("20261116T180000Z-aaaaaa", with_env=False)   # a live process that does not carry the job's id
        self.assertEqual(self.hook().returncode, 0)

    @unittest.skipUnless(LINUX, "reads the boot id")
    def test_a_job_from_an_earlier_boot_is_not_running(self):
        self.rw_job("20261116T180000Z-aaaaaa", boot="00000000-0000-0000-0000-000000000000")
        self.assertEqual(self.hook().returncode, 0)

    # -- kgate

    def test_a_running_kgate_client_of_this_thread_refuses_the_stop_and_names_it(self):
        p = self.kgate_entry("kgate-1794853578-111")
        done = self.hook()
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("kgate job kgate-1794853578-111", done.stderr)
        self.assertIn("kgate cancel kgate-1794853578-111", done.stderr)
        self.assertIn(MOD.wait_hint(p.pid), done.stderr)

    def test_the_stop_is_allowed_when_the_kgate_client_is_gone_or_was_replaced(self):
        p = self.kgate_entry("kgate-1794853578-111")
        self.assertEqual(self.hook().returncode, 2)
        self.stop(p)
        self.assertEqual(self.hook().returncode, 0)
        self.kgate_entry("kgate-1794853578-222", tamper=True)   # same pid, different start time: a recycled pid
        self.assertEqual(self.hook().returncode, 0)

    @unittest.skipUnless(LINUX, "pid namespaces are Linux")
    def test_a_client_in_another_pid_namespace_is_not_counted(self):
        self.kgate_entry("kgate-1794853578-111", pidns="pid:[1]")
        self.assertEqual(self.hook().returncode, 0)

    def test_another_threads_kgate_job_is_not_counted(self):
        self.kgate_entry("kgate-1794853578-111", thread=OTHER)
        self.kgate_entry("kgate-1794853578-222", thread=None)   # an entry written before the field existed
        self.assertEqual(self.hook().returncode, 0)

    def test_a_kgate_job_started_by_run_and_wake_is_listed_once_as_the_run_and_wake_job(self):
        self.rw_job("20261116T180000Z-aaaaaa")
        self.kgate_entry("kgate-1794853578-111", job="20261116T180000Z-aaaaaa")
        done = self.hook()
        self.assertEqual(done.returncode, 2)
        self.assertIn("1 job ", done.stderr)
        self.assertNotIn("kgate job kgate-1794853578-111", done.stderr)

    def test_both_kinds_are_named_together(self):
        self.rw_job("20261116T180000Z-aaaaaa")
        self.kgate_entry("kgate-1794853578-111")
        done = self.hook()
        self.assertEqual(done.returncode, 2)
        self.assertIn("2 jobs", done.stderr)
        self.assertIn("run-and-wake job 20261116T180000Z-aaaaaa", done.stderr)
        self.assertIn("kgate job kgate-1794853578-111", done.stderr)

    # -- count mode (the lead's turn-end check takes the number as a fact)

    def test_count_prints_the_running_jobs_of_this_thread_and_never_refuses(self):
        self.rw_job("20261116T180000Z-aaaaaa")
        self.rw_job("20261116T180000Z-bbbbbb", thread=OTHER)
        self.kgate_entry("kgate-1794853578-111")
        self.kgate_entry("kgate-1794853578-222", job="20261116T180000Z-aaaaaa")
        done = self.hook(MINE, "--count")
        self.assertEqual((done.returncode, done.stdout.strip(), done.stderr), (0, "2", ""))

    def test_count_is_zero_with_nothing_running_with_no_thread_and_on_unreadable_records(self):
        self.assertEqual(self.hook(MINE, "--count").stdout.strip(), "0")
        self.rw_job("20261116T180000Z-aaaaaa")
        self.assertEqual(self.hook(None, "--count").stdout.strip(), "0")
        (self.rw / "log.jsonl").write_text('{"event": "start", "thread": "thread:me" broken\n')
        done = self.hook(MINE, "--count")
        self.assertEqual((done.returncode, done.stdout.strip()), (0, "0"))

    # -- fail open

    def test_no_thread_means_no_refusal(self):
        self.rw_job("20261116T180000Z-aaaaaa")
        self.assertEqual(self.hook(thread=None).returncode, 0)

    def test_unreadable_records_never_trap_the_session(self):
        (self.rw / "log.jsonl").write_text('{"event": "start", "thread": "thread:me" broken\n\x00\xff\n')
        (self.kg / "active" / "kgate-1-1.json").write_text("{not json")
        self.assertEqual(self.hook().returncode, 0)
        shutil.rmtree(self.rw)
        shutil.rmtree(self.kg)
        self.assertEqual(self.hook().returncode, 0)


class WaitHintTest(unittest.TestCase):
    """`tail --pid` is GNU only; the hint on macOS must be a command stock macOS has."""

    def test_macos_hint_uses_caffeinate_and_not_the_gnu_only_tail_option(self):
        hint = MOD.wait_hint(4242, "darwin")
        self.assertIn("`caffeinate -w 4242`", hint)
        self.assertNotIn("--pid", hint)
        self.assertIn("t3_background_wait", hint)

    def test_linux_hint_is_tail_pid(self):
        self.assertIn("`tail --pid=4242 -f /dev/null`", MOD.wait_hint(4242, "linux"))

    def test_the_default_follows_the_running_platform(self):
        self.assertEqual(MOD.wait_hint(7), MOD.wait_hint(7, sys.platform))


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi needed")
class SeatFileTest(unittest.TestCase):
    """Only the builder's seat file carries this Stop hook (the lead's carries lead_turn_end.py, tested in tests/lead-turn-end); it runs the script and passes its exit 2 through; it fails open."""

    @staticmethod
    def render(seat, profile):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "chezmoi.yaml"
            cfg.write_text(json.dumps({"data": {"profile": profile}}))
            r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                               input=(ROOT / ("dot_claude/fleet/seat-%s.json.tmpl" % seat)).read_text(), capture_output=True, text=True, timeout=120,
                               env=dict(os.environ, HOME=tmp))
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def test_only_the_builder_seat_has_this_stop_hook_on_both_profiles(self):
        for profile in ("personal", "axon-work-computer"):
            for seat in ("builder", "lead", "planner", "reviewer", "scout", "coordinator"):
                hooks = self.render(seat, profile).get("hooks")
                if seat == "lead":
                    self.assertNotIn("stop_running_jobs.py", json.dumps(hooks))   # the lead's own Stop hook is lead_turn_end.py
                elif seat == "builder":
                    self.assertEqual(list(hooks), ["Stop"], (profile, seat))
                    self.assertEqual(len(hooks["Stop"]), 1)
                    self.assertIn("stop_running_jobs.py", hooks["Stop"][0]["hooks"][0]["command"])
                else:
                    self.assertIsNone(hooks, (profile, seat))

    def test_the_command_passes_exit_2_through_and_fails_open(self):
        command = self.render("builder", "personal")["hooks"]["Stop"][0]["hooks"][0]["command"]
        with tempfile.TemporaryDirectory() as home:
            def run(thread=None):
                env = {**os.environ, "HOME": home, "RUN_AND_WAKE_STATE": home + "/rw", "KGATE_STATE": home + "/kg"}
                env.pop("T3CODE_THREAD_ID", None)
                if thread:
                    env["T3CODE_THREAD_ID"] = thread
                return subprocess.run(["sh", "-c", command], input="{}", capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(run().returncode, 0)   # script not installed: allowed
            hooks = Path(home) / ".local/share/agent-harness/hooks"
            hooks.mkdir(parents=True)
            shutil.copy(HOOK, hooks / "stop_running_jobs.py")
            self.assertEqual(run("thread:none").returncode, 0)   # installed, nothing running
            sleeper = subprocess.Popen(["sleep", "60"], env={**os.environ, "RUN_AND_WAKE_JOB": "j1"})
            self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
            os.makedirs(home + "/rw")
            Path(home + "/rw/log.jsonl").write_text(json.dumps({"event": "start", "job": "j1", "thread": "thread:t", "pid": sleeper.pid, "cmd": ["sleep", "60"], "ts": "t"}) + "\n")
            done = run("thread:t")
            self.assertEqual(done.returncode, 2, done.stderr)
            self.assertIn("j1", done.stderr)


if __name__ == "__main__":
    unittest.main()
