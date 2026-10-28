---
name: no-ai-slop
description: Detect or remove formulaic LLM-writing patterns while preserving facts, technical precision, and the writer's voice. Use when editing documents to sound authored, direct, or less AI-like, or when auditing text for AI-slop patterns without rewriting it.
---

# No AI Slop

Edit prose without replacing one generic model voice with another. Patterns are revision signals. They do not prove AI wrote the text.

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

When the draft is the repository owner's own writing, or when asked to repair a draft that reads as generated, read [voice-profile.md](voice-profile.md), identify the register, then read only that register's section in [voice-excerpts.md](voice-excerpts.md). Use 3–5 excerpts at most. The registers are opinion, design, specification, systems explainer, incident, review comments, tasking prompts, and casual/status. If none fits, use the draft alone and do not read the excerpts. Where voice-profile.md or voice-excerpts.md conflicts with this file, this file controls. Casual/status evidence comes from owner-supplied Slack and remains unmeasured. Keep its emoji, emphasis, and thank-you closers out of document registers. Review comments, PR reviews included, carry no thank-you; open with the first finding. A suspected generated draft cannot supply its own voice evidence.

Keep this analysis internal unless the user asks for it. The one exception is a first line in every report, `Voice: profile loaded|not loaded; register: <name>|none`, placed at the top of `Findings` or `What changed`.

## Protect Meaning

Preserve all claims, qualifications, causal relationships, and scope. Never invent facts, examples, statistics, quotations, citations, opinions, or sources.

Treat these spans as protected unless the user explicitly requests changes:

- code, commands, configuration, and quoted literals;
- URLs, citations, issue IDs, and version numbers;
- names, dates, quantities, percentages, and units;
- product terms, glossary terms, and domain-specific vocabulary; and
- uncertainty or limitation language.

Repeat a precise term. Do not cycle through synonyms. If meaning is unclear, ask; do not guess.

Every clause must trace to the source wording. A clause that adds irony, drama, an example, or an attitude the source does not contain is invented content, even when it sounds plausible. Cut it.

When drafting from an interview or dictation, use the owner's own words and details. Do not turn option labels or phrasings the agent wrote into prose for the owner.

## Editing Principles

- Preserve distinctive vocabulary, cadence, bluntness, humor, uncertainty, and useful imperfection.
- Leave strong sentences alone. Do not normalize every paragraph into the same polished shape.
- Cut empty framing before rewriting wording.
- Assert the claim you mean. Never build it by rejecting an alternative first.
- Prefer concrete facts, mechanisms, consequences, and judgments over abstract importance claims.
- Keep useful setup, digressions, and longer sentences when they add context or character.
- Use direct verbs when clearer, but do not ban passive voice or forms of “be.”
- Keep existing structure unless it obscures the argument.
- Never optimize for an AI-detector score. Optimize for clarity, specificity, fidelity, and voice.
- When the brief asks you to persuade, lay out the facts in causal order and let the reader draw the stakes. Do not add stakes clauses or end a paragraph on a kicker.

## Patterns to Inspect

A single word or construction is not enough. Edit when a pattern is empty, repeated, misleading, or mismatched to the voice. One entry below is an unconditional ban and takes no such judgment: **binary contrast templates**.

- **Throat clearing:** “Here's the thing,” “It's worth noting,” “In today's world.” Remove setup that delays the point.
- **Binary contrast templates:** banned. Any construction that reaches its point by first rejecting an alternative: “It's not X. It's Y.”, “not X, but Y”, “X, not Y”, “X rather than Y”, “less about X, more about Y”, “instead of X, Y”, “X in place of Y”, stat drama such as “X overall but only Y when…”, and negative lists such as “Not for A, not for B.” Delete the rejected half and assert the claim. For stat drama, give the second figure in parentheses or its own sentence, without “only.” If the rejection is load-bearing, split it out as its own standalone prohibition sentence (“Do not do X.”) placed after the claim. Exactly three things survive the ban: a negation with no replacement attached to it, `not` used as a data value inside an enumeration, and text inside code, commands, or quotation marks that must stay verbatim. Limitation or scope language is not a survivor. Rewrite it as a claim plus a standalone negation. Never satisfy this ban by weakening the claim.

