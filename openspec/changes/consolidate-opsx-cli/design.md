<!-- authored: in-session -->
## Context

Three sibling bash CLIs — `opsx-gate` (322 lines), `opsx-models` (230), `opsx-loop` (56) —
deploy from `dot_local/bin/executable_opsx-*` to `~/.local/bin/`. They share concerns
(front-matter reading, layered config, `OPSX_*` conventions, error style) but no code. The
opsx-loop pi extension (`dot_pi/agent/extensions/opsx-loop/`) and the canonical skills
invoke them by name. This change folds the three into one `opsx` multitool (hard cutover),
adds a model-config write surface, and fixes three opsx-loop correctness bugs.

Constitution I (chezmoi is source of truth — the new binary + removals must be expressed in
source), II (canonical skills carry the renamed invocations), VIII (`openspec/` not
deployed), IX (skill edits → adversarial-multimodel review). Domain invariant 8 (`bin/`
gitignore needs allowlist — already satisfied for `dot_local/bin/`).

## Goals / Non-Goals

**Goals:**
- One executable `opsx` with `gate` / `models` / `loop` subcommands; legacy names removed.
- Harness-neutral `opsx models set/get/list` write surface (user layer default), atomic +
  comment-preserving.
- pi `/opsx-loop models` thin wrapper over `opsx models`.
- Fix arg truncation, worktree staleness, and add stall detection in the opsx-loop extension.
- Every in-repo caller migrated; old binaries removed from the deployed home.

**Non-Goals:**
- No compatibility shims for legacy names (hard cutover — explicit user choice).
- No list-mutation grammar for `set review` (replace-only; manual YAML for lists — A1).
- No new config knob for the stall threshold (constant default 3 — A3).
- No rewrite of historical ADRs 0005-0010 (a new ADR records the consolidation).
- The loop still stops at gate-green (it does not auto-archive — unchanged).

## Decisions

### D1: Single-file `opsx` dispatcher (not a libexec multi-script layout)

**Choice:** One `dot_local/bin/executable_opsx` containing a `case "$1"` dispatcher plus the
three subcommand bodies as clearly-sectioned, prefix-namespaced functions (`gate_*`,
`models_*`, `loop_*`), each subcommand's existing logic moved in near-verbatim.

**Implementation guardrails (bash side-effects — per review):** each legacy body becomes a
function that RETURNS a status; top-level `exit` calls inside the old scripts become
`return` (only the dispatcher boundary exits). Globals are localized or prefixed per
subcommand to prevent leakage between dispatches. `usage`/`PROG` become subcommand-specific.
The gate's internal model resolution (which used to shell `opsx-models`) calls the in-file
`models_*` function (or `opsx models`) — no self-exec of the old name. `bash -n` plus ALL
existing gate + models test suites run against `dot_local/bin/executable_opsx <subcommand>`.

**Alternatives considered:**
- **git-style libexec** (`opsx` dispatcher + `~/.local/libexec/opsx/{gate,models,loop}`):
  cleaner per-file separation, but adds a deployed directory, path-resolution logic, and
  three more executables — the opposite of the consolidation the user asked for.
- **Keep three scripts, add a thin `opsx` wrapper that execs them**: leaves the
  proliferation in place (just adds a 4th file). Rejected — contradicts hard cutover.

**Rationale:** the user's intent is *fewer* artifacts and one tool. A single file is the
most literal consolidation, one PATH entry, one chezmoi source file, atomic deploy.
Function-prefix discipline + section banners keep a ~640-line script navigable; the logic is
already factored into functions in the source scripts.

**4-point test:** multiple approaches ✓, lasting ✓, reasonable disagreement ✓ (libexec is a
defensible idiom), constrains future structure ✓ → **ADR candidate: YES** (records
consolidation + single-file choice; supersedes the implicit one-script-per-tool pattern).

### D2: Hard cutover with explicit `.chezmoiremove` for the old targets

**Choice:** Within the worktree: write `executable_opsx`, migrate all callers, `git rm` the
three `executable_opsx-*` source files in one change. Add a `.chezmoiremove` listing
`.local/bin/opsx-gate`, `.local/bin/opsx-models`, `.local/bin/opsx-loop` so `chezmoi apply`
deletes the now-orphaned deployed binaries (chezmoi does NOT auto-remove targets when a
source file is deleted).

**Alternatives considered:**
- **Manual `rm ~/.local/bin/opsx-*` at deploy**: works once but is not reproducible on other
  machines — violates Constitution I. Rejected.
- **Leave old binaries deployed**: they would shadow/confuse; callers already migrated.
  Rejected.

