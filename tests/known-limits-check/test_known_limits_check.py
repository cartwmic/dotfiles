"""Black-box tests for dot_local/share/agent-harness/bin/executable_known-limits-check.

The fixture is the past mistake, written generically: a PR description accepted a known limit on the
condition that a follow-up ticket be filed, named no ticket, and nothing failed until a reviewer
noticed. The check accepts one form only: a "## Known limits" section whose every line is a list item,
an indented continuation, or the single line "None"; the phrase is reserved everywhere else; and every
marker-carrying ticket is confirmed through a tracker lookup, so a made-up ticket does not pass. The
check must fail on that body and pass on the corrected ones. Nothing here writes inside the repo.

    python3 -m unittest discover -s tests/known-limits-check -v

The 44-row table is the blind design's conformance suite (redesign-3-blind.md section 9), with the
amendments A1-A3 applied where they change a row's outcome; each changed row says so.
"""
import importlib.machinery
import importlib.util
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
FIXED_WITH_TICKET = PAST_MISTAKE.replace("will be filed.", "will be filed. Follow-up: PROJ-123.")
FIXED_PERMANENT = PAST_MISTAKE.replace("will be filed.", "will be filed, accepted as permanent.")
PENDING = "--record-pending"
FOOTER = "\U0001f916 Generated with [a coding agent](https://example.com/agent)"


def run(*args, stdin=None, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          timeout=30, input=stdin, env=env)


