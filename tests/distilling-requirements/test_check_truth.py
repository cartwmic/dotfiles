"""check_truth.py: register rows that pass the shape check but fail the truth check, run as the skill runs it (scripts on files, the sibling
deriving-readable-docs scripts called by path).
The fixture register has four rows that check_shape.py passes:
  R-1 holds; R-2 cites a real line that does the opposite of what the row says (only a checker can tell); R-4 has owner evidence only;
  R-5 rests on the README. A second fixture adds R-3, which cites a line the file does not have (check_citations.py catches it before any checker runs).
No model session runs here: the checker's report is recorded in the test, in the form check-brief.md asks for, and score.py ties it to the claims
file the adapter and slice.py really made.
Run: python3 -I tests/distilling-requirements/test_check_truth.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills"
TRUTH = SKILLS / "distilling-requirements/scripts/check_truth.py"
SHAPE = SKILLS / "distilling-requirements/scripts/check_shape.py"
CODEMAP = SKILLS / "deriving-readable-docs/scripts"

NOTES = '''NOTES = []


def add_note(text):
    if not text.strip():
        raise ValueError("empty note")
    NOTES.append(text)
    return len(NOTES)


def clear_notes():
    NOTES.clear()
'''
REPO = {"src/notes.py": NOTES, "README.md": "# Notes\n\nNotes are kept in memory.\n"}
HEAD = "```text\nshape: requirements/1\nrepo: demo\ncommit: 0000000000000000000000000000000000000000\nscope: whole repo\ndate: 2026-11-21\nnot-read: none\n" \
       "counts: R=%d SM=0 I=0 U=0 F=0 Q=0\n```\n# Requirements: demo\n\n## 1. Requirements register\n\n" \
       "| id | lens | kind | durability | status | requirement | evidence | check | fit | enforced | note |\n|---|---|---|---|---|---|---|---|---|---|---|\n"
TAIL = "\n## 2. State machines\n\nNone found.\n\n## 3. Unenforced invariants\n\nNone found.\n\n## 4. Findings\n\nNone found.\n\n## 5. Open questions\n\nNone.\n\n## Changelog\n\n- 2026-11-21: first pass.\n"
ROWS = {
    "R-1": "An empty note shall be refused with an error.|src/notes.py:4-5",
    "R-2": "Clearing the store shall keep the saved notes.|src/notes.py:11-12",
    "R-3": "Adding a note shall return how many notes are stored.|src/notes.py:99",
    "R-4": "Notes shall be kept for the length of the project.|owner:Dana, kickoff call",
    "R-5": "The store shall hold notes in memory.|README.md:3",
}


def register(ids):
    rows = ""
    for i in ids:
        req, ev = ROWS[i].split("|")
        rows += "| %s | product | implicit | enduring | proposed | %s | %s | none | none | yes | |\n" % (i, req, ev)
    return HEAD % len(ids) + rows + TAIL


def run(script, *args):
    r = subprocess.run([sys.executable, "-I", str(script), *map(str, args)], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def make(tmp, ids):
    """Write the fixture repo and a register of the given rows; return (repo, requirements path, work folder)."""
    root = Path(tmp)
    for rel, text in REPO.items():
        (root / "repo" / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / "repo" / rel).write_text(text)
    (root / "REQUIREMENTS.md").write_text(register(ids))
    return root / "repo", root / "REQUIREMENTS.md", root / "work"


def report(slice_dir, verdicts, lines_read):
    """A recorded checker report for slice-1 in the form check-brief.md asks for: a read row per claim, finding lines, the Counts line."""
    claims = [l.split(" | ", 2) for l in (Path(slice_dir) / "slice-1.claims.txt").read_text().splitlines()]
    verdict = {cid: verdicts.get(cid, "HOLDS") for cid, _, _ in claims}
    out = ["Slice: slice-1"] + ["read | %s | %s | %s" % (cid, verdict[cid], lines_read[cid]) for cid, _, _ in claims]
    out += ["%s | %s | MISSING_CONDITION | the claim | the code shows the opposite (src/notes.py:11-12) | drop it" % (cid, v) for cid, v in verdict.items() if v != "HOLDS"]
    n = {v: sum(1 for x in verdict.values() if x == v) for v in ("HOLDS", "WRONG", "OVERSTATED", "UNSUPPORTED")}
    out.append("Counts: claims checked %d; HOLDS %d; WRONG %d; OVERSTATED %d; UNSUPPORTED %d." % (len(claims), n["HOLDS"], n["WRONG"], n["OVERSTATED"], n["UNSUPPORTED"]))
    return "\n".join(out) + "\n"


class TruthCheckTest(unittest.TestCase):
    def prepare(self, tmp, ids):
        repo, req, work = make(tmp, ids)
        code, out, err = run(TRUTH, "prepare", req, "--out", work)
        self.assertEqual(code, 0, err)
        return repo, req, work, out

    def test_the_shape_check_passes_every_row_of_both_registers(self):
        for ids in (["R-1", "R-2", "R-4", "R-5"], ["R-1", "R-2", "R-3", "R-4", "R-5"]):
            with tempfile.TemporaryDirectory() as tmp:
                _, req, _ = make(tmp, ids)
                self.assertEqual(run(SHAPE, req), (0, "ok\n", ""), ids)

    def test_prepare_turns_rows_into_claims_and_leaves_out_a_row_with_owner_evidence_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, work, out = self.prepare(tmp, ["R-1", "R-2", "R-4", "R-5"])
            doc = (work / "register-claims.md").read_text()
            self.assertIn("3 rows to check, 1 not checked: R-4", out)
            self.assertIn("## R-1\nAn empty note shall be refused with an error. `src/notes.py:4-5`", doc)
            self.assertNotIn("R-4", doc)
            # a row that rests on the README says so in its sentence, because the check brief fails a doc-backed claim that does not
            self.assertIn("The store shall hold notes in memory (README). `README.md:3`", doc)
            meta = json.loads((work / "rows.json").read_text())
            self.assertEqual([r["id"] for r in meta["rows"]], ["R-1", "R-2", "R-5"])
            self.assertEqual(doc.splitlines()[meta["rows"][1]["line"] - 1].split(" `")[0], "Clearing the store shall keep the saved notes.")

    def test_a_row_citing_a_line_that_does_not_exist_fails_the_citation_gate_before_any_checker_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, work, _ = self.prepare(tmp, ["R-1", "R-2", "R-3", "R-4", "R-5"])
            code, out, _ = run(CODEMAP / "check_citations.py", work / "register-claims.md", repo)
            self.assertEqual(code, 1)
            self.assertIn("src/notes.py:99: line out of range (file has 12 lines)", out)
            self.assertIn("1 bad", out)

    def test_a_row_citing_a_real_line_that_does_the_opposite_passes_every_script_and_only_the_checker_fails_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, work, _ = self.prepare(tmp, ["R-1", "R-2", "R-4", "R-5"])
            doc = work / "register-claims.md"
            gate = run(CODEMAP / "check_citations.py", doc, repo)
            self.assertEqual(gate[0], 0, gate[1])  # the line exists and the sentence has no number, name or overreach word to catch
            code, out, err = run(CODEMAP / "slice.py", doc, repo, "--out", work / "slices")
            self.assertEqual(code, 0, err)
            self.assertIn("3 claims, 0 flags", out)  # nothing flagged either: the checker has to read the code
            claims = dict((l.split(" | ", 2)[0], l.split(" | ", 2)[2]) for l in (work / "slices/slice-1.claims.txt").read_text().splitlines())
            wrong = next(c for c, s in claims.items() if s.startswith("Clearing the store"))
            reads = {c: "src/notes.py:4-5" for c in claims}
            reads[wrong] = "src/notes.py:11-12"
            reports = work / "reports"
            reports.mkdir()
            (reports / "slice-1.md").write_text(report(work / "slices", {wrong: "WRONG"}, reads))
            scored = run(CODEMAP / "score.py", reports, "--repo", repo, "--slices", work / "slices")
            self.assertEqual(scored[0], 0, scored[2])  # the recorded report fits the claims file the adapter and slice.py made
            self.assertIn("WRONG: 1", scored[1])
            code, out, _ = run(TRUTH, "verdicts", work, reports)
            self.assertEqual(code, 1)
            self.assertIn("R-2 WRONG src/notes.py:11-12", out)
            self.assertIn("R-1 HOLDS src/notes.py:4-5", out)
            self.assertIn("R-5 HOLDS README.md:3", out)
            self.assertIn("R-4 NOT CHECKED", out)
            self.assertIn("2 of 3 checked rows HOLD", out)

    def test_when_the_checker_holds_every_row_the_verdicts_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, work, _ = self.prepare(tmp, ["R-1", "R-4", "R-5"])
            run(CODEMAP / "slice.py", work / "register-claims.md", repo, "--out", work / "slices")
            reports = work / "reports"
            reports.mkdir()
            claims = (work / "slices/slice-1.claims.txt").read_text().splitlines()
            (reports / "slice-1.md").write_text(report(work / "slices", {}, {l.split(" | ")[0]: "src/notes.py:4" for l in claims}))
            self.assertEqual(run(TRUTH, "verdicts", work, reports)[0], 0)

    def test_a_row_the_checker_gave_no_verdict_counts_as_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, work, _ = self.prepare(tmp, ["R-1", "R-5"])
            reports = work / "reports"
            reports.mkdir()
            (reports / "slice-1.md").write_text("Slice: slice-1\nread | 5.1 | HOLDS | src/notes.py:4\n")
            code, out, _ = run(TRUTH, "verdicts", work, reports)
            self.assertEqual(code, 1)
            self.assertRegex(out, r"R-1 NO VERDICT|R-5 NO VERDICT")

    def test_usage_errors_exit_2_and_no_bytecode_is_left_in_the_deployed_skill_folders(self):
        self.assertEqual(run(TRUTH)[0], 2)
        self.assertEqual(run(TRUTH, "prepare", "/nonexistent", "--out", "/tmp/x")[0], 2)
        self.assertEqual(list(SKILLS.glob("*/scripts/__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
