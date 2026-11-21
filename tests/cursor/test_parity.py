"""Cursor is a first-class harness: whatever the canonical MCP server file and the canonical skills hold must reach Cursor, on both profiles.
Renders both profiles (real chezmoi), runs the real apply script's `cursor` step in a scratch HOME, and fails when a canonical server is
missing from ~/.cursor/mcp.json or a canonical skill is missing from the folders Cursor reads, unless the server is named in
dot_local/share/agent-harness/canonical/mcp/cursor-exclude.txt (with its reason).

    python3 -m unittest discover -s tests/cursor -p 'test_parity.py' -v
"""
import re
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cursor_apply import HARNESS, PROFILES, ROOT, Apply, access, canonical_servers, canonical_skills, exclusions  # noqa: E402

# The user-level skill folders Cursor reads without a setting, from the cursor-agent 2026.11.19 bundle (.cursor/skills and .agents/skills;
# .claude/skills and .codex/skills only with its third-party switch on, so they do not count here).
CURSOR_SKILL_DIRS = (".agents/skills", ".cursor/skills")


RULE = ROOT / "dot_cursor/rules/agent-harness.mdc.tmpl"
INSTRUCTIONS = HARNESS / "canonical/instructions"
# Which canonical instruction file each profile's agents are given (the Claude, Codex and Pi renderings use the same set). The hindsight guide
# and AGENTS.md go to everyone; the others only where their profile applies. A new file in canonical/instructions fails
# test_every_canonical_instruction_file_is_accounted_for until it is placed here (and in the Cursor rule).
INSTRUCTION_FILES = {
    "AGENTS.md": PROFILES,
    "hindsight-guidance.md": PROFILES,
    "profile-personal.md": ("personal",),
    "profile-work.md": ("axon-work-computer",),
    "axon-playbook.md.tmpl": ("axon-work-computer",),
}


def cursor_rule(profile):
    return access.chezmoi(profile, "execute-template", stdin=RULE.read_text())


def instruction_text(name, profile):
    """A canonical instruction file as an agent should read it on the profile (the two templates rendered)."""
    p = INSTRUCTIONS / name
    return access.chezmoi(profile, "execute-template", stdin=p.read_text()) if name.endswith((".tmpl", "profile-work.md")) else p.read_text()


def missing_servers(profile, cursor_servers):
    """Canonical MCP servers for the profile that are neither in the Cursor output nor on the exclusion list."""
    return sorted(set(canonical_servers(profile)) - exclusions() - set(cursor_servers))


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi needed")
class CursorParity(unittest.TestCase):
    def test_every_canonical_mcp_server_reaches_cursor_on_both_profiles(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                a = Apply(self, profile)
                a.run()
                self.assertEqual(missing_servers(profile, a.servers()), [],
                                 "canonical MCP servers missing from ~/.cursor/mcp.json on %s (add them to the apply, or to cursor-exclude.txt with a reason)" % profile)

    def test_every_canonical_skill_reaches_a_folder_cursor_reads_on_both_profiles(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                a = Apply(self, profile)
                a.run()
                seen = set()
                for d in CURSOR_SKILL_DIRS:
                    p = a.home / d
                    if p.is_dir():
                        seen |= {x.name for x in p.iterdir() if (x / "SKILL.md").is_file()}
                self.assertEqual(sorted(set(canonical_skills()) - seen), [],
                                 "canonical skills Cursor cannot see on %s" % profile)

    def test_the_exclusion_list_names_only_canonical_servers(self):
        canonical = set().union(*(set(canonical_servers(p)) for p in PROFILES))
        self.assertEqual(sorted(exclusions() - canonical), [], "cursor-exclude.txt names servers that are not canonical any more")

    def test_the_cursor_rule_carries_every_canonical_instruction_file_on_both_profiles(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                rule = cursor_rule(profile)
                self.assertTrue(re.match(r"---\n(?:.*\n)*?alwaysApply: true\n(?:.*\n)*?---\n", rule), "an always-apply rule: Cursor loads it into every session")
                for name, profiles in INSTRUCTION_FILES.items():
                    if profile in profiles:
                        self.assertIn(instruction_text(name, profile).strip(), rule, "%s is missing from the Cursor rule on %s" % (name, profile))
                    else:  # another profile's file: its opening line (the file is a template there, which this profile cannot render) is absent
                        first = next(l for l in (INSTRUCTIONS / name).read_text().splitlines() if l.strip())
                        self.assertNotIn(first, rule, "%s belongs to another profile and is in the Cursor rule on %s" % (name, profile))

    def test_every_canonical_instruction_file_is_accounted_for(self):
        self.assertEqual(sorted(p.name for p in INSTRUCTIONS.iterdir()), sorted(INSTRUCTION_FILES))

    def test_the_check_catches_the_past_gap_atlassian_missing_on_work(self):
        """Cursor seats on the work profile once had no Jira server. The same check, fed that output, fails and names jira."""
        a = Apply(self, "axon-work-computer")
        a.run()
        without_jira = {k: v for k, v in a.servers().items() if k != "jira"}
        self.assertEqual(missing_servers("axon-work-computer", without_jira), ["jira"])
        self.assertEqual(missing_servers("personal", without_jira), [])  # personal has no jira, so the same output is fine there

    def test_a_canonical_server_the_apply_does_not_write_fails_the_check(self):
        a = Apply(self, "axon-work-computer", exclude="jira\n")  # the apply skips jira here, the real list does not name it
        a.run()
        self.assertEqual(missing_servers("axon-work-computer", a.servers()), ["jira"])


if __name__ == "__main__":
    unittest.main()
