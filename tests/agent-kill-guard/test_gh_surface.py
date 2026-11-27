"""gh_surface.py: what `surface` says about every way an agent can write a pull request or an issue with gh, and that the commands the review skills tell agents to run
still pass.

Each row is a whole command line, read as the hook reads it (bash_rules.Walk finds the gh commands, bash_rules.gh_command parses them), and the expected effects and verdict.
The rows come from a survey of the installed hook; the HOLES are the ones the hook let through before gh_surface existed, so a classifier that allows everything
fails on every one of them (the last test runs that stub). Nothing here reads a route, a reason or any other internal of the module: only the effects, the verdict and
whether the module lists the command.
"""
import re
import unittest
from pathlib import Path

import test_bash_rules as base

bash_rules = base.bash_rules
ROOT = base.ROOT
import gh_surface as gs  # noqa: E402  (test_bash_rules put the hooks directory on sys.path)

F = "/tmp/pr-5-body.aB3xY9"
NEW_PR, NEW_ISSUE = "pr-create title body", "issue-create title body"
UNLISTED = None  # expected effects of a command the module does not list: refused, whatever it is


def graphql(text, flags=""):
    return "gh api graphql -f query='%s'%s" % (text, flags)


# (id, command, effects (space separated), verdict). `UNLISTED` as the effects: not on the table, so refused.
ROWS = [
    # gh pr create and edit: the checked-body form stays the only way to set text
    ("P1", "gh pr create -t T -b x", NEW_PR, gs.PR_BODY),
    ("P2", "gh pr create -t T -F " + F, NEW_PR, gs.PR_BODY),
    ("P3", "gh pr edit 5 -F " + F, "body", gs.PR_BODY),
    ("P4", "gh pr edit 5 -bx", "body", gs.PR_BODY),
    ("P5", "gh pr edit 5 -t T", "title", gs.PR_BODY),
    ("P6", "gh pr edit 5 --add-label x", "other", gs.ALLOW),
    ("P7", "gh pr edit 5 --add-reviewer a", "other", gs.ALLOW),
    ("P8", "gh pr edit 5 --base main", "other", gs.ALLOW),
    ("P9", "gh pr edit 5 -t T -F " + F, "title body", gs.PR_BODY),
    ("P10", "gh pr edit 5 --add-label x -b y", "body other", gs.PR_BODY),
    ("P11", "gh pr new -t T -b x", NEW_PR, gs.PR_BODY),
    # merge, by every route gh has
    ("M1", "gh pr merge 5 --merge", "merge", gs.MERGE_GATE),
    ("M2", "ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge 5 -Rcartwmic/coordinator", "merge", gs.MERGE_GATE),
    ("M3", "ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge 5 --merge", "merge", gs.MERGE_GATE),
    ("M4", "gh pr merge 5 --auto --merge", "merge", gs.MERGE_GATE),
    ("M5", "gh api -X PUT repos/o/r/pulls/5/merge -f merge_method=merge", "merge", gs.REFUSE),
    ("M5a", "gh api -XPUT repos/o/r/pulls/5/merge", "merge", gs.REFUSE),
    ("M5b", "gh api --method=put https://api.github.com/repos/o/r/pulls/5/merge", "merge", gs.REFUSE),
    ("M5c", "gh api repos/o/r/pulls/5/merge -f merge_method=squash", "merge", gs.REFUSE),  # a field makes the default method POST
    ("M5d", "gh api repositories/123/pulls/5/merge -X PUT", "merge", gs.REFUSE),
    ("M5e", "gh api '/repos/{owner}/{repo}/pulls/5/merge/' -X PUT", "merge", gs.REFUSE),
    ("M5f", "gh api -X PUT https://ghe.example.com/api/v3/repos/o/r/pulls/5/merge", "merge", gs.REFUSE),
    ("M5g", "gh api -X PUT 'repos/o/r/pulls/5/merge?merge_method=squash'", "merge", gs.REFUSE),
    ("M5h", "gh api -X POST repos/o/r/merges -f base=main -f head=topic", "merge", gs.REFUSE),
    ("M6", graphql('mutation{mergePullRequest(input:{pullRequestId:"X"}){clientMutationId}}'), "merge", gs.REFUSE),
    ("M7", graphql('mutation{enablePullRequestAutoMerge(input:{pullRequestId:"X"}){clientMutationId}}'), "merge", gs.REFUSE),
    ("M7a", graphql('mutation{enqueuePullRequest(input:{pullRequestId:"X"}){clientMutationId}}'), "merge", gs.REFUSE),
    ("M8", "ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge some-branch --merge", "merge", gs.MERGE_GATE),
    ("M9", "ci-main-status --merge-gate a && pr-body-check a 5 && gh pr merge 5 -R cartwmic/other --merge", "merge", gs.MERGE_GATE),
    ("M10", "gh api repos/o/r/pulls/5/merge", "", gs.ALLOW),  # a GET asks whether it is merged
    # state changes and REST edits of a pull request or an issue
    ("S1", "gh pr close 5", "other", gs.ALLOW),
    ("S2", "gh pr reopen 5", "other", gs.ALLOW),
    ("S3", "gh pr ready 5", "other", gs.ALLOW),
    ("S4", "gh api -X PATCH repos/o/r/pulls/5 -f state=closed", "other", gs.ALLOW),
    ("S5", "gh api -X PATCH repos/o/r/pulls/5 -f title=x", "title", gs.REFUSE),
    ("S6", "gh api -X PATCH repos/o/r/pulls/5 -f base=main", "other", gs.ALLOW),
    ("B1", "gh api -X PATCH repos/o/r/pulls/5 -f body=x", "body", gs.REFUSE),
    ("B2", "gh api -XPATCH repos/o/r/pulls/5 -Fbody=@" + F, "body", gs.REFUSE),
    ("B3", "gh api -X PATCH repos/o/r/pulls/5 --input " + F, "title body", gs.REFUSE),
    ("B4", "gh api -X PATCH repos/o/r/issues/5 -f body=x", "body", gs.REFUSE),
    ("B5", "gh api -X PATCH repos/o/r/issues/5 -f title=x", "title", gs.REFUSE),
    ("B6", "gh api -X PATCH repos/o/r/issues/5 -f state=closed", "other", gs.ALLOW),
    ("B7", "gh api repos/o/r/pulls -f title=t -f head=h -f base=main -f body=x", NEW_PR, gs.REFUSE),
    ("B8", graphql('mutation{updatePullRequest(input:{pullRequestId:"X",body:"x"}){clientMutationId}}'), "title body", gs.REFUSE),
    ("B9", "gh api graphql -F query=@" + F, UNLISTED, gs.REFUSE),
    ("B10", "gh api graphql --input " + F, UNLISTED, gs.REFUSE),
    ("B11", graphql('mutation{createPullRequest(input:{repositoryId:"R",baseRefName:"main",headRefName:"h",title:"t",body:"b"}){clientMutationId}}'), NEW_PR, gs.REFUSE),
    ("B12", "gh api -X PATCH https://api.github.com/repos/o/r/pulls/5 -f body=x", "body", gs.REFUSE),
    ("B13", "gh api --hostname github.com -X PATCH repos/o/r/pulls/5 -f body=x", "body", gs.REFUSE),
    ("B14", "gh api -X PATCH repos/o/r/pulls/5/ -f body=x", "body", gs.REFUSE),
    ("B15", "gh api -X PATCH repositories/123/pulls/5 -f body=x", "body", gs.REFUSE),
    ("B16", "gh api --newflag v -X PATCH repos/o/r/pulls/5 -f body=x", UNLISTED, gs.REFUSE),
    ("B16a", "gh api -X PATCH repos/o/r/pulls/5 -f body=x --newflag=v", UNLISTED, gs.REFUSE),  # one operand, so only the unknown flag gives it away
    ("B16b", "gh api user --newflag", UNLISTED, gs.REFUSE),  # fails closed on a read too
    ("B17", "gh api -X PATCH 'repos/{owner}/{repo}/pulls/5?x=1' -f title=x", "title", gs.REFUSE),
    ("B18", "gh api -X PATCH repos/o/r/pulls/5 -f foo=1", UNLISTED, gs.REFUSE),
    ("B19", "gh api -X DELETE repos/o/r/pulls/5", UNLISTED, gs.REFUSE),
    ("B20", "gh api -X PATCH repos/o/r/pulls/5/../6 -f title=x", UNLISTED, gs.REFUSE),
    ("B21", "gh api -X PATCH 'repos/o/r/pulls%2F5' -f title=x", UNLISTED, gs.REFUSE),
    ("B22", "gh api -X POST repos/o/r/pulls/5/frobnicate", UNLISTED, gs.REFUSE),  # a write the table does not name, on the surface
    ("B23", "gh api -X POST repos/o/r/issues/5/frobnicate", UNLISTED, gs.REFUSE),
    ("B24", "gh api", UNLISTED, gs.REFUSE),
    ("G1", graphql('mutation M{updatePullRequest(input:{pullRequestId:"X",body:"x"}){clientMutationId}}'), "title body", gs.REFUSE),
    # issues
    ("I1", "gh issue create -t T -b x", NEW_ISSUE, gs.ISSUE_OPEN),
    ("I2", "gh issue edit 5 -b x", "body", gs.REFUSE),  # gh sends updatePullRequest for a PR number: the hook cannot tell, and no checked route to an issue's text exists yet
    ("I3", "gh issue edit 5 -F " + F, "body", gs.REFUSE),
    ("I4", "gh issue edit 5 -t T", "title", gs.REFUSE),
    ("I5", "gh issue comment 5 -b x", "comment", gs.ALLOW),
    ("I6", "gh issue close 5", "other", gs.ALLOW),
    ("I7", "gh api repos/o/r/issues -f title=t -f body=x", NEW_ISSUE, gs.ISSUE_OPEN),
    ("I8", graphql('mutation{createIssue(input:{repositoryId:"R",title:"t"}){clientMutationId}}'), NEW_ISSUE, gs.ISSUE_OPEN),
    ("I9", "gh issue -R o/r edit 5 -b x", "body", gs.REFUSE),
    ("I11", "gh api -X PATCH repos/o/r/issues/5 --input " + F, "title body", gs.REFUSE),
    ("I12", graphql('mutation{updateIssue(input:{id:"X",body:"x"}){clientMutationId}}'), "title body", gs.REFUSE),
    ("I13", "gh issue edit 5 --newflag x", UNLISTED, gs.REFUSE),
    # `gh issue edit`: text in any spelling is refused, whatever the number; only the label, assignee, milestone, project and link flags pass
    ("IE1", "gh issue edit 5 -tT", "title", gs.REFUSE),
    ("IE2", "gh issue edit 5 --title=T", "title", gs.REFUSE),
    ("IE3", "gh issue edit 5 --title T", "title", gs.REFUSE),
    ("IE4", "gh issue edit 5 --body=x", "body", gs.REFUSE),
    ("IE5", "gh issue edit 5 -bx", "body", gs.REFUSE),
    ("IE6", "gh issue edit 5 --body-file=f", "body", gs.REFUSE),
    ("IE7", "gh issue edit 5 -F -", "body", gs.REFUSE),
    ("IE8", "gh issue edit 5 --attach p.png", "body", gs.REFUSE),
    ("IE9", "gh issue edit 5 --attach=p.png", "body", gs.REFUSE),
    ("IE10", "gh -R o/r issue edit 5 -b x", "body", gs.REFUSE),
    ("IE11", "gh issue edit 5 6 -t T", "title", gs.REFUSE),
    ("IE12", "gh issue edit 5 --add-label x -b y", "other body", gs.REFUSE),  # one text flag refuses the whole command
    ("IE13", "gh issue edit 5 --title T --body-file " + F, "title body", gs.REFUSE),
    ("IE14", "gh issue edit https://github.com/o/r/pull/5 -b x", "body", gs.REFUSE),
    ("IE15", "gh issue edit 5 -b x --help --help=false", "body", gs.REFUSE),  # the last --help is false: the command runs
    ("IE16", "env gh issue edit 5 -b x", "body", gs.REFUSE),
    ("IE17", "bash -c 'gh issue edit 5 -b x'", "body", gs.REFUSE),
    ("IE18", "echo 5 | xargs gh issue edit -b x", "body", gs.REFUSE),
    ("IE19", "gh issue ed 5 -b x", UNLISTED, gs.REFUSE),
    ("IE20", "gh issue edit 5 --add-reviewer r", UNLISTED, gs.REFUSE),  # a pr edit flag, which gh issue edit does not have
    ("IE21", "gh issue edit 5 --add-label x --add-assignee a -m v --add-project p", "other", gs.ALLOW),
    ("IE22", "gh issue edit 5 -R o/r --remove-label x --remove-assignee a --remove-milestone --remove-project p", "other", gs.ALLOW),
    ("IE23", "gh issue edit 5 --parent 7 --add-sub-issue 8 --add-blocked-by 9 --type bug", "other", gs.ALLOW),
    ("IE24", "gh issue edit 888", "", gs.ALLOW),  # no flags: gh asks on a terminal, and an agent shell has none
    ("IE25", "gh issue edit 5 -- -t x", "", gs.ALLOW),  # after `--` the words are operands, not flags
    ("IE26", "gh issue edit 5 -t x --help", "", gs.ALLOW),  # a help read
    ("IE27", "gh issue edit 5 -h", "", gs.ALLOW),
    ("IE28", "gh pr edit 5 --add-label x --add-reviewer r --base main", "other", gs.ALLOW),
    ("I14", "gh issue delete 5", "other", gs.REFUSE),
    # comments and reviews: no check exists for them, and the review skills post them
    ("C1", "gh pr comment 5 -b x", "comment", gs.ALLOW),
    ("C2", "gh pr comment 5 -F " + F, "comment", gs.ALLOW),
    ("C3", "gh pr comment 5 --edit-last -b x", "comment", gs.ALLOW),
    ("C4", "gh pr review 5 --comment -b x", "comment", gs.ALLOW),
    ("C5", "gh api repos/o/r/issues/5/comments -f body=x", "comment", gs.ALLOW),
    ("C6", "gh api -X PATCH repos/o/r/issues/comments/9 -f body=x", "comment", gs.ALLOW),
    ("C7", "gh api repos/o/r/pulls/5/reviews -f body=x -f event=COMMENT", "comment", gs.ALLOW),
    ("C8", graphql('mutation{addComment(input:{subjectId:"X",body:"x"}){clientMutationId}}'), "comment", gs.ALLOW),
    ("C9", graphql('mutation{resolveReviewThread(input:{threadId:"X"}){clientMutationId}}'), "other", gs.ALLOW),
    ("C10", "gh api repos/o/r/pulls/5/comments/9/replies -f body=x", "comment", gs.ALLOW),
    # what is not a pull request or an issue
    ("O1", "gh api user", "", gs.ALLOW),
    ("O2", "gh api repos/o/r/pulls --jq '.[].number'", "", gs.ALLOW),
    ("O3", "gh api -X POST repos/o/r/git/refs -f ref=refs/heads/x -f sha=y", "", gs.ALLOW),  # not claimed: the API form of `git push`, left open
    ("O4", "gh repo view o/r", "", gs.ALLOW),
    ("O5", "gh pr list --state open", "", gs.ALLOW),
    ("O6", "gh pr view 5 --json body", "", gs.ALLOW),
    ("O7", "gh co 5", "", gs.ALLOW),
    ("O8", "gh pr checks 5 --repo o/r", "", gs.ALLOW),
    ("O9", "gh pr edit 5 --help", "", gs.ALLOW),
    ("O10", "gh pr", "", gs.ALLOW),
    ("O11", "gh --version", "", gs.ALLOW),
    ("O12", "pr-open --edit 5 --body-file " + F, "", gs.ALLOW),   # a child process the hook never sees gh in
    ("O13", "~/git/coordinator/scripts/merge-pr.sh 5", "", gs.ALLOW),
    ("O14", "gh event listen --repo o/r", "", gs.ALLOW),  # gh 2.105 `event`: prints a PR's events, sets no text, merges nothing
    # what gh may do that the table cannot read
    ("U1", "gh -x pr merge 5", UNLISTED, gs.REFUSE),
    ("U2", "gh pr -t T edit 5", UNLISTED, gs.REFUSE),
    ("U3", "gh pr merge 5 --newflag", UNLISTED, gs.REFUSE),
    ("U4", "gh pr edit 5 --newflag x -t T", UNLISTED, gs.REFUSE),
    ("U5", "gh pr frobnicate 5", UNLISTED, gs.REFUSE),
    ("U6", "gh brand-new-command", UNLISTED, gs.REFUSE),
    ("U7", "gh alias set pe 'pr edit' && gh pe 5 -b x", UNLISTED, gs.REFUSE),
    ("U8", "gh pe 5 -b x", UNLISTED, gs.REFUSE),
    ("U9", "gh pr merge 5 --help=false", "merge", gs.MERGE_GATE),  # `--help=false` runs the command
    # gh keeps the LAST value of a repeated `--help`: `--help` then `--help=false` runs the command. A `-h` anywhere is help to gh, so U9e is a help read the module
    # refuses (the safe direction); it stays a row to pin that the module never reads help where gh runs the command.
    ("U9a", "gh pr merge 5 --help --help=false", "merge", gs.MERGE_GATE),
    ("U9b", "gh pr merge 5 --help=false --help", "", gs.ALLOW),
    ("U9c", "gh pr merge 5 --help=0", "merge", gs.MERGE_GATE),
    ("U9d", "gh pr merge 5 --help=true", "", gs.ALLOW),
    ("U9e", "gh pr merge 5 -h --help=false", "merge", gs.MERGE_GATE),
    ("U9f", "gh pr merge 5 --help=false -h", "", gs.ALLOW),
    ("U9g", "gh pr merge 5 --help --help=0", "merge", gs.MERGE_GATE),
    ("U9h", "gh pr merge 5 --help=maybe", "merge", gs.MERGE_GATE),  # gh rejects a value it cannot read; refuse rather than call it help
    ("U9i", "gh pr merge 5 --help=false --help=true", "", gs.ALLOW),
    ("U9j", "gh api -X PUT repos/o/r/pulls/5/merge --help --help=false", "merge", gs.REFUSE),
    ("U9k", "gh pr edit 5 -b x --help --help=false", "body", gs.PR_BODY),
    ("U9l", "gh api -X PUT repos/o/r/pulls/5/merge --help=false --help", "", gs.ALLOW),
    ("U10", "gh pr revert 5", NEW_PR, gs.REFUSE),
    ("U11", "gh agent create x", "pr-create", gs.REFUSE),
    # the same gh commands behind a wrapper the hook unwraps
    ("W1", "GH_CALLER=pr-open gh pr edit 5 -b x", "body", gs.PR_BODY),
    ("W2", "/usr/bin/gh pr edit 5 -b x", "body", gs.PR_BODY),
    ("W3", "env gh pr edit 5 -b x", "body", gs.PR_BODY),
    ("W4", "echo 5 | xargs gh pr edit -b x", "body", gs.PR_BODY),
    ("W5", "bash -c 'gh pr edit 5 -b x'", "body", gs.PR_BODY),
    ("W6", "gh pr edit 5 -F -", "body", gs.PR_BODY),
    # graphql: what the tokenizer reads and what it cannot
    ("Q1", graphql("query{viewer{login}}"), "", gs.ALLOW),
    ("Q2", graphql("query{viewer{login}} # mergePullRequest"), "", gs.ALLOW),
    ("Q2a", graphql('mutation{addComment(input:{subjectId:"X",body:"b"}){clientMutationId} # mergePullRequest\n}'), "comment", gs.ALLOW),  # a comment at the root is not a field
    ("Q3", graphql('mutation{addComment(input:{subjectId:"X",body:"mergePullRequest"}){clientMutationId}}'), "comment", gs.ALLOW),
    ("Q4", graphql('mutation{a: mergePullRequest(input:{pullRequestId:"X"}){clientMutationId}}'), "merge", gs.REFUSE),
    ("Q5", graphql('mutation{addComment(input:{subjectId:"X",body:"b"}){clientMutationId} mergePullRequest(input:{pullRequestId:"X"}){clientMutationId}}'), "comment merge", gs.REFUSE),
    ("Q6", graphql("mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}", " -F t=THREAD_ID"), "other", gs.ALLOW),
    ("Q7", graphql('mutation{...F} fragment F on Mutation{mergePullRequest(input:{pullRequestId:"X"}){clientMutationId}}'), UNLISTED, gs.REFUSE),
    ("Q8", graphql('mutation{deleteRef(input:{refId:"X"}){clientMutationId}}'), UNLISTED, gs.REFUSE),
    ("Q9", 'gh api graphql -f query="$(cat /tmp/q.graphql)"', UNLISTED, gs.REFUSE),
    ("Q10", "gh api graphql -f query=@" + F, UNLISTED, gs.REFUSE),
    ("Q11", "gh api graphql -f query='$Q'", UNLISTED, gs.REFUSE),
    ("Q12", "gh api graphql", UNLISTED, gs.REFUSE),
    ("Q13", graphql('mutation{addComment(input:{body:"x}){id}}'), UNLISTED, gs.REFUSE),
    ("Q14", graphql("query{viewer{login}}", " -f query='mutation{mergePullRequest(input:{pullRequestId:\"X\"}){clientMutationId}}'"), "merge", gs.REFUSE),
    ("Q15", graphql('mutation{addComment(input:{subjectId:"X",body:"""mergePullRequest { x }"""}){clientMutationId}}'), "comment", gs.ALLOW),
    ("Q16", graphql("query{mutation: viewer{login}}"), "", gs.ALLOW),
    ("Q17", graphql('query Q($o:String!){repository(owner:$o,name:"r"){id}}', " -F o=x"), "", gs.ALLOW),
    ("Q18", graphql("mutation{}"), UNLISTED, gs.REFUSE),
    ("Q19", graphql('mutation{addComment(input:{subjectId:"X",body:"b"}){clientMutationId}'), UNLISTED, gs.REFUSE),
    ("Q21", graphql('mutation{addComment(input:{subjectId:"X",body:"#"}){clientMutationId} mergePullRequest(input:{pullRequestId:"X"}){clientMutationId}}'), "comment merge", gs.REFUSE),  # a # in a string starts no comment
    ("Q22", graphql('mutation{addComment(input:{subjectId:"X",body:"}}"}){clientMutationId} mergePullRequest(input:{pullRequestId:"X"}){clientMutationId}}'), "comment merge", gs.REFUSE),  # braces in a string close nothing
    ("Q20", "gh api graphql -f query=@- < " + F, UNLISTED, gs.REFUSE),
]

