"""score.py: the round score from checker reports, the lab metrics and the reader check, run as the skill runs it (as a script, on files).
Run: python3 -I tests/deriving-readable-docs/test_score.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"


def run(*args, cwd=None):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "score.py"), *args], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout, r.stderr


def counts(claims, holds, wrong, over, unsup):
    """The `read` rows check brief version 8 asks for (one a claim, each with the line read), then the Counts line."""
    verdicts = ["HOLDS"] * holds + ["WRONG"] * wrong + ["OVERSTATED"] * over + ["UNSUPPORTED"] * unsup
    rows = "".join("read | %d.1 | %s | src/x.py:1\n" % (i, v) for i, v in enumerate(verdicts, 1))
    return rows + "Counts: claims checked %d; HOLDS %d; WRONG %d; OVERSTATED %d; UNSUPPORTED %d.\n" % (claims, holds, wrong, over, unsup)


# finding lines in the two shapes the r4 reports used, with and without a cause tag
V4_ROW = '113 | OVERSTATED | "sends the text `replayText` returns" | the forwarder only acks (src/inbox/forwarder.ts:206-207) | add the case\n'
V4_ROW_NAMED = "SPEC.md:430 | OVERSTATED | While a component is stuck, an add is refused | holds only while no redesign (src/traces/domain/trigger.ts:45) | add the condition\n"
V5_ROW = "7 | WRONG | NAME | `--foo` | the flag is `--bar` (src/cli.ts:3) | rename\n"
V5_COND = "9 | OVERSTATED | MISSING_CONDITION | always retries | gives up after 3 (src/net.ts:8) | say when\n"


def write_reports(d, files):
    for name, text in files.items():
        Path(d, name).write_text(text)
    return d


class ScoreTest(unittest.TestCase):
    def test_a_folder_of_reports_is_summed_into_claims_errors_and_rate(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, {"A.md": V4_ROW + counts(98, 97, 0, 1, 0), "B.md": V4_ROW_NAMED + V5_ROW + counts(100, 98, 1, 1, 0)})
            code, out, err = run(d)
        self.assertEqual(code, 0, err)
        self.assertIn("claims checked: 198", out)
        self.assertIn("errors: 3 out of 198 claims", out)
        self.assertIn("rate (W+O+U)/claims: 1.5%  (3/198)", out)

    def test_findings_are_counted_by_cause_and_an_old_report_without_a_cause_is_untagged(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, {"A.md": V5_ROW + V5_COND + V4_ROW + counts(50, 47, 1, 2, 0)})
            code, out, err = run(d)
        self.assertEqual(code, 0, err)
        self.assertIn("causes: NAME 1, MISSING_CONDITION 1, UNTAGGED 1", out.replace("MISSING_CONDITION 1, NAME 1", "NAME 1, MISSING_CONDITION 1"))

    def test_a_part1_report_is_scored_apart_from_the_appendix(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, {"A.md": V5_ROW + counts(200, 199, 1, 0, 0), "part1.md": V5_COND + counts(40, 39, 0, 1, 0)})
            code, out, err = run(d)
        self.assertEqual(code, 0, err)
        self.assertIn("rate (W+O+U)/claims: 0.8%  (2/240)", out)
        self.assertIn("appendix rate: 0.5%  (1/200)", out)
        self.assertIn("part 1 rate: 2.5%  (1/40)", out)

    def test_counts_that_do_not_add_up_fail_and_name_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, {"A.md": V4_ROW + counts(98, 95, 0, 1, 0)})
            code, out, err = run(d)
        self.assertEqual(code, 1)
        self.assertIn("A.md", err)
        self.assertIn("is 96, not the 98 claims checked", err)

    def test_a_report_with_fewer_finding_lines_than_errors_fails(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, {"A.md": V4_ROW + counts(98, 95, 1, 2, 0)})
            code, out, err = run(d)
        self.assertEqual(code, 1)
        self.assertIn("1 finding lines", err)

    def test_a_report_without_a_counts_line_or_with_two_fails(self):
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, {"A.md": "all fine\n"})
            self.assertEqual(run(d)[0], 1)
            write_reports(d, {"A.md": counts(1, 1, 0, 0, 0) + counts(1, 1, 0, 0, 0)})
            code, out, err = run(d)
        self.assertEqual(code, 1)
        self.assertIn("2 Counts lines", err)

    def test_a_counts_header_that_is_not_a_checker_line_is_not_read(self):
        """The assembled docs of the old flow carry `Counts: harvested N; ...`; a folder holding only those has no score."""
        with tempfile.TemporaryDirectory() as d:
            write_reports(d, {"PRD.md": "- Counts: harvested 5; left out 1; used 3; read by name only 0; not cited 1.\n"})
            code, out, err = run(d)
        self.assertEqual(code, 1)
        self.assertIn("no `Counts: claims checked", err)

    def test_an_empty_folder_or_missing_path_fails(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(run(d)[0], 1)
            self.assertEqual(run(d + "/missing")[0], 1)

    def test_a_folder_is_not_searched_below_its_own_files(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "round2").mkdir()
            Path(d, "round2", "R2.md").write_text(counts(5, 5, 0, 0, 0))
            write_reports(d, {"A.md": counts(10, 10, 0, 0, 0)})
            code, out, err = run(d)
        self.assertIn("claims checked: 10", out)

    def test_two_repos_are_scored_apart_and_pooled(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            write_reports(a, {"A.md": V5_ROW + counts(100, 99, 1, 0, 0)})
            write_reports(b, {"A.md": counts(300, 300, 0, 0, 0)})
            code, out, err = run("one=" + a, "two=" + b)
        self.assertEqual(code, 0, err)
        self.assertIn("repo one", out)
        self.assertIn("repo two", out)
        self.assertIn("pooled over 2 repos", out)
        self.assertIn("rate (W+O+U)/claims: 0.2%  (1/400)", out)

    def test_words_and_errors_per_1000_words_come_from_the_doc_as_the_check_counts_them(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            Path(repo, "a.rs").write_text("x\n" * 5)
            Path(repo, "src").mkdir()
            Path(repo, "src/x.py").write_text("x\n")
            Path(d, "GUIDE.md").write_text("## A4 S\n\nIt reads one file (`a.rs:1`). It writes two files (`a.rs:2`).\n\n<!-- printed -->\nrow row row row\n<!-- /printed -->\n")
            rep = Path(d, "reports")
            rep.mkdir()
            write_reports(rep, {"A.md": V5_ROW + counts(2, 1, 1, 0, 0)})
            out_file = Path(d, "out", "score.json")
            code, out, err = run(str(rep), "--doc", str(Path(d, "GUIDE.md")), "--repo", repo, "--out", str(out_file))
            data = json.loads(out_file.read_text())
            txt = out_file.with_suffix(".txt").read_text()
        self.assertEqual(code, 0, err)
        self.assertIn("words: 10; errors per 1,000 words: 100.00; script claims: 2; words per claim: 4.0", out)
        self.assertEqual(data["repos"][0]["errors"], 1)
        self.assertIn("errors: 1 out of 2 claims", txt)


class ClaimCountTest(unittest.TestCase):
    """The checkers' claim count is the score's; when the script counts the doc's sentences differently the score prints both and the difference."""

    def score(self, checkers_claims, doc):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            Path(repo, "a.rs").write_text("x\n" * 5)
            Path(repo, "src").mkdir()
            Path(repo, "src/x.py").write_text("x\n")
            Path(d, "GUIDE.md").write_text(doc)
            rep = Path(d, "reports")
            rep.mkdir()
            write_reports(rep, {"A.md": counts(checkers_claims, checkers_claims, 0, 0, 0)})
            return run(str(rep), "--doc", str(Path(d, "GUIDE.md")), "--repo", repo)

    DOC = "## A4 S\n\nIt reads one file (`a.rs:1`). It writes two files (`a.rs:2`). It stops (`a.rs:3`).\n"

    def test_a_difference_is_printed_and_the_rate_keeps_the_checker_count(self):
        code, out, err = self.score(2, self.DOC)
        self.assertEqual(code, 0, err)
        self.assertIn("claim count: checkers 2, script 3, difference +1", out)
        self.assertIn("claims checked: 2", out)

    def test_no_difference_line_when_the_counts_agree(self):
        code, out, err = self.score(3, self.DOC)
        self.assertEqual(code, 0, err)
        self.assertNotIn("claim count:", out)


