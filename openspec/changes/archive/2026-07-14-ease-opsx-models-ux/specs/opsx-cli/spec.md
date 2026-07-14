<!-- authored: in-session -->
# Capability: opsx-cli

## ADDED Requirements

### Requirement: Interactive Models Set

THE `opsx models set` command SHALL offer an interactive configuration flow when
invoked with no role/value arguments, OR with a role but no value, on a TTY.
THE flow SHALL: (1) select a role among `author`, `review`, `impl`, and
`author-in-session` when the role was not supplied; (2) for model roles, obtain
a model catalog by running `pi --list-models` and present it via `fzf` WHEN
`fzf` is available on PATH, OTHERWISE via a numbered select/read fallback;
(3) for `review`, allow multi-select so the selection order becomes the stored
list order; (4) for scalar model roles, allow single-select; (5) AFTER model
selection for model roles, offer an optional thinking/effort suffix from the
pi vocabulary `off|minimal|low|medium|high|xhigh|max` (or skip/none), appending
`:<level>` to each chosen model id WHEN a level other than off/none is chosen;
(6) for `author-in-session`, prompt for boolean `true`/`false` only (no model
catalog); (7) write the result to the user layer with the same atomic write
semantics as non-interactive `set`. Non-interactive `opsx models set <role>
<value…>` SHALL remain available as the script/power-user escape hatch and
SHALL NOT require a TTY.

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

#### Scenario: Thinking suffix appended when chosen
- **WHEN** the user selects model `cursor/composer-2.5` and thinking level
  `high` in the interactive flow
- **THEN** the stored value SHALL be `cursor/composer-2.5:high`

#### Scenario: Missing pi fails actionable
- **IF** `pi` is missing from PATH or `pi --list-models` fails / yields no
  parseable models during an interactive model pick
- **THEN** `opsx models set` SHALL exit non-zero with an actionable stderr
  message and SHALL NOT write the target file

#### Scenario: Non-interactive set still works without TTY
- **WHEN** `opsx models set impl cursor/composer-2.5` is run non-interactively
- **THEN** it SHALL write the value without launching a picker

## MODIFIED Requirements

### Requirement: Model Config Write Surface

THE `opsx models` subcommand SHALL provide `set <role> <value…>`, `get <role>`,
and `list` operations that write and read role configuration in the user YAML
file. The settable roles SHALL be `author`, `review`, `impl`, and
`author-in-session`; the hyphenated `author-in-session` token SHALL map to the
YAML key `author_in_session` and its value SHALL be coerced/validated as a
boolean (`true`/`false`). The sole write target SHALL be the user layer
(`~/.config/opsx/models.yaml`); `--layer user` remains accepted as an explicit
spelling of the default, and `--layer project` SHALL be REJECTED with an error
naming the project-layer removal and the front-matter alternative (per the
opsx-model-config Layered Resolution Order), exiting non-zero without writing
any file. `set` SHALL create the target file (and its parent directory) if
absent. For scalar roles (`author`, `impl`), `set` writes a single string
value (replace semantics). For the list-valued `review` role, `set` SHALL
accept either a single token, a comma-separated token, or multiple positional
tokens, parse them into an ordered list (trimmed, empty segments dropped), and
store that list as a YAML sequence under `review` (full replace of any prior
list; no merge). A single review token SHALL store a one-element YAML list (or
equivalent list-valued form that `opsx models review` prints as one line).
Writes SHALL be atomic and SHALL preserve existing comments and key order.
`get <role>` SHALL mirror the resolver's read semantics (layered resolution;
empty stdout + exit 0 when unset), and SHALL accept an optional `--layer user`
to read back the raw value stored in the user layer. The YAML file remains the
sole source of truth; this surface is an editor, not a new owner. Model id
values MAY include a pi thinking suffix (`:<level>`); the write surface SHALL
store such values verbatim without stripping the suffix.

#### Scenario: Set writes the role to the default user layer
- **WHEN** `opsx models set author claude-bridge/claude-opus-4-8` is run with no `--layer`
- **THEN** `~/.config/opsx/models.yaml` SHALL be updated so its `author` key equals `claude-bridge/claude-opus-4-8`, and `opsx models get author --layer user` SHALL print that value

