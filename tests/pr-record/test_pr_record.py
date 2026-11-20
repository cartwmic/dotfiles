"""Black-box test for dot_local/bin/executable_pr-record, the shim that prints a PR's agent record path and fills the record from a description.

The shim execs `node` on $HOME/git/coordinator/scripts/pr-record.ts. Here HOME is a scratch directory that holds that path,
`node` is a stand-in that calls `gh` the way the real command reads a PR, and `gh` records the environment it was started with.
Nothing reaches GitHub, the coordinator checkout or the real home directory.

    python3 -m unittest discover -s tests/pr-record -v
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "dot_local/bin/executable_pr-record"

FAKE_GH = r'''#!/bin/sh
printf 'urgent=%s caller=%s\n' "${GH_URGENT-unset}" "${GH_CALLER-unset}" >> "$FAKE_GH_ENV_LOG"
exit 0
'''

FAKE_NODE = r'''#!/bin/sh
# Stands in for node. The real check reads the PR through gh, so this makes the same kind of gh call.
exec gh pr view 1 --repo cartwmic/dotfiles --json body
'''


class ShimGhEnvironment(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pr-record-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for name, text in (("gh", FAKE_GH), ("node", FAKE_NODE)):
            (self.bin / name).write_text(text, encoding="utf-8")
            (self.bin / name).chmod(0o755)
        self.home = self.dir / "home"
        (self.home / "git/coordinator/scripts").mkdir(parents=True)
        (self.home / "git/coordinator/scripts/pr-record.ts").write_text("// stand-in: the fake node does not read it\n", encoding="utf-8")
        self.env_log = self.dir / "gh-env.log"

    def run_shim(self):
        # Built from scratch, so no GH_URGENT or GH_CALLER leaks in from the shell that runs the tests.
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.home), "FAKE_GH_ENV_LOG": str(self.env_log)}
        return subprocess.run(["sh", str(SHIM), "import", "dotfiles#1"], env=env, capture_output=True, text=True, timeout=60)

    def test_the_gh_call_made_under_the_shim_is_urgent_and_names_the_command(self):
        result = self.run_shim()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.env_log.read_text(encoding="utf-8").splitlines(), ["urgent=1 caller=pr-record"])

    def test_a_missing_coordinator_script_is_exit_2_with_the_fix(self):
        (self.home / "git/coordinator/scripts/pr-record.ts").unlink()
        result = self.run_shim()
        self.assertEqual(result.returncode, 2)
        self.assertIn("pr-record.ts is missing: pull ~/git/coordinator", result.stderr)


if __name__ == "__main__":
    unittest.main()
