"""A layer 1 hit is named by its term number. The term's text appears in no output and no log line, in any mode.

The planted fake term is invented ("zxq-planted-term"); it is term 2 of the terms file used here.
"""
import subprocess
import unittest

from test_gh_wrapper import WrapperBase
from test_leak_guard import Base, ZERO

PLANTED = "zxq-planted-term"


class TermsHidden(Base):
    def setUp(self):
        super().setUp()
        (self.home / ".config" / "leak-guard" / "terms").write_text("# invented\nharmless-term\n%s\n" % PLANTED)

    def assertHidden(self, done):
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("term 2", done.stderr)
        self.assertNotIn(PLANTED, done.stdout + done.stderr)
        log = self.home / ".local" / "state" / "leak-guard" / "log.jsonl"
        self.assertNotIn(PLANTED, log.read_text())

    def test_pre_commit(self):
        self.stage("notes.txt", "a line with %s in it\n" % PLANTED)
        self.assertHidden(self.guard("pre-commit"))

    def test_commit_msg(self):
        msg = self.tmp / "MSG"
        msg.write_text("subject\n\nbody with %s\n" % PLANTED)
        self.assertHidden(self.guard("commit-msg", str(msg)))

    def test_pre_push(self):
        remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-q", "origin", "main", "--no-verify")
        (self.repo / "f.txt").write_text("text with %s\n" % PLANTED)
        self.git("add", "f.txt")
        self.git("commit", "-q", "-m", "change", "--no-verify")
        tip = self.git("rev-parse", "HEAD").stdout.strip()
        done = self.guard("pre-push", "origin", str(remote), stdin="refs/heads/feature %s refs/heads/feature %s\n" % (tip, ZERO))
        self.assertHidden(done)

    def test_text(self):
        path = self.tmp / "body.txt"
        path.write_text("a line with %s in it\n" % PLANTED)
        self.assertHidden(self.guard("text", str(path)))

    def test_a_term_in_a_file_name_is_hidden_too_and_a_bad_regex_is_named_by_number(self):
        self.stage("%s.txt" % "x", "fine\n")
        (self.home / ".config" / "leak-guard" / "terms").write_text("harmless-term\n%s(unclosed\n" % PLANTED)
        done = self.guard("pre-commit")
        self.assertEqual(done.returncode, 1)
        self.assertIn("term 2 of the terms file", done.stderr)
        self.assertNotIn(PLANTED, done.stdout + done.stderr)

    def test_the_term_number_counts_terms_not_blank_or_comment_lines(self):
        (self.home / ".config" / "leak-guard" / "terms").write_text("# one\n\nharmless-term\n  # two\n\n%s\n" % PLANTED)
        self.stage("notes.txt", "%s\n" % PLANTED)
        done = self.guard("pre-commit")
        self.assertIn("notes.txt:1: term 2", done.stderr)


class TermsHiddenInTheWrapper(WrapperBase):
    def test_the_wrappers_block_output_and_both_logs_name_the_term_by_number_only(self):
        (self.home / ".config" / "leak-guard" / "terms").write_text("# invented\nharmless-term\n%s\n" % PLANTED)
        done = self.gh("pr", "comment", "5", "--body", "a line with %s in it" % PLANTED)
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn("body:1: term 2", done.stderr)
        self.assertNotIn(PLANTED, done.stdout + done.stderr)
        self.assertNotIn(PLANTED, (self.home / ".local" / "state" / "leak-guard" / "log.jsonl").read_text())


if __name__ == "__main__":
    unittest.main()
