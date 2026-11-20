"""check_citations.py --guards and the stricter --audit: a condition sheet with every guard marked, an evidence row for every cited line,
no uncited sentence without an "inferred" label, and a failure summary that names the checks that failed.
Run: python3 -I tests/deriving-readable-docs/test_guards_audit.py"""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"

REPO = {
    "src/a.ts": "export function run(x: number) {\n  if (!x) return 1;\n  if (x > 5) throw new Error('big');\n  return doIt(x);\n}\n",
    "src/b.ts": "export const LIMIT = 5;\n",
    "src/c.rs": "fn main() {}\n",
}
DOC = "## A4 Running\n\nIt calls doIt with the number. `src/a.ts:4` [A4.aaaa]\nThe limit is 5. `src/b.ts:1` [A4.bbbb]\n"
AUDIT = ('3 | assert: src/a.ts:4 "return doIt(x);" | exits: src/a.ts:2 off the path: x is zero; src/a.ts:3 off the path: x over 5 | callers: none found | found: nothing | result: HOLDS\n'
         '4 | assert: src/b.ts:1 "export const LIMIT = 5;" | exits: none listed | callers: none found | found: nothing | result: HOLDS\n')
EVIDENCE = '`src/a.ts:4` | "return doIt(x);" | called with a number\n`src/b.ts:1` | "export const LIMIT = 5;" | set here\n'
GUARDS_OK = "guard | src/a.ts:2 | return | if (!x) return 1; | covered: not relevant: zero is another case\nguard | src/a.ts:3 | throw | if (x > 5) throw new Error('big'); | covered: A4.aaaa\n"


def make(files):
    tmp = tempfile.TemporaryDirectory()
    for rel, text in files.items():
        p = Path(tmp.name) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp


def run(doc, repo, *args):
    with tempfile.TemporaryDirectory() as d:
        Path(d, "doc.md").write_text(doc)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), str(Path(d, "doc.md")), repo, *args], capture_output=True, text=True)
    return r.returncode, r.stdout.replace(d + "/", "")


class GuardsOutputTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = make(REPO)

    @classmethod
    def tearDownClass(cls):
        cls.repo.cleanup()

    def test_it_prints_one_row_for_each_exit_above_a_cited_line_ready_to_mark(self):
        code, out = run(DOC, self.repo.name, "--guards")
        self.assertEqual(code, 0, out)
        rows = [l for l in out.splitlines() if l.startswith("guard | ")]
        self.assertEqual(len(rows), 2, out)
        self.assertIn("guard | src/a.ts:2 | return | if (!x) return 1; | covered:", rows[0])
        self.assertIn("guard | src/a.ts:3 | throw |", rows[1])
        self.assertTrue(all(r.rstrip().endswith("covered:") for r in rows))

    def test_a_cited_file_with_no_function_exits_gives_a_sheet_with_no_rows(self):
        code, out = run("## A4 x\n\nThe limit is 5. `src/b.ts:1` [A4.bbbb]\n", self.repo.name, "--guards")
        self.assertEqual(code, 0)
        self.assertEqual([l for l in out.splitlines() if l.startswith("guard | ")], [])

    def test_an_exit_cited_twice_is_one_row(self):
        doc = DOC + "It also calls it. `src/a.ts:4` [A4.cccc]\n"
        self.assertEqual(len([l for l in run(doc, self.repo.name, "--guards")[1].splitlines() if l.startswith("guard | ")]), 2)


class AuditFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = make(REPO)

    @classmethod
    def tearDownClass(cls):
        cls.repo.cleanup()

    def audit(self, doc=DOC, audit=AUDIT, guards=GUARDS_OK, evidence=EVIDENCE, extra=()):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "audit.md").write_text(audit)
            if guards is not None:
                Path(d, "guards.md").write_text(guards)
            if evidence is not None:
                Path(d, "evidence.md").write_text(evidence)
            Path(d, "doc.md").write_text(doc)
            r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), str(Path(d, "doc.md")), self.repo.name, "--audit", str(Path(d, "audit.md")), *extra],
                               capture_output=True, text=True)
        return r.returncode, r.stdout

    def test_a_draft_with_every_file_in_place_passes(self):
        code, out = self.audit()
        self.assertEqual(code, 0, out)

    # -- the condition sheet
    def test_a_missing_condition_sheet_fails_the_audit(self):
        code, out = self.audit(guards=None)
        self.assertEqual(code, 1)
        self.assertIn("FAIL guards:", out)
        self.assertIn("--guards", out)

    def test_an_unmarked_guard_fails_and_is_named(self):
        code, out = self.audit(guards=GUARDS_OK.replace("covered: A4.aaaa", "covered:"))
        self.assertEqual(code, 1)
        self.assertIn("FAIL guards:", out)
        self.assertIn("src/a.ts:3", out)
        self.assertNotIn("src/a.ts:2 is", out)

    def test_a_guard_the_sheet_leaves_out_fails(self):
        code, out = self.audit(guards=GUARDS_OK.split("\n")[0] + "\n")
        self.assertEqual(code, 1)
        self.assertIn("src/a.ts:3", out)

    def test_not_relevant_needs_a_reason(self):
        code, out = self.audit(guards=GUARDS_OK.replace("covered: not relevant: zero is another case", "covered: not relevant:"))
        self.assertEqual(code, 1)
        self.assertIn("src/a.ts:2", out)

    def test_a_sentence_id_that_is_not_in_the_draft_does_not_cover_a_guard(self):
        code, out = self.audit(guards=GUARDS_OK.replace("covered: A4.aaaa", "covered: A4.zzzz"))
        self.assertEqual(code, 1)
        self.assertIn("A4.zzzz", out)

    def test_a_sentence_that_cites_another_file_does_not_cover_a_guard(self):
        code, out = self.audit(guards=GUARDS_OK.replace("covered: A4.aaaa", "covered: A4.bbbb"))
        self.assertEqual(code, 1)
        self.assertIn("A4.bbbb", out)
        self.assertIn("src/a.ts", out)

    def test_an_empty_sheet_is_not_a_missing_one(self):
        doc = "## A4 x\n\nThe limit is 5. `src/b.ts:1` [A4.bbbb]\n"
        code, out = self.audit(doc, '3 | assert: src/b.ts:1 "export const LIMIT = 5;" | exits: none listed | callers: none found | found: nothing | result: HOLDS\n',
                               "# guards\n", EVIDENCE)
        self.assertEqual(code, 0, out)

    def test_the_sheet_and_evidence_paths_can_be_named(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "g.md").write_text(GUARDS_OK)
            Path(d, "e.md").write_text(EVIDENCE)
            code, out = self.audit(guards=None, evidence=None, extra=("--guards-file", str(Path(d, "g.md")), "--evidence-file", str(Path(d, "e.md"))))
        self.assertEqual(code, 0, out)

    # -- the evidence file
    def test_a_missing_evidence_file_fails_the_audit(self):
        code, out = self.audit(evidence=None)
        self.assertEqual(code, 1)
        self.assertIn("FAIL evidence:", out)

    def test_a_cited_line_with_no_evidence_row_fails_and_is_named(self):
        code, out = self.audit(evidence=EVIDENCE.split("\n")[0] + "\n")
        self.assertEqual(code, 1)
        self.assertIn("FAIL evidence:", out)
        self.assertIn("src/b.ts:1", out)

    def test_an_evidence_row_whose_text_is_not_on_the_line_fails(self):
        code, out = self.audit(evidence=EVIDENCE.replace('"return doIt(x);"', '"return somethingElse(x);"'))
        self.assertEqual(code, 1)
        self.assertIn("src/a.ts:4", out)

    def test_one_row_inside_a_cited_range_is_enough(self):
        doc = "## A4 x\n\nIt runs the whole function. `src/a.ts:1-4` [A4.aaaa]\n"
        audit = '3 | assert: src/a.ts:4 "return doIt(x);" | exits: none listed | callers: none found | found: nothing | result: HOLDS\n'
        code, out = self.audit(doc, audit, "# guards\nguard | src/a.ts:2 | return | x | covered: A4.aaaa\nguard | src/a.ts:3 | throw | x | covered: A4.aaaa\n", EVIDENCE)
        self.assertEqual(code, 0, out)

    # -- uncited sentences
    def test_an_uncited_sentence_with_no_inferred_label_fails(self):
        doc = DOC + "This section shows how it runs. [A4.dddd]\n"
        code, out = self.audit(doc)
        self.assertEqual(code, 1)
        self.assertIn("FAIL uncited:", out)
        self.assertIn("This section shows how it runs", out)

    def test_an_uncited_sentence_labelled_inferred_passes(self):
        doc = DOC + "This section shows how it runs (inferred from the names). [A4.dddd]\n"
        code, out = self.audit(doc)
        self.assertEqual(code, 0, out)

    def test_a_readme_label_without_a_citation_is_not_enough(self):
        doc = DOC + "The README says it runs (README). [A4.dddd]\n"
        self.assertIn("FAIL uncited:", self.audit(doc)[1])

    def test_the_id_after_a_citation_is_not_an_uncited_sentence(self):
        code, out = self.audit()
        self.assertNotIn("uncited", out)

    def test_without_the_audit_an_uncited_sentence_is_only_listed(self):
        code, out = run(DOC + "This section shows how it runs.\n", self.repo.name)
        self.assertEqual(code, 0, out)


class NamedFailuresTest(unittest.TestCase):
    """Defect 14: the run printed "1 failed checks" and never said which."""

    @classmethod
    def setUpClass(cls):
        cls.repo = make(REPO)

    @classmethod
    def tearDownClass(cls):
        cls.repo.cleanup()

    def test_the_summary_names_each_kind_of_failed_check_with_its_count(self):
        doc = "## A4 x\n\nThe limit is 9. `src/b.ts:1` [A4.bbbb]\nThe name is `Nope`. `src/b.ts:1` [A4.cccc]\n"
        code, out = run(doc, self.repo.name)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"2 failed checks \((number 1, string 1|string 1, number 1)\)")

    def test_a_clean_run_has_no_list(self):
        code, out = run(DOC, self.repo.name)
        self.assertIn("0 failed checks, ", out)
        self.assertNotIn("0 failed checks (", out)

    def test_a_bad_citation_is_counted_by_name_too(self):
        code, out = run("## A4 x\n\nIt is there. `src/b.ts:99` [A4.bbbb]\n", self.repo.name)
        self.assertEqual(code, 1)
        self.assertRegex(out, r"1 failed checks \(citation 1\)")


if __name__ == "__main__":
    unittest.main()
