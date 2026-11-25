"""runlog.py and the log line score.py and lint_main.py leave (design principle 14): each run of those scripts appends one JSON line to a log that
outlasts the terminal. Run as the skill runs the scripts (as scripts, on files), with the state folder pointed at a scratch folder.
Run: python3 -I tests/deriving-readable-docs/test_runlog.py"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"
SURFACES = [{"kind": "command", "name": "notes add", "file": "src/cli.py", "line": 3}]
GUIDE = ("# Part 1: In plain English\n\n## What it is\n\nIt saves notes. [A4.0001]\nWho it is for: anyone who takes notes. [A4.0001]\n\n"
         "## How to start\n\nYou run `notes add` to save one. [A4.0001]\n\n# Part 2: Appendix\n\n## A4 Notes\n\n"
         "The `notes add` command saves a note. `src/cli.py:3` [A4.0001]\nIt stops after 5 notes. `src/cli.py:7` [A4.0002]\n")
DOC = ("# Part 1: In plain English\n\n## What it is\n\nIt saves notes. [A4.0001]\n\n# Part 2: Appendix\n\n## A4 Notes\n\n"
       "The add command saves a note. `src/cli.py:3` [A4.0001]\nIt stops after 5 notes. `src/cli.py:7` [A4.0002]\n")
COUNTS = "Counts: claims checked %d; HOLDS %d; WRONG 0; OVERSTATED 0; UNSUPPORTED 0.\n"
PART1_REPORT = "Slice: slice-1\nread | 5.1 | HOLDS | src/cli.py:3\n" + COUNTS % (1, 1)


def run(state, name, *args):
    env = dict(os.environ, XDG_STATE_HOME=str(state), HOME=str(state))
    r = subprocess.run([sys.executable, "-I", str(SCRIPTS / name), *map(str, args)], capture_output=True, text=True, env=env)
    return r.returncode, r.stdout, r.stderr


def records(state):
    path = Path(state, "deriving-readable-docs", "log.jsonl")
    return [json.loads(l) for l in path.read_text().splitlines()] if path.is_file() else []


class RunlogTest(unittest.TestCase):
    def test_a_call_appends_one_json_line_with_the_numbers_it_was_given(self):
        with tempfile.TemporaryDirectory() as state:
            code = subprocess.run([sys.executable, "-I", "-B", "-c", "import sys; sys.path.insert(0, %r); from runlog import log_run; log_run('x.py', 'act', 'ok', n=3)" % str(SCRIPTS)],
                                  env=dict(os.environ, XDG_STATE_HOME=state)).returncode
            self.assertEqual(code, 0)
            (row,) = records(state)
            self.assertEqual({k: row[k] for k in ("script", "action", "outcome", "n")}, {"script": "x.py", "action": "act", "outcome": "ok", "n": 3})
            self.assertRegex(row["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertGreaterEqual(row["duration_s"], 0)

    def test_a_log_that_cannot_be_written_does_not_change_the_result(self):
        with tempfile.TemporaryDirectory() as d:
            blocked = Path(d, "file")
            blocked.write_text("not a folder")  # makedirs under a file fails
            with tempfile.TemporaryDirectory() as work:
                Path(work, "GUIDE.md").write_text(GUIDE)
                Path(work, "src").mkdir()
                Path(work, "src/cli.py").write_text("x\n" * 10)
                Path(work, "surfaces.json").write_text(json.dumps(SURFACES))
                code, out, err = run(blocked, "lint_main.py", Path(work, "GUIDE.md"), work, "--surfaces", Path(work, "surfaces.json"))
            self.assertEqual(code, 0, out + err)
            self.assertEqual(err, "")

    def test_every_copy_of_the_helper_in_the_skills_is_the_same_file(self):
        copies = sorted(HERE.parents[1].glob("dot_local/share/agent-harness/canonical/skills/*/scripts/runlog.py"))
        self.assertGreaterEqual(len(copies), 1)
        self.assertEqual({c.read_text() for c in copies}.__len__(), 1, [str(c) for c in copies])


class ScoreLogTest(unittest.TestCase):
    def score(self, state, reports):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            Path(d, "src/cli.py").write_text("x\n" * 10)
            Path(d, "GUIDE.md").write_text(DOC)
            run(state, "slice.py", Path(d, "GUIDE.md"), d, "--out", Path(d, "slices"))
            Path(d, "reports").mkdir()
            for name, text in reports.items():
                Path(d, "reports", name).write_text(text)
            return run(state, "score.py", Path(d, "reports"), "--repo", d, "--slices", Path(d, "slices"))

    def test_a_refusal_for_a_slice_with_no_report_leaves_a_record_naming_it(self):
        with tempfile.TemporaryDirectory() as state:
            code, out, err = self.score(state, {"part1-1.md": PART1_REPORT})
            self.assertEqual(code, 1, out + err)
            (row,) = records(state)
            self.assertEqual((row["script"], row["action"], row["outcome"]), ("score.py", "score", "refused"))
            self.assertIn("slice-2", row["reason"])
            self.assertIs(row["fix_round"], True)

    def test_a_scored_round_leaves_a_record_with_its_claims_and_errors(self):
        with tempfile.TemporaryDirectory() as state:
            slice2 = "Slice: slice-2\nread | 11.1 | HOLDS | src/cli.py:3\nread | 12.1 | HOLDS | src/cli.py:7\n" + COUNTS % (2, 2)
            code, out, err = self.score(state, {"part1-1.md": PART1_REPORT, "slice-2.md": slice2})
            self.assertEqual(code, 0, out + err)
            (row,) = records(state)
            self.assertEqual((row["outcome"], row["claims"], row["errors"]), ("ok", 3, 0))


class LintLogTest(unittest.TestCase):
    def lint(self, state, guide, *extra):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "src").mkdir()
            Path(d, "src/cli.py").write_text("x\n" * 10)
            Path(d, "GUIDE.md").write_text(guide)
            Path(d, "surfaces.json").write_text(json.dumps(SURFACES))
            return run(state, "lint_main.py", Path(d, "GUIDE.md"), d, "--surfaces", Path(d, "surfaces.json"), *extra)

    def test_a_run_leaves_the_part_1_word_count_it_printed(self):
        with tempfile.TemporaryDirectory() as state:
            code, out, err = self.lint(state, GUIDE)
            self.assertEqual(code, 0, out + err)
            (row,) = records(state)
            printed = int(out.split("Part 1: ")[1].split(" words")[0])
            self.assertEqual((row["script"], row["action"], row["outcome"], row["part1_words"], row["words_limit"]), ("lint_main.py", "lint-part1", "ok", printed, 1000))
            self.assertGreater(printed, 10)

    def test_a_halved_budget_is_logged_as_the_limit_the_run_used(self):
        with tempfile.TemporaryDirectory() as state:
            code, out, err = self.lint(state, GUIDE, "--max-words", "20")
            self.assertEqual(code, 1, out + err)
            (row,) = records(state)
            self.assertEqual((row["words_limit"], row["outcome"]), (20, "failed"))
            self.assertIn("(limit 20)", out)

    def test_a_guide_that_fails_a_check_is_logged_as_failed_with_the_count(self):
        with tempfile.TemporaryDirectory() as state:
            code, out, err = self.lint(state, GUIDE.replace("You run `notes add` to save one. [A4.0001]", "You run `notes add` to save one. [A9.9999]"))
            self.assertEqual(code, 1, out + err)
            (row,) = records(state)
            self.assertEqual((row["outcome"], row["fails"]), ("failed", 1))


if __name__ == "__main__":
    unittest.main()
