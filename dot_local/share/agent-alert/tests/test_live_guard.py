"""Unit test of live_guard.py against scratch stand-ins (no live state is read).

Run (from the repository root):

    python3 -m unittest discover -s dot_local/share/agent-alert/tests -p 'test_live_guard.py'
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

GUARD = common.TESTS_DIR / "live_guard.py"
GIT_ENV = {
    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(cwd, *args):
    done = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert done.returncode == 0, (args, done.stderr)
    return done.stdout.strip()


class LiveGuardTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="live-guard-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        # Stand-in for the live home and the live Herdr config directory.
        self.home = self.root / "home"
        self.herdr_dir = self.home / ".config" / "herdr"
        self.herdr_dir.mkdir(parents=True)
        (self.herdr_dir / "config.toml").write_text("theme = 'a'\n")
        (self.herdr_dir / "plugins.json").write_text("{}\n")
        # Stand-in herdr binary whose answers come from two files.
        self.plugin_list = self.root / "plugin-list.txt"
        self.status = self.root / "status.txt"
        self.plugin_list.write_text("1 plugin installed\n")
        self.status.write_text("status: running\nversion: 0.9.1\n")
        self.herdr = self.root / "herdr"
        self.herdr.write_text(
            '#!/bin/sh\ncase "$1" in plugin) cat "%s";; status) cat "%s";; *) exit 9;; esac\n' % (self.plugin_list, self.status)
        )
        self.herdr.chmod(self.herdr.stat().st_mode | stat.S_IXUSR)
        # Stand-in repository with a bare remote and a feature branch.
        self.remote = self.root / "remote.git"
        self.repo = self.root / "repo"
        git(self.root, "init", "--bare", "-b", "main", str(self.remote))
        git(self.root, "init", "-b", "main", str(self.repo))
        (self.repo / "dot_local" / "share" / "agent-alert").mkdir(parents=True)
        (self.repo / "dot_local" / "share" / "agent-alert" / "tool.py").write_text("a\n")
        (self.repo / ".chezmoiignore").write_text("x\n")
        (self.repo / "README.md").write_text("readme\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-m", "base")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "origin", "main")
        git(self.repo, "checkout", "-b", "feat/x")
        self.snapshot = self.root / "snapshots" / "baseline.json"

    def guard(self, command, *extra, file=None):
        arguments = [
            sys.executable, str(GUARD), command,
            "--file", str(file or self.snapshot),
            "--home", str(self.home),
            "--herdr-config-dir", str(self.herdr_dir),
            "--repo", str(self.repo),
            "--herdr-bin", str(self.herdr),
            *extra,
        ]
        return subprocess.run(arguments, env=GIT_ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)

    def take_snapshot(self):
        done = self.guard("snapshot")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(self.snapshot.is_file())
        return done

    def assert_check_ok(self):
        done = self.guard("check")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def assert_check_differs(self, expected_text):
        done = self.guard("check")
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn(expected_text, done.stdout)

    def test_snapshot_records_live_baseline_outside_the_checkout(self):
        done = self.take_snapshot()
        self.assertNotIn(str(self.repo), str(self.snapshot))
        text = self.snapshot.read_text()
        for expected in ("config.toml", "plugins.json", "1 plugin installed", "version: 0.9.1", ".local/share/coordinator/inbox.jsonl", "absent", "feat/x"):
            self.assertIn(expected, text)
        self.assertIn(git(self.repo, "rev-parse", "HEAD"), done.stdout)

    def test_snapshot_inside_the_checkout_is_refused(self):
        done = self.guard("snapshot", file=self.repo / "snapshot.json")
        self.assertEqual(done.returncode, 2)
        self.assertFalse((self.repo / "snapshot.json").exists())

    def test_unchanged_state_and_planned_edits_pass(self):
        self.take_snapshot()
        self.assert_check_ok()
        planned = self.repo / "dot_local" / "share" / "agent-alert"
        (planned / "tool.py").write_text("edited\n")
        (planned / "new.py").write_text("new\n")
        (planned / "tests").mkdir()
        (planned / "tests" / "t.py").write_text("t\n")
        (self.repo / ".chezmoiignore").write_text("edited\n")
        self.assert_check_ok()

    def test_live_file_change_is_detected(self):
        self.take_snapshot()
        (self.herdr_dir / "config.toml").write_text("theme = 'b'\n")
        self.assert_check_differs("config.toml")

    def test_plugins_json_change_is_detected(self):
        self.take_snapshot()
        (self.herdr_dir / "plugins.json").write_text('{"x":1}\n')
        self.assert_check_differs("plugins.json")

    def test_live_plugin_list_and_server_version_changes_are_detected(self):
        self.take_snapshot()
        self.plugin_list.write_text("2 plugins installed\n")
        self.assert_check_differs("herdr_plugin_list")
        self.plugin_list.write_text("1 plugin installed\n")
        self.assert_check_ok()
        self.status.write_text("status: running\nversion: 0.9.2\n")
        self.assert_check_differs("herdr_server_status")

    def test_live_inbox_config_or_log_appearing_is_detected(self):
        self.take_snapshot()
        cases = (
            (".local/share/coordinator/inbox.jsonl", ".local/share/coordinator/inbox.jsonl"),
            (".config/agent-alert/config.json", "live_listing .config/agent-alert"),
            (".local/state/agent-alert/agent-alert.log", "live_listing .local/state/agent-alert"),
        )
        for relative, expected in cases:
            path = self.home / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x")
            self.assert_check_differs(expected)
            shutil.rmtree(self.home / ".local", ignore_errors=True)
            shutil.rmtree(self.home / ".config" / "agent-alert", ignore_errors=True)
            self.assert_check_ok()

    def test_new_commit_is_detected(self):
        self.take_snapshot()
        (self.repo / "dot_local" / "share" / "agent-alert" / "tool.py").write_text("committed\n")
        git(self.repo, "commit", "-am", "oops")
        self.assert_check_differs("HEAD commit")

    def test_moved_remote_tip_is_detected(self):
        git(self.repo, "push", "origin", "feat/x")
        self.take_snapshot()
        self.assert_check_ok()
        other = self.root / "other"
        git(self.root, "clone", "-b", "feat/x", str(self.remote), str(other))
        (other / "pushed.txt").write_text("p\n")
        git(other, "add", "-A")
        git(other, "commit", "-m", "someone pushed")
        git(other, "push", "origin", "feat/x")
        self.assert_check_differs("remote tip")

    def test_absent_remote_branch_is_the_baseline_and_a_push_is_detected(self):
        done = self.take_snapshot()
        self.assertIn('"remote_tip": "absent"', done.stdout)
        self.assert_check_ok()
        git(self.repo, "push", "origin", "feat/x")
        self.assert_check_differs("remote tip")

    def test_change_outside_the_planned_set_is_detected(self):
        self.take_snapshot()
        (self.repo / "README.md").write_text("changed\n")
        self.assert_check_differs("README.md")
        git(self.repo, "checkout", "--", "README.md")
        self.assert_check_ok()
        (self.repo / "stray.txt").write_text("untracked\n")
        self.assert_check_differs("stray.txt")
        (self.repo / "stray.txt").unlink()
        (self.repo / "README.md").rename(self.repo / "RENAMED.md")
        self.assert_check_differs("README.md")

    def test_unreachable_remote_fails_loudly_for_snapshot_and_check(self):
        broken = self.guard("snapshot", "--remote", str(self.root / "no-such-remote.git"))
        self.assertEqual(broken.returncode, 2)
        self.assertIn("not a pass", broken.stderr)
        self.assertFalse(self.snapshot.exists())
        self.take_snapshot()
        git(self.repo, "remote", "set-url", "origin", str(self.root / "no-such-remote.git"))
        done = self.guard("check")
        self.assertEqual(done.returncode, 2)
        self.assertIn("not a pass", done.stderr)

    def test_missing_herdr_or_snapshot_fails_loudly(self):
        done = self.guard("snapshot", "--herdr-bin", str(self.root / "no-herdr"))
        self.assertEqual(done.returncode, 2)
        self.assertEqual(self.guard("check", file=self.root / "none.json").returncode, 2)


if __name__ == "__main__":
    unittest.main()
