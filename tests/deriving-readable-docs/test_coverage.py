"""The coverage pass of the extend mode: coverage.py turns a lister's facts and a grader's grades into a to-do list and a record.
Run: python3 -I tests/deriving-readable-docs/test_coverage.py"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs"
SCRIPTS = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True
import coverage  # noqa: E402
import lint_main  # noqa: E402

FACTS = """# lister output
F1 | core | purpose | The tool syncs notes to a server. | src/app.py:3
F2 | core | setting | The sync interval defaults to 30 seconds. | src/app.py:10
F3 | detail | limit | A note over 1 MB is skipped. | src/app.py:22-24
F4 | detail | failure | A refused connection is retried 3 times. | src/net.py:7
F5 | core | run | Start it with the sync command. | src/app.py:30
"""
GUIDE = """# Part 1: In plain English

## What it is

It syncs your notes to a server. [A3.aaaa]

# Part 2: Appendix: technical detail

## A3 Whole product

The tool syncs notes to a server. `src/app.py:3` [A3.aaaa]

## A4 Syncing

The sync interval is set in the settings. `src/app.py:10` [A4.bbbb]

A refused connection is retried 3 times. `src/net.py:7` [A4.cccc]
"""
BUDGET = 7000
GRADES = """F1 | COVERED | "It syncs your notes to a server."
F2 | PARTIAL | "The sync interval is set in the settings."
F3 | MISSING | -
F4 | COVERED | "A refused connection is retried 3 times."
F5 | MISSING | -
"""


class Work(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "repo/src").mkdir(parents=True)
        (self.root / "work").mkdir()
        (self.root / "repo/src/app.py").write_text("\n".join("app %d" % i for i in range(1, 41)) + "\n")
        (self.root / "repo/src/net.py").write_text("\n".join("net %d" % i for i in range(1, 21)) + "\n")
        self.repo, self.work = str(self.root / "repo"), str(self.root / "work")
        self.write("facts.txt", FACTS)
        self.write("grades.md", GRADES)
        self.write("GUIDE.md", GUIDE)

    def write(self, name, text):
        (self.root / "work" / name).write_text(text, encoding="utf-8")

    def path(self, name):
        return str(self.root / "work" / name)

    def run_cli(self, *args, label="first"):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "coverage.py"), self.path("facts.txt"), self.path("grades.md"), self.path("GUIDE.md"), self.repo,
                            "--label", label, "--work", self.work, *(("--budget", str(BUDGET)) if "--budget" not in args else ()), *args], capture_output=True, text=True)
        return r


class FactsTest(Work):
    def test_a_well_formed_file_reads_with_ranges_and_skips_comments(self):
        facts = coverage.read_facts(self.path("facts.txt"), self.repo)
        self.assertEqual([f[0] for f in facts], ["F1", "F2", "F3", "F4", "F5"])
        self.assertEqual([f[1] for f in facts], [True, True, False, False, True])
        self.assertEqual(facts[2][4], "src/app.py:22-24")

    def test_a_row_of_another_shape_is_refused_with_its_line(self):
        self.write("facts.txt", FACTS + "F6 | big | setting | a fact | src/app.py:2\n")
        with self.assertRaisesRegex(coverage.CoverageError, r"facts.txt:7: not a fact row"):
            coverage.read_facts(self.path("facts.txt"), self.repo)

    def test_an_unknown_kind_is_refused(self):
        self.write("facts.txt", "F1 | core | feeling | a fact | src/app.py:2\n")
        with self.assertRaisesRegex(coverage.CoverageError, "not a fact row"):
            coverage.read_facts(self.path("facts.txt"), self.repo)

    def test_a_repeated_id_is_refused(self):
        self.write("facts.txt", FACTS + "F1 | detail | flow | again | src/app.py:2\n")
        with self.assertRaisesRegex(coverage.CoverageError, "F1 is on two rows"):
            coverage.read_facts(self.path("facts.txt"), self.repo)

    def test_a_cite_to_a_file_the_repo_lacks_or_past_its_end_is_refused(self):
        for bad in ("src/nope.py:2", "src/app.py:41", "src/app.py:30-99", "src/app.py:9-3"):
            self.write("facts.txt", "F1 | core | purpose | a fact | %s\n" % bad)
            with self.assertRaisesRegex(coverage.CoverageError, "invented the place", msg=bad):
                coverage.read_facts(self.path("facts.txt"), self.repo)

    def test_the_last_line_of_a_file_is_a_real_line(self):
        self.write("facts.txt", "F1 | core | purpose | a fact | src/app.py:40\n")
        self.assertEqual(len(coverage.read_facts(self.path("facts.txt"), self.repo)), 1)

    def test_an_empty_file_is_refused(self):
        self.write("facts.txt", "# nothing\n")
        with self.assertRaisesRegex(coverage.CoverageError, "holds no fact"):
            coverage.read_facts(self.path("facts.txt"), self.repo)

    def test_facts_only_mode_counts_and_refuses(self):
        run = lambda: subprocess.run([sys.executable, "-I", str(SCRIPTS / "coverage.py"), "--facts", self.path("facts.txt"), self.repo], capture_output=True, text=True)
        r = run()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "5 facts, 3 core"))
        self.write("facts.txt", "F1 | core | purpose | a fact | src/nope.py:2\n")
        r = run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("invented", r.stderr)


class GradesTest(Work):
    def facts(self):
        return coverage.read_facts(self.path("facts.txt"), self.repo)

    def test_each_fact_needs_exactly_one_row(self):
        self.write("grades.md", GRADES.replace("F5 | MISSING | -\n", ""))
        with self.assertRaisesRegex(coverage.CoverageError, "no row for: F5"):
            coverage.read_grades(self.path("grades.md"), self.facts())
        self.write("grades.md", GRADES + "F5 | MISSING | -\n")
        with self.assertRaisesRegex(coverage.CoverageError, "F5 has two rows"):
            coverage.read_grades(self.path("grades.md"), self.facts())

    def test_a_row_for_no_fact_is_refused(self):
        self.write("grades.md", GRADES + "F9 | MISSING | -\n")
        with self.assertRaisesRegex(coverage.CoverageError, "F9 is not in the facts file"):
            coverage.read_grades(self.path("grades.md"), self.facts())

    def test_prose_around_the_rows_is_ignored_and_the_quote_marks_come_off(self):
        self.write("grades.md", "Here are my grades:\n\n" + GRADES + "\nDone.\n")
        got = coverage.read_grades(self.path("grades.md"), self.facts())
        self.assertEqual(got["F1"], ("COVERED", ["It syncs your notes to a server."]))


class VerifyTest(Work):
    def graded(self, text, guide=GUIDE):
        facts = coverage.read_facts(self.path("facts.txt"), self.repo)
        self.write("grades.md", text)
        return coverage.verify(coverage.read_grades(self.path("grades.md"), facts), guide)

    def test_a_quote_found_in_the_guide_keeps_its_grade_and_says_where(self):
        got = self.graded(GRADES)
        self.assertEqual(got["F1"][:1] + got["F1"][2:3], ("COVERED", "part1"))
        self.assertEqual(got["F2"][0], "PARTIAL")
        self.assertEqual(got["F2"][2], "appendix")
        self.assertEqual(got["F4"][2], "appendix")

    def test_a_quote_with_the_tag_citation_or_spacing_of_the_guide_still_matches(self):
        got = self.graded(GRADES.replace('"A refused connection is retried 3 times."', '"A  refused connection is retried 3 times. `src/net.py:7` [A4.cccc]"').replace("`src/net.py:7`", ""))
        self.assertEqual(got["F4"][0], "COVERED")

    def test_a_quote_not_in_the_guide_counts_as_missing_and_says_why(self):
        got = self.graded(GRADES.replace("retried 3 times", "retried five times"))
        self.assertEqual(got["F4"][0], "MISSING")
        self.assertIn("not in the guide", got["F4"][3])

    def test_a_covered_row_with_no_quote_counts_as_missing(self):
        got = self.graded(GRADES.replace('F1 | COVERED | "It syncs your notes to a server."', "F1 | COVERED | -"))
        self.assertEqual(got["F1"][0], "MISSING")
        self.assertIn("no quote", got["F1"][3])

    def test_a_note_after_the_closing_quote_is_not_part_of_the_quote(self):
        """The grader brief allows `"line" (the value differs: 60 seconds)`: the row keeps its PARTIAL grade and its quote."""
        got = self.graded(GRADES.replace('"The sync interval is set in the settings."', '"The sync interval is set in the settings." (the value differs: 60 seconds)'))
        self.assertEqual((got["F2"][0], got["F2"][1], got["F2"][3]), ("PARTIAL", ["The sync interval is set in the settings."], ""))

    def test_a_quote_that_holds_quote_marks_of_its_own_keeps_them_up_to_the_last_mark(self):
        guide = GUIDE.replace("The sync interval is set in the settings.", 'The setting "interval" is set in the settings.')
        got = self.graded(GRADES.replace('"The sync interval is set in the settings."', '"The setting "interval" is set in the settings." (no value)'), guide)
        self.assertEqual(got["F2"][0], "PARTIAL")

    def test_a_quote_that_leaves_out_a_citation_in_the_middle_of_the_line_matches(self):
        guide = GUIDE.replace("A refused connection is retried 3 times. `src/net.py:7` [A4.cccc]", "A refused connection `src/net.py:7`, `src/app.py:2-4` is retried 3 times. [A4.cccc]")
        got = self.graded(GRADES, guide)
        self.assertEqual(got["F4"][0], "COVERED")
        got = self.graded(GRADES.replace('"A refused connection is retried 3 times."', '"A refused connection, and it is retried 3 times."'), guide.replace("`src/net.py:7`, `src/app.py:2-4` is", "`src/net.py:7`, and it is"))
        self.assertEqual(got["F4"][0], "COVERED")
        got = self.graded(GRADES.replace('"A refused connection is retried 3 times."', '"A refused connection `src/net.py:7`, `src/app.py:2-4` is retried 3 times."'), guide)
        self.assertEqual(got["F4"][0], "COVERED")

    def test_a_quote_that_is_only_in_part_2_is_not_part_1(self):
        got = self.graded(GRADES.replace("It syncs your notes to a server.", "The tool syncs notes to a server."))
        self.assertEqual(got["F1"][2], "appendix")


class BuildTest(Work):
    def rec(self, grades=GRADES, guide=GUIDE):
        self.write("grades.md", grades)
        facts = coverage.read_facts(self.path("facts.txt"), self.repo)
        return coverage.build(facts, coverage.read_grades(self.path("grades.md"), facts), guide, self.repo, BUDGET)

    def test_counts_rates_and_core_counts(self):
        rec = self.rec()
        self.assertEqual((rec["facts"], rec["covered"], rec["partial"], rec["missing"]), (5, 2, 1, 2))
        self.assertEqual((rec["covered_percent"], rec["covered_or_partial_percent"]), (40.0, 60.0))
        self.assertEqual((rec["core"], rec["core_covered"]), (3, 1))

    def test_a_downgraded_quote_lowers_the_covered_figure(self):
        self.assertEqual(self.rec(GRADES.replace("retried 3 times", "retried five times"))["covered"], 1)

    def test_part_1_words_are_counted_as_lint_main_counts_them(self):
        """One definition of Part 1 words: a guide whose Part 1 is one word over the cap fails lint_main's part1-words check, and coverage.py reports the same word count and a negative room."""
        part1 = " ".join(["word"] * (lint_main.WORDS_MAX + 1))
        guide = "# Part 1: In plain English\n\n## What it is\n\n%s\n\n# Part 2: Appendix: technical detail\n\n## A3 Whole\n\nThe tool syncs notes. `src/app.py:3` [A3.aaaa]\n" % part1
        rec = self.rec(guide=guide)
        fails, _ = lint_main.lint(guide, self.repo, [], [])
        said = [int(re.match(r"(\d+) words", d).group(1)) for _, kind, d in fails if kind == "part1-words"]
        self.assertEqual(said, [rec["part1_words"]])
        self.assertEqual(rec["part1_room"], lint_main.WORDS_MAX - said[0])
        self.assertLess(rec["part1_room"], 0)

    def test_a_fact_goes_to_the_section_that_cites_its_file_most_else_a3(self):
        by_file = coverage.sections(GUIDE, self.repo)
        self.assertEqual(coverage.suggest("src/net.py:9", by_file), "A4")
        self.assertEqual(coverage.suggest("src/app.py:30", by_file), "A3")  # A3 and A4 cite it once each: the lower number
        self.assertEqual(coverage.suggest("src/other.py:2", by_file), "A3")

    def test_a_file_cited_twice_in_a_section_goes_to_that_section(self):
        guide = GUIDE.replace("The sync interval is set in the settings. `src/app.py:10`", "The sync interval is set in the settings. `src/app.py:10` `src/app.py:12`")
        self.assertEqual(coverage.suggest("src/app.py:30", coverage.sections(guide, self.repo)), "A4")


