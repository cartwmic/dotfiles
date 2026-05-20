# Review

<!--
Controlled-vocabulary mode switchboard. The apply instruction reads these
modes and dispatches behavior. Override any mode by setting it to a
non-default value.
-->

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | S | XS\|S\|M\|L\|XL — skill decides which artifacts to author per Scale (graph is static; gating lives in the opsx-* skills, not the schema YAML) |
| Execution Mode | standard | standard\|tdd-preferred\|tdd-required |
| Verification Mode | retained-recommended | inline-only\|retained-recommended\|retained-required — retained-required forces verify.md before archive |
| Debug Mode | standard | standard\|systematic-debugging |
| Review Status | not-requested | not-requested\|requested\|findings-received\|resolved |
| Delegation Mode | single-agent | single-agent\|subagent-eligible\|subagent-required |
| Worktree Mode | same-tree | same-tree\|worktree-eligible\|worktree-required |
| Spec Level | spec-anchored | spec-anchored\|spec-first\|spec-as-source (warning if last) |

## Worktree Base SHA

<!--
Captured by apply at worktree creation:
  git -C <worktree-path> rev-parse HEAD

Used by all file-contract diffs in this apply session so per-task commits
don't advance the diff base mid-task. Leave empty until apply starts.

If Worktree Mode = same-tree, this field is N/A.
-->

**Worktree Base SHA:** <empty until apply captures it>

## Manual Adjustments

<!-- Author-driven overrides to defaults. One bullet per non-default
value with rationale. Examples:
- "Worktree Mode = worktree-required because Task 3.2 touches shared
  state and must roll back cleanly on failure."
- "Debug Mode = systematic-debugging because we're chasing a regression
  introduced in commit abc1234."
-->

- <override + rationale>

## Execution Notes

<!-- Transient observations appended during apply. The apply step writes
one-line entries here when a non-trivial decision is made mid-task. Not
durable knowledge — that goes to retrospective.md Promote-candidates. -->

- YYYY-MM-DD HH:MM — <note>
