"""The fix round of the extend mode: check_citations.py (row budget, one sentence a line, duplicate lines, numbers across `_`, `,` and k/M), coverage.py (placement),
inventory.py and final_recheck.py (re-check routing). Each test breaks one rule and fails without its change.
Run: python3 -I tests/deriving-readable-docs/test_extend_fixes.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True
import coverage  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_coverage as cov  # noqa: E402
import test_final_recheck as base  # noqa: E402
SKILL_DIR = SCRIPTS.parent
EXTEND = (SKILL_DIR / "references/extend.md").read_text(encoding="utf-8")
LISTER = (SKILL_DIR / "references/coverage-lister.md").read_text(encoding="utf-8")


def make_repo(files):
    tmp = tempfile.TemporaryDirectory()
    for rel, text in files.items():
        p = Path(tmp.name) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp


def check(doc, files, *extra):
    with make_repo(files) as repo, tempfile.TemporaryDirectory() as d:
        docp = Path(d) / "DOC.md"
        docp.write_text(doc)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), str(docp), repo, *extra], capture_output=True, text=True)
    return r.returncode, r.stdout


REPO = {"src/a.rs": "one\ntwo\nthree\n"}


class RowBudgetTest(unittest.TestCase):
    """F7: a writer's budget is rows x 25 words; the `## A<n> <title>` heading is not a row."""
    DOC = "## A4 Adding and listing notes\n\nIt saves a note in the test (`src/a.rs:1`).\nIt lists a note in the test (`src/a.rs:2`).\n"  # 5 heading words, 2 rows of 7 words

    def test_the_heading_is_not_counted_against_the_row_budget(self):
        code, out = check(self.DOC, REPO, "--max-row-words", "14")
        self.assertEqual(code, 0, out)
        code, out = check(self.DOC, REPO, "--max-row-words", "13")
        self.assertEqual(code, 1)
        self.assertIn("FAIL budget: 14 words outside the headings, budget 13", out)

    def test_max_words_still_counts_the_heading(self):
        self.assertEqual(check(self.DOC, REPO, "--max-words", "18")[0], 1)
        self.assertEqual(check(self.DOC, REPO, "--max-words", "19")[0], 0)

    def test_extend_md_gives_the_writer_the_row_budget_flag(self):
        step = EXTEND.split("## E3")[1].split("## E4")[0]
        self.assertIn("--max-row-words <rows x estimate>", step)
        self.assertNotIn("--max-words <rows x estimate>", step)

    def test_a_row_budget_that_is_not_a_number_is_a_usage_error(self):
        self.assertEqual(check(self.DOC, REPO, "--max-row-words", "lots")[0], 2)


APPENDIX = "# Part 2: Appendix\n\n## A4 Adding\n\n%s"


class OneSentenceLineTest(unittest.TestCase):
    """F5: the check refuses an appendix line of two sentences, so the writer learns it at write time and not when stamp.py refuses it."""

    def test_an_appendix_line_of_two_sentences_fails_and_names_the_line(self):
        code, out = check(APPENDIX % "It saves a note. It lists notes. `src/a.rs:1`\n", REPO)
        self.assertEqual(code, 1, out)
        self.assertIn("DOC.md:5: FAIL sentences: 2 sentences on one line", out)

    def test_one_sentence_a_line_passes_and_a_stop_inside_a_quoted_message_is_one_sentence(self):
        doc = APPENDIX % 'It saves a note. `src/a.rs:1`\nIt says "Unable to save. Try again." `src/a.rs:2`\n'
        code, out = check(doc, {"src/a.rs": "x\nUnable to save. Try again.\n"})
        self.assertEqual(code, 0, out)

    def test_part_1_lines_of_several_sentences_are_not_refused(self):
        doc = "# Part 1: In plain English\n\n## What it is\n\nIt saves notes. It lists notes. [A4.0001]\n" + (APPENDIX % "It saves a note. `src/a.rs:1` [A4.0001]\n")
        self.assertEqual(check(doc, REPO)[0], 0)


