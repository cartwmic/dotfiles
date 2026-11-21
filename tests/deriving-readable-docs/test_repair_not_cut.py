"""Step 15 repairs before it cuts: a claim that fails for a missing condition, a name or a count gets one fix and one re-check; a cut that leaves Part 1 failing lint_main
is fixed once or dropped whole, and never leaves the shipped guide failing it.
Run: python3 -I tests/deriving-readable-docs/test_repair_not_cut.py"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import test_final_recheck as base  # noqa: E402

sys.path.insert(0, str(base.SCRIPTS))
import lint_main  # noqa: E402

script, Work, line_of, SKILL, FIX_ROUNDS = base.script, base.Work, base.line_of, base.SKILL, base.FIX_ROUNDS

GUIDE = """# Part 1: In plain English

## What it is

Notes saves notes. [A3.0001]
Who it is for: people who take notes. [A3.0001]

## How to start

Run the add command to save a note. [A4.0001]

## What you can do

You can keep 5 notes a day unless the limit is raised. [A4.0002] [A4.0005]
You can list notes. [A4.0003]

# Part 2: Appendix

## A3 The product

Notes saves notes. `src/cli.py:1` [A3.0001]

## A4 Adding

It saves a note. `src/cli.py:3` [A4.0001]
It stops after 5 notes. `src/cli.py:7` [A4.0002]
It lists notes. `src/cli.py:3` [A4.0003]
It stops unless the limit is raised. `src/cli.py:8` [A4.0005]
"""


def lint(text, repo):
    return [(k, d) for _, k, d in lint_main.lint(text, str(repo), [], [])[0]]


def ids_of(text, *needles):
    return ["%d.1" % line_of(text, n) for n in needles]


class RepairListTest(unittest.TestCase):
    def repair(self, report, ids, guide=GUIDE):
        with Work() as w:
            w.write("GUIDE.md", guide)
            w.write("ids.txt", "\n".join(ids) + "\n")
            w.write("rep/slice-1.md", report)
            code, out, err = script("repair", w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), "--out", w.p("repair.txt"))
            return code, out, err, (w.dir / "repair.txt").read_text().split() if (w.dir / "repair.txt").exists() else None

    def report(self, rows, findings):
        return "Slice: slice-1\n" + "".join("read | %s | %s | src/cli.py:3\n" % r for r in rows) + "".join(f + "\n" for f in findings)

    def test_a_missing_condition_a_name_or_a_count_is_to_fix_and_any_other_cause_is_to_cut(self):
        a, b, c = (line_of(GUIDE, "It saves a note."), line_of(GUIDE, "It stops after 5"), line_of(GUIDE, "It lists notes. `"))
        rep = self.report([("%d.1" % a, "OVERSTATED"), ("%d.1" % b, "WRONG"), ("%d.1" % c, "UNSUPPORTED")],
                          ["%d.1 | OVERSTATED | MISSING_CONDITION | saves | the code skips empty notes (src/cli.py:3) | add it" % a,
                           "%d.1 | WRONG | COUNT | 5 | the limit is 6 (src/cli.py:7) | say 6" % b,
                           "%d.1 | UNSUPPORTED | KIND | lists | it is a script step (src/cli.py:3) | cut" % c])
        code, out, err, fix = self.repair(rep, ["%d.1" % a, "%d.1" % b, "%d.1" % c])
        self.assertEqual(code, 0, err)
        self.assertEqual(fix, ["%d.1" % a, "%d.1" % b])
        self.assertRegex(out, r"fix \| %d\.1 \| OVERSTATED \| MISSING_CONDITION" % a)
        self.assertRegex(out, r"fix \| %d\.1 \| WRONG \| COUNT" % b)
        self.assertRegex(out, r"cut \| %d\.1 \| UNSUPPORTED \| KIND" % c)
        self.assertIn("2 to fix once, 1 to cut, 0 hold", out)

    def test_a_name_finding_is_to_fix_whatever_its_verdict(self):
        a = line_of(GUIDE, "It saves a note.")
        rep = self.report([("%d.1" % a, "UNSUPPORTED")], ["%d.1 | UNSUPPORTED | NAME | note | the name is x (src/cli.py:3) | rename" % a])
        self.assertEqual(self.repair(rep, ["%d.1" % a])[3], ["%d.1" % a])

    def test_a_finding_with_no_cause_named_is_to_cut(self):
        a = line_of(GUIDE, "It saves a note.")
        rep = self.report([("%d.1" % a, "WRONG")], ["%d.1 | WRONG | the code says otherwise" % a])
        code, out, _, fix = self.repair(rep, ["%d.1" % a])
        self.assertEqual((code, fix), (0, []))
        self.assertIn("cut | %d.1 | WRONG | none named" % a, out)

    def test_a_finding_keyed_by_a_bare_doc_line_names_the_claim_on_that_line(self):
        a = line_of(GUIDE, "It saves a note.")
        rep = self.report([("%d.1" % a, "OVERSTATED")], ["%d | OVERSTATED | MISSING_CONDITION | saves | skips empty | add it" % a])
        self.assertEqual(self.repair(rep, ["%d.1" % a])[3], ["%d.1" % a])

    def test_a_claim_that_holds_is_not_listed_and_a_claim_with_no_row_is_an_error(self):
        a = line_of(GUIDE, "It saves a note.")
        code, out, _, fix = self.repair(self.report([("%d.1" % a, "HOLDS")], []), ["%d.1" % a])
        self.assertEqual((code, fix), (0, []))
        self.assertIn("0 to fix once, 0 to cut, 1 hold", out)
        code, _, err, _ = self.repair(self.report([], []), ["%d.1" % a])
        self.assertEqual(code, 1)
        self.assertIn("no report row for", err)


class CutExceptTest(unittest.TestCase):
    def test_a_claim_named_by_except_is_not_cut_and_the_others_are(self):
        with Work() as w:
            a, b = line_of(GUIDE, "It saves a note."), line_of(GUIDE, "It lists notes. `")
            w.write("fix.txt", "%d.1\n" % a)
            code, out, err, after = w.cut(GUIDE, ["%d.1" % a, "%d.1" % b], {"%d.1" % a: "OVERSTATED", "%d.1" % b: "WRONG"}, "--except", w.p("fix.txt"))
            self.assertEqual(code, 0, err)
            self.assertIn("It saves a note.", after)
            self.assertNotIn("It lists notes.", after)

    def test_a_claim_named_by_except_still_needs_its_report_row(self):
        with Work() as w:
            a = line_of(GUIDE, "It saves a note.")
            w.write("fix.txt", "%d.1\n" % a)
            code, _, err, _ = w.cut(GUIDE, ["%d.1" % a], {}, "--except", w.p("fix.txt"))
            self.assertEqual(code, 1)
            self.assertIn("no report row for", err)


class FixThenRecheckThenCutTest(unittest.TestCase):
    """The step 15 order on a guide: cut what cannot be repaired, fix the rest once in place, re-check them, cut only what the re-check still fails."""

    def first_pass(self, w):
        a, c = line_of(GUIDE, "It stops after 5"), line_of(GUIDE, "It lists notes. `")
        w.write("GUIDE.md", GUIDE)
        w.write("ids.txt", "%d.1\n%d.1\n" % (a, c))
        w.write("rep/slice-1.md", "Slice: slice-1\nread | %d.1 | OVERSTATED | src/cli.py:7\nread | %d.1 | WRONG | src/cli.py:3\n"
                                  "%d.1 | OVERSTATED | MISSING_CONDITION | stops | the code has a flag | add it\n%d.1 | WRONG | KIND | lists | a script step | cut\n" % (a, c, a, c))
        script("repair", w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), "--out", w.p("repair.txt"))
        code, _, err = script("cut", w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), "--except", w.p("repair.txt"), "--clean")
        self.assertEqual(code, 0, err)
        return a

    def recheck(self, w, fixed_text, verdict):
        """Edit the line in place, list what changed against the post-cut copy, check it once and cut with the re-check's verdict."""
        cut1 = (w.dir / "GUIDE.md").read_text()
        w.write("GUIDE.cut1.md", cut1)
        w.write("GUIDE.md", cut1.replace("It stops after 5 notes.", fixed_text))
        code, out, err = script("changed", w.p("GUIDE.md"), w.dir, "--was", w.p("GUIDE.cut1.md"), "--out", w.p("changed2.txt"))
        self.assertEqual(code, 0, err)
        ids = (w.dir / "changed2.txt").read_text().split()
        (w.dir / "rep2").mkdir(exist_ok=True)
        w.write("rep2/slice-1.md", "Slice: slice-1\n" + "".join("read | %s | %s | src/cli.py:7\n" % (i, verdict) for i in ids))
        code, out, err = script("cut", w.p("GUIDE.md"), w.dir, "--ids", w.p("changed2.txt"), "--reports", w.p("rep2"), "--clean")
        self.assertEqual(code, 0, err)
        return ids, out, (w.dir / "GUIDE.md").read_text()

    def test_the_unrepairable_claim_is_cut_first_and_the_repairable_one_survives_for_its_fix(self):
        with Work() as w:
            self.first_pass(w)
            after = (w.dir / "GUIDE.md").read_text()
            self.assertNotIn("It lists notes. `", after)
            self.assertIn("It stops after 5 notes.", after)

    def test_a_fix_that_the_re_check_passes_stays_and_the_clean_copy_carries_it(self):
        with Work() as w:
            self.first_pass(w)
            ids, out, after = self.recheck(w, "It stops after 5 notes unless the flag is set.", "HOLDS")
            self.assertEqual(len(ids), 1)
            self.assertIn("all HOLD, nothing cut", out)
            self.assertIn("It stops after 5 notes unless the flag is set.", after)
            clean = (w.dir / "GUIDE.clean.md").read_text()
            self.assertIn("It stops after 5 notes unless the flag is set.", clean)
            self.assertNotIn("[A4.0002]", clean)

    def test_a_fix_that_the_re_check_still_fails_is_cut_then(self):
        with Work() as w:
            self.first_pass(w)
            _, out, after = self.recheck(w, "It stops after 5 notes unless the flag is set.", "OVERSTATED")
            self.assertIn("cut | ", out)
            self.assertNotIn("It stops after 5 notes", after)
            self.assertNotIn("It stops after 5 notes", (w.dir / "GUIDE.clean.md").read_text())


