"""agent-chrome.service, the systemd user unit that starts the agent Chrome at login, and the script that loads it (real files, real chezmoi).
The unit parses with the expected keys, its ExecStart target is in the source tree, the load script renders, and both are ignored
everywhere except personal Linux. RestartJourneyTest runs the real unit file and the real launcher under the real user systemd manager, in a scratch
HOME on a scratch port, with a fake Chrome (AGENT_CHROME_REAL=1: the real Chrome, which needs a display): start, restart several times, restart
from a Chrome started by hand, stop. After every restart a NEW process must answer on the port. It skips when there is no user systemd manager."""
import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from test_render import ROOT, chezmoi

LAUNCHER = ROOT / "dot_local/bin/executable_agent-chrome"
UNIT = ROOT / "dot_config/systemd/user/agent-chrome.service"
LOADER = ROOT / "run_onchange_after_78_agent_chrome_systemd.sh.tmpl"
IGNORED = (".config/systemd/user/agent-chrome.service", "78_agent_chrome_systemd.sh")


class LoginUnitTest(unittest.TestCase):
    def test_unit_has_the_expected_keys(self):
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read(UNIT)
        svc = cp["Service"]
        self.assertEqual((svc["Type"], svc["Restart"]), ("simple", "on-failure"))
        self.assertTrue(svc["ExecStartPre"].endswith("agent-chrome --stop") and svc["ExecStart"].endswith("agent-chrome --foreground"))
        self.assertIn("RestartSec", svc)
        self.assertEqual(cp["Install"]["WantedBy"], "graphical-session.target")
        self.assertEqual((cp["Unit"]["PartOf"], cp["Unit"]["After"]), ("graphical-session.target",) * 2)
        self.assertIn("StartLimitBurst", cp["Unit"])

    def test_exec_start_target_exists_in_the_source_tree(self):
        for key in ("ExecStartPre", "ExecStart"):
            line = [l for l in UNIT.read_text().splitlines() if l.startswith(key + "=")][0].split("=", 1)[1]
            exe = line.split()[0]
            self.assertTrue(exe.startswith("%h/.local/bin/"), exe)
            self.assertTrue((ROOT / "dot_local/bin" / ("executable_" + exe.rsplit("/", 1)[1])).is_file(), exe)

    def test_unit_passes_systemd_analyze_when_available(self):
        if not shutil.which("systemd-analyze"):
            self.skipTest("no systemd-analyze")
        with tempfile.TemporaryDirectory() as tmp:   # a copy that points at the source-tree launcher, so the host's installed one does not matter
            copy = Path(tmp) / "agent-chrome.service"
            copy.write_text(UNIT.read_text().replace("%h/.local/bin/agent-chrome", str(LAUNCHER)))
            r = subprocess.run(["systemd-analyze", "--user", "verify", str(copy)], capture_output=True, text=True)
        self.assertNotIn("agent-chrome.service:", r.stderr, r.stderr)   # complaints about the unit itself; the rest is the host's own units

    def test_load_script_renders_with_both_hashes_and_is_valid_shell(self):
        out = chezmoi("personal", "execute-template", stdin=LOADER.read_text())
        self.assertRegex(out, r"(?m)^# unit: [0-9a-f]{64}$")
        self.assertRegex(out, r"(?m)^# launcher: [0-9a-f]{64}$")
        subprocess.run(["sh", "-n"], input=out, text=True, check=True)

    def test_ignored_everywhere_except_personal_linux(self):
        for profile, os_name, deployed in (("personal", "linux", True), ("axon-work-computer", "linux", False),
                                           ("personal", "darwin", False), ("axon-work-computer", "darwin", False)):
            with self.subTest(profile=profile, os=os_name):
                data = json.dumps({"chezmoi": {"os": os_name}})
                ignored = chezmoi(profile, "execute-template", "--override-data", data, stdin=(ROOT / ".chezmoiignore").read_text()).splitlines()
                for path in IGNORED:
                    self.assertEqual(path in ignored, not deployed, path)


# A fake Chrome: serves its own pid on /json/version, so a test can tell one Chrome process from the next.
FAKE_CHROME = """#!%s
import http.server, os, socketserver, sys
port = int([a for a in sys.argv if a.startswith("--remote-debugging-port=")][0].split("=")[1])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a): pass
socketserver.TCPServer.allow_reuse_address = True
socketserver.TCPServer(("127.0.0.1", port), H).serve_forever()
""" % sys.executable


