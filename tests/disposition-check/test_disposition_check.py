"""Black-box test for dot_local/share/agent-harness/bin/executable_disposition-check.

The fixture is the past mistake, written generically: a review finding whose fix is an artifact outside
the diff (a ticket, a doc, a config change elsewhere) was marked fixed with only a commit sha, so the log
looked fixed while nothing in it could be checked. The check must refuse that disposition and accept the
corrected one. The git repo is a scratch one; nothing here writes inside the dotfiles checkout.

    python3 -m unittest discover -s tests/disposition-check -v
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/share/agent-harness/bin/executable_disposition-check"


def disposition(fid, **kw):
    rec = {"event": "disposition", "at": "2026-11-19T00:00:00Z", "id": fid, "outcome": "fixed"}
    rec.update(kw)
    return json.dumps(rec)


class DispositionCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = Path(self.tmp) / "repo"
        self.repo.mkdir()
        self.git("init", "-q", ".")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        (self.repo / "f").write_text("a\n")
        self.git("add", "f")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").stdout.strip()
        (self.repo / "f").write_text("b\n")
        self.git("commit", "-qam", "fix")
        self.head = self.git("rev-parse", "HEAD").stdout.strip()
        self.outside = "0123456789abcdef0123456789abcdef01234567"

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
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, timeout=30)

    def test_the_past_mistake_fails_a_sha_outside_the_change(self):
        log = self.log(disposition("r1.f1", sha=self.outside))
        out = self.run_check("--head", self.head, "--repo", str(self.repo), log)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("r1.f1", out.stderr)
        self.assertIn("artifact", out.stderr)

    def test_the_corrected_disposition_names_the_artifact(self):
        log = self.log(disposition("r1.f1", sha=self.outside, artifact="docs/follow-up.md"))
        self.assertEqual(self.run_check("--head", self.head, "--repo", str(self.repo), log).returncode, 0)

    def test_an_artifact_alone_passes(self):
        log = self.log(disposition("r1.f1", artifact="PROJ-123"))
        self.assertEqual(self.run_check("--head", self.head, "--repo", str(self.repo), log).returncode, 0)

    def test_a_sha_in_the_change_passes_without_an_artifact(self):
        for sha in (self.base, self.head):
            with self.subTest(sha=sha[:12]):
                log = self.log(disposition("r1.f1", sha=sha))
                self.assertEqual(self.run_check("--head", self.head, "--repo", str(self.repo), log).returncode, 0)

    def test_a_fixed_disposition_with_neither_field_is_refused_even_without_a_head(self):
        log = self.log(disposition("r1.f1"))
        out = self.run_check(log)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("neither a sha nor an artifact", out.stderr)

    def test_without_a_head_only_the_shape_is_checked(self):
        log = self.log(disposition("r1.f1", sha=self.outside))
        self.assertEqual(self.run_check(log).returncode, 0)

    def test_other_events_and_broken_lines_are_ignored(self):
        log = self.log(
            json.dumps({"event": "round", "at": "t", "round": 1, "review_round": 1, "stage": "diff",
                        "verdict": "fail", "head": self.head, "reviewer": "r", "session": "s"}),
            "not json at all",
            disposition("r1.f1", sha=self.outside, artifact="PROJ-123"),
        )
        self.assertEqual(self.run_check("--head", self.head, "--repo", str(self.repo), log).returncode, 0)

    def test_a_rejected_or_residual_disposition_is_not_checked(self):
        log = self.log(
            json.dumps({"event": "disposition", "at": "t", "id": "r1.f1", "outcome": "rejected", "reason": "the triage test it failed"}),
            json.dumps({"event": "disposition", "at": "t", "id": "r1.f2", "outcome": "residual", "accepted_by": "who"}),
        )
        self.assertEqual(self.run_check("--head", self.head, "--repo", str(self.repo), log).returncode, 0)

    def test_stdin_is_read_when_the_log_is_a_dash(self):
        text = disposition("r1.f1", sha=self.outside) + "\n"
        out = subprocess.run([sys.executable, str(SCRIPT), "--head", self.head, "--repo", str(self.repo), "-"],
                             capture_output=True, text=True, timeout=30, input=text)
        self.assertEqual(out.returncode, 1, out.stderr)

    def test_an_unresolvable_head_is_an_error(self):
        log = self.log(disposition("r1.f1", sha=self.outside))
        out = self.run_check("--head", "deadbeef", "--repo", str(self.repo), log)
        self.assertEqual(out.returncode, 2, out.stderr)

    def test_usage_errors_exit_2(self):
        self.assertEqual(self.run_check().returncode, 2)
        self.assertEqual(self.run_check("--repo", "/nonexistent", "--head", self.head, "x.jsonl").returncode, 2)


if __name__ == "__main__":
    unittest.main()
