## Why

The opsx-superpowers workflow enforces nothing: every step, gate, and review is prose an LLM can silently skip (README admits per-Scale gating "lives in the skills, not the schema"), and `openspec validate` only checks structure. We want an explore→loop flow where, after agreeing on intent, a single orchestrator agent drives a change to completion behind a **deterministic** gate — integrated into the harness but not coupled to it (Constitution II). Structural, manifest, and verdict-freshness checks are non-bypassable by prose; judgment verdicts (code-review/verify) remain attestations but are bound to the current diff (stale or unprovenanced verdicts fail the gate), so the agent cannot mark pass and keep editing.

## What Changes

- Add `opsx-gate` — a harness-neutral CLI that is the **primary** source of enforcement truth (archive re-checks the same fields as defense-in-depth for out-of-loop archiving): reads `openspec status`, required-artifacts-by-Scale, a validation manifest, and verify/code-review verdicts; exits 0 (archivable) or non-zero with a stable-format "what's red" report. Deterministic; no LLM judgment.
- Add `openspec/opsx-gates.yaml` manifest convention (fills the schema's dangling `project.md` validator reference) declaring repo validation commands run by exit code; plus `OPSX_VALIDATE` for user-supplied gates.
- Add `openspec-loop` skill — a single-agent orchestrator playbook: consumes a frozen `intent.md` from explore, advances the change until `opsx-gate` is green, and **delegates every review/validation-judgment step to a blind subagent** that judges current work against the phase-appropriate baseline (intent pre-design; intent + plan post-apply).
- Add post-implementation adversarial review: skill-managed `code-review.md` artifact (template + `Code Review Mode` switchboard mode) reviewing the actual diff, gating archive — distinct from the existing pre-impl analyze review.
- **BREAKING (default change):** `Worktree Mode` default flips `same-tree` → `worktree-required` for **all** Scales; apply/archive own the worktree lifecycle (create, base-SHA, merge, cleanup) as the autonomous loop's blast-radius sandbox.
- **MODIFIED:** the `goal-loop` extension gains a **pluggable command-judge** (judge may be a shell command whose exit code is the verdict) so a generic loop runtime can use `opsx-gate` — the extension never learns about opsx (no coupling).
- Freeze explore output: `openspec-explore` writes an immutable `intent.md` (intent + constraints + invariants) that the loop and reviewers treat as source-of-truth.

## Capabilities

### New Capabilities
- `opsx-gate-enforcement`: the `opsx-gate` CLI, the `opsx-gates.yaml` manifest, the cheap→expensive short-circuit ordering, and the machine-checkable completion predicate.
- `opsx-loop-orchestration`: the `openspec-loop` skill — explore→freeze-intent seam, single-orchestrator loop, subagent-review-against-baseline rule, gate as stop condition, harness-neutral core with per-harness adapters.
- `opsx-post-impl-review`: `code-review.md` adversarial diff review, `Code Review Mode`, and the phase-keyed review-baseline rules.

### Modified Capabilities
- `goal-loop`: add a pluggable judge — model-judge (current) OR command-judge (exit code = verdict); keep the extension opsx-agnostic.
- `opsx-workflow-schema`: worktree-required default at all Scales + lifecycle; `Code Review Mode`; required-artifact-by-Scale as a hard gate input; Validation Gates reference.
- `opsx-skill-integration`: apply produces `code-review.md` + runs worktree create/merge/cleanup + gate integration; archive hard-gates on code-review verdict; `openspec-explore` freezes `intent.md`; register `openspec-loop`.

## Impact

- **New deps:** `yq` for manifest parsing (installed via mise per Constitution V; `jq`+JSON is the zero-new-dep fallback).
- **Affected files:**
  - `dot_local/bin/executable_opsx-gate`, `dot_local/bin/executable_opsx-loop` (→ `~/.local/bin/`; requires the `!dot_local/bin/` gitignore allowlist, domain invariant 8).
  - `dot_local/share/agent-harness/canonical/skills/openspec-loop/` (new skill; deploys + symlinks per domain invariant 12 / Constitution II).
  - `dot_local/share/openspec/schemas/opsx-superpowers/`: `templates/code-review.md`, `templates/opsx-gates.yaml`, `templates/review.md`, `schema.yaml`, `capability-hooks.md`, `README.md`.
  - `references/opsx-superpowers-mode.md` for openspec-apply-change + openspec-archive-change + openspec-explore (skill edits → Constitution IX adversarial review).
  - `dot_pi/agent/extensions/goal/` (command-judge enhancement; generic, opsx-agnostic).
- **Systems:** harness-neutral core (CLI + skill + manifest) runs on pi today, Codex/Claude via adapter rebind; pi extension is a thin optional kickoff/runtime adapter.
- **Not coupled litmus:** delete the pi extension → workflow still runs (degraded continuation via bash + `AGENT_CMD` fallback); substance lives in `opsx-gate` + `openspec-loop`.
- **Affects which projects:** any repo opting into `opsx-superpowers`; the gate/manifest are per-project, the skill/CLI/extension are user-level.
