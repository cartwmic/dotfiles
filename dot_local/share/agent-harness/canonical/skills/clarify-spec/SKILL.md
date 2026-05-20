---
name: clarify-spec
description: Three-pass quality gate over EARS acceptance criteria — ambiguity, inconsistency, completeness. Produces a clarify.md findings file with 2-option questions for resolution. Used by the opsx-superpowers schema's clarify artifact (and invokable directly against any specs/**/spec.md).
license: MIT
compatibility: "Requires OpenSpec 1.3.0+ AND a project using `schema: opsx-superpowers` (or another schema declaring a `clarify` artifact). For standalone use, no schema requirement — just point at a specs/ directory."
metadata:
  author: cartwmic
  version: "1.0"
  generatedBy: "opsx-superpowers"
---

Run a three-pass quality gate over EARS acceptance criteria in `specs/**/spec.md`. Produce a findings file with numbered 2-option questions for user resolution.

This is the canonical implementation of the `opsx-superpowers` schema's `clarify` artifact. It is also invokable standalone (without an active OpenSpec change) against any `specs/<capability>/spec.md` to audit it.

**Three passes:**
1. **Ambiguity** — paraphrase divergence
2. **Inconsistency** — pairwise antecedent overlap
3. **Completeness** — priority-bounded combination enumeration

The full procedure, EARS reference, and quality-property definitions are in the references directory. Read them before drafting.

---

**Input contract**

- **Required:** path to a `specs/` directory (or a single `spec.md` file). When running under an OpenSpec change, this is `openspec/changes/<name>/specs/`.
- **Optional:** project root for resolving `openspec/domain.md` (used as ground-truth invariants).
- **Optional:** scope flag (`--delta-only` vs `--full-corpus`). Default `--delta-only`; clarify operates on the change's added/modified content, not the merged current+delta. This keeps Pass 2 and Pass 3 tractable in brownfield work.

**Output contract**

Write a single markdown file matching `~/.local/share/openspec/schemas/opsx-superpowers/templates/clarify.md`. The file MUST contain:

1. Three numbered sections (Pass 1 — Ambiguity, Pass 2 — Inconsistency, Pass 3 — Completeness)
2. Each section contains a findings table with columns: `# | AC ref | Question | Option A | Option B | Status | Resolution`
3. An "Outstanding (status != answered)" section auto-populated from the findings tables
4. A "Summary" section with per-pass counts and a Gate Status line: `READY for design | BLOCKED on N unanswered findings`

Status values: `unanswered | answered | deferred`. Only `answered` and `deferred` permit progression to design.

**Steps**

1. **Locate and read inputs**
   - Read every `spec.md` file in the target path. Extract `### Requirement:` blocks (with their child `#### Scenario:` blocks).
   - For each Requirement, compute the canonical AC ID `<capability>.<requirement-slug>` (slug rules in `references/quality-properties.md`).
   - Read `openspec/domain.md` if present. Treat invariants there as ground truth.
   - Read `openspec/constitution.md` if present. Use for context but don't enforce here — that's the analyze artifact's job.

2. **Pass 1 — Ambiguity (paraphrase divergence)**

   For each acceptance criterion AC:
   - Generate three independent paraphrases that preserve the AC's stated meaning. Use different sentence structures.
   - Compare the three paraphrases pairwise. For each pair, ask: do they have different inputs, different outputs, or different logical relations? If yes → semantic divergence.
   - When any pair diverges, record an ambiguity finding:
     - `Question`: one sentence describing the divergence
     - `Option A`: the first plausible interpretation ("keep meaning X")
     - `Option B`: the second plausible interpretation ("change to meaning Y")
     - `Status`: `unanswered`
   - Skip if all three paraphrases converge.

3. **Pass 2 — Inconsistency (bounded pairwise antecedent overlap)**

   - Enumerate AC pairs. For each pair `(A1, A2)`:
     - Identify A1's antecedent (the `WHEN`, `WHILE`, `WHERE`, or `IF` clause; ubiquitous ACs have implicit "always" antecedent).
     - Identify A2's antecedent. Ask: can both antecedents hold simultaneously? Use `openspec/domain.md` invariants to rule out impossibilities.
     - If both can hold simultaneously, check the consequents (`THE <system> SHALL …`) for conflict on any shared observable output.
     - When a conflict exists, record an inconsistency finding with the minimal contradicting set named.
   - **Scaling note:** at >20 ACs in a single change, do NOT enumerate full N² pairs. Prioritize:
     - Pairs within the same Requirement (highest priority — local consistency)
     - Pairs sharing entity names in their consequents
     - Pairs where one is an `IF…THEN` error AC and the other is a related `WHEN` nominal AC (most likely conflict source)
   - Cap at 20 inconsistency findings per spec file; record the highest-conflict subset.

4. **Pass 3 — Completeness (priority-bounded enumeration)**

   - List the events declared in the change's specs (extract from `WHEN` antecedents).
   - List the states declared in the change's specs (extract from `WHILE` antecedents).
   - For each (event, state) combination NOT covered by any AC, ask: is this combination realistic given `openspec/domain.md` invariants?
     - If invariants rule it out, do NOT record a finding (it's not a real gap).
     - If invariants permit it AND no AC covers it, this is an uncovered combination.
   - Rank uncovered combinations by impact (presence of safety/error implications, presence in core flows, etc.).
   - Cap at 10 findings per spec file (the 10 highest-impact uncovered combinations). Do NOT enumerate the full cartesian product — that produces combinatorial noise.

5. **Assemble the findings file**

   - Populate the three tables.
   - Auto-populate the Outstanding section (all rows with `status != answered`).
   - Write the Summary section with counts + Gate Status.

6. **Surface to user**

   If running under an OpenSpec change and any findings are `unanswered`:
   - Echo each unanswered finding to the user as a 2-option prompt.
   - Wait for user answer ("A", "B", or "DEFER").
   - Update the findings table with the answer + a resolution note.
   - When all findings are `answered` or `deferred`, set Gate Status to `READY for design` and continue.

   If running standalone (no change):
   - Write the findings file and return.
   - The user resolves findings asynchronously.

**Output during execution**

```
## Clarify: <change-name | path>

Pass 1 — Ambiguity: N findings
Pass 2 — Inconsistency: N findings
Pass 3 — Completeness: N findings

Total: N findings → wrote clarify.md
Unanswered: N (BLOCKING design progression)
Deferred: N (echoed to analyze.md outstanding-risks)
```

**Guardrails**

- Do NOT enumerate full N² pairs at N > 20. Prioritize per Pass 2 rules.
- Do NOT enumerate full cartesian product in Pass 3. Cap at 10 priority findings per spec.
- Operate on delta content by default. The full current+delta corpus is opt-in (`--full-corpus`).
- Read `openspec/domain.md` before Pass 2 and Pass 3 — invariants there bound reachability.
- Findings must include the canonical AC ID in the `AC ref` column for cross-referencing to verify gate later.
- Never modify spec.md files. The user resolves findings and the answer updates clarify.md only.
- If running standalone and the user later edits the spec, they re-run clarify-spec.

**References**

- `references/ears-patterns.md` — the five EARS patterns and the WHEN/IF discipline rule
- `references/quality-properties.md` — Testable / Solution-free / Unambiguous / Consistent / Complete with positive and negative examples; canonical AC ID slug rules
- `references/three-pass-procedure.md` — full procedure (this skill's body is the summary)
