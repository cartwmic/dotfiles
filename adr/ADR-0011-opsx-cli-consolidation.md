# ADR-0011: Consolidate opsx CLIs into one `opsx` multitool (hard cutover)

**Status:** Accepted
**Date:** 2026-06-26
**Source change:** `openspec/changes/archive/2026-06-26-consolidate-opsx-cli/`
**Supersedes:** —
**Superseded by:** —

## Context

The opsx-superpowers workflow accreted three sibling bash CLIs one change at a time:
`opsx-gate` (deterministic exit-code gate, ADR-0005), `opsx-models` (harness-neutral role→model
resolver, add-opsx-model-config), and `opsx-loop` (Ralph-style fallback driver, ADR-0007). They
shared concerns — front-matter reading, layered config, `OPSX_*` conventions, error style — but
no code, and there was no single home to add the model-config WRITE surface the user wanted. The
user challenged the proliferation directly ("why a third sibling executable?").

Constitution I (chezmoi is the single source of truth, including removals) and IX (skill edits
require adversarial review) constrain how a destructive rename may ship.

## Decision Drivers

- Reduce surface: one tool, not three, per the user's anti-proliferation intent.
- A harness-neutral WRITE surface (`opsx models set/get/list`) must live with the resolver, not
  in the pi extension (which stays a consumer — ADR-0007 decoupling).
- The delivery form must stay process-invocable by any harness (pi extension spawns it; Codex/
  Claude/bash shell out) — an executable on PATH, not a sourced shell library.

## Decision

1. **One `opsx` dispatcher** (`dot_local/bin/executable_opsx`) with `gate` / `models` / `loop`
   subcommands. Each subcommand body is a **subshell function** `name() ( … )` so `exit`, `set`,
   globals, and `PROG` stay isolated per dispatch; the gate/resolver/loop logic is ported
   near-verbatim. The gate's author-marker check calls the in-file `opsx_models` function rather
   than shelling a separate binary.
2. **Hard cutover, no compatibility shims.** The three standalone executables are `git rm`'d and
   `.chezmoiremove` deletes their deployed targets on `chezmoi apply`. Every in-repo caller
   (canonical skills, schema/templates, pi extensions, tests, the root gates manifest) is migrated
   to the `opsx <subcommand>` form. Verified by a token-level legacy-executable scan over caller
   paths.
3. **`opsx models` gains a write surface** — `set/get/list` with user-layer default, `--layer
   user|project`, atomic temp-then-rename, comment/order preservation via `yq -i`, create-if-
   absent, `author-in-session` boolean coercion. YAML files remain the sole source of truth; the
   surface is an editor, not a new owner. The pi `/opsx-loop models` command is a thin wrapper.
4. **Spec-of-record migration (the D6 sub-decision).** Because the cutover DELETES the executables,
   every behavior capability that named them in normative prose (`opsx-gate-enforcement`,
   `opsx-model-config`, `opsx-workflow-schema`, `opsx-loop-orchestration`, `opsx-skill-integration`)
   received a full-content MODIFIED delta migrating the command-name references to the subcommand
   form, so the archived corpus names only commands that exist. Requirement NAMES (AC-ID keys cited
   by code/tests) were retained verbatim. The rename was scripted with protection of filenames
   (`opsx-gates.yaml`, `opsx-models.yaml`) and capability/identifier names.

## Alternatives Considered

- **git-style libexec** (`opsx` dispatcher + `~/.local/libexec/opsx/{gate,models,loop}`): cleaner
  per-file separation but adds a deployed directory and three more executables — the opposite of
  the consolidation requested. Rejected.
- **Compatibility shims** (`opsx-gate` → `exec opsx gate "$@"`): safer migration but leaves three
  leftover shim files, the exact proliferation being removed. Rejected by the owner.
- **Logical-name spec convention** (leave specs naming "opsx-gate command" + scope the scan): far
  less churn, but leaves the archived corpus asserting removed executables — flagged by both blind
  reviewers as a record defect. Rejected by the owner in favor of full MODIFIED migration.

## Consequences

- **Positive:** one PATH entry, one chezmoi source file, shared conventions, a single home for the
  write surface; spec-of-record stays honest after the rename.
- **Negative / risk:** hard cutover has no shim — any out-of-repo caller (shell alias, stored
  snippet) invoking `opsx-gate`/`opsx-models`/`opsx-loop` breaks on the next `chezmoi apply` across
  machines. Accepted as an explicit owner choice; the managed surface (skills/schema/extension/
  tests) is migrated in the same change.
- A ~740-line single bash file is larger; mitigated by section banners + function prefixes.

## Validation

Two-round pre-impl adversarial review (opus-4-8 + gpt-5.5) + three-round blind post-impl
code-review converged 0 P0 / 0 P1; `opsx gate consolidate-opsx-cli` → GATE-PASS (L); 133 tests
green (72 shell across opsx-models/opsx-gate/author-marker/opsx-cli, 29 opsx-loop helpers, 32 goal).
