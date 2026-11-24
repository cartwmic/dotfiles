# Finding triage

Whoever acts on review findings (the driver, the author, the agent applying fixes) runs these four tests on every finding, whoever raised it: a person, a bot or a reviewer agent. Who wrote a finding does not make it true.

1. **Real.** It holds when checked against the code, the document or a run. Say how you checked.
2. **Useful.** Fixing it changes something a user, a caller or the next maintainer would notice. Taste and hypotheticals fail. So does a fix that an existing job, check or process already does.
3. **Maintainable.** Test the finding and its fix against the owner's design principles, `~/.local/share/agent-harness/design-principles.md`. A fix that breaks a principle is declined: cite the section. A fix that adds machinery the need does not require fails §4. A cap that hides a wrong cause fails §9.
4. **In intent.** It fits the stated intent and scope of the change under review and of the overall work that change belongs to. Anything else, especially a problem that existed before the change, is a follow-up, not part of this change. A defect the change itself introduces (a regression, broken behaviour, data loss in what it touches) is always in scope, even if the stated intent does not mention it. Only problems the change did not cause can be follow-ups.

Run them in order. Act on a finding that passes all four.

- **Failed test 1, 2 or 3:** decline it with one short reason that starts with the test it failed.
- **Failed test 4:** it is a follow-up. Do not decline or drop it. Mention it as a non-blocking note that starts "for a follow-up:". It never blocks the change and is never a blocker or should-fix.
- **Fixing one that passed: fix the claim, not the line.** A finding names one sentence, flag, count or example that is wrong. That claim has a copy in every artifact that states it: the code, a skill or help text, the tests, the PR description and the agent record. Fix the source, then search the others for the claim's distinctive words (grep the PR description and the agent record for the old phrase) and fix every copy that still says it. A fix that corrects the one line the finding cites and leaves a copy in the PR description is the commonest reason a finding comes back as a follow-on. Say in the disposition which copies you searched. Then read the whole PR description against the new diff once; `Description checked` says you did, not that it is right. If the finding gives a command (a repro or a "done when"), run it after the fix and quote its result.

```
declined (useful): the message is never shown to a user
for a follow-up: the retry loop already had no cap before this change
```

List the declined findings (with reasons) and the follow-ups in whatever the owner reads: a draft, report or summary. That lets the owner overrule. They need not go in text posted to other people.

Where a findings log is kept (`findings-contract.md`), a declined blocking finding is recorded as `rejected`, with that reason.
