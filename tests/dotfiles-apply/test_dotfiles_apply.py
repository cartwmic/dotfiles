"""dotfiles-apply (dot_local/bin/executable_dotfiles-apply): dotfiles are applied only from a commit the gate approves.

Real chezmoi and real git against a scratch source checkout (with a bare repository as its origin) and a scratch HOME, no TTY. The gate is a stub
`ci-main-status` that answers the question `--tip dotfiles --contains SHA` the way the real one does: yes (exit 0, the line with the full commit) when the
commit it was told is green contains SHA, no (exit 1) otherwise, so a history can be written down commit by commit. The past case is in
`test_the_bad_day`: a change is merged, the only green commit does not contain it, and nothing may be applied until a later green commit does.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_dotfiles-apply"
UPDATE = ROOT / "dot_local/bin/executable_dotfiles-update"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]

GATE = """#!/bin/sh
# Stub of `ci-main-status --tip dotfiles --contains SHA`: GATE_GREEN holds the one green main commit; GATE_REMOTE is the repository to ask git about.
echo "$*" >> "$GATE_LOG"
[ "$1" = "--tip" ] && [ "$2" = "dotfiles" ] && [ "$3" = "--contains" ] || { echo "usage: ci-main-status --tip REPO --contains SHA" >&2; exit 2; }
full=$(git -C "$GATE_REMOTE" rev-parse --verify --quiet "$4^{commit}") || { echo "dotfiles: ERROR  $4 is not a commit of cartwmic/dotfiles"; exit 2; }
green=$(cat "$GATE_GREEN" 2>/dev/null)
[ -n "$green" ] || { echo "dotfiles: NO  no main commit has a finished green run, so none contains $(echo "$4" | cut -c1-7)"; exit 1; }
if git -C "$GATE_REMOTE" merge-base --is-ancestor "$full" "$green"; then
  echo "dotfiles: GREEN  run 777 passed on $(echo "$green" | cut -c1-7), which contains $(echo "$full" | cut -c1-7); commit $green"
  exit 0
fi
echo "dotfiles: NO  main's newest green commit $(echo "$green" | cut -c1-7) (run 777) does not contain $(echo "$4" | cut -c1-7); a run is going"
exit 1
"""

# A chezmoi that behaves as the real one except where a test says so: SHIM_NOOP_APPLY=1 makes `apply` do nothing and succeed (a half-landed apply),
# SHIM_STOP_ON_DIFF=FILE creates FILE when `diff` runs (a lead puts a stop file down while the diff is shown).
CHEZMOI_SHIM = """#!/bin/sh
for word in "$@"; do
  case "$word" in apply|diff) sub="$word"; break;; esac
