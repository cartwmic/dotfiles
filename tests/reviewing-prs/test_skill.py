#!/usr/bin/env python3
"""The reviewing-prs skill: the two Approve rule lines are in the template (outside any profile branch, so both profiles get them).
Run: python3 -I -m unittest discover -s tests/reviewing-prs -v
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "dot_local/share/agent-harness/canonical/skills/reviewing-prs/SKILL.md.tmpl"

APPROVE_RULES = (
    "Approve is not used when a point must be fixed before merge: use Comment or Request changes.",
    "When the draft recommends Approve, frame every point as optional: the author can take it now or in a follow-up, never as a step before merge.",
)


class ApproveRuleTest(unittest.TestCase):
    longMessage = False  # a failure names the missing line only, not the whole skill

    def test_both_approve_rule_lines_are_in_the_skill(self):
        flat = " ".join(TEMPLATE.read_text().split())
        for line in APPROVE_RULES:
            self.assertIn(line, flat, "the reviewing-prs skill lacks this rule line: %s" % line)


if __name__ == "__main__":
    unittest.main()
