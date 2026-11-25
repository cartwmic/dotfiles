"""Black-box test for dot_local/bin/executable_issue-open: the one command that expands an issue body's claim tokens and opens the issue.

Nothing reaches GitHub. `gh` and `claims` are stand-ins named by PATH and CLAIMS: the fake `claims expand FILE` replaces the token {{claim:aaaaaaaaaaaaaaaa}} with
"EXPANDED", refuses a body that holds {{claim:bbbbbbbbbbbbbbbb}} (exit 1, a reason on stderr), exits 3 for {{claim:cccccccccccccccc}} (it could not run), and ends every
output with a Sources footer, as the real one does. The real claims command is exercised in tests/profiles/test_gate_coverage.py (the wrapper) and in the PR's own run.

    python3 -m unittest discover -s tests/issue-open -v
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_issue-open"

FAKE_GH = r'''#!/bin/sh
printf 'gh' >> "$FAKE_LOG"; for a in "$@"; do printf ' [%s]' "$a" >> "$FAKE_LOG"; done; printf '\n' >> "$FAKE_LOG"
[ -z "${FAKE_GH_FAIL-}" ] || { echo "boom" >&2; exit 1; }
for a in "$@"; do [ "$prev" = --body-file ] && cp "$a" "$FAKE_POSTED"; prev=$a; done
printf 'GH_CALLER=%s\n' "$GH_CALLER" >> "$FAKE_LOG"
echo "${FAKE_GH_OUT-https://github.com/cartwmic/scratch/issues/9}"
'''

FAKE_CLAIMS = r'''#!/bin/sh
printf 'claims' >> "$FAKE_LOG"; for a in "$@"; do printf ' [%s]' "$a" >> "$FAKE_LOG"; done; printf '\n' >> "$FAKE_LOG"
[ "$1" = expand ] || exit 2
if grep -q 'claim:bbbbbbbbbbbbbbbb' "$2"; then echo "refused (stale-read): the lines moved" >&2; exit 1; fi
if grep -q 'claim:cccccccccccccccc' "$2"; then echo "claims: cannot read the store" >&2; exit 3; fi
sed 's/{{claim:aaaaaaaaaaaaaaaa}}/EXPANDED/g' "$2"
printf '\nSources: ran 1, read 0, live 0, said 0, none 0, unchecked 0; numerals outside tokens: 0\n'
'''


class IssueOpen(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="issue-open-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for name, text in (("gh", FAKE_GH), ("claims", FAKE_CLAIMS)):
            (self.bin / name).write_text(text, encoding="utf-8")
            (self.bin / name).chmod(0o755)
        self.log = self.dir / "calls.log"
        self.posted = self.dir / "posted.md"
        self.state = self.dir / "state"
        self.body = self.dir / "body.md"
        self.body.write_text("The count is {{claim:aaaaaaaaaaaaaaaa}}.\n")
        self.repo = self.dir / "work"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin", "https://github.com/cartwmic/scratch.git"], check=True)

    def run_it(self, *args, stdin=None, cwd=None, env_extra=None):
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.dir), "XDG_STATE_HOME": str(self.state), "TMPDIR": str(self.dir),
               "FAKE_LOG": str(self.log), "FAKE_POSTED": str(self.posted)}
        env.update(env_extra or {})
        return subprocess.run(["/bin/sh", str(SCRIPT), *args], input=stdin, capture_output=True, text=True, env=env, cwd=str(cwd or self.repo), timeout=60)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def records(self):
        path = self.state / "issue-open/log.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_creates_the_issue_from_the_expanded_body_and_prints_the_url(self):
        r = self.run_it("--title", "A title", "--body-file", str(self.body), "--repo", "cartwmic/scratch")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "https://github.com/cartwmic/scratch/issues/9"), r.stderr)
        self.assertIn("The count is EXPANDED.", self.posted.read_text())
        self.assertIn("Sources: ran 1", self.posted.read_text())
        self.assertNotIn("{{claim:", self.posted.read_text())
        gh = [c for c in self.calls() if c.startswith("gh")][0]
        self.assertTrue(gh.startswith("gh [issue] [create] [--repo] [cartwmic/scratch] [--title] [A title] [--body-file] ["), gh)
        self.assertIn("GH_CALLER=issue-open", self.calls())

    def test_claims_expand_reads_a_copy_of_the_body_not_the_original(self):
        self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch")
        expand = [c for c in self.calls() if c.startswith("claims")][0]
        self.assertTrue(expand.startswith("claims [expand] ["), expand)
        self.assertNotIn(str(self.body), expand)
        self.assertNotIn("--observed-only", expand)  # a typed claim shows as the author's word; it is loud, not refused

    def test_the_body_can_come_from_stdin(self):
        r = self.run_it("--title", "t", "--body-file", "-", "--repo", "cartwmic/scratch", stdin="Seen {{claim:aaaaaaaaaaaaaaaa}}\n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Seen EXPANDED", self.posted.read_text())

    def test_labels_assignees_a_milestone_and_a_project_are_passed_through_whole(self):
        r = self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch", "--label", "good first issue", "--label=bug", "--assignee", "cartwmic",
                        "--milestone", "v 1", "--project", "*")
        self.assertEqual(r.returncode, 0, r.stderr)
        gh = [c for c in self.calls() if c.startswith("gh")][0]
        for part in ("[--label] [good first issue]", "[--label] [bug]", "[--assignee] [cartwmic]", "[--milestone] [v 1]", "[--project] [*]"):
            self.assertIn(part, gh)

    def test_a_refused_claim_creates_nothing_and_says_why(self):
        self.body.write_text("Stale {{claim:bbbbbbbbbbbbbbbb}}\n")
        r = self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch")
        self.assertEqual(r.returncode, 1)
        self.assertIn("refused (stale-read): the lines moved", r.stderr)
        self.assertIn("nothing was created", r.stderr.splitlines()[-1])
        self.assertTrue(r.stderr.splitlines()[-1].startswith("[issue-open] ERROR: "))
        self.assertEqual([c for c in self.calls() if c.startswith("gh")], [])
        self.assertEqual([x["outcome"] for x in self.records()], ["refused"])

    def test_a_claims_command_that_cannot_run_is_a_failure_not_a_refusal(self):
        self.body.write_text("{{claim:cccccccccccccccc}}\n")
        r = self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch")
        self.assertEqual(r.returncode, 2)
        self.assertEqual([c for c in self.calls() if c.startswith("gh")], [])
        self.assertEqual([x["outcome"] for x in self.records()], ["failed"])

    def test_a_missing_claims_command_creates_nothing(self):
        r = self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch", env_extra={"CLAIMS": "no-such-claims"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("no-such-claims is not on PATH", r.stderr)
        self.assertEqual([c for c in self.calls() if c.startswith("gh")], [])

    def test_dry_run_prints_the_expanded_body_and_the_command_and_creates_nothing(self):
        r = self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch", "--label", "bug", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("The count is EXPANDED.", r.stdout)
        self.assertIn("gh 'issue' 'create' '--repo' 'cartwmic/scratch' '--title' 't' '--body-file'", r.stdout)
        self.assertIn("'--label' 'bug'", r.stdout)
        self.assertEqual([c for c in self.calls() if c.startswith("gh")], [])
        self.assertEqual([x["outcome"] for x in self.records()], ["dry-run"])

    def test_dry_run_still_refuses_a_bad_claim(self):
        self.body.write_text("{{claim:bbbbbbbbbbbbbbbb}}\n")
        r = self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch", "--dry-run")
        self.assertEqual(r.returncode, 1)

    def test_a_claim_token_in_the_title_is_refused_before_anything_runs(self):
        r = self.run_it("--title", "Count {{claim:aaaaaaaaaaaaaaaa}}", "--body-file", str(self.body), "--repo", "cartwmic/scratch")
        self.assertEqual(r.returncode, 2)
        self.assertIn("title holds a claim token", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_arguments_that_would_skip_the_check_are_refused(self):
        for extra in (["--body", "typed"], ["--fill"], ["--web"], ["--editor"], ["--template", "t"], ["--recover", "r"], ["-b", "x"]):
            with self.subTest(extra=extra):
                r = self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch", *extra)
                self.assertEqual(r.returncode, 2)
                self.assertIn("unknown argument", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_title_and_a_body_file_are_required_and_the_file_must_have_text(self):
        self.assertEqual(self.run_it("--body-file", str(self.body)).returncode, 2)
        self.assertEqual(self.run_it("--title", "t").returncode, 2)
        empty = self.dir / "empty.md"
        empty.write_text("")
        r = self.run_it("--title", "t", "--body-file", str(empty), "--repo", "cartwmic/scratch")
        self.assertEqual(r.returncode, 2)
        self.assertIn("missing or empty", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_the_repo_defaults_to_the_origin_of_the_directory_and_says_so(self):
        r = self.run_it("--title", "t", "--body-file", str(self.body))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("repo cartwmic/scratch: taken from the origin", r.stderr)
        self.assertIn("[--repo] [cartwmic/scratch]", [c for c in self.calls() if c.startswith("gh")][0])

    def test_gh_failing_or_printing_no_url_is_a_failure(self):
        r = self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch", env_extra={"FAKE_GH_FAIL": "1"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("gh issue create failed", r.stderr)
        r = self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch", env_extra={"FAKE_GH_OUT": "created"})
        self.assertEqual(r.returncode, 2)
        self.assertIn("gave no issue URL", r.stderr)

    def test_every_run_writes_one_log_line_and_help_writes_none(self):
        self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch")
        records = self.records()
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]["outcome"], records[0]["exit"], records[0]["repo"], records[0]["mode"]), ("created", 0, "cartwmic/scratch", "create"))
        self.assertEqual(self.run_it("--help").returncode, 0)
        self.assertEqual(len(self.records()), 1)

    def test_temporary_copies_are_removed_on_success_and_on_refusal(self):
        self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch")
        self.body.write_text("{{claim:bbbbbbbbbbbbbbbb}}\n")
        self.run_it("--title", "t", "--body-file", str(self.body), "--repo", "cartwmic/scratch")
        self.assertEqual([p.name for p in self.dir.glob("issue-open-body.*")] + [p.name for p in self.dir.glob("issue-open-expanded.*")], [])


if __name__ == "__main__":
    unittest.main()
