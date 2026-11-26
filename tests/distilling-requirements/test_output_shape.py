"""output-shape.md and check_shape.py: the shape the skill tells writers to follow is the shape the checker holds them to.
Run: python3 -I tests/distilling-requirements/test_output_shape.py"""
import runlog_support  # first: keeps the run out of the real log
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

STATE = runlog_support.STATE  # runlog_support keeps these runs out of the real log

SKILL = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/distilling-requirements"
SHAPE = (SKILL / "references/output-shape.md").read_text(encoding="utf-8")

HEADER = "```text\nshape: requirements/2\nrepo: x\ncommit: " + "a" * 40 + "\nsnapshot: 2026-11-22 at " + "a" * 40 + "\nhistory: " + "a" * 40 + "\nscope: whole repo\nrepo-wide: yes\ninterview: none\ndate: 2026-11-22\nnot-read: none\ncounts: R=0 SM=1 I=0 U=0 F=0 Q=0\n```\n\n# x\n\nSnapshot of x at aaaaaaa on 2026-11-22. Not maintained: it records the code at that commit, not today's.\n\n"


def check(machine):
    with tempfile.TemporaryDirectory() as d:
        Path(d, "REQUIREMENTS.md").write_text(HEADER + "### SM-1: job\n\n" + machine)
        r = subprocess.run([sys.executable, "-I", str(SKILL / "scripts/check_shape.py"), str(Path(d, "REQUIREMENTS.md"))], capture_output=True, text=True)
    return r.stdout + r.stderr


class OutputShapeTest(unittest.TestCase):
    def test_the_shape_says_a_machine_field_is_a_dash_bullet_and_the_checker_refuses_one_without(self):
        self.assertIn("each a bullet that starts `- `", SHAPE)
        self.assertIn("state machine has no '- writers:' line", check("writers: the CLI\n"))
        self.assertNotIn("state machine has no", check("- writers: the CLI\n"))

    def test_every_field_the_shape_says_the_checker_refuses_without_a_dash_is_refused(self):
        said = re.search(r"\(`check_shape\.py` refuses ([^)]*) without it\)", SHAPE)
        fields = re.findall(r"`(\w+):`", said.group(1))
        self.assertIn("writers", fields)
        for field in fields:
            self.assertIn("state machine has no '- %s:' line" % field, check("- writers: the CLI\n%s: x\n" % field if field != "writers" else "%s: x\n" % field), field)

    def test_an_incidental_surface_still_gets_a_row_so_coverage_can_reach_zero(self):
        self.assertIn("still gets a row marked `incidental` that cites it", SHAPE)


if __name__ == "__main__":
    unittest.main()
