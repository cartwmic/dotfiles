"""Black-box test for dot_local/bin/executable_pr-open: the one command that checks a PR description and opens (or edits) the PR.

Nothing reaches GitHub. The repo is a scratch git repository with a bare local `origin`. `gh`, `pr-body-check` and `pr-record` are stand-ins on PATH that
write their arguments to a log; the fake check refuses a body that holds the word REFUSEME and says so on stdout, as the real one does.

    python3 -m unittest discover -s tests/pr-open -v
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_pr-open"

FAKE_GH = r'''#!/bin/sh
printf 'gh' >> "$FAKE_LOG"; for a in "$@"; do printf ' [%s]' "$a" >> "$FAKE_LOG"; done; printf '\n' >> "$FAKE_LOG"
case "$1 $2" in
  "pr create") for a in "$@"; do [ "$prev" = --body-file ] && cp "$a" "$FAKE_POSTED"; prev=$a; done
               [ -z "${FAKE_GH_FAIL-}" ] || { echo "boom" >&2; exit 1; }
               echo "https://github.com/cartwmic/scratch/pull/42" ;;
  "api -X") for a in "$@"; do case $a in body=@*) cp "${a#body=@}" "$FAKE_POSTED" ;; esac; done
            echo "https://github.com/cartwmic/scratch/pull/7" ;;
esac
'''

FAKE_CHECK = r'''#!/bin/sh
printf 'pr-body-check' >> "$FAKE_LOG"; for a in "$@"; do printf ' [%s]' "$a" >> "$FAKE_LOG"; done; printf '\n' >> "$FAKE_LOG"
while [ $# -gt 0 ]; do [ "$1" = --body-file ] && body=$2; shift; done
if grep -q REFUSEME "$body"; then echo "pr-body-check: FAIL $body (bookkeeping in the description)"; exit 1; fi
echo "pr-body-check: OK $body"
'''

FAKE_RECORD = r'''#!/bin/sh
echo "/records/$2.md"
'''


class PrOpen(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pr-open-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for name, text in (("gh", FAKE_GH), ("pr-body-check", FAKE_CHECK), ("pr-record", FAKE_RECORD)):
            (self.bin / name).write_text(text, encoding="utf-8")
            (self.bin / name).chmod(0o755)
        self.log = self.dir / "calls.log"
        self.posted = self.dir / "posted.md"
        self.origin = self.dir / "origin.git"
        self.repo = self.dir / "work"
        self.git(self.dir, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(self.dir, "clone", "-q", str(self.origin), str(self.repo))
        (self.repo / "a.txt").write_text("one\n")
        self.git(self.repo, "add", "a.txt")
        self.git(self.repo, "commit", "-q", "-m", "first")
        self.git(self.repo, "push", "-q", "origin", "main")
        self.git(self.repo, "remote", "set-head", "origin", "main")
        self.git(self.repo, "remote", "set-url", "origin", "https://github.com/cartwmic/scratch.git")
        self.git(self.repo, "config", "remote.origin.pushurl", str(self.origin))  # `get-url` says GitHub, a push goes to the bare repo
        self.git(self.repo, "checkout", "-q", "-b", "feature")
        (self.repo / "a.txt").write_text("two\n")
        self.git(self.repo, "commit", "-q", "-am", "second")
        self.body = self.dir / "body.md"
        self.body.write_text("What changed and why.\n\nProven: ran it.\n")

    def git(self, cwd, *args):
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
        return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout

    def run_open(self, *args, stdin=None, extra_env=None):
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.dir), "FAKE_LOG": str(self.log), "FAKE_POSTED": str(self.posted)}
        env.update(extra_env or {})
        return subprocess.run(["sh", str(SCRIPT), *args], cwd=self.repo, env=env, input=stdin, capture_output=True, text=True, timeout=60)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def remote_branches(self):
        return self.git(self.origin, "branch", "--list").split()

    def test_a_refused_body_creates_and_pushes_nothing(self):
        self.body.write_text("REFUSEME\n")
        result = self.run_open("--title", "T", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 1)
        self.assertIn("pr-body-check: FAIL", result.stdout)  # the check's own message is shown
        self.assertEqual(result.stderr.strip().splitlines()[-1].split(":")[0], "[pr-open] ERROR")
        self.assertIn("nothing was created", result.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("gh")])
        self.assertNotIn("feature", self.remote_branches())

    def test_an_accepted_body_pushes_the_branch_and_opens_the_pr(self):
        result = self.run_open("--title", "A title", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertTrue(lines[0].startswith("pr-body-check: OK"))  # the check's own pass line comes first
        self.assertEqual(lines[1], "https://github.com/cartwmic/scratch/pull/42")
        self.assertIn("/records/cartwmic/scratch#42.md", lines[2])  # where the agent record goes
        self.assertIn("feature", self.remote_branches())
        calls = self.calls()
        self.assertTrue(calls[0].startswith("pr-body-check [--body-file] ["), calls)
        self.assertIn("[--base] [origin/main]", calls[0])  # the same branch commits and diff as the hook's own form reads
        create = calls[1]
        for part in ("[pr] [create]", "[--repo] [cartwmic/scratch]", "[--base] [main]", "[--head] [feature]", "[--title] [A title]", "[--body-file]"):
            self.assertIn(part, create)
        self.assertNotIn("--draft", create)
        self.assertEqual(self.posted.read_text(), self.body.read_text())

    def test_the_check_and_the_post_read_the_same_private_copy(self):
        self.run_open("--title", "T", "--body-file", str(self.body))
        calls = self.calls()
        checked = calls[0].split("[--body-file] [")[1].split("]")[0]
        posted = calls[1].split("[--body-file] [")[1].split("]")[0]
        self.assertEqual(checked, posted)
        self.assertNotEqual(checked, str(self.body))
        self.assertFalse(Path(checked).exists())  # removed when the command ends

    def test_draft_is_passed_through(self):
        self.assertEqual(self.run_open("--title", "T", "--body-file", str(self.body), "--draft").returncode, 0)
        self.assertIn("[--draft]", self.calls()[1])

    def test_the_body_can_come_from_stdin(self):
        result = self.run_open("--title", "T", "--body-file", "-", stdin="from stdin\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.posted.read_text(), "from stdin\n")

    def test_a_branch_that_already_has_an_upstream_is_pushed_only_when_ahead(self):
        self.git(self.repo, "push", "-q", "-u", "origin", "feature")
        self.run_open("--title", "T", "--body-file", str(self.body))
        sha = self.git(self.origin, "rev-parse", "feature").strip()
        self.assertEqual(sha, self.git(self.repo, "rev-parse", "HEAD").strip())
        (self.repo / "a.txt").write_text("three\n")
        self.git(self.repo, "commit", "-q", "-am", "third")
        self.run_open("--title", "T", "--body-file", str(self.body))
        self.assertEqual(self.git(self.origin, "rev-parse", "feature").strip(), self.git(self.repo, "rev-parse", "HEAD").strip())

    def test_a_gh_failure_exits_non_zero_with_a_one_line_reason(self):
        result = self.run_open("--title", "T", "--body-file", str(self.body), extra_env={"FAKE_GH_FAIL": "1"})
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr.strip().splitlines()[-1], "[pr-open] ERROR: gh pr create failed")

    def test_the_base_branch_itself_is_refused(self):
        self.git(self.repo, "checkout", "-q", "main")
        result = self.run_open("--title", "T", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 2)
        self.assertIn("is the base branch", result.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("gh")])

    def test_bad_arguments_exit_2(self):
        for args in ([], ["--title", "T"], ["--body-file", str(self.body)], ["--title", "T", "--body-file", str(self.dir / "missing")],
                     ["--edit", "x", "--body-file", str(self.body)], ["--edit", "7", "--body-file", str(self.body), "--base", "main"], ["--bogus"]):
            with self.subTest(args=args):
                result = self.run_open(*args)
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stderr.strip().splitlines()[-1].startswith("[pr-open] ERROR: "), result.stderr)
        self.assertFalse([c for c in self.calls() if c.startswith("gh")])

    def test_edit_checks_then_patches_the_body_through_gh_api(self):
        result = self.run_open("--edit", "7", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "https://github.com/cartwmic/scratch/pull/7")
        calls = self.calls()
        self.assertTrue(calls[0].startswith("pr-body-check"))
        self.assertIn("[api] [-X] [PATCH] [repos/cartwmic/scratch/pulls/7]", calls[1])
        self.assertNotIn("[pr] [edit]", calls[1])
        self.assertEqual(self.posted.read_text(), self.body.read_text())

    def test_edit_with_a_title_sets_it_too(self):
        self.run_open("--edit", "7", "--body-file", str(self.body), "--title", "New title")
        self.assertIn("[-f] [title=New title]", self.calls()[1])

    def test_a_refused_body_is_not_patched(self):
        self.body.write_text("REFUSEME\n")
        result = self.run_open("--edit", "7", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 1)
        self.assertIn("pr-body-check: FAIL", result.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith("gh")])

    def test_edit_works_outside_a_git_repo_with_repo_named(self):
        elsewhere = self.dir / "elsewhere"
        elsewhere.mkdir()
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.dir), "FAKE_LOG": str(self.log), "FAKE_POSTED": str(self.posted)}
        result = subprocess.run(["sh", str(SCRIPT), "--edit", "7", "--repo", "cartwmic/other", "--body-file", str(self.body)],
                                cwd=elsewhere, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("repos/cartwmic/other/pulls/7", self.calls()[1])


if __name__ == "__main__":
    unittest.main()
