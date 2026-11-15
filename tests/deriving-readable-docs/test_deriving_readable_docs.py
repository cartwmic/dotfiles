"""harvest_points.py and check_citations.py, run as the skill runs them: as scripts, on throwaway repos."""
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
        doc = "See `http://localhost:8080/x`, `localhost:8080`, `example.com:443`, at `12:30`, and `src/a.rs:1`.\n"
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
        code, out = check("At `127.0.0.1:8080` and `2026-11-15T03:04:17`, see `src/a.rs:1`.\n", REPO)
        self.assertEqual(code, 0)
        self.assertIn("checked 1 citations", out)

    def test_a_doc_with_no_citations_fails(self):
        code, out = check("Plain prose, nothing to check.\n", REPO)
        self.assertEqual(code, 2)
        self.assertIn("checked 0 citations", out)

    def test_bad_usage_exits_2(self):
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