**Rationale:** `.chezmoiremove` is the chezmoi-native, cross-machine-reproducible removal
mechanism — keeps source the single truth (Constitution I).

**4-point test:** lasting ✓ but low disagreement → folded into the D1 ADR, not its own.

### D3: `opsx models` write surface — yq -i, replace semantics, create-if-absent, atomic

**Choice:** `set <role> <model> [--layer user|project]` writes via `yq -i '.<role> =
strenv(VAL)' <file>` (mikefarah yq preserves comments + key order), writing to a temp file
then `mv` into place (atomic). Creates the target file (and `~/.config/opsx/` for the user
layer) if absent. `set` is replace-only (scalar) per A1. `get <role>` mirrors the resolver's
read semantics (empty stdout + exit 0 when unset — C2). `list` prints each role's resolved
value + source layer. Invalid role/layer → error, no write.

**Rationale:** reuses the yq already required (no new dep); atomic temp+rename is trivial in
bash and prevents corruption; replace-only keeps the editor simple (lists stay manual).

**4-point test:** low disagreement, implementation detail → not an ADR.

### D4: pi `/opsx-loop models` is a thin pass-through

**Choice:** the extension routes `models <args>` to `spawnSync("opsx", ["models", ...args])`
and returns stdout/stderr. Bare `/opsx-loop models` → `opsx models list` (C1). No config
logic in the extension — it stays a consumer (matches the existing export-only contract).

**4-point test:** not an ADR.

### D5: Stall detection + worktree re-resolution live in `LoopState`/`agent_end`

**Choice:** add `lastReason`/`stallCount` tracking in the extension's loop state; on each
`agent_end`, after computing the verdict, if `reason === lastReason` increment, else reset;
at `>= 3` stop+preserve+notify. Re-read `Worktree Path` from `review.md` each `agent_end`
(not just at kickoff) and use it for the gate call. Parser reworked to route leading
keywords (`status`/`clear`/`models`) with full remaining tokens, else first token = change
name with a surfaced "ignored extra tokens" note.

**4-point test:** bug-fix behavior; not an ADR (but specced).

### D6: Spec-of-record migration via MODIFIED deltas; requirement NAMES retained as AC-ID keys

**Choice:** Because the hard cutover DELETES the standalone executables, every behavior
capability that names them in normative prose (`opsx-gate-enforcement`, `opsx-model-config`,
`opsx-workflow-schema`, `opsx-loop-orchestration`, `opsx-skill-integration`) gets a MODIFIED
delta migrating `opsx-gate`→`opsx gate` / `opsx-models`→`opsx models` (full requirement
content restated). Requirement NAMES are retained verbatim — e.g. `opsx-gate is the
deterministic judge` — because their canonical AC-ID slugs (`opsx-loop-kickoff.opsx-gate-is-
the-deterministic-judge`) are cited in extension code/tests; renaming would break the
AC↔test mapping the verify gate checks. The token-substitution is scripted with protection
of filenames (`opsx-gates.yaml`, `opsx-models.yaml`) and capability/identifier names to
avoid corruption.

**Alternatives considered:**
- **Logical-name convention + scoped scan** (leave specs saying “opsx-gate command”): far
  less churn, but leaves the archived corpus asserting removed executables — both reviewers
  flagged it as a record defect. Rejected by owner.

**Rationale:** keeps the spec-of-record honest after a destructive rename while preserving
the AC↔test traceability the gate enforces.

**4-point test:** lasting ✓, disagreement ✓ → noted in the D1 consolidation ADR (not its own).

## Risks / Trade-offs

| # | Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|---|
| R1 | A caller is missed in the rename → broken invocation | Medium | High | Hard-cutover AC: repo scan for legacy tokens in verify; gate self-tests + extension transpile |
| R2 | `.chezmoiremove` deletes the wrong path | Low | High | List exact `.local/bin/opsx-{gate,models,loop}` only; `chezmoi diff` reviewed before apply |
| R3 | Merging 3 scripts introduces a regression in gate/resolver logic | Medium | High | Port logic near-verbatim into prefixed functions; re-run all existing gate+models test suites against `opsx gate`/`opsx models` |
| R4 | `yq -i` reformats/strips comments on some YAML shapes | Low | Medium | Comment-preservation test in `tests/opsx-cli/`; temp+rename keeps original intact on failure |
| R5 | Big single bash file harder to maintain | Medium | Low | Section banners + function prefixes; accepted trade-off for consolidation |
| R6 | Hard cutover breaks out-of-repo callers (aliases, snippets) cross-machine, no shim | Medium | Medium | Explicit owner choice; documented in Migration Plan; `apply_harness_config.sh` + skills migrated in same change so the managed surface is consistent |
| R7 | `set review` silently shrinks the multi-model review list | Medium | Medium | AC requires a replace-warning showing the prior list; list authoring stays manual |

