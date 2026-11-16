"""The kitty helper for agent-desktop on a Mac (.chezmoitemplates/agent-desktop-relay.sh, installed as ~/.local/bin/agent-desktop-relay)
and the macOS script's side of it: an ssh call is handed to the helper, which runs it inside kitty (the app that holds the macOS
permissions) and hands back stdout, stderr and the exit code.

The real relay script and the real macOS script run under /bin/sh with a PATH of stubs and coreutils only. `open` is a fake kitty:
it starts what kitty would be told to run, in the background. Nothing here needs a Mac. What it cannot show (that kitty holds the
permissions, that `open` starts kitty in a GUI session, bash 3.2 on a Mac) is the live check's job (docs/agent-desktop.md).
Run: python3 -m unittest discover -s tests/agent-desktop -p 'test_macos_relay.py'
"""
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BODY = REPO / ".chezmoitemplates/agent-desktop-macos.sh"
RELAY = REPO / ".chezmoitemplates/agent-desktop-relay.sh"
REAL = ("cat", "cut", "date", "head", "id", "ln", "mkdir", "mkfifo", "mktemp", "mv", "nohup", "ps", "rm", "sleep", "tr")
DOC = "docs/agent-desktop.md"

FAKE_OPEN = """#!/bin/sh
echo "open $*" >> "$FAKE_CALLS"
[ -z "${FAKE_OPEN_NOOP:-}" ] || exit 0
[ "$1" = -na ] || exit 64
shift 2
[ "$1" = --args ] || exit 64
shift
while :; do case ${1:-} in --*=*) shift ;; *) break ;; esac; done
if [ -n "${FAKE_KITTY:-}" ]; then nohup "$FAKE_KITTY" "$@" >/dev/null 2>&1 & exit 0; fi  # the helper is a child of a process named kitty
nohup "$@" >/dev/null 2>&1 &
"""

# A stand-in for the kitty program: it runs what it is told to run as its child, as kitty does, so the helper's parent is "kitty".
FAKE_KITTY = """#!/bin/sh
"$@"
"""

# Stands in for the macOS script when the relay is tested alone. Each mode shows one thing the relay must carry.
FAKE_BODY = """#!/bin/sh
case ${1:-} in
  argv) for a in "$@"; do printf '%s\\0' "$a"; done ;;
  bytes) printf 'out-no-newline'; printf 'err\\n\\n' >&2; exit 7 ;;
  pwd) pwd -P ;;
  env) printf '%s|%s|%s' "${AGENT_DESKTOP_IN_RELAY:-}" "${AGENT_DESKTOP_RUN_ID:-}" "${SSH_CONNECTION:-}" ;;
  echo-after) sleep "$2"; printf '%s' "$3" ;;
  kill-helper) kill -9 "$(cat "$XDG_STATE_HOME/agent-desktop/relay/pid")"; sleep 8 ;;
esac
"""

# Stand-ins for the tools the macOS script calls (the same idea as test_macos.py). The helper is started with FAKE_WHO=helper and an
# ssh caller's environment does not have it, so a result that says "helper" came through the helper.
FAKE_TOOL = """#!/bin/sh
name=${0##*/}
case $name in
  screencapture) for a in "$@"; do last=$a; done; echo png > "$last" ;;
  osascript)
    case ${5:-} in
      preflight) echo granted ;;
      windows) printf 'Calculator\\t%s\\t100,80\\t232x408\\t511\\n' "${FAKE_WHO:-nobody}" ;;
      cursor) if [ "${FAKE_WHO:-}" = helper ]; then echo "961 553"; else echo "1 1"; fi ;;
      focus) echo "execution error: no running app named $6" >&2; exit 1 ;;
      type) printf '%s' "$6" > "$FAKE_TYPED" ;;
      [0-9]*) echo "hide $5" >> "$FAKE_CALLS"; [ -z "${FAKE_HIDE_EXIT:-}" ] || { echo "execution error: no app" >&2; exit 1; } ;;
    esac ;;
esac
"""


