# Execution Plan

<!--
tasks.md is COARSE (task IDs + contracts).
plan.md is FINE-GRAINED — what openspec-apply-change actually executes.
Each plan step Covers one or more task IDs and expands them into
5-step micro-tasks (when Execution Mode = tdd-required) or a simple
ordered list (otherwise).
-->

## Plan step 1: <descriptive name>

- **Covers:** T1.1, T1.2
- **Pre-conditions:**
  - <env, files, prior steps>
- **Action (5-step micro-tasks):**
  1. Write failing test (cites AC `<spec>:R<n>`)
  2. Run test → expect FAIL
  3. Minimal implementation
  4. Run test → expect PASS
  5. Commit (`feat: …` or `fix: …`; subject ≤72 chars)
- **Verification:**
  - <validators that run: typecheck, lint, unit tests, integration tests>
- **Rollback:**
  - <how to undo if this step fails>

## Plan step 2: <descriptive name>

- **Covers:** T2.1
- **Pre-conditions:** <…>
- **Action:** <…>
- **Verification:** <…>
- **Rollback:** <…>

<!-- When Debug Mode = systematic-debugging, every plan step
also includes: -->

<!--
- **Observed Failure:**
    Error verbatim: <…>
    Repro steps: <…>
- **Debugging Trail:**
    Attempt 1 (timestamp): <hypothesis + ruled out because …>
    Attempt 2 (timestamp): <…>
-->

## Completion Verification

<!-- The verification command(s) that prove the whole plan is done.
Lifted into verify.md check 5 (AC↔test) and check 6 (constitution). -->

- <command + expected result>

## Manual Adjustments

<!-- Author overrides to the plan structure. Mode flags that affected
the plan shape. -->

- <override + rationale>
