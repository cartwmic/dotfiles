# Phase 11: Finalize Plan

**Mode:** Hybrid (orchestrator + user — socratic)

**Reads:** `docs/desloppify/desloppify-plan-draft.md`, `docs/desloppify/review-blind.md`, `docs/desloppify/review-contextual.md`

**Produces:** `docs/desloppify/desloppify-plan.md`

## Overview

Present the plan draft alongside both adversarial reviews. Guide the user through evaluating the critiques and deciding what to accept, reject, or investigate further. Then finalize the plan with the user's execution strategy.

## Step 1: Preview the Plan

The user has not seen the plan yet. Give them a baseline before showing critiques:
- Present the plan's **Plan Overview** section (scope, total improvements, score distribution)
- Show the **Quick Wins** section (easy wins to orient around)
- Briefly walk through the improvement groups/categories at a high level
- Ask: "Does this feel like the right shape? Any immediate reactions before I show you the adversarial reviews?"

This gives the user a mental model of the plan before they encounter critiques of it.

## Step 2: Present the Adversarial Reviews

Now show the review findings:
- Brief summary of blind reviewer's key points (2-3 bullets)
- Brief summary of context-aware reviewer's key points (2-3 bullets)
- Where the reviewers agree (high-signal — both independently flagged the same issue)
- Where they disagree (interesting — different perspectives)

## Step 3: Walk Through Critiques

For each substantive critique, discuss with the user:

**Where reviewers agree:**
- "Both reviewers flagged X. The blind reviewer saw it from the code directly; the contextual reviewer found it contradicts Phase 6 analysis. Should we update the plan?"

**Blind reviewer findings:**
- "The blind reviewer thinks the plan misses Y, which they found by reading the code fresh. Our analysis pipeline didn't surface this — should we add it?"
- "The blind reviewer thinks improvement Z is unjustified — they couldn't find evidence in the code. Do you agree, or is there context they're missing?"

**Context-aware reviewer findings:**
- "The contextual reviewer found that improvements A and B are actually the same issue listed twice. Should we merge them?"
- "The contextual reviewer thinks the effort estimate for C is too optimistic based on the seam assessment. Should we revise?"

**One critique at a time.** Don't dump everything at once.

## Step 4: Socratic Organization

After incorporating review feedback, guide the user through plan organization:

"Now that we've refined the improvements, let's talk about how to organize and execute them."

Questions to explore (one at a time):
- "How are you planning to tackle this — feature by feature, riskiest first, quick wins first, or something else?"
- "Do you have constraints? A release coming up, limited bandwidth, specific deadline?"
- "Are there areas you want to protect from changes right now?"
- "Do you want a plan you execute over weeks, or a focused sprint?"
- "Any improvements that jumped out as must-do or definitely-skip?"

Let the organization structure emerge from the conversation.

## Step 5: Write Final Plan

Incorporate all revisions and write `docs/desloppify/desloppify-plan.md`:

```markdown
# Desloppify Plan

## Plan Overview
- **Generated:** [Date]
- **Scope:** [From config]
- **Organization strategy:** [What user chose and why]
- **Total improvements:** N (H high-impact, M medium, L low)
- **Review notes:** [Key changes made from adversarial review feedback]

## Execution Strategy
[How the user plans to approach this, constraints, timeline]

## Improvements

### [Group Name] (based on chosen organization)

#### Improvement: [Title]
- **Source:** [Which analysis phase(s)]
- **Impact:** [High/Medium/Low]
- **Effort:** [Small/Medium/Large]
- **Risk:** [High/Medium/Low]
- **Slices affected:** [Vertical and/or horizontal]
- **Description:** [What to change and why]
- **Seam assessment:** [Safety of this change]
- **Enables:** [Other improvements this unblocks]
- **Requires:** [Prerequisites]
- **Verification:** [Specific methods]
- **Review notes:** [Any modifications from adversarial review, if applicable]

[Repeat per improvement]

## Dependency Graph
[Improvement dependencies — text or diagram]

## Quick Wins
[Low-effort + high-impact + low-risk]

## Deferred / Out of Scope
[Explicitly deferred with reasoning]

## Adversarial Review Summary
[Brief record of what the reviews found and how it shaped the final plan]
```
