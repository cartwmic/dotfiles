"""check_truth.py: truth-check fix rounds after the first check only the rows the previous fix round changed (references/truth-check.md, step 5).
The fixture register and the recorded checker report are those of test_check_truth.py.
Run: python3 -m unittest discover -s tests/distilling-requirements"""
import runlog_support  # first: keeps the run out of the real log
import tempfile
import unittest
from pathlib import Path

from test_check_truth import CODEMAP, TRUTH, make, report, run

STATE = runlog_support.STATE  # runlog_support keeps these runs out of the real log


def check_round(repo, work, verdicts):
    """Slice the claims doc of a round, record a checker report (default HOLDS, `verdicts` by row sentence start), run verdicts; (exit code, output)."""
    run(CODEMAP / "slice.py", work / "register-claims.md", repo, "--out", work / "slices")
    claims = [l.split(" | ", 2) for l in (work / "slices/slice-1.claims.txt").read_text().splitlines()]
    chosen = {cid: v for cid, _, sentence in claims for start, v in verdicts.items() if sentence.startswith(start)}
    reports = work / "reports"
    reports.mkdir()
    (reports / "slice-1.md").write_text(report(work / "slices", chosen, {cid: "src/notes.py:4" for cid, _, _ in claims}))
    code, out, _ = run(TRUTH, "verdicts", work, reports)
    return code, out


class LaterRounds(unittest.TestCase):
    def round1(self, tmp):
        repo, req, work = make(tmp, ["R-1", "R-2", "R-5"])
        self.assertEqual(run(TRUTH, "prepare", req, "--out", work / "round1")[0], 0)
        code, out = check_round(repo, work / "round1", {"Clearing": "WRONG"})
        self.assertEqual(code, 1)
        self.assertIn("R-2 WRONG", out)
        return repo, req, work

    def test_round_two_checks_only_the_row_the_fix_changed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, req, work = self.round1(tmp)
            req.write_text(req.read_text().replace("Clearing the store shall keep the saved notes.", "Clearing the store shall empty the saved notes."))
            code, out, err = run(TRUTH, "prepare", req, "--out", work / "round2", "--since", work / "round1")
            self.assertEqual(code, 0, err)
            self.assertIn("2 rows unchanged since", out)
            self.assertIn("R-1, R-5", out)
            self.assertIn("1 rows to check", out)
            doc = (work / "round2/register-claims.md").read_text()
            self.assertIn("Clearing the store shall empty the saved notes.", doc)
            self.assertNotIn("An empty note", doc)
            self.assertNotIn("(README)", doc)
            code, out = check_round(repo, work / "round2", {})
            self.assertEqual(code, 0, out)
            self.assertIn("R-2 HOLDS src/notes.py", out)
            self.assertIn("R-1 HOLDS unchanged since the last round", out)
            self.assertIn("R-5 HOLDS unchanged since the last round", out)
            self.assertIn("1 of 1 checked rows HOLD", out)
            self.assertIn("2 unchanged since the last round, not checked again", out)

    def test_a_row_that_failed_and_was_left_alone_is_checked_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, req, work = self.round1(tmp)
            code, out, _ = run(TRUTH, "prepare", req, "--out", work / "round2", "--since", work / "round1")
            self.assertEqual(code, 0)
            self.assertIn("2 rows unchanged", out)
            self.assertIn("Clearing the store", (work / "round2/register-claims.md").read_text())
            code, out = check_round(repo, work / "round2", {"Clearing": "WRONG"})
            self.assertEqual(code, 1)  # the carried rows do not hide it
            self.assertIn("R-2 WRONG", out)

    def test_a_third_round_still_carries_what_the_first_round_held(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, req, work = self.round1(tmp)
            req.write_text(req.read_text().replace("Clearing the store shall keep the saved notes.", "Clearing the store shall empty the saved notes."))
            run(TRUTH, "prepare", req, "--out", work / "round2", "--since", work / "round1")
            check_round(repo, work / "round2", {"Clearing": "OVERSTATED"})
            req.write_text(req.read_text().replace("shall empty the saved notes.", "shall remove every saved note."))
            code, out, _ = run(TRUTH, "prepare", req, "--out", work / "round3", "--since", work / "round2")
            self.assertEqual(code, 0)
            self.assertIn("2 rows unchanged", out)
            self.assertIn("R-1, R-5", out)

    def test_since_needs_verdicts_to_have_run_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, req, work = make(tmp, ["R-1"])
            (work / "round1").mkdir(parents=True)
            code, _, err = run(TRUTH, "prepare", req, "--out", work / "round2", "--since", work / "round1")
            self.assertEqual(code, 2)
            self.assertIn("run `verdicts` in that folder first", err)

    def test_truth_check_says_later_rounds_check_only_changed_rows_and_why(self):
        text = (Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/distilling-requirements/references/truth-check.md").read_text()
        self.assertIn("A later round checks only the rows the previous fix round changed", text)
        self.assertIn("already checked against the same code", text)
        self.assertIn("--since", text)


if __name__ == "__main__":
    unittest.main()
