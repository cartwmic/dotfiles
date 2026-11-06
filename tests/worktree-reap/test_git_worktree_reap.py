"""Black-box tests for dot_local/bin/executable_git-worktree-reap.

The real script runs against a scratch repo with a local bare "origin": merged, unmerged, dirty and busy worktrees, and the main checkout.
A fake `gh` (GIT_WORKTREE_REAP_GH) answers `gh pr list --head BRANCH` from files the test writes, so no network or login is needed.
The RED controls run a copy of the script with one check cut out and assert the wrong worktree is then removed, so each test is shown to bite.
"""
import os
import shutil
import time
import subprocess
import tempfile
import unittest
from pathlib import Path

FAKE_GH = """#!/bin/sh
while [ $# -gt 0 ]; do case $1 in --head) br=$2; shift ;; esac; shift; done
echo "$br" >> "$FAKE/gh_calls"
if [ -f "$FAKE/gh_fail" ]; then echo "gh: To get started with GitHub CLI, please run: gh auth login" >&2; exit 1; fi
if [ -f "$FAKE/gh_$br.json" ]; then cat "$FAKE/gh_$br.json"; else echo "[]"; fi
"""

SCRIPT = Path(__file__).resolve().parents[2] / "dot_local/bin/executable_git-worktree-reap"


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, text=True, capture_output=True).stdout.strip()


