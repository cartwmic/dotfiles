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

**Evidence status.** Traits below were reported independently across six documents, but only
one has been counted in full: the specification (4,924 words of prose, excluding tables and
prompt templates). Rules marked *(measured)* have numbers behind them. Rules marked
*(reported)* rest on convergent qualitative reporting and are tendencies, not laws. An
earlier revision of this file stated several tendencies as universals and was wrong about
parallel triples; a blind review against the primary sample caught it.

**Genre fitness overrides every rule here.** Where a rule would make a requirement vaguer,
a heading less navigable, or push a substantive claim into an aside, the document's job
wins and the rule loses. This profile is evidence about one writer, not a style authority.

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

**V2. Absolutes are rare and usually earned** *(measured)*. In the specification, `always`
appears 0 times, `never` twice, `must` twice — and one `never` is a genuine contract
("Never changes"). Claims are more often bounded in time and version: "for v1.0", "at this
time", "right now", "in the first iteration". Prefer a bounded claim, but do not strip an
absolute that a requirement genuinely needs.

**V3. Every hedge names its uncertainty** *(measured)*. A hedge is followed immediately by
the reason for it. Vague softening with no stated cause does not occur.

**V4. Concede asymmetrically, then move on.** No balanced on-the-one-hand structure in any
of the six documents. A cost gets a clause, not a matching paragraph.

**V5. Documents often admit their own decay** *(reported)*. Where a claim can go stale it
tends to be date-stamped inline, and freshness is stated in ordinary language rather than as
a confidence score. Not present in every document: the specification carries no authorial
freshness date.

**V6. Endings narrow, they do not swell** *(reported)*. Documents end by reducing their own
claim or simply stopping. No recap, no call to action, no closing flourish.

**V7. Parentheses carry the candid part** *(measured: 20.9 per 1,000 words)*. The
qualification that would not survive in the main clause goes in brackets. Do not use this to
hide a substantive claim or a requirement — an aside is for qualification, not content.

**V8. Scare quotes mark a label not fully endorsed.** They also carry quoted utterances,
example strings, and enum values freely, so quotation marks alone are not a voice signal.

**V9. In argumentative writing, sub-headings are often claims** (`Use Codex for
plan-following execution`). In specifications they are plain labels (`Design Principles`,
`Metrics`). Match the register, and never trade a navigable heading for a rhetorical one.

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

- **Excess parallel triples.** Measured at roughly 4.5 per 1,000 words of prose, so they
  are present and normal — the defect is overuse. Generated prose runs two to three times
  that rate. Count only rhetorical parallelism: a specification enumeration such as
  `satisfied, unmet, not evaluated, or downstream` is content and must not be broken. An
  earlier version of this file claimed a zero rate, which the primary sample contradicts.
  Breaking a genuine enumeration to lower a count has already cost one document a
  prohibition, so treat that as the greater risk.
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

Measured rates come from the specification's prose. Treat them as direction, not quota, and
never damage meaning to hit one.

| Check | Author measurement | Target |
|---|---|---|
| Rhetorical parallel triples / 1k words | 4.5 | within about 2x; enumerations exempt |
| Paragraphs opening with a bold phrase | 0 | zero; use plain micro-heads |
| Median sentence length | 15 words | 13–17 |
| Sentences over 40 words | 6.5% | do not flatten below ~3% |
| Colons / 1k words | 30.3 | well above typical generated prose |
| Parentheses / 1k words | 20.9 | qualification only, never content |
| Em dashes / 1k words | 13.8 in specifications, 0 in opinion and incident writing | register-dependent; ask before adding |
| First-person `I` | 0 in specifications | only at a contestable judgment, and not in an accepted requirements document |
| Final paragraph | — | narrows the claim or stops; no kicker |
| Concessions | — | one clause, not a mirrored paragraph |