_loader = importlib.machinery.SourceFileLoader("known_limits_check", str(SCRIPT))
_spec = importlib.util.spec_from_loader(_loader.name, _loader)
klc = importlib.util.module_from_spec(_spec)
_loader.exec_module(klc)


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

    def tracker(self, name, lines):
        p = Path(self.tmp) / name
        p.write_text("#!/bin/sh\n" + "\n".join(lines) + "\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
        return str(p)

    # -- the past mistake and the corrected forms -------------------------------------------

    def test_the_past_mistake_fails_and_names_the_line(self):
        out = run("--body-file", self.body(PAST_MISTAKE))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("Characters outside the font print as ?", out.stderr)
        self.assertIn('"accepted as permanent"', out.stderr)

    def test_a_ticket_or_a_permanent_acceptance_passes(self):
        for text in (FIXED_PERMANENT,):
            with self.subTest(body=text.splitlines()[3]):
                self.assertEqual(run("--body-file", self.body(text), PENDING).returncode, 0)

    def test_a_filed_ticket_passes_when_the_tracker_confirms_it(self):
        tracker = self.tracker("tracker-ok", ["exit 0"])
        out = run("--body-file", self.body(FIXED_WITH_TICKET), "--tracker-cmd", tracker)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("references confirmed", out.stdout)

    def test_no_known_limits_section_passes(self):
        self.assertEqual(run("--body-file", self.body("# PR\n\nSome prose.\n")).returncode, 0)

    def test_stdin_is_read_when_no_file_is_given(self):
        self.assertEqual(run(stdin=PAST_MISTAKE).returncode, 1)
        self.assertEqual(run(PENDING, stdin=FIXED_PERMANENT).returncode, 0)

    def test_two_bodies_are_both_checked(self):
        good = self.body(FIXED_PERMANENT, "good.md")
        bad = self.body(PAST_MISTAKE, "bad.md")
        out = run("--body-file", good, "--body-file", bad, PENDING)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("bad.md", out.stderr)
        self.assertNotIn("good.md:", out.stderr)

    # -- the blind design's 44-row conformance table (amendments applied where noted) --------

    ROWS = [
        ("no section", "## Summary\n\nFix the parser.\n", 0, []),
        ("ends at next heading", "## Summary\nx\n\n## Known limits\n\n- Slow. Follow-up: PROJ-12"
         "\n- No Windows. Accepted as permanent\n\n## Proven\nran it\n", 0, []),
        ("ends at a rule", "## Known limits\n- A. Follow-up: PROJ-1\n\n---\n" + FOOTER + "\n", 0, []),
        # row 4 under A1: a trailing attribution footer is outside the section, so it passes
        ("attribution footer after the section", "## Known limits\n- A. Follow-up: PROJ-1\n\n"
         + FOOTER + "\n", 0, []),
        ("decisions trailer", "## Known limits\n- A. Tracked in #44\n\nDecisions: #4, #7\n", 0, []),
        # row 6 under A1: a Decisions line with body text after it is not the trailer, so it is
        # inside the section and fails there
        ("decisions line with text after it", "## Known limits\n- A. Tracked in #44\n\n"
         "Decisions: #4\nAlso more text\n", 1, ["not a list item"]),
        ("none line", "## Known limits\n\nNone\n\n## Proven\nx\n", 0, []),
        ("none with a period", "## Known limits\nnone.\n", 0, []),
        ("none as an item", "## Known limits\n- None\n", 1, ["not as a list item"]),
        ("n-a is not none", "## Known limits\nN/A\n", 1, ["not a list item"]),
        ("none next to items", "## Known limits\nNone\n- A. Follow-up: X-1\n", 1,
         ["must be the only line"]),
        ("empty section", "## Known limits\n\n## Proven\nx\n", 1, ["section is empty"]),
        ("heading is case-insensitive", "## KNOWN LIMITS\n- A. Follow-up: X-1\n", 0, []),
        ("items and continuations", "## Known limits\n- A is slow\n  on big repos.\n"
         "  - only with LFS\n  Follow-up: X-9\n* B. Tracked in #3\n1. C. Tracked in #4\n", 0, []),
        ("lazy wrap", "## Known limits\n- A is slow\non big repos. Follow-up: X-9\n", 1,
         ["not a list item"]),
        ("intro line", "## Known limits\nThese are the limits:\n- A. Follow-up: X-1\n", 1,
         ["not a list item"]),
        ("hidden limit after the list", "## Known limits\n- A. Follow-up: X-1\n\nAlso B is slow.\n",
         1, ["not a list item"]),
        ("sub-heading inside", "## Known limits\n- A. Follow-up: X-1\n### Perf\n- B slow\n", 1,
         ["sub-heading"]),
        ("ends at a level-1 heading", "## Known limits\n- A. Follow-up: X-1\n# Appendix\nstuff\n",
         0, []),
        ("fence inside", "## Known limits\n- A. Follow-up: X-1\n```\nB slow\n```\n",
         1, ["code fence", "not a list item"]),
        ("comment inside", "## Known limits\n<!-- one per line -->\n- A. Follow-up: X-1\n", 1,
         ["HTML comment"]),
        ("duplicate heading", "## Known limits\n- A. Follow-up: X-1\n## Known limits\n- B\n", 1,
         ["second"]),
        ("level-3 heading label", "### Known limits\n- A\n", 1, ["written as a label"]),
        ("known limitations heading", "## Known limitations\n- A\n", 1, ["written as a label"]),
        ("heading with more words", "## Known limits and risks\n- A\n", 1, ["heading mentions"]),
        ("bold label", "**Known limits**\n- A\n", 1, ["written as a label"]),
        ("bold inline none", "**Known limits:** none\n", 1, ["written inline"]),
        ("quote italic inline", "> _Known limits_: B is slow\n", 1, ["written inline"]),
        ("list item inline", "## Notes\n- Known limits: B is slow\n", 1, ["written inline"]),
        ("decorated prose", "## Notes\n**Known** _limits_ - B slow\n", 1, ["appears outside"]),
        # row 31 under A3: an inline code span in ordinary prose is skipped
        ("code span in prose", "## Notes\nSee `Known limits` below.\n", 0, []),
        # row 32 under A2: the wrapped second line reads as a bare limit label; still loud, same line
        ("soft wrap", "## Notes\nThere are known\nlimits: B slow.\n", 1, ["written as a label"]),
        ("br tag", "## Notes\nKnown<br>limits: B\n", 1, ["written inline"]),
        ("nbsp", "## Notes\nKnown&nbsp;limits: B\n", 1, ["written inline"]),
        ("comment mention", "## Summary\n<!-- Known limits: B -->\nx\n", 1, ["appears outside"]),
        # row 36 under A3: a label-shaped line inside a fence is still scanned
        ("fence mention", "## Summary\n```\nKnown limits: B\n```\n", 1,
         ["written inline"]),
        ("prose limitation", "## Summary\nThis removes a known limitation of the parser.\n", 1,
         ["appears outside"]),
        ("tool name is not a mention", "## Summary\nAdds `known-limits-check` to preflight.\n",
         0, []),
        ("unknown limits", "## Summary\nNo unknown limits here.\n", 0, []),
        ("one-space indent is not an item", "## Known limits\n - A. Follow-up: X-1\n", 1,
         ["not a list item"]),
        ("table", "## Known limits\n| limit | ticket |\n|---|---|\n| A | X-1 |\n", 1,
         ["not a list item"]),
        ("setext label", "Known limits\n------------\n- A\n", 1, ["written as a label"]),
        # row 43: the finder passes; coverage fails the unmarked item, tested at CLI level below
        ("unmarked item", "## Known limits\n- A is slow.\n", 0, []),
        ("crlf normalized", "## Known limits\r\n- A. Follow-up: X-1\r\n", 0, []),
    ]

    def test_the_blind_design_table(self):
        for name, text, want, fragments in self.ROWS:
            with self.subTest(row=name):
                errors, _ = klc.structural_check(klc.normalize(text.encode("utf-8")))
                self.assertEqual(bool(errors), want == 1, (errors, want))
                for fragment in fragments:
                    self.assertTrue(any(fragment in msg for _, msg in errors),
                                    (fragment, errors))

    # -- A1: the trailer ----------------------------------------------------------------------

    def test_a_decisions_line_then_a_footer_ends_the_section(self):
        text = "## Known limits\n- A, accepted as permanent.\n\nDecisions: #12\n\n" + FOOTER + "\n"
        self.assertEqual(run("--body-file", self.body(text), PENDING).returncode, 0)

    def test_a_paragraph_between_the_decisions_line_and_the_footer_fails(self):
        text = ("## Known limits\n- A, accepted as permanent.\n\nDecisions: #12\n\n"
                + "A paragraph after the trailer.\n\n" + FOOTER + "\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("not a list item", out.stderr)

    def test_each_attribution_form_is_outside_the_section(self):
        for footer in (FOOTER, "Generated with a coding agent", "Co-Authored-By: an agent <a@example.com>"):
            text = "## Known limits\n- A, accepted as permanent.\n\n" + footer + "\n"
            with self.subTest(footer=footer[:20]):
                self.assertEqual(run("--body-file", self.body(text), PENDING).returncode, 0)

    # -- A2: bare limit labels ----------------------------------------------------------------

    def test_bare_limit_labels_fail(self):
        for line in ("*Limitations*", "_Limitations_", "> *Limitations*", "Limitations",
                     "Limitations:", "## Limits"):
            with self.subTest(line=line):
                out = run("--body-file", self.body("# PR\n\n" + line + "\n\n- untracked\n"))
                self.assertEqual(out.returncode, 1, out.stderr)
                self.assertIn("written as a label", out.stderr)

    def test_prose_that_opens_with_limitations_passes(self):
        text = "## Summary\nLimitations of the old parser are gone.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_heading_that_starts_with_limitations_fails(self):
        out = run("--body-file", self.body("### Limitations of this change\n\n- untracked\n"))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("written as a label", out.stderr)

    def test_the_accepted_limit_phrase_is_reserved(self):
        out = run("--body-file", self.body("## Notes\nAccepted limits: rendering.\n"))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("written inline", out.stderr)

    # -- A3: code outside the section ---------------------------------------------------------

    def test_a_code_span_in_prose_is_skipped(self):
        text = "## Notes\nSee `Known limits` below.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_label_written_in_code_still_fails(self):
        text = "## Notes\n- `Known limits:` B is slow\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("written inline", out.stderr)

    def test_a_fence_with_ordinary_prose_is_skipped(self):
        text = "## Summary\n```\nB is slow and untracked.\n```\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_an_unclosed_fence_is_an_error(self):
        out = run("--body-file", self.body("## Summary\n```\nnever closes\n"))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("fence never closes", out.stderr)

    # -- A4: the judge is unchanged -----------------------------------------------------------

    def test_a_nested_item_needs_its_own_marker(self):
        text = "## Known limits\n- A. Follow-up: PROJ-1.\n  - B breaks, no ticket filed.\n"
        out = run("--no-lookup", "--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 3", out.stderr)

    def test_a_group_label_with_covered_children_passes(self):
        text = "## Known limits\n- Rendering:\n  - Emoji print as ? Follow-up: PROJ-1.\n"
        self.assertEqual(run("--no-lookup", "--body-file", self.body(text)).returncode, 0)

    def test_a_bare_key_is_not_coverage(self):
        text = "## Known limits\n- Emoji print as ? (UTF-8).\n"
        out = run("--no-lookup", "--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("is not marked as coverage", out.stderr)

    def test_marker_keys_are_case_sensitive(self):
        bad = "## Known limits\n- A. follow-up: proj-1.\n"
        good = "## Known limits\n- A. follow-up: PROJ-1.\n"
        self.assertEqual(run("--no-lookup", "--body-file", self.body(bad)).returncode, 1)
        self.assertEqual(run("--no-lookup", "--body-file", self.body(good)).returncode, 0)

    def test_the_link_forms_are_read(self):
        for item in ("- A. Tracked in /browse/PROJ-1.",
                     "- A. Tracked in https://example.com/issues/44."):
            text = "## Known limits\n" + item + "\n"
            with self.subTest(item=item):
                self.assertEqual(run("--no-lookup", "--body-file", self.body(text)).returncode, 0)

    def test_an_unmarked_item_fails_coverage(self):
        out = run("--no-lookup", "--body-file", self.body("## Known limits\n- A is slow.\n"))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("limit has no follow-up", out.stderr)

    def test_a_lowercase_ticket_is_not_a_ticket(self):
        text = PAST_MISTAKE.replace("will be filed.", "will be filed. follow-up: proj-1.")
        self.assertEqual(run("--no-lookup", "--body-file", self.body(text)).returncode, 1)

    # -- the permanent marker: plain words in the body, the decision id in the agent record --------

    def record(self, text, name="pr-record.md"):
        return self.body(text, name)

    def test_the_old_in_body_marker_forms_are_refused_with_the_rewrite(self):
        for item in ("- A, accepted as permanent (decision #4).", "- A, accepted as permanent (decision TBD).",
                     "- A. Permanent: decision 4.", "- A. Permanent: #4.", "- A, accepted as permanent. See decision 12."):
            with self.subTest(item=item):
                out = run("--no-lookup", PENDING, "--body-file", self.body("## Known limits\n" + item + "\n"))
                self.assertEqual(out.returncode, 1, out.stderr)
                self.assertIn("decision id is written in the description", out.stderr)
                self.assertIn("Permanent limits: #ID", out.stderr)

    def test_a_permanent_item_with_no_record_flag_fails_loudly(self):
        out = run("--body-file", self.body(FIXED_PERMANENT))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("--record-pending", out.stderr)
        self.assertIn("no record was given", out.stderr)

    def test_pending_passes_and_says_the_record_was_not_checked(self):
        out = run("--body-file", self.body(FIXED_PERMANENT), PENDING)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("record not checked (pending)", out.stdout)

    def test_the_record_must_name_the_decision(self):
        body = self.body(FIXED_PERMANENT)
        good = self.record("Principles: pass.\n\nPermanent limits: #5989\nDecisions: #5989 #6001\n")
        out = run("--body-file", body, "--record", good)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("backed by the record", out.stdout)

    def test_a_record_without_the_line_a_missing_record_and_an_unlisted_id_fail(self):
        body = self.body(FIXED_PERMANENT)
        cases = {
            "no line": (self.record("Decisions: #5989\n", "no-line.md"), 'no "Permanent limits: #ID" line'),
            "line with no id": (self.record("Permanent limits: none\nDecisions: #5989\n", "no-id.md"), 'no "Permanent limits: #ID" line'),
            "id not in Decisions": (self.record("Permanent limits: #5989\nDecisions: none material\n", "not-listed.md"), "not on its \"Decisions:\" line"),
            "no such file": (str(Path(self.tmp) / "absent.md"), "cannot be read"),
        }
        for name, (record, fragment) in cases.items():
            with self.subTest(case=name):
                out = run("--body-file", body, "--record", record)
                self.assertEqual(out.returncode, 1, out.stderr)
                self.assertIn(fragment, out.stderr)

    def test_one_line_covers_several_permanent_items_and_ids(self):
        text = "## Known limits\n- A, accepted as permanent.\n- B, accepted as permanent.\n"
        record = self.record("Permanent limits: #11, #12\nDecisions: #11 #12\n", "two.md")
        self.assertEqual(run("--body-file", self.body(text), "--record", record).returncode, 0)

    def test_a_bold_label_in_the_record_is_read(self):
        record = self.record("**Permanent limits:** #7\n**Decisions:** #7\n", "bold.md")
        self.assertEqual(run("--body-file", self.body(FIXED_PERMANENT), "--record", record).returncode, 0)

    def test_the_record_is_not_read_when_nothing_is_permanent(self):
        out = run("--no-lookup", "--body-file", self.body(FIXED_WITH_TICKET), "--record", str(Path(self.tmp) / "absent.md"))
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_a_structural_error_prints_its_line_and_never_a_traceback(self):
        out = run("--body-file", self.body("# PR\n\nLimits: B is slow.\n"), PENDING)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn('line 3: "Limits" written as a label', out.stderr)
        self.assertNotIn("Traceback", out.stderr)

    def test_the_how_to_footer_shows_the_new_marker_and_the_record_line(self):
        out = run("--body-file", self.body(PAST_MISTAKE))
        self.assertIn("accepted as permanent", out.stderr.split("How to write known limits:")[1])
        self.assertIn("Permanent limits: #4", out.stderr)
        self.assertNotIn("(decision #4)", out.stderr)

    def test_the_usage_line_names_the_record_flags(self):
        out = run("--nope")
        self.assertEqual(out.returncode, 2)
        self.assertIn("[--record FILE | --record-pending]", out.stderr)

    def test_record_and_pending_together_are_a_usage_error(self):
        self.assertEqual(run("--record", "x", PENDING).returncode, 2)
        self.assertEqual(run("--record").returncode, 2)

    # -- usage --------------------------------------------------------------------------------

    def test_usage_errors_exit_2(self):
        self.assertEqual(run("--nope").returncode, 2)
        self.assertEqual(run("--body-file").returncode, 2)
        self.assertEqual(run("--body-file", "/nonexistent/body.md").returncode, 2)
        self.assertEqual(run("--tracker-cmd").returncode, 2)

    def test_a_non_utf8_body_fails_loudly(self):
        p = Path(self.tmp) / "binary.md"
        p.write_bytes(b"## Known limits\n- A \xff is slow.\n")
        out = run("--body-file", str(p))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("not UTF-8", out.stderr)

    # -- the tracker lookup: a made-up ticket must not pass ------------------------------------

    def test_a_tracker_that_confirms_the_ticket_passes(self):
        tracker = self.tracker("tracker-ok", ['[ "$1" = PROJ-123 ] && exit 0', "exit 1"])
        out = run("--body-file", self.body(FIXED_WITH_TICKET), "--tracker-cmd", tracker)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("references confirmed", out.stdout)

    def test_a_made_up_ticket_fails_even_with_a_marker(self):
        tracker = self.tracker("tracker-refuses", ['echo "$1: no such ticket" >&2', "exit 1"])
        out = run("--body-file", self.body(FIXED_WITH_TICKET), "--tracker-cmd", tracker)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("PROJ-123 could not be confirmed", out.stderr)
        self.assertIn("no such ticket", out.stderr)

    def test_an_unreachable_tracker_fails_not_silently(self):
        out = run("--body-file", self.body(FIXED_WITH_TICKET), "--tracker-cmd", "/nonexistent/tracker")
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("PROJ-123 could not be confirmed", out.stderr)

    def test_a_key_with_no_lookup_configured_fails_not_silently(self):
        env = dict(os.environ)
        env.pop("KNOWN_LIMITS_TRACKER_CMD", None)
        out = run("--body-file", self.body(FIXED_WITH_TICKET), env=env)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("PROJ-123 could not be confirmed", out.stderr)
        self.assertIn("no tracker lookup is configured", out.stderr)

    def test_lookups_off_is_a_deliberate_flag(self):
        out = run("--no-lookup", "--body-file", self.body(FIXED_WITH_TICKET))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("lookups off", out.stdout)

    def test_the_tracker_command_from_the_environment(self):
        tracker = self.tracker("tracker-env", ['echo "$1 is closed" >&2', "exit 1"])
        env = dict(os.environ, KNOWN_LIMITS_TRACKER_CMD=tracker)
        out = run("--body-file", self.body(FIXED_WITH_TICKET), env=env)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("PROJ-123 could not be confirmed", out.stderr)

    def test_each_distinct_key_is_looked_up_once(self):
        calls = self.tracker("tracker-count", ['echo "$1" >> "%s/calls.txt"' % self.tmp, "exit 0"])
        text = "## Known limits\n- A. Follow-up: PROJ-1. Also Tracked: PROJ-2.\n- B. Follow-up: PROJ-1.\n"
        out = run("--body-file", self.body(text), "--tracker-cmd", calls)
        self.assertEqual(out.returncode, 0, out.stderr)
        keys = (Path(self.tmp) / "calls.txt").read_text().split()
        self.assertEqual(sorted(keys), ["PROJ-1", "PROJ-2"])

    def test_a_github_issue_url_is_looked_up_with_gh(self):
        gh = self.tracker("gh", ['[ "$1" = issue ] || exit 10',
                                 '[ "$3" = "https://example.com/issues/44" ] || exit 11',
                                 'echo "{\\\"state\\\": \\\"OPEN\\\", \\\"url\\\": \\\"https://example.com/issues/44\\\"}"'])
        env = dict(os.environ, PATH=str(Path(self.tmp)) + os.pathsep + os.environ["PATH"])
        text = "## Known limits\n- A. Tracked in https://example.com/issues/44.\n"
        out = run("--body-file", self.body(text), env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("references confirmed", out.stdout)

    def test_a_missing_github_issue_fails(self):
        gh = self.tracker("gh", ['echo "not found" >&2', "exit 1"])
        env = dict(os.environ, PATH=str(Path(self.tmp)) + os.pathsep + os.environ["PATH"])
        text = "## Known limits\n- A. Tracked in https://example.com/issues/44.\n"
        out = run("--body-file", self.body(text), env=env)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("https://example.com/issues/44 could not be confirmed", out.stderr)

    def test_a_pull_request_number_as_an_issue_url_does_not_confirm(self):
        gh = self.tracker("gh", ['echo "{\\"state\\": \\"OPEN\\", \\"url\\": \\"https://example.com/o/r/pull/44\\"}"'])
        env = dict(os.environ, PATH=str(Path(self.tmp)) + os.pathsep + os.environ["PATH"])
        text = "## Known limits\n- A. Tracked in https://example.com/issues/44.\n"
        out = run("--body-file", self.body(text), env=env)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("pull request, not an issue", out.stderr)

    def test_a_pull_request_in_a_repo_named_issues_does_not_confirm(self):
        gh = self.tracker("gh", ['echo "{\\"state\\": \\"OPEN\\", \\"url\\": \\"https://example.com/o/issues/pull/44\\"}"'])
        env = dict(os.environ, PATH=str(Path(self.tmp)) + os.pathsep + os.environ["PATH"])
        text = "## Known limits\n- A. Tracked in https://example.com/o/issues/44.\n"
        out = run("--body-file", self.body(text), env=env)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("pull request, not an issue", out.stderr)

    def test_a_closed_issue_counts_as_filed(self):
        gh = self.tracker("gh", ['echo "{\\\"state\\\": \\\"CLOSED\\\", \\\"url\\\": \\\"https://example.com/issues/44\\\"}"'])
        env = dict(os.environ, PATH=str(Path(self.tmp)) + os.pathsep + os.environ["PATH"])
        text = "## Known limits\n- A. Tracked in https://example.com/issues/44.\n"
        out = run("--body-file", self.body(text), env=env)
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_a_body_with_no_markers_needs_no_lookup(self):
        self.assertEqual(run("--body-file", self.body("## Known limits\n\nNone\n")).returncode, 0)
        out = run("--body-file", self.body(PAST_MISTAKE))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("limit has no follow-up", out.stderr)
