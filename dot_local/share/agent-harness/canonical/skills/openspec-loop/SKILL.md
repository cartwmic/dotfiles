---
name: openspec-loop
description: Drive an opsx-superpowers change to completion as a single orchestrator agent, advancing until opsx gate is green and delegating every review/validation-judgment step to a blind subagent. Use after an explore session has frozen intent.md, to autonomously complete propose→apply→archive behind the deterministic gate.
license: MIT
compatibility: Requires the opsx gate CLI and an opsx-superpowers change. Subagent dispatch and loop continuation are capability hooks that degrade to inline.
---

# openspec-loop

**Announce at start:** "I'm using the openspec-loop skill."

Single-orchestrator, gate-driven loop. One agent stays in control, consults
`opsx gate` for the next failing check, performs the next step, and repeats until
the gate exits 0. Reviews are delegated to blind subagents judged against a frozen
baseline. This is the harness-neutral workflow brain; the loop runtime (continuation
budget) and subagent dispatch are adapters.

## Preconditions

- `intent.md` exists in the change dir (frozen by `openspec-explore`). It is the
  immutable baseline; never edit it without explicit human authorization.
- `opsx gate` is on PATH. The gate — not your judgment — defines "done".

## The cycle

Each turn:

1. Run `opsx gate <change>` (with `--worktree <path>` when worktree-required).
   - Exit 0 → **stop**; report the change ready to archive.
   - Non-zero → read the report. Findings are emitted in lifecycle dependency
     order; take the **earliest blocking** `GATE-FAIL` line.
2. Address exactly that failure (one unit of progress), then commit:

   | Earliest failure | Action |
   |---|---|
   | missing artifact | author it (`openspec-propose`/edit), tracing to `intent.md` |
   | unchecked tasks | implement the next task under its file contract; check it off |
   | failing validation command | fix the code; never weaken the gate |
   | missing/failing review (clarify/analyze/code-review/verify) | **dispatch a blind subagent** (below) |

3. Loop. Bound by `loop_max_iterations` (review.md front-matter), mapped onto the
   runtime turn budget so a single budget governs the loop. On budget exhaustion,
   stop and **preserve** the worktree/branch for inspection.

## Subagent review against baseline (mandatory)

Every review or validation-**judgment** step is delegated to a blind subagent — the
orchestrator never self-authors a verdict. The subagent judges current work against
the phase-appropriate baseline:

| Phase | Baseline the subagent judges against |
|---|---|
| clarify | `intent.md` |
| analyze | `intent.md` + proposal + specs + design + constitution + domain |
| code-review (post-apply) | `intent.md` + proposal + specs + design + plan + tasks status, over the diff `Diff Base SHA..HEAD` |

The subagent authors the verdict artifact (body, Verdict, Diff Base SHA, reviewed
range, `review_mode`, provenance). For Constitution-IX changes (existing-skill edits)
the code-review must be multi-model adversarial; a `degraded-single-model` verdict does
**not** satisfy the gate — `opsx gate` and archive treat it as failed.

Capability hook `subagent-dispatch`: use the host adapter (e.g. pi-subagents) when
registered; if none, run inline, mark `review_mode: degraded-single-model`, and tell
the user it does not satisfy a gating-required review — recommend running
`adversarial-review-cycle` manually.

## Role models (opsx models)

The orchestrator CONSUMES harness-neutral model config (it does not own it). The
opsx-loop pi extension exports `OPSX_AUTHOR_MODEL` / `OPSX_REVIEW_MODELS` /
`OPSX_IMPL_MODEL` / `OPSX_AUTHOR_IN_SESSION` on loop start; from any harness, resolve
directly with `opsx models <role> --change <name>` (values are already
provider-qualified). Dispatch one blind reviewer per configured `review` model and
pass `impl` to implementation subagents, each verbatim as the subagent `model:`.
Author artifacts in-session by default (write the `<!-- authored: in-session -->`
marker); delegate authoring only when `OPSX_AUTHOR_IN_SESSION` is `false`. Unset roles
fall back to the session/default model — never hard-fail.
(opsx-skill-integration.skills-honor-configured-role-models)

## Stop conditions

- `opsx gate` exits 0 → ready to archive (the loop does not itself archive).
- Budget exhausted → stop, preserve worktree, report remaining failures.
- A clarify blocker or adversarial 🔴-tier decision needing the owner → pause and ask.

## Harness-agnostic fallback

With no loop-continuation adapter, the workflow still runs via the `opsx loop` bash
driver (Ralph-style, `AGENT_CMD`-parameterized) calling this same prompt and gate.
Deleting the kickoff adapter loses convenience, not the workflow.