def sh_env(tmp, home, bin_dir, **extra):
    env = {"PATH": str(bin_dir), "HOME": str(home), "XDG_STATE_HOME": str(home / ".state"), "FAKE_CALLS": str(tmp / "calls"),
           "FAKE_TYPED": str(tmp / "typed"), "SSH_CONNECTION": "10.0.0.1 1 10.0.0.2 22"}
    env.update(extra)
    return env


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="adr-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.bin = self.tmp / "bin"
        (self.home / ".local/bin").mkdir(parents=True)
        self.bin.mkdir()
        for name in REAL:
            (self.bin / name).symlink_to(shutil.which(name))
        for name, text in (("open", FAKE_OPEN), ("screencapture", FAKE_TOOL), ("osascript", FAKE_TOOL)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.relay = self.home / ".local/bin/agent-desktop-relay"
        self.body = self.home / ".local/bin/agent-desktop"
        shutil.copy(RELAY, self.relay)
        shutil.copy(BODY, self.body)
        for f in (self.relay, self.body):
            f.chmod(0o755)
        self.fake_body = self.tmp / "fake-body"
        self.fake_body.write_text(FAKE_BODY)
        self.fake_body.chmod(0o755)
        self.state = self.home / ".state/agent-desktop"
        self.addCleanup(self.kill_helper)

    def env(self, **extra):
        return sh_env(self.tmp, self.home, self.bin, **extra)

    def run_cmd(self, argv, cwd=None, timeout=30, **extra):
        return subprocess.run(argv, env=self.env(**extra), capture_output=True, timeout=timeout, cwd=cwd)

    def relay_cmd(self, *args, **kw):
        return self.run_cmd(["/bin/sh", str(self.relay), *args], **kw)

    def ssh(self, *args, **kw):
        """What an agent's ssh shell runs: the installed macOS script, with SSH_CONNECTION set."""
        return self.run_cmd(["/bin/sh", str(self.body), *args], **kw)

    def pid(self):
        p = self.state / "relay/pid"
        return int(p.read_text()) if p.exists() else None

    def kill_helper(self):
        pid = self.pid()
        if pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def start_helper(self, **extra):
        r = self.relay_cmd("start", AGENT_DESKTOP_RELAY_START_WAIT="10", **extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def calls(self):
        f = self.tmp / "calls"
        return f.read_text().splitlines() if f.exists() else []


class RelayTest(Base):
    """The relay alone, with a stand-in for the macOS script."""

    def setUp(self):
        super().setUp()
        self.start_helper(AGENT_DESKTOP_BIN=str(self.fake_body))

    def call(self, *args, **kw):
        return self.relay_cmd("call", *args, **kw)

    def test_stdout_stderr_and_exit_code_come_back_unchanged(self):
        r = self.call("bytes")
        self.assertEqual((r.stdout, r.stderr, r.returncode), (b"out-no-newline", b"err\n\n", 7))

    def test_arguments_with_spaces_quotes_newlines_and_nothing_arrive_unchanged(self):
        args = ["argv", "a b", "it's \"q\"", "line1\nline2", "ends\n\n", "", "-n", "$HOME `x` $(y)", "*", "  lead", "tab\tx", "back\\slash"]
        r = self.call(*args)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, b"".join(a.encode() + b"\0" for a in args))

    def test_the_call_runs_in_the_callers_directory(self):
        d = self.tmp / "work dir"
        d.mkdir()
        r = self.call("pwd", cwd=d)
        self.assertEqual(r.stdout.decode().strip(), str(d.resolve()))

    def test_the_helper_runs_the_script_as_inside_the_helper_and_hands_it_the_run_id(self):
        r = self.call("env")
        marker, run_id, _ = r.stdout.decode().split("|")
        self.assertEqual(marker, "1")
        self.assertTrue(run_id)
        line = [l for l in (self.state / "agent-desktop.log").read_text().splitlines() if "relay call" in l][-1]
        self.assertIn("run=%s " % run_id, line)

    def test_callers_at_the_same_time_each_get_their_own_output(self):
        results = {}

        def go(i):
            results[i] = self.call("echo-after", "0.%d" % (9 - i), "caller-%d" % i)

        threads = [threading.Thread(target=go, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        for i in range(8):
            self.assertEqual((results[i].stdout, results[i].returncode), (("caller-%d" % i).encode(), 0), i)

    def test_status_says_running_and_exits_zero(self):
        r = self.relay_cmd("status")
        self.assertEqual(r.returncode, 0)
        self.assertIn(b"running", r.stdout)
        self.assertIn(str(self.pid()).encode(), r.stdout)

    def test_a_second_helper_will_not_start_while_one_is_running(self):
        first = self.pid()
        r = self.relay_cmd("serve", timeout=10)
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"already running", r.stderr)
        self.assertEqual(self.pid(), first)
        opens = len(self.calls())
        self.assertEqual(self.relay_cmd("start").returncode, 0)
        self.assertEqual(len(self.calls()), opens, "start opened kitty again while the helper was running")
        self.assertEqual(self.call("bytes").returncode, 7)

    def test_a_helper_that_is_still_setting_up_is_not_taken_over(self):
        # a second helper starts after the first has its pid file and before it has made its FIFO
        self.relay_cmd("stop")
        fake = self.tmp / "agent-desktop-relay"  # a live process with the helper's name and no FIFO
        # a script, not a copy of the sleep binary: a multi-call coreutils (Ubuntu 26.04) exits when run under another name
        fake.write_text("#!/bin/sh\nwhile :; do sleep 1; done\n")
        fake.chmod(0o755)
        other = subprocess.Popen([str(fake)])
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        self.assertIsNone(other.poll())
        (self.state / "relay").mkdir(parents=True, exist_ok=True)
        (self.state / "relay/pid").write_text("%d\n" % other.pid)
        r = self.relay_cmd("serve", timeout=10)
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"already running", r.stderr)
        self.assertEqual(self.pid(), other.pid)

    def test_the_helper_dying_during_a_call_ends_it_with_exit_one(self):
        t0 = time.time()
        r = self.call("kill-helper", timeout=20)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, b"")
        self.assertIn(b"agent-desktop-relay", r.stderr)
        self.assertLess(time.time() - t0, 6, "waited for the call to finish instead of noticing the helper was gone")

    def test_start_brings_the_helper_back_after_it_was_killed(self):
        old = self.pid()
        os.kill(old, signal.SIGKILL)
        self.assertEqual(self.call("bytes").returncode, 1)
        self.start_helper(AGENT_DESKTOP_BIN=str(self.fake_body))
        self.assertNotEqual(self.pid(), old)
        self.assertEqual(self.call("bytes").returncode, 7)

    def test_stop_ends_the_helper_and_start_brings_it_back(self):
        old = self.pid()
        r = self.relay_cmd("stop")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.relay_cmd("status").returncode, 1)
        with self.assertRaises(OSError):
            os.kill(old, 0)
        self.assertEqual(self.relay_cmd("stop").returncode, 0, "stopping a helper that is not running is not an error")
        self.start_helper(AGENT_DESKTOP_BIN=str(self.fake_body))
        self.assertEqual(self.call("bytes").returncode, 7)

    def test_stop_signal_removes_its_state(self):
        os.kill(self.pid(), signal.SIGTERM)
        deadline = time.time() + 5
        while time.time() < deadline and (self.state / "relay/pid").exists():
            time.sleep(0.05)
        self.assertFalse((self.state / "relay/pid").exists())
        self.assertEqual(self.relay_cmd("status").returncode, 1)


