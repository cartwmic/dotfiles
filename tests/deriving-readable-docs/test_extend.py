"""The extend mode (passes 2 and 3): extend.py picks and slices only the lines a pass wrote, stamp.py --guide stamps a shipped guide, and the docs name what the scripts take.
Run: python3 -I tests/deriving-readable-docs/test_extend.py"""
import json
import re
import shlex
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import test_coverage as base  # noqa: E402
from test_final_recheck import line_of  # noqa: E402

SCRIPTS, SKILL_DIR = base.SCRIPTS, base.SKILL_DIR
SKILL = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
EXTEND = (SKILL_DIR / "references/extend.md").read_text(encoding="utf-8")
CHECK_BRIEF = (SKILL_DIR / "references/check-brief.md").read_text(encoding="utf-8")

OLD = """<!-- printed -->
# demo guide

Repo: demo. Commit: abc. Date: 2026-11-21.
<!-- /printed -->

# Part 1: In plain English

## What it is

Demo syncs notes to a server. [A3.aaaa]
Who it is for: people who keep notes. [A3.aaaa]

## What you can do

The sync interval is set in the settings. [A4.bbbb]
A refused connection is retried 3 times. [A4.dddd]

# Part 2: Appendix: technical detail

## A3 Whole product

Demo syncs notes to a server. `src/app.py:3` [A3.aaaa]

## A4 Syncing

The sync interval is set in the settings. `src/app.py:10` [A4.bbbb]
Notes are read from the folder. `src/app.py:20` [A4.cccc]
A refused connection is retried 3 times. `src/net.py:7` [A4.dddd]
A note over 1 MB is skipped. `src/app.py:35` [A4.eeee]
"""


def swap(text, old, new):
    assert old in text, old
    return text.replace(old, new)


class Fixture(base.Work):
    def setUp(self):
        super().setUp()
        self.write("GUIDE.was.md", OLD)

    def diff(self, new, *extra, name="out"):
        self.write("GUIDE.md", new)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "extend.py"), "diff", self.path("GUIDE.was.md"), self.path("GUIDE.md"), self.repo, "--out", self.path(name), *extra],
                           capture_output=True, text=True)
        return r

    def context(self, name="out"):
        """{sentence: reason} from context.txt. A Part 1 sentence has an appendix twin with the same words, so the Part 1 row is keyed "Part 1: <sentence>"."""
        rows = [l.split(" | ", 2) for l in Path(self.path(name + "/context.txt")).read_text().splitlines()]
        return {("Part 1: " if r[1] == "Part 1, tagged line" else "") + re.sub(r"\s*\[A\d+\.\w+\]", "", r[2]).strip(): r[1] for r in rows}


class NothingChangedTest(Fixture):
    def test_an_unchanged_guide_picks_nothing_and_writes_empty_slices(self):
        r = self.diff(OLD)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"unchanged 9, checked 0 \(nothing changed\)")
        self.assertEqual(Path(self.path("out/changed.txt")).read_text(), "")
        self.assertEqual(json.loads(Path(self.path("out/slices.json")).read_text()), [])


