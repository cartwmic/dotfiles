"""Black-box test for dot_local/bin/executable_pr-open: the one command that checks a PR description and opens (or edits) the PR.

Nothing reaches GitHub. The repo is a scratch git repository with a bare local `origin`. `gh`, `pr-body-check` and `pr-record` are stand-ins on PATH that
write their arguments to a log; the fake check refuses a body that holds the word REFUSEME and says so on stdout, as the real one does.

    python3 -m unittest discover -s tests/pr-open -v
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_pr-open"
LIMITS_CHECK = ROOT / "dot_local/share/agent-harness/bin/executable_known-limits-check"  # the real check, not a stand-in

FAKE_GH = r'''#!/bin/sh
printf 'gh' >> "$FAKE_LOG"; for a in "$@"; do printf ' [%s]' "$a" >> "$FAKE_LOG"; done; printf '\n' >> "$FAKE_LOG"
case "$1 $2" in
  "pr create") for a in "$@"; do [ "$prev" = --body-file ] && cp "$a" "$FAKE_POSTED"; prev=$a; done
               [ -z "${FAKE_GH_FAIL-}" ] || { echo "boom" >&2; exit 1; }
               echo "https://github.com/cartwmic/scratch/pull/42" ;;
  "api -X") for a in "$@"; do case $a in body=@*) cp "${a#body=@}" "$FAKE_POSTED" ;; esac; done
            echo "https://github.com/cartwmic/scratch/pull/7" ;;
  "api repos/"*) echo "${FAKE_PR_INFO:-open false}" ;;
esac
'''

FAKE_CHECK = r'''#!/bin/sh
printf 'pr-body-check' >> "$FAKE_LOG"; for a in "$@"; do printf ' [%s]' "$a" >> "$FAKE_LOG"; done; printf '\n' >> "$FAKE_LOG"
while [ $# -gt 0 ]; do [ "$1" = --body-file ] && body=$2; shift; done
if grep -q REFUSEME "$body"; then echo "pr-body-check: FAIL $body (bookkeeping in the description)"; exit 1; fi
echo "pr-body-check: OK $body"
'''

FAKE_RECORD = r'''#!/bin/sh
echo "${FAKE_RECORD_DIR:-/records}/$2.md"
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
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.dir), "FAKE_LOG": str(self.log), "FAKE_POSTED": str(self.posted),
               "KNOWN_LIMITS_CHECK": str(LIMITS_CHECK)}
        env.update(extra_env or {})
        return subprocess.run(["sh", str(SCRIPT), *args], cwd=self.repo, env=env, input=stdin, capture_output=True, text=True, timeout=60)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def patches(self):
        return [c for c in self.calls() if "[PATCH]" in c]

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
        self.assertTrue(lines[0].startswith("known-limits:"))  # the limits check runs first
        self.assertTrue(lines[1].startswith("pr-body-check: OK"))  # then the body check's own pass line
        self.assertEqual(lines[2], "https://github.com/cartwmic/scratch/pull/42")
        self.assertIn("/records/cartwmic/scratch#42.md", lines[3])  # where the agent record goes
        self.assertIn("pr-body-check cartwmic/scratch 42 --skip-intent-review", lines[4])  # the form that reads the record; the --body-file form does not
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

    def test_a_branch_cut_from_origin_main_is_pushed_under_its_own_name(self):
        self.git(self.repo, "checkout", "-q", "-b", "cut", "--track", "origin/main")  # its upstream is origin/main, which a bare `git push` refuses
        (self.repo / "a.txt").write_text("cut\n")
        self.git(self.repo, "commit", "-q", "-am", "on cut")
        result = self.run_open("--title", "T", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cut", self.remote_branches())
        self.assertEqual(self.git(self.repo, "rev-parse", "--abbrev-ref", "@{u}").strip(), "origin/cut")

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

    def test_edit_checks_then_reads_the_state_then_patches_the_body_through_gh_api(self):
        result = self.run_open("--edit", "7", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], "https://github.com/cartwmic/scratch/pull/7")
        calls = self.calls()
        self.assertTrue(calls[0].startswith("pr-body-check"))
        self.assertIn("[api] [repos/cartwmic/scratch/pulls/7]", calls[1])  # the state is read before the PATCH
        self.assertEqual(self.patches(), [calls[2]])
        self.assertIn("[api] [-X] [PATCH] [repos/cartwmic/scratch/pulls/7]", calls[2])
        self.assertNotIn("[pr] [edit]", calls[2])
        self.assertEqual(self.posted.read_text(), self.body.read_text())

    def test_an_open_pr_is_still_edited(self):
        result = self.run_open("--edit", "7", "--body-file", str(self.body), extra_env={"FAKE_PR_INFO": "open false"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.patches()), 1)
        self.assertEqual(self.posted.read_text(), self.body.read_text())

    def test_a_merged_pr_is_refused_and_not_patched(self):
        result = self.run_open("--edit", "7", "--body-file", str(self.body), extra_env={"FAKE_PR_INFO": "closed true"})
        self.assertEqual(result.returncode, 2, result.stderr)
        last = result.stderr.strip().splitlines()[-1]
        self.assertTrue(last.startswith("[pr-open] ERROR: cartwmic/scratch#7 is merged"), last)
        self.assertIn("If you meant another repo, pass --repo OWNER/REPO", last)
        self.assertEqual(self.patches(), [])
        self.assertFalse(self.posted.exists())

    def test_a_closed_pr_is_refused_and_not_patched(self):
        result = self.run_open("--edit", "7", "--body-file", str(self.body), extra_env={"FAKE_PR_INFO": "closed false"})
        self.assertEqual(result.returncode, 2, result.stderr)
        last = result.stderr.strip().splitlines()[-1]
        self.assertTrue(last.startswith("[pr-open] ERROR: cartwmic/scratch#7 is closed"), last)
        self.assertIn("If you meant another repo, pass --repo OWNER/REPO", last)
        self.assertEqual(self.patches(), [])
        self.assertFalse(self.posted.exists())

    def test_the_repo_taken_from_origin_is_named_on_stderr_in_both_modes(self):
        for args in (("--edit", "7"), ("--title", "T")):
            with self.subTest(args=args):
                result = self.run_open(*args, "--body-file", str(self.body))
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = [line for line in result.stderr.splitlines() if "taken from the origin of this directory" in line]
                self.assertEqual(len(lines), 1, result.stderr)
                self.assertIn("cartwmic/scratch", lines[0])

    def test_no_origin_line_when_repo_is_given(self):
        for args in (("--edit", "7"), ("--title", "T")):
            with self.subTest(args=args):
                result = self.run_open(*args, "--body-file", str(self.body), "--repo", "cartwmic/scratch")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("taken from the origin", result.stderr)

    def test_edit_with_a_title_sets_it_too(self):
        self.run_open("--edit", "7", "--body-file", str(self.body), "--title", "New title")
        self.assertIn("[-f] [title=New title]", self.patches()[0])

    def test_a_refused_body_is_not_patched(self):
        self.body.write_text("REFUSEME\n")
        result = self.run_open("--edit", "7", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 1)
        self.assertIn("pr-body-check: FAIL", result.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith("gh")])

    def test_edit_works_outside_a_git_repo_with_repo_named(self):
        elsewhere = self.dir / "elsewhere"
        elsewhere.mkdir()
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.dir), "FAKE_LOG": str(self.log), "FAKE_POSTED": str(self.posted),
               "KNOWN_LIMITS_CHECK": str(LIMITS_CHECK)}
        result = subprocess.run(["sh", str(SCRIPT), "--edit", "7", "--repo", "cartwmic/other", "--body-file", str(self.body)],
                                cwd=elsewhere, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("repos/cartwmic/other/pulls/7", self.patches()[0])

    # -- known-limits-check runs on the body at create and at edit, before anything else ------------------------------------------------

    LABELLED = "What changed.\n\nLimits: the font has no emoji.\n\nProven: ran it.\n"  # the past mistake: a limit outside "## Known limits"
    PERMANENT = "What changed.\n\n## Known limits\n- The font has no emoji, accepted as permanent.\n\n## Proven\nran it.\n"

    def test_a_limit_outside_the_section_is_refused_on_create_before_anything_runs(self):
        self.body.write_text(self.LABELLED)
        result = self.run_open("--title", "T", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 1)
        self.assertIn('"Limits" written as a label', result.stderr)  # the check's own line says which line to fix
        last = result.stderr.strip().splitlines()[-1]
        self.assertIn("[pr-open] ERROR", last)
        self.assertIn("'## Known limits'", last)
        self.assertIn("nothing was created", last)
        self.assertEqual(self.calls(), [])  # not even pr-body-check ran
        self.assertNotIn("feature", self.remote_branches())

    def test_a_limit_outside_the_section_is_refused_on_edit_before_the_pr_is_read(self):
        self.body.write_text(self.LABELLED)
        result = self.run_open("--edit", "7", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 1)
        self.assertIn("nothing was changed", result.stderr)
        self.assertEqual(self.calls(), [])  # no pr-body-check, no state read, no PATCH

    def test_the_phrase_outside_the_section_is_refused(self):
        self.body.write_text("What changed.\n\nZero change on the runner (see Known limits).\n\n## Known limits\nNone\n")
        result = self.run_open("--title", "T", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 1)
        self.assertIn('"known limit" appears outside', result.stderr)

    def test_a_decision_id_in_a_limit_is_refused(self):
        self.body.write_text("What.\n\n## Known limits\n- A gap, accepted as permanent (decision #4).\n")
        result = self.run_open("--title", "T", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Permanent limits: #ID", result.stderr)

    def test_a_permanent_limit_opens_the_pr_with_the_record_pending(self):
        self.body.write_text(self.PERMANENT)
        result = self.run_open("--title", "T", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("record not checked (pending)", result.stdout)
        self.assertEqual(self.posted.read_text(), self.PERMANENT)

    def test_a_body_with_no_limits_section_passes_the_check(self):
        result = self.run_open("--title", "T", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 0, result.stderr)

    def record_dir(self, text):
        records = self.dir / "records"
        records.mkdir(exist_ok=True)
        if text is not None:
            (records / "cartwmic" ).mkdir(exist_ok=True)
            (records / "cartwmic/scratch#7.md").write_text(text)
        return {"FAKE_RECORD_DIR": str(records)}

    def test_edit_reads_the_record_when_it_exists(self):
        self.body.write_text(self.PERMANENT)
        env = self.record_dir("Permanent limits: #5989\nDecisions: #5989\n")
        result = self.run_open("--edit", "7", "--body-file", str(self.body), extra_env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("backed by the record", result.stdout)
        self.assertEqual(len(self.patches()), 1)

    def test_edit_refuses_a_record_that_lacks_the_permanent_line(self):
        self.body.write_text(self.PERMANENT)
        env = self.record_dir("Decisions: #5989\n")
        result = self.run_open("--edit", "7", "--body-file", str(self.body), extra_env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn('no "Permanent limits: #ID" line', result.stderr)
        self.assertEqual(self.patches(), [])

    def test_edit_with_no_record_file_yet_passes_with_it_pending(self):
        self.body.write_text(self.PERMANENT)
        env = self.record_dir(None)
        result = self.run_open("--edit", "7", "--body-file", str(self.body), extra_env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("record not checked (pending)", result.stdout)

    def limits_log(self):
        log = self.dir / ".local/state/known-limits-check/log.jsonl"  # the check's own log; HOME is the scratch directory
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def test_a_refusal_log_line_says_why_and_on_create_which_branch(self):
        self.body.write_text(self.LABELLED)
        self.run_open("--title", "T", "--body-file", str(self.body))
        (record,) = self.limits_log()
        self.assertEqual(record["outcome"], "refused")
        self.assertEqual(record["context"], {"caller": "pr-open", "mode": "create", "repo": "cartwmic/scratch", "head": "feature"})
        (problem,) = record["problems"]
        self.assertEqual((problem["rule"], problem["line"]), ("label", 3))
        self.assertIn('"Limits" written as a label', problem["message"])

    def test_an_edit_log_line_carries_the_pr_and_the_record_mode(self):
        self.body.write_text(self.LABELLED)
        self.run_open("--edit", "7", "--body-file", str(self.body))
        self.body.write_text(self.PERMANENT)
        self.run_open("--edit", "7", "--body-file", str(self.body))
        refused, ok = self.limits_log()
        self.assertEqual((refused["outcome"], refused["context"]["pr"], refused["context"]["mode"], "head" in refused["context"]), ("refused", "7", "edit", False))
        self.assertEqual((ok["outcome"], ok["record"], ok["permanent"], ok["problems"]), ("ok", "pending", 1, []))

    def test_an_unwritable_log_never_changes_the_outcome(self):
        (self.dir / ".local").write_text("a file where the state directory would be\n")
        result = self.run_open("--title", "T", "--body-file", str(self.body))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_a_missing_known_limits_check_is_a_could_not_run_error(self):
        result = self.run_open("--title", "T", "--body-file", str(self.body), extra_env={"KNOWN_LIMITS_CHECK": str(self.dir / "absent")})
        self.assertEqual(result.returncode, 2)
        self.assertIn("known-limits-check is not at", result.stderr)
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