class NumberFormTest(unittest.TestCase):
    """F4: a number is the same number in digits with `_` or `,` between the groups, and with the words thousand and million."""

    def passes(self, sentence, code_line):
        code, out = check("## A4 Limits\n\n%s `src/a.ts:1`\n" % sentence, {"src/a.ts": code_line + "\n"})
        return code == 0, out

    def test_groups_with_commas_or_underscores_are_one_number_across_more_than_one_group(self):
        for sentence, line in (("It caps at 1,000,000 rows.", "const CAP = 1_000_000;"), ("It caps at 1_000_000 rows.", "const CAP = 1_000_000;"),
                               ("It caps at 1000000 rows.", "const CAP = 1,000,000;"), ("It caps at 2,000,000,000 rows.", "const CAP = 2_000_000_000;"),
                               ("It caps at 900,000 rows.", "const CAP = 900_000;"),
                               ("It caps at 1_000_000 rows.", "const CAP = 1000000;"), ("It caps at 2_000_000_000 rows.", "const CAP = 2000000000;")):
            ok, out = self.passes(sentence, line)
            self.assertTrue(ok, "%s | %s | %s" % (sentence, line, out))

    def test_a_number_followed_by_thousand_or_million_matches_its_digits(self):
        for sentence, line in (("It caps at 2 million rows.", "const CAP = 2_000_000;"), ("It caps at 1.5 million rows.", "const CAP = 1_500_000;"),
                               ("It caps at 1.1 million rows.", "const CAP = 1_100_000;"), ("It caps at 5 thousand rows.", "const CAP = 5000;"), ("It caps at 900 thousand rows.", "const CAP = 900_000;")):
            ok, out = self.passes(sentence, line)
            self.assertTrue(ok, "%s | %s | %s" % (sentence, line, out))

    def test_a_wrong_number_still_fails_and_a_bare_900_is_not_900_thousand(self):
        for sentence, line in (("It caps at 3 million rows.", "const CAP = 2_000_000;"), ("It caps at 900 rows.", "const CAP = 900_000;"),
                               ("It caps at 1,000,000 rows.", "const CAP = 1_000_001;"), ("It caps at 2_000_000 rows.", "const CAP = 1_000_000;"),
                               ("It caps at 2_000_000_000 rows.", "const CAP = 1_000_000_000;")):
            ok, out = self.passes(sentence, line)
            self.assertFalse(ok, "%s | %s" % (sentence, line))
            self.assertIn("FAIL number", out)

    def test_a_k_or_m_suffix_is_not_a_number_the_check_reads(self):
        self.assertTrue(self.passes("It reads 4k bytes at a time.", "const BLOCK = 4096;")[0])


PLACE_GUIDE = """# Part 1: In plain English

## What it is

It syncs notes. [A3.aaaa]

# Part 2: Appendix: technical detail

## A3 Whole product

The tool syncs notes. `src/app.py:1` [A3.aaaa]

## A4 Networking

A refused connection is retried. `src/net/retry.py:1` [A4.bbbb]

## A5 Screens

The list view shows notes. `ui/view/list.py:1` [A5.cccc]
"""


class PlacementTest(unittest.TestCase):
    """F6: a MISSING fact whose file no line cites goes to the section whose cited files share the longest path prefix with it, not to A3."""

    def section_of(self, cite):
        files = {"src/app.py": "x\n", "src/net/retry.py": "x\n", "ui/view/list.py": "x\n", "src/net/tcp.py": "x\n" * 9, "ui/view/detail.py": "x\n" * 9,
                 "ui/menu.py": "x\n" * 9, "tools/make.py": "x\n" * 9}
        with make_repo(files) as repo:
            rec = coverage.build([("F1", False, "failure", "A fact.", cite)], {"F1": ("MISSING", [])}, PLACE_GUIDE, repo, grow=1500)
        return rec["rows"][0]["section"]

    def test_the_section_with_the_longest_shared_path_prefix_wins(self):
        self.assertEqual(self.section_of("src/net/tcp.py:3"), "A4")  # src/net/ beats src/
        self.assertEqual(self.section_of("ui/view/detail.py:3"), "A5")

    def test_a_shorter_shared_prefix_still_beats_the_fallback(self):
        self.assertEqual(self.section_of("ui/menu.py:3"), "A5")

    def test_a_fact_that_shares_no_folder_with_any_cited_file_goes_to_a3(self):
        self.assertEqual(self.section_of("tools/make.py:3"), "A3")

    def test_a_fact_whose_own_file_is_cited_keeps_the_section_that_cites_it_most(self):
        self.assertEqual(self.section_of("src/net/retry.py:1"), "A4")


