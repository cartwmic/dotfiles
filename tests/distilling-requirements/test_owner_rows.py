"""A row whose evidence includes owner:interview states what the owner requires: the truth check hands the checker its note and the rule to judge it by.
Run: python3 -m unittest discover -s tests/distilling-requirements"""
import runlog_support  # first: keeps the run out of the real log
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = runlog_support.STATE  # runlog_support keeps these runs out of the real log

SKILL = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/distilling-requirements"
CODEMAP = SKILL.parent / "deriving-readable-docs/scripts"
TRUTH = SKILL / "scripts/check_truth.py"
RULE = ("A row whose evidence includes `owner:interview` states what the owner requires, not what the code does today. Judge whether the row's sentence "
        "and its note, read together, describe truly how far the cited code meets that requirement, including what it does not meet. A sentence that "
        "plainly states the owner's requirement and says the code does not meet it HOLDS if the cited code shows the gap.")
CODE = "def main(side):\n    return side\n"
ROWS = [
    ("R-1", "The tool shall run on every host the owner uses.", "owner:interview 2026-11-26 Q6; src/app.py:1",
     "Accepted in the interview on 2026-11-26. No code branches on a host name (app.py:2); the zone is fixed."),
    ("R-2", "The tool shall return its argument.", "src/app.py:2", "Plain row, note stays out."),
    ("R-3", "The owner shall be asked first.", "owner:interview 2026-11-26 Q2", "Owner only: nothing to read."),
]


def register():
    head = ("```text\nshape: requirements/2\nrepo: demo\ncommit: %s\nsnapshot: 2026-11-26 at %s\nhistory: %s\nscope: whole repo\nrepo-wide: yes\ninterview: i.md\n"
            "date: 2026-11-26\nnot-read: none\ncounts: R=%d SM=0 I=0 U=0 F=0 Q=0\n```\n# Requirements: demo\n\nSnapshot of demo at 0000000 on 2026-11-26. Not maintained: "
            "it records the code at that commit, not today's.\n\n## 1. Requirements register\n\n"
            "| id | lens | kind | durability | status | requirement | evidence | check | fit | enforced | note |\n|---|---|---|---|---|---|---|---|---|---|---|\n" % ("0" * 40, "0" * 40, "0" * 40, len(ROWS)))
    rows = "".join("| %s | quality | explicit | enduring | accepted | %s | %s | none | none | partial | %s |\n" % r for r in ROWS)
    return head + rows


def run(script, *args):
    r = subprocess.run([sys.executable, "-I", str(script), *map(str, args)], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


class OwnerRows(unittest.TestCase):
    def prepared(self, tmp):
        root = Path(tmp)
        (root / "repo/src").mkdir(parents=True)
        (root / "repo/src/app.py").write_text(CODE)
        (root / "REQUIREMENTS.md").write_text(register())
        code, out, err = run(TRUTH, "prepare", root / "REQUIREMENTS.md", "--out", root / "work")
        self.assertEqual(code, 0, err)
        return root / "repo", root / "work", out

    def test_an_interview_row_is_marked_and_its_note_goes_to_a_side_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, work, out = self.prepared(tmp)
            doc = (work / "register-claims.md").read_text()
            lines = doc.splitlines()
            self.assertIn("The tool shall run on every host the owner uses (owner requirement). `src/app.py:1`", doc)
            self.assertIn("The tool shall return its argument. `src/app.py:2`", doc)  # a plain row is left as it was
            self.assertNotIn("Accepted in the interview", doc)  # the note's date and numbers would fail check_citations.py in the sentence
            first = next(n for n, l in enumerate(lines, 1) if "(owner requirement)" in l)
            self.assertEqual((work / "owner-notes.txt").read_text(),
                             "%d | R-1 | Accepted in the interview on 2026-11-26. No code branches on a host name (app.py:2); the zone is fixed.\n" % first)
            self.assertIn("1 owner-requirement rows (R-1)", out)
            self.assertNotIn("..", out.split("give each checker")[1].split(" as well")[0])  # the addendum path is printed normalized
            self.assertTrue(Path(out.split("give each checker ")[1].split(" and ")[0]).is_file())
            records = [json.loads(l) for l in (Path(STATE) / "distilling-requirements/log.jsonl").read_text().splitlines()]
            self.assertEqual(records[-1]["owner_rows"], 1)
            self.assertEqual(run(CODEMAP / "check_citations.py", work / "register-claims.md", repo)[0], 0)

    def test_the_note_file_is_empty_when_no_row_states_an_owner_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo/src").mkdir(parents=True)
            (root / "repo/src/app.py").write_text(CODE)
            text = register().replace("owner:interview 2026-11-26 Q6; ", "")
            (root / "REQUIREMENTS.md").write_text(text)
            code, out, _ = run(TRUTH, "prepare", root / "REQUIREMENTS.md", "--out", root / "work")
            self.assertEqual(code, 0)
            self.assertEqual((root / "work/owner-notes.txt").read_text(), "")
            self.assertNotIn("owner-requirement", out)
            self.assertNotIn("(owner requirement)", (root / "work/register-claims.md").read_text())

    def test_a_two_sentence_owner_row_is_two_claims_on_the_line_the_note_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "repo/src").mkdir(parents=True)
            (root / "repo/src/app.py").write_text(CODE)
            two = ROWS[0][:1] + ("The tool shall run on every host. It shall say which host it chose.",) + ROWS[0][2:]
            text = register().replace(ROWS[0][1], two[1])
            (root / "REQUIREMENTS.md").write_text(text)
            self.assertEqual(run(TRUTH, "prepare", root / "REQUIREMENTS.md", "--out", root / "work")[0], 0)
            code, _, err = run(CODEMAP / "slice.py", root / "work/register-claims.md", root / "repo", "--out", root / "work/slices")
            self.assertEqual(code, 0, err)
            claims = (root / "work/slices/slice-1.claims.txt").read_text().splitlines()
            line = (root / "work/owner-notes.txt").read_text().split(" | ")[0]
            mine = [c for c in claims if c.startswith(line + ".")]
            self.assertEqual(len(mine), 2, claims)  # two claims on the owner line: only the second ends with the tag
            self.assertNotIn("(owner requirement)", mine[0])
            self.assertIn("(owner requirement)", mine[1])
            brief = (SKILL / "references/check-brief-owner-rows.md").read_text()
            self.assertIn("Every claim `N.k` whose `N` is a doc line in `owner-notes.txt`", brief)  # so the first claim gets the note too

    def test_the_rule_is_in_truth_check_and_in_the_brief_the_checker_gets(self):
        for name in ("truth-check.md", "check-brief-owner-rows.md"):
            text = (SKILL / "references" / name).read_text()
            self.assertIn(RULE, text, name)
        self.assertIn("check-brief-owner-rows.md", (SKILL / "references/truth-check.md").read_text())


if __name__ == "__main__":
    unittest.main()
