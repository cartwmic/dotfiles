"""The extend mode (passes 2 and 3): extend.py picks and slices only the lines a pass wrote, stamp.py --guide stamps a shipped guide, and the docs name what the scripts take.
Run: python3 -I tests/deriving-readable-docs/test_extend.py"""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.dont_write_bytecode = True
import test_coverage as base  # noqa: E402

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

    def test_a_new_line_needs_no_to_do_row(self):
        new = swap(OLD, "Notes are read from the folder. `src/app.py:20` [A4.cccc]\n", "Notes are read from the folder. `src/app.py:20` [A4.cccc]\nThe folder defaults to notes. `src/app.py:21` [A4.ffff]\n")
        self.assertEqual(self.diff(new, "--todo", self.todo("A4.bbbb")).returncode, 0)


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
