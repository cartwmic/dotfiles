# Intent — add-opsx-loop-harness

<!--
Frozen baseline produced at explore/propose time. The loop and review subagents
treat this as source-of-truth; changing it requires explicit human authorization.
This change is Scale L; opsx-gate requires intent.md at Scale >= M, so this file
also makes the change self-consistent with its own gate (dogfood).
-->

## Intent

Turn the opsx-superpowers workflow from prose the agent can ignore into a
deterministically-enforced, explore→loop flow: after the human agrees on intent,
a single orchestrator agent drives a change to completion behind a harness-neutral
exit-code gate it cannot talk past — integrated into the harness but not coupled to it.

## Constraints

- **Harness-neutral core, thin adapters.** Enforcement (opsx-gate), workflow
  (openspec-loop skill), and the manifest are harness-agnostic. Subagent dispatch
  and loop continuation are capability hooks that degrade to inline. Deleting the pi
  adapter must still leave a runnable workflow (bash fallback).
- **Enforcement is deterministic, not prose.** Structural, manifest, and verdict-
  freshness checks are non-bypassable; judgment verdicts (verify/code-review) are
  attestations bound to the current diff via an immutable Diff Base SHA + adapter-
  stamped provenance. The agent cannot mark pass then keep editing.
- **Reuse, don't rebuild.** The loop engine is the existing pi `goal` extension with
  a generic pluggable command-judge; it must stay opsx-agnostic.
- **Reviews are independent.** Every review/validation-judgment step is delegated to a
  blind subagent judging against a frozen baseline; a degraded single-model/self review
  does not satisfy a gating-required code-review or Constitution IX.
- **Worktree-required for all sizes** as the autonomous loop's blast-radius sandbox;
  same-tree remains an explicit override.

## Invariants honored

- Constitution II (canonical skill path), V (mise owns tool install), VIII (openspec
  workspace not deployed), IX (skill edits ≥ M get adversarial review — satisfied by the
  post-impl code-review over the skill diffs, not the plan review).
- Domain invariants 8 (dot_local/bin gitignore allowlist), 12 (skill symlink), 13/14
  (archive immutability; MODIFIED carries full content).
- chezmoi's fixed source root must not be violated: deploy-affecting verifications run
  post-merge or with an explicit `--source`/`CHEZMOI_SOURCE_DIR`; never `chezmoi apply`
  real home from a loop worktree.

## Non-goals

- Replacing OpenSpec or migrating to Spec-Kit/Kiro.
- A git-hook backstop (deferred to a follow-up change).
- A bespoke loop engine.
