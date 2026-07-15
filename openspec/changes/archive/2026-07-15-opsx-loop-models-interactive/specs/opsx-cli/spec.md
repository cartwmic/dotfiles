<!-- authored: in-session -->
# Capability: opsx-cli

## MODIFIED Requirements

### Requirement: Interactive Models Set

THE `opsx models set` command SHALL offer an interactive configuration flow when
invoked with no role/value arguments, OR with a role but no value, on a TTY.
THE flow SHALL: (1) select a role among `author`, `review`, `impl`, and
`author-in-session` when the role was not supplied; (2) for model roles, obtain
a model catalog by running `pi --list-models` and present it via `fzf` WHEN
`fzf` is available on PATH, OTHERWISE via a numbered select/read fallback;
(3) for `review`, allow sequential multi-select so the selection order becomes
the stored list order; (4) for scalar model roles, allow single-select;
(5) for `review`, AFTER EACH model pick, offer an optional thinking/effort
suffix from the pi vocabulary `off|minimal|low|medium|high|xhigh|max` (or
skip/none) for THAT model only, appending `:<level>` to that id WHEN a level
other than off/none/skip is chosen, BEFORE prompting for the next model —
SHALL NOT apply one shared thinking level across the whole review list;
(6) for scalar model roles (`author`, `impl`), AFTER the single model
selection, offer one optional thinking/effort suffix with the same vocabulary
and append rules; (7) for `author-in-session`, prompt for boolean `true`/`false`
only (no model catalog); (8) write the result to the user layer with the same
atomic write semantics as non-interactive `set`. Non-interactive
`opsx models set <role> <value…>` SHALL remain available as the
script/power-user escape hatch and SHALL NOT require a TTY; per-entry
`:thinking` suffixes on review list tokens SHALL continue to be preserved.

#### Scenario: Bare set launches role then model flow
- **WHEN** `opsx models set` is run with no arguments on a TTY
- **THEN** it SHALL prompt for a role, then run the role-appropriate picker,
  and on confirmation SHALL write the chosen value(s) to
  `~/.config/opsx/models.yaml`

#### Scenario: Role-only set skips role pick
- **WHEN** `opsx models set review` is run with no value on a TTY
- **THEN** it SHALL skip the role prompt and open the multi-select model
  catalog for `review`

#### Scenario: Catalog comes from pi list-models
- **WHEN** the interactive model picker runs
- **THEN** it SHALL populate candidates from `pi --list-models` output as
  `provider/id` entries and SHALL NOT use a hard-coded built-in model catalog

#### Scenario: fzf preferred with numbered fallback
- **WHILE** `fzf` is on PATH
- **WHEN** the interactive model picker runs
- **THEN** it SHALL use `fzf` for filtering/selection; **WHILE** `fzf` is
  absent, **WHEN** the picker runs, **THEN** it SHALL fall back to a numbered
  select/read UI without failing solely because `fzf` is missing

#### Scenario: Thinking suffix appended when chosen for scalar role
- **WHEN** the user selects model `cursor/composer-2.5` and thinking level
  `high` in the interactive flow for `impl` (or `author`)
- **THEN** the stored value SHALL be `cursor/composer-2.5:high`

#### Scenario: Review thinking is per selected model
- **WHEN** the user interactively selects review models `cursor/composer-2.5`
  then `anthropic/claude-sonnet-5`, choosing thinking `high` for the first and
  `xhigh` for the second
- **THEN** the stored `review` list SHALL contain
  `cursor/composer-2.5:high` and `anthropic/claude-sonnet-5:xhigh` as separate
  entries (selection order preserved) and SHALL NOT apply a single shared
  thinking level to both ids

#### Scenario: Missing pi fails actionable
- **IF** `pi` is missing from PATH or `pi --list-models` fails / yields no
  parseable models during an interactive model pick
- **THEN** `opsx models set` SHALL exit non-zero with an actionable stderr
  message and SHALL NOT write the target file

#### Scenario: Non-interactive set still works without TTY
- **WHEN** `opsx models set impl cursor/composer-2.5` is run non-interactively
- **THEN** it SHALL write the value without launching a picker

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-cli.interactive-models-set | [x] | [x] | [x] | [x] | [x] |
