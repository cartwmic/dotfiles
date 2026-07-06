# Clarify — add-opsx-design-fidelity-gate

**Source:** blind three-pass clarify dispatch (ambiguity / inconsistency /
completeness) over the 4 delta spec files, cross-checked against the frozen
intent (`555da54`), live capability specs, constitution, and domain invariants.
**Judge attestation:** `Attested HEAD: ae27b2d33f6c0da4b9f796ab04239df1d0a9dfa3`,
`Attested Path: /Users/cartwmic/.local/share/chezmoi` (pre-worktree dispatch —
integration checkout is the only tree at clarify time).
**Findings:** 8. **Resolution authority:** autonomous drive-to-green loop;
rulings recorded here and applied to the delta specs in the same commit.

## Findings and rulings

### C1 — Worktree-mandatory abolition incomplete: surviving live requirements still describe same-tree (INCONSISTENCY)

Live requirements NOT in the delta set still carry same-tree semantics and
would survive archive-merge verbatim, contradicting the new worktree-always
requirements: `opsx-workflow-schema/Worktree Lifecycle Ownership` (two
same-tree scenarios + mode-conditional wording), `opsx-workflow-schema/Per-task
file contracts` ("or, in same-tree mode, …"), `opsx-skill-integration/
Mode-driven openspec-apply-change` (`worktree-eligible`/`same-tree`
conditionals — `worktree-eligible` becomes a dangling enum),
`opsx-adversarial-review/Post Apply Code Review Artifact` ("both worktree and
same-tree modes").

- **Option A:** leave survivors for a later cleanup change.
- **Option B:** add full-content MODIFIED blocks for all four surviving
  requirements, deleting every same-tree path; update proposal Impact.

**Ruling: B.** A BREAKING mandate whose acceptance sketch says "no gate, skill,
template, or test surface retains a reachable same-tree path" cannot ship
half-applied. All four requirements added as MODIFIED deltas; proposal Impact
updated to enumerate touched requirements.

### C2 — Fidelity runs pre-worktree; worktree-bound attestation is unsatisfiable (INCONSISTENCY)

Fidelity is judged BEFORE tasks generation; the worktree is created by apply
AFTER propose. At fidelity-seal time no `opsx/<change>` worktree exists, yet
the attestation path check demands the dispatched worktree root and declares
the integration checkout INVALID → every fidelity verdict INVALID → permanent
red.

- **Option A:** re-time fidelity post-worktree (contradicts frozen intent).
- **Option B:** carve out pre-worktree judgments: they attest the integration
  checkout, whose canonicalized root satisfies the path check for those
  dispatches; fidelity freshness is carried by the digest bindings (not a
  Reviewed Range), and its `Attested HEAD` binds to the integration-checkout
  HEAD at judgment.

**Ruling: B.** Applied to `Reviewer Tree Identity Attestation`, `Design
Fidelity Judge`, and `Verdict Freshness And Provenance`. The carve-out is
scoped strictly to judgments dispatched before worktree creation
(clarify/analyze/design-fidelity); every post-implementation dispatch keeps the
unconditional worktree path check.

### C3 — "Recompute each recorded digest from the located tree" ambiguous (AMBIGUITY)

Change-dir artifacts (intent.md, design.md, delta specs) live and are committed
on the integration checkout; the freshness locator resolves the worktree.
Hashing from the worktree yields stale/absent copies.

- **Option A:** state the integration-checkout reading explicitly.
- **Option B:** amend the requirement: digests recomputed from
  `openspec/changes/<change>/` in the integration checkout, decoupled from the
  worktree range-freshness locator; scenario pinning the tree.

**Ruling: B.** Applied to `Design Fidelity Verdict Enforcement`.

### C4 — `violated` + human waiver has no deterministic gate-pass path (INCONSISTENCY)

The escalation valve records a human waiver, the skill lets tasks proceed on
"delivered OR waiver", but the gate's only pass condition was
`Fidelity: delivered` — a waived change could never go green.

- **Option A:** land waived changes outside the gate via the landing.
- **Option B:** explicit deterministic waiver path: `Fidelity: violated` plus a
  non-empty human-waiver field naming the ruling = satisfied check (analogous
  to `doneness_mode: waived` + rationale).

**Ruling: B.** Applied to `Design Fidelity Verdict Enforcement` (prose +
scenario); the `Violated verdict fails the gate` scenario now scoped to
"with no human-waiver field". Waiver authorship stays human-only at the
decision-audit landing; digests must still match (a waiver does not survive
post-waiver edits).

### C5 — Escalation trigger "same failing rows" contradicts the no-cross-round-matching non-goal (INCONSISTENCY)

Detecting "same rows keep failing" IS cross-round finding matching, which the
frozen intent forbids; each re-seal overwrites the artifact so nothing can
compare rows anyway.

- **Option A:** read loosely as consecutive `violated` totals; reconcile wording.
- **Option B:** trigger = two consecutive sealed `violated` verdicts regardless
  of which rows failed; state explicitly that no per-row cross-round comparison
  occurs.

**Ruling: B.** Applied to `Design Fidelity Judge` (prose + scenario).

### C6 — Digest binding misses post-seal ADDITION/REMOVAL of delta spec files (COMPLETENESS)

The gate iterated only *recorded* digest fields; a new delta spec file added
after sealing has no recorded field, mismatches nothing, and its ACs enter
unjudged.

- **Option A:** assume the spec-file set never changes post-seal (false — a
  `violated` re-authoring cycle can add a capability delta).
- **Option B:** gate enumerates the actual `specs/**/spec.md` set and fails
  closed when it differs from the recorded digest-field set; scenario added.

**Ruling: B.** Applied to `Design Fidelity Verdict Enforcement`.

### C7 — Consecutive-`violated` count has no specified persistence (COMPLETENESS)

Each re-judgment re-seals `design-fidelity.md`; nothing said where the
"2nd consecutive violated" state lives or that it survives a session restart.

- **Option A:** state that the count lives in the existing round ledger /
  Execution Notes (already freshness-protected by dispatch-integrity).
- **Option B:** new persisted history structure inside design-fidelity.md.

**Ruling: A (stated explicitly).** The round ledger already persists
per-dispatch outcomes and is orchestrator-sealed and freshness-protected; a
second history structure would duplicate it. Applied to `Design Fidelity
Judge`: sealed fidelity outcomes SHALL be recorded as round-ledger entries and
the valve counts consecutive `violated` entries from the ledger.

### C8 — Key-less tier-default same-tree in-flight changes evade the `worktree_mode`-key rejection (COMPLETENESS)

A pre-deployment change that ran same-tree by tier default wrote no
`worktree_mode` key and no `opsx/<change>` branch, but did capture a same-tree
Diff Base — the key-rejection scenario never fires.

- **Option A:** rely on C1's removal of the surviving same-tree freshness
  scenario (subsumption).
- **Option B:** pin an explicit migration scenario: same-tree-shaped locator
  (Diff Base present, empty Worktree Path, no branch) fails the verdict checks
  naming the re-home remedy.

**Ruling: B (belt over C1's braces).** Applied to `Worktree Mandatory Gate
Enforcement`. C1's fix removes the contradicting survivor; this scenario makes
the migration behavior directly testable regardless.

## Disposition

All 8 findings resolved; rulings applied to the delta specs in this commit.
`openspec validate add-opsx-design-fidelity-gate --strict` green post-apply.
No findings remain open; none escalated to the owner (no frozen-intent
contradiction required — C2's carve-out preserves the intent's "before tasks
are generated" timing, and C5/C7 align the valve with the intent's own
non-goals).
