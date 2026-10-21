"""Render dot_pi/private_agent/private_settings.json.tmpl for both desktop profiles with the real chezmoi.

Personal turns native Pi auto-compaction on at 40% of each enabled model's window (Pi takes an absolute reserve:
it compacts when context > window - reserveTokens, so reserve = 60% of the window). Work stays disabled.

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

# Context windows as listed by 'pi --list-models' (checked 2026-10-21). Add a row when a model is enabled.
WINDOWS = {
    "claude-compat/claude-sonnet-5-5": 1_000_000,
    "claude-compat/claude-opus-5-5": 1_000_000,
    "claude-compat/claude-haiku-5-5": 1_000_000,
    "openrouter/z-ai/glm-5.3-flash": 1_000_000,
    "openai-codex/gpt-6.1-sol": 872_000,
    "openai-codex/gpt-6-astra": 872_000,
    "openai-codex/gpt-6-luna": 272_000,
}


def render(profile):
    with tempfile.TemporaryDirectory() as home:
        config = Path(home) / "chezmoi.yaml"
        config.write_text("{}\n")  # no hooks from the developer's own config
        result = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(config), "--destination", home,
             "execute-template", "--override-data", json.dumps({"profile": profile})],
            input=TEMPLATE.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class SettingsRenderTests(unittest.TestCase):
    def test_personal_compacts_at_forty_percent_of_each_models_window(self):
        comp = render("personal")["compaction"]
        self.assertIs(comp["enabled"], True)
        self.assertNotIn("reserveTokens", comp)  # ordinary reserve stays at Pi's default
        overrides = comp["modelOverrides"]
        self.assertEqual(set(overrides), set(WINDOWS))
        for model, window in WINDOWS.items():
            reserve = overrides[model]["reserveTokens"]
            self.assertEqual(reserve, window * 6 // 10, model)
            self.assertEqual(window - reserve, window * 4 // 10, model)  # trigger point
            self.assertLess(reserve, window)

    def test_every_enabled_personal_model_has_an_override(self):
        settings = render("personal")
        missing = [m for m in settings["enabledModels"] if m not in settings["compaction"]["modelOverrides"]]
        self.assertEqual(missing, [])

    def test_work_profile_keeps_compaction_disabled(self):
        self.assertEqual(render("axon-work-computer")["compaction"], {"enabled": False})


if __name__ == "__main__":
    unittest.main()