class MergeFactsTest(cov.Work):
    """F1: three listers each write a facts file; `coverage.py --facts a b c <repo> --out facts.txt` merges them."""

    def facts_file(self, name, rows):
        """rows: [(core, kind, fact, cite)] written as F1.. in a file of the work folder."""
        self.write(name, "".join("F%d | %s | %s | %s | %s\n" % (i, "core" if c else "detail", k, f, ct) for i, (c, k, f, ct) in enumerate(rows, 1)))

    def merge(self, *names, out="merged.txt"):
        args = [self.path(n) for n in names]
        r = subprocess.run([sys.executable, "-I", str(cov.SCRIPTS / "coverage.py"), "--facts", *args, self.repo, *(("--out", self.path(out)) if out else ())], capture_output=True, text=True)
        merged = Path(self.path(out)).read_text() if out and Path(self.path(out)).exists() else None
        return r, merged

    def rows_of(self, merged):
        return [l.split(" | ") for l in merged.split("\n") if l and not l.startswith("#")]

    def test_the_same_cite_and_the_same_named_thing_is_one_fact_and_the_first_wording_stays(self):
        self.facts_file("a.txt", [(False, "setting", "The `--interval` flag defaults to 30 seconds.", "src/app.py:10")])
        self.facts_file("b.txt", [(True, "setting", "`--interval` is 30 seconds unless set.", "src/app.py:10")])
        r, merged = self.merge("a.txt", "b.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self.rows_of(merged)
        self.assertEqual(rows, [["F1", "core", "setting", "The `--interval` flag defaults to 30 seconds.", "src/app.py:10"]])  # the copy that was core makes it core
        self.assertIn("1 facts, 1 core", r.stdout)
        self.assertIn("1 duplicates dropped", r.stdout)

    def test_two_different_named_things_on_one_range_are_two_facts(self):
        self.facts_file("a.txt", [(False, "setting", "The `--interval` flag defaults to 30 seconds.", "src/app.py:10-20")])
        self.facts_file("b.txt", [(False, "setting", "The `--retries` flag defaults to 3.", "src/app.py:10-20")])
        self.assertEqual(len(self.rows_of(self.merge("a.txt", "b.txt")[1])), 2)

    def test_a_fact_that_names_nothing_is_a_duplicate_when_cite_and_words_match_after_case_and_punctuation(self):
        self.facts_file("a.txt", [(False, "limit", "A note over 1 MB is skipped.", "src/app.py:22-24"), (False, "limit", "A note over 2 MB is refused.", "src/app.py:22-24")])
        self.facts_file("b.txt", [(False, "limit", "a note over 1 MB is skipped", "src/app.py:22-24")])
        self.assertEqual([r[3] for r in self.rows_of(self.merge("a.txt", "b.txt")[1])], ["A note over 1 MB is skipped.", "A note over 2 MB is refused."])

    def test_the_merge_numbers_the_facts_again_and_the_file_passes_the_facts_check(self):
        self.facts_file("a.txt", [(False, "run", "Start it with the sync command.", "src/app.py:30")])
        self.facts_file("b.txt", [(False, "flow", "A refused connection is retried 3 times.", "src/net.py:7")])
        _, merged = self.merge("a.txt", "b.txt")
        self.assertEqual([r[0] for r in self.rows_of(merged)], ["F1", "F2"])
        r = subprocess.run([sys.executable, "-I", str(cov.SCRIPTS / "coverage.py"), "--facts", self.path("merged.txt"), self.repo], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "2 facts, 0 core"))

    def test_the_100_row_cap_is_kept_after_the_merge_and_each_lister_keeps_a_share(self):
        for n, name in enumerate("abc"):
            self.facts_file("%s.txt" % name, [(False, "setting", "Setting `s%d_%d` is on." % (n, i), "src/app.py:%d" % (i % 40 + 1)) for i in range(40)])
        r, merged = self.merge("a.txt", "b.txt", "c.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = self.rows_of(merged)
        self.assertEqual(len(rows), 100)
        share = [sum(1 for x in rows if x[3].startswith("Setting `s%d_" % n)) for n in range(3)]
        self.assertEqual(sorted(share), [33, 33, 34], share)
        self.assertIn("20 cut by the cap of 100", r.stdout)

    def test_at_most_20_facts_stay_core_and_the_first_ones_do(self):
        for n, name in enumerate("abc"):
            self.facts_file("%s.txt" % name, [(True, "setting", "Setting `c%d_%d` is on." % (n, i), "src/app.py:%d" % (i + 1)) for i in range(10)])
        r, merged = self.merge("a.txt", "b.txt", "c.txt")
        rows = self.rows_of(merged)
        self.assertEqual(sum(1 for x in rows if x[1] == "core"), 20)
        self.assertEqual([x[1] for x in rows[:20]], ["core"] * 20)
        self.assertEqual([x[1] for x in rows[20:]], ["detail"] * 10)

    def test_a_file_that_is_not_facts_is_refused_by_name_and_several_files_need_out(self):
        self.facts_file("a.txt", [(False, "run", "Start it.", "src/app.py:30")])
        self.write("b.txt", "F1 | big | run | x | src/app.py:2\n")
        r, _ = self.merge("a.txt", "b.txt")
        self.assertEqual(r.returncode, 1)
        self.assertIn("b.txt:1: not a fact row", r.stderr)
        self.assertEqual(self.merge("a.txt", "a.txt", out=None)[0].returncode, 2)

    def test_one_file_and_no_out_is_the_old_check_that_writes_nothing(self):
        r, _ = self.merge("facts.txt", out=None)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "5 facts, 3 core"))


INVENTORY = """# inventory: 6 rows
limit | MAX_SYNC_BATCH = 25 | src/app.py:5
message | The server is busy, try later | src/net.py:12
route | /sync | src/net.py:5
header | Authorization | src/app.py:3
default | SYNC_HOME = /var/lib/sync | src/app.py:23
default | SYNC_PORT = 8080 | src/app.py:35
"""


