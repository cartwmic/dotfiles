---
name: correcting-repeated-mistakes
description: Use when the same correction or review finding comes up a second time in a repo, when a finding is labelled repeat or follow-on, when a rule is already written down and agents still break it, or when asked to stop agents repeating a mistake. Finds the mistake class, fixes it at the highest level that works (architecture, then types, then a lint or CI check, then a test, then written instructions), proves the new check fails on the real past mistake, and records what now enforces the rule. Do not use it for a first-time mistake or a one-off bug; fix those and move on.
---

# Correcting repeated mistakes

Make a mistake that agents keep repeating impossible. Another written instruction is the last resort. The bar is `~/.local/share/agent-harness/design-principles.md`: §8 (mechanism in code, judgment in agents) and §9 (fix the cause; no caps or defense in depth nobody asked for). Assume every contributor is an agent that sees only the files it opened, copies the nearest example and takes the shortest path that works. Build the repo so a change that looks right from one file is right for the whole repo.

## 1. Find the class

A mistake class counts once it has happened twice. Sources:

- Review findings logs: `~/.local/share/agent-traces/emitted/review/<item>/findings.jsonl` and `~/.local/bin/agent-traces review report --item <item>`. Findings labelled `repeat` or `follow-on` are classes already; the log keys them by component, and the `label` event in `findings.jsonl` names the earlier finding (`of`), which the report does not print. A class across PRs shows only by searching all logs: `grep -l '"relation":"repeat"' ~/.local/share/agent-traces/emitted/review/*/findings.jsonl`.
- Fix-a-fix commits in `git log`: commits that only repair an earlier fix. Often the best source. One run found 8 commits that did nothing but move line numbers in a doc. Read the log for repeated subjects and for the same file touched again and again.
- Michael's corrections: coordinator playbook rules and the quotes behind them.
- Reverts, review comments, and comments that explain a workaround.

Name each class by what the agent did and what it should have done. If you cannot show two cases, it is not a class yet. Stop and say so.

## 2. Fix at the highest level that works

Take the first level that makes the mistake impossible or loud. Say why you passed over each higher one.

1. **Architecture.** One owner per piece of state, one supported way per task. Hide internals so the wrong import fails. Replace hand-synced lists with one source of truth. Delete the old way and the dead code an agent would copy.
2. **Types.** Make the bad state unwritable.
3. **Lint or CI check.** For what still compiles. Its error names the file, type or function to use instead. If the bad pattern is already common, fail only on new additions. Exceptions go on the offending line with a reason, an expiry date and a human's approval.
4. **Test.** It must pass two imagined edits. Break the behavior (wrong value, skipped or doubled effect): the test must fail. Change only the internals: it must still pass. Fix or delete tests that fail either edit.
5. **Written instruction.** Last, and only for judgment calls. Nothing fails when an agent skips it.

If deciding needs judgment, a check cannot own it: write the instruction and say so.

Before you change a doc, schema or format, find what else reads or quotes it (grep for its name and path). Update those in the same change.

## 3. Prove it

For each new check, show it fails on the real past mistake and passes now: rerun the old commit, or a copy of the bad code. Run it the way the repo's gate runs it (CI, kgate or whatever the repo uses). A check you only saw pass is not proven.

A fix that removes the mistake (an architecture fix) cannot fail on the past, because the mistake is gone. Add a guard check whose error names the fix, and show the guard fails on the past instance. Example: the fix drops line numbers from a doc; the guard fails on any line-number citation and says to cite the symbol instead.

## 4. Keep the record

- Where the repo has a rule table, or the coordinator playbook has an `Enforced by` field, record what now enforces the rule.
- If the rule was already written and nothing enforced it, that is a repeat: fix it at a higher level in the same change.
- Drop a rule once its mistake cannot happen.

## 5. Reply

One entry per class: the evidence (both cases, with commits, finding ids or quotes), the level chosen, the proof, and why each higher level did not work.
