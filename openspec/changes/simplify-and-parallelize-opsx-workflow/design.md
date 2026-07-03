# Design: simplify-and-parallelize-opsx-workflow

Decisions binding implementation. Baseline: frozen intent.md (fbc9ad9), delta
specs post-clarify. Everything below is deterministic and model-free in the
gate/extension paths (ADR-0007 lineage).

## D1 — `opsx status` runs the gate in a NEW cheap mode (`--cheap`)

The fleet view needs "gate red/green + earliest failing check" per change, but
running full validations (bun/test suites) per change makes status minutes-slow
and effectively unusable as a glance view. `opsx gate` already has a two-phase
structure (cheap checks → validations). Decision: add an internal `--cheap`
flag to `opsx gate` that runs ALL deterministic file/front-matter/verdict
checks but SKIPS validation-command execution, and have `opsx status` consume
it. Status labels the summary `gate(cheap)` so a green never overclaims
("validations not run"). Full-gate truth stays `opsx gate <change>`.
Status output: one block per change — change name, Scale (+full_rigor), gate(cheap)
summary + earliest failing check, worktree path + `valid|invalid|none` on
branch `opsx/<change>`, `loop_hold` + reason (or `—`), `base: N behind main`
(from Diff Base SHA; placeholders when locator absent). Always exit 0.

## D2 — A1 + A3 + A2-detector live in a new `opsx archive-check <change>` verb

The "archive/land path" enforcement home is a single deterministic verb the
openspec-archive-change skill MUST run (and quote) immediately before
`openspec archive`:
1. **land-base-currency**: `git merge-base opsx/<change> main` == `git rev-parse main`;
   branch-absent ⇒ satisfied (same-tree exemption per clarify C-1); failure names
   the rebase remedy.
2. **duplicate-ADR scan**: filename-derived `ADR-NNNN` collision check across `adr/`.
3. **multi-dir commit detector (advisory)**: scans `main` commits in
   `<Diff Base SHA>..main` (skipping merge commits' combined view via
   `--first-parent -m` file lists per commit) for any commit touching ≥2 distinct
   `openspec/changes/<change>/` dirs; prints advisory findings; NEVER affects exit code.
Exit non-zero iff check 1 or 2 fails. `opsx status` does not run archive-check.

## D3 — B2 tier collapse in the gate

`validate_mode scale` vocabulary becomes `XS S M`; new boolean front-matter key
`full_rigor` (absent ⇒ false; non-boolean ⇒ fail closed). Required-artifact
table becomes a function of (scale, full_rigor):
- XS: review.md only (as today).
- S: + proposal, tasks (as today).
- M: + specs/, intent.md, plan.md, verify/code-review per modes, **doneness.md**;
  clarify.md and analyze.md NOT required.
- M + full_rigor: + clarify.md, analyze.md (the former M/L/XL full set).
Budget defaults (when `loop_max_iterations` absent): XS=10, S=20, M=40,
M+full_rigor=80. L/XL inputs fail closed with the relabel message
("relabel to `scale: M` + `full_rigor: true`").
**Migration wrinkle (this change itself):** this change is gated by the
DEPLOYED (old, 5-tier) gate throughout its life — the new gate only goes live
at post-archive `chezmoi apply`. Its own `scale: XL` therefore stays valid for
its entire lifecycle; the worktree's `tests/opsx-gate` test the NEW gate binary
from the worktree. No in-flight relabel needed.

## D4 — B1 doneness-combined dispatch at plain M

- Gate: at M (no full_rigor), doneness.md remains REQUIRED (unchanged checks:
  presence, verdict, freshness, intent-SHA binding) but its accepted provenance
  set gains `review_mode: blind-single-judge` authored by the DESIGNATED
  doneness reviewer = first entry of the resolved `review` role (clarify A-1).
  At M+full_rigor the independent-judge provenance is required exactly as today.
