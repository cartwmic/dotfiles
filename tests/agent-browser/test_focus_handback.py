"""agent-chrome's macOS focus hand-back: even under open -g -n, Chrome activates itself in-process when its
first window shows (chromium issue 40246767), so the launcher records who is front before the launch as an
instance (ASN and pid) and, once the port answers, watches briefly and hands the front back with
lsappinfo setfront if the agent Chrome took it. The user's own Chrome and the agent Chrome are both
com.google.Chrome, so the front is told apart by instance (pid), never by bundle id, and the hand-back
names an instance (lsappinfo setfront), never open -b (which can only raise a bundle). Proven with a fake
lsappinfo, a fake open and a fake Chrome that "self-activates" (the fake lsappinfo reports it as front from
then on); never starts a real Chrome. Set AGENT_CHROME_SCRIPT to run these against another launcher script."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPT = Path(os.environ.get("AGENT_CHROME_SCRIPT")
              or (Path(__file__).resolve().parents[2] / "dot_local/bin/executable_agent-chrome"))

FAKE_CHROME = """#!%s
import http.server, json, os, socketserver, sys
open(os.environ["FAKE_ARGV"], "a").write(json.dumps(sys.argv[1:]) + "\\n")
open(os.environ["FAKE_CHROME_PID"], "w").write(str(os.getpid()))   # the fake lsappinfo maps the agent Chrome's ASN to this pid
if os.environ.get("FAKE_SELF_ACTIVATE"):
    open(os.environ["FAKE_FRONT_MARKER"], "w").write("front\\n")   # self-activation: the fake lsappinfo reports Chrome as front from now on
port = int([a for a in sys.argv if a.startswith("--remote-debugging-port=")][0].split("=")[1])
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"{}")
    def log_message(self, *a): pass
socketserver.TCPServer(("127.0.0.1", port), H).serve_forever()
""" % sys.executable

FAKE_OPEN = """#!%s
import json, os, subprocess, sys
args = sys.argv[1:]
open(os.environ["FAKE_ARGV"] + ".open", "a").write(json.dumps(args) + "\\n")
if "-b" in args:
    sys.exit(0)   # a bundle-id hand-back: recorded, nothing real to activate (the launcher must never do this)
bundle = args[args.index("-a") + 1]
subprocess.Popen([os.path.join(bundle, "Contents/MacOS/fake-chrome")] + args[args.index("--args") + 1:],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)   # like open: spawn and return at once
""" % sys.executable

CHROME_ASN, PREV_ASN, PREV_PID = "ASN:0xdeadbeef:chrome", "ASN:0x0000face:prev", "424242"


def fake_lsappinfo(same_bundle=False, prev_quits=False, setfront_works=True):
    """front is the agent Chrome once the marker exists (it "self-activated"), or always the previous app.
    same_bundle: the previous app answers with the agent Chrome's own bundle id (the user's own Chrome).
    prev_quits: the recorded app's ASN resolves to no pid once the agent Chrome is up (it quit).
    setfront_works: setfront to the previous app gives the front back (the marker goes). When False it behaves as on a
    GitHub macOS runner: it prints "ERROR #-54 permErr", exits 0 and changes nothing."""
    prev_bundle = "local.fake-chrome" if same_bundle else "com.prev.app"
    return """#!%s
import json, os, sys
args = sys.argv[1:]
open(os.environ["FAKE_ARGV"] + ".lsappinfo", "a").write(json.dumps(args) + "\\n")
chrome_asn, prev_asn, prev_pid = "%s", "%s", "%s"
steal = os.path.exists(os.environ["FAKE_FRONT_MARKER"])
if args == ["front"]:
    print(chrome_asn if steal else prev_asn)
elif args[:1] == ["setfront"]:
    if %r:
        if os.path.exists(os.environ["FAKE_FRONT_MARKER"]):
            os.remove(os.environ["FAKE_FRONT_MARKER"])
    else:
        print("ERROR #-54 permErr")
elif args[:3] == ["info", "-only", "pid"]:
    if args[3] == chrome_asn:
        print(open(os.environ["FAKE_CHROME_PID"]).read().strip())
    elif args[3] == prev_asn and (not %r or not steal):
        print(prev_pid)
elif args[:3] == ["info", "-only", "bundleid"]:
    if args[3] == chrome_asn:
        print('"CFBundleIdentifier"="local.fake-chrome"')
    elif args[3] == prev_asn:
        print('"CFBundleIdentifier"="%s"')
