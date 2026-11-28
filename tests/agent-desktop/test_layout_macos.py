"""The Mac side of which computer gets which agent-desktop file: a Mac gets the `66` install step on both profiles, others do not.

Runs the real chezmoi against the real source with a throwaway config and destination, once per system and profile
(`--override-data` sets chezmoi.os and profile, so every case runs on this machine). `managed --include=scripts` lists the
run steps by their deploy name. The Linux, Windows and ignore-rule parts are `test_layout.py`.
Run: python3 -m unittest discover -s tests/agent-desktop -p 'test_layout_macos.py'
"""
import json
import os
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


def managed(system, profile, *include):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile)
        override = json.dumps({"profile": profile, "chezmoi": {"os": system}})
        r = subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(cfg), "--config-format", "yaml",
                            "--destination", str(home), "--override-data", override, "managed", *include],
                           capture_output=True, text=True, env=source_tree.chezmoi_env(home), timeout=120)
    if r.returncode:
        raise AssertionError("chezmoi managed (%s, %s) failed: %s" % (system, profile, r.stderr))
    return set(r.stdout.split())


class MacLayoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {(s, p): managed(s, p) for s in SYSTEMS for p in PROFILES}
        cls.steps = {(s, p): managed(s, p, "--include=scripts") for s in SYSTEMS for p in PROFILES}

    def test_a_mac_runs_the_install_step_on_both_profiles(self):
        for profile in PROFILES:
            self.assertIn(MAC_STEP, self.steps[("darwin", profile)], "a Mac (%s) must run %s" % (profile, MAC_STEP))

    def test_linux_and_windows_skip_the_install_step_on_both_profiles(self):
        for system in ("linux", "windows"):
            for profile in PROFILES:
                self.assertNotIn(MAC_STEP, self.steps[(system, profile)], "%s %s must skip %s" % (system, profile, MAC_STEP))

    def test_a_mac_does_not_get_the_linux_script_as_a_managed_file(self):
        for profile in PROFILES:
            self.assertNotIn(LINUX_SCRIPT, self.files[("darwin", profile)], profile)

    def test_the_mac_script_is_not_a_second_managed_file_at_the_linux_path(self):
        # chezmoi refuses two sources for one destination, so on a Mac nothing is managed at the agent-desktop path at all:
        # the install step copies the macOS script there.
        for profile in PROFILES:
            got = [p for p in self.files[("darwin", profile)] if ("agent-desktop" in p or "agent_desktop" in p) and p != MAC_STEP]
            self.assertEqual(got, [], profile)

    def test_the_personal_linux_script_is_still_managed_on_personal_linux(self):
        self.assertIn(LINUX_SCRIPT, self.files[("linux", "personal")])

    def test_the_install_step_source_and_the_script_body_exist(self):
        self.assertTrue((REPO / "run_onchange_after_66_agent_desktop_macos.sh.tmpl").is_file(), "the 66 install step is missing")
        self.assertTrue((REPO / ".chezmoitemplates/agent-desktop-macos.sh").is_file(), "the macOS script body is missing")
        self.assertTrue((REPO / ".chezmoitemplates/agent-desktop-relay.sh").is_file(), "the kitty helper source is missing")


if __name__ == "__main__":
    unittest.main()
