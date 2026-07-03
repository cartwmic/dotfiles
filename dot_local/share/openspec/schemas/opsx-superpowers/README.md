# opsx-superpowers — OpenSpec workflow schema

User-level schema deployed to `~/.local/share/openspec/schemas/opsx-superpowers/` via chezmoi (OpenSpec's XDG_DATA_HOME-compliant location; the resolver checks `${XDG_DATA_HOME:-~/.local/share}/openspec/schemas/<name>/`).
Persisted canonically at `~/.local/share/chezmoi/dot_local/share/openspec/schemas/opsx-superpowers/`.

## Activation

In any project's `openspec/config.yaml`:

```yaml
schema: opsx-superpowers
```

The default `spec-driven` schema is unaffected. Per-project opt-in. Reversible.

## What this schema gives you that `spec-driven` does not

| Capability | spec-driven | opsx-superpowers |
|---|---|---|
| Artifact graph | proposal → specs → design → tasks (4) | proposal → specs → clarify → design → analyze → review → tasks → plan (8 schema artifacts) + skill-managed verify.md + skill-managed retrospective.md + skill-managed ADR promotion |
| Acceptance criteria format | bullet-list WHEN/THEN | EARS notation (5 patterns) with 5 quality properties |
| Constitution / domain referenced | no | yes — every artifact reads `openspec/constitution.md` + `openspec/domain.md` |
| Clarify phase | no | yes — 3 passes (ambiguity / inconsistency / completeness) |
| Analyze phase | no | yes — read-only cross-artifact lint with 7 checks |
| ADR persistence past archive | no | yes — `openspec-archive-change` skill promotes qualifying decisions to `<repo>/adr/ADR-NNNN-<slug>.md` before archive using `templates/adr.md` (not a schema artifact — see schema.yaml D11 rationale) |
| Mode switchboard | no | yes — `review.md` front-matter switchboard (Scale, Execution, Verification, Debug, Review-Status, Delegation, Worktree, Code-Review, Loop-Budget, Validation-Source, Doneness, Spec-Level, plus optional model keys — see Mode reference below) |
| Scale-adaptive artifact gating | no | yes — XS skips heavy artifacts; M is the typical full graph; `full_rigor: true` adds ADR promotion + adversarial-on-analyze + retrospective (the former L/XL extras) |
| Pre-flight commit before worktree | no | yes (apply step records the immutable merge-base `Diff Base SHA` for file-contract diffs) |
| Per-task file contracts | no | yes — `files_allowed` / `files_forbidden` / `allow_new_files` + `intent: fix\|feature\|refactor\|infra` |
| AC↔test ID mapping as verify gate | no | yes — `verify.md` (skill-produced) blocks archive if mapping incomplete; canonical AC ID format `<capability>.<requirement-slug>` |
| Retrospective with mcp-memory promotion | no | yes — pre-archive `retrospective.md` (skill-produced) with `Promote candidates` (all 9 mcp-memory types) parsed by `openspec-archive-change` |
| Adversarial review at high stakes | manual | invoked automatically by the `analyze` artifact when `full_rigor: true` |

## Scale tiers

Pick one in `review.md` (`Scale: <value>`). The vocabulary is `XS | S | M` plus an
optional boolean `full_rigor` front-matter key (default `false`). The schema's apply
rules gate required artifacts on `(Scale, full_rigor)`. A Scale outside `XS|S|M`, or a
non-boolean `full_rigor`, FAILS CLOSED (a loud gate/validation failure) — never a
silent permissive default.

review.md is required at EVERY tier (it is the Scale/mode source the gate reads first and fails closed without) — it is never in the Optional column.

| Scale | Example | Required artifacts | Optional |
|---|---|---|---|
| **XS** | typo, comment fix, single-line config tweak | review | everything else |
| **S** | single-file bug fix, small refactor | review, proposal, tasks | specs, design, plan, verify, adr, retrospective (clarify runs the ambiguity pass only; analyze runs checks 1, 2, 7 — reduced, not skipped) |
| **M** | typical feature, cross-file but single capability | review, intent, proposal, specs, tasks, plan (+ verify / code-review / **doneness** per modes) — clarify open questions fold into `proposal.md ## Open Questions` and analyze is deterministic-only (no standalone `clarify.md`/`analyze.md`); **design.md is NOT required at plain M — it is decision-gated (authored only when a decision warrants it, D5)** | design (decision-gated), adr (unless decision passes 4-point test), retrospective |
| **M + `full_rigor: true`** | cross-capability change, breaking change, new capability, migration (the former **L**/**XL**) | all plain-M required + standalone `clarify.md`, + blind `analyze.md` dispatch, + **`design.md`** (the former L/XL full set always carried design), + independently dispatched blind doneness judge, + adr candidates, + adversarial-review-cycle from analyze, + retrospective before archive | — |

The 2-model blind adversarial code review stays gating-required at EVERY tier — the
tier table never weakens it.

Heuristic: if you're unsure, pick S. If clarify produces blockers, the schema will tell you to upgrade.

### Migration note (5-tier → 3-tier)

The former five-tier vocabulary (`XS S M L XL`) collapsed to `XS S M` + `full_rigor`.
Mapping: **L** and **XL** both become **`Scale: M` with `full_rigor: true`**. For an
in-flight (non-archived) change still labeled `Scale: L` or `Scale: XL`, the
deterministic gate now FAILS CLOSED on the unknown Scale (a loud failure, never a
silent pass) — relabel it to `Scale: M` + `full_rigor: true` to proceed. Already-archived
changes and their historical review records are NEVER rewritten (their gate ran under the
old deployed schema).

## Mode reference (in `review.md`)

Each mode has a controlled vocabulary. Default values shown in **bold**.

| Mode | Values | Effect |
|---|---|---|
| `Scale` | XS / **S** / M | Gates which artifacts are required for apply completion (vocabulary `XS\|S\|M`; out-of-range fails closed) |
| `full_rigor` | **false** / true | Opts a Scale-M change into the ADR-promotion + adversarial-on-analyze + independent-clarify/analyze/doneness + retrospective extras formerly implied by `L`/`XL` |
| `Execution Mode` | **standard** / tdd-preferred / tdd-required | tdd-required: each task starts with a failing test, then minimal impl |
| `Verification Mode` | inline-only / **retained-recommended** / retained-required | retained-required: `verify.md` is mandatory before archive |
| `Debug Mode` | **standard** / systematic-debugging | systematic-debugging: `plan.md` MUST contain `Observed Failure` and `Debugging Trail` before code changes |
| `Review Status` | **not-requested** / requested / findings-received / resolved | State machine for `adversarial-review-cycle` invocation |
| `Delegation Mode` | **single-agent** / subagent-eligible / subagent-required | subagent-*: `openspec-apply-change` dispatches tasks via `pi-subagents` |
| `Worktree Mode` | worktree-required / worktree-eligible / same-tree | Default DERIVED by tier when absent — XS/S ⇒ **same-tree**, M ⇒ **worktree-required**; an explicit value always wins. worktree-* runs every task in a `git worktree` (the loop's blast-radius sandbox), main agent owns writeback |
| `Code Review Mode` | none / advisory / **gating-required (M+)** | gating-required: `code-review.md` adversarial diff review must pass before archive |
| `Loop Max Iterations` | integer (authoring-time default **XS=10 / S=20 / M=40 / full_rigor=80**) | drive-loop budget; mapped onto the loop runtime turn budget |
| `Validation Source Mode` | **required** / waived | required: Scale ≥ M must declare an agent-independent validation source |
| `Doneness Mode` | **required (M+)** / waived | required: gate reads a sealed `doneness.md` verdict (blind judge, intent-satisfaction) as the sole-remaining-failure backstop. At plain M the verdict rides the code-review dispatch (designated reviewer = first `review` model, `review_mode: blind-single-judge`), still sealed to a separate `doneness.md`; `full_rigor` dispatches an independent judge. `waived` needs a non-empty `doneness_waiver_rationale` |
| `Spec Level` | **spec-anchored** / spec-first / spec-as-source | spec-anchored = OpenSpec's natural mode; spec-as-source warns about MDD-era trade-offs |

### Role models (optional, via `opsx models`)

review.md front-matter MAY pin per-change models/providers, resolved by the
harness-neutral `opsx models` CLI (sibling to `opsx gate`):

| Key | Meaning |
|---|---|
| `author_model` / `review_models` / `impl_model` | role model(s); `review_models` is a string or list (one blind reviewer per entry) |
| `author_in_session` | boolean (default **true**) — when true, authoring stays in the parent session and is not delegated |
| `provider` / `author_provider` / `review_provider` / `impl_provider` | qualify BARE model ids; a value containing `/` is used verbatim |

Layering (highest wins): env > review.md front-matter >
user `~/.config/opsx/models.yaml` > session default. (The project-layer
`openspec/opsx-models.yaml` is RETIRED — an existing one is ignored with a one-time
warning; pin per-project via change front-matter instead.)
The `opsx-loop` extension exports `OPSX_AUTHOR_MODEL` / `OPSX_REVIEW_MODELS` /
`OPSX_IMPL_MODEL` / `OPSX_AUTHOR_IN_SESSION` on loop start; unset roles fall back to
the session model. `opsx gate` fails an authoring artifact missing the
`<!-- authored: in-session -->` marker only when the `author` role is configured.

## Schema-managed vs skill-managed artifacts

**8 artifacts in the schema graph** (proposal, specs, clarify, design, analyze, review, tasks, plan): OpenSpec's CLI tracks these. `openspec status --json` reports completion. `openspec validate --strict` enforces structure.

**3 artifacts produced by skills, with templates in this schema** (verify.md, retrospective.md, ADR promotion): the opsx-* skills author these at the right lifecycle moment using the templates as references. They are NOT declared in `schema.yaml artifacts:` because:

- OpenSpec's `isComplete` check is existence-only; declaring optional artifacts perpetually breaks completion reporting.
- The schema has no per-Scale gating mechanism; declared artifacts apply to all changes regardless of Scale.
- ADRs writing outside the change dir via a `generates` glob match any pre-existing ADR and report themselves done before any work happens (verified against OpenSpec 1.3.0 source).

The templates are still available at `~/.local/share/openspec/schemas/opsx-superpowers/templates/` and the apply instruction in `schema.yaml` documents the skill contract for each.

## Capability hooks (graceful degradation)

When an artifact's instruction prefers a Superpowers-style capability (e.g., `verification-before-completion`), the schema invokes the locally-registered skill via the capability-hook lookup in `capability-hooks.md`. If no local skill matches, the artifact instruction's manual fallback executes. The schema **always works** without any Superpowers-style skills installed.

See `capability-hooks.md` for the current capability → skill mapping.

## Driving a change (the loop)

After `openspec-explore` freezes `intent.md`, drive the change to completion behind
the deterministic gate:

- **`opsx gate <change>`** — the single (primary) source of enforcement truth. Reads
  modes from `review.md` front-matter, runs required-artifacts-by-Scale, the
  `openspec/opsx-gates.yaml` validation manifest (+ `OPSX_VALIDATE`), and mode-aware
  verify/code-review verdicts (freshness-bound to an immutable `Diff Base SHA`). Exits
  0 when ready to archive; else prints `GATE-FAIL <check_id> <blocking> <message>`.
- **`openspec-loop` skill** — single orchestrator agent: each turn runs `opsx gate`,
  fixes the earliest blocking failure, delegates every review verdict to a blind
  subagent judged against the frozen baseline. Stops when the gate is green.
- **Loop runtime (adapter ladder)** — primary: the dedicated **`opsx-loop` pi
  extension** (`/opsx-loop <change>` or `/opsx-loop goal [text]`), which adds what the
  generic paths lack: per-turn worktree re-resolution, stall detection with the
  doneness gap-set ratchet, role-model env export, and goal/conversation kickoff.
  Alternative: the pi `goal` extension with a command-judge
  (`PI_GOAL_JUDGE_CMD='opsx gate <change>'`). Harness-agnostic fallback: the
  **`opsx loop`** bash driver (`AGENT_CMD`-parameterized, no stall detection —
  bounded 40-iteration default instead).

Enforcement lives below the harness (exit codes), so the same workflow runs on pi
today or another harness tomorrow by swapping one adapter. The `opsx-gates.yaml`
manifest + git/CI are where deterministic teeth live; the skills are prose the gate
backs up.

## Files in this schema

```
opsx-superpowers/
├── README.md                          # this file
├── schema.yaml                        # artifact graph (8) + apply discipline + skill contract
├── capability-hooks.md                # capability → local-skill mapping
└── templates/
    ├── constitution-template.md       # filled into project's openspec/constitution.md
    ├── domain-template.md             # filled into project's openspec/domain.md
    ├── opsx-models.yaml               # role model/provider config convention (opsx models CLI)
    │
    ├── # Schema-managed (tracked by openspec status):
    ├── proposal.md
    ├── spec.md                        # EARS reference + canonical AC ID + 5-property checklist
    ├── clarify.md                     # 3-pass findings tables
    ├── design.md                      # 4-point ADR-candidate test in Decisions block
    ├── analyze.md                     # 7 cross-artifact checks; EARS check is human-triage
    ├── review.md                      # mode switchboard + Diff Base SHA
    ├── tasks.md                       # task contracts + TDD-aware allow_new_files
    ├── plan.md                        # execution driver
    │
    ├── # Skill-managed (post-apply / pre-archive):
    ├── adr.md                         # MADR 4.0 short form (used by openspec-archive-change)
    ├── verify.md                      # 6 hard checks + canonical AC↔test grep + binary green/red
    └── retrospective.md               # 6 sections; promote-candidates use all 9 mcp-memory types
```

## Prerequisites

- **OpenSpec ≥ 1.3.0** (`openspec --version`)
- **Per-project**: `openspec/constitution.md` and `openspec/domain.md` (created via the `openspec-propose` skill on first non-XS change; templates in this schema)
- **Optional but recommended**: `~/.pi/agent/skills/clarify-spec/`, `adversarial-review-cycle`, `pi-subagents`, the `hindsight` memory MCP server (graceful degradation when absent)

## Authoring notes

- Markdown brevity is a feature, not a bug. Templates are kept under ~80 lines each. Fowler's "markdown review overload" critique applies — tables over prose, checklists over paragraphs, no duplication across artifacts.
- The artifact graph is a DAG declared in `schema.yaml`. Editing it is supported; deleting required artifacts breaks `openspec validate --strict`.
- There is deliberately NO `adr` schema artifact: ADR promotion is skill-managed at archive time (`openspec-archive-change` writes `<repo>/adr/ADR-NNNN-<slug>.md` from `templates/adr.md`), because a schema-level `generates` glob escaping the change directory is a validation bug, not a feature (see schema.yaml D11 rationale).
- The 5 EARS patterns are mandatory for new ACs; the analyze step blocks `WHEN`-on-error-conditions (must be `IF…THEN`).

## License

MIT (matches the chezmoi repo).

## See also

- OpenSpec project: <https://github.com/Fission-AI/OpenSpec>
- EARS reference: <https://alistairmavin.com/ears/>
- Kiro's deep-spec analysis (May 2026): <https://kiro.dev/blog/deep-spec-analysis/>
- Inspirations: pi-specdocs (ADR), ralphy-openspec (file contracts), Superpowers (Iron Law / verification-before-completion), Veath/openspec-spec-driven-superpowers (mode switchboard), danielhanold/superspec (pre-flight commit, verify, retrospective), intent-driven-dev/openspec-schemas (escape-glob ADR pattern)
