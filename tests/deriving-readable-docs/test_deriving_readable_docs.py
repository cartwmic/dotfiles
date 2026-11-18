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


def check(doc, files):
    with make_repo(files) as repo, tempfile.TemporaryDirectory() as d:
        docp = Path(d) / "DOC.md"
        docp.write_text(doc)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), str(docp), repo], capture_output=True, text=True)
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
    return [l for l in report.splitlines() if (": %s " % kind) in l]


class ClaimTest(unittest.TestCase):
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

    def test_design_65_a_count_of_things_is_listed(self):
        doc = "How an ask travels is split across four parts that meet in one file. `a.ts:1`\n"
        out = check(doc, {"a.ts": "x\n"})[1]
        self.assertIn("flag count: four parts | ", out)
        self.assertIn("flag count: 6 words", check("- It warns at 6 words. `a.ts:1`\n", {"a.ts": "6\n"})[1])
        self.assertNotIn("flag count", check("- It waits 45 minutes, exit 409 and 2 seconds. `a.ts:1`\n", {"a.ts": "45 409 2\n"})[1])

    def test_spec_860_an_uncited_overreach_sentence_after_the_header_is_listed(self):
        doc = HEADER + "- The Limits section is refreshed. `a.ts:1`\n- It sits in src/status-limits.ts (only push-test names cover it).\n"
        code, out = check(doc, {"a.ts": "x\n"})
        self.assertEqual(code, 0)
        self.assertIn("flag uncited: only", out)
        self.assertNotIn("flag overreach", check("# Doc\n\nEvery citation is shown. `a.ts:1`\n\n## Part\n\n- It runs. `a.ts:1`\n", {"a.ts": "x\n"})[1])

    def test_claims_are_not_judged_when_a_citation_under_them_is_bad(self):
        code, out = check("- It sends 99. `a.ts:1`, `a.ts:9`\n", {"a.ts": "x\n"})
        self.assertEqual(code, 1)
        self.assertIn("1 bad", out)
        self.assertNotIn("FAIL", out)


if __name__ == "__main__":
    unittest.main()