""" % (sys.executable, CHROME_ASN, PREV_ASN, PREV_PID, setfront_works, prev_quits, prev_bundle)

FAKE_OSASCRIPT = """#!%s
import json, os, sys
open(os.environ["FAKE_ARGV"] + ".osascript", "a").write(json.dumps(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_OSASCRIPT_WORKS") and os.path.exists(os.environ["FAKE_FRONT_MARKER"]):
    os.remove(os.environ["FAKE_FRONT_MARKER"])   # NSRunningApplication activate: the previous app is front again
""" % sys.executable

BROKEN_LSAPPINFO = "#!/bin/sh\nexit 127\n"   # stands in for a missing or failing lsappinfo


def leftovers(folder, wait=5):
    """The processes whose command line names a path under folder, once they have had up to `wait` seconds to go."""
    deadline = time.monotonic() + wait
    while True:
        out = subprocess.run(["ps", "-A", "-ww", "-o", "command="], capture_output=True, text=True, check=True).stdout
        found = [line for line in out.splitlines() if str(folder) in line]
        if not found or time.monotonic() > deadline:
            return found
        time.sleep(0.05)


def free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class LauncherFixture(unittest.TestCase):
    """The fake bundle, fake tools and launcher run the tests below share; no tests of its own."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="agent-chrome-handback-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.argv = self.root / "argv.log"
        self.marker = self.root / "front-marker"
        self.chrome_pid = self.root / "chrome-pid"
        self.port = free_port()
        self.bundle = self.root / "Fake.app"
        (self.bundle / "Contents/MacOS").mkdir(parents=True)
        (self.bundle / "Contents/Info.plist").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
            '<key>CFBundleExecutable</key><string>fake-chrome</string>'
            '<key>CFBundleIdentifier</key><string>local.fake-chrome</string>'
            '<key>CFBundlePackageType</key><string>APPL</string></dict></plist>')
        exe = self.bundle / "Contents/MacOS/fake-chrome"
        exe.write_text(FAKE_CHROME)
        exe.chmod(0o755)

    def install(self, lsappinfo):
        for name, body in (("open", FAKE_OPEN), ("lsappinfo", lsappinfo), ("osascript", FAKE_OSASCRIPT)):
            tool = self.bin / name
            tool.write_text(body)
            tool.chmod(0o755)

    def run_script(self, self_activate=True, osascript_works=False, focus_wait="1", timeout=60):
        env = {"PATH": str(self.bin) + os.pathsep + os.environ["PATH"], "HOME": str(self.home),
               "AGENT_CHROME_APP": str(self.bundle), "AGENT_CHROME_OS": "Darwin",
               "AGENT_CHROME_PORT": str(self.port), "AGENT_CHROME_WAIT": "10",
               "AGENT_CHROME_FOCUS_WAIT": focus_wait, "FAKE_ARGV": str(self.argv),
               "FAKE_FRONT_MARKER": str(self.marker), "FAKE_CHROME_PID": str(self.chrome_pid)}
        if self_activate:
            env["FAKE_SELF_ACTIVATE"] = "1"
        if osascript_works:
            env["FAKE_OSASCRIPT_WORKS"] = "1"
        # The launcher leaves the fake Chrome running, as the real one does. Everything the launcher starts stays in
        # its process group, so killing the group when the call ends (return, timeout or Ctrl-C) leaves nothing behind.
        # A finally, not addCleanup: unittest skips cleanups on KeyboardInterrupt.
        with subprocess.Popen(["sh", str(SCRIPT)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              start_new_session=True) as proc:
            try:
                out, err = proc.communicate(timeout=timeout)
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)

    def open_calls(self):
        path = Path(str(self.argv) + ".open")
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def lsappinfo_calls(self):
        path = Path(str(self.argv) + ".lsappinfo")
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def osascript_calls(self):
        path = Path(str(self.argv) + ".osascript")
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def setfront_calls(self):
        return [c for c in self.lsappinfo_calls() if c[:1] == ["setfront"]]

    def record(self):
        path = self.home / ".local/state/agent-chrome/agent-chrome.log"
        return path.read_text().splitlines() if path.exists() else []


class FocusHandback(LauncherFixture):
    def test_steal_hands_the_front_back_to_the_recorded_instance(self):
        """The fake Chrome "activates itself" once it is up: the launcher must hand the front back to the
        app instance that was front before the launch, exactly once, through lsappinfo setfront with the
        recorded ASN — never through open -b."""
        self.install(fake_lsappinfo())
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = self.open_calls()
        self.assertEqual(calls[0][:4], ["-g", "-n", "-a", str(self.bundle)])   # the launch went through open -g -n
        self.assertEqual(len(calls), 1)                                        # the launch only: no open -b
        self.assertEqual(self.setfront_calls(), [["setfront", PREV_ASN]])      # one hand-back, to the recorded instance
        self.assertEqual(self.osascript_calls(), [])                           # setfront took, so nothing else is tried
        self.assertEqual(self.lsappinfo_calls()[0], ["front"])                 # the front was recorded before the launch
        self.assertIn("handed it back", self.record()[-1])

    def test_a_setfront_that_exits_0_and_changes_nothing_falls_back_to_activating_the_recorded_pid(self):
        """On a GitHub macOS runner lsappinfo setfront prints permErr, exits 0 and leaves the front alone. The
        launcher judges by the front, not the exit code, so it activates the recorded instance by pid
        (NSRunningApplication through osascript JXA) and logs the hand-back as done only when the front moved."""
        self.install(fake_lsappinfo(setfront_works=False))
        r = self.run_script(osascript_works=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.setfront_calls(), [["setfront", PREV_ASN]])
        calls = self.osascript_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:2], ["-l", "JavaScript"])
        self.assertIn("runningApplicationWithProcessIdentifier(%s)" % PREV_PID, calls[0][-1])   # the instance, not a bundle
        self.assertIn("NSRunningApplication handed it back", self.record()[-1])
        self.assertEqual(len(self.open_calls()), 1)     # the launch only: no open -b

    def test_a_hand_back_that_no_call_achieves_is_logged_as_an_error_and_the_launch_still_succeeds(self):
        self.install(fake_lsappinfo(setfront_works=False))
        r = self.run_script()      # the fake osascript does nothing either
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.osascript_calls()), 1)
        self.assertIn("ERROR: the agent Chrome took the front at launch; could not hand it back", self.record()[-1])

    def test_same_bundle_front_and_no_steal_means_no_handback(self):
        """The user's own Chrome (same bundle id as the agent Chrome) is front and the agent Chrome never
        takes it: nothing may hand the front back. The bundle ids match, so only the instance (pid)
        comparison can tell the two Chrome apps apart — a bundle-id comparison misfires here."""
        self.install(fake_lsappinfo(same_bundle=True))
        r = self.run_script(self_activate=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.open_calls()), 1)     # the launch only: no open -b
        self.assertEqual(self.setfront_calls(), [])     # and no setfront
        self.assertNotIn("handed it back", "\n".join(self.record()))

    def test_same_bundle_steal_hands_the_front_back_to_the_recorded_instance(self):
        """The user's own Chrome is front and the agent Chrome (same bundle id) steals it: the front goes
        back to the recorded instance with lsappinfo setfront — never open -b, which can only name the
        shared bundle and could raise the agent Chrome's window instead."""
        self.install(fake_lsappinfo(same_bundle=True))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.setfront_calls(), [["setfront", PREV_ASN]])
        self.assertEqual(len(self.open_calls()), 1)     # the launch only: no open -b
        self.assertIn("handed it back", self.record()[-1])

    def test_recorded_app_quit_skips_the_handback(self):
        """The agent Chrome steals the front but the app that was front at launch has quit: skip the
        hand-back and say so — no relaunch (open -b would bring the quit app back from the dead)."""
        self.install(fake_lsappinfo(prev_quits=True))
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.setfront_calls(), [])
        self.assertEqual(len(self.open_calls()), 1)
        self.assertIn("has quit", self.record()[-1])

    def test_no_handback_when_chrome_never_takes_the_front(self):
        self.install(fake_lsappinfo())
        r = self.run_script(self_activate=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.open_calls()), 1)   # the launch only: no open -b
        self.assertEqual(self.setfront_calls(), [])
        self.assertNotIn("handed it back", "\n".join(self.record()))
        self.assertIn("INFO: Chrome started", self.record()[-1])

    def test_launch_survives_a_broken_lsappinfo(self):
        """Recording the front fails: launch anyway, say so in the log, never fail the launch over focus."""
        self.install(BROKEN_LSAPPINFO)
        r = self.run_script(self_activate=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.open_calls()), 1)   # the launch happened
        self.assertIn("could not record the frontmost app", "\n".join(self.record()))
        self.assertNotIn("handed it back", "\n".join(self.record()))


