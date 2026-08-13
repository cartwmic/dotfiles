# House voice profile

Evidence-derived writing profile for the repository owner. Load this in Edit mode when the
target document is the owner's own writing, or when asked to make a draft read as authored
rather than generated. Pair with [voice-excerpts.md](voice-excerpts.md).

Derived from six documents the owner wrote himself: an opinionated tooling comparison, an
evaluation-metrics specification, a system design produced under deadline, a cross-service
systems explainer, and two post-incident reviews. Each document was analysed independently
with no access to the others. Only traits that converged across analyses appear here.

Internal service names, regions, and product terms in the excerpts are genericised.
Sentence shape is preserved verbatim, because shape is what carries voice.

## 0. Three registers, not one

Treating this as a single style produces the wrong output. The measured split:

| Register | First person | Em dash / semicolon | Median sentence |
|---|---|---|---|
| Opinion / recommendation | heavy `I`, 3.15:1 over impersonal | none at all | 13.5 w |
| Specification | almost none, 1:15.8 | frequent em dash and colon | 15 w |
| Design / decision | 81% impersonal, `we` common, `I` rare | rare | 14.5 w |
| Incident review | zero `I`, `we` only subordinated | none | 14–19 w |

Match the register before matching anything else. A PRD or design doc sits between design
and specification: impersonal by default, `we` for commitments, `I` only for a judgment
being personally staked.

## 1. Rules

**V1. `I` appears only where a claim is contestable and he is owning it.** Not for
narration, not for softening. Everywhere else the subject is the system, the team, or the
work.

**V2. No absolutes.** `always` and `never` appear zero times across the opinion, design,
and incident documents; `must` appears 0–3 times. Claims are bounded in time and version
instead: "for v1.0", "at this time", "right now", "in the first iteration".

**V3. Every hedge names its uncertainty.** A hedge is followed immediately by the reason
for it. Vague softening with no stated cause does not occur.

**V4. Concede asymmetrically, then move on.** No balanced on-the-one-hand structure in any
of the six documents. A cost gets a clause, not a matching paragraph.

**V5. Documents admit their own decay.** Claims are date-stamped inline. Freshness is
stated in ordinary language, never as a confidence score.

**V6. Endings narrow, they do not swell.** Every document ends by reducing its own claim
or simply stopping. No recap, no call to action, no closing flourish.

**V7. Parentheses carry the candid part.** The qualification that would not survive in the
main clause goes in brackets.

**V8. Scare quotes mark a label not fully endorsed.** Quotation marks never carry speech.

**V9. Sub-headings are claims; top-level headings are labels.**

**V10. Rough edges survive.** Occasional `it's` for `its`, run-on sentences, subjectless
fragments. Working prose, not copy-edited prose. Do not introduce errors deliberately, but
do not sand every sentence to the same finish either.

**V11. In incident writing, accountability lands on roles and systems, never people.**
Wrong calls get the benefit of what was known at the time. No moral vocabulary.

**V12. Slash compression instead of spelling out a distinction.** "users/customers",
"who/when/how", "low risk/priority".

## 2. Anti-patterns

Each item below was independently reported as absent by at least two of the six analyses.
Treat any of these appearing in a draft as a defect to fix.

- **Parallel triples.** Not present in any of the six documents. A rate approaching one
  per paragraph is the single loudest generated-text signal.
- **Bold sentence lead-ins.** Zero of 314 units in the specification. The owner's
  substitute is a plain micro-head: a short fragment acting as a label, followed by
  full-sentence explanation. Use that instead.
- **Rhetorical questions.** Questions appear only inside mechanical five-whys chains.
- **Importance puffery.** No "critical to understand", "key takeaway", "worth noting".
  Where something matters, say what breaks.
- **Dramatic colon reveals.** Colons introduce lists and contracts only.
- **Symmetrical concession blocks.**
- **Polished closing flourish, recap, or call to action.**
- **External citations or appeals to authority.** Support is internal: tickets, prior art,
  stakeholder acceptance, measured estimates.
- **Probabilistic confidence language.** Ranges, buffers, `~`, and invented 1–5 scales are
  in character; confidence percentages are not.
- **Emotional or apologetic register in incident writing.**

## 3. Checks

Run these against a draft before calling it done. Each is countable.

| Check | Target |
|---|---|
| Parallel triples per 1,000 words | near zero |
| Paragraphs opening with a bold phrase | near zero; use micro-heads |
| Sentence length distribution | median 9–19 words, with genuinely short and genuinely long outliers present |
| `always` / `never` / `must` | zero, unless a requirement genuinely demands it |
| First-person `I` | only at a contestable judgment |
| Final paragraph | narrows the claim or stops; no kicker |
| Concessions | one clause, not a mirrored paragraph |