def user_systemd():
    r = subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True) if shutil.which("systemctl") else None
    return bool(r and r.returncode == 0 and shutil.which("ss"))


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@unittest.skipUnless(sys.platform.startswith("linux") and user_systemd(), "needs a Linux user systemd manager and ss")
class RestartJourneyTest(unittest.TestCase):
    RESTARTS = int(os.environ.get("AGENT_CHROME_RESTARTS", "10"))

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="agent-chrome-unit-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.port = free_port()
        self.name = "agent-chrome-test-%d.service" % os.getpid()
        env = ["HOME=%s" % self.home, "XDG_STATE_HOME=%s" % (self.tmp / "state"), "AGENT_CHROME_PORT=%d" % self.port]
        self.env = dict(os.environ, HOME=str(self.home), XDG_STATE_HOME=str(self.tmp / "state"), AGENT_CHROME_PORT=str(self.port))
        if not os.environ.get("AGENT_CHROME_REAL"):
            app = self.tmp / "Chrome"
            app.write_text(FAKE_CHROME)
            app.chmod(0o755)
            env.append("AGENT_CHROME_APP=%s" % app)
            self.env["AGENT_CHROME_APP"] = str(app)
        # The real unit file; only the launcher path (%h) is pointed at the source tree and the scratch environment is added.
        text = UNIT.read_text().replace("%h/.local/bin/agent-chrome", str(LAUNCHER)).replace("[Service]\n", "[Service]\n" + "".join('Environment="%s"\n' % e for e in env))
        (self.tmp / self.name).write_text(text)
        self.ctl("link", str(self.tmp / self.name))

    def tearDown(self):
        self.ctl("stop", self.name)
        self.ctl("disable", self.name)
        subprocess.run(["pkill", "-9", "-f", str(self.tmp)], check=False)
        self.ctl("daemon-reload")
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ctl(self, *args):
        return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)

    def pid_on_port(self):
        out = subprocess.run(["ss", "-Htlnp", "sport = :%d" % self.port], capture_output=True, text=True).stdout
        m = re.search(r"pid=(\d+)", out)
        return int(m.group(1)) if m else None

    def answers(self):
        try:
            return urllib.request.urlopen("http://127.0.0.1:%d/json/version" % self.port, timeout=2).status == 200
        except OSError:
            return False

    def wait_for(self, what, cond, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return
            time.sleep(0.05)
        log = subprocess.run(["journalctl", "--user", "-u", self.name, "-n", "20", "--no-pager"], capture_output=True, text=True).stdout
        self.fail("timed out waiting for %s\n%s" % (what, log))

    def up(self):
        self.wait_for("Chrome to answer on port %d" % self.port, self.answers)
        return self.pid_on_port()

    def test_start_restart_many_times_restart_from_a_hand_started_chrome_and_stop(self):
        self.assertEqual(self.ctl("start", self.name).returncode, 0)
        old = self.up()
        self.assertIsNotNone(old)
        seen = [old]
        for _ in range(self.RESTARTS):
            self.assertEqual(self.ctl("restart", self.name).returncode, 0)
            new = self.up()
            self.assertNotIn(new, seen, "restart left the same Chrome %s (seen %s)" % (new, seen))
            self.assertEqual(self.ctl("is-active", self.name).stdout.strip(), "active")
            seen.append(new)
        print("\nrestarts: Chrome pids %s" % seen, file=sys.stderr)
        # Chrome started by hand (outside the unit), then the unit started over it
        self.ctl("stop", self.name)
        self.wait_for("the port to go quiet after stop", lambda: not self.answers())
        subprocess.run([str(LAUNCHER)], env=self.env, check=True, capture_output=True)
        by_hand = self.up()
        self.assertNotIn(by_hand, seen)
        for _ in range(3):
            self.assertEqual(self.ctl("restart", self.name).returncode, 0)
            new = self.up()
            self.assertNotIn(new, seen + [by_hand])
            seen.append(new)
        self.assertFalse(os.path.exists("/proc/%d" % by_hand), "the hand-started Chrome is still running")
        self.assertEqual(self.ctl("stop", self.name).returncode, 0)
        self.wait_for("the port to go quiet after the final stop", lambda: not self.answers())
        self.assertIsNone(self.pid_on_port())


if __name__ == "__main__":
    unittest.main()
