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

    def test_out_file_and_label(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "o.md"
            done = run(self.base, "--out", str(out), "--label", "Target")
            self.assertEqual((done.returncode, done.stdout), (0, ""), done.stderr)
            self.assertTrue(out.read_text().startswith("#### Target"))

    def test_no_frs_is_not_a_matrix(self):
        self.fails("## FRs\n| id | text | dp |\n|---|---|---|\n\n## DPs\n| id | text |\n|---|---|\n", "no FRs")

    def test_any_heading_ends_a_table(self):
        text = self.base.replace("\n## X", "\n## Notes\n| id | text | parts |\n|---|---|---|\n| DP9 | stray | z |\n\n## X")
        self.assertEqual([d["id"] for d in facts(text)["dps"]], ["DP1", "DP2"])

    def test_removed_table_needs_as_found(self):
        self.fails(self.base + "\n## Removed\n| fr | dp | by |\n|---|---|---|\n| FR1 | DP2 | D1 |\n", "needs --as-found")


class TargetEvidence(unittest.TestCase):
    base = build([("FR1", "DP1"), ("FR2", "DP2")], ["DP1", "DP2"])

    def test_design_ids_are_target_evidence_only(self):
        for ev in ("D2", "G1", "T3", "OR-4", "IR-1"):
            text = self.base + "| FR1 | DP2 | decision D2 makes FR1 depend on DP2 | %s |\n" % ev
            self.assertEqual(run(text, "--target").returncode, 0, ev)
            done = run(text)
            self.assertEqual(done.returncode, 1, ev)
            self.assertIn("is none of", done.stderr)

    def test_cochange_only_x_is_listed(self):
        r = facts(self.base + "| FR1 | DP2 | they change together because of the shared format | cochange:a.py+b.py |\n")
        self.assertEqual(r["x_cochange_only"], [{"fr": "FR1", "dp": "DP2"}])
        out = run(self.base + "| FR1 | DP2 | r | cochange:a.py+b.py |\n").stdout
        self.assertIn("cites only co-change, which is correlation", out)
        mixed = facts(self.base + "| FR1 | DP2 | r | cochange:a.py+b.py; src/a.py:3 |\n")
        self.assertEqual(mixed["x_cochange_only"], [])


def pair_files(found, target):
    d = tempfile.mkdtemp()
    atexit.register(shutil.rmtree, d, True)
    for name, text in (("found.md", found), ("target.md", target)):
        (Path(d) / name).write_text(text, encoding="utf-8")
    return str(Path(d) / "found.md"), str(Path(d) / "target.md")


class AsFoundVersusTarget(unittest.TestCase):
    frs = [("FR1", "DP1"), ("FR2", "DP2")]
    found = build(frs, ["DP1", "DP2"], [("FR1", "DP2"), ("FR2", "DP1")])  # coupled
    target = build(frs, ["DP1", "DP2"], [("FR2", "DP1")]) + ""

    def go(self, target_text):
        found, target = pair_files(self.found, target_text)
        return subprocess.run([sys.executable, "-I", str(SCRIPT), target, "--as-found", found], capture_output=True, text=True)

    def test_removed_x_without_a_decision_is_refused(self):
        done = self.go(self.target)
        self.assertEqual(done.returncode, 1)
        self.assertIn("X (FR1, DP2) is in the as-found matrix and gone from the target", done.stderr)

    def test_removed_x_with_a_decision_passes_and_is_listed(self):
        done = self.go(self.target + "\n## Removed\n| fr | dp | by |\n|---|---|---|\n| FR1 | DP2 | D3 |\n")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("removed X (FR1, DP2) by D3", done.stdout)
        self.assertIn("Classification: decoupled", done.stdout)

    def test_removed_by_must_be_a_decision_of_a_removed_cell(self):
        row = "\n## Removed\n| fr | dp | by |\n|---|---|---|\n| %s | %s | %s |\n"
        self.assertIn("must be a decision id", self.go(self.target + row % ("FR1", "DP2", "OR-1")).stderr)
        self.assertIn("the target still has this X", self.go(self.target + row % ("FR2", "DP1", "D3")).stderr)
        self.assertIn("the as-found matrix has no such X", self.go(self.target + row % ("FR1", "DP1", "D3")).stderr)

    def test_added_x_is_listed_and_may_cite_a_decision(self):
        found, target = pair_files(build(self.frs, ["DP1", "DP2"], [("FR2", "DP1")]),
                                   build(self.frs, ["DP1", "DP2"], [("FR2", "DP1")]) + "| FR1 | DP2 | D5 moves the check into DP2 | D5 |\n")
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), target, "--as-found", found], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("added X (FR1, DP2): D5 moves the check into DP2 [D5]", done.stdout)


