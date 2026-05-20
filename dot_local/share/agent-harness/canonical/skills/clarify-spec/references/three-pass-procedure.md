# Three-pass clarify procedure (full reference)

Detail for each of the three passes. The skill body (`SKILL.md`) is the summary; this is the canonical source.

## Pass 1 — Ambiguity (paraphrase divergence)

**Goal:** detect ACs that two independent readers would formalize differently.

### Algorithm

For each acceptance criterion AC in `specs/**/spec.md`:

1. Generate three independent paraphrases:
   - Paraphrase 1: rewrite the AC using different sentence structure but same meaning.
   - Paraphrase 2: rewrite again with a third structure.
   - Paraphrase 3: rewrite again, attempting to use the most-divergent valid alternative meaning if the AC has any latent ambiguity.

2. Pairwise compare (3 paraphrases → 3 pairs):
   - For each pair (Pi, Pj), ask:
     - Do they have different INPUTS named?
     - Do they have different OUTPUTS named?
     - Do they have different LOGICAL RELATIONS between input and output?
   - If any of the three is yes → semantic divergence.

3. When divergence detected, record a finding:
   - `Question`: 1 sentence describing the divergence (e.g., "Does 'remove the record' mean hard-delete or soft-delete?")
   - `Option A`: the as-written interpretation (e.g., "Hard-delete: row is gone")
   - `Option B`: the alternative (e.g., "Soft-delete: row marked deleted but retained")
   - `Status`: `unanswered`

### Counter-examples (skip when these patterns appear)

- All three paraphrases converge on the same input, output, and relation → no finding.
- The AC contains explicit terms that disambiguate (e.g., "mark as deleted such that it is no longer visible in any user-facing view") → no finding.
- The ambiguity is purely stylistic (word choice) without semantic effect → no finding.

### Pass 1 budget

No cap — every AC gets paraphrased. Cost is O(N) where N = AC count.

---

## Pass 2 — Inconsistency (bounded pairwise antecedent overlap)

**Goal:** detect AC pairs whose consequents conflict on a shared observable output under reachable antecedents.

### Algorithm

1. Enumerate AC pairs in priority order:
   - **Priority 1:** pairs WITHIN the same Requirement block (local consistency).
   - **Priority 2:** pairs SHARING entity names in their consequents.
   - **Priority 3:** pairs where one is `IF…THEN` (error) and the other is `WHEN` (nominal) referencing the same entity (most common conflict source).
   - **Priority 4:** all remaining pairs.

2. For each pair `(A1, A2)`:
   - Extract A1's antecedent and A2's antecedent.
   - Read `openspec/domain.md`. Use invariants there to rule out impossibilities.
     - Example invariant: "An order cannot be canceled before submission."
     - If A1.antecedent = "order is canceled" and A2.antecedent = "order is being submitted for the first time", domain invariant rules these out as simultaneous → skip pair.
   - If both antecedents CAN hold simultaneously, examine consequents:
     - Identify shared observable outputs (e.g., both consequents affect `order_fulfilled`).
     - Check if values diverge on any shared output (e.g., A1 says `fulfill = true`, A2 says `fulfill = false`).
   - If conflict found, record inconsistency finding with the minimal contradicting set:
     - `Question`: e.g., "R1 says fulfill but R5 says don't fulfill when (order canceled + new submission). Which wins?"
     - `Option A`: keep both (R1 wins on this trigger, document precedence rule)
     - `Option B`: narrow one or both (e.g., R5 → "while canceled AND not resubmitted")

3. **N² scaling boundary:**
   - If AC count ≤ 20, enumerate all pairs (≤ 190 comparisons; tractable).
   - If AC count 21–50, enumerate only priorities 1-3 above (typically ≤ 100 comparisons).
   - If AC count > 50, enumerate priority 1 only + a sample of priority 2+3 (≤ 50 comparisons total).

4. **Cap at 20 findings per spec file.** Record the 20 highest-conflict findings (those where consequents directly contradict on observable outputs).

### Pass 2 budget

O(N²) worst case; bounded to ~100-200 comparisons in practice via priority ordering.

---

## Pass 3 — Completeness (priority-bounded combination enumeration)

**Goal:** detect uncovered (event, state) combinations where the spec is silent on system behavior.

### Algorithm

1. Extract declared events:
   - Parse all `WHEN <trigger>` clauses across the spec.
   - Deduplicate to a unique event list.

2. Extract declared states:
   - Parse all `WHILE <state>` clauses.
   - Deduplicate to a unique state list.
   - Add an implicit "default" state (the absence of any declared state).

3. Compute candidate combinations:
   - For each declared event E:
     - For each declared state S (plus "default"):
       - Combination (E, S) is a candidate.

4. Filter candidates:
   - Read `openspec/domain.md`. For each candidate (E, S), check: do any domain invariants rule out this combination?
     - Example: "An order cannot be canceled before submission" rules out (E=submit-order, S=order-canceled) as impossible.
   - Discard ruled-out candidates.

5. Check coverage for surviving candidates:
   - For each surviving (E, S), check: is there at least one AC whose antecedent matches both this event AND this state?
   - If yes → covered, skip.
   - If no → uncovered. Add to findings list.

6. Rank uncovered combinations by impact:
   - Higher impact: combinations involving safety-critical state, financial state, identity/auth state, data-modifying events.
   - Lower impact: combinations involving UI-only state, idempotent read events.

7. **Cap at 10 findings per spec file.** Record only the 10 highest-impact uncovered combinations. The cap exists because:
   - 5 events × 5 states = 25 combinations
   - 10 events × 10 states = 100 combinations
   - Most combinations after the top 10 are either domain-ruled-out or low-impact noise.

8. Format each finding:
   - `Question`: "What should the system do WHEN <event> AND WHILE <state>?"
   - `Option A`: intentionally undefined (silence is acceptable)
   - `Option B`: add new AC with a drafted text (provide a starter)

### Pass 3 budget

O(|events| × |states|) before filtering; bounded to ≤ 10 findings recorded per spec file.

---

## Brownfield vs greenfield scope

By default, clarify operates on the **delta content only** — the spec.md files in `openspec/changes/<name>/specs/` for the current change.

For brownfield changes that modify an existing capability with many existing ACs:

- Pass 1 only paraphrases ACs in the delta (`ADDED` and `MODIFIED` blocks).
- Pass 2 considers delta ACs vs delta ACs AND delta ACs vs current-spec ACs (i.e., does the delta conflict with what's already shipped?). Current-vs-current pairs are NOT examined (those would have been examined when their changes shipped).
- Pass 3 enumerates only events/states declared in the delta. Uncovered combinations in the delta scope are findings; uncovered combinations that existed before this change are NOT findings (out of scope).

The `--full-corpus` flag opts in to examining the merged current+delta corpus. Use sparingly — explosive cost.

---

## Findings file structure

The output file (`clarify.md` in the change dir) follows the schema's `templates/clarify.md`. Tables: one per pass, plus an Outstanding section and Summary. The skill writes only this file.

## See also

- `ears-patterns.md` — the EARS pattern reference (canonical syntax)
- `quality-properties.md` — the 5 quality properties + canonical AC ID format
- Schema's `clarify` artifact instruction in `~/.local/share/openspec/schemas/opsx-superpowers/schema.yaml`
- Kiro's deep-spec analysis (May 2026) for the upstream SMT-backed version: <https://kiro.dev/blog/deep-spec-analysis/>
