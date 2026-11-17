"""The using-browse skill (a template, one file for both profiles) as chezmoi renders it for personal Linux, personal macOS and the work Mac.
Personal Linux is the text the machines already proven run, byte for byte (fixtures/using-browse-personal-linux.md). The work Mac gets no
personal account, 1Password, Beeper or Gmail instruction; a Mac gets the Mac commands (agent-chrome by hand, Cmd+Shift+X, the front-app check)."""
import json
import re
import unittest

from test_render import ROOT, chezmoi

TMPL = ROOT / "dot_local/share/agent-harness/canonical/skills/using-browse/SKILL.md.tmpl"
GOLDEN = ROOT / "tests/agent-browser/fixtures/using-browse-personal-linux.md"
WORK_INTRO = "Work Mac. Never use personal accounts, personal 1Password, Beeper or Gmail. If a site needs a sign-in, a code or an approval you do not have, stop and ask Michael."
FRONT_CHECK = "frontmostApplication.processIdentifier"


def render(profile, os_name):
    return chezmoi(profile, "execute-template", "--override-data", json.dumps({"chezmoi": {"os": os_name}}), stdin=TMPL.read_text())


class UsingBrowseSkillTest(unittest.TestCase):
    def test_personal_linux_is_the_shipped_text_byte_for_byte(self):
        self.assertEqual(render("personal", "linux"), GOLDEN.read_text())

    def test_personal_linux_keeps_the_status_retry_step(self):
        self.assertIn("call `status` again, up to 3 times", render("personal", "linux"))

    def test_personal_macos_uses_the_mac_commands_and_keeps_the_personal_text(self):
        text = render("personal", "darwin")
        for want in ("run `agent-chrome` (a Mac has no login unit; nothing restarts it)", 'agent-desktop focus "Google Chrome"', FRONT_CHECK,
                     "agent-desktop key x cmd shift", "~/Downloads", "Personal accounts only; never the work Mac.", "## 1Password rules",
                     "read it from Gmail or Beeper", "call `status` again, up to 3 times"):
            self.assertIn(want, text)
        for gone in ("systemctl", "ctrl shift", "google-chrome`"):
            self.assertNotIn(gone, text)

    def test_the_work_mac_has_the_mac_commands_and_no_personal_instruction(self):
        text = render("axon-work-computer", "darwin")
        for want in (WORK_INTRO, "run `agent-chrome` (a Mac has no login unit; nothing restarts it)", 'agent-desktop focus "Google Chrome"', FRONT_CHECK,
                     "agent-desktop key Escape", "exits 1 and names a permission, stop and tell Michael", "call `status` again, up to 3 times"):
            self.assertIn(want, text)
        # The one place the words appear is the intro's "never" line.
        rest = text.replace(WORK_INTRO, "")
        for word in ("Gmail", "Beeper", "1Password", "1password"):
            self.assertNotIn(word, rest)
        for gone in ("systemctl", "ctrl shift", "key x ", "Personal accounts only", "## 1Password rules", "do not ask Michael first"):
            self.assertNotIn(gone, text)

    def test_every_render_is_a_valid_skill_file(self):
        for profile, os_name in (("personal", "linux"), ("personal", "darwin"), ("axon-work-computer", "darwin")):
            with self.subTest(profile=profile, os=os_name):
                text = render(profile, os_name)
                self.assertTrue(text.startswith("---\nname: using-browse\ndescription: "), text[:80])
                self.assertEqual(len(re.findall(r"^---$", text, re.M)), 2)
                self.assertNotIn("{{", text)
                self.assertTrue(text.endswith("\n"))
                self.assertFalse(text.endswith("\n\n"))


if __name__ == "__main__":
    unittest.main()
