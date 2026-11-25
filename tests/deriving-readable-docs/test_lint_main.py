"""lint_main.py: the Part 1 gate, run as a script on a small GUIDE.md. Each test breaks one rule of a passing guide.
Run: python3 -I tests/deriving-readable-docs/test_lint_main.py"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = tempfile.mkdtemp(prefix="state-")  # the scripts log each run (runlog.py): keep these runs out of the real log
os.environ["XDG_STATE_HOME"] = STATE
atexit.register(shutil.rmtree, STATE, True)

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"

SURFACES = [{"kind": "command", "name": "notes add", "file": "src/cli.py", "line": 3}, {"kind": "flag", "name": "--tag <name>", "file": "src/cli.py", "line": 5}]

GUIDE = """# Part 1: In plain English

## What it is

Notes lets you save short notes from the terminal. [A3.1]
Who it is for: anyone who takes notes in a terminal. [A3.1]

## How to start

You run `notes add` to save one. [A4.1]

## What you can do

You can keep up to 5 notes in one day. [A4.2]

# Part 2: Appendix

## A3 The product as a whole

Notes saves short notes from the terminal. `src/cli.py:1` [A3.1]

## A4 Adding notes

The `notes add` command saves a note. `src/cli.py:3` [A4.1]
It stops after 5 notes in one day. `src/cli.py:7` [A4.2]
"""


def lint(guide, *extra, surfaces=SURFACES):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "src").mkdir()
        (Path(d) / "src/cli.py").write_text("x\n" * 10)
        Path(d, "GUIDE.md").write_text(guide)
        Path(d, "surfaces.json").write_text(json.dumps(surfaces))
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "lint_main.py"), str(Path(d, "GUIDE.md")), d, "--surfaces", str(Path(d, "surfaces.json")), *extra],
                           capture_output=True, text=True)
    return r.returncode, r.stdout


def sentence(n):
    return " ".join("word%d" % i for i in range(n))


class LintMainTest(unittest.TestCase):
    def fails(self, guide, kind):
        code, out = lint(guide)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL %s:" % kind, out)
        return out

    def test_a_guide_that_follows_every_rule_passes(self):
        code, out = lint(GUIDE)
        self.assertEqual(code, 0, out)
        self.assertIn("0 failed checks, 0 warnings", out)

    def test_a_sentence_over_18_words_fails_and_is_named(self):
        out = self.fails(GUIDE.replace("You run `notes add` to save one. [A4.1]", "You run `notes add` to save %s. [A4.1]" % sentence(16)), "sentence-length")
        self.assertIn("22 words, limit 18", out)

    def test_an_average_over_14_words_fails_even_when_no_sentence_is_over_18(self):
        long = "You run `notes add` to save %s in one day. [A4.1]" % sentence(10)
        guide = GUIDE.replace("You run `notes add` to save one. [A4.1]", long).replace("Notes lets you save short notes from the terminal. [A3.1]", long)
        out = self.fails(guide, "sentence-length")
        self.assertIn("average", out)

    def test_a_sentence_without_a_tag_fails(self):
        self.fails(GUIDE.replace("You run `notes add` to save one. [A4.1]", "You run `notes add` to save one."), "tag")

    def test_a_tag_that_names_no_appendix_sentence_fails(self):
        out = self.fails(GUIDE.replace("in one day. [A4.2]\n\n# Part 2", "in one day. [A4.9]\n\n# Part 2"), "tag")
        self.assertIn("[A4.9] names no appendix line", out)

    def test_a_tag_after_the_full_stop_counts(self):
        guide = GUIDE.replace("You run `notes add` to save one. [A4.1]", "You run `notes add` to save one. [A4.1]")
        self.assertEqual(lint(guide)[0], 0)
        self.assertEqual(lint(GUIDE.replace("one. [A4.1]", "one [A4.1]."))[0], 0)

    def test_a_citation_in_part_1_fails(self):
        self.fails(GUIDE.replace("to save one.", "to save one (`src/cli.py:3`)."), "citation")

    def test_a_heading_deeper_than_two_levels_fails(self):
        self.fails(GUIDE.replace("## What you can do", "### What you can do"), "heading-depth")

    def test_a_backticked_name_that_is_not_a_surface_fails_and_a_flag_word_of_a_surface_passes(self):
        out = self.fails(GUIDE.replace("`notes add`", "`ghost`"), "backticks")
        self.assertIn("`ghost` is not a surface name", out)
        code, out = lint(GUIDE.replace("You run `notes add` to save one.", "You run `--tag` to save one."))
        self.assertEqual(code, 1, out)  # --tag is a surface (the word of its row), but not in the tagged sentence A4.1
        self.assertNotIn("not a surface name", out)
        self.assertIn("appendix-match", out)

    def test_more_than_8_backticked_names_fails(self):
        names = [{"kind": "command", "name": "cmd%d" % i, "file": "a", "line": 1} for i in range(9)]
        guide = GUIDE.replace("You run `notes add` to save one. [A4.1]", " ".join("`cmd%d`" % i for i in range(9)) + ". [A4.1]")
        guide = guide.replace("The `notes add` command", "The " + " ".join("`cmd%d`" % i for i in range(9)) + " command")
        code, out = lint(guide, surfaces=names)
        self.assertEqual(code, 1, out)
        self.assertIn("9 distinct backticked names, limit 8", out)

    def test_more_than_3_flag_tokens_fails(self):
        out = self.fails(GUIDE.replace("to save one.", "to save one with --a, --b, --c or --d."), "flags")
        self.assertIn("4 --flag tokens, limit 3", out)

    def test_jargon_above_4_hits_per_1000_words_fails_and_the_list_is_a_file(self):
        guide = GUIDE.replace("to save one.", "to save one over the api.")
        out = self.fails(guide, "jargon")
        self.assertIn("1 hits in", out)
        with tempfile.TemporaryDirectory() as d:
            Path(d, "none.txt").write_text("# nothing\nzzz\n")
            code, out = lint(guide, "--jargon", str(Path(d, "none.txt")))
            self.assertEqual(code, 0, out)  # the same word passes when the list does not hold it

    def test_a_number_the_tagged_appendix_sentence_lacks_fails(self):
        out = self.fails(GUIDE.replace("up to 5 notes", "up to 6 notes"), "appendix-match")
        self.assertIn("number 6 is not in [A4.2]", out)

    def test_a_quoted_string_the_tagged_appendix_sentence_lacks_fails(self):
        self.fails(GUIDE.replace("to save one.", 'to save one called "daily".'), "appendix-match")

    def test_a_number_in_a_different_appendix_sentence_than_the_tagged_one_fails(self):
        self.fails(GUIDE.replace("in one day. [A4.2]\n\n# Part 2", "in one day. [A4.1]\n\n# Part 2"), "appendix-match")

    def test_part_1_over_1000_words_fails_at_any_step_and_1000_passes(self):
        filler = lambda n: "\n".join("Notes lets you %s. [A3.1]" % sentence(8) for _ in range(n))
        self.assertEqual(lint(GUIDE.replace("## What you can do", filler(95) + "\n\n## What you can do"))[0], 1)  # over 1,000
        out = lint(GUIDE.replace("## What you can do", filler(95) + "\n\n## What you can do"))[1]
        self.assertIn("FAIL part1-words:", out)
        self.assertIn("limit 1000", out)
        self.assertIn("never cut How to start", out)
        self.assertNotIn("warn part1-words", out)
        self.assertEqual(lint(GUIDE.replace("## What you can do", filler(85) + "\n\n## What you can do"))[0], 0)  # under it

    def test_the_part_1_word_count_is_printed_whether_or_not_a_check_fails(self):
        import re
        counts = []
        for guide in (GUIDE, GUIDE.replace("## What you can do", "\n".join("Notes lets you %s. [A3.1]" % sentence(8) for _ in range(95)) + "\n\n## What you can do")):
            out = lint(guide)[1]
            counts.append(int(re.search(r"Part 1: (\d+) words \(limit 1000\)", out).group(1)))
        self.assertLess(counts[0], 100)
        self.assertGreater(counts[1], 1000)

    def test_max_words_sets_the_part_1_limit_and_a_bad_value_is_a_usage_error(self):
        code, out = lint(GUIDE, "--max-words", "20")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL part1-words:", out)
        self.assertIn("limit 20 at every step", out)
        self.assertIn("(limit 20)", out)
        self.assertEqual(lint(GUIDE, "--max-words", "500")[0], 0)
        self.assertEqual(lint(GUIDE, "--max-words", "many")[0], 2)

    def test_a_trailing_option_with_no_value_exits_2_instead_of_using_a_default(self):
        for option in ("--max-words", "--jargon", "--fixed"):
            self.assertEqual(lint(GUIDE, option)[0], 2, option)

    def test_a_guide_without_a_part_1_heading_fails(self):
        code, out = lint(GUIDE.replace("# Part 1: In plain English", "# Overview"))
        self.assertEqual(code, 1)
        self.assertIn("FAIL part1: no heading `Part 1`", out)
        self.assertIn("Part 1: 0 words (limit 1000)", out)  # the run finishes: no traceback, the count line is still printed

    def test_the_appendix_is_not_judged(self):
        long_appendix = GUIDE + "\nIt stops after 5 notes %s and every one goes `src/cli.py:3`.\n" % sentence(40)
        self.assertEqual(lint(long_appendix)[0], 0)

    def test_bad_usage_exits_2(self):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "lint_main.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