done
if [ "$sub" = apply ] && [ -n "${SHIM_NOOP_APPLY:-}" ]; then exit 0; fi
if [ "$sub" = diff ] && [ -n "${SHIM_STOP_ON_DIFF:-}" ]; then : > "$SHIM_STOP_ON_DIFF"; fi
exec "$CHEZMOI_REAL" "$@"
"""


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("git"), "chezmoi and git needed")
class DotfilesApply(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bare = self.tmp / "remote.git"
        self.src = self.tmp / "src"  # the machine's chezmoi source checkout: it only moves when the command moves it
        self.author = self.tmp / "author"  # where changes are made and pushed to main, as other people's merges are
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.green = self.tmp / "green"
        self.gate_log = self.tmp / "gate.log"
        self.state = self.home / ".local/state/dotfiles-apply"
        self.install("ci-main-status", GATE)
        self.install("chezmoi", CHEZMOI_SHIM)
        self.install("dotfiles-update", '#!/bin/sh\nexec python3 "%s" "$@"\n' % UPDATE)  # git keeps dotfiles-update at mode 644: run it by its interpreter
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.bare), str(self.author)], check=True, capture_output=True)
        self.write("dot_a", "one\n")
        self.write("dot_b", "one\n")
        self.write("run_onchange_after_10_mark.sh", "#!/bin/sh\necho ran >> \"$HOME/script-ran\"\n# v1\n")
        self.write("run_after_20_always.sh", "#!/bin/sh\n: always\n")
        self.base = self.commit("init")
        subprocess.run(["git", "clone", "-q", str(self.bare), str(self.src)], check=True, capture_output=True)
        self.cfg = self.tmp / "chezmoi.yaml"
        self.config(profile="personal")
        self.env = dict(os.environ, HOME=str(self.home), PATH="%s:%s" % (self.bin, os.environ["PATH"]), CHEZMOI_REAL=shutil.which("chezmoi"),
                        GATE_GREEN=str(self.green), GATE_LOG=str(self.gate_log), GATE_REMOTE=str(self.bare), XDG_STATE_HOME=str(self.home / ".local/state"),
                        DOTFILES_APPLY_CHEZMOI_ARGS="--config %s --config-format yaml --source %s --destination %s" % (self.cfg, self.src, self.home))
        for name in ("T3CODE_THREAD_ID", "CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID"):
            self.env.pop(name, None)
        self.chezmoi("apply")  # first apply: everything clean
        (self.home / "script-ran").unlink()
        self.set_green(self.base)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def install(self, name, text):
        (self.bin / name).write_text(text)
        (self.bin / name).chmod(0o755)

    def config(self, profile="personal", extra=""):
        self.cfg.write_text("sourceDir: %s\ndata:\n  profile: %s\n%s" % (self.src, profile, extra))

    def write(self, name, text):
        (self.author / name).write_text(text)

    def commit(self, message):
        """Commit what was written (in the author's clone) and push it to main; returns the commit."""
        subprocess.run(["git", "-C", str(self.author), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.author), *GIT[1:], "commit", "-qm", message], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.author), "push", "-q", "origin", "HEAD:main"], check=True, capture_output=True)
        return self.rev("HEAD", self.author)

    def rev(self, ref, repo=None):
        return subprocess.run(["git", "-C", str(repo or self.src), "rev-parse", ref], capture_output=True, text=True, check=True).stdout.strip()

    def set_green(self, sha):
        self.green.write_text(sha + "\n")

    def chezmoi(self, *args):
        return subprocess.run(["chezmoi", "--no-tty", *shlex.split(self.env["DOTFILES_APPLY_CHEZMOI_ARGS"]), *args], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, env=self.env, timeout=120)

    def apply(self, *args, **env):
        return subprocess.run([sys.executable, str(SCRIPT), *args], stdin=subprocess.DEVNULL, capture_output=True, text=True, env=dict(self.env, **env), timeout=180)

    def read(self, name):
        return (self.home / name).read_text()

    def log(self):
        path = self.state / "log.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def gate_calls(self):
        return self.gate_log.read_text().splitlines() if self.gate_log.exists() else []

    def checkout(self):
        return self.rev("HEAD")

    # --- the gate decides -------------------------------------------------------------------------------------------------------------------

    def test_the_bad_day(self):
        """A change merged (dot_a), the only green commit is the one before it: nothing is applied and the checkout stays. A later green commit contains it: it applies."""
        self.write("dot_a", "two\n")
        change = self.commit("the change")
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("does not approve", r.stdout)
        self.assertIn("Wait for the main run", r.stdout)
        self.assertEqual(self.read(".a"), "one\n")
        self.assertEqual(self.checkout(), self.base)
        refused = self.log()[-1]
        self.assertEqual((refused["outcome"], refused["exit"], refused["asked"], refused["commit"]), ("untested", 1, change, None))
        self.write("dot_c", "later\n")
        later = self.commit("a later commit")
        self.set_green(later)
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, "other pending: .c came with the later commit\n" + r.stdout + r.stderr)  # the checkout moved to the tested commit
        self.assertEqual(self.checkout(), later)
        self.assertEqual(self.read(".a"), "one\n")
        r = self.apply("--contains", change, ".a", ".c")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.read(".a"), self.read(".c")), ("two\n", "later\n"))
        applied = self.log()[-1]
        self.assertEqual((applied["outcome"], applied["exit"], applied["asked"], applied["commit"], applied["run"]), ("applied", 0, change, later, "run 777"))
        self.assertEqual(sorted(applied["paths"]), ["~/.a", "~/.c"])

    def test_the_checkout_moves_to_the_tested_commit_and_not_to_the_tip(self):
        self.write("dot_a", "two\n")
        change = self.commit("the change")
        self.set_green(change)
        self.write("dot_a", "three\n")
        tip = self.commit("an untested tip")
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.checkout(), change)
        self.assertNotEqual(self.checkout(), tip)
        self.assertEqual(self.read(".a"), "two\n")

    def test_no_sha_asks_for_the_newest_tested_commit_from_the_checkouts_base(self):
        self.write("dot_a", "two\n")
        self.write("dot_b", "two\n")
        tested = self.commit("tested")
        self.set_green(tested)
        self.write("dot_a", "untested\n")
        self.commit("tip")
        r = self.apply()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.gate_calls(), ["--tip dotfiles --contains " + self.base])
        self.assertEqual((self.read(".a"), self.read(".b")), ("two\n", "two\n"))
        self.assertEqual(self.checkout(), tested)

    def test_no_sha_and_nothing_tested_past_the_base_is_nothing_to_do(self):
        r = self.apply()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nothing to do", r.stdout)
        self.assertEqual(self.log()[-1]["outcome"], "nothing-to-do")

    def test_nothing_to_do_names_the_tested_commit_and_the_run_and_logs_them(self):
        """The first real run after a restart's start script has already applied the change: it must still say which tested commit and run it stands on."""
        self.write("dot_a", "two\n")
        change = self.commit("the change")
        self.set_green(change)
        self.assertEqual(self.apply("--contains", change, ".a").returncode, 0)
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nothing to do: tested commit %s (run 777)" % change[:12], r.stdout)
        said = self.log()[-1]
        self.assertEqual((said["outcome"], said["exit"], said["commit"], said["run"], said["asked"]), ("nothing-to-do", 0, change, "run 777", change))

    def test_the_state_of_2026_11_28_11_49z_is_refused(self):
        """Fixture from the sixth start-script apply: the gate said no because main's newest green commit does not contain the change and a run is going."""
        self.install("ci-main-status", "#!/bin/sh\necho \"dotfiles: NO  main's newest green commit 759b526 (run 46133341039) does not contain adfb89a; a run is going\"\nexit 1\n")
        self.write("dot_a", "two\n")
        change = self.commit("pull request 1038")
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("759b526 (run 46133341039) does not contain adfb89a; a run is going", r.stdout)
        self.assertEqual((self.read(".a"), self.checkout()), ("one\n", self.base))
        refused = self.log()[-1]
        self.assertEqual((refused["outcome"], refused["exit"]), ("untested", 1))
        self.assertIn("a run is going", refused["reason"])

    def test_a_gate_that_cannot_be_run_applies_nothing(self):
        self.write("dot_a", "two\n")
        change = self.commit("the change")
        self.set_green(change)
        (self.bin / "ci-main-status").unlink()
        r = self.apply("--contains", change, ".a", PATH="%s:/usr/bin:/bin" % self.bin)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((self.read(".a"), self.checkout()), ("one\n", self.base))
        self.assertEqual(self.log()[-1]["outcome"], "gate-error")

    def test_a_sha_the_gate_does_not_know_is_wrong_usage(self):
        r = self.apply("--contains", "0123456", ".a")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.log()[-1]["outcome"], "gate-error")
        r = self.apply("--contains", "not-a-sha")
        self.assertEqual(r.returncode, 2)
        said = self.log()[-1]
        self.assertEqual((said["outcome"], said["exit"]), ("usage", 2))  # a wrong call leaves its line too

    def test_an_unknown_flag_is_wrong_usage_and_is_logged(self):
        r = self.apply("--nonsense")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual((self.log()[-1]["outcome"], self.log()[-1]["exit"]), ("usage", 2))
        self.assertEqual(self.gate_calls(), [])

    def test_leave_pending_with_the_whole_commit_is_wrong_usage(self):
        r = self.apply("--whole-commit", "--leave-pending", "~/x")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.log()[-1]["outcome"], "usage")

    def test_a_gate_that_could_not_read_main_is_gate_error_and_not_untested(self):
        self.install("ci-main-status", "#!/bin/sh\necho 'dotfiles: ERROR  cannot read main: rate limited'\nexit 1\n")
        r = self.apply("--contains", self.base, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.log()[-1]["outcome"], "gate-error")

    def test_the_log_line_keeps_the_paths_asked_for_and_the_paths_left(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        r = self.apply("--contains", change, ".a", "--leave-pending", "~/10_mark.sh")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)  # untested: nothing tested contains it
        said = self.log()[-1]
        self.assertEqual((said["outcome"], said["requested"], said["left"], said["paths"]), ("untested", [".a"], ["~/10_mark.sh"], []))

    # --- what it applies --------------------------------------------------------------------------------------------------------------------

    def test_named_paths_only_and_it_stops_on_anything_else_pending(self):
        self.write("dot_a", "two\n")
        self.write("dot_b", "two\n")
        change = self.commit("two changes")
        self.set_green(change)
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(str(self.home / ".b"), r.stdout)
        self.assertEqual((self.read(".a"), self.read(".b")), ("one\n", "one\n"))
        self.assertEqual(self.log()[-1]["outcome"], "other-pending")
        r = self.apply("--contains", change, ".a", "--whole-commit")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.read(".a"), self.read(".b")), ("two\n", "two\n"))

    def test_a_named_path_is_applied_as_itself_and_the_diff_is_shown(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        r = self.apply("--contains", change, str(self.home / ".a"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("+two", r.stdout)
        self.assertIn("-one", r.stdout)

    def test_a_named_directory_stands_for_the_pending_files_under_it(self):
        (self.author / "dot_dir").mkdir()
        self.write("dot_dir/one", "new\n")
        self.write("dot_dir/two", "new\n")
        change = self.commit("a directory of files")
        self.set_green(change)
        r = self.apply("--contains", change, ".dir")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.read(".dir/one"), self.read(".dir/two")), ("new\n", "new\n"))
        self.assertEqual(self.log()[-1]["outcome"], "applied")

    def test_a_path_left_pending_is_not_taken_with_the_directory_that_holds_it(self):
        (self.author / "dot_dir").mkdir()
        self.write("dot_dir/one", "new\n")
        self.write("dot_dir/two", "new\n")
        change = self.commit("a directory of files")
        self.set_green(change)
        r = self.apply("--contains", change, ".dir", "--leave-pending", str(self.home / ".dir/two"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read(".dir/one"), "new\n")
        self.assertFalse((self.home / ".dir/two").exists())

    def test_naming_only_current_paths_while_something_else_is_pending_is_not_nothing_to_do(self):
        self.write("dot_b", "two\n")
        change = self.commit("change to b")
        self.set_green(change)
        r = self.apply("--contains", change, ".a")  # .a is current; .b, which the commit changed, is pending and was not named
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(".b", r.stdout)
        self.assertEqual((self.log()[-1]["outcome"], self.read(".b")), ("other-pending", "one\n"))

    def test_a_new_file_in_a_new_directory_brings_its_directory(self):
        (self.author / "dot_dir").mkdir()
        self.write("dot_dir/file", "new\n")
        change = self.commit("new file")
        self.set_green(change)
        r = self.apply("--contains", change, ".dir/file")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read(".dir/file"), "new\n")

    def test_a_named_script_is_run_through_chezmoi_and_recorded(self):
        self.write("run_onchange_after_10_mark.sh", "#!/bin/sh\necho ran >> \"$HOME/script-ran\"\n# v2\n")
        change = self.commit("script change")
        self.set_green(change)
        r = self.apply("--contains", change)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read("script-ran"), "ran\n")
        r = self.apply("--contains", change)
        self.assertIn("nothing to do", r.stdout)  # chezmoi recorded the run: the script is no longer pending
        self.assertEqual(self.read("script-ran"), "ran\n")

    def test_a_script_you_did_not_name_is_other_pending(self):
        self.write("dot_a", "two\n")
        self.write("run_onchange_after_10_mark.sh", "#!/bin/sh\necho ran >> \"$HOME/script-ran\"\n# v2\n")
        change = self.commit("file and script")
        self.set_green(change)
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("10_mark.sh", r.stdout)
        self.assertFalse((self.home / "script-ran").exists())
        script = [line.split()[-1] for line in self.chezmoi("status", "--path-style", "absolute").stdout.splitlines() if "10_mark.sh" in line][0]
        r = self.apply("--contains", change, ".a", script)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.read("script-ran"), "ran\n")

    def test_a_script_left_pending_on_purpose_does_not_stop_the_run_and_is_not_run(self):
        self.write("dot_a", "two\n")
        self.write("dot_b", "two\n")
        self.write("run_onchange_after_10_mark.sh", "#!/bin/sh\necho ran >> \"$HOME/script-ran\"\n# v2\n")
        change = self.commit("two files and a script")
        self.set_green(change)
        r = self.apply("--contains", change, ".a", "--leave-pending", "~/10_mark.sh")
        self.assertEqual(r.returncode, 1, "only what was named as left may stay pending\n" + r.stdout)
        self.assertIn(".b", r.stdout)
        self.assertNotIn("10_mark.sh", r.stdout)
        r = self.apply("--contains", change, ".a", ".b", "--leave-pending", "~/10_mark.sh")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.read(".a"), self.read(".b")), ("two\n", "two\n"))
        self.assertFalse((self.home / "script-ran").exists())
        self.assertEqual(self.log()[-1]["outcome"], "applied")

    def test_a_path_edited_here_is_not_overwritten_and_the_run_fails(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        (self.home / ".a").write_text("mine\n")
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.read(".a"), "mine\n")
        self.assertEqual(self.log()[-1]["outcome"], "failed")

    def test_a_whole_commit_that_holds_a_path_back_exits_1(self):
        self.write("dot_a", "two\n")
        self.write("dot_b", "two\n")
        change = self.commit("change")
        self.set_green(change)
        (self.home / ".a").write_text("mine\n")
        r = self.apply("--contains", change, "--whole-commit")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((self.read(".a"), self.read(".b")), ("mine\n", "two\n"))
        self.assertEqual(self.log()[-1]["outcome"], "held")

    def test_it_fails_loudly_when_something_it_applied_is_still_pending(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        r = self.apply("--contains", change, ".a", SHIM_NOOP_APPLY="1")  # an apply that reports success and changes nothing
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("still pending", r.stdout)
        self.assertEqual(self.log()[-1]["outcome"], "still-pending")

    # --- the checkout -----------------------------------------------------------------------------------------------------------------------

    def test_a_checkout_with_uncommitted_changes_is_not_moved(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        (self.src / "dot_b").write_text("edited in the source\n")
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((self.checkout(), self.read(".a")), (self.base, "one\n"))
        self.assertEqual(self.log()[-1]["outcome"], "source-dirty")

    def test_a_checkout_on_another_branch_is_not_moved(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        subprocess.run(["git", "-C", str(self.src), "checkout", "-q", "-b", "wip"], check=True)
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("is on wip, not main", r.stdout)
        self.assertEqual((self.checkout(), self.read(".a")), (self.base, "one\n"))
        self.assertEqual(self.log()[-1]["outcome"], "source-not-main")

    def test_a_checkout_already_at_the_tested_commit_with_edits_is_not_applied_from(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        subprocess.run(["git", "-C", str(self.src), "pull", "--ff-only", "-q"], check=True)
        (self.src / "dot_a").write_text("edited in the source, untested\n")
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((self.read(".a"), self.log()[-1]["outcome"]), ("one\n", "source-dirty"))
        subprocess.run(["git", "-C", str(self.src), "checkout", "-q", "--", "dot_a"], check=True)
        (self.src / "dot_new").write_text("a file git does not track\n")
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((self.read(".a"), self.log()[-1]["outcome"]), ("one\n", "source-dirty"))

    def test_a_checkout_with_a_commit_of_its_own_is_not_moved(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        subprocess.run(["git", "-C", str(self.src), "pull", "-q", "--ff-only"], check=True)
        (self.src / "dot_a").write_text("three\n")
        subprocess.run(["git", "-C", str(self.src), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.src), *GIT[1:], "commit", "-qm", "a commit of its own"], check=True, capture_output=True)
        ahead = self.checkout()
        self.assertNotEqual(ahead, change)
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.checkout(), ahead)
        self.assertEqual(self.log()[-1]["outcome"], "source-not-behind")

    # --- stop, profile, dry run, log --------------------------------------------------------------------------------------------------------

    def test_a_stop_file_holds_the_run_before_anything_moves(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        self.state.mkdir(parents=True)
        (self.state / "stop").write_text("lead holds pin 5\n")
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("lead holds pin 5", r.stdout)
        self.assertEqual((self.checkout(), self.read(".a")), (self.base, "one\n"))
        self.assertEqual(self.log()[-1]["outcome"], "stopped")
        (self.state / "stop").unlink()
        self.assertEqual(self.apply("--contains", change, ".a").returncode, 0)

    def test_a_stop_file_put_down_while_the_diff_is_shown_holds_the_apply(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        self.state.mkdir(parents=True)
        r = self.apply("--contains", change, ".a", SHIM_STOP_ON_DIFF=str(self.state / "stop"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(self.read(".a"), "one\n")
        self.assertEqual(self.log()[-1]["outcome"], "stopped")

    def test_it_refuses_on_the_work_profile_before_asking_the_gate(self):
        self.config(profile="axon-work-computer")
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        r = self.apply("--contains", change, ".a")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("applies only on personal", r.stdout)
        self.assertEqual((self.gate_calls(), self.read(".a"), self.checkout()), ([], "one\n", self.base))
        self.assertEqual(self.log()[-1]["outcome"], "profile")

    def test_it_refuses_when_the_config_runs_a_hook_on_reading_the_source(self):
        self.config(extra="hooks:\n  read-source-state:\n    pre:\n      command: \"true\"\n")
        r = self.apply("--contains", self.base)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((self.gate_calls(), self.log()[-1]["outcome"]), ([], "hooks"))

    def test_it_refuses_a_hook_that_runs_after_the_source_is_read_too(self):
        self.config(extra="hooks:\n  read-source-state:\n    post:\n      command: \"true\"\n")
        r = self.apply("--contains", self.base)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual((self.gate_calls(), self.log()[-1]["outcome"]), ([], "hooks"))

    def test_dry_run_asks_the_gate_and_moves_and_applies_nothing(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        r = self.apply("--contains", change, ".a", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("would move the source checkout", r.stdout)
        self.assertEqual((self.read(".a"), self.checkout()), ("one\n", self.base))
        self.assertEqual(self.log()[-1]["outcome"], "dry-run")

    def test_every_run_leaves_one_line_naming_the_caller(self):
        self.write("dot_a", "two\n")
        change = self.commit("change")
        self.set_green(change)
        self.apply("--contains", change, ".a", T3CODE_THREAD_ID="thread-1")
        line = self.log()[-1]
        self.assertEqual(line["caller"], "t3:thread-1")
        for key in ("ts", "duration_ms", "action", "outcome", "exit", "asked", "commit", "run", "paths", "whole", "dry_run", "reason"):
            self.assertIn(key, line)
        self.assertEqual((line["action"], line["whole"], line["dry_run"]), ("apply", False, False))
        self.assertEqual(len(self.log()), 1)

    def test_help_names_the_stop_file_and_the_exit_codes(self):
        r = self.apply("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("Exit 0: applied, or nothing to do. Exit 1: refused or failed", r.stdout)
        self.assertIn("~/.local/state/dotfiles-apply/stop", r.stdout)


if __name__ == "__main__":
    unittest.main()
