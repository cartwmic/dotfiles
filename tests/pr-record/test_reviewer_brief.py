"""The reviewer brief and the findings contract reach the work profile too, which has no `pr-record` and no coordinator `pr-body-check`.

The agent-record rule must apply only where the profile has `pr-record`; elsewhere a reviewer checks the `Decisions:` line in the handoff or the
PR description. Without that, every work PR that makes a material choice would fail review for a record nobody can write there.
The hook that refuses a description or a merge is personal-only (tests/agent-kill-guard/test_bash_rules.py, "the work profile ... do not run it").
"""

import unittest
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness"


class WorkProfileTextTests(unittest.TestCase):
    def test_the_brief_scopes_the_record_rule_to_a_profile_with_pr_record(self):
        brief = (HARNESS / "reviewer-brief.md").read_text(encoding="utf-8")
        self.assertIn("applies only where the profile has `pr-record` (`command -v pr-record`", brief)
        self.assertIn("the `Decisions:` line stays at the end of the handoff or the PR description, and you check it there", brief)
        self.assertIn("where the profile has `pr-record`; elsewhere, a PR with none in its description", brief)
        self.assertIn("Where the profile has no `pr-record`, the `Decisions:` line in the description is expected, not a finding", brief)

    def test_the_contract_says_the_decisions_line_stays_in_the_description_without_pr_record(self):
        contract = (HARNESS / "findings-contract.md").read_text(encoding="utf-8")
        self.assertIn("on a profile with no `pr-record` the `Decisions:` line stays in the handoff or the PR description", contract)


if __name__ == "__main__":
    unittest.main()
