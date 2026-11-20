"""Appendix ids, stamp.py, and the Part 1 gates that keep an appendix sentence's conditions and its source label (lint_main.py).
Each test breaks one rule of a passing guide, or runs the two round-1 guides through the gate.
Run: python3 -I tests/deriving-readable-docs/test_ids_and_part1.py"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"
sys.path.insert(0, str(SCRIPTS))
sys.dont_write_bytecode = True
from claims import appendix_index, doc_lines, prose_sentences  # noqa: E402

SURFACES = [{"kind": "command", "name": "notes add", "file": "src/cli.py", "line": 3}, {"kind": "flag", "name": "--tag <name>", "file": "src/cli.py", "line": 5}]

GUIDE = """# Part 1: In plain English

## What it is

Notes lets you save short notes from the terminal. [A3.a1]
Who it is for: anyone who takes notes in a terminal. [A3.a1]

## How to start

Run `notes add` to save your first note. [A4.b1]

## What you can do

You can keep up to 5 notes in one day. [A4.b2]

# Part 2: Appendix

## A3 The product as a whole

Notes saves short notes from the terminal. `src/cli.py:1` [A3.a1]

## A4 Adding notes

### The add command

The `notes add` command saves a note. `src/cli.py:3` [A4.b1]
It stops after 5 notes in one day. `src/cli.py:7` [A4.b2]
"""


def lint(guide, *extra, surfaces=SURFACES, files=None):
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "src").mkdir()
        (Path(d) / "src/cli.py").write_text("x\n" * 10)
        for rel, text in (files or {}).items():
            Path(d, rel).write_text(text)
        Path(d, "GUIDE.md").write_text(guide)
        Path(d, "surfaces.json").write_text(json.dumps(surfaces))
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "lint_main.py"), str(Path(d, "GUIDE.md")), d, "--surfaces", str(Path(d, "surfaces.json")), *extra],
                           capture_output=True, text=True)
    return r.returncode, r.stdout


def with_a4(guide, line, new):
    assert line in guide, line
    return guide.replace(line, new)


class IdsTest(unittest.TestCase):
    def test_an_appendix_sentence_is_found_by_the_id_it_carries_not_by_its_position(self):
        idx = appendix_index(GUIDE, "/nonexistent")
        self.assertEqual(sorted(idx), ["A3.a1", "A4.b1", "A4.b2"])
        self.assertIn("saves a note", idx["A4.b1"][1])
        cut = GUIDE.replace("The `notes add` command saves a note. `src/cli.py:3` [A4.b1]\n", "")
        self.assertIn("5 notes", appendix_index(cut, "/nonexistent")["A4.b2"][1])  # a cut line does not renumber the lines after it

    def test_a_split_line_leaves_the_other_ids_alone(self):
        split = GUIDE.replace("It stops after 5 notes in one day. `src/cli.py:7` [A4.b2]",
                              "It stops after 5 notes. `src/cli.py:7` [A4.b2]\nThe count is per day. `src/cli.py:7`")
        idx = appendix_index(split, "/nonexistent")
        self.assertIn("A4.b1", idx)
        self.assertIn("A4.b2", idx)
        self.assertIn("A3.a1", idx)

    def test_a_subheading_inside_a_section_does_not_end_the_section(self):
        """Defect 1: a `###` heading reset the section, so the sentences under it dropped out of the index."""
        idx = appendix_index(GUIDE, "/nonexistent")
        self.assertIn("A4.b1", idx)  # sits under `### The add command`
        later = GUIDE.replace("It stops after", "### More\n\nIt stops after")
        self.assertIn("A4.b2", appendix_index(later, "/nonexistent"))

    def test_the_first_sentence_after_a_non_section_heading_is_not_indexed_into_the_last_section(self):
        tail = GUIDE + "\n## A-last Not read\n\nNobody read the docs. [A4.zz]\n"
        self.assertNotIn("A4.zz", appendix_index(tail, "/nonexistent"))

    def test_a_cited_line_is_marked_cited_and_an_uncited_one_is_not(self):
        idx = appendix_index(GUIDE.replace("`src/cli.py:3` ", ""), "/nonexistent")
        self.assertFalse(idx["A4.b1"][2])
        self.assertTrue(idx["A4.b2"][2])


class StampTest(unittest.TestCase):
    DRAFT = "## A4 Adding notes\n\nIntro line with no citation, inferred.\n\n- The command saves a note. `src/cli.py:3`\n- It stops after 5 notes. `src/cli.py:7` [A4.keep]\n\n```\ncode `x:1`\n```\n\n| a | b |\n"

    def stamp(self, text):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "A4.md")
            p.write_text(text)
            r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "stamp.py"), str(p)], capture_output=True, text=True)
            return r.returncode, r.stdout + r.stderr, p.read_text()

    def test_each_prose_line_without_an_id_gets_one_in_its_sections_name(self):
        code, out, text = self.stamp(self.DRAFT)
        self.assertEqual(code, 0, out)
        lines = text.splitlines()
        self.assertRegex(lines[2], r"^Intro line with no citation, inferred\. \[A4\.[0-9a-f]{4}\]$")
        self.assertRegex(lines[4], r"^- The command saves a note\. `src/cli.py:3` \[A4\.[0-9a-f]{4}\]$")
        self.assertIn("2 lines stamped", out)

    def test_an_id_already_there_stays_and_a_second_run_changes_nothing(self):
        code, out, text = self.stamp(self.DRAFT)
        self.assertIn("It stops after 5 notes. `src/cli.py:7` [A4.keep]", text)
        code, out, again = self.stamp(text)
        self.assertEqual(again, text)
        self.assertIn("0 lines stamped", out)

    def test_headings_fenced_code_and_table_rows_are_left_alone(self):
        code, out, text = self.stamp(self.DRAFT)
        self.assertIn("## A4 Adding notes\n", text)
        self.assertIn("```\ncode `x:1`\n```", text)
        self.assertIn("| a | b |\n", text)

    def test_the_new_ids_in_one_file_are_all_different(self):
        many = "## A4 x\n\n" + "".join("Line %d is here.\n" % i for i in range(300))
        code, out, text = self.stamp(many)
        ids = re.findall(r"\[(A4\.[0-9a-f]+)\]", text)
        self.assertEqual(len(ids), 300)
        self.assertEqual(len(set(ids)), 300)

    def test_a_file_that_starts_in_no_section_is_refused(self):
        code, out, text = self.stamp("A line before any heading.\n")
        self.assertEqual(code, 1)
        self.assertIn("## A<n>", out)

    def test_an_id_changes_no_claim_word_or_citation_result(self):
        """The id is not a word, not a claim and not a source label."""
        def check(doc):
            with tempfile.TemporaryDirectory() as d:
                Path(d, "src").mkdir()
                Path(d, "src/a.py").write_text("x\n")
                Path(d, "doc.md").write_text(doc)
                r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), str(Path(d, "doc.md")), d, "--max-sentence-words", "18"], capture_output=True, text=True)
            return r.returncode, r.stdout.replace(d, "")
        plain = "## A4 x\n\nIt always runs. `src/a.py:1`\nIt is inferred. \nEvery job ends. (README)\n"
        stamped = "## A4 x\n\nIt always runs. `src/a.py:1` [A4.0001]\nIt is inferred. [A4.0002]\nEvery job ends. (README) [A4.0003]\n"
        a, b = check(plain), check(stamped)
        self.assertEqual(a, b)
        self.assertIn("FAIL", check("## A4 x\n\nEvery job ends. [A4.0003]\n")[1])  # an id is not a source label: this uncited "every" still fails


class ConditionTest(unittest.TestCase):
    def fails(self, guide, kind):
        code, out = lint(guide)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL %s:" % kind, out)
        return out

    def test_a_guide_that_follows_every_rule_passes(self):
        code, out = lint(GUIDE)
        self.assertEqual(code, 0, out)

    def test_an_appendix_condition_the_part_1_sentence_drops_fails(self):
        guide = with_a4(GUIDE, "You can keep up to 5 notes in one day. [A4.b2]", "You can keep 5 notes a day. [A4.b2]")
        guide = guide.replace("It stops after 5 notes in one day.", "It stops after 5 notes in one day unless you use the flag.")
        out = self.fails(guide, "condition")
        self.assertIn("unless", out)
        self.assertIn("A4.b2", out)

    def test_a_part_1_sentence_that_names_a_condition_passes(self):
        guide = GUIDE.replace("It stops after 5 notes in one day.", "It stops after 5 notes in one day unless you use the flag.")
        guide = guide.replace("You can keep up to 5 notes in one day. [A4.b2]", "You can keep 5 notes a day, unless you use the flag. [A4.b2]")
        code, out = lint(guide)
        self.assertEqual(code, 0, out)

    def test_by_default_names_a_condition_only_when_the_appendix_sentence_states_a_default(self):
        """The round 2 writers pasted "by default" to get past this check. It now counts when the tagged line itself says default (test_round3.py has the refusals)."""
        for phrase in ("by default", "in the default setup"):
            guide = GUIDE.replace("It stops after 5 notes in one day.", "It stops after 5 notes in one day when the limit is on, which defaults to 5.")
            guide = guide.replace("You can keep up to 5 notes in one day. [A4.b2]", "You can keep 5 notes a day %s. [A4.b2]" % phrase)
            code, out = lint(guide)
            self.assertEqual(code, 0, "%s: %s" % (phrase, out))

    def test_an_appendix_sentence_with_no_condition_asks_nothing_of_part_1(self):
        guide = GUIDE.replace("You can keep up to 5 notes in one day. [A4.b2]", "You can keep notes. [A4.b2]")
        code, out = lint(guide)
        self.assertEqual(code, 0, out)

    def test_the_words_of_a_condition_are_listed_in_one_place(self):
        src = (SCRIPTS / "lint_main.py").read_text().split('"""', 2)[2]
        self.assertEqual(len(re.findall(r"^CONDITION = ", src, re.M)), 1)
        self.assertEqual([l for l in src.splitlines() if "unless" in l and not l.startswith(("CONDITION", "ABSOLUTE"))], [])


