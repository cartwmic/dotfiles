# Phase 9: Consolidate Plan Draft

**Mode:** Subagent-only

**Reads:** All prior artifacts

**Produces:** `docs/desloppify/desloppify-plan-draft.md`

## Overview

Merge all findings from Phases 6-8 into a comprehensive, prioritized, actionable improvement plan draft. This draft goes through adversarial review (Phase 10) before the user finalizes it (Phase 11).

## Step 1: Dispatch Plan Draft Subagent

Use `./prompts/plan-draft-prompt.md`.

The subagent:
1. Collects findings from Phase 6 (read **Summary** sections only from per-member analyses — not full text), Phase 7 (per-set, full text), Phase 8 (holistic, full text)
2. Deduplicates — same issue found at multiple analysis levels gets consolidated
3. Groups findings into candidate improvements
4. Scores each improvement on effort/impact/risk
5. Maps dependencies between improvements
6. Assigns verification methods from `config.md`
7. Ensures every improvement is independently deployable

### Scoring Dimensions

**Impact** (How much does this improve the codebase?):
- High: Fixes systemic issue, benefits multiple slices, reduces risk
- Medium: Fixes localized issue, benefits one slice significantly
- Low: Cosmetic improvement, minor consistency fix

**Effort** (How hard is this change?):
- Small: < 1 day, touches few files, low complexity
- Medium: 1-3 days, moderate scope, some complexity
- Large: 3+ days, broad scope, high complexity or risk

**Risk** (What could go wrong?):
- High: Core path, low test coverage, high coupling, many dependents
- Medium: Important path, partial test coverage, moderate coupling
- Low: Well-tested area, clear interfaces, few dependents

Risk assessment uses seam identification from Phase 6.

### Dependency Mapping

For each improvement, identify:
- **Enables:** Other improvements this makes possible or easier
- **Requires:** Other improvements that should come first
- **Conflicts:** Other improvements that can't coexist (choose one)

## Step 2: Write Draft Artifact

The subagent writes its output to `docs/desloppify/desloppify-plan-draft.md`.

The orchestrator briefly reviews for completeness, then proceeds to Phase 10 (Adversarial Review).

**Do NOT present the draft to the user yet.** The adversarial reviews in Phase 10 will improve the draft before the user sees it in Phase 11.

## Draft Format

```markdown
# Desloppify Plan — Draft

## Plan Overview
- **Generated:** [Date]
- **Scope:** [From config]
- **Total improvements:** N (H high-impact, M medium, L low)

## Improvements

### [Group Name] (based on chosen organization)

#### Improvement: [Title]
- **Source:** [Phase 6/7/8 — which analysis found this]
- **Impact:** [High/Medium/Low]
- **Effort:** [Small/Medium/Large]
- **Risk:** [High/Medium/Low]
- **Slices affected:** [Which vertical/horizontal slices]
- **Description:** [What to change and why]
- **Seam assessment:** [Safety of this change — test coverage, interfaces]
- **Enables:** [Other improvements this unblocks]
- **Requires:** [Prerequisites]
- **Verification:** [Specific methods for this improvement]

[Repeat per improvement]

## Dependency Graph
[Text or mermaid diagram showing improvement dependencies]

## Quick Wins
[Improvements that are low-effort + high-impact + low-risk]

## Deferred / Out of Scope
[Improvements explicitly deferred with reasoning]
```
