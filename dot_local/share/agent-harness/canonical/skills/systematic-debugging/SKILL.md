---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes — especially when tempted by a "quick fix", under time pressure, after a prior fix failed, or when each fix reveals a new symptom elsewhere
---

# Systematic Debugging

## Overview

Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you have not completed Phase 1, you cannot propose fixes.

## When to Use

Use for ANY technical issue: test failures, production bugs, unexpected behavior, performance problems, build failures, integration issues.

**Use this ESPECIALLY when:**
- Under time pressure (emergencies make guessing tempting)
- A "one-line fix" seems obvious
- You have already tried 1+ fixes
- You do not fully understand the issue

**Do not skip when:** the issue seems simple, you are in a hurry, or someone wants it fixed NOW. Systematic is faster than thrashing.

## The Four Phases

Complete each phase before the next.

### Phase 1: Root Cause Investigation

1. **Read errors carefully.** Stack traces, line numbers, error codes — the answer is often verbatim in the message.
2. **Reproduce consistently.** Exact steps. Every time? If not reproducible, gather more data; do not guess.
3. **Check recent changes.** `git diff`, recent commits, new dependencies, env differences.
4. **Instrument component boundaries.** For multi-component systems (CI → build → sign, API → service → DB), log inputs and outputs at each boundary, then run once to see WHERE it breaks before investigating WHY.
5. **Trace data flow backward.** Where does the bad value originate? See `root-cause-tracing.md` for the full backward-tracing technique.

### Phase 2: Pattern Analysis

1. **Find working examples** of similar code in the same codebase.
2. **Read reference implementations completely** — every line. Skimming guarantees bugs.
3. **List every difference** between working and broken, however small. Do not assume "that cannot matter."
4. **Map dependencies, config, and assumptions.**

### Phase 3: Hypothesis and Testing

1. **State one hypothesis explicitly:** "I think X is the root cause because Y." Write it down.
2. **Test minimally.** Smallest possible change. One variable.
3. **Verify.** Worked → Phase 4. Did not → form a NEW hypothesis. Do not stack fixes.
4. **When you do not know, say so.** Do not pretend. Research or ask.

### Phase 4: Implementation

1. **Write a failing test first.** Automated if possible, one-off script otherwise. Use the `test-driven-development` skill.
2. **Make ONE change.** No "while I'm here" cleanups. No bundled refactors.
3. **Verify:** test passes, nothing else broke, issue actually resolved.
4. **If the fix did not work:** count attempts. If <3, return to Phase 1 with new evidence. **If ≥3, STOP — see Phase 4.5.**

### Phase 4.5: After 3+ Failed Fixes — Question Architecture

Pattern of architectural failure (not a wrong hypothesis):
- Each fix surfaces a new problem somewhere else
- Fixes require "massive refactoring" to land
- Shared state / coupling keeps reappearing

**Stop fixing. Discuss architecture with the user before attempting another fix.**

## Red Flags — STOP

Catch yourself thinking any of these → return to Phase 1:

- "Quick fix for now, investigate later"
- "Just try changing X and see"
- "Multiple changes at once, then run tests"
- "Skip the test, I'll verify manually"
- "It's probably X, let me fix that"
- "I don't fully understand but this might work"
- "Pattern says X but I'll adapt it"
- Proposing solutions before tracing data flow
- "One more fix attempt" (after 2+ failures)
- Each fix reveals a new problem in a different place

## Signals From the User That You're Off Track

- "Is that not happening?" → you assumed without verifying
- "Will it show us…?" → you should have added evidence gathering
- "Stop guessing" → you are proposing fixes without understanding
- "Ultrathink this" → question fundamentals, not symptoms
- "We're stuck?" (frustrated) → your approach is not working

When you see these: STOP. Return to Phase 1.

## Common Rationalizations

| Excuse | Reality |
|---|---|
| "Issue is simple, don't need process" | Simple bugs have root causes too. Process is fast for them. |
| "Emergency, no time" | Systematic is faster than guess-and-check. |
| "Just try this first, then investigate" | First fix sets the pattern. Do it right from the start. |
| "I'll write the test after confirming" | Untested fixes do not stick. Test first proves it. |
| "Multiple fixes at once saves time" | Cannot isolate what worked. Causes new bugs. |
| "Reference too long, I'll adapt the pattern" | Partial understanding guarantees bugs. Read it completely. |
| "I see the problem, let me fix it" | Seeing symptoms ≠ understanding root cause. |
| "One more fix" (after 2+ failures) | 3+ failures = architectural problem. See Phase 4.5. |

## Quick Reference

| Phase | Key Activities | Done When |
|---|---|---|
| 1. Root Cause | Read errors, reproduce, check changes, instrument boundaries, trace data | You understand WHAT and WHY |
| 2. Pattern | Find working examples, compare, list differences | Differences enumerated |
| 3. Hypothesis | State one theory, test minimally | Confirmed, or new hypothesis |
| 4. Implementation | Failing test → one fix → verify | Bug resolved, no regressions |
| 4.5. Architecture | After 3+ failures, stop and re-evaluate | Architectural decision made with user |

## When the Process Reveals "No Root Cause"

Sometimes investigation shows the issue is genuinely environmental, timing-dependent, or external. Then: document what you investigated, implement appropriate handling (retry, timeout, clearer error), and add monitoring.

**But:** most "no root cause" claims are incomplete investigation.

## Supporting Techniques (this directory)

- **`root-cause-tracing.md`** — backward trace through the call stack to find the original trigger
- **`defense-in-depth.md`** — add validation at multiple layers after finding root cause
- **`condition-based-waiting.md`** — replace arbitrary timeouts with condition polling
- **`find-polluter.sh`** — bisect a test suite to find which test creates unwanted shared state

## Related Skills

- **test-driven-development** — for the failing test in Phase 4
- **verification-before-completion** — verify the fix actually worked before claiming success
