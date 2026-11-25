"""The reviewer brief and the findings contract reach both desktop profiles, and both have `pr-record` and the coordinator `pr-body-check`.

The agent-record rule applies on personal and on work: the `Decisions:` line is in the PR's agent record, never in the PR description (the hook that
refuses a description or a merge runs on both: tests/agent-kill-guard/test_bash_rules.py). Only a machine with no `pr-record`, which neither desktop
profile is (Termux), keeps the line in the handoff. A text that tells a work lead the opposite fails a PR at merge, after review passed it.
"""

import unittest
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness"


class WorkProfileTextTests(unittest.TestCase):
    def test_the_brief_applies_the_record_rule_on_both_desktop_profiles(self):
        brief = (HARNESS / "reviewer-brief.md").read_text(encoding="utf-8")
        self.assertIn("applies on both desktop profiles, personal and work, where `pr-record` is installed", brief)
        self.assertIn("(or has no record, where the machine has `pr-record`: both desktop profiles; elsewhere, a handoff with none)", brief)
        self.assertIn("On both desktop profiles a `Decisions:` line in the description is a finding", brief)

    def test_no_text_puts_the_work_profile_outside_the_record_rule(self):
        for name in ("reviewer-brief.md", "findings-contract.md"):
            text = (HARNESS / name).read_text(encoding="utf-8")
            for stale in ("(the work profile)", "the work profile has none", "stays in the handoff or the PR description", "the personal profile). Where it does not"):
                self.assertNotIn(stale, text, name)

    def test_the_contract_says_neither_desktop_profile_lacks_pr_record(self):
        contract = (HARNESS / "findings-contract.md").read_text(encoding="utf-8")
        self.assertIn("on a machine with no `pr-record`, which neither desktop profile is, the `Decisions:` line stays in the handoff", contract)


class ClaimsSentenceTests(unittest.TestCase):
    """The one judgment the claims tool leaves to the reviewer: whether a claim's record supports it, and which true statements carry no claim."""

    def test_the_brief_asks_whether_each_claims_record_supports_it(self):
        brief = (HARNESS / "reviewer-brief.md").read_text(encoding="utf-8")
        self.assertIn("for each claim, does its record support it; list true statements that have none.", brief)


class NoteFixDecisionTests(unittest.TestCase):
    """A fix made for a review finding or note that changes a design choice is itself a choice, and is logged."""

    def test_the_brief_makes_a_missing_record_for_a_choice_changing_fix_a_finding(self):
        brief = (HARNESS / "reviewer-brief.md").read_text(encoding="utf-8")
        self.assertIn("A fix for an earlier finding or note is a choice too when it changes a design choice", brief)
        self.assertIn("A fix that changed a choice and has no record is a blocking finding with the `decision log:` prefix, not a silent pass", brief)
        self.assertIn("A pure wording or mechanical fix is not a choice and needs none", brief)

    def test_the_contract_names_the_decision_id_on_a_fixed_disposition_that_changed_a_choice(self):
        contract = (HARNESS / "findings-contract.md").read_text(encoding="utf-8")
        self.assertIn("A `fixed` disposition whose fix changed a design choice also names that choice's decision id", contract)


if __name__ == "__main__":
    unittest.main()
