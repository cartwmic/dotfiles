"""docs/agent-desktop.md tells a new reader what agent-desktop does on each computer and how to set it up again.

The checks read the doc as a person would look for things: the contract near the top, one section per computer, and in
each section the steps and the "Reproduce" line. They look for facts (action names, exit codes, file paths, the names of the
permissions), not for exact sentences. Relative links must resolve and the README row must point at the doc.
Run: python3 -m unittest discover -s tests/agent-desktop -p 'test_docs.py'
"""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs/agent-desktop.md"
README = REPO / "README.md"
ACTIONS = ("shot", "windows", "focus", "move", "click", "type", "key", "cursor", "ui")


def sections():
    """{heading text: body} for each `## ` section of the doc."""
    out, name = {}, None
    for line in DOC.read_text().splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = ""
        elif name is not None:
            out[name] += line + "\n"
    return out


def section(keyword):
    found = [body for name, body in sections().items() if keyword.lower() in name.lower()]
    if len(found) != 1:
        raise AssertionError("expected exactly one '## ' section with %r in its heading, found %d" % (keyword, len(found)))
    return found[0]


class DocTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DOC.is_file():
            raise AssertionError("%s does not exist" % DOC.relative_to(REPO))
        cls.text = DOC.read_text()

    def test_the_readme_row_links_to_the_doc_and_no_longer_says_personal_linux_only(self):
        row = [l for l in README.read_text().splitlines() if l.startswith("| Agent desktop helper")]
        self.assertEqual(len(row), 1)
        self.assertIn("docs/agent-desktop.md", row[0])
        self.assertNotIn("Personal Linux only", row[0])

    def test_every_relative_link_resolves(self):
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", self.text):
            if re.match(r"[a-z]+:", target):
                continue
            self.assertTrue((DOC.parent / target).exists(), "broken link: %s" % target)

    def test_the_contract_names_the_actions_with_their_arguments(self):
        contract = section("contract")
        for action in ACTIONS:
            self.assertIn("agent-desktop %s" % action, contract, action)
        for usage in ("shot FILE [REGION]", "focus NAME", "move X Y", "click X Y [left|right|middle]", "key KEY [MOD...]", "ui ARGS..."):
            self.assertIn(usage, contract, usage)

    def test_the_contract_gives_the_exit_codes_and_the_log(self):
        contract = section("contract")
        for code in ("0", "1", "2", "69"):
            self.assertRegex(contract, r"(?m)^\|\s*%s\s*\|" % code, "exit code %s (a table row starting `| %s |`)" % (code, code))
        self.assertIn("agent-desktop.log", contract)
        self.assertIn(".local/state/agent-desktop", contract)
        self.assertIn("%LOCALAPPDATA%", contract)
        self.assertIn("run id", contract)
        self.assertRegex(contract, r"(?i)type.{0,80}length")

    def test_each_of_the_four_computers_has_a_section(self):
        for keyword in ("Omarchy", "Mac mini", "G14", "work Mac"):
            self.assertTrue(section(keyword).strip(), keyword)

    def test_the_per_computer_table_says_what_each_computer_uses(self):
        table = section("four computers")
        for word in ("Omarchy", "Mac mini", "G14", "work Mac", "Hyprland", "screencapture", "osascript", "PowerShell", "scheduled task"):
            self.assertIn(word, table, word)

    def test_every_setup_section_has_a_reproduce_line(self):
        for keyword in ("Omarchy", "Mac mini", "G14"):
            self.assertRegex(section(keyword), r"(?i)reproduce", keyword)

    def test_omarchy_says_what_it_cannot_do(self):
        omarchy = section("Omarchy")
        self.assertIn("9 of the 14", omarchy)
        self.assertRegex(omarchy, r"(?i)cannot list buttons by name")
        self.assertIn("unchanged", omarchy)

    def test_the_mac_steps_name_the_two_permissions_and_the_kitty_helper(self):
        mac = section("Mac mini")
        for word in ("Screen Recording", "Screen & System Audio Recording", "Accessibility", "kitty", "agent-desktop-relay start",
                     "agent-desktop-relay status", "com.cartwmic.agent-desktop-relay", "No Automation permission", "US keyboard"):
            self.assertIn(word, mac, word)
        self.assertNotIn("sshd-keygen-wrapper", mac)
        self.assertRegex(mac, r"(?i)asks again")
        self.assertIn("66_agent_desktop_macos.sh", mac)
        self.assertNotIn("PLACEHOLDER", mac)

    def test_the_work_mac_section_says_the_helper_is_left_out_and_why(self):
        work = section("work Mac")
        self.assertIn("not the kitty helper", work)
        self.assertRegex(work, r"(?i)read-only check")

    def test_the_g14_section_covers_unlock_install_and_the_pinned_vercel_download(self):
        g14 = section("G14")
        self.assertIn("windows/install.ps1", g14)
        self.assertRegex(g14, r"(?i)unlock")
        self.assertIn("v1.3.1", g14)
        self.assertRegex(g14, r"(?i)checksum")
        self.assertRegex(g14, r"(?i)second run.{0,60}(nothing|changes? nothing|downloads? nothing)")
        self.assertRegex(g14, r"(?i)login, PIN, sleep, power")

    def test_the_g14_section_says_a_locked_screen_exits_1_and_never_returns_a_blank_result(self):
        g14 = section("G14")
        self.assertRegex(g14, r"(?is)locked.{0,200}exit(s| code)? 1")
        self.assertRegex(g14, r"(?i)never.{0,80}blank")

    def test_the_g14_section_says_ui_goes_through_the_scheduled_task_and_both_sides_log(self):
        g14 = section("G14")
        self.assertRegex(g14, r"(?is)`?agent-desktop ui`?.{0,120}scheduled task")
        self.assertRegex(g14, r"(?is)both sides.{0,120}log|log.{0,120}both sides")

    def test_the_work_mac_section_says_each_action_is_its_own_ask(self):
        work = section("work Mac")
        self.assertRegex(work, r"(?i)its own ask")
        self.assertRegex(work, r"(?i)KVM")


if __name__ == "__main__":
    unittest.main()
