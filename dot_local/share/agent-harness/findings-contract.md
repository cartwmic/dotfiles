# Findings contract, v1

What a reviewer returns, what code may check about it, and the records the review log keeps. `reviewer-brief.md` tells reviewers what to look for; this file says what shape the answer takes. Two implementations follow it (the agent-kit `traces` component's review tool and Loop Engine's lean-change provider). They share this file and a fixture, and no code.

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

- The fixture is not kept in this folder. Its two copies live in the agent-kit `traces` component (`src/traces/fixtures/`) and loop-engine, as byte-identical copies, and nowhere else. The fixture's sha256 is `ffb5f849d93f77fcf723bf396832ec47d23829ef077f44cf3497830b007183f1` (26 cases). Each repo's test pins its copy's sha256.
- To change the fixture, change the kit's copy and loop-engine's copy and both pins together, in one change set.
- "Same schema" means the same finding fields and the same demotion rules. It does not mean the same envelope: Loop Engine runs the fixture's findings through its own per-finding check and its duplicate-id and unknown-severity checks, and does not parse them as its `Review`.

## The review log

Reviews of one item are kept in `${AGENT_TRACES_DIR:-~/.local/share/agent-traces}/emitted/review/<item>/`. It holds:

- `round-<N>/`: a folder per round holding the reviewer's `findings.json` and `REVIEW.md`. A round may hold several readers (see "Several readers in one round"); then each reader has its own sub-folder, `round-<N>/<reader>/findings.json` and `REVIEW.md`, and the round folder holds no `findings.json` of its own.
- `findings.jsonl`: the log. Append-only, one JSON object per line, each with `event` and a UTC `at`.
- `report.json`: a summary derived from `findings.jsonl` alone, defined in "The report" below.

Two round numbers. `N`, the *log round*, is counted across the item's stages, starts at 1 and is never reused; it names the folder and the ids `r<N>.<id>` (`r<N>.<reader>.<id>` when the round has several readers), and is the `round` of every event. `review_round` is counted per stage within the current review sequence: 1 for a stage's first round in the sequence, then that stage's previous review round plus 1. It is the round number that `reviewer-brief.md` §6 means, so a stage's first review in a sequence is round 1 (the whole diff) however many rounds of another stage came before it. A review sequence is the log rounds from one that starts a sequence up to the next: it starts at an item's first round and at a new design after a redesign switch; a change of stage does not start one. The exact rule is in the stuck-trigger paragraph below. With one counter for the whole sequence, a diff review after three design rounds would arrive as round 4 and get only the fix diff; with the log round counted per stage, two stages would collide in `r<N>.<id>`. A round with several readers is still one log round and one review round.

`<item>` is `<repo>#<pr>`, a run id, or, for design work, `<folder>:<document>` (the work folder's name, a colon, and the document's name without its extension), so two documents reviewed in one folder do not share an item and a counter. `<repo>` is the repo's git directory name, for example `cartwmic-homelab-v2#94` or `coordinator#217`, so that a project label can be resolved from it.

`agent-traces review` writes the log (by hand until it ships). Every finding gets a log-wide id `r<N>.<id>` (round number, then the return's own id), because ids repeat across rounds. In a round with several readers the id is `r<N>.<reader>.<id>` (round number, reader, then that reader's own id), because ids also repeat across readers. Every other record points to a finding by that log id.

| `event` | Fields | Written when |
|---|---|---|
| `round` | `round` (the log round, here and in every other event), `review_round` (integer, ≥ 1; must follow the sequence rule in the trigger paragraph), `stage`: `mechanism`, `intent`, `plan`, `design`, `diff` or `other`, `new_sequence?`, `head`, `reviewer`, `verdict`: `pass` or `fail`, `session`, `model?`, `duration_ms?`, `cost_usd?`, `readers?` | The driver adds a round. `review_round` and `stage` are required. Written once per round, even when the return has no findings, so a clean pass leaves a line. A second add for a round already in the log is refused because of it. `session` is the reviewer's session or thread id (it points back to the transcript). `cost_usd` is the cost of the round. `readers` is present only when the round has several readers (see "Several readers in one round"). `new_sequence` is `true` on a round that starts a review sequence and `false` on one that continues it; `agent-traces review add` writes it on every round. A round without it follows the earlier rule (`review_round` 1 starts a sequence; any other value is the previous round's plus 1 on the same stage), so logs written before this amendment read as they always did. |
| `finding` | `id` (log id), `round`, `head`, `reviewer`, `severity`, `effective`, `demoted_reason?`, `component`, `text`, `obligation?`, `evidence?`, `consequence?` | The driver adds a round, one record per finding in its return. The round's `session` and `cost_usd` are on its `round` record, not repeated here. |
| `label` | `id`, `relation`: `new`, `repeat` or `follow-on`; `of?` (an earlier log id); `component?` | A fresh agent that is not the driver labels a blocking finding. The latest label wins. A label may replace `component`, so two spellings of one component count as one. |
| `disposition` | `id`, `outcome`: `fixed` (`sha`), `rejected` (`reason`; it names the triage test it failed, see `finding-triage.md`) or `residual` (`accepted_by`) | The driver records what became of a blocking finding. |
| `redesign` | `component`, `round`, `blind_session`, `comparer_session`, `makes_impossible`: `yes` or `no`; `action`: `switched`, `rang-michael` or `kept-fixing` | The lead records the blind redesign check for a stuck component. |
| `judge` | `round`, `session`, `verdict`: `churning` or `not-churning` | A fresh judge who is not the driver gives the churn verdict. The churn test counts a round's blocking findings as it does for a one-reader round, reading the stage of the round just finished (that stage's last two review rounds in the sequence), leaving out same-round duplicates (defined in the stuck-trigger paragraph below). Distinct findings from different readers each count. |
| `escape` | `item`, `head`, `round` (the round that passed the defect), `found_by` (a PR, issue or dogfood id), `text`, `of?` (the log id of an earlier note or demoted finding that named this defect) | Whoever finds a later defect that traces to a reviewed change. |

