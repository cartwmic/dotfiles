# Intent classification release qualification

This directory binds released intent behavior to the exact classification authority published in frozen Explore guidance. It covers all 45 current rule/condition branches: 37 selected-axis branches, three deciding-policy branches, and five holistic branches.

`manifest.json` is the release corpus. Every row names a standalone intent fixture or a controlled decider challenge, selected axis, expected axis verdict and controlling identity, expected final verdict and policy identity, expected selected-axis identity for targeted consensus, and driver-visible or retained-regression status. Full-roster consensus may cite any supplied axis finding or an exact corrected identity. A challenge may declare separate full-roster final expectations when selecting the omitted owning axis changes the deciding policy.

## Deterministic conformance

```sh
python3 tests/intent/check_manifest.py
```

This command makes no model calls. When `SC_BIN` is unset it first rebuilds the candidate provider, then invokes its `describe` role and rejects:

- missing, duplicate, or orphaned executable, guide-index, or manifest identities;
- changes to the accepted 45-branch release anchor;
- authored Explore overview drift or verdict-bearing text in the identifier-only index;
- malformed or path-escaping fixtures, rows, challenge responses, and pairings;
- fixture or challenge content that differs from the independently anchored reviewed corpus digests;
- axis identities owned by another axis or carrying the wrong verdict;
- challenge rosters without exactly one declared response per selected axis.

Distinct paths and hashes preserve reviewed fixture identity; they do not by themselves prove semantic isolation. Full-roster real-model observations prove that every non-controlling axis passes for each live case.

```sh
python3 -m unittest tests/intent/test_harness.py
```

Harness regressions reject duplicate binding records, contradictory embedded consensus evidence, and unsafe controlled-model routing.

`SC_BIN` selects another provider binary. Default is `target/debug/software-change`.

## Live calibration and qualification

Use smoke diagnostics while tuning one or more cases:

```sh
SC_PROFILE=smoke SC_CASE_JOBS=3 SC_GAP=0 \
  sh tests/intent/executable_run.sh pg-001-code-fact pg-002-problem-only
```

Smoke mode makes one targeted observation per selected row, performs no full-roster observation, and reports `diagnostic-pass` or `diagnostic-fail`. It is not release evidence.

Run release qualification once candidate behavior is stable:

```sh
SC_PROFILE=release SC_CASE_JOBS=3 SC_GAP=0 sh tests/intent/executable_run.sh
```

The runner obtains the full graph from the candidate provider and supplies its exact frozen Explore guidance to every ordinary `evaluate_gates` request. Release profile gives each manifest row three fresh targeted observations and one fresh complete-roster observation. Artifact roots are never reused, so a cached failure cannot masquerade as repeated evidence.

Live rows use real configured axis and consensus models. Challenge rows route a reserved synthetic axis model through `judge_wrapper.py`; the wrapper returns only the response declared for that axis and mode, while every consensus-model call is delegated unchanged to the configured real judge command. Routing is based on exact model identity plus prompt shape, never call order. No provider request field or production finding-injection API exists.

Environment:

- `SC_BIN` — candidate provider binary.
- `SC_JUDGE_MODEL` — real live axis model. Default `openai-codex/gpt-5.6-sol`.
- `SC_DECIDER_MODEL` — real consensus model. Default `openai-codex/gpt-5.6-sol`.
- `SC_JUDGE_COMMAND_JSON` — real Pi-compatible command argv as JSON. Default `["pi"]`.
- `SC_JUDGE_EXTENSIONS_JSON` — explicit extension paths as JSON array.
- `SC_JUDGE_EXT` — compatibility shorthand for one extension; empty means none.
- `SC_OUT` — artifact root. Default `$TMPDIR/sc-intent-qualification`.
- `SC_GAP` — seconds between observations. Default `5`.
- `SC_TIMEOUT` — provider and judge budget in seconds. Default `1200`.
- `SC_PROFILE` — `release` for three targeted plus one full-roster observation, or `smoke` for one targeted observation only. Default `release`.
- `SC_CASE_JOBS` — bounded number of cases evaluated concurrently. Default `1`; use `3` with native providers after confirming account rate limits. Bridge providers should normally remain at `1`.
- `SC_MAX_PARALLEL_AXES` — full-roster axis concurrency within each case. Default `1`; serial axis calls avoid bridge timeouts. Peak judge concurrency can reach `SC_CASE_JOBS × SC_MAX_PARALLEL_AXES`.

Named rows may be passed for diagnosis:

```sh
sh tests/intent/executable_run.sh sa-001-product-target dc-category-error
```

A release-profile subset is always reported as `partial` and exits nonzero. Smoke diagnostics may pass, but never count as qualification. Targeted evidence never substitutes for full-roster evidence, and a release challenge cannot qualify unless its paired organic live row also qualifies.

## Results and reasons

Qualification exits zero only when every driver-visible and regression row has three consecutive targeted matches and one determinate all-axis match, with no mismatch or indeterminate observation. Model or bridge indeterminacy is recorded separately from semantic mismatch; both disqualify.

Default artifacts:

- `$SC_OUT/run.json` — release qualification report.
- `$SC_OUT/provider-graph.json` — candidate `describe` reply and frozen guidance.
- `$SC_OUT/raw/<case>/<mode>-<attempt>/response.json` — raw provider evidence.
- `$SC_OUT/raw/<case>/<mode>-<attempt>/stderr.txt` — provider and bridge diagnostics.
- `$SC_OUT/raw/<case>/<mode>-<attempt>/routes.jsonl` — challenge interception/delegation proof.
- `$SC_OUT/observations/...` — normalized verdicts, identities, models, rubric set, reasons, and classification.

Inspect all raw reasons:

```sh
python3 tests/intent/report.py show --reasons "$SC_OUT/run.json"
```

Exact executable branches remain the semantic contract. This matrix measures whether candidate models and bridge behavior adhere to that contract; finite calibration evidence does not replace it.