def write_draft(root, name, claims, words, errors, mc, script_claims, lab):
    """One draft's score.json and lab.json, shaped as `score.py --out` and `score.py --lab --out` write them."""
    d = Path(root, name)
    d.mkdir()
    causes = {"MISSING_CONDITION": mc, "NAME": errors - mc, "COUNT": 0, "KIND": 0, "OTHER": 0, "UNTAGGED": 0}
    Path(d, "score.json").write_text(json.dumps({"repos": [{"name": name, "claims": claims, "errors": errors, "words": words, "script_claims": script_claims,
                                                          "causes": causes}]}))
    Path(d, "lab.json").write_text(json.dumps(lab))
    return str(d / "score.json"), str(d / "lab.json")


class PoolTest(unittest.TestCase):
    """--pool: the pooled summary of a round, so that no runner writes its own analyze script."""
    A = dict(behaviours=14, behaviours_kept=14, condition_lines=40, condition_lines_cited=30, claims=20, words=400, conditional_words=16)
    B = dict(behaviours=10, behaviours_kept=9, condition_lines=20, condition_lines_cited=10, claims=30, words=500, conditional_words=10)

    def pool(self, *groups):
        """groups are NAME=a,b: the group NAME pools drafts a and/or b."""
        with tempfile.TemporaryDirectory() as root:
            files = {"a": write_draft(root, "a", claims=18, words=410, errors=2, mc=1, script_claims=20, lab=self.A),
                     "b": write_draft(root, "b", claims=28, words=520, errors=1, mc=1, script_claims=30, lab=self.B)}
            args = []
            for g in groups:
                name, members = g.split("=")
                args += ["%s=%s,%s" % ((name,) + files[m]) for m in members.split(",")]
            return run("--pool", *args)

    def test_a_group_is_pooled_over_its_drafts_with_the_lab_runners_columns(self):
        code, out, err = self.pool("both=a,b")
        self.assertEqual(code, 0, err)
        row = [l for l in out.splitlines() if l.startswith("both")][0]
        self.assertIn("drafts words  930 claims  46(checked) errors  3 rate 6.5%  err/1000w 3.23  MC/1000w 2.15", row)
        self.assertIn("words/claim 18.0 (mean of drafts 18.3)", row)  # 900 words in 50 script claims; the mean of 20.0 and 16.7
        self.assertIn("behaviours 23/24 95.8%", row)
        self.assertIn("cond lines 40/60 66.7%", row)
        self.assertIn("conditional w/1000w 28.9", row)
        self.assertIn("claim count: checkers 46, script 50, difference +4", row)

    def test_each_group_gets_its_own_row(self):
        code, out, err = self.pool("one=a", "two=b")
        self.assertEqual(code, 0, err)
        self.assertEqual([l.split()[0] for l in out.splitlines() if l.strip()], ["one", "two"])
        self.assertIn("errors  2 rate 11.1%", out)  # 2 of the 18 claims the checkers counted for draft a

    def test_a_missing_file_or_a_score_without_words_is_an_error_naming_it(self):
        code, out, err = run("--pool", "x=/no/such/score.json,/no/such/lab.json")
        self.assertEqual(code, 1)
        self.assertIn("/no/such/score.json", err)
        with tempfile.TemporaryDirectory() as d:
            Path(d, "score.json").write_text(json.dumps({"repos": [{"claims": 3, "errors": 0, "causes": {"MISSING_CONDITION": 0}}]}))
            Path(d, "lab.json").write_text(json.dumps(self.A))
            code, out, err = run("--pool", "x=%s,%s" % (Path(d, "score.json"), Path(d, "lab.json")))
        self.assertEqual(code, 1)
        self.assertIn("score.json", err)
        self.assertIn("--doc", err)

    def test_bad_usage_exits_2(self):
        self.assertEqual(run("--pool")[0], 2)
        self.assertEqual(run("--pool", "no-equals-sign")[0], 2)


