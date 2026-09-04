# No AI Slop Check

Run after one editing pass. Inspect changed passages against original draft. This checklist tests the policy in `SKILL.md`; when wording conflicts, `SKILL.md` controls.

## Fidelity

- No claim, qualifier, causal relationship, scope, or uncertainty changed.
- No fact, example, statistic, quotation, citation, opinion, or source was invented.
- Code, commands, configuration, URLs, identifiers, versions, names, dates, quantities, units, and domain terms remain exact unless user requested changes.
- Precise repeated terms were not replaced with ambiguous synonyms.

## Voice

- Core point and observed voice signals remain recognizable.
- Strong or distinctive sentences were left alone.
- Changes did not make every sentence or paragraph uniformly polished.
- When house examples were available, they guided style without leaking their content or forcing another genre's structure.

## Quality

- Zero binary contrast templates survive or were introduced. Search changed passages for `not … but`, `, not `, `rather than`, `instead of`, `less about … more about`, and `It's not X. It's Y.` Every hit is a failure unless it is a negation with no replacement attached, `not` as a data value in an enumeration, or a protected span.
- Material formulaic patterns were removed or grounded in specific content.
- Cuts and rewrites are proportional to actual problems.
- New wording is clearer or more specific. No synonym churn.
- Structure and formatting changed only where they impeded the document's job.
- No decision relied on an AI-detector score or tried to mimic detector heuristics.