class NotRunningTest(Base):
    def assert_names_the_helper(self, r):
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stdout, b"")
        lines = r.stderr.decode().strip().splitlines()
        self.assertEqual(len(lines), 1, lines)
        for word in ("helper", "agent-desktop-relay start", DOC):
            self.assertIn(word, lines[0])

    def test_with_no_helper_an_ssh_call_exits_one_with_one_line_that_says_how_to_start_it(self):
        t0 = time.time()
        self.assert_names_the_helper(self.ssh("cursor", timeout=10))
        self.assertLess(time.time() - t0, 5)
        self.assertEqual(self.calls(), [], "the call started something")

    def test_state_left_by_a_dead_helper_does_not_hang_the_call(self):
        relay = self.state / "relay"
        relay.mkdir(parents=True)
        dead = subprocess.Popen(["sleep", "0"])
        dead.wait()
        (relay / "pid").write_text("%d\n" % dead.pid)
        os.mkfifo(relay / "requests")
        self.assert_names_the_helper(self.ssh("cursor", timeout=10))

    def test_a_pid_that_another_program_now_holds_is_not_the_helper(self):
        relay = self.state / "relay"
        relay.mkdir(parents=True)
        other = subprocess.Popen(["sleep", "30"])
        self.addCleanup(other.kill)
        (relay / "pid").write_text("%d\n" % other.pid)
        os.mkfifo(relay / "requests")
        self.assert_names_the_helper(self.ssh("cursor", timeout=10))
        self.assertEqual(self.relay_cmd("status").returncode, 1)

    def test_start_gives_up_with_exit_one_when_kitty_does_not_bring_the_helper_up(self):
        t0 = time.time()
        r = self.relay_cmd("start", FAKE_OPEN_NOOP="1", AGENT_DESKTOP_RELAY_START_WAIT="1", timeout=15)
        self.assertEqual(r.returncode, 1)
        self.assertIn(b"agent-desktop-relay", r.stderr)
        self.assertLess(time.time() - t0, 5)


