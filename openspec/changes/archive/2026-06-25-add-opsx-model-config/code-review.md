# Code Review — add-opsx-model-config

**Verdict:** pass
**review_mode:** adversarial-multimodel
**reviewer-provenance:** claude-bridge/claude-opus-4-8 (blind) + deepseek/deepseek-v4-pro (blind), independent post-impl review over the diff; each ran all four verification suites
**Diff Base SHA:** a7d19e5abcd9ec8787eab197adc3aeb8fe6e2e01
**Reviewed Range:** a7d19e5abcd9ec8787eab197adc3aeb8fe6e2e01..f21ae21f9321610c7843d57a8bc4aced1fa8b489

<!--
Authored by assembling two BLIND post-implementation review subagents (Constitution IX:
this change edits existing skills, so the review is adversarial-multimodel — two distinct
models/providers; a degraded-single-model verdict would not satisfy the gate). Neither
reviewer self-authored the final verdict line; the orchestrator assembled their independent
verdicts with provenance. Both ran the suites themselves (no trust in claims).
-->

## Outcome

Both reviewers: **PASS**, 0 P0, 0 P1.

| Reviewer | Model | Verdict | P0 | P1 | P2 |
|---|---|---|---|---|---|
| A | claude-bridge/claude-opus-4-8 | PASS | 0 | 0 | 3 |
| B | deepseek/deepseek-v4-pro | PASS | 0 | 0 | 4 |

## Independent verification (both reviewers ran these)

| Suite | Result |
|---|---|
| tests/opsx-models/test_opsx_models.sh | 25 passed, 0 failed |
| tests/opsx-gate/test_opsx_gate.sh | 26 passed, 0 failed |
| tests/opsx-gate/test_author_marker.sh | 4 passed, 0 failed |
| opsx-loop `bun test helpers.test.ts` | 21 pass, 0 fail |

## What was confirmed correct

- **Provider rules:** slash-value verbatim (incl. multi-segment openrouter id); bare id qualified by role provider then default provider; review list entries qualified independently; role provider beats default. Verified by direct invocation, not just bundled tests.
- **Layering:** env > change front-matter > project > user > default; empty env = unset; highest layer fully REPLACES the review list (no union); invalid root exits non-zero; missing change falls through.
- **author-in-session boolean:** default true; env/front-matter/project false all correct; source-aware JSON uses a real boolean (`--argjson`).
- **Gate marker check (bootstrap-safety):** author configured + missing marker → fail; configured + marker → pass; **author UNCONFIGURED → SKIPPED** (this change's own review.md leaves model fields unset, so it does not self-brick); author_in_session false → skipped; resolver/jq absent → skipped. Enumerated scan set matches the spec.
- **De-scope cleanliness:** NO run-history / model-provenance enforcement added (`grep` over resolver/gate/extension hits only the pre-existing unrelated `reviewer-provenance` field). Matches design D3.
- **Shell safety:** no `eval`; keys hard-coded (never user input); `$CHANGE`/paths quoted; front-matter via mktemp + rm; globals avoid command-substitution source loss. No injection surface.
- **Extension consumer:** `spawnSync` 5s timeout; resolver-absent → vars unset (pre-change behavior); only genuinely-configured roles exported; malformed JSON swallowed.

## Findings (all P2 — non-blocking, accepted)

Not fixed in this apply: editing code/design post-review would stale the verdict range; all are cosmetic/doc/optional with no functional impact. Recorded for follow-up:

- **A-P2-1** gate marker glob `specs/*/spec.md` is single-level vs spec wording `specs/**` — correct for OpenSpec's single-level layout; switch to `find` only if nested capability dirs are ever allowed.
- **A-P2-2 / B-P2** `review --with-default` emits scalar `"session"` not a list — harmless (every consumer ignores `source:default`).
- **A-P2-3** design.md Migration step 5 mentions exporting `OPSX_*_PROVIDER`; the extension exports the 4 vars actually specified (model values are already provider-qualified, so a separate provider env is unnecessary) — doc/impl drift, not a defect.
- **B-P2** `extract_fm` awk doesn't parse YAML block scalars containing a leading `---`; adequate for the simple key/value front-matter the schema enforces (graceful fallthrough otherwise).
- **B-P2** no explicit test for the resolver-absent gate-skip path (behavior is straightforward; condition is the `[ -n "$MODELS_BIN" ]` guard).
- **B-P2** a mistyped bare boolean `author_model: false` would resolve to the string `"false"`; document that model/provider keys must be strings.
- **B-P2** `buildModelEnv`'s `configured` guard also excludes `source:default` (intentional; comment documents it) — consider a clearer name.

## Conclusion

Implementation matches the specs; resolver layering + provider rules correct; gate marker check fails-configured / skips-unconfigured (bootstrap-safe); run-history provenance cleanly absent; no injection/quoting defects; all suites pass independently under two distinct models. **PASS.**