class FixOwed(unittest.TestCase):
    def test_god_module_owes_a_fix(self):
        r = facts(build([("FR1", "DP1"), ("FR2", "DP1"), ("FR3", "DP2")], ["DP1", "DP2"]))
        self.assertEqual(r["class"], "not classified")
        self.assertIn("DP DP1 delivers several FRs (FR1, FR2)", r["fix_owed"])
        self.assertIn("Fix owed", run(build([("FR1", "DP1"), ("FR2", "DP1")], ["DP1"])).stdout)

    def test_non_square_and_unmet_owe_a_fix(self):
        r = facts(build([("FR1", "DP1"), ("FR2", "")], ["DP1"]))
        self.assertIn("FR FR2 has no DP", r["fix_owed"])
        self.assertIn("the matrix is not square, so it is not classified", r["fix_owed"])

    def test_coupled_block_owes_a_fix_and_decoupled_owes_none(self):
        frs = [("FR1", "DP1"), ("FR2", "DP2")]
        self.assertEqual(facts(build(frs, ["DP1", "DP2"], [("FR1", "DP2"), ("FR2", "DP1")]))["fix_owed"], ["coupled block {DP1, DP2}"])
        self.assertEqual(facts(build(frs, ["DP1", "DP2"], [("FR1", "DP2")]))["fix_owed"], [])


class Warnings(unittest.TestCase):
    def test_more_than_nine_frs_warns_and_exits_0(self):
        frs = [("FR%d" % i, "DP%d" % i) for i in range(1, 11)]
        done = run(build(frs, ["DP%d" % i for i in range(1, 11)]))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("warning: 10 FRs", done.stderr)
        self.assertIn("Warning: 10 FRs", done.stdout)
        self.assertEqual(run(build(frs[:9], ["DP%d" % i for i in range(1, 10)])).stderr, "")


class LoopEngineExample(unittest.TestCase):
    """An illustrative example of 6 FRs: its evidence is a placeholder register and decisions, never invented code lines."""
    found = HERE / "fixtures/loop-engine-as-found.md"
    target = HERE / "fixtures/loop-engine-target.md"

    def test_as_found_is_coupled_and_target_is_decoupled(self):
        a = facts(self.found.read_text())
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), str(self.target), "--as-found", str(self.found), "--json"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        t = json.loads(done.stdout)
        self.assertEqual((a["class"], a["blocks"]), ("coupled", [["DP2", "DP6"]]))
        self.assertEqual(t["class"], "decoupled")
        self.assertEqual(t["order"], ["DP1", "DP4", "DP5", "DP2", "DP3", "DP6"])
        self.assertEqual([(c["fr"], c["dp"], c["by"]) for c in t["changes"]["removed"]], [("FR2", "DP6", "D1"), ("FR6", "DP2", "D2")])
        self.assertEqual([(c["fr"], c["dp"]) for c in t["changes"]["added"]], [("FR6", "DP3")])

    def test_fixtures_are_marked_illustrative_and_cite_no_code(self):
        for path in (self.found, self.target):
            text = path.read_text()
            self.assertIn("Illustrative example, not a real repo", text)
            self.assertNotRegex(text, r"\w+\.py:\d+|commit:")


if __name__ == "__main__":
    unittest.main()
