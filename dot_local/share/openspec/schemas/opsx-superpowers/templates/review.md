---
# Machine-readable mode block — the SOLE source opsx-gate reads (it never parses
# the prose table below). Keep the table in sync as the human-facing mirror.
scale: S
worktree_mode: worktree-required
execution_mode: standard
verification_mode: retained-recommended
debug_mode: standard
review_status: not-requested
delegation_mode: single-agent
code_review_mode: advisory
loop_max_iterations: 20
validation_source_mode: required
spec_level: spec-anchored
# ── Optional per-change model/provider overrides (resolved by `opsx-models`) ──
# Pin models for THIS change above the project/user config files. A value
# containing "/" is a complete pi model id used verbatim; a BARE id is qualified
# by the provider keys. Roles left unset fall back to the session model.
# author_model: claude-bridge/claude-opus-4-8
# review_models: [claude-bridge/claude-opus-4-8, openai-codex/gpt-5.5]
# impl_model: claude-bridge/claude-opus-4-8
# author_in_session: true
# provider: claude-bridge          # default provider for bare ids
# author_provider: claude-bridge   # per-role provider overrides
# review_provider: openrouter
# impl_provider: claude-bridge
---

# Review

<!--
Controlled-vocabulary mode switchboard. The apply instruction reads these modes
and dispatches behavior; opsx-gate reads the YAML front-matter above. Override
any mode by setting it (in BOTH the front-matter and this table).
-->

## Modes

| Mode | Value | Notes |
|---|---|---|
| Scale | S | XS\|S\|M\|L\|XL — skills author per Scale (graph is static; gating lives in the skills + opsx-gate) |
| Execution Mode | standard | standard\|tdd-preferred\|tdd-required |
| Verification Mode | retained-recommended | inline-only\|retained-recommended\|retained-required — retained-required forces verify.md green before archive |
| Debug Mode | standard | standard\|systematic-debugging |
| Review Status | not-requested | not-requested\|requested\|findings-received\|resolved |
| Delegation Mode | single-agent | single-agent\|subagent-eligible\|subagent-required — dispatch via the subagent-dispatch capability hook (pi-subagents is the pi adapter) |
| Worktree Mode | worktree-required | worktree-required (default, all Scales)\|worktree-eligible\|same-tree (explicit override) |
| Code Review Mode | advisory | none\|advisory\|gating-required — default gating-required at Scale ≥ M; gating-required blocks archive on code-review.md Verdict |
| Loop Max Iterations | 20 | iteration budget; mapped onto the loop runtime turn budget (S≈20, M≈40, L≈80) |
| Validation Source Mode | required | required\|waived — waived (with rationale) lets Scale ≥ M pass with no agent-independent validation source |
| Spec Level | spec-anchored | spec-anchored\|spec-first\|spec-as-source (warning if last) |
| Model Config | (unset) | optional `author_model`/`review_models`/`impl_model`/`author_in_session` + `provider`/`*_provider` front-matter keys, resolved by `opsx-models`; unset ⇒ session model |

## Diff Base + Worktree locator

<!--
Captured by apply at worktree creation. `Diff Base SHA` = integration-branch
merge-base, IMMUTABLE for the life of the `opsx/<change>` branch; used by
file-contract diffs, code-review diff base, and opsx-gate verdict freshness.
In same-tree mode, Diff Base SHA = pre-apply HEAD and Worktree Path is empty.
-->

**Diff Base SHA:** <empty until apply captures it>
**Worktree Path:** <empty until apply captures it>
**Integration Branch:** main

## Manual Adjustments

<!-- Author-driven overrides to defaults. One bullet per non-default value with
rationale. Keep the front-matter, the table, and these notes consistent. -->

- <override + rationale>

## Execution Notes

<!-- Transient observations appended during apply. One-line entries when a
non-trivial decision is made mid-task. Durable knowledge → retrospective.md. -->

- YYYY-MM-DD HH:MM — <note>
