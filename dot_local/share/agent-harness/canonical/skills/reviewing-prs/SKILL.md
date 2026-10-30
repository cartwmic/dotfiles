---
name: reviewing-prs
description: Reviews someone else's pull request or branch on five fixed axes (intent-fit, correctness, security, tests, maintainability). Uses fresh reviewer sessions and driver triage, and nothing is posted until the owner approves the exact draft. Use when asked to review a colleague's or an agent's PR or branch. Not for reviewing your own change.
---

# Reviewing PRs

Correct use gives a review of someone else's work that:

- answers every axis;
- carries only confirmed findings that meet the severity bar;
- posts nothing the owner has not approved, exact text included.

Review the work, not the person.

## Scope

- **For:** a pull request on any of your Git hosts, or a local branch (base..head), written by a person or an agent.
- **Not for:** your own change, writing fixes, or approving or merging in the owner's place.
- **Size:** any. Lockfiles, snapshots, and vendored or generated files need no reading. List what you exempted in the draft.

## 1. Freeze the subject

1. **Fetch the head** into a local clone, for example `git fetch origin pull/N/head` on GitHub. Record the base sha, head sha, merge base, changed files and author (human or agent).
2. **Save the stated intent** verbatim: the PR body, the linked ticket and any linked plan. If there is none, that is an intent-fit finding.
3. **Save the repository's own rules** as they stand at head: AGENTS.md, CONTRIBUTING, CODEOWNERS, and lint and format config. These are the standard you review against.
4. **Use a local reviews folder** outside every repository and synced folder: `~/.local/share/pr-reviews/<repo>-<number>/`. Packets, reviewer output, triage and drafts go there. Keep it after posting.

## 2. Review: one fresh session per axis

| Axis | Question |
|---|---|
| intent-fit | Does the diff do what the stated intent says, all of it and nothing unrelated? Name a missing part, an unrelated change, a claim the diff does not support, or a doc or contract it makes false. If there is no stated intent, say what a reviewer cannot judge without it. |
| correctness | Which concrete input, state or sequence makes the changed code behave wrongly (crash, wrong result, data loss, race, regression)? Give the input and the line. |
| security | Does the change open a path from untrusted input, a credential, or regulated or sensitive data to a place it must not reach: injection, authorization bypass, unsafe deserialization, secrets in code or logs? Name the source, the path and the sink. |
| tests | Would the tests fail if the changed behavior were wrong? Name a changed behavior with no test, or a test that cannot fail or mirrors the implementation. |
| maintainability | Does the diff add a lasting cost to the next person who changes this code: duplication, a needless abstraction or layer, a hidden coupling, a misleading name, dead code? Name the cost and who pays it. Judge against the repository's rules and the design principles below. |

1. **Write one packet per axis.** It holds the axis question, the severity bar (section 3), the intent sources, the repository rules, the diff `merge_base..head`, a read-only checkout at head, and the files to cover.
2. **Start a fresh session for each packet,** with no other context. Run it from the reviews folder, so session files never land in a repository.
   - Confirm delegation with the owner first, unless it is already authorized.
   - Use the model the owner named.
3. **What each reviewer returns:**
   - the axis and the head sha;
   - the files it covered;
   - a verdict (pass or fail) with a note for each question;
   - findings, each with id, severity, path, line, text, obligation, evidence and consequence.
4. **Split a large PR** across sessions by file. Together they must cover every file that is not exempt.
5. **For a high-risk change,** add a second correctness session. High risk means auth, data migration, concurrency, money, or regulated or sensitive data.
6. **Do one pass per axis per head.** Do not repeat review until it comes back clean. A new head means a new review.

## 3. Severity bar

- **blocker:** merging causes a defect, a security exposure or data loss on a realistic path.
- **should-fix:** a real cost the author should address, such as a missing test for changed behavior, a misleading doc, or fragile code the diff introduces.
- **nit:** a preference.
- **question:** the reviewer cannot tell.

A blocker or should-fix must name the obligation, the evidence and the consequence. Without all three it is at most a nit. Do not comment on what CI or a formatter already enforces.

## 4. Triage

You (the driver) judge every finding. Read the code at head, or run a command, and mark the finding:

- **confirmed:** it holds. A confirmed blocker or should-fix records how you checked: the code path, or the command and the tail of its output.
- **refuted:** it does not hold. Keep it out of the draft and give the owner the reason.
- **duplicate:** name the original finding.
- **out-of-scope:** pre-existing, or outside the diff.

Do not debate with reviewers. The owner sees refuted findings at the checkpoint and can overrule.

## 5. Draft

The draft has a summary, inline comments, and an event: COMMENT, REQUEST_CHANGES or APPROVE.

- **Every confirmed blocker and should-fix** appears in exactly one comment, or is held back with a reason.
- **Every comment** cites at least one confirmed finding.
- **Inline comments** carry only blockers, should-fixes and questions. Nits go in one short optional list in the summary.
- **Out-of-scope findings** get at most one mention in the summary, as pre-existing. They never block.
- **APPROVE** is never the event while a confirmed blocker is in the draft.
- **Every inline line** lies inside a diff hunk at head.
- **Write the summary and inline comments in the owner's voice** with the no-ai-slop skill, review comments register. Change wording only: keep every finding, file:line, identifier and quoted string.
- **Tell the owner** in your report that you used no-ai-slop for the draft.

## 6. Owner review, then post

1. **Show the owner the draft verbatim.** Below it, collapsed: held-back findings, refuted findings with reasons, and the files covered on each axis.
2. **Post only after the owner's own words approve this exact draft.** Any edit needs a new approval.
3. **Before posting, read the PR head again.** If it moved, stop. The owner withholds or starts a new review.
4. **Post exactly the approved text as one review,** for example with `gh api` on GitHub. Then read the posted review back and compare it with the draft.
5. **If the owner says not to post,** give them the text and stop.

## Privacy

- **Code, findings and the author's name** stay in the reviews folder and in your conversation with the owner.
- **Updates to shared channels** carry state and counts only: no finding text, code or names.
- **Regulated or sensitive data in a diff** (personal data, credentials, customer records): cite the path and line, and never quote the values.

## Design principles

The maintainability reviewer also judges the diff against four sections of the owner's design principles
(`~/.local/share/agent-harness/design-principles.md`). This applies in every repository, the owner's own included:

- **§4 YAGNI and KISS:** code, abstractions, configuration or files the current need does not require.
- **§8 Judgment in agents, mechanism in code:** judgment encoded as keyword rules or heuristics, or deterministic work left to a model.
- **§9 Fix the cause:** caps, budgets or thresholds that hide wrong behavior; layered safeguards nobody asked for.
- **§12 Verified from the outside:** the blocking-finding bar, and machinery that can be removed while keeping the required behavior.

Rules:

- **Cite the section by number** in the finding, for example "§4".
- **A principle alone supports at most should-fix.** It becomes a blocker only when the repository's own rules require the same thing.
- **No other section applies to PR review.** In particular, §10 never lowers the security bar.
