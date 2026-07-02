# Code Review

**Change:** add-opsx-doneness-judge
**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** blind subagents claude-bridge/claude-opus-4-8 + openai-codex/gpt-5.5 (4 rounds), dispatched via pi-subagents
**Diff Base SHA:** 30d6d7917b5b342c7ab89d1138ccecae41a9c58d
**Reviewed Range:** 30d6d7917b5b342c7ab89d1138ccecae41a9c58d..1e1e4f295ebea43dd76b224091ec4218bc55cbea

## Summary

Blind multi-model post-implementation review (Constitution IX — this change edits the
`openspec-loop` skill). Two independent reviewers (opus-4-8 + gpt-5.5), each running all
suites independently, over four convergence rounds.

- **Round 1:** opus PASS (1 P2); gpt FAIL (1 P1 + 1 P2).
- **Round 2:** opus PASS (0/0/0); gpt FAIL (0 P0/0 P1, 1 P2).
- **Round 3:** opus PASS (0/0/0); gpt FAIL (0 P0/0 P1, 2 P2).
- **Round 4:** **opus PASS (0/0/1); gpt PASS (0/0/1)** — converged, 0 P0 / 0 P1 both.

## Findings resolved

- **P1 (gpt R1) — provenance review_mode absence accepted.** The gate failed only a
  literal `degraded-single-model`; a satisfied doneness.md with no `review_mode` passed.
  **Fixed:** the gate now fails a missing OR degraded `review_mode` (`dmode` check) with a
  gate test deleting the field.
- **P2 (gpt R1) — stale doneness emitted under `doneness-stale`.** Split the doneness
  check id and defeated the extension's `key=='doneness'` stall routing. **Fixed:**
  `freshness_check "$DONE" doneness`; a satisfied-but-stale verdict now correctly re-routes
  to the ordinary content/HEAD signal via `classifyDoneness`.
- **P2 (gpt R2) — content-less block-scalar waiver bypass.** `doneness_waiver_rationale: >`
  with no content read as `>` (non-empty) → bare waiver bypass. **Fixed:**
  `waiver_has_rationale()` requires real content; this change's own review.md hardened to
  an inline rationale.
- **P2 (gpt R3) — comment-only / quoted-whitespace / `>`-with-trailing-comment waiver
  bypasses.** **Fixed:** the reader unwraps quotes, strips inline/whole-line YAML comments,
  trims, and only enters block-scalar mode for a bare `>`/`|` marker.

## Findings accepted (non-blocking P2, both reviewers PASS)

- **Waiver rationale reader is a lightweight text reader, not a full YAML interpreter**
  (opus R4 P2 / gpt R4 P2). A few adversarial YAML-semantic edge values could still be
  accepted as content. Accepted: the `doneness_waiver_rationale` is a **self-attested**
  waiver written by the change owner (same tripwire posture as the accepted in-session
  authoring marker — a same-UID actor who wants to bypass their own waiver always can);
  all common/accidental empty forms are now rejected. Full YAML fidelity would require a
  new `yq` dependency in the gate (Constitution V — no new dev-tool install) for no
  meaningful threat-model gain.

## Suites (independently run by both reviewers, green)

- `test_opsx_gate.sh`: 52 passed / 0 failed
- `test_author_marker.sh`: 4 passed / 0 failed
- extension `helpers.test.ts`: 45 passed / 0 failed
- `bash -n dot_local/bin/executable_opsx`: clean
- `bun build index.ts --target node`: clean
- `openspec validate add-opsx-doneness-judge --strict`: valid
