"""agent_kit_bump.py (dot_local/user_scripts/executable_agent_kit_bump.py): its apply and install steps go through `dotfiles-apply`, so a pin is installed only
from a commit the gate approves.

`apply()` runs for real. Its collaborators that need a repository or chezmoi (the worktree, the PR's targets, the drift check, the installed version) are replaced;
the command it calls is a stub `dotfiles-apply` on PATH that records its arguments and exits as told, and every other command it runs is recorded.
"""
import contextlib
import importlib.machinery
import io
import os
import stat
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHA = "b" * 40
STUB = """#!/bin/sh
echo "$*" >> "$STUB_LOG"
echo "dotfiles-apply: $STUB_SAYS"
[ -n "$STUB_ERR" ] && echo "$STUB_ERR" >&2
exit "${STUB_EXIT:-0}"
"""


def load():
    path = ROOT / "dot_local/user_scripts/executable_agent_kit_bump.py"
    loader = importlib.machinery.SourceFileLoader("agent_kit_bump_under_test", str(path))
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
        self.commands = []
        self.old = {k: os.environ.get(k) for k in ("PATH", "STUB_LOG", "STUB_SAYS", "STUB_EXIT", "STUB_ERR")}
        os.environ.update(PATH="%s:%s" % (self.bin, os.environ["PATH"]), STUB_LOG=str(self.log), STUB_SAYS="applied")
        os.environ.pop("STUB_EXIT", None)
        os.environ.pop("STUB_ERR", None)
        self.m = load()
        self.pins = {self.dest / self.m.KIT_DEST / name: (name, b"a", b"b") for name in self.m.PIN_FILES}
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

        self.m.run = run
        self.m.git = lambda source, *args, step, check=True: types.SimpleNamespace(returncode=0, stdout="", stderr="")
        self.m.Worktree = Tree
        self.m.pr_targets = lambda wt, sha, dest: self.pins
        self.m.check_drift = lambda wt, dest, targets, log: None
        self.m.installed_version = lambda dest: "1.2.3"
        self.pending = ""  # what `chezmoi status --include scripts` lists
        self.m.chezmoi = lambda wt, *args, step, check=True: types.SimpleNamespace(returncode=0, stdout=self.pending, stderr="")
        self.logged = types.SimpleNamespace(record=lambda *a: None)

    def tearDown(self):
        for key, value in self.old.items():
            os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)

    def apply(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.m.apply(self.tmp / "src", self.dest, SHA, {"number": 9, "url": "https://example.test/pull/9"}, "1.2.3", self.logged)

    def stub_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_the_pins_and_the_install_script_go_through_one_dotfiles_apply_with_the_merge_commit(self):
        self.apply()
        pins = " ".join(str(p) for p in sorted(self.pins))
        self.assertEqual(self.stub_calls(), ["--contains %s %s %s" % (SHA, pins, self.dest / self.m.INSTALL_TARGET)])

    def test_other_scripts_the_merge_leaves_pending_are_left_and_the_install_script_is_not(self):
        self.pending = " R 65_agent_kit_install.sh\n R 10_mise_bootstrap.sh\n"
        self.apply()
        pins = " ".join(str(p) for p in sorted(self.pins))
        self.assertEqual(self.stub_calls(), ["--contains %s --leave-pending %s %s %s" % (SHA, self.dest / "10_mise_bootstrap.sh", pins, self.dest / self.m.INSTALL_TARGET)])

    def test_nothing_applies_or_moves_the_source_checkout_by_itself(self):
        self.apply()
        self.assertEqual(self.commands, [])  # no chezmoi, no git merge: every change to the machine is the command's

    def test_a_refusal_stops_at_the_apply_step_and_a_rerun_can_resume(self):
        os.environ.update(STUB_EXIT="1", STUB_SAYS="the gate does not approve a commit that contains the merge")
        with self.assertRaises(self.m.Stop) as caught:
            self.apply()
        self.assertEqual(caught.exception.step, "apply")
        self.assertIn("the gate does not approve", str(caught.exception))
        self.assertIn("run this script again", str(caught.exception))
        self.assertEqual(len(self.stub_calls()), 1)
        os.environ.pop("STUB_EXIT")
        self.apply()
        self.assertEqual(len(self.stub_calls()), 2)

    def test_what_the_command_wrote_to_stderr_is_passed_on_in_full(self):
        os.environ.update(STUB_ERR="65_agent_kit_install.sh: npm ci failed (the script's own error)")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.apply()
        self.assertEqual(err.getvalue().strip(), "65_agent_kit_install.sh: npm ci failed (the script's own error)")

    def test_a_failed_install_script_stops_at_the_apply_step(self):
        os.environ.update(STUB_EXIT="1", STUB_SAYS="chezmoi: 65_agent_kit_install.sh: exit status 1")
        with self.assertRaises(self.m.Stop) as caught:
            self.apply()
        self.assertEqual(caught.exception.step, "apply")
        self.assertIn("65_agent_kit_install.sh", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
