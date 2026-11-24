"""The creating-formal-verification skill and the pinned pstack statechart external land on the personal profile only.

The work profile (axon-work-computer) gets neither: a third-party tool that installs Java and a TLA+ jar on first run is asked about
before it goes on the employer's machine. Termux gets neither: it has no Java. Same `chezmoi managed` run as test_coverage.py, with
the termux profile added.
"""
import unittest

from test_coverage import managed

SKILL = ".local/share/agent-harness/canonical/skills/creating-formal-verification/SKILL.md"
EXTERNAL = ".local/share/agent-harness/external-skills/pstack/statechart/SKILL.md"


class FormalVerificationProfiles(unittest.TestCase):
    def test_personal_gets_the_skill_and_the_external(self):
        got = managed("personal")
        self.assertIn(SKILL, got)
        self.assertIn(EXTERNAL, got)

    def test_work_and_termux_get_neither(self):
        for profile in ("axon-work-computer", "termux"):
            with self.subTest(profile=profile):
                got = managed(profile)
                self.assertNotIn(SKILL, got)
                self.assertNotIn(EXTERNAL, got)
                self.assertEqual([p for p in got if "creating-formal-verification" in p or "external-skills/pstack" in p], [])


if __name__ == "__main__":
    unittest.main()
