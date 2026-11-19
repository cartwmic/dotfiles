"""run_onchange_after_91_browse_setup.sh, on both profiles: the real script (rendered by real chezmoi) against a scratch HOME with a fake `browse` shim.
It must turn Browse's auto-update off, delete the self-updating ~/.local/bin/browse that `browse install` writes (it would shadow the pin),
remove what browser-harness left, and leave everything else alone."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMPL = ROOT / "run_onchange_after_91_browse_setup.sh.tmpl"
SHIM = '#!/bin/sh\necho "$@" >> "$FAKE_LOG"\n[ "$1" = --version ] && echo 0.1.0\nexit 0\n'


PROFILES = ("personal", "axon-work-computer")


def render(profile):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile)
        return subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                              input=TMPL.read_text(), capture_output=True, text=True, timeout=60, check=True,
                              env=dict(os.environ, HOME=tmp)).stdout


class SetupCases:   # every case runs for each profile below
    profile = None

    @classmethod
    def setUpClass(cls):
        cls.script = render(cls.profile)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="browse-setup-test-")
        self.home = Path(self.tmp.name)
        self.log = self.home / "shim.log"

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, rel, text="x"):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def shim(self):
        p = self.put(".local/share/mise/shims/browse", SHIM)
        p.chmod(0o755)

    def run_script(self):
        return subprocess.run(["sh", "-c", self.script], env={"PATH": os.environ["PATH"], "HOME": str(self.home), "FAKE_LOG": str(self.log)},
                              capture_output=True, text=True, timeout=60)

    def test_the_pinned_shim_is_told_to_turn_auto_update_off(self):
        self.shim()
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.log.read_text().splitlines()[0], "update --mode off")

    def test_the_self_updating_copy_from_browse_install_is_deleted(self):
        self.shim()
        copy = self.put(".local/bin/browse")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(copy.exists())
        self.assertIn("removed ~/.local/bin/browse", r.stdout)

    def test_browser_harness_leftovers_go_and_nothing_else(self):
        self.shim()
        gone = [self.put(".local/share/browser-harness-mcp/server.py"), self.put(".local/share/pi-mcp-lazy/seed/browser-harness.json"),
                self.put(".local/state/pi-mcp-lazy/browser-harness.json")]
        kept = [self.put(".local/share/pi-mcp-lazy/seed/rea.json"), self.put(".local/state/pi-mcp-lazy/rea.json"), self.put(".local/bin/agent-chrome"),
                self.put(".local/share/agent-chrome-profile/Default/Cookies")]
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([p.exists() for p in gone], [False] * 3)
        self.assertEqual([p.exists() for p in kept], [True] * 4)
        self.assertFalse((self.home / ".local/share/browser-harness-mcp").exists())   # the whole folder

    def test_a_clean_home_is_a_no_op_that_still_succeeds(self):
        self.shim()
        self.assertEqual(self.run_script().returncode, 0)

    def test_a_missing_shim_fails_and_names_the_fix(self):
        copy = self.put(".local/bin/browse")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("mise install", r.stdout)
        self.assertTrue(copy.exists(), "must not delete the only browse there is")


class PersonalSetupTest(SetupCases, unittest.TestCase):
    profile = "personal"


class WorkSetupTest(SetupCases, unittest.TestCase):
    profile = "axon-work-computer"


if __name__ == "__main__":
    unittest.main()
