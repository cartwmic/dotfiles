"""The rules the SKILL.md of designing-the-smallest-version states in prose, pinned so an edit cannot drop them.
Run: python3 -I tests/designing-the-smallest-version/test_skill_text.py"""
import unittest
from pathlib import Path

SKILL = (Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/designing-the-smallest-version/SKILL.md").read_text(encoding="utf-8")


class RegisterLabels(unittest.TestCase):
    def test_the_label_is_named_where_the_design_has_a_place_for_it(self):
        self.assertIn("in the `Inputs used` header line of `DESIGN.md` (label, file, commit)", SKILL)
        self.assertNotIn("Inputs list of Section 1", SKILL)  # Section 1 is Orientation: it has no Inputs list


if __name__ == "__main__":
    unittest.main()
