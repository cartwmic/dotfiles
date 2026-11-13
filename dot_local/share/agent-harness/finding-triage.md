# Finding triage

Whoever acts on review findings (the driver, the author, the agent applying fixes) runs these four tests on every finding, whoever raised it: a person, a bot or a reviewer agent. Who wrote a finding does not make it true.

1. **Real.** It holds when checked against the code, the document or a run. Say how you checked.
2. **Useful.** Fixing it changes something a user, a caller or the next maintainer would notice. Taste and hypotheticals fail. So does a fix that an existing job, check or process already does.
3. **Maintainable.** Test the finding and its fix against the owner's design principles, `~/.local/share/agent-harness/design-principles.md`. A fix that breaks a principle is declined: cite the section. A fix that adds machinery the need does not require fails §4. A cap that hides a wrong cause fails §9.
4. **In intent.** It fits the stated intent and scope of the change under review and of the overall work that change belongs to. Anything else, especially a problem that existed before the change, is a follow-up, not part of this change. A defect the change itself introduces (a regression, broken behaviour, data loss in what it touches) is always in scope, even if the stated intent does not mention it. Only problems the change did not cause, or gaps already covered elsewhere, can be follow-ups.

Run them in order. Act on a finding that passes all four.

- **Failed test 1, 2 or 3:** decline it with one short reason that starts with the test it failed.
- **Failed test 4:** it is a follow-up. Do not decline or drop it. Mention it as a non-blocking note that starts "for a follow-up:". It never blocks the change and is never a blocker or should-fix.

```
declined (useful): the message is never shown to a user
for a follow-up: the retry loop already had no cap before this change
```

List the declined findings (with reasons) and the follow-ups in whatever the owner reads: a draft, report or summary. That lets the owner overrule. They need not go in text posted to other people.

Where a findings log is kept (`findings-contract.md`), a declined blocking finding is recorded as `rejected`, with that reason.
