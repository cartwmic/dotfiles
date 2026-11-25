"""Black-box test for dot_local/bin/executable_finding-sweep, the shim that runs the coordinator checkout's finding-sweep script.

HOME is a scratch directory that holds the script path and `node` is a stand-in that prints what it was started with, so nothing reaches the
coordinator checkout or the real home directory.

    python3 -m unittest discover -s tests/finding-sweep -v
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "dot_local/bin/executable_finding-sweep"

FAKE_NODE = r'''#!/bin/sh
printf 'node %s\n' "$*"
exit 7
'''


class Shim(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="finding-sweep-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        (self.bin / "node").write_text(FAKE_NODE, encoding="utf-8")
        (self.bin / "node").chmod(0o755)
        self.home = self.dir / "home"
        self.script = self.home / "git/coordinator/scripts/finding-sweep.ts"
        self.script.parent.mkdir(parents=True)
        self.script.write_text("// stand-in: the fake node does not read it\n", encoding="utf-8")

    def run_shim(self, *args):
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.home)}
        return subprocess.run(["sh", str(SHIM), *args], env=env, capture_output=True, text=True, timeout=60)

    def test_it_runs_the_coordinator_script_with_the_arguments_and_keeps_its_exit_code(self):
        result = self.run_shim("coordinator#1741", "r1.some-finding")
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertIn("finding-sweep.ts coordinator#1741 r1.some-finding", result.stdout)
        self.assertIn(str(self.script), result.stdout)

    def test_a_missing_coordinator_script_is_exit_2_with_the_fix(self):
        self.script.unlink()
        result = self.run_shim("coordinator#1741", "r1.some-finding")
        self.assertEqual(result.returncode, 2)
        self.assertIn("finding-sweep.ts is missing: pull ~/git/coordinator", result.stderr)


if __name__ == "__main__":
    unittest.main()