class PickTest(Fixture):
    def test_a_new_line_is_picked_with_the_line_before_it_and_the_line_after_it(self):
        new = swap(OLD, "Notes are read from the folder. `src/app.py:20` [A4.cccc]\n", "Notes are read from the folder. `src/app.py:20` [A4.cccc]\nThe folder defaults to notes. `src/app.py:21` [A4.ffff]\n")
        r = self.diff(new)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.context(), {"The folder defaults to notes.": "new line", "Notes are read from the folder.": "line before a changed",
                                          "A refused connection is retried 3 times.": "changed"})
        self.assertIn("unchanged 7, checked 3 (changed 1, line before a changed 1, new line 1)", r.stdout)

    def test_an_edited_line_keeps_its_id_and_is_picked_with_the_part_1_sentence_tagged_to_it(self):
        new = swap(OLD, "The sync interval is set in the settings. `src/app.py:10`", "The sync interval defaults to 30 seconds. `src/app.py:10`")
        self.diff(new)
        got = self.context()
        self.assertEqual(got["The sync interval defaults to 30 seconds."], "edited line")
        self.assertEqual(got["Part 1: The sync interval is set in the settings."], "Part 1, tagged line")
        self.assertNotIn("A note over 1 MB is skipped.", got)  # an untouched line is not picked

    def test_the_line_before_an_edited_line_is_picked_because_its_condition_may_sit_on_the_next_line(self):
        new = swap(OLD, "A refused connection is retried 3 times. `src/net.py:7`", "A refused connection is retried 5 times. `src/net.py:7`")
        self.diff(new)
        self.assertEqual(self.context()["Notes are read from the folder."], "line before a changed")
        self.assertNotIn("A note over 1 MB is skipped.", self.context())

    def test_a_line_that_only_moved_is_picked_and_a_line_the_pass_did_not_touch_is_not(self):
        moved = swap(swap(OLD, "A note over 1 MB is skipped. `src/app.py:35` [A4.eeee]\n", ""), "Notes are read from the folder. `src/app.py:20` [A4.cccc]\n",
                     "A note over 1 MB is skipped. `src/app.py:35` [A4.eeee]\nNotes are read from the folder. `src/app.py:20` [A4.cccc]\n")
        self.diff(moved)
        got = self.context()
        self.assertIn("A note over 1 MB is skipped.", got)
        self.assertEqual(got["A note over 1 MB is skipped."], "changed")
        self.assertNotIn("A refused connection is retried 3 times.", got)  # the lines on either side of the move stay unpicked unless they follow a changed one
        self.assertNotIn("Demo syncs notes to a server.", got)

    def test_a_new_part_1_sentence_is_picked(self):
        new = swap(OLD, "The sync interval is set in the settings. [A4.bbbb]\n", "The sync interval is set in the settings. [A4.bbbb]\nA note over 1 MB is skipped. [A4.eeee]\n")
        self.diff(new)
        self.assertEqual(self.context()["A note over 1 MB is skipped."], "changed")

    def test_a_removed_line_is_reported_and_not_picked(self):
        new = swap(OLD, "Notes are read from the folder. `src/app.py:20` [A4.cccc]\n", "")
        r = self.diff(new)
        self.assertIn("REMOVED A4.cccc | Notes are read from the folder.", r.stdout)
        self.assertNotIn("Notes are read from the folder.", self.context())

    def test_the_slices_are_the_ones_score_py_reads(self):
        """Reports written for the slices score against them like any pass-1 report (a Part 1 slice, then an appendix slice)."""
        new = swap(OLD, "A refused connection is retried 3 times. `src/net.py:7`", "A refused connection is retried 5 times. `src/net.py:7`")
        self.diff(new)
        (self.root / "work/reports").mkdir()
        total = 0
        for k, name in ((1, "part1-report-1.md"), (2, "report-2.md")):
            ids = [c.split(" | ")[0] for c in Path(self.path("out/slice-%d.claims.txt" % k)).read_text().splitlines()]
            total += len(ids)
            self.write("reports/" + name, "Slice: slice-%d\n" % k + "".join("read | %s | HOLDS | src/net.py:7\n" % i for i in ids)
                       + "Counts: claims checked %d; HOLDS %d; WRONG 0; OVERSTATED 0; UNSUPPORTED 0.\n" % (len(ids), len(ids)))
        self.assertEqual(total, 3)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "score.py"), "x=" + self.path("reports"), "--doc", self.path("GUIDE.md"), "--repo", self.repo,
                            "--slices", self.path("out")], capture_output=True, text=True)
        self.assertIn("errors: 0 out of 3 claims", r.stdout, r.stdout + r.stderr)