class TodoTest(Work):
    def todo(self, grades=GRADES):
        self.write("grades.md", grades)
        facts = coverage.read_facts(self.path("facts.txt"), self.repo)
        rec = coverage.build(facts, coverage.read_grades(self.path("grades.md"), facts), GUIDE, self.repo, BUDGET)
        return coverage.todo_text("first", rec)

    def test_it_lists_each_partial_and_missing_fact_and_no_covered_one(self):
        text = self.todo()
        self.assertIn("3 of 5 facts to work", text)
        for fid in ("F2 PARTIAL", "F3 MISSING", "F5 MISSING"):
            self.assertIn(fid, text)
        self.assertNotIn("F1 COVERED", text)
        self.assertNotRegex(text, r"- F1 ")

    def test_a_partial_row_shows_the_guide_line_it_improves_and_the_code_line(self):
        text = self.todo()
        self.assertRegex(text, r"F2 PARTIAL core \| The sync interval defaults to 30 seconds\. \| code: `src/app\.py:10` \| guide has: \"The sync interval is set in the settings\.\"")

    def test_a_downgraded_row_says_why(self):
        text = self.todo(GRADES.replace("retried 3 times", "retried five times"))
        self.assertRegex(text, r"F4 MISSING detail .*graded COVERED but the quote is not in the guide")

    def test_core_facts_are_listed_again_for_part_1_with_the_room_left(self):
        text = self.todo()
        part1 = text.split("## Part 1 (core facts)")[1]
        self.assertRegex(part1, r"Part 1 holds \d+ of 1000 words: room \d+")
        self.assertIn("- F2 |", part1)
        self.assertIn("- F5 |", part1)
        self.assertNotIn("F3", part1)  # a detail fact stays in the appendix

    def test_with_every_core_fact_covered_part_1_says_none(self):
        text = self.todo(GRADES.replace('F2 | PARTIAL | "The sync interval is set in the settings."', 'F2 | COVERED | "The sync interval is set in the settings."').replace("F5 | MISSING | -", 'F5 | COVERED | "It syncs your notes to a server."'))
        self.assertIn("none: no core fact is left to add", text)

    def test_each_section_lists_the_files_its_facts_cite_for_the_writers_brief(self):
        text = self.todo()
        self.assertRegex(text, r"## A3\nFiles: src/app\.py\n- F5")
        self.assertRegex(text, r"## A4\nFiles: src/app\.py\n- F2")
        self.assertIn("`cov-A<n>.md`", text)

    def test_the_rows_are_grouped_under_their_section_in_order(self):
        text = self.todo()
        self.assertLess(text.index("## A3"), text.index("## Part 1"))


