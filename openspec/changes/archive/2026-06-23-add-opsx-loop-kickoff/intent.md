# Intent — add-opsx-loop-kickoff

## Intent

Close the gap the owner identified: the `openspec-loop` skill is a worker playbook, not a loop guarantee. Give pi a single command `/opsx-loop <change>` that deterministically loops — inject a turn, run `opsx-gate` as the judge, continue until green or budget — so looping is guaranteed by an engine, not best-effort agent self-iteration.

## Constraints

- **Do NOT modify the `goal` extension.** It stays a generic command-judge loop. The new extension is a separate, dedicated pi adapter that reuses the same `agent_end` + `sendUserMessage(followUp)` mechanism without runtime coupling.
- **Self-contained.** No cross-extension imports that could break when extensions deploy to separate dirs; the extension carries its own small pure helpers.
- **Judge is opsx-gate (deterministic).** The loop stops on `opsx-gate` exit 0; never on agent self-assessment.
- **Single budget.** Read `loop_max_iterations` from the change's `review.md` front-matter; default sensibly if absent.
- **Interrupt/error stops the loop** (mirror goal-loop semantics); preserve the worktree on budget exhaustion.

## Invariants honored

- Constitution II (extension lives at canonical chezmoi source path, deploys via chezmoi).
- Constitution III (no secrets), V (no new dev-tool install).
- ADR-0006 (loop runtime = command-judge), ADR-0007 (orchestrator primary; this is the pi kickoff adapter).
- Domain: pi extension is `dot_pi/agent/extensions/<name>/` deploying to `~/.pi/agent/extensions/<name>/` (NOT a `.pi/` root path).

## Non-goals

- Editing the `goal` extension or the `openspec-loop` skill.
- A non-pi kickoff (other harnesses use the `opsx-loop` bash driver).
- Worktree creation (apply/the loop worker handles that; the kickoff resolves an existing/declared worktree).
