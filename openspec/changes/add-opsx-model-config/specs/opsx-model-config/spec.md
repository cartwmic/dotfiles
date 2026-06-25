# Capability: opsx-model-config

## ADDED Requirements

### Requirement: Role Model Resolver

THE opsx-models command SHALL resolve the configured model(s) for a requested role — `author`, `review`, or `impl` — distinguishing CONFIGURED values from the unconfigured/built-in-default case so consumers and the gate can tell them apart. The built-in default for every role SHALL be the literal sentinel `session`, meaning "use the session/default model" (no real model id ships as a default). The resolver resolves strings UNCONDITIONALLY — it does NOT branch on `author_in_session` (that boolean is a separate surface consumed by the skills/gate).

#### Scenario: Configured role prints its value
- **WHEN** `opsx-models author` is run and the author role is set at some layer
- **THEN** it SHALL print the resolved author model id on one line and exit 0

#### Scenario: Unconfigured role prints nothing
- **WHEN** `opsx-models author` is run and no layer configures the author role
- **THEN** it SHALL print NOTHING to standard output and exit 0 (empty stdout = unset); `--with-default` SHALL instead print the built-in default sentinel `session`

#### Scenario: Source-aware JSON
- **WHEN** `opsx-models <role> --json` is run
- **THEN** it SHALL print `{"value": <string|list|null>, "source": "env|change|project|user|default|unset"}`, where `value` is the SAME provider-resolved string(s) the plain output prints, so consumers enforce only on a configured source

#### Scenario: author-in-session boolean has a resolver surface
- **WHEN** `opsx-models author-in-session --json [--change <c>]` is run
- **THEN** it SHALL print `{"value": <boolean|null>, "source": "env|change|project|user|default|unset"}` (env name `OPSX_AUTHOR_IN_SESSION`), with the same layering as roles and a built-in default of true, so the boolean is executable from any harness

#### Scenario: Review role is a list
- **WHEN** `opsx-models review` is run with the role configured
- **THEN** it SHALL print each resolved review model id on its own line (newline-delimited)

#### Scenario: Any value containing a slash is returned verbatim
- **WHEN** a role is configured to a value CONTAINING `/` (one or more segments, e.g. `claude-bridge/claude-opus-4-8` OR the multi-segment `openrouter/openai/gpt-5.5`)
- **THEN** `opsx-models <role>` SHALL print it UNCHANGED — it is treated as a complete, already-qualified pi model id and the `provider` keys are NOT applied to it

#### Scenario: Bare id qualified by a configured provider
- **WHILE** a role's value is BARE (no `/`, e.g. `claude-opus-4-8`) and a `provider` is configured for that role (or a top-level default `provider`, e.g. `claude-bridge`)
- **THEN** `opsx-models <role>` SHALL print `<provider>/<id>` (e.g. `claude-bridge/claude-opus-4-8`); a bare id with NO provider configured SHALL be printed bare (the consumer resolves it)

#### Scenario: Unknown role
- **IF** opsx-models is invoked with a first argument other than `author`, `review`, `impl`, or `author-in-session`
- **THEN** it SHALL print an error to standard error and exit non-zero

### Requirement: Layered Resolution Order

THE opsx-models resolver SHALL resolve each role by precedence, highest first: environment variable, then the change's review.md front-matter (when `--change` is given), then the project `openspec/opsx-models.yaml`, then the user `~/.config/opsx/models.yaml`, then a built-in default. For the list-valued `review` role, the highest layer that sets the role SHALL fully REPLACE lower layers (no union). An empty environment value SHALL be treated as unset. The model env vars SHALL be `OPSX_AUTHOR_MODEL`, `OPSX_REVIEW_MODELS` (note the plural — list-valued), and `OPSX_IMPL_MODEL`; `OPSX_REVIEW_MODELS` SHALL be newline- or comma-delimited (trimmed, order preserved). PROVIDER resolution SHALL key purely on the presence of a `/`: a value CONTAINING `/` is a complete pi model id used VERBATIM (its provider is its leading segment; the provider keys do NOT apply, so an openrouter-style multi-segment id MUST be written in full, e.g. `openrouter/openai/gpt-5.5`). A BARE value (no `/`) SHALL be qualified by the role's `provider` (env `OPSX_<ROLE>_PROVIDER` — i.e. `OPSX_AUTHOR_PROVIDER`/`OPSX_REVIEW_PROVIDER`/`OPSX_IMPL_PROVIDER` > front-matter > project > user), else the top-level default `provider` (env `OPSX_PROVIDER` > front-matter > project > user), else left bare for the consumer to resolve. Each `review` list entry SHALL be provider-resolved independently. The `author_in_session` boolean uses the same layering with env `OPSX_AUTHOR_IN_SESSION`.

#### Scenario: Environment overrides files
- **WHILE** `OPSX_AUTHOR_MODEL` is set non-empty
- **THEN** it SHALL win over any file-configured author model

