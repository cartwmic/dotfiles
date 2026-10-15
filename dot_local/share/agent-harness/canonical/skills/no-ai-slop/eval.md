# No AI Slop Check

Run after one editing pass. Inspect changed passages against original draft. This checklist tests the policy in `SKILL.md`; when wording conflicts, `SKILL.md` controls.

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

- Zero binary contrast templates survive or were introduced. Search changed passages for `not … but`, `, not `, `rather than`, `instead of`, `in place of`, `but only`, `yet only`, `less about … more about`, and `It's not X. It's Y.` Every hit is a failure unless it is a negation with no replacement attached, `not` as a data value in an enumeration, or a protected span.
- Material formulaic patterns were removed or grounded in specific content.
- No trailing stakes clause, maxim, counterfactual punch, or announced structure survives unless it adds a fact the reader lacks.
- No wrap-up sentence restates a list as an abstract thesis. No paragraph ends on an echo kicker (a repeated phrase used as a tagline).
- The first and last sentence of each changed paragraph say something specific to this subject. Neither restates the other, and neither could move unchanged into another product's document.
- Cuts and rewrites are proportional to actual problems.
- New wording is clearer or more specific. No synonym churn.
- Structure and formatting changed only where they impeded the document's job.
- No decision relied on an AI-detector score or tried to mimic detector heuristics.

## Reporting

- The report lists every check above that ran, with its result, and every flagged passage left for the owner.
- The report does not claim the result matches the owner's voice.
