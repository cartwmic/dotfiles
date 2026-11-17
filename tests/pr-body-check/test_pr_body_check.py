"""Black-box test for dot_local/bin/executable_pr-body-check, the shim the merge chains run before a merge or a PR body edit.

The shim execs `node` on $HOME/git/coordinator/scripts/pr-body-check.ts. Here HOME is a scratch directory that holds that path,
`node` is a stand-in that calls `gh` the way the real check reads a PR, and `gh` records the environment it was started with.
Nothing reaches GitHub, the coordinator checkout or the real home directory.

    python3 -m unittest discover -s tests/pr-body-check -v
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "dot_local/bin/executable_pr-body-check"

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
        self.dir = Path(tempfile.mkdtemp(prefix="pr-body-check-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for name, text in (("gh", FAKE_GH), ("node", FAKE_NODE)):
            (self.bin / name).write_text(text, encoding="utf-8")
            (self.bin / name).chmod(0o755)
        self.home = self.dir / "home"
        (self.home / "git/coordinator/scripts").mkdir(parents=True)
        (self.home / "git/coordinator/scripts/pr-body-check.ts").write_text("// stand-in: the fake node does not read it\n", encoding="utf-8")
        self.env_log = self.dir / "gh-env.log"

    def run_shim(self):
        # Built from scratch, so no GH_URGENT or GH_CALLER leaks in from the shell that runs the tests.
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.home), "FAKE_GH_ENV_LOG": str(self.env_log)}
        return subprocess.run(["sh", str(SHIM), "cartwmic/dotfiles", "1"], env=env, capture_output=True, text=True, timeout=60)

    def test_the_gh_call_made_under_the_shim_is_urgent_and_names_the_check(self):
        result = self.run_shim()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.env_log.read_text(encoding="utf-8").splitlines(), ["urgent=1 caller=pr-body-check"])


if __name__ == "__main__":
    unittest.main()
