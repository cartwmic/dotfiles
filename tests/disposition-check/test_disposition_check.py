"""Black-box test for dot_local/share/agent-harness/bin/executable_disposition-check.

The fixture is the past mistake, written generically: a review finding whose fix is an artifact outside
the diff (a ticket, a doc, a config change elsewhere) was marked fixed with only a commit sha, so the log
looked fixed while nothing in it could be checked. The check must refuse that disposition and accept the
corrected one. The git repo is a scratch one; nothing here writes inside the dotfiles checkout.

    python3 -m unittest discover -s tests/disposition-check -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/share/agent-harness/bin/executable_disposition-check"

OUTSIDE = "0123456789abcdef0123456789abcdef01234567"


def disposition(fid, **kw):
    rec = {"event": "disposition", "at": "2026-11-19T00:00:00Z", "id": fid, "outcome": "fixed"}
    rec.update(kw)
    return json.dumps(rec)


class DispositionCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.runlog = str(Path(self.tmp) / "run-log" / "log.jsonl")
        self.repo = Path(self.tmp) / "repo"
        self.repo.mkdir()
        self.git("init", "-q", ".")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        (self.repo / "f").write_text("root\n")
        self.git("add", "f")
        self.git("commit", "-qm", "root")
        self.root = self.git("rev-parse", "HEAD").stdout.strip()
        (self.repo / "f").write_text("base\n")
        self.git("commit", "-qam", "base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        (self.repo / "f").write_text("head\n")
        self.git("commit", "-qam", "fix")
        self.head = self.git("rev-parse", "HEAD").stdout.strip()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        done = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def log(self, *lines, name="findings.jsonl"):
        p = Path(self.tmp) / name
        p.write_text("\n".join(lines) + "\n")
        return str(p)

    def run_check(self, *args):
        # the run log goes to a scratch file, never to the real state folder
        env = dict(os.environ, DISPOSITION_CHECK_LOG=self.runlog)
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=30, env=env)

    def run_records(self):
        p = Path(self.runlog)
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def test_the_past_mistake_fails_a_sha_outside_the_change(self):
        log = self.log(disposition("r1.f1", sha=OUTSIDE))
        out = self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("r1.f1", out.stderr)
        self.assertIn("artifact", out.stderr)

    def test_the_corrected_disposition_names_the_artifact(self):
        log = self.log(disposition("r1.f1", sha=OUTSIDE, artifact="docs/follow-up.md"))
        self.assertEqual(self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log).returncode, 0)

    def test_an_artifact_alone_passes(self):
        log = self.log(disposition("r1.f1", artifact="PROJ-123"))
        self.assertEqual(self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log).returncode, 0)

    def test_a_sha_of_the_change_passes_without_an_artifact(self):
        log = self.log(disposition("r1.f1", sha=self.head))
        self.assertEqual(self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log).returncode, 0)

    def test_a_sha_at_or_before_the_base_is_not_the_change(self):
        log = self.log(disposition("r1.f1", sha=self.base))
        out = self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("not part of the change", out.stderr)

    def test_without_a_base_a_sha_reachable_from_the_head_passes(self):
        log = self.log(disposition("r1.f1", sha=self.root))
        self.assertEqual(self.run_check("--head", self.head, "--repo", str(self.repo), log).returncode, 0)

    def test_a_fixed_disposition_with_neither_field_is_refused_even_without_a_head(self):
        log = self.log(disposition("r1.f1"))
        out = self.run_check(log)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("neither a sha nor an artifact", out.stderr)

    def test_without_a_head_only_the_shape_is_checked(self):
        log = self.log(disposition("r1.f1", sha=OUTSIDE))
        self.assertEqual(self.run_check(log).returncode, 0)

    def test_the_latest_disposition_wins_a_corrected_fixed_passes(self):
        log = self.log(
            disposition("r1.f1", sha=OUTSIDE),
            disposition("r1.f1", sha=OUTSIDE, artifact="PROJ-123"),
        )
        self.assertEqual(self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log).returncode, 0)

    def test_the_latest_disposition_wins_a_later_rejected_passes(self):
        log = self.log(
            disposition("r1.f1", sha=OUTSIDE),
            json.dumps({"event": "disposition", "at": "t", "id": "r1.f1", "outcome": "rejected", "reason": "the triage test it failed"}),
        )
        self.assertEqual(self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log).returncode, 0)

    def test_the_latest_disposition_wins_a_later_sha_only_fixed_fails(self):
        log = self.log(
            disposition("r1.f1", artifact="PROJ-123"),
            disposition("r1.f1", sha=OUTSIDE),
        )
        out = self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("r1.f1", out.stderr)

    def test_other_events_and_other_fields_are_ignored(self):
        log = self.log(
            json.dumps({"event": "round", "at": "t", "round": 1, "review_round": 1, "stage": "diff",
                        "verdict": "fail", "head": self.head, "reviewer": "r", "session": "s"}),
            json.dumps({"event": "disposition", "at": "t", "id": "r1.f1", "outcome": "rejected", "reason": "the triage test it failed"}),
            json.dumps({"event": "disposition", "at": "t", "id": "r1.f2", "outcome": "residual", "accepted_by": "who"}),
        )
        self.assertEqual(self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log).returncode, 0)

    def test_a_damaged_line_is_warned_about_with_its_line_number(self):
        log = self.log(
            disposition("r1.f1", artifact="PROJ-123"),
            "{not json",
        )
        out = self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("warning", out.stderr)
        self.assertIn("findings.jsonl:2 is not valid JSON", out.stderr)

    def test_stdin_is_read_when_the_log_is_a_dash(self):
        text = disposition("r1.f1", sha=OUTSIDE) + "\n"
        out = subprocess.run([sys.executable, str(SCRIPT), "--head", self.head, "--base", self.base,
                              "--repo", str(self.repo), "-"],
                             capture_output=True, text=True, timeout=30, input=text,
                             env=dict(os.environ, DISPOSITION_CHECK_LOG=self.runlog))
        self.assertEqual(out.returncode, 1, out.stderr)

    def test_an_unresolvable_head_is_an_error(self):
        log = self.log(disposition("r1.f1", sha=OUTSIDE))
        out = self.run_check("--head", "deadbeef", "--repo", str(self.repo), log)
        self.assertEqual(out.returncode, 2, out.stderr)
    # A rebase, amend, squash or force-push removes the sha a driver recorded while the fix stays in the change.
    # The scratch history: root -> base -> head (the setUp one). Each case builds a rewritten branch beside it.

    def commit_file(self, name, text, message):
        (self.repo / name).write_text(text)
        self.git("add", name)
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def run_rewritten(self, sha, head, base):
        log = self.log(disposition("r1.f1", sha=sha))
        return self.run_check("--head", head, "--base", base, "--repo", str(self.repo), log)

    def fix_on_a_branch(self):
        """base -> fix (touches g only), then the branch is rewritten three ways by the tests."""
        self.git("checkout", "-q", "-b", "work", self.base)
        return self.commit_file("g", "fix\n", "the fix")

    def test_a_sha_a_rebase_removed_passes_when_its_change_is_in_the_head(self):
        fix = self.fix_on_a_branch()
        self.git("checkout", "-q", "-b", "moved", self.head)  # the target branch moved on: head is the new base
        new_base = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("cherry-pick", fix)
        rebased = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(fix, rebased)
        out = self.run_rewritten(fix, rebased, new_base)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("no longer reachable from the head", out.stdout)
        self.assertIn("r1.f1", out.stdout)

    def test_a_sha_an_amend_removed_passes(self):
        fix = self.fix_on_a_branch()
        self.git("commit", "-q", "--amend", "-m", "the fix, reworded")
        amended = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertNotEqual(fix, amended)
        self.assertEqual(self.run_rewritten(fix, amended, self.base).returncode, 0)

    def test_a_sha_a_squash_folded_into_a_larger_commit_passes(self):
        fix = self.fix_on_a_branch()
        self.commit_file("h", "more\n", "more work")
        self.git("reset", "-q", "--soft", self.base)
        self.git("commit", "-qm", "squashed")
        squashed = self.git("rev-parse", "HEAD").stdout.strip()
        out = self.run_rewritten(fix, squashed, self.base)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_a_sha_whose_fix_a_later_commit_reverted_is_still_refused(self):
        fix = self.fix_on_a_branch()
        self.git("checkout", "-q", "-b", "other", self.base)
        self.commit_file("g", "fix\n", "the fix again")
        self.git("revert", "--no-edit", "HEAD")
        reverted = self.git("rev-parse", "HEAD").stdout.strip()
        out = self.run_rewritten(fix, reverted, self.base)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("not an ancestor of the head", out.stderr)
        self.assertIn("record the sha of the commit in base..head that carries it", out.stderr)

    def test_a_sha_whose_lines_a_later_commit_edited_again_is_still_refused(self):
        fix = self.fix_on_a_branch()
        self.git("checkout", "-q", "-b", "other", self.base)
        self.commit_file("g", "fix\n", "the fix again")
        edited = self.commit_file("g", "fix, then reworked\n", "rework")
        out = self.run_rewritten(fix, edited, self.base)
        self.assertEqual(out.returncode, 1, out.stderr)

    def test_a_sha_whose_change_is_already_in_the_base_is_not_the_change(self):
        fix = self.fix_on_a_branch()
        self.git("checkout", "-q", "-b", "other", self.base)
        in_base = self.commit_file("g", "fix\n", "the same fix, landed on the target branch")
        head = self.commit_file("h", "unrelated\n", "unrelated work")
        out = self.run_rewritten(fix, head, in_base)
        self.assertEqual(out.returncode, 1, out.stderr)

    def test_an_unrelated_commit_outside_the_change_is_refused(self):
        stranger = self.fix_on_a_branch()  # never reaches the head below
        out = self.run_rewritten(stranger, self.head, self.base)
        self.assertEqual(out.returncode, 1, out.stderr)

    def test_without_a_base_a_removed_sha_is_still_refused(self):
        fix = self.fix_on_a_branch()
        self.git("commit", "-q", "--amend", "-m", "reworded")
        amended = self.git("rev-parse", "HEAD").stdout.strip()
        log = self.log(disposition("r1.f1", sha=fix))
        out = self.run_check("--head", amended, "--repo", str(self.repo), log)
        self.assertEqual(out.returncode, 1, out.stderr)

    def test_a_merge_commit_sha_is_never_mapped(self):
        fix = self.fix_on_a_branch()
        self.git("checkout", "-q", "-b", "side", self.base)
        self.commit_file("k", "side\n", "side")
        self.git("merge", "-q", "--no-ff", "-m", "merge", fix)
        merge = self.git("rev-parse", "HEAD").stdout.strip()
        self.git("checkout", "-q", "-b", "squashed", self.base)
        self.git("merge", "-q", "--squash", merge)
        self.git("commit", "-qm", "squashed")
        squashed = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(self.run_rewritten(merge, squashed, self.base).returncode, 1)

    # The run log: a mapped pass turns a refusal into a pass, so each one leaves a JSON line that survives the terminal.

    def test_a_mapped_pass_writes_one_log_line_naming_item_finding_sha_and_head(self):
        fix = self.fix_on_a_branch()
        self.git("commit", "-q", "--amend", "-m", "reworded")
        amended = self.git("rev-parse", "HEAD").stdout.strip()
        out = self.run_rewritten(fix, amended, self.base)
        self.assertEqual(out.returncode, 0, out.stderr)
        (rec,) = self.run_records()
        self.assertEqual(rec["tool"], "disposition-check")
        self.assertEqual(rec["outcome"], "mapped-pass")
        self.assertEqual(rec["item"], os.path.basename(self.tmp))
        self.assertEqual((rec["finding"], rec["sha"], rec["head"]), ("r1.f1", fix, amended))
        self.assertEqual(rec["base"], self.base)
        self.assertRegex(rec["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_a_refusal_writes_one_log_line_with_its_reason(self):
        log = self.log(disposition("r1.f1", sha=OUTSIDE), disposition("r1.f2"))
        out = self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log)
        self.assertEqual(out.returncode, 1, out.stderr)
        by_finding = {r["finding"]: r for r in self.run_records()}
        self.assertEqual({r["outcome"] for r in by_finding.values()}, {"refused"})
        self.assertIn("no commit", by_finding["r1.f1"]["reason"])
        self.assertEqual(by_finding["r1.f2"]["reason"], "no-sha-no-artifact")

    def test_a_pass_without_mapping_writes_no_log_line(self):
        log = self.log(disposition("r1.f1", sha=self.head), disposition("r1.f2", artifact="PROJ-1"))
        self.assertEqual(self.run_check("--head", self.head, "--base", self.base, "--repo", str(self.repo), log).returncode, 0)
        self.assertEqual(self.run_records(), [])

    def test_no_log_writes_nothing_and_an_unwritable_log_never_changes_the_result(self):
        fix = self.fix_on_a_branch()
        self.git("commit", "-q", "--amend", "-m", "reworded")
        amended = self.git("rev-parse", "HEAD").stdout.strip()
        log = self.log(disposition("r1.f1", sha=fix))
        args = ("--head", amended, "--base", self.base, "--repo", str(self.repo))
        self.assertEqual(self.run_check(*args, "--no-log", log).returncode, 0)
        self.assertEqual(self.run_records(), [])
        blocked = Path(self.tmp) / "blocked"
        blocked.write_text("a file, not a folder\n")
        self.assertEqual(self.run_check(*args, "--log", str(blocked / "log.jsonl"), log).returncode, 0)

    def test_the_usage_line_names_the_log_flags(self):
        out = self.run_check()
        self.assertEqual(out.returncode, 2)
        self.assertIn("[--log FILE | --no-log]", out.stderr)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.run_check().returncode, 2)
        self.assertEqual(self.run_check("--repo", "/nonexistent", "--head", self.head, "x.jsonl").returncode, 2)


if __name__ == "__main__":
    unittest.main()
