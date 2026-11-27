"""The work rules of the gh wrapper (scripts/gh-wrapper-lib/gh_policy.py): issue first, squash only, the issue form, the close rule.

Each test drives the installed layout (bin/gh next to lib/) as a caller does, with a fake real gh that answers the issue and pull request reads from the
environment and records every call. A refusal is a non-zero exit with the sentence on standard error and no write reaching the real gh.
"""
import json
import os
import stat
import subprocess
import sys
import unittest

from test_gh_wrapper import LIB, WrapperBase, load_wrapper

sys.path.insert(0, str(LIB))
import gh_policy as P      # noqa: E402

W = load_wrapper()

ISSUE = "https://github.com/someone/other/issues/%d"
PULL = "https://github.com/someone/other/pull/%d"

FAKE_GH = '''#!%s
import json, os, sys
a = sys.argv[1:]
with open(os.path.join(os.environ["FAKE"], "gh-calls.jsonl"), "a") as f:
    f.write(json.dumps({"argv": a, "prompt_disabled": os.environ.get("GH_PROMPT_DISABLED")}) + "\\n")
def say(doc):
    print(json.dumps(doc)); sys.exit(0)
def fail():
    sys.stderr.write("GraphQL: Could not resolve to an issue or pull request\\n"); sys.exit(1)
if a[:2] == ["issue", "view"] and "--json" in a:
    n, fields = a[2], a[a.index("--json") + 1]
    issues = json.loads(os.environ.get("FAKE_ISSUES", "{}"))
    if n not in issues:
        fail()
    if fields == "state,url":
        say(issues[n])
    say({"closedByPullRequestsReferences": [{"url": u} for u in json.loads(os.environ.get("FAKE_CLOSED_BY", "{}")).get(n, [])]})
if a[:2] == ["pr", "view"] and "--json" in a:
    states = json.loads(os.environ.get("FAKE_PR_STATES", "{}"))
    if a[2] not in states:
        fail()
    say({"state": states[a[2]]})
print("real gh out")
''' % sys.executable

OPEN = {"5": {"state": "OPEN", "url": ISSUE % 5}}
GOOD_ISSUE = "## Problem\nIt is slow.\n\n## Wanted\nFast.\n\n## Done when\nIt is fast.\n"