**Contrast scan.** In both modes, search the whole document, not only changed passages, for `not`, `rather than`, `instead of`, `in place of`, `unlike`, `less about`, `but only`, and `yet only`. Read each hit with the sentence after it, since a contrast can cross a sentence boundary. Report every hit as `quote → rewritten | survivor (reason)`. In Detect mode, report each non-survivor under the pattern name below.
- **Faux-insight setups:** “What everyone misses,” “The uncomfortable truth.” Remove borrowed authority and support the claim.
- **Importance puffery:** “pivotal,” “transformative,” “a testament to.” Replace labels with a fact already in the draft that makes the point matter. If none exists, cut the label.
- **Trailing stakes:** a clause tacked onto a fact to restate why it matters. This covers participles (“highlighting,” “underscoring,” “showcasing”), “…, and X can mean Y,” and paired stakes such as “a missed deadline or a missed sale.” Cut the clause. Keep a consequence only when it adds a fact the reader lacks, and give it its own sentence.
- **Maxims and counterfactuals:** universal rules such as “Every X needs Y,” counterfactual punches such as “without X, we're guessing” or “flying blind,” and one-line openers that fit any document (“Cost and scale are coupled.”). State the specific fact from the draft that the maxim stands in for, or cut it. A general statement that follows from named specifics in the same passage and carries the writer's own hedge or example is not a maxim. Flag the shape when nothing concrete follows it.
- **Wrap-up generalizations:** a sentence after a list or example set that restates the items as an abstract thesis (“and then they become X,” “the pattern is Y”). Cut it, or name the specific case from the draft that it stands for.
- **Announced structure and restatement:** “This does two things,” “Two steps set the pace. One is… The other is…,” a paragraph whose last sentence restates its first from the other side, and mirrored or chiastic doublets (“their load and their incidents on our capacity and our on-call”). Name the items directly, state each point once, and drop the doublet's second half.
- **Weasel attribution:** “experts agree,” “studies show,” “many argue.” Name a source or remove the unsupported attribution.
- **Generic promotional language:** words such as “robust,” “streamline,” “unlock,” “leverage,” or “cutting-edge” when they hide a specific mechanism.
- **Interpretive metadiscourse:** “The key point is,” “This distinction matters,” “As you can see.” Let evidence carry emphasis when it already does.
- **Synonym cycling:** changing names for the same concept only to avoid repetition.
- **Robotic rhythm:** repeated sentence shapes, uniformly sized paragraphs, stacked fragments, or mechanically balanced lists. This includes echo kickers: a repeated verb phrase or word pair (“get done and get done fast”) closing a paragraph as a tagline.
- **Dramatic scaffolding:** colon reveals, “Question? Answer.” pairs, negative lists, or mic-drop fragments used as decoration.
- **Generic endings:** recap paragraphs, fake-profound kickers, or “In conclusion” after the argument has already ended.
- **Formatting slop:** decorative bold, emoji headings, needless micro-sections, or lists that obscure a simple relationship.
- **Punctuation habits:** clusters of em dashes or other punctuation used as a default rhythm. Keep punctuation that genuinely improves the sentence.

Use the portability test: if a sentence could move unchanged to an unrelated person, company, or product, it may be filler. Cut it or ground it in this subject. Apply it to the first and last sentence of every paragraph, where maxims and kickers collect.

## Workflow

1. Read the complete draft before changing it.
2. Identify purpose, core point, protected spans, and voice signals.
3. In Detect mode, report every material pattern and stop. If none appear, say so. Label each finding with the exact pattern name from Patterns to Inspect, without the trailing colon and without extra words. Report a portability failure under the pattern it matches. Order findings by position in the draft. A binary contrast template is always material. Any other pattern is material when it meets the empty, repeated, misleading, or mismatched test.
4. In Edit mode, make one minimum-effective editing pass.
5. Check all changed passages against [eval.md](eval.md) and collect every failed check. The contrast scan and the portability test cover the whole document.
6. If checks fail, make one targeted repair pass limited to affected passages; it may address several known failures. Recheck those passages. Do not run another general rewrite.
7. Restore original wording wherever fidelity remains uncertain. Restoring never brings back a binary contrast template; flag that passage instead. Flag every other unresolved passage and failed check for human review.
8. Deliver according to Edit mode: update requested files in place, or return full edited text. Include a concise `What changed` section. If no material edit was needed, return the original unchanged and say so.
9. In `What changed`, list every [eval.md](eval.md) check, each marked `pass`, `fail`, or `not run (reason)`. For the contrast scan, list every hit and its disposition. For the portability test, state how many paragraphs were examined and quote any failing sentence. List every flagged passage left for the owner. Do not claim the result is in the owner's voice; the owner decides that.

Stop after checks pass or unresolved failures are flagged. Repeated rewriting causes factual drift, synonym churn, and voice flattening.

## Output Shapes

Detect:

```markdown
## Findings
- **Pattern name:** “quoted passage” — brief problem; suggested fix.
```

With no findings: `No material slop patterns found.`

Edit returned in chat:

```markdown
[full edited document]

## What changed
- Short description of material edits, or “No material edit needed.”
```

For in-place file edits, report changed paths. Do not repeat full files.

## Attribution

Adapted from Peter Yang's [`no-ai-slop`](https://github.com/petergyang/no-ai-slop) under the bundled [MIT License](LICENSE). This version adds exemplar-grounded house voice, protected factual spans, word rules that depend on context, a hard ban on binary contrast templates, detector-gaming rejection, and a bounded editing loop.
