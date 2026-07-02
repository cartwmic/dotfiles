---
name: "OPSX: Loop"
description: Drive an opsx-superpowers change to a green opsx gate via the openspec-loop orchestrator (delegates to the openspec-loop skill)
category: Workflow
tags: [workflow, loop, enforcement, experimental]
---

Load and follow the **openspec-loop** skill (`~/.claude/skills/openspec-loop/SKILL.md`) for this request: drive the named change to completion behind the deterministic gate — each cycle run `opsx gate <change>` (with `--worktree` when applicable), fix the EARLIEST blocking GATE-FAIL, delegate review/doneness verdicts to blind subagents, and stop ONLY when the gate exits 0. The loop never archives; report gate-green and hand control back to the user.

**Input**: a change name (e.g. `/opsx:loop add-clipboard-extension`).

Do not improvise an alternate loop flow: the skill is the single source of truth for this command. This command is deliberately a thin wrapper so the procedure cannot drift from the skill (docs/audits/2026-07-02-opsx-workflow-audit.md, finding 7).

$ARGUMENTS
