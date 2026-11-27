"""An id cited from another register is written `<label>:<id>`; check_shape.py takes it and still holds a file's own ids to the old rules.
Run: python3 -m unittest discover -s tests/distilling-requirements"""
import runlog_support  # first: keeps the run out of the real log
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = runlog_support.STATE  # runlog_support keeps these runs out of the real log

SKILL = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/distilling-requirements"
OUTPUT_SHAPE = (SKILL / "references/output-shape.md").read_text(encoding="utf-8")
SHA = "a" * 40
COLS = "| id | lens | kind | durability | status | requirement | evidence | check | fit | enforced | note |\n|---|---|---|---|---|---|---|---|---|---|---|\n"


def file_text(counts, body):
    head = ("```text\nshape: requirements/2\nrepo: x\ncommit: %s\nsnapshot: 2026-11-22 at %s\nhistory: %s\nscope: whole repo\nrepo-wide: yes\n"
            "interview: none\ndate: 2026-11-22\nnot-read: none\ncounts: %s\n```\n\n# x\n\nSnapshot of x at aaaaaaa on 2026-11-22. Not maintained: "
            "it records the code at that commit, not today's.\n\n" % (SHA, SHA, SHA, counts))
    return head + body + "\n## 2.\n\n## 3.\n\n## 4.\n\n## 5.\n\n## Run log\n"


def check(note, status="proposed", durability="enduring", questions=""):
    row = "## 1.\n\n" + COLS + "| R-1 | product | explicit | %s | %s | It shall x. | a.py:1 | none | none | yes | %s |\n" % (durability, status, note)
    text = file_text("R=1 SM=0 I=0 U=0 F=0 Q=%d" % questions.count("- Q-"), row + "\n" + questions)
    with tempfile.TemporaryDirectory() as d:
        Path(d, "REQUIREMENTS.md").write_text(text)
        r = subprocess.run([sys.executable, "-I", str(SKILL / "scripts/check_shape.py"), str(Path(d, "REQUIREMENTS.md"))], capture_output=True, text=True)
    return r.stdout + r.stderr


class QualifiedIds(unittest.TestCase):
    def test_a_qualified_id_of_another_register_is_not_dangling(self):
        out = check("Same job as core:R-12; see cli:F-3 and core:Q-9.")
        self.assertNotIn("dangling", out)
        self.assertIn("ok", out)

    def test_a_bare_id_this_file_lacks_is_still_dangling(self):
        self.assertIn("dangling reference R-12", check("Same job as R-12."))

    def test_a_qualified_id_does_not_hide_a_bare_one_beside_it(self):
        self.assertIn("dangling reference R-12", check("core:R-12 and R-12."))

    def test_a_qualified_q_is_not_this_files_open_question(self):
        out = check("Waiting on core:Q-1.", status="disputed")
        self.assertIn("a disputed or unclear row needs a Q-<n> in its note", out)
        self.assertEqual(check("Waiting on Q-1.", status="disputed", questions="## 5. Open questions\n\n- Q-1: which? Blocks R-1.\n").count("needs a Q"), 0)

    def test_the_shape_says_how_to_cite_another_register(self):
        self.assertIn("`<label>:<id>`", OUTPUT_SHAPE)
        self.assertIn("core:R-12", OUTPUT_SHAPE)


if __name__ == "__main__":
    unittest.main()
