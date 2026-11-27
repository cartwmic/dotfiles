"""Every test file here says how to run it, and the words are the discover command, which works (python3 -I drops this folder from sys.path, so runlog_support would not import).
Run: python3 -m unittest discover -s tests/distilling-requirements"""
import runlog_support  # first: keeps the run out of the real log
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
COMMAND = "python3 -m unittest discover -s tests/distilling-requirements"
INNER = "RUN_HEADERS_INNER"


class RunHeaders(unittest.TestCase):
    def test_every_run_line_is_the_discover_command(self):
        for path in sorted(HERE.glob("test_*.py")):
            lines = re.findall(r"^Run: (.*?)\"*$", path.read_text(encoding="utf-8").split("import ", 1)[0], re.MULTILINE)
            self.assertEqual(lines, [COMMAND], path.name)

    @unittest.skipIf(os.environ.get(INNER), "this is the run the outer test started")
    def test_the_command_runs_and_passes(self):
        env = dict(os.environ, **{INNER: "1"})
        # The header command, narrowed to this one file with -p, proves the command works from the repo root
        # (runlog_support imports under discover) without running the whole suite a second time.
        result = subprocess.run([sys.executable] + COMMAND.split()[1:] + ["-p", Path(__file__).name], cwd=REPO, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        self.assertIn("OK", result.stderr)


if __name__ == "__main__":
    unittest.main()
