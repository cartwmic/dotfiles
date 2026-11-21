"""The closing step of the general skill (final_recheck.py): list what changed after the last checker report, and cut what the fresh check does not pass.
Each test breaks one rule and fails without its change.
Run: python3 -I tests/deriving-readable-docs/test_final_recheck.py"""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"
SKILL_DIR = SCRIPTS.parent
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
FIX_ROUNDS = (SKILL_DIR / "references/fix-rounds.md").read_text(encoding="utf-8")
READER = (SKILL_DIR / "references/reader-check.md").read_text(encoding="utf-8")

PART1 = """# Part 1: In plain English

## What it is

Notes saves notes. [A3.0001]
Who it is for: people who take notes. [A3.0001]

## How to start

Run `notes add` to save a note. [A4.0001]

## What you can do

You can keep 5 notes a day. [A4.0002]
You can list notes. [A4.0003] It sorts them by date. [A4.0004]
Notes can be listed and pinned. [A4.0003] [A4.0004]
- You can pin a note. [A4.0004]
"""
APPENDIX = """
# Part 2: Appendix

## A3 The product

Notes saves notes. `src/cli.py:1` [A3.0001]

## A4 Adding

It saves a note. `src/cli.py:3` [A4.0001]
It stops after 5 notes. `src/cli.py:7` [A4.0002]
It lists notes. `src/cli.py:3` [A4.0003]
It sorts notes by date. `src/cli.py:5` [A4.0004]
"""
GUIDE = PART1 + APPENDIX


def script(*args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "final_recheck.py"), *map(str, args)], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def line_of(text, needle):
    return next(n for n, l in enumerate(text.split("\n"), 1) if needle in l)


class Work(tempfile.TemporaryDirectory):
    """A repo with src/cli.py and a folder for the guide, its old copy, ids and reports."""

    def __enter__(self):
        d = Path(super().__enter__())
        (d / "src").mkdir()
        (d / "src/cli.py").write_text("x\n" * 10)
        (d / "rep").mkdir()
        self.dir = d
        return self

    def write(self, name, text):
        (self.dir / name).write_text(text)
        return str(self.dir / name)

    def p(self, name):
        return str(self.dir / name)

    def changed(self, new, old):
        self.write("GUIDE.md", new)
        self.write("OLD.md", old)
        code, out, err = script("changed", self.p("GUIDE.md"), self.dir, "--was", self.p("OLD.md"), "--out", self.p("changed.txt"))
        assert code == 0, err
        return out, (self.dir / "changed.txt").read_text().split()

    def cut(self, guide, ids, rows, *extra):
        """rows: {claim id: verdict}. Returns (exit code, stdout, stderr, the guide after)."""
        self.write("GUIDE.md", guide)
        self.write("ids.txt", "\n".join(ids) + "\n")
        self.write("rep/slice-1.md", "Slice: slice-1\n" + "".join("read | %s | %s | src/cli.py:3\n" % kv for kv in rows.items()))
        code, out, err = script("cut", self.p("GUIDE.md"), self.dir, "--ids", self.p("ids.txt"), "--reports", self.p("rep"), *extra)
        return code, out, err, (self.dir / "GUIDE.md").read_text()


