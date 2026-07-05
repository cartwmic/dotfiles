# Code Review

<!--
Filled from the shipped template
~/.local/share/openspec/schemas/opsx-superpowers/templates/code-review.md.
Orchestrator-sealed from blind reviewer findings files
(/tmp/hrdi-cr-r{1,2,3}-{opus,sonnet}.md). Every round: blind, fresh-context,
2 models, attestation preamble verified, pre/post round snapshots clean.
-->

**Change:** harden-opsx-reviewer-dispatch-integrity
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** pi-subagents delegate — claude-bridge/claude-opus-4-8 + claude-bridge/claude-sonnet-5 (blind, per-round fresh context)
**Diff Base SHA:** ff5a8606923247f37f0af87c691cc90b989aa25a
**Reviewed Range:** ff5a8606923247f37f0af87c691cc90b989aa25a..555da54cb309c716b29a6f0fd7c529a42f247061
**Attested HEAD:** 555da54cb309c716b29a6f0fd7c529a42f247061
**Baseline:** intent.md (frozen, sha256 1137f1ec02e548020688a6e14ade7b470ad033660a00560e5a0c0e4244e97410) + proposal + clarify + 3 delta specs + plan + tasks status
**Generated:** 2026-07-05

## Round tracker

| Round | Mode | P0 | P1 | P2 | P3 | Reviewer verdicts | Reviewed HEAD |
|---|---|---|---|---|---|---|---|
| 1 | blind | 1 | 1 | 0 | 2 | opus:fail sonnet:fail | 1194f0c1be25d510f4f891fbb7bacf2c8138e3dd |
| 2 | blind | 0 | 0 | 0 | 2 | opus:pass sonnet:pass | 7d2330b129109a68986aa0b60f3e648be2b24225 |
| 3 | blind | 0 | 0 | 0 | 2 | opus:pass sonnet:pass | 90f7383d16709754e7e92235c3e20d4c8e10d5e7 |
| 4 | blind (confirm; range re-attested after sibling-intent commits staled the 90f7383 seal) | 0 | 0 | 0 | 3 | opus:pass sonnet:pass | 555da54cb309c716b29a6f0fd7c529a42f247061 |

Attestations: all six reviewer dispatches attested the exact dispatched HEAD +
toplevel; zero INVALID verdicts; pre/post round snapshots identical every round
(read-only contract held).

## Findings resolution

- **R1 (both reviewers, same root): doneness Attested HEAD bound live
  IMPL_HEAD** — self-staled on the doneness-only sealing commit the freshness
  allowlist exists to tolerate; would have blocked archive of every full_rigor
  change. Fixed: bind the artifact's recorded Reviewed Range head (mirrors the
  code-review binding; freshness owns recorded-head→HEAD). d-fr-seal
  trailing-commit regression added (gate 141). Commits 5d43d3b, 59ea8e1.
- **R2 P3 ×2** — doneness template wording (implementation HEAD → recorded
  range head) and stale suite-count note: both fixed pre-seal (e70c49b).
- **R3 quiet.** Rounds 1→3 converged 2→0 P0/P1 with fixes landing between
  rounds (quiet-round protocol, zero human rulings).

## Warnings (open P2/P3 — advisory, recorded per contract, never a fix round)

- [P3] executable_opsx attestation equality resolves the recorded range head
  with plain `rev-parse` (echoes nonexistent 40-hex verbatim); forged
  range+attestation pairs are rejected by the always-co-gated freshness
  ancestor/base checks, so no gate-passable path exists. Optional hardening:
  `rev-parse --verify "<head>^{commit}"` for self-sufficiency. (R3 opus)
- [P3] 40-hex regex rejects upper-case hex; `git rev-parse` emits lower-case
  only, so verbatim attestations always match — fail-closed direction correct.
  (R3 opus)

## Validators (round 4 head)

bash -n clean; opsx-gate 141/0; review-convergence 168/0; opsx-cli 67/0;
opsx-models 34/0; author-marker 4/0; bun opsx-loop 60/0;
openspec validate --strict valid (change) and 12/12 (specs).
