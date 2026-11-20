"""The round 3 changes to the general deriving-readable-docs skill, each run as the skill runs it (a script on files). Each test breaks one rule.
Round 2 data (the khoj-opus slice-4 report, lines of the round 2 guides) are the fixtures: tests/deriving-readable-docs/fixtures/round2/.
Run: python3 -I tests/deriving-readable-docs/test_round3.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"
ROUND2 = HERE / "fixtures/round2"
SURFACES = [{"kind": "command", "name": "notes add", "file": "src/cli.py", "line": 3}, {"kind": "flag", "name": "--tag <name>", "file": "src/cli.py", "line": 5}]


def script(name, *args, cwd=None):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / name), *map(str, args)], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def make(files):
    tmp = tempfile.TemporaryDirectory()
    for rel, text in files.items():
        p = Path(tmp.name) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp


# --- change 1: the checker depth floor -------------------------------------------------------------------------------
DOC = ("# Part 1: In plain English\n\n## What it is\n\nIt saves notes. [A4.0001]\n\n# Part 2: Appendix\n\n## A4 Notes\n\n"
       "The add command saves a note. `src/cli.py:3` [A4.0001]\nIt stops after 5 notes. `src/cli.py:7` [A4.0002]\n")
REPO = {"src/cli.py": "x\n" * 10}


def counts(claims, holds, wrong=0, over=0, unsup=0):
    return "Counts: claims checked %d; HOLDS %d; WRONG %d; OVERSTATED %d; UNSUPPORTED %d.\n" % (claims, holds, wrong, over, unsup)


class DepthFloorScoreTest(unittest.TestCase):
    def score(self, reports, doc=DOC, slices=True):
        """Cut DOC into slices, write the reports (name -> text), score them with --slices; return (code, out, err)."""
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(doc)
            script("slice.py", Path(d, "GUIDE.md"), repo, "--out", Path(d, "slices"))
            (Path(d) / "reports").mkdir()
            for name, text in reports.items():
                Path(d, "reports", name).write_text(text)
            extra = ["--slices", Path(d, "slices")] if slices else []
            return script("score.py", Path(d, "reports"), "--repo", repo, *extra)

    P1 = "Slice: slice-1\nread | 5.1 | HOLDS | src/cli.py:3\n" + counts(1, 1)
    A = ("Slice: slice-2\nread | 11.1 | HOLDS | src/cli.py:3\nread | 12.1 | HOLDS | src/cli.py:7\n" + counts(2, 2))

    def test_a_report_with_a_row_and_a_line_for_every_claim_of_its_slice_passes(self):
        code, out, err = self.score({"part1-1.md": self.P1, "slice-2.md": self.A})
        self.assertEqual(code, 0, err + out)
        self.assertIn("claims checked: 3", out)

    def test_a_finding_line_headed_by_a_claim_id_is_counted(self):
        found = ("Slice: slice-2\nread | 11.1 | HOLDS | src/cli.py:3\nread | 12.1 | WRONG | src/cli.py:7\n"
                 "12.1 | WRONG | NAME | the words | what the code shows (src/cli.py:7) | the fix\n" + counts(2, 1, wrong=1))
        code, out, err = self.score({"part1-1.md": self.P1, "slice-2.md": found})
        self.assertEqual(code, 0, err + out)
        self.assertIn("NAME", out)

    def test_a_report_that_lacks_a_row_for_a_claim_of_its_slice_fails_and_names_it(self):
        short = "Slice: slice-2\nread | 11.1 | HOLDS | src/cli.py:3\n" + counts(1, 1)
        code, out, err = self.score({"part1-1.md": self.P1, "slice-2.md": short})
        self.assertEqual(code, 1)
        self.assertIn("slice-2.md", err)
        self.assertIn("12.1", err)

    def test_a_row_with_no_line_fails_even_for_holds(self):
        bare = "Slice: slice-2\nread | 11.1 | HOLDS | src/cli.py\nread | 12.1 | HOLDS | src/cli.py:7\n" + counts(2, 2)
        code, out, err = self.score({"part1-1.md": self.P1, "slice-2.md": bare})
        self.assertEqual(code, 1)
        self.assertIn("11.1", err)
        self.assertIn("path:line", err)

    def test_a_row_whose_line_is_not_in_the_repo_fails(self):
        far = self.A.replace("src/cli.py:7", "src/cli.py:99")
        code, out, err = self.score({"part1-1.md": self.P1, "slice-2.md": far})
        self.assertEqual(code, 1)
        self.assertIn("src/cli.py:99", err)

    def test_the_rows_must_add_up_to_the_counts_line(self):
        lie = self.A.replace("HOLDS 2; WRONG 0", "HOLDS 1; WRONG 1").replace("Counts:", "11 | WRONG | NAME | x | y (src/cli.py:3) | z\nCounts:")
        code, out, err = self.score({"part1-1.md": self.P1, "slice-2.md": lie})
        self.assertEqual(code, 1)
        self.assertIn("rows", err)

    def test_a_report_in_the_old_format_has_no_rows_and_is_refused_by_name(self):
        """The round 2 slice-4 report of khoj-opus marked 96 of 96 claims HOLDS and shows nothing it read: the depth floor cannot pass it."""
        with tempfile.TemporaryDirectory() as d:
            code, out, err = script("score.py", ROUND2 / "khoj-opus")
        self.assertEqual(code, 1)
        self.assertIn("slice-4.md", err)
        self.assertIn("read |", err)

    def test_an_untagged_glossary_entry_takes_outside_for_its_line_and_no_other_claim_may(self):
        doc = DOC.replace("# Part 2: Appendix", "## Glossary\n\nslug: a short name in a web address.\n\n# Part 2: Appendix")
        a = self.A.replace("11.1", "15.1").replace("12.1", "16.1")
        ok = "Slice: slice-1\nread | 5.1 | HOLDS | src/cli.py:3\nread | 9.1 | HOLDS | outside\n" + counts(2, 2)
        self.assertEqual(self.score({"part1-1.md": ok, "slice-2.md": a}, doc)[0], 0)
        bad = ok.replace("5.1 | HOLDS | src/cli.py:3", "5.1 | HOLDS | outside")
        code, out, err = self.score({"part1-1.md": bad, "slice-2.md": a}, doc)
        self.assertEqual(code, 1)
        self.assertIn("5.1", err)

    def test_without_slices_the_rows_are_still_required(self):
        code, out, err = self.score({"slice-2.md": "read | 1.1 | HOLDS | src/cli.py:3\n" + counts(1, 1)}, slices=False)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.score({"slice-2.md": counts(1, 1)}, slices=False)[0], 1)


# --- change 1 and 7: slice.py ------------------------------------------------------------------------------------------
def big_doc(n):
    return "# Part 2: Appendix\n\n## A4 Notes\n\n" + "".join("It does thing %d. `src/cli.py:2` [A4.%04x]\n" % (i, i) for i in range(n))


class SliceTest(unittest.TestCase):
    def slices(self, doc, *extra, files=None):
        with make(files or REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(doc)
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), repo, "--out", Path(d, "out"), *extra)
            got = {p.name: p.read_text() for p in Path(d, "out").glob("*")} if Path(d, "out").exists() else {}
        return code, out, err, got

    def test_a_slice_never_holds_more_than_60_claims_even_inside_one_section(self):
        code, out, err, files = self.slices(big_doc(150))
        self.assertEqual(code, 0, err)
        sizes = [s["claims"] for s in json.loads(files["slices.json"])]
        self.assertEqual((sum(sizes), max(sizes)), (150, 60))

    def test_a_limit_above_60_is_a_usage_error(self):
        self.assertEqual(self.slices(big_doc(5), "--max-claims", "61")[0], 2)

    def test_each_slice_writes_its_claim_ids_one_a_line(self):
        code, out, err, files = self.slices(DOC)
        self.assertEqual(files["slice-1.claims.txt"], "5.1 | claim | It saves notes. [A4.0001]\n")
        self.assertEqual(files["slice-2.claims.txt"], "11.1 | claim | The add command saves a note. [A4.0001]\n12.1 | claim | It stops after 5 notes. [A4.0002]\n")
        self.assertTrue(json.loads(files["slices.json"])[0]["part1"])
        self.assertFalse(json.loads(files["slices.json"])[1]["part1"])

    def test_an_untagged_glossary_entry_is_marked_outside(self):
        doc = DOC.replace("# Part 2: Appendix", "## Glossary\n\nslug: a short name in a web address.\ncache: a store. [A4.0002]\n\n# Part 2: Appendix")
        files = self.slices(doc)[3]
        self.assertIn("| outside | slug: a short name in a web address.", files["slice-1.claims.txt"])
        self.assertIn("| claim | cache: a store.", files["slice-1.claims.txt"])

    def test_a_list_of_ids_cuts_slices_of_only_those_sentences(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "ids.txt").write_text("# changed\n12\nA4.0001\n")
            code, out, err, files = self.slices(DOC, "--ids", str(Path(d, "ids.txt")))
        self.assertEqual(code, 0, err)
        self.assertEqual(files["slice-1.claims.txt"], "11.1 | claim | The add command saves a note. [A4.0001]\n12.1 | claim | It stops after 5 notes. [A4.0002]\n")
        self.assertEqual(len([n for n in files if n.endswith(".claims.txt")]), 1)

    def test_an_id_that_is_nowhere_in_the_doc_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "ids.txt").write_text("A4.dead\n")
            code, out, err, files = self.slices(DOC, "--ids", str(Path(d, "ids.txt")))
        self.assertEqual(code, 1)
        self.assertIn("A4.dead", err)


# --- change 2: line numbers -------------------------------------------------------------------------------------------
FORM_FEED = "line one\n\f(setq a 1)\nline three\n\fline four\nthe target\nlast\n"


class LineNumberTest(unittest.TestCase):
    def test_a_form_feed_does_not_shift_the_numbers_a_cited_line_gets(self):
        """cat -n and the Read tool count only newlines: the target is line 5. splitlines() cut at the form feeds and called it line 7."""
        doc = "## A4 x\n\nThe target is named. `src/a.el:5` [A4.0001]\n"
        with make({"src/a.el": FORM_FEED}) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "doc.md").write_text(doc)
            code, out, err = script("check_citations.py", Path(d, "doc.md"), repo, "--sheet")
        self.assertIn("     5  the target", out)

    def test_the_file_has_as_many_lines_as_cat_n_numbers(self):
        """cat -n numbers 6 lines; splitlines() found 8, so a citation of line 7 passed."""
        doc = "## A4 x\n\nIt ends. `src/a.el:7` [A4.0001]\n"
        with make({"src/a.el": FORM_FEED}) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "doc.md").write_text(doc)
            code, out, err = script("check_citations.py", Path(d, "doc.md"), repo)
        self.assertIn("line out of range (file has 6 lines)", out)

    def test_show_prints_a_range_numbered_as_cat_n_numbers_it(self):
        with make({"src/a.el": FORM_FEED}) as repo:
            code, out, err = script("check_citations.py", "--show", "src/a.el:4-5", repo)
            cat = subprocess.run(["cat", "-n", "src/a.el"], capture_output=True, text=True, cwd=repo).stdout.split("\n")
        self.assertEqual(code, 0, err)
        self.assertEqual([l.split(None, 1)[0] for l in out.split("\n")[1:3]], ["4", "5"])
        self.assertIn("the target", out)
        self.assertEqual(cat[4].split("\t")[0].strip(), "5")

    def test_show_of_a_line_that_is_not_there_fails(self):
        with make({"src/a.el": FORM_FEED}) as repo:
            code, out, err = script("check_citations.py", "--show", "src/a.el:3-9", repo)
        self.assertEqual(code, 1)

    def test_drafting_sends_writers_to_show_not_cat_n(self):
        text = (SCRIPTS.parent / "references/drafting.md").read_text()
        self.assertIn("--show", text)
        self.assertNotRegex(text, r"(?i)use `Read`, or `cat -n`")


class FixRoundScoreTest(unittest.TestCase):
    def test_a_fix_round_report_is_scored_against_its_own_slices_folder(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(DOC, encoding="utf-8")
            script("slice.py", Path(d, "GUIDE.md"), repo, "--out", Path(d, "slices"))
            Path(d, "changed.txt").write_text("12.1\n", encoding="utf-8")
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), repo, "--ids", Path(d, "changed.txt"), "--out", Path(d, "slices-fix1"),
                                    "--record-fixed", Path(d, "fixed-ids.txt"))
            self.assertEqual(code, 0, err)
            Path(d, "r1").mkdir()
            Path(d, "r1", "part1-1.md").write_text("Slice: slice-1\nread | 5.1 | HOLDS | src/cli.py:3\n" + counts(1, 1), encoding="utf-8")
            Path(d, "r1", "slice-2.md").write_text("Slice: slice-2\nread | 11.1 | HOLDS | src/cli.py:3\nread | 12.1 | HOLDS | src/cli.py:7\n" + counts(2, 2), encoding="utf-8")
            Path(d, "r2").mkdir()
            Path(d, "r2", "slice-1.md").write_text("Slice: slice-1\nread | 12.1 | HOLDS | src/cli.py:7\n" + counts(1, 1), encoding="utf-8")
            first = script("score.py", Path(d, "r1"), "--repo", repo, "--slices", Path(d, "slices"))
            fix = script("score.py", Path(d, "r2"), "--repo", repo, "--slices", Path(d, "slices-fix1"))
            wrong = script("score.py", Path(d, "r2"), "--repo", repo, "--slices", Path(d, "slices"))
        self.assertEqual(first[0], 0, first[1] + first[2])
        self.assertEqual(fix[0], 0, fix[1] + fix[2])
        self.assertEqual(wrong[0], 1, "the first round's slice-1 holds other claims")


class FindingCountMessageTest(unittest.TestCase):
    def test_a_missing_finding_line_error_names_the_claim_id_form(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "r").mkdir()
            Path(d, "r", "slice-1.md").write_text("Slice: slice-1\nread | 1.1 | WRONG | src/cli.py:3\n" + counts(1, 0, wrong=1), encoding="utf-8")
            code, out, err = script("score.py", Path(d, "r"), "--repo", repo)
        self.assertEqual(code, 1)
        self.assertIn("`claim id | verdict | CAUSE | ...`", err)


# --- change 2 again: a form feed in a doc line does not shift the doc's line numbers --------------------------------------------
FF_REPO = {
    "src/a.ts": "export function run(x: number) {\n  if (!x) return 1;\n  if (x > 5) throw new Error('big');\n  return doIt(x);\n}\n",
    "src/cli.py": "x\n" * 10,
}
FF_DOC = ("# Part 1: In plain English\n\n## What it is\f\n\nIt saves notes. [A4.aaaa]\n\n# Part 2: Appendix\n\n## A4 Notes\f\n\n"
          "It calls doIt with the number. `src/a.ts:4` [A4.aaaa]\nIt stops after 5 notes. `src/cli.py:7` [A4.bbbb]\n")


class FormFeedDocTest(unittest.TestCase):
    def test_a_claim_id_counts_lines_on_newlines_only(self):
        with make(FF_REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(FF_DOC, encoding="utf-8")
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), repo, "--out", Path(d, "s"))
            claims = "".join(p.read_text() for p in sorted(Path(d, "s").glob("*.claims.txt")))
        self.assertEqual(code, 0, err)
        self.assertIn("5.1 | claim | It saves notes.", claims)
        self.assertIn("11.1 | claim | It calls doIt with the number.", claims)

    def test_stamp_gives_each_line_its_own_id_when_a_heading_holds_a_form_feed(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d, "A3.md")
            f.write_text("## A3 x\f\n\nIt runs. `src/cli.py:1`\nIt stops. `src/cli.py:2`\n", encoding="utf-8")
            code, out, err = script("stamp.py", f)
            lines = f.read_text(encoding="utf-8").split("\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(lines[0], "## A3 x\f")
        self.assertEqual(len(lines), 5)
        self.assertRegex(lines[2], r"It runs\. `src/cli.py:1` \[A3\.\w{4}\]$")
        self.assertRegex(lines[3], r"It stops\. `src/cli.py:2` \[A3\.\w{4}\]$")

    def test_a_part_1_tag_finds_its_appendix_sentence_when_headings_before_it_hold_a_form_feed(self):
        doc = ("# Part 1: In plain English\n\n## What it is\f\n\nIt stops after 5 notes. [A4.bbbb]\n\n# Part 2: Appendix\n\n## A4 Notes\f\n\n"
               "It calls doIt with the number. `src/a.ts:4` [A4.aaaa]\nIt stops after 5 notes. `src/cli.py:7` [A4.bbbb]\n")
        with make(FF_REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(doc, encoding="utf-8")
            Path(d, "surfaces.json").write_text(json.dumps(SURFACES), encoding="utf-8")
            code, out, err = script("lint_main.py", Path(d, "GUIDE.md"), repo, "--surfaces", Path(d, "surfaces.json"))
        self.assertNotIn("appendix-match", out + err)
        self.assertNotIn("A4.bbbb", out + err)

    def test_a_guard_is_covered_by_an_id_when_the_headings_before_it_hold_a_form_feed(self):
        audit = ('3 | assert: src/a.ts:4 "return doIt(x);" | exits: src/a.ts:2 off the path: x is zero; src/a.ts:3 off the path: x over 5 | callers: none found | found: nothing | result: HOLDS\n')
        guards = "guard | src/a.ts:2 | return | if (!x) return 1; | covered: not relevant: zero is another case\nguard | src/a.ts:3 | throw | if (x > 5) throw new Error('big'); | covered: A4.aaaa\n"
        evidence = '`src/a.ts:4` | "return doIt(x);" | called with a number\n'
        doc = "## A4 Running\f\n\nIt calls doIt with the number. `src/a.ts:4` [A4.aaaa]\n"
        with make(FF_REPO) as repo, tempfile.TemporaryDirectory() as d:
            for name, text in (("audit.md", audit), ("guards.md", guards), ("evidence.md", evidence), ("doc.md", doc)):
                Path(d, name).write_text(text, encoding="utf-8")
            code, out, err = script("check_citations.py", Path(d, "doc.md"), repo, "--audit", Path(d, "audit.md"))
        self.assertEqual(code, 0, out + err)

    def test_part_1_is_cut_at_the_heading_line_not_at_a_form_feed(self):
        doc = ("# Part 1: In plain English\n\n## What it is\n\nIt saves notes. [A4.aaaa]\n\n\x0c## Part 2 is not here\n\nIt stops. [A4.bbbb]\n\n"
               "# Part 2: Appendix\n\n## A4 Notes\n\nIt saves a note. `src/cli.py:3` [A4.aaaa]\n")
        with make(FF_REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(doc, encoding="utf-8")
            code, out, err = script("score.py", "--reader", Path(d, "GUIDE.md"))
        self.assertEqual(code, 0, err)
        self.assertIn("It stops.", out)

    def test_a_form_feed_line_does_not_open_a_heading(self):
        doc = "# Guide\n\nIt saves notes.\x0c## Looks like a heading\nIt stops. `src/cli.py:3`\n"
        with make(FF_REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(doc, encoding="utf-8")
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), repo)
        self.assertEqual(code, 0, err)
        self.assertIn("2 claims", out)


class UsageTest(unittest.TestCase):
    def test_score_with_a_slices_folder_that_is_not_there_exits_2(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "r").mkdir()
            Path(d, "r", "slice-1.md").write_text("Slice: slice-1\n" + counts(0, 0), encoding="utf-8")
            code, out, err = script("score.py", Path(d, "r"), "--repo", repo, "--slices", Path(d, "nowhere"))
        self.assertEqual(code, 2, out + err)

    def test_slice_with_an_ids_file_that_is_not_there_exits_2(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(DOC, encoding="utf-8")
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), repo, "--ids", Path(d, "nope.txt"))
        self.assertEqual(code, 2, err)

    def test_record_fixed_without_ids_exits_2(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(DOC, encoding="utf-8")
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), repo, "--record-fixed", Path(d, "fixed.txt"))
            self.assertFalse(Path(d, "fixed.txt").exists())
        self.assertEqual(code, 2, err)

    def test_a_quote_that_is_part_of_a_line_of_the_cited_range_is_found(self):
        doc = "## A4 Notes\n\nIt stops after 5 notes. `src/cli.py:2-3` [A4.aaaa]\n"
        evidence = '`src/cli.py:2` | "limit = 5" | the limit\n`src/cli.py:3` | "stop()" | it stops\n'
        audit = '3 | assert: src/cli.py:2 "limit = 5" | exits: none listed | callers: none found | found: nothing | result: HOLDS\n'
        repo_files = {"src/cli.py": "def run():\n    limit = 5  # the cap\n    stop()  # then stop\n"}
        with make(repo_files) as repo, tempfile.TemporaryDirectory() as d:
            for name, text in (("audit.md", audit), ("guards.md", "# guards\n"), ("evidence.md", evidence), ("doc.md", doc)):
                Path(d, name).write_text(text, encoding="utf-8")
            code, out, err = script("check_citations.py", Path(d, "doc.md"), repo, "--audit", Path(d, "audit.md"))
        self.assertNotIn("no evidence row", out + err)


# --- change 3: --resolve takes the definition, in the product ---------------------------------------------------------------
AGENT_KIT = {
    "package.json": '{\n  "name": "kit"\n}\n',
    "scripts/consumer-smoke.mjs": "const board = await openBoard();\nconst jobs = [];\nfunction reach() {}\nconst traces = 1;\nconst send = () => 1;\nfunction onlyInScripts() {}\n",
    "src/board/cli.ts": "export function run(argv: string[], { program = 'board' }: CliEnv): number {\n  const [command] = argv;\n  if (command === 'board') return 1;\n  return 0;\n}\n",
    "src/jobs/cli.ts": "export function run(argv: string[], { program = 'jobs' }: CliEnv): number {\n  const [command] = argv;\n  if (command === 'jobs') return 1;\n  return 0;\n}\n",
    "src/reach/cli.ts": "export function run(argv: string[], { program = 'reach' }: CliEnv): number {\n  const [command] = argv;\n  if (command === 'reach') return 1;\n  if (command === 'send') return 2;\n  return 0;\n}\n",
    "src/traces/cli.ts": "export function run(argv: string[], { program = 'traces' }: CliEnv): number {\n  const [command] = argv;\n  if (command === 'traces') return 1;\n  return 0;\n}\n",
    "src/board/usecases/write.ts": "async function send(action: Action): Promise<unknown> {\n  return action;\n}\n",
    "test/fixture.ts": "const onlyInTests = 1;\n",
}


class ResolveTest(unittest.TestCase):
    def resolve(self, names, files=AGENT_KIT):
        with make(files) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "n.txt").write_text(names)
            code, out, err = script("surfaces.py", repo, "--resolve", Path(d, "n.txt"))
        return dict(l.split(" | ") for l in out.splitlines())

    def test_a_command_the_scan_finds_resolves_to_it_not_to_a_script_or_an_unrelated_function(self):
        got = self.resolve("board\njobs\nreach\ntraces\nsend\n")
        self.assertEqual({k: v.split(":")[0] for k, v in got.items()},
                         {"board": "src/board/cli.ts", "jobs": "src/jobs/cli.ts", "reach": "src/reach/cli.ts", "traces": "src/traces/cli.ts", "send": "src/reach/cli.ts"})

    def test_a_name_in_a_script_or_a_test_only_is_a_weak_match(self):
        got = self.resolve("onlyInScripts\nonlyInTests\nnowhere\n")
        self.assertEqual(got["onlyInScripts"], "WEAK MATCH scripts/consumer-smoke.mjs:6")
        self.assertEqual(got["onlyInTests"], "WEAK MATCH test/fixture.ts:1")
        self.assertEqual(got["nowhere"], "NOT FOUND")

    def test_a_definition_in_the_product_beats_a_scripts_hit_that_comes_first(self):
        files = {"scripts/a.mjs": "function build() {}\n", "src/b.ts": "export function build() {}\n"}
        self.assertEqual(self.resolve("build\n", files)["build"], "src/b.ts:1")

    def test_assemble_counts_weak_matches_in_the_header_and_does_not_print_them_in_a1(self):
        files = {"surfaces.json": json.dumps(SURFACES), "scout.resolved": "add | src/cli.py:3\nweak | WEAK MATCH scripts/x.mjs:2\nteleport | NOT FOUND\n",
                 "A3.md": "## A3 The product\n\nIt saves notes. `src/cli.py:1` [A3.0001]\n", "part1.md": "## What it is\n\nIt saves notes. [A3.0001]\n"}
        with make({**REPO, **{"work/" + k: v for k, v in files.items()}}) as d:
            code, out, err = script("assemble.py", Path(d, "work"), d, "--date", "2026-11-20", "-o", Path(d, "G.md"))
            guide = Path(d, "G.md").read_text()
        self.assertEqual(code, 0, err)
        self.assertIn("1 scout names found, 1 not found and dropped, 1 weak matches", guide)
        self.assertNotIn("scout | weak", guide)


# --- change 4: evidence rows ---------------------------------------------------------------------------------------------
HANDLER = ('def delete(slug):\n    raise HTTPException(status_code=404, detail="Agent not found")\n'
           '    query = f"select `id` from agents where slug = {slug}"\n    return ok\n')


class EvidenceRowTest(unittest.TestCase):
    def audit(self, evidence, cite="src/h.py:2"):
        doc = "## A4 x\n\nA missing agent is a 404. `%s` [A4.aaaa]\n" % cite
        n = 3
        audit = '%d | assert: src/h.py:2 "raise HTTPException(status_code=404, detail=" | exits: none listed | callers: none found | found: nothing | result: HOLDS\n' % n
        with make({"src/h.py": HANDLER}) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "doc.md").write_text(doc)
            Path(d, "audit.md").write_text(audit)
            Path(d, "guards.md").write_text("# guards\n")
            Path(d, "evidence.md").write_text(evidence)
            code, out, err = script("check_citations.py", Path(d, "doc.md"), repo, "--audit", Path(d, "audit.md"))
        return [l for l in out.splitlines() if "FAIL evidence" in l]

    def test_a_row_that_copies_a_line_with_double_quotes_whole_passes(self):
        row = '| 1 | `src/h.py:2` | "raise HTTPException(status_code=404, detail="Agent not found")" | the route | 404 | yes | none |\n'
        self.assertEqual(self.audit(row), [])

    def test_a_row_that_copies_a_line_with_backticks_whole_passes(self):
        row = '| 1 | `src/h.py:3` | "query = f"select `id` from agents where slug = {slug}"" | the route | a query | yes | none |\n'
        self.assertEqual(self.audit(row, "src/h.py:3"), [])

    def test_a_row_that_diverges_from_its_line_after_an_inner_quote_fails(self):
        """The row text read as far as the first inner quote only (`raise HTTPException(status_code=404, detail=`), so a row copied wrongly passed."""
        row = '| 1 | `src/h.py:2` | "raise HTTPException(status_code=404, detail="Agent missing")" | the route | 404 | yes | none |\n'
        self.assertEqual(len(self.audit(row)), 1)

    def test_a_row_that_diverges_from_its_line_after_a_backtick_fails(self):
        row = '| 1 | `src/h.py:3` | "query = f"select `name` from agents where slug = {slug}"" | the route | a query | yes | none |\n'
        self.assertEqual(len(self.audit(row, "src/h.py:3")), 1)

    def test_a_range_row_may_quote_any_line_of_its_range(self):
        row = '| 1 | `src/h.py:2-4` | "return ok" | the route | ok | yes | none |\n'
        self.assertEqual(self.audit(row), [])

    def test_a_quote_that_is_not_on_any_line_of_the_range_still_fails(self):
        row = '| 1 | `src/h.py:2-4` | "raise HTTPException(status_code=500)" | the route | 404 | yes | none |\n'
        self.assertEqual(len(self.audit(row)), 1)

    def test_a_single_line_row_with_the_text_of_another_line_still_fails(self):
        row = '| 1 | `src/h.py:2` | "return ok" | the route | ok | yes | none |\n'
        self.assertEqual(len(self.audit(row)), 1)


# --- change 5: one sentence a line, and the default rule -------------------------------------------------------------------------------
class StampSentenceTest(unittest.TestCase):
    def stamp(self, text):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "A4.md").write_text(text)
            code, out, err = script("stamp.py", Path(d, "A4.md"))
            return code, out, Path(d, "A4.md").read_text()

    def test_a_line_with_two_sentences_is_refused_and_the_message_names_the_fix(self):
        code, out, after = self.stamp("## A4 x\n\nIt runs. `a.py:1` It stops. `a.py:2`\n")
        self.assertEqual(code, 1)
        self.assertIn("A4.md:3", out)
        self.assertIn("one sentence", out)
        self.assertEqual(after, "## A4 x\n\nIt runs. `a.py:1` It stops. `a.py:2`\n")

    def test_a_stamped_line_that_later_got_a_second_sentence_is_refused_too(self):
        self.assertEqual(self.stamp("## A4 x\n\nIt runs. It stops. `a.py:1` [A4.0001]\n")[0], 1)

    def test_one_sentence_per_line_is_stamped_as_before(self):
        code, out, after = self.stamp("## A4 x\n\nIt runs. `a.py:1`\nIt stops, unless told. `a.py:2`\n")
        self.assertEqual(code, 0, out)
        self.assertEqual(after.count("[A4."), 2)

    def test_a_dotted_name_or_number_inside_a_sentence_is_not_a_second_sentence(self):
        self.assertEqual(self.stamp("## A4 x\n\nIt reads `a.py` v1.2 and stops after 3.5 seconds. `a.py:1`\n")[0], 0)

    def test_assemble_refuses_a_two_sentence_line_too(self):
        files = {"surfaces.json": "[]", "part1.md": "## What it is\n\nIt runs. [A3.0001]\n",
                 "A3.md": "## A3 x\n\nIt runs. It stops. `src/cli.py:1` [A3.0001]\n"}
        with make({**REPO, **{"work/" + k: v for k, v in files.items()}}) as d:
            code, out, err = script("assemble.py", Path(d, "work"), d, "-o", Path(d, "G.md"))
        self.assertEqual(code, 1)
        self.assertIn("one sentence", err)

    def test_drafting_lays_sentences_out_one_a_line(self):
        text = (SCRIPTS.parent / "references/drafting.md").read_text()
        self.assertRegex(text, r"(?i)one sentence (on |a |per |to a )(each )?line")
        self.assertNotIn("short paragraphs or list items", text)


GUIDE_COND = """# Part 1: In plain English

