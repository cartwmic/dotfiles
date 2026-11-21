"""Cursor is a first-class harness: whatever the canonical MCP server file and the canonical skills hold must reach Cursor, on both profiles.
Renders both profiles (real chezmoi), runs the real apply script's `cursor` step in a scratch HOME, and fails when a canonical server is
missing from ~/.cursor/mcp.json or a canonical skill is missing from the folders Cursor reads, unless the server is named in
dot_local/share/agent-harness/canonical/mcp/cursor-exclude.txt (with its reason).

    python3 -m unittest discover -s tests/cursor -p 'test_parity.py' -v
"""
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cursor_apply import PROFILES, Apply, canonical_servers, canonical_skills, exclusions  # noqa: E402

# The user-level skill folders Cursor reads without a setting, from the cursor-agent 2026.11.19 bundle (.cursor/skills and .agents/skills;
# .claude/skills and .codex/skills only with its third-party switch on, so they do not count here).
CURSOR_SKILL_DIRS = (".agents/skills", ".cursor/skills")


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
        for profile in PROFILES:
            stale = exclusions() - set(canonical_servers(profile)) if profile == "axon-work-computer" else set()
            self.assertEqual(sorted(stale), [], "cursor-exclude.txt names servers that are not canonical any more")

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
