# House voice profile

Evidence-derived writing profile for the repository owner. Load this in Edit mode when the
target document is the owner's own writing, or when asked to repair a draft that reads as
generated. Pair with [voice-excerpts.md](voice-excerpts.md).

The document rules come from six owner-written sources: an opinionated tooling comparison,
an evaluation-metrics specification, a system design, a cross-service explainer, and two
post-incident reviews. Reported traits converged across those sources. Measured rates come
from 4,237 words of specification prose and apply only as loose guidance.

Casual/status Slack, review comments, and tasking prompts supply unmeasured evidence for
their own registers. Private exchanges appear as redacted excerpts only when the owner
explicitly requests inclusion. Internal names and product terms are genericised while
sentence shape is preserved.

Genre fitness overrides this profile. A requirement must remain testable, a heading must
remain navigable, and substantive content must stay in the main clause. This is evidence
about one writer, with no authority as a general style guide.

## 0. Register comes first

Treating this as a single style produces the wrong output. The measured split:

| Register | First person | Em dash / semicolon | Median sentence |
|---|---|---|---|
| Opinion / recommendation | heavy `I`, 3.15:1 over impersonal | none at all | 13.5 w |
| Specification | almost none, 1:15.8 | frequent em dash and colon | 15 w |
| Design / decision | 81% impersonal, `we` common, `I` rare | rare | 14.5 w |
| Incident review | zero `I`, `we` only subordinated | none | 14–19 w |
| Casual / status | heavy `I` for owned work and commitments | none observed | highly variable; bullets, long additive paragraphs, and rapid short turns |

Two unmeasured working registers sit outside this table. Review comments lead with direct
questions, test the implications of a term or framing, and often offer a concrete example or
alternative that would resolve the ambiguity. Challenges are owned with `I` / `IMO` and may
end with a scope hedge or self-deprecating aside. A short comment can consist only of the
missing distinction. Tasking prompts lead with the requested outcome, attach the known gap
or reason inline, and state validation or subagent constraints in the same working register.

Match the register before matching anything else. A PRD or design doc sits between design
and specification: impersonal by default, `we` for commitments, `I` only for a judgment
being personally staked.

Casual / status is for team-channel updates, alignment notes, and similarly informal
owned-work writing. It is not a document style. Do not import its emoji, word-level
italics, thank-you closers, or phrasing like "gets destroyed" into specifications,
designs, or incident reviews. Do not rewrite a status update into the impersonal
document register to satisfy the document rules.

Traits unique to casual / status, from the supplied Slack sources:

- Opens with a one-line purpose fragment (`Update for those curious:`, `Summary of my
  alignment with [colleague] from the misunderstanding at the sync meeting:`). Headings
  that recast the miss do not appear.
- Others' points are attributed, then agreed with. He does not absorb them as his insight.
- Italics mark the one word under dispute (`_understandings_`, `_active_`, `_should_`).
  In documents the same job is scare quotes or a defining clause.
- A quoted invented situation makes a failure mode concrete, then a blunt consequence
  follows.
- Slash-fused informal compounds (`naildown/explore`, `framework/harness`,
  `claims/narrative/RCA`) — V12, rougher, including spellings that are not the dictionary
  form.
