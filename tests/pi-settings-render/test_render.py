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


if __name__ == "__main__":
    unittest.main()