class LabelTest(unittest.TestCase):
    def guide(self, appendix, part1):
        return GUIDE.replace("It stops after 5 notes in one day. `src/cli.py:7` [A4.b2]", appendix + " [A4.b2]").replace(
            "You can keep up to 5 notes in one day. [A4.b2]", part1 + " [A4.b2]")

    def test_a_label_the_appendix_sentence_carries_must_stay_in_part_1(self):
        guide = self.guide("The README says it stops after 5 notes. `README.md:3`", "It stops after 5 notes a day.")
        code, out = lint(guide)
        self.assertEqual(code, 1, out)
        self.assertIn("FAIL label:", out)
        self.assertIn("README", out)

    def test_a_part_1_sentence_that_keeps_the_label_passes(self):
        guide = self.guide("The README says it stops after 5 notes. `README.md:3`", "The README says it stops after 5 notes a day.")
        self.assertEqual(lint(guide)[0], 0)

    def test_a_file_named_in_the_label_counts(self):
        guide = self.guide("CONTRACT.md says it stops after 5 notes. `CONTRACT.md:3`", "It stops after 5 notes a day.")
        code, out = lint(guide, files={"CONTRACT.md": "x\n" * 5})  # a repo file: its name is a source
        self.assertIn("FAIL label:", out)
        guide = self.guide("CONTRACT.md says it stops after 5 notes. `CONTRACT.md:3`", "CONTRACT.md says it stops after 5 notes a day.")
        self.assertEqual(lint(guide, files={"CONTRACT.md": "x\n" * 5})[0], 0)

    def test_a_code_comment_label_in_brackets_after_the_citation_counts(self):
        guide = self.guide("It stops after 5 notes (code comment). `src/cli.py:7`", "It stops after 5 notes a day.")
        self.assertIn("FAIL label:", lint(guide)[1])
        guide = self.guide("It stops after 5 notes (code comment). `src/cli.py:7`", "A code comment says it stops after 5 notes a day.")
        self.assertEqual(lint(guide)[0], 0)