class InventoryCandidateTest(cov.Work):
    """F1: an inventory row that no guide line cites and no fact names goes to the to-do as a MISSING candidate, after the lister's facts and only while the to-do has room."""

    def setUp(self):
        super().setUp()
        self.write("inventory.txt", INVENTORY)
        self.write("facts.txt", cov.FACTS + "F6 | detail | interface | The sync route accepts a note. | src/net.py:15\n")
        self.write("grades.md", cov.GRADES + "F6 | MISSING | -\n")

    def run_cli(self, *args, label="first"):
        return subprocess.run([sys.executable, "-I", str(cov.SCRIPTS / "coverage.py"), self.path("facts.txt"), self.path("grades.md"), self.path("GUIDE.md"), self.repo,
                               "--label", label, "--work", self.work, "--grow", "1500", *args], capture_output=True, text=True)

    def rec(self, *extra):
        r = self.run_cli(*extra, "--inventory", self.path("inventory.txt"), label="inv")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(Path(self.path("coverage-inv.json")).read_text()), Path(self.path("coverage-inv.todo.md")).read_text(), r.stdout

    def test_a_row_nothing_covers_is_a_missing_candidate_and_the_others_are_not(self):
        rec, todo, out = self.rec()
        cands = [r for r in rec["rows"] if r.get("candidate")]
        self.assertEqual([(c["id"], c["cite"]) for c in cands], [("I1", "src/app.py:5"), ("I2", "src/net.py:12"), ("I3", "src/app.py:35")])
        for c in cands:
            self.assertEqual((c["state"], c["core"], c["listed"]), ("MISSING", False, True))
        self.assertIn("- I1 MISSING detail | ", todo)
        self.assertIn("MAX_SYNC_BATCH = 25", todo)
        self.assertIn("inventory: 3 candidates, 3 listed", out)

    def test_a_row_a_guide_line_cites_a_fact_range_holds_or_a_fact_names_is_no_candidate(self):
        rec, _, _ = self.rec()
        left = {r["cite"] for r in rec["rows"] if r.get("candidate")}
        self.assertNotIn("src/app.py:3", left)   # the A3 line cites it
        self.assertNotIn("src/app.py:23", left)  # F3 cites src/app.py:22-24
        self.assertNotIn("src/net.py:5", left)   # F6 names the sync route

    def test_candidates_are_not_facts_and_move_no_count(self):
        rec, _, _ = self.rec()
        plain = self.run_cli(label="plain")
        self.assertEqual(plain.returncode, 0, plain.stderr)
        base_rec = json.loads(Path(self.path("coverage-plain.json")).read_text())
        for key in ("facts", "covered", "partial", "missing", "covered_percent", "core", "did_not_fit"):
            self.assertEqual(rec[key], base_rec[key], key)
        self.assertEqual(rec["todo"][:len(base_rec["todo"])], base_rec["todo"])  # the lister's facts keep their order, the candidates follow

    def test_a_full_to_do_takes_no_candidate(self):
        rec, todo, out = self.rec("--words-per-fact", "750")  # room for 2 rows at 750 words: the lister's own MISSING facts fill it
        self.assertEqual(rec["fit"], 2)
        self.assertEqual([r for r in rec["todo"] if r.startswith("I")], [])
        self.assertIn("inventory: 3 candidates, 0 listed", out)
        self.assertNotIn("I1", todo)

    def test_the_candidates_of_one_kind_do_not_crowd_out_the_others(self):
        self.write("inventory.txt", "".join("limit | MAX_%d = %d | src/app.py:%d\n" % (i, i, 30 + i) for i in range(1, 6)) + "message | The server is busy, try later | src/net.py:12\n")
        rec, _, _ = self.rec("--words-per-fact", "300")  # room for 5 rows: the lister's 4 facts and one candidate, and it is the message, not the first limit
        self.assertEqual([r["cite"] for r in rec["rows"] if r.get("candidate") and r["listed"]], ["src/net.py:12"])

    def test_a_candidate_is_placed_next_to_the_line_that_cites_its_file(self):
        rec, todo, _ = self.rec()
        cand = {r["cite"]: r for r in rec["rows"] if r.get("candidate")}
        self.assertEqual(cand["src/net.py:12"]["section"], "A4")
        self.assertEqual(cand["src/net.py:12"]["near"][0], "A4.cccc")
        self.assertIn("add next to A4.cccc", todo)

    def test_a_malformed_inventory_is_refused_and_no_inventory_means_no_candidates(self):
        self.write("inventory.txt", "limit | MAX | not a cite\n")
        r = self.run_cli("--inventory", self.path("inventory.txt"), label="bad")
        self.assertEqual(r.returncode, 1)
        self.assertIn("inventory.txt:1: not an inventory row", r.stderr)
        r = self.run_cli(label="none")
        self.assertNotIn("inventory:", r.stdout)


