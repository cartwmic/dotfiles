"""check_citations.py --max-sentence-words and the claims line, the doc-file overreach rule, and the claims.py reader, run as scripts.
Run: python3 -I tests/deriving-readable-docs/test_sentence_limit.py"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"
REPO = {"src/a.rs": "one\ntwo\nthree\n", "README.md": "# r\nIt serves every peer.\n"}


def check(doc, *extra):
    with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as d:
        for rel, text in REPO.items():
            p = Path(repo) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        docp = Path(d) / "DOC.md"
        docp.write_text(doc)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), str(docp), repo, *extra], capture_output=True, text=True)
    return r.returncode, r.stdout


def words(n):
    return " ".join("w%d" % i for i in range(n))


class SentenceLimitTest(unittest.TestCase):
    def test_a_sentence_over_the_limit_fails_and_names_its_length(self):
        code, out = check("## S\n\nIt reads %s (`src/a.rs:1`).\n" % words(19), "--max-sentence-words", "18")
        self.assertEqual(code, 1, out)
        self.assertIn(":3: FAIL sentence-length: 21 words, limit 18", out)

    def test_a_sentence_at_the_limit_passes(self):
        code, out = check("## S\n\nIt reads %s (`src/a.rs:1`).\n" % words(16), "--max-sentence-words", "18")
        self.assertEqual(code, 0, out)

    def test_without_the_option_a_long_sentence_is_not_a_failure(self):
        code, out = check("## S\n\nIt reads %s (`src/a.rs:1`).\n" % words(40))
        self.assertEqual(code, 0, out)
        self.assertNotIn("sentence-length", out)

    def test_a_citation_in_the_middle_does_not_cut_a_long_sentence_in_two(self):
        doc = "## S\n\nIt reads %s `src/a.rs:1` and then it writes %s `src/a.rs:2`.\n" % (words(9), words(9))
        code, out = check(doc, "--max-sentence-words", "18")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL sentence-length: 24 words", out)

    def test_two_short_sentences_on_one_line_are_two_claims_each_under_the_limit(self):
        code, out = check("## S\n\nIt reads %s (`src/a.rs:1`). It writes %s (`src/a.rs:2`).\n" % (words(12), words(12)), "--max-sentence-words", "18")
        self.assertEqual(code, 0, out)
        self.assertIn("2 claims, 28 words in them, 14.0 words per claim", out)

    def test_the_claims_line_counts_sentences_bullets_and_rows_not_headings_or_the_header(self):
        doc = ("# Title\n\nRepo: r. Commit: c.\n\n## S\n\n- It reads one (`src/a.rs:1`).\n- It reads two (`src/a.rs:2`).\n\n"
               "| name | what |\n|---|---|\n| a | one |\n")
        code, out = check(doc)
        self.assertIn("claims, ", out)
        claims_line = [l for l in out.splitlines() if "words per claim" in l][0]
        self.assertTrue(claims_line.startswith("4 claims, 10 words in them"), claims_line)  # 2 bullets and 2 table rows; the separator row, the header and headings are not claims

    def test_a_printed_block_is_not_a_claim_and_not_a_word(self):
        doc = "## S\n\nIt reads one (`src/a.rs:1`).\n\n<!-- printed -->\nA1 | every surface here is `src/zzz.rs:99` and wrong\n<!-- /printed -->\n"
        code, out = check(doc)
        self.assertEqual(code, 0, out)  # the printed row cites a missing file and says "every": neither is checked
        self.assertIn("1 claims, 3 words in them, 3.0 words per claim", out)
        self.assertIn("4 words", out)  # the printed row adds none: "It reads one" is 3 words and the heading is the 4th

    def test_a_bad_limit_is_a_usage_error(self):
        self.assertEqual(check("## S\n\nIt reads one (`src/a.rs:1`).\n", "--max-sentence-words", "many")[0], 2)

    def test_a_part_1_tag_is_not_a_word(self):
        code, out = check("## S\n\nIt reads %s. [A4.2] It writes it (`src/a.rs:1`).\n" % words(16), "--max-sentence-words", "18")
        self.assertEqual(code, 0, out)


class DocFileOverreachTest(unittest.TestCase):
    def test_every_backed_only_by_a_readme_line_fails_unless_it_says_so(self):
        code, out = check("## S\n\nIt serves every peer (`README.md:2`).\n")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL overreach: every", out)
        self.assertEqual(check("## S\n\nIt serves every peer `README.md:2` (README).\n")[0], 0)

    def test_every_backed_by_a_code_line_is_only_listed(self):
        code, out = check("## S\n\nIt serves every peer (`src/a.rs:1`).\n")
        self.assertEqual(code, 0, out)
        self.assertIn("flag overreach: every", out)

    def test_a_part_1_tag_labels_an_uncited_sentence(self):
        doc = "## Part 1\n\nIt reads every file. [A4.2]\n\n## A4 Reading\n\nIt reads one file (`src/a.rs:1`).\n"
        code, out = check(doc)
        self.assertEqual(code, 0, out)
        self.assertEqual(check("## Part 1\n\nIt reads every file.\n\n## A4 Reading\n\nIt reads one file (`src/a.rs:1`).\n")[0], 1)


if __name__ == "__main__":
    unittest.main()
