---
name: "OPSX: Apply"
description: Implement tasks from an OpenSpec change (delegates to the openspec-apply-change skill)
category: Workflow
tags: [workflow, artifacts, experimental]
---

Load and follow the **openspec-apply-change** skill (`~/.claude/skills/openspec-apply-change/SKILL.md`) for this request. Follow it exactly, including the schema branch: when the change's schema is `opsx-superpowers`, load `references/opsx-superpowers-mode.md` — worktree lifecycle (immutable merge-base `Diff Base SHA`), per-task file contracts, post-apply verify.md/code-review.md production, and the `opsx gate <change> --worktree <path>` completion gate.

Do not improvise an alternate apply flow: the skill is the single source of truth for this command. This command is deliberately a thin wrapper so the procedure cannot drift from the skill (docs/audits/2026-07-02-opsx-workflow-audit.md, finding 7).

$ARGUMENTS
