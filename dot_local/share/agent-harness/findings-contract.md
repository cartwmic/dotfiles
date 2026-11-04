# Findings contract, v1

What a reviewer returns, what code may check about it, and the records the review log keeps. `reviewer-brief.md` tells reviewers what to look for; this file says what shape the answer takes. Two implementations follow it (agent-events' review module and Loop Engine's lean-change provider). They share this file and a fixture, and no code.

## The return

One JSON object, saved as `findings.json`:

```json
{ "findings_schema": 1,
  "reviewer": "name",
  "head": "<commit SHA, or a document's sha256>",
  "brief_sha256": "<sha256 of reviewer-brief.md>",
  "findings": [ { "id": "f1", "severity": "blocking", "text": "...",
                  "obligation": "...", "evidence": "...", "consequence": "...",
                  "component": "..." } ] }
```

| Field | Type | Rule |
|---|---|---|
| `findings_schema` | integer | Must be `1`. A return without it is a v0 return. Loop Engine reads old stored v0 records as before (blocking, every field as then). The review tool rejects them. |
| `reviewer`, `head` | string | Required, not blank. `head` is the commit SHA, or for a document review the file's sha256 (Loop Engine may give the tree id it records). |
| `brief_sha256` | string | The review tool requires it and compares it to the current `reviewer-brief.md`. Optional in Loop Engine, whose reviewers get a packet and not the file. |
| `findings[].id` | string | Required, not blank, unique within the return. |
| `findings[].severity` | `"blocking"` or `"note"` | Required. Anything else rejects the return. |
| `findings[].text` | string | Required, not blank: what is wrong. |
| `findings[].obligation` | string | Required for blocking: the intent criterion or constraint, the principle section, or the repo rule. Optional on a note. |
| `findings[].evidence` | string | Required for blocking: a file:line, or a run and its result. For a Loop Engine intent check, the intent's wording. |
| `findings[].consequence` | string | Required for blocking: what a user would hit. |
| `findings[].component` | string | The part of the system the finding is in, in the reviewer's own words (a module, command or feature). The review log wants it on every blocking finding, because the log keys on it. `add` accepts a blocking finding without one. The labelling agent supplies it with a `label` (`component`), `report` lists such findings as "needs component", and the stuck trigger does not count them toward any component until a label gives them one. The return's own checks do not require it: a blocking finding without it is still blocking. The driver never edits a saved return. Optional on a note. |
| `findings[].question` | string | Loop Engine only (its fixed questions). A Loop Engine note keeps a known `question`. Other implementations accept it and ignore it. |

## Rules

1. **Demotion.** A finding is *effectively blocking* only if `severity` is `blocking` and `obligation`, `evidence` and `consequence` are all non-blank after trimming. Otherwise it is *effectively a note*, with the reason `demoted: missing <fields>`, the missing fields in the order obligation, evidence, consequence, joined by `, ` (for example `demoted: missing evidence, consequence`). Demotion is computed on read and never rewrites the record. A note is never demoted.
2. **Verdict.** PASS means no finding is effectively blocking. Otherwise FAIL.
3. **Disposition.** Only effectively-blocking findings need an outcome (`fixed` or `rejected`, or `residual` in the log). Notes need none.
4. **Rejected, not demoted.** The return is malformed: not JSON, `findings_schema` missing or not `1`, blank `reviewer` or `head`, `findings` not a list, a finding that is not an object, blank or duplicate `id`, blank `text`, missing or unknown `severity`. The fixture's reject codes, in check order: `bad-json`, `bad-schema-version`, `blank-reviewer`, `blank-head`, `bad-shape` (`findings` is not a list, or any finding is not an object), `blank-id`, `duplicate-id`, `blank-text`, `bad-severity`. Checks run in that order, and each check runs over all findings before the next check starts; the first check that fails gives the code. So a blank `text` on the first finding and a blank `id` on the second give `blank-id`.
5. **Code checks presence and shape, not truth.** It cannot tell whether evidence is true, whether the consequence is "ordinary single-user use", or whether the obligation applies. Agents judge those. A `brief_sha256` match shows a reviewer was given the brief, not that it followed it.

## The conformance fixture

The fixture is `findings-conformance-v1.json`: cases of `{name, input, expected}`. `expected` holds `accepted`, and then either the `verdict` and each finding's `effective` severity and demotion reason, or the `reject` code (a code, not message text). A string `input` is raw file text (for the bad-JSON case). A case whose `expected` has `v0_reader: true` is skipped by an implementation that reads v0 records. A case whose `expected` has `envelope: true` tests the shape of the return itself and not a finding's fields; an implementation that does not parse the envelope skips it (Loop Engine does). The envelope cases are exactly those that reject with `bad-json`, `bad-schema-version`, `blank-reviewer`, `blank-head` or `bad-shape`. Every other case is per-finding and every implementation runs it. `brief_sha256` is not tested by the fixture.

- The fixture is not kept in this folder. Its two copies live in dotfiles (`dot_local/share/agent-events/fixtures/`, not deployed) and loop-engine, as byte-identical copies. The fixture's sha256 is `ffb5f849d93f77fcf723bf396832ec47d23829ef077f44cf3497830b007183f1` (26 cases). Each repo's test pins its copy's sha256.
- To change the fixture, change both copies and both pins together, in one change set.
- "Same schema" means the same finding fields and the same demotion rules. It does not mean the same envelope: Loop Engine runs the fixture's findings through its own per-finding check and its duplicate-id and unknown-severity checks, and does not parse them as its `Review`.

