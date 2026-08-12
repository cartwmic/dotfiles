---
name: writing-skills
description: Creates and revises concise, portable agent skills. Use when authoring SKILL.md bundles.
---

# Writing Skills

## Goal

Capture reusable guidance that an agent would not reliably infer on its own.

**Core principle:** Prefer the smallest skill that changes behavior correctly. Apply KISS and YAGNI: start with one `SKILL.md`; add supporting files or scripts only after a real task proves they are needed.

## Choose the Right Home

Create a skill when guidance:

- applies across projects or repeated tasks;
- requires judgment rather than mechanical enforcement;
- is easy to forget or apply incorrectly; and
- will likely be reused.

Use something else when:

- project-specific convention → project agent instructions;
- one-off lesson → project documentation or no artifact;
- mechanical rule → formatter, linter, schema, test, or script;
- existing authoritative documentation already suffices → link to it.

## Portable Format

Every skill is a directory containing `SKILL.md`:

```text
skill-name/
└── SKILL.md
```

Minimal frontmatter:

```yaml
---
name: skill-name
description: States what the skill does and when it should be used.
---
```

Rules:

- `name` must match the parent directory.
- Use 1–64 lowercase letters, digits, and hyphens.
- Do not start or end with a hyphen or use consecutive hyphens.
- `description` must be non-empty and at most 1,024 characters.
- Describe capability and intended use. Keep workflow details in the body.
- Use only `name` and `description` unless another standard field or harness-specific feature is needed.

Optional standard fields include `license`, `compatibility`, `metadata`, and experimental `allowed-tools`. Omit them by default.

## Authoring Workflow

1. **State outcome.** Write one sentence describing what correct use accomplishes.
2. **Identify missing guidance.** Include only knowledge or decisions an agent is unlikely to supply reliably.
3. **Choose freedom level.** Match instruction precision to task fragility.
4. **Write minimal workflow.** Put required actions in execution order.
5. **Add one useful example.** Add none when prose is already clear.
6. **Dogfood on real work.** Use the skill manually, observe mistakes or waste, then revise only those points.
7. **Cut again.** Remove repetition, background knowledge, speculative branches, and unused resources.

## Match Freedom to Task

| Task shape | Guidance |
|---|---|
| Context-dependent; several valid approaches | Principles and heuristics |
| Preferred pattern; controlled variation | Pseudocode, template, or parameterized command |
| Fragile, deterministic, or easy to perform incorrectly | Exact steps or bundled script |

Do not prescribe exact mechanics where judgment is useful. Do not leave fragile operations to improvisation.

## Write Instructions Agents Can Execute

- Use direct, imperative steps.
- Put prerequisites before dependent actions.
- State required inputs, outputs, and stopping conditions.
- Explain non-obvious constraints briefly.
- Give a sensible default instead of a menu of equivalent choices.
- Use consistent terminology.
- Prefer concrete examples over abstract commentary.
- Avoid narratives about the session where guidance was discovered.
- Avoid absolute language unless rule is genuinely absolute.
- Do not repeat information already available from tool help or linked references.

For complex work, include a short checklist or validation loop:

```text
run → inspect result → fix reported issue → rerun until clean
```

## Progressive Disclosure

Keep `SKILL.md` as overview and operational path. Move content out only when it is large or conditionally relevant:

```text
skill-name/
├── SKILL.md
├── reference.md       # detailed material read only when needed
├── template.md        # reusable output shape
└── scripts/
    └── validate.py    # deterministic operation
```

Guidelines:

- Keep `SKILL.md` under 500 lines; prefer much less.
- Reference supporting files directly from `SKILL.md` with relative Markdown links.
- State when each supporting file should be read or script run.
- Avoid reference chains; keep supporting files one hop from `SKILL.md`.
- Add a table of contents to long reference files.
- Delete files that dogfooding never uses.

## Examples and Scripts

One strong example beats several weak variants. An example should be realistic, focused, and ready to adapt.

Bundle a script only when it provides determinism, saves repeated generation, or performs validation better than prose. Give it:

- clear arguments and output;
- explicit dependencies;
- useful errors;
- safe handling of expected edge cases; and
- a documented command showing how to run it.

Actually run bundled scripts before considering the skill complete.

## Review Checklist

### Scope

- [ ] Guidance is reusable and belongs in a skill.
- [ ] Skill has one clear job.
- [ ] Content addresses observed need, not imagined future need.

### Structure

- [ ] Directory and lowercase `name` match.
- [ ] Frontmatter is valid and minimal.
- [ ] Workflow appears in execution order.
- [ ] Supporting files are necessary, directly referenced, and one hop deep.

### Quality

- [ ] Instructions use appropriate freedom level.
- [ ] Inputs, outputs, validation, and stopping conditions are clear where needed.
- [ ] Examples add information rather than repetition.
- [ ] No duplicated, stale, or obvious material remains.
- [ ] Bundled scripts were executed successfully.

### Dogfood

- [ ] Invoke skill manually on real work.
- [ ] Fix observed ambiguity, omission, or waste.
- [ ] Do not add machinery for failures not yet observed.

## References

- [Agent Skills specification](https://agentskills.io/specification)
- [Anthropic skill authoring best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)
- [OpenAI Codex skills](https://developers.openai.com/codex/skills)
