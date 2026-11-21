"""Black-box test for dot_local/bin/executable_intent-review-check, the shim that runs the review-record merge rule.

The shim execs `node` on $HOME/git/coordinator/scripts/intent-review-check.ts. Here HOME is a scratch directory that holds that path,
`node` is a stand-in that records the arguments and the environment it was started with, and `gh` is never called.
Nothing reaches GitHub, the coordinator checkout or the real home directory.

    python3 -m unittest discover -s tests/intent-review-check -v
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "dot_local/bin/executable_intent-review-check"

FAKE_NODE = r'''#!/bin/sh
printf '%s\n' "$@" > "$FAKE_NODE_ARGS_LOG"
printf 'urgent=%s caller=%s\n' "${GH_URGENT-unset}" "${GH_CALLER-unset}" > "$FAKE_NODE_ENV_LOG"
exit 0
'''


class ShimRunsTheScript(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="intent-review-check-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        (self.bin / "node").write_text(FAKE_NODE, encoding="utf-8")
        (self.bin / "node").chmod(0o755)
        self.home = self.dir / "home"
        (self.home / "git/coordinator/scripts").mkdir(parents=True)
        self.script = self.home / "git/coordinator/scripts/intent-review-check.ts"
        self.script.write_text("// stand-in: the fake node does not read it\n", encoding="utf-8")
        self.args_log = self.dir / "node-args.log"
        self.env_log = self.dir / "node-env.log"

    def run_shim(self, *args):
        # Built from scratch, so no GH_URGENT or GH_CALLER leaks in from the shell that runs the tests.
        env = {
            "PATH": "%s:%s" % (self.bin, os.environ["PATH"]),
            "HOME": str(self.home),
            "FAKE_NODE_ARGS_LOG": str(self.args_log),
            "FAKE_NODE_ENV_LOG": str(self.env_log),
        }
        return subprocess.run(["sh", str(SHIM), *args], env=env, capture_output=True, text=True, timeout=60)

    def test_the_script_runs_with_the_arguments_it_was_given(self):
        result = self.run_shim("cartwmic/loop-engine", "184")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            self.args_log.read_text(encoding="utf-8").splitlines(),
            ["--experimental-strip-types", "--disable-warning=ExperimentalWarning", str(self.script), "cartwmic/loop-engine", "184"],
        )

    def test_the_gh_reads_under_the_shim_are_urgent_and_name_the_check(self):
        result = self.run_shim("cartwmic/loop-engine", "184")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.env_log.read_text(encoding="utf-8").splitlines(), ["urgent=1 caller=intent-review-check"])

    def test_a_missing_coordinator_script_is_exit_2_with_the_fix(self):
        self.script.unlink()
        result = self.run_shim("cartwmic/loop-engine", "184")
        self.assertEqual(result.returncode, 2)
        self.assertIn("intent-review-check.ts is missing: pull ~/git/coordinator", result.stderr)
        self.assertFalse(self.args_log.exists(), "node must not start when the script is missing")


if __name__ == "__main__":
    unittest.main()
