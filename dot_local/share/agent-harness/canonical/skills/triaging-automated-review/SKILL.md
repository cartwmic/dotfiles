---
name: triaging-automated-review
description: Use when pull request feedback needs working through, whether it comes from bots such as Claude Code Review or Cursor Bugbot or from people, or when the owner asks you to carry a PR through automated review. It waits for the bots, tests every finding for being real, useful, maintainable and in scope, then fixes it, defers it to a follow-up or declines it with the failed test named. It answers and resolves bot threads, drafts replies to people for the owner to approve, asks the bots to look again, finishes with a reviewing-prs pass on the final head, and stops when a round brings nothing new.
---

# Triaging automated review

The aim is a PR where each finding, whether a bot, a person or your own review
raised it, ended up fixed, deferred or declined, with a reason that holds. The
bots' threads are answered and closed, the people's findings are triaged with
drafted replies waiting for the owner, and the head you hand over has been
through `reviewing-prs`.

## Before you start

- Work only on a PR the owner asked you to take through review. That covers
  pushing fixes to its branch, answering and resolving bot threads, and posting
  a bot's re-run command. Requesting reviewers, marking it ready, approving and
  merging are the owner's.
- Findings from people count too, but you write drafts only. A reply to a person goes
  out under the owner's name, so the owner has to approve that exact text before
  each send. Until then it stays in your report. Their threads are theirs to
  resolve unless the owner says otherwise.
- Find out what the PR is for and what larger change it belongs to: the body,
  the linked ticket or plan, any sibling PRs.
- **Local overlays.** For each
  `~/.local/share/agent-harness/external-skills/*/skills/triaging-automated-review/SKILL.md`
  that exists, read it. It names the bots, check names, hosts, preflight and
  repo rules for the repos it covers. Where it applies to the PR's remote,
  follow it. Where it conflicts with this file, it wins. If none exists, skip
  silently.

## Loop

1. **Let the bots finish.** Run `gh pr checks NUMBER --repo OWNER/REPO` and
   hold while any bot check is pending, because a half-posted review gives you
   half the findings. A check that only waits for a person is not a bot check.
