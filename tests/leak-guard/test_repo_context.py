"""Repo context in the layer-2 prompt: names the target branch already publishes and the change also holds are named in the prompt, so the judge does not report them.

Halcyon and Zephyrine are invented; "fooco" is the pretend layer-1 term. The fake judge reports every FAKE_FLAG name it sees in what it is sent.
"""
import os
import subprocess
import sys
import unittest

from test_leak_guard import Base, SCRIPT


class RepoContextBase(Base):
    def setUp(self):
        super().setUp()
        self.remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        self.git("remote", "add", "origin", str(self.remote))
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
    def test_a_name_the_target_branch_publishes_is_named_in_the_prompt_and_an_unknown_one_is_not(self):
        done = self.guard("text", self.body("see the Halcyon docs and the Zephyrine docs\n"), env=self.judge("Zephyrine"))
        self.assertEqual(done.returncode, 1, done.stderr)
        sent = (self.fake / "stdin.txt").read_text()
        self.assertIn("do not report them: Halcyon", sent)
        self.assertNotIn("Zephyrine, ", sent)
        self.assertNotIn(", Zephyrine", sent)
        self.assertNotIn("The Halcyon tools live here", sent, "the repo context names the name, never whole files")

    def test_ordinary_lowercase_words_are_never_named_even_when_the_branch_holds_them(self):
        done = self.guard("text", self.body("the tools live here too\n"), env={"FAKE_CLAUDE": "clean"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("do not report them", (self.fake / "stdin.txt").read_text())

    def test_a_repo_known_name_reported_anyway_is_skipped_not_blocked(self):
        done = self.guard("text", self.body("see the Halcyon docs\n"), env=self.judge("Halcyon"))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("skipped, its name is already in the repository", done.stderr)
        self.assertIn("Halcyon", done.stderr)
        self.assertEqual(self.log()[-1]["known_skipped"], 1)

    def test_a_layer_1_term_still_blocks_even_when_the_branch_publishes_it(self):
        (self.repo / "docs.txt").write_text("The Halcyon tools live here\nand fooco runs them\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "docs", "--no-verify")
        self.git("push", "-q", "origin", "main", "--no-verify")
        done = self.guard("text", self.body("fooco is mentioned in the docs\n"))
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("BLOCKED by the terms list (layer 1)", done.stderr)
        self.assertIn("body.txt:1: term 1", done.stderr)
        self.assertEqual(self.calls(), 0, "layer 1 blocks before any judge is called")

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
