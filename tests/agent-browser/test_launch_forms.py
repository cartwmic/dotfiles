"""Launch-form probe for the agent Chrome on macOS (opt-in: AGENT_CHROME_PROBE=1, real Chrome).

For each candidate launch form it starts the agent Chrome on a throwaway profile, samples the
frontmost app ('lsappinfo front') every 50 ms from before the launch until the journey has settled,
and reports per form whether the front changed (and for how long), whether a window was created
(page targets over CDP: driving works), and whether the app is hidden ('lsappinfo info -only
isHidden'). A form only wins if the front never changed AND driving works: a hidden launch (form a)
or a missing CDP window (forms b/c) must not be crowned for merely never changing the front:
  plain  open -g -n (today's default; the hand-back is the only guard)
  a      open -g -j -n (hidden launch)
  b      open -g -n with --no-startup-window, the first window created over CDP in the background
  c      a and b together

This journey starts REAL Chrome instances. It never runs in ordinary test discovery: it is skipped
unless AGENT_CHROME_PROBE=1 and Chrome exists, and it must only be run while nobody is using the Mac.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from front_sampler import FrontSampler

SCRIPT = Path(__file__).resolve().parents[2] / "dot_local/bin/executable_agent-chrome"
CHROME_APP = os.environ.get("AGENT_CHROME_APP") or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FORMS = ("plain", "a", "b", "c")
SETTLE = 3.0   # after the launcher exits, keep sampling: a late self-activation must still be seen


def page_targets(port):
    """The page targets on the debug port; an empty list means the launch cannot be driven."""
    try:
        data = json.load(urllib.request.urlopen("http://127.0.0.1:%s/json/list" % port, timeout=5))
    except Exception:
        return []
    return [t for t in data if t.get("type") == "page"]


def app_hidden(profile):
    """Whether the app running this profile is hidden (lsappinfo isHidden); None if it cannot be told."""
    try:
        r = subprocess.run(["pgrep", "-f", "--", "--user-data-dir=" + profile],
                           capture_output=True, text=True, timeout=10)
        pids = r.stdout.split()
        if not pids:
            return None
        asn = subprocess.run(["lsappinfo", "find", "pid=" + pids[0]],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        m = re.match(r"ASN:[0-9a-fx-]+", asn)
        if not m:
            return None
        info = subprocess.run(["lsappinfo", "info", "-only", "isHidden", m.group(0)],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return None
    value = info.partition("=")[2].strip()   # '"isHidden"=[ NULL ]' when not hidden
    return value not in ("", "[ NULL ]", "0", "false")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@unittest.skipUnless(sys.platform == "darwin", "macOS only: the frontmost-app steal is a macOS behavior")
@unittest.skipIf(not os.access(CHROME_APP, os.X_OK), "needs Chrome at %s" % CHROME_APP)
@unittest.skipUnless(os.environ.get("AGENT_CHROME_PROBE") == "1",
                     "opt-in probe: set AGENT_CHROME_PROBE=1 (starts real Chrome; run only while nobody is using the Mac)")
class LaunchForms(unittest.TestCase):
    def probe(self, form):
        scratch = tempfile.mkdtemp(prefix="agent-chrome-probe-%s-" % form)
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        env = dict(os.environ,
                   AGENT_CHROME_PORT=str(free_port()),
                   AGENT_CHROME_PROFILE=scratch + "/profile",
                   AGENT_CHROME_WAIT="30",
                   AGENT_CHROME_LAUNCH_FORM=form,
                   XDG_STATE_HOME=scratch + "/state")
        sampler = FrontSampler()
        sampler.start()
        pages = []
        hidden = None
        try:
            r = subprocess.run([str(SCRIPT)], env=env, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                self.fail("agent-chrome did not start (form %s): %s" % (form, (r.stdout + r.stderr).strip()))
            time.sleep(SETTLE)
            # Fairness: inspect page targets and hidden state while Chrome is still running.
            pages = page_targets(env["AGENT_CHROME_PORT"])
            hidden = app_hidden(scratch + "/profile")
        finally:
            sampler.stop()
            subprocess.run([str(SCRIPT), "--stop"], env=env, capture_output=True, text=True, timeout=60)
        detail = sampler.describe()   # names the baseline and each app the front went to, with timings
        print("PROBE launch form %s: front changed: %s; window created: %s; app hidden: %s" % (
            form,
            ("yes (%s)" % detail) if detail else "no",
            ("yes (%d page target%s)" % (len(pages), "" if len(pages) == 1 else "s")) if pages else "no",
            ("yes" if hidden else "no") if hidden is not None else "unknown"))
        if "could not create the first window" in (r.stdout + r.stderr):
            print("PROBE launch form %s: the launch logged 'could not create the first window over CDP'" % form)
        return sampler.excursions()

    def test_report_front_changes_per_launch_form(self):
        for form in FORMS:
            with self.subTest(form=form):
                self.probe(form)


if __name__ == "__main__":
    unittest.main()