## The review log

Reviews of one item are kept in `${AGENT_TRACES_DIR:-~/.local/share/agent-traces}/emitted/review/<item>/`. It holds:

- `round-<N>/`: a folder per round holding the reviewer's `findings.json` and `REVIEW.md`.
- `findings.jsonl`: the log. Append-only, one JSON object per line, each with `event` and a UTC `at`.

Two round numbers. `N`, the *log round*, is counted across the item's stages, starts at 1 and is never reused; it names the folder and the ids `r<N>.<id>`, and is the `round` of every event. `review_round` is counted within the current review sequence and restarts at 1 when a new sequence starts: the first review at a stage, and a new design after a redesign switch. It is the round number that `reviewer-brief.md` §6 means. A review sequence is the log rounds from one with `review_round` 1 up to the next. The exact rule for when a sequence starts is in the stuck-trigger paragraph below. With one counter, a new design's review would arrive as round 4 and get only the fix diff; with one counter per stage, two stages would collide in `r<N>.<id>`.

`<item>` is `<repo>#<pr>`, a run id, or, for design work, `<folder>:<document>` (the work folder's name, a colon, and the document's name without its extension), so two documents reviewed in one folder do not share an item and a counter. `<repo>` is the repo's git directory name, for example `cartwmic-homelab-v2#94` or `coordinator#217`, so that a project label can be resolved from it.

`agent-events review` writes the log (by hand until it ships). Every finding gets a log-wide id `r<N>.<id>` (round number, then the return's own id), because ids repeat across rounds. Every other record points to a finding by that log id.

| `event` | Fields | Written when |
|---|---|---|
| `round` | `round` (the log round, here and in every other event), `review_round` (integer, ≥ 1; must follow the sequence rule in the trigger paragraph), `stage`: `mechanism`, `intent`, `plan`, `design`, `diff` or `other`, `head`, `reviewer`, `verdict`: `pass` or `fail`, `session`, `model?`, `duration_ms?`, `cost_usd?` | The driver adds a round. `review_round` and `stage` are required. Written once per round, even when the return has no findings, so a clean pass leaves a line. A second add for a round already in the log is refused because of it. `session` is the reviewer's session or thread id (it points back to the transcript). `cost_usd` is the cost of the round. |
| `finding` | `id` (log id), `round`, `head`, `reviewer`, `severity`, `effective`, `demoted_reason?`, `component`, `text`, `obligation?`, `evidence?`, `consequence?` | The driver adds a round, one record per finding in its return. The round's `session` and `cost_usd` are on its `round` record, not repeated here. |
| `label` | `id`, `relation`: `new`, `repeat` or `follow-on`; `of?` (an earlier log id); `component?` | A fresh agent that is not the driver labels a blocking finding. The latest label wins. A label may replace `component`, so two spellings of one component count as one. |
| `disposition` | `id`, `outcome`: `fixed` (`sha`), `rejected` (`reason`) or `residual` (`accepted_by`) | The driver records what became of a blocking finding. |
| `redesign` | `component`, `round`, `blind_session`, `comparer_session`, `makes_impossible`: `yes` or `no`; `action`: `switched`, `rang-michael` or `kept-fixing` | The lead records the blind redesign check for a stuck component. |
| `judge` | `round`, `session`, `verdict`: `churning` or `not-churning` | A fresh judge who is not the driver gives the churn verdict. |
| `escape` | `item`, `head`, `round` (the round that passed the defect), `found_by` (a PR, issue or dogfood id), `text`, `of?` (the log id of an earlier note or demoted finding that named this defect) | Whoever finds a later defect that traces to a reviewed change. |

A finding record with `effective: note` is a residual. It needs no disposition and no label.

**The stuck trigger.** It is computed per component, using the component from the latest `label` of each finding (a label's `component` replaces the finding's own). A component fires the trigger at log round *r* when it has an effectively-blocking finding whose latest relation is `repeat` or `follow-on` in log round *r* and again in log round *r*−1, that is, in two consecutive log rounds *of one review sequence*. It fires at the second of those rounds. A repeat cannot appear before review round 2, so the earliest firing is review round 3. A blocking finding with no component, from the finding or its latest label, is not counted until it has one. A new sequence (a round with `review_round` 1) starts the count afresh. The labeller judges new, repeat or follow-on within the current sequence. The review round follows this rule: a sequence starts (review round 1) at an item's first round, at a round whose stage differs from the previous round's stage, or at a round marked as a new sequence (`--new-sequence`, used for a new design after a redesign switch); otherwise the review round is the previous round's plus 1. `agent-events review add` checks it; by-hand logs follow it too. A trigger is *skipped* when that component has no `redesign` event at or after the log round it fired. One implementation computes this trigger; the findings CLI and the agent-events exporter both call it.

## Version

v1. A change to a field, a rule or a record shape is a new version of this file and of the fixture, and both implementations move together. The log-record additions made before any tool wrote the log (`review_round`, `stage`, `model`, `duration_ms`, `escape.of`, the round folder, the `<folder>:<document>` item form) belong to v1. The return and the fixture are unchanged.