# The rows the hook let through before gh_surface: none may be ALLOW, and each is a row the allow-everything stub gets wrong. (U9e is not one: gh prints help for it and the hook refused it before.)
HOLES = {"I2", "I3", "I4", "I9", "IE1", "IE2", "IE3", "IE4", "IE5", "IE6", "IE7", "IE8", "IE9", "IE10", "IE11", "IE12", "IE13", "IE14", "IE15", "IE16", "IE17", "IE18", "U9a", "U9g", "U9j", "U9k", "M5", "M6", "M7", "S5", "B5", "B8", "B9", "B10", "B11", "B15", "B16", "G1", "I8", "I12"}
# The rows that must stay allowed, whatever else changes: the sanctioned writers and the commands the review skills run.
STAY_ALLOWED = {"P6", "P7", "P8", "S1", "S2", "S3", "S4", "S6", "B6", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "I5", "I6", "IE21", "IE22", "IE23", "IE24", "IE25", "IE26", "IE27", "IE28", "O12", "O13", "O14"}


def classify(command, surface=gs.surface):
    """(effects, verdict, listed) of a command line: the union over every gh command in it, with the strictest verdict."""
    found = [surface(bash_rules.gh_command(c.words[1:])) for c in bash_rules.Walk(command).cmds if bash_rules._base(c.words[0]) == "gh"]
    return (frozenset().union(*(s.effects for s in found)), max((s.verdict for s in found), key=gs.SEVERITY.index, default=gs.ALLOW), all(s.listed for s in found))


