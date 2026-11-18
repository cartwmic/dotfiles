"""Repo context in the layer-2 prompt: names the target branch already publishes and the change also holds are named in the prompt, so the judge does not report them.

Halcyon and Zephyrine are invented; "fooco" is the pretend layer-1 term. The fake judge reports every FAKE_FLAG name it sees in what it is sent.
"""
import os
import subprocess
import sys
import unittest

from test_leak_guard import Base, SCRIPT


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


if __name__ == "__main__":
    unittest.main()
