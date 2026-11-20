"""SKILL.md and references/drafting.md of the general skill: what they say must match the scripts and the shape the design set.
Run: python3 -I tests/deriving-readable-docs/test_skill_docs.py"""
import re
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs"
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
DRAFTING = (SKILL_DIR / "references/drafting.md").read_text(encoding="utf-8")
CALLED_FROM_SKILL = ("surfaces.py", "check_citations.py", "lint_main.py", "assemble.py", "slice.py", "score.py", "harvest_points.py")


def frontmatter(text):
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return dict(l.split(": ", 1) for l in m.group(1).splitlines() if ": " in l)


class SkillShapeTest(unittest.TestCase):
    def test_the_description_says_any_repo_and_one_guide_and_not_tests_or_journeys(self):
        desc = frontmatter(SKILL)["description"]
        self.assertEqual(frontmatter(SKILL)["name"], "deriving-readable-docs")
        self.assertIn("any repo", desc)
        self.assertIn("GUIDE.md", desc)
        for gone in ("journey", "validation point", "PRD.md", "SPEC.md"):
            self.assertNotIn(gone, desc, gone)

    def test_no_line_of_skill_md_names_a_journey(self):
        self.assertEqual([l for l in SKILL.splitlines() if re.search("journey", l, re.I)], [])

    def test_the_output_is_one_guide_and_tests_are_optional_evidence(self):
        self.assertIn("GUIDE.md", SKILL)
        for gone in ("PRD.md", "DESIGN.md", "SPEC.md"):
            self.assertNotIn(gone, SKILL)
        self.assertRegex(SKILL, r"(?i)code is the source")
        self.assertRegex(SKILL, r"(?i)tests?[^.\n]*optional|optional[^.\n]*tests?")

    def test_it_stays_near_the_length_the_design_set(self):
        self.assertLess(len(SKILL.split()), 1400)


class EveryStepIsAScriptCallTest(unittest.TestCase):
    def test_each_mechanical_script_is_called_by_its_path_and_exists(self):
        for name in CALLED_FROM_SKILL:
            self.assertIn("scripts/" + name, SKILL, name)
            self.assertTrue((SKILL_DIR / "scripts" / name).is_file(), name)

    def test_the_sentence_limit_is_passed_as_eighteen(self):
        self.assertRegex(SKILL, r"check_citations\.py[^`]*--max-sentence-words 18")

    def test_every_flag_in_a_command_is_one_its_script_has(self):
        seen = 0
        for cmd in re.findall(r"`(python3 -I [^`]+)`", SKILL):
            script = re.search(r"scripts/(\w+\.py)", cmd)
            self.assertIsNotNone(script, cmd)
            source = (SKILL_DIR / "scripts" / script.group(1)).read_text(encoding="utf-8")
            for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", cmd):
                self.assertIn(flag, source, "%s is not a flag of %s" % (flag, script.group(1)))
                seen += 1
        self.assertGreater(seen, 8)

    def test_the_reader_check_is_a_step_and_its_file_exists(self):
        self.assertIn("references/reader-check.md", SKILL)
        self.assertRegex(SKILL, r"score\.py --reader")

    def test_every_reference_file_named_exists(self):
        named = set(re.findall(r"references/([\w.-]+)", SKILL + DRAFTING))
        self.assertTrue(named)
        for name in named:
            self.assertTrue((SKILL_DIR / "references" / name).is_file(), name)

    def test_the_removed_count_block_is_not_named(self):
        for gone in ("--points", "--left-out", "left-out.txt"):
            self.assertNotIn(gone, SKILL + DRAFTING)

    def test_no_script_is_left_that_nothing_calls(self):
        """A script the skill no longer uses is deleted in the same change: each one is named by SKILL.md, drafting.md or another script."""
        scripts = sorted((SKILL_DIR / "scripts").glob("*.py"))
        corpus = {p.name: p.read_text(encoding="utf-8") for p in scripts}
        corpus["SKILL.md"], corpus["drafting.md"] = SKILL, DRAFTING
        for p in scripts:
            users = [n for n, text in corpus.items() if n != p.name and (p.name in text or p.stem in text and re.search(r"import %s\b|from %s import" % (p.stem, p.stem), text))]
            self.assertTrue(users, "%s is used by nothing" % p.name)


class DraftingLimitTest(unittest.TestCase):
    def test_the_limit_is_stated_with_split_and_keep_the_condition(self):
        self.assertRegex(DRAFTING, r"(?i)at most 18 words")
        self.assertRegex(DRAFTING, r"(?i)split[^.\n]*keep the condition in each part")

    def test_the_stage_2_command_and_the_lead_limits_pass_the_limit_to_the_check(self):
        self.assertGreaterEqual(len(re.findall(r"check_citations\.py[^`\n]*--max-sentence-words 18", DRAFTING)), 2)

    def test_the_old_word_per_sentence_figure_and_the_thin_sentence_rule_are_gone(self):
        self.assertNotIn("about 25 words", DRAFTING)
        self.assertNotIn("B/25", DRAFTING)
        self.assertNotIn("thin sentences", DRAFTING)
        self.assertRegex(DRAFTING, r"about 14 words")


if __name__ == "__main__":
    unittest.main()
