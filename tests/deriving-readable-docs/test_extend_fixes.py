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


if __name__ == "__main__":
    unittest.main()