class ChangedTest(unittest.TestCase):
    def run_changed(self, new, old):
        with Work() as w:
            return w.changed(new, old)

    def test_a_reworded_sentence_is_listed_and_the_others_are_not(self):
        new = GUIDE.replace("It stops after 5 notes.", "It stops after 5 notes a day.")
        out, ids = self.run_changed(new, GUIDE)
        self.assertEqual(ids, ["%d.1" % line_of(new, "stops after 5 notes a day")])
        self.assertIn("It stops after 5 notes a day. [A4.0002]", out)

    def test_a_sentence_that_only_changed_its_tag_is_listed(self):
        """The checker judged the words against the old tag; a new tag is an edit nobody checked."""
        new = GUIDE.replace("You can keep 5 notes a day. [A4.0002]", "You can keep 5 notes a day. [A4.0003]")
        self.assertEqual(self.run_changed(new, GUIDE)[1], ["%d.1" % line_of(new, "keep 5 notes")])

    def test_a_sentence_that_only_changed_its_cited_lines_is_listed(self):
        new = GUIDE.replace("It stops after 5 notes. `src/cli.py:7`", "It stops after 5 notes. `src/cli.py:8`")
        self.assertEqual(self.run_changed(new, GUIDE)[1], ["%d.1" % line_of(new, "stops after")])

    def test_a_guide_that_is_as_it_was_says_nothing_changed_and_writes_an_empty_ids_file(self):
        out, ids = self.run_changed(GUIDE, GUIDE)
        self.assertIn("nothing changed", out)
        self.assertEqual(ids, [])

    def test_a_cut_sentence_does_not_make_its_neighbour_a_changed_one(self):
        new = GUIDE.replace("It stops after 5 notes. `src/cli.py:7` [A4.0002]\n", "")
        self.assertEqual(self.run_changed(new, GUIDE)[1], [])

    def test_slice_was_picks_up_a_tag_only_edit_too(self):
        """slice.py --was and the closing step share one definition of changed."""
        new = GUIDE.replace("You can keep 5 notes a day. [A4.0002]", "You can keep 5 notes a day. [A4.0003]")
        with Work() as w:
            w.write("GUIDE.md", new)
            w.write("OLD.md", GUIDE)
            w.write("ids.txt", "A4.0001\n")
            r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "slice.py"), w.p("GUIDE.md"), str(w.dir), "--ids", w.p("ids.txt"), "--was", w.p("OLD.md"), "--out", w.p("o")],
                               capture_output=True, text=True)
            claims = (w.dir / "o/slice-1.claims.txt").read_text()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("You can keep 5 notes a day.", claims)

    def test_usage_errors_exit_2(self):
        self.assertEqual(script()[0], 2)
        self.assertEqual(script("changed", "/no/GUIDE.md", "/tmp", "--was", "/no/old.md")[0], 2)
        self.assertEqual(script("cut", "/no/GUIDE.md", "/tmp")[0], 2)


