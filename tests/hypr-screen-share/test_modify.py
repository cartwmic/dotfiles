"""The modify_ script for ~/.config/hypr/hyprland.lua keeps one 1Password no_screen_share=false block and nothing else of its own."""
import subprocess
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "dot_config/hypr/modify_hyprland.lua"
RULE = 'o.window("^(1[pP]assword|com\\\\.onepassword\\\\.OnePassword)$", { no_screen_share = false })'
BEGIN = "-- BEGIN dotfiles: 1Password in screen shares"
HYPRLAND = 'require("default.hypr.omarchy")\n\n-- Add any other personal Hyprland configuration below.\n-- o.window("qemu", { workspace = "5" })\n'


def run(stdin):
    return subprocess.run(["sh", str(SCRIPT)], input=stdin, text=True, capture_output=True, timeout=30, check=True).stdout


class ModifyTest(unittest.TestCase):
    def test_appends_rule_and_keeps_the_rest(self):
        out = run(HYPRLAND)
        self.assertTrue(out.startswith(HYPRLAND))
        self.assertEqual(out.count(RULE), 1)
        self.assertEqual(out.count(BEGIN), 1)

    def test_idempotent(self):
        once = run(HYPRLAND)
        self.assertEqual(run(once), once)

    def test_replaces_an_edited_block(self):
        edited = run(HYPRLAND).replace("= false", "= true")
        self.assertEqual(run(edited), run(HYPRLAND))

    def test_keeps_text_after_the_block(self):
        later = run(HYPRLAND) + '-- later\no.window("qemu", { workspace = "5" })\n'
        out = run(later)
        self.assertEqual(out.count(BEGIN), 1)
        self.assertIn("-- later", out)

    def test_no_file_no_output(self):
        self.assertEqual(run(""), "")


if __name__ == "__main__":
    unittest.main()
