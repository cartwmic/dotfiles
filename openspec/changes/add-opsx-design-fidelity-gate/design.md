# Design — add-opsx-design-fidelity-gate

## Context

The oxide-clone `crypt-secret-structural-hardening` run (session `019f2d9f`)
shipped a design that silently swapped the frozen intent's structural mechanism
for manual per-site handling; analyze passed because the design *nominally
cited* the right sections. The shipped G2/G3 hardening (tree-identity
attestation, read-only dispatch window) closed the wrong-tree and
mid-review-mutation defects, but three residuals remain: reviewer chat replies
contradicting their findings files, off-tree reviewer writes to the integration
checkout, and (discovered on our own `harden-opsx-reviewer-dispatch-integrity`
run) post-seal bookkeeping staling sealed verdicts in same-tree mode. The owner
additionally mandated abolishing same-tree execution entirely — worktree is the
only model — for parallel development.

Constitution/domain constraints respected: gate checks stay deterministic and
model-free (field parsing + git plumbing + sha256 only); model judgment lives
in dispatched subagents; verdict artifacts are sealed by the orchestrator, never
self-authored; MODIFIED deltas carry full requirement content (domain
invariant 14); freshness protection on every gate-read decision input is a hard
invariant (frozen intent).

Clarify rulings C1–C8 (clarify.md) are design inputs: pre-worktree attestation
carve-out, integration-checkout digest source, deterministic waiver path,
row-free escalation valve with ledger persistence, spec-file set equality,
key-less migration scenario.

## Goals / Non-Goals

**Goals:**
- A blocking, digest-bound, per-AC design-fidelity verdict before tasks
  generation on every design-bearing change, at every Scale, no waiver key.
- Verdicts derived exclusively from findings files; conversational replies are
  never verdict inputs.
- The read-only dispatch window covers both trees (reviewed worktree AND
  integration checkout).
- Worktree-mandatory execution: no mode, no derivation, no same-tree path on
  any gate/skill/template/test surface; post-seal bookkeeping non-staling falls
  out structurally.

**Non-Goals:**
- No delta-scoped re-judging, no cross-judgment finding matching (re-judges are
  full sweeps).
- No sandboxing or OS-level enforcement of reviewer read-only discipline —
  detection + voiding, not prevention.
- No relitigation of the shipped attestation semantics for post-implementation
  dispatches.
- No new worktree plumbing — `opsx worktree ensure` and the locator/resolver
  machinery are reused as-is.

## Decisions

### D1: design-fidelity.md — sealed per-AC entailment artifact, digest-bound, gate-checked deterministically

**Choice:** New verdict artifact `design-fidelity.md`, produced by filling a
new shipped template (`templates/design-fidelity.md`), sealed by the
orchestrator. Body: one verdict row per delta AC — `entailed | not-entailed |
not-covered` + evidence; own-line gate-read fields: `**Fidelity:**`
(`delivered | violated`), judge provenance (adapter-stamped),
`**Attested HEAD:**`, one sha256 digest field per bound file (intent.md,
design.md, every `specs/**/spec.md`), optional `**Human Waiver:**`. The gate
check (`opsx gate`, new `design-fidelity` check) is deterministic and
model-free: parse fields; enumerate the actual `specs/**/spec.md` set under
`openspec/changes/<change>/` **in the integration checkout** and fail on any
set difference vs recorded digest fields (C6); recompute each digest from the
integration-checkout change dir (C3 — change-dir artifacts are committed there;
the worktree may hold stale copies); fail closed on absence, mismatch,
unparseable fields, or `violated` without waiver. `WHERE` no design.md exists,
the check is not required.

**Alternatives considered:**
- **Fidelity section inside analyze.md**: couples freshness to analyze's
  lifecycle; analyze is advisory at plain M, fidelity must block at every
  Scale. Rejected.
- **Judge model re-run at gate time**: violates the deterministic/model-free
  gate constitution principle. Rejected.
- **Digest of design.md only**: intent and delta specs are the entailment's
  other two legs; editing either invalidates the judgment. All three bound.

**Rationale:** Digest binding makes "edit ⇒ re-judge" mechanical; set equality
closes the add-a-spec-file-after-seal hole; integration-checkout hashing is the
only tree where the bound files are current.

**4-point test:** multiple approaches, lasting artifact contract, disagreement
plausible, constrains future gate evolution → ADR candidate **Y**.

### D2: Dispatch channels + pre-worktree attestation carve-out

**Choice:** `full_rigor: true` — the fidelity sweep rides the existing blind
analyze dispatch as a REQUIRED section of that dispatch prompt, verdict still
sealed to the separate design-fidelity.md. Plain M (and design-bearing S/XS) —
one narrow post-design blind mini-dispatch produces the same sealed artifact.
Judge contract mirrors the baseline-bounded reviewer contract: block only on
clear non-entailment of the AC as written; ambiguity routes an advisory
clarify-class finding. Attestation: fidelity (like clarify/analyze) is
dispatched **before worktree creation**, so the judge attests the integration
checkout — path check satisfied by equality with the canonicalized
integration-checkout root, `Attested HEAD` = integration-checkout HEAD at
dispatch (C2). The gate binds fidelity's attestation as a 40-hex literal but
never demands Reviewed-Range equality (no range exists); freshness is carried
by the digests alone. The carve-out is scoped strictly to pre-worktree
judgments; every post-implementation dispatch keeps the unconditional worktree
path check.

