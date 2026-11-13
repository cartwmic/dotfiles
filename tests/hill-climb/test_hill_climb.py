# Vendored from https://github.com/Bil0000/Hill-Climb, tests/test_hill_climb.py at commit
# 84b95909383379d4a84ad02ecadf928aba6b3b9b (MIT, Copyright (c) 2026 Bil0000).
# Edits: the scripts are loaded from this repo's canonical skill bundle under their chezmoi source
# names (executable_climb.py, executable_judge.py), and the argv[1] root override is gone because
# it breaks "python3 -m unittest discover". Nothing else changed.
import fcntl
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/canonical/skills/hill-climb/scripts"
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("climb", SCRIPTS / "executable_climb.py")
climb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(climb)
spec = importlib.util.spec_from_file_location("judge", SCRIPTS / "executable_judge.py")
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


def git(*args):
    subprocess.run(["git", *args], check=True, capture_output=True)


class ClimbTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name) / "repo"
        self.repo.mkdir()
        environment = mock.patch.dict(os.environ, {"HILL_CLIMB_HOME": temporary.name})
        environment.start()
        self.addCleanup(environment.stop)
        previous = Path.cwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, previous)
        git("init", "-q", "-b", "main")
        git("config", "user.email", "test@example.com")
        git("config", "user.name", "Test")
        Path("value.txt").write_text("3\n")
        Path("check.sh").write_text("echo noise 99\ncat value.txt\n")
        git("add", ".")
        git("commit", "-q", "-m", "start")

    def run_climb(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = climb.main(list(args))
        return code, out.getvalue() + err.getvalue()

    def start(self, *extra):
        code, output = self.run_climb(
            "init", "speed", "--goal", "raise the value", "--check", "sh check.sh",
            "--direction", "max", "--target", "8", "--lock", "check.sh", *extra,
        )
        self.assertEqual(code, 0, output)
        return output

    def card(self):
        return json.loads(Path(".hill-climb/speed/card.json").read_text())

    def test_keeps_gains_and_undoes_losses(self):
        output = self.start()
        self.assertIn("Baseline 3", output)
        self.assertIn("no guard", output)
        self.assertEqual(subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(), "climb/speed")

        Path("value.txt").write_text("5\n")
        code, output = self.run_climb("try", "bump to five")
        self.assertEqual(code, 0, output)
        self.assertIn("kept", output)

        Path("value.txt").write_text("4\n")
        Path("scratch.txt").write_text("leftover\n")
        code, output = self.run_climb("try", "drop to four")
        self.assertIn("undone", output)
        self.assertEqual(Path("value.txt").read_text(), "5\n")
        self.assertFalse(Path("scratch.txt").exists())

        Path("value.txt").write_text("9\n")
        code, output = self.run_climb("try", "jump to nine")
        self.assertIn("BAR REACHED", output)
        self.assertIn("The card says: stop", output)
        self.assertEqual(self.card()["best"]["score"], 9)
        log = subprocess.check_output(["git", "log", "--format=%s"], text=True).splitlines()
        self.assertEqual(log[:2], ["climb(speed): step 3 jump to nine", "climb(speed): step 1 bump to five"])

        code, output = self.run_climb("status")
        self.assertIn("Score 3 -> 9", output)
        self.assertIn("drop to four", output)

    def test_guard_failure_undoes_a_gain(self):
        self.assertNotIn("no guard", self.start("--guard", "grep -qv 7 value.txt"))
        Path("value.txt").write_text("7\n")
        code, output = self.run_climb("try", "seven breaks the guard")
        self.assertIn("guard failed", output)
        self.assertEqual(Path("value.txt").read_text(), "3\n")

    def test_locked_check_refuses_to_score(self):
        self.start()
        Path("check.sh").write_text("echo 100\n")
        code, output = self.run_climb("try", "rewrite the check")
        self.assertEqual(code, 1)
        self.assertIn("Locked files changed", output)

        Path("value.txt").write_text("50\n")
        code, output = self.run_climb("relock", "--why", "sneak a code change in")
        self.assertEqual(code, 1)
        self.assertIn("value.txt", output)

        git("checkout", "value.txt")
        with open(climb.git("rev-parse", "--git-path", "hill-climb.lock"), "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code, output = self.run_climb("relock", "speed", "--why", "an interrupted relock still runs")
            self.assertEqual(code, 1)
            self.assertIn("still running", output)
            self.assertEqual(self.run_climb("status")[0], 0)
        code, output = self.run_climb("relock", "speed", "--why", "the old check read the wrong file")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.card()["best"]["score"], 100)

    def test_check_that_edits_a_locked_file_is_undone(self):
        Path("data.txt").write_text("a\n")
        Path("check.sh").write_text('if [ "$(cat value.txt)" = 5 ]; then echo x >> data.txt; fi\ncat value.txt\n')
        self.start("--lock", "data.txt")
        Path("value.txt").write_text("5\n")
        code, output = self.run_climb("try", "five edits the data")
        self.assertIn("changed a locked file", output)
        self.assertEqual(Path("data.txt").read_text(), "a\n")
        self.assertEqual(self.card()["best"]["score"], 3)
        Path("check.sh").write_text('if [ "$(cat value.txt)" = 5 ]; then rm data.txt; fi\ncat value.txt\n')
        git("commit", "-qam", "check deletes the data")
        self.run_climb("relock", "--why", "deleting check")
        Path("value.txt").write_text("5\n")
        self.assertIn("changed a locked file", self.run_climb("try", "five deletes the data")[1])
        self.assertEqual(Path("data.txt").read_text(), "a\n")

    def test_timed_out_check_cannot_write_after_undo(self):
        Path("check.sh").write_text(
            "if [ -f slow ]; then (sleep 2; echo 9 > value.txt) >/dev/null 2>&1 & exec sleep 9; fi\ncat value.txt\n"
        )
        self.start("--timeout", "1")
        Path("value.txt").write_text("5\n")
        Path("slow").write_text("")
        self.assertIn("timed out", self.run_climb("try", "slow")[1])
        time.sleep(2.5)
        self.assertEqual(Path("value.txt").read_text(), "3\n")

    def test_runs_from_a_subfolder(self):
        Path("sub").mkdir()
        Path("sub/keep.txt").write_text("")
        git("add", ".")
        git("commit", "-qm", "sub")
        os.chdir("sub")
        self.start()
        os.chdir(self.repo)
        Path("value.txt").write_text("1\n")
        self.assertIn("undone", self.run_climb("try", "worse")[1])
        self.assertTrue(Path(".hill-climb/speed/card.json").exists())

    def test_broken_check_is_undone_and_logged(self):
        self.start()
        Path("value.txt").write_text("not a number\n")
        code, output = self.run_climb("try", "garbage")
        self.assertIn("broke", output)
        self.assertEqual(Path("value.txt").read_text(), "3\n")

    def test_init_needs_a_clean_tree_and_a_passing_guard(self):
        Path("value.txt").write_text("4\n")
        code, output = self.run_climb("init", "speed", "--goal", "g", "--check", "sh check.sh", "--direction", "max")
        self.assertEqual(code, 1)
        self.assertIn("value.txt", output)
        git("checkout", "value.txt")
        code, output = self.run_climb(
            "init", "speed", "--goal", "g", "--check", "sh check.sh", "--direction", "max", "--guard", "false",
        )
        self.assertEqual(code, 1)
        self.assertIn("guard already fails", output)
        self.assertEqual(subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(), "main")

    def test_new_check_files_are_committed_on_the_climb_branch(self):
        Path("bench").mkdir()
        Path("bench/check.sh").write_text("cat value.txt\n")
        code, output = self.run_climb(
            "init", "speed", "--goal", "g", "--check", "sh bench/check.sh", "--direction", "min",
            "--target", "3x", "--lock", "bench/",
        )
        self.assertEqual(code, 0, output)
        self.assertAlmostEqual(self.card()["target"], 1)
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s"], text=True).strip(), "climb(speed): add the check")
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s", "main"], text=True).strip(), "start")

    def test_raise_needs_the_current_bar(self):
        self.start()
        code, output = self.run_climb("raise", "20", "--why", "too early")
        self.assertEqual(code, 1)
        Path("value.txt").write_text("9\n")
        self.run_climb("try", "nine")
        code, output = self.run_climb("raise", "2x", "--why", "double it")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.card()["target"], 18)

    def test_noisy_baseline_warns(self):
        Path("check.sh").write_text("python3 -c 'import random; print(random.random())'\n")
        git("commit", "-qam", "noisy")
        output = self.start("--runs", "5")
        self.assertIn("moved", output)

    def test_percent_min_gain_scales_with_the_score(self):
        Path("value.txt").write_text("100\n")
        git("commit", "-qam", "hundred")
        self.start("--min-gain", "5%")
        Path("value.txt").write_text("104\n")
        self.assertIn("undone", self.run_climb("try", "four percent")[1])
        Path("value.txt").write_text("106\n")
        self.assertIn("kept", self.run_climb("try", "six percent")[1])

    def test_reviews_quiet_the_plateau_then_call_it_stuck(self):
        self.start()
        for step in range(5):
            Path("value.txt").write_text("1\n")
            self.run_climb("try", f"worse {step}")
        self.assertIn("PLATEAU", self.run_climb("status")[1])
        self.run_climb("review", "check is fine, out of ideas")
        self.assertNotIn("PLATEAU", self.run_climb("status")[1])
        for step in range(5):
            Path("value.txt").write_text("1\n")
            self.run_climb("try", f"still worse {step}")
        self.run_climb("review", "nothing new")
        self.assertIn("STUCK", self.run_climb("status")[1])

    def test_drop_returns_to_base_with_the_check_files(self):
        Path("bench").mkdir()
        Path("bench/check.sh").write_text("cat value.txt\n")
        self.run_climb("init", "speed", "--goal", "g", "--check", "sh bench/check.sh", "--direction", "max", "--lock", "bench")
        code, output = self.run_climb("drop")
        self.assertEqual(code, 0, output)
        self.assertEqual(subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(), "main")
        self.assertEqual(Path("bench/check.sh").read_text(), "cat value.txt\n")
        self.assertFalse(Path(".hill-climb/speed/card.json").exists())
        code, output = self.run_climb("init", "speed", "--goal", "g", "--check", "sh bench/check.sh", "--direction", "max", "--lock", "bench")
        self.assertEqual(code, 0, output)

    def test_kit_is_saved_and_reused_in_another_repo(self):
        Path("bench").mkdir()
        Path("bench/check.sh").write_text("cat value.txt\n")
        git("add", "bench")
        git("commit", "-qm", "bench")
        code, output = self.run_climb(
            "init", "speed", "--goal", "raise it", "--check", "sh bench/check.sh", "--direction", "max",
            "--target", "2x", "--guard", "true", "--lock", "bench",
        )
        self.assertEqual(code, 0, output)
        self.assertIn("Saved kit", output)
        Path(".hill-climb/speed/notes.md").write_text("cache the parse\n")
        self.run_climb("save")

        other = self.repo.parent / "other"
        other.mkdir()
        os.chdir(other)
        git("init", "-q", "-b", "main")
        self.assertIn("speed", self.run_climb("kits", "raise")[1])
        code, output = self.run_climb("reuse", "speed")
        self.assertEqual(code, 0, output)
        self.assertEqual(Path("bench/check.sh").read_text(), "cat value.txt\n")
        self.assertEqual(Path(".hill-climb/speed/notes.md").read_text(), "cache the parse\n")
        self.assertIn("--target 2x", output)
        self.assertIn("--guard true", output)
        self.assertNotIn("value.txt", [p.name for p in Path(".").iterdir()])

    def test_reuse_refuses_unsafe_kit_paths(self):
        folder = Path(os.environ["HILL_CLIMB_HOME"]) / "kits" / "x"
        folder.mkdir(parents=True)
        with tarfile.open(folder / "evil.tar.gz", "w:gz") as tar:
            for name, data in (("kit.json", b"{}"), ("files/../../escape.txt", b"x")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        code, output = self.run_climb("reuse", "x/evil")
        self.assertEqual(code, 1)
        self.assertIn("unsafe", output)

        outside = self.repo.parent / "outside"
        outside.mkdir()
        Path("linked").symlink_to(outside)
        with tarfile.open(folder / "link.tar.gz", "w:gz") as tar:
            for name, data in (("kit.json", b"{}"), ("files/linked/new.txt", b"x")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        code, output = self.run_climb("reuse", "x/link")
        self.assertEqual(code, 1)
        self.assertIn("symlink", output)
        self.assertFalse((outside / "new.txt").exists())

    def test_fix_keeps_an_equal_score_but_not_a_worse_one(self):
        self.start()
        Path("fix.txt").write_text("repair\n")
        self.assertIn("undone", self.run_climb("try", "same score")[1])
        Path("fix.txt").write_text("repair\n")
        self.assertIn("kept", self.run_climb("try", "repair", "--fix")[1])
        Path("value.txt").write_text("2\n")
        self.assertIn("undone", self.run_climb("try", "worse repair", "--fix")[1])

    def test_fix_rejects_a_small_loss_inside_the_min_gain(self):
        Path("value.txt").write_text("100\n")
        git("commit", "-qam", "hundred")
        self.start("--min-gain", "5%")
        Path("value.txt").write_text("96\n")
        self.assertIn("undone", self.run_climb("try", "small loss", "--fix")[1])
        self.assertEqual(self.card()["best"]["score"], 100)

    def test_big_files_are_never_committed(self):
        self.start()
        Path("value.txt").write_text("9\n")
        with mock.patch.object(climb, "COMMIT_LIMIT", 100), mock.patch.object(climb, "STATE_WARN", 100):
            Path("dump.bin").write_bytes(b"x" * 200)
            code, output = self.run_climb("try", "nine with a dump")
            self.assertIn("over 0 MB: dump.bin", output)
            self.assertFalse(Path("dump.bin").exists())
            self.assertEqual(Path("value.txt").read_text(), "3\n")
            Path(".hill-climb/speed/data").mkdir()
            Path(".hill-climb/speed/data/seed.db").write_bytes(b"x" * 200)
            self.assertIn("STORAGE", self.run_climb("status")[1])

    def test_init_refuses_a_big_file_the_agent_wrote(self):
        Path("bench").mkdir()
        Path("bench/check.sh").write_text("cat value.txt\n")
        Path("bench/dump.bin").write_bytes(b"x" * 200)
        with mock.patch.object(climb, "COMMIT_LIMIT", 100):
            code, output = self.run_climb("init", "speed", "--goal", "g", "--check", "sh bench/check.sh",
                                          "--direction", "max", "--lock", "bench")
        self.assertEqual(code, 1)
        self.assertIn("dump.bin", output)
        self.assertEqual(subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(), "main")

    def test_check_output_is_never_committed(self):
        Path("check.sh").write_text("head -c 200 /dev/zero > dump.bin\necho run > report.txt\ncat value.txt\n")
        git("commit", "-qam", "check that writes files")
        with mock.patch.object(climb, "COMMIT_LIMIT", 100):
            output = self.start()
            self.assertIn("Not committed", output)
            Path("value.txt").write_text("5\n")
            code, output = self.run_climb("try", "bump to five")
        self.assertIn("kept", output)
        self.assertIn("dump.bin, report.txt", output)
        committed = subprocess.check_output(["git", "log", "--format=", "--name-only", "main..HEAD"], text=True).split()
        self.assertEqual(committed, ["value.txt"])
        self.assertFalse(Path("dump.bin").exists())
        self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], text=True), "")

    def test_guard_that_rewrites_code_is_refused(self):
        code, output = self.run_climb("init", "speed", "--goal", "g", "--check", "sh check.sh", "--direction", "max",
                                      "--lock", "check.sh", "--guard", "echo 0 > value.txt")
        self.assertEqual(code, 1)
        self.assertIn("changed value.txt", output)
        git("checkout", "value.txt")
        self.start("--guard", 'if [ "$(cat value.txt)" = 5 ]; then echo 6 > value.txt; fi')
        Path("value.txt").write_text("5\n")
        code, output = self.run_climb("try", "five, which the guard rewrites")
        self.assertIn("broke", output)
        self.assertIn("changed value.txt", output)
        self.assertEqual(Path("value.txt").read_text(), "3\n")
        self.assertEqual(self.card()["best"]["score"], 3)

    def test_scoring_leaves_the_real_index_alone(self):
        self.start("--guard", "git diff --quiet")
        Path("value.txt").write_text("5\n")
        code, output = self.run_climb("try", "an unstaged edit the guard can see")
        self.assertIn("guard failed: git diff --quiet", output)
        self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], text=True), "")

    def test_paired_check_that_rewrites_code_is_refused(self):
        Path("check.sh").write_text('if [ "$(cat value.txt)" = 5 ]; then echo 9 > value.txt; fi\ncat value.txt\n')
        git("commit", "-qam", "rewriting check")
        self.start("--paired", "--runs", "2", "--guard", "git diff --cached --quiet")
        Path("value.txt").write_text("5\n")
        code, output = self.run_climb("try", "five, which the check rewrites")
        self.assertIn("broke", output)
        self.assertIn("changed value.txt", output)
        self.assertEqual(self.card()["best"]["score"], 3)
        Path("value.txt").write_text("4\n")
        code, output = self.run_climb("try", "four, unstaged for the guard")
        self.assertIn("kept", output)
        self.assertEqual(subprocess.check_output(["git", "show", "HEAD:value.txt"], text=True), "4\n")

    def test_check_that_drops_an_ignore_rule_keeps_ignored_files(self):
        Path(".gitignore").write_text("secret.txt\n")
        Path("check.sh").write_text('[ "$(cat value.txt)" = 5 ] && : > .gitignore\ncat value.txt\n')
        git("add", ".")
        git("commit", "-qm", "ignore secret")
        self.start()
        Path("secret.txt").write_text("mine\n")
        Path("value.txt").write_text("5\n")
        self.assertIn("broke", self.run_climb("try", "five, which empties the ignore file")[1])
        self.assertEqual(Path("secret.txt").read_text(), "mine\n")

    def test_paired_check_that_rewrites_the_old_code_is_refused(self):
        Path(".gitignore").write_text("armed\n")
        Path("check.sh").write_text('[ -f armed ] && [ "$(cat value.txt)" = 3 ] && echo 1 > value.txt\ncat value.txt\n')
        git("add", ".")
        git("commit", "-qm", "check that rewrites the old side")
        self.start("--paired")
        Path("armed").write_text("")
        Path("value.txt").write_text("2\n")
        output = self.run_climb("try", "two, worse than three")[1]
        self.assertIn("broke", output)
        self.assertEqual(self.card()["best"]["score"], 3)

    def test_paired_check_cannot_hide_an_edit_by_staging_it(self):
        Path("check.sh").write_text('if [ "$(cat value.txt)" = 5 ]; then echo 9 > value.txt; git add value.txt; fi\ncat value.txt\n')
        git("commit", "-qam", "check that stages its edit")
        self.start("--paired")
        Path("value.txt").write_text("5\n")
        self.assertIn("broke", self.run_climb("try", "five, which the check rewrites and stages")[1])
        self.assertEqual(self.card()["best"]["score"], 3)

    def test_paired_check_cannot_hide_an_edit_by_committing_it(self):
        Path(".gitignore").write_text("armed\n")
        Path("check.sh").write_text('[ -f armed ] && [ "$(cat value.txt)" = 3 ] && echo 1 > value.txt && git commit -qam hide\ncat value.txt\n')
        git("add", ".")
        git("commit", "-qm", "check that commits on the old side")
        self.start("--paired")
        Path("armed").write_text("")
        Path("value.txt").write_text("2\n")
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True)
        self.assertIn("broke", self.run_climb("try", "two, worse than three")[1])
        self.assertEqual(self.card()["best"]["score"], 3)
        self.assertEqual(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True), head)

    def test_paired_check_that_commits_on_another_branch_and_fails_keeps_that_branch(self):
        Path("check.sh").write_text('[ "$(cat value.txt)" = 2 ] && git switch -qc personal && git commit -qam mine && exit 1\ncat value.txt\n')
        git("commit", "-qam", "check that leaves the climb branch")
        self.start("--paired")
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True)
        Path("value.txt").write_text("2\n")
        self.assertIn("broke", self.run_climb("try", "two")[1])
        self.assertEqual(subprocess.check_output(["git", "branch", "--show-current"], text=True).strip(), "climb/speed")
        self.assertEqual(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True), head)
        self.assertEqual(subprocess.check_output(["git", "log", "-1", "--format=%s", "personal"], text=True).strip(), "mine")

    def test_guard_that_commits_is_undone(self):
        self.start("--guard", 'git commit -qam guard || true')
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True)
        Path("value.txt").write_text("5\n")
        self.assertIn("a guard moved HEAD", self.run_climb("try", "five")[1])
        self.assertEqual(subprocess.check_output(["git", "rev-parse", "HEAD"], text=True), head)
        self.assertEqual(Path("value.txt").read_text(), "3\n")

    def test_paired_check_output_in_a_locked_folder_does_not_trip_the_lock(self):
        Path("bench").mkdir()
        Path("bench/check.sh").write_text("date +%s%N > bench/last-run.txt\ncat value.txt\n")
        code, output = self.run_climb("init", "speed", "--goal", "g", "--check", "sh bench/check.sh",
                                      "--direction", "max", "--lock", "bench", "--paired")
        self.assertEqual(code, 0, output)
        Path("value.txt").write_text("5\n")
        self.assertIn("kept", self.run_climb("try", "bump to five")[1])

    def test_force_added_ignored_file_is_committed(self):
        Path(".gitignore").write_text("gen.txt\n")
        Path("check.sh").write_text("cat gen.txt 2>/dev/null || cat value.txt\n")
        git("add", ".")
        git("commit", "-qm", "ignore gen")
        self.start()
        Path("gen.txt").write_text("6\n")
        git("add", "-f", "gen.txt")
        code, output = self.run_climb("try", "force-add a generated six")
        self.assertIn("kept", output)
        self.assertEqual(subprocess.check_output(["git", "show", "HEAD:gen.txt"], text=True), "6\n")

    def test_check_output_in_a_locked_folder_does_not_trip_the_lock(self):
        Path("bench").mkdir()
        Path("bench/check.sh").write_text("date +%s%N > bench/last-run.txt\ncat value.txt\n")
        code, output = self.run_climb("init", "speed", "--goal", "g", "--check", "sh bench/check.sh",
                                      "--direction", "max", "--lock", "bench")
        self.assertEqual(code, 0, output)
        Path("value.txt").write_text("5\n")
        code, output = self.run_climb("try", "bump to five")
        self.assertIn("kept", output)
        Path("bench/check.sh").write_text("date +%s%N > bench/last-run.txt\necho 1 > relock-report.txt\ncat value.txt\n")
        code, output = self.run_climb("relock", "--why", "report too")
        self.assertEqual(code, 0, output)
        self.assertFalse(Path("relock-report.txt").exists())
        Path("value.txt").write_text("7\n")
        self.assertIn("kept", self.run_climb("try", "bump to seven")[1])

    def test_budget_stops_the_climb(self):
        self.start("--max-steps", "1")
        Path("value.txt").write_text("2\n")
        self.run_climb("try", "worse")
        Path("value.txt").write_text("5\n")
        code, output = self.run_climb("try", "over budget")
        self.assertEqual(code, 1)
        self.assertIn("Budget used", output)
        self.assertIn("Budget now 3 steps", self.run_climb("budget", "speed", "--steps", "2")[1])
        self.assertIn("kept", self.run_climb("try", "two more steps")[1])
        Path("value.txt").write_text("6\n")
        self.run_climb("try", "last step inside the limit")
        Path("value.txt").write_text("7\n")
        code, output = self.run_climb("try", "past the limit")
        self.assertIn("still gaining", output)
        self.assertIn("kept", output)
        for step in range(5):
            Path("note.txt").write_text(f"{step}\n")
            self.run_climb("try", f"flat repair {step}", "--fix")
        Path("value.txt").write_text("8\n")
        code, output = self.run_climb("try", "flat repairs are not gains")
        self.assertEqual(code, 1, output)

    def test_hard_budget_stops_even_while_gaining(self):
        self.start("--max-steps", "1", "--hard")
        Path("value.txt").write_text("5\n")
        self.run_climb("try", "gain")
        Path("value.txt").write_text("6\n")
        code, output = self.run_climb("try", "over the hard limit")
        self.assertEqual(code, 1)
        self.assertIn("Budget used: 1 of 1 steps.", output)

    def test_hours_budget_stops_the_climb(self):
        self.start("--max-hours", "1")
        card = self.card()
        card["started"] -= 7200
        Path(".hill-climb/speed/card.json").write_text(json.dumps(card))
        Path("value.txt").write_text("5\n")
        code, output = self.run_climb("try", "too late")
        self.assertEqual(code, 1)
        self.assertIn("2.0 of 1 hours", output)
        self.assertIn("Budget now 3 hours", self.run_climb("budget", "--hours", "1")[1])
        self.assertIn("kept", self.run_climb("try", "more time")[1])
        card = self.card()
        card["started"] -= 7200
        Path(".hill-climb/speed/card.json").write_text(json.dumps(card))
        log = Path(".hill-climb/speed/log.jsonl")
        old = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 7200))
        log.write_text("".join(json.dumps({**json.loads(line), "time": old}) + "\n" for line in log.read_text().splitlines()))
        Path("value.txt").write_text("6\n")
        code, output = self.run_climb("try", "no gain in the last hour")
        self.assertEqual(code, 1)
        self.assertIn("no gain in the last hour", output)
        self.assertIn("Budget now no limit", self.run_climb("budget", "--off")[1])
        Path("value.txt").write_text("6\n")
        self.assertIn("kept", self.run_climb("try", "no limit")[1])
        self.assertIn("min a step", self.run_climb("status")[1])

    def test_paired_scoring_sees_a_gain_under_rising_load(self):
        Path("check.sh").write_text(
            "n=$(( $(cat .hill-climb/runs 2>/dev/null || echo 0) + 1 )); echo $n > .hill-climb/runs\n"
            "echo $(( $(cat value.txt) + n * 10 ))\n"
        )
        Path("extra.txt").write_text("kept\n")
        git("add", ".")
        git("commit", "-qm", "load grows every run")
        code, output = self.run_climb(
            "init", "speed", "--goal", "lower it", "--check", "sh check.sh", "--direction", "min",
            "--target", "2x", "--lock", "check.sh", "--runs", "3", "--paired",
        )
        self.assertEqual(code, 0, output)
        Path("README").write_text("same\n")
        git("add", "README")
        self.assertIn("undone", self.run_climb("try", "no real change")[1])

        Path("value.txt").write_text("2\n")
        Path("extra.txt").unlink()
        Path("new.txt").write_text("added\n")
        code, output = self.run_climb("try", "one less")
        self.assertIn("kept", output)
        self.assertNotIn("BAR REACHED", output)
        self.assertEqual(Path("value.txt").read_text(), "2\n")
        self.assertFalse(Path(".hill-climb/speed/pending-tree").exists())
        self.assertFalse(Path("extra.txt").exists())
        self.assertEqual(subprocess.check_output(["git", "show", "HEAD:new.txt"], text=True), "added\n")

        Path("value.txt").write_text("4\n")
        self.assertIn("undone", self.run_climb("try", "one more")[1])
        self.assertEqual(Path("value.txt").read_text(), "2\n")
        self.assertIn("--paired", self.run_climb("reuse", "speed")[1])

    def test_paired_step_cannot_slow_the_old_code_with_leftover_files(self):
        Path("check.sh").write_text(
            "[ -f hook.sh ] && sh hook.sh pre\ns=$(cat value.txt); [ -f poison ] && s=$((s + 100))\n"
            "echo $s\n[ -f hook.sh ] && sh hook.sh post\ntrue\n"
        )
        git("commit", "-qam", "hookable check")
        self.start("--paired", "--direction", "min")
        Path("hook.sh").write_text('if [ "$1" = pre ]; then rm -f poison; else touch poison; fi\n')
        self.assertIn("undone", self.run_climb("try", "poison the old side")[1])
        self.assertFalse(Path("poison").exists())

    def test_paired_check_that_edits_a_locked_file_is_undone(self):
        Path("data.txt").write_text("a\n")
        Path("check.sh").write_text('if [ "$(cat value.txt)" = 2 ]; then echo x >> data.txt; fi\ncat value.txt\n')
        git("add", ".")
        git("commit", "-qm", "data")
        self.start("--lock", "data.txt", "--paired", "--direction", "min")
        Path("value.txt").write_text("2\n")
        self.assertIn("changed a locked file", self.run_climb("try", "two edits the data")[1])
        self.assertEqual(Path("data.txt").read_text(), "a\n")
        self.assertEqual(Path("value.txt").read_text(), "3\n")

    def test_failing_count_climbs_and_grows_with_new_findings(self):
        Path("tests").mkdir()
        Path("tests/run.sh").write_text(
            "fail=0\nfor t in tests/t_*; do sh $t >/dev/null || { echo \"FAIL $t\"; fail=$((fail+1)); }; done\n"
            "echo \"\\033[31mfailures=$fail, errors=1\\033[0m\"\n[ $fail = 0 ]\n"
        )
        Path("tests/t_a").write_text("grep -q a code.txt\n")
        Path("tests/t_b").write_text("grep -q b code.txt\n")
        Path("code.txt").write_text("\n")
        Path(".gitignore").write_text("*.pyc\nconftest*\n")
        Path("tests/cache.pyc").write_text("written by the first run\n")
        git("add", ".")
        git("commit", "-qm", "tests")
        code, output = self.run_climb(
            "init", "audit", "--goal", "every finding fixed", "--check", "sh tests/run.sh",
            "--score", r"failures=(\d+)|errors=(\d+)", "--direction", "min", "--target", "1", "--lock", "tests",
            "--holdout", "echo failures=9; echo 42",
        )
        self.assertEqual(code, 0, output)
        self.assertIn("Baseline 3", output)
        self.assertIn("Holdout baseline 42", output)
        self.assertIn("no guard", output)
        Path("tests/cache.pyc").write_text("written by the next run\n")
        Path("tests/conftest.sh").write_text("skip every test\n")
        self.assertIn("Locked files changed", self.run_climb("try", "hide a new ignored file in the tests")[1])
        Path("tests/conftest.sh").unlink()
        Path("code.txt").write_text("a\n")
        self.assertIn("kept    2", self.run_climb("try", "fix a")[1])
        self.assertIn("FAIL tests/t_b", Path(".hill-climb/audit/best.txt").read_text())
        self.assertIn("FAIL tests/t_b", Path(".hill-climb/audit/last.txt").read_text())
        Path("tests/t_c").write_text("grep -q c code.txt\n")
        code, output = self.run_climb("relock", "--why", "found c")
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(Path(".hill-climb/audit/card.json").read_text())["best"]["score"], 3)
        Path("code.txt").write_text("a\nb\nc\n")
        self.assertIn("BAR REACHED", self.run_climb("try", "fix b and c")[1])
        Path(".hill-climb/audit/notes.md").write_text("- [x] a\n- [ ] d: needs the spec\n")
        self.assertIn("d: needs the spec", self.run_climb("status")[1])

    def test_one_climb_edits_and_undoes_several_repos(self):
        other = self.repo.parent / "web"
        other.mkdir()
        git("-C", str(other), "init", "-q", "-b", "main")
        git("-C", str(other), "config", "user.email", "test@example.com")
        git("-C", str(other), "config", "user.name", "Test")
        (other / "value.txt").write_text("1\n")
        (other / "check.sh").write_text("cat value.txt\n")
        git("-C", str(other), "add", ".")
        git("-C", str(other), "commit", "-qm", "start")
        code, output = self.run_climb(
            "init", "speed", "--goal", "raise both", "--check", "sh check.sh", "--check", f"sh -c 'cd {other} && sh check.sh'",
            "--direction", "max", "--repo", str(other), "--lock", "check.sh", "--lock", "../web/check.sh",
        )
        self.assertEqual(code, 0, output)
        self.assertIn("Baseline 4", output)
        self.assertIn("in 2 repos", output)
        branch = subprocess.check_output(["git", "-C", str(other), "branch", "--show-current"], text=True).strip()
        self.assertEqual(branch, "climb/speed")

        (other / "value.txt").write_text("0\n")
        Path("value.txt").write_text("9\n")
        Path("scratch.txt").write_text("x\n")
        (other / "scratch.txt").write_text("x\n")
        os.chdir(other)
        self.assertIn("kept", self.run_climb("try", "both repos")[1])
        os.chdir(self.repo)
        self.assertEqual(subprocess.check_output(["git", "-C", str(other), "show", "HEAD:value.txt"], text=True), "0\n")

        (other / "value.txt").write_text("1\n")
        Path("value.txt").write_text("10\n")
        git("-C", str(other), "config", "commit.gpgsign", "true")
        git("-C", str(other), "config", "gpg.program", "false")
        code, output = self.run_climb("try", "web cannot commit")
        self.assertEqual(code, 1, output)
        main_head = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        self.assertEqual(main_head, self.card()["best"]["commit"])
        self.assertEqual(Path("value.txt").read_text(), "10\n")
        git("-C", str(other), "config", "--unset", "commit.gpgsign")
        git("checkout", "value.txt")
        git("-C", str(other), "checkout", "value.txt")

        (other / "value.txt").write_text("-5\n")
        (other / "junk.txt").write_text("x\n")
        self.assertIn("undone", self.run_climb("try", "worse in web")[1])
        self.assertEqual((other / "value.txt").read_text(), "0\n")
        self.assertFalse((other / "junk.txt").exists())

        (other / "check.sh").write_text("echo 100\n")
        (other / "value.txt").write_text("5\n")
        self.assertIn("Locked files changed", self.run_climb("try", "edit the web check")[1])
        git("-C", str(other), "checkout", "check.sh", "value.txt")
        code, output = self.run_climb("drop")
        self.assertEqual(code, 0, output)
        branch = subprocess.check_output(["git", "-C", str(other), "branch", "--show-current"], text=True).strip()
        self.assertEqual(branch, "main")
        self.assertIn("../web/check.sh", output)

    def test_slow_check_warns_at_init(self):
        with mock.patch.object(climb, "measure", return_value=(3, 0, 40)):
            self.assertNotIn("each step will take", self.start())
            git("switch", "-q", "main")
            self.assertIn("each step will take about 3 min", self.run_climb(
                "init", "paired", "--goal", "g", "--check", "sh check.sh", "--direction", "max", "--paired",
            )[1])


class JudgeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        (self.folder / "rubric.md").write_text("Score clarity.\n")
        (self.folder / "work.txt").write_text("draft\n")

    def panel(self, replies):
        judges = {
            name: (lambda reply: lambda *args: SimpleNamespace(returncode=0, stdout=reply, stderr=""))(reply)
            for name, reply in replies.items()
        }
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(judge.JUDGES, judges, clear=True), mock.patch.object(judge.shutil, "which", return_value="x"):
            with redirect_stdout(out), redirect_stderr(err):
                try:
                    judge.main([
                        "--rubric", str(self.folder / "rubric.md"), "--candidate", str(self.folder / "work.txt"),
                        "--panel", ",".join(replies), "--notes", str(self.folder / "notes.md"),
                    ])
                except SystemExit as error:
                    return None, str(error)
        return out.getvalue().strip().splitlines()[-1], (self.folder / "notes.md").read_text()

    def test_median_score_and_notes(self):
        score, notes = self.panel({
            "a": 'thinking... {"score": 4, "worst": "vague", "fix": "name it"}',
            "b": '{"score": 8, "worst": "long", "fix": "cut"}',
            "c": '{"score": 7, "worst": "dense", "fix": "split"}',
        })
        self.assertEqual(score, "7")
        self.assertIn("a: 4/10. Worst: vague Fix: name it", notes)

    def test_too_few_answers_give_no_score(self):
        score, error = self.panel({"a": '{"score": 9}', "b": '{"score": 1e9}', "c": "no json"})
        self.assertIsNone(score)
        self.assertIn("Only 1 of 3", error)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]])
