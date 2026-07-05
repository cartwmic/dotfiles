# Proposal: harden-opsx-repo-portability

<!-- authored: in-session -->

## Why

The opsx toolchain breaks outside this repo's shape: a repo whose default
branch is not `main` fails archive base-currency (the check hardcodes
`main`), and repos missing `openspec/constitution.md` / `openspec/domain.md`
run the autonomous loop with a blind-review baseline that silently doesn't
exist (the propose skill's interactive A/B/C prompt is the only enforcement,
and the loop never pauses there). Both violate the gate's fail-closed
posture (Constitution: deterministic gate as arbiter).

## What Changes

- Add one deterministic integration-branch resolver helper to
  `dot_local/bin/executable_opsx`; resolution order (first hit wins):
  committed review.md `**Integration Branch:**` field → `git symbolic-ref
  refs/remotes/origin/HEAD` → local `main` → local `master` → loud named
  failure. No config-file override key (intent D1).
- Route all three functional `main` hardcodes through the helper: `opsx
  status` Diff-Base staleness, `archive-check` base-currency, duplicate-ADR
  first-parent scan (intent D2). Messages name the resolved branch.
- review.md template's `**Integration Branch:**` default becomes
  capture-time detected (resolver steps 2-4), not the literal `main`.
- **NEW gate check (fail-closed, every Scale)**: `openspec/constitution.md`
  and `openspec/domain.md` must both exist non-empty in the integration
  checkout; failure directive names `constitution-template.md` /
  `domain-template.md` as the scaffolding remedy (intent D3/D4). No
  auto-scaffold, no waiver key.
- Prose surfaces that assert `main` as the integration branch updated to
  resolved-branch language where they describe these checks.
- Tests: resolver order (field/origin-HEAD/master-only/fail-loud), non-main
  base-currency pass/fail, preflight red per missing artifact + green.

Not breaking: this repo resolves to `main` (behavior unchanged); the
preflight is green here (both artifacts exist).

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `opsx-cli`: new requirement — deterministic integration-branch resolution
  (order, loud failure); `Status Fleet View` staleness computed against the
  resolved branch.
- `opsx-gate-enforcement`: `Land Base Currency` restated against the
  resolved integration branch (merge-base vs resolved-branch HEAD, remedy
  names the branch); duplicate ADR scan restated likewise; new requirement —
  project-artifact preflight (constitution.md + domain.md, fail-closed at
  every Scale, template-naming remedy).
- `opsx-workflow-schema`: review.md template `Integration Branch` locator
  default is capture-time detected, never a hardcoded literal.

## Impact

Affected files:
- `dot_local/bin/executable_opsx` — resolver helper; status ~1315/1364-1370,
  archive-check ~1414-1427, dup-ADR scan ~1452-1464; new gate check.
- `dot_local/share/openspec/schemas/opsx-superpowers/templates/review.md` —
  locator default comment/value.
- Skill/schema prose surfaces asserting literal `main` for these checks
  (audit at apply; intent keeps opsx-loop extension out of scope — it has
  zero `main` references).
- `tests/opsx-cli/test_opsx_cli.sh`, `tests/opsx-gate/test_opsx_gate.sh` —
  new cases.

Affects which projects: every repo consuming opsx via chezmoi apply;
enables non-`main`-default repos and repos bootstrapping without
constitution/domain (they now get a red gate + remedy instead of a silent
run).

## Open Questions

(none — Scale S; ambiguity-pass clarify runs after specs)