class CutThatLeavesPart1FailingTest(unittest.TestCase):
    """The run's failure: a cut left a Part 1 sentence with an `unless` no tagged line has, and lint_main failed on the shipped guide."""

    def test_the_fixture_passes_lint_main_before_the_cut(self):
        with Work() as w:
            self.assertEqual(lint(GUIDE, w.dir), [])

    def test_cutting_the_line_that_carried_the_unless_makes_lint_main_fail_and_a_drop_clears_it(self):
        with Work() as w:
            b = line_of(GUIDE, "It stops unless the limit is raised.")
            code, _, err, after = w.cut(GUIDE, ["%d.1" % b], {"%d.1" % b: "WRONG"})
            self.assertEqual(code, 0, err)
            failed = lint(after, w.dir)
            self.assertEqual([k for k, _ in failed], ["absolute"], failed)
            self.assertIn("unless", failed[0][1])
            sentence = line_of(after, "You can keep 5 notes a day unless")
            w.write("dropped.txt", "%d.1\n" % sentence)
            code, out, err = script("drop", w.p("GUIDE.md"), w.dir, "--ids", w.p("dropped.txt"), "--clean")
            self.assertEqual(code, 0, err)
            dropped = (w.dir / "GUIDE.md").read_text()
            self.assertNotIn("You can keep 5 notes", dropped)
            self.assertEqual(lint(dropped, w.dir), [])
            self.assertNotIn("You can keep 5 notes", (w.dir / "GUIDE.clean.md").read_text())

    def test_a_fix_in_place_that_states_the_condition_clears_it_without_a_drop(self):
        with Work() as w:
            b = line_of(GUIDE, "It stops unless the limit is raised.")
            _, _, _, after = w.cut(GUIDE, ["%d.1" % b], {"%d.1" % b: "WRONG"})
            fixed = after.replace("You can keep 5 notes a day unless the limit is raised.", "You can keep 5 notes a day.")
            self.assertEqual(lint(fixed, w.dir), [])