class ThroughTheScriptTest(Base):
    """The macOS script as an agent's ssh shell runs it, with the helper running and the real script inside it."""

    def setUp(self):
        super().setUp()
        self.start_helper(FAKE_WHO="helper")

    def direct(self, *args, **kw):
        """The same call inside the helper's own environment: not over ssh, so the script runs it itself."""
        env = self.env(FAKE_WHO="helper")
        env.pop("SSH_CONNECTION")
        return subprocess.run(["/bin/sh", str(self.body), *args], env=env, capture_output=True, timeout=30, **kw)

    def test_a_call_over_ssh_gives_what_running_it_directly_gives(self):
        for args in (("windows",), ("cursor",), ("focus", "Nothing"), ("move", "x", "y"), ("bogus",), ()):
            with self.subTest(args=args):
                got, want = self.ssh(*args), self.direct(*args)
                self.assertEqual((got.stdout, got.stderr, got.returncode), (want.stdout, want.stderr, want.returncode))

    def test_exit_codes_one_and_two_pass_through(self):
        self.assertEqual(self.ssh("focus", "Nothing").returncode, 1)
        self.assertEqual(self.ssh("move", "1").returncode, 2)

    def test_text_to_type_arrives_unchanged_including_trailing_newlines(self):
        text = "line1\nline2 \"quoted\" it's\n\n"
        r = self.ssh("type", text)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.tmp / "typed").read_bytes(), text.encode())

    def test_the_script_inside_the_helper_does_not_hand_the_call_back_to_the_helper(self):
        # the helper was started from a shell with SSH_CONNECTION set; the call still finishes
        r = self.ssh("cursor", timeout=10)
        self.assertEqual((r.stdout, r.returncode), (b"961 553\n", 0), r.stderr)  # 961 553 is what the helper's environment answers

    def test_one_log_line_for_the_forwarded_call_and_the_steps_inside_share_its_run_id(self):
        self.assertEqual(self.ssh("move", "3", "4").returncode, 0)
        lines = (self.state / "agent-desktop.log").read_text().splitlines()
        relay_line = [l for l in lines if "relay call" in l]
        self.assertEqual(len(relay_line), 1, lines)
        run_id = relay_line[0].split("run=")[1].split()[0]
        steps = [l for l in lines if " move 3 4" in l]
        self.assertEqual(len(steps), 1, lines)
        self.assertIn("run=%s " % run_id, steps[0])
        self.assertIn("exit=0", relay_line[0])

    def test_the_log_for_a_forwarded_call_never_holds_the_typed_text(self):
        self.ssh("type", "secret phrase here")
        self.assertNotIn("secret phrase", (self.state / "agent-desktop.log").read_text())

    def test_the_forwarding_adds_little_time(self):
        def median(call):
            times = []
            for _ in range(9):
                t0 = time.time()
                call("cursor")
                times.append(time.time() - t0)
            return sorted(times)[4]

        self.ssh("cursor")
        forwarded, direct = median(self.ssh), median(self.direct)
        self.assertLess(forwarded - direct, 0.5, "forwarded %.3f s, direct %.3f s" % (forwarded, direct))  # about 0.1 s on the Mac mini