**Alternatives considered:**
- **Re-time fidelity post-worktree**: contradicts the frozen intent's
  "before tasks are generated"; a design defect discovered after implementation
  wastes the whole apply. Rejected.
- **Separate fidelity dispatch even at full_rigor**: doubles dispatch cost for
  the tier that already runs a blind analyze; the analyze judge reads the same
  three inputs. Rejected.

**Rationale:** Reuses existing dispatch plumbing; carve-out keeps the
attestation rule total (every dispatch attests *the tree it was given*) without
weakening post-implementation discrimination.

**4-point test:** timing/channel choices lasting, disagreement real → ADR
candidate **Y**.

### D3: Deterministic human-waiver path

**Choice:** `Fidelity: violated` + non-empty own-line `**Human Waiver:**` field
naming the human ruling = gate check satisfied (waived), the analogue of
`doneness_mode: waived` + rationale (C4). The waiver is written only by a human
ruling at the decision-audit landing, never self-authored. Digest bindings stay
enforced — any post-waiver edit to a bound file stales the waived seal like any
other.

**Alternatives considered:**
- **Land waived changes outside the gate** (loop_hold + manual merge): leaves
  the gate permanently red on a legitimately waived change, breaking
  gate-as-arbiter and every downstream automation. Rejected.
- **Waiver sets `Fidelity: delivered`**: self-authored `delivered` is exactly
  the forgery class this change exists to kill. Rejected.

**Rationale:** Only enumerable deterministic green path that keeps human
authority explicit and auditable in the artifact.

**4-point test:** → ADR candidate **Y**.

### D4: Escalation valve counts consecutive `violated` from the round ledger

**Choice:** Every sealed fidelity verdict is recorded as a round-ledger entry
(the ledger is orchestrator-sealed and freshness-protected per
dispatch-integrity). The valve fires on two consecutive `violated` ledger
entries — regardless of which rows failed, no per-row cross-round comparison
(C5, C7) — routing to the decision-audit landing with the fidelity history
instead of a third automatic dispatch. Ledger persistence makes the count
survive session restarts and re-seals.

**Alternatives considered:**
- **"Same failing rows" trigger**: is cross-round finding matching, forbidden
  by the frozen intent's non-goals; also unimplementable — each re-seal
  overwrites the artifact. Rejected.
- **History structure inside design-fidelity.md**: duplicates the ledger;
  a second freshness-protected store to maintain. Rejected.

**Rationale:** The ledger already exists, already persists, already protected.

**4-point test:** borderline (mechanism reuse) — ADR candidate **N**.

### D5: Findings file is the sole verdict source

**Choice:** For every reviewer/judge dispatch (code review, doneness, design
fidelity, judged clarify/analyze), the orchestrator consolidates verdict,
findings, and attestation exclusively from the subagent's findings output file
(the `output:` file of the dispatch). The conversational reply is never parsed
for verdict content. Absent file, or file lacking the required verdict
line/attestation fields ⇒ INVALID (invalid-not-fail semantics: excluded from
gating, ledger, and round budget; incident recorded; re-dispatch or reviewer-set
repair).

**Alternatives considered:**
- **Reply as fallback when file is absent**: the gpt-5.2 "no implementation
  changed" incident is precisely a persuasive reply masking a defect-bearing
  file; any reply-trust path recreates it. Rejected.
- **Reply/file cross-check with conflict error**: adds a comparison of a
  freeform channel against the structured one — the freeform channel has no
  contract to check against. Rejected.

**Rationale:** One structured channel, one contract, mechanically checkable.

**4-point test:** → ADR candidate **Y**.

### D6: Dual-tree read-only window

**Choice:** The pre/post round snapshots cover the reviewed worktree AND (when
a different tree — the worktree-always norm) the integration checkout: per tree
`git rev-parse HEAD` + `git status --porcelain=v1`, with the change's own
`openspec/changes/<change>/` paths excluded (orchestrator-sealed bookkeeping,
the only permitted in-window writes). Delta in either tree ⇒ all round verdicts
INVALID, surgical restore (`git restore` only status-changed tracked paths;
delete only window-introduced untracked paths; never blanket `git clean`),
incident recorded. Plain git commands only.

**Alternatives considered:**
- **Reviewed-tree-only window** (status quo): the session-019f2d9f reviewer
  wrote the integration checkout's progress.md — invisible to a one-tree
  window. Rejected.