2. **List the unresolved threads** with the query under [Commands](#commands),
   from bots and people alike. Read people's top-level reviews and comments too.
   A thread marked outdated (`isOutdated`, `line: null`) still has an
   `originalLine`; compare it with the current code before you decide.
3. **Triage.** Open the code each finding points at, apply the
   [four tests](#the-four-tests), and note the verdict, with the failed test for
   anything you defer or decline.
   A finding from a reviewer agent whose return carries a `repro` (the
   `reviewing-prs` pass in step 8) first gets `agent-traces review repro`: a
   finding whose repro does not reproduce is declined, unless you write why it
   stands (`finding-triage.md`).
4. **Fix, test, lint, push.** Commit each fix small, on the PR's own branch, and
   run the checks the repo has for what you changed before you push.
5. **Answer and resolve.** In each bot thread you triaged, post one reply:
   "Fixed in `<sha>`: <what changed>", "Declined (<test>): <true reason>" or
   "Deferred, outside this PR: <follow-up>". Then resolve it. **Before you
   resolve a bot thread, read every reply in it.** If any reply's author is
   neither a bot nor the owner (the `viewer` login), treat the thread as a human
   finding: draft the reply for the owner and leave the thread open. Your own
   replies post as the owner and do not count. Replies for people's threads are
   drafts, sent only once the owner approves the exact text. For a person's
   top-level review or comment, draft a single PR comment that covers each
   finding in it. Use the `no-ai-slop` skill for every reply: brief, and
   sounding like the owner.
6. **Pushed? Return to step 1.** The push may trigger another bot pass.
7. **Re-request or re-run the bot reviews.** Once nothing is left to fix, or
   only declines and deferrals remain, send each bot its re-run command, or
   re-request its review, where it has one. Wait for it (step 1) and triage
   what it adds. If there is no re-run, or it brings no new applicable finding,
   go to step 8.
8. **Run the `reviewing-prs` skill on the final head**, as an extra pair of
   eyes. (That skill is meant for other people's work; the owner asked for it
   here.)
9. **Triage what it finds** by the same four tests, fix what passes and push.
   Its findings have no threads, so put declines and deferrals in the report.
10. **Go round again** until a round turns up nothing that applies. What goes to
    people must be the head that was reviewed last. If you pushed after that
    review, review just the new commits (`<last reviewed sha>..HEAD`).

Write any PR body text with the `no-ai-slop` skill as well.

## The four tests

Run the four tests in `~/.local/share/agent-harness/finding-triage.md` on every
finding, whoever wrote it: real, useful, maintainable, fits. Authorship proves
nothing: a person's or a bot's finding is a claim until it passes. That file holds the wording; this
skill does not restate it. What this skill adds for PR review:

- **Real.** If a finding rests on how a dependency behaves, read that
  dependency's source. Something you cannot confirm does not pass this test yet.
- **Useful.** Comment wording, test style and coverage points are not useful on
  their own. Take one only if it leaves a test unable to fail, makes a test
  flaky, or leaves something false on record that later work will build on.
- **Maintainable.** Name the `~/.local/share/agent-harness/design-principles.md`
  section in your verdict, whether it backs the fix or rules it out. Adding a
  layer, limit or safeguard that was never requested breaks §4 or §9, judgment
  moved into code breaks §8, and an import across components breaks §7. When the proposed fix fails,
  look for a smaller one that passes, and decline only if none does.
- **Fits.** A finding that reverses something the owner decided fails this
  test. When scope is unclear, ask (see [Stop](#stop)).

## Outcomes

- **Fix:** it passes all four tests.
- **Defer:** it is real but belongs outside this PR (test 4, fits). Say so in the
  reply and name where it goes: an existing ticket, or a line in your report. File
  no ticket unasked. Do not fix it in this PR, and it must not hold the PR up. List
  deferrals apart from declines in the report.
- **Decline:** it fails test 1, 2 or 3, or reverses an owner decision. The reply
  names the failed test.

Check every reason you give before you give it. "An existing test covers it"
needs that test's name. If a finding you declined earlier comes back, test the
old reason again and reuse it only if it still holds. After fixing a helper,
`git grep` for its callers and fix or justify each one.

## Stop

Stop and report to the owner when:

- nothing applies to the current head. Report the rounds, each fix with its SHA,
  each decline with the failed test and reason, each deferral with where it
  goes, where the bots and the self-review stand, and the drafted replies to
  people that wait for approval;
- a finding calls for a scope or product decision. Ask, and say what you
  recommend; or
- round after round brings the same kind of finding and the count is not
  falling. Say what keeps coming back rather than looping again.

## Commands

```sh
# unresolved threads, plus who "the owner" is (owner, repo, number)
gh api graphql -f query='
query($o:String!,$r:String!,$n:Int!){viewer{login} repository(owner:$o,name:$r){pullRequest(number:$n){
  reviewThreads(first:100){nodes{id isResolved isOutdated path line originalLine
    root:comments(first:1){nodes{databaseId}}
    comments(last:20){totalCount nodes{author{login __typename} body}}}}}}}' \
  -F o=OWNER -F r=REPO -F n=NUMBER

# answer in a thread (the root comment's databaseId, `root` above)
gh api repos/OWNER/REPO/pulls/NUMBER/comments/COMMENT_ID/replies -f body="$(cat reply.md)"

# close a thread (its id from the query)
gh api graphql -f query='mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}' -F t=THREAD_ID

# ask a bot that listens for PR comments to run again
gh pr comment NUMBER --repo OWNER/REPO --body "<the bot's re-run command>"
```

With more than 100 threads, page through them with
`reviewThreads(first:100, after:$cursor)`. A comment is a bot's when its
author's `__typename` is `Bot`, and the owner's when its login is the `viewer`
login; GraphQL gives a bot's login bare where REST adds `[bot]`. If a thread's
`totalCount` is over 20, page back before you resolve it.
