"""run_onchange_after_80_spotlight_off_workshop.sh against a fake mdutil on PATH: which calls it makes in each state."""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "run_onchange_after_80_spotlight_off_workshop.sh"

# The fake keeps its state in $FAKE_STATE ("on" or "off"), logs every call to $FAKE_LOG, and ignores "-i off" when $FAKE_STUCK is set.
FAKE = """#!/bin/sh
echo "$*" >> "$FAKE_LOG"
case "$1" in
  -s) if [ "$(cat "$FAKE_STATE")" = on ]; then echo "$2:"; echo "	Indexing enabled. "; else echo "$2:"; echo "	Indexing disabled. "; fi ;;
  -i) [ -n "${FAKE_STUCK:-}" ] || echo "$2" > "$FAKE_STATE" ;;
esac
"""


@unittest.skipUnless(sys.platform == "darwin", "the script exits early off macOS")
class SpotlightOffTest(unittest.TestCase):
    def run_script(self, state, mounted=True, stuck=False):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bindir = tmp / "bin"
            bindir.mkdir()
            fake = bindir / "mdutil"
            fake.write_text(FAKE)
            fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
            (tmp / "state").write_text(state if state == "on" else "off")
            volume = tmp / "vol"
            if mounted:
                volume.mkdir()
            env = dict(os.environ, PATH="%s:%s" % (bindir, os.environ["PATH"]), FAKE_LOG=str(tmp / "log"),
                       FAKE_STATE=str(tmp / "state"), SPOTLIGHT_WORKSHOP_VOLUME=str(volume))
            if stuck:
                env["FAKE_STUCK"] = "1"
            r = subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30)
            log = (tmp / "log").read_text().splitlines() if (tmp / "log").exists() else []
            return r, log, str(volume), (tmp / "state").read_text().strip()

    def test_volume_absent_makes_no_calls(self):
        r, log, _, _ = self.run_script("on", mounted=False)
        self.assertEqual((r.returncode, log), (0, []))
        self.assertIn("not mounted", r.stdout)

    def test_indexing_on_is_turned_off_for_that_volume_only(self):
        r, log, vol, state = self.run_script("on")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(log, ["-s " + vol, "-i off " + vol, "-s " + vol])
        self.assertEqual(state, "off")

    def test_already_off_changes_nothing(self):
        r, log, vol, _ = self.run_script("off")
        self.assertEqual((r.returncode, log), (0, ["-s " + vol]))

    def test_still_on_after_the_change_fails(self):
        r, _, _, _ = self.run_script("on", stuck=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("still on", r.stdout)


if __name__ == "__main__":
    unittest.main()
