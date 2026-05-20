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
| Mode switchboard | no | yes — `review.md` with 8 modes (Scale, Execution, Verification, Debug, Review-Status, Delegation, Worktree, Spec-Level) |
| Scale-adaptive artifact gating | no | yes — XS skips heavy artifacts; M is the typical full graph; L/XL add ADR + adversarial review + retrospective |
| Pre-flight commit before worktree | no | yes (apply step captures Worktree Base SHA for file-contract diffs) |
| Per-task file contracts | no | yes — `files_allowed` / `files_forbidden` / `allow_new_files` + `intent: fix\|feature\|refactor\|infra` |
| AC↔test ID mapping as verify gate | no | yes — `verify.md` (skill-produced) blocks archive if mapping incomplete; canonical AC ID format `<capability>.<requirement-slug>` |
| Retrospective with mcp-memory promotion | no | yes — pre-archive `retrospective.md` (skill-produced) with `Promote candidates` (all 9 mcp-memory types) parsed by `openspec-archive-change` |
| Adversarial review at high stakes | manual | invoked automatically by `analyze` artifact when `Scale ≥ L` |

## Scale tiers

Pick one in `review.md` (`Scale: <value>`). The schema's apply rules gate required artifacts on this choice.

| Scale | Example | Required artifacts | Optional |
|---|---|---|---|
| **XS** | typo, comment fix, single-line config tweak | proposal, tasks | everything else |
| **S** | single-file bug fix, small refactor | proposal, specs, tasks, plan | clarify, design, analyze, review, verify, adr, retrospective |
| **M** | typical feature, cross-file but single capability | proposal, specs, clarify, design, analyze, review, tasks, plan, verify | adr (unless decision passes 4-point test), retrospective |
| **L** | cross-capability change, breaking change, new ADR-worthy decisions | + adr, + adversarial-review-cycle from analyze | retrospective |
| **XL** | new capability, migration, multi-week project | full graph including retrospective | — |

Heuristic: if you're unsure, pick S. If clarify produces blockers, the schema will tell you to upgrade.

## Mode reference (in `review.md`)

Each mode has a controlled vocabulary. Default values shown in **bold**.

| Mode | Values | Effect |
|---|---|---|
| `Scale` | XS / **S** / M / L / XL | Gates which artifacts are required for apply completion |
| `Execution Mode` | **standard** / tdd-preferred / tdd-required | tdd-required: each task starts with a failing test, then minimal impl |
| `Verification Mode` | inline-only / **retained-recommended** / retained-required | retained-required: `verify.md` is mandatory before archive |
| `Debug Mode` | **standard** / systematic-debugging | systematic-debugging: `plan.md` MUST contain `Observed Failure` and `Debugging Trail` before code changes |
| `Review Status` | **not-requested** / requested / findings-received / resolved | State machine for `adversarial-review-cycle` invocation |
| `Delegation Mode` | **single-agent** / subagent-eligible / subagent-required | subagent-*: `openspec-apply-change` dispatches tasks via `pi-subagents` |
| `Worktree Mode` | **same-tree** / worktree-eligible / worktree-required | worktree-required: every task runs in `git worktree`, main agent owns writeback |
| `Spec Level` | **spec-anchored** / spec-first / spec-as-source | spec-anchored = OpenSpec's natural mode; spec-as-source warns about MDD-era trade-offs |

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

## Files in this schema

```
opsx-superpowers/
├── README.md                          # this file
├── schema.yaml                        # artifact graph (8) + apply discipline + skill contract
├── capability-hooks.md                # capability → local-skill mapping
└── templates/
    ├── constitution-template.md       # filled into project's openspec/constitution.md
    ├── domain-template.md             # filled into project's openspec/domain.md
    │
    ├── # Schema-managed (tracked by openspec status):
    ├── proposal.md
    ├── spec.md                        # EARS reference + canonical AC ID + 5-property checklist
    ├── clarify.md                     # 3-pass findings tables
    ├── design.md                      # 4-point ADR-candidate test in Decisions block
    ├── analyze.md                     # 7 cross-artifact checks; EARS check is human-triage
    ├── review.md                      # mode switchboard + Worktree Base SHA
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
- **Optional but recommended**: `~/.pi/agent/skills/clarify-spec/`, `adversarial-review-cycle`, `pi-subagents`, `mcp_memory_store_memory` (graceful degradation when absent)

## Authoring notes

- Markdown brevity is a feature, not a bug. Templates are kept under ~80 lines each. Fowler's "markdown review overload" critique applies — tables over prose, checklists over paragraphs, no duplication across artifacts.
- The artifact graph is a DAG declared in `schema.yaml`. Editing it is supported; deleting required artifacts breaks `openspec validate --strict`.
- `adr` artifact's `generates: ../../../adr/ADR-*.md` is intentional — ADRs escape the change directory so they survive `openspec archive`.
- The 5 EARS patterns are mandatory for new ACs; the analyze step blocks `WHEN`-on-error-conditions (must be `IF…THEN`).

## License

MIT (matches the chezmoi repo).

## See also

- OpenSpec project: <https://github.com/Fission-AI/OpenSpec>
- EARS reference: <https://alistairmavin.com/ears/>
- Kiro's deep-spec analysis (May 2026): <https://kiro.dev/blog/deep-spec-analysis/>
- Inspirations: pi-specdocs (ADR), ralphy-openspec (file contracts), Superpowers (Iron Law / verification-before-completion), Veath/openspec-spec-driven-superpowers (mode switchboard), danielhanold/superspec (pre-flight commit, verify, retrospective), intent-driven-dev/openspec-schemas (escape-glob ADR pattern)