class HideTheWindowTest(Base):
    """After `start`, the helper's kitty is hidden with NSRunningApplication (no Automation permission), once."""

    def setUp(self):
        super().setUp()
        self.kitty = self.tmp / "Contents/MacOS/kitty"
        self.kitty.parent.mkdir(parents=True)
        self.kitty.write_text(FAKE_KITTY)
        self.kitty.chmod(0o755)

    def hides(self):
        return [c for c in self.calls() if c.startswith("hide ")]

    def kitty_pid(self):
        out = subprocess.run(["ps", "-p", str(self.pid()), "-o", "ppid="], capture_output=True, text=True).stdout.strip()
        return int(out)

    def test_start_hides_the_kitty_that_runs_the_helper(self):
        self.start_helper(FAKE_KITTY=str(self.kitty), AGENT_DESKTOP_BIN=str(self.fake_body))
        self.assertEqual(self.hides(), ["hide %d" % self.kitty_pid()])

    def test_starting_a_helper_that_is_already_running_hides_nothing_more(self):
        self.start_helper(FAKE_KITTY=str(self.kitty))
        r = self.relay_cmd("start")
        self.assertIn(b"already running", r.stdout)
        self.assertEqual(len(self.hides()), 1)

    def test_a_hide_that_fails_does_not_fail_start_and_is_logged(self):
        r = self.relay_cmd("start", FAKE_KITTY=str(self.kitty), FAKE_HIDE_EXIT="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(b"started", r.stdout)
        self.assertEqual(self.relay_cmd("status").returncode, 0)
        self.assertIn("could not hide", (self.state / "agent-desktop.log").read_text())

    def test_a_parent_that_is_not_kitty_is_never_hidden(self):
        self.start_helper()
        self.assertEqual(self.hides(), [])

    def test_the_hide_uses_nsrunningapplication_and_not_system_events(self):
        text = RELAY.read_text()
        self.assertIn("NSRunningApplication", text)
        self.assertNotIn("System Events", text)
        self.assertNotIn("Application(", text)


class WithoutTheHelperTest(Base):
    def test_a_mac_with_no_helper_installed_runs_the_call_itself_even_over_ssh(self):
        self.relay.unlink()
        r = self.ssh("cursor")
        self.assertEqual((r.stdout, r.returncode), (b"1 1\n", 0), r.stderr)

    def test_not_over_ssh_the_script_runs_the_call_itself_whether_or_not_the_helper_runs(self):
        env = self.env()
        env.pop("SSH_CONNECTION")
        r = subprocess.run(["/bin/sh", str(self.body), "cursor"], env=env, capture_output=True, timeout=30)
        self.assertEqual((r.stdout, r.returncode), (b"1 1\n", 0), r.stderr)


if __name__ == "__main__":
    unittest.main()
