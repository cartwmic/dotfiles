---
name: no-ai-slop
description: Detect or remove formulaic LLM-writing patterns while preserving facts, technical precision, and the writer's voice. Use when editing documents to sound authored, direct, or less AI-like, or when auditing text for AI-slop patterns without rewriting it.
---

# No AI Slop

Edit prose without replacing one generic model voice with another. Treat patterns as revision signals, not proof that AI wrote the text.

## Modes

**Detect** when the user asks to audit, scan, flag, or assess text without changing it. For each material finding:

- name the pattern;
- quote the affected passage;
- explain the problem briefly; and
- suggest the kind of fix, without rewriting the document.

Do not assign an AI probability or guess who wrote the text.

**Edit** by default when the user asks to improve supplied prose. Make the minimum effective edit. When the user asks to edit a repository file, modify that file in place and report its path plus a short `What changed` section. Otherwise, return the edited text and `What changed`. Never modify a file in Detect mode.

If no draft or document path is available, ask for one. Ask about audience or intended effect only when context cannot resolve it.

## Establish Voice

Before editing, identify the document's purpose and up to 3–5 evidence-supported voice signals worth preserving, such as:

- vocabulary and technical register;
- sentence and paragraph rhythm;
- directness, formality, humor, or uncertainty;
- characteristic asides or rough edges; and
- how the writer opens, transitions, and concludes.

Use up to 3–5 short, relevant examples when the user provides them or project instructions identify accepted documents. Do not search broadly for examples. If none are available, infer voice from the draft itself. Prefer observed traits over labels such as “human,” “engaging,” or “professional.” Do not copy example content or force imitation where genres differ.

When the draft is the repository owner's own writing, or when asked to make a draft read as authored rather than generated, read [voice-profile.md](voice-profile.md) for the evidence-derived house voice and [voice-excerpts.md](voice-excerpts.md) for exemplars. Match the register first — opinion, specification, design, incident, and casual/status writing differ in that profile — then apply its rules and countable checks. Casual/status is owner-supplied Slack, not part of the original measured set; do not import its emoji, italics-for-emphasis, or thank-you closers into the document registers. Do not infer voice from the draft alone when the draft is suspected of being generated: the draft's voice is the thing under repair.

Keep this analysis internal unless the user asks for it.

## Protect Meaning

Preserve all claims, qualifications, causal relationships, and scope. Never invent facts, examples, statistics, quotations, citations, opinions, or sources.

Treat these spans as protected unless the user explicitly requests changes:

- code, commands, configuration, and quoted literals;
- URLs, citations, issue IDs, and version numbers;
- names, dates, quantities, percentages, and units;
- product terms, glossary terms, and domain-specific vocabulary; and
- uncertainty or limitation language.

Repeat a precise term rather than cycling through synonyms. If meaning is unclear, ask instead of guessing.

## Editing Principles

- Preserve distinctive vocabulary, cadence, bluntness, humor, uncertainty, and useful imperfection.
- Leave strong sentences alone. Do not normalize every paragraph into the same polished shape.
- Cut empty framing before rewriting wording.
- Prefer concrete facts, mechanisms, consequences, and judgments over abstract importance claims.
- Keep useful setup, digressions, and longer sentences when they add context or character.
- Use direct verbs when clearer, but do not ban passive voice or forms of “be.”
- Keep existing structure unless it obscures the argument.
- Never optimize for an AI-detector score. Optimize for clarity, specificity, fidelity, and voice.

## Patterns to Inspect

A single word or construction is not enough. Edit when a pattern is empty, repeated, misleading, or mismatched to the voice.

- **Throat clearing:** “Here's the thing,” “It's worth noting,” “In today's world.” Remove setup that delays the point.
- **Binary contrast templates:** “It's not X. It's Y.” State the useful claim directly unless contrast carries real meaning.
- **Faux-insight setups:** “What everyone misses,” “The uncomfortable truth.” Remove borrowed authority and support the claim.
- **Importance puffery:** “pivotal,” “transformative,” “a testament to.” Replace labels with the fact that makes the point matter.
- **Superficial analysis:** trailing clauses beginning with “highlighting,” “underscoring,” or “showcasing” that restate significance instead of explaining consequence.
- **Weasel attribution:** “experts agree,” “studies show,” “many argue.” Name a source or remove the unsupported attribution.
- **Generic promotional language:** words such as “robust,” “streamline,” “unlock,” “leverage,” or “cutting-edge” when they hide a specific mechanism.
- **Interpretive metadiscourse:** “The key point is,” “This distinction matters,” “As you can see.” Let evidence carry emphasis when it already does.
- **Synonym cycling:** changing names for the same concept only to avoid repetition.
- **Robotic rhythm:** repeated sentence shapes, uniformly sized paragraphs, stacked fragments, or mechanically balanced lists.
- **Dramatic scaffolding:** colon reveals, “Question? Answer.” pairs, negative lists, or mic-drop fragments used as decoration.
- **Generic endings:** recap paragraphs, fake-profound kickers, or “In conclusion” after the argument has already ended.
- **Formatting slop:** decorative bold, emoji headings, needless micro-sections, or lists that obscure a simple relationship.
- **Punctuation habits:** clusters of em dashes or other punctuation used as a default rhythm. Keep punctuation that genuinely improves the sentence.

Use the portability test: if a sentence could move unchanged to an unrelated person, company, or product, it may be filler. Cut it or ground it in this subject.

## Workflow

1. Read the complete draft before changing it.
2. Identify purpose, core point, protected spans, and voice signals.
3. In Detect mode, report every material pattern and stop. If none appear, say so.
4. In Edit mode, make one minimum-effective editing pass.
5. Check all changed passages against [eval.md](eval.md) and collect every failed check.
6. If checks fail, make one targeted repair pass limited to affected passages; it may address several known failures. Recheck those passages. Do not run another general rewrite.
7. Restore original wording wherever fidelity remains uncertain. Flag every other unresolved passage and failed check for human review.
8. Deliver according to Edit mode: update requested files in place, or return full edited text. Include a concise `What changed` section. If no material edit was needed, return the original unchanged and say so.

Stop after checks pass or unresolved failures are flagged. Repeated rewriting causes factual drift, synonym churn, and voice flattening.

## Output Shapes

Detect:

```markdown
## Findings
- **Pattern:** “quoted passage” — brief problem; suggested fix.
```

With no findings: `No material slop patterns found.`

Edit returned in chat:

```markdown
[full edited document]

## What changed
- Short description of material edits, or “No material edit needed.”
```

For in-place file edits, report changed paths instead of repeating full files.

## Attribution

Adapted from Peter Yang's [`no-ai-slop`](https://github.com/petergyang/no-ai-slop) under the bundled [MIT License](LICENSE). This version adds exemplar-grounded house voice, protected factual spans, contextual rather than blanket word rules, detector-gaming rejection, and a bounded editing loop.
