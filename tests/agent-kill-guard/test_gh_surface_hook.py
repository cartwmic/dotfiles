"""gh_surface through the real hook: refuse_pattern_kill.py, run as a script from a temp copy of the hooks directory, the way every harness runs it.

test_gh_surface.py reads the module's own verdicts. This file runs a whole command line through the hook script (profile personal, the claims command present so the issue rule is
armed) and reads the exit code: 2 refused, 0 allowed. It holds the cases the wiring has to change (the holes that were open, reached by `gh api`, and `gh issue edit` text), the
cases that must not change (the sanctioned writers, state changes, comments, and every gh command in the two review skills), and a run with the table switched off, to show
the cases above can fail.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_bash_rules as base
from test_gh_surface import HOLES, ROWS, STAY_ALLOWED, Skills

HOOKS = base.HOOKS
COMMANDS = {row[0]: row[1] for row in ROWS}
ENV_DROP = ("AGENT_HARNESS_CONTAINER", "AGENT_HARNESS_PROFILE", "AGENT_HARNESS_COORDINATOR_REPO", "AGENT_HARNESS_GUARD_LOG")

# Open in the hook this PR replaces (the hook on main refused S5 and B5 already: its title rule had landed), refused through gh_surface now.
FLIPPED = ["M5", "M6", "M7", "S5", "B5", "B8", "B9", "B10", "B11", "B15", "B16", "G1", "I8", "I12"]
# `gh issue edit` text: allowed while an issue's text had no checked route and issue-open could not edit; refused from this PR, until `issue-open --edit` (dotfiles issue 890).
ISSUE_EDIT_TEXT = ["I2", "I3", "I4", "I9"]
# The commands that must not change. O12 and O13 are `pr-open --edit` and `merge-pr.sh`.
UNCHANGED = ["P6", "P7", "P8", "S1", "S2", "S3", "S4", "S6", "B6", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "I5", "I6", "O12", "O13"]


class Runs:
    """A copy of the hooks directory with a profile file and a coordinator checkout that holds the claims command; `run(command)` is the hook's exit code."""

    def __init__(self, surface_source=None):
        self.tmp = tempfile.mkdtemp()
        self.hooks = Path(self.tmp) / "hooks"
        shutil.copytree(HOOKS, self.hooks, ignore=shutil.ignore_patterns("__pycache__"))
        (self.hooks / "profile").write_text("personal\n")
        if surface_source is not None:
            (self.hooks / "gh_surface.py").write_text(surface_source)
        self.repo = Path(self.tmp) / "coordinator"
        (self.repo / "src/claims").mkdir(parents=True)
        (self.repo / "src/claims/cli.ts").write_text("// stub\n")

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run(self, command):
        env = {k: v for k, v in os.environ.items() if k not in ENV_DROP}
        env.update(AGENT_HARNESS_GUARD_LOG=os.devnull, AGENT_HARNESS_COORDINATOR_REPO=str(self.repo))
        payload = {"tool_name": "Bash", "cwd": self.tmp, "tool_input": {"command": command}}
        done = subprocess.run([sys.executable, str(self.hooks / "refuse_pattern_kill.py")], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30)
        return done