- Skill (openspec-loop): at plain M the code-review dispatch prompt for the
  designated reviewer carries a mandatory final section — the doneness question
  judged against frozen intent.md + delta ACs — and that reviewer writes
  doneness.md separately from code-review findings. Other reviewers' prompts
  unchanged. At full_rigor: current separate doneness-judge dispatch retained.
- Extension: no change to the doneness ratchet (doneness.md exists at all
  tiers ≥ M); `readDoneness`/`classifyDoneness` untouched.

## D5 — B1 clarify/analyze thinning at plain M

- Gate artifact table per D3 (clarify.md/analyze.md not required at plain M).
- openspec-propose skill: at plain M, clarify questions are authored into
  proposal.md `## Open Questions` and resolved there (same 2-option discipline,
  inline); at full_rigor the standalone blind clarify artifact is required.
- Analyze at plain M = deterministic checks only (tiling/traceability/EARS
  lint) run by the orchestrator inline, recorded in a short analyze section of
  proposal.md or plan.md — no blind dispatch, no analyze.md required.

## D6 — B4 worktree-mode default derivation

Gate + template: when `worktree_mode` is ABSENT from front-matter, derive
XS/S ⇒ `same-tree`, M ⇒ `worktree-required`. An explicit value always wins.
Template ships the derivation comment; extension `resolveWorktree` behavior
unchanged (absent locator + same-tree just means no `--worktree`).

## D7 — B4 model-config project-layer removal

`executable_opsx` opsx_models: delete the project-yaml read; when
`openspec/opsx-models.yaml` exists, print a one-time warning to stderr
("project model layer removed; use review.md front-matter") — warning does not
affect exit codes or stdout contract. JSON `source` enum loses `project`.
Template opsx-models.yaml reworded. Tests updated.

## D8 — B3 consolidation mechanics at archive

`openspec archive` applies the ADDED/REMOVED deltas; the five retired
capability spec files end up empty/removed by the deltas. The archive step
(skill prose) then deletes any now-empty `openspec/specs/<cap>/` dirs and runs
`openspec validate --specs --strict` (must be green) before the archive commit.
No spec-of-record content is hand-migrated — the deltas carry everything.

## D9 — Skill surfaces (Constitution IX: gating multi-model code review)

- openspec-loop SKILL.md: tier vocabulary XS/S/M(+full_rigor); plain-M combined
  doneness dispatch (D4); A2 rule — every integration-checkout commit the loop
  drives uses `git commit -- <paths>` scoped to the change dir; landing prose
  unchanged (loop_hold on integration copy).
- openspec-archive-change: run `opsx archive-check <change>` before
  `openspec archive`; quote its output; refuse on non-zero; delete empty spec
  dirs post-archive (D8).
- openspec-propose + openspec-apply-change reference: tier vocabulary; plain-M
  clarify-in-proposal (D5); locator publication unchanged (ADR-0023).
- goal-loop spec + any goal-extension docs: deprecation note only (no code).

## D10 — Test plan homes

- `tests/opsx-gate`: 3-tier vocabulary, full_rigor artifact matrix, fail-closed
  L/XL + relabel message, worktree-mode derivation, doneness provenance at
  plain M vs full_rigor.
- `tests/opsx-cli`: `opsx status` (fleet block, placeholders, exit-0, no side
  effects), `opsx gate --cheap`, `opsx archive-check` (base currency incl.
  same-tree exemption, ADR-dup, advisory detector).
- `tests/opsx-models`: project layer ignored + warning; enum without `project`.
- Extension bun tests: budget-default keying (XS/S/M/full_rigor); everything
  else behaviorally unchanged (hold/latch/stall untouched).
- `tests/opsx-review-convergence` surface tests: skill prose pins for D4/D5/D9.

## Non-decisions (explicitly out, per intent non-goals)

No locks/flock, no distill nonce, no branch-first/`.opsx-control`, no
in-session multi-loop, no review weakening, no auto-archive/deploy, no
rewriting archived changes.