## What it is

Notes lets you save short notes from the terminal. [A3.0001]

## How to start

Run `notes add` to save your first note. [A4.0001]

## What you can do

%s

# Part 2: Appendix

## A3 The product as a whole

Notes saves short notes from the terminal. `src/cli.py:1` [A3.0001]

## A4 Adding notes

The `notes add` command saves a note. `src/cli.py:3` [A4.0001]
%s
"""


def lint(guide, *extra):
    with make({"src/cli.py": "x\n" * 10}) as repo, tempfile.TemporaryDirectory() as d:
        Path(d, "GUIDE.md").write_text(guide)
        Path(d, "surfaces.json").write_text(json.dumps(SURFACES))
        code, out, err = script("lint_main.py", Path(d, "GUIDE.md"), repo, "--surfaces", Path(d, "surfaces.json"), *extra)
    return code, out


def cond_guide(part1, appendix):
    return GUIDE_COND % (part1, appendix + " [A4.0002]")


class ByDefaultTest(unittest.TestCase):
    def test_by_default_does_not_stand_in_for_a_condition_the_appendix_line_holds(self):
        guide = cond_guide("You can keep 5 notes a day by default. [A4.0002]", "It stops after 5 notes unless you use the flag. `src/cli.py:7`")
        code, out = lint(guide)
        self.assertEqual(code, 1)
        self.assertIn("FAIL condition:", out)

    def test_by_default_passes_when_the_appendix_sentence_states_a_default(self):
        guide = cond_guide("You can keep 5 notes a day by default. [A4.0002]", "It stops after 5 notes unless the limit is set, which defaults to 5. `src/cli.py:7`")
        self.assertEqual(lint(guide)[0], 0, lint(guide)[1])

    def test_naming_the_condition_still_passes(self):
        guide = cond_guide("You can keep 5 notes a day unless you use the flag. [A4.0002]", "It stops after 5 notes unless you use the flag. `src/cli.py:7`")
        self.assertEqual(lint(guide)[0], 0, lint(guide)[1])

    def test_the_very_next_sentence_with_the_same_tag_may_carry_the_condition(self):
        guide = cond_guide("You can keep 5 notes a day. [A4.0002]\nThat holds unless you use the flag. [A4.0002]", "It stops after 5 notes unless you use the flag. `src/cli.py:7`")
        self.assertEqual(lint(guide)[0], 0, lint(guide)[1])

    def test_a_next_sentence_with_another_tag_does_not(self):
        guide = cond_guide("You can keep 5 notes a day. [A4.0002]\nThat holds unless you use the flag. [A3.0001]", "It stops after 5 notes unless you use the flag. `src/cli.py:7`")
        self.assertIn("FAIL condition:", lint(guide)[1])


# --- change 6: otherwise, without and when count only where they open a clause --------------------------------------------------------
class ClauseWordTest(unittest.TestCase):
    """Lines of the round 2 guides: a Part 1 fix that dropped a plain `without` was refused for it."""
    def refused(self, appendix, part1="It saves 5 notes a day. [A4.0002]"):
        return "FAIL condition:" in lint(cond_guide(part1, appendix + " `src/cli.py:7`"))[1]

    def test_without_as_a_preposition_is_not_a_condition(self):
        self.assertFalse(self.refused("Per the README, npm install fails with a 401 without a read:packages token.", "Per the README, npm install fails with a 401. [A4.0002]"))
        self.assertFalse(self.refused("Sharing copies a conversation into a public one that anyone can read without sign-in."))

    def test_without_that_opens_a_clause_is_one(self):
        self.assertTrue(self.refused("It runs, without asking first."))
        self.assertTrue(self.refused("Without a token, it fails."))

    def test_when_that_opens_a_clause_is_one_in_the_middle_of_a_sentence_too(self):
        self.assertTrue(self.refused("It returns 401 when the key is missing."))
        self.assertTrue(self.refused("When the key is missing, it returns 401."))

    def test_a_word_inside_a_quoted_message_or_a_code_name_is_not_the_sentences_own_condition(self):
        self.assertFalse(self.refused('It prints "Unable to run when offline."'))
        self.assertFalse(self.refused("It reads the `whenReady` hook."))

    def test_otherwise_counts_only_at_the_start_of_a_clause(self):
        self.assertTrue(self.refused("It stops at 5; otherwise it goes on."))
        self.assertFalse(self.refused("It stops at 5 or otherwise ends the loop."))


# --- change 7: the fixed-ids file --------------------------------------------------------------------------------------------------------
P1 = "Notes lets you save short notes from the terminal. [A3.0001]"


class FixedSentenceTest(unittest.TestCase):
    def test_slice_records_the_part_1_sentences_it_re_checks_keyed_by_their_tags(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(DOC)
            Path(d, "ids.txt").write_text("5\n12\n")
            code, out, err = script("slice.py", Path(d, "GUIDE.md"), repo, "--ids", Path(d, "ids.txt"), "--out", Path(d, "o"), "--record-fixed", Path(d, "fixed-ids.txt"))
            text = Path(d, "fixed-ids.txt").read_text()
        self.assertEqual(code, 0, err)
        self.assertEqual(text, "A4.0001 | It saves notes.\n")

    def test_a_later_record_for_the_same_tags_replaces_the_row(self):
        with make(REPO) as repo, tempfile.TemporaryDirectory() as d:
            Path(d, "ids.txt").write_text("5\n")
            Path(d, "fixed-ids.txt").write_text("A4.0001 | An older text.\n")
            Path(d, "GUIDE.md").write_text(DOC)
            script("slice.py", Path(d, "GUIDE.md"), repo, "--ids", Path(d, "ids.txt"), "--out", Path(d, "o"), "--record-fixed", Path(d, "fixed-ids.txt"))
            self.assertEqual(Path(d, "fixed-ids.txt").read_text(), "A4.0001 | It saves notes.\n")

    def lint_fixed(self, fixed, part1):
        guide = GUIDE_COND % (part1, "It stops after 5 notes. `src/cli.py:7` [A4.0002]")
        with tempfile.TemporaryDirectory() as d:
            Path(d, "fixed-ids.txt").write_text(fixed)
            return lint(guide, "--fixed", str(Path(d, "fixed-ids.txt")))

    def test_lint_warns_when_a_fixed_sentence_was_reworded_and_still_exits_clean(self):
        code, out = self.lint_fixed("A4.0002 | You can keep 5 notes a day.\n", "You can keep five notes each day. [A4.0002]")
        self.assertEqual(code, 0, out)
        self.assertIn("warn fixed:", out)
        self.assertIn("You can keep 5 notes a day.", out)

    def test_lint_is_quiet_when_the_fixed_sentence_is_as_it_was(self):
        code, out = self.lint_fixed("A4.0002 | You can keep 5 notes a day.\n", "You can keep 5 notes a day. [A4.0002]")
        self.assertEqual((code, "warn fixed" in out), (0, False), out)

    def test_a_bad_fixed_file_path_is_a_usage_error(self):
        self.assertEqual(lint(GUIDE_COND % (P1, "x. `src/cli.py:7` [A4.0002]"), "--fixed", "/no/such")[0], 2)


# --- change: the reader bar ------------------------------------------------------------------------------------------------------------------
class GlossaryAndReaderTest(unittest.TestCase):
    GLOSS = "## Glossary\n\nslug: a short name in a web address.\n"

    def test_an_untagged_entry_defining_an_outside_term_passes(self):
        guide = GUIDE_COND.replace("# Part 2: Appendix", self.GLOSS + "\n# Part 2: Appendix") % ("You can keep 5 notes. [A4.0002]", "It stops after 5 notes. `src/cli.py:7` [A4.0002]")
        code, out = lint(guide)
        self.assertEqual(code, 0, out)

    def test_an_untagged_entry_that_names_something_of_the_repo_fails(self):
        for entry in ("add: the `notes add` command.", "tag: set with --tag."):
            guide = GUIDE_COND.replace("# Part 2: Appendix", "## Glossary\n\n%s\n\n# Part 2: Appendix" % entry) % ("You can keep 5 notes. [A4.0002]", "It stops after 5 notes. `src/cli.py:7` [A4.0002]")
            self.assertIn("FAIL glossary:", lint(guide)[1], entry)

    def test_sixteen_entries_are_allowed(self):
        entries = "".join("term%d: a thing outside.\n" % i for i in range(16))
        guide = GUIDE_COND.replace("# Part 2: Appendix", "## Glossary\n\n%s\n# Part 2: Appendix" % entries) % ("You can keep 5 notes. [A4.0002]", "It stops after 5 notes. `src/cli.py:7` [A4.0002]")
        self.assertEqual(lint(guide)[0], 0, lint(guide)[1])

    def test_lint_has_no_unknown_option_any_more(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "u.txt").write_text("slug\n")
            self.assertEqual(lint(GUIDE_COND % (P1, "It stops. `src/cli.py:7` [A4.0002]"), "--unknown", str(Path(d, "u.txt")))[0], 2)

    def test_the_reader_answers_report_prints_the_unknown_words_and_does_not_gate_on_them(self):
        guide = DOC
        answers = "".join("## Q%d\n\nanswer\n> It saves notes.\n\n" % i for i in range(1, 6)) + "## Unknown words\n\nslug\nwebhook\n"
        with tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(guide)
            Path(d, "answers.md").write_text(answers)
            code, out, err = script("score.py", "--reader", Path(d, "GUIDE.md"), "--answers", Path(d, "answers.md"))
        self.assertEqual(code, 0, out + err)
        self.assertIn("unknown words: 2 (slug, webhook)", out)

    def test_the_reader_prompt_says_to_leave_out_a_word_the_text_defines(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(DOC)
            code, out, err = script("score.py", "--reader", Path(d, "GUIDE.md"))
        self.assertRegex(out, r"(?i)do not list a word[^.]*defines")


if __name__ == "__main__":
    unittest.main()
