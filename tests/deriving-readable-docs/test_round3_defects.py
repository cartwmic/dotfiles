"""The defects the round 3 runs (khoj, agent-kit) tripped on, each run as the skill runs it (a script on files). Each test breaks one rule.
The fixtures are excerpts of the round 3 data: tests/deriving-readable-docs/fixtures/round3/.
Run: python3 -I tests/deriving-readable-docs/test_round3_defects.py"""
import atexit
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = tempfile.mkdtemp(prefix="state-")  # the scripts log each run (runlog.py): keep these runs out of the real log
os.environ["XDG_STATE_HOME"] = STATE
atexit.register(shutil.rmtree, STATE, True)

HERE = Path(__file__).resolve().parent
SKILL = HERE.parents[1] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs"
SCRIPTS = SKILL / "scripts"
ROUND3 = HERE / "fixtures/round3"
SURFACES = [{"kind": "command", "name": "notes add", "file": "src/cli.py", "line": 3}, {"kind": "flag", "name": "--tag <name>", "file": "src/cli.py", "line": 5}]


def script(name, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / name), *map(str, args)], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def make(files):
    tmp = tempfile.TemporaryDirectory()
    for rel, text in files.items():
        p = Path(tmp.name) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp


def counts(claims, holds, wrong=0, over=0, unsup=0):
    return "Counts: claims checked %d; HOLDS %d; WRONG %d; OVERSTATED %d; UNSUPPORTED %d.\n" % (claims, holds, wrong, over, unsup)


# --- defect 9, 11, 5: --audit ------------------------------------------------------------------------------------------------------------
JIRA_LINE = (ROUND3 / "jira-line.txt").read_text().rstrip("\n")
JIRA_ROW = (ROUND3 / "jira-evidence-row.md").read_text().rstrip("\n")
JIRA_REPO = {"src/board/trackers/jira.ts": "".join("// line %d\n" % i for i in range(1, 39)) + JIRA_LINE + "\n"}
JIRA_DOC = "## A8 Config\n\nA jira section with grantsWrite true is refused. `src/board/trackers/jira.ts:39` [A8.aaaa]\n"
JIRA_AUDIT = '3 | assert: src/board/trackers/jira.ts:39 "partOf<JiraSection | undefined>(parts, \'jira\')?.grantsWrite === true" | exits: none listed | callers: none found | found: nothing | result: HOLDS\n'


class AuditFilesTest(unittest.TestCase):
    def audit(self, evidence=JIRA_ROW + "\n", audit=JIRA_AUDIT, choice="- the jira grant\n", audit_file=True, repo=JIRA_REPO, doc=JIRA_DOC):
        with make(repo) as r, tempfile.TemporaryDirectory() as d:
            Path(d, "doc.md").write_text(doc, encoding="utf-8")
            if audit_file:
                Path(d, "audit.md").write_text(audit, encoding="utf-8")
            Path(d, "guards.md").write_text("# guards\n")
            if evidence is not None:
                Path(d, "evidence.md").write_text(evidence, encoding="utf-8")
            if choice is not None:
                Path(d, "choice.md").write_text(choice)
            code, out, err = script("check_citations.py", Path(d, "doc.md"), r, "--audit", Path(d, "audit.md"))
            return code, out.replace(d, "<d>"), err

    def test_a_row_whose_quoted_line_holds_a_pipe_is_read_whole(self):
        code, out, err = self.audit()
        self.assertEqual(code, 0, out + err)

    def test_the_text_after_the_pipe_is_checked_too(self):
        """The row used to end its quote at ` | `, so the part after it was never compared with the line."""
        code, out, err = self.audit(evidence=JIRA_ROW.replace("undefined>(parts", "undefined>(wrong text"))
        self.assertEqual(code, 1, out + err)
        self.assertIn("no evidence row for src/board/trackers/jira.ts:39", out)

    def test_a_pipe_row_is_not_dropped_silently(self):
        """The cut quote had no closing mark, so the row vanished and the cited line had no evidence row at all."""
        code, out, err = self.audit(evidence=JIRA_ROW + "\n")
        self.assertNotIn("no evidence row", out)

    def test_an_or_operator_in_a_quoted_line_is_read_whole(self):
        repo = {"src/a.ts": "const x = a || b;\n"}
        doc = "## A4 x\n\nIt falls back to b. `src/a.ts:1` [A4.aaaa]\n"
        audit = '3 | assert: src/a.ts:1 "const x = a || b;" | exits: none listed | callers: none found | found: nothing | result: HOLDS\n'
        code, out, err = self.audit(evidence='`src/a.ts:1` | "const x = a || b;" | the default\n', audit=audit, repo=repo, doc=doc)
        self.assertEqual(code, 0, out + err)

    def test_a_missing_audit_file_is_a_fail_that_names_the_path(self):
        code, out, err = self.audit(audit_file=False)
        self.assertEqual(code, 1, out + err)
        self.assertRegex(out, r"FAIL audit: no audit file at <d>/audit\.md")

    def test_a_missing_choice_file_is_a_fail_that_names_the_path(self):
        code, out, err = self.audit(choice=None)
        self.assertEqual(code, 1, out + err)
        self.assertRegex(out, r"FAIL choice: no choice file at <d>/choice\.md")

    def test_an_empty_choice_file_fails_too(self):
        self.assertEqual(self.audit(choice="  \n")[0], 1)

    def test_the_rules_are_written_down_in_the_check_and_the_drafting_method(self):
        text = (SCRIPTS / "check_citations.py").read_text() + (SKILL / "references/drafting.md").read_text()
        self.assertIn("choice.md", text)
        self.assertRegex(text, r"(?i)one line[^\n]*never a range")
        self.assertRegex(text, r"narrowed to")
        self.assertRegex(text, r"(?i)evidence file is completed against the cited lines of the draft")


