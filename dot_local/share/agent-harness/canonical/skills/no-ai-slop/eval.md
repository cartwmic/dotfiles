# No AI Slop Check

Run after one editing pass. Inspect changed passages against original draft. The contrast scan and the portability test cover the whole document. This checklist tests the policy in `SKILL.md`; when wording conflicts, `SKILL.md` controls.

## Fidelity

- No claim, qualifier, causal relationship, scope, or uncertainty changed.
- No fact, example, statistic, quotation, citation, opinion, or source was invented.
- Each changed clause traces to source wording. No irony, drama, or attitude was added that the source lacks.
- When drafted from an interview or dictation, wording comes from the owner's own words, not from option labels the agent wrote.
- Code, commands, configuration, URLs, identifiers, versions, names, dates, quantities, units, and domain terms remain exact unless user requested changes.
- Precise repeated terms were not replaced with ambiguous synonyms.

## Voice

- Core point and observed voice signals remain recognizable.
- Strong or distinctive sentences were left alone.
- Changes did not make every sentence or paragraph uniformly polished.
- When house examples were available, they guided style without leaking their content or forcing another genre's structure.

## Quality

- Zero binary contrast templates survive or were introduced. Run the contrast scan defined in SKILL.md over the whole document. Every hit not listed as rewritten or as one of the three survivors fails.
- Material formulaic patterns were removed or grounded in specific content.
- No trailing stakes clause, maxim, counterfactual punch, or announced structure survives unless it adds a fact the reader lacks.
- No wrap-up sentence restates a list as an abstract thesis. No paragraph ends on an echo kicker (a repeated phrase used as a tagline).
- The first and last sentence of every paragraph say something specific to this subject. Neither restates the other, and neither could move unchanged into another product's document.
- Cuts and rewrites are proportional to actual problems.
- New wording is clearer or more specific. No synonym churn.
- Structure and formatting changed only where they impeded the document's job.
- No decision relied on an AI-detector score or tried to mimic detector heuristics.

## Reporting

- The report lists every check above, each marked `pass`, `fail`, or `not run (reason)`. The contrast scan lists every hit with its disposition. The portability check states how many paragraphs it examined and quotes any failing sentence.
- The report begins with the `Voice:` line defined in SKILL.md.
- The report lists every flagged passage left for the owner.
- The report does not claim the result matches the owner's voice.
