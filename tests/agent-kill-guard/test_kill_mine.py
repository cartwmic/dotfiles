"""kill-mine (dot_local/bin/executable_kill-mine): signals only the processes the caller's own agent session started.

Fake sessions are real processes that carry the marker variables a harness gives its tool-call shells; the tests run the real script as the caller.
Linux only (it reads /proc)."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
SCRIPT = ROOT / "dot_local/bin/executable_kill-mine"
SLEEPER = "import sys,time; print('up', flush=True); time.sleep(600)"
STUBBORN = "import signal,sys,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('up', flush=True); time.sleep(600)"

# A Claude Code tool-call shell: the thread id and the session id. A harness process (claude, T3's sh wrapper) has the thread id only.
CLAUDE_A = {"T3CODE_THREAD_ID": "thread-A", "CLAUDE_CODE_SESSION_ID": "session-A"}
CLAUDE_B = {"T3CODE_THREAD_ID": "thread-B", "CLAUDE_CODE_SESSION_ID": "session-B"}


def env(**markers):
    return {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/"), **markers}


class Sessions(unittest.TestCase):
    """Fake agent sessions: real processes that carry the marker variables of a harness's tool-call shells."""

    def setUp(self):
        self.token = "km-" + uuid.uuid4().hex  # in every helper's command line, so one pattern matches them all
        self.procs = []
        self.addCleanup(self.reap)

    def reap(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
            p.stdout.close()

    def start(self, markers, code=SLEEPER, *words):
        p = subprocess.Popen([sys.executable, "-c", code, self.token, *words], env=env(**markers), stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        self.assertEqual(p.stdout.readline().strip(), "up")  # ready: the signal handler (if any) is installed
        return p

    def kill_mine(self, caller, *args, pattern=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args, pattern or self.token], env=env(**caller), capture_output=True, text=True, timeout=30)

    def assertDead(self, p):
        self.assertIsNotNone(p.wait(timeout=10))

    def assertAlive(self, p):
        self.assertIsNone(p.poll())


@unittest.skipUnless(sys.platform == "linux", "kill-mine reads /proc")
class KillMine(Sessions):
    # --- the session filter -------------------------------------------------------------------------------------------------------

    def test_kills_its_own_session_and_leaves_an_identical_process_of_another(self):
        a, b = self.start(CLAUDE_A), self.start(CLAUDE_B)
        run = self.kill_mine(CLAUDE_A)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertDead(a)
        self.assertAlive(b)
        self.assertIn("signalled %d " % a.pid, run.stdout)
        self.assertNotIn(str(b.pid), run.stdout)

    def test_the_same_thread_after_a_resume_is_still_mine(self):
        old = self.start({"T3CODE_THREAD_ID": "thread-A", "CLAUDE_CODE_SESSION_ID": "session-before-resume"})
        self.assertEqual(self.kill_mine({"T3CODE_THREAD_ID": "thread-A", "CLAUDE_CODE_SESSION_ID": "session-after-resume"}).returncode, 0)
        self.assertDead(old)

    def test_without_t3_the_session_id_decides(self):
        a, b = self.start({"CLAUDE_CODE_SESSION_ID": "s1"}), self.start({"CLAUDE_CODE_SESSION_ID": "s2"})
        self.assertEqual(self.kill_mine({"CLAUDE_CODE_SESSION_ID": "s1"}).returncode, 0)
        self.assertDead(a)
        self.assertAlive(b)

    def test_pi_sessions_sharing_one_inherited_thread_id_are_told_apart(self):
        one = self.start({"T3CODE_THREAD_ID": "shared", "PI_SESSION_FILE": "/s/1.jsonl"})
        two = self.start({"T3CODE_THREAD_ID": "shared", "PI_SESSION_FILE": "/s/2.jsonl"})
        self.assertEqual(self.kill_mine({"T3CODE_THREAD_ID": "shared", "PI_SESSION_FILE": "/s/1.jsonl"}).returncode, 0)
        self.assertDead(one)
        self.assertAlive(two)

    def test_a_harness_process_is_never_mine_even_with_the_same_thread_id(self):
        harness = self.start({"T3CODE_THREAD_ID": "thread-A"})  # claude, T3's sh wrapper: the thread id, no tool-call-shell variable
        pi = self.start({"T3CODE_THREAD_ID": "shared"})          # Pi itself: no PI_SESSION_FILE
        for caller in (CLAUDE_A, {"T3CODE_THREAD_ID": "shared", "PI_SESSION_FILE": "/s/1.jsonl"}):
            run = self.kill_mine(caller)
            self.assertEqual(run.returncode, 1, run.stderr)
            self.assertIn("did not start them", run.stderr)
        self.assertAlive(harness)
        self.assertAlive(pi)

    # --- the caller ---------------------------------------------------------------------------------------------------------------

    def test_never_kills_its_own_caller_or_itself(self):
        a = self.start(CLAUDE_A)
        # The shell's command line holds the token too, so it matches the pattern; it is the caller (the tool-call shell) and must survive.
        shell = subprocess.run(["sh", "-c", "%s %s %s; echo survived-$?" % (sys.executable, SCRIPT, self.token)], env=env(**CLAUDE_A),
                               capture_output=True, text=True, timeout=30)
        self.assertIn("survived-0", shell.stdout)
        self.assertDead(a)
        self.assertNotIn("sh -c", shell.stdout)

    def test_refuses_with_no_session_marker_and_kills_nothing(self):
        a = self.start(CLAUDE_A)
        for caller in ({}, {"T3CODE_THREAD_ID": "thread-A"}):  # the thread id alone is a harness marker, not a tool-call shell's
            run = self.kill_mine(caller)
            self.assertEqual(run.returncode, 2)
            self.assertIn("no agent session marker", run.stderr)
        self.assertAlive(a)

    def test_refuses_on_macos(self):
        loader = importlib.machinery.SourceFileLoader("kill_mine", str(SCRIPT))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader("kill_mine", loader))
        loader.exec_module(module)
        err = io.StringIO()
        with mock.patch.object(sys, "platform", "darwin"), contextlib.redirect_stderr(err):
            self.assertEqual(module.main(["x"], env=CLAUDE_A), 2)
        self.assertIn("kill <pid>", err.getvalue())

    # --- the command line ---------------------------------------------------------------------------------------------------------

    def test_nothing_matching_exits_1_and_says_so(self):
        run = self.kill_mine(CLAUDE_A, pattern="km-no-such-process-" + uuid.uuid4().hex)
        self.assertEqual(run.returncode, 1)
        self.assertIn("no process matches", run.stderr)

    def test_dry_run_names_the_process_and_signals_nothing(self):
        a = self.start(CLAUDE_A)
        run = self.kill_mine(CLAUDE_A, "--dry-run")
        self.assertEqual(run.returncode, 0)
        self.assertIn("would signal %d " % a.pid, run.stdout)
        self.assertAlive(a)

    def test_the_signal_option_reaches_a_process_that_ignores_term(self):
        stubborn = self.start(CLAUDE_A, STUBBORN)
        self.assertEqual(self.kill_mine(CLAUDE_A).returncode, 0)  # TERM is ignored
        self.assertAlive(stubborn)
        self.assertEqual(self.kill_mine(CLAUDE_A, "-9").returncode, 0)
        self.assertDead(stubborn)
        self.assertEqual(stubborn.returncode, -9)

    def test_signal_names_and_pgrep_f_are_accepted(self):
        for args in (("-KILL",), ("-SIGKILL",), ("-f", "-KILL")):
            p = self.start(CLAUDE_A)
            self.assertEqual(self.kill_mine(CLAUDE_A, *args).returncode, 0, args)
            self.assertDead(p)
            self.assertEqual(p.returncode, -9, args)

    def test_a_pattern_that_starts_with_a_dash_goes_after_double_dash(self):
        a = self.start(CLAUDE_A)
        run = subprocess.run([sys.executable, str(SCRIPT), "--", "-c.*" + self.token], env=env(**CLAUDE_A), capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertDead(a)

    def test_usage_errors_exit_2(self):
        for args in ([], ["-NOPE", "x"], ["a", "b"], ["--", "("]):
            run = subprocess.run([sys.executable, str(SCRIPT), *args], env=env(**CLAUDE_A), capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 2, args)
            self.assertIn("kill-mine:", run.stderr)


HOOK = ROOT / "dot_local/share/agent-harness/hooks/refuse_pattern_kill.py"
# Real commands the hook refused in agent sessions (week of 2026-11-09, retro build-1116 L6), with the command line of the process each one was after.
REAL = [
    ("pkill -f 'ssh.*18317' 2>/dev/null", "ssh -i k -o BatchMode=yes -f -L 18317:127.0.0.1:18317 homelab"),
    ("pkill -f 'remote-debugging-port=9333'", "chromium --remote-debugging-port=9333 --user-data-dir=/tmp/p"),
    ("pkill -f \"vitest run\"", "node /w/node_modules/.bin/vitest run src/core.test.ts"),
    ("pkill -f \"http.server 8765\"", "python3 -m http.server 8765"),
    ("pkill -TERM -f \"rebuild.sh --host 192.0.2.1\"", "bash rebuild.sh --host 192.0.2.1"),
    ("pkill -f -- '--user-data-dir=/tmp/profile-x'", "chromium --user-data-dir=/tmp/profile-x --headless"),
]


def rewrite(command):
    """pkill [-f] [-SIGNAL] PATTERN  ->  kill-mine [-SIGNAL] -- PATTERN: the change an agent makes after the refusal."""
    words = [w for w in shlex.split(command.split(" 2>")[0]) if w not in ("pkill", "-f", "--")]
    return words[:-1], words[-1]  # the pattern is the last word, even when it starts with -


@unittest.skipUnless(sys.platform == "linux", "kill-mine reads /proc")
class ReplayOfRefusedCommands(Sessions):
    def test_the_refusal_names_kill_mine_before_the_pid_advice(self):
        for command, _ in REAL:
            with self.subTest(command=command):
                run = subprocess.run([sys.executable, str(HOOK), "--command", command], capture_output=True, text=True, timeout=30)
                self.assertEqual(run.returncode, 2)
                self.assertIn("refused in agent sessions", run.stderr)
                self.assertLess(run.stderr.index("kill-mine"), run.stderr.index("exact PID"))
                self.assertIn("kgate cancel <id>", run.stderr)

    def test_the_kill_mine_form_of_each_kills_the_victim_of_this_session_only(self):
        for command, victim in REAL:
            with self.subTest(command=command):
                self.token = "km-" + uuid.uuid4().hex
                mine, theirs = self.start(CLAUDE_A, SLEEPER, victim), self.start(CLAUDE_B, SLEEPER, victim)
                flags, pattern = rewrite(command)
                run = subprocess.run([sys.executable, str(SCRIPT), *flags, "--", pattern], env=env(**CLAUDE_A), capture_output=True, text=True, timeout=30)
                self.assertEqual(run.returncode, 0, "%s -> %s: %s" % (command, [*flags, pattern], run.stderr))
                self.assertDead(mine)
                self.assertAlive(theirs)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi needed")
class Deploy(unittest.TestCase):
    def test_deployed_executable_on_both_desktop_profiles_and_not_on_termux(self):
        for profile, want in (("personal", True), ("axon-work-computer", True), ("termux", False)):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as tmp:
                home = Path(tmp) / "home"
                home.mkdir()
                (Path(tmp) / "chezmoi.yaml").write_text("data:\n  profile: %s\n" % profile)
                run = subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(Path(tmp) / "chezmoi.yaml"), "--config-format", "yaml",
                                      "--destination", str(home), "managed"], capture_output=True, text=True, env=source_tree.chezmoi_env(home), timeout=120)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(".local/bin/kill-mine" in run.stdout.split(), want)


if __name__ == "__main__":
    unittest.main()