class CutTest(unittest.TestCase):
    def run_cut(self, guide, ids, rows, *extra):
        with Work() as w:
            return w.cut(guide, ids, rows, *extra)

    def n(self, needle, guide=GUIDE):
        return line_of(guide, needle)

    def test_a_claim_that_holds_is_kept_and_the_guide_is_as_it_was(self):
        code, out, err, after = self.run_cut(GUIDE, ["%d.1" % self.n("It stops after")], {"%d.1" % self.n("It stops after"): "HOLDS"})
        self.assertEqual(code, 0, err)
        self.assertEqual(after, GUIDE)
        self.assertIn("nothing cut", out)

    def test_an_appendix_claim_that_is_not_holds_loses_its_line_and_nothing_else(self):
        for verdict in ("WRONG", "OVERSTATED", "UNSUPPORTED"):
            n = self.n("It stops after")
            code, out, err, after = self.run_cut(GUIDE, ["%d.1" % n], {"%d.1" % n: verdict})
            self.assertEqual(code, 0, err)
            self.assertNotIn("It stops after 5 notes.", after, verdict)
            self.assertIn("It lists notes. `src/cli.py:3` [A4.0003]", after)
            self.assertIn("cut | %d.1 | %s" % (n, verdict), out)

    def test_a_part_1_sentence_tagged_only_to_a_cut_line_is_cut_with_it(self):
        n = self.n("It stops after")
        _, out, _, after = self.run_cut(GUIDE, ["%d.1" % n], {"%d.1" % n: "WRONG"})
        self.assertNotIn("You can keep 5 notes a day.", after)
        self.assertIn("cut, lost its only tag", out)

    def test_a_part_1_sentence_that_keeps_another_tag_stays_without_the_dead_one_and_is_listed(self):
        n = self.n("It sorts notes by date")
        _, out, _, after = self.run_cut(GUIDE, ["%d.1" % n], {"%d.1" % n: "WRONG"})
        self.assertIn("Notes can be listed and pinned. [A4.0003]\n", after)
        self.assertNotIn("[A4.0004]", after)
        self.assertRegex(out, r"kept, tag removed \(\[A4\.0004\]\) \| %d\.1" % self.n("Notes can be listed"))

    def test_in_a_two_sentence_line_only_the_sentence_that_lost_its_tag_goes(self):
        n = self.n("It sorts notes by date")
        _, _, _, after = self.run_cut(GUIDE, ["%d.1" % n], {"%d.1" % n: "WRONG"})
        self.assertIn("You can list notes. [A4.0003]\n", after)
        self.assertNotIn("It sorts them by date.", after)

    def test_a_list_mark_survives_an_edit_and_a_whole_list_line_can_go(self):
        guide = GUIDE.replace("- You can pin a note. [A4.0004]", "- You can list and pin notes. [A4.0003] [A4.0004]")
        n = self.n("It sorts notes by date", guide)
        _, _, _, after = self.run_cut(guide, ["%d.1" % n], {"%d.1" % n: "WRONG"})
        self.assertIn("- You can list and pin notes. [A4.0003]\n", after)
        _, _, _, after = self.run_cut(GUIDE, ["%d.1" % self.n("It sorts notes by date")], {"%d.1" % self.n("It sorts notes by date"): "WRONG"})
        self.assertNotIn("pin a note", after)
        self.assertNotRegex(after, r"(?m)^-\s*$")

    def test_a_part_1_claim_that_is_not_holds_loses_its_sentence_alone(self):
        n = self.n("You can list notes.")
        _, _, _, after = self.run_cut(GUIDE, ["%d.2" % n], {"%d.2" % n: "OVERSTATED"})
        self.assertIn("You can list notes. [A4.0003]\n", after)
        self.assertNotIn("It sorts them by date.", after)
        self.assertIn("It sorts notes by date. `src/cli.py:5` [A4.0004]", after)  # its appendix line was not the one that failed

    def test_a_cut_does_not_reword_and_leaves_every_other_line_byte_for_byte(self):
        n = self.n("It stops after")
        _, _, _, after = self.run_cut(GUIDE, ["%d.1" % n], {"%d.1" % n: "WRONG"})
        keep = [l for l in GUIDE.split("\n") if "5 notes" not in l]
        self.assertEqual([l for l in after.split("\n") if l in keep], [l for l in keep if l in after.split("\n")])
        self.assertEqual(len(after.split("\n")), len(GUIDE.split("\n")) - 2)

    def test_a_claim_with_no_report_row_is_an_error_and_writes_nothing(self):
        n = self.n("It stops after")
        code, _, err, after = self.run_cut(GUIDE, ["%d.1" % n], {})
        self.assertEqual(code, 1)
        self.assertIn("no report row for: %d.1" % n, err)
        self.assertEqual(after, GUIDE)

    def test_an_id_that_is_not_in_the_guide_is_an_error(self):
        code, _, err, _ = self.run_cut(GUIDE, ["999.1"], {"999.1": "HOLDS"})
        self.assertEqual(code, 1)
        self.assertIn("999.1", err)

    def test_an_empty_ids_file_cuts_nothing(self):
        with Work() as w:
            w.write("GUIDE.md", GUIDE)
            w.write("ids.txt", "")
            code, out, err = script("cut", w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"))
            self.assertEqual(code, 0, err)
            self.assertEqual((w.dir / "GUIDE.md").read_text(), GUIDE)

    def test_o_writes_elsewhere_and_clean_writes_the_guide_without_tags(self):
        n = self.n("It stops after")
        with Work() as w:
            code, out, err, _ = w.cut(GUIDE, ["%d.1" % n], {"%d.1" % n: "WRONG"}, "-o", w.p("GUIDE.final.md"), "--clean")
            self.assertEqual(code, 0, err)
            self.assertEqual((w.dir / "GUIDE.md").read_text(), GUIDE)
            self.assertNotIn("5 notes a day", (w.dir / "GUIDE.final.md").read_text())
            clean = (w.dir / "GUIDE.final.clean.md").read_text()
            self.assertNotRegex(clean, r"\[A\d+\.\w+\]")
            self.assertIn("It saves a note.", clean)

    def test_the_cut_guide_still_passes_the_citation_check_and_lint(self):
        n = self.n("It sorts notes by date")
        with Work() as w:
            w.write("surfaces.json", "[]")
            code, _, err, _ = w.cut(GUIDE, ["%d.1" % n], {"%d.1" % n: "WRONG"})
            self.assertEqual(code, 0, err)
            r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), w.p("GUIDE.md"), str(w.dir)], capture_output=True, text=True)
            self.assertNotIn("not found", r.stdout)
            self.assertNotRegex(r.stdout, r"\[A4\.0004\]")


