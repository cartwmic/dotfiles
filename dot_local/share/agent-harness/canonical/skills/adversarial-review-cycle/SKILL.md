---
name: adversarial-review-cycle
description: User-invoked only. Do not auto-select. Run blind multi-model adversarial reviews on plan artifacts with iterative revision, owner decision audit, and artifact cleanup.
---

# Adversarial Review Cycle

Iteratively improve plan artifacts through blind multi-model adversarial reviews, auto-applied revisions, owner checkpoints, and artifact cleanup.

**Announce at start:** "I'm using the adversarial-review-cycle skill."

**REQUIRED SUB-SKILL:** Use review-plans for each reviewer subagent.

## Blind Reviews — Default

Reviewer subagents are **blind by default**: each one sees only the artifacts and the review-plans skill. They do **not** see other reviewers' output, prior-round findings, the round tracker, or the convergent-findings table. Break blindness only when the user explicitly requests it (e.g., "let reviewer B see A's P1 findings", "run a consensus round after disclosure").

**Red Flags — STOP:**

- About to pass prior-round findings to a reviewer "for context"
- About to share Reviewer A's output with Reviewer B "to save a round"
- Including the round tracker or a previous convergent-findings table in a reviewer prompt
- Telling a reviewer which severity other reviewers assigned

**Blind means:** same prompt, same artifact set, independent analysis. Disagreement between reviewers is the signal — don't collapse it by leakage.

## Scope Discipline — Default Answer Is No

Expand scope only when (a) **required** — the original goal is unachievable without it — or (b) **explicitly approved by the user** in the decision audit. Everything else is a follow-up, not part of this cycle. Operational mechanics live in Step 4 and Step 9.

**Red Flags — STOP and ask:**

- "While we're in here, we should also…"
- Reviewer question has multiple valid answers; the one you'd pick enlarges the plan
- Adding a task, artifact, or acceptance criterion not in source requirements
- Fix for a P1/P2 requires *new* functionality rather than correcting existing functionality

**All of these mean: surface in Step 6 before applying, not after.**

## Inputs

| Input | Required? |
|---|---|
| Artifact paths | Yes — ask if not provided |
| Reviewer configuration | Yes — user specifies models and subagent invocation |
| Source requirements (backlog item, ticket) | No — needed for Step 9 |

## Core Loop

**Steps 1–5** repeat until stop conditions are met. Then **Steps 6–10** run once.

### Step 1: Launch Blind Reviews

Dispatch reviewer subagents per user's configuration. Each reviewer reads all artifact files and gets the review-plans skill. Reviewers operate blind — see "Blind Reviews — Default" above for what that means and when to break it.

If a subagent fails, stop the cycle and report the failure. Let the user decide how to proceed.

### Step 2: Summarize

Produce a convergent findings table and update the round tracker:

**Round tracker** (maintained across all rounds):

| Round | P0 | P1 | P2 | P3 | Approvals |
|---|---|---|---|---|---|
| 1 | 0 | 6 | 4 | 2 | 0/2 |
| 2 | 0 | 2 | 5 | 3 | 0/2 |
| 3 | 0 | 0 | 3 | 4 | 1/2 |

**Convergent findings** (this round):

| # | Issue | Reviewer A | Reviewer B | Severity |
|---|---|---|---|---|
| 1 | Description | ✅ P1 | ✅ P1 | **P1** |
| 2 | Description | ✅ P2 | — | **P2** |

### Step 3: Stop Conditions

Stop the review loop based on the P0+P1 trajectory in the round tracker:

- **P0+P1 = 0 for this round** — blockers resolved, move to Step 6
- **P0+P1 flat or rising for 2 consecutive rounds** — treadmill, move to Step 6
- **Both reviewers approve** — move to Step 6

Do NOT stop when P0 or unaddressed P1 findings exist and the trajectory is still declining.

### Step 4: Apply Revisions

For each finding, classify before applying:

- **Bug fix / gap fill** (reviewer identified a problem, fix is clear) → auto-apply
- **New scope / feature addition** (fix requires adding something the plan didn't originally include) → flag for owner, apply only with confirmation

Track every autonomous decision: what you changed, what alternatives existed, whether it was a direct reviewer recommendation or your design choice.

### Step 5: Loop

Return to Step 1 with updated artifacts.

---

### Step 6: Decision Audit

Present the owner with all autonomous decisions from Step 4, categorized:

- **Design choices** — you picked approach A over B
- **Scope changes** — items added or removed
- **Questions you answered yourself** — reviewer asked, you decided

For each: what you decided, what the alternatives were. Ask: "Anything you disagree with or want changed?"

### Step 7: Apply Owner Amendments

Apply corrections. If substantial, return to Step 1 for another review round. If minor, continue.

### Step 8: Artifact Cleanup

Audit each artifact against its intended purpose. Each artifact type has a semantic boundary — content that crosses into another artifact's domain should be moved or removed.

Common bleed patterns from iterative review:
- Design rationale leaking into task descriptions
- Implementation details leaking into behavioral specs
- Scoping caveats scattered across multiple artifacts instead of one
- Numbering gaps from removed items
- Duplicate or contradictory statements across artifacts

### Step 9: Backlog Cross-Reference

If source requirements exist, cross-reference:

- **Coverage** — does the plan achieve what was asked for?
- **Gaps** — anything missing?
- **Scope creep** — anything added that wasn't asked for? Categorize as "necessary for the goal" vs "useful but separate work"

Present to owner for confirmation.

### Step 10: Final Validation Review

Run one last blind review round against the cleaned-up artifacts. This catches issues introduced by cleanup edits and confirms the final state is coherent. If P0/P1 findings emerge, return to Step 4. Otherwise, done.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Leaking prior findings into a reviewer prompt "for context" | Blind by default — break only with explicit user instruction |
| Auto-applying scope additions without flagging | Distinguish bug fixes from new scope in Step 4 |
| No round tracker — can't tell if converging | Maintain the P0/P1 table every round |
| Chasing P3s forever | Stop condition keys off P0+P1 trajectory, not total count |
| Skipping artifact cleanup | Review rounds cause semantic bleed between artifacts |
| Skipping backlog cross-reference | Artifacts drift from the original goal over many rounds |
| Skipping final validation | Cleanup edits can introduce new inconsistencies |
