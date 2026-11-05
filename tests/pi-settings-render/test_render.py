"""Render dot_pi/private_agent/private_settings.json.tmpl for both desktop profiles with the real chezmoi.

Native Pi auto-compaction stays off (the auto-compact extension decides when to compact), but compaction.reserveTokens
sets the summary output cap (min(0.8 x reserveTokens, model max output)). Pi's default of 16384 caps summaries at
13107 tokens, which a long-lived session's iterative summary outgrew.

    python3 -m unittest discover -s tests/pi-settings-render -v
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "dot_pi" / "private_agent" / "private_settings.json.tmpl"


# The local data keys the work profile requires (docs/profiles.md, "Local data keys"); placeholder values.
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}


def render(profile):
    with tempfile.TemporaryDirectory() as home:
        config = Path(home) / "chezmoi.yaml"
        config.write_text("{}\n")  # no hooks from the developer's own config
        result = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(config), "--destination", home,
             "execute-template", "--override-data", json.dumps({"profile": profile, **(WORK_DATA if profile == "axon-work-computer" else {})})],
            input=TEMPLATE.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class SettingsRenderTests(unittest.TestCase):
    def test_native_auto_compaction_is_off_in_both_profiles(self):
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile=profile):
                comp = render(profile)["compaction"]
                self.assertIs(comp["enabled"], False)
                self.assertNotIn("modelOverrides", comp)  # no per-model native triggers alongside the extension

    def test_summary_cap_is_raised_above_the_default(self):
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile=profile):
                reserve = render(profile)["compaction"]["reserveTokens"]
                self.assertEqual(reserve, 100000)
                self.assertGreater(int(0.8 * reserve), 13107)  # Pi default cap that was hit

    def test_opus_is_medium_and_every_other_model_keeps_its_level(self):
        # Models with no modelThinkingLevels entry (other providers, /model switches, resumes) follow defaultThinkingLevel,
        # so only the Opus routes move and the global default stays high.
        expected = {
            "personal": {
                "openai-codex/gpt-6.1-sol": "high", "openai-codex/gpt-6-astra": "high",
                "claude-compat/claude-opus-5-5": "medium", "claude-compat/claude-sonnet-5-5": "high",
                "claude-compat/claude-haiku-5-5": "xhigh",
            },
            "axon-work-computer": {"anthropic/claude-opus-5-5": "medium"},
        }
        for profile, levels in expected.items():
            with self.subTest(profile=profile):
                s = render(profile)
                self.assertEqual(s["defaultModel"], "claude-opus-5-5")
                self.assertEqual(s["defaultThinkingLevel"], "high")
                self.assertEqual(s["modelThinkingLevels"], levels)


if __name__ == "__main__":
    unittest.main()