- Scope limits are stated and then dropped ("isn't pretending to X, that's a separate
  issue, but there _should_ be Y"). This is an observed casual/status shape that disclaims
  an assumption the reader would actually make. It grants no licence for the banned binary
  contrast template in Anti-patterns, and it must not be carried into a document register.
- May end with a real thank-you and a small emoji, a small hopeful aside after a stated
  digression, an explicit `Summary -` that reports schedule or status, or simply stop.
  None should be normalized into a document-style conclusion.
- Commitments are dated in ordinary language ("I will start on this harness tomorrow",
  "in the PRD soon here").
- Firsthand technical comparisons can be strongly opinionated, but their boundary stays
  visible: personal use, limited experience, current cost, or uncertainty about another
  team's implementation constraints.
- Optimism is often paired with the evidence still needed before committing long term.
  Enthusiasm does not erase the validation condition.
- Delays and limitations are reported candidly with their cause, current distance from the
  intended timeline, recovery plan, and the point at which the slippage will be reassessed.
- Offers to help are concrete and low-ceremony: ask who owns the work, request the relevant
  repository or access, state willingness to spend time, and make room for the owner to be
  candid about boundaries.
- Confidence tracks current experience. Stale familiarity does not support a present-tense
  claim.
- Live conversation can collapse to lowercase fragments, one-line agreement, jokes, and
  immediate follow-up questions. Do not expand these into polished paragraphs or preserve
  an exchange sequence merely to reproduce that rhythm.

## 1. Rules

**V1. In document registers, `I` appears only where a claim is contestable and he is
owning it.** Narration and softening never take it. Everywhere else the subject is the
system, the team, or the work.

**In casual / status writing, `I` is the default for owned work, commitments, and
alignment.** "I've been working on that feedback", "I will start on this harness
tomorrow", "I agree with this take". Do not strip first person from a status update to
satisfy the document rule.

**V2. Absolutes are rare and usually earned** *(measured)*. In the specification, `always`
appears 0 times, `never` twice, `must` twice — and one `never` is a genuine contract
("Never changes"). Claims are more often bounded in time and version: "for v1.0", "at this
time", "right now", "in the first iteration". Prefer a bounded claim, but do not strip an
absolute that a requirement genuinely needs.

**V3. Every hedge names its uncertainty** *(measured)*. A hedge is followed immediately by
the reason for it. Vague softening with no stated cause does not occur.

**V4. Concede asymmetrically, then move on.** No balanced on-the-one-hand structure in any
of the six documents. A cost gets a clause. Never a matching paragraph.

**V5. Documents often admit their own decay** *(reported)*. Where a claim can go stale it
tends to be date-stamped inline, and freshness is stated in ordinary language. Confidence
scores do not appear. Not present in every document: the specification carries no authorial
freshness date.

**V6. Endings narrow, they do not swell** *(reported)*. Documents end by reducing their own
claim or simply stopping. No recap, no call to action, no closing flourish. Casual /
status writing has more than one observed ending: a genuine thank-you plus a small emoji,
a hopeful aside after `Anyways, I digress`, or an explicit `Summary -` that states schedule
or status without inflating it. Leave the observed ending alone. Do not force the document
rule onto it.

**V7. Parentheses carry the candid part** *(measured: 22.9 per 1,000 words, though many
carry plain schema mechanics with no candour in them)*. The
qualification that would not survive in the main clause goes in brackets. Do not use this to
hide a substantive claim or a requirement — an aside qualifies. Content belongs in the main
clause.

**V8. Scare quotes mark a label not fully endorsed.** They also carry quoted utterances,
example strings, and enum values freely, so quotation marks alone are not a voice signal.

**V9. In argumentative writing, sub-headings are often claims** (`Use Codex for
plan-following execution`). In specifications they are plain labels (`Design Principles`,
`Metrics`). Match the register, and never trade a navigable heading for a rhetorical one.

**V10. Rough edges survive.** Occasional `it's` for `its`, run-on sentences, subjectless
fragments, fused spellings (`naildown/explore`), lowercase mid-stream (`prd`), and slightly
broken closers (`into the prd going as well`) appear in the evidence. Never introduce an
error. Leave harmless rough edges when correcting them would only homogenize the prose.

**V11. In incident writing, accountability lands on roles and systems, never people.**
Wrong calls get the benefit of what was known at the time. No moral vocabulary.

**V12. Slash compression carries a distinction the sentence never spells out** *(measured)*.
"users/customers", "who/when/how", "low risk/priority". Casual writing runs this
rougher: "naildown/explore", "framework/harness", "claims/narrative/RCA".

**V13. Tables carry repeated comparable records; prose keeps its enumerations** *(measured)*.
The sample contains 29 comma-coordinated prose inventories. Use a table for comparable
records with shared fields. Leave ordinary enumerations in prose.

**V14. Long sentences appear and are built by subordination** *(measured: 7.6% of prose
sentences exceed 40 words; median 16)*. Ordinary joins include `so`, `while`, `whereas`,
`which`, `since`, and semicolons. Merge only when the clauses already share a clear relation.
Never invent causality or leave a pronoun without a stable antecedent. The measured rate is
not a quota.

Requirements are exempt from V14. Keep one testable obligation per sentence.

## 2. Anti-patterns

Each item below was independently reported as absent by at least two of the six analyses.
Treat any of these appearing in a draft as a defect to fix.

- **Excess parallel triples.** The sample contains roughly 5.2 per 1,000 words of prose.
  Count rhetorical parallelism only. A specification enumeration such as `satisfied, unmet,
  not evaluated, or downstream` carries content and must remain intact.
- **Bold lead-ins on running prose paragraphs.** Zero of 314 units in the specification. In
  flowing prose the owner's substitute is a plain micro-head: a short fragment acting as a
  label, followed by full-sentence explanation.

  Labelled list items may use bold lead-ins, including identifiers (`G1`, `J3`, `R12`) and
  names (`Timeliness.`, `Executor routing.`). Those labels help readers scan for a specific
  requirement. Bold opening a running paragraph remains decorative.
- **Rhetorical questions**, a register-sensitive tendency. They do occur. The
  sample opens a section with "can users trust the answers, are responses grounded in
  evidence, and does the system know when to stay silent?", so framing questions do occur in
  specifications. Genuine open questions in a requirements document are not a defect at all.
  What to avoid is the decorative question-then-answer beat.
- **Importance puffery.** No "critical to understand", "key takeaway", "worth noting".
  Where something matters, say what breaks.
- **Dramatic colon reveals.** Colons introduce lists and contracts only.
- **Binary contrast templates — banned outright in every register.** Any construction that
  reaches its point by first rejecting an alternative: "It's not X. It's Y.", "not X, but
  Y", "X, not Y", "X rather than Y", "less about X, more about Y", "instead of X, Y", and
  negative lists such as "Not for A, not for B." The owner names this the single framing he
  most wants absent, so it is not a countable tendency and has no genre-fitness override.
  Delete the rejected half and assert the claim. Where the rejection is load-bearing, make
  it a standalone prohibition sentence after the claim. Survivors: a negation with no
  replacement attached, `not` as a data value in an enumeration, and verbatim excerpts.
- **Symmetrical concession blocks.**
- **Polished closing flourish, recap, or call to action.** Casual / status writing may
  end with a genuine thank-you plus a small emoji, a hopeful aside after a digression,
  or a factual `Summary -`; leave that. Do not add those endings to a document, and do
  not treat them as this anti-pattern.
- **External citations or appeals to authority.** Support is internal: tickets, prior art,
  stakeholder acceptance, measured estimates.
- **Probabilistic confidence language.** Ranges, buffers, `~`, and invented 1–5 scales are
  in character; confidence percentages are not.
- **Emotional or apologetic register in incident writing.** Casual warmth (a thank-you,
  "gets destroyed") is register-bound and must not migrate here.

## 3. Checks

Run these against a draft before calling it done. Each is countable.

Measured rates come from the specification's prose. Treat them as direction. None is a
quota, and never damage meaning to hit one. One row below is a hard gate at zero.

Measure prose sections and specification sections separately. Applying prose targets to a
requirements list is how a stylistic pass starts damaging obligations.

| Check | Author measurement | Target |
|---|---|---|
| Comma-separated triples / 1k words | 5.2 | direction only; the count depends on whether enumerations are included, and a genuine enumeration is content. Never break one to lower the number |
| Prose paragraphs opening with a bold phrase | 0 | zero; use plain micro-heads |
| Labelled list items opening with bold | — | expected; owner override, leave alone |
| Median sentence length | 16 words | 13–17 in prose; requirements may sit lower |
| Sentences over 40 words, prose | 7.6% | some should exist; no quota, and never at the cost of a clean relation between clauses |
| Sentences over 40 words, requirements | — | no target; one obligation per sentence wins |
| Sentences under 8 words | 19.0% | keep the short punches; do not merge them away |
| Colons / 1k words | 34.5 | well above typical generated prose |
| Parentheses / 1k words | 22.9 | qualification only, never content |
| Em dashes / 1k words | 15.6 in this specification, 0 in opinion and incident writing | register-dependent; ask before adding |
| Sentence-length spread (stdev) | 13.9 | unstable across tokenizers; inspect, do not gate |
| First-person `I` | 0 in specifications | only at a contestable judgment, and not in an accepted requirements document. Casual / status: expected for owned work; do not strip |
| Final paragraph | — | narrows the claim or stops; no kicker. Casual / status: preserve an observed thank-you, digression aside, factual `Summary -`, or abrupt stop |
| Concessions | — | one clause; never a mirrored paragraph |
| Binary contrast templates | — | hard zero, all registers. Grep changed text for `not … but`, `, not `, `rather than`, `instead of`, `less about`. Every hit fails unless the negation has no replacement attached, `not` is a data value in an enumeration, or the span is a verbatim excerpt |
