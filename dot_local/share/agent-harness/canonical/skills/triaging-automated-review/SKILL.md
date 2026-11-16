---
name: triaging-automated-review
description: Use when a PR has review findings to triage, from bots (Claude Code Review, Cursor Bugbot or similar) or from human reviewers, or when the owner asks to take a PR through automated review to approval. It waits for bot reviews, puts every finding through four tests (real, useful, maintainable, fits intent), fixes what passes, defers out-of-scope findings to a follow-up, declines the rest with the failed test named, replies to and resolves bot threads, drafts replies to humans, re-runs the bots, then runs reviewing-prs on the final head, and repeats until nothing applies. Replies to humans are drafts until the owner approves them.
---

# Triaging automated review

Goal: every review finding on the PR, from a bot, a human or self-review, is
fixed, deferred or declined with a true reason. Bot threads are answered and
resolved. Human findings are triaged, with their draft replies approved or
listed as pending. The final head has passed `reviewing-prs`.

## Before you start

- The owner must have asked for this on this PR. That covers pushing fixes to
  the PR branch, replying in and resolving bot threads, and posting a bot's
  re-run command. It does not cover requesting reviewers, marking ready,
  approving or merging.
- **Human reviewers' findings are in scope, but you only draft.** Never post a
  reply to a human under the owner's name until the owner approves that exact
  text for that send. Triage the finding, write the draft reply, and put it in
  the report. After approval, post it. Leave the thread for the reviewer to
  resolve unless the owner says to resolve that one.
- Know the PR's intent, and the intent of the larger change it belongs to: read
  the PR body and any linked ticket, plan or sibling PRs.
- **Local overlays.** For each
  `~/.local/share/agent-harness/external-skills/*/skills/triaging-automated-review/SKILL.md`
  that exists, read it. It names the bots, check names, hosts, preflight and
  repo rules for the repos it covers. Where it applies to the PR's remote,
  follow it. Where it conflicts with this file, it wins. If none exists, skip
  silently.

## Loop

1. **Wait for bot checks.** Read `gh pr checks NUMBER --repo OWNER/REPO` and
   wait while any bot check is pending; do not triage a half-posted review. A
   check that waits for a human is not a bot check; ignore it.
2. **List open review threads** with the GraphQL query in
   [Commands](#commands). Keep the unresolved ones, from bots and humans. Also
   read top-level review bodies and comments from humans; they carry findings
   too. For an outdated thread (`isOutdated`, `line: null`) read
   `originalLine` and check whether the code it pointed at still exists.
3. **Triage** each finding. Open the code it points at and run the
   [four tests](#the-four-tests). Write down the verdict and, for a decline or
   deferral, the test it failed.
4. **Fix, test, lint, push.** Make the fixes as small commits on the same
   branch. Run the repo's tests and lints for what you touched, then push.
5. **Reply and resolve.** For every bot thread you triaged, reply in the thread
   ("Fixed in `<sha>`: what changed.", "Declining: fails <test>, the true
   reason.", or "Out of scope for this PR: follow-up <ticket or note>."), then
   resolve it. For a human's thread, write the same reply as a draft and post
   it only after the owner approves that exact text. For a human's top-level
   review or comment, draft one PR comment that answers each finding in it.
   Write each reply with the `no-ai-slop` skill: short, in the owner's voice.
6. **If you pushed, go to step 1.** A push can start a new bot review.
7. **Re-request or re-run the bot reviews.** When no findings are left, or the
   latest are all declined or deferred, post each bot's re-run command, or
   re-request its review, if it has one. Then go to step 1.
8. **Run the `reviewing-prs` skill on the final head**, as a fresh-eyes pass.
   (That skill is for someone else's work; the owner asked for it here.)
9. **Triage its findings** with the same four tests, fix what passes, and push.
   Self-review findings have no threads: report declines and deferrals to the
   owner instead.
10. **Repeat** until a round brings nothing applicable. The head that goes to
    humans must be the head that was last reviewed; if you pushed after the
    self-review, review the new delta (`<last reviewed sha>..HEAD`).

Write any PR body text with the `no-ai-slop` skill too.

## The four tests

Every finding gets all four, whoever wrote it. A finding is not right because a
person or a bot wrote it. The shared wording is
`~/.local/share/agent-harness/finding-triage.md`.

1. **Real.** Verify it against the code: reproduce it or read it. A claim about
   a dependency's behaviour needs the dependency's source read. A finding you
   cannot verify is not real yet.
2. **Useful.** Fixing it is worth the change, including the cost of another
   review cycle. A real defect, missing requirement, security or data risk, or
   break of a written repo convention is useful. Style the repo does not
   require is not, and neither is a fix that an existing job or check already
   does (gold plating). Comment, test-style and coverage findings are not
   useful by default; take one only when it makes a test unable to fail, makes
   a test flaky, or states something false that a later change will rely on.
3. **Maintainable.** The fix serves long-term maintainability under
   `~/.local/share/agent-harness/design-principles.md`. Cite the section in
   your verdict, whether it supports the fix or blocks it: a layer, cap or guard
   nobody asked for fails §4 or §9; moving judgment into code fails §8; a
   cross-component import fails §7. This test judges the fix. If the suggested
   fix fails, pick a smaller one that passes. Decline under this test only when
   no fix passes.
4. **Fits.** It fits the intent and scope of this PR and of the overall change
   it belongs to. A problem that existed before the PR, or is outside its
   scope, is deferred. A defect the PR itself introduces is always in scope. A
   finding that undoes a decision the owner made fails here.

## Outcomes

- **Fix:** passes all four tests.
- **Defer:** real, but out of this PR's scope (test 4). The reply says so and
  names the follow-up (an existing ticket, or a note in the report; file no
  ticket unasked). It is never fixed in this PR and never blocks it. The report
  lists deferred findings apart from declined ones.
- **Decline:** fails test 1, 2 or 3, or undoes an owner decision. The reply
  names the test it failed.

Every decline reason must be true and checked, not asserted: "an existing test
covers it" needs the test's name. A finding you declined before comes back:
re-check the earlier reason before declining again, and reuse it if it still
holds. When you fix a helper, `git grep` its callers and fix or justify each.

## Stop

Stop and report to the owner when:

- nothing applies on the current head. Report the rounds run, fixes with SHAs,
  declines with the failed test and reason, deferrals with their follow-ups,
  bot state, self-review state, and the draft replies to humans awaiting
  approval;
- a finding needs a scope or product decision. Ask, with your recommendation; or
- rounds keep repeating the same class of finding and the count does not go
  down. Say what keeps recurring instead of looping.

## Commands

```sh
# open threads (owner, repo, number)
gh api graphql -f query='
query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){pullRequest(number:$n){
  reviewThreads(first:100){nodes{id isResolved isOutdated path line originalLine
    comments(first:1){nodes{databaseId author{login} body}}}}}}}' \
  -F o=OWNER -F r=REPO -F n=NUMBER

# reply in a thread (databaseId of the thread's first comment)
gh api repos/OWNER/REPO/pulls/NUMBER/comments/COMMENT_ID/replies -f body="$(cat reply.md)"

# resolve a thread (id from the query)
gh api graphql -f query='mutation($t:ID!){resolveReviewThread(input:{threadId:$t}){thread{isResolved}}}' -F t=THREAD_ID

# re-run a bot that reads a PR comment
gh pr comment NUMBER --repo OWNER/REPO --body "<the bot's re-run command>"
```

More than 100 threads: page with `reviewThreads(first:100, after:$cursor)`.
GraphQL returns a bot's login bare; REST adds `[bot]`. Match the form your API
returns.