class ListerDocsTest(unittest.TestCase):
    """F1: E1 runs three listers, one for each lens, on the inventory; the lister brief is blind to any key or score and names no repo."""

    def test_e1_runs_inventory_then_three_listers_then_the_merge(self):
        e1 = EXTEND.split("## E1")[1].split("## E2")[0]
        for text in ("inventory.py <repo>", "Three fresh listers run in parallel", "facts-1.txt", "facts-3.txt", "coverage.py --facts facts-1.txt facts-2.txt facts-3.txt <repo> --out facts.txt",
                     "setup, config and operation", "user-visible behaviour, messages and errors", "integrations, limits and edge cases", "never the guide, a key or a score"):
            self.assertIn(text, e1)
        self.assertIn("--inventory inventory.txt", EXTEND.split("## E2")[1].split("## E3")[0])

    def test_the_lister_brief_gives_the_three_lenses_the_inventory_and_a_share_of_the_cap(self):
        for text in ("1. **Setup, config and operation:**", "2. **User-visible behaviour, messages and errors:**", "3. **Integrations, limits and edge cases:**", "inventory.txt",
                     "You have not seen a key, a score", "aim for 35 to 50", "at most 100 rows", "At most 7 rows are `core`"):
            self.assertIn(text, LISTER)
        self.assertTrue(LISTER.startswith("Seat: lead (skill writer), Opus 5.5 medium"))

    def test_every_flag_of_a_script_command_in_extend_md_is_in_that_script(self):
        for cmd in __import__("re").findall(r"`(python3 -I <skill>/scripts/([\w.]+)[^`]*)`", EXTEND):
            source = (SCRIPTS / cmd[1]).read_text()
            for flag in __import__("re").findall(r"(?<![\w-])(--[a-z][a-z-]*)", cmd[0]):
                self.assertIn(flag, source, "%s in %s" % (flag, cmd[1]))


