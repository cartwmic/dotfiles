---
name: "OPSX: Loop"
description: Drive an opsx-superpowers change to a green opsx-gate via the openspec-loop orchestrator (Experimental)
category: Workflow
tags: [workflow, loop, enforcement, experimental]
---

Drive a single opsx-superpowers change to completion behind the deterministic
`opsx-gate`. Kicks off the `openspec-loop` orchestrator; the loop ends only when
`opsx-gate <change>` exits 0.

**Input**: A change name (e.g. `/opsx:loop add-clipboard-extension`). If omitted,
infer from context or prompt with `openspec list --json`.

**Preconditions**
- `intent.md` exists in the change dir (frozen by `/opsx:explore`). It is the
  immutable baseline — never edit it without explicit human authorization.
- `opsx-gate` is on PATH (`~/.local/bin/opsx-gate`).

**Steps**

1. Announce: "Using change: <name>" and that the loop stops only at a green gate.
2. Ensure the worktree exists (Worktree Mode is worktree-required by default):
   pre-flight commit the change subtree, `git worktree add -B opsx/<name> <path>`,
   record the immutable `Diff Base SHA` (integration merge-base), `Worktree Path`,
   and `Integration Branch` into `review.md`.
3. Invoke the **openspec-loop** skill for `<name>`. Each turn:
   - run `opsx-gate <name> --worktree <path>`; exit 0 → stop (ready to archive).
   - else address the earliest blocking `GATE-FAIL` line; delegate any review
     verdict to a blind subagent judged against the frozen baseline.
4. Respect the loop budget (`loop_max_iterations` in review.md front-matter);
   on exhaustion, stop and preserve the worktree for inspection.
5. When green, suggest `/opsx:archive` (which merges the worktree + cleans up).

**Harness-neutral equivalents**
- pi: set a command-judge and run the generic goal loop —
  `PI_GOAL_JUDGE_CMD='opsx-gate <name> --worktree <path>'` then `/goal advance <name> to a green opsx-gate`.
- any harness / CI: `AGENT_CMD='<headless agent>' opsx-loop <name> --worktree <path>`
  (the bash driver; the only thing it knows about a harness is `$AGENT_CMD`).

**Guardrails**
- The gate — not your judgment — defines "done". Never fabricate a green verdict;
  the gate recomputes the diff range and rejects stale/unprovenanced verdicts.
- Never self-author a review verdict; reviews go to a blind subagent.
- Pause for the owner on clarify blockers or adversarial 🔴-tier decisions.
