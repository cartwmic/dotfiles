"""The rules the SKILL.md of designing-the-smallest-version states in prose, pinned so an edit cannot drop them.
Run: python3 -I tests/designing-the-smallest-version/test_skill_text.py"""
import unittest
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/designing-the-smallest-version/SKILL.md").read_text(encoding="utf-8")


class SecurityRule(unittest.TestCase):
    def test_generic_security_sections_stay_out(self):
        self.assertIn("add no generic security or threat sections", SKILL)

    def test_an_owner_stated_security_requirement_is_a_constraint_the_design_meets(self):
        self.assertIn("A security requirement the owner states", SKILL)
        self.assertIn("is a constraint the design must meet", SKILL)
        self.assertIn("show where the design meets it and the decision that does", SKILL)

    def test_the_old_blanket_ban_is_gone(self):
        self.assertNotIn("add no security or threat sections", SKILL)


class RegisterLabels(unittest.TestCase):
    def test_the_label_is_named_where_the_design_has_a_place_for_it(self):
        self.assertIn("in the `Inputs used` header line of `DESIGN.md` (label, file, commit)", SKILL)
        self.assertIn("Inputs used (given / inferred; with several registers, each one's label, file and commit)", SKILL)  # the header template
        self.assertNotIn("Inputs list of Section 1", SKILL)  # Section 1 is Orientation: it has no Inputs list


class DogfoodPath(unittest.TestCase):
    CHECKLIST = (Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/review-plans/references/review-checklist.md").read_text(encoding="utf-8")

    def test_the_path_names_the_measures_and_the_way_back_for_each_increment(self):
        self.assertIn("switched on for real use when built", SKILL)
        self.assertIn("the number that would change course, and the one command that undoes it", SKILL)
        self.assertIn("An increment never depends on an observation period.", SKILL)
        self.assertIn("measures and where logged, change-course number, undo command, depends on (steps only), parallel?", SKILL)  # the template line

    def test_the_plan_review_checklist_asks_for_the_same_and_not_for_a_rollout_strategy(self):
        self.assertIn("Each step is switched on for real use when built", self.CHECKLIST)
        self.assertNotIn("Rollout and rollback strategy exists", self.CHECKLIST)


if __name__ == "__main__":
    unittest.main()
