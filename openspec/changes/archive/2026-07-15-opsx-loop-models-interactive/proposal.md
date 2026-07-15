<!-- authored: in-session -->
# Proposal — opsx-loop-models-interactive

## Why

`/opsx-loop models set` cannot reuse shell interactive `opsx models set` (no
TTY handoff via `pi.exec` / ExtensionUIContext). Slash stays thin-wrapper-only,
so users leave pi to configure roles. Separately, CLI interactive review applies
one shared thinking level to the whole list — mixed-effort panels need
per-model suffixes. Path B (pi TUI pick → non-interactive CLI write) + CLI
per-model thinking closes both gaps (Constitution I: chezmoi-deployed extension
+ CLI; domain: CLI owns YAML writes).

## What Changes

- `/opsx-loop models set` bare or role-only with `hasUI`: role → substring-
  filtered catalog (`pi --list-models`) → review: sequential pick → thinking
  per model → Done; author/impl: one model → one thinking; then
  `opsx models set <role> <id[:suffix]…>` (extension never writes YAML).
- Value-bearing `/opsx-loop models set <role> <value…>` stays thin passthrough;
  bare `/opsx-loop models` still lists; no-UI falls back without hanging.
- CLI interactive `opsx models set` / `set review`: prompt thinking **after each
  review pick** (not one shared level); hermetic tests for mixed suffixes.
- Catalog parse + timeout relax for `pi --list-models` on interactive slash path.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `opsx-loop`: Interactive bare/role-only `models set` when UI available (Path B);
  write still via CLI only.
- `opsx-cli`: Interactive review thinking is per selected model (after each pick).
- `opsx-model-config`: (no requirement change — per-entry suffixes already
  required; interactive must produce that shape). Leave empty unless AC wording
  needs a cross-ref; prefer CLI/loop deltas only.

## Impact

**Affected files (expected):**
- `dot_pi/agent/extensions/opsx-loop/` (interactive set UX + spawn)
- `dot_local/bin/executable_opsx` (interactive review thinking loop)
- `tests/opsx-models/test_opsx_models.sh` (hermetic per-model thinking)
- Extension unit/TUI tests as needed
- Delta specs under `openspec/changes/opsx-loop-models-interactive/specs/`

**Dependencies:** `pi` (catalog), existing `opsx models` write surface,
`@earendil-works/pi-tui` SelectList via `ctx.ui.custom`.

**Systems:** user layer `~/.config/opsx/models.yaml` only; no front-matter
auto-pin; no TTY handoff; no `opsx models catalog --json`.

## Open Questions (plain-M clarify-in-proposal)

### Q1: Catalog source for Path B?
- **A (chosen):** Extension parses `pi --list-models` (same layout as CLI).
- B: New `opsx models catalog --json`.
- **Resolution:** A — frozen intent; B deferred non-goal.

### Q2: Picker filter semantics?
- **A (chosen):** Substring/contains on `provider/id` via custom SelectList.
- B: Stock `ui.select` / startsWith-only SelectList.
- **Resolution:** A — ~547 ids; typing `claude` must find `anthropic/claude-…`.

### Q3: Review thinking prompt timing?
- **A (chosen):** After each model pick.
- B: After all picks, then per-model pass.
- **Resolution:** A — matches sequential pick loop; human-authorized amend.

### Q4: CLI scope?
- **A (chosen):** Same per-model review thinking in `executable_opsx`.
- B: Pi-only; CLI stays shared-suffix.
- **Resolution:** A — avoid slash/CLI drift; human-authorized widen.

### Q5: Design.md this change?
- **A (chosen):** Skip standalone design (plain-M decision-gated; forks frozen
  in intent).
- B: Author design for picker architecture ADR.
- **Resolution:** A — no open trade-off left; record in analyze notes.

## Deterministic analyze (plain-M inline)

- **Tiling:** Path B slash UX + CLI per-model thinking cover frozen intent;
  non-goals (TTY, zellij, catalog --json) excluded.
- **Traceability:** Constraints map to `opsx-loop` + `opsx-cli` delta ACs below.
- **EARS lint:** Delta requirements use WHEN/WHILE/IF + SHALL; no vague SHOULD.
- **Blockers:** none.
