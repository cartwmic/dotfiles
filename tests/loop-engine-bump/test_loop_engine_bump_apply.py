"""loop_engine_bump.py (dot_local/user_scripts/executable_loop_engine_bump.py): its apply step goes through `dotfiles-apply`, so a pin is installed only from a
commit the gate approves.

`apply()` runs for real. Its collaborators that need a repository, chezmoi or mise (the worktree, the PR's targets, the drift check, the installed versions) are
replaced; the command it calls is a stub `dotfiles-apply` on PATH that records its arguments and exits as told, and every other command it runs is recorded.
"""
import contextlib
import importlib.machinery
import io
import os
import stat
import subprocess
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 40
STUB = """#!/bin/sh
echo "$*" >> "$STUB_LOG"
echo "dotfiles-apply: $STUB_SAYS"
exit "${STUB_EXIT:-0}"
"""


def load():
    path = ROOT / "dot_local/user_scripts/executable_loop_engine_bump.py"
    loader = importlib.machinery.SourceFileLoader("loop_engine_bump_under_test", str(path))
    module = types.ModuleType(loader.name)
    loader.exec_module(module)
    return module


class Apply(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "dotfiles-apply").write_text(STUB)
        (self.bin / "dotfiles-apply").chmod(0o755 | stat.S_IXUSR)
        self.log = self.tmp / "stub.log"
        self.dest = self.tmp / "home"
        self.mise = self.dest / ".config/mise/config.toml"
        self.commands = []
        self.old = {k: os.environ.get(k) for k in ("PATH", "STUB_LOG", "STUB_SAYS", "STUB_EXIT")}
        os.environ.update(PATH="%s:%s" % (self.bin, os.environ["PATH"]), STUB_LOG=str(self.log), STUB_SAYS="applied")
        os.environ.pop("STUB_EXIT", None)
        self.m = load()
        real_run = self.m.run

        def run(cmd, step, cwd=None, env=None, check=True):
            if str(cmd[0]) == "dotfiles-apply":
                return real_run(cmd, step, cwd=cwd, env=env, check=check)
            self.commands.append([str(c) for c in cmd])
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        class Tree:
            path = self.tmp / "wt"

            def __init__(self, *_):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        self.pending = ""
        self.m.run = run
        self.m.git = lambda source, *args, step, check=True: types.SimpleNamespace(returncode=0, stdout="", stderr="")
        self.m.Worktree = Tree
        self.m.pr_targets = lambda wt, sha: {self.mise: ("dot_config/mise/config.toml", b"a", b"b")}
        self.m.check_drift = lambda wt, dest, targets, log: self.mise
        self.m.chezmoi = lambda wt, *args, step, check=True: types.SimpleNamespace(returncode=0, stdout=self.pending, stderr="")
        self.m.installed_versions = lambda dest: {tool: "1.2.3" for tool in self.m.TOOLS}
        self.logged = types.SimpleNamespace(record=lambda *a: None)

    def tearDown(self):
        for key, value in self.old.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)

    def apply(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.m.apply(self.tmp / "src", self.dest, SHA, {"number": 7, "url": "https://example.test/pull/7"}, "1.2.3", self.logged)

    def stub_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_the_pr_targets_go_through_dotfiles_apply_with_the_merge_commit(self):
        self.apply()
        self.assertEqual(self.stub_calls(), ["--contains %s %s" % (SHA, self.mise)])

    def test_nothing_applies_or_moves_the_source_checkout_by_itself(self):
        self.apply()
        self.assertEqual([c for c in self.commands if "chezmoi" in c[0] or c[0] == "git"], [])
        self.assertIn(["mise", "install", *self.m.TOOLS], self.commands)

    def test_a_refusal_stops_the_apply_before_the_install_and_a_rerun_can_resume(self):
        os.environ.update(STUB_EXIT="1", STUB_SAYS="the gate does not approve a commit that contains the merge")
        with self.assertRaises(self.m.Stop) as caught:
            self.apply()
        self.assertEqual(caught.exception.step, "apply")
        self.assertIn("the gate does not approve", str(caught.exception))
        self.assertIn("run this script again", str(caught.exception))
        self.assertEqual(self.commands, [])  # no mise install, no verify
        os.environ.pop("STUB_EXIT")
        self.apply()  # the rerun: the same call, now approved
        self.assertIn(["mise", "install", *self.m.TOOLS], self.commands)

    def test_the_pods_container_tools_script_is_run_through_dotfiles_apply_after_the_install(self):
        self.pending = " R 05_container_tools.sh\n"
        self.apply()
        script = self.dest / "05_container_tools.sh"
        self.assertEqual(self.stub_calls(), ["--contains %s --leave-pending %s %s" % (SHA, script, self.mise), "--contains %s %s" % (SHA, script)])

    def test_other_scripts_the_merge_leaves_pending_are_left_for_a_later_full_apply(self):
        self.pending = " R 05_container_tools.sh\n R 10_mise_bootstrap.sh\n"
        self.apply()
        a, b = self.dest / "05_container_tools.sh", self.dest / "10_mise_bootstrap.sh"
        self.assertEqual(self.stub_calls(), ["--contains %s --leave-pending %s --leave-pending %s %s" % (SHA, a, b, self.mise),
                                             "--contains %s --leave-pending %s %s" % (SHA, b, a)])

    def test_a_machine_that_does_not_list_the_script_runs_none(self):
        self.apply()
        self.assertEqual(len(self.stub_calls()), 1)


if __name__ == "__main__":
    unittest.main()
