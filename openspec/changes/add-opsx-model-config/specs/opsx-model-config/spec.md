# Capability: opsx-model-config

## ADDED Requirements

### Requirement: Role Model Resolver

THE opsx-models command SHALL resolve the configured model(s) for a requested role — `author`, `review`, or `impl` — distinguishing CONFIGURED values from the unconfigured/built-in-default case so consumers and the gate can tell them apart.

#### Scenario: Configured role prints its value
- **WHEN** `opsx-models author` is run and the author role is set at some layer
- **THEN** it SHALL print the resolved author model id on one line and exit 0

#### Scenario: Unconfigured role prints nothing
- **WHEN** `opsx-models author` is run and no layer configures the author role
- **THEN** it SHALL print NOTHING to standard output and exit 0 (empty stdout = unset); `--with-default` SHALL instead print the built-in default

#### Scenario: Source-aware JSON
- **WHEN** `opsx-models <role> --json` is run
- **THEN** it SHALL print `{"value": <string|list|null>, "source": "env|change|project|user|default|unset"}` so consumers enforce only on a configured source

#### Scenario: author-in-session boolean has a resolver surface
- **WHEN** `opsx-models author-in-session --json [--change <c>]` is run
- **THEN** it SHALL print `{"value": <boolean|null>, "source": "env|change|project|user|default|unset"}` (env name `OPSX_AUTHOR_IN_SESSION`), with the same layering as roles and a built-in default of true, so the boolean is executable from any harness

#### Scenario: Review role is a list
- **WHEN** `opsx-models review` is run with the role configured
- **THEN** it SHALL print each resolved review model id on its own line (newline-delimited)

#### Scenario: Unknown role
- **IF** opsx-models is invoked with a first argument other than `author`, `review`, `impl`, or `author-in-session`
- **THEN** it SHALL print an error to standard error and exit non-zero

### Requirement: Layered Resolution Order

THE opsx-models resolver SHALL resolve each role by precedence, highest first: environment variable, then the change's review.md front-matter (when `--change` is given), then the project `openspec/opsx-models.yaml`, then the user `~/.config/opsx/models.yaml`, then a built-in default. For the list-valued `review` role, the highest layer that sets the role SHALL fully REPLACE lower layers (no union). An empty environment value SHALL be treated as unset. `OPSX_REVIEW_MODELS` SHALL be newline- or comma-delimited (trimmed, order preserved).

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

### Requirement: Config Conventions

THE schema SHALL define `openspec/opsx-models.yaml` (project) and `~/.config/opsx/models.yaml` (user), each mapping `author` (string), `review` (string or list), `impl` (string), and `author_in_session` (boolean); and the matching `review.md` front-matter keys `author_model`, `review_models`, `impl_model`, `author_in_session`. A template SHALL ship with the schema.

#### Scenario: Template shipped
- **WHEN** the schema is deployed
- **THEN** `templates/opsx-models.yaml` SHALL document the roles, `author_in_session`, and the resolution order

#### Scenario: Review accepts string or list
- **WHEN** `review` is a single string in a file
- **THEN** opsx-models review SHALL print that one model; **WHEN** a list, it SHALL print each entry

### Requirement: Author In Session By Default

THE workflow SHALL author artifacts in the parent session (its model) by default, and SHALL NOT delegate authoring unless `author_in_session` is explicitly false. To make recurrence DETECTABLE (not policy-only), the in-session authoring STEP (running in the parent session — NOT a dispatch adapter, which does not run when nothing is delegated) SHALL write an `authored: in-session` marker on artifacts it authors, and `opsx-gate` SHALL fail an authoring artifact that instead carries a delegated model stamp, or that carries no authoring marker while the `author` role specifically has a configured model.

#### Scenario: Authoring is not delegated by default
- **WHILE** `author_in_session` is unset or true
- **WHEN** an artifact is authored
- **THEN** it SHALL be authored in the parent session, SHALL NOT dispatch an authoring subagent, and the in-session authoring step SHALL write an `authored: in-session` marker

#### Scenario: A delegated-stamp on an authoring artifact fails the gate
- **WHILE** `author_in_session` is true/unset
- **IF** an authoring artifact carries a delegated model stamp (i.e. authoring was silently delegated — the original bug)
- **THEN** opsx-gate SHALL report a failed check and exit non-zero

#### Scenario: Opt-in delegation passes the author model and is stamped
- **WHILE** `author_in_session` is false and an `author` model is configured
- **WHEN** authoring is delegated
- **THEN** the authoring subagent SHALL be dispatched with the configured author model and its actual model stamped, subject to the same provenance check as review/impl

### Requirement: Model Provenance Enforcement

WHEN review, implementation, or opt-in-delegated authoring work is delegated for a role that HAS a configured model, THE produced artifact SHALL carry an adapter-stamped provenance recording `{role, requested_model, actual_model, adapter, harness}`, and `opsx-gate` SHALL FAIL the gate (fail-closed) if that stamp is missing, unverifiable, or its `actual_model` does not match the configured role model. Comparison SHALL be exact on provider-qualified ids, with matching permitted only via an explicit alias table — never unconstrained suffix matching. For the `review` role, every configured review model SHALL have a matching stamp (required set, not subset). Where a role has NO configured model, the check SHALL be skipped.

#### Scenario: Missing stamp on a configured delegated role fails (fail-closed)
- **WHILE** a role model is configured and that role's work was delegated
- **IF** the produced artifact carries no provenance stamp (or an unverifiable one)
- **THEN** opsx-gate SHALL report a `model-provenance-missing` failed check and exit non-zero

#### Scenario: Mismatched actual model fails
- **WHILE** a role model is configured
- **IF** the stamped `actual_model` does not equal the configured role model (after alias resolution)
- **THEN** opsx-gate SHALL report a `model-mismatch` failed check and exit non-zero

#### Scenario: All configured review models must have run
- **WHILE** `review_models` configures models [A, B]
- **IF** the code-review provenance stamps only A
- **THEN** opsx-gate SHALL fail (required set: B's reviewer is missing)

#### Scenario: No configured role model skips the check
- **IF** a role has no configured model at any layer (source = unset/default)
- **THEN** opsx-gate SHALL NOT enforce a provenance match for that role

---

## Acceptance criterion quality checklist

| AC ID | Testable | Solution-free | Unambiguous | Consistent | Complete |
|---|---|---|---|---|---|
| opsx-model-config.role-model-resolver | [x] | [x] | [x] | [x] | [x] |
| opsx-model-config.layered-resolution-order | [x] | [x] | [x] | [x] | [x] |
| opsx-model-config.config-conventions | [x] | [x] | [x] | [x] | [x] |
| opsx-model-config.author-in-session-by-default | [x] | [x] | [x] | [x] | [x] |
| opsx-model-config.model-provenance-enforcement | [x] | [x] | [x] | [x] | [x] |
