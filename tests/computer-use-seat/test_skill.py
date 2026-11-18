"""Render the using-computer skill with the real chezmoi for each profile and OS, and check what each reader gets.

The skill is one template for both profiles. The browser-tool line is the only line that names `browser-harness`,
so PR 545 removing that server later changes one line. Fails (does not skip) when chezmoi is not installed.

    python3 -m unittest discover -s tests/computer-use-seat -p test_skill.py -v
"""

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "dot_local" / "share" / "agent-harness" / "canonical" / "skills" / "using-computer" / "SKILL.md.tmpl"


def render(profile, chezmoi_os):
    with tempfile.TemporaryDirectory() as home:
        config = Path(home) / "chezmoi.yaml"
        config.write_text("{}\n")
        override = json.dumps({"profile": profile, "chezmoi": {"os": chezmoi_os}})
        result = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(config), "execute-template", "--override-data", override],
            input=SKILL.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120,
        )
    assert result.returncode == 0, result.stderr
    return result.stdout


def tool_section(text):
    """The '## Which tool' section. Other sections name tools too, so tool checks read only this slice."""
    start = text.index("## Which tool")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class UsingComputerSkillTests(unittest.TestCase):
    def test_chezmoi_is_installed(self):
        self.assertIsNotNone(shutil.which("chezmoi"), "chezmoi is required: this test must not skip")

    def test_personal_linux_names_browse_and_saves_focus_first(self):
        text = render("personal", "linux")
        self.assertTrue(text.startswith("---\nname: using-computer\n"))
        self.assertIn("`using-browse`", text)
        self.assertIn("the `browse` MCP server", text)
        self.assertNotIn("browser-harness", text)
        save = text.index("agent-desktop save")
        self.assertLess(save, text.index("agent-chrome"))
        self.assertLess(save, text.index("Browser tool:"))
        self.assertIn("agent-desktop restore", text)
        self.assertLess(save, text.index("agent-desktop restore"))
        self.assertIn("1Password", text)
        self.assertNotIn("FastPass", text)

    def test_personal_mac_has_no_save_or_restore(self):
        text = render("personal", "darwin")
        self.assertIn("the `browse` MCP server", text)
        self.assertNotIn("agent-desktop save", text)
        self.assertNotIn("agent-desktop restore", text)

    def test_work_mac_names_browser_harness_and_stops_on_fastpass(self):
        text = render("axon-work-computer", "darwin")
        self.assertIn("browser-harness", text)
        self.assertNotIn("Browse, the `browse` MCP server", text)
        self.assertNotIn("using-browse", text)
        self.assertIn("FastPass", text)
        self.assertRegex(text, r"(?i)stop and ask your lead")
        self.assertNotIn("agent-desktop save", text)
        self.assertNotIn("agent-desktop restore", text)
        self.assertNotIn("1Password", text)

    def test_personal_tool_list_names_every_tool_it_has(self):
        for chezmoi_os in ("linux", "darwin"):
            with self.subTest(os=chezmoi_os):
                section = tool_section(render("personal", chezmoi_os))
                for name in ("agent-chrome", "agent-download", "agent-login", "agent-desktop"):
                    self.assertIn(name, section)

    def test_work_tool_list_names_only_tools_the_work_profile_installs(self):
        section = tool_section(render("axon-work-computer", "darwin"))
        self.assertIn("browser-harness", section)
        self.assertIn("agent-chrome", section)
        self.assertIn("agent-desktop", section)
        self.assertNotIn("agent-download", section)  # .chezmoiignore leaves it out on work
        self.assertNotIn("agent-login", section)     # .chezmoiignore leaves it out on work

    def test_only_one_template_line_names_browser_harness(self):
        lines = [l for l in SKILL.read_text(encoding="utf-8").splitlines() if "browser-harness" in l]
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith("- Browser tool:"))

    def test_every_render_has_the_seat_sections(self):
        for profile, chezmoi_os in (("personal", "linux"), ("personal", "darwin"), ("axon-work-computer", "darwin")):
            with self.subTest(profile=profile, os=chezmoi_os):
                text = render(profile, chezmoi_os)
                for heading in ("## Order", "## Which tool", "agent-desktop shot",
                                "Never start another browser or browser tool."):
                    self.assertIn(heading, text)
                self.assertIsNone(re.search(r"\{\{|\}\}", text))


if __name__ == "__main__":
    unittest.main()
