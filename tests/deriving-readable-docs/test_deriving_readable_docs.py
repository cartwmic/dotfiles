"""harvest_points.py and check_citations.py, run as the skill runs them: as scripts, on throwaway repos.
Run: python3 -I tests/deriving-readable-docs/test_deriving_readable_docs.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"

FILES = {
    "tests/test_calc.py": "import pytest\n\nclass TestMath:\n    def test_add(self):\n        pass\n\ndef test_top():\n    pass\n",
    "tests/test_uni.py": "import unittest\n\nclass T(unittest.TestCase):\n    def test_one(self):\n        pass\n",
    "src/lib.rs": "#[test]\nfn plain() {}\n\n#[tokio::test]\nasync fn with_runtime() {}\n\n#[test]\n#[ignore]\nfn ignored() {}\n",
    "pkg/a_test.go": "package a\n\nfunc TestThing(t *testing.T) {}\nfunc helper() {}\n",
    "web/a.test.ts": "import { describe, it } from 'vitest';\ndescribe('cart', () => {\n  it('adds an item', () => {});\n  it.skip(`removes it`, () => {});\n  describe('checkout', () => {\n    test('pays', () => {});\n  });\n});\nit.each([1])('each %s', () => {});\n",
    "spec/a_spec.rb": "RSpec.describe Cart do\n  it 'holds items' do\n  end\nend\n",
    "test/a_test.exs": 'defmodule ATest do\n  describe "pay" do\n    test "charges once", %{} do\n    end\n  end\nend\n',
    "t/x.bats": '@test "it runs" {\n  true\n}\n',
    "features/pay.feature": "Feature: Payment\n  Scenario: Card accepted\n    Given a card\n",
    "scripts/ship-journey.sh": "#!/bin/sh\n# Ships a build end to end.\ntrue\n",
    "node_modules/x/a.test.js": "it('vendored', () => {});\n",
    "target/debug/t.rs": "#[test]\nfn built() {}\n",
    "src/many.rs": "#[test_case(1)]\n#[test_case(2)]\nfn param(x: i32) {}\n",
    "src/test/java/CartTest.java": "class CartTest {\n  @Test\n  void adds() {}\n  @ParameterizedTest\n  @ValueSource(ints = 1)\n  public void many(int x) {}\n  @Test void inline() {}\n  @TestInstance void nope() {}\n}\n",
    "Pay.Tests/PayTests.cs": "public class PayTests {\n  [Fact]\n  public void Charges() {}\n  [Theory]\n  [InlineData(1)]\n  public async Task Refunds(int x) {}\n  [Test]\n  public void NUnitStyle() {}\n}\n",
    "cpp/cart_test.cc": "TEST(Cart, AddsItem) {}\nTEST_F(Fix, Works) {}\nTEST_CASE(\"catch case\") {}\n",
    "Tests/CartTests.swift": "import XCTest\nclass CartTests: XCTestCase {\n    func testAdd() {}\n    func helper() {}\n}\n",
    "README.md": "# not code\n",
}


def make_repo(files):
    tmp = tempfile.TemporaryDirectory()
    for rel, text in files.items():
        p = Path(tmp.name) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return tmp


def harvest(repo):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "harvest_points.py"), repo], capture_output=True, text=True)
    return r.returncode, r.stdout


class HarvestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = make_repo(FILES)
        code, out = harvest(cls.tmp.name)
        assert code == 0, out
        cls.out = out
        cls.points = json.loads(out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def names(self, file):
        return [p["name"] for p in self.points if p["file"] == file]

    def test_is_a_json_array_with_stable_ids_in_file_then_line_order(self):
        self.assertIsInstance(self.points, list)
        self.assertEqual([p["id"] for p in self.points], ["P%d" % n for n in range(1, len(self.points) + 1)])
        keys = [(p["file"], p["line"]) for p in self.points]
        self.assertEqual(keys, sorted(keys))

    def test_same_input_same_output(self):
        self.assertEqual(harvest(self.tmp.name)[1], self.out)

    def test_each_point_has_the_documented_fields(self):
        for p in self.points:
            self.assertEqual(set(p), {"id", "name", "kind", "file", "line", "framework", "context"})
            self.assertGreaterEqual(p["line"], 1)

    def test_python(self):
        self.assertEqual(self.names("tests/test_calc.py"), ["test_add", "test_top"])
        pts = {p["name"]: p for p in self.points if p["file"] == "tests/test_calc.py"}
        self.assertEqual(pts["test_add"]["context"], "TestMath")
        self.assertEqual(pts["test_add"]["framework"], "pytest")
        self.assertEqual(pts["test_add"]["line"], 4)
        uni = [p for p in self.points if p["file"] == "tests/test_uni.py"][0]
        self.assertEqual(uni["framework"], "unittest")

    def test_rust_attribute_variants_report_the_fn_line(self):
        pts = [(p["name"], p["line"]) for p in self.points if p["file"] == "src/lib.rs"]
        self.assertEqual(pts, [("plain", 2), ("with_runtime", 5), ("ignored", 9)])

    def test_stacked_rust_test_case_lines_list_the_fn_once(self):
        self.assertEqual([(p["name"], p["line"]) for p in self.points if p["file"] == "src/many.rs"], [("param", 3)])

    def test_junit(self):
        pts = [(p["name"], p["line"], p["context"], p["framework"]) for p in self.points if p["file"].endswith("CartTest.java")]
        self.assertEqual(pts, [("adds", 3, "CartTest", "junit"), ("many", 6, "CartTest", "junit"), ("inline", 7, "CartTest", "junit")])

    def test_csharp_xunit_and_nunit(self):
        pts = [(p["name"], p["line"], p["framework"]) for p in self.points if p["file"].endswith("PayTests.cs")]
        self.assertEqual(pts, [("Charges", 3, "xunit"), ("Refunds", 6, "xunit"), ("NUnitStyle", 8, "nunit")])

    def test_googletest_and_catch2(self):
        pts = [(p["name"], p["line"], p["framework"]) for p in self.points if p["file"] == "cpp/cart_test.cc"]
        self.assertEqual(pts, [("Cart.AddsItem", 1, "googletest"), ("Fix.Works", 2, "googletest"), ("catch case", 3, "catch2")])

    def test_swift_xctest(self):
        pts = [(p["name"], p["line"], p["context"]) for p in self.points if p["file"].endswith("CartTests.swift")]
        self.assertEqual(pts, [("testAdd", 3, "CartTests")])

    def test_go(self):
        self.assertEqual(self.names("pkg/a_test.go"), ["TestThing"])

    def test_js_modifiers_template_names_nesting_and_each(self):
        pts = [p for p in self.points if p["file"] == "web/a.test.ts"]
        self.assertEqual([p["name"] for p in pts], ["adds an item", "removes it", "pays", "each %s"])
        self.assertEqual(pts[0]["context"], "cart")
        self.assertEqual(pts[2]["context"], "cart > checkout")
        self.assertEqual(pts[0]["framework"], "vitest")
        self.assertEqual(pts[3]["context"], "")

    def test_ruby_elixir_bats_gherkin(self):
        self.assertEqual(self.names("spec/a_spec.rb"), ["holds items"])
        self.assertEqual(self.names("test/a_test.exs"), ["charges once"])
        self.assertEqual(self.names("t/x.bats"), ["it runs"])
        g = [p for p in self.points if p["file"] == "features/pay.feature"][0]
        self.assertEqual((g["name"], g["kind"], g["context"]), ("Card accepted", "scenario", "Payment"))

    def test_journey_named_file_without_points_is_one_point_named_by_its_comment(self):
        p = [p for p in self.points if p["file"] == "scripts/ship-journey.sh"]
        self.assertEqual(len(p), 1)
        self.assertEqual((p[0]["kind"], p[0]["context"]), ("journey-file", "Ships a build end to end."))

    def test_vendored_and_build_dirs_and_non_code_are_skipped(self):
        files = {p["file"] for p in self.points}
        self.assertFalse([f for f in files if f.startswith(("node_modules/", "target/")) or f.endswith(".md")])

    def test_bare_repo_gives_an_empty_array(self):
        with make_repo({"README.md": "hi\n"}) as d:
            self.assertEqual(harvest(d), (0, "[]\n"))

    def test_bad_usage_exits_2(self):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "harvest_points.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


def check(doc, files, *extra):
    with make_repo(files) as repo, tempfile.TemporaryDirectory() as d:
        docp = Path(d) / "DOC.md"
        docp.write_text(doc)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), str(docp), repo, *extra], capture_output=True, text=True)
    return r.returncode, r.stdout


def check_counted(doc, files, left_out=None):
    """check() with the harvest of the repo as --points, as the skill runs it (step 2 then step 7)."""
    with make_repo(files) as repo, tempfile.TemporaryDirectory() as d:
        pts = Path(d) / "points.json"
        pts.write_text(harvest(repo)[1])
        extra = ["--points", str(pts)]
        if left_out is not None:
            (Path(d) / "left-out.txt").write_text(left_out)
            extra += ["--left-out", str(Path(d) / "left-out.txt")]
        docp = Path(d) / "DOC.md"
        docp.write_text(doc)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), str(docp), repo, *extra], capture_output=True, text=True)
    return r.returncode, r.stdout


REPO = {"src/a.rs": "one\ntwo\nthree\n", "Makefile": "all:\n\ttrue\n"}


class CitationTest(unittest.TestCase):
    def test_good_citations_pass_and_are_counted(self):
        code, out = check("It does a thing (`src/a.rs:2`) and a span (`src/a.rs:1-3`), see `Makefile:2`.\n", REPO)
        self.assertEqual(code, 0)
        self.assertIn("checked 3 citations, 0 bad", out)

    def test_missing_file_and_out_of_range_line_are_reported(self):
        code, out = check("a `src/missing.rs:1` b `src/a.rs:4` c `src/a.rs:2-9` d `src/a.rs:0`\n", REPO)
        self.assertEqual(code, 1)
        self.assertIn("no such file", out)
        self.assertEqual(out.count("line out of range (file has 3 lines)"), 2)
        self.assertIn("src/a.rs:0: bad line range", out)
        self.assertIn("4 bad", out)

    def test_path_escaping_the_repo_is_reported(self):
        code, out = check("`../../etc/hosts:1`\n", REPO)
        self.assertEqual(code, 1)
        self.assertIn("outside the repo", out)

    def test_urls_ports_and_clock_times_are_not_citations(self):
        doc = "It starts here `src/a.rs:1`, then see `http://localhost:8080/x`, `localhost:8080`, `example.com:443` and `12:30`.\n"
        code, out = check(doc, REPO)
        self.assertEqual(code, 0)
        self.assertIn("checked 1 citations", out)

    def test_citations_in_fenced_code_are_skipped(self):
        code, out = check("```\n`src/nope.rs:1`\n```\nReal: `src/a.rs:1`.\n", REPO)
        self.assertEqual(code, 0)
        self.assertIn("checked 1 citations", out)

    def test_several_citations_in_one_span(self):
        code, out = check("`src/a.rs:1, src/gone.rs:2`\n", REPO)
        self.assertEqual(code, 1)
        self.assertIn("checked 2 citations, 1 bad", out)

    def test_dotless_missing_file_and_space_after_colon_are_not_skipped(self):
        code, out = check("Build with `Makefile:5`, then `src/a.rs: 2`, and `src/gone.rs: 1`.\n", {"src/a.rs": "one\ntwo\n"})
        self.assertEqual(code, 1)
        self.assertIn("checked 3 citations, 2 bad", out)
        self.assertIn("Makefile:5: no such file", out)
        self.assertIn("src/gone.rs:1: no such file", out)

    def test_citation_inside_a_span_with_other_words_is_checked(self):
        code, out = check("`see src/a.rs:9 for it`\n", REPO)
        self.assertEqual(code, 1)
        self.assertIn("src/a.rs:9: line out of range", out)

    def test_every_citation_in_the_doc_is_counted(self):
        doc = "`src/a.rs:1` `Makefile:2` `src/a.rs: 3` `see src/a.rs:2 x` `src/a.rs:1-3`\n"
        code, out = check(doc, REPO)
        self.assertEqual(code, 0)
        self.assertIn("checked 5 citations, 0 bad", out)

    def test_ipv4_and_timestamps_are_not_citations(self):
        code, out = check("It starts here `src/a.rs:1`, at `127.0.0.1:8080` and `2026-11-15T03:04:17`.\n", REPO)
        self.assertEqual(code, 0)
        self.assertIn("checked 1 citations", out)

    def test_a_doc_with_only_caller_list_claims_exits_2_as_the_skill_says(self):
        code, out = check("Customers can pay by card (from your list, item 3). Refunds take a day (from your list, item 4).\n", REPO)
        self.assertEqual(code, 2)
        self.assertIn("checked 0 citations, 0 bad", out)

    def test_a_doc_with_no_citations_fails(self):
        code, out = check("Plain prose, nothing to check.\n", REPO)
        self.assertEqual(code, 2)
        self.assertIn("checked 0 citations", out)

    def test_bad_usage_exits_2(self):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


# Sentences from the coordinator docs written at f455f086 (docs-v2), with shortened copies of the lines they cited.
# CORRECTIONS.md in docs-v3 lists what was wrong in them. Named spec_144, design_65, prd_57 and spec_860 are real
# mistakes that the check must fail or flag as written. The "constructed" tests are modelled on a v2 sentence but do
# not reproduce its wrong fact (the string and comment checks have no real v2 mistake behind them).
LAYOUT_TEST = (
    "describe('layout', () => {\n"
    "  it(`a paragraph of ${LIMITS.paragraphWords} words is fine; one more is named by its first words`, () => {\n"
    "    expect(layoutWarnings(words(LIMITS.paragraphWords))).toEqual([]);\n"
    "  });\n"
    "});\n"
)
LIMITS_TS = "export const LIMITS = {\n  /** Words in one paragraph or list item. */\n  paragraphWords: 60,\n  bulletRun: 5,\n};\n"
BOARD_SYNC = (
    "// `coordinator board sync github`: the runner of the board-to-GitHub-Project sync.\n"
    "// BOARD.md is canonical; the sync writes its values to the project and never pulls. This file only wires: it reads the board,\n"
    "// one GitHub item list and the baseline file, and asks the planner what differs.\n"
    "import { readProjectItems } from './board-sync-github.ts';\n"
)
SPEC_144 = "Layout checks only warn: a paragraph or list item over 60 words, more than 5 list items in a row. "
HEADER = "# Doc\n\nWritten from a commit. Every citation is shown.\n\n## Part\n\n"


def lines_of(report, kind):
    return [l for l in report.splitlines() if (": %s:" % kind) in l]


class ClaimTest(unittest.TestCase):
    def test_a_bad_citation_in_a_heading_still_fails(self):
        code, out = check("## Parsing `src/a.rs:99`\n\n- It counts. `src/a.rs:1`\n", REPO)
        self.assertEqual(code, 1, out)
        self.assertIn("src/a.rs:99: line out of range", out)
        self.assertNotIn(": flag ", check("## Every part\n\n- It counts. `src/a.rs:1`\n", REPO)[1])  # a heading is not a claim

    def test_a_straight_quote_inside_backticks_is_code_not_a_quoted_string(self):
        files = {"src/parse.py": "if c == '\"':\n    start()\nif c == '\"':\n    end()\n"}
        code, out = check("- A string opens on `\"` and closes on the next `\"`. `src/parse.py:1-4`\n", files)
        self.assertEqual(code, 0, out)

    def test_a_parenthetical_that_names_no_source_is_judged_as_uncited_words(self):
        out = check("- It runs. `a.ts:1` (only on Mondays)\n", {"a.ts": "x\n"})[1]
        self.assertIn("flag uncited: only", out)

    def test_citations_joined_by_and_back_one_claim_together(self):
        files = {"src/a.ts": "const a = 1;\n", "src/b.ts": "const LIMIT = 42;\n"}
        code, out = check("- The limit is 42. `src/a.ts:1` and `src/b.ts:1`\n", files)
        self.assertEqual(code, 0, out)

    def test_a_backticked_path_outside_the_repo_is_not_exempt(self):
        with make_repo({"repo/src/a.ts": "const a = 1;\n", "outside.txt": "x\n"}) as root, tempfile.TemporaryDirectory() as d:
            docp = Path(d) / "DOC.md"
            docp.write_text("- It reads `../outside.txt`. `src/a.ts:1`\n")
            r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), str(docp), str(Path(root) / "repo")],
                               capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("FAIL string: '../outside.txt'", r.stdout)

    def test_spec_144_a_limit_that_lives_in_a_constant_fails_until_the_constant_is_cited(self):
        files = {"src/send-gate.test.ts": LAYOUT_TEST, "src/send-gate.ts": LIMITS_TS}
        code, out = check("- " + SPEC_144 + "`src/send-gate.test.ts:1-5`\n", files)
        self.assertEqual(code, 1)
        self.assertIn("FAIL number: 60 is not in the cited lines", out)
        self.assertIn("FAIL number: 5 is not in the cited lines", out)
        code, out = check("- " + SPEC_144 + "`src/send-gate.test.ts:1-5`, `src/send-gate.ts:1-5`\n", files)
        self.assertEqual(code, 0, out)

    def test_a_number_may_sit_a_window_of_five_lines_from_the_range_and_no_further(self):
        body = lambda gap: "\n".join(["x"] * gap) + "\nconst limit = 77;\n"
        near, far = {"a.ts": "const a = 1;\n" + body(4)}, {"a.ts": "const a = 1;\n" + body(5)}
        doc = "- The limit is 77. `a.ts:1`\n"
        self.assertEqual(check(doc, near)[0], 0)
        code, out = check(doc, far)
        self.assertEqual(code, 1)
        self.assertIn("FAIL number: 77", out)

    def test_a_wrong_number_is_caught_and_a_right_one_in_another_form_is_not(self):
        files = {"a.ts": "const settleMs = options.settleMs ?? 15_000;\nconst cap = 2000;\n", "journeys/111-ac11-x.journey.ts": "// header\n"}
        for sentence in ("It settles after 15 seconds by default.", "It stops at 2,000.", "It sends about 6,600 characters.",
                         "Journey 111 holds it."):
            cite = "`journeys/111-ac11-x.journey.ts:1`" if "111" in sentence else "`a.ts:1-2`"
            self.assertEqual(check("- %s %s\n" % (sentence, cite), files)[0], 0, sentence)
        code, out = check("- It settles after 30 seconds by default. `a.ts:1-2`\n", files)
        self.assertEqual(code, 1)
        self.assertIn("FAIL number: 30", out)

    def test_a_list_numeral_and_a_citation_number_are_not_claims(self):
        self.assertEqual(check("4. It runs. `a.ts:1`\n", {"a.ts": "run();\n"})[0], 0)

    def test_constructed_a_named_file_the_cited_lines_never_mention_fails(self):
        files = {"board-cli.ts": "// runs the board command as a child process\n// no module is imported\n", "a.rs": "x\n"}
        doc = "The board is a git repository holding `BOARD.md` and a config file. `board-cli.ts:1`\n"
        code, out = check(doc, files)
        self.assertEqual(code, 1)
        self.assertIn("FAIL string: 'BOARD.md'", out)
        files["board-cli.ts"] += "// BOARD.md is canonical\n"
        self.assertEqual(check(doc.replace("1`", "1-3`"), files)[0], 0)

    def test_quoted_strings_and_commands_are_matched_as_words_and_an_existing_path_is_exempt(self):
        files = {"a.ts": "export const OFF = 'reach';\nrun(['send']);\n", "src/real.ts": "x\n"}
        doc = "In T3 mode `reach send` is refused, per \"send\", and `src/real.ts` is untouched. `a.ts:1-2`\n"
        self.assertEqual(check(doc, files)[0], 0)
        code, out = check("It prints \"Queued as event\" and `reach drop`. `a.ts:1-2`\n", files)
        self.assertEqual(code, 1)
        self.assertIn("FAIL string: 'Queued as event'", out)
        self.assertIn("FAIL string: 'reach drop'", out)

    def test_constructed_a_sentence_resting_on_comment_lines_is_flagged_unless_it_says_so(self):
        files = {"src/board-sync.ts": BOARD_SYNC}
        doc = "- The board sync writes to the project and nothing else. `src/board-sync.ts:1-3`%s\n"
        code, out = check(doc % "", files)
        self.assertEqual(code, 0)
        self.assertIn("flag comment: src/board-sync.ts:1-3", out)
        self.assertEqual(lines_of(check(doc % " (code comment)", files)[1], "flag comment"), [])
        self.assertEqual(lines_of(check(doc.replace("writes", "writes, the header says,") % "", files)[1], "flag comment"), [])
        both = doc.replace("`src/board-sync.ts:1-3`", "`src/board-sync.ts:1-3`, `src/board-sync.ts:4`")
        self.assertEqual(lines_of(check(both % "", files)[1], "flag comment"), [])  # a code line backs it too

    def test_prd_57_overreach_words_are_listed_but_do_not_fail(self):
        files = {"src/board-sync.ts": BOARD_SYNC}
        code, out = check("- The board sync writes to the GitHub Project and never reads back. `src/board-sync.ts:4`\n", files)
        self.assertEqual(code, 0)
        self.assertIn("flag overreach: never | ", out)
        self.assertIn("0 failed checks, 1 flagged sentences", out)

    def test_each_overreach_word_is_listed_and_a_plain_sentence_is_not(self):
        for word in ("every", "all", "always", "never", "only", "none", "any", "No answer is sent", "everything", "anyone"):
            doc = "- It %s runs. `a.ts:1`\n" % word if " " not in word else "- %s. `a.ts:1`\n" % word
            self.assertIn("flag overreach", check(doc, {"a.ts": "x\n"})[1], word)
        for plain in ("It runs on a timer.", "It no longer reads the file.", "It is a card, not a list."):
            self.assertNotIn("flag overreach", check("- %s `a.ts:1`\n" % plain, {"a.ts": "x\n"})[1], plain)

    def test_next_is_listed_because_a_journey_that_skips_wakes_proves_a_later_one(self):
        out = check("- With 5.2 GB free the next wake carries the reading. `a.ts:1`\n", {"a.ts": "5.2\n"})[1]
        self.assertIn("flag overreach: next | ", out)
        self.assertNotIn("flag overreach", check("- A later wake carries the reading. `a.ts:1`\n", {"a.ts": "x\n"})[1])

    def test_design_65_a_count_of_things_is_listed(self):
        doc = "How an ask travels is split across four parts that meet in one file. `a.ts:1`\n"
        out = check(doc, {"a.ts": "x\n"})[1]
        self.assertIn("flag count: four parts | ", out)
        self.assertIn("flag count: 6 words", check("- It warns at 6 words. `a.ts:1`\n", {"a.ts": "6\n"})[1])
        self.assertNotIn("flag count", check("- It waits 45 minutes, exit 409 and 2 seconds. `a.ts:1`\n", {"a.ts": "45 409 2\n"})[1])

    def test_spec_860_an_uncited_overreach_sentence_after_the_header_fails_unless_it_says_where_it_comes_from(self):
        doc = HEADER + "- The Limits section is refreshed. `a.ts:1`\n- It sits in src/status-limits.ts (only push-test names cover it).\n"
        code, out = check(doc, {"a.ts": "x\n"})
        self.assertEqual(code, 1)
        self.assertIn("FAIL uncited: only", out)
        self.assertEqual(check(doc.replace("(only push", "(README: only push"), {"a.ts": "x\n"})[0], 0)
        self.assertEqual(check(doc.replace("It sits", "Inferred: it sits"), {"a.ts": "x\n"})[0], 0)
        self.assertEqual(check(doc.replace("(only push-test names cover it)", "and no test covers it"), {"a.ts": "x\n"})[0], 1)  # "no <noun>" counts here
        self.assertNotIn("flag overreach", check("# Doc\n\nEvery citation is shown. `a.ts:1`\n\n## Part\n\n- It runs. `a.ts:1`\n", {"a.ts": "x\n"})[1])

    def test_claims_are_not_judged_when_a_citation_under_them_is_bad(self):
        code, out = check("- It sends 99. `a.ts:1`, `a.ts:9`\n", {"a.ts": "x\n"})
        self.assertEqual(code, 1)
        self.assertIn("1 bad", out)
        self.assertNotIn("FAIL", out)


# Round-1 sentences from the coordinator and agent-kit docs of 2026-11-18 (explore-codemap climb), where fresh checkers
# found 13% of claims wrong, overstated or unsupported. Each test below names the doc line it comes from and keeps a
# shortened copy of the lines that line cited.
PEERS_TEST = (
    "describe('http peers', () => {\n"
    "  it('refuses a source that is not a peer', async () => {\n"
    "    expect(await post({ source: 'agent.zed' })).toEqual(403);\n"
    "  });\n"
    "});\n"
)
BROKEN_TEST = (
    "it.each([\n"
    "  ['state'], ['scope'], ['delete'], ['project verb'], ['project ref'],\n"
    "])('refuses a broken %s', (subject) => {\n"
    "  expect(run(subject).exit).toBe(2);\n"
    "});\n"
)
PEERS_FILES = {"src/inbox/http.peers.test.ts": PEERS_TEST, "src/inbox/http.ts": "export const peers = new Set();\n"}


class OverreachFailTest(unittest.TestCase):
    def test_agent_kit_prd_53_only_on_a_sentence_that_cites_tests_alone_fails(self):
        doc = "- Another agent can post only if its name is on the inbox's peer list. `src/inbox/http.peers.test.ts:2-4`\n"
        code, out = check(doc, PEERS_FILES)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL overreach: only | Another agent can post only", out)
        self.assertIn("1 failed checks", out)

    def test_coordinator_prd_33_a_heading_sentence_with_only_fails_the_same_way(self):
        code, out = check("**Only Michael counts.** A message from a second account is dropped. `src/inbox/http.peers.test.ts:2-4`\n", PEERS_FILES)
        self.assertEqual((code, "FAIL overreach: only" in out), (1, True))

    def test_the_fix_names_the_case_cites_the_code_or_labels_it(self):
        base = "- Another agent can post only if its name is on the inbox's peer list. `src/inbox/http.peers.test.ts:2-4`"
        for fixed in (
            base.replace("Another agent can post only", "In the test, a source that is not a peer is refused; a post is accepted only"),
            base.replace("only if", "for example only if"),
            base.replace("Another", "Inferred: another"),
            base + ", `src/inbox/http.ts:1`",  # the code that defines the set is cited too
            base + " (README)",
        ):
            self.assertEqual(check(fixed + "\n", PEERS_FILES)[0], 0, fixed)

    def test_agent_kit_design_115_a_count_in_words_of_a_test_set_fails_but_a_digit_value_does_not(self):
        files = {"src/board/c08.conformance.test.ts": BROKEN_TEST, "src/board/cli.ts": "export {};\n"}
        code, out = check("- It refuses four broken subjects. `src/board/c08.conformance.test.ts:1-5`\n", files)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL overreach: four broken subjects", out)
        self.assertEqual(check("- It exits 2 on each case. `src/board/c08.conformance.test.ts:4`\n", files)[0], 1)  # each is a quantifier
        code, out = check("- It exits 2 for a broken subject. `src/board/c08.conformance.test.ts:4`\n", files)
        self.assertEqual(code, 0, out)

    def test_words_outside_the_list_and_non_test_citations_only_list_the_sentence(self):
        for word in ("next", "none", "any", "No answer is sent"):
            doc = "- With none of it set, the next wake is sent. `src/inbox/http.peers.test.ts:2-4`\n" if word == "next" else "- It sends %s. `src/inbox/http.peers.test.ts:2-4`\n" % word
            code, out = check(doc, PEERS_FILES)
            self.assertEqual(code, 0, doc + out)
            self.assertIn("flag overreach", out)
        self.assertEqual(check("- Every peer is listed. `src/inbox/http.ts:1`\n", PEERS_FILES)[0], 0)  # source code can define the set

    def test_a_test_path_is_found_by_name_or_by_the_harvest(self):
        files = {"checks/odd_name.py": "def test_one():\n    assert 1\n", "src/x.py": "x = 1\n"}
        doc = "- It always passes. `checks/odd_name.py:2`\n"
        self.assertEqual(check(doc, files)[0], 0)  # not a test by its name
        self.assertEqual(check_counted("# D\n\n- Counts: harvested 1; left out 0; used 1; read by name only 0; not cited 0.\n\n## P\n\n" + doc, files)[0], 1)  # the harvest knows it is one


def counted_doc(counts, body):
    return "# Doc\n\n- Repo: r.\n- Counts: %s.\n\n## Part\n\n%s" % (counts, body)


COUNT_FILES = {
    "src/a.test.ts": "it('one', () => {\n  expect(1).toBe(1);\n});\nit('two', () => {\n  expect(2).toBe(2);\n});\nit('three', () => {\n  expect(3).toBe(3);\n});\n",
    "src/b.test.ts": "it('four', () => {\n  expect(4).toBe(4);\n});\n",
    "evals/c.test.ts": "it('five', () => {\n  expect(5).toBe(5);\n});\n",
}


class HeaderCountsTest(unittest.TestCase):
    def counts(self, line, body="- It checks 2. `src/a.test.ts:1-6`\n- Four is checked. `src/b.test.ts:2`\n", left_out="evals/\n"):
        return check_counted(counted_doc(line, body), COUNT_FILES, left_out)

    def test_right_numbers_pass(self):
        code, out = self.counts("harvested 5; left out 1; used 3; read by name only 0; not cited 1")
        self.assertEqual(code, 0, out)

    def test_agent_kit_spec_5_used_590_a_range_that_spans_two_points_counts_both(self):
        code, out = self.counts("harvested 5; left out 1; used 2; read by name only 0; not cited 2")
        self.assertEqual(code, 1, out)
        self.assertIn("header says used 2; the harvest and this doc's citations give 3", out)
        self.assertIn("header says not cited 2; the harvest and this doc's citations give 1", out)

    def test_left_out_by_id_by_file_and_by_folder(self):
        for left_out in ("P1\n", "evals/c.test.ts\n", "evals/\n"):
            self.assertEqual(self.counts("harvested 5; left out 1; used 3; read by name only 0; not cited 1", left_out=left_out)[0], 0, left_out)
        code, out = self.counts("harvested 5; left out 0; used 3; read by name only 0; not cited 2", left_out="")
        self.assertEqual(code, 0, out)

    def test_a_point_cited_only_in_a_sentence_that_says_inferred_is_read_by_name_only(self):
        body = "- It checks 2. `src/a.test.ts:1-6`\n- Inferred: four is checked. `src/b.test.ts:2`\n"
        self.assertEqual(self.counts("harvested 5; left out 1; used 2; read by name only 1; not cited 1", body)[0], 0)
        self.assertEqual(self.counts("harvested 5; left out 1; used 3; read by name only 0; not cited 1", body)[0], 1)

    def test_a_header_without_one_of_the_five_counts_fails_and_names_the_value(self):
        code, out = self.counts("harvested 5; left out 1; used 3; not cited 1")
        self.assertEqual(code, 1)
        self.assertIn("header has no `read by name only N` (the harvest and this doc's citations give 0)", out)

    def test_thousands_separators_and_words_between_key_and_number_are_read(self):
        files = {"src/a.test.ts": "".join("it('t%d', () => {\n  expect(1).toBe(1);\n});\n" % i for i in range(1200))}
        doc = counted_doc("Points harvested: 1,200. Left out: 0. Points used in this document, body read and cited as proven: 1. "
                          "Points read by name only: 0. Points not cited, with no claim made: 1,199", "- It checks one. `src/a.test.ts:1-3`\n")
        code, out = check_counted(doc, files)
        self.assertEqual(code, 0, out)

    def test_counts_are_not_checked_without_points(self):
        self.assertEqual(check(counted_doc("harvested 99", "- It checks 2. `src/a.test.ts:1-6`\n"), COUNT_FILES)[0], 0)

    def test_left_out_without_points_is_a_usage_error(self):
        self.assertEqual(check("- It runs. `a.ts:1`\n", {"a.ts": "x\n"}, "--left-out", "x.txt")[0], 2)


NOT_BACKED = (
    "# Doc\n\n- Counts: harvested 2; left out 0; used 1; read by name only 0; not cited 1.\n\n## Part\n\n- It runs. `src/a.test.ts:1-3`\n\n"
    "## Not backed by any validation point\n\n%s\n"
)
NOT_BACKED_FILES = {
    "src/a.test.ts": "it('runs', () => {\n  expect(1).toBe(1);\n});\n",
    "scripts/publish.test.mjs": "it('publishes', () => {\n  // builds images/hub/Dockerfile and pushes it\n  expect(push).toBeCalled();\n});\n",
    "images/hub/Dockerfile": "FROM node\n",
}


class NotBackedTest(unittest.TestCase):
    def test_coordinator_prd_60_a_searched_name_that_a_test_file_holds_fails(self):
        entry = '- The hub image is built from `images/hub/Dockerfile`. I searched the test files for "Dockerfile" and found no match.'
        code, out = check_counted(NOT_BACKED % entry, NOT_BACKED_FILES)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL not-backed: `Dockerfile` is in a test file, scripts/publish.test.mjs:2; cite it or drop the entry", out)

    def test_citing_the_line_that_holds_it_passes(self):
        entry = '- The hub image is built from `images/hub/Dockerfile`. A comment in a publish test names "Dockerfile" without asserting it. `scripts/publish.test.mjs:2`'
        doc = (NOT_BACKED % entry).replace("used 1; read by name only 0; not cited 1", "used 2; read by name only 0; not cited 0")
        code, out = check_counted(doc, NOT_BACKED_FILES)
        self.assertEqual(code, 0, out)

    def test_a_name_no_test_holds_a_bare_word_and_text_outside_the_section_are_not_checked(self):
        for entry in ('- The hub image starts from `FROM node`. `images/hub/Dockerfile:1`', '- The hub image is `FROM`. `images/hub/Dockerfile:1`', '- The hub builds. I searched for "Dockerfile".'):
            doc = NOT_BACKED % entry
            if "Dockerfile" in entry:
                doc = doc.replace("## Not backed by any validation point", "## Other notes")
            self.assertEqual(check_counted(doc, NOT_BACKED_FILES)[0], 0, entry)

    def test_a_file_the_writer_left_out_is_not_a_test_file(self):
        entry = '- The hub image is built from `images/hub/Dockerfile`. I searched the test files for "Dockerfile" and found no match.'
        self.assertEqual(check_counted(NOT_BACKED % entry, NOT_BACKED_FILES, left_out="scripts/\n")[0], 1)  # the count in the header is now wrong, nothing else
        code, out = check_counted((NOT_BACKED % entry).replace("harvested 2; left out 0; used 1; read by name only 0; not cited 1", "harvested 2; left out 1; used 1; read by name only 0; not cited 0"), NOT_BACKED_FILES, left_out="scripts/\n")
        self.assertEqual(code, 0, out)


class SheetTest(unittest.TestCase):
    def test_sheet_prints_each_claim_with_its_cited_lines_and_skips_the_checks(self):
        code, out = check("- It is wrong about 99. `src/a.rs:1-2`\n", REPO, "--sheet")
        self.assertEqual(code, 0)  # the number 99 would fail the check; the sheet does not check
        self.assertIn("== doc line 1: It is wrong about 99.", out)
        self.assertIn("-- src/a.rs:1-2", out)
        self.assertIn("     1  one", out)
        self.assertIn("     2  two", out)
        self.assertNotIn("three", out)


if __name__ == "__main__":
    unittest.main()
