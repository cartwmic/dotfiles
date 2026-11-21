"""check_citations.py --sheet lists the early exits of every function a cited range touches, not only the one holding its last line.
Run: python3 -I tests/deriving-readable-docs/test_sheet_exits.py"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "dot_local/share/agent-harness/canonical/skills/deriving-readable-docs/scripts"
TWO_FUNCTIONS = (
    "def first(x):\n    if x is None:\n        return None\n    y = x + 1\n    return y\n\n\n"
    "def second(z):\n    if z < 0:\n        raise ValueError('neg')\n    return z\n"
)


def sheet(source, cite):
    with tempfile.TemporaryDirectory() as d:
        Path(d, "src").mkdir()
        Path(d, "src/a.py").write_text(source)
        Path(d, "doc.md").write_text("## A4 x\n\nIt checks values. `src/a.py:%s` [A4.0001]\n" % cite)
        r = subprocess.run([sys.executable, "-I", str(SCRIPTS / "check_citations.py"), "doc.md", ".", "--sheet"], capture_output=True, text=True, cwd=d)
    return r.stdout


class SheetExitsTest(unittest.TestCase):
    def test_a_range_that_starts_in_one_function_and_ends_in_another_lists_the_exits_of_both(self):
        out = sheet(TWO_FUNCTIONS, "4-11")
        self.assertIn("early exits between the start of `def first(x):` (line 1) and line 5", out)
        self.assertIn("return None", out)
        self.assertIn("early exits between the start of `def second(z):` (line 8) and line 11", out)

    def test_a_range_inside_one_function_lists_only_that_function(self):
        out = sheet(TWO_FUNCTIONS, "9-11")
        self.assertIn("`def second(z):`", out)
        self.assertNotIn("`def first(x):`", out)


if __name__ == "__main__":
    unittest.main()