# --- defect 12, 13: --show and --guards ---------------------------------------------------------------------------------------------------
class ShowAndGuardsTest(unittest.TestCase):
    def test_show_past_the_end_prints_the_files_line_count(self):
        with make({"src/a.ts": "one\ntwo\nthree\n"}) as repo:
            code, out, err = script("check_citations.py", "--show", "src/a.ts:2-9", repo)
        self.assertEqual(code, 1)
        self.assertIn("src/a.ts:2-9: line out of range (file has 3 lines)", out + err)

    def test_show_of_a_line_past_the_end_names_the_count_too(self):
        with make({"src/a.ts": "one\ntwo\n"}) as repo:
            code, out, err = script("check_citations.py", "--show", "src/a.ts:7", repo)
        self.assertIn("file has 2 lines", out + err)

    def test_guards_print_an_or_operator_as_written(self):
        repo = {"src/a.ts": "export function f(x: number | null) {\n  if (x === null || x < 0) return 1;\n  return x;\n}\n"}
        with make(repo) as r, tempfile.TemporaryDirectory() as d:
            Path(d, "doc.md").write_text("## A4 x\n\nIt returns x. `src/a.ts:3` [A4.aaaa]\n")
            code, out, err = script("check_citations.py", Path(d, "doc.md"), r, "--guards")
        self.assertIn("if (x === null || x < 0) return 1;", out)
        self.assertNotIn("//", out)

    def test_a_guard_row_with_an_or_operator_is_still_read_back(self):
        repo = {"src/a.ts": "export function f(x: number | null) {\n  if (x === null || x < 0) return 1;\n  return x;\n}\n"}
        doc = "## A4 x\n\nIt returns x. `src/a.ts:3` [A4.aaaa]\n"
        with make(repo) as r, tempfile.TemporaryDirectory() as d:
            Path(d, "doc.md").write_text(doc)
            sheet = script("check_citations.py", Path(d, "doc.md"), r, "--guards")[1].replace("covered:\n", "covered: A4.aaaa\n")
            Path(d, "guards.md").write_text(sheet)
            Path(d, "audit.md").write_text('3 | assert: src/a.ts:3 "return x;" | exits: src/a.ts:2 stated | callers: none found | found: nothing | result: HOLDS\n')
            Path(d, "evidence.md").write_text('`src/a.ts:3` | "return x;" | the value\n')
            Path(d, "choice.md").write_text("- x\n")
            code, out, err = script("check_citations.py", Path(d, "doc.md"), r, "--audit", Path(d, "audit.md"))
        self.assertEqual(code, 0, out + err)


# --- defect 14: guard noise ---------------------------------------------------------------------------------------------------------------
FACTORY = (ROUND3 / "matrix-factory.ts").read_text()


