"""Which computer gets which agent-desktop file: personal Linux the Omarchy script, a Mac the `66` install step, Windows nothing.

Runs the real chezmoi against the real source with a throwaway config and destination, once per system and profile
(`--override-data` sets chezmoi.os and profile, so every case runs on this machine). The `windows/` folder is also checked in
a scratch source that holds the real ignore file and a planted `windows/` file, so the ignore rule is tested on files
that exist even before the folder does. The Mac side of the `66` script (it is managed on darwin) is `test_layout_macos.py`.
Run: python3 -m unittest discover -s tests/agent-desktop -p 'test_layout.py'
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
SYSTEMS = ("linux", "darwin", "windows")
PROFILES = ("personal", "axon-work-computer")
LINUX_SCRIPT = ".local/bin/agent-desktop"
MAC_STEP = "66_agent_desktop_macos.sh"


def chezmoi(source, system, profile, *args):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile)
        override = json.dumps({"profile": profile, "chezmoi": {"os": system}})
        r = subprocess.run(["chezmoi", "--source", str(source), "--config", str(cfg), "--config-format", "yaml",
                            "--destination", str(home), "--override-data", override, *args],
                           capture_output=True, text=True, env=source_tree.chezmoi_env(home), timeout=120)
    if r.returncode:
        raise AssertionError("chezmoi %s (%s, %s) failed: %s" % (args[0], system, profile, r.stderr))
    return r.stdout


def managed(source, system, profile):
    return set(chezmoi(source, system, profile, "managed").split())


def ignored(system, profile):
    """The destination patterns .chezmoiignore lists for this system and profile."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("{}\n")
        override = json.dumps({"profile": profile, "chezmoi": {"os": system, "destDir": str(Path(tmp) / "dest")}})
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "execute-template", "--override-data", override],
                           input=(REPO / ".chezmoiignore").read_text(), capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, HOME=tmp))
    assert r.returncode == 0, r.stderr
    return {line.strip() for line in r.stdout.splitlines() if line.strip() and not line.startswith("#")}


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class LayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.managed = {(s, p): managed(source_tree.source(), s, p) for s in SYSTEMS for p in PROFILES}

    def test_personal_linux_gets_the_omarchy_script(self):
        self.assertIn(LINUX_SCRIPT, self.managed[("linux", "personal")])

    def test_work_linux_gets_no_agent_desktop_file(self):
        got = self.managed[("linux", "axon-work-computer")]
        self.assertNotIn(LINUX_SCRIPT, got)
        self.assertEqual([p for p in got if "agent-desktop" in p or "agent_desktop" in p], [])

    def test_a_mac_does_not_get_the_linux_script_on_either_profile(self):
        for profile in PROFILES:
            self.assertNotIn(LINUX_SCRIPT, self.managed[("darwin", profile)], profile)

    def test_windows_gets_no_agent_desktop_file_on_either_profile(self):
        for profile in PROFILES:
            got = self.managed[("windows", profile)]
            self.assertEqual([p for p in got if "agent-desktop" in p or "agent_desktop" in p], [], profile)

    def test_the_mac_install_step_is_for_a_mac_only(self):
        for system in ("linux", "windows"):
            for profile in PROFILES:
                self.assertTrue(MAC_STEP in ignored(system, profile), "%s must be ignored on %s %s" % (MAC_STEP, system, profile))
        for profile in PROFILES:
            self.assertFalse(MAC_STEP in ignored("darwin", profile), "%s must not be ignored on a Mac (%s)" % (MAC_STEP, profile))

    def test_the_windows_folder_is_ignored_on_every_system_and_profile(self):
        for system in SYSTEMS:
            for profile in PROFILES:
                self.assertTrue(any(p in ("windows", "windows/", "windows/**") for p in ignored(system, profile)), "windows is not ignored on %s %s" % (system, profile))

    def test_nothing_in_the_windows_folder_is_deployed_to_a_home_folder(self):
        # A scratch source: the real ignore file and templates, plus files shaped like the folder's. This checks the ignore rule
        # on files that exist, whether or not the real folder does yet.
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            (src / "windows").mkdir(parents=True)
            for name in ("README.md", "install.ps1", "agent-desktop.ps1", "agent-desktop.cmd"):
                (src / "windows" / name).write_text("")
            (src / "dot_probe").write_text("")
            shutil.copy(REPO / ".chezmoiignore", src)
            shutil.copy(REPO / ".chezmoidata.toml", src)
            shutil.copytree(REPO / ".chezmoitemplates", src / ".chezmoitemplates")
            for system in SYSTEMS:
                for profile in PROFILES:
                    got = managed(src, system, profile)
                    self.assertIn(".probe", got, "the scratch source deploys nothing, so the check proves nothing")
                    self.assertEqual([p for p in got if p == "windows" or p.startswith("windows/")], [], (system, profile))

    def test_the_real_windows_folder_is_not_deployed(self):
        self.assertTrue((REPO / "windows").is_dir() and any((REPO / "windows").iterdir()), "windows/ must exist and hold files")
        for (system, profile), got in self.managed.items():
            self.assertEqual([p for p in got if p == "windows" or p.startswith("windows/")], [], (system, profile))

    def test_the_old_gate_comment_no_longer_says_a_mac_cannot_have_it(self):
        text = (REPO / ".chezmoiignore").read_text()
        self.assertFalse("macOS is not Wayland" in text, "the old comment on the agent-desktop gate is still in .chezmoiignore")


if __name__ == "__main__":
    unittest.main()
