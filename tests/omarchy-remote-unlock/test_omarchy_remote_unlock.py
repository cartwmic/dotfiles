"""scripts/omarchy-remote-unlock.sh against throwaway local sshd servers with a fake password agent.

The fake agent stands in for `systemd-tty-ask-password-agent --watch` behind the early-boot SSH server: it prints a
prompt, reads one line from the terminal and records it. Nothing here touches a real host or a real passphrase.
"""
import os
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "omarchy-remote-unlock.sh"
SSHD = shutil.which("sshd") or next((p for p in ("/usr/sbin/sshd",) if Path(p).exists()), None)
PASS = "fake-passphrase-7f3a91"
ALIAS = "omarchy-unlock"

AGENT = """#!/bin/bash
# Fake systemd-tty-ask-password-agent. mode: hold | exit-after | drop-first
dir=$(dirname "$0")
mode=$(cat "$dir/mode")
n=$(cat "$dir/count" 2>/dev/null || echo 0)
echo $((n + 1)) > "$dir/count"
printf 'Password: '
if [ "$mode" = drop-first ] && [ "$n" -eq 0 ]; then exit 0; fi
IFS= read -r line
printf '%s\\n' "$line" >> "$dir/received"
if [ "$mode" = exit-after ]; then exit 0; fi
sleep 5
"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for(check, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


def keygen(path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(path)], check=True)


@unittest.skipUnless(SSHD and shutil.which("ssh") and shutil.which("ssh-keygen"), "sshd, ssh and ssh-keygen are required")
class RemoteUnlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="remote-unlock-test."))
        for name in ("hostA", "hostB", "userkey", "ctlkey"):
            keygen(cls.tmp / name)
        cls.agent_dir = cls.tmp / "agent"
        # The caller's own ssh into "mac-mini": a plain login that runs whatever command it is given.
        cls.ctl_port = free_port()
        (cls.tmp / "ctl_authorized").write_text((cls.tmp / "ctlkey.pub").read_text())
        cls.ctl = cls.start_sshd(cls.ctl_port, cls.tmp / "hostB", cls.tmp / "ctl_authorized", cls.tmp / "ctl.log")

    @classmethod
    def tearDownClass(cls):
        cls.ctl.terminate()
        cls.ctl.wait()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    @staticmethod
    def start_sshd(port, host_key, authorized_keys, log):
        conf = log.with_suffix(".conf")
        conf.write_text(
            f"ListenAddress 127.0.0.1\nHostKey {host_key}\nAuthorizedKeysFile {authorized_keys}\n"
            "UsePAM no\nStrictModes no\nPasswordAuthentication no\nPidFile none\nLogLevel INFO\n")
        with open(log, "w") as stderr:
            proc = subprocess.Popen([SSHD, "-D", "-e", "-p", str(port), "-f", str(conf)], stderr=stderr)
        assert wait_for(lambda: proc.poll() is not None or _listening(port)), "sshd did not start"
        assert proc.poll() is None, log.read_text()
        return proc

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix="case.", dir=self.tmp))
        self.addCleanup(shutil.rmtree, self.work, True)
        self.log = self.work / "waiter.log"
        self.known_hosts = self.work / "known_hosts"
        self.waiter_tmp = self.work / "tmpdir"
        self.waiter_tmp.mkdir()
        self.servers = []
        self.addCleanup(self.stop_everything)

    def stop_everything(self):
        for pid in self.waiter_pids():
            os.kill(pid, signal.SIGTERM)
        for server in self.servers:
            server.terminate()
            server.wait()

    # ---- helpers ----

    def pin(self, key="hostA.pub"):
        done = subprocess.run(["bash", str(SCRIPT), "--pin-hostkey", str(self.tmp / key), "--alias", ALIAS, "--known-hosts", str(self.known_hosts)],
                              capture_output=True, text=True, timeout=20)
        self.assertEqual(done.returncode, 0, done.stderr)

    def target(self, port, host_key="hostA", mode="hold"):
        """An early-boot stand-in: sshd on `port` that accepts only userkey and forces the fake agent."""
        d = self.work / f"target{port}"
        d.mkdir()
        agent = d / "agent.sh"
        agent.write_text(AGENT)
        agent.chmod(0o755)
        (d / "mode").write_text(mode)
        (d / "authorized").write_text(f'command="{agent}" {(self.tmp / "userkey.pub").read_text()}')
        server = self.start_sshd(port, self.tmp / host_key, d / "authorized", d / "sshd.log")
        self.servers.append(server)
        return d

    def start_waiter(self, port, passphrase=PASS, timeout=60, extra=()):
        """Start the waiter the way the lead does: a passphrase piped into one ssh to the 'mac-mini'."""
        args = ["--host", "127.0.0.1", "--port", str(port), "--user", os.environ.get("USER") or "root",
                "--identity", str(self.tmp / "userkey"), "--known-hosts", str(self.known_hosts), "--log", str(self.log),
                "--timeout", str(timeout), "--interval", "0.5", "--prompt-delay", "0.5", "--linger", "1", *extra]
        remote = f"TMPDIR={shlex.quote(str(self.waiter_tmp))} bash {shlex.quote(str(SCRIPT))} " + " ".join(shlex.quote(a) for a in args)
        started = time.monotonic()
        # No timeout-then-ignore: if the waiter keeps the caller's pipes open, this call hangs and the test fails on the timeout.
        done = subprocess.run(
            ["ssh", "-F", "/dev/null", "-i", str(self.tmp / "ctlkey"), "-p", str(self.ctl_port), "-o", "IdentitiesOnly=yes",
             "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes", "127.0.0.1", remote],
            input=passphrase + "\n", capture_output=True, text=True, timeout=20)
        return done, time.monotonic() - started

    def waiter_pids(self):
        out = subprocess.run(["pgrep", "-f", "--", f"--log {self.log}"], capture_output=True, text=True).stdout.split()
        return [int(p) for p in out]

    def log_text(self):
        return self.log.read_text() if self.log.exists() else ""

    def received(self, target):
        f = target / "received"
        return f.read_text().splitlines() if f.exists() else []

    def accepted(self, target):
        return (target / "sshd.log").read_text().count("Accepted publickey")

    def assert_secret_nowhere(self, *texts):
        for text in texts:
            self.assertNotIn(PASS, text)

    # ---- tests ----

    def test_caller_returns_at_once_then_the_passphrase_is_sent_once_when_the_server_comes_up(self):
        self.pin()
        port = free_port()
        done, elapsed = self.start_waiter(port)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertLess(elapsed, 3, "the caller's ssh must return at once")
        self.assertTrue(wait_for(lambda: "waiting for" in self.log_text()))
        pids = self.waiter_pids()
        self.assertTrue(pids, "the waiter keeps running after the caller's ssh ended")

        # While it waits: the value is not in the process list, the waiter's environment or its arguments.
        ps = subprocess.run(["ps", "-ww", "-eo", "args"], capture_output=True, text=True).stdout
        self.assertNotIn(PASS, ps)
        for pid in pids:
            for name in ("environ", "cmdline"):
                p = Path(f"/proc/{pid}/{name}")
                if p.exists():
                    self.assertNotIn(PASS.encode(), p.read_bytes())

        agent = self.target(port)
        self.assertTrue(wait_for(lambda: self.received(agent)), "the passphrase should arrive once the server is up")
        self.assertTrue(wait_for(lambda: not self.waiter_pids()), "the waiter exits after sending")
        self.assertEqual(self.received(agent), [PASS])
        self.assertEqual(self.accepted(agent), 1)
        log = self.log_text()
        self.assertIn("connected", log)
        self.assertIn("passphrase written to the connection", log)
        self.assert_secret_nowhere(log, done.stdout, done.stderr, (agent / "sshd.log").read_text())
        self.assertEqual(list(self.waiter_tmp.iterdir()), [], "the waiter removes its temp files")

    def test_a_connection_that_drops_before_the_prompt_is_not_a_send_and_the_next_one_gets_it_once(self):
        self.pin()
        port = free_port()
        agent = self.target(port, mode="drop-first")
        self.start_waiter(port)
        self.assertTrue(wait_for(lambda: self.received(agent)))
        self.assertTrue(wait_for(lambda: not self.waiter_pids()))
        self.assertEqual(self.received(agent), [PASS])
        self.assertEqual(self.accepted(agent), 2)
        self.assertIn("connection closed before the passphrase was written", self.log_text())

    def test_a_connection_that_drops_after_the_send_is_never_retried(self):
        self.pin()
        port = free_port()
        agent = self.target(port, mode="exit-after")
        self.start_waiter(port)
        self.assertTrue(wait_for(lambda: not self.waiter_pids()), "the waiter exits after its one send")
        self.assertEqual(self.received(agent), [PASS])
        self.assertEqual(self.accepted(agent), 1)
        self.assertIn("connection closed by the server", self.log_text())

    def test_a_server_with_another_host_key_gets_nothing(self):
        self.pin("hostA.pub")
        port = free_port()
        agent = self.target(port, host_key="hostB")   # the normal sshd: right login key, wrong host key
        done, _ = self.start_waiter(port, timeout=3)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(wait_for(lambda: not self.waiter_pids()), "the waiter gives up at the timeout")
        self.assertEqual(self.received(agent), [])
        self.assertEqual(self.accepted(agent), 0, "the login must not get as far as accepting the key")
        self.assertFalse((agent / "count").exists(), "the forced command never ran")
        log = self.log_text()
        self.assertIn("Host key verification failed", log)
        self.assertIn("timeout", log)
        self.assertNotIn("connected", log)
        self.assert_secret_nowhere(log)

    def test_it_gives_up_at_the_timeout_when_nothing_answers(self):
        self.pin()
        started = time.monotonic()
        self.start_waiter(free_port(), timeout=2)
        self.assertTrue(wait_for(lambda: not self.waiter_pids()))
        self.assertLess(time.monotonic() - started, 10)
        log = self.log_text()
        self.assertIn("timeout after", log)
        self.assertIn("passphrase not sent", log)
        self.assert_secret_nowhere(log)

    def test_a_signal_stops_the_waiter_and_removes_its_temp_files(self):
        self.pin()
        self.start_waiter(free_port())
        self.assertTrue(wait_for(lambda: "waiting for" in self.log_text()))
        for pid in self.waiter_pids():
            os.kill(pid, signal.SIGTERM)
        self.assertTrue(wait_for(lambda: not self.waiter_pids()))
        self.assertIn("stopped by signal", self.log_text())
        self.assertEqual(list(self.waiter_tmp.iterdir()), [])

    # ---- argument and input handling ----

    def run_script(self, *args, stdin=""):
        return subprocess.run(["bash", str(SCRIPT), *args], input=stdin, capture_output=True, text=True, timeout=20)

    def test_it_refuses_to_start_without_a_pinned_host_key(self):
        done = self.run_script("--known-hosts", str(self.known_hosts), "--log", str(self.log), "--identity", str(self.tmp / "userkey"), stdin=PASS + "\n")
        self.assertEqual(done.returncode, 2)
        self.assertIn("--pin-hostkey", done.stderr)
        self.assertFalse(self.log.exists())
        self.assert_secret_nowhere(done.stdout, done.stderr)

    def test_it_refuses_an_empty_passphrase(self):
        self.pin()
        for stdin in ("", "\n"):
            done = self.run_script("--known-hosts", str(self.known_hosts), "--log", str(self.log), "--identity", str(self.tmp / "userkey"), stdin=stdin)
            self.assertEqual(done.returncode, 2)
        self.assertFalse(self.log.exists())

    def test_it_takes_no_passphrase_from_arguments(self):
        done = self.run_script(PASS)
        self.assertEqual(done.returncode, 2)
        self.assertIn("unknown argument", done.stderr)

    # ---- --pin-hostkey ----

    def known_lines(self):
        return self.known_hosts.read_text().splitlines()

    def test_pin_from_a_key_file_writes_one_line_under_the_alias(self):
        self.pin("hostA.pub")
        self.assertEqual(len(self.known_lines()), 1)
        self.assertTrue(self.known_lines()[0].startswith(f"{ALIAS} ssh-ed25519 "))
        self.assertNotIn("test", self.known_lines()[0], "the key comment is not copied")
        self.assertEqual(self.known_hosts.stat().st_mode & 0o777, 0o600)
        found = subprocess.run(["ssh-keygen", "-F", ALIAS, "-f", str(self.known_hosts)], capture_output=True, text=True)
        self.assertEqual(found.returncode, 0)

    def test_pin_from_a_line_and_from_tool_output_with_a_header(self):
        line = (self.tmp / "hostA.pub").read_text().strip()
        done = self.run_script("--pin-hostkey", line, "--alias", ALIAS, "--known-hosts", str(self.known_hosts))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.known_lines(), [f"{ALIAS} {' '.join(line.split()[:2])}"])
        header = f"Public key portion is:\n{(self.tmp / 'hostB.pub').read_text()}Fingerprint: SHA256:abc\n"
        done = self.run_script("--pin-hostkey", header, "--alias", ALIAS, "--known-hosts", str(self.known_hosts))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.known_lines(), [f"{ALIAS} {' '.join((self.tmp / 'hostB.pub').read_text().split()[:2])}"])

    def test_pin_replaces_only_the_alias_line_and_keeps_other_hosts(self):
        other = "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl"
        self.known_hosts.write_text(f"{other}\n{ALIAS} ssh-ed25519 AAAAOLDOLDOLD\n")
        self.pin("hostB.pub")
        lines = self.known_lines()
        self.assertEqual(lines[0], other)
        self.assertEqual(len(lines), 2)
        self.assertNotIn("OLDOLD", self.known_hosts.read_text())

    def test_pin_rejects_text_that_is_not_a_key_and_leaves_the_file_alone(self):
        self.known_hosts.write_text("keep me\n")
        done = self.run_script("--pin-hostkey", "not a key", "--alias", ALIAS, "--known-hosts", str(self.known_hosts))
        self.assertEqual(done.returncode, 2)
        self.assertEqual(self.known_hosts.read_text(), "keep me\n")


def _listening(port):
    with socket.socket() as s:
        s.settimeout(0.2)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    unittest.main()