@unittest.skipUnless(shutil.which("lsof"), "lsof is not installed")
class WorktreeReap(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.root = root
        self.env = {**os.environ, "HOME": str(root), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
        os.environ.update({k: self.env[k] for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")})
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")])
        self.fake = root / "fake"
        self.fake.mkdir()
        fake_gh = root / "gh"
        (root / "gh.new").write_text(FAKE_GH)
        (root / "gh.new").chmod(0o755)
        os.replace(root / "gh.new", fake_gh)
        self.env.update({"FAKE": str(self.fake), "GIT_WORKTREE_REAP_GH": str(fake_gh)})
        origin = root / "origin.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
        self.main = root / "repo"
        subprocess.run(["git", "clone", str(origin), str(self.main)], check=True, capture_output=True)
        git(self.main, "checkout", "-b", "main")
        (self.main / "README").write_text("hello\n")
        git(self.main, "add", "README")
        git(self.main, "commit", "-m", "first")
        git(self.main, "push", "-u", "origin", "main")
        self.wt = {}
        # merged: a commit of its own, then merged into main and pushed
        self.add("merged", commit=True)
        git(self.main, "merge", "--no-ff", "-m", "merge merged", "merged")
        # fast-forward style: merged and busy / dirty are made from merged branches too
        self.add("dirty", commit=True)
        self.add("busy", commit=True)
        git(self.main, "merge", "--no-ff", "-m", "merge dirty", "dirty")
        git(self.main, "merge", "--no-ff", "-m", "merge busy", "busy")
        git(self.main, "push", "origin", "main")
        # unmerged: a commit that is not in main
        self.add("unmerged", commit=True)
        (self.wt["dirty"] / "README").write_text("changed\n")
        self.busy = subprocess.Popen(["sleep", "300"], cwd=self.wt["busy"])
        self.addCleanup(self.stop_busy)

    def stop_busy(self):
        if self.busy.poll() is None:
            self.busy.kill()
        self.busy.wait()

    def add(self, name, commit):
        path = self.root / "wt" / name
        git(self.main, "worktree", "add", "-b", name, str(path))
        if commit:
            (path / f"{name}.txt").write_text(name + "\n")
            git(path, "add", f"{name}.txt")
            git(path, "commit", "-m", name)
        self.wt[name] = path

    def pr_merged(self, branch, head, number=7):
        """The fake gh reports this branch's PR as merged with this head commit (written to a temp name, then renamed)."""
        (self.fake / "gh.new").write_text(f'[{{"headRefOid":"{head}","number":{number}}}]\n')
        os.replace(self.fake / "gh.new", self.fake / f"gh_{branch}.json")

    def make_old(self, path, hours=48):
        """Backdate the .git file and the index of a worktree, as if it had been made `hours` ago."""
        then = time.time() - hours * 3600
        gitdir = Path(git(path, "rev-parse", "--absolute-git-dir"))
        for f in (path / ".git", gitdir / "index"):
            os.utime(f, (then, then))

    def reap(self, *args, script=SCRIPT, cwd=None):
        return subprocess.run(["sh", str(script), *args], cwd=cwd or self.root, env=self.env, text=True, capture_output=True, timeout=60)

    def lines(self, result):
        """Output lines keyed by worktree path."""
        by_path = {}
        for line in result.stdout.splitlines():
            rest = line.split(" ", 1)[1]
            by_path[rest.split(" (")[0].split(":")[0]] = line
        return by_path

    def test_removes_only_the_merged_idle_clean_worktree_and_says_why_for_each_other(self):
        result = self.reap(str(self.main))
        self.assertEqual(result.returncode, 0, result.stderr)
        by_path = self.lines(result)
        self.assertEqual(len(result.stdout.splitlines()), 5, result.stdout)   # one line per worktree
        self.assertEqual(by_path[str(self.wt["merged"])], f"removed {self.wt['merged']} (merged)")
        self.assertEqual(by_path[str(self.wt["unmerged"])], f"kept {self.wt['unmerged']}: unmerged not merged into origin/main")
        self.assertEqual(by_path[str(self.wt["dirty"])], f"kept {self.wt['dirty']}: has modifications")
        self.assertEqual(by_path[str(self.wt["busy"])], f"kept {self.wt['busy']}: a process has files open in it")
        self.assertEqual(by_path[str(self.main)], f"kept {self.main}: main checkout")
        self.assertFalse(self.wt["merged"].exists())
        for name in ("unmerged", "dirty", "busy"):
            self.assertTrue(self.wt[name].exists(), name)
        self.assertTrue(self.main.exists())

    def test_branch_refs_are_kept(self):
        self.reap(str(self.main))
        branches = git(self.main, "branch", "--format=%(refname:short)").split()
        for name in ("main", "merged", "unmerged", "dirty", "busy"):
            self.assertIn(name, branches)

    def test_dry_run_changes_nothing_and_says_what_it_would_do(self):
        before = git(self.main, "worktree", "list", "--porcelain")
        result = self.reap("--dry-run", str(self.main))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"would remove {self.wt['merged']} (merged)", result.stdout)
        self.assertNotIn("removed ", result.stdout)
        self.assertEqual(git(self.main, "worktree", "list", "--porcelain"), before)
        self.assertTrue(self.wt["merged"].exists())

    def test_a_second_run_removes_nothing_more(self):
        self.reap(str(self.main))
        result = self.reap(str(self.main))
        self.assertNotIn("removed ", result.stdout)
        self.assertEqual(len(result.stdout.splitlines()), 4, result.stdout)

    def test_a_worktree_is_removed_once_it_is_idle(self):
        self.stop_busy()
        result = self.reap(str(self.main))
        self.assertIn(f"removed {self.wt['busy']} (busy)", result.stdout)

    def test_a_shell_standing_in_a_worktree_keeps_it(self):
        result = self.reap(str(self.main), cwd=self.wt["merged"])   # the reaper's own current directory is inside it
        self.assertIn(f"kept {self.wt['merged']}: a process has files open in it", result.stdout)
        self.assertTrue(self.wt["merged"].exists())

    def test_runs_from_inside_a_linked_worktree_and_never_removes_the_main_checkout(self):
        result = self.reap(cwd=self.wt["unmerged"])   # REPO defaults to the current directory
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"kept {self.main}: main checkout", result.stdout)
        self.assertTrue(self.main.exists())
        self.assertFalse(self.wt["merged"].exists())

    def test_a_new_commit_on_main_that_the_branch_lacks_is_still_merged(self):
        (self.main / "later.txt").write_text("later\n")
        git(self.main, "add", "later.txt")
        git(self.main, "commit", "-m", "later")
        git(self.main, "push", "origin", "main")
        self.assertIn(f"removed {self.wt['merged']} (merged)", self.reap(str(self.main)).stdout)

    def test_not_a_repo_is_a_usage_error(self):
        result = self.reap(str(self.root))
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a git repo", result.stderr)
        self.assertEqual(self.reap("--nope").returncode, 2)

    # --- squash merges: the PR is merged and the branch tip is the PR's head ---
    def test_a_squash_merged_branch_whose_tip_is_the_pr_head_is_removed(self):
        self.add("squashed", commit=True)   # its commit is not in main: main got a squash commit instead
        self.pr_merged("squashed", git(self.wt["squashed"], "rev-parse", "HEAD"))
        result = self.reap(str(self.main))
        self.assertIn(f"removed {self.wt['squashed']} (squashed)", result.stdout)
        self.assertFalse(self.wt["squashed"].exists())

    def test_the_same_branch_with_one_more_commit_after_the_merge_is_kept(self):
        self.add("squashed", commit=True)
        self.pr_merged("squashed", git(self.wt["squashed"], "rev-parse", "HEAD"))
        (self.wt["squashed"] / "after.txt").write_text("after the merge\n")
        git(self.wt["squashed"], "add", "after.txt")
        git(self.wt["squashed"], "commit", "-m", "after")
        result = self.reap(str(self.main))
        self.assertIn(f"kept {self.wt['squashed']}: squashed not merged into origin/main", result.stdout)
        self.assertTrue(self.wt["squashed"].exists())

    def test_gh_is_not_asked_about_a_branch_that_is_an_ancestor(self):
        self.reap(str(self.main))
        calls = (self.fake / "gh_calls").read_text().split() if (self.fake / "gh_calls").exists() else []
        self.assertNotIn("merged", calls)
        self.assertIn("unmerged", calls)

    def test_without_gh_a_branch_that_is_not_an_ancestor_is_kept_as_unknown_and_the_ancestor_rule_still_works(self):
        self.env["GIT_WORKTREE_REAP_GH"] = "gh-is-not-installed"
        result = self.reap(str(self.main))
        self.assertIn(f"kept {self.wt['unmerged']}: merged state unknown (no gh)", result.stdout)
        self.assertIn(f"removed {self.wt['merged']} (merged)", result.stdout)

    def test_a_gh_that_fails_keeps_the_branch_and_says_so(self):
        (self.fake / "gh_fail").write_text("")
        result = self.reap(str(self.main))
        self.assertIn(f"kept {self.wt['unmerged']}: merged state unknown (gh failed: gh: To get started", result.stdout)
        self.assertTrue(self.wt["unmerged"].exists())

    # --- fresh worktrees ---
    def fresh(self, name="fresh"):
        path = self.root / "wt" / name
        git(self.main, "worktree", "add", "-b", name, str(path), "origin/main")
        self.wt[name] = path
        return path

    def test_a_fresh_worktree_with_no_commits_of_its_own_is_kept(self):
        path = self.fresh()
        result = self.reap(str(self.main))
        self.assertIn(f"kept {path}: no own commits, younger than 24h", result.stdout)
        self.assertTrue(path.exists())

    def test_an_old_worktree_with_no_commits_of_its_own_is_removed(self):
        path = self.fresh()
        self.make_old(path)
        result = self.reap(str(self.main))
        self.assertIn(f"removed {path} (fresh)", result.stdout)

    def test_the_age_is_configurable_and_judged_by_the_newer_of_git_file_and_index(self):
        path = self.fresh()
        self.make_old(path, hours=5)
        self.assertIn("younger than 24h", self.reap(str(self.main)).stdout)
        self.assertIn("younger than 8h", self.reap("--min-age", "8", str(self.main)).stdout)
        gitdir = Path(git(path, "rev-parse", "--absolute-git-dir"))
        os.utime(gitdir / "index", None)   # touched just now: the worktree is in use
        self.assertIn("younger than 1h", self.reap("--min-age", "1", str(self.main)).stdout)
        os.utime(gitdir / "index", (time.time() - 5 * 3600,) * 2)
        self.assertIn(f"removed {path} (fresh)", self.reap("--min-age", "1", str(self.main)).stdout)

    def test_min_age_zero_removes_a_fresh_worktree_and_a_bad_value_is_a_usage_error(self):
        path = self.fresh()
        self.assertIn(f"removed {path} (fresh)", self.reap("--min-age", "0", str(self.main)).stdout)
        for value in ("soon", "-1"):
            self.assertEqual(self.reap("--min-age", value, str(self.main)).returncode, 2, value)
        self.assertEqual(self.reap("--min-age").returncode, 2)

    def test_a_worktree_with_commits_of_its_own_is_not_held_back_by_its_age(self):
        # merged (its own commit, merged with a merge commit) was created a moment ago and is removed at once
        self.assertIn(f"removed {self.wt['merged']} (merged)", self.reap(str(self.main)).stdout)

    # --- RED controls: cut one check out of a copy of the script; the wrong worktree goes ---
    def mutant(self, old, new):
        text = SCRIPT.read_text()
        self.assertEqual(text.count(old), 1, old)
        path = self.root / "mutant"
        path.write_text(text.replace(old, new))
        self.assertEqual(subprocess.run(["sh", "-n", str(path)]).returncode, 0)
        return path

    def test_red_without_the_merged_check_an_unmerged_worktree_is_removed(self):
        mutant = self.mutant('merge-base --is-ancestor "$sha" refs/remotes/origin/main', 'merge-base --is-ancestor "$sha" "$sha"')
        result = self.reap(str(self.main), script=mutant)
        self.assertIn(f"removed {self.wt['unmerged']} (unmerged)", result.stdout)

    def test_red_without_the_open_files_check_a_busy_worktree_is_removed(self):
        mutant = self.mutant('lsof +D "$real"', 'lsof +D /nonexistent-dir')
        result = self.reap(str(self.main), script=mutant)
        self.assertIn(f"removed {self.wt['busy']} (busy)", result.stdout)

    def test_red_with_force_a_dirty_worktree_is_removed(self):
        mutant = self.mutant('  if [ -n "$(git -C "$path" status --porcelain 2>/dev/null | head -n 1)" ]; then printf \'kept %s: has modifications\\n\' "$path"; return 0; fi\n', '')
        mutant = self.mutant_on(mutant, 'worktree remove "$path"', 'worktree remove --force "$path"')
        result = self.reap(str(self.main), script=mutant)
        self.assertIn(f"removed {self.wt['dirty']} (dirty)", result.stdout)

    def test_red_without_git_refusing_a_dirty_worktree_stays_kept_by_git(self):
        # the status pre-check is for the message and for --dry-run; git itself still refuses without --force
        mutant = self.mutant('  if [ -n "$(git -C "$path" status --porcelain 2>/dev/null | head -n 1)" ]; then printf \'kept %s: has modifications\\n\' "$path"; return 0; fi\n', '')
        result = self.reap(str(self.main), script=mutant)
        self.assertIn(f"kept {self.wt['dirty']}: git refused:", result.stdout)
        self.assertTrue(self.wt["dirty"].exists())

    def test_red_without_the_pr_head_check_a_squash_branch_with_a_later_commit_is_removed(self):
        self.add("squashed", commit=True)
        self.pr_merged("squashed", git(self.wt["squashed"], "rev-parse", "HEAD"))
        (self.wt["squashed"] / "after.txt").write_text("after the merge\n")
        git(self.wt["squashed"], "add", "after.txt")
        git(self.wt["squashed"], "commit", "-m", "after")
        mutant = self.mutant('grep -Eq "\\"headRefOid\\": *\\"$sha\\""', 'grep -Eq "\\"headRefOid\\""')
        self.assertIn(f"removed {self.wt['squashed']} (squashed)", self.reap(str(self.main), script=mutant).stdout)

    def test_red_without_the_age_check_a_fresh_worktree_is_removed(self):
        path = self.fresh()
        mutant = self.mutant("if on_main_line && ! old_enough;", "if false;")
        self.assertIn(f"removed {path} (fresh)", self.reap(str(self.main), script=mutant).stdout)

    def mutant_on(self, path, old, new):
        text = path.read_text()
        self.assertEqual(text.count(old), 1, old)
        path.write_text(text.replace(old, new))
        return path


if __name__ == "__main__":
    unittest.main()
