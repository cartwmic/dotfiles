# Finding triage

Whoever acts on review findings (the driver, the author, the agent applying fixes) runs these four tests on every finding, whoever raised it: a person, a bot or a reviewer agent. Who wrote a finding does not make it true.

1. **Real.** It holds when checked against the code, the document or a run. Say how you checked.
2. **Useful.** Fixing it changes something a user, a caller or the next maintainer would notice. Taste and hypotheticals fail.
3. **Maintainable.** The fix serves long-term maintainability under `~/.local/share/agent-harness/design-principles.md`. Cite the section. A fix that adds machinery the need does not require fails §4. A cap that hides a wrong cause fails §9.
4. **In intent.** It fits the intent of the change under review and of the overall work that change belongs to. Anything else is a follow-up, not part of this change.

Run them in order. Act on a finding that passes all four. Decline the rest with one short reason that starts with the first test it failed:

```
declined (useful): the message is never shown to a user
```

Every draft, report or summary of the review lists the declined findings with their reasons, so the owner can overrule them.

Where a findings log is kept (`findings-contract.md`), a declined blocking finding is recorded as `rejected`, with that reason.
