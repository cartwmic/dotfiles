<!-- authored: in-session -->
# Capability: opsx-loop

## MODIFIED Requirements

### Requirement: Model config subcommand

THE extension SHALL provide a `/opsx-loop models` subcommand: WHEN the user
issues `/opsx-loop models` with a `get` or `list` directive, OR a value-bearing
`set` (`set <role> <value…>`), it SHALL shell out to `opsx models` with the
corresponding arguments and report its result, acting purely as a thin wrapper
so the `opsx models` CLI remains the owner of the write. WHEN the user issues
bare `/opsx-loop models set` or role-only `/opsx-loop models set <role>` AND
the extension has an interactive UI (`hasUI`), it SHALL run an in-TUI
interactive configuration flow that: (1) selects a role among `author`,
`review`, `impl`, and `author-in-session` when the role was not supplied;
(2) for model roles, obtains a catalog by running `pi --list-models` and
presents a filterable picker whose filter matches substring/contains on the
`provider/id` string; (3) for `review`, uses sequential single picks ending on
Done/Esc so selection order becomes the list order, and AFTER EACH model pick
prompts thinking for THAT model only (vocabulary
`off|minimal|low|medium|high|xhigh|max|skip`) appending `:<level>` when
applicable BEFORE the next pick — SHALL NOT apply one shared thinking level to
the whole review list; (4) for `author`/`impl`, single model pick then one
thinking prompt; (5) for `author-in-session`, boolean only; THEN SHALL invoke
`opsx models set <role> <id[:suffix]…>` with the chosen values and SHALL NOT
write any models config file itself. WHILE no interactive UI is available,
bare or role-only `set` SHALL fall back to the thin-wrapper / actionable-error
path and SHALL NOT hang awaiting TUI input. The wrapper SHALL invoke
`opsx models` with the active repository as the working directory (or pass
`OPSX_ROOT`) so a `--layer project` write targets the active repo even when
pi's process cwd differs. The extension SHALL offer `models` as an argument
completion. Bare `/opsx-loop models` with no further directive SHALL still
invoke `opsx models list`.

#### Scenario: Set wrapper delegates to the CLI
- **WHEN** the user issues `/opsx-loop models set author <model>`
- **THEN** the extension SHALL invoke `opsx models set author <model>` and
  report success or the CLI's error, without writing any config file itself

#### Scenario: Interactive bare set with UI
- **WHILE** the extension has an interactive UI
- **WHEN** the user issues `/opsx-loop models set` with no further arguments
- **THEN** the extension SHALL run the in-TUI role → model → thinking flow and
  SHALL finish by invoking `opsx models set <role> <value…>` without writing
  any models config file itself

#### Scenario: Interactive role-only set with UI
- **WHILE** the extension has an interactive UI
- **WHEN** the user issues `/opsx-loop models set review` with no value
- **THEN** the extension SHALL skip the role prompt, run sequential model picks
  with per-model thinking, and SHALL invoke
  `opsx models set review <id[:suffix]…>` with selection order preserved

#### Scenario: Review interactive thinking is per model
- **WHILE** the extension has an interactive UI
- **WHEN** the user picks two review models and chooses distinct thinking
  levels for each
- **THEN** the CLI invocation SHALL pass distinct per-id suffixes (or none)
  matching those choices, not one shared suffix applied to every id

#### Scenario: Catalog filter matches substring
- **WHILE** the interactive model picker is showing catalog ids
- **WHEN** the user types a substring that appears mid-id (e.g. `claude` in
  `anthropic/claude-sonnet-5`)
- **THEN** that id SHALL remain a matching candidate (filter SHALL NOT be
  startsWith-only on the full `provider/id`)

#### Scenario: No-UI bare set does not hang
- **WHILE** the extension has no interactive UI
- **WHEN** the user issues `/opsx-loop models set` with no further arguments
- **THEN** the extension SHALL NOT block awaiting TUI input; it SHALL fall
  back to thin-wrapper / actionable error behavior

#### Scenario: List wrapper shows resolved roles
- **WHEN** the user issues `/opsx-loop models list`
- **THEN** the extension SHALL invoke `opsx models list` and present its output

#### Scenario: Project-layer write targets the active repo
- **WHEN** the user issues `/opsx-loop models set <role> <model> --layer project`
- **THEN** the wrapper SHALL invoke `opsx models` with the active repo cwd (or
  `OPSX_ROOT`) so the project file resolved is the active repo's
  `openspec/opsx-models.yaml`, not a directory derived from pi's process cwd

#### Scenario: Bare models lists the resolved roles
- **WHEN** the user issues `/opsx-loop models` with no further directive
- **THEN** the extension SHALL invoke `opsx models list` and present its output

#### Scenario: Models offered as completion
- **WHEN** the user requests argument completions for `/opsx-loop`
- **THEN** `models` SHALL appear alongside `goal`, `status`, and `clear`

#### Scenario: Missing catalog fails actionable
- **IF** `pi --list-models` fails or yields no parseable models during an
  interactive `/opsx-loop models set` pick
- **THEN** the extension SHALL surface an actionable error and SHALL NOT write
  any models config file

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-loop.model-config-subcommand | [x] | [x] | [x] | [x] | [x] |
