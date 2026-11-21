"""Render dot_pi/private_agent/extensions/coordinator-helper-gate/config.json.tmpl for both desktop profiles with the real chezmoi.

The extension reads the coordinator checkout and state directory from that file. Personal and work point at their own coordinator;
agentHost.removeCoordinatorHook (the coordinator runs elsewhere) renders the gate off, as it takes the hook out of Claude's settings.
Also checks the extension lands in each profile's file list, and its test file does not. Skipped when chezmoi is not installed.

    python3 -m unittest discover -s tests/coordinator-helper-gate -v
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "dot_pi" / "private_agent" / "extensions" / "coordinator-helper-gate" / "config.json.tmpl"
HOME = "/home/someone"

# The local data keys the work profile requires (docs/profiles.md, "Local data keys"); placeholder values.
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}


def data(profile, extra=None):
    return {"profile": profile, "chezmoi": {"homeDir": HOME, "os": "linux"}, **(WORK_DATA if profile == "axon-work-computer" else {}), **(extra or {})}


def render(profile, extra=None):
    with tempfile.TemporaryDirectory() as home:
        config = Path(home) / "chezmoi.yaml"
        config.write_text("{}\n")  # no hooks from the developer's own config
        result = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(config), "execute-template", "--override-data", json.dumps(data(profile, extra))],
            input=TEMPLATE.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def managed(profile):
    """The destination paths chezmoi would write for the profile, under .pi/agent/extensions/coordinator-helper-gate."""
    with tempfile.TemporaryDirectory() as home:
        config = Path(home) / "chezmoi.yaml"
        config.write_text("{}\n")
        result = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(config), "--destination", home, "managed", "--include=files", "--path-style=relative", "--override-data", json.dumps(data(profile))],
            capture_output=True, text=True, timeout=300,
        )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line.startswith(".pi/agent/extensions/coordinator-helper-gate/")]


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class HelperGateRenderTests(unittest.TestCase):
    def test_personal_points_at_the_personal_coordinator(self):
        self.assertEqual(render("personal"), {"enabled": True, "coordinatorRepo": f"{HOME}/git/coordinator", "stateDir": f"{HOME}/.local/share/coordinator"})

    def test_work_points_at_the_work_coordinator(self):
        self.assertEqual(render("axon-work-computer"), {"enabled": True, "coordinatorRepo": f"{HOME}/coordinator-work", "stateDir": f"{HOME}/.local/share/coordinator-work"})

    def test_an_instance_repo_override_wins_as_it_does_for_the_claude_hook(self):
        got = render("personal", {"instances": {"coordinator": {"repo": "/srv/coordinator"}}})
        self.assertEqual(got["coordinatorRepo"], "/srv/coordinator")

    def test_the_agent_host_switch_renders_the_gate_off(self):
        got = render("personal", {"agentHost": {"removeCoordinatorHook": True}})
        self.assertFalse(got["enabled"])

    def test_the_extension_deploys_on_both_profiles_and_its_test_does_not(self):
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile=profile):
                files = managed(profile)
                for name in ("index.ts", "config.json", "README.md"):
                    self.assertIn(f".pi/agent/extensions/coordinator-helper-gate/{name}", files)
                self.assertNotIn(".pi/agent/extensions/coordinator-helper-gate/index.test.ts", files)


if __name__ == "__main__":
    unittest.main()
