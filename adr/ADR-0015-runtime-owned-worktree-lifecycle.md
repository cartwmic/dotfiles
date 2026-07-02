# ADR-0015: Worktree lifecycle is runtime-owned via `opsx worktree ensure` / `opsx clean`

**Status:** Accepted
**Date:** 2026-07-02
**Source change:** direct-edit audit remediation (docs/audits/2026-07-02-opsx-workflow-audit.md, finding 12)
**Supersedes:** — (implements what opsx-workflow-schema's Worktree Lifecycle Ownership specified as skill prose)
**Superseded by:** —

## Context

The Worktree Lifecycle Ownership requirement (immutable merge-base `Diff Base SHA`,
preserve-base-on-reuse with ancestry check, abort-on-creation-failure) existed only as
prose in the apply skill reference. The autonomous loop therefore proceeded only insofar
as the agent followed instructions — no deterministic component created, verified, or
cleaned worktrees, and nothing ever removed the worktree/branch of an ABANDONED change
(only the archive merge path cleaned up), leaking stale worktrees holding uncommitted
verdict files.

## Decision

Two deterministic subcommands in the `opsx` CLI own the lifecycle:

- `opsx worktree ensure <change> [--path <p>] [--integration-branch <b>]` — creates
  branch `opsx/<change>` + worktree from the integration branch and prints the locator
  fields (`Diff Base SHA` = merge-base, `Worktree Path`, `Integration Branch`) for
  review.md; on branch reuse it PRESERVES the recorded base and exits 1 (halt for human
  repair) when the base is absent or not an ancestor; any creation failure exits 1 with
  an actionable message. Skills call this instead of hand-rolling `git worktree` +
  `merge-base` commands.
- `opsx clean <change> [--force]` — removes an abandoned change's worktree + branch,
  refusing a dirty worktree without `--force` (unsealed verify/code-review/doneness
  verdicts live uncommitted there), idempotent when nothing remains.

Enforcement of *placement* (gate validating path/branch of a recorded worktree) remains
in `opsx gate` as before; `ensure`/`clean` own creation/reuse/cleanup.

## Consequences

- The known audit gap class (creation failure, stale-branch reuse, abandoned-change
  cleanup) is closed by exit codes, not prose; hermetic tests cover the full matrix in
  `tests/opsx-cli/`.
- Skills retain writeback ownership of review.md (the command prints, the skill writes),
  keeping the CLI free of markdown-editing responsibilities.
- Gate-failure cleanup deliberately remains "preserve the worktree" (spec: budget
  exhaustion/stall preserve for inspection); `opsx clean` is the explicit disposal verb.
