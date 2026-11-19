"""Black-box test for dot_local/share/agent-harness/bin/executable_known-limits-check.

The fixture is the past mistake, written generically: a PR description accepted a known limit on the
condition that a follow-up ticket be filed, named no ticket, and nothing failed until a reviewer noticed.
The check must fail on that body and pass on the corrected ones. Nothing here writes inside the repo.

    python3 -m unittest discover -s tests/known-limits-check -v
"""
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/share/agent-harness/bin/executable_known-limits-check"

PAST_MISTAKE = (
    "# PR\n\n"
    "## Known limits\n\n"
    "- Characters outside the font print as ?. A follow-up ticket will be filed.\n"
)
FIXED_WITH_TICKET = PAST_MISTAKE.replace("will be filed.", "will be filed (PROJ-123).")
FIXED_PERMANENT = PAST_MISTAKE.replace("will be filed.", "will be filed, accepted as permanent (decision #1244).")


def run(*args, stdin=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          timeout=30, input=stdin)


class KnownLimitsCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def body(self, text, name="body.md"):
        p = Path(self.tmp) / name
        p.write_text(text)
        return str(p)

    def test_the_past_mistake_fails_and_names_the_line(self):
        out = run("--body-file", self.body(PAST_MISTAKE))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("Characters outside the font print as ?", out.stderr)
        self.assertIn("accepted as permanent (decision #N)", out.stderr)

    def test_a_ticket_or_a_permanent_acceptance_passes(self):
        for text in (FIXED_WITH_TICKET, FIXED_PERMANENT):
            with self.subTest(body=text.splitlines()[3]):
                self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_no_known_limits_section_passes(self):
        self.assertEqual(run("--body-file", self.body("# PR\n\nSome prose.\n")).returncode, 0)

    def test_the_section_ends_at_the_next_heading(self):
        text = FIXED_WITH_TICKET + "\n## Notes\n\n- A line with no ticket here is out of the section.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_bold_heading_opens_the_section(self):
        text = PAST_MISTAKE.replace("## Known limits", "**Known limits**")
        self.assertEqual(run("--body-file", self.body(text)).returncode, 1)

    def test_a_lowercase_ticket_is_not_a_ticket(self):
        text = PAST_MISTAKE.replace("will be filed.", "will be filed (proj-123).")
        self.assertEqual(run("--body-file", self.body(text)).returncode, 1)

    def test_a_permanent_acceptance_needs_its_decision_number(self):
        text = PAST_MISTAKE.replace("will be filed.", "will be filed, accepted as permanent (decision TBD).")
        self.assertEqual(run("--body-file", self.body(text)).returncode, 1)

    def test_stdin_is_read_when_no_file_is_given(self):
        self.assertEqual(run(stdin=PAST_MISTAKE).returncode, 1)
        self.assertEqual(run(stdin=FIXED_WITH_TICKET).returncode, 0)

    def test_two_bodies_are_both_checked(self):
        good = self.body(FIXED_WITH_TICKET, "good.md")
        bad = self.body(PAST_MISTAKE, "bad.md")
        out = run("--body-file", good, "--body-file", bad)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("bad.md", out.stderr)
        self.assertNotIn("good.md:", out.stderr)

    def test_tracker_command_confirms_each_distinct_ticket(self):
        tracker = Path(self.tmp) / "tracker-ok"
        tracker.write_text("#!/bin/sh\necho \"confirmed $1\"\n")
        tracker.chmod(tracker.stat().st_mode | stat.S_IEXEC)
        text = PAST_MISTAKE.replace("will be filed.", "will be filed (PROJ-1). Also (PROJ-2) tracks the rest.")
        out = run("--body-file", self.body(text), "--tracker-cmd", str(tracker))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("tracker confirmed", out.stdout)

    def test_tracker_command_refuses_a_ticket_that_is_not_open(self):
        tracker = Path(self.tmp) / "tracker-shut"
        tracker.write_text("#!/bin/sh\necho \"$1 is closed\" >&2\nexit 1\n")
        tracker.chmod(tracker.stat().st_mode | stat.S_IEXEC)
        text = FIXED_WITH_TICKET
        out = run("--body-file", self.body(text), "--tracker-cmd", str(tracker))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("PROJ-123 is not confirmed", out.stderr)

    def test_tracker_command_from_the_environment(self):
        tracker = Path(self.tmp) / "tracker-env"
        tracker.write_text("#!/bin/sh\nexit 0\n")
        tracker.chmod(tracker.stat().st_mode | stat.S_IEXEC)
        env = dict(os.environ, KNOWN_LIMITS_TRACKER_CMD=str(tracker))
        out = subprocess.run([sys.executable, str(SCRIPT), "--body-file", self.body(FIXED_WITH_TICKET)],
                             capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_a_missing_tracker_command_is_an_error_not_a_failure(self):
        out = run("--body-file", self.body(FIXED_WITH_TICKET), "--tracker-cmd", "/nonexistent/tracker")
        self.assertEqual(out.returncode, 2, out.stderr)

    def test_usage_errors_exit_2(self):
        self.assertEqual(run("--nope").returncode, 2)
        self.assertEqual(run("--body-file").returncode, 2)
        self.assertEqual(run("--body-file", "/nonexistent/body.md").returncode, 2)


if __name__ == "__main__":
    unittest.main()