class TodoGuardTest(Fixture):
    def todo(self, line_id, listed=True, state="PARTIAL"):
        self.write("coverage-extend.json", json.dumps({"rows": [{"id": "F1", "state": state, "line_id": line_id, "listed": listed}]}))
        return self.path("coverage-extend.json")

    EDIT = ("The sync interval is set in the settings. `src/app.py:10`", "The sync interval defaults to 30 seconds. `src/app.py:10`")

    def test_an_edit_the_to_do_named_passes(self):
        r = self.diff(swap(OLD, *self.EDIT), "--todo", self.todo("A4.bbbb"))
        self.assertEqual((r.returncode, "NOT IN THE TO-DO" in r.stdout), (0, False), r.stdout)

    def test_an_edit_of_an_old_line_the_to_do_did_not_name_fails_and_still_writes_the_slices(self):
        r = self.diff(swap(OLD, *self.EDIT), "--todo", self.todo("A4.cccc"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("NOT IN THE TO-DO A4.bbbb | The sync interval defaults to 30 seconds.", r.stdout)
        self.assertTrue(Path(self.path("out/changed.txt")).read_text().strip())

    def test_a_partial_row_that_did_not_fit_the_room_does_not_license_an_edit(self):
        r = self.diff(swap(OLD, *self.EDIT), "--todo", self.todo("A4.bbbb", listed=False))
        self.assertEqual(r.returncode, 1)

    NEW = swap(OLD, "Notes are read from the folder. `src/app.py:20` [A4.cccc]\n", "Notes are read from the folder. `src/app.py:20` [A4.cccc]\nThe folder defaults to notes. `src/app.py:21` [A4.ffff]\n")

    def missing(self, cite, listed=True, state="MISSING"):
        self.write("coverage-extend.json", json.dumps({"rows": [{"id": "F2", "state": state, "line_id": None, "listed": listed, "cite": cite}]}))
        return self.path("coverage-extend.json")

    def test_a_new_line_that_a_listed_missing_row_explains_passes(self):
        for cite in ("src/app.py:21", "src/app.py:18-25"):
            r = self.diff(self.NEW, "--todo", self.missing(cite))
            self.assertEqual((r.returncode, "NOT IN THE TO-DO" in r.stdout), (0, False), r.stdout)

    def test_a_new_line_that_no_listed_missing_row_explains_fails_and_still_writes_the_slices(self):
        for todo in (self.todo("A4.bbbb"), self.missing("src/app.py:90"), self.missing("src/net.py:21"), self.missing("src/app.py:21", listed=False), self.missing("src/app.py:21", state="PARTIAL")):
            r = self.diff(self.NEW, "--todo", todo)
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("NOT IN THE TO-DO new A4.ffff | The folder defaults to notes.", r.stdout)
            self.assertTrue(Path(self.path("out/changed.txt")).read_text().strip())

    def test_a_new_line_without_the_to_do_flag_is_not_checked(self):
        self.assertEqual(self.diff(self.NEW).returncode, 0)


class UsageTest(Fixture):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(SCRIPTS / "extend.py"), *args], capture_output=True, text=True)

    def test_bad_usage_exits_2(self):
        self.write("GUIDE.md", OLD)
        was, doc = self.path("GUIDE.was.md"), self.path("GUIDE.md")
        for args in ((), ("nope",), ("diff", was, doc, self.repo), ("diff", was, doc, self.repo, "--out", self.path("o"), "--max-claims", "0"),
                     ("diff", was, self.path("missing.md"), self.repo, "--out", self.path("o")), ("diff", was, doc, self.repo, "--out", self.path("o"), "--todo", self.path("missing.json")),
                     ("index", doc)):
            self.assertEqual(self.run_cli(*args).returncode, 2, args)

    def test_index_lists_each_appendix_id_with_its_sentence_and_no_part_1_line(self):
        self.write("GUIDE.md", OLD)
        r = self.run_cli("index", self.path("GUIDE.md"), self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines()[:2], ["A3.aaaa | Demo syncs notes to a server.", "A4.bbbb | The sync interval is set in the settings."])
        self.assertEqual(len(r.stdout.splitlines()), 5)


class StampGuideTest(Fixture):
    NEW = swap(OLD, "A note over 1 MB is skipped. `src/app.py:35` [A4.eeee]\n", "A note over 1 MB is skipped. `src/app.py:35` [A4.eeee]\nA note with no title is skipped. `src/app.py:36`\n")

    def stamp(self, *args):
        return subprocess.run([sys.executable, "-I", str(SCRIPTS / "stamp.py"), *args, self.path("GUIDE.md")], capture_output=True, text=True)

    def test_a_whole_guide_is_refused_without_the_flag_because_part_1_comes_first(self):
        self.write("GUIDE.md", swap(self.NEW, "## What it is\n\n", "## What it is\n\nA plain sentence with no tag.\n"))
        r = self.stamp()
        self.assertEqual(r.returncode, 1)
        self.assertIn("comes before the first `## A<n>` heading", r.stdout)

    def test_with_guide_only_the_new_appendix_line_gets_an_id_and_everything_else_is_byte_for_byte(self):
        untagged = swap(self.NEW, "## What it is\n\n", "## What it is\n\nA plain sentence with no tag.\n")  # Part 1 prose with no id is left alone too
        self.write("GUIDE.md", untagged)
        r = self.stamp("--guide")
        self.assertEqual(r.returncode, 0, r.stdout)
        after = Path(self.path("GUIDE.md")).read_text()
        added = re.search(r"A note with no title is skipped\. `src/app\.py:36` \[A4\.[0-9a-f]{4}\]\n", after)
        self.assertIsNotNone(added, after)
        self.assertEqual(after.replace(added.group(0), "A note with no title is skipped. `src/app.py:36`\n"), untagged)

    def test_a_guide_with_every_line_stamped_is_left_alone(self):
        self.write("GUIDE.md", OLD)
        self.assertEqual(self.stamp("--guide").returncode, 0)
        self.assertEqual(Path(self.path("GUIDE.md")).read_text(), OLD)