#### Scenario: Per-change front-matter overrides project and user files
- **WHILE** no env override is set and `--change <c>` is given and that change's review.md front-matter sets a role
- **THEN** the front-matter value SHALL win over the project and user files

#### Scenario: Highest layer replaces the review list
- **WHILE** front-matter sets `review_models: [A]` and the project file sets `review: [A, B]`
- **THEN** the resolved review set SHALL be exactly `[A]` (full replace, not `[A, B]`)

#### Scenario: Missing change or review.md falls through
- **IF** `--change <c>` is given but the change or its review.md does not exist
- **THEN** the resolver SHALL fall through to the project/user/default layers without error; an invalid project root SHALL exit non-zero

#### Scenario: A slash-containing value ignores a configured provider
- **WHILE** a role's model value is `claude-bridge/claude-opus-4-8` (contains `/`) AND a different `provider` is configured for that role
- **THEN** the resolved value SHALL stay `claude-bridge/claude-opus-4-8` verbatim (the provider keys do not re-qualify a slash-containing value)

#### Scenario: Default provider applies only to a bare id
- **WHILE** the top-level default `provider` is `claude-bridge` and a role is set to the bare id `claude-haiku-4-5`
- **THEN** the resolved value SHALL be `claude-bridge/claude-haiku-4-5`

#### Scenario: openrouter multi-segment id is written in full
- **WHILE** the user wants `gpt-5.5` on openrouter (whose model id is `openai/gpt-5.5`)
- **THEN** they SHALL configure the full value `openrouter/openai/gpt-5.5`, which the resolver prints verbatim (a bare `gpt-5.5` + `provider: openrouter` would yield `openrouter/gpt-5.5`, which is NOT the openrouter id — documented in the template)

### Requirement: Config Conventions

THE schema SHALL define `openspec/opsx-models.yaml` (project) and `~/.config/opsx/models.yaml` (user), each mapping `author` (string), `review` (string or list), `impl` (string), `author_in_session` (boolean), an optional top-level default `provider` (string), and optional per-role provider keys (`author_provider`, `review_provider`, `impl_provider`); and the matching `review.md` front-matter keys `author_model`, `review_models`, `impl_model`, `author_in_session`, `provider`, `author_provider`, `review_provider`, `impl_provider`. Model values MAY be provider-qualified (`<provider>/<id>`) — that is the primary way to pin a provider — and the provider keys qualify bare ids. A template SHALL ship with the schema.

#### Scenario: Template shipped
- **WHEN** the schema is deployed
- **THEN** `templates/opsx-models.yaml` SHALL document the roles, providers (inline + the `provider` keys), `author_in_session`, and the resolution order

#### Scenario: Review accepts string or list
- **WHEN** `review` is a single string in a file
- **THEN** opsx-models review SHALL print that one model; **WHEN** a list, it SHALL print each entry

### Requirement: Author In Session By Default

THE workflow SHALL author artifacts in the parent session (its model) by default, and SHALL NOT delegate authoring unless `author_in_session` is explicitly false. The in-session authoring STEP SHALL write an `authored: in-session` marker on artifacts it authors, and `opsx-gate` SHALL fail an authoring artifact that carries no authoring marker while the `author` role specifically has a configured model and `author_in_session` is true/unset. The marker is a cheap SELF-ATTESTED tripwire for the observed bug (silent authoring delegation would not run the in-session marker step); it is NOT model provenance — this change does not attempt to enforce delegated model provenance via a post-hoc gate (a same-UID actor can write any file the gate reads). Delegated review/impl/opt-out-author dispatch passes the configured model best-effort; it is not gate-verified.

#### Scenario: Authoring is not delegated by default
- **WHILE** `author_in_session` is unset or true
- **WHEN** an artifact is authored
- **THEN** it SHALL be authored in the parent session, SHALL NOT dispatch an authoring subagent, and the in-session authoring step SHALL write an `authored: in-session` marker

#### Scenario: Missing in-session marker fails the gate
- **WHILE** `author_in_session` is true/unset and the `author` role is configured
- **IF** an authoring artifact carries no `authored: in-session` marker
- **THEN** opsx-gate SHALL report a failed check and exit non-zero

#### Scenario: Opt-in delegation dispatches with the author model (best-effort, not gate-verified)
- **WHILE** `author_in_session` is false and an `author` model is configured
- **WHEN** authoring is delegated
- **THEN** the authoring subagent SHALL be dispatched with the configured author model (`model:` field); the gate does not require the in-session marker and does not verify the delegated model

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-model-config.role-model-resolver | [x] | [x] | [x] | [x] | [x] |
| opsx-model-config.layered-resolution-order | [x] | [x] | [x] | [x] | [x] |
| opsx-model-config.config-conventions | [x] | [x] | [x] | [x] | [x] |
| opsx-model-config.author-in-session-by-default | [x] | [x] | [x] | [x] | [x] |
