"""`coordinator` must be on the personal profile's PATH. The homelab chat seat posts with `coordinator lead post HomelabChat`, and its
hook allows only that bare word, so zsh finds it through ~/.local/bin/coordinator. The chezmoi source makes that link
(dot_local/bin/symlink_coordinator.tmpl). This renders the source for the personal profile with a throwaway HOME and a minimal
config, the same way tests/profiles/test_coverage.py does, and checks that the link is managed and points at the coordinator's pane-bin.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
LINK = ".local/bin/coordinator"
TARGET = ".local/share/coordinator/pane-bin/coordinator"


class CoordinatorLinkTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.home.mkdir()
        self.config = Path(tmp.name) / "chezmoi.yaml"
        self.config.write_text("data:\n  profile: personal\n")

    def chezmoi(self, *args):
        r = subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(self.config), "--config-format", "yaml",
                            "--destination", str(self.home), *args],
                           capture_output=True, text=True, env=source_tree.chezmoi_env(self.home), timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_personal_profile_links_coordinator_into_local_bin(self):
        self.assertIn(LINK, self.chezmoi("managed").split())
        # `chezmoi cat` prints a link's target followed by one newline. The target itself has no newline, so a
        # stray newline in the source would show up here as a second one.
        self.assertEqual(self.chezmoi("cat", str(self.home / LINK)), "%s\n" % (self.home / TARGET))


if __name__ == "__main__":
    unittest.main()