class GuardNoiseTest(unittest.TestCase):
    def sheet(self, cites):
        doc = "## A6 Ports\n\n" + "".join("Sentence %d. `src/matrix.ts:%s` [A6.%04x]\n" % (i, c, i) for i, c in enumerate(cites))
        with make({"src/matrix.ts": FACTORY}) as r, tempfile.TemporaryDirectory() as d:
            Path(d, "doc.md").write_text(doc)
            return script("check_citations.py", Path(d, "doc.md"), r, "--sheet")[1], script("check_citations.py", Path(d, "doc.md"), r, "--guards")[1]

    def test_a_method_cited_on_its_signature_line_does_not_list_the_factorys_throws(self):
        sheet, _ = self.sheet(["9-11", "14"])
        self.assertNotIn("room_id", sheet)
        self.assertNotIn("space_id", sheet)
        self.assertNotIn("early exits between the start of `export function createMatrixPort", sheet)

    def test_the_factorys_throws_are_listed_under_a_line_of_its_own_body(self):
        sheet, _ = self.sheet(["7"])
        self.assertIn("room_id", sheet)
        self.assertIn("space_id", sheet)

    def test_the_condition_sheet_lists_them_once_when_the_body_is_cited_and_not_at_all_otherwise(self):
        _, guards_methods = self.sheet(["9-11", "14"])
        self.assertEqual([l for l in guards_methods.splitlines() if "room_id" in l], [])
        _, guards_body = self.sheet(["7", "9-11"])
        self.assertEqual(len([l for l in guards_body.splitlines() if "room_id" in l]), 1)

    def test_a_nested_python_def_line_belongs_to_that_function(self):
        src = "def make(x):\n    if not x:\n        raise ValueError('x')\n    def inner(y):\n        return y\n    return inner\n"
        with make({"src/m.py": src}) as r:
            code, out, err = script("early_exits.py", Path(r, "src/m.py"), 4)
            body = script("early_exits.py", Path(r, "src/m.py"), 6)[1]
        self.assertNotIn("raise", out)
        self.assertIn("raise", body)


# --- defect 15: assemble --index ----------------------------------------------------------------------------------------------------------
class IndexTest(unittest.TestCase):
    def test_the_index_leaves_no_space_before_a_stop_or_a_comma(self):
        repo = {"src/cli.py": "a\nb\nc\n", "README.md": "# Notes\n"}
        a3 = ("## A3 The product as a whole\n\nNotes saves short notes, which the README calls `notes`. `README.md:1` [A3.aaaa]\n"
              "A note is kept `src/cli.py:2`. [A3.bbbb]\nThe port is written against reach. `src/cli.py:2`, `src/cli.py:3` [A3.cccc]\n")
        with make(repo) as r, tempfile.TemporaryDirectory() as d:
            Path(d, "A3.md").write_text(a3)
            Path(d, "surfaces.json").write_text("[]")
            code, out, err = script("assemble.py", d, r, "--index")
        self.assertEqual(code, 0, err)
        for line in out.splitlines():
            self.assertNotRegex(line, r" [.,;:]", line)
        self.assertIn("A3.aaaa | Notes saves short notes, which the README calls `notes`.", out)
        self.assertIn("A3.cccc | The port is written against reach.\n", out + "\n")


# --- defect 16, 6: score.py ---------------------------------------------------------------------------------------------------------------
# The header assemble.py prints: lint_main.py fails a guide without it.
SNAP = ("<!-- printed -->\n# x guide\n\nSnapshot of x at 0000000 on 2026-11-20. Not maintained: it records the code at that commit, not today's.\n\n"
        "Repo: x. Commit: " + "0" * 40 + ". Date: 2026-11-20. Snapshot: 2026-11-20 at " + "0" * 40 + ".\n<!-- /printed -->\n\n")

DOC = ("# Part 1: In plain English\n\n## What it is\n\nIt saves notes. [A4.0001]\n\n# Part 2: Appendix\n\n## A4 Notes\n\n"
       "The add command saves a note. `src/cli.py:3` [A4.0001]\nIt stops after 5 notes. `src/cli.py:7` [A4.0002]\n")
REPO = {"src/cli.py": "x\n" * 10}