- **Snapshot every repo tree** (all worktrees): unrelated concurrent changes'
  worktrees legitimately mutate in parallel; voiding on their activity
  deadlocks parallel development. Two trees are exactly the dispatch's blast
  radius. Rejected.

**Rationale:** Covers every tree a dispatched reviewer can plausibly write.

**4-point test:** → ADR candidate **Y**.

### D7: Worktree-mandatory — abolish the mode, fail closed on its ghosts

**Choice:** Remove `Worktree Mode` from the switchboard vocabulary and the
XS/S⇒same-tree derivation entirely. Enforcement: (a) a `worktree_mode` key in
review.md front-matter is a failed gate check naming the delete-the-key remedy;
(b) past Diff Base capture, locator + convention-path both failing to validate
as a git worktree on `opsx/<change>` fails verdict evaluation loudly — never a
silent integration-checkout fallback — including the key-less tier-default
migration shape (Diff Base present, empty Worktree Path, no branch ⇒ re-home
remedy `opsx worktree ensure <change>`, C8); (c) Land Base Currency requires
the `opsx/<change>` branch to exist — a change is never landed from
integration-checkout commits; (d) skill surfaces present worktree as the only
model, XS included (ensure → locator → apply → review → merge → cleanup);
(e) same-tree scenarios/clauses deleted from Worktree Lifecycle Ownership,
Per-task file contracts, Mode-driven apply, Post Apply Code Review Artifact
(C1). `opsx-cli` worktree commands are reused unchanged.

**Alternatives considered:**
- **Keep same-tree as an explicit opt-out**: retains the entire dual-mode test
  matrix, the attestation carve-out for post-impl reviews, and the post-seal
  staling trap this change exists to kill; contradicts the owner mandate.
  Rejected.
- **Derive worktree-required at every tier but keep the key**: a dead key that
  can only confuse; fail-closed rejection is strictly clearer. Rejected.

**Rationale:** Owner mandate; parallel development wants N changes = N
worktrees with zero tree contention; every same-tree special case in gate and
skills deletes.

**4-point test:** → ADR candidate **Y** (BREAKING).

### D8: Post-seal bookkeeping non-staling — structural, not allowlisted

**Choice:** No mechanism is added. Under worktree-always, sealed verdicts bind
to the `opsx/<change>` worktree branch HEAD; orchestrator bookkeeping
(loop_hold, follow-ups.md routing, Execution Notes) commits on the integration
checkout per the writeback-owner discipline and therefore never moves the
verdict-bound HEAD. The hard invariant holds untouched: gate-read decision
inputs stay freshness-protected, review.md is never allowlisted wholesale —
a post-seal edit to gate-read decision inputs still fails closed/stales.

**Alternatives considered:**
- **Verdict-file allowlist in the freshness check**: allowlists are exactly the
  self-serve staleness-evasion channel the intent forbids. Rejected.
- **Separate bookkeeping file outside review.md**: unnecessary once same-tree
  dies; adds a surface. Rejected.

**Rationale:** The trap was a same-tree artifact; D7 deletes its preconditions.
Deterministic, model-free, BSD-git compatible (plain plumbing only).

**4-point test:** consequence of D7, not independently contested → ADR
candidate **N** (documented as D7 corollary).

## Risks / Trade-offs

| # | Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|---|
| R1 | Fidelity judge too strict — blocks on defensible designs, stalls loops | Medium | Medium | Bounded contract (block only on clear non-entailment); ambiguity routes advisory; D4 valve caps at two rounds → human ruling |
| R2 | XS changes pay worktree overhead for typo-class fixes | High | Low | Accepted by owner ruling (uniform ergonomics); `opsx worktree ensure` is one command; cleanup owned by archive |
| R3 | Digest false-stales from incidental change-dir edits (e.g. tasks.md) | Medium | Low | Only intent.md, design.md, specs/ are bound — tasks/plan/verify edits never stale fidelity |
| R4 | Pre-worktree carve-out weakens attestation if misapplied to post-impl dispatches | Low | High | Carve-out scoped by dispatch class in spec text; post-impl path check unconditional; scenario pins integration-checkout attestation as INVALID for worktree dispatches |
| R5 | In-flight pre-deployment same-tree changes brick on the new gate | Low | Medium | C8 migration scenario names the re-home remedy; verified only this change is active |
| R6 | Dual-tree restore deletes wanted untracked files | Low | Medium | Surgical restore: only window-introduced untracked paths; never blanket clean; incident recorded before restore |

## Migration Plan

1. Land gate + schema + template + skill surfaces together (single change;
   surfaces move together).
2. This change itself is the only active change; it re-homes to a worktree at
   its own apply step (first consumer of worktree-always).
3. Any future resurrection of a pre-deployment same-tree change hits the C8
   fail-closed path with the `opsx worktree ensure` remedy.
4. Rollback: revert the change commit range; no data migration (artifacts are
   additive; `worktree_mode` keys were already absent from active changes).

## Open Questions

None — clarify C1–C8 resolved the open design inputs; escalation/waiver
authority is pinned to the decision-audit landing.