class DropTest(unittest.TestCase):
    def drop(self, w, guide, needle):
        w.write("GUIDE.md", guide)
        w.write("dropped.txt", "%d.1\n" % line_of(guide, needle))
        code, out, err = script("drop", w.p("GUIDE.md"), w.dir, "--ids", w.p("dropped.txt"))
        return code, out, err, (w.dir / "GUIDE.md").read_text()

    def test_it_refuses_the_who_it_is_for_sentence_and_changes_nothing(self):
        with Work() as w:
            code, _, err, after = self.drop(w, GUIDE, "Who it is for:")
            self.assertEqual(code, 1)
            self.assertIn("Who it is for sentence", err)
            self.assertEqual(after, GUIDE)

    def test_it_refuses_the_last_sentence_of_how_to_start(self):
        with Work() as w:
            code, _, err, after = self.drop(w, GUIDE, "Run the add command")
            self.assertEqual(code, 1)
            self.assertIn("last sentence of How to start", err)
            self.assertEqual(after, GUIDE)

    def test_it_drops_one_of_two_how_to_start_steps(self):
        two = GUIDE.replace("Run the add command to save a note. [A4.0001]", "Run the add command to save a note. [A4.0001]\nThen list them. [A4.0003]")
        with Work() as w:
            code, _, err, after = self.drop(w, two, "Then list them.")
            self.assertEqual(code, 0, err)
            self.assertNotIn("Then list them.", after)
            self.assertIn("Run the add command", after)

    def test_it_drops_an_ordinary_part_1_sentence_and_leaves_the_appendix_alone(self):
        with Work() as w:
            code, out, err, after = self.drop(w, GUIDE, "You can list notes.")
            self.assertEqual(code, 0, err)
            self.assertNotIn("You can list notes.", after)
            self.assertIn("It lists notes. `src/cli.py:3` [A4.0003]", after)

    def test_it_needs_an_ids_file(self):
        with Work() as w:
            w.write("GUIDE.md", GUIDE)
            self.assertEqual(script("drop", w.p("GUIDE.md"), w.dir)[0], 2)