class ScoreTest(unittest.TestCase):
    def fix_round(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(DOC, encoding="utf-8")
            Path(d, "changed.txt").write_text("12.1\n", encoding="utf-8")
            script("slice.py", Path(d, "GUIDE.md"), repo, "--ids", Path(d, "changed.txt"), "--out", Path(d, "slices-fix1"))
            Path(d, "r2").mkdir()
            Path(d, "r2", "slice-1.md").write_text("Slice: slice-1\nread | 12.1 | WRONG | src/cli.py:7\n12.1 | WRONG | MISSING_CONDITION | x | y | z\n" + counts(1, 0, 1), encoding="utf-8")
            return script("score.py", Path(d, "r2"), "--doc", Path(d, "GUIDE.md"), "--repo", repo, "--slices", Path(d, "slices-fix1"))

    def test_a_fix_round_compares_the_sentences_it_re_checked_with_their_own_words(self):
        code, out, err = self.fix_round()
        self.assertEqual(code, 0, out + err)
        self.assertIn("fix round: 1 of the guide's 3 claims were re-checked", out)
        self.assertNotIn("difference", out)
        self.assertIn("script claims: 1;", out)
        self.assertIn("words: 5;", out)  # "It stops after 5 notes." is five words; the id is not one

    def test_a_full_round_is_unchanged(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(DOC, encoding="utf-8")
            script("slice.py", Path(d, "GUIDE.md"), repo, "--out", Path(d, "slices"))
            Path(d, "r1").mkdir()
            Path(d, "r1", "part1-1.md").write_text("Slice: slice-1\nread | 5.1 | HOLDS | src/cli.py:3\n" + counts(1, 1), encoding="utf-8")
            Path(d, "r1", "slice-2.md").write_text("Slice: slice-2\nread | 11.1 | HOLDS | src/cli.py:3\nread | 12.1 | HOLDS | src/cli.py:7\n" + counts(2, 2), encoding="utf-8")
            code, out, err = script("score.py", Path(d, "r1"), "--doc", Path(d, "GUIDE.md"), "--repo", repo, "--slices", Path(d, "slices"))
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("fix round", out)
        self.assertIn("script claims: 3;", out)

    def depth(self, lines_read):
        """A slice of 6 claims whose report names `lines_read` as the evidence of each claim."""
        doc = "# Part 2: Appendix\n\n## A4 Notes\n\n" + "".join("It does thing %d. `src/cli.py:2` [A4.%04x]\n" % (i, i) for i in range(6))
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(doc)
            script("slice.py", Path(d, "GUIDE.md"), repo, "--out", Path(d, "slices"))
            claims = [l.split(" | ")[0] for l in Path(d, "slices", "slice-1.claims.txt").read_text().splitlines()]
            Path(d, "r").mkdir()
            rows = "".join("read | %s | HOLDS | src/cli.py:%d\n" % (c, lines_read[i % len(lines_read)]) for i, c in enumerate(claims))
            Path(d, "r", "slice-1.md").write_text("Slice: slice-1\n" + rows + counts(6, 6))
            return script("score.py", Path(d, "r"), "--repo", repo, "--slices", Path(d, "slices"))

    def test_a_report_that_read_one_line_for_six_claims_gets_a_depth_warning_and_still_exits_0(self):
        code, out, err = self.depth([2])
        self.assertEqual(code, 0, out + err)
        self.assertIn("warning depth: slice-1.md read 1 distinct lines for 6 claims, below one in three", out)
        self.assertIn("tool calls", out)

    def test_two_distinct_lines_for_six_claims_is_the_floor_and_does_not_warn(self):
        code, out, err = self.depth([2, 3])
        self.assertNotIn("warning", out)


# --- defect 7: slices ---------------------------------------------------------------------------------------------------------------------
def part1_doc(n_main, n_glossary):
    main = "## What it is\n\n" + "".join("Sentence %d here. [A4.%04x]\n" % (i, i) for i in range(n_main))
    gloss = "\n## Glossary\n\n" + "".join("term%d: a thing. [A4.%04x]\n" % (i, i) for i in range(n_glossary))
    return "# Part 1: In plain English\n\n" + main + gloss + "\n# Part 2: Appendix\n\n## A4 Notes\n\nThe add command saves a note. `src/cli.py:3` [A4.0001]\n"


class SliceBalanceTest(unittest.TestCase):
    def sizes(self, doc, *extra):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(doc)
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), repo, "--out", Path(d, "out"), *extra)
            return [(s["claims"], s["part1"]) for s in json.loads(Path(d, "out", "slices.json").read_text())]

    def test_69_part_1_claims_make_two_slices_of_35_and_34_not_60_and_9(self):
        """khoj's Part 1: a 60-claim section and a 9-claim glossary were two slices."""
        sizes = self.sizes(part1_doc(60, 9))
        self.assertEqual(sizes, [(35, True), (34, True), (1, False)])

    def test_n_claims_go_into_ceil_n_over_60_slices_of_near_equal_size(self):
        for n in (61, 120, 121, 150):
            sizes = [c for c, p1 in self.sizes(part1_doc(n, 0)) if p1]
            self.assertEqual(len(sizes), -(-n // 60), (n, sizes))
            self.assertLessEqual(max(sizes) - min(sizes), 1, (n, sizes))

    def test_the_slices_still_cover_every_line_once(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            doc = part1_doc(60, 9)
            Path(d, "GUIDE.md").write_text(doc)
            script("slice.py", Path(d, "GUIDE.md"), repo, "--out", Path(d, "out"))
            spans = [(s["first_line"], s["last_line"]) for s in json.loads(Path(d, "out", "slices.json").read_text())]
        self.assertEqual(spans[0][0], 1)
        self.assertEqual(spans[-1][1], len(doc.split("\n")) - 1)
        self.assertEqual([b[0] for a, b in zip(spans, spans[1:])], [a[1] + 1 for a, b in zip(spans, spans[1:])])

    def test_a_list_of_ids_is_balanced_too(self):
        doc = part1_doc(69, 0)
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(doc)
            Path(d, "ids.txt").write_text("\n".join(str(n) for n, l in enumerate(doc.split("\n"), 1) if l.startswith("Sentence")) + "\n")
            script("slice.py", Path(d, "GUIDE.md"), repo, "--ids", Path(d, "ids.txt"), "--out", Path(d, "out"))
            sizes = [s["claims"] for s in json.loads(Path(d, "out", "slices.json").read_text())]
        self.assertEqual(sizes, [35, 34])


# --- defect 3: --record-fixed -------------------------------------------------------------------------------------------------------------
GUIDE_COND = ("# Part 1: In plain English\n\n## What it is\n\nNotes lets you save short notes from the terminal. [A3.0001]\nWho it is for: anyone who takes notes in a terminal. [A3.0001]\n\n## How to start\n\nYou run `notes add` to save one. [A4.0001]\n\n"
              "## What you can do\n\n%s\n\n# Part 2: Appendix\n\n## A3 The product as a whole\n\nNotes saves short notes from the terminal. `src/cli.py:1` [A3.0001]\n\n"
              "## A4 Adding notes\n\nThe `notes add` command saves a note. `src/cli.py:3` [A4.0001]\n%s\n")


class RecordFixedTest(unittest.TestCase):
    A = "It stops after 5 notes. `src/cli.py:7` [A4.0002]"
    P = "You can keep 5 notes a day. [A4.0002]"

    def record(self, verdict):
        guide = GUIDE_COND % (self.P, self.A)
        n = guide.split("\n").index(self.P) + 1
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(guide)
            Path(d, "ids.txt").write_text("%d\n" % n)
            (Path(d) / "rep").mkdir()
            Path(d, "rep", "part1-1.md").write_text("Slice: slice-1\nread | %d.1 | %s | src/cli.py:7\n" % (n, verdict))
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), repo, "--ids", Path(d, "ids.txt"), "--reports", Path(d, "rep"), "--record-fixed", Path(d, "fixed-ids.txt"))
            self.assertEqual(code, 0, err)
            return Path(d, "fixed-ids.txt").read_text()

    def lint(self, fixed, now):
        guide = GUIDE_COND % (now, self.A)
        with tempfile.TemporaryDirectory() as d, make({"src/cli.py": "x\n" * 10}) as repo:
            Path(d, "GUIDE.md").write_text(SNAP + guide)
            Path(d, "surfaces.json").write_text(json.dumps(SURFACES))
            Path(d, "fixed-ids.txt").write_text(fixed)
            return script("lint_main.py", Path(d, "GUIDE.md"), repo, "--surfaces", Path(d, "surfaces.json"), "--fixed", Path(d, "fixed-ids.txt"))

    def test_a_sentence_whose_re_check_holds_is_recorded_as_it_stands(self):
        self.assertEqual(self.record("HOLDS"), "A4.0002 | You can keep 5 notes a day.\n")

    def test_a_sentence_that_failed_its_re_check_is_recorded_as_cut(self):
        for verdict in ("WRONG", "OVERSTATED", "UNSUPPORTED"):
            self.assertEqual(self.record(verdict), "A4.0002 | cut\n", verdict)

    def test_a_sentence_with_no_row_is_recorded_as_cut(self):
        guide = GUIDE_COND % (self.P, self.A)
        n = guide.split("\n").index(self.P) + 1
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(guide)
            Path(d, "ids.txt").write_text("%d\n" % n)
            (Path(d) / "rep").mkdir()
            script("slice.py", Path(d, "GUIDE.md"), repo, "--ids", Path(d, "ids.txt"), "--reports", Path(d, "rep"), "--record-fixed", Path(d, "fixed-ids.txt"))
            self.assertEqual(Path(d, "fixed-ids.txt").read_text(), "A4.0002 | cut\n")

    def test_lint_does_not_warn_when_the_cut_sentence_is_reworded(self):
        """The required cut after fix round 2 used to make `lint --fixed` warn that a fixed sentence was reworded."""
        code, out, err = self.lint(self.record("WRONG"), "You can keep up to 5 notes.  [A4.0002]")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn("warn fixed", out)

    def test_lint_still_warns_when_a_sentence_that_held_is_reworded(self):
        code, out, err = self.lint(self.record("HOLDS"), "You can keep five notes each day. [A4.0002]")
        self.assertIn("warn fixed", out)

    def test_record_fixed_without_reports_is_a_usage_error(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(GUIDE_COND % (self.P, self.A))
            Path(d, "ids.txt").write_text("5\n")
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), repo, "--ids", Path(d, "ids.txt"), "--record-fixed", Path(d, "fixed-ids.txt"))
        self.assertEqual(code, 2)


