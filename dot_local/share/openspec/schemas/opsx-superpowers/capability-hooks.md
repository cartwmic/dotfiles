# Capability hooks — capability → local-skill mapping

The `opsx-superpowers` schema's artifact instructions name **capabilities**,
not specific skill IDs. This file maps each capability to a preferred
locally-available skill, with documented manual fallback when no local
skill matches.

The skill resolution is best-effort: if no local skill is registered for a
capability, the artifact instruction's manual fallback executes. The schema
ALWAYS works without any of these skills installed.

## Indirection rationale

The capability table below is structurally an indirection layer. As of this schema's initial release, most capabilities resolve to exactly one candidate — the user's local skill. The indirection is intentional even when degenerate: it documents the contract so future hosts that ship multiple skills implementing the same capability (or different harnesses than pi) have a published lookup path.

If this stays degenerate after dogfooding, future schema versions may collapse the abstraction.

## Resolution algorithm (used by the opsx-* skills)

```
For each capability hook in an artifact's instruction:
  1. Look up the capability in the table below.
  2. For each candidate skill in declared order:
     a. If the skill is registered on this host, invoke it.
     b. Log: "[capability:NAME] invoked skill:CANDIDATE"
     c. Break.
  3. If no candidate is registered:
     a. Log: "[capability:NAME] no skill available, using manual fallback"
     b. Execute the artifact instruction's manual procedure inline.
```

## Capability table

| Capability | Used by artifact | Candidate skills (in priority order) | Manual fallback |
|---|---|---|---|
| `clarify-spec` | clarify | 1. `clarify-spec` (this repo, `dot_local/share/agent-harness/canonical/skills/clarify-spec/`) | Execute the 3 passes (ambiguity / inconsistency / completeness) inline using the prose in clarify.md instruction. Pass 3 is priority-bounded (cap 10 findings per spec). |
| `adversarial-review` | analyze (when Scale ≥ L) | 1. `adversarial-review-cycle` (this repo) | Run a single-model self-review of the 7 analyze checks. Emit a "DEGRADED MODE: no adversarial-review-cycle skill available" note in analyze.md's header. |
| `subagent-driven-implementation` | apply (when Delegation Mode = subagent-*) | 1. `pi-subagents` (this repo) — built-in subagent + worktree + intercom | Execute tasks inline in the main agent. Emit a "DEGRADED MODE: no subagent skill available" note in review.md's Execution Notes. |
| `file-isolation-via-worktree` | apply (when Worktree Mode = worktree-*) | 1. `pi-subagents` with `worktree: true` 2. inline `git worktree add` per the pre-flight commit + worktree convention | Implementation runs in-tree on the integration branch. Emit a "DEGRADED MODE: same-tree execution" note in review.md. |
| `verification-before-completion` | verify | 1. `verification-before-completion` (Superpowers, if installed) 2. inline | Execute the 6 verify checks inline. The reverse-direction (manual fallback) is the canonical implementation; the Superpowers skill is a wrapper. |
| `systematic-debugging` | apply (when Debug Mode = systematic-debugging) | 1. `systematic-debugging` (this repo) | Execute the 4-phase root-cause investigation inline per the skill's own SKILL.md reference. |
| `finish-development-branch` | apply (final step, optional) | 1. `finishing-a-development-branch` (Superpowers, if installed) | Manual merge/PR procedure documented per-project. |
| `memory-promotion` | archive (when retrospective.md present) | 1. `mcp_memory_store_memory` MCP tool | If MCP tool not available, write the candidates to a `retrospective-promote-pending.md` file in the change dir for later ingestion. |
| `adversarial-review-postimpl` | code-review (post-apply, when Code Review Mode != none) | 1. `adversarial-review-cycle` (this repo) over the diff `Diff Base SHA..HEAD` | Single-model self-review of the diff; mark `review_mode: degraded-single-model` in code-review.md. Degraded does NOT satisfy gating-required or Constitution IX. |
| `subagent-dispatch` | apply (Delegation Mode subagent-*) + every review/validation-judgment step | 1. `pi-subagents` (pi adapter) 2. host-native subagent (Claude Task, etc.) | Run inline; the verdict is `degraded-single-model` (gate-failing for gating-required). The schema names NO specific harness — pi-subagents is just the pi adapter. |
| `loop-continuation` | the opsx drive loop | 1. `goal` extension command-judge (`PI_GOAL_JUDGE_CMD=opsx gate <change>`) 2. `opsx loop` bash driver (`AGENT_CMD`-parameterized) | The bash `opsx loop` driver always works; deleting the extension loses only convenience. |

## Notes on each capability

### `clarify-spec`

The local `dot_local/share/agent-harness/canonical/skills/clarify-spec/` skill is the canonical implementation
of the three-pass clarify procedure for this schema. If unavailable, the
manual fallback in `clarify.md` instruction does the same work inline with
no measurable quality difference (the skill is just prose extraction).

### `adversarial-review`

`adversarial-review-cycle` is multi-model + multi-round. The single-model
fallback is significantly weaker; the schema flags this with a DEGRADED
MODE note so reviewers know the analyze artifact may be missing findings.

### `subagent-driven-implementation`

This is the most consequential capability. `pi-subagents` provides parallel
execution, intercom-coordinated workflows, and worktree isolation. The
manual fallback (inline execution) loses parallelism and isolation but
preserves correctness.

### `file-isolation-via-worktree`

Two valid implementations:
- `pi-subagents` with `worktree: true` (preferred — couples isolation to
  delegation)
- raw `git worktree add` per-task (used when delegation isn't desired but
  isolation still is)

The pre-flight commit step in apply runs BEFORE either implementation
spawns a worktree, so artifact files are present in both checkouts.

### `verification-before-completion`

The Superpowers skill of this name is a generic "verify before claiming
done" reminder. This schema's verify.md artifact is the canonical
implementation of that discipline — the skill is a thin wrapper.

### `systematic-debugging`

This repo has a local `systematic-debugging` skill. The schema invokes it
only when Debug Mode is explicitly set; the default `standard` debug mode
does not activate this capability.

### `finish-development-branch`

Optional final step in apply. Not invoked unless the user explicitly
includes it in review.md's Execution Notes or asks the apply skill.

### `memory-promotion`

The mcp-memory MCP server (host: `mcp-memory.internal.cartwmic.com`) is
the canonical destination. The fallback to a pending file is for hosts
that don't have the MCP server configured.

## See also

- Schema definition: `schema.yaml`
- Activation + Scale tiers: `README.md`
- mcp-memory contract: see CLAUDE.md "Memory: mcp-memory MCP server"