class RecheckRoutingTest(unittest.TestCase):
    """F2: in an extend pass every failure on any line goes to repair first, for two tries, then to the cut."""
    G = base.GUIDE
    SAVES, STOPS, LISTS = [base.line_of(base.GUIDE, n) for n in ("It saves a note.", "It stops after 5", "It lists notes. `")]

    def n(self, line):
        return "%d.1" % line

    def report(self, rows, findings=()):
        return "Slice: slice-1\n" + "".join("read | %s | %s | src/cli.py:3\n" % r for r in rows) + "".join(f + "\n" for f in findings)

    def run_step(self, mode, report, ids, *extra, guide=None, was=None):
        with base.Work() as w:
            w.write("GUIDE.md", guide or self.G)
            w.write("OLD.md", was or self.G)
            w.write("ids.txt", "\n".join(ids) + "\n")
            w.write("rep/slice-1.md", report)
            extra = [w.p("OLD.md") if x == "@OLD" else x for x in extra]
            code, out, err = base.script(mode, w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), "--out", w.p("fix.txt"), *extra) if mode == "repair" else \
                base.script(mode, w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), *extra)
            fix = (w.dir / "fix.txt").read_text().split() if (w.dir / "fix.txt").exists() else None
            return code, out, err, fix, (w.dir / "GUIDE.md").read_text()

    def six_causes(self):
        causes = ("MISSING_CONDITION", "NAME", "COUNT", "KIND", "OTHER")
        a = [base.line_of(self.G, x) for x in ("It saves a note.", "It stops after 5", "It lists notes. `", "It sorts notes by date. `", "Notes saves notes. `")]
        ids = [self.n(i) for i in a]
        finds = ["%s | OVERSTATED | %s | words | the code | fix" % (i, c) for i, c in zip(ids, causes)]
        return ids, self.report([(i, "OVERSTATED") for i in ids], finds)

    def test_every_cause_and_a_failure_with_no_finding_is_to_fix_on_try_1_and_try_2(self):
        ids, rep = self.six_causes()
        extra = self.n(base.line_of(self.G, "You can keep 5 notes a day."))
        ids.append(extra)
        rep += "read | %s | WRONG | src/cli.py:3\n" % extra  # a failing claim with no finding row at all
        for tries in ("1", "2"):
            code, out, err, fix, _ = self.run_step("repair", rep, ids, "--try", tries)
            self.assertEqual(code, 0, err)
            self.assertEqual(sorted(fix), sorted(ids), tries)
            self.assertIn("6 to fix once, 0 to cut, 0 hold", out)

    def test_try_3_is_the_cut_and_every_failure_is_listed_as_cut(self):
        ids, rep = self.six_causes()
        code, out, err, fix, _ = self.run_step("repair", rep, ids, "--try", "3")
        self.assertEqual((code, fix), (0, []), err)
        self.assertEqual(out.count("cut | "), 5)
        self.assertNotIn("fix | ", out)

    def test_without_try_the_old_routing_stands(self):
        ids, rep = self.six_causes()
        self.assertEqual(self.run_step("repair", rep, ids)[3], ids[:3])

    def test_a_failure_on_a_line_the_pass_changed_is_routed_though_the_ids_file_lacks_it(self):
        new = self.G.replace("It lists notes. `src/cli.py:3`", "It lists all notes. `src/cli.py:3`")
        lists, saves = self.n(base.line_of(new, "It lists all notes.")), self.n(base.line_of(new, "It saves a note."))
        rep = self.report([(lists, "OVERSTATED"), (saves, "HOLDS")], ["%s | OVERSTATED | KIND | lists | the code | fix" % lists])
        with base.Work() as w:
            w.write("GUIDE.md", new)
            w.write("OLD.md", self.G)
            w.write("ids.txt", saves + "\n")
            w.write("rep/slice-1.md", rep)
            args = (w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), "--was", w.p("OLD.md"))
            code, out, err = base.script("repair", *args, "--try", "1", "--out", w.p("fix.txt"))
            self.assertEqual(code, 0, err)
            self.assertEqual((w.dir / "fix.txt").read_text().split(), [lists])
            code, out, err = base.script("cut", *args)
            self.assertEqual(code, 0, err)
            after = (w.dir / "GUIDE.md").read_text()
            self.assertNotIn("It lists all notes.", after)
            self.assertIn("It saves a note.", after)

    def test_a_failure_on_a_line_as_the_old_guide_has_it_is_routed_to_repair_then_to_the_cut(self):
        lists, saves = self.n(self.LISTS), self.n(self.SAVES)
        rep = self.report([(lists, "WRONG"), (saves, "HOLDS")], ["%s | WRONG | KIND | lists | the code | cut" % lists])
        with base.Work() as w:
            w.write("GUIDE.md", self.G)
            w.write("OLD.md", self.G)
            w.write("ids.txt", saves + "\n")
            w.write("rep/slice-1.md", rep)
            args = (w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), "--was", w.p("OLD.md"))
            code, out, err = base.script("repair", *args, "--try", "1", "--out", w.p("fix.txt"))
            self.assertEqual((code, (w.dir / "fix.txt").read_text().split()), (0, [lists]), err)
            self.assertIn("1 failing claims the ids file did not name are routed too (1 as OLD.md has them)", out)
            code, out, err = base.script("repair", *args, "--try", "3", "--out", w.p("fix.txt"))
            self.assertEqual((code, (w.dir / "fix.txt").read_text()), (0, ""), err)
            self.assertIn("cut | %s | WRONG" % lists, out)
            code, out, err = base.script("cut", *args)
            self.assertEqual(code, 0, err)
            self.assertNotIn("It lists notes.", (w.dir / "GUIDE.md").read_text())
            self.assertIn("It saves a note.", (w.dir / "GUIDE.md").read_text())

    def test_a_line_next_to_a_changed_claim_that_fails_is_routed_too(self):
        new = self.G.replace("It saves a note.", "It saves a note fast.")
        saves, stops = self.n(base.line_of(new, "It saves a note fast.")), self.n(base.line_of(new, "It stops after 5"))
        rep = self.report([(saves, "HOLDS"), (stops, "OVERSTATED")], ["%s | OVERSTATED | MISSING_CONDITION | stops | the code | fix" % stops])
        code, out, err, fix, _ = self.run_step("repair", rep, [saves], "--was", "@OLD", "--try", "1", guide=new)
        self.assertEqual((code, fix), (0, [stops]), err)

    def test_a_pending_claim_the_repair_never_edited_is_listed_again_until_a_checker_passes_it(self):
        lists = self.n(self.LISTS)
        with base.Work() as w:
            w.write("GUIDE.md", self.G)
            w.write("OLD.md", self.G)
            w.write("ids.txt", lists + "\n")
            w.write("fix.txt", lists + "\n")
            w.write("rep/slice-1.md", self.report([(lists, "WRONG")]))
            args = (w.p("GUIDE.md"), w.dir, "--ids", w.p("ids.txt"), "--reports", w.p("rep"), "--was", w.p("OLD.md"))
            code, out, err = base.script("cut", *args, "--except", w.p("fix.txt"), "--held-out", w.p("held.txt"))
            self.assertEqual(code, 0, err)
            self.assertEqual((w.dir / "GUIDE.md").read_text(), self.G)
            code, out, err = base.script("changed", w.p("GUIDE.md"), w.dir, "--was", w.p("OLD.md"), "--skip", w.p("held.txt"), "--out", w.p("changed2.txt"))
            self.assertEqual((w.dir / "changed2.txt").read_text().split(), [lists], out)
            w.write("rep/slice-1.md", self.report([(lists, "HOLDS")]))
            code, out, err = base.script("cut", *args, "--held-out", w.p("held2.txt"))
            code, out, err = base.script("changed", w.p("GUIDE.md"), w.dir, "--was", w.p("OLD.md"), "--skip", w.p("held.txt"), "--skip", w.p("held2.txt"), "--out", w.p("changed3.txt"))
            self.assertEqual((w.dir / "changed3.txt").read_text().split(), [])

    def test_skip_takes_the_held_files_of_every_round(self):
        with base.Work() as w:
            old = self.G
            new = old.replace("It saves a note.", "It saves a note fast.").replace("It lists notes. `", "It lists notes well. `")
            w.write("GUIDE.md", new)
            w.write("OLD.md", old)
            saves, lists = self.n(base.line_of(new, "It saves a note fast.")), self.n(base.line_of(new, "It lists notes well."))
            w.write("ids.txt", saves + "\n" + lists + "\n")
            held = []
            for i, cid in enumerate((saves, lists)):
                w.write("rep/slice-1.md", self.report([(cid, "HOLDS")]))
                w.write("only%d.txt" % i, cid + "\n")
                code, _, err = base.script("cut", w.p("GUIDE.md"), w.dir, "--ids", w.p("only%d.txt" % i), "--reports", w.p("rep"), "--held-out", w.p("held%d.txt" % i))
                self.assertEqual(code, 0, err)
                held += ["--skip", w.p("held%d.txt" % i)]
            code, out, err = base.script("changed", w.p("GUIDE.md"), w.dir, "--was", w.p("OLD.md"), *held, "--out", w.p("changed.txt"))
            self.assertEqual(code, 0, err)
            self.assertEqual((w.dir / "changed.txt").read_text().split(), [])

    def test_held_out_appends_each_round_to_one_file_that_skip_takes_once(self):
        with base.Work() as w:
            old = self.G
            new = old.replace("It saves a note.", "It saves a note fast.").replace("It lists notes. `", "It lists notes well. `")
            w.write("GUIDE.md", new)
            w.write("OLD.md", old)
            saves, lists = self.n(base.line_of(new, "It saves a note fast.")), self.n(base.line_of(new, "It lists notes well."))
            for cid in (saves, lists):
                w.write("rep/slice-1.md", self.report([(cid, "HOLDS")]))
                w.write("only.txt", cid + "\n")
                code, _, err = base.script("cut", w.p("GUIDE.md"), w.dir, "--ids", w.p("only.txt"), "--reports", w.p("rep"), "--held-out", w.p("held.txt"))
                self.assertEqual(code, 0, err)
            self.assertEqual(len((w.dir / "held.txt").read_text().splitlines()), 2)
            code, _, err = base.script("cut", w.p("GUIDE.md"), w.dir, "--ids", w.p("only.txt"), "--reports", w.p("rep"), "--held-out", w.p("held.txt"))
            self.assertEqual(len((w.dir / "held.txt").read_text().splitlines()), 2)  # the same claim passed again is not written twice
            code, out, err = base.script("changed", w.p("GUIDE.md"), w.dir, "--was", w.p("OLD.md"), "--skip", w.p("held.txt"), "--out", w.p("changed.txt"))
            self.assertEqual((code, (w.dir / "changed.txt").read_text().split()), (0, []), err)

    def test_e7_gives_held_txt_to_every_round_and_skip_once(self):
        step = EXTEND.split("## E7")[1].split("## E8")[0]
        self.assertNotIn("held2.txt", step)
        self.assertEqual(step.count("--skip"), step.count("--skip held.txt"))
        self.assertEqual(step.count("--held-out held.txt"), 2)

    def test_try_and_was_need_their_values(self):
        for bad in (("--try", "0"), ("--try", "two"), ("--was", "/no/such/file.md")):
            ids, rep = self.six_causes()
            self.assertEqual(self.run_step("repair", rep, ids, *bad)[0], 2, bad)

    def test_e7_names_the_flags_the_script_takes_and_the_two_tries(self):
        step = EXTEND.split("## E7")[1].split("## E8")[0]
        source = (SCRIPTS / "final_recheck.py").read_text()
        for flag in ("--try 1", "--try 2", "--was GUIDE.was.md"):
            self.assertIn(flag, step)
        for flag in {f for cmd in __import__("re").findall(r"`(python3 -I [^`]*final_recheck\.py[^`]*)`", step) for f in __import__("re").findall(r"(?<![\w-])(--?[a-z][a-z-]*)", cmd.split("final_recheck.py", 1)[1])}:
            self.assertIn(flag, source, flag)
        self.assertNotRegex(step, r"(?i)cause MISSING_CONDITION, NAME or COUNT is `fix`")