class HowToStartTest(unittest.TestCase):
    def test_a_guide_without_a_how_to_start_section_fails(self):
        guide = GUIDE.replace("## How to start\n\nRun `notes add` to save your first note. [A4.b1]\n\n", "")
        code, out = lint(guide)
        self.assertEqual(code, 1)
        self.assertIn("FAIL how-to-start:", out)

    def test_an_empty_how_to_start_section_fails(self):
        guide = GUIDE.replace("Run `notes add` to save your first note. [A4.b1]\n", "")
        self.assertIn("FAIL how-to-start:", lint(guide)[1])

    def test_a_step_that_rests_on_an_uncited_appendix_line_fails(self):
        guide = GUIDE.replace("The `notes add` command saves a note. `src/cli.py:3` [A4.b1]", "The `notes add` command saves a note. [A4.b1]")
        code, out = lint(guide)
        self.assertEqual(code, 1)
        self.assertIn("FAIL how-to-start:", out)
        self.assertIn("A4.b1", out)

    def test_the_section_is_found_whatever_the_case(self):
        self.assertEqual(lint(GUIDE.replace("## How to start", "## How to Start"))[0], 0)


class GlossaryTest(unittest.TestCase):
    WITH = GUIDE.replace("# Part 2: Appendix", "## Glossary\n\n- notes add: the command that saves a note. [A4.b1]\n- slug: a short name in a web address. [A3.a1]\n\n# Part 2: Appendix")

    def test_a_glossary_with_entries_in_the_form_passes(self):
        self.assertEqual(lint(self.WITH)[0], 0, lint(self.WITH)[1])

    def test_an_entry_with_no_term_and_definition_fails(self):
        guide = GUIDE.replace("# Part 2: Appendix", "## Glossary\n\n- A line with no colon at all. [A3.a1]\n\n# Part 2: Appendix")
        self.assertIn("FAIL glossary:", lint(guide)[1])


