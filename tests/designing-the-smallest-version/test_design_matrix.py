"""design_matrix.py checks, classifies and renders an Axiomatic Design matrix, run through its real CLI.
Run: python3 -I tests/designing-the-smallest-version/test_design_matrix.py"""
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

STATE = tempfile.mkdtemp(prefix="state-")  # the script logs each run (runlog.py): keep these runs out of the real log
os.environ["XDG_STATE_HOME"] = STATE
atexit.register(shutil.rmtree, STATE, True)

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "dot_local/share/agent-harness/canonical/skills/designing-the-smallest-version/scripts/design_matrix.py"


def dec(n):
    """A DESIGN.md decision id, built so this file does not spell one out."""
    return "D" + str(n)


def run(text, *extra, name="m.md"):
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / name
        path.write_text(text, encoding="utf-8")
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), str(path), *extra], capture_output=True, text=True)
    return done


def build(frs, dps, xs=(), ev=None):
    """frs: (id, dp); dps: ids; xs: (fr, dp) cells, each given a valid reason and evidence (`ev` for all of them, else a path:line).
    Rows are written in the order given."""
    out = ["## FRs", "| id | text | dp |", "|---|---|---|"]
    out += ["| %s | need %s | %s |" % (f, f, d) for f, d in frs]
    out += ["", "## DPs", "| id | text | parts |", "|---|---|---|"]
    out += ["| %s | part %s | src/%s.py |" % (d, d, d.lower()) for d in dps]
    out += ["", "## X", "| fr | dp | reason | evidence |", "|---|---|---|---|"]
    out += ["| %s | %s | %s moves %s | %s |" % (f, d, d, f, ev or "src/%s.py:%d" % (d.lower(), n + 1)) for n, (f, d) in enumerate(xs)]
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


class NotSquareWording(unittest.TestCase):
    def test_which_way_it_is_not_square(self):
        more_frs = run(build([("FR1", "DP1"), ("FR2", "")], ["DP1"])).stdout
        self.assertIn("More FRs than DPs (2 FRs, 1 DPs). Theorem 1", more_frs)
        self.assertIn("coupled, or some FRs cannot be met", more_frs)
        more_dps = run(build([("FR1", "DP1")], ["DP1", "DP2"])).stdout
        self.assertIn("More DPs than FRs (2 DPs, 1 FRs). Theorem 3", more_dps)
        self.assertIn("redundant", more_dps)


class MixedDesign(unittest.TestCase):
    frs = [("FR1", "DP1"), ("FR2", "DP2"), ("FR3", "")]

    def test_paired_part_is_classified_and_unmet_is_said_apart(self):
        r = facts(build(self.frs, ["DP1", "DP2"], [("FR1", "DP2")]))
        self.assertEqual((r["class"], r["paired_class"]), ("not classified", "decoupled"))
        self.assertEqual(r["order"], ["DP2", "DP1"])
        self.assertEqual(r["unmet_frs"], ["FR3"])
        out = run(build(self.frs, ["DP1", "DP2"], [("FR1", "DP2")])).stdout
        self.assertIn("The 2 FR(s) that have a DP of their own (FR1, FR2) are decoupled. DP order (set earlier ones first): DP2 -> DP1.", out)
        self.assertIn("FRs with no DP: FR3.", out)
        header, rows = matrix_rows(out)
        self.assertEqual(header, ["DP2", "DP1"])
        self.assertEqual(rows["FR1"], ["X", "X"])

    def test_coupled_paired_part_still_owes_its_block(self):
        r = facts(build(self.frs, ["DP1", "DP2"], [("FR1", "DP2"), ("FR2", "DP1")]))
        self.assertEqual((r["paired_class"], r["blocks"]), ("coupled", [["DP1", "DP2"]]))
        self.assertIn("coupled block {DP1, DP2}", r["fix_owed"])

    def test_dp_serving_several_frs_is_left_out_of_the_paired_part(self):
        r = facts(build([("FR1", "DP1"), ("FR2", "DP1"), ("FR3", "DP2")], ["DP1", "DP2"]))
        self.assertEqual((r["class"], r["paired_class"], list(r["pair"])), ("not classified", "uncoupled", ["DP2"]))


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

    def test_headings_match_whole(self):
        cell = "| FR1 | DP2 | r | src/a.py:3 |\n"
        for heading in ("## X notes", "## Xray", "## X cells (old)"):
            text = self.base.replace("\n## X\n", "\n%s\n" % heading) + cell
            self.assertEqual(facts(text)["x"], [], heading)
        self.assertEqual(len(facts(self.base + cell)["x"]), 1)
        text = self.base.replace("## DPs", "## DPs overview")
        self.fails(text, "no `## DPs` section")

    def test_unknown_missing_and_repeated_columns(self):
        self.fails(self.base.replace("| id | text | dp |", "| id | text | dps |"), "FRs table: missing column(s) dp; unknown column(s) dps")
        self.fails(self.base.replace("| id | text | parts |", "| id | text | parts | owner |").replace("| DP1 | part DP1 | src/dp1.py |", "| DP1 | part DP1 | src/dp1.py | me |").replace("| DP2 | part DP2 | src/dp2.py |", "| DP2 | part DP2 | src/dp2.py | me |"), "DPs table: unknown column(s) owner")
        self.fails(self.base.replace("| fr | dp | reason | evidence |", "| fr | dp | reason |"), "X table: missing column(s) evidence")
        self.fails(self.base.replace("| id | text | dp |", "| id | id | dp |"), "repeated column(s) id")

    def test_removed_table_needs_as_found(self):
        self.fails(self.base + "\n## Removed\n| fr | dp | by |\n|---|---|---|\n| FR1 | DP2 | %s |\n" % dec(1), "needs --as-found")


