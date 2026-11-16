"""Script 68 retires the loaded LaunchAgent com.cartwmic.sync-claude-pi-auth, which .chezmoiremove alone left running.

The fake launchctl keeps "loaded" as a file. The fake uname says Darwin. Nothing here calls the real launchctl.
"""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "run_once_after_68_retire_sync_claude_pi_auth_launchd.sh"
LABEL = "com.cartwmic.sync-claude-pi-auth"

FAKE_LAUNCHCTL = r"""#!/bin/sh
case $1 in
  print) [ -f "$FAKE/loaded" ] || exit 113 ;;
  bootout) [ -f "$FAKE/loaded" ] || exit 3; [ -n "${FAKE_STUCK:-}" ] || rm -f "$FAKE/loaded" ;;
  *) exit 64 ;;
esac
"""


def run(loaded, plist, stuck=False, os_name="Darwin"):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fake, home, bindir = tmp / "fake", tmp / "home", tmp / "bin"
        for d in (fake, home / "Library/LaunchAgents", bindir):
            d.mkdir(parents=True)
        for name, body in (("launchctl", FAKE_LAUNCHCTL), ("uname", f"#!/bin/sh\necho {os_name}\n")):
            f = bindir / name
            f.write_text(body)
            f.chmod(f.stat().st_mode | stat.S_IXUSR)
        if loaded:
            (fake / "loaded").touch()
        pl = home / "Library/LaunchAgents" / f"{LABEL}.plist"
        if plist:
            pl.touch()
        env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(home), "FAKE": str(fake)}
        if stuck:
            env["FAKE_STUCK"] = "1"
        r = subprocess.run(["sh", str(SCRIPT)], env=env, capture_output=True, text=True)
        return r, (fake / "loaded").exists(), pl.exists()


class RetireTest(unittest.TestCase):
    def test_unloads_a_loaded_job_and_removes_its_plist(self):
        r, loaded, plist = run(loaded=True, plist=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(loaded)
        self.assertFalse(plist)

    def test_job_loaded_after_chezmoi_already_removed_the_plist(self):
        r, loaded, plist = run(loaded=True, plist=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(loaded)

    def test_nothing_to_do_when_already_gone(self):
        r, loaded, plist = run(loaded=False, plist=False)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_fails_and_keeps_the_plist_when_the_unload_does_not_take(self):
        r, loaded, plist = run(loaded=True, plist=True, stuck=True)
        self.assertEqual(r.returncode, 1)
        self.assertTrue(plist)
        self.assertIn("could not unload", r.stdout + r.stderr)

    def test_does_nothing_off_macos(self):
        r, loaded, plist = run(loaded=True, plist=True, os_name="Linux")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(loaded)
        self.assertTrue(plist)


if __name__ == "__main__":
    unittest.main()
