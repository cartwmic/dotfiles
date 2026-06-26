<!-- authored: in-session -->
# Clarify Findings

Three passes over the delta ACs in `specs/opsx-cli/spec.md` and
`specs/opsx-loop-kickoff/spec.md`. All findings self-resolved (autonomous run); 0 unanswered.

## Pass 1 — Ambiguity (semantic-entropy lite)

| # | AC ref | Question | Option A (keep) | Option B (change) | Status | Resolution |
|---|---|---|---|---|---|---|
| A1 | opsx-cli:Model Config Write Surface | `opsx models set review <model>` — review is list-valued; does `set` replace the whole list or append one entry? | Replace: `set` writes a single scalar value, replacing any existing list | Append/merge into a list | answered | **A**. `set <role> <model>` writes one value (replace). List authoring stays manual YAML editing — keeps the write surface a simple editor, avoids list-mutation grammar. Documented in design D3. |
| A2 | opsx-cli:Hard Cutover | Does the "no legacy name" scan flag the `opsx-loop` pi extension dir / `/opsx-loop` slash command? | Exempt — they are not executables | Rename them too | answered | **A**. Extension dir + slash command keep their names (not CLIs). Only the bash *driver* executable folds into `opsx loop`. Already exempted in the AC. |
| A3 | opsx-loop-kickoff:Stall detection | Where is the consecutive-failure threshold configured? | Built-in constant default 3, not a new config surface | New `review.md`/yaml key | answered | **A**. Hard-coded default 3. Avoids adding a config knob for a guardrail; revisit only if it bites. |

## Pass 2 — Inconsistency (pairwise antecedent overlap)

| # | AC pair | Shared antecedent | Conflict on output | Option A (keep both) | Option B (resolve) | Status | Resolution |
|---|---|---|---|---|---|---|---|
| I1 | Argument parsing preserves full input ↔ Single-command guaranteed loop | user issues `/opsx-loop <token> <more...>` | what the extra tokens do | both: keyword→subcommand, else change-name + ignored-with-note | — | answered | **A**. No conflict: the parser checks a leading keyword set (`status`/`clear`/`models`) first; only a non-keyword first token is a change name, and trailing tokens then surface an "ignored" note. Deterministic precedence. |
| I2 | opsx-gate is the deterministic judge (worktree re-resolve each turn) ↔ Budget exhausted preserves worktree | loop active, gate red | worktree handling | both consistent | — | answered | **A**. Re-resolution only *reads* `Worktree Path`; it never removes a worktree. Budget/stall stops still preserve it. No conflict. |

## Pass 3 — Completeness (event/state combination enumeration)

| # | Combination | Question | Option A (intentional silence) | Option B (add new AC) | Status | Resolution |
|---|---|---|---|---|---|---|
| C1 | `/opsx-loop models` with NO directive | What happens on bare `models`? | undefined | default to `list` | answered | **B (folded into existing AC)**. Bare `/opsx-loop models` → behaves as `models list`. Captured by the Model config subcommand req's list path; design D4 notes the default. |
| C2 | `opsx models get <role>` when role unset | output? | undefined | mirror resolver: empty stdout, exit 0 | answered | **B**. `get` mirrors `opsx models <role>` resolution semantics (empty stdout = unset, exit 0). Documented in design D3; no separate AC needed (it is the resolver's existing contract). |
| C3 | `opsx models set` when target YAML file does not yet exist | output? | error | create the file then write | answered | **B**. `set` SHALL create the target file (and parent dir for the user layer) if absent, then write atomically. Covered by the atomic-write AC; design D3 records create-if-absent. |

## Outstanding (status != answered)

None. All findings answered; 0 unanswered, 0 deferred.
