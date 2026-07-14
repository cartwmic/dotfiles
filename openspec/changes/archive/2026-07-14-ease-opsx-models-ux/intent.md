# Intent — ease-opsx-models-ux

**Status:** FROZEN (explore concluded 2026-07-14)
**Recommended Scale:** M, `full_rigor: false`

Schema: opsx-superpowers. This intent.md is the frozen baseline; do not edit
without explicit human authorization.

## Intent

Make configuring opsx role models easy for humans: an interactive
`opsx models set` flow that discovers real model ids from `pi --list-models`,
supports multi-reviewer selection, and encodes thinking/effort as the existing
pi model suffix (`provider/id:high`), writing only the user layer
(`~/.config/opsx/models.yaml`).

Today's pain: users must know exact `provider/id` strings; multi-reviewer
lists require hand-editing YAML (CLI `set review` stores a scalar and warns
on replace); thinking level has no opsx config home despite pi already
accepting `:thinking` suffixes and `--thinking`.

Target flow for bare `opsx models set` (no args):

```
role pick → model catalog (fzf if present, else numbered select)
         → optional thinking suffix (off|minimal|low|medium|high|xhigh|max)
         → write user yaml
```

For `review`: multi-select from the same catalog; selection order becomes
list order; write a proper multi-value review config (not a single opaque
comma-string that the CLI currently treats as one scalar).

Non-interactive `opsx models set <role> <value>` remains the power-user /
script escape hatch and MUST keep accepting suffix-bearing ids verbatim.

## Constraints

- **UX home:** interactive path lives on `opsx models set` (bare or
  role-only). YAML + env + front-matter stay power-user surfaces; do not
  invent a second config CLI.
- **Write target:** default (and only interactive) write layer is user
  `~/.config/opsx/models.yaml`. Do not auto-write change `review.md`
  front-matter in this change.
- **Effort encoding:** thinking/effort is the pi model-id suffix
  (`provider/id:high`). No new `*_effort` / global `effort` YAML keys.
- **Catalog source:** `pi --list-models` (optionally with search). If `pi`
  is missing or the list fails, fail with an actionable error; do not
  invent a hard-coded model catalog.
- **Picker engine:** prefer `fzf` when present; otherwise fall back to
  numbered bash `select`/read. Do not hard-require fzf.
- **Roles in scope:** `author`, `review`, `impl`, and boolean
  `author-in-session` (true/false prompt). Review is multi-select; others
  single-select (plus thinking suffix where applicable).
- **Resolver contract preserved:** layered resolution order
  (env > change front-matter > user > default), `session` sentinel,
  slash-verbatim qualification, reserved verbs `set|get|list`, and
  role-read / `--json` stdout contracts remain byte-compatible for
  existing consumers (loop export, gate).
- **Review list write:** interactive (and preferably non-interactive)
  multi-reviewer set MUST write a real multi-value review config that
  `opsx models review` prints newline-delimited — fix today's
  scalar-only `set review` limitation rather than documenting YAML-only
  multi-edit forever.
- **Atomic writes:** keep the existing temp-file + `mv` write pattern;
  never leave a half-written `models.yaml`.
- **Code home:** primarily `dot_local/bin/executable_opsx` (+ capability
  specs under `openspec/specs/opsx-model-config` / `opsx-cli`, schema
  template docs if needed, and agent-independent CLI tests under
  `tests/opsx-models/` or adjacent).
- **Validation:** agent-independent shell tests for interactive path
  stubs / non-interactive multi-review write / suffix round-trip; no
  live network required.

## Invariants honored

- Constitution I — opsx CLI source stays at chezmoi path
  `dot_local/bin/executable_opsx` and deploys via `chezmoi apply`.
- Constitution III — no secrets; model ids are not credentials.
- Constitution VIII — `openspec/` workspace not chezmoi-deployed.
- Domain naming — kebab-case change name; capability deltas use
  ADDED/MODIFIED headers with full requirement bodies.
- Existing `opsx-model-config` layered resolution + project-layer removal
  warning remain authoritative; this change extends the write/UX surface,
  it does not reintroduce a project yaml layer.

## Non-goals

- Shell autocomplete / completion scripts (can follow later).
- Auto-pinning into change `review.md` front-matter from the picker.
- Separate `effort` / `thinking` YAML keys or per-role effort fields.
- Hard dependency on fzf, gum, or a TUI framework.
- Changing gate / loop dispatch semantics beyond passing suffix-bearing
  model ids through as they already pass model strings today.
- Reintroducing project-layer `openspec/opsx-models.yaml`.
- A full dashboard TUI (role table always-on); linear role→model flow is
  enough for v1.
- Validating that a chosen thinking level is supported by every provider
  (best-effort UX hint OK; do not block writes on catalog metadata gaps).