class Hook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hook = Runs()

    @classmethod
    def tearDownClass(cls):
        cls.hook.close()

    def test_the_rows_named_here_are_rows(self):
        for rid in FLIPPED + ISSUE_EDIT_TEXT + UNCHANGED:
            self.assertIn(rid, COMMANDS, rid)
        self.assertLessEqual(set(UNCHANGED) - {"O12", "O13"}, STAY_ALLOWED)
        self.assertLessEqual(set(FLIPPED) | set(ISSUE_EDIT_TEXT), HOLES)  # the module's own table calls every one of them a hole

    def test_every_hole_is_refused(self):
        for rid in FLIPPED:
            with self.subTest(row=rid):
                done = self.hook.run(COMMANDS[rid])
                self.assertEqual(done.returncode, 2, "%s was allowed: %s" % (rid, COMMANDS[rid]))
                self.assertTrue(done.stderr.strip(), "a refusal with no text")

    def test_the_rest_api_merge_is_refused_and_names_the_gated_ways(self):
        done = self.hook.run("gh api -X PUT repos/o/r/pulls/5/merge -f merge_method=merge")
        self.assertEqual(done.returncode, 2)
        self.assertIn("gh pr merge", done.stderr)
        self.assertIn("merge-pr.sh", done.stderr)
        for command in ("gh api -X PUT repos/o/r/pulls/5/merge", "gh api --method=put https://api.github.com/repos/o/r/pulls/5/merge/", "gh api -X PUT repositories/1/pulls/5/merge", "gh api -XPUT repos/o/r/merges -f base=a -f head=b"):
            with self.subTest(command=command):
                self.assertEqual(self.hook.run(command).returncode, 2)
        self.assertEqual(self.hook.run("gh api repos/o/r/pulls/5/merge").returncode, 0)  # a GET asks whether it is merged

    def test_issue_edit_text_is_refused_and_points_at_issue_890(self):
        """Decision 6868 (leave `gh issue edit` bodies allowed until issue-open can edit) is reversed by decision 7032: the refusal stands until `issue-open --edit` lands."""
        for rid in ISSUE_EDIT_TEXT:
            with self.subTest(row=rid):
                done = self.hook.run(COMMANDS[rid])
                self.assertEqual(done.returncode, 2, COMMANDS[rid])
                self.assertIn("dotfiles issue 890", done.stderr)
        self.assertEqual(self.hook.run("gh issue edit 5 --add-label bug --add-assignee a").returncode, 0)  # a label is not text

    def test_no_refusal_cites_a_ledger_id_or_an_owed_number(self):
        for rid in FLIPPED + ISSUE_EDIT_TEXT:
            text = self.hook.run(COMMANDS[rid]).stderr
            with self.subTest(row=rid):
                self.assertNotIn("owed", text)
                self.assertNotRegex(text, r"#\d{3,}")

    def test_the_commands_that_must_not_change_still_pass(self):
        for rid in UNCHANGED:
            with self.subTest(row=rid):
                done = self.hook.run(COMMANDS[rid])
                self.assertEqual(done.returncode, 0, "%s was refused: %s\n%s" % (rid, COMMANDS[rid], done.stderr))

    def test_every_gh_command_in_the_two_review_skills_passes(self):
        seen = []
        for name in Skills.SKILLS:
            for text in Skills.commands((base.ROOT / name).read_text()):
                for cmd in base.bash_rules.Walk(text).cmds:
                    if base.bash_rules._base(cmd.words[0]) == "gh":
                        command = shlex.join(cmd.words)
                        seen.append(command)
                        with self.subTest(skill=Path(name).parent.name, command=command[:80]):
                            done = self.hook.run(command)
                            self.assertEqual(done.returncode, 0, "refused: %s\n%s" % (command, done.stderr))
        self.assertGreaterEqual(len(seen), 5, seen)  # not vacuous: the thread query, the reply, the resolve, the bot re-run, the checks
        self.assertTrue(any("graphql" in c for c in seen) and any("replies" in c for c in seen) and any("pr comment" in c for c in seen), seen)

    def test_a_redirect_after_a_read_is_not_a_second_endpoint(self):
        for command in ("gh api repos/o/r/pulls/5 -q .title 2>/dev/null", "gh api repos/o/r/contents/a?ref=x -q .content 2>&1 | base64 -d", "gh api user > /tmp/out.json", "gh api user >/tmp/out.json 2>&1"):
            with self.subTest(command=command):
                self.assertEqual(self.hook.run(command).returncode, 0)
        gates = "ci-main-status --merge-gate o/r && pr-body-check o/r 5 && "
        self.assertEqual(self.hook.run(gates + "gh pr merge 5 -R o/r 2>&1").returncode, 0)
        self.assertEqual(self.hook.run("gh api -X PATCH repos/o/r/pulls/5 -f body=x 2>/dev/null").returncode, 2)

    def test_the_gates_on_a_cli_merge_are_unchanged(self):
        self.assertEqual(self.hook.run("gh pr merge 5 --squash").returncode, 2)
        self.assertEqual(self.hook.run("ci-main-status --merge-gate o/r && pr-body-check o/r 5 && gh pr merge 5 -R o/r --squash").returncode, 0)
        self.assertEqual(self.hook.run("ci-main-status --merge-gate o/r && pr-body-check o/r 5 && gh pr merge 6 -R o/r --squash").returncode, 2)
        self.assertEqual(self.hook.run("ci-main-status --merge-gate o/r && pr-body-check o/r 5 && gh pr merge 5 -R cartwmic/coordinator").returncode, 2)

    def test_an_unknown_gh_command_or_flag_on_the_surface_is_refused_naming_the_table(self):
        for command in ("gh pe 5 -b x", "gh pr frobnicate 5", "gh api user --newflag", "gh pr -t T edit 5", "gh issue create --newflag"):
            with self.subTest(command=command):
                done = self.hook.run(command)
                self.assertEqual(done.returncode, 2)
                self.assertIn("gh_surface.py", done.stderr)


class TheChecksCanFail(unittest.TestCase):
    """The same commands, with gh_surface switched to allow everything and read nothing (the hook as it behaved before it asked the table): every hole passes, so the test above fails there."""

    @classmethod
    def setUpClass(cls):
        source = (HOOKS / "gh_surface.py").read_text() + "\n\ndef surface(gh):\n    return Surface(frozenset(), ALLOW, True, '', 'stub')\n"
        cls.hook = Runs(source)

    @classmethod
    def tearDownClass(cls):
        cls.hook.close()

    def test_with_the_table_off_every_hole_is_allowed(self):
        for rid in FLIPPED + ISSUE_EDIT_TEXT:
            with self.subTest(row=rid):
                self.assertEqual(self.hook.run(COMMANDS[rid]).returncode, 0, COMMANDS[rid])


class GhSurfaceIsInstalledWithTheRules(unittest.TestCase):
    """bash_rules imports gh_surface, and the hook fails open when an import fails (a hook that cannot run must not stop an agent): a hooks directory without gh_surface.py would turn
    every rule off, not only the gh ones. So the file must travel with bash_rules.py everywhere that copies the hooks."""

    def test_a_hooks_directory_with_no_gh_surface_allows_everything_which_is_why_it_must_ship(self):
        hook = Runs()
        try:
            (hook.hooks / "gh_surface.py").unlink()
            self.assertEqual(hook.run("gh api -X PUT repos/o/r/pulls/5/merge").returncode, 0)
            self.assertEqual(hook.run("pkill -f x").returncode, 2)  # the pkill check does not need the rules
        finally:
            hook.close()

    def test_the_source_directory_has_the_module_beside_the_rules(self):
        self.assertTrue((HOOKS / "gh_surface.py").is_file())
        self.assertIn("import gh_surface", (HOOKS / "bash_rules.py").read_text())


if __name__ == "__main__":
    unittest.main()
