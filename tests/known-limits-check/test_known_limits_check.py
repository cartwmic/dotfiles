"""Black-box test for dot_local/share/agent-harness/bin/executable_known-limits-check.

The fixture is the past mistake, written generically: a PR description accepted a known limit on the
condition that a follow-up ticket be filed, named no ticket, and nothing failed until a reviewer noticed.
The check finds Known-limits blocks loosely (a heading, an inline "Known limits:" line, a bold label, or a
list item that is just the label), then judges strictly: every limit unit carries its own marker
("Follow-up: KEY", "Tracked: KEY" / "Tracked in KEY", a /browse/KEY link, or the permanent form), with no
inheritance from a parent. The check must fail on that body and pass on the corrected ones. Nothing here
writes inside the repo.

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
FIXED_WITH_TICKET = PAST_MISTAKE.replace("will be filed.", "will be filed. Follow-up: PROJ-123.")
FIXED_PERMANENT = PAST_MISTAKE.replace("will be filed.", "will be filed, accepted as permanent (decision #1).")


def run(*args, stdin=None, env=None):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                          timeout=30, input=stdin, env=env)


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
        for text in (
            PAST_MISTAKE.replace("will be filed.", "will be filed (proj-123)."),
            PAST_MISTAKE.replace("will be filed.", "will be filed. follow-up: proj-1."),
        ):
            with self.subTest(body=text.splitlines()[3]):
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

    # -- the tracker hook --------------------------------------------------------------------

    def test_tracker_command_confirms_each_distinct_ticket(self):
        tracker = self.tracker("tracker-refuses-second", ['[ "$1" = PROJ-2 ] && exit 1', "exit 0"])
        text = PAST_MISTAKE.replace("will be filed.", "will be filed. Follow-up: PROJ-1. Also Tracked: PROJ-2.")
        out = run("--body-file", self.body(text), "--tracker-cmd", tracker)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("PROJ-2 is not confirmed", out.stderr)

    def test_a_tracker_that_accepts_everything_confirms(self):
        tracker = self.tracker("tracker-ok", ["exit 0"])
        out = run("--body-file", self.body(FIXED_WITH_TICKET), "--tracker-cmd", tracker)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("tracker confirmed", out.stdout)

    def test_tracker_command_refuses_a_ticket_that_is_not_open(self):
        tracker = self.tracker("tracker-shut", ['echo "$1 is closed" >&2', "exit 1"])
        out = run("--body-file", self.body(FIXED_WITH_TICKET), "--tracker-cmd", tracker)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("PROJ-123 is not confirmed", out.stderr)

    def test_tracker_command_from_the_environment(self):
        tracker = self.tracker("tracker-env", ['echo "$1 is closed" >&2', "exit 1"])
        env = dict(os.environ, KNOWN_LIMITS_TRACKER_CMD=tracker)
        out = run("--body-file", self.body(FIXED_WITH_TICKET), env=env)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("PROJ-123 is not confirmed", out.stderr)

    def test_a_missing_tracker_command_is_an_error_not_a_failure(self):
        out = run("--body-file", self.body(FIXED_WITH_TICKET), "--tracker-cmd", "/nonexistent/tracker")
        self.assertEqual(out.returncode, 2, out.stderr)

    def test_usage_errors_exit_2(self):
        self.assertEqual(run("--nope").returncode, 2)
        self.assertEqual(run("--body-file").returncode, 2)
        self.assertEqual(run("--body-file", "/nonexistent/body.md").returncode, 2)

    # -- units: wrapping, paragraphs, lead-ins ------------------------------------------------

    def test_a_wrapped_bullet_with_the_ticket_on_the_continuation_passes(self):
        text = "# PR\n\n## Known limits\n\n- Characters outside the font print as ?; tracked in\n  PROJ-123.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_wrapped_bullet_with_no_ticket_on_any_of_its_lines_fails(self):
        text = "# PR\n\n## Known limits\n\n- Characters outside the font print as ?; a follow-up\n  will be filed.\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 5", out.stderr)

    def test_a_paragraph_limit_under_the_heading_fails(self):
        text = "# PR\n\n## Known limits\n\nCharacters outside the font print as ?. A follow-up ticket will be filed.\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 5", out.stderr)

    def test_an_intro_line_followed_by_an_untracked_bullet_fails(self):
        text = ("# PR\n\n## Known limits\n\nThese are accepted for this PR:\n\n"
                "- Characters outside the font print as ?. A follow-up ticket will be filed.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 7", out.stderr)

    def test_an_item_a_paragraph_then_an_untracked_item_fails(self):
        text = ("# PR\n\n## Known limits\n\n- A is slow (PROJ-1).\n\nAlso:\n\n"
                "- Characters outside the font print as ?. A follow-up ticket will be filed.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 9", out.stderr)

    def test_an_intro_ending_in_a_colon_is_covered_by_its_ticketed_list(self):
        text = "# PR\n\n## Known limits\n\nThese are accepted:\n\n- Tracked in PROJ-1.\n- Tracked in PROJ-2.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_leadin_bullet_with_ticketed_sub_bullets_passes(self):
        text = "# PR\n\n## Known limits\n\n- Font gaps:\n  - Emoji print as ? Follow-up: PROJ-1.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    # -- the body trailer ---------------------------------------------------------------------

    def test_known_limits_as_the_last_section_ends_before_the_decisions_line(self):
        text = ("# PR\n\n## Known limits\n\n- Tracked in PROJ-1.\n\n"
                "Decisions: #1\n\nGenerated with a coding agent\n")
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_none_block_before_the_trailers_passes(self):
        text = "# PR\n\n## Known limits\n\nNone.\n\nDecisions: #12\n\nGenerated with a coding agent\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_the_trailers_are_not_reported_as_limits(self):
        text = ("# PR\n\n## Known limits\n\n"
                "Characters outside the font print as ?. A follow-up ticket will be filed.\n\n"
                "Decisions: #12\n\nGenerated with a coding agent\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("Characters outside the font print as ?", out.stderr)
        self.assertNotIn("Decisions", out.stderr)
        self.assertNotIn("Generated with", out.stderr)

    # -- bare keys are not coverage -----------------------------------------------------------

    def test_a_bare_key_is_not_coverage(self):
        for key in ("UTF-8", "PROJ-1"):
            text = "# PR\n\n## Known limits\n\n- Emoji print as ? (%s).\n" % key
            with self.subTest(key=key):
                out = run("--body-file", self.body(text))
                self.assertEqual(out.returncode, 1, out.stderr)
                self.assertIn("is not marked as coverage", out.stderr)
                self.assertIn('Add "Follow-up: %s"' % key, out.stderr)

    def test_gpt4_in_prose_is_a_bare_key(self):
        text = ("# PR\n\n## Known limits\n\n"
                "- Prompts over the GPT-4 context limit are cut. A follow-up ticket will be filed.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn('Add "Follow-up: GPT-4"', out.stderr)

    # -- round 3: nesting is judged per unit, with no inheritance -----------------------------

    def test_a_marked_parent_with_an_untracked_child_fails(self):
        text = ("# PR\n\n## Known limits\n\n- Emoji print as ? Follow-up: PROJ-1.\n"
                "  - Ligatures break. A follow-up ticket will be filed.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 6", out.stderr)

    def test_a_group_label_with_one_covered_and_one_untracked_child_fails(self):
        text = ("# PR\n\n## Known limits\n\n- Rendering:\n"
                "  - Emoji print as ? Follow-up: PROJ-1.\n"
                "  - Ligatures break. A follow-up ticket will be filed.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 7", out.stderr)

    def test_a_one_space_list_with_an_untracked_item_fails(self):
        text = ("# PR\n\n## Known limits\n\n - Emoji print as ? Follow-up: PROJ-1.\n"
                " - Ligatures break. A follow-up ticket will be filed.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 6", out.stderr)

    def test_a_loose_nested_list_with_blank_lines_fails(self):
        text = ("# PR\n\n## Known limits\n\n- Rendering:\n\n"
                "  - Emoji print as ? Follow-up: PROJ-1.\n\n"
                "  - Ligatures break. A follow-up ticket will be filed.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 9", out.stderr)

    def test_a_numbered_nested_list_fails(self):
        text = ("# PR\n\n## Known limits\n\n1. Rendering\n"
                "   1. Emoji (PROJ-1).\n"
                "   2. Ligatures break.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 6", out.stderr)

    # -- round 3: the other block-opening forms -----------------------------------------------

    def test_an_inline_known_limits_line_opens_the_section(self):
        text = "Known limits: Characters outside the font print as ?. A follow-up ticket will be filed.\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 1", out.stderr)

    def test_an_inline_known_limits_line_with_a_marker_passes(self):
        text = "Known limits: Characters outside the font print as ?. Follow-up: PROJ-1.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_bold_label_with_a_colon_opens_the_section(self):
        text = "# PR\n\n**Known limits:**\n\n- Characters outside the font print as ?. Follow-up: PROJ-1.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_sub_heading_does_not_end_the_section(self):
        text = ("# PR\n\n## Known limits\n\n### Rendering\n\n"
                "- Emoji print as ? Follow-up: PROJ-1.\n"
                "- Ligatures break. A follow-up ticket will be filed.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 8", out.stderr)

    def test_a_stray_label_line_fails(self):
        for line in ("Known limits - rendering", "Known limits and caveats:"):
            with self.subTest(line=line):
                out = run("--body-file", self.body("# PR\n\n" + line + "\n"))
                self.assertEqual(out.returncode, 1, out.stderr)
                self.assertIn("does not read", out.stderr)

    # -- round 2: a prose limit in a block that also has a list -------------------------------

    def test_a_prose_limit_after_a_covered_list_fails(self):
        text = ("# PR\n\n## Known limits\n\n- B is slow. Follow-up: PROJ-1.\n\n"
                "Limit A is untracked.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 7", out.stderr)

    def test_a_prose_limit_before_a_covered_list_fails(self):
        text = ("# PR\n\n## Known limits\n\nLimit A is untracked.\n\n"
                "- B is slow. Follow-up: PROJ-1.\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("line 5", out.stderr)

    # -- round 4: marker keys are case-sensitive -----------------------------------------------

    def test_a_marker_key_is_case_sensitive(self):
        for text in (
            "- Only amd64 images are built. Follow-up: x86-64 and arm64 images later.",
            "- Emoji print as ?. Follow-up: utf-16 output needs a decision.",
            "- A. follow-up: proj-1.",
        ):
            with self.subTest(body=text):
                out = run("--body-file", self.body("# PR\n\n## Known limits\n\n" + text + "\n"))
                self.assertEqual(out.returncode, 1, out.stderr)
        text = "# PR\n\n## Known limits\n\n- A. follow-up: PROJ-1.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_tracked_in_marker_key_is_case_sensitive(self):
        text = "# PR\n\n## Known limits\n\n- Old logs are not migrated. Tracked in sha-256 rollout notes.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 1)

    # -- round 4: a standalone bold or inline label holds a section ----------------------------

    def test_a_bold_label_with_none_under_it_passes(self):
        text = "# PR\n\n**Known limits**\n\nNone.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_bold_label_with_covered_prose_passes(self):
        text = "# PR\n\n**Known limits**\n\nEmoji print as ?. Follow-up: PROJ-1.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_an_inline_label_with_covered_prose_passes(self):
        text = "# PR\n\nKnown limits:\n\nEmoji print as ?. Follow-up: PROJ-1.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_prose_after_the_list_under_a_bold_label_fails(self):
        text = ("# PR\n\n**Known limits**\n\n- A. Follow-up: PROJ-1.\n\n"
                "B also breaks; ticket to come.\n\n**Testing**\n\nran it\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("B also breaks", out.stderr)

    def test_a_covered_list_followed_by_another_bold_label_passes(self):
        text = "# PR\n\n**Known limits**\n\n- A. Follow-up: PROJ-1.\n\n**Testing**\n\n- ran it\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    # -- round 4: a GitHub issue URL is coverage ------------------------------------------------

    def test_a_github_issue_url_is_coverage(self):
        text = "# PR\n\n## Known limits\n\n- Emoji gap. Follow-up: https://github.com/o/r/issues/12\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_tracker_that_refuses_an_issue_url_fails(self):
        tracker = self.tracker("tracker-refuse-url", ["exit 1"])
        text = "# PR\n\n## Known limits\n\n- Emoji gap. Follow-up: https://github.com/o/r/issues/12\n"
        out = run("--body-file", self.body(text), "--tracker-cmd", tracker)
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("not confirmed", out.stderr)

    # -- round 4 notes: list-label form and the stray rule --------------------------------------

    def test_a_list_item_starting_with_the_label_fails(self):
        out = run("--body-file", self.body("# PR\n\n## Summary\n\n- Known limits: emoji print as ?, no ticket yet.\n"))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("does not read", out.stderr)
        text = "# PR\n\n## Summary\n\n- Known limits: rendering is slow. Follow-up: PROJ-1.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 1, "the list-label form is not read, covered or not")

    def test_ordinary_sentences_are_not_stray(self):
        text = "# PR\n\nLimitations of this approach are listed in the design doc.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_paragraph_starting_with_known_limits_is_stray(self):
        out = run("--body-file", self.body("# PR\n\nKnown limits are below.\n"))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("does not read", out.stderr)

    # -- round 5: label-like lines in the wrong form fail loudly --------------------------------

    def test_label_like_lines_in_the_wrong_form_fail(self):
        cases = [
            "## Known limits (v1)",
            "## Known limitations in this PR",
            "### Limitations of this change",
            "**Known limits (v1)**",
        ]
        for line in cases:
            with self.subTest(line=line):
                text = "# PR\n\n" + line + "\n\n- A breaks, no ticket.\n"
                out = run("--body-file", self.body(text))
                self.assertEqual(out.returncode, 1, out.stderr)

    # -- round 5: what ends a bold or Label: block ----------------------------------------------

    def test_a_plain_label_line_ends_a_label_block(self):
        text = "# PR\n\nKnown limits:\n\n- A. Follow-up: PROJ-1.\n\nTesting:\n\n- ran it\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_a_bold_run_in_label_ends_a_label_block(self):
        text = "# PR\n\n**Known limits**\n\n- A. Follow-up: PROJ-1.\n\n**Testing:** ran the suite.\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    def test_prose_before_a_plain_label_under_a_bold_label_fails(self):
        text = ("# PR\n\n**Known limits**\n\n- A. Follow-up: PROJ-1.\n\n"
                "B untracked.\n\nTesting:\n\n- ran it\n")
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("B untracked", out.stderr)
        self.assertNotIn("ran it", out.stderr)

    def test_a_bold_run_in_label_right_after_a_label_block_is_empty_loud(self):
        text = "# PR\n\n**Known limits**\n\n**Emoji:** prints ?.\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("no list items", out.stderr)

    # -- round 5 / decision #1258: group titles inside blocks -----------------------------------

    def test_a_bold_group_title_inside_a_heading_block_ends_nothing(self):
        text = "# PR\n\n## Known limits\n\n- A. Follow-up: PROJ-1.\n\n**Export**\n\n- B is slow\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("B is slow", out.stderr)

    def test_a_label_line_with_text_inside_a_heading_block_is_judged(self):
        text = "# PR\n\n## Known limits\n\n- A. Follow-up: PROJ-1.\n\nNote: B is slow\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("B is slow", out.stderr)

    def test_a_bold_group_title_ends_a_label_block_residual(self):
        # decision #1258: a bold group title inside a bold or Label: known-limits block ends the block
        text = "# PR\n\n**Known limits**\n\n- A. Follow-up: PROJ-1.\n\n**Export**\n\n- B is slow\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('ended by label "**Export**"', out.stdout)

    def test_the_cost_of_group_titles_in_heading_blocks_is_pinned(self):
        text = "# PR\n\n## Known limits\n\n- A. Follow-up: PROJ-1.\n\n**Testing**\n\n- ran it\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 1)

    # -- round 5: the pre-pass fails loudly on an unclosed fence or comment ---------------------

    def test_an_unclosed_fence_fails_loud(self):
        text = "# PR\n\n## Summary\n\n```\n- A breaks, no ticket.\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("never closes", out.stderr)

    def test_an_unclosed_comment_fails_loud(self):
        text = "# PR\n\n## Summary\n\n<!-- under construction\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 1, out.stderr)
        self.assertIn("never closes", out.stderr)

    def test_a_bold_decisions_line_ends_the_body(self):
        text = "# PR\n\n## Known limits\n\n- A. Follow-up: PROJ-1.\n\n**Decisions:** #3\n\nGenerated\n"
        self.assertEqual(run("--body-file", self.body(text)).returncode, 0)

    # -- round 5: the span line ------------------------------------------------------------------

    def test_a_passing_body_prints_the_block_span(self):
        text = "## Known limits\n\n- A. Follow-up: PROJ-1.\n\n## Testing\n\n- ran it\n"
        out = run("--body-file", self.body(text))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn('block 1, lines 3-4, 1 item(s), ended by heading "## Testing" at line 5', out.stdout)

if __name__ == "__main__":
    unittest.main()
