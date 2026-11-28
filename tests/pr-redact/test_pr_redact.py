"""Black-box test for dot_local/bin/executable_pr-redact: the one command that changes a merged or closed pull request's description, by exact replacement only.

Nothing reaches GitHub. `gh` is a stand-in on PATH: it serves one pull request from a JSON file, keeps the body a PATCH sends, and logs each call. Every private-looking
string here is made up (10.0.0.9, host.internal.example, /home/someone/work).

    python3 -m unittest discover -s tests/pr-redact -v
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_pr-redact"

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"args": args, "caller": os.environ.get("GH_CALLER")}) + "\n")
pr = json.load(open(os.environ["FAKE_PR"]))
down = os.environ["FAKE_PR"] + ".down"  # set when a failed write is followed by a GitHub that cannot be read
if "-X" not in args:
    if os.environ.get("FAKE_GET_FAIL") or os.path.exists(down):
        sys.stderr.write("HTTP 502\n"); sys.exit(1)
    print(json.dumps(pr)); sys.exit(0)
if os.environ.get("FAKE_PATCH_FAIL") == "before":
    sys.stderr.write("HTTP 403\n"); sys.exit(1)
if os.environ.get("FAKE_PATCH_FAIL") == "down":
    open(down, "w").close(); sys.stderr.write("HTTP 502\n"); sys.exit(1)
body = None
for a in args:
    if a.startswith("body=@"):
        body = open(a[len("body=@"):], encoding="utf-8", newline="").read()
open(os.environ["FAKE_POSTED"], "w", encoding="utf-8", newline="").write(body)
pr["body"] = body + os.environ.get("FAKE_STORE_EXTRA", "")  # a storage that changes the text
if os.environ.get("FAKE_PATCH_FAIL") == "after":  # the write lands, the answer is lost
    json.dump(pr, open(os.environ["FAKE_PR"], "w"))
    sys.stderr.write("HTTP 502\n"); sys.exit(1)
if os.environ.get("FAKE_PATCH_FAIL") == "other":  # the write fails and someone else's text is there
    pr["body"] = "someone else's text\n"
    json.dump(pr, open(os.environ["FAKE_PR"], "w"))
    sys.stderr.write("HTTP 502\n"); sys.exit(1)
json.dump(pr, open(os.environ["FAKE_PR"], "w"))
print(json.dumps(pr))
'''

BODY = ("Moves the check to host.internal.example.\n\n"
        "It listens on 10.0.0.9, and reads /home/someone/work/notes.md.\n"
        "Again host.internal.example, and 10.0.0.9 once more.\n")


class PrRedact(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="pr-redact-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "bin").mkdir()
        (self.dir / "bin/gh").write_text(FAKE_GH)
        (self.dir / "bin/gh").chmod(0o755)
        self.pr = self.dir / "pr.json"
        self.set_pr()
        self.state = self.dir / "state"
        self.rep = self.dir / "replacements.tsv"
        self.write_reps("host.internal.example\tan internal host\n10.0.0.9\ta private address\n")

    def set_pr(self, body=BODY, state="closed"):
        self.pr.write_text(json.dumps({"state": state, "merged": state == "closed", "body": body}))

    def write_reps(self, text):
        self.rep.write_text(text, encoding="utf-8")

    def run_cmd(self, *extra, repo="cartwmic/scratch", number="7", env=None, reps=True):
        args = ["--repo", repo, "--pr", number] + (["--replacements", str(self.rep)] if reps else []) + list(extra)
        full = {"PATH": "%s:%s" % (self.dir / "bin", os.environ["PATH"]), "HOME": str(self.dir), "XDG_STATE_HOME": str(self.state),
                "FAKE_LOG": str(self.dir / "calls.log"), "FAKE_PR": str(self.pr), "FAKE_POSTED": str(self.dir / "posted.md")}
        full.update(env or {})
        return subprocess.run([sys.executable, str(SCRIPT), *args], env=full, capture_output=True, text=True, timeout=60)

    def calls(self):
        log = self.dir / "calls.log"
        return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []

    def writes(self):
        return [c for c in self.calls() if "-X" in c["args"]]

    def records(self):
        log = self.state / "pr-redact/log.jsonl"
        return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []

    def stored(self):
        return json.loads(self.pr.read_text())["body"]

    def assertUnchanged(self):
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.stored(), BODY)

    def test_exact_replacements_are_the_only_change_and_are_posted_byte_for_byte(self):
        result = self.run_cmd()
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = BODY.replace("host.internal.example", "an internal host").replace("10.0.0.9", "a private address")
        self.assertEqual((self.dir / "posted.md").read_text(), expected)
        self.assertEqual(self.stored(), expected)
        self.assertIn("edited", result.stdout)
        self.assertNotIn("10.0.0.9", result.stdout + result.stderr)
        self.assertNotIn("internal.example", result.stdout + result.stderr)

    def test_each_neutral_phrase_replaces_its_string_and_any_other_phrase_is_refused(self):
        self.set_pr("Asked by Pat, rule 0a1b2c3d, in /work/session-1/notes. Pat again.\n")
        self.write_reps("Pat\tthe owner\nrule 0a1b2c3d\ta private id\n/work/session-1/notes\ta private folder\n")
        result = self.run_cmd()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stored(), "Asked by the owner, a private id, in a private folder. the owner again.\n")
        self.set_pr("Asked by Pat.\n")
        self.write_reps("Pat\tthe boss\n")
        self.assertEqual(self.run_cmd().returncode, 1)
        self.assertEqual(self.stored(), "Asked by Pat.\n")

    def test_the_call_goes_through_gh_api_with_the_caller_named_and_the_body_from_a_file(self):
        self.run_cmd()
        read, write = self.calls()
        self.assertEqual(read["args"], ["api", "repos/cartwmic/scratch/pulls/7"])
        self.assertEqual(write["args"][:4], ["api", "-X", "PATCH", "repos/cartwmic/scratch/pulls/7"])
        self.assertTrue(write["args"][5].startswith("body=@"))
        self.assertEqual(write["caller"], "pr-redact")

    def test_one_pass_a_phrase_is_not_searched_again_and_the_longer_string_wins(self):
        self.set_pr("see 10.0.0.9 and 10.0.0.9.5\n")
        self.write_reps("10.0.0.9.5\ta private address\n10.0.0.9\tan internal host\n")
        # the longer string is replaced whole; the shorter one matches only where the longer does not
        self.assertEqual(self.run_cmd().returncode, 0)
        self.assertEqual(self.stored(), "see an internal host and a private address\n")

    def test_a_string_that_only_occurs_inside_a_longer_listed_string_is_refused_as_missing(self):
        self.set_pr("see 10.0.0.9.5 only\n")
        self.write_reps("10.0.0.9.5\ta private address\n10.0.0.9\tan internal host\n")
        result = self.run_cmd()
        self.assertEqual(result.returncode, 1)
        self.assertIn("line 2", result.stderr)
        self.assertEqual(self.writes(), [])

    def test_a_phrase_outside_the_neutral_set_is_refused_before_github_is_read(self):
        self.write_reps("10.0.0.9\tsomething else\n")
        result = self.run_cmd()
        self.assertEqual(result.returncode, 1)
        self.assertIn("line 1", result.stderr)
        self.assertIn("neutral", result.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_string_that_is_missing_is_refused_and_named_by_line_only(self):
        self.write_reps("host.internal.example\tan internal host\n10.9.9.9\ta private address\n")
        result = self.run_cmd()
        self.assertEqual(result.returncode, 1)
        self.assertIn("line 2", result.stderr)
        self.assertNotIn("10.9.9.9", result.stdout + result.stderr)
        self.assertUnchanged()

    def test_allow_clean_excuses_only_the_case_where_every_string_is_absent(self):
        self.set_pr("Nothing private here.\n")
        self.assertEqual(self.run_cmd().returncode, 1)  # without the flag the missing strings are refused
        result = self.run_cmd("--allow-clean")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already clean", result.stdout)
        self.assertEqual(self.writes(), [])
        self.set_pr("only host.internal.example is here\n")  # one present, one absent: still a refusal, flag or not
        self.assertEqual(self.run_cmd("--allow-clean").returncode, 1)
        self.assertEqual(self.writes(), [])

    def test_an_open_pull_request_is_refused_and_pointed_to_pr_open(self):
        self.set_pr(state="open")
        result = self.run_cmd()
        self.assertEqual(result.returncode, 1)
        self.assertIn("pr-open --edit", result.stderr)
        self.assertEqual(self.writes(), [])

    def test_bad_replacement_lines_are_refused(self):
        for text, why in (("no tab here\n", "line 1"), ("\tan internal host\n", "empty"), ("an internal host\tan internal host\n", "neutral phrase"),
                          ("10.0.0.9\ta private address\n10.0.0.9\ta private address\n", "line 2"), ("", "no lines")):
            with self.subTest(text=text):
                self.write_reps(text)
                result = self.run_cmd()
                self.assertEqual(result.returncode, 1)
                self.assertIn(why, result.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_failed_read_changes_nothing_and_says_so(self):
        result = self.run_cmd(env={"FAKE_GET_FAIL": "1"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("nothing was changed", result.stderr)
        self.assertUnchanged()
        self.assertEqual(self.records()[-1]["outcome"], "failed")

    def test_a_failed_write_changes_nothing_and_says_so(self):
        result = self.run_cmd(env={"FAKE_PATCH_FAIL": "before"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("was not changed", result.stderr)
        self.assertEqual(self.stored(), BODY)
        self.assertEqual(self.records()[-1]["outcome"], "failed")
        self.assertEqual(self.records()[-1]["reason"], "github-write-failed")

    def test_a_write_that_landed_before_the_error_is_reported_as_edited(self):
        result = self.run_cmd(env={"FAKE_PATCH_FAIL": "after"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("edited (GitHub reported an error after storing it)", result.stdout)
        self.assertEqual(self.records()[-1]["outcome"], "edited")

    def test_a_failed_write_that_leaves_other_text_is_reported_as_unknown(self):
        result = self.run_cmd(env={"FAKE_PATCH_FAIL": "other"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not be confirmed", result.stderr)
        self.assertNotIn("was not changed", result.stderr)
        self.assertEqual(self.records()[-1]["reason"], "github-write-unknown")

    def test_a_failed_write_followed_by_an_unreadable_description_is_reported_as_unknown(self):
        result = self.run_cmd(env={"FAKE_PATCH_FAIL": "down"})
        self.assertEqual(result.returncode, 2)
        self.assertIn("could not be confirmed", result.stderr)
        self.assertNotIn("was not changed", result.stderr)
        self.assertEqual(self.records()[-1]["reason"], "github-write-unknown")

    def test_a_phrase_that_contains_a_later_string_is_not_searched_again(self):
        self.set_pr("a host b 10.0.0.9\n")
        self.write_reps("10.0.0.9\tan internal host\nhost\ta private address\n")
        self.assertEqual(self.run_cmd().returncode, 0)
        self.assertEqual(self.stored(), "a a private address b an internal host\n")  # a second pass over the first replacement would change its "host"

    def test_a_stored_body_that_is_not_the_computed_text_is_a_failure(self):
        result = self.run_cmd(env={"FAKE_STORE_EXTRA": " "})  # GitHub keeps one character more than was sent
        self.assertEqual(result.returncode, 2)
        self.assertIn("not the text pr-redact computed", result.stderr)
        self.assertEqual(self.records()[-1]["outcome"], "failed")
        self.assertEqual(self.records()[-1]["reason"], "stored-body-differs")

    def test_dry_run_posts_nothing_and_is_recorded(self):
        result = self.run_cmd("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dry run", result.stdout)
        self.assertUnchanged()
        self.assertEqual(self.records()[-1]["outcome"], "dry-run")

    def test_the_record_has_counts_and_hashes_and_never_a_string(self):
        self.assertEqual(self.run_cmd().returncode, 0)
        (rec,) = self.records()
        expected = BODY.replace("host.internal.example", "an internal host").replace("10.0.0.9", "a private address")
        self.assertEqual((rec["repo"], rec["pr"], rec["outcome"], rec["exit"], rec["reason"]), ("cartwmic/scratch", 7, "edited", 0, ""))
        self.assertEqual((rec["replacements"], rec["strings"]), (4, 2))  # two matches of each string
        self.assertEqual(rec["before_sha256"], hashlib.sha256(BODY.encode()).hexdigest())
        self.assertEqual(rec["after_sha256"], hashlib.sha256(expected.encode()).hexdigest())
        raw = (self.state / "pr-redact/log.jsonl").read_text()
        for private in ("10.0.0.9", "internal.example", "private address"):
            self.assertNotIn(private, raw)

    def test_a_refusal_is_recorded_with_a_fixed_reason(self):
        self.set_pr(state="open")
        self.run_cmd()
        (rec,) = self.records()
        self.assertEqual((rec["outcome"], rec["exit"], rec["reason"]), ("refused", 1, "pull-request-open"))

    def test_missing_or_bad_arguments_exit_2_and_help_writes_no_record(self):
        self.assertEqual(self.run_cmd(reps=False).returncode, 2)
        self.assertEqual(self.run_cmd(repo="nonsense").returncode, 2)
        self.assertEqual(self.run_cmd(number="x").returncode, 2)
        self.assertEqual(self.run_cmd("--surprise").returncode, 2)
        before = len(self.records())
        helped = subprocess.run([sys.executable, str(SCRIPT), "--help"], env={"PATH": os.environ["PATH"], "HOME": str(self.dir), "XDG_STATE_HOME": str(self.state)},
                                capture_output=True, text=True)
        self.assertEqual(helped.returncode, 0)
        self.assertIn("neutral phrases", helped.stdout)
        self.assertEqual(len(self.records()), before)


if __name__ == "__main__":
    unittest.main()