#### Scenario: Effective resolution may still be shadowed by a higher layer
- **WHILE** a higher-precedence layer (env or change front-matter) already sets the role
- **WHEN** `opsx models set author <model>` writes the user layer
- **THEN** the user-layer file SHALL contain `<model>`, but a subsequent `opsx models author` (full layered resolution) MAY still print the higher layer's value; only `get author --layer user` is guaranteed to return the just-written value

#### Scenario: Author-in-session is settable
- **WHEN** `opsx models set author-in-session false` is run
- **THEN** the target file's `author_in_session` key SHALL be set to the boolean `false`, and `opsx models author-in-session --json` SHALL resolve `false`

#### Scenario: Project layer write is rejected with the removal message
- **IF** `opsx models set <role> <model> --layer project` is run
- **THEN** `opsx models` SHALL print an error naming the project-layer removal and the review.md front-matter alternative, and SHALL exit non-zero without writing any file

#### Scenario: Setting review with one model replaces the whole list
- **WHILE** the `review` role is currently configured with multiple models in the target layer
- **WHEN** `opsx models set review <model>` is run
- **THEN** the stored `review` value SHALL be exactly the one-element list `[<model>]` (full replace; no merge with the prior list)

#### Scenario: Setting review with comma-separated models stores a YAML list
- **WHEN** `opsx models set review claude-bridge/a,openai-codex/b` is run
- **THEN** the user layer SHALL store a YAML list of two entries, and
  `opsx models review` (with that user layer winning) SHALL print
  `claude-bridge/a` and `openai-codex/b` each on its own line

#### Scenario: Setting review with multiple positional tokens stores a YAML list
- **WHEN** `opsx models set review claude-bridge/a openai-codex/b` is run
- **THEN** the user layer SHALL store those two entries as a YAML list in
  argument order

#### Scenario: Failed write leaves the original intact
- **IF** the temp write, the YAML update, or the rename fails
- **THEN** `opsx models` SHALL exit non-zero, leave the prior target file byte-for-byte unchanged, and remove any temporary file it created

#### Scenario: List reports resolved roles with sources
- **WHEN** `opsx models list` is run
- **THEN** it SHALL print each role (`author`, `review`, `impl`, `author-in-session`) with its resolved value and the layer that supplied it

#### Scenario: Get of an unset scalar role is empty
- **WHEN** `opsx models get <role>` is run for `author`, `review`, or `impl` and no layer configures the role
- **THEN** it SHALL print nothing to standard output and exit 0

#### Scenario: Get of author-in-session reflects its boolean default
- **WHEN** `opsx models get author-in-session` is run and no layer configures it
- **THEN** the effective read SHALL print the built-in boolean default `true` (matching the resolver's `author-in-session` default), WHILE `opsx models get author-in-session --layer user` SHALL print nothing when that specific layer does not set the key

#### Scenario: Non-boolean author-in-session value is rejected
- **IF** `opsx models set author-in-session <value>` is given a value that is not `true` or `false`
- **THEN** `opsx models` SHALL print an error and exit non-zero without writing any file

#### Scenario: Invalid role is rejected
- **IF** `opsx models set <role> <model>` is given a role other than `author`, `review`, `impl`, or `author-in-session`
- **THEN** `opsx models` SHALL print an error and exit non-zero without writing any file

#### Scenario: Invalid layer is rejected
- **IF** `opsx models set <role> <model> --layer <x>` is given a layer other than `user` (the retired `project` value carries its own rejection scenario above)
- **THEN** `opsx models` SHALL print an error and exit non-zero without writing any file

#### Scenario: Suffix-bearing model id is stored verbatim
- **WHEN** `opsx models set impl cursor/composer-2.5:high` is run
- **THEN** the user layer `impl` value SHALL equal `cursor/composer-2.5:high`
  with the `:high` suffix preserved

## REMOVED Requirements
<!-- none -->

## RENAMED Requirements
<!-- none -->

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-cli.interactive-models-set | [x] | [x] | [x] | [x] | [x] |
| opsx-cli.model-config-write-surface | [x] | [x] | [x] | [x] | [x] |