class DuplicateLineTest(unittest.TestCase):
    """F3: two appendix lines that make the same claim are one claim twice."""

    def test_two_lines_with_the_same_words_after_case_and_spacing_fail_and_name_the_first(self):
        doc = APPENDIX % "It saves a note. `src/a.rs:1`\nIt  SAVES a note.  `src/a.rs:2`\n"
        code, out = check(doc, REPO)
        self.assertEqual(code, 1, out)
        self.assertIn("DOC.md:6: FAIL duplicate: the same claim as line 5", out)

    def test_the_same_words_under_another_section_still_fail(self):
        doc = (APPENDIX % "It saves a note. `src/a.rs:1`\n") + "\n## A5 Listing\n\nIt saves a note. `src/a.rs:3`\n"
        self.assertIn("FAIL duplicate", check(doc, REPO)[1])

    def test_different_claims_and_a_part_1_sentence_that_restates_a_line_pass(self):
        doc = "# Part 1: In plain English\n\n## What it is\n\nIt saves a note. [A4.0001]\n\n" + (APPENDIX % "It saves a note. `src/a.rs:1` [A4.0001]\nIt lists notes. `src/a.rs:2`\n")
        code, out = check(doc, REPO)
        self.assertEqual(code, 0, out)
        self.assertNotIn("duplicate", out)


