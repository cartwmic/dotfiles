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

    def git_head(self):
        return subprocess.run(["git", "-C", str(self.src), "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()

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
        head = self.git_head()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip().splitlines(), ["dotfiles-update: source at %s, was %s (no new commits)" % (head, head),
                                                         "dotfiles-update: nothing to update."])

    def test_pulls_the_source_first(self):
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.bare), str(other)], check=True, capture_output=True)
        (other / "dot_b").write_text("from-remote\n")
        subprocess.run(["git", "-C", str(other), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(other), *GIT[1:], "commit", "-qm", "remote"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(other), "push", "-q", "origin", "HEAD:main"], check=True, capture_output=True)
        was = self.git_head()
        r = self.update(pull=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read(".b"), "from-remote\n")
        self.assertIn("source at %s, was %s\n" % (self.git_head(), was), r.stdout)  # E19: the commit that was applied, and the one before
        self.assertNotEqual(self.git_head(), was)

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

    # --- E20: each script that ran is reported with its exit code ---

    def test_every_script_that_ran_is_reported_with_its_exit_code(self):
        self.write("run_onchange_after_10_mark.sh", "#!/bin/sh\necho ran >> \"$HOME/script-ran\"\n# v2\n")
        self.write("run_onchange_after_20_quiet.sh", "#!/bin/sh\nexit 0\n")
        self.commit("scripts")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ran 2 script(s)", r.stdout)
        self.assertIn("  script 10_mark.sh   exit 0\n", r.stdout)
        self.assertIn("  script 20_quiet.sh   exit 0\n", r.stdout)

    def test_a_script_that_exits_0_but_says_it_failed_inside_is_visible(self):
        # E21: the kit install printed WARN and exited 0, and `apply --verbose` showed nothing about it.
        self.write("run_onchange_after_20_kit.sh", "#!/bin/sh\necho '[kit] WARN: npm ci failed' >&2\necho fine\nexit 0\n")
        self.commit("script that fails inside")
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("  script 20_kit.sh   exit 0   (its output says: [kit] WARN: npm ci failed)", r.stdout)

    def test_a_script_that_fails_is_named_with_its_exit_code_and_the_run_exits_1(self):
        self.write("run_onchange_after_20_bad.sh", "#!/bin/sh\necho 'ERROR: boom' >&2\nexit 7\n")
        self.commit("failing script")
        r = self.update()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("  script 20_bad.sh   exit 7   (its output says: ERROR: boom)", r.stdout)
        self.assertIn("20_bad.sh exited non-zero", r.stdout)

    # --- E22: a run_after_ script is listed by `chezmoi status` after every apply; that is not a pending change ---

    def test_an_always_run_script_in_status_is_reported_clean_with_the_reason_and_still_runs(self):
        self.write("run_after_75_reconcile.sh", "#!/bin/sh\necho ran >> \"$HOME/always-ran\"\n")
        self.commit("always-run script")
        self.chezmoi("apply")
        (self.home / "always-ran").unlink()
        status = self.chezmoi("status")
        self.assertIn("75_reconcile.sh", status.stdout)  # the symptom: a clean machine, and status still lists it
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("dotfiles-update: nothing to update.", r.stdout)
        self.assertIn("clean: 1 always-run script(s) (run_after_/run_before_) are listed by `chezmoi status` after every apply", r.stdout)
        self.assertIn("  script 75_reconcile.sh   exit 0", r.stdout)
        self.assertEqual(self.read("always-ran"), "ran\n")  # it still runs, as `chezmoi apply` would (instances_reconcile retries on every apply)

    def test_dry_run_names_the_always_run_scripts_and_runs_nothing(self):
        self.write("run_after_75_reconcile.sh", "#!/bin/sh\necho ran >> \"$HOME/always-ran\"\n")
        self.commit("always-run script")
        self.chezmoi("apply")
        (self.home / "always-ran").unlink()
        r = self.update("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("they would run now: 75_reconcile.sh", r.stdout)
        self.assertFalse((self.home / "always-ran").exists())

    def test_a_changed_script_is_not_called_clean(self):
        self.write("run_onchange_after_10_mark.sh", "#!/bin/sh\necho ran >> \"$HOME/script-ran\"\n# v2\n")
        self.commit("script change")
        r = self.update()
        self.assertNotIn("nothing to update", r.stdout)
        self.assertNotIn("clean:", r.stdout)

    # --- review round 4 ---

    def test_a_held_removal_is_held_and_reported_not_a_crash(self):
        # f1: an edited file the source REMOVES (.chezmoiremove) and a local file inside an exact_ directory used to end the run with exit 1.
        self.write(".chezmoiremove", ".rm\n")
        (self.home / ".rm").write_text("mine\n")  # chezmoi never wrote it: removing it would lose it
        (self.src / "exact_dot_ex").mkdir()
        self.write("exact_dot_ex/kept", "k\n")
        self.write("dot_z", "z\n")
        self.commit("remove, exact dir, new file")
        self.chezmoi("apply", str(self.home / ".ex"), str(self.home / ".z"))
        (self.home / ".ex/mine").write_text("local\n")
        r = self.update()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.read(".rm"), "mine\n")
        self.assertEqual(self.read(".ex/mine"), "local\n")
        self.assertIn("~/.rm", r.stdout)
        self.assertIn("the source removes it, apply would delete it", r.stdout)
        self.assertIn("~/.ex/mine", r.stdout)
        r = self.update("--take-source", ".rm", "--keep-local", ".ex/mine")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.home / ".rm").exists())
        saved = list((self.home / ".local/state/dotfiles-update").glob("*/.rm"))
        self.assertEqual([p.read_text() for p in saved], ["mine\n"])  # the copy was saved before the removal

    def test_a_binary_source_file_over_a_held_path_does_not_crash(self):
        # f2: chezmoi cat of non-UTF-8 content raised UnicodeDecodeError in the report.
        self.write("dot_bin", "text\n")
        self.commit("bin v1")
        self.chezmoi("apply", str(self.home / ".bin"))
        (self.home / ".bin").write_text("local edit\n")
        (self.src / "dot_bin").write_bytes(b"\xff\xfe\x00\x01\x80")
        self.commit("bin v2 is binary")
        r = self.update()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("binary file, apply would replace it", r.stdout)
        self.assertNotIn("Traceback", r.stderr)
        r = self.update("--take-source", ".bin")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.home / ".bin").read_bytes(), b"\xff\xfe\x00\x01\x80")

    def test_git_repo_externals_are_refreshed_though_status_does_not_list_them(self):
        # f3: `chezmoi status` never lists a git-repo external that is due a pull, and no full apply ran.
        remote = self.tmp / "ext-remote"
        subprocess.run(["git", "init", "-q", "-b", "main", str(remote)], check=True)
        (remote / "f").write_text("f\n")
        subprocess.run(["git", "-C", str(remote), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(remote), *GIT[1:], "commit", "-qm", "i"], check=True, capture_output=True)
        self.write(".chezmoiexternal.toml", '[".ext"]\n  type = "git-repo"\n  url = "%s"\n  refreshPeriod = "1s"\n' % remote)
        self.commit("external")
        self.assertEqual(self.chezmoi("apply").returncode, 0)  # clones it
        (remote / "g").write_text("g\n")
        subprocess.run(["git", "-C", str(remote), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(remote), *GIT[1:], "commit", "-qm", "g"], check=True, capture_output=True)
        import time
        time.sleep(2)
        self.assertNotIn(".ext", self.chezmoi("status").stdout)  # the review's red: nothing pending as far as status knows
        r = self.update()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.home / ".ext/g").exists())
        self.assertIn("checked 1 git-repo external(s)", r.stdout)

    def test_a_new_file_in_a_directory_you_deleted_waits_and_nothing_else_stops(self):
        # f4: the new file was called clean, the batched apply failed on the missing parent and updated nothing.
        (self.src / "dot_d").mkdir()
        self.write("dot_d/a", "a\n")
        self.commit("d")
        self.chezmoi("apply")
        shutil.rmtree(self.home / ".d")
        self.write("dot_d/new", "n\n")
        self.write("dot_a", "two\n")
        self.commit("new file in the deleted directory, and another change")
        r = self.update()
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.read(".a"), "two\n")  # the rest still applied
        self.assertIn("~/.d   you deleted it here", r.stdout)
        self.assertIn("waiting on a held directory", r.stdout)
        self.assertFalse((self.home / ".d").exists())
        r = self.update("--take-source", ".d", "--take-source", ".d/a")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.read(".d/a"), self.read(".d/new")), ("a\n", "n\n"))  # the waiting file followed its directory

    def test_no_build_cache_is_committed_or_deployable(self):
        # f5: a .pyc under dot_local/bin was committed and would have been deployed to every machine.
        if not (ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "*__pycache__*", "*.pyc"], capture_output=True, text=True).stdout.split()
        self.assertEqual(tracked, [])
        ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "dot_local/bin/__pycache__/x.pyc"])
        self.assertEqual(ignored.returncode, 0)

    def test_every_real_run_leaves_a_record_and_a_dry_run_leaves_none(self):
        # f6: design principle 14, a record that survives the terminal.
        self.conflict_state()
        self.update("--dry-run")
        self.assertFalse((self.home / ".local/state/dotfiles-update/log.jsonl").exists())
        r = self.update("--take-source", ".a")
        self.assertEqual(r.returncode, 3)
        lines = (self.home / ".local/state/dotfiles-update/log.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["exit"], 3)
        self.assertIn("~/.b", record["applied"])
        self.assertEqual([t["path"] for t in record["taken"]], ["~/.a"])
        self.assertTrue(record["taken"][0]["saved"].endswith("/.a"))
        self.assertEqual([h["path"] for h in record["held"]], ["~/.c"])
        self.assertEqual(record["source_was"], record["source_now"])

    # --- review round 5 ---

    def test_a_run_that_stops_in_a_script_still_records_and_says_what_it_already_changed(self):
        # f1: the record was written only on exit 0 or 3, so a failed run lost the applied and taken lists and the backup path.
        self.conflict_state()
        self.write("run_onchange_after_20_bad.sh", "#!/bin/sh\necho 'npm ERR! code E401' >&2\nexit 1\n")
        self.commit("failing script")
        r = self.update("--take-source", ".a", "--keep-local", ".c")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.read(".a"), "two\n")
        self.assertIn("before it stopped, dotfiles-update had applied", r.stdout)
        self.assertIn("saved your copy of ~/.a as ~/.local/state/dotfiles-update/", r.stdout)
        record = json.loads((self.home / ".local/state/dotfiles-update/log.jsonl").read_text().splitlines()[-1])
        self.assertEqual(record["exit"], 1)
        self.assertIn("~/.b", record["applied"])
        self.assertTrue(record["taken"][0]["saved"].endswith("/.a"))
        self.assertTrue(Path(record["taken"][0]["saved"]).is_file())

    def test_a_failing_scripts_own_output_is_shown_and_recorded(self):
        # f3: since E20 the output was swallowed: only "exit 1" was shown.
        self.write("run_onchange_after_20_bad.sh", "#!/bin/sh\necho 'npm ERR! code E401'\necho 'second line' >&2\nexit 1\n")
        self.write("run_onchange_after_10_soft.sh", "#!/bin/sh\necho 'Error: could not reach the registry'\nexit 0\n")
        self.commit("scripts")
        r = self.update()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("      | npm ERR! code E401", r.stdout)
        self.assertIn("      | second line", r.stdout)
        self.assertIn("script 10_soft.sh   exit 0   (its output says: Error: could not reach the registry)", r.stdout)
        record = json.loads((self.home / ".local/state/dotfiles-update/log.jsonl").read_text().splitlines()[-1])
        bad = [x for x in record["scripts"] if x["name"] == "20_bad.sh"][0]
        self.assertEqual((bad["exit"], bad["tail"][:1]), (1, ["npm ERR! code E401"]))

    def test_waiting_works_at_every_depth_and_a_taken_child_needs_its_held_parent_taken(self):
        # f2: with .d and .d/e both deleted, taking only .d, or only .d/a, made the batched apply fail on a missing parent.
        (self.src / "dot_d/e").mkdir(parents=True)
        self.write("dot_d/a", "a\n")
        self.write("dot_d/e/g", "g\n")
        self.commit("tree")
        self.chezmoi("apply")
        shutil.rmtree(self.home / ".d")
        self.write("dot_d/e/new", "n\n")
        self.write("dot_a", "two\n")
        self.commit("deep new file and another change")
        r = self.update("--take-source", ".d/a")  # its parent .d is held and not taken
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual(self.read(".a"), "two\n")  # the rest still applied, nothing exited 1
        self.assertIn("~/.d/a", r.stdout)
        self.assertIn("its directory ~/.d is held too, so take that as well in the same run", r.stdout)
        self.assertFalse((self.home / ".d").exists())
        r = self.update("--take-source", ".d")  # .d/e is held and not taken: .d/e/new must keep waiting
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertTrue((self.home / ".d").is_dir())
        self.assertFalse((self.home / ".d/e/new").exists())
        r = self.update("--take-source", ".d/a", "--take-source", ".d/e", "--take-source", ".d/e/g")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.read(".d/a"), self.read(".d/e/g"), self.read(".d/e/new")), ("a\n", "g\n", "n\n"))

    def test_script_output_that_is_not_utf8_does_not_crash_the_report(self):
        # round 6 f1: the merged --debug log was decoded strictly, so one stray byte ended the run in a traceback.
        self.write("run_onchange_after_20_latin.sh", "#!/bin/sh\nprintf 'caf\\351 ERROR \\377\\n'\nexit 1\n")
        self.write("run_onchange_after_10_ok.sh", "#!/bin/sh\nprintf 'caf\\351\\n'\nexit 0\n")
        self.commit("scripts that print latin-1 bytes")
        r = self.update()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("script 10_ok.sh   exit 0", r.stdout)
        self.assertIn("script 20_latin.sh   exit 1", r.stdout)


if __name__ == "__main__":
    unittest.main()
