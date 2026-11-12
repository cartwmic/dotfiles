"""The retired retrod systemd unit: .chezmoiremove takes it off personal hosts and leaves the coordinator's unit in the same directory.

A real apply into a scratch HOME, with a source dir that holds only a copy of .chezmoiremove (the full source pulls a GitHub archive
on any apply). The source has no .chezmoiignore, so this proves the removal itself; the full-source dry-run in the PR checks the ignore
rules too. Run: python3 -m unittest discover -s tests/instances -v
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UNITS = ".local/share/instances/systemd"
WORK = "axon-work-computer"
HAVE_CHEZMOI = shutil.which("chezmoi") is not None


@unittest.skipUnless(HAVE_CHEZMOI, "chezmoi not installed")
class RetiredFilesTest(unittest.TestCase):
    """retrod.service goes on personal and nothing else goes. The work profile never had the unit, so its apply leaves both files alone."""

    def apply(self, profile):
        """chezmoi with a source dir that holds only a copy of .chezmoiremove, against a scratch HOME that holds both unit files."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        src, home = root / "src", root / "home"
        src.mkdir()
        shutil.copy(ROOT / ".chezmoiremove", src / ".chezmoiremove")
        d = home / UNITS
        d.mkdir(parents=True)
        for f in ("retrod.service", "coordinatord.service"):
            (d / f).write_text("x")
        cfg = root / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile)
        r = subprocess.run(["chezmoi", "--source", str(src), "--config", str(cfg), "--config-format", "yaml",
                            "--destination", str(home), "--persistent-state", str(root / "state.boltdb"), "--no-tty",
                            "apply", "--exclude=scripts"],
                           capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return d

    def test_personal_removes_retrod_and_keeps_the_coordinator_unit(self):
        d = self.apply("personal")
        self.assertFalse((d / "retrod.service").exists())
        self.assertTrue((d / "coordinatord.service").exists())
        self.assertTrue(d.is_dir())

    def test_work_keeps_both_units(self):
        d = self.apply(WORK)
        self.assertTrue((d / "retrod.service").exists())
        self.assertTrue((d / "coordinatord.service").exists())
        self.assertTrue(d.is_dir())


if __name__ == "__main__":
    unittest.main()