A finding record with `effective: note` is a residual. It needs no disposition and no label.

**The stuck trigger.** It is computed per component, using the component from the latest `label` of each finding (a label's `component` replaces the finding's own). A component fires the trigger at log round *r* when it has an effectively-blocking finding whose latest relation is `repeat` or `follow-on` in log round *r* and again in log round *r*−1, that is, in two consecutive rounds *of one stage in one review sequence* (that stage's rounds in the sequence, in order; rounds of other stages between them do not break the run). It fires at the second of those rounds. A repeat cannot appear in a sequence's first round, so the earliest firing is the sequence's third round. A blocking finding with no component, from the finding or its latest label, is not counted until it has one. A *same-round duplicate* is a finding whose latest label is `repeat` or `follow-on` and whose `of` is a finding in the same log round: it is one defect raised by several readers, not the return of an earlier defect. A same-round duplicate is left out of this count and of the churn count (the `judge` row), in every round; every other finding counts exactly as in a one-reader round. A log round with several readers is one round for this count. The labeller uses this only to merge readers' duplicates, so a one-reader round has none. A new sequence starts the count afresh. The labeller judges new, repeat or follow-on within the current sequence. The review round follows this rule: a sequence starts (review round 1) at an item's first round or at a round marked as a new sequence (`--new-sequence`, used for the first round of a new design after a redesign switch); every other round counts per stage: review round 1 for the first round of its stage in the sequence, otherwise that stage's previous review round in the sequence plus 1. `agent-traces review add` checks it; by-hand logs follow it too. A trigger is *skipped* when that component has no `redesign` event at or after the log round it fired. The kit's review tool computes the trigger once and writes the result to `report.json`; the agent-events reader reads that file and computes no trigger.

## Several readers in one round

A log round can hold several **readers**: each returns its own review of the same head in the same round (for example an ordinary reader and a simplicity reader on a data path). A round with a single reader is unchanged: the layout `round-<N>/findings.json`, the ids `r<N>.<id>` and the `round` event are as defined above.

- **Folder.** One sub-folder per reader, `round-<N>/<reader>/`, each holding that reader's `findings.json` and `REVIEW.md`. `<reader>` is a short slug the driver chooses, such as `a`, `b` or `simplicity`, and is unique within the round. Every reader's `head` is the same, and `add` refuses a round whose readers' heads differ.
- **One `add` for the round.** The log is append-only and the `round` line is written once, so one `add` carries every reader (each as a `--reader`, with its return and optionally its session, model and cost). It validates every return first, then writes one `round` event, then every reader's findings. A `finding` record's `reviewer` is the `reviewer` of the return it came from. The driver waits until all readers have returned. A later `add` for the same `N` stays refused. The several-reader form and the single-return form cannot be mixed in one `add`.
- **Ids.** `r<N>.<reader>.<id>`. The return's own id is as before, unique within its reader's return.
- **`round` event.** It gains an optional `readers`: `[{ "reader", "session", "model?", "verdict", "cost_usd?" }]`, one entry per reader in the order given. The top-level fields stay, so a reader of the log that ignores `readers` needs no change: `verdict` is `fail` if any reader's verdict is `fail`; `cost_usd` is the sum of the readers' known costs (a partial total when some reader's cost is unknown; the `readers` entries show which), and absent if none is known; `model` is set when all readers share one model and absent otherwise; `session` and `reviewer` are the first reader's. With one reader the event has no `readers` and is as before.
- **Labels.** The labelling agent merges a defect that several readers raise in the same round: it labels one finding `new` and each duplicate `repeat` with `--of` the same-round finding. A same-round duplicate (defined in the trigger paragraph above) is left out of the stuck trigger and of the churn count.
- **Report.** `report.json` gains an optional `rounds` (see "The report").

## The report

One file per item, `<item>/report.json`. It is derived from `findings.jsonl` alone and rewritten by every write verb and by `report`. It carries ids, counts and enumerated values only: no component names, no text, no session ids. Canonical bytes: `JSON.stringify(report, null, 2) + "\n"` with keys in the order below, so a golden file compares byte for byte.

```json
{
  "report_schema": 1,
  "findings_schema": 1,
  "item": "coordinator#217",
  "log": { "lines": 14, "events": { "round": 3, "finding": 6, "label": 4, "disposition": 1, "redesign": 0, "judge": 0, "escape": 0 } },
  "summarises": {
    "events": ["round", "finding", "label", "disposition", "redesign", "judge", "escape"],
    "fields": {
      "round": ["round", "review_round", "stage", "verdict"],
      "finding": ["id", "round", "severity", "effective", "component"],
      "label": ["id", "relation", "component"],
      "disposition": ["id", "outcome"],
      "redesign": ["component", "round"],
      "judge": [], "escape": []
    }
  },
  "sequences": [ { "sequence": 1, "first_round": 1, "last_round": 3, "stage": "design" } ],
  "rounds": [ { "round": 3, "readers": ["a", "b"] } ],
  "findings": [ { "id": "r1.f1", "round": 1, "sequence": 1, "effective": "blocking", "relation": "new", "outcome": "fixed", "has_component": true } ],
  "stuck": [ { "sequence": 1, "round": 3, "review_round": 3, "skipped": false } ],
  "counts": { "needs_component": 0, "undisposed_blocking": 1, "skipped_redesigns": 0 },
  "state": "open"
}
```

| Field | Meaning |
|---|---|
| `report_schema` | integer; `1`. Any other value is unknown to a v1 reader. |
| `findings_schema` | integer; the contract's return version the log was written under (`1`). The log lines carry no such field; the tool refuses any return that is not 1, so this records it. |
| `item` | the item, as in the folder name. |
| `log.lines` | number of non-empty lines in `findings.jsonl` when the report was written. A reader that counts a different number knows the report is stale. |
| `log.events` | count of lines per event kind. Their sum equals `lines`. |
| `summarises.events` | the event kinds this report accounts for. An event kind in the log that is not listed here means the log is newer than the report. |
| `summarises.fields` | for each kind, the fields the report reads. A provenance list; a reader does not check log lines against it. |
| `sequences[]` | one per review sequence, in order: its ordinal (1-based), first and last log round, and the stage of its first round. |
| `rounds[]` | optional; present only when at least one `round` event has `readers`, and then one entry per such round, in log order: the log round and the readers' slugs in the order the event gives them. Slugs only: each reader's verdict stays in the log's `round` event. It sits after `sequences` and before `findings`. A log with no `readers` has no `rounds` key and its bytes are as before. `summarises` is unchanged. |
| `findings[]` | one per `finding` event, in log order: log id, log round, the sequence ordinal, `effective` (`blocking` or `note`), `relation` (the latest label, or `null` for a note or an unlabelled finding), `outcome` (the latest disposition: `fixed`, `rejected`, `residual`, or `null`), `has_component` (from the finding or its latest label). |
| `stuck[]` | one per component firing, in order: the sequence, the log round and review round it fired at, and `skipped` (no `redesign` for that component at or after that round). Two components firing at one round give two entries; the names stay out. |
| `counts` | `needs_component`: effectively-blocking findings with no component; `undisposed_blocking`: effectively-blocking findings with no outcome; `skipped_redesigns`: `stuck` entries with `skipped` true. |
| `state` | `passed` when the last `round` event's verdict is `pass`, else `open`. An item with no `round` event has no report. |

A change to a field, a name or a meaning is a new `report_schema`. Adding the optional `rounds` field is not: it stays `report_schema` 1, because no field a v1 reader validates changes. The golden log pairs (a `findings.jsonl` and its `report.json`) live in the kit and in dotfiles (the reader's test), vendored byte for byte and pinned by a manifest sha256; they change together, in one change set, as with the fixture. The set covers a treadmill (stuck at review round 3), a clean pass, a design-then-diff pair (sequence boundary), a redesign switch (`--new-sequence`), a missing component then a label that supplies it, an interleaved pair (design, diff, design, diff, design: stuck at the third design round) and its old-way control (the same history written without `new_sequence`: no stuck), and a hand-written log.

## Version

v1. A change to a field, a rule or a record shape is a new version of this file and of the fixture, and both implementations move together. The log-record additions made before any tool wrote the log (`review_round`, `stage`, `model`, `duration_ms`, `escape.of`, the round folder, the `<folder>:<document>` item form) belong to v1. `report.json` and its `report_schema` (1) are added to v1 before any tool writes it; a change to its shape is a new `report_schema`. Several readers in one round (the sub-folders, `r<N>.<reader>.<id>`, the optional `readers` on the `round` event, the same-round duplicate rule and the optional `rounds` in the report) is an additive amendment to v1, made before any tool writes it; a log with one reader per round is read and written as before. The return and the fixture are unchanged. The per-stage review round (the optional `new_sequence` on the `round` event, the sequence rule above, and the stuck and churn reading by stage) is an additive amendment to v1: `report.json` and `report_schema` are unchanged, and a round without `new_sequence` is read under the earlier rule.
