"""agent-chrome.service, the systemd user unit that starts the agent Chrome at login, and the script that loads it (real files, real chezmoi).
The unit parses with the expected keys, its ExecStart target is in the source tree, the load script renders, and both are ignored
everywhere except personal Linux."""
import configparser
import json
import subprocess
import unittest
from pathlib import Path

from test_render import ROOT, chezmoi

UNIT = ROOT / "dot_config/systemd/user/agent-chrome.service"
LOADER = ROOT / "run_onchange_after_78_agent_chrome_systemd.sh.tmpl"
IGNORED = (".config/systemd/user/agent-chrome.service", "78_agent_chrome_systemd.sh")


class LoginUnitTest(unittest.TestCase):
    def test_unit_has_the_expected_keys(self):
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.optionxform = str
        cp.read(UNIT)
        svc = cp["Service"]
        self.assertEqual((svc["Type"], svc["RemainAfterExit"], svc["Restart"]), ("oneshot", "yes", "on-failure"))
        self.assertIn("RestartSec", svc)
        self.assertEqual(cp["Install"]["WantedBy"], "graphical-session.target")
        self.assertEqual((cp["Unit"]["PartOf"], cp["Unit"]["After"]), ("graphical-session.target",) * 2)
        self.assertIn("StartLimitBurst", cp["Unit"])

    def test_exec_start_target_exists_in_the_source_tree(self):
        exec_start = [l for l in UNIT.read_text().splitlines() if l.startswith("ExecStart=")][0].split("=", 1)[1]
        self.assertTrue(exec_start.startswith("%h/.local/bin/"), exec_start)
        self.assertTrue((ROOT / "dot_local/bin" / ("executable_" + exec_start.rsplit("/", 1)[1])).is_file(), exec_start)

    def test_unit_passes_systemd_analyze_when_available(self):
        r = subprocess.run(["systemd-analyze", "--user", "verify", str(UNIT)], capture_output=True, text=True)
        if r.returncode == 127 or "not found" in r.stderr:
            self.skipTest("no systemd-analyze")
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


if __name__ == "__main__":
    unittest.main()
