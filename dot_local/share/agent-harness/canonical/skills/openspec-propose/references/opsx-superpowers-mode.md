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
What Scale tier? (XS / S / M / L / XL)
  XS: typo/comment/single-line config — proposal + tasks only
  S:  single-file bug/small refactor — + specs, plan
  M:  typical feature — full graph; verify recommended
  L:  cross-capability/breaking — + ADR candidates flagged;
                                  adversarial-review invoked at analyze
  XL: new capability/migration — + retrospective required pre-archive
```

Use the **AskUserQuestion tool**. Default to S if unclear.

Also ask:
```
Spec Level? (spec-anchored / spec-first / spec-as-source)
  Default: spec-anchored (recommended; matches OpenSpec model)
  spec-as-source emits an MDD-trade-offs warning (experimental only)
```

Default to spec-anchored. If user picks spec-as-source, surface the warning before continuing.

Record the choices; they'll be written into `review.md` when that artifact is authored.

## Artifact loop — Scale-aware

Walk artifacts in dependency order returned by `openspec status --change <name> --json`. For each `ready` artifact, decide via Scale:

| Scale | proposal | specs | clarify | design | analyze | review | tasks | plan |
|---|---|---|---|---|---|---|---|---|
| XS | ✓ | skip | skip | skip | skip | skip | ✓ | skip |
| S  | ✓ | ✓ | ambiguity-only | skip | checks 1,2,7 only | skip | ✓ | ✓ (simple list) |
| M  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| L  | ✓ | ✓ | ✓ | ✓ | + adversarial-review | ✓ | ✓ | ✓ |
| XL | ✓ | ✓ | ✓ | ✓ | + adversarial-review | ✓ | ✓ | ✓ |

When an artifact is SKIPPED, write a one-line placeholder `<artifact>.md` with content like `<!-- Skipped per Scale=XS. -->` so the file exists and `openspec status` reports it done. This is the most honest workaround for OpenSpec's existence-only completion check; the placeholder makes the skip visible.

When an artifact is AUTHORED, follow its `instruction` from `openspec instructions <artifact> --change <name> --json` AND apply the additions below.

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

```
Invoking ~/.pi/agent/skills/clarify-spec/ via Skill tool against
openspec/changes/<name>/specs/.

Pass 1 (ambiguity), Pass 2 (inconsistency), Pass 3 (completeness,
priority-capped at 10 per spec).
```

Wait for clarify.md output. For each `unanswered` finding, prompt the user with the 2-option question. Update clarify.md status. Findings marked `deferred` are auto-copied into analyze.md's outstanding-risks section when that artifact is authored.

Block design generation if any clarify finding remains `unanswered`.

### analyze artifact: capability hook for adversarial-review

When Scale ≥ L, dispatch via:

```
Skill tool → adversarial-review-cycle
Inputs:
  - proposal.md
  - specs/**/spec.md
  - clarify.md (resolved findings)
  - design.md
Models: opus + gpt-5 (or whichever defaults the skill specifies)
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
Scale:       <S | M | L | XL>
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
