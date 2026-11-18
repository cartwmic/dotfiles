"""Repo context in the layer-2 prompt: names the target branch already publishes and the change also holds are named in the prompt, so the judge does not report them.

Halcyon and Zephyrine are invented; "fooco" is the pretend layer-1 term. The fake judge reports every FAKE_FLAG name it sees in what it is sent.
"""
import os
import shutil
import subprocess
import sys
import time
import unittest

from test_leak_guard import ZERO, Base, SCRIPT, load_guard


TARGET = "fooco-dev/guarded"       # the repository the text is posted to, as the gh wrapper names it
OTHER = "fooco-dev/other"          # a different repository, whose checkout must never name its own names as published


class RepoContextBase(Base):
    def setUp(self):
        super().setUp()
        self.remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        # The remote is named as its public URL; git rewrites it to the local bare repo for transport, as insteadOf does on a real machine.
        self.git("remote", "add", "origin", "https://github.com/%s.git" % TARGET)
        self.git("config", "url.file://%s.insteadOf" % self.remote, "https://github.com/%s.git" % TARGET)
        (self.repo / "docs.txt").write_text("The Halcyon tools live here\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "docs", "--no-verify")
        self.git("push", "-q", "origin", "main", "--no-verify")

    def body(self, text):
        path = self.tmp / "body.txt"
        path.write_text(text)
        return str(path)

    def judge(self, *flag):
        return {"FAKE_CLAUDE": "flagnames", "FAKE_FLAG": ",".join(flag)}


class TextModeRepoContext(RepoContextBase):
    def guard_text(self, body, env, target=TARGET):
        return self.guard("text", "--repo", target, self.body(body), env=env)

    def test_a_name_the_target_branch_publishes_is_named_in_the_prompt_and_an_unknown_one_is_not(self):
        done = self.guard_text("see the Halcyon docs and the Zephyrine docs\n", self.judge("Zephyrine"))
        self.assertEqual(done.returncode, 1, done.stderr)
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("do not report them: Halcyon", sent)
        self.assertNotIn("Zephyrine, ", sent)
        self.assertNotIn(", Zephyrine", sent)
        self.assertNotIn("The Halcyon tools live here", sent, "the repo context names the name, never whole files")

    def test_ordinary_lowercase_words_are_never_named_even_when_the_branch_holds_them(self):
        done = self.guard_text("the tools live here too\n", {"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("do not report them", (self.fake / "stdin.txt").read_text())

    def test_a_repo_known_name_reported_anyway_is_skipped_not_blocked(self):
        done = self.guard_text("see the Halcyon docs\n", self.judge("Halcyon"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("skipped, its name is already in the repository", done.stderr)
        self.assertIn("Halcyon", done.stderr)
        self.assertEqual(self.log()[-1]["known_skipped"], 1)

    def test_a_layer_1_term_still_blocks_even_when_the_branch_publishes_it(self):
        (self.repo / "docs.txt").write_text("The Halcyon tools live here\nand fooco runs them\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "docs", "--no-verify")
        self.git("push", "-q", "origin", "main", "--no-verify")
        done = self.guard("text", "--repo", TARGET, self.body("fooco is mentioned in the docs\n"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("BLOCKED by the terms list (layer 1)", done.stderr)
        self.assertIn("body.txt:1: term 1", done.stderr)
        self.assertEqual(self.calls(), 0, "layer 1 blocks before any judge is called")

    def test_a_checkout_of_another_repository_never_names_its_names_as_published(self):
        # The gh wrapper runs leak-guard in the caller's directory: a checkout of repo Y, posting to repo X, must not get Y's names as a base.
        other_remote = self.tmp / "other.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(other_remote)], check=True)
        other = self.tmp / "other-clone"
        other.mkdir()
        env = {**os.environ, "HOME": str(self.home), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        subprocess.run(["git", "init", "-q", "-b", "main", str(other)], check=True, env=env)
        subprocess.run(["git", "-C", str(other), "remote", "add", "origin", "https://github.com/%s.git" % OTHER], check=True, env=env)
        subprocess.run(["git", "-C", str(other), "config", "url.file://%s.insteadOf" % other_remote, "https://github.com/%s.git" % OTHER], check=True, env=env)
        (other / "docs.txt").write_text("The Halcyon tools live here\n")
        subprocess.run(["git", "-C", str(other), "add", "-A"], check=True, env=env)
        subprocess.run(["git", "-C", str(other), "commit", "-q", "-m", "docs"], check=True, env=env)
        subprocess.run(["git", "-C", str(other), "push", "-q", "origin", "main"], check=True, env=env)
        for target, blocks in ((TARGET, True), (OTHER, False)):
            with self.subTest(target):
                body = self.body("see the Halcyon docs\n")
                run_env = {**os.environ, "HOME": str(self.home), "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), **self.judge("Halcyon")}
                done = subprocess.run([sys.executable, str(SCRIPT), "text", "--repo", target, body], cwd=other, capture_output=True, text=True, env=run_env, timeout=60)
                sent = (self.fake / "stdin.txt").read_text()
                self.assertEqual(done.returncode, 1 if blocks else 0, done.stderr)
                self.assertEqual("do not report them" in sent, not blocks, sent[-400:])
                self.assertEqual("skipped, its name is already in the repository" in done.stderr, not blocks)

    def test_no_remote_or_no_repository_gives_no_repo_context(self):
        lonely = self.tmp / "lonely"
        lonely.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(lonely)], check=True)
        (lonely / "body.txt").write_text("see the Halcyon docs\n")
        env = {**os.environ, "HOME": str(self.home), "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), **self.judge("Halcyon")}
        done = subprocess.run([sys.executable, str(SCRIPT), "text", "body.txt"], cwd=lonely, capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 1, done.stderr)   # no tracking refs, so Halcyon is new here
        self.assertNotIn("do not report them", (self.fake / "stdin.txt").read_text())


class CommitAndPushShareTheContext(RepoContextBase):
    def test_the_pre_commit_prompt_names_what_head_already_holds(self):
        self.stage("notes.txt", "see the Halcyon docs\n")
        done = self.guard("pre-commit", env=self.judge("Halcyon"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("do not report them: Halcyon", (self.fake / "stdin.txt").read_text())

    def test_the_pre_push_prompt_names_what_the_remote_already_publishes(self):
        self.git("checkout", "-q", "-b", "feature")
        (self.repo / "notes.txt").write_text("see the Halcyon docs\n")
        self.git("add", "notes.txt")
        self.git("commit", "-q", "-m", "mention", "--no-verify")
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote),
                          stdin="refs/heads/feature %s refs/heads/feature %s\n" % (tip, "0" * 40), env=self.judge("Halcyon"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("do not report them: Halcyon", (self.fake / "stdin.txt").read_text())
        self.assertIn("skipped, its name is already in the repository", done.stderr)

    def test_a_name_added_by_an_earlier_commit_of_the_same_push_is_not_named_as_published(self):
        self.git("checkout", "-q", "-b", "feature")
        for name, text in (("one.txt", "The Zephyrine tools live here\n"), ("two.txt", "see the Zephyrine docs\n")):
            (self.repo / name).write_text(text)
            self.git("add", name)
            self.git("commit", "-q", "-m", "mention", "--no-verify")
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote),
                          stdin="refs/heads/feature %s refs/heads/feature %s\n" % (tip, "0" * 40), env=self.judge("Zephyrine"))
        self.assertEqual(done.returncode, 1, done.stderr)
        sent = (self.fake / "stdin.txt").read_text()
        self.assertNotIn("report them: Zephyrine", sent, "a name this same push adds is new, whatever an earlier commit of the push holds")
        self.assertNotIn(", Zephyrine", sent)
        self.assertNotIn("skipped", done.stderr)

    def test_a_name_the_branch_lacks_is_not_named_in_the_pre_push_prompt(self):
        self.git("checkout", "-q", "-b", "feature")
        (self.repo / "notes.txt").write_text("see the Zephyrine docs\n")
        self.git("add", "notes.txt")
        self.git("commit", "-q", "-m", "mention", "--no-verify")
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(self.remote),
                          stdin="refs/heads/feature %s refs/heads/feature %s\n" % (tip, "0" * 40), env=self.judge("Zephyrine"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertNotIn("do not report them", (self.fake / "stdin.txt").read_text())


class PublishedBase(RepoContextBase):
    """What counts as already published: the remote's default branch plus, at pre-push, each pushed branch the remote already has -- never the remote's
    every branch (hundreds of tracking refs made every pre-push grep for minutes)."""

    def side_branches(self, count):
        """Branches on the remote that main does not have, each on its OWN commit with its own file (distinct trees: the old code, which de-duplicated
        commits, would grep every one of them), with tracking refs here: what a long-lived fork or a busy remote looks like. Built with one fast-import."""
        main = self.git("rev-parse", "HEAD").stdout.strip()
        stream = []
        for i in range(count):
            body = "side %d notes\n" % i
            stream.append("commit refs/heads/side%d\ncommitter T <t@example.invalid> 0 +0000\ndata 4\nside\nfrom %s\n"
                          "M 100644 inline side%d.txt\ndata %d\n%s\n" % (i, main, i, len(body), body))
        subprocess.run(["git", "-C", str(self.remote), "fast-import", "--quiet"], input="".join(stream), check=True, text=True, capture_output=True)
        self.git("fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*")

    def logging_git(self):
        """A `git` first on PATH that records each `git grep`'s arguments, then runs the real git: the guard is observed from outside, as a process."""
        real = shutil.which("git")
        wrap = self.tmp / "gitlog"
        wrap.mkdir()
        log = self.tmp / "git-grep-args.txt"
        (wrap / "git").write_text('#!/bin/sh\nfor a in "$@"; do [ "$a" = grep ] && { printf \'%%s\\n\' "$*" >> "%s"; break; }; done\nexec "%s" "$@"\n'
                                  % (log, real))
        (wrap / "git").chmod(0o755)
        return wrap, log

    def side_branch_with(self, name):
        """A branch on the remote, and only there, whose files hold the name."""
        self.git("checkout", "-q", "-b", "side")
        (self.repo / "side.txt").write_text("The %s tools live here\n" % name)
        self.git("add", "side.txt")
        self.git("commit", "-q", "-m", "side", "--no-verify")
        self.git("push", "-q", "origin", "side", "--no-verify")
        self.git("checkout", "-q", "main")
        self.git("branch", "-q", "-D", "side")
        self.git("fetch", "-q", "origin")

    def feature_commit(self, name, text):
        self.git("checkout", "-q", "-B", "feature")
        (self.repo / name).write_text(text)
        self.git("add", name)
        self.git("commit", "-q", "-m", "mention", "--no-verify")
        return self.git("rev-parse", "HEAD").stdout.strip()

    def push_line(self, tip, remote_sha=ZERO):
        return "refs/heads/feature %s refs/heads/feature %s\n" % (tip, remote_sha)

    def test_pre_push_with_many_tracking_refs_greps_only_the_default_and_pushed_trees(self):
        self.side_branches(300)
        self.assertEqual(len(set(self.git("for-each-ref", "--format=%(objectname)", "refs/remotes/origin/").stdout.split())), 301,
                         "301 tracking refs on 301 distinct commits")
        self.git("remote", "set-head", "origin", "--auto")     # the default branch named by refs/remotes/origin/HEAD, as a clone has
        tip = self.feature_commit("notes.txt", "see the Halcyon docs\n")
        wrap, log = self.logging_git()
        env = {**self.judge(), "PATH": "%s:%s:%s" % (wrap, self.bin, os.environ["PATH"])}
        t0 = time.monotonic()
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env=env)
        elapsed = time.monotonic() - t0
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Halcyon", (self.fake / "stdin.txt").read_text(), "the name main publishes is named in the prompt")
        main_sha = self.git("rev-parse", "refs/remotes/origin/main").stdout.strip()
        greps = log.read_text().splitlines() if log.exists() else []
        self.assertTrue(greps, "the repo context greps the published trees")
        for line in greps:
            shas = [w for w in line.split() if len(w) == 40 and all(c in "0123456789abcdef" for c in w)]
            self.assertEqual(shas, [main_sha], "every grep runs over the default branch only, never the 300 side branches: %s" % line[:200])
        self.assertLess(elapsed, 20.0, "pre-push and its repo context stay fast with 301 tracking refs")

    def default_branch_case(self, branch, set_head):
        """A fresh remote whose only branch is `branch`, fetched; returns the trees the guard treats as published."""
        remote = self.tmp / ("remote-%s.git" % branch)
        subprocess.run(["git", "init", "-q", "--bare", "-b", branch, str(remote)], check=True)
        self.git("remote", "add", branch, str(remote))
        self.git("push", "-q", branch, "HEAD:refs/heads/%s" % branch, "--no-verify")
        self.git("fetch", "-q", branch)
        if set_head:
            self.git("remote", "set-head", branch, "--auto")
        else:
            self.git("remote", "set-head", branch, "-d", check=False)   # newer git sets <remote>/HEAD on fetch; take it away to test the fallback
            self.assertNotEqual(self.git("symbolic-ref", "-q", "refs/remotes/%s/HEAD" % branch, check=False).returncode, 0)
        cwd = os.getcwd()
        os.chdir(self.repo)
        try:
            return load_guard().published_trees(branch)
        finally:
            os.chdir(cwd)

    def test_the_default_branch_falls_back_from_head_to_main_to_master_and_otherwise_there_is_none(self):
        head = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(self.default_branch_case("trunk", set_head=True), [head], "HEAD's target is the default")
        self.assertEqual(self.default_branch_case("master", set_head=False), [head], "with no HEAD and no main, master")
        self.assertEqual(self.default_branch_case("develop", set_head=False), [], "no HEAD, main or master: no base, so nothing counts as published")

    def test_a_name_only_a_side_branch_holds_is_not_published_at_pre_push(self):
        self.side_branch_with("Sidewinder")
        tip = self.feature_commit("notes.txt", "see the Sidewinder docs\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip), env=self.judge("Sidewinder"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertNotIn("do not report them", (self.fake / "stdin.txt").read_text())
        self.assertNotIn("skipped", done.stderr)

    def test_a_name_only_a_side_branch_holds_is_not_published_in_text_mode(self):
        self.side_branch_with("Sidewinder")
        done = self.guard("text", "--repo", TARGET, self.body("see the Sidewinder docs\n"), env=self.judge("Sidewinder"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertNotIn("do not report them", (self.fake / "stdin.txt").read_text())
        self.assertNotIn("skipped", done.stderr)

    def test_a_pushed_branch_the_remote_already_has_joins_the_base(self):
        self.git("checkout", "-q", "-b", "feature")
        (self.repo / "one.txt").write_text("The Sidewinder tools live here\n")
        self.git("add", "one.txt")
        self.git("commit", "-q", "-m", "add", "--no-verify")
        tip1 = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("push", "-q", "origin", "feature", "--no-verify")   # the remote now has feature
        self.git("fetch", "-q", "origin")       # and the tracking ref says so
        tip2 = self.feature_commit("two.txt", "see the Sidewinder docs\n")
        done = self.guard("pre-push", "origin", str(self.remote), stdin=self.push_line(tip2, tip1), env=self.judge("Sidewinder"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("skipped, its name is already in the repository", done.stderr)

if __name__ == "__main__":
    unittest.main()
