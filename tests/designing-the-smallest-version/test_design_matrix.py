"""design_matrix.py checks, classifies and renders an Axiomatic Design matrix, run through its real CLI.
Run: python3 -I tests/designing-the-smallest-version/test_design_matrix.py"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = tempfile.mkdtemp(prefix="state-")  # the script logs each run (runlog.py): keep these runs out of the real log
os.environ["XDG_STATE_HOME"] = STATE
atexit.register(shutil.rmtree, STATE, True)

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "dot_local/share/agent-harness/canonical/skills/designing-the-smallest-version/scripts/design_matrix.py"


def run(text, *extra, name="m.md"):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / name
        path.write_text(text, encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), str(path), *extra], capture_output=True, text=True)
    return done


def build(frs, dps, xs=()):
    """frs: (id, dp); dps: ids; xs: (fr, dp) cells, each given a valid reason and evidence. Rows are written in the order given."""
    out = ["## FRs", "| id | text | dp |", "|---|---|---|"]
    out += ["| %s | need %s | %s |" % (f, f, d) for f, d in frs]
    out += ["", "## DPs", "| id | text | parts |", "|---|---|---|"]
    out += ["| %s | part %s | src/%s.py |" % (d, d, d.lower()) for d in dps]
    out += ["", "## X", "| fr | dp | reason | evidence |", "|---|---|---|---|"]
    out += ["| %s | %s | %s moves %s | src/%s.py:%d |" % (f, d, d, f, d.lower(), n + 1) for n, (f, d) in enumerate(xs)]
    return "\n".join(out) + "\n"


def facts(text):
    done = run(text, "--json")
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def matrix_rows(markdown):
    """{row FR: [marks]} and the column header, from the rendered matrix."""
    lines = [ln for ln in markdown.splitlines() if ln.startswith("|")]
    header = [c.strip() for c in lines[0].strip("|").split("|")][1:]
    rows = {}
    for ln in lines[2:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if not cells[0].startswith("**"):
            break
        rows[cells[0].strip("*")] = cells[1:]
    return header, rows


class Classes(unittest.TestCase):
    def test_uncoupled_is_diagonal(self):
        r = facts(build([("FR1", "DP1"), ("FR2", "DP2")], ["DP1", "DP2"]))
        self.assertEqual(r["class"], "uncoupled")
        self.assertEqual(r["blocks"], [])

    def test_decoupled_gives_order_and_triangle_whatever_the_input_order(self):
        cells = [("FR1", "DP3"), ("FR2", "DP3"), ("FR1", "DP2")]  # DP3 -> FR1, DP3 -> FR2, DP2 -> FR1: order DP3, DP2, DP1
        frs = [("FR1", "DP1"), ("FR2", "DP2"), ("FR3", "DP3")]
        a = run(build(frs, ["DP1", "DP2", "DP3"], cells))
        b = run(build(list(reversed(frs)), ["DP3", "DP2", "DP1"], list(reversed(cells))))
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertIn("Classification: decoupled.", a.stdout)
        header, rows = matrix_rows(a.stdout)
        self.assertEqual(header, ["DP3", "DP2", "DP1"])
        pair = {"DP1": "FR1", "DP2": "FR2", "DP3": "FR3"}
        for j, dp in enumerate(header):  # the FR of column j is row j: no X to the right of the diagonal (lower triangle)
            for i, mark in enumerate(rows[pair[dp]]):
                if i > j:
                    self.assertEqual(mark, "0", "%s has an X above the diagonal at column %s" % (pair[dp], header[i]))
        self.assertEqual(rows["FR3"], ["X", "0", "0"])
        self.assertEqual(rows["FR2"], ["X", "X", "0"])
        self.assertEqual(rows["FR1"], ["X", "X", "X"])
        self.assertEqual(a.stdout.split("Off-diagonal")[0], b.stdout.split("Off-diagonal")[0])

    def test_order_ties_break_by_natural_id(self):
        r = facts(build([("FR10", "DP10"), ("FR9", "DP9"), ("FR2", "DP2")], ["DP10", "DP9", "DP2"], [("FR10", "DP2")]))
        self.assertEqual(r["class"], "decoupled")
        self.assertEqual(r["order"], ["DP2", "DP9", "DP10"])

    def test_coupled_lists_blocks_as_scc(self):
        frs = [("FR1", "DP1"), ("FR2", "DP2"), ("FR3", "DP3"), ("FR4", "DP4")]
        cells = [("FR1", "DP2"), ("FR2", "DP1"), ("FR3", "DP1"), ("FR4", "DP3")]
        r = facts(build(frs, ["DP1", "DP2", "DP3", "DP4"], cells))
        self.assertEqual(r["class"], "coupled")
        self.assertEqual(r["blocks"], [["DP1", "DP2"]])
        self.assertEqual(r["order"], ["DP1", "DP2", "DP3", "DP4"])
        out = run(build(frs, ["DP1", "DP2", "DP3", "DP4"], cells)).stdout
        self.assertIn("Classification: coupled. Coupled blocks (strongly connected): {DP1, DP2}.", out)

    def test_two_separate_cycles_are_two_blocks(self):
        frs = [("FR%d" % i, "DP%d" % i) for i in range(1, 5)]
        r = facts(build(frs, ["DP1", "DP2", "DP3", "DP4"], [("FR1", "DP2"), ("FR2", "DP1"), ("FR3", "DP4"), ("FR4", "DP3")]))
        self.assertEqual(r["blocks"], [["DP1", "DP2"], ["DP3", "DP4"]])


class NotSquare(unittest.TestCase):
    def test_fewer_dps_than_frs_is_unmet_and_theorem_1(self):
        out = run(build([("FR1", "DP1"), ("FR2", "")], ["DP1"]))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("not classified", out.stdout)
        self.assertIn("Theorem 1", out.stdout)
        self.assertIn("FRs with no DP: FR2.", out.stdout)
        self.assertEqual(facts(build([("FR1", "DP1"), ("FR2", "")], ["DP1"]))["unmet_frs"], ["FR2"])

    def test_two_frs_naming_one_dp(self):
        r = facts(build([("FR1", "DP1"), ("FR2", "DP1")], ["DP1"]))
        self.assertEqual(r["class"], "not classified")
        self.assertEqual(r["dps_serving_several_frs"], {"DP1": ["FR1", "FR2"]})
        self.assertIn("Theorem 1", r["theorem"])

    def test_more_dps_than_frs_is_redundant_and_names_removal_candidates(self):
        text = build([("FR1", "DP1")], ["DP1", "DP2"], [("FR1", "DP2")])
        out = run(text)
        self.assertIn("Theorem 3", out.stdout)
        self.assertIn("DP DP2 serves no FR (removal candidate); it still affects FR1", out.stdout)
        self.assertEqual(facts(text)["removal_candidates"], ["DP2"])

    def test_same_count_but_unpaired_is_not_classified(self):
        r = facts(build([("FR1", "DP1"), ("FR2", "")], ["DP1", "DP2"]))
        self.assertEqual(r["class"], "not classified")
        self.assertEqual(r["unmet_frs"], ["FR2"])
        self.assertEqual(r["removal_candidates"], ["DP2"])
        self.assertIn("Theorem 4", r["theorem"])

    def test_part_in_several_dps_is_reported_not_judged(self):
        text = build([("FR1", "DP1"), ("FR2", "DP2")], ["DP1", "DP2"]).replace("src/dp2.py", "src/dp1.py")
        r = facts(text)
        self.assertEqual(r["class"], "uncoupled")
        self.assertEqual(r["parts_in_several_dps"], {"src/dp1.py": ["DP1", "DP2"]})


class BadInput(unittest.TestCase):
    base = build([("FR1", "DP1"), ("FR2", "DP2")], ["DP1", "DP2"])

    def fails(self, text, needle):
        done = run(text)
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn(needle, done.stderr)
        self.assertEqual(done.stdout, "")

    def test_missing_reason(self):
        self.fails(self.base + "| FR1 | DP2 |  | src/a.py:3 |\n", "reason is missing")

    def test_missing_evidence(self):
        self.fails(self.base + "| FR1 | DP2 | because |  |\n", "evidence is missing")

    def test_an_import_is_not_evidence(self):
        self.fails(self.base + "| FR1 | DP2 | because | import a |\n", "is none of path:line")

    def test_evidence_kinds_pass(self):
        ev = "src/a.py:3-9; cochange:a.py+b.py; commit:3fa9c21; DF-4"
        self.assertEqual(run(self.base + "| FR1 | DP2 | because | %s |\n" % ev).returncode, 0)

    def test_unknown_and_duplicate_ids(self):
        self.fails(self.base + "| FR9 | DP2 | because | F-1 |\n", "FR9 is not in the FR table")
        self.fails(self.base + "| FR1 | DP9 | because | F-1 |\n", "DP9 is not in the DP table")
        self.fails(self.base.replace("| FR2 | need FR2 | DP2 |", "| FR1 | need FR2 | DP2 |"), "FR FR1: listed twice")
        self.fails(self.base.replace("| FR2 | need FR2 | DP2 |", "| FR2 | need FR2 | DP7 |"), "dp DP7 is not in the DP table")

    def test_diagonal_cell_and_duplicate_cell_are_refused(self):
        self.fails(self.base + "| FR1 | DP1 | because | F-1 |\n", "the diagonal is implied")
        self.fails(self.base + "| FR1 | DP2 | a | F-1 |\n| FR1 | DP2 | b | F-1 |\n", "listed twice")

    def test_missing_section_and_bad_row(self):
        self.fails("## FRs\n| id | text | dp |\n|---|---|---|\n| FR1 | x | DP1 |\n", "no `## DPs` section")
        self.fails(self.base.replace("| FR1 | need FR1 | DP1 |", "| FR1 | need FR1 |"), "row has 2 cells")

    def test_json_input_and_out_file(self):
        data = {"frs": [{"id": "FR1", "text": "a", "dp": "DP1"}, {"id": "FR2", "text": "b", "dp": "DP2"}],
                "dps": [{"id": "DP1", "text": "p", "parts": ["x.py"]}, {"id": "DP2", "text": "q"}],
                "x": [{"fr": "FR2", "dp": "DP1", "reason": "r", "evidence": "x.py:1"}]}
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "o.md"
            done = run(json.dumps(data), "--out", str(out), "--label", "Target", name="m.json")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(done.stdout, "")
            text = out.read_text()
        self.assertTrue(text.startswith("#### Target"))
        self.assertIn("Classification: decoupled. DP order (set earlier ones first): DP1 -> DP2.", text)


class LoopEngineExample(unittest.TestCase):
    """A hand-written example of 6 FRs: its evidence is invented, its shape is the one the skill documents."""

    def test_as_found_is_coupled_and_target_is_decoupled(self):
        found = facts((HERE / "fixtures/loop-engine-as-found.md").read_text())
        target = facts((HERE / "fixtures/loop-engine-target.md").read_text())
        self.assertEqual((found["class"], found["blocks"]), ("coupled", [["DP2", "DP6"]]))
        self.assertEqual(target["class"], "decoupled")
        self.assertEqual(target["order"], ["DP1", "DP4", "DP5", "DP2", "DP3", "DP6"])


if __name__ == "__main__":
    unittest.main()