def mismatch(row, surface=gs.surface):
    """A sentence naming what a classifier got wrong for one row, or None."""
    rid, command, expected, verdict = row
    effects, got, listed = classify(command, surface)
    if expected is UNLISTED:
        return None if (got, listed) == (gs.REFUSE, False) else "%s: %s is not refused as unlisted (verdict %s, listed %s)" % (rid, command, got, listed)
    if (effects, got, listed) != (frozenset(expected.split()), verdict, True):
        return "%s: %s is %s %s (listed %s), expected %s %s" % (rid, command, sorted(effects), got, listed, expected.split(), verdict)
    return None


def stub(gh):
    """The classifier the hook behaved like before: it allows everything and reads nothing."""
    return gs.Surface(frozenset(), gs.ALLOW, True, "", "stub")


class Table(unittest.TestCase):
    def test_every_row_classifies_as_the_effect_it_has(self):
        for row in ROWS:
            with self.subTest(row=row[0]):
                self.assertIsNone(mismatch(row))

    def test_the_ids_are_unique_and_the_named_sets_name_rows(self):
        ids = [row[0] for row in ROWS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(HOLES | STAY_ALLOWED, set(ids))

    def test_no_hole_is_allowed(self):
        for row in ROWS:
            if row[0] in HOLES:
                with self.subTest(row=row[0]):
                    self.assertNotEqual(classify(row[1])[1], gs.ALLOW)

    def test_the_rows_that_must_stay_allowed_are_allowed(self):
        for row in ROWS:
            if row[0] in STAY_ALLOWED:
                with self.subTest(row=row[0]):
                    self.assertEqual(classify(row[1])[1:], (gs.ALLOW, True))

    def test_a_classifier_that_allows_everything_fails_every_hole(self):
        """The table is what fails on the past: the stub that stands for the hook before gh_surface gets each hole row wrong."""
        for row in ROWS:
            if row[0] in HOLES:
                with self.subTest(row=row[0]):
                    self.assertIsNotNone(mismatch(row, stub))
        self.assertEqual(sum(mismatch(row, stub) is not None for row in ROWS) > len(HOLES), True, "the stub also fails the other rows that are not plain reads")


class Spellings(unittest.TestCase):
    """The same write in every spelling gh reads gives the same answer."""

    def test_a_method_in_any_spelling_and_case(self):
        for method in ("-X PUT", "-XPUT", "-X=PUT", "--method PUT", "--method=PUT", "-X put", "--method=Put"):
            with self.subTest(method=method):
                self.assertEqual(classify("gh api %s repos/o/r/pulls/5/merge" % method)[:2], (frozenset({"merge"}), gs.REFUSE))

    def test_an_endpoint_in_every_form(self):
        for endpoint in ("repos/o/r/pulls/5/merge", "/repos/o/r/pulls/5/merge", "repos/o/r/pulls/5/merge/", "repositories/1/pulls/5/merge", "repos/{owner}/{repo}/pulls/5/merge",
                         "https://api.github.com/repos/o/r/pulls/5/merge", "https://ghe.example.com/api/v3/repos/o/r/pulls/5/merge", "repos/o/r/pulls/5/merge?merge_method=squash"):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(classify("gh api -X PUT '%s'" % endpoint)[:2], (frozenset({"merge"}), gs.REFUSE))

    def test_a_flag_in_any_place_does_not_hide_the_endpoint(self):
        for command in ("gh api -X PUT repos/o/r/pulls/5/merge --hostname github.com", "gh api --hostname github.com repos/o/r/pulls/5/merge -X PUT",
                        "gh -R o/r api -X PUT repos/o/r/pulls/5/merge", "gh api -i -X PUT repos/o/r/pulls/5/merge --silent"):
            with self.subTest(command=command):
                self.assertEqual(classify(command)[:2], (frozenset({"merge"}), gs.REFUSE))

    def test_a_field_in_any_spelling(self):
        for field in ("-f body=x", "-fbody=x", "-f=body=x", "--raw-field body=x", "--raw-field=body=x", "-F body=@f", "--field body=x", "-F 'body[]=x'"):
            with self.subTest(field=field):
                self.assertIn("body", classify("gh api -X PATCH repos/o/r/pulls/5 %s" % field)[0])

    def test_a_pr_edit_flag_in_every_spelling(self):
        for flags, effects in (("-t T", "title"), ("-tT", "title"), ("--title T", "title"), ("--title=T", "title"), ("-b x", "body"), ("-F f", "body"), ("--body-file f", "body"),
                               ("--body-file=f", "body"), ("-R o/r -b x", "body"), ("-R o/r --add-label x", "other")):
            with self.subTest(flags=flags):
                self.assertEqual(classify("gh pr edit 5 " + flags)[0], frozenset(effects.split()))


class Reader(unittest.TestCase):
    def test_graphql_root_fields(self):
        read = gs.mutation_fields
        self.assertEqual(read("query{a{b}}"), [])
        self.assertEqual(read("{a}"), [])
        self.assertEqual(read("mutation{a(x:1){b} c}"), ["a", "c"])
        self.assertEqual(read("mutation M($x:In!=\"d\"){z:a(input:{k:[1,2]},y:$x)@include(if:true){b}}"), ["a"])
        self.assertEqual(read("mutation{a}\nquery Q{b}\nmutation N{c}"), ["a", "c"])

    def test_graphql_that_cannot_be_read_is_none(self):
        for text in ("", "   ", "mutation{", "mutation{a}}", "mutation{a(}", 'mutation{a(x:"y)}', "mutation{...F}", "mutation{}", "mutation{ ... on Mutation { a } }", "mutation{a(x:$(id))}"):
            with self.subTest(text=text):
                self.assertIsNone(gs.mutation_fields(text))


def verdict_of(*words):
    return gs.surface(bash_rules.gh_command(list(words)))


class EditFlags(unittest.TestCase):
    """`gh issue edit` and `gh pr edit` read every flag from one table (EDIT_FLAGS), and the table follows the flags the hook's FLAG_ROWS name."""

    @staticmethod
    def long_names(*keys):
        return set(bash_rules._table(*keys)[0]) - gs.EDIT_IGNORED

    def test_edit_flags_cover_the_flag_rows(self):
        """A flag added to either edit row and not to the table fails here, instead of passing as a no-effect flag."""
        self.assertEqual(set(gs.EDIT_FLAGS), self.long_names(("issue", "edit"), ("pr", "edit")))

    def test_a_flag_the_table_lacks_is_refused_not_passed(self):
        """Every flag of both rows is listed; one that is dropped from the table comes back unlisted (the check can fail)."""
        smaller = {k: v for k, v in gs.EDIT_FLAGS.items() if k != "add-label"}
        original = gs.EDIT_FLAGS
        try:
            gs.EDIT_FLAGS = smaller
            got = verdict_of("issue", "edit", "5", "--add-label", "x")
        finally:
            gs.EDIT_FLAGS = original
        self.assertEqual((got.verdict, got.listed), (gs.REFUSE, False))
        self.assertIn("`add-label`", got.reason)
        self.assertIn("EDIT_FLAGS", got.reason)  # the fix named is the one that works: add the flag to EDIT_FLAGS, not "add a row"
        self.assertIn("FLAG_ROWS", got.reason)

    def test_a_flag_the_hook_does_not_know_names_both_tables_to_fix(self):
        for words in (("pr", "edit", "5", "--newflag"), ("issue", "edit", "5", "--newflag"), ("api", "user", "--newflag")):
            with self.subTest(words=words):
                got = verdict_of(*words)
                self.assertEqual((got.verdict, got.listed), (gs.REFUSE, False))
                self.assertIn("`--newflag`", got.reason)
                self.assertIn("FLAG_ROWS", got.reason)

    def test_a_flag_before_the_subcommand_says_where_to_put_it_and_never_shows_its_value(self):
        got = verdict_of("pr", "--title=SECRETVALUE", "edit", "5")
        self.assertEqual((got.verdict, got.listed), (gs.REFUSE, False))
        self.assertIn("`--title`", got.reason)
        self.assertNotIn("SECRETVALUE", got.reason)
        self.assertIn("so the hook cannot tell the subcommand", got.reason)
        self.assertIn("Put the flag after the subcommand", got.reason)

    def test_the_report_names_each_flag_once_with_its_verdict(self):
        lines = edit_flags_report()
        self.assertEqual(sorted(line.split()[0] for line in lines), sorted("--" + k for k in gs.EDIT_FLAGS))
        by_flag = {line.split()[0]: line.split() for line in lines}
        self.assertEqual(by_flag["--body"][2:], ["refuse", "pr-body"])
        self.assertEqual(by_flag["--add-label"][2:], ["allow", "allow"])
        self.assertEqual(by_flag["--add-reviewer"][2:], ["-", "allow"])  # a flag `gh issue edit` does not have


class Reasons(unittest.TestCase):
    """A refusal text must not send an agent to a command the module refuses."""

    @staticmethod
    def reasons():
        texts = [v for k, v in vars(gs).items() if k.startswith("WHY_") and isinstance(v, str)]
        for table in (gs.PR_VERBS, gs.ISSUE_VERBS, gs.AGENT_TASK_VERBS):
            texts += [row[2] for row in table.values() if len(row) > 2]
        return texts

    def test_commands_named_in_reasons_are_allowed(self):
        named = []
        for text in self.reasons():
            for span in re.findall(r"`([^`]+)`", text):
                if span.startswith("gh ") and "%s" not in span:
                    named.append(span)
                    with self.subTest(command=span):
                        got = gs.surface(bash_rules.gh_command(span.split()[1:]))
                        self.assertTrue(got.listed and got.verdict != gs.REFUSE, "%s is named in a refusal text but the module refuses it: %s" % (span, got.verdict))
        self.assertTrue(named, "no gh command is named in any refusal text, so this test reads nothing")

    def test_the_check_can_fail(self):
        """The old texts sent agents to `gh issue edit N --body-file F`, which is refused now."""
        got = gs.surface(bash_rules.gh_command("issue edit N --body-file F".split()))
        self.assertEqual(got.verdict, gs.REFUSE)

    def test_no_reason_sends_an_agent_to_gh_issue_edit_for_text(self):
        for text in self.reasons():
            with self.subTest(text=text[:50]):
                self.assertNotIn("gh issue edit", text)


class Skills(unittest.TestCase):
    """Every gh command the two review skills tell an agent to run passes (verdict ALLOW, and the module lists it), so the skills and the allow table cannot drift apart."""
    SKILLS = ["dot_local/share/agent-harness/canonical/skills/triaging-automated-review/SKILL.md", "dot_local/share/agent-harness/canonical/skills/reviewing-prs/SKILL.md.tmpl"]

    @staticmethod
    def commands(text):
        """The gh commands in a skill: every fenced block, and every inline code span that is a command (`gh` and at least two more words; `gh api` alone is a mention)."""
        blocks = re.findall(r"^```\w*\n(.*?)^```", text, re.M | re.S)
        spans = [s for s in re.findall(r"`([^`\n]+)`", re.sub(r"^```.*?^```", "", text, flags=re.M | re.S)) if re.match(r"gh \S+ \S+", s)]
        return blocks + spans

    def test_every_gh_command_in_the_skills_is_allowed(self):
        seen = []
        for name in self.SKILLS:
            for text in self.commands((ROOT / name).read_text()):
                for cmd in bash_rules.Walk(text).cmds:
                    if bash_rules._base(cmd.words[0]) == "gh":
                        seen.append(" ".join(cmd.words))
                        with self.subTest(skill=Path(name).parent.name, command=" ".join(cmd.words)[:80]):
                            got = gs.surface(bash_rules.gh_command(cmd.words[1:]))
                            self.assertEqual((got.verdict, got.listed), (gs.ALLOW, True))
        # not vacuous: the five commands of triaging-automated-review (checks, the thread query, the reply, the resolve, the bot re-run)
        self.assertGreaterEqual(len(seen), 5, seen)
        self.assertTrue(any("graphql" in c for c in seen) and any("replies" in c for c in seen) and any("pr comment" in c for c in seen), seen)


def edit_flags_report():
    """One line per EDIT_FLAGS key: the flag, its effect, and the verdict of `gh issue edit` and of `gh pr edit` carrying just that flag (`-` where the command does not have it)."""
    table = bash_rules._table(("issue", "edit"), ("pr", "edit"))[0]
    lines = []
    for name, effect in gs.EDIT_FLAGS.items():
        shown = []
        for group in ("issue", "pr"):
            got = verdict_of(group, "edit", "5", "--" + name, *(["x"] if table[name][1] else []))
            shown.append(got.verdict if got.listed else "-")
        lines.append("%-22s %-6s %-7s %s" % ("--" + name, effect, shown[0], shown[1]))
    return lines


if __name__ == "__main__":
    import sys
    if "--edit-flags" in sys.argv:
        print("%-22s %-6s %-7s %s" % ("flag", "effect", "issue", "pr"))
        print("\n".join(edit_flags_report()))
    else:
        unittest.main()