# --- defect 10: ids are not words ---------------------------------------------------------------------------------------------------------
class WordsTest(unittest.TestCase):
    TWENTY = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen"

    def test_an_id_is_not_a_word_in_the_sentence_limit_of_either_script(self):
        line = "%s. `src/cli.py:2` [A4.0001]" % self.TWENTY  # 18 words and an id
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "doc.md").write_text("## A4 x\n\n%s\n" % line)
            code, out, err = script("check_citations.py", Path(d, "doc.md"), repo, "--max-sentence-words", 18)
            self.assertNotIn("sentence-length", out)
            Path(d, "doc.md").write_text("## A4 x\n\n%s five. `src/cli.py:2` [A4.0001]\n" % self.TWENTY)  # 19 words: the limit is live
            self.assertIn("FAIL sentence-length", script("check_citations.py", Path(d, "doc.md"), repo, "--max-sentence-words", 18)[1])
            guide = "# Part 1: In plain English\n\n## What it is\n\nIt is small. [A4.0001]\nIt is plain. [A4.0001]\n%s. [A4.0001]\n\n# Part 2: Appendix\n\n## A4 x\n\n%s\n" % (self.TWENTY, line)
            Path(d, "GUIDE.md").write_text(SNAP + guide)
            Path(d, "surfaces.json").write_text("[]")
            code, out, err = script("lint_main.py", Path(d, "GUIDE.md"), repo, "--surfaces", Path(d, "surfaces.json"))
        self.assertNotRegex(out, r"sentence-length: \d+ words")

    def test_the_word_count_is_the_same_with_and_without_ids(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            for name, text in (("a.md", "## A4 x\n\nIt saves a note. `src/cli.py:2` [A4.0001]\n"), ("b.md", "## A4 x\n\nIt saves a note. `src/cli.py:2`\n")):
                Path(d, name).write_text(text)
            out_a = script("check_citations.py", Path(d, "a.md"), repo)[1]
            out_b = script("check_citations.py", Path(d, "b.md"), repo)[1]
        self.assertEqual(re.search(r"(\d+) words\n", out_a).group(1), re.search(r"(\d+) words\n", out_b).group(1))

    def test_skill_and_drafting_say_ids_are_not_words(self):
        for name in ("SKILL.md", "references/drafting.md"):
            text = (SKILL / name).read_text()
            self.assertRegex(text, r"(?i)ids[^\n]*not words", name)


# --- defect 18: jargon and source labels --------------------------------------------------------------------------------------------------
class LintWordsTest(unittest.TestCase):
    JARGON = "# jargon\nthread\nendpoint\nendpoints\nserialize\nsqlite\n"

    def hits(self, text):
        guide = ("# Part 1: In plain English\n\n## What it is\n\n%s [A3.0001]\n\n# Part 2: Appendix\n\n## A3 The product as a whole\n\nNotes saves short notes. `src/cli.py:1` [A3.0001]\n" % text)
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(SNAP + guide)
            Path(d, "surfaces.json").write_text("[]")
            Path(d, "jargon.txt").write_text(self.JARGON)
            code, out, err = script("lint_main.py", Path(d, "GUIDE.md"), repo, "--surfaces", Path(d, "surfaces.json"), "--jargon", Path(d, "jargon.txt"))
        m = re.search(r"FAIL jargon: (\d+) hits", out)
        return int(m.group(1)) if m else 0

    def test_a_plural_or_an_ending_counts_as_the_term(self):
        self.assertEqual(self.hits("Threads run. A thread waits."), 2)
        self.assertEqual(self.hits("It serializes, serialized and serializing."), 3)

    def test_a_span_is_counted_once_when_two_terms_match_it(self):
        self.assertEqual(self.hits("Two endpoints answer."), 1)

    def test_a_longer_word_that_only_starts_with_a_term_is_not_a_hit(self):
        self.assertEqual(self.hits("The threadbare notes thread."), 1)

    def test_cli_json_and_http_left_the_list_and_sqlite_stays(self):
        terms = {l.strip().lower() for l in (SKILL / "references/jargon.txt").read_text().splitlines() if l.strip() and not l.startswith("#")}
        self.assertFalse(terms & {"cli", "json", "http", "https"}, terms)
        self.assertTrue({"sqlite", "cron"} <= terms)

    def label(self, appendix, part1, repo_files):
        guide = ("# Part 1: In plain English\n\n## What it is\n\n%s [A3.0001]\n\n# Part 2: Appendix\n\n## A3 The product as a whole\n\n%s `src/cli.py:1` [A3.0001]\n" % (part1, appendix))
        with make(dict(REPO, **repo_files)) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(SNAP + guide)
            Path(d, "surfaces.json").write_text("[]")
            code, out, err = script("lint_main.py", Path(d, "GUIDE.md"), repo, "--surfaces", Path(d, "surfaces.json"))
        return out

    def test_a_md_name_that_is_not_a_repo_file_is_not_a_source_label(self):
        out = self.label("Notes writes its list to notes.md.", "Notes saves its list.", {})
        self.assertNotIn("FAIL label", out)

    def test_a_md_name_that_is_a_repo_file_is_a_source_label(self):
        out = self.label("CONTRACT.md says notes are kept.", "Notes are kept.", {"docs/CONTRACT.md": "x\n"})
        self.assertIn("FAIL label", out)
        self.assertNotIn("FAIL label", self.label("CONTRACT.md says notes are kept.", "CONTRACT.md says notes are kept.", {"docs/CONTRACT.md": "x\n"}))


# --- the skill text -----------------------------------------------------------------------------------------------------------------------
class SkillTextTest(unittest.TestCase):
    SKILL_TEXT = (SKILL / "SKILL.md").read_text()
    FIX_FILE = SKILL / "references/fix-rounds.md"

    def test_step_9_names_who_fixes_and_who_cuts(self):
        step = self.SKILL_TEXT.split("9. **Check every claim.**")[1].split("10. **Score.**")[0]
        self.assertRegex(step, r"the lead fixes appendix findings")
        self.assertRegex(step, r"the lead then cuts or narrows what still fails")
        self.assertRegex(step, r"missing condition also goes to its tagged appendix line")

    def test_fix_rounds_reruns_check_citations_before_slice_ids(self):
        fix = self.FIX_FILE.read_text()
        self.assertLess(fix.index("check_citations.py"), fix.index("--ids changed.txt --out"))
        self.assertRegex(fix, r"in the same round")
        self.assertRegex(fix, r"After fix round 2 the lead cuts, or narrows to what the code shows, each sentence that still fails, a Part 1 sentence included")

    def test_step_5_lists_choice_md_among_the_files_the_audit_wants(self):
        step = self.SKILL_TEXT.split("5. **Frame and section writers.**")[1].split("6. **Part 1.**")[0]
        for name in ("work/choice.md", "work/guards.md", "work/evidence.md"):
            self.assertIn(name, step)


if __name__ == "__main__":
    unittest.main()
