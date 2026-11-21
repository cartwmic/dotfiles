"""SKILL.md and references/drafting.md of the general skill: what they say must match the scripts and the shape the design set.
Run: python3 -I tests/deriving-readable-docs/test_skill_docs.py"""
import re
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs"
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
DRAFTING = (SKILL_DIR / "references/drafting.md").read_text(encoding="utf-8")
READER = (SKILL_DIR / "references/reader-check.md").read_text(encoding="utf-8")
CHECK_BRIEF = (SKILL_DIR / "references/check-brief.md").read_text(encoding="utf-8")
CALLED_FROM_SKILL = ("surfaces.py", "check_citations.py", "lint_main.py", "assemble.py", "slice.py", "score.py", "harvest_points.py", "stamp.py", "lint_brief.py")


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
        for cmd in re.findall(r"`(python3 -I [^`]+)`", SKILL + READER + DRAFTING + CHECK_BRIEF):
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


class RoundTwoTest(unittest.TestCase):
    """What the second climb round changed in the written method."""
    INPUT_RULE = "the appendix sentences plus the index"

    def step(self, n):
        m = re.search(r"^%d\. (.*)$" % n, SKILL, re.M)
        self.assertIsNotNone(m, "step %d" % n)
        return m.group(1)

    def test_the_front_writer_input_rule_is_one_sentence_in_both_files(self):
        self.assertIn(self.INPUT_RULE, self.step(6))
        self.assertIn(self.INPUT_RULE, DRAFTING)
        self.assertNotIn("index only", SKILL.lower())

    def test_step_5_asks_for_six_to_ten_appendix_sections_grouping_scout_names(self):
        self.assertRegex(self.step(5), r"6-10 appendix sections")
        self.assertRegex(self.step(5), r"(?i)group[^.]*scout")

    def test_stamping_is_a_step_before_the_audit_and_the_assembly(self):
        self.assertRegex(self.step(5), r"stamp\.py")
        self.assertRegex(DRAFTING, r"stamp\.py")

    def test_step_9_stops_after_two_fix_rounds_and_cuts_or_narrows(self):
        step = self.step(9)
        self.assertRegex(step, r"at most 2 fix rounds")
        self.assertRegex(step, r"(?i)cut|narrow")
        self.assertRegex(step, r"(?i)split[^.]*(rather|not)[^.]*checker")

    def test_part_1_has_a_how_to_start_section_in_the_front_writers_list(self):
        self.assertIn("How to start", SKILL)
        self.assertRegex(DRAFTING, r"(?i)how to start")
        self.assertRegex(DRAFTING, r"(?i)frame writer[^\n]*how to start|how to start[^\n]*frame writer|install")

    def test_drafting_warns_against_cat_n_on_several_files(self):
        self.assertRegex(DRAFTING, r"cat -n")
        self.assertRegex(DRAFTING, r"(?i)several files|more than one file")

    def test_drafting_asks_for_the_guard_sheet_and_the_evidence_file(self):
        for word in ("--guards", "guards.md", "not relevant", "evidence.md"):
            self.assertIn(word, DRAFTING, word)

    def test_the_reader_bar_is_five_of_five_and_the_lint_and_the_unknown_list_does_not_gate(self):
        self.assertRegex(READER, r"5 of 5|5/5")
        self.assertRegex(READER, r"(?i)does not gate")
        self.assertNotRegex(READER + SKILL + DRAFTING, r"--unknown|15 entries|at most 15")
        self.assertIn("--surfaces", READER)
        self.assertNotRegex(READER, r"at most 3 unknown")
        self.assertNotRegex(READER, r"at least 4 of 5")

    def test_the_reader_is_opus_and_gets_one_fix_round(self):
        reader = READER.split("## Reader", 1)[1].split("##", 1)[0]
        self.assertIn("Opus", reader)
        self.assertNotIn("Sonnet", reader)
        self.assertRegex(READER, r"(?i)one (reader )?fix round")

    def test_the_check_brief_tells_checkers_a_value_set_on_the_cited_line_holds_for_count(self):
        self.assertRegex(CHECK_BRIEF, r"(?i)set on the cited line")
        self.assertRegex(CHECK_BRIEF, r"version 8")
        self.assertNotRegex(CHECK_BRIEF, r"version [567]\b")

    def test_a_glossary_entry_is_tagged_like_any_other_part_1_sentence(self):
        self.assertRegex(DRAFTING, r"(?i)glossary[^\n]*each[^\n]*tag")

    def test_the_reader_does_not_list_a_word_the_text_defines(self):
        self.assertRegex(READER, r"(?i)do not list a word the text defines")

    def test_every_session_the_skill_starts_names_its_model(self):
        self.assertIn("scout session (Sonnet)", SKILL)
        self.assertIn("fresh Opus session per writer", SKILL)
        self.assertIn("Opus front writer", SKILL)
        self.assertIn("Opus checker session", SKILL)
        self.assertIn("fresh Opus reader", SKILL)
        self.assertIn("fresh Opus grader", SKILL)
        self.assertIn("Seat: checker, Opus", CHECK_BRIEF)
        self.assertNotIn("the model the caller's table gives", DRAFTING + SKILL)
        self.assertNotIn("the model your seat table gives", CHECK_BRIEF)

    def test_the_front_writer_brief_states_the_backtick_cap_the_surfaces_rule_and_no_ai_slop(self):
        front = DRAFTING.split("**Front writer**", 1)[1]
        self.assertRegex(front, r"(?i)at most 8 distinct backticked")
        self.assertIn("surfaces.json", front)
        self.assertIn("no-ai-slop", front)

    def test_step_9_has_the_lead_use_a_front_writer_session_for_part_1_and_a_list_of_ids(self):
        self.assertRegex(SKILL, r"(?i)Part 1 finding is fixed by a fresh Opus front-writer session")
        self.assertIn("--ids", SKILL)
        self.assertIn("--record-fixed", SKILL)
        self.assertIn("--fixed", SKILL)
        self.assertIn("--slices", SKILL)

    def test_the_check_brief_asks_for_a_row_for_every_claim_and_the_next_sentence_rule(self):
        self.assertRegex(CHECK_BRIEF, r"read \| N\.k \| VERDICT \| path:line")
        self.assertRegex(CHECK_BRIEF, r"(?i)very next sentence that carries the same tag")
        self.assertRegex(CHECK_BRIEF, r"(?i)at most 60 claims")

    def test_the_check_brief_says_how_to_judge_by_default_in_part_1(self):
        self.assertRegex(CHECK_BRIEF, r"(?i)by default")
        self.assertRegex(CHECK_BRIEF, r"(?i)by default[^.\n]*(default|shows)")


if __name__ == "__main__":
    unittest.main()
