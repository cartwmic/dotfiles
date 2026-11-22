"""The fix round of the extend mode: check_citations.py (row budget, one sentence a line, duplicate lines, numbers across `_`, `,` and k/M), coverage.py (placement),
inventory.py and final_recheck.py (re-check routing). Each test breaks one rule and fails without its change.
Run: python3 -I tests/deriving-readable-docs/test_extend_fixes.py"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True
import coverage  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_final_recheck as base  # noqa: E402
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


class NumberFormTest(unittest.TestCase):
    """F4: a number is the same number in digits with `_` or `,` between the groups, and with the words thousand and million."""

    def passes(self, sentence, code_line):
        code, out = check("## A4 Limits\n\n%s `src/a.ts:1`\n" % sentence, {"src/a.ts": code_line + "\n"})
        return code == 0, out

    def test_groups_with_commas_or_underscores_are_one_number_across_more_than_one_group(self):
        for sentence, line in (("It caps at 1,000,000 rows.", "const CAP = 1_000_000;"), ("It caps at 1_000_000 rows.", "const CAP = 1_000_000;"),
                               ("It caps at 1000000 rows.", "const CAP = 1,000,000;"), ("It caps at 2,000,000,000 rows.", "const CAP = 2_000_000_000;"),
                               ("It caps at 900,000 rows.", "const CAP = 900_000;")):
            ok, out = self.passes(sentence, line)
            self.assertTrue(ok, "%s | %s | %s" % (sentence, line, out))

    def test_a_number_followed_by_thousand_or_million_matches_its_digits(self):
        for sentence, line in (("It caps at 2 million rows.", "const CAP = 2_000_000;"), ("It caps at 1.5 million rows.", "const CAP = 1_500_000;"),
                               ("It caps at 1.1 million rows.", "const CAP = 1_100_000;"), ("It caps at 5 thousand rows.", "const CAP = 5000;"), ("It caps at 900 thousand rows.", "const CAP = 900_000;")):
            ok, out = self.passes(sentence, line)
            self.assertTrue(ok, "%s | %s | %s" % (sentence, line, out))

    def test_a_wrong_number_still_fails_and_a_bare_900_is_not_900_thousand(self):
        for sentence, line in (("It caps at 3 million rows.", "const CAP = 2_000_000;"), ("It caps at 900 rows.", "const CAP = 900_000;"),
                               ("It caps at 1,000,000 rows.", "const CAP = 1_000_001;")):
            ok, out = self.passes(sentence, line)
            self.assertFalse(ok, "%s | %s" % (sentence, line))
            self.assertIn("FAIL number", out)

    def test_a_k_or_m_suffix_is_not_a_number_the_check_reads(self):
        self.assertTrue(self.passes("It reads 4k bytes at a time.", "const BLOCK = 4096;")[0])


PLACE_GUIDE = """# Part 1: In plain English

## What it is

It syncs notes. [A3.aaaa]

# Part 2: Appendix: technical detail

## A3 Whole product

The tool syncs notes. `src/app.py:1` [A3.aaaa]

## A4 Networking

A refused connection is retried. `src/net/retry.py:1` [A4.bbbb]

## A5 Screens

