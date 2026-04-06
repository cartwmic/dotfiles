# Phase 9: Finalize Plan

**Mode:** Hybrid (orchestrator + user — socratic)

**Reads:** `docs/desloppify/desloppify-plan-draft.md`, `docs/desloppify/review-blind.md`, `docs/desloppify/review-contextual.md`

**Produces:** `docs/desloppify/desloppify-plan.md`

## Overview

Present the plan draft alongside both adversarial reviews. Guide the user through evaluating the critiques and deciding what to accept, reject, or investigate further. Then finalize the plan with the user's execution strategy.

## Step 1: Preview the Plan

The user has not seen the plan yet. Give them a baseline before showing critiques:
- Present the plan's overview section (scope, total improvements, score distribution)
- Show the quick wins section
- Walk through improvement groups at a high level
- Ask: "Does this feel like the right shape? Any immediate reactions before I show you the adversarial reviews?"

## Step 2: Present the Adversarial Reviews

Show review findings:
- Brief summary of blind reviewer's key points (2-3 bullets)
- Brief summary of context-aware reviewer's key points (2-3 bullets)
- Where reviewers agree (high-signal)
- Where they disagree (interesting)

## Step 3: Walk Through Critiques

For each substantive critique, discuss with the user one at a time:

**Where reviewers agree:**
- "Both reviewers flagged X. Should we update the plan?"

**Blind reviewer findings:**
- "The blind reviewer thinks the plan misses Y. Should we add it?"
- "The blind reviewer thinks Z is unjustified. Do you agree?"

**Context-aware reviewer findings:**
- "The contextual reviewer found A and B are the same issue listed twice. Merge them?"
- "The contextual reviewer thinks the effort estimate for C is too optimistic. Revise?"

## Step 4: Socratic Organization

After incorporating review feedback, guide the user through plan organization:

"Now that we've refined the improvements, let's talk about how to organize and execute them."

Questions to explore (one at a time):
- "How are you planning to tackle this — feature by feature, riskiest first, quick wins first?"
- "Do you have constraints? A release coming up, limited bandwidth?"
- "Are there areas you want to protect from changes right now?"
- "Do you want a plan you execute over weeks, or a focused sprint?"

Let the organization structure emerge from the conversation.

## Step 5: Write Final Plan

Write `docs/desloppify/desloppify-plan.md`:

```markdown
# Desloppify Plan

## Plan Overview
- **Generated:** [Date]
- **Scope:** [From config]
- **Organization strategy:** [What user chose and why]
- **Total improvements:** N (H high-impact, M medium, L low)
- **Review notes:** [Key changes from adversarial review feedback]

## Execution Strategy
[How the user plans to approach this, constraints, timeline]

## Improvements

### [Group Name]

#### Improvement: [Title]
- **Source:** [Which concern investigation]
- **Impact:** [High/Medium/Low]
- **Effort:** [Small/Medium/Large]
- **Risk:** [High/Medium/Low]
- **Files affected:** [Specific files]
- **Description:** [What to change and why]
- **Enables:** [Other improvements this unblocks]
- **Requires:** [Prerequisites]
- **Verification:** [How to verify this improvement]

[Repeat per improvement]

## Quick Wins
[Low-effort + high-impact + low-risk]

## Deferred / Out of Scope
[Explicitly deferred with reasoning]

## Adversarial Review Summary
[Brief record of what reviews found and how it shaped the final plan]
```