def positional_ids(guide):
    """Round 1 numbered the appendix by position (A4.2 = second sentence of A4). Stamp each appendix line with the ids its sentences had, so the
    round-1 Part 1 tags still point where they pointed, and nothing else in the guide changes."""
    lines = guide.splitlines()
    by_line = defaultdict(list)
    for n, s in prose_sentences(guide, "/nonexistent"):
        by_line[n].append(s)
    sec, k = None, 0
    for n, line, header, heading in doc_lines(guide):
        if heading:
            m = re.match(r"#+\s+A(\d+)\b", line)
            sec, k = (m.group(1), 0) if m else (None, 0)
            continue
        if sec is None:
            continue
        ids = []
        for _ in by_line.get(n, []):
            k += 1
            ids.append("[A%s.%d]" % (sec, k))
        if ids:
            lines[n - 1] += " " + "".join(ids)
    return "\n".join(lines) + "\n"


def report_rows(path):
    rows = []
    for l in path.read_text().splitlines():
        m = re.match(r"(\d+) \| (\w+) \| (\w+) \| ([^|]*) \|", l)
        if m:
            rows.append((int(m.group(1)), m.group(2), m.group(3), m.group(4).strip().strip('"')))
    return rows


def squash(t):
    return " ".join(re.findall(r"[a-z0-9]+", t.lower()))


class Round1GuidesTest(unittest.TestCase):
    """The two guides the first climb round wrote, and the Part 1 errors its checkers found in them (Part 1 held 11 and 18). The gate must catch
    enough of them by script: a Part 1 sentence that drops a condition or a source label its tagged appendix sentence carries."""

    def run_guide(self, name, need):
        guide = positional_ids((HERE / "fixtures/round1" / name / "GUIDE.md").read_text())
        code, out = lint(guide)
        flagged = [(int(m.group(1)), squash(m.group(3))) for m in re.finditer(r"GUIDE\.md:(\d+): FAIL (condition|label): (.*)", out)]
        rows = report_rows(HERE / "fixtures/round1" / name / "part1-report.md")
        caught = [r for r in rows if any(n == r[0] and squash(r[3])[:60] in text for n, text in flagged)]
        self.assertGreaterEqual(len(caught), need, "%d of %d checker errors caught\n%s" % (len(caught), len(rows), out))
        return len(rows), len(caught), len(flagged)

    def test_agent_kit_five_of_its_eleven_part_1_errors_are_caught(self):
        self.assertEqual(self.run_guide("agent-kit", 5)[0], 11)

    def test_khoj_five_of_its_eighteen_part_1_errors_are_caught(self):
        self.assertEqual(self.run_guide("khoj", 5)[0], 18)


if __name__ == "__main__":
    unittest.main()
