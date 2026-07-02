---
description: Propose a new change - create it and generate all artifacts in one step (delegates to the openspec-propose skill)
---

Load and follow the **openspec-propose** skill (`~/.pi/agent/skills/openspec-propose/SKILL.md`) for this request. Follow it exactly, including:

- passing `--schema` per the project's `openspec/config.yaml` at `openspec new change`, and
- the step-2.5 schema branch: when `schemaName == "opsx-superpowers"`, load `references/opsx-superpowers-mode.md` (Scale + Spec Level prompt, EARS picker, clarify/analyze invocations, adversarial review at Scale ≥ L).

Do not improvise an alternate propose flow: the skill is the single source of truth for this command. This prompt is deliberately a thin wrapper so the procedure cannot drift from the skill (see docs/audits/2026-07-02-opsx-workflow-audit.md, finding 7).

$ARGUMENTS
