# openspec-propose under schema: opsx-superpowers

Loaded when step 2.5 detects `schemaName == "opsx-superpowers"`. Replaces the default artifact loop with the schema's 8-artifact graph plus quality gates.

## Pre-flight: project setup

1. **Check `openspec/constitution.md`.** If missing, prompt the user:
   ```
   This project uses opsx-superpowers but has no constitution.md.
   Skill `openspec-propose` needs principles to reference. Options:
     A) Use the template at
        ~/.local/share/openspec/schemas/opsx-superpowers/templates/constitution-template.md
        and let me draft an initial version for review.
     B) Skip (only safe for Scale=XS changes; the analyze artifact's
        Check 1 will report "no constitution to check").
     C) Cancel — I'll fill in constitution.md first.
   ```
   For B, proceed with a console warning. For C, exit.

2. **Check `openspec/domain.md`.** Same pattern with the domain-template.md.

## Up-front mode picker

Before the artifact loop, ask the user:

```
What Scale tier? (XS / S / M) — plus optional full_rigor for the M tier
  XS: typo/comment/single-line config — proposal + tasks only
  S:  single-file bug/small refactor — + specs, plan
  M:  typical feature — full graph; clarify open questions fold into
      proposal.md ## Open Questions, analyze is deterministic-only, doneness
      rides the code-review dispatch; verify recommended
  M + full_rigor: true — cross-capability / breaking / new-capability /
      migration (the former L and XL): standalone clarify.md + blind analyze
      dispatch + independently dispatched doneness judge + ADR candidates +
      adversarial-review invoked at analyze + retrospective required pre-archive
```

Use the **AskUserQuestion tool**. Default to S if unclear. A Scale outside XS|S|M,
or a non-boolean full_rigor, fails the gate closed — never silently defaulted. (The
former `L`/`XL` labels map to `Scale: M` + `full_rigor: true`.)

Also ask:
```
Spec Level? (spec-anchored / spec-first / spec-as-source)
  Default: spec-anchored (recommended; matches OpenSpec model)
  spec-as-source emits an MDD-trade-offs warning (experimental only)
```

Default to spec-anchored. If user picks spec-as-source, surface the warning before continuing.

Record the choices; they'll be written into `review.md` when that artifact is authored.

## Artifact loop — Scale-aware

Walk artifacts in dependency order returned by `openspec status --change <name> --json`. For each `ready` artifact, decide via Scale.

**review.md is NEVER skipped at any Scale** — it is authored at every Scale (XS/S/M) because it is the Scale/mode source the gate reads first and fails CLOSED without. XS/S skip only the OTHER artifacts per the D3 required-artifact table (`opsx-gate-enforcement.required-artifact-by-scale`); a skipped review.md would make the change ungateable.

| Scale | proposal | specs | clarify | design | analyze | review | tasks | plan |
|---|---|---|---|---|---|---|---|---|
| XS | ✓ | skip | skip | skip | skip | ✓ | ✓ | skip |
| S  | ✓ | ✓ | ambiguity-only | skip | checks 1,2,7 only | ✓ | ✓ | ✓ (simple list) |
| M  | ✓ | ✓ | in-proposal ¹ | decision-gated ³ | deterministic-only ² | ✓ | ✓ | ✓ |
| M + full_rigor | ✓ | ✓ | ✓ standalone | ✓ | ✓ blind + adversarial-review | ✓ | ✓ | ✓ |

¹ **Plain-M clarify-in-proposal:** at Scale M WITHOUT full_rigor, do NOT author a
standalone `clarify.md`. Instead put the clarify open questions inline in
`proposal.md` under a `## Open Questions` heading and resolve them there under the
SAME 2-option self-resolution discipline (each finding gets a 2-option question the
author resolves in-place). A `full_rigor: true` change authors the standalone blind
`clarify.md` as before.
² **Plain-M deterministic-only analyze:** at Scale M WITHOUT full_rigor, analyze is
the deterministic checks only (tiling / traceability / EARS lint) run inline by the
orchestrator and recorded in a short analyze section of `proposal.md` or `plan.md` —
NO blind analyze dispatch and NO standalone `analyze.md`. `full_rigor: true` runs the
full blind analyze dispatch (+ adversarial-review).
³ **Plain-M decision-gated design:** at Scale M WITHOUT full_rigor, `design.md` is
NOT a required artifact (D3/D5) — author it ONLY when a decision warrants it (a
non-trivial trade-off / the ADR 4-point test), and it is decision-gated, not gate-
required. `full_rigor: true` makes `design.md` required (the former L/XL full set
always carried design). review.md is authored (✓) at EVERY tier.