class SkillWiringTest(unittest.TestCase):
    def step15(self):
        return SKILL.split("**Final re-check.**")[1].split("\n")[0]

    def test_step_15_repairs_once_re_checks_then_cuts_and_the_shipped_guide_passes_lint_main(self):
        step = self.step15()
        for word in ("repair", "one fix", "re-check", "lint_main.py", "drop"):
            self.assertIn(word, step)
        text = FIX_ROUNDS.split("## Final re-check")[1]
        order = [text.index(w) for w in ("final_recheck.py changed", "final_recheck.py repair", "cut GUIDE.md", "--except", "final_recheck.py changed", "final_recheck.py drop")]
        self.assertEqual(order[0], min(order))
        self.assertRegex(text, r"(?i)must pass `lint_main\.py`")
        self.assertRegex(text, r"(?i)one fix and one re-check before it may be cut")

    def test_every_flag_of_the_new_commands_exists_in_the_script(self):
        source = (base.SCRIPTS / "final_recheck.py").read_text()
        seen = 0
        for cmd in re.findall(r"`(python3 -I [^`]*final_recheck\.py[^`]*)`", SKILL + FIX_ROUNDS):
            for flag in re.findall(r"(?<![\w-])(--?[a-z][a-z-]*)", cmd.split("final_recheck.py", 1)[1]):
                self.assertIn(flag, source, flag)
                seen += 1
        self.assertGreater(seen, 12)


if __name__ == "__main__":
    unittest.main()