class Policy(WrapperBase):
    def setUp(self):
        super().setUp()
        (self.realbin / "gh").write_text(FAKE_GH)
        self.switch("on")

    def switch(self, value):
        d = self.home / ".config" / "gh-wrapper"
        d.mkdir(parents=True, exist_ok=True)
        (d / "policy").write_text(value + "\n")

    def run_gh(self, *args, env=None):
        self.reset()
        return self.gh(*args, cwd=self.other_cwd, env=env)

    def writes(self):
        """The real gh calls that are not the layer's own reads."""
        return [c["argv"] for c in self.real_calls() if c["argv"][1:2] not in (["view"],)]

    def refused(self, done, sentence):
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertEqual(self.writes(), [], "a write reached the real gh")
        self.assertIn("gh-wrapper: refused", done.stderr)
        self.assertIn(sentence, done.stderr)

    def passed(self, done, *args):
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.writes(), [list(args)])

    def policy_log(self):
        path = self.home / ".local" / "state" / "gh-wrapper" / "policy.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def body(self, text):
        """A body file of its own for each call, so a table of cases can make several before any runs."""
        return self.file("body-%d.md" % len(list(self.files.iterdir())), text)

    # ---- the switch ---------------------------------------------------------------------------------------------------------------------------------

    def test_with_the_switch_off_or_missing_every_command_goes_through_as_before(self):
        for setting in ("off", None):
            with self.subTest(setting):
                if setting is None:
                    (self.home / ".config" / "gh-wrapper" / "policy").unlink()
                else:
                    self.switch(setting)
                for args in (["pr", "merge", "5", "--merge"], ["pr", "create", "--title", "t", "--body", "no link"], ["issue", "close", "5"],
                             ["issue", "create", "--title", "t", "--body", "bare"]):
                    done = self.run_gh(*args)
                    self.assertEqual((done.returncode, done.stdout), (0, "real gh out\n"), done.stderr)
                    self.assertEqual([c["argv"] for c in self.real_calls()], [args])

    def test_the_wrapper_hands_the_layer_the_flags_of_each_command_it_judges(self):
        for klass in P.RULE_OF:
            self.assertIn(klass, W.FOR_LAYERS)
            self.assertIn(W.FOR_LAYERS[klass], W.FLAGS)

    # ---- issue first --------------------------------------------------------------------------------------------------------------------------------

    def test_a_pull_request_with_no_linked_issue_is_refused_and_the_sentence_says_what_to_run(self):
        for args in (["--title", "t", "--body", "no link here"], ["--title", "t", "--body", "text\nCloses #5"], ["--title", "t", "--body", "closes #5"],
                     ["--title", "t", "--body-file", self.body("Closes #5 and more words\n")]):
            with self.subTest(args):
                done = self.run_gh("pr", "create", *args, env={"FAKE_ISSUES": json.dumps(OPEN)})
                self.refused(done, "first line of its body must be `Closes #N` or `Refs #N`")
                self.assertIn("issue-open", done.stderr)
                self.assertIn("pr-open", done.stderr)

    def test_a_pull_request_whose_body_cannot_be_read_is_refused(self):
        for args, why in ((["--title", "t"], "there is no body"), (["--title", "t", "--fill"], "there is no body"), (["--title", "t", "--body-file", "-"], "standard input"),
                          (["--title", "t", "--body-file", "/no/such/file"], "cannot be read")):
            with self.subTest(args):
                self.refused(self.run_gh("pr", "create", *args), why)

    def test_a_pull_request_linked_to_an_open_issue_goes_through_with_its_arguments_untouched(self):
        env = {"FAKE_ISSUES": json.dumps({**OPEN, "6": {"state": "OPEN", "url": ISSUE % 6}})}
        for first, n in (("Closes #5", "5"), ("Refs #6", "6")):
            with self.subTest(first):
                args = ["pr", "create", "--title", "t", "--body-file", self.body(first + "\n\nthe rest\n"), "--base", "main", "--draft"]
                done = self.run_gh(*args, env=env)
                self.passed(done, *args)
                read = [c for c in self.real_calls() if c["argv"][1:2] == ["view"]]
                self.assertEqual([c["argv"] for c in read], [["issue", "view", n, "--json", "state,url"]])
                self.assertEqual(read[0]["prompt_disabled"], "1")

    def test_the_issue_is_read_in_the_repository_the_command_names(self):
        done = self.run_gh("pr", "create", "--repo", "someone/other", "--title", "t", "--body", "Closes #5", env={"FAKE_ISSUES": json.dumps(OPEN)})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.real_calls()[0]["argv"], ["issue", "view", "5", "-R", "someone/other", "--json", "state,url"])

    def test_the_link_must_name_an_open_issue_that_exists(self):
        for issues, why in (({"5": {"state": "CLOSED", "url": ISSUE % 5}}, "not an open issue"), ({"5": {"state": "OPEN", "url": PULL % 5}}, "not an open issue"),
                            ({}, "cannot be read")):
            with self.subTest(why, issues=issues):
                self.refused(self.run_gh("pr", "create", "--title", "t", "--body", "Closes #5", env={"FAKE_ISSUES": json.dumps(issues)}), why)

    def test_gh_pr_new_is_the_same_command_as_pr_create(self):
        self.refused(self.run_gh("pr", "new", "--title", "t", "--body", "no link"), "not linked to an issue")

    # The forms below are what each tool really sets (checked against the last 30 days of real pull requests when they were written).
    EXEMPT = (
        ("release", "release/v0.76.3", "release: v0.76.3"),
        ("release", "release/v0.71.1", "release: prepare v0.71.1"),
        ("agent-kit pin bump", "agent-kit-v0.82.0", "chore(agent-kit): pin @cartwmic/agent-kit 0.82.0"),
        ("loop-engine pin bump", "loop-engine-v0.71.2", "feat(loop-engine): import v0.71.2 skills; bump pins to 0.71.2"),
        ("t3 pin bump", "t3-pin/0.0.31", "t3 pin: 0.0.31"),
        ("revert", "revert-12-fix-the-thing", 'Revert "fix(area): the thing (#12)"'),
    )

    def test_exactly_the_release_pin_bump_and_revert_kinds_are_exempt(self):
        self.assertEqual(sorted({k for k, _, _ in self.EXEMPT}), sorted(k for k, _, _ in P.PR_WITHOUT_ISSUE))

    def test_each_exempt_kind_goes_through_with_no_issue_and_the_use_is_logged(self):
        for kind, head, title in self.EXEMPT:
            with self.subTest(kind, head=head):
                args = ["pr", "create", "--base", "main", "--head", head, "--title", title, "--body", "no link"]
                self.passed(self.run_gh(*args), *args)
                self.assertEqual([(r["rule"], r["outcome"], r["kind"]) for r in self.policy_log()][-1], ("issue-first", "exempt", kind))
                self.assertNotIn(head, json.dumps(self.policy_log()))

    def test_a_look_alike_made_by_hand_is_still_refused(self):
        for head, title, why in (("feature/x", "release: v1.2.3", "the title alone"), ("release/v1.2.3", "add a thing", "the branch alone"),
                                 ("feature/x", 'Revert "something"', "a revert title on an ordinary branch"), ("revert-1-x", "undo it", "a revert branch with an ordinary title"),
                                 ("agent-kit-v1.2.3", "chore: bump", "the branch alone"), ("my-t3-pin/1", "t3 pin: 1", "a prefix"),
                                 ("release/v1.2", "release: v1.2", "a version with two parts"), ("loop-engine-v1.2.3", "feat(loop-engine): other work", "the branch alone")):
            with self.subTest(why, head=head, title=title):
                self.refused(self.run_gh("pr", "create", "--head", head, "--title", title, "--body", "no link"), "not linked to an issue")

    def test_an_exempt_form_with_no_head_or_no_title_is_refused(self):
        self.refused(self.run_gh("pr", "create", "--title", "release: v1.2.3", "--body", "no link"), "not linked to an issue")
        self.refused(self.run_gh("pr", "create", "--head", "release/v1.2.3", "--body", "no link"), "not linked to an issue")

    # ---- squash only --------------------------------------------------------------------------------------------------------------------------------

    def test_a_merge_commit_or_a_rebase_merge_is_refused_in_every_spelling(self):
        for flag, word in (("--merge", "--merge"), ("-m", "--merge"), ("--rebase", "--rebase"), ("-r", "--rebase")):
            with self.subTest(flag):
                done = self.run_gh("pr", "merge", "5", flag, "--match-head-commit", "abc")
                self.refused(done, "squash only: `%s` is refused. Merge with `--squash`." % word)
        self.refused(self.run_gh("pr", "-R", "someone/other", "merge", "5", "--merge"), "squash only")

    def test_a_squash_merge_through_the_gate_command_goes_through(self):
        for args in (["pr", "merge", "5", "--squash", "--match-head-commit", "abc123"], ["pr", "merge", "5", "-s", "--delete-branch", "--body-file", "-"],
                     ["pr", "merge", "5", "--auto", "--squash"], ["pr", "merge", "--help"]):
            with self.subTest(args):
                self.passed(self.run_gh(*args), *args)

    # gh reads a flag that stands before the group at the command, so a flag there must not switch the rules off: not a repository flag, not a `--name=value`.
    LEADING = (["-R", "x/y"], ["--repo", "x/y"], ["--repo=x/y"], ["-Rx/y"], ["-R=x/y"], ["-R", "x/y", "-R", "z/w"], ["--help=false"], ["--repo=x/y", "--help=false"],
               ["--reason=completed"], ["--merge=true"], ["--hostname", "github.com"], ["--no-such-flag"], ["-x", "value"])

    def test_a_flag_before_the_group_does_not_get_round_any_rule(self):
        body = self.body("no link")
        issue = self.body("## Problem\nx\n")
        for lead in self.LEADING:
            with self.subTest(lead):
                self.refused(self.run_gh(*lead, "pr", "merge", "5", "--merge"), "")
                self.refused(self.run_gh(*lead, "pr", "merge", "5", "--rebase"), "")
                self.refused(self.run_gh(*lead, "pr", "create", "--title", "t", "--body-file", body), "")
                self.refused(self.run_gh(*lead, "issue", "create", "--title", "t", "--body-file", issue), "")
                self.refused(self.run_gh(*lead, "issue", "close", "5"), "")

    def test_a_pull_request_or_issue_body_that_is_not_a_regular_file_is_refused(self):
        fifo = str(self.tmp / "body.fifo")
        os.mkfifo(fifo)      # what /dev/stdin and `<(...)` are: opening it here would block or leave gh an empty body
        for path in (fifo, "/dev/null"):
            with self.subTest(path):
                self.refused(self.run_gh("pr", "create", "--title", "t", "--body-file", path), "regular file")
                self.refused(self.run_gh("issue", "create", "--title", "t", "--body-file", path, "--label", "bug"), "regular file")

    def test_a_call_with_the_repository_flag_before_the_group_that_follows_the_rules_goes_through_and_reads_that_repository(self):
        env = {"FAKE_ISSUES": json.dumps(OPEN)}
        args = ["-R", "x/y", "pr", "create", "--title", "t", "--body", "Closes #5"]
        self.passed(self.run_gh(*args, env=env), *args)
        self.assertEqual(self.real_calls()[0]["argv"], ["issue", "view", "5", "-R", "x/y", "--json", "state,url"])
        for squash in (["--repo", "x/y", "pr", "merge", "5", "--squash"], ["--help=false", "pr", "merge", "5", "--squash"], ["-R", "x/y", "-R", "z/w", "pr", "merge", "5", "-s"]):
            self.passed(self.run_gh(*squash), *squash)

    def test_only_a_true_help_value_skips_the_rules(self):
        for flag in ("--help=false", "-h=false", "--help=0", "--help=false", "--help=nonsense"):
            with self.subTest(flag):
                self.refused(self.run_gh("pr", "merge", "5", "--merge", flag), "squash only")
        for lead in (["--help"], ["--help=true"], ["--repo=x/y", "--help"]):      # a help request before the group is still a help request
            with self.subTest(lead):
                args = [*lead, "pr", "merge", "5", "--merge"]
                self.passed(self.run_gh(*args), *args)
        for tail in (["--help"], ["-h"], ["--help=true"], ["--help=false", "--help"]):
            with self.subTest(tail):
                args = ["pr", "merge", "5", "--merge", *tail]
                self.passed(self.run_gh(*args), *args)

    def merge_script(self, caller_line):
        """A script named merge-pr.sh, as the coordinator's is, that runs the merge call."""
        script = self.tmp / "scripts" / "merge-pr.sh"
        script.parent.mkdir(exist_ok=True)
        script.write_text("#!/bin/sh\n%s\ngh pr merge 5 \"$@\" --match-head-commit abc\n" % caller_line)
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return str(script)

    def run_script(self, script, *flags, env=None):
        self.reset()
        return subprocess.run(["sh", script, *flags], cwd=str(self.other_cwd), capture_output=True, text=True, env=self.env(env), timeout=60)

    def test_the_merge_script_stopgap_needs_the_name_and_the_script_and_is_logged_and_never_covers_rebase(self):
        named = self.merge_script("export GH_CALLER=merge-pr")
        done = self.run_script(named, "--merge")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.writes(), [["pr", "merge", "5", "--merge", "--match-head-commit", "abc"]])
        used = self.policy_log()
        self.assertEqual([(r["rule"], r["outcome"], r["who"]) for r in used], [("squash-only", "exempt", "merge-pr")])
        self.assertIn("temporary", used[0]["kind"])
        self.refused(self.run_script(named, "--rebase"), "`--rebase` is refused")
        self.refused(self.run_script(self.merge_script("export GH_CALLER=somebody-else"), "--merge"), "`--merge` is refused")
        self.refused(self.run_script(self.merge_script(":"), "--merge"), "`--merge` is refused")
        # the name alone, from a caller that is not the script, does not do it
        self.refused(self.run_gh("pr", "merge", "5", "--merge", env={"GH_CALLER": "merge-pr"}), "`--merge` is refused")

    # ---- the issue form -----------------------------------------------------------------------------------------------------------------------------

    def test_an_issue_needs_its_three_parts_and_exactly_one_kind_label(self):
        base = ["issue", "create", "--title", "t"]
        cases = (
            (["--body-file", self.body("## Problem\nx\n## Wanted\ny\n"), "--label", "bug"], "no Done when"),
            (["--body-file", self.body("Problem: x\n"), "--label", "bug"], "no Wanted or Done when"),
            (["--body", "just a sentence", "--label", "bug"], "no Problem or Wanted or Done when"),
            (["--body", "Problem statement is long.\nWanted to do it.\nDone when we say.", "--label", "bug"], "no Problem"),
            (["--body-file", self.body(GOOD_ISSUE)], "exactly one kind label"),
            (["--body-file", self.body(GOOD_ISSUE), "--label", "urgent"], "exactly one kind label"),
            (["--body-file", self.body(GOOD_ISSUE), "--label", "bug", "--label", "docs"], "exactly one kind label"),
            (["--body-file", self.body(GOOD_ISSUE), "--label", "bug,change"], "exactly one kind label"),
        )
        for tail, sentence in cases:
            with self.subTest(tail):
                done = self.run_gh(*base, *tail)
                self.refused(done, sentence)
                self.assertIn("issue-open" if "no " in sentence else "gh label create", done.stderr)

    def test_a_well_formed_issue_goes_through_and_other_labels_do_not_count(self):
        for tail in (["--label", "bug"], ["--label", "Flaky Test"], ["--label", "change", "--label", "help wanted"], ["-l", "docs,urgent"], ["--label=question"]):
            with self.subTest(tail):
                args = ["issue", "create", "--title", "t", "--body-file", self.body(GOOD_ISSUE), *tail]
                self.passed(self.run_gh(*args), *args)
        for body in ("**Problem.** a\n**Wanted.** b\n**Done when.** c\n", "### Problem\na\n### Wanted\nb\n### Done when\nc\n", "problem:\na\nWANTED\nb\ndone when:\nc\n"):
            args = ["issue", "new", "--title", "t", "--body", body, "--label", "bug"]
            self.passed(self.run_gh(*args), *args)

    # ---- closing issues -----------------------------------------------------------------------------------------------------------------------------

    def test_an_issue_closes_only_with_a_merged_linked_pull_request_or_as_not_planned_with_a_comment(self):
        env = {"FAKE_ISSUES": json.dumps(OPEN), "FAKE_CLOSED_BY": json.dumps({"5": [PULL % 9]}), "FAKE_PR_STATES": json.dumps({PULL % 9: "OPEN"})}
        for tail in ([], ["--reason", "completed"], ["--reason", "not planned"], ["--reason", "not planned", "--comment", "  "], ["--comment", "moot"],
                     ["--duplicate-of", "4"], ["--reason", "duplicate", "--comment", "same as 4"]):
            with self.subTest(tail):
                self.refused(self.run_gh("issue", "close", "5", *tail, env=env), "an issue closes only with a merged pull request linked to it")
        for args in (["issue", "close", "5", "--reason", "not planned", "--comment", "moot: the file is gone"], ["issue", "close", "5", "-r", "not planned", "-c", "dup of #4"]):
            self.passed(self.run_gh(*args, env=env), *args)
        env["FAKE_PR_STATES"] = json.dumps({PULL % 9: "MERGED"})
        for args in (["issue", "close", "5"], ["issue", "close", "5", "--reason", "completed", "--comment", "done in #9"]):
            self.passed(self.run_gh(*args, env=env), *args)
        no_pr = {"FAKE_ISSUES": json.dumps(OPEN)}
        self.refused(self.run_gh("issue", "close", "5", env=no_pr), "an issue closes only")
        self.refused(self.run_gh("issue", "close", env=env), "an issue closes only")

    # ---- every refusal is one line in the policy log -------------------------------------------------------------------------------------------------

    def test_each_refusal_is_one_log_line_with_its_rule_and_never_the_text(self):
        self.run_gh("pr", "merge", "5", "--merge", env={"GH_CALLER": "someone"})
        self.run_gh("issue", "close", "5", "--comment", "secret words 4242")
        self.run_gh("issue", "create", "--title", "private title", "--body", "bare")
        log = self.policy_log()
        self.assertEqual([(r["rule"], r["outcome"], r["class"]) for r in log], [("squash-only", "refused", "pr merge"), ("close-rule", "refused", "issue close"),
                                                                            ("issue-form", "refused", "issue create")])
        self.assertEqual(log[0]["who"], "someone")
        text = (self.home / ".local" / "state" / "gh-wrapper" / "policy.jsonl").read_text()
        for word in ("secret words", "4242", "private title"):
            self.assertNotIn(word, text)

    # ---- a flag the wrapper cannot read -------------------------------------------------------------------------------------------------------------

    def test_a_flag_that_is_not_in_the_table_is_refused_for_these_commands_only(self):
        self.refused(self.run_gh("pr", "merge", "5", "--squash", "--no-such-flag"), "not in the wrapper's table")
        done = self.run_gh("pr", "view", "5", "--no-such-flag")      # another command: left alone
        self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
