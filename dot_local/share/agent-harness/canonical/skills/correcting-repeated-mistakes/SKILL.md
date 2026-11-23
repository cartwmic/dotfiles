---
name: correcting-repeated-mistakes
description: Use to retro your own failure, miss or bug, whether a code change or a process went wrong, when one serious failure or incident needs a retro, when the same correction or review finding comes up a second time, when a finding is labelled repeat or follow-on, or when a rule is already written down and agents still break it. Traces the failure to a mechanism you can change, names its class, climbs to the larger pattern the class is an instance of (checked by a blind pass), searches the history for other cases, proposes one fix per tier of the enforcement pyramid (codebase, static analysis, verification, prose, human review) and builds the highest that works, proves the new check fails on the real failure, and records what now enforces it. Not for a trivial one-off bug; fix that and move on.
---

# Correcting repeated mistakes

Make a failure impossible, or loud, instead of promising to do better. Another written instruction is the last resort. The bar is `~/.local/share/agent-harness/design-principles.md`: §8 (mechanism in code, judgment in agents) and §9 (fix the cause; no caps or defense in depth nobody asked for). Assume every contributor is an agent that sees only the files it opened, copies the nearest example and takes the shortest path that works. Build the repo so a change that looks right from one file is right for the whole repo.

## 1. Find the class

Two ways in. Both end with a named class and then steps 2 to 7.

### From a repeat

A mistake has happened twice. Sources:

- Review findings logs: `~/.local/share/agent-traces/emitted/review/<item>/findings.jsonl` and `~/.local/bin/agent-traces review report --item <item>`. Findings labelled `repeat` or `follow-on` are classes already; the log keys them by component, and the `label` event in `findings.jsonl` names the earlier finding (`of`), which the report does not print. A class across PRs shows only by searching all logs: `grep -l '"relation":"repeat"' ~/.local/share/agent-traces/emitted/review/*/findings.jsonl`.
- Fix-a-fix commits in `git log`: commits that only repair an earlier fix. Often the best source. One run found 8 commits that did nothing but move line numbers in a doc. Read the log for repeated subjects and for the same file touched again and again.
- Michael's corrections: coordinator playbook rules and the quotes behind them.
- Reverts, review comments, and comments that explain a workaround.

Name the class by what the agent did and what it should have done. Show both cases.

### From one failure

Use this for a serious incident, a bug that cost real time, or a miss in your own work, even if it has not happened twice.

1. **Gather the facts.** Timeline, logs, ledger entries and session evidence. Write down what happened, when, and how long it lasted. Do not explain it yet.
2. **Trace the cause chain.** Ask why until you reach the mechanism that let it happen. Stop at a cause you can change. "The agent was slow" and "I forgot" are not that; ask what let it matter.
3. **Name the class.** What kind of thing failed, worded so it covers other instances, not this one.
4. **Search the history for other cases** of that class: `git log`, the review findings logs (above), playbook rules and their quotes (`playbook show`), and Retro proposals (`retro list`, in the retro repo's CLI; `retro show <id>` for one). Search by the mechanism, not by the symptom's words.
5. **Judge what you found.**
   - At least one earlier case: it is a repeated class. Continue with the repeat bar.
   - None: still name the class and pick the fix level, but say plainly that the class rests on one case. Aim the fix at the mechanism of the pattern you find in step 2, which covers siblings nobody has seen by construction. Do not add layered defenses nobody asked for (§9).

## 2. Climb to the pattern above the class

Do this before you propose any fix. A class is still narrow: it names what went wrong here. Ask what general property of how the work is produced or checked let it happen, and what else that property lets through. That is the pattern. Name one pattern or several. Climb as high as the evidence holds, and say where the evidence stops.

Example: the class "an unsourced number" is an instance of the pattern "a claim whose evidence does not travel with it". A check for numbers fixes the class. Only the pattern covers a date, a name, or a "this is already done".

Search the history (as in step 1.4) for other instances of each pattern, not only of the class. Say which cases are the class and which only the pattern.

## 3. One fix per tier, then pick

For each pattern, write one fix at each tier of the enforcement pyramid (the canonical instructions' "Enforcement: the inverted pyramid", with the same tier contents), top first. "No fix at this tier" is allowed, with the reason.

1. **Codebase.** API design, architecture, refactoring. Make the mistake impossible. One owner per piece of state, one supported way per task. Hide internals so the wrong import fails. Replace hand-synced lists with one source of truth. Delete the old way and the dead code an agent would copy.
2. **Static analysis.** Lints, types, compilers, tests, CI. Make the bad state unwritable in types. A lint or CI check keys on the general shape of the mistake, not a keyword list. Its error names the file, type or function to use instead. If the bad pattern is already common, fail only on new additions. Exceptions go on the offending line with a reason, an expiry date and a human's approval. A test must pass two imagined edits. Break the behavior (wrong value, skipped or doubled effect): it must fail. Change only the internals: it must still pass. Fix or delete tests that fail either edit.
3. **Verification.** Runtime and formal checks: a replay, a re-run of a claim's source command, a runtime assert, a proof.
4. **Prose.** An instruction, only for judgment calls. Nothing fails when an agent skips it.
5. **Human review.** What Michael still looks at, made cheap: one named check, in one place, with the evidence beside it.

If deciding needs judgment, a check cannot own it: write the instruction and say so. Then pick which fix to build first and say why. It is usually the highest tier that works. Say why you passed over each higher one. The fixes for the other tiers stay as proposals, and are built only if the first fix proves not enough (§9).

Before you change a doc, schema or format, find what else reads or quotes it (grep for its name and path). Update those in the same change.

## 4. Blind pass

Before you reply, get a reading that has not seen your patterns or fixes. Start a fresh agent on the Reviewer seat (per the seat table in the user instructions). Give it the failure facts and the named class, and nothing else. Ask: "What larger pattern is this an instance of, and what would make the whole pattern impossible?"

Compare its answer with yours. Record what it found that you missed, and fold that in. If it found nothing new, say so.

If your session cannot start subagents, do the pass yourself as a separate written step: put your patterns and fixes aside, answer the question from the facts alone, then compare. Say in the reply that it was a written pass, not a fresh agent.

## 5. Prove it

For each new check, show it fails on the real past failure and passes now: rerun the old commit, or a copy of the bad code. Run it the way the repo's gate runs it (CI, kgate or whatever the repo uses). A check you only saw pass is not proven.

A fix that removes the mistake (an architecture fix) cannot fail on the past, because the mistake is gone. Add a guard check whose error names the fix, and show the guard fails on the past instance. Example: the fix drops line numbers from a doc; the guard fails on any line-number citation and says to cite the symbol instead.

## 6. Keep the record

- Where the repo has a rule table, or the coordinator playbook has an `Enforced by` field, record what now enforces the rule.
- If the rule was already written and nothing enforced it, that is a repeat: fix it at a higher level in the same change.
- Drop a rule once its mistake cannot happen.

## 7. Reply

One entry per class: the cause chain (for a single failure), the evidence (each case, with commits, finding ids or quotes), the pattern or patterns above it and where the evidence stops, a table of one fix per tier for each pattern, which fix you picked to build first and why each higher tier did not work, with the other tiers' fixes left as proposals, the blind-pass comparison, and the proof. If you found only one case, say: "This class rests on one case."