class RecheckAfterRepairTest(Fixture):
    """E7 step 4 re-checks a claim that failed its check and that the lead left unedited. The test reads the E7 commands out of extend.md, fills in `<skill>` and `<repo>`,
    and reads step 4's `...` as the guide and repo operands. It runs them in the pass folder. Only the checker's reports are written by hand. On wording that compares with
    GUIDE.new.cut.md, the unedited line is never listed again and this test fails."""

    NEW_CLAIM = "A note is saved on every edit."
    NEW = swap(swap(OLD, "Notes are read from the folder. `src/app.py:20` [A4.cccc]\n", "Notes are read from the folder. `src/app.py:20` [A4.cccc]\n"
                    "A note is saved on every edit. `src/app.py:21` [A4.ffff]\n"),
               "The sync interval is set in the settings. `src/app.py:10`", "The sync interval defaults to 30 seconds. `src/app.py:10`")

    def e7_steps(self):
        """{step number: the `python3 -I` commands in backticks on that numbered line of E7 in extend.md}."""
        section = EXTEND.split("## E7 Repair before cut")[1].split("## E8 ")[0]
        steps = {}
        for line in section.splitlines():
            m = re.match(r"(\d+)\. ", line)
            if m:
                steps[int(m.group(1))] = re.findall(r"`(python3 -I <skill>/scripts/[^`]+)`", line)
        return steps

    def run_step(self, command):
        args = shlex.split(command.replace("<skill>", str(SKILL_DIR)).replace("<repo>", self.repo).replace(" ... ", " GUIDE.md %s " % self.repo))
        self.assertEqual(args[:2], ["python3", "-I"], command)
        return subprocess.run([sys.executable, "-I", *args[2:]], cwd=self.path(""), capture_output=True, text=True)

    def checker_report(self, folder, ids, failing, finding=""):
        """What a fresh checker writes for one slice: a read row for each claim, the failing one with OVERSTATED, and its finding if the check gave one."""
        Path(self.path(folder)).mkdir(exist_ok=True)
        rows = "".join("read | %s | %s | src/app.py:3\n" % (i, "OVERSTATED" if i == failing else "HOLDS") for i in ids)
        self.write(folder + "/slice-1.md", "Slice: slice-1\n" + rows + finding)

    def test_a_claim_that_failed_its_check_and_was_left_unedited_is_listed_and_checked_again(self):
        r = self.diff(self.NEW, name="slices-new")  # E6: the pass's own extend.py diff
        self.assertEqual(r.returncode, 0, r.stdout)
        shutil.copyfile(self.path("GUIDE.md"), self.path("GUIDE.new.cut.md"))  # E6: keep GUIDE.md as GUIDE.new.cut.md
        new_id = "%d.1" % line_of(self.NEW, self.NEW_CLAIM)
        passed_id = "%d.1" % line_of(self.NEW, "The sync interval defaults")
        ids = Path(self.path("slices-new/changed.txt")).read_text().split()
        self.assertIn(new_id, ids)
        self.checker_report("reports-new", ids, new_id, "%s | OVERSTATED | MISSING_CONDITION | saves | it saves only when sync is on (src/app.py:21) | add the condition\n" % new_id)

        steps = self.e7_steps()
        self.assertEqual([len(steps[k]) for k in (1, 2, 4, 5)], [1, 1, 4, 3], steps)
        r = self.run_step(steps[1][0])  # step 1: the claim is a fix, not a cut
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"fix \| %s \| OVERSTATED \| MISSING_CONDITION" % re.escape(new_id))
        r = self.run_step(steps[2][0])  # step 2: --except keeps it
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(self.NEW_CLAIM, Path(self.path("GUIDE.md")).read_text())  # step 3 is the lead's edit, and this lead leaves the line alone
        r = self.run_step(steps[4][0])  # step 4: what is still different, less what a checker passed as it stands
        self.assertEqual(r.returncode, 0, r.stderr)
        again = Path(self.path("changed2.txt")).read_text().split()
        self.assertIn(new_id, again, "E7 step 4 did not list the line left unedited, so no checker sees it again")
        self.assertNotIn(passed_id, again)  # an edited line that a checker passed is skipped
        r = self.run_step(steps[4][1])  # one fresh checker per slice gets it
        self.assertEqual(r.returncode, 0, r.stderr)
        claims = [line.split(" | ")[0] for p in Path(self.path("slices-new2")).glob("slice-*.claims.txt") for line in p.read_text().splitlines() if line.strip()]
        self.assertIn(new_id, claims)
        self.assertEqual(set(claims), set(again), "the slice must hold only the ids in changed2.txt: a --was here also adds each claim that differs from GUIDE.was.md, held ones included")
        self.checker_report("reports-new2", again, new_id)  # the fresh check still fails it
        r = self.run_step(steps[4][2])  # the second try: a repaired claim that still fails is repaired once more, not cut
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"fix \| %s \| OVERSTATED" % re.escape(new_id))
        r = self.run_step(steps[4][3])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(self.NEW_CLAIM, Path(self.path("GUIDE.md")).read_text())
        r = self.run_step(steps[5][0])  # what neither round's held file passed
        self.assertEqual(r.returncode, 0, r.stderr)
        third = Path(self.path("changed3.txt")).read_text().split()
        self.assertIn(new_id, third)
        r = self.run_step(steps[5][1])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.checker_report("reports-new3", third, new_id)  # it still fails after its second repair
        r = self.run_step(steps[5][2])  # cut now
        self.assertEqual(r.returncode, 0, r.stderr)
        after = Path(self.path("GUIDE.md")).read_text()
        self.assertNotIn(self.NEW_CLAIM, after)
        self.assertIn("The sync interval defaults to 30 seconds.", after)

    def test_e8_re_checks_with_the_same_was_file_as_step_4(self):
        was = re.search(r"--was (\S+)", self.e7_steps()[4][0]).group(1)
        self.assertIn(was, EXTEND.split("## E8 ")[1])


