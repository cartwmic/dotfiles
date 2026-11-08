"""dotfiles-update (dot_local/bin/executable_dotfiles-update): a non-interactive update with a stated policy for locally edited files.

Real chezmoi against a scratch source repository and a scratch HOME, no TTY. The red control is plain `chezmoi apply` in the same state:
it exits 1 ("could not open a new TTY") and applies nothing past the conflict, which is the failure that stopped the work Mac's update.
"""
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_dotfiles-update"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("git"), "chezmoi and git needed")
class DotfilesUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bare = self.tmp / "remote.git"
        self.src = self.tmp / "src"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.bare), str(self.src)], check=True, capture_output=True)
        self.write("dot_a", "one\n")
        self.write("dot_b", "one\n")
        self.write("dot_c", "one\n")
        self.write("run_onchange_after_10_mark.sh", "#!/bin/sh\necho ran >> \"$HOME/script-ran\"\n# v1\n")
        self.commit("init")
        self.cfg = self.tmp / "chezmoi.yaml"
        self.cfg.write_text("sourceDir: %s\n" % self.src)
        self.env = dict(os.environ, HOME=str(self.home), DOTFILES_UPDATE_CHEZMOI_ARGS="--config %s --config-format yaml --source %s --destination %s" % (
            self.cfg, self.src, self.home))
        self.chezmoi("apply")  # first apply: everything clean
        (self.home / "script-ran").unlink()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, text):
        (self.src / name).write_text(text)

    def commit(self, message):
        subprocess.run(["git", "-C", str(self.src), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.src), *GIT[1:], "commit", "-qm", message], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.src), "push", "-q", "origin", "HEAD:main"], check=True, capture_output=True)

    def chezmoi(self, *args):
        return subprocess.run(["chezmoi", "--no-tty", *shlex.split(self.env["DOTFILES_UPDATE_CHEZMOI_ARGS"]), *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, env=self.env, timeout=120)

    def update(self, *args, pull=False):
        return subprocess.run(["python3", str(SCRIPT), *([] if pull else ["--no-pull"]), *args], stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, env=self.env, timeout=180)

    def read(self, name):
        return (self.home / name).read_text()

    def conflict_state(self):
        """.a: edited here and changed in the source. .b: changed in the source only. .c: edited here only. Script: its source changed."""
        (self.home / ".a").write_text("local-a\n")
        (self.home / ".c").write_text("local-c\n")
        self.write("dot_a", "two\n")
        self.write("dot_b", "two\n")
        self.write("run_onchange_after_10_mark.sh", "#!/bin/sh\necho ran >> \"$HOME/script-ran\"\n# v2\n")
        self.commit("source change")

    def test_red_control_plain_chezmoi_apply_fails_with_no_tty_and_stops(self):
        self.conflict_state()
        r = subprocess.run(["chezmoi", *shlex.split(self.env["DOTFILES_UPDATE_CHEZMOI_ARGS"]), "apply"], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, env=self.env, timeout=120)  # as `chezmoi update` runs it, no --no-tty
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertRegex(r.stderr, r"could not open a new TTY|EOF")
        self.assertEqual(self.read(".b"), "one\n")  # nothing past the conflict was applied

    def test_conflicts_are_listed_never_overwritten_and_clean_files_still_apply(self):
        self.conflict_state()
        r = self.update()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.read(".a"), "local-a\n")  # not overwritten
        self.assertEqual(self.read(".c"), "local-c\n")
        self.assertEqual(self.read(".b"), "two\n")  # the clean file applied
        self.assertFalse((self.home / "script-ran").exists())  # scripts held back while a conflict is open
        self.assertIn("HELD: 2 path(s)", r.stdout)
        self.assertIn("~/.a", r.stdout)
        self.assertIn("~/.c", r.stdout)
        self.assertIn("held back 1 script(s)", r.stdout)
        self.assertIn("--take-source PATH", r.stdout)

    def test_the_report_shows_real_line_counts(self):
        self.conflict_state()
        r = self.update()
        self.assertIn("~/.a   edited here; apply would add 1 and remove 1 line(s)", r.stdout)

    def test_a_pending_directory_never_overwrites_an_edited_file_inside_it(self):
        # Round 1 review: `chezmoi apply --force DIR` recurses, so a directory pending on its own (here its attributes changed) took an edited file with it.
        (self.src / "dot_d").mkdir()
        self.write("dot_d/f", "one\n")
        self.commit("dir")
        self.chezmoi("apply")
        (self.home / ".d/f").write_text("local-d\n")
        subprocess.run(["git", "-C", str(self.src), "mv", "dot_d", "private_dot_d"], check=True)
        self.write("private_dot_d/f", "two\n")
        self.commit("directory attributes and the file inside change")
        r = self.update()
        self.assertEqual(self.read(".d/f"), "local-d\n", r.stdout)  # not overwritten
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertIn("~/.d/f", r.stdout)

    def drop_directory(self, how):
        # Round 2 review: `chezmoi status` shows only the directory for a removal or replacement, never the edited file inside it.
        (self.src / "dot_dd").mkdir()
        self.write("dot_dd/f", "one\n")
        self.commit("dir")
        self.chezmoi("apply")
        (self.home / ".dd/f").write_text("local-dd\n")
        subprocess.run(["git", "-C", str(self.src), "rm", "-rq", "dot_dd"], check=True)
        if how == "chezmoiremove":
            self.write(".chezmoiremove", ".dd\n")
        else:
            self.write("dot_dd", "now a file\n")
        self.commit("source drops the directory")
        r = self.update()
        self.assertEqual(self.read(".dd/f"), "local-dd\n", r.stdout)  # still there
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertIn("~/.dd", r.stdout)

    def test_a_directory_in_chezmoiremove_is_a_conflict_not_a_silent_delete(self):
        self.drop_directory("chezmoiremove")

    def test_a_directory_that_becomes_a_file_is_a_conflict_not_a_silent_delete(self):
        self.drop_directory("becomes_file")

    def test_a_new_source_file_over_a_local_file_chezmoi_never_wrote_is_held(self):
        # Round 3 review: chezmoi leaves the first status column blank for a path it never recorded, so blank did not mean "not edited here".
        (self.home / ".x").write_text("mine\n")
        self.write("dot_x", "from source\n")
        self.commit("source adds x")
        r = self.update()
        self.assertEqual(self.read(".x"), "mine\n", r.stdout)
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertIn("chezmoi has no record of writing it", r.stdout)

    def test_a_source_symlink_over_a_local_file_is_held(self):
        (self.home / ".lnk").write_text("mine\n")
        os.symlink("dot_a", self.src / "symlink_dot_lnk")
        self.commit("source adds a symlink")
        r = self.update()
        self.assertFalse((self.home / ".lnk").is_symlink(), r.stdout)
        self.assertEqual(self.read(".lnk"), "mine\n")
        self.assertEqual(r.returncode, 3, r.stdout)

    def test_a_mode_only_local_edit_is_held(self):
        os.chmod(self.home / ".b", 0o600)
        self.write("dot_b", "two\n")
        self.commit("source changes b")
        r = self.update()
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertIn("~/.b", r.stdout)
        self.assertEqual(self.read(".b"), "one\n")

    def test_a_dropped_directory_of_only_unedited_chezmoi_files_is_removed_but_junk_in_it_holds_it(self):
        (self.src / "dot_dd").mkdir()
        self.write("dot_dd/f", "one\n")
        self.commit("dir")
        self.chezmoi("apply")
        subprocess.run(["git", "-C", str(self.src), "rm", "-rq", "dot_dd"], check=True)
        self.write(".chezmoiremove", ".dd\n")
        self.commit("source drops the directory")
        (self.home / ".dd/.DS_Store").write_text("junk\n")  # not written by chezmoi
        held = self.update()
        self.assertEqual(held.returncode, 3, held.stdout)
        self.assertTrue((self.home / ".dd/f").exists())
        self.assertIn("inside that chezmoi did not write", held.stdout)
        (self.home / ".dd/.DS_Store").unlink()
        r = self.update()  # now every file in it is unedited chezmoi work: nothing is lost by removing it
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse((self.home / ".dd").exists())

    def test_line_counts_include_lines_that_start_with_dashes_or_pluses(self):
        self.write("dot_lua", "-- one\n-- two\nreal\n++ plus\n")
        self.commit("lua")
        self.chezmoi("apply")
        (self.home / ".lua").write_text("edited\n")
        self.write("dot_lua", "real\n-- three\n++ other\n")
        self.commit("lua changes")
        r = self.update()
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertIn("~/.lua   edited here; apply would add 3 and remove 1 line(s)", r.stdout)

    def test_take_source_on_a_file_deleted_here_says_there_was_no_copy(self):
        self.conflict_state()
        (self.home / ".a").unlink()
        r = self.update("--take-source", ".a", "--keep-local", ".c")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("you had no copy here to save", r.stdout)
        self.assertEqual(self.read(".a"), "two\n")

    def test_take_source_saves_the_local_copy_then_applies_the_source(self):
        self.conflict_state()
        r = self.update("--take-source", ".a", "--keep-local", ".c")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read(".a"), "two\n")
        self.assertEqual(self.read(".c"), "local-c\n")  # kept
        saved = list((self.home / ".local/state/dotfiles-update").glob("*/.a"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_text(), "local-a\n")
        self.assertTrue((self.home / "script-ran").exists())  # no conflict left: scripts run
        self.assertIn("kept your local version of ~/.c", r.stdout)

    def test_a_partial_decision_still_exits_3_for_the_rest(self):
        self.conflict_state()
        r = self.update("--take-source", ".a")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(self.read(".a"), "two\n")
        self.assertIn("HELD: 1 path(s)", r.stdout)
        self.assertFalse((self.home / "script-ran").exists())

    def test_dry_run_changes_nothing(self):
        self.conflict_state()
        before = {n: self.read(n) for n in (".a", ".b", ".c")}
        r = self.update("--dry-run")
        self.assertEqual(r.returncode, 3)
        self.assertEqual({n: self.read(n) for n in (".a", ".b", ".c")}, before)
        self.assertFalse((self.home / ".local/state/dotfiles-update").exists())

    def test_nothing_pending_is_exit_0(self):
        r = self.update()
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "dotfiles-update: nothing to update."))

    def test_pulls_the_source_first(self):
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.bare), str(other)], check=True, capture_output=True)
        (other / "dot_b").write_text("from-remote\n")
        subprocess.run(["git", "-C", str(other), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(other), *GIT[1:], "commit", "-qm", "remote"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(other), "push", "-q", "origin", "HEAD:main"], check=True, capture_output=True)
        r = self.update(pull=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read(".b"), "from-remote\n")

    def test_a_path_outside_the_conflict_list_is_reported_not_acted_on(self):
        self.conflict_state()
        r = self.update("--take-source", ".b", "--keep-local", ".a", "--keep-local", ".c")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("~/.b is not held", r.stdout)

    def test_the_same_path_in_both_flags_is_refused(self):
        self.conflict_state()
        r = self.update("--take-source", ".a", "--keep-local", ".a")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.read(".a"), "local-a\n")


if __name__ == "__main__":
    unittest.main()
