"""Black-box tests for dot_local/bin/executable_stack-map-merge-check, the merge-time check that a cartwmic/dotfiles PR does not break the agent stack map page.

Each test runs the real check, with the real stack map generator, in a scratch HOME: four small repositories under ~/git (a bare origin and a clone each,
the same world the stack-map tests build), a pull request pushed to `refs/pull/N/head` on the dotfiles origin, and a stand-in `gh` that prints the
PR's head commit. Nothing reaches GitHub or the real ~/git.

    python3 -m unittest discover -s tests/stack-map-merge-check -v
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests/stack-map"))
import test_stack_map as sm  # noqa: E402  (its World builds the four repositories; only the fixture is used here, no test class)

CHECK = ROOT / "dot_local/bin/executable_stack-map-merge-check"
GENERATOR = "dot_local/user_scripts/executable_stack_map.py"
CONTENT = "docs/stack-map/content.md"
GOOD_SNIPPET = '"name": "coordinator"'
RENAMED = '"name": "coordinator-renamed"'

FAKE_GH = """#!/bin/sh
echo "$*" >> "$FAKE_GH_LOG"
cat "$FAKE_GH_SHA_FILE"
"""


def git(clone, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(clone), *args], check=True, capture_output=True, text=True).stdout.strip()


class MergeCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.world = sm.World(self.home)  # the repositories are ~/git/<name>, each with a bare origin
        self.dotfiles = self.world.root / "dotfiles"
        self.world.change("dotfiles", GENERATOR, (ROOT / GENERATOR).read_text(encoding="utf-8"))
        self.bin = self.home / "stub-bin"
        self.bin.mkdir()
        (self.bin / "gh").write_text(FAKE_GH, encoding="utf-8")
        (self.bin / "gh").chmod(0o755)
        self.sha_file, self.gh_log = self.home / "gh-sha", self.home / "gh.log"

    def pull_request(self, number, files, remove=()):
        """Commit `files` ({path: text}) on a branch off dotfiles main and push it to refs/pull/N/head. Returns the commit."""
        git(self.dotfiles, "checkout", "-q", "-b", "pr%s" % number, "origin/main")
        for path, text in files.items():
            target = self.dotfiles / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        for path in remove:
            git(self.dotfiles, "rm", "-q", path)
        git(self.dotfiles, "add", "-A")
        git(self.dotfiles, "commit", "-q", "--allow-empty", "-m", "pr %s" % number)
        sha = git(self.dotfiles, "rev-parse", "HEAD")
        git(self.dotfiles, "push", "-q", "origin", "HEAD:refs/pull/%s/head" % number)
        git(self.dotfiles, "checkout", "-q", "main")
        self.sha_file.write_text(sha + "\n", encoding="utf-8")
        return sha

    def content(self, old=None, new=None, extra=""):
        text = self.world.read("dotfiles", CONTENT)
        if old:
            assert old in text
            text = text.replace(old, new)
        return text + extra

    def check(self, number=1, repo="cartwmic/dotfiles"):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "STACK_MAP", "XDG_"))}
        env.update(HOME=str(self.home), PATH="%s:%s" % (self.bin, os.environ["PATH"]), FAKE_GH_SHA_FILE=str(self.sha_file), FAKE_GH_LOG=str(self.gh_log))
        return subprocess.run([sys.executable, str(CHECK), repo, str(number)], capture_output=True, text=True, env=env, timeout=300)

    def assertRefused(self, done, *words):
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn("this PR breaks the stack map page build: fix content.md or the generator, or the cited code", done.stderr)
        for word in words:
            self.assertIn(word, done.stderr)

    def moved_coordinator(self):
        """Another repository changes the line a citation points at, so the page breaks on main with no PR involved."""
        self.world.change("coordinator", "package.json", self.world.read("coordinator", "package.json").replace(GOOD_SNIPPET, RENAMED))

    def test_a_pr_that_breaks_a_snippet_is_refused_with_the_generators_line(self):
        self.pull_request(1, {CONTENT: self.content(GOOD_SNIPPET, '"name": "no such text"')})
        done = self.check(1)
        self.assertRefused(done, "coordinator:package.json:0: snippet", "page's own files (docs/stack-map/content.md)")

    def test_a_good_pr_passes_and_says_how_many_citations_it_verified(self):
        text = self.content(extra="\nOne more plain sentence.\n")
        self.pull_request(2, {CONTENT: text})
        done = self.check(2)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("the stack map page builds with this PR", done.stdout)
        self.assertIn("%d citations verified" % len(re.findall(r"\[\[[^\]]+\]\]", text)), done.stdout, text)

    def test_a_pr_that_touches_nothing_on_the_page_and_builds_fine_passes(self):
        self.pull_request(3, {"README.md": "# Dotfiles\n\nPersonal dotfiles managed with [chezmoi](https://www.chezmoi.io/) and mise. Edited.\n"})
        self.assertEqual(self.check(3).returncode, 0)

    def test_a_pr_is_judged_when_it_breaks_the_page_for_a_cited_dotfiles_file(self):
        """Not only content.md: a PR that changes a line a citation points at in a dotfiles file breaks the page, and main does not."""
        self.pull_request(4, {"README.md": self.world.read("dotfiles", "README.md").replace("# Dotfiles", "# Home")})
        self.assertRefused(self.check(4), "dotfiles:README.md:0: snippet")

    def test_a_break_made_by_another_repository_does_not_block_a_pr_that_touches_no_page_file(self):
        self.moved_coordinator()
        self.pull_request(5, {"README.md": "# Dotfiles\n\nPersonal dotfiles managed with [chezmoi](https://www.chezmoi.io/) and mise. More words.\nA line.\n"})
        done = self.check(5)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("warning: the stack map page does not build with this PR", done.stderr)
        self.assertIn("coordinator:package.json:0: snippet", done.stderr)

    def test_a_pr_on_the_page_is_refused_while_main_is_broken_and_the_pr_does_not_fix_it(self):
        self.moved_coordinator()
        self.pull_request(6, {CONTENT: self.content(extra="\nOne more plain sentence.\n")})
        self.assertRefused(self.check(6), "coordinator:package.json:0: snippet")

    def test_a_pr_that_fixes_the_page_passes_while_main_is_broken(self):
        self.moved_coordinator()
        self.pull_request(7, {CONTENT: self.content("[[coordinator:package.json|" + GOOD_SNIPPET, "[[coordinator:package.json|" + RENAMED)})
        done = self.check(7)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("the stack map page builds with this PR", done.stdout)

    def test_the_generator_used_is_the_prs_own(self):
        """Main's generator builds the page fine. The PR's generator reads the text from a file that does not exist, so only the PR's own generator can fail it."""
        text = (ROOT / GENERATOR).read_text(encoding="utf-8")
        self.assertIn('CONTENT_PATH = "docs/stack-map/content.md"', text)
        self.pull_request(8, {GENERATOR: text.replace('CONTENT_PATH = "docs/stack-map/content.md"', 'CONTENT_PATH = "docs/stack-map/gone.md"')})
        self.assertRefused(self.check(8), "dotfiles:docs/stack-map/gone.md:0: missing at origin/main", "page's own files (dot_local/user_scripts/executable_stack_map.py)")

    def test_a_pr_that_deletes_the_generator_is_refused(self):
        self.pull_request(9, {}, remove=[GENERATOR])
        self.assertRefused(self.check(9), "the generator is gone")

    def test_the_stack_map_tests_count_as_page_files(self):
        self.moved_coordinator()
        self.pull_request(10, {"tests/stack-map/test_x.py": "x = 1\n"})
        self.assertRefused(self.check(10), "tests/stack-map/test_x.py")

    def test_the_tests_of_this_check_are_not_page_files(self):
        self.moved_coordinator()
        self.pull_request(11, {"tests/stack-map-merge-check/test_x.py": "x = 1\n"})
        done = self.check(11)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("warning", done.stderr)

    def test_the_repo_may_be_written_dotfiles_and_gh_is_asked_for_cartwmic_dotfiles(self):
        self.pull_request(12, {})
        self.assertEqual(self.check(12, "dotfiles").returncode, 0)
        self.assertIn("pr view 12 --repo cartwmic/dotfiles --json headRefOid", self.gh_log.read_text(encoding="utf-8"))

    def test_another_repo_or_a_bad_number_is_a_usage_error(self):
        self.assertEqual(self.check(1, "acme/app").returncode, 2)
        self.assertEqual(self.check("x").returncode, 2)

    def test_a_usage_error_is_written_to_the_log(self):
        """Every run adds a record, a usage error included: a caller that passes the wrong arguments leaves a trace."""
        log = self.home / ".local/state/stack-map-merge-check/log.jsonl"
        self.assertEqual(self.check(1, "acme/app").returncode, 2)
        self.assertEqual(self.check("x").returncode, 2)
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(r["pr"], r["outcome"], r["exit"]) for r in records], [(1, "error", 2), (None, "error", 2)])
        for r in records:
            self.assertTrue(r["failed"][0].startswith("usage: stack-map-merge-check cartwmic/dotfiles PR"), r)

    def test_it_leaves_the_clone_the_log_and_the_scratch_directory_as_they_were(self):
        self.pull_request(13, {CONTENT: self.content(GOOD_SNIPPET, '"name": "no such text"')})
        main = git(self.dotfiles, "rev-parse", "main")
        self.assertEqual(self.check(13).returncode, 1)
        self.assertEqual(git(self.dotfiles, "rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(git(self.dotfiles, "rev-parse", "main"), main)
        self.assertEqual(git(self.dotfiles, "status", "--porcelain"), "")
        self.assertEqual(git(self.dotfiles, "for-each-ref", "refs/stack-map-merge-check"), "")
        self.assertEqual(sorted((self.home / "tmp").iterdir()), [], "the scratch directory is removed")
        self.assertFalse((self.home / ".local/state/stack-map").exists(), "the real run log is not written")

    def test_every_run_adds_one_record_to_its_own_log(self):
        log = self.home / ".local/state/stack-map-merge-check/log.jsonl"
        self.pull_request(18, {CONTENT: self.content(GOOD_SNIPPET, '"name": "no such text"')})
        self.assertEqual(self.check(18).returncode, 1)
        self.pull_request(19, {})
        self.assertEqual(self.check(19).returncode, 0)
        self.sha_file.write_text("not a sha\n", encoding="utf-8")
        self.assertEqual(self.check(19).returncode, 2)
        records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(r["pr"], r["outcome"], r["exit"]) for r in records], [(18, "refused", 1), (19, "passed", 0), (19, "error", 2)])
        self.assertTrue(records[0]["failed"][0].startswith("coordinator:package.json:0: snippet"))
        self.assertGreaterEqual(records[1]["citations"], 1)
        for r in records:
            self.assertRegex(r["utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            self.assertIn("duration_ms", r)

    def test_a_fetch_that_fails_cannot_pass(self):
        self.pull_request(14, {})
        git(self.world.root / "agent-kit", "remote", "set-url", "origin", str(self.home / "no-such-origin"))
        done = self.check(14)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("git fetch origin main failed in %s" % (self.world.root / "agent-kit"), done.stderr)
        self.assertEqual(sorted((self.home / "tmp").iterdir()) if (self.home / "tmp").exists() else [], [])

    def test_a_pr_head_that_moved_while_checking_cannot_pass(self):
        self.pull_request(15, {})
        self.sha_file.write_text("1" * 40 + "\n", encoding="utf-8")
        done = self.check(15)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("moved while checking", done.stderr)

    def test_a_gh_that_fails_cannot_pass(self):
        self.pull_request(16, {})
        self.sha_file.write_text("not a sha\n", encoding="utf-8")
        done = self.check(16)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("could not read the head commit", done.stderr)

    def test_a_machine_without_the_clones_refuses_with_the_reason(self):
        self.pull_request(17, {})
        os.rename(self.world.root / "loop-engine", self.world.root / "gone")
        done = self.check(17)
        self.assertEqual(done.returncode, 2, done.stdout + done.stderr)
        self.assertIn("is not a git clone", done.stderr)


if __name__ == "__main__":
    unittest.main()