class NothingLeftRunning(LauncherFixture):
    """The fake Chrome the launcher starts must not outlive the call that ran it, however the call ends."""

    def test_after_a_call_that_returns(self):
        self.install(fake_lsappinfo())
        self.assertEqual(self.run_script().returncode, 0)
        self.assertTrue(self.chrome_pid.exists())      # the fake Chrome did start
        self.assertEqual(leftovers(self.root), [])

    def test_after_a_call_that_times_out(self):
        self.install(fake_lsappinfo())
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_script(self_activate=False, focus_wait="30", timeout=3)    # the launcher is still watching for the front
        self.assertTrue(self.chrome_pid.exists())
        self.assertEqual(leftovers(self.root), [])

    def test_after_a_call_that_is_interrupted(self):
        """A child Python runs the same call and is sent SIGINT once the fake Chrome is up (a fact read from its pid file)."""
        scratch = tempfile.TemporaryDirectory(prefix="agent-chrome-leakcheck-")
        self.addCleanup(scratch.cleanup)
        code = ("import sys; sys.path.insert(0, %r); import test_focus_handback as t\n"
                "case = t.LauncherFixture(); case.setUp()\n"
                "case.install(t.fake_lsappinfo()); case.run_script(self_activate=False, focus_wait='30')\n") % str(Path(__file__).parent)
        child = subprocess.Popen([sys.executable, "-c", code], env={**os.environ, "TMPDIR": scratch.name},
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(child.kill)
        deadline = time.monotonic() + 30
        while not list(Path(scratch.name).glob("agent-chrome-handback-*/chrome-pid")):
            self.assertLess(time.monotonic(), deadline, "the fake Chrome never started")
            self.assertIsNone(child.poll(), "the child ended before the fake Chrome started")
            time.sleep(0.05)
        child.send_signal(signal.SIGINT)
        child.wait(timeout=30)
        self.assertEqual(leftovers(scratch.name), [])


if __name__ == "__main__":
    unittest.main()