class RecordTest(Work):
    def test_a_label_writes_json_todo_and_a_row_in_the_log(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = json.loads(Path(self.path("coverage-first.json")).read_text())
        self.assertEqual((rec["covered"], rec["partial"], rec["missing"]), (2, 1, 2))
        self.assertTrue(Path(self.path("coverage-first.todo.md")).is_file())
        log = Path(self.path("coverage.md")).read_text().splitlines()
        self.assertEqual(log[2], "| first | 5 | 2 | 1 | 2 | 40.0 | 60.0 | 1 of 3 | %d |" % rec["part1_words"])

    def test_the_second_label_adds_a_row_and_leaves_the_first_record_alone(self):
        self.run_cli()
        before = Path(self.path("coverage-first.json")).read_text()
        self.write("grades.md", GRADES.replace("F3 | MISSING | -", 'F3 | COVERED | "The sync interval is set in the settings."'))
        r = self.run_cli(label="repair")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(Path(self.path("coverage-first.json")).read_text(), before)
        rows = Path(self.path("coverage.md")).read_text().splitlines()
        self.assertEqual([l.split(" | ")[0] for l in rows[2:]], ["| first", "| repair"])

    def test_a_label_already_recorded_is_refused_and_nothing_changes(self):
        self.run_cli()
        before = Path(self.path("coverage-first.json")).read_text(), Path(self.path("coverage.md")).read_text()
        self.write("grades.md", GRADES.replace("F5 | MISSING | -", 'F5 | COVERED | "It syncs your notes to a server."'))
        r = self.run_cli()
        self.assertEqual(r.returncode, 1)
        self.assertIn("already recorded", r.stderr)
        self.assertEqual((Path(self.path("coverage-first.json")).read_text(), Path(self.path("coverage.md")).read_text()), before)

    def test_min_fails_below_and_passes_at_or_above_after_writing_the_files(self):
        r = self.run_cli("--min", "98")
        self.assertEqual(r.returncode, 1)
        self.assertIn("BELOW 98%: 3 facts are still not covered", r.stdout)
        self.assertTrue(Path(self.path("coverage-first.json")).is_file())
        every = "\n".join('F%d | COVERED | "It syncs your notes to a server."' % i for i in range(1, 6)) + "\n"
        self.write("grades.md", every)
        r = self.run_cli("--min", "100", label="final")
        self.assertEqual((r.returncode, r.stdout.count("BELOW")), (0, 0), r.stderr)

    def test_a_malformed_file_exits_1_and_writes_nothing(self):
        self.write("grades.md", GRADES.replace("F5 | MISSING | -\n", ""))
        r = self.run_cli()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(sorted(os.listdir(self.work)), ["GUIDE.md", "facts.txt", "grades.md"])

    def test_bad_usage_exits_2(self):
        for args in (("--label", "Bad Label"), ("--min", "lots")):
            r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "coverage.py"), self.path("facts.txt"), self.path("grades.md"), self.path("GUIDE.md"), self.repo,
                                "--work", self.work, *(args if args[0] == "--label" else ("--label", "x") + args)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, args)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "coverage.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)

    def test_the_summary_line_names_the_label_the_counts_and_the_part_1_words(self):
        r = self.run_cli()
        self.assertRegex(r.stdout, r"^first: 5 facts, covered 2, partial 1, missing 2: 40\.0% covered, 60\.0% covered or partial; core 1 of 3 covered; Part 1 \d+ of 1000 words")


if __name__ == "__main__":
    unittest.main()