class TargetEvidence(unittest.TestCase):
    base = build([("FR1", "DP1"), ("FR2", "DP2")], ["DP1", "DP2"])

    def test_design_ids_are_target_evidence_only(self):
        for ev in (dec(2), "G1", "T" + "3", "OR-4", "IR-1"):
            text = self.base + "| FR1 | DP2 | a decision makes FR1 depend on DP2 | %s |\n" % ev
            self.assertEqual(run(text, "--target").returncode, 0, ev)
            done = run(text)
            self.assertEqual(done.returncode, 1, ev)
            self.assertIn("run with --target", done.stderr)

    def test_target_x_citing_only_code_is_refused(self):
        text = self.base + "| FR1 | DP2 | because | src/a.py:3 |\n"
        done = run(text, "--target")
        self.assertEqual(done.returncode, 1)
        self.assertIn("a target X needs a reason, not only code", done.stderr)
        self.assertEqual(run(text).returncode, 0)  # as found, code is the evidence
        self.assertEqual(run(self.base + "| FR1 | DP2 | because | src/a.py:3; %s |\n" % dec(2), "--target").returncode, 0)

    def test_mode_b_target_alone_runs_with_target(self):
        done = run(self.base + "| FR1 | DP2 | %s puts the check in DP2 | %s |\n" % (dec(4), dec(4)), "--target")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Classification: decoupled", done.stdout)

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
    target = build(frs, ["DP1", "DP2"], [("FR2", "DP1")], ev=dec(1))

    def go(self, target_text):
        found, target = pair_files(self.found, target_text)
        return subprocess.run([sys.executable, "-I", str(SCRIPT), target, "--as-found", found], capture_output=True, text=True)

    def test_removed_x_without_a_decision_is_refused(self):
        done = self.go(self.target)
        self.assertEqual(done.returncode, 1)
        self.assertIn("X (FR1, DP2) is in the as-found matrix and gone from the target", done.stderr)

    def test_removed_x_with_a_decision_passes_and_is_listed(self):
        done = self.go(self.target + "\n## Removed\n| fr | dp | by |\n|---|---|---|\n| FR1 | DP2 | %s |\n" % dec(3))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("removed X (FR1, DP2) by " + dec(3), done.stdout)
        self.assertIn("Classification: decoupled", done.stdout)

    def test_removed_by_must_be_a_decision_of_a_removed_cell(self):
        row = "\n## Removed\n| fr | dp | by |\n|---|---|---|\n| %s | %s | %s |\n"
        self.assertIn("must be a decision id", self.go(self.target + row % ("FR1", "DP2", "OR-1")).stderr)
        self.assertIn("the target still has this X", self.go(self.target + row % ("FR2", "DP1", dec(3))).stderr)
        self.assertIn("the as-found matrix has no such X", self.go(self.target + row % ("FR1", "DP1", dec(3))).stderr)

    def test_added_x_is_listed_and_may_cite_a_decision(self):
        found, target = pair_files(build(self.frs, ["DP1", "DP2"], [("FR2", "DP1")]),
                                   build(self.frs, ["DP1", "DP2"], [("FR2", "DP1")], ev=dec(1)) + "| FR1 | DP2 | %s moves the check into DP2 | %s |\n" % (dec(5), dec(5)))
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), target, "--as-found", found], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("added X (FR1, DP2): %s moves the check into DP2 [%s]" % (dec(5), dec(5)), done.stdout)


