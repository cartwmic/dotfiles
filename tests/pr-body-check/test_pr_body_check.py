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

FAKE_CI_MAIN_STATUS = r'''#!/bin/sh
# Stands in for ci-main-status: records its arguments, and exits as FAKE_THREADS_EXIT says (default 0).
echo "$*" >> "$FAKE_THREADS_LOG"
echo "fake ci-main-status said: unresolved"
exit "${FAKE_THREADS_EXIT:-0}"
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
        (self.bin / "ci-main-status").write_text(FAKE_CI_MAIN_STATUS, encoding="utf-8")
        (self.bin / "ci-main-status").chmod(0o755)
        self.threads_log = self.dir / "threads.log"
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


class ShimThreadCheck(ShimGhEnvironment):
    """After the body check passes on `pr-body-check REPO PR`, the shim runs `ci-main-status --threads REPO PR` (playbook 580f3e02 step 3)."""

    def shim(self, *args, node_exit=0, threads_exit=0):
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.home), "FAKE_GH_ENV_LOG": str(self.env_log),
               "FAKE_THREADS_LOG": str(self.threads_log), "FAKE_THREADS_EXIT": str(threads_exit)}
        (self.bin / "node").write_text("#!/bin/sh\nexit %d\n" % node_exit, encoding="utf-8")
        return subprocess.run(["sh", str(SHIM), *args], env=env, capture_output=True, text=True, timeout=60)

    def threads_calls(self):
        return self.threads_log.read_text(encoding="utf-8").splitlines() if self.threads_log.exists() else []

    def test_a_merge_chain_check_runs_the_thread_check_on_the_same_repo_and_pr(self):
        result = self.shim("cartwmic/dotfiles", "12")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.threads_calls(), ["--threads cartwmic/dotfiles 12"])

    def test_an_unresolved_thread_fails_the_check_with_the_thread_check_output(self):
        result = self.shim("cartwmic/dotfiles", "12", threads_exit=1)
        self.assertEqual(result.returncode, 1)
        self.assertIn("fake ci-main-status said: unresolved", result.stdout)

    def test_a_failed_body_check_stops_before_the_thread_check_and_keeps_its_exit_code(self):
        result = self.shim("cartwmic/dotfiles", "12", node_exit=1)
        self.assertEqual(result.returncode, 1)
        result = self.shim("cartwmic/dotfiles", "12", node_exit=2)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.threads_calls(), [])

    def test_a_check_before_a_review_round_does_not_read_threads(self):
        self.assertEqual(self.shim("cartwmic/dotfiles", "12", "--skip-intent-review").returncode, 0)
        self.assertEqual(self.threads_calls(), [])

    def test_a_body_only_check_does_not_read_threads(self):
        self.assertEqual(self.shim("--body-file", "/tmp/pr-body.x").returncode, 0)
        self.assertEqual(self.shim("cartwmic/dotfiles", "12", "--body-file", "/tmp/pr-12-body.x").returncode, 0)
        self.assertEqual(self.threads_calls(), [])

    def test_a_form_with_no_repo_and_pr_pair_does_not_read_threads(self):
        for args in (["--pr", "12", "--repo", "cartwmic/dotfiles"], ["cartwmic/dotfiles"], ["cartwmic/dotfiles", "x"]):
            self.assertEqual(self.shim(*args).returncode, 0, args)
        self.assertEqual(self.threads_calls(), [])


if __name__ == "__main__":
    unittest.main()
