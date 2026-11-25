"""assemble.py and slice.py, run as the skill runs them (as scripts), on a small repo and work folder; then the assembled guide is fed to the checks.
Run: python3 -I tests/deriving-readable-docs/test_assemble.py"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = tempfile.mkdtemp(prefix="state-")  # the scripts log each run (runlog.py): keep these runs out of the real log
os.environ["XDG_STATE_HOME"] = STATE
atexit.register(shutil.rmtree, STATE, True)

SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"

REPO = {
    "src/cli.py": 'import argparse\np.add_argument("--tag")\np.add_argument("--color")\n\n@click.command()\ndef add():\n    pass\n',
    "tests/test_cli.py": 'def test_tag():\n    run(["--tag", "x"])\n',
    "README.md": "# Notes\n",
    "docs/guide.md": "x\n",
}
SURFACES = [
    {"kind": "flag", "name": "--tag", "file": "src/cli.py", "line": 2},
    {"kind": "flag", "name": "--color", "file": "src/cli.py", "line": 3},
    {"kind": "command", "name": "add", "file": "src/cli.py", "line": 5},
]
POINTS = [{"id": "P1", "name": "test_tag", "kind": "test", "file": "tests/test_cli.py", "line": 1, "framework": "pytest", "context": ""}]
PART1 = "## What it is\n\nNotes saves short notes. [A3.1]\nWho it is for: anyone who takes notes. [A3.1]\nYou tag a note with an option. [A4.1]\n"
A3 = "## A3 The product as a whole\n\nNotes saves short notes `README.md:1`. [A3.1]\n"
A4 = "## A4 Tagging\n\nThe --tag option sets a tag `src/cli.py:2`. [A4.1]\nThe --color option sets a color `src/cli.py:3`. [A4.2]\n"


def setup(d, repo, **over):
    for rel, text in REPO.items():
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    parts = {"part1.md": PART1, "A3.md": A3, "A4.md": A4, "surfaces.json": json.dumps(SURFACES), "points.json": json.dumps(POINTS),
             "scout.resolved": "add | src/cli.py:5\nteleport | NOT FOUND\n", "not-read.txt": "# nobody read these\ndocs/\n"}
    parts.update(over)
    for name, text in parts.items():
        if text is not None:
            Path(d, name).write_text(text)


def run(script, *args):
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / script), *args], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


class AssembleTest(unittest.TestCase):
    def assemble(self, *extra, **over):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            setup(d, repo, **over)
            code, out, err = run("assemble.py", d, repo, "--date", "2026-11-20", *extra)
            guide = Path(d, "GUIDE.md")
            clean = Path(d, "GUIDE.clean.md")
            return code, out, err, guide.read_text() if guide.exists() else None, clean.read_text() if clean.exists() else None

    def test_a_section_has_the_same_word_count_in_the_writers_check_and_in_the_assembled_guide(self):
        """The heading is a word of the section both times: the budget a writer checks against is the budget the guide is held to."""
        import re
        def words(path, repo):
            return int(re.search(r"(\d+) words\n", run("check_citations.py", str(path), repo)[1]).group(1))
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            setup(d, repo)
            self.assertEqual(run("assemble.py", d, repo, "--date", "2026-11-20")[0], 0)
            guide = Path(d, "GUIDE.md").read_text()
            start = guide.index("## A4 Tagging")
            end = guide.index("\n## ", start + 1)
            Path(d, "section.md").write_text(guide[start:end] + "\n")
            self.assertEqual(words(Path(d, "section.md"), repo), words(Path(d, "A4.md"), repo))
            self.assertEqual(words(Path(d, "A4.md"), repo), 14)  # the heading's 2 words are in it

    def test_the_guide_is_header_part_1_then_the_appendix_in_order(self):
        code, out, err, guide, _ = self.assemble()
        self.assertEqual(code, 0, err)
        order = [guide.index(x) for x in ("guide\n", "# Part 1: In plain English", "# Part 2: Appendix", "## A1 Surfaces", "## A2 Evidence",
                                             "## A3 The product", "## A4 Tagging", "## A-last Not read")]
        self.assertEqual(order, sorted(order))

    def test_the_header_prints_the_counts_from_the_files_it_was_given(self):
        code, out, err, guide, _ = self.assemble()
        self.assertIn("Date: 2026-11-20.", guide)
        self.assertIn("Commit: no git.", guide)
        self.assertIn("Counts: 3 surfaces (command 1, flag 2); 1 scout names found, 1 not found and dropped, 0 weak matches (only in scripts or tests) dropped; 1 test cases in 1 files; 1 of 3 named surfaces appear in tests.", guide)

    def test_a2_lists_the_surfaces_no_test_names(self):
        code, out, err, guide, _ = self.assemble()
        a2 = guide[guide.index("## A2 Evidence"):guide.index("## A3")]
        self.assertIn("tests found: 1 cases in 1 files", a2)
        self.assertIn("surfaces named in tests: 1 of 3", a2)
        self.assertIn("never named in tests:\nflag | --color | src/cli.py:3\ncommand | add | src/cli.py:5", a2)  # `add` is under 3 characters of name plus no test text: not named
        self.assertNotIn("flag | --tag", a2)

    def test_a_git_repo_gets_its_commit(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            setup(d, repo)
            for cmd in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"]):
                subprocess.run(["git", "-C", repo, *cmd], check=True, capture_output=True)
            sha = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
            run("assemble.py", d, repo, "--date", "2026-11-20")
            self.assertIn("Commit: %s." % sha, Path(d, "GUIDE.md").read_text())

    def test_printed_rows_sit_between_markers_so_the_check_does_not_count_them(self):
        code, out, err, guide, _ = self.assemble()
        self.assertEqual(guide.count("<!-- printed -->"), guide.count("<!-- /printed -->"))
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            setup(d, repo)
            run("assemble.py", d, repo, "--date", "2026-11-20")
            code, out, err = run("check_citations.py", str(Path(d, "GUIDE.md")), repo)
        self.assertEqual(code, 0, out)  # A1 and A2 rows cite lines and say no; none of it is judged
        self.assertNotIn("A-last", out)

    def test_clean_copy_has_no_tags_and_no_markers(self):
        code, out, err, guide, clean = self.assemble("--clean")
        self.assertIn("[A3.1]", guide)
        self.assertNotIn("[A", clean)
        self.assertNotIn("printed", clean)
        self.assertIn("Notes saves short notes.\nWho it is for: anyone who takes notes.\nYou tag a note", clean)

    def test_the_clean_copy_sits_beside_the_guide_named_after_it_and_is_reported(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            setup(d, repo)
            out_file = str(Path(d, "GUIDE.final.md"))
            code, out, err = run("assemble.py", d, repo, "--date", "2026-11-20", "-o", out_file, "--clean")
            self.assertEqual(code, 0, err)
            self.assertTrue(Path(d, "GUIDE.final.clean.md").exists())
            self.assertFalse(Path(d, "GUIDE.final.md.clean.md").exists())
            self.assertIn("wrote %s" % Path(d, "GUIDE.final.clean.md"), out)

    def test_index_lists_each_appendix_sentence_under_its_tag_and_needs_no_part_1(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            setup(d, repo, **{"part1.md": None})
            code, out, err = run("assemble.py", d, repo, "--index")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["A3.1 | Notes saves short notes.", "A4.1 | The --tag option sets a tag.", "A4.2 | The --color option sets a color."])

    def test_a_prose_line_with_no_id_is_an_error_that_names_the_file_and_stamp_py(self):
        code, out, err, guide, _ = self.assemble(**{"A4.md": A4 + "A third line with no id.\n"})
        self.assertEqual(code, 1)
        self.assertIn("A4.md has 1 lines with no id", err)
        self.assertIn("stamp.py", err)
        self.assertIsNone(guide)

    def test_an_id_on_two_lines_is_an_error(self):
        code, out, err, guide, _ = self.assemble(**{"A4.md": A4.replace("[A4.2]", "[A4.1]")})
        self.assertEqual(code, 1)
        self.assertIn("id A4.1 is on two lines", err)

    def test_stamped_section_files_assemble_and_the_tags_stay_in_the_clean_copy_out(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            setup(d, repo, **{"A4.md": "## A4 Tagging\n\nThe --tag option sets a tag `src/cli.py:2`.\n"})
            code, out, err = run("stamp.py", str(Path(d, "A4.md")))
            self.assertEqual(code, 0, out + err)
            code, out, err = run("assemble.py", d, repo, "--index")
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"A4\.[0-9a-f]{4} \| The --tag option sets a tag\.")

    def test_the_assembled_guide_passes_lint_main_and_the_tags_resolve(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            setup(d, repo, **{"part1.md": "## What it is\n\nNotes saves short notes. [A3.1]\nWho it is for: anyone who takes notes. [A3.1]\n\n## How to start\n\nYou set a tag with an option. [A4.1]\n"})
            run("assemble.py", d, repo, "--date", "2026-11-20")
            code, out, err = run("lint_main.py", str(Path(d, "GUIDE.md")), repo, "--surfaces", str(Path(d, "surfaces.json")))
        self.assertEqual(code, 0, out + err)

    def test_a_missing_or_misnumbered_section_is_an_error(self):
        code, out, err, guide, _ = self.assemble(**{"A4.md": None})
        self.assertEqual(code, 0)  # A3 alone is a valid guide
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            setup(d, repo)
            Path(d, "A6.md").write_text("## A6 Gap\n\nx.\n")
            code, out, err = run("assemble.py", d, repo)
            self.assertEqual(code, 1)
            self.assertIn("no gap", err)
            Path(d, "A6.md").unlink()
            Path(d, "A4.md").write_text("## A5 Wrong number\n\nx.\n")
            code, out, err = run("assemble.py", d, repo)
            self.assertEqual(code, 1)
            self.assertIn("A4.md must start with a `## A4 <title>` heading", err)

    def test_a_not_read_path_that_is_not_in_the_repo_is_an_error(self):
        code, out, err, guide, _ = self.assemble(**{"not-read.txt": "docs/\nvanished/\n"})
        self.assertEqual(code, 1)
        self.assertIn("vanished/ is not in the repo", err)

    def test_without_surfaces_or_part_1_it_says_which_file_is_missing(self):
        self.assertIn("surfaces.json", self.assemble(**{"surfaces.json": None})[2])
        self.assertIn("part1.md", self.assemble(**{"part1.md": None})[2])

    def test_bad_usage_exits_2(self):
        self.assertEqual(run("assemble.py")[0], 2)


SLICE_DOC = "# T\n\nIntro.\n\n" + "".join("## S%d\n\n%s\n\n" % (i, " ".join("It does thing %d `src/cli.py:2`." % (10 * i + k) for k in range(4))) for i in range(1, 6))


class SliceTest(unittest.TestCase):
    def slices(self, doc, *extra):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as repo:
            Path(repo, "src").mkdir()
            Path(repo, "src/cli.py").write_text("x\n" * 5)
            Path(d, "DOC.md").write_text(doc)
            code, out, err = run("slice.py", str(Path(d, "DOC.md")), repo, "--out", str(Path(d, "out")), *extra)
            files = {p.name: p.read_text() for p in Path(d, "out").glob("*")} if Path(d, "out").exists() else {}
        return code, out, err, files

    def test_claims_are_cut_between_lines_into_near_equal_slices_and_the_last_slice_reaches_the_end(self):
        code, out, err, files = self.slices(SLICE_DOC, "--max-claims", "9")
        self.assertEqual(code, 0, err)
        # 20 claims, 4 on each line: ceil(20 / 9) = 3 slices, cut between lines; a slice starts at its first line with a claim and ends before the next one's
        first_of = lambda n: [i for i, l in enumerate(SLICE_DOC.split("\n"), 1) if "thing %d " % n in l][0]
        self.assertEqual(out.splitlines(), ["slice 1: lines 1-%d, 8 claims, 0 flags" % (first_of(30) - 1),
                                            "slice 2: lines %d-%d, 8 claims, 0 flags" % (first_of(30), first_of(50) - 1),
                                            "slice 3: lines %d-%d, 4 claims, 0 flags" % (first_of(50), len(SLICE_DOC.splitlines()))])
        self.assertEqual([s["claims"] for s in json.loads(files["slices.json"])], [8, 8, 4])

    def test_a_section_over_the_limit_is_a_slice_of_its_own_marked_over(self):
        code, out, err, files = self.slices(SLICE_DOC, "--max-claims", "3")
        self.assertIn(", over", out.splitlines()[1])
        self.assertTrue(all(s["over"] for s in json.loads(files["slices.json"])[1:]))

    def test_each_slice_gets_the_flags_whose_line_is_inside_it(self):
        doc = SLICE_DOC.replace("It does thing 11", "It does every thing 11", 1).replace("It does thing 51", "It does all thing 51", 1)
        code, out, err, files = self.slices(doc, "--max-claims", "9")
        self.assertIn("flag overreach: every", files["slice-1.flags.txt"])
        self.assertNotIn("flag overreach: all", files["slice-1.flags.txt"])
        self.assertIn("flag overreach: all", files["slice-3.flags.txt"])
        self.assertEqual(files["slice-2.flags.txt"], "")

    def test_part_1_and_the_appendix_are_never_one_slice(self):
        """The checkers' Part 1 report is scored apart from the appendix, so no slice may hold claims of both."""
        doc = ("# Part 1: In plain English\n\n## What it is\n\nIt reads files. [A4.1]\n\n# Part 2: Appendix\n\n## A4 Reading\n\nIt reads files `src/cli.py:2`.\n")
        code, out, err, files = self.slices(doc)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.splitlines(), ["slice 1: lines 1-%d, 1 claims, 0 flags" % (doc.split("\n").index("# Part 2: Appendix") ),
                                            "slice 2: lines %d-%d, 1 claims, 0 flags" % (doc.split("\n").index("# Part 2: Appendix") + 1, len(doc.splitlines()))])

    def test_a_claim_keeps_no_stray_comma_where_its_citation_was_taken_out(self):
        doc = ("# Part 2: Appendix\n\n## A4 Reading\n\nIt reads `src/cli.py:2`, then stops. [A4.0001]\n"
               "It reads `src/cli.py:2`, `src/cli.py:3` and writes `src/cli.py:4`; it stops. [A4.0002]\n")
        code, out, err, files = self.slices(doc)
        self.assertEqual(code, 0, err)
        self.assertEqual([l.split(" | ", 2)[2] for l in files["slice-1.claims.txt"].splitlines()],
                         ["It reads, then stops. [A4.0001]", "It reads, and writes; it stops. [A4.0002]"])

    def test_bad_usage_exits_2(self):
        self.assertEqual(run("slice.py")[0], 2)
        self.assertEqual(self.slices(SLICE_DOC, "--max-claims", "zero")[0], 2)


if __name__ == "__main__":
    unittest.main()
