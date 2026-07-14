<!-- authored: in-session -->
# Proposal — ease-opsx-models-ux

## Why

Configuring opsx role models is sharp: users must know exact `provider/id`
strings, `opsx models set review` can only write a scalar (YAML multi-edit
warned as escape hatch), and thinking/effort has no opsx home despite pi
already accepting `:thinking` suffixes. Interactive picker + multi-review
list write + suffix-on-id closes that gap without new config keys
(Constitution I: keep CLI at `dot_local/bin/executable_opsx`).

## What Changes

- Interactive `opsx models set` (bare or role-only): role pick → model catalog
  from `pi --list-models` (fzf if present, else numbered select) → optional
  thinking suffix → write user `~/.config/opsx/models.yaml`.
- Review multi-select writes a real YAML list; non-interactive
  `opsx models set review` accepts comma-separated (or multi-arg) values and
  stores a list so `opsx models review` prints newline-delimited entries.
- Thinking/effort encoded only as pi model-id suffix (`provider/id:high`);
  no new `*_effort` keys.
- Tests under `tests/opsx-models/` for multi-review write, suffix round-trip,
  and interactive path stubs (no live network).
- Docs/template touch in schema `opsx-models.yaml` if needed for suffix +
  interactive usage notes.

## Capabilities

### New Capabilities
- (none)

### Modified Capabilities
- `opsx-cli`: Interactive `opsx models set` UX; multi-value review write;
  preserve atomic user-layer writes and reserved-verb dispatch.
- `opsx-model-config`: Document/require that suffix-bearing model ids
  (`provider/id:thinking`) resolve and round-trip verbatim through the
  resolver and write surface (no stripping of `:thinking`).

## Impact

**Affected files (expected):**
- `dot_local/bin/executable_opsx` (`opsx_models` write/interactive path)
- `tests/opsx-models/test_opsx_models.sh` (+ any interactive stub helpers)
- `dot_local/share/openspec/schemas/opsx-superpowers/templates/opsx-models.yaml`
  (usage notes only, if needed)
- Delta specs under `openspec/changes/ease-opsx-models-ux/specs/`

**Dependencies:** `pi` (catalog), optional `fzf`, existing `yq`.

**Systems:** user layer `~/.config/opsx/models.yaml` only; no front-matter
auto-pin; no project-layer revive.

## Open Questions (plain-M clarify-in-proposal)

### Q1: Effort encoding?
- **A (chosen):** Suffix on model id (`provider/id:high`).
- B: Separate `*_effort` keys / global effort.
- **Resolution:** A — matches `pi --model sonnet:high`; zero new YAML keys.

### Q2: Interactive write target?
- **A (chosen):** User defaults only (`~/.config/opsx/models.yaml`).
- B: Also offer change front-matter pin.
- **Resolution:** A — front-matter remains power-user / non-goal for v1.

### Q3: Bare `opsx models set` shape?
- **A (chosen):** Linear role → model → thinking.
- B: Always-on role dashboard.
- **Resolution:** A — simpler v1; dashboard is non-goal.

### Q4: Multi-review edit?
- **A (chosen):** Multi-select from catalog; selection order = list order.
- B: Incremental add/remove loop.
- **Resolution:** A — replace-whole-list semantics match today's set contract.

### Q5: Picker engine?
- **A (chosen):** Prefer `fzf` when present; else numbered select.
- B: Hard-require fzf.
- **Resolution:** A — no hard new dep (intent constraint).

### Q6: Non-interactive multi-review syntax?
- **A (chosen):** Comma-separated value and/or repeated tokens → YAML list;
  single token still replaces with one-element list.
- B: Keep scalar-only CLI; YAML-only multi-edit.
- **Resolution:** A — required by intent ("fix scalar-only set review").

## Deterministic analyze (plain-M, inline)

| Check | Result |
|---|---|
| 1 Tiling | Modified `opsx-cli` + `opsx-model-config` cover picker, multi-review write, suffix passthrough |
| 2 Traceability | Intent constraints map to MODIFIED/ADDED ACs in both deltas |
| 7 EARS lint | Event/state for nominal; IF…THEN for missing `pi` / cancel / invalid |

No blockers. Outstanding risk: `pi --list-models` format drift → fail actionable
if parse yields zero models; do not invent a hard-coded catalog.

## Assumptions recorded

- `pi --model provider/id:thinking` and `--thinking` vocabulary
  (`off|minimal|low|medium|high|xhigh|max`) are the suffix enum.
- Resolver already treats slash-containing values as verbatim; suffix rides
  inside that string (e.g. `cursor/composer-2.5:high`).
- Design.md skipped (plain-M decision-gated): explore+intent already froze
  UX/encoding choices; no ADR-worthy architecture fork beyond intent.
- Shell autocomplete deferred (intent non-goal).