## Migration Plan

1. Pre-flight commit (propose artifacts), create worktree `opsx/consolidate-opsx-cli`,
   record Diff Base SHA + Worktree Path in review.md.
2. Build `executable_opsx` (port gate→`gate_*`, models→`models_*`, loop→`loop_*`, add
   `models set/get/list`). `git rm` the three old source scripts. Add `.chezmoiremove`.
3. Migrate callers: extension spawn calls + new `/opsx-loop models` + parser/worktree/stall;
   canonical skills + schema/templates (`opsx-gate`→`opsx gate`, etc.); tests retargeted +
   new `tests/opsx-cli/`.
4. Verify (all suites green, transpile, shell syntax, repo legacy-token scan), blind
   multi-model code-review (Constitution IX), `opsx gate consolidate-opsx-cli --worktree`.
5. Archive ff-merge → main; `chezmoi apply` (materializes `opsx`, removes old via
   `.chezmoiremove`); `apply_harness_config.sh` re-links skills. Promote D1 ADR.

**Rollback:** revert the merge commit; `chezmoi apply` restores the three executables (their
source returns). NOTE: after revert, `executable_opsx` leaves source and `.chezmoiremove` no
longer lists `~/.local/bin/opsx`, so chezmoi will NOT auto-remove the deployed `opsx` —
rollback MUST also `rm ~/.local/bin/opsx` (or temporarily add it to `.chezmoiremove`), the
same orphan-asymmetry the forward path fixes for the old names.

**`opsx loop` consumer:** the folded Ralph bash driver (`opsx loop`) is the harness-neutral
fallback continuation mechanism (ADR-0007) used by non-pi harnesses (claude/codex) and
manual shell runs; the pi extension does NOT call it (pi drives the loop in-process and
spawns `opsx gate`/`opsx models` directly). It is retained for that cross-harness fallback.

**Hard-cutover blast radius:** `.chezmoiremove` deletes the old names on every machine's next
apply with no shim; any out-of-repo caller (shell aliases, stored snippets) breaks. Accepted
per the explicit hard-cutover choice; called out here so it is not a surprise (R-new).

**Migration inventory (exhaustive, classify-then-act):** run
`rg -l 'opsx-gate|opsx-models|opsx-loop' --glob '!openspec/changes/archive' .` and classify
EVERY hit as migrate (caller), exempt (capability name / filename / pi-extension dir /
slash-command / spec-of-record handled by delta / adr history), or remove (the three source
scripts). The exact verify scan is scoped to caller paths (see opsx-cli Hard Cutover AC).

**Exact verification commands (Scale-L):**
```
bash -n dot_local/bin/executable_opsx
tests/opsx-gate/test_opsx_gate.sh           # retargeted to `opsx gate`
tests/opsx-gate/test_author_marker.sh
tests/opsx-models/test_opsx_models.sh       # retargeted to `opsx models`
tests/opsx-cli/test_opsx_cli.sh             # dispatch + write surface (new)
cd dot_pi/agent/extensions/opsx-loop && bun test helpers.test.ts && bun build index.ts --target node --outfile /dev/null
# token-level legacy-executable scan (caller paths only). Match bare command tokens, then
# drop exempt identifiers, so an exempt name co-located on a line cannot mask a real stale
# invocation (per review). Covers opsx-gate, opsx-models AND the opsx-loop bash driver;
# exempts capability names, config filenames, the pi-extension dir + /opsx-loop slash cmd.
rg -oN --no-filename 'opsx-(gate|models|loop)[A-Za-z0-9._-]*' dot_local/share dot_pi tests docs openspec/opsx-gates.yaml \
  | sed 's/[.,:);]*$//' | sort -u \
  | rg -v 'opsx-gate-enforcement|opsx-model-config|opsx-gates\.yaml|opsx-models\.yaml|opsx-loop-(orchestration|kickoff)|opsx-skill-integration|opsx-workflow-schema|opsx-post-impl-review' \
  | rg -v '^opsx-loop$'   # bare 'opsx-loop' = the pi extension dir + /opsx-loop slash command (not an executable); expect: empty
openspec validate consolidate-opsx-cli --type change --strict
chezmoi diff   # confirm old binaries removed, opsx added
opsx gate consolidate-opsx-cli --worktree <path>
```

## Open Questions

None blocking. (Stall threshold default 3 and replace-only `set` are resolved in clarify.)