class LabTest(unittest.TestCase):
    REPO_FILES = {"src/a.ts": "\n".join("line %d" % i for i in range(1, 40)) + "\n"}
    LIST = "# behaviours\nB1 | src/a.ts:10 | src/a.ts:8, src/a.ts:12-13\nB2 | src/a.ts:30 |\nB3 | src/a.ts:35 | src/a.ts:34\n"

    def lab(self, draft, listing=None):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            for rel, text in self.REPO_FILES.items():
                Path(repo, rel).parent.mkdir(parents=True, exist_ok=True)
                Path(repo, rel).write_text(text)
            Path(d, "list.txt").write_text(listing or self.LIST)
            Path(d, "draft.md").write_text(draft)
            return run("--lab", str(Path(d, "list.txt")), str(Path(d, "draft.md")), repo)

    def test_behaviours_kept_and_condition_lines_cited(self):
        draft = "## A4 S\n\nIt stops when the file is missing (`src/a.ts:8`, `src/a.ts:10`). It reads the next line `src/a.ts:30-32`.\n"
        code, out, err = self.lab(draft)
        self.assertEqual(code, 0, err)
        self.assertIn("behaviours kept: 2 of 3 (66.7%)", out)
        self.assertIn("condition lines cited: 1 of 3 (33.3%)", out)
        self.assertIn("behaviours not cited: B3", out)
        self.assertIn("condition lines not cited: B1 src/a.ts:12; B3 src/a.ts:34", out)

    def test_a_citation_range_covers_the_lines_inside_it(self):
        code, out, err = self.lab("## A4 S\n\nIt reads it `src/a.ts:7-14`. It stops `src/a.ts:30`. It ends `src/a.ts:33-36`.\n")
        self.assertIn("behaviours kept: 3 of 3 (100.0%)", out)
        self.assertIn("condition lines cited: 3 of 3 (100.0%)", out)

    def test_conditional_words_are_counted_per_1000_words_outside_code_spans(self):
        code, out, err = self.lab("## A4 S\n\nIt stops when X, unless `if` Y `src/a.ts:10`. It runs `src/a.ts:30`.\n")
        self.assertIn("conditional words per 1,000 words: 222.2  (2 in 9)", out)

    def test_a_malformed_list_line_is_an_error(self):
        code, out, err = self.lab("## A4 S\n\nIt runs `src/a.ts:10`.\n", "B1 only\n")
        self.assertEqual(code, 1)
        self.assertIn("expected `ID | path:line | cond, cond`", err)