class RunLog(unittest.TestCase):
    """Every exit leaves one record in the run log (design-principles.md §14): ok, failed, refused (either input, --out, a usage error); logged.py also records a crash."""
    frs = [("FR1", "DP1"), ("FR2", "DP2")]

    def last_record(self, done):
        """The newest record and the record count."""
        path = Path(os.environ["XDG_STATE_HOME"]) / "designing-the-smallest-version" / "log.jsonl"  # read now: another test module in the run may have set it last
        lines = path.read_text(encoding="utf-8").splitlines()
        return json.loads(lines[-1]), len(lines)

    def records(self):
        path = Path(os.environ["XDG_STATE_HOME"]) / "designing-the-smallest-version" / "log.jsonl"  # read now: another test module in the run may have set it last
        return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0

    def test_ok_run_logs_ok(self):
        before = self.records()
        done = run(build(self.frs, ["DP1", "DP2"]))
        self.assertEqual(done.returncode, 0, done.stderr)
        rec, n = self.last_record(done)
        self.assertEqual((n, rec["script"], rec["outcome"], rec["cls"]), (before + 1, "design_matrix.py", "ok", "uncoupled"))

    def test_unreadable_input_logs_refused(self):
        before = self.records()
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "/nonexistent/m.md"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        rec, n = self.last_record(done)
        self.assertEqual((n, rec["outcome"], rec["reason"]), (before + 1, "refused", "unreadable input"))

    def test_unreadable_as_found_logs_refused(self):
        before = self.records()
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "t.md"
            target.write_text(build(self.frs, ["DP1", "DP2"], ev=dec(1)), encoding="utf-8")
            done = subprocess.run([sys.executable, "-I", str(SCRIPT), str(target), "--as-found", str(Path(d) / "missing.md")], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        rec, n = self.last_record(done)
        self.assertEqual((n, rec["outcome"], rec["reason"]), (before + 1, "refused", "unreadable as-found input"))

    def test_usage_error_logs_refused(self):
        before = self.records()
        done = subprocess.run([sys.executable, "-I", str(SCRIPT), "--bogus"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)
        rec, n = self.last_record(done)
        self.assertEqual((n, rec["outcome"], rec["exit"]), (before + 1, "refused", 2))

    def test_unwritable_out_logs_refused(self):
        before = self.records()
        done = run(build(self.frs, ["DP1", "DP2"]), "--out", "/nonexistent/dir/out.md")
        self.assertEqual(done.returncode, 2)
        self.assertIn("cannot write --out", done.stderr)
        rec, n = self.last_record(done)
        self.assertEqual((n, rec["outcome"], rec["reason"]), (before + 1, "refused", "cannot write --out"))

    def test_invalid_tables_log_failed(self):
        before = self.records()
        done = run(build([("FR1", "DP9"), ("FR2", "DP2")], ["DP1", "DP2"]))  # FR1 names a DP that is not in the table
        self.assertEqual(done.returncode, 1)
        rec, n = self.last_record(done)
        self.assertEqual((n, rec["outcome"]), (before + 1, "failed"))


class SharedParts(unittest.TestCase):
    frs = [("FR1", "DP1"), ("FR2", "DP2")]

    def god(self, xs=(), shared=""):
        text = build(self.frs, ["DP1", "DP2"], xs).replace("src/dp2.py", "src/dp1.py")
        return text + shared

    def test_shared_part_with_neither_x_nor_reason_is_flagged(self):
        r = facts(self.god())
        self.assertEqual(r["shared_parts_unexplained"], {"src/dp1.py": [["DP1", "DP2"]]})
        self.assertIn("part src/dp1.py is in DP1 and DP2 with neither an X between them nor a `## Shared` reason", r["fix_owed"])

    def test_an_x_between_the_pair_covers_it_either_way(self):
        self.assertEqual(facts(self.god([("FR1", "DP2")]))["fix_owed"], [])
        self.assertEqual(facts(self.god([("FR2", "DP1")]))["fix_owed"], [])

    def test_a_written_reason_covers_it(self):
        text = self.god(shared="\n## Shared\n| dp1 | dp2 | reason |\n|---|---|---|\n| DP2 | DP1 | the file is a constants table, edited by neither |\n")
        r = facts(text)
        self.assertEqual((r["shared_parts_unexplained"], r["fix_owed"]), ({}, []))
        self.assertIn("Shared part, no coupling (DP1, DP2): the file is a constants table", run(text).stdout)

    def test_bad_shared_rows_are_refused(self):
        head = "\n## Shared\n| dp1 | dp2 | reason |\n|---|---|---|\n"
        for row, needle in (("| DP1 | DP2 |  |", "reason is missing"), ("| DP1 | DP9 | r |", "two different DPs"), ("| DP1 | DP1 | r |", "two different DPs")):
            done = run(self.god(shared=head + row + "\n"))
            self.assertEqual(done.returncode, 1, row)
            self.assertIn(needle, done.stderr)
        apart = build(self.frs, ["DP1", "DP2"]) + head + "| DP1 | DP2 | r |\n"
        self.assertIn("share no part", run(apart).stderr)


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
        with tempfile.TemporaryDirectory() as d:
            rendered = Path(d) / "target.md"
            rendered.write_text(re.sub(r"<dec-(\d+)>", lambda m: dec(m.group(1)), self.target.read_text()), encoding="utf-8")
            done = subprocess.run([sys.executable, "-I", str(SCRIPT), str(rendered), "--as-found", str(self.found), "--json"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        t = json.loads(done.stdout)
        self.assertEqual((a["class"], a["blocks"]), ("coupled", [["DP2", "DP6"]]))
        self.assertEqual(t["class"], "decoupled")
        self.assertEqual(t["order"], ["DP1", "DP4", "DP5", "DP2", "DP3", "DP6"])
        self.assertEqual([(c["fr"], c["dp"], c["by"]) for c in t["changes"]["removed"]], [("FR2", "DP6", dec(1)), ("FR6", "DP2", dec(2))])
        self.assertEqual([(c["fr"], c["dp"]) for c in t["changes"]["added"]], [("FR6", "DP3")])

    def test_fixtures_are_marked_illustrative_and_cite_no_code(self):
        for path in (self.found, self.target):
            text = path.read_text()
            self.assertIn("Illustrative example, not a real repo", text)
            self.assertNotRegex(text, r"\w+\.py:\d+|commit:")


class QualifiedIds(unittest.TestCase):
    """Two registers each have an F-1: a finding cited from one of several registers carries its label, `<label>:F-1`."""
    base = build([("FR1", "DP1"), ("FR2", "DP2")], ["DP1", "DP2"])

    def x(self, evidence, *extra):
        return run(self.base + "| FR1 | DP2 | because | %s |\n" % evidence, *extra)

    def test_a_qualified_finding_id_is_evidence_as_found_and_in_a_target(self):
        for ev in ("core:F-3", "cli:U-1", "loop-core:F-12", "core:F-3; src/a.py:3"):
            self.assertEqual(self.x(ev).returncode, 0, ev)
            self.assertEqual(self.x(ev, "--target").returncode, 0, ev)

    def test_a_label_is_lowercase_and_the_designs_own_findings_stay_bare(self):
        for ev in ("Core:F-3", "core:DF-3", "core:R-3x", ":F-3", "core:F-", "commit:F-3"):
            done = self.x(ev)
            self.assertEqual(done.returncode, 1, ev)
            self.assertIn("is none of path:line", done.stderr)

    def test_the_bare_forms_still_pass(self):
        self.assertEqual(self.x("F-3; DF-2; U-1").returncode, 0)


if __name__ == "__main__":
    unittest.main()