class StampGuideSentenceTest(unittest.TestCase):
    """F8: stamp.py --guide stamps the lines that have no id and reports a line of two sentences, so an earlier pass's line does not stop the whole guide."""
    GUIDE = "# Notes\n\n## What it is\n\nIt saves notes.\n\n## A4 Behaviours\n\nIt saves a note. `src/a.rs:1` [A4.1111]\n%s"

    def stamp(self, tail):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "GUIDE.md"
            p.write_text(self.GUIDE % tail)
            r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "stamp.py"), "--guide", str(p)], capture_output=True, text=True)
            return r.returncode, r.stdout, p.read_text()

    def test_a_two_sentence_line_with_an_id_from_an_earlier_pass_is_reported_and_the_new_line_is_stamped(self):
        code, out, after = self.stamp("It lists notes. It sorts them. `src/a.rs:2` [A4.2222]\nIt deletes a note. `src/a.rs:3`\n")
        self.assertEqual(code, 0, out)
        self.assertIn("GUIDE.md:10: 2 sentences on one line, left as it is (it has an id from an earlier pass)", out)
        self.assertRegex(after, r"It deletes a note\. `src/a\.rs:3` \[A4\.[0-9a-f]{4}\]\n")
        self.assertIn("It lists notes. It sorts them. `src/a.rs:2` [A4.2222]\n", after)

    def test_a_new_two_sentence_line_is_reported_with_exit_1_and_the_other_new_line_is_still_stamped(self):
        code, out, after = self.stamp("It lists notes. It sorts them. `src/a.rs:2`\nIt deletes a note. `src/a.rs:3`\n")
        self.assertEqual(code, 1, out)
        self.assertIn("GUIDE.md:10: 2 sentences on one line, left as it is:", out)
        self.assertNotIn("earlier pass", out)
        self.assertIn("It lists notes. It sorts them. `src/a.rs:2`\n", after)
        self.assertRegex(after, r"It deletes a note\. `src/a\.rs:3` \[A4\.[0-9a-f]{4}\]\n")

    def test_a_section_file_without_the_flag_is_still_refused_whole(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "A4.md"
            p.write_text("## A4 Behaviours\n\nIt lists notes. It sorts them. `src/a.rs:2`\nIt deletes a note. `src/a.rs:3`\n")
            r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "stamp.py"), str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertNotIn("[A4.", p.read_text())


class ReaderFixRoundDocTest(unittest.TestCase):
    """F11: reader-check.md lets the one fix round add the appendix lines an answer needs before the front writer cites them, and the grader takes any way to start the docs give."""
    READER = (SKILL_DIR / "references/reader-check.md").read_text(encoding="utf-8")

    def test_the_fix_round_has_a_section_writer_add_the_appendix_lines_before_the_front_writer_cites_them(self):
        fix = self.READER.split("## One fix round")[1].split("## Limit")[0]
        self.assertRegex(fix, r"section writer.*first adds the appendix lines")
        self.assertRegex(fix, r"front writer then cites them")
        self.assertLess(fix.index("section writer"), fix.index("front-writer session"))
        self.assertIn("There is no second fix round", fix)
        self.assertIn("appendix lines and the sentences the fix changed are checked in the final re-check", fix)

    def test_the_grader_accepts_any_way_to_start_the_docs_give(self):
        grader = self.READER.split("## Grader")[1].split("## Pass bar")[0]
        self.assertRegex(grader, r"Q3 it accepts any way to start that the docs give")
        self.assertIn("need not be the one the docs list first", grader)


class CitationJoinTest(unittest.TestCase):
    """F12: the claim text a checker reads has no stray commas where commas, `;` or "and" joined the citations."""
    DOC = ("# Part 2\n\n## A4 Stuff\n\nIt saves one `src/a.rs:1`, `src/a.rs:2` [A4.2222]\nIt saves two. `src/a.rs:1`, `src/a.rs:2`, `src/a.rs:3` [A4.2223]\n"
           "It saves three. `src/a.rs:1` and `src/a.rs:2`; `src/a.rs:3` [A4.2224]\nIt saves four. `src/a.rs:1` [A4.2225]\n")

    def claim_rows(self):
        with make_repo(REPO) as repo, tempfile.TemporaryDirectory() as d:
            doc = Path(d) / "DOC.md"
            doc.write_text(self.DOC)
            r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "slice.py"), str(doc), repo, "--out", str(Path(d) / "out")], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return (Path(d) / "out/slice-1.claims.txt").read_text().splitlines()

    def test_citations_joined_by_commas_semicolons_or_and_leave_no_stray_mark_in_the_claim_text(self):
        rows = self.claim_rows()
        self.assertEqual([r.split(" | ", 2)[2] for r in rows], ["It saves one [A4.2222]", "It saves two. [A4.2223]", "It saves three. [A4.2224]", "It saves four. [A4.2225]"])
        for r in rows:
            self.assertNotRegex(r, r"[,;]\s*[,;]|\s,|\band\s*\[")

    def test_the_claim_ids_and_the_appendix_lines_do_not_change(self):
        with make_repo(REPO) as repo:
            sys.path.insert(0, str(SCRIPTS))
            import claims
            self.assertEqual([c[0] for c in claims.claim_ids(self.DOC, repo)], ["5.1", "6.1", "7.1", "8.1"])


if __name__ == "__main__":
    unittest.main()
