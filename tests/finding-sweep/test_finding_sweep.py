"""Black-box test for dot_local/bin/executable_finding-sweep, the shim that runs the coordinator checkout's finding-sweep script.

HOME is a scratch directory that holds the script path and `node` is a stand-in that prints what it was started with, so nothing reaches the
coordinator checkout or the real home directory.

    python3 -m unittest discover -s tests/finding-sweep -v
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "dot_local/bin/executable_finding-sweep"

FAKE_NODE = r'''#!/bin/sh
for a in "$@"; do printf 'arg:%s\n' "$a"; done
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

    def run_shim(self, *args, **extra):
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.home), "XDG_STATE_HOME": str(self.dir / "state")}
        env.update(extra)
        return subprocess.run(["sh", str(SHIM), *args], env=env, capture_output=True, text=True, timeout=60)

    def test_it_runs_the_coordinator_script_with_each_argument_whole_and_keeps_its_exit_code(self):
        result = self.run_shim("coordinator#1741", "r1.some finding")
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.splitlines()[-3:],
            [
                "arg:%s" % self.script,
                "arg:coordinator#1741",
                "arg:r1.some finding",
            ],
        )

    def test_the_checkout_comes_from_coordinator_instance_when_it_is_there(self):
        other = self.dir / "work-checkout/scripts/finding-sweep.ts"
        other.parent.mkdir(parents=True)
        other.write_text("// stand-in\n", encoding="utf-8")
        instance = self.home / ".local/share/agent-harness/coordinator-instance"
        instance.parent.mkdir(parents=True)
        instance.write_text("%s\n%s\n" % (other.parent.parent, self.dir / "work-state"), encoding="utf-8")  # line 2 is the state directory on the work profile
        result = self.run_shim("x#1", "r1.y")
        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertIn("arg:%s" % other, result.stdout)

    def test_coordinator_repo_beats_coordinator_instance(self):
        other = self.dir / "env-checkout/scripts/finding-sweep.ts"
        other.parent.mkdir(parents=True)
        other.write_text("// stand-in\n", encoding="utf-8")
        result = self.run_shim("x#1", "r1.y", COORDINATOR_REPO=str(other.parent.parent))
        self.assertIn("arg:%s" % other, result.stdout)

    def test_a_missing_coordinator_script_is_exit_2_with_the_fix_and_one_json_record(self):
        self.script.unlink()
        result = self.run_shim("coordinator#1741", "r1.some-finding")
        self.assertEqual(result.returncode, 2)
        self.assertIn("finding-sweep.ts is missing: pull the coordinator checkout", result.stderr)
        lines = (self.dir / "state/agent-harness/finding-sweep.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        again = self.run_shim("coordinator#1741", "r1.some-finding")  # a second run adds a line: the file is appended to, never rewritten
        self.assertEqual(again.returncode, 2)
        self.assertEqual(len((self.dir / "state/agent-harness/finding-sweep.jsonl").read_text(encoding="utf-8").splitlines()), 2)
        record = json.loads(lines[0])
        self.assertEqual((record["event"], record["script"], record["path"]), ("script-missing", "finding-sweep", str(self.script)))


if __name__ == "__main__":
    unittest.main()
