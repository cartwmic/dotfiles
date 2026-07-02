---
description: Archive a completed change (delegates to the openspec-archive-change skill; gate-guarded)
---

Load and follow the **openspec-archive-change** skill (`~/.pi/agent/skills/openspec-archive-change/SKILL.md`) for this request. Follow it exactly, including:

- the schema branch: when the change's schema is `opsx-superpowers`, load `references/opsx-superpowers-mode.md` and enforce ALL archive HARD-GATEs (gate-green via `opsx gate <change>`, verify.md, code-review.md, doneness, ADR promotion, memory promotion). NEVER perform a plain move-to-archive for an opsx-superpowers change — that bypasses every enforcement control.

Do not improvise an alternate archive flow: the skill is the single source of truth for this command. This prompt is deliberately a thin wrapper so the procedure cannot drift from the skill (see docs/audits/2026-07-02-opsx-workflow-audit.md, finding 7).

$ARGUMENTS