GUIDE = ("# Part 1: In plain English\n\n## What it is\n\nIt lets you save notes. [A4.1] It runs on a laptop. [A4.2]\n\n"
         "<!-- printed -->\nA1 rows that are not Part 1\n<!-- /printed -->\n\n# Part 2: Appendix\n\n## A4 Notes\n\nThe appendix is not shown to the reader (`a.rs:1`).\n")


class ReaderTest(unittest.TestCase):
    def reader(self, *extra, answers=None):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "GUIDE.md").write_text(GUIDE)
            args = ["--reader", str(Path(d, "GUIDE.md"))]
            if answers is not None:
                Path(d, "answers.md").write_text(answers)
                args += ["--answers", str(Path(d, "answers.md"))]
            return run(*args)

    def test_the_brief_has_the_five_questions_and_part_1_without_tags_or_the_appendix(self):
        code, out, err = self.reader()
        self.assertEqual(code, 0, err)
        self.assertIn("1. In one sentence, what is it, and who would use it?", out)
        self.assertIn("5. Name one thing it does not do", out)
        self.assertIn("It lets you save notes. It runs on a laptop.", out)
        self.assertNotIn("[A4", out)
        self.assertNotIn("appendix is not shown", out)
        self.assertNotIn("A1 rows", out)

    ANSWERS = "".join("## Q%d\n\nanswer\n\n> %s\n\n" % (i, q) for i, q in
                      enumerate(["It lets you save notes.", "It lets you save notes.", "It runs on a laptop.", "It runs on a laptop."], 1)) + "## Q5\n\nNOT IN TEXT\n"

    def test_quotes_that_are_sentences_of_part_1_pass(self):
        code, out, err = self.reader(answers=self.ANSWERS)
        self.assertEqual(code, 0, out + err)
        self.assertIn("4 quotes, 0 not in Part 1; 0 answers without a quote", out)

    def test_a_quote_that_is_not_in_part_1_fails_and_names_its_line(self):
        code, out, err = self.reader(answers=self.ANSWERS.replace("It runs on a laptop.", "It runs on a server.", 1))
        self.assertEqual(code, 1)
        self.assertIn("answers.md:17: quote is not in Part 1: It runs on a server.", out)

    def test_a_sentence_that_is_only_in_the_appendix_is_not_a_quote(self):
        code, out, err = self.reader(answers=self.ANSWERS.replace("It lets you save notes.", "The appendix is not shown to the reader.", 1))
        self.assertEqual(code, 1)
        self.assertIn("quote is not in Part 1: The appendix is not shown", out)

    def test_an_answer_with_no_quote_and_no_not_in_text_fails(self):
        code, out, err = self.reader(answers=self.ANSWERS.replace("NOT IN TEXT", "unsure"))
        self.assertEqual(code, 1)
        self.assertIn("Q5 has no quote and no NOT IN TEXT", out)

    def test_a_guide_with_no_part_1_heading_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "G.md").write_text("## A4 only\n\nIt runs (`a.rs:1`).\n")
            code, out, err = run("--reader", str(Path(d, "G.md")))
        self.assertEqual(code, 1)
        self.assertIn("no heading `Part 1`", err)


if __name__ == "__main__":
    unittest.main()
