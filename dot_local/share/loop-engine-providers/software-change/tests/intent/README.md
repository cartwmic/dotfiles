# Intent classification conformance and calibration

This directory preserves the complete 45-branch intent corpus while separating reproducible phase checks from bounded live-model evidence.

## Three evidence surfaces

1. **Deterministic conformance** validates executable branches, frozen Explore publication, manifest identities, fixtures, challenges, and the fixed release cohort. It makes no judge calls.
2. **Release-core qualification** observes the twelve user-visible pass/fail contrasts three times each. Two expected verdicts qualify a case; all three observations remain evidence.
3. **Extended characterization** observes any selected cases, or all 45 cases, once. It reports behavior but never claims release qualification.

Production intent rubrics, consensus behavior, frozen-rubric enforcement, and non-intent semantic subjects are outside this harness change.

## Deterministic phase checks

```sh
python3 tests/intent/check_manifest.py
python3 tests/intent/test_harness.py
python3 -m py_compile tests/intent/*.py
sh -n tests/intent/executable_run.sh
```

`check_manifest.py` rebuilds the candidate provider when `SC_BIN` is unset, invokes `describe`, and rejects before live dispatch:

- missing, duplicate, malformed, or orphaned executable, guide-index, or manifest identities;
- changes to the accepted 45-branch inventory;
- authored Explore overview drift or verdict-bearing index prose;
- malformed or path-escaping fixtures, challenges, responses, and pairings;
- fixture or challenge bytes outside the reviewed digest anchors;
- cross-axis identity ownership or verdict disagreement;
- any change to the fixed six ordered release-core pass/fail pairs.

These checks belong in phase checkpoints. They require no network judge access.

## Fixed release-core cohort

`manifest.json.release_core_cases` contains twelve live fixtures:

| Boundary | Pass | Fail |
|---|---|---|
| Product target / implementation location | `sa-001-product-target` | `sa-001-implementation-location` |
| Observable behavior / internal mechanism | `sa-002-observable-behavior` | `sa-002-internal-mechanism` |
| Public contract / incidental channel | `sa-003-public-contract` | `sa-003-incidental-channel` |
| Finished release property / work instruction | `ov-001-release-property` | `ov-001-work-instruction` |
| Externally imposed mechanism / unsourced preference | `sa-002-externally-imposed-mechanism` | `cl-002-solution-preference` |
| Closed / open empty scope | `sf-001-closed-empty-scope` | `sf-001-open-empty-scope` |

Run one complete qualification into a new artifact root:

```sh
SC_PROFILE=release-core \
SC_OUT=/tmp/sc-intent-release-core-1 \
SC_FIDELITY_ATTESTATION=tests/intent/evidence/fidelity-attestation.json \
SC_CASE_JOBS=3 \
SC_GAP=0 \
sh tests/intent/executable_run.sh
```

Release-core accepts no case arguments. It produces exactly three targeted observations for each fixed case and no full-roster observations. Each case qualifies when at least two observations return the expected selected-axis and final verdicts.

All 36 observations stay in one evidence set. One disagreement or indeterminate result remains visible and cannot be replaced by a case-only rerun. Two disagreements fail that case. Missing attempts, duplicate records, mixed candidate or rubric identities, cross-run evidence, or partial cohorts fail the report.

Release qualification also requires a machine-readable independent fidelity attestation. Its six ordered mappings must exactly cover the fixed cohort, every mapping and source review must be supported, and provenance must be independent of rubric, manifest, checker, and live-observation authorship. The attestation is embedded in the report and protected by a canonical digest. `evidence/release-core-report.json` retains the complete reviewable 36-observation release evidence, including raw provider responses. `evidence/release-evidence.json` records its digest, identities, counts, and independent review provenance.

Verify a saved report without judge access:

```sh
python3 tests/intent/report.py verify-release \
  /tmp/sc-intent-release-core-1/run.json
```

## Observation classifications

Every normalized observation has one classification:

- `match` — expected verdicts and exact expected identities;
- `classification_variance` — expected passing verdict, but another declared passing condition owned by the selected axis; counts toward the verdict majority and remains separately reported;
- `verdict_mismatch` — selected-axis or final verdict differs from the protected expectation;
- `indeterminate` — malformed, missing, unknown, contradictory, replayed, misrouted, or unavailable evidence prevents a trustworthy classification.

Only `match` and `classification_variance` count as expected verdicts. Alternate failing identities never receive equivalence credit. Controlled decider challenges retain exact identity and route checks because category correction and defect non-waiver depend on those policies.

## Extended characterization

Observe selected cases once:

```sh
SC_PROFILE=characterization \
SC_OUT=/tmp/sc-intent-characterization-pg \
SC_CASE_JOBS=3 \
SC_GAP=0 \
sh tests/intent/executable_run.sh \
  pg-001-code-fact pg-002-problem-only
```

Observe all 45 branches once by omitting case arguments. Characterization reports `characterization-complete` when every requested observation is retained, even when it contains verdict alerts. Its report always has `release_qualified: false`.

## Immutable artifact ownership

`SC_OUT` must not exist. The runner rejects an existing path instead of deleting or reusing it. Every invocation creates:

- a random `evidence_set_id`;
- a SHA-256 candidate-binary identity;
- one frozen rubric-set identity;
- normalized observations carrying all three identities;
- raw provider responses, stderr, requests, and challenge routes.

A release report cannot combine observations with another evidence-set, candidate, or rubric identity. Do not merge later passing samples into an earlier report. A new run is new evidence, not a correction of old evidence.

## Environment

- `SC_PROFILE` — `characterization` (default) or `release-core`.
- `SC_OUT` — absent destination directory. Default: `$TMPDIR/sc-intent-characterization`.
- `SC_FIDELITY_ATTESTATION` — required readable JSON attestation for `release-core`; unused by characterization.
- `SC_BIN` — candidate provider binary; unset rebuilds `target/debug/software-change`.
- `SC_JUDGE_MODEL` — live axis model; default `openai-codex/gpt-5.6-sol`.
- `SC_DECIDER_MODEL` — consensus model; default `openai-codex/gpt-5.6-sol`.
- `SC_JUDGE_COMMAND_JSON` — Pi-compatible judge command argv; default `["pi"]`.
- `SC_JUDGE_EXTENSIONS_JSON` — explicit extension paths as JSON array.
- `SC_JUDGE_EXT` — compatibility shorthand for one extension.
- `SC_CASE_JOBS` — bounded concurrent cases; default `1`. Native providers may use `3`; bridge providers should normally use `1`.
- `SC_MAX_PARALLEL_AXES` — selected-axis concurrency inside a case; default `1`.
- `SC_GAP` — seconds between observations; default `5`.
- `SC_TIMEOUT` — provider and judge budget; default `1200` seconds.

Inspect evidence:

```sh
python3 tests/intent/report.py show --reasons "$SC_OUT/run.json"
```

Report schema version 2 replaces old `semantic_mismatch`, `diagnostic-pass`, `partial`, and perfect-streak release statuses. Consumers must use `classification`, `release_qualified`, and `qualification` from schema v2.