When an artifact is SKIPPED, write NO placeholder `<artifact>.md` — skipped artifacts simply do not exist. The gate derives its required set from Scale (the D3 required-artifact table), so an absent optional artifact is correct; `openspec status` will report the skipped artifact as not-done and that is expected (the schema's static artifact graph does not reflect Scale-driven skips). A placeholder review.md in particular would break Scale parsing and make the change ungateable, so review.md is authored for real at every Scale and never stubbed. Log the deliberate skip (e.g. `Scale=XS: skipping specs/clarify/design/analyze/plan`) so it is visible.

When an artifact is AUTHORED, follow its `instruction` from `openspec instructions <artifact> --change <name> --json` AND apply the additions below.

### Model & provider configuration (opsx models)

Role models/providers are configured harness-neutrally and resolved via the
`opsx models` CLI (env `OPSX_*_MODEL` exported by the opsx-loop extension, or
`opsx models <role> --change <name>` directly). All values are already
provider-qualified; pass them through verbatim. Unset roles fall back to the
session/default model — never hard-fail.

- **Author in-session by default.** Author the artifacts in THIS (parent) session.
  Do NOT delegate authoring to a subagent unless `OPSX_AUTHOR_IN_SESSION` (or
  `opsx models author-in-session --change <name>`) is `false`. As each authoring
  artifact (`proposal`/`intent`/`design`/`clarify`/`tasks`/`plan`/`specs/**`) is
  written in-session, include the literal marker line `<!-- authored: in-session -->`
  in it (an inert HTML comment) — `opsx gate` checks for it when an `author` model
  is configured. On opt-out, dispatch the authoring subagent with the `author`
  model and omit the marker.
- **Review dispatch.** When dispatching blind review subagents, dispatch one
  reviewer per configured `review` model (newline/comma-delimited
  `OPSX_REVIEW_MODELS`), passing each as the subagent `model:`. Unset → use the
  skill's defaults.

### specs artifact: EARS-pattern picker

Before drafting any spec.md, ask the user (per capability):

```
For capability <name>, which AC patterns are predominantly needed?
Choose all that apply:
  [ ] Ubiquitous (THE <system> SHALL …) — invariants
  [ ] Event-driven (WHEN … THE … SHALL …) — nominal triggers
  [ ] State-driven (WHILE … THE … SHALL …) — preconditions
  [ ] Optional (WHERE feature, THE … SHALL …) — feature flags
  [ ] Unwanted (IF … THEN THE … SHALL …) — errors/exceptions
```

Use the answer to guide drafting (don't force all patterns; the picker is hint, not requirement).

After drafting, compute canonical AC IDs for every Requirement and surface them to the user:
```
Generated AC IDs:
  user-export.user-can-export-data
  user-export.export-rejects-empty-dataset
  ...
Use these in tests; the verify gate greps for literal matches.
```

### clarify artifact: invoke clarify-spec skill

Only at Scale S (ambiguity pass) or `full_rigor: true` (full standalone clarify). At
plain Scale M the clarify open questions live in `proposal.md ## Open Questions`
instead (footnote ¹ above) — skip the standalone clarify.md.

```
Invoking ~/.pi/agent/skills/clarify-spec/ via Skill tool against
openspec/changes/<name>/specs/.

Pass 1 (ambiguity), Pass 2 (inconsistency), Pass 3 (completeness,
priority-capped at 10 per spec).
```

Wait for clarify.md output. For each `unanswered` finding, prompt the user with the 2-option question. Update clarify.md status. Findings marked `deferred` are auto-copied into analyze.md's outstanding-risks section when that artifact is authored.

Block design generation if any clarify finding remains `unanswered`.

### analyze artifact: capability hook for adversarial-review

At plain Scale M (no full_rigor), skip this dispatch: run the deterministic analyze
checks inline and record them in `proposal.md`/`plan.md` (footnote ² above). When
`full_rigor: true`, dispatch via:

```
Skill tool → adversarial-review-cycle
Inputs:
  - proposal.md
  - specs/**/spec.md
  - clarify.md (resolved findings)
  - design.md
Models: the configured `review` set (`OPSX_REVIEW_MODELS` / `opsx models review
        --change <name>`), one reviewer per entry; else the skill defaults
        (opus + gpt-5)
Rounds: per skill defaults
```

Record round-by-round findings as appendices in analyze.md. Treat any blocker finding as halt-and-fix before continuing to tasks.

### tasks artifact: contract field prompts

When authoring tasks.md, for each task that touches code (not pure documentation tasks), ASK the user whether to declare a file contract:
```
Task 4.2 ("Implement export function"):
  intent? (fix / feature / refactor / infra)
  Restrict file scope? If yes, list files_allowed globs.
  Forbid any paths? files_forbidden globs.
  allow_new_files? (default true)
```

Skip the prompt for tasks the user marks as "no contract needed" (docs, comments, etc.).

## Wrap-up

After all required artifacts are done (per the Scale table above):

```
## Proposal Complete

Change:      <name>
Schema:      opsx-superpowers
Scale:       <XS | S | M>  (full_rigor: <true|false>)
Spec Level:  spec-anchored

Artifacts authored:
  ✓ proposal.md
  ✓ specs/<capability>/spec.md     (N requirements; AC IDs listed)
  ✓ clarify.md                     (N findings, 0 unanswered)
  ✓ design.md                      (N Decisions; M ADR candidates)
  ✓ analyze.md                     (N findings; 0 blockers)
  ✓ review.md                      (modes recorded)
  ✓ tasks.md                       (N tasks with K contracts)
  ✓ plan.md                        (N plan steps)

Next: /opsx-apply <name>
```

## Schema-only fallback

If any required capability hook (clarify-spec, adversarial-review-cycle) cannot resolve, log `[DEGRADED MODE] no <capability> skill available; running manual fallback` and execute the procedure inline using the schema artifact instruction's manual prose. Never silently skip.