The list view shows notes. `ui/view/list.py:1` [A5.cccc]
"""


class PlacementTest(unittest.TestCase):
    """F6: a MISSING fact whose file no line cites goes to the section whose cited files share the longest path prefix with it, not to A3."""

    def section_of(self, cite):
        files = {"src/app.py": "x\n", "src/net/retry.py": "x\n", "ui/view/list.py": "x\n", "src/net/tcp.py": "x\n" * 9, "ui/view/detail.py": "x\n" * 9,
                 "ui/menu.py": "x\n" * 9, "tools/make.py": "x\n" * 9}
        with make_repo(files) as repo:
            rec = coverage.build([("F1", False, "failure", "A fact.", cite)], {"F1": ("MISSING", [])}, PLACE_GUIDE, repo, grow=1500)
        return rec["rows"][0]["section"]

    def test_the_section_with_the_longest_shared_path_prefix_wins(self):
        self.assertEqual(self.section_of("src/net/tcp.py:3"), "A4")  # src/net/ beats src/
        self.assertEqual(self.section_of("ui/view/detail.py:3"), "A5")

    def test_a_shorter_shared_prefix_still_beats_the_fallback(self):
        self.assertEqual(self.section_of("ui/menu.py:3"), "A5")

    def test_a_fact_that_shares_no_folder_with_any_cited_file_goes_to_a3(self):
        self.assertEqual(self.section_of("tools/make.py:3"), "A3")

    def test_a_fact_whose_own_file_is_cited_keeps_the_section_that_cites_it_most(self):
        self.assertEqual(self.section_of("src/net/retry.py:1"), "A4")


class RecheckRoutingTest(unittest.TestCase):
    """F2: in an extend pass every failure of a claim the pass wrote goes to repair first, for two tries, then to the cut; a claim the pass did not touch is reported and left alone."""
    G = base.GUIDE
    SAVES, STOPS, LISTS = [base.line_of(base.GUIDE, n) for n in ("It saves a note.", "It stops after 5", "It lists notes. `")]

    def n(self, line):
        return "%d.1" % line

    def report(self, rows, findings=()):
        return "Slice: slice-1\n" + "".join("read | %s | %s | src/cli.py:3\n" % r for r in rows) + "".join(f + "\n" for f in findings)

    def run_step(self, mode, report, ids, *extra, guide=None, was=None):
        with base.Work() as w:
            w.write("GUIDE.md", guide or self.G)
            w.write("OLD.md", was or self.G)
            w.write("ids.txt", "\n".join(ids) + "\n")
            w.write("rep/slice-1.md", report)
            code, out, err = base.script(mode, w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), "--out", w.p("fix.txt"), *extra) if mode == "repair" else \
                base.script(mode, w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), *extra)
            fix = (w.dir / "fix.txt").read_text().split() if (w.dir / "fix.txt").exists() else None
            return code, out, err, fix, (w.dir / "GUIDE.md").read_text()

    def six_causes(self):
        causes = ("MISSING_CONDITION", "NAME", "COUNT", "KIND", "OTHER")
        a = [base.line_of(self.G, x) for x in ("It saves a note.", "It stops after 5", "It lists notes. `", "It sorts notes by date. `", "Notes saves notes. `")]
        ids = [self.n(i) for i in a]
        finds = ["%s | OVERSTATED | %s | words | the code | fix" % (i, c) for i, c in zip(ids, causes)]
        return ids, self.report([(i, "OVERSTATED") for i in ids], finds)

    def test_every_cause_and_a_failure_with_no_finding_is_to_fix_on_try_1_and_try_2(self):
        ids, rep = self.six_causes()
        extra = self.n(base.line_of(self.G, "You can keep 5 notes a day."))
        ids.append(extra)
        rep += "read | %s | WRONG | src/cli.py:3\n" % extra  # a failing claim with no finding row at all
        for tries in ("1", "2"):
            code, out, err, fix, _ = self.run_step("repair", rep, ids, "--try", tries)
            self.assertEqual(code, 0, err)
            self.assertEqual(sorted(fix), sorted(ids), tries)
            self.assertIn("6 to fix once, 0 to cut, 0 hold", out)

    def test_try_3_is_the_cut_and_every_failure_is_listed_as_cut(self):
        ids, rep = self.six_causes()
        code, out, err, fix, _ = self.run_step("repair", rep, ids, "--try", "3")
        self.assertEqual((code, fix), (0, []), err)
        self.assertEqual(out.count("cut | "), 5)
        self.assertNotIn("fix | ", out)

    def test_without_try_the_old_routing_stands(self):
        ids, rep = self.six_causes()
        self.assertEqual(self.run_step("repair", rep, ids)[3], ids[:3])

    def test_a_failure_on_a_line_the_pass_changed_is_routed_though_the_ids_file_lacks_it(self):
        new = self.G.replace("It lists notes. `src/cli.py:3`", "It lists all notes. `src/cli.py:3`")
        lists, saves = self.n(base.line_of(new, "It lists all notes.")), self.n(base.line_of(new, "It saves a note."))
        rep = self.report([(lists, "OVERSTATED"), (saves, "HOLDS")], ["%s | OVERSTATED | KIND | lists | the code | fix" % lists])
        with base.Work() as w:
            w.write("GUIDE.md", new)
            w.write("OLD.md", self.G)
            w.write("ids.txt", saves + "\n")
            w.write("rep/slice-1.md", rep)
            args = (w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), "--was", w.p("OLD.md"))
            code, out, err = base.script("repair", *args, "--try", "1", "--out", w.p("fix.txt"))
            self.assertEqual(code, 0, err)
            self.assertEqual((w.dir / "fix.txt").read_text().split(), [lists])
            code, out, err = base.script("cut", *args)
            self.assertEqual(code, 0, err)
            after = (w.dir / "GUIDE.md").read_text()
            self.assertNotIn("It lists all notes.", after)
            self.assertIn("It saves a note.", after)

    def test_a_failure_on_a_line_that_is_as_the_old_guide_has_it_is_reported_and_left_alone(self):
        lists, saves = self.n(self.LISTS), self.n(self.SAVES)
        rep = self.report([(lists, "WRONG"), (saves, "HOLDS")], ["%s | WRONG | KIND | lists | the code | cut" % lists])
        with base.Work() as w:
            w.write("GUIDE.md", self.G)
            w.write("OLD.md", self.G)
            w.write("ids.txt", saves + "\n")
            w.write("rep/slice-1.md", rep)
            args = (w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), "--was", w.p("OLD.md"))
            code, out, err = base.script("repair", *args, "--try", "1", "--out", w.p("fix.txt"))
            self.assertEqual((code, (w.dir / "fix.txt").read_text()), (0, ""), err)
            self.assertIn("unchanged | %s | WRONG | It lists notes." % lists, out)
            code, out, err = base.script("cut", *args)
            self.assertEqual(code, 0, err)
            self.assertIn("unchanged | %s | WRONG | It lists notes." % lists, out)
            self.assertEqual((w.dir / "GUIDE.md").read_text(), self.G)

    def test_skip_takes_the_held_files_of_every_round(self):
        with base.Work() as w:
            old = self.G
            new = old.replace("It saves a note.", "It saves a note fast.").replace("It lists notes. `", "It lists notes well. `")
            w.write("GUIDE.md", new)
            w.write("OLD.md", old)
            saves, lists = self.n(base.line_of(new, "It saves a note fast.")), self.n(base.line_of(new, "It lists notes well."))
            w.write("ids.txt", saves + "\n" + lists + "\n")
            held = []
            for i, cid in enumerate((saves, lists)):
                w.write("rep/slice-1.md", self.report([(cid, "HOLDS")]))
                w.write("only%d.txt" % i, cid + "\n")
                code, _, err = base.script("cut", w.p("GUIDE.md"), w.dir, "--ids", w.p("only%d.txt" % i), "--reports", w.p("rep"), "--held-out", w.p("held%d.txt" % i))
                self.assertEqual(code, 0, err)
                held += ["--skip", w.p("held%d.txt" % i)]
            code, out, err = base.script("changed", w.p("GUIDE.md"), w.dir, "--was", w.p("OLD.md"), *held, "--out", w.p("changed.txt"))
            self.assertEqual(code, 0, err)
            self.assertEqual((w.dir / "changed.txt").read_text().split(), [])

    def test_try_and_was_need_their_values(self):
        for bad in (("--try", "0"), ("--try", "two"), ("--was", "/no/such/file.md")):
            ids, rep = self.six_causes()
            self.assertEqual(self.run_step("repair", rep, ids, *bad)[0], 2, bad)

    def test_e7_names_the_flags_the_script_takes_and_the_two_tries(self):
        step = EXTEND.split("## E7")[1].split("## E8")[0]
        source = (SCRIPTS / "final_recheck.py").read_text()
        for flag in ("--try 1", "--try 2", "--was GUIDE.was.md"):
            self.assertIn(flag, step)
        for flag in {f for cmd in __import__("re").findall(r"`(python3 -I [^`]*final_recheck\.py[^`]*)`", step) for f in __import__("re").findall(r"(?<![\w-])(--?[a-z][a-z-]*)", cmd.split("final_recheck.py", 1)[1])}:
            self.assertIn(flag, source, flag)
        self.assertNotRegex(step, r"(?i)cause MISSING_CONDITION, NAME or COUNT is `fix`")


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
