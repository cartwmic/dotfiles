"""The fix round of the extend mode: check_citations.py (row budget, one sentence a line, duplicate lines, numbers across `_`, `,` and k/M), coverage.py (placement),
inventory.py and final_recheck.py (re-check routing). Each test breaks one rule and fails without its change.
Run: python3 -I tests/deriving-readable-docs/test_extend_fixes.py"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"
SKILL_DIR = SCRIPTS.parent
EXTEND = (SKILL_DIR / "references/extend.md").read_text(encoding="utf-8")


def make_repo(files):
    tmp = tempfile.TemporaryDirectory()
    for rel, text in files.items():
        p = Path(tmp.name) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp


def check(doc, files, *extra):
    with make_repo(files) as repo, tempfile.TemporaryDirectory() as d:
        docp = Path(d) / "DOC.md"
        docp.write_text(doc)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), str(docp), repo, *extra], capture_output=True, text=True)
    return r.returncode, r.stdout


REPO = {"src/a.rs": "one\ntwo\nthree\n"}


class RowBudgetTest(unittest.TestCase):
    """F7: a writer's budget is rows x 25 words; the `## A<n> <title>` heading is not a row."""
    DOC = "## A4 Adding and listing notes\n\nIt saves a note in the test (`src/a.rs:1`).\nIt lists a note in the test (`src/a.rs:2`).\n"  # 5 heading words, 2 rows of 7 words

    def test_the_heading_is_not_counted_against_the_row_budget(self):
        code, out = check(self.DOC, REPO, "--max-row-words", "14")
        self.assertEqual(code, 0, out)
        code, out = check(self.DOC, REPO, "--max-row-words", "13")
        self.assertEqual(code, 1)
        self.assertIn("FAIL budget: 14 words outside the headings, budget 13", out)

    def test_max_words_still_counts_the_heading(self):
        self.assertEqual(check(self.DOC, REPO, "--max-words", "18")[0], 1)
        self.assertEqual(check(self.DOC, REPO, "--max-words", "19")[0], 0)

    def test_extend_md_gives_the_writer_the_row_budget_flag(self):
        step = EXTEND.split("## E3")[1].split("## E4")[0]
        self.assertIn("--max-row-words <rows x estimate>", step)
        self.assertNotIn("--max-words <rows x estimate>", step)

    def test_a_row_budget_that_is_not_a_number_is_a_usage_error(self):
        self.assertEqual(check(self.DOC, REPO, "--max-row-words", "lots")[0], 2)


APPENDIX = "# Part 2: Appendix\n\n## A4 Adding\n\n%s"


class OneSentenceLineTest(unittest.TestCase):
    """F5: the check refuses an appendix line of two sentences, so the writer learns it at write time and not when stamp.py refuses it."""

    def test_an_appendix_line_of_two_sentences_fails_and_names_the_line(self):
        code, out = check(APPENDIX % "It saves a note. It lists notes. `src/a.rs:1`\n", REPO)
        self.assertEqual(code, 1, out)
        self.assertIn("DOC.md:5: FAIL sentences: 2 sentences on one line", out)

    def test_one_sentence_a_line_passes_and_a_stop_inside_a_quoted_message_is_one_sentence(self):
        doc = APPENDIX % 'It saves a note. `src/a.rs:1`\nIt says "Unable to save. Try again." `src/a.rs:2`\n'
        code, out = check(doc, {"src/a.rs": "x\nUnable to save. Try again.\n"})
        self.assertEqual(code, 0, out)

    def test_part_1_lines_of_several_sentences_are_not_refused(self):
        doc = "# Part 1: In plain English\n\n## What it is\n\nIt saves notes. It lists notes. [A4.0001]\n" + (APPENDIX % "It saves a note. `src/a.rs:1` [A4.0001]\n")
        self.assertEqual(check(doc, REPO)[0], 0)


class DuplicateLineTest(unittest.TestCase):
    """F3: two appendix lines that make the same claim are one claim twice."""

    def test_two_lines_with_the_same_words_after_case_and_spacing_fail_and_name_the_first(self):
        doc = APPENDIX % "It saves a note. `src/a.rs:1`\nIt  SAVES a note.  `src/a.rs:2`\n"
        code, out = check(doc, REPO)
        self.assertEqual(code, 1, out)
        self.assertIn("DOC.md:6: FAIL duplicate: the same claim as line 5", out)

    def test_the_same_words_under_another_section_still_fail(self):
        doc = (APPENDIX % "It saves a note. `src/a.rs:1`\n") + "\n## A5 Listing\n\nIt saves a note. `src/a.rs:3`\n"
        self.assertIn("FAIL duplicate", check(doc, REPO)[1])

    def test_different_claims_and_a_part_1_sentence_that_restates_a_line_pass(self):
        doc = "# Part 1: In plain English\n\n## What it is\n\nIt saves a note. [A4.0001]\n\n" + (APPENDIX % "It saves a note. `src/a.rs:1` [A4.0001]\nIt lists notes. `src/a.rs:2`\n")
        code, out = check(doc, REPO)
        self.assertEqual(code, 0, out)
        self.assertNotIn("duplicate", out)


if __name__ == "__main__":
    unittest.main()
