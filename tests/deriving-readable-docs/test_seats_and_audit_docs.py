"""Seat names, the table header report row, and the condition audit of coverage lines, as the skill text states them.
Run: python3 -I tests/deriving-readable-docs/test_seats_and_audit_docs.py"""
import re
import sys
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs"
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.dont_write_bytecode = True
import score  # noqa: E402

REF = SKILL_DIR / "references"
text = lambda p: p.read_text(encoding="utf-8")
SKILL, DRAFTING, COVERAGE, CHECK = text(SKILL_DIR / "SKILL.md"), text(REF / "drafting.md"), text(REF / "coverage.md"), text(REF / "check-brief.md")
WRITER, CHECKER, SCOUT = "Seat: lead (skill writer), Opus 5.5 medium", "Seat: reviewer (skill checker), Opus 5.5 medium", "Seat: scout, Haiku 5.5 xhigh"


class SeatNamesTest(unittest.TestCase):
    def test_skill_and_drafting_name_each_session_by_the_seat_table(self):
        for doc in (SKILL, DRAFTING):
            for seat in (WRITER, SCOUT):
                self.assertIn(seat, doc)
        self.assertIn(CHECKER, SKILL)

    def test_the_first_line_of_each_brief_file_is_its_seat(self):
        self.assertTrue(text(REF / "coverage-lister.md").startswith(WRITER))
        self.assertTrue(text(REF / "coverage-grader.md").startswith(CHECKER))
        self.assertTrue(CHECK.startswith(CHECKER))
        reader = text(REF / "reader-check.md")
        self.assertIn(CHECKER, reader)
        self.assertIn(WRITER, reader)

    def test_no_session_is_named_by_a_bare_model_family_any_more(self):
        for name in ("SKILL.md", "references/drafting.md", "references/coverage.md", "references/fix-rounds.md", "references/reader-check.md", "references/coverage-lister.md",
                     "references/coverage-grader.md", "references/check-brief.md"):
            body = text(SKILL_DIR / name)
            self.assertNotRegex(body, r"Seat: (?:checker|lister|grader|writer), Opus", name)
            self.assertNotRegex(body, r"(?i)\b(?:fresh|separate|a) Opus (?:session|writer|checker|reader|grader|lister|front)", name)
            self.assertNotIn("Sonnet", body, name)


class HeaderRowTest(unittest.TestCase):
    def test_the_check_brief_gives_the_exact_row_for_a_table_header_and_forbids_the_wrong_one(self):
        self.assertIn("`read | N.k | HOLDS | outside`", CHECK)
        self.assertRegex(CHECK, r"(?i)table header row")
        self.assertIn("Never `outside | outside`", CHECK)
        self.assertRegex(CHECK, r"version 10")

    def test_score_reads_that_row_and_reports_the_same_in_its_error(self):
        rows = score.parse_rows("report.md", "Slice: slice-1\nread | 3.1 | HOLDS | outside\nread | 4.1 | HOLDS | src/a.py:3\n")
        self.assertEqual(rows, [("3.1", "HOLDS", "outside"), ("4.1", "HOLDS", "src/a.py:3")])
        self.assertIn("read | N.k | HOLDS | outside", Path(SKILL_DIR / "scripts/score.py").read_text())


class CoverageConditionAuditTest(unittest.TestCase):
    def test_every_added_or_edited_line_and_every_part_1_sentence_gets_an_audit_row(self):
        for phrase in ("Every line a writer adds or edits, and every Part 1 sentence a coverage step adds", "the whole function around it", "early exits, flags, branches and other callers",
                       "either stated in the line or the line is narrowed", "work/part1-audit.md"):
            self.assertIn(phrase, COVERAGE)

    def test_an_edited_lines_audit_row_covers_the_whole_line(self):
        self.assertRegex(COVERAGE, r"(?i)for an edited line the audit row covers the whole line")
        self.assertRegex(COVERAGE, r"(?i)the edit may not drop one")

    def test_the_coverage_writer_passes_the_same_check_as_the_main_writers_and_its_flags_exist(self):
        cmd = re.search(r"`(python3 -I <skill>/scripts/check_citations\.py cov-A<n>\.md[^`]*)`", COVERAGE)
        self.assertIsNotNone(cmd)
        source = (SKILL_DIR / "scripts/check_citations.py").read_text()
        for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", cmd.group(1)):
            self.assertIn(flag, source, flag)
        self.assertIn("--audit work/audit.md", cmd.group(1))
        self.assertIn("work/guards.md", COVERAGE)
        self.assertIn("work/evidence.md", COVERAGE)

    def test_the_skill_says_step_8_lines_are_audited_as_the_main_writers_are(self):
        step = re.search(r"^8\. (.*)$", SKILL, re.M).group(1)
        self.assertRegex(step, r"every line audited as step 5's are")

    def test_a_partial_fact_is_an_edit_and_a_missing_fact_goes_next_to_its_neighbour_in_the_text(self):
        self.assertRegex(COVERAGE, r"A PARTIAL fact is an edit")
        self.assertRegex(COVERAGE, r"never gets a second line")
        self.assertRegex(COVERAGE, r"directly after it")
        self.assertRegex(COVERAGE, r"never goes at the top of the section")
        self.assertNotIn("a prose line before the section's first `###` block", COVERAGE)

    def test_the_fit_rule_and_the_budget_flag_are_in_the_text(self):
        self.assertIn("--budget <the whole-guide budget of step 4>", COVERAGE)
        self.assertIn("## Did not fit", COVERAGE)
        self.assertIn("25 words a fact", COVERAGE)
        self.assertNotIn("25 words for each fact", COVERAGE)


if __name__ == "__main__":
    unittest.main()
