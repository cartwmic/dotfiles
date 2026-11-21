"""The coverage to-do routes and fits: a PARTIAL fact is an edit of the line that holds it, a MISSING fact goes next to the nearest related line, and the to-do lists only what the word room holds.
Run: python3 -I tests/deriving-readable-docs/test_coverage_fit.py"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import test_coverage as base  # noqa: E402

coverage, SCRIPTS, SKILL_DIR = base.coverage, base.SCRIPTS, base.SKILL_DIR

# A4 holds three lines of src/app.py (5, 20 and a table row at 35); A3 holds one.
GUIDE = """# Part 1: In plain English

## What it is

It syncs your notes to a server. [A3.aaaa] The sync interval is set in the settings. [A4.bbbb]

# Part 2: Appendix: technical detail

## A3 Whole product

The tool syncs notes to a server. `src/app.py:3` [A3.aaaa]

## A4 Syncing

The sync interval is set in the settings. `src/app.py:10` [A4.bbbb]

Notes are read from the folder. `src/app.py:20` [A4.cccc]

A refused connection is retried 3 times. `src/net.py:7` [A4.dddd]

### Defaults and limits

| Setting or behaviour | Value | Unit | Cited |
|---|---|---|---|
| note size limit | 1 | MB | `src/app.py:35` [A4.eeee] |
"""
FACTS = """F1 | core | purpose | The tool syncs notes to a server. | src/app.py:3
F2 | core | setting | The sync interval defaults to 30 seconds. | src/app.py:10
F3 | detail | limit | A note over 1 MB is skipped. | src/app.py:36
F4 | detail | failure | A refused connection is retried 3 times. | src/net.py:7
F5 | core | run | Start it with the sync command. | src/app.py:22
F6 | detail | setting | The notes folder defaults to notes. | src/app.py:21
F7 | detail | flow | The server answers with a token. | src/other.py:2
"""
GRADES = """F1 | COVERED | "The tool syncs notes to a server."
F2 | PARTIAL | "The sync interval is set in the settings."
F3 | MISSING | -
F4 | COVERED | "A refused connection is retried 3 times."
F5 | MISSING | -
F6 | PARTIAL | "Notes are read from the folder."
F7 | MISSING | -
"""


class Fixture(base.Work):
    def setUp(self):
        super().setUp()
        (self.root / "repo/src/other.py").write_text("other 1\nother 2\n")
        self.write("facts.txt", FACTS)
        self.write("grades.md", GRADES)
        self.write("GUIDE.md", GUIDE)

    def rec(self, grades=GRADES, guide=GUIDE, budget=base.BUDGET, **kw):
        facts = coverage.read_facts(self.path("facts.txt"), self.repo)
        self.write("grades.md", grades)
        return coverage.build(facts, coverage.read_grades(self.path("grades.md"), facts), guide, self.repo, budget, **kw)

    def row(self, rec, fid):
        return next(r for r in rec["rows"] if r["id"] == fid)


class PartialIsAnEditTest(Fixture):
    def test_a_partial_fact_is_routed_to_the_line_that_holds_its_quote(self):
        rec = self.rec()
        f2 = self.row(rec, "F2")
        self.assertEqual((f2["section"], f2["line_id"], f2["route"]), ("A4", "A4.bbbb", "edit"))
        f6 = self.row(rec, "F6")
        self.assertEqual((f6["section"], f6["line_id"]), ("A4", "A4.cccc"))

    def test_the_section_is_the_one_the_line_sits_in_not_the_one_that_cites_its_file_most(self):
        """The file src/app.py is cited once by A3 and four times by A4's lines, but a PARTIAL quote that is A3's own line goes to A3."""
        grades = GRADES.replace('F2 | PARTIAL | "The sync interval is set in the settings."', 'F2 | PARTIAL | "The tool syncs notes to a server."')
        f2 = self.row(self.rec(grades), "F2")
        self.assertEqual((f2["section"], f2["line_id"]), ("A3", "A3.aaaa"))

    def test_the_to_do_says_edit_this_line_in_place_for_a_partial_fact_and_never_add(self):
        text = coverage.todo_text("first", self.rec())
        self.assertRegex(text, r"- F2 PARTIAL core \|.*\| edit line A4\.bbbb in place")
        self.assertNotRegex(text, r"- F2 PARTIAL[^\n]*add next to")

    def test_a_partial_quote_in_part_1_goes_to_the_appendix_line_its_sentence_is_tagged_with(self):
        guide = GUIDE.replace("It syncs your notes to a server. [A3.aaaa]", "It syncs your notes every thirty seconds. [A4.cccc] [A4.bbbb]")
        grades = GRADES.replace('F2 | PARTIAL | "The sync interval is set in the settings."', 'F2 | PARTIAL | "It syncs your notes every thirty seconds."')
        f2 = self.row(self.rec(grades, guide), "F2")
        self.assertEqual((f2["line_id"], f2["route"]), ("A4.cccc", "edit via Part 1"))
        self.assertIn("(the Part 1 sentence is tagged to it)", coverage.todo_text("first", self.rec(grades, guide)))

    def test_a_partial_quote_in_a_table_row_goes_to_the_row_id_and_the_file_it_came_from(self):
        grades = GRADES.replace('F3 | MISSING | -', 'F3 | PARTIAL | "note size limit | 1 | MB"')
        f3 = self.row(self.rec(grades), "F3")
        self.assertEqual((f3["section"], f3["line_id"]), ("A4", "A4.eeee"))

    def test_a_quote_no_one_line_holds_falls_back_and_says_the_routing_is_a_guess(self):
        guide = GUIDE.replace("The sync interval is set in the settings. `src/app.py:10` [A4.bbbb]", "The sync interval is set `src/app.py:10` [A4.bbbb]\n\nin the settings. `src/app.py:11` [A4.ffff]")
        guide = guide.replace(" The sync interval is set in the settings. [A4.bbbb]", "")  # Part 1 does not say it either
        f2 = self.row(self.rec(guide=guide), "F2")
        self.assertEqual((f2["route"], f2["line_id"]), ("guess", None))
        self.assertIn("the section is a guess", coverage.todo_text("first", self.rec(guide=guide)))

    def test_two_lines_that_hold_the_quote_go_to_the_one_citing_the_facts_file(self):
        guide = GUIDE + "\n## A5 More\n\nThe sync interval is set in the settings. `src/net.py:9` [A5.gggg]\n"
        f2 = self.row(self.rec(guide=guide), "F2")
        self.assertEqual(f2["line_id"], "A4.bbbb")


class MissingGoesNextToItsNeighbourTest(Fixture):
    def test_a_missing_fact_names_the_nearest_line_of_its_section_that_cites_the_file(self):
        rec = self.rec()
        f5 = self.row(rec, "F5")  # src/app.py:22: A4 cites 10, 20 and 35
        self.assertEqual((f5["section"], f5["route"], f5["near"][0]), ("A4", "add", "A4.cccc"))
        self.assertIn("add next to A4.cccc (cites `src/app.py:20`)", coverage.todo_text("first", rec))

    def test_a_neighbour_that_is_a_table_row_says_to_add_a_row(self):
        rec = self.rec(GRADES.replace("F5 | MISSING | -", 'F5 | COVERED | "The tool syncs notes to a server."'))
        f3 = self.row(rec, "F3")  # src/app.py:36 is next to the table row at 35
        self.assertEqual(f3["near"][0], "A4.eeee")
        self.assertIn("a table row, so add a row of its table", coverage.todo_text("first", rec))

    def test_a_missing_fact_in_a_file_no_line_of_its_section_cites_says_where_instead(self):
        rec = self.rec()
        f7 = self.row(rec, "F7")
        self.assertIsNone(f7["near"])
        self.assertIn("add after the last prose line of its section (no line of it cites this file)", coverage.todo_text("first", rec))


class RankAndFitTest(Fixture):
    def test_the_order_is_core_first_then_missing_before_partial_then_fact_number(self):
        self.assertEqual([r["id"] for r in coverage.rank(self.rec()["rows"])], ["F5", "F2", "F3", "F7", "F6"])

    def test_the_room_is_the_budget_less_the_words_check_citations_counts(self):
        path = self.path("GUIDE.md")
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), path, self.repo], capture_output=True, text=True)
        counted = int(re.search(r"(\d+) words\n", r.stdout).group(1))
        rec = self.rec(budget=counted + 130)
        self.assertEqual((rec["guide_words"], rec["room"]), (counted, 130))

    def test_the_to_do_lists_what_fits_at_the_stated_estimate_and_the_rest_did_not_fit(self):
        words = self.rec()["guide_words"]
        rec = self.rec(budget=words + 60)  # 60 words at 25 a fact: 2 facts
        self.assertEqual((rec["words_per_fact"], rec["fit"]), (25, 2))
        self.assertEqual((rec["todo"], rec["did_not_fit"]), (["F5", "F2"], ["F3", "F7", "F6"]))
        text = coverage.todo_text("first", rec)
        self.assertIn("2 of 7 facts to work, 3 did not fit", text)
        self.assertIn("Room: 60 words left of the %d-word budget" % (words + 60), text)
        self.assertIn("at 25 words a fact", text)
        listed, left = text.split("## Did not fit")
        for fid in ("F3", "F6", "F7"):
            self.assertNotIn("- %s " % fid, listed)
            self.assertIn("- %s " % fid, left)

    def test_a_core_fact_that_did_not_fit_gets_no_part_1_candidate(self):
        words = self.rec()["guide_words"]
        text = coverage.todo_text("first", self.rec(budget=words + 30))  # one fact: F5
        part1 = text.split("## Part 1 (core facts)")[1].split("## Did not fit")[0]
        self.assertIn("- F5 |", part1)
        self.assertNotIn("- F2 |", part1)

    def test_the_estimate_is_an_option(self):
        words = self.rec()["guide_words"]
        self.assertEqual(self.rec(budget=words + 60, words_per_fact=10)["fit"], 6)

    def test_no_room_lists_nothing_and_an_over_budget_guide_does_not_crash(self):
        words = self.rec()["guide_words"]
        for budget in (words, words - 500):
            rec = self.rec(budget=budget)
            self.assertEqual((rec["fit"], rec["todo"]), (0, []))
            self.assertEqual(len(rec["did_not_fit"]), 5)
            self.assertIn("0 of 7 facts to work, 5 did not fit", coverage.todo_text("first", rec))

    def test_the_json_record_holds_the_room_and_each_rows_listed_flag(self):
        words = self.rec()["guide_words"]
        self.run_cli("--budget", str(words + 30))
        rec = json.loads(Path(self.path("coverage-first.json")).read_text())
        self.assertEqual((rec["room"], rec["todo"]), (30, ["F5"]))
        self.assertEqual([r["id"] for r in rec["rows"] if r["listed"]], ["F5"])


class TheLogKeepsItsTableTest(Fixture):
    def log(self):
        return Path(self.path("coverage.md")).read_text().splitlines()

    def test_facts_that_did_not_fit_are_listed_in_coverage_md_under_their_label(self):
        words = self.rec()["guide_words"]
        r = self.run_cli("--budget", str(words + 60))
        self.assertEqual(r.returncode, 0, r.stderr)
        text = "\n".join(self.log())
        self.assertIn("## Did not fit (first)", text)
        self.assertRegex(text, r"- F3 MISSING detail \| A note over 1 MB is skipped\. \| code: `src/app\.py:36`")
        self.assertRegex(r.stdout, r"to-do 2 facts, 3 did not fit \(room 60 words\)")

    def test_the_next_label_row_still_lands_inside_the_table_after_a_list_was_written(self):
        words = self.rec()["guide_words"]
        self.run_cli("--budget", str(words + 60))
        r = self.run_cli("--budget", str(words + 60), label="repair")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = self.log()
        table = [l for l in lines if l.startswith("|")]
        self.assertEqual([l.split(" | ")[0] for l in table][2:], ["| first", "| repair"])
        self.assertEqual(lines.index(table[-1]), len(table) - 1)  # the table is one block at the top
        self.assertEqual(sum(1 for l in lines if l.startswith("## Did not fit")), 2)

    def test_with_everything_fitting_the_log_is_the_table_alone(self):
        self.run_cli()
        self.assertTrue(all(l.startswith("|") for l in self.log()))


class FactsCapTest(base.Work):
    def facts(self, n):
        return "".join("F%d | detail | purpose | fact %d | src/app.py:%d\n" % (i, i, (i % 40) + 1) for i in range(1, n + 1))

    def test_a_list_of_100_reads_and_101_is_sent_back(self):
        self.write("facts.txt", self.facts(100))
        self.assertEqual(len(coverage.read_facts(self.path("facts.txt"), self.repo)), 100)
        self.write("facts.txt", self.facts(101))
        with self.assertRaisesRegex(coverage.CoverageError, "101 facts, over the cap of 100"):
            coverage.read_facts(self.path("facts.txt"), self.repo)

    def test_facts_only_mode_refuses_101_and_the_lister_brief_says_100(self):
        self.write("facts.txt", self.facts(101))
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "coverage.py"), "--facts", self.path("facts.txt"), self.repo], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn("over the cap of 100", r.stderr)
        lister = (SKILL_DIR / "references/coverage-lister.md").read_text(encoding="utf-8")
        self.assertRegex(lister, r"at most 100 rows")
        self.assertNotIn("120", lister)


class UsageTest(Fixture):
    def test_the_budget_is_required_and_must_be_a_positive_whole_number(self):
        run = lambda *extra: subprocess.run([sys.executable, "-I", str(SCRIPTS / "coverage.py"), self.path("facts.txt"), self.path("grades.md"), self.path("GUIDE.md"), self.repo,
                                             "--label", "x", "--work", self.work, *extra], capture_output=True, text=True)
        for extra in ((), ("--budget", "lots"), ("--budget", "0"), ("--budget", "7000", "--words-per-fact", "0")):
            self.assertEqual(run(*extra).returncode, 2, extra)
        self.assertEqual(run("--budget", "7000").returncode, 0)


if __name__ == "__main__":
    unittest.main()