class ExtendDocsTest(unittest.TestCase):
    def test_skill_md_has_the_extend_section_and_adds_no_numbered_step(self):
        self.assertIn("## Extend an existing guide (passes 2 and 3)", SKILL)
        section = SKILL.split("## Extend an existing guide (passes 2 and 3)")[1]
        self.assertNotRegex(section, r"(?m)^\d+\. \*\*")  # tests and readers find pass 1's steps by `N. **Name.**`
        for word in ("references/extend.md", "COVERED, PARTIAL or MISSING", "--grow 1500", "1,500 words", "1,000 words", "core facts", "in place", "extend.py diff", "check-brief.md` as written", "Repair before cut"):
            self.assertIn(word, section)

    def test_the_method_names_every_script_it_calls_and_the_one_checker_brief(self):
        for script in ("coverage.py", "stamp.py --guide", "extend.py index", "extend.py diff", "check_citations.py", "lint_main.py", "final_recheck.py repair", "final_recheck.py cut",
                       "final_recheck.py changed", "final_recheck.py drop", "score.py new=reports-new"):
            self.assertIn(script, EXTEND, script)
        self.assertRegex(EXTEND, r"references/check-brief\.md` as written \(the same brief pass 1 uses\)")
        self.assertRegex(EXTEND, r"never run `assemble\.py`")

    def test_e6_names_the_repaired_copy_as_the_old_file_the_same_way_e7_step_4_does(self):
        e6 = EXTEND.split("## E6 ")[1].split("## E7 ")[0]
        e7 = EXTEND.split("## E7 ")[1].split("## E8 ")[0]
        self.assertIn("When a run repaired the incoming guide first, that repaired copy is the old file (`GUIDE.was.md`) instead", e6)
        self.assertIn("When a run repaired the incoming guide first, that repaired copy is the `--was` file instead", e7)

    def test_a_partial_fact_is_an_edit_and_a_missing_fact_goes_next_to_its_neighbour(self):
        self.assertRegex(EXTEND, r"A PARTIAL fact never gets a second line")
        self.assertRegex(EXTEND, r"directly after it, never at the top of the section")

    def test_the_condition_audit_and_the_part_1_guard_are_written(self):
        self.assertRegex(EXTEND, r"(?i)the condition audit")
        self.assertRegex(EXTEND, r"the edit may not drop one")
        self.assertRegex(EXTEND, r"fixed once by the front writer, then dropped")
        self.assertRegex(EXTEND, r"New Part 1 text is only for core facts")
        self.assertRegex(EXTEND, r"A finding is repaired, not deleted")

    def test_the_check_brief_is_the_frozen_version_8_and_names_no_table_rule(self):
        self.assertIn("version 8", CHECK_BRIEF)
        self.assertNotRegex(CHECK_BRIEF, r"(?i)defaults and limits")

    def test_no_privacy_or_threat_topic_is_added(self):
        self.assertRegex(EXTEND, r"(?i)add no security, privacy or threat language")


if __name__ == "__main__":
    unittest.main()