class SkillWordsTest(unittest.TestCase):
    def test_skill_md_calls_the_script_and_every_flag_in_its_command_exists(self):
        self.assertIn("scripts/final_recheck.py", SKILL)
        source = (SCRIPTS / "final_recheck.py").read_text()
        for cmd in re.findall(r"`(python3 -I [^`]*final_recheck\.py[^`]*)`", SKILL + FIX_ROUNDS):
            for flag in re.findall(r"(?<![\w-])(--?[a-z][a-z-]*)", cmd.split("final_recheck.py", 1)[1]):
                self.assertIn(flag, source, flag)

    def test_the_closing_step_lists_cuts_and_never_rewrites_or_reassembles(self):
        step = SKILL.split("**Final re-check.**")[1].split("\n")[0]
        self.assertIn("final_recheck.py", step)
        self.assertIn("--was", step)
        self.assertRegex(step, r"(?i)no rewrite, no further round")
        self.assertIn("assemble.py", step)

    def test_fix_rounds_md_spells_out_the_closing_step_in_order(self):
        text = FIX_ROUNDS.split("## Final re-check")[1]
        steps = [text.index(w) for w in ("final_recheck.py changed", "slice.py GUIDE.md", "fresh checker", "score.py", "final_recheck.py cut", "check_citations.py", "lint_main.py")]
        self.assertEqual(steps, sorted(steps))
        self.assertRegex(text, r"(?i)nothing changed, stop")
        self.assertRegex(text, r"(?i)is not a second pass over the guide")
        self.assertRegex(text, r"(?i)nothing is reworded, and there is no further round")

    def test_the_old_wording_that_left_the_lead_cuts_unchecked_is_gone(self):
        self.assertNotRegex(SKILL, r"the lead makes every cut after that")
        self.assertNotRegex(FIX_ROUNDS, r"the lead makes every cut, a Part 1 sentence included")

    def test_the_reader_fix_goes_through_the_same_closing_step(self):
        self.assertRegex(SKILL.split("**Reader check.**")[1].split("\n")[0], r"step 12 checks its edits")
        self.assertRegex(READER.split("## One fix round")[1], r"(?i)final re-check")

    def test_fix_rounds_md_says_the_lead_cuts_are_checked_by_the_final_re_check(self):
        self.assertRegex(FIX_ROUNDS.split("## Part 1 over")[0], r"(?i)until the final re-check below")

    def test_there_is_no_full_final_check_of_the_whole_guide(self):
        self.assertNotRegex(SKILL + FIX_ROUNDS, r"(?i)check the whole guide again|every claim again|full final check")


if __name__ == "__main__":
    unittest.main()
