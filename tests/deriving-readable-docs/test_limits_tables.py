"""The Defaults and limits and When things fail tables: stamp.py gives a data row an id, assemble.py gathers the `###` blocks of the section files into two sections,
lint_main.py lets Part 1 tag a row, check_citations.py checks a row's value against the cited line, and a table header row is not a claim.
Run: python3 -I tests/deriving-readable-docs/test_limits_tables.py"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"

REPO = {"src/server.py": 'import sys\nTIMEOUT = 30  # seconds\n\ndef start(db):\n    if not db:\n        sys.exit(1)\n', "README.md": "# Server\n"}
LIMITS = "### Defaults and limits\n\n| Setting or behaviour | Value | Unit | Cited |\n|---|---|---|---|\n| request timeout | 30 | seconds | `src/server.py:2` |\n"
FAILS = "### When things fail\n\n| Case | What happens | Cited |\n|---|---|---|\n| no database at start | the process exits with code 1 | `src/server.py:6` |\n"
A3 = "## A3 The product as a whole\n\nServer runs requests `README.md:1`. [A3.0001]\n"
A4 = "## A4 Serving\n\nThe server waits for a request `src/server.py:2`. [A4.0001]\n\n" + LIMITS + "\n" + FAILS
PART1 = ("## What it is\n\nServer runs requests. [A3.0001]\nWho it is for: anyone who runs a server. [A3.0001]\n\n## How to start\n\nYou start the server. [A3.0001]\n\n"
         "## What it needs and keeps\n\nA request times out after 30 seconds. [A4.0001]\n")


def run(script, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def folder(d, repo, **over):
    for rel, text in REPO.items():
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    files = {"A3.md": A3, "A4.md": A4, "part1.md": PART1, "surfaces.json": json.dumps([{"kind": "command", "name": "start", "file": "src/server.py", "line": 4}])}
    files.update(over)
    for name, text in files.items():
        Path(d, name).write_text(text)


def stamped_assemble(d, repo, **over):
    folder(d, repo, **over)
    for p in sorted(Path(d).glob("A*.md")):
        run("stamp.py", str(p))
    return run("assemble.py", d, repo, "--date", "2026-11-21", "-o", str(Path(d, "GUIDE.md")))


class StampRowsTest(unittest.TestCase):
    def stamp(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "A4.md")
            p.write_text(text)
            code, out, err = run("stamp.py", str(p))
            return code, p.read_text()

    def test_a_data_row_gets_an_id_inside_its_last_cell_and_the_header_and_separator_do_not(self):
        code, text = self.stamp("## A4 Serving\n\n" + LIMITS)
        self.assertEqual(code, 0)
        lines = text.splitlines()
        self.assertEqual(lines[2], "### Defaults and limits")
        self.assertEqual(lines[4], "| Setting or behaviour | Value | Unit | Cited |")
        self.assertEqual(lines[5], "|---|---|---|---|")
        self.assertRegex(lines[6], r"^\| request timeout \| 30 \| seconds \| `src/server\.py:2` \[A4\.[0-9a-f]{4}\] \|$")

    def test_a_table_with_no_separator_row_is_not_stamped(self):
        code, text = self.stamp("## A4 Serving\n\n| a | b |\n")
        self.assertIn("| a | b |\n", text)


class AssembleTablesTest(unittest.TestCase):
    def assemble(self, **over):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            code, out, err = stamped_assemble(d, repo, **over)
            guide = Path(d, "GUIDE.md")
            return code, err, guide.read_text() if guide.exists() else None

    def test_the_blocks_become_two_sections_after_the_last_one_and_before_a_last(self):
        code, err, guide = self.assemble()
        self.assertEqual(code, 0, err)
        order = [guide.index(x) for x in ("## A4 Serving", "## A5 Defaults and limits", "## A6 When things fail", "## A-last Not read")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("### Defaults and limits", guide)
        self.assertNotIn("### When things fail", guide)
        self.assertRegex(guide, r"## A5 Defaults and limits\n\n\| Setting or behaviour \| Value \| Unit \| Cited \|\n\|---\|---\|---\|---\|\n\| request timeout \| 30 \| seconds \|")
        self.assertRegex(guide, r"## A6 When things fail\n\n\| Case \| What happens \| Cited \|\n\|---\|---\|---\|\n\| no database at start \| the process exits with code 1 \|")

    def test_rows_of_two_files_are_in_one_table_in_file_order(self):
        more = "## A5 Storing\n\nThe store keeps rows `src/server.py:2`. [A5.0001]\n\n### Defaults and limits\n\n| Setting or behaviour | Value | Unit | Cited |\n|---|---|---|---|\n| store row cap | 30 | rows | `src/server.py:2` |\n"
        code, err, guide = self.assemble(**{"A5.md": more})
        self.assertEqual(code, 0, err)
        table = guide[guide.index("## A6 Defaults and limits"):guide.index("## A7 When things fail")]
        self.assertLess(table.index("request timeout"), table.index("store row cap"))
        self.assertEqual(table.count("| Setting or behaviour |"), 1)

    def test_a_guide_with_no_rows_says_so_in_a_printed_block(self):
        code, err, guide = self.assemble(**{"A4.md": "## A4 Serving\n\nThe server waits for a request `src/server.py:2`. [A4.0001]\n"})
        self.assertEqual(code, 0, err)
        self.assertIn("## A5 Defaults and limits\n\n<!-- printed -->\nnone listed\n<!-- /printed -->", guide)

    def test_a_block_with_another_header_is_refused(self):
        code, err, guide = self.assemble(**{"A4.md": A4.replace("| Value | Unit |", "| Number | Unit |")})
        self.assertEqual(code, 1)
        self.assertIn("A4.md", err)
        self.assertIn("Setting or behaviour | Value | Unit | Cited", err)

    def test_a_block_with_prose_in_it_is_refused(self):
        code, err, guide = self.assemble(**{"A4.md": A4.replace("### When things fail\n\n", "### When things fail\n\nThe failures are below.\n\n")})
        self.assertEqual(code, 1)
        self.assertIn("holds only a table", err)

    def test_a_row_with_no_id_is_refused_and_names_the_file(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            folder(d, repo)
            Path(d, "A3.md").write_text(A3)
            Path(d, "A4.md").write_text(A4)
            run("stamp.py", str(Path(d, "A3.md")))
            run("stamp.py", str(Path(d, "A4.md")))
            Path(d, "A4.md").write_text(Path(d, "A4.md").read_text().replace(" [A4.", " [X.").replace("`src/server.py:6` [X.", "`src/server.py:6` ["))
            code, out, err = run("assemble.py", d, repo)
        self.assertEqual(code, 1)
        self.assertIn("A4.md", err)
        self.assertIn("no id", err)

    def test_the_index_lists_a_row_under_its_id_for_the_front_writer(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            stamped_assemble(d, repo)
            code, out, err = run("assemble.py", d, repo, "--index")
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"A4\.[0-9a-f]{4} \| request timeout; 30; seconds\n")
        self.assertRegex(out, r"A4\.[0-9a-f]{4} \| no database at start; the process exits with code 1\n")


class GuideChecksTest(unittest.TestCase):
    def guide(self, part1=PART1):
        d, repo = tempfile.mkdtemp(), tempfile.mkdtemp()
        stamped_assemble(d, repo, **{"part1.md": part1})
        return d, repo

    def row_id(self, guide, needle):
        line = next(l for l in guide.splitlines() if needle in l)
        return line[line.rindex("[A4.") + 1:line.rindex("]")]

    def test_part_1_can_tag_a_row_and_its_number_is_checked_against_the_row(self):
        d, repo = self.guide()
        guide = Path(d, "GUIDE.md").read_text()
        rid = self.row_id(guide, "request timeout")
        ok = PART1.replace("[A4.0001]", "[%s]" % rid)
        Path(d, "good.md").write_text(guide.replace(PART1.strip(), ok.strip()))
        code, out, err = run("lint_main.py", str(Path(d, "good.md")), repo, "--surfaces", str(Path(d, "surfaces.json")))
        self.assertEqual(code, 0, out)
        Path(d, "bad.md").write_text(guide.replace(PART1.strip(), ok.replace("30 seconds", "45 seconds").strip()))
        code, out, err = run("lint_main.py", str(Path(d, "bad.md")), repo, "--surfaces", str(Path(d, "surfaces.json")))
        self.assertEqual(code, 1, out)
        self.assertIn("number 45 is not in", out)

    def test_check_citations_fails_a_row_whose_value_is_not_on_the_cited_line(self):
        d, repo = self.guide()
        guide = Path(d, "GUIDE.md").read_text()
        code, out, err = run("check_citations.py", str(Path(d, "GUIDE.md")), repo, "--max-sentence-words", "18")
        self.assertEqual(code, 0, out)
        Path(d, "wrong.md").write_text(guide.replace("| request timeout | 30 |", "| request timeout | 60 |"))
        code, out, err = run("check_citations.py", str(Path(d, "wrong.md")), repo, "--max-sentence-words", "18")
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL number: 60 is not in the cited lines", out)

    def test_a_table_header_row_is_outside_for_the_checkers_and_a_data_row_is_a_claim(self):
        d, repo = self.guide()
        code, out, err = run("slice.py", str(Path(d, "GUIDE.md")), repo, "--out", str(Path(d, "slices")))
        self.assertEqual(code, 0, err)
        claims = "".join(p.read_text() for p in sorted(Path(d, "slices").glob("*.claims.txt")))
        header = next(l for l in claims.splitlines() if "Setting or behaviour" in l)
        self.assertIn("| outside |", header)
        row = next(l for l in claims.splitlines() if "request timeout" in l)
        self.assertIn("| claim |", row)

    def test_an_uncited_header_row_does_not_fail_the_writers_audit_pass(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            folder(d, repo)
            run("stamp.py", str(Path(d, "A4.md")))
            code, out, err = run("check_citations.py", str(Path(d, "A4.md")), repo, "--audit", str(Path(d, "no-such-audit.md")))
        self.assertNotIn("Setting or behaviour", out)  # the missing audit file fails, but no `uncited` finding names the header row
        self.assertNotIn("FAIL uncited", out)


if __name__ == "__main__":
    unittest.main()
