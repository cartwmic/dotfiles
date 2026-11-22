# Findings contract, v1

What a reviewer returns, what code may check about it, and the records the review log keeps. `reviewer-brief.md` tells reviewers what to look for; this file says what shape the answer takes. Two implementations follow it (the agent-kit `traces` component's review tool and Loop Engine's lean-change provider). They share this file and a fixture, and no code.

## The return

One JSON object, saved as `findings.json`: `findings_schema`, `reviewer`, `head`, `brief_sha256`, and `findings` (a list of finding objects with the fields below).

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
| `findings[].component` | string | The part of the system the finding is in, in the reviewer's own words (a module, command or feature). The review log keys on it and wants it on every blocking finding, but the return's checks do not require it: a blocking finding without it is still blocking, and `add` accepts it. The labelling agent on the Reviewer seat supplies one with a `label` (`component`); `report` lists such findings as "needs component". The driver never edits a saved return. Optional on a note. |
| `findings[].question` | string | Loop Engine only (its fixed questions). A Loop Engine note keeps a known `question`. Other implementations accept it and ignore it. |

## Rules

1. **Demotion.** A finding is *effectively blocking* only if `severity` is `blocking` and `obligation`, `evidence` and `consequence` are all non-blank after trimming. Otherwise it is *effectively a note*, with the reason `demoted: missing <fields>`, the missing fields in the order obligation, evidence, consequence, joined by `, ` (for example `demoted: missing evidence, consequence`). Demotion is computed on read and never rewrites the record. A note is never demoted.
2. **Verdict.** PASS means no finding is effectively blocking. Otherwise FAIL.
3. **Disposition.** Only effectively-blocking findings need an outcome (`fixed` or `rejected`, or `residual` in the log). Notes need none. A `fixed` disposition names where the fix lives: `sha` for a commit of the reviewed change, or `artifact` for a fix outside the diff (a tracker ticket key, a doc path, a config location). A fix outside the diff recorded with only a sha looks fixed while nothing in the log can check it, so `disposition-check` (a dotfiles script, both profiles) refuses a `fixed` disposition that has neither field, and one whose `sha` is not a commit of the reviewed change (run with the item's head and base), unless it carries an `artifact`. The reviewer brief runs it at re-review, from round 2 on, on the item's log. While the kit's `record disposition` cannot write `artifact`, a driver appends the corrected disposition line to `findings.jsonl` by hand (one JSON object, the same fields, with `artifact`); the log is append-only and the latest disposition of a finding wins, so the hand-appended record replaces the earlier one. Presence and shape only: whether the sha or the artifact really carries the fix is judged, not checked (rule 5).
4. **Rejected, not demoted.** A malformed return is rejected with the first code that fails, in this order: `bad-json` (not JSON), `bad-schema-version` (`findings_schema` missing or not `1`), `blank-reviewer`, `blank-head`, `bad-shape` (`findings` is not a list, or any finding is not an object), `blank-id`, `duplicate-id`, `blank-text`, `bad-severity` (missing or unknown). Each check runs over all findings before the next starts, so a blank `text` on the first finding and a blank `id` on the second give `blank-id`.
5. **Code checks presence and shape, not truth.** It cannot tell whether evidence is true, whether the consequence is "ordinary use" (defined in `reviewer-brief.md` §5), or whether the obligation applies. Agents judge those. A `brief_sha256` match shows a reviewer was given the brief, not that it followed it.
6. **Decision-log findings.** A blocking finding that a material choice has no decision record (`reviewer-brief.md` §1) has an `obligation` that starts with the literal prefix `decision log:`. The prefix is only how such findings are told apart; no field, check or code changes, and it is never the `component`.

## The owner-intent block

A reviewer judges the change against the owner's words, not against the driver's restatement of them: the restatement is where the "small set of tools" and "refuses any change, even if the bot is tricked" guarantees were lost (coordinator#782). So every review `brief.md` carries one block that `review-intent` (a dotfiles script, both profiles) generates from the ledger. The driver appends it: `review-intent --pr <OWNER/REPO#N> [--body-file round-N/brief.md] >> round-N/brief.md`. For an item with no PR, give the ids by hand (`--ask N`, `--decision N`) or cite them in the brief and pass the brief as `--body-file`. Loop Engine lean-change rounds (`review add --from lean-change`) are exempt: their intent is checked by the engine.

```
## Owner intent (generated by review-intent)
<!-- review-intent v1 asks=<sorted ids, comma-separated, or none> decisions=<same> sha256=<hex> -->
<body>
<!-- /review-intent -->
```

- **Body.** The lines between the marker line and the end line. For each ask: its summary, question, the chosen option, his answer and his own "Other" words verbatim, each follow-up on the ask (verbatim, oldest first, labelled with who wrote it unless he did; `review-intent` reads these from `ledger show ask N --history`, since `--json` leaves them out), the answered time, and why it was cited. For each decision: its summary, question, chosen option, why and ask. With nothing cited, the body is one line saying so and the marker reads `asks=none decisions=none`. Nothing time-dependent is in it, so the same ledger gives the same bytes.
- **The sha256** is of the body's UTF-8 bytes, taken with LF line ends (a CRLF brief is read as LF) from the first byte after the marker line's line end up to, not including, the end line. A body edited by hand no longer matches its marker.
- **What is cited.** Outside any earlier generated block, in the PR's agent record (`<traces dir>/emitted/review/<item>/pr-record.md`, which holds the `Decisions:` line; the PR description carries none, playbook 5a05bfe8; on a profile with no `pr-record` the `Decisions:` line stays in the handoff or the PR description) and the brief: every `#N` on a `Decisions:` line (decisions); every `ask #N` or `asks #N` (asks). `ask` is case-insensitive; an item is `#N` or a range `#N-#M` (hyphen, en dash or em dash, `#` on the end optional), and items join with `,`, `and` or `&` (`asks #1113-#1115`, `asks #5, #7 and #9`). Bold and italic marks on a `Decisions:` line are ignored. A bare number with no `#` is not a citation (`ask 5 minutes`). The marker lists those, plus: for a `--pr` that touches `leads/<type>.*`, the ask ids in `approved_by` of `leads/<type>.json` at the PR head (skipped when the file or the key is not there); each decision's `ask_id` and any `ask #N` in its why, and for each cited ask the ask its workstream's creation why names (one step; the asks found that way are not followed again). That why is free text, so there `ask 870` with no `#` counts for the first item or a range end (`asks 1113-1115`), a later item in a list still needs its `#` (so `ask #1175, 22:09Z` is one ask and a time), a bare number followed by a time or a unit (`ask 5 minutes`, `ask 5pm`, `ask 3 times`) is not an ask, while a `#N` is one unless a time follows (`ask #5:30`), and a number that is no ask is left out instead of refused. A follow-up is labelled with who wrote it. `review-intent` quotes ledger text so that no line of it can pass for the block's own end line.
- **Refused.** `review-intent` exits 1 and prints nothing when a cited id is not in the ledger. From agent-kit 0.63.0, `agent-traces review add` (not `--from lean-change`) exits 1 when the brief has no header with a v1 marker and end line, when the marker's sha256 is not the body's, or when the brief cites an ask or decision outside the block that the marker does not list. It reads no ledger: the check is of shape only. `agent-traces review brief-check` runs the same test. `agent-traces review verify --item <item> (--head <sha> | --any-head) [--require-block]` (a merge gate, same release) reads the item's log and, with `--require-block`, the passing round's brief.md, and runs this same test on it. `--item` is the log folder's name as given (`dotfiles#N` and `chezmoi#N` are one item); `--any-head` is for a Loop Engine run, whose last round decides whatever its head, and a lean-change round needs no block.
- **The reviewer** reads the block first and judges against it ahead of any restated intent (`reviewer-brief.md` §1).

## The conformance fixture

The fixture is `findings-conformance-v1.json`: cases of `{name, input, expected}`. `expected` holds `accepted`, then either the `verdict` and each finding's `effective` severity and demotion reason, or the `reject` code (a code, not message text). A string `input` is raw file text (the bad-JSON case). A case whose `expected` has `v0_reader: true` is skipped by an implementation that reads v0 records. A case whose `expected` has `envelope: true` tests the return's own shape, not a finding's fields; an implementation that does not parse the envelope skips it (Loop Engine does). The envelope cases are exactly those that reject with `bad-json`, `bad-schema-version`, `blank-reviewer`, `blank-head` or `bad-shape`; every other case is per-finding and every implementation runs it. The fixture does not test `brief_sha256`.

- The fixture is not kept in this folder. Its two byte-identical copies, and no others, live in the agent-kit `traces` component (`src/traces/fixtures/`) and loop-engine. The fixture's sha256 is `ffb5f849d93f77fcf723bf396832ec47d23829ef077f44cf3497830b007183f1` (26 cases). Each repo's test pins its copy's sha256.
- To change the fixture, change the kit's copy and loop-engine's copy and both pins together, in one change set.
- "Same schema" means the same finding fields and the same demotion rules. It does not mean the same envelope: Loop Engine runs the fixture's findings through its own per-finding check and its duplicate-id and unknown-severity checks, and does not parse them as its `Review`.

## The review log

Reviews of one item are kept in `${AGENT_TRACES_DIR:-~/.local/share/agent-traces}/emitted/review/<item>/`. It holds:

- `round-<N>/`: a folder per round holding the reviewer's `findings.json` and `REVIEW.md` (for several readers, see "Several readers in one round").
- `findings.jsonl`: the log. Append-only, one JSON object per line, each with `event` and a UTC `at`.
- `report.json`: a summary derived from `findings.jsonl` alone, defined in "The report" below.

Two round numbers. `N`, the *log round*, is counted across the item's stages, starts at 1 and is never reused; it names the folder and the ids `r<N>.<id>`, and is the `round` of every event. `review_round` is counted per stage within the current review sequence: 1 for a stage's first round in the sequence, then that stage's previous review round plus 1. It is the round number `reviewer-brief.md` §6 means, so a stage's first review in a sequence is round 1 (the whole diff) however many rounds of another stage came before it. A review sequence is the log rounds from one that starts a sequence up to the next: it starts at an item's first round and at a new design after a redesign switch; a change of stage does not start one. The exact rule is in the stuck-trigger paragraph below. (One counter for the whole sequence would give a diff review after three design rounds round 4 and only the fix diff; a log round counted per stage would make two stages collide in `r<N>.<id>`.) A round with several readers is still one log round and one review round.

`<item>` is `<repo>#<pr>`, a run id, or, for design work, `<folder>:<document>` (the work folder's name, a colon, and the document's name without its extension), so two documents in one folder do not share an item and a counter. `<repo>` is the repo's git directory name (`coordinator#217`), so a project label can be resolved from it.

**One item id per PR or per run.** A new PR or run gets a new item; an item id is never reused for a second PR or run. One item that spans several diffs makes the stuck and churn tests unreadable: they count rounds within one item, so rounds of unrelated diffs look like one review that never converges (`r720-ha-3member-2` held 29 rounds over several diffs). A PR that is reviewed again after a rewrite is still one item: the redesign path (`--new-sequence`) is for that.

`agent-traces review` writes the log (by hand until it ships). Every finding gets a log-wide id `r<N>.<id>` (round number, then the return's own id), because ids repeat across rounds; with several readers it is `r<N>.<reader>.<id>`, because ids also repeat across readers. Every other record points to a finding by that log id.

| `event` | Fields | Written when |
|---|---|---|
| `round` | `round` (the log round, here and in every other event), `review_round` (integer, ≥ 1; must follow the sequence rule in the trigger paragraph), `stage`: `mechanism`, `intent`, `plan`, `design`, `diff` or `other`, `new_sequence?`, `head`, `reviewer`, `verdict`: `pass` or `fail`, `session`, `model?`, `duration_ms?`, `cost_usd?`, `readers?` | The driver adds a round. `review_round` and `stage` are required. Written once per round, even when the return has no findings, so a clean pass leaves a line; a second add for a round already in the log is refused. `session` is the reviewer's session or thread id (it points back to the transcript). `cost_usd` is the round's cost. `readers` is present only when the round has several readers. `new_sequence` is `true` on a round that starts a review sequence and `false` on one that continues it; `agent-traces review add` writes it on every round. A round without it follows the earlier rule (`review_round` 1 starts a sequence; any other value is the previous round's plus 1 on the same stage), so older logs read as they always did. |
| `finding` | `id` (log id), `round`, `head`, `reviewer`, `severity`, `effective`, `demoted_reason?`, `component`, `text`, `obligation?`, `evidence?`, `consequence?` | The driver adds a round, one record per finding in its return. The round's `session` and `cost_usd` are on its `round` record, not repeated here. |
| `label` | `id`, `relation`: `new`, `repeat` or `follow-on`; `of?` (an earlier log id); `component?` | A fresh agent that is not the driver, on the Reviewer seat (the seat table's model, today Opus 5.5 medium; its brief's first line is `Seat: Reviewer. Model: Opus 5.5 medium.`), labels a blocking finding. The latest label wins. A label may replace `component`, so two spellings of one component count as one. |
| `disposition` | `id`, `outcome`: `fixed` (`sha`, or `artifact` when the fix lives outside the diff; rule 3), `rejected` (`reason`; it names the triage test it failed, see `finding-triage.md`) or `residual` (`accepted_by`) | The driver records what became of a blocking finding. |
| `redesign` | `component`, `round`, `blind_session`, `comparer_session`, `makes_impossible`: `yes` or `no`; `action`: `switched`, `rang-michael` or `kept-fixing` | The lead records the blind redesign check for a stuck component. |
| `judge` | `round`, `session`, `verdict`: `churning` or `not-churning` | A fresh judge who is not the driver, on the Reviewer seat (the seat table's model, today Opus 5.5 medium; its brief's first line is `Seat: Reviewer. Model: Opus 5.5 medium.`), gives the churn verdict. The churn test reads the stage of the round just finished (that stage's last two review rounds in the sequence) and counts a round's blocking findings as for a one-reader round, leaving out same-round duplicates (defined in the stuck-trigger paragraph). Distinct findings from different readers each count. |
| `escape` | `item`, `head`, `round` (the round that passed the defect), `found_by` (a PR, issue or dogfood id), `text`, `of?` (the log id of an earlier note or demoted finding that named this defect) | Whoever finds a later defect that traces to a reviewed change. |

A finding record with `effective: note` is a residual. It needs no disposition and no label.

**The stuck trigger.** It is computed per component, using the component from each finding's latest `label` (a label's `component` replaces the finding's own). A component fires at log round *r* when it has an effectively-blocking finding whose latest relation is `repeat` or `follow-on` in log round *r* and again in log round *r*−1, that is, in two consecutive rounds *of one stage in one review sequence* (that stage's rounds in the sequence, in order; rounds of other stages between them do not break the run). It fires at the second of those rounds. A repeat cannot appear in a sequence's first round, so the earliest firing is the sequence's third round. A blocking finding with no component, from the finding or its latest label, is not counted until it has one. A *same-round duplicate* is a finding whose latest label is `repeat` or `follow-on` and whose `of` is a finding in the same log round: one defect raised by several readers, not the return of an earlier defect. It is left out of this count and of the churn count (the `judge` row), in every round; every other finding counts as in a one-reader round. A log round with several readers is one round for this count. The labeller on the Reviewer seat uses this only to merge readers' duplicates, so a one-reader round has none. A new sequence starts the count afresh. The labeller judges new, repeat or follow-on within the current sequence. The review round follows this rule: a sequence starts (review round 1) at an item's first round or at a round marked as a new sequence (`--new-sequence`, used for the first round of a new design after a redesign switch); every other round counts per stage: review round 1 for the first round of its stage in the sequence, otherwise that stage's previous review round in the sequence plus 1. `agent-traces review add` checks it; by-hand logs follow it too. A trigger is *skipped* when that component has no `redesign` event at or after the log round it fired. The kit's review tool computes the trigger once and writes the result to `report.json`; the agent-events reader reads that file and computes no trigger.

**What `add` refuses, besides a bad review round.** (`agent-traces review add` v0.60.0 and later; playbook 58fdb05d steps 2 and 3.) `add` refuses round N+1 when the item's latest round N has `verdict` `fail`, a `review_round` of 2 or more, no `judge` event for round N, and no `redesign` event for round N whose `action` is `switched` or `rang-michael`. The refusal names the missing step and the two commands (`review record judge`, `review record redesign`). A `kept-fixing` redesign does not satisfy it (step 3 still owes a judge); a `churning` verdict does (the judge has run; what follows is the driver's). A pass, a round at review round 1 and the first round of a new sequence after a `switched` redesign are not refused. `add` also refuses while a component is stuck and has no redesign, and a round without `--new-sequence` right after a `switched` redesign.

## Several readers in one round

A log round can hold several **readers**: each returns its own review of the same head in the same round. A round with a single reader is unchanged: `round-<N>/findings.json`, ids `r<N>.<id>` and the `round` event are as defined above.

- **Folder.** One sub-folder per reader, `round-<N>/<reader>/`, each holding that reader's `findings.json` and `REVIEW.md`. The round folder holds no `findings.json` of its own. `<reader>` is a short slug the driver chooses (`a`, `b`, `simplicity`), unique within the round. Every reader's `head` is the same; `add` refuses a round whose readers' heads differ.
- **One `add` for the round.** The `round` line is written once, so one `add` carries every reader (each as a `--reader`, with its return and optionally its session, model and cost). It validates every return first, then writes one `round` event, then every reader's findings. A `finding` record's `reviewer` is the `reviewer` of the return it came from. The driver waits until all readers have returned. A later `add` for the same `N` stays refused. The several-reader and single-return forms cannot be mixed in one `add`.
- **`round` event.** It gains an optional `readers`: `[{ "reader", "session", "model?", "verdict", "cost_usd?" }]`, one entry per reader in the order given. The top-level fields stay, so a log reader that ignores `readers` needs no change: `verdict` is `fail` if any reader's is `fail`; `cost_usd` is the sum of the readers' known costs (partial when some are unknown; the `readers` entries show which), absent if none is known; `model` is set when all readers share one model, else absent; `session` and `reviewer` are the first reader's. With one reader the event has no `readers`.
- **Labels.** The labelling agent on the Reviewer seat merges a defect that several readers raise in the same round: it labels one finding `new` and each duplicate `repeat` with `--of` the same-round finding (a same-round duplicate, defined in the trigger paragraph).
- **Report.** `report.json` gains an optional `rounds` (see "The report").

## The report

One file per item, `<item>/report.json`. It is derived from `findings.jsonl` alone and rewritten by every write verb and by `report`. It carries ids, counts and enumerated values only: no component names, no text, no session ids. Canonical bytes: `JSON.stringify(report, null, 2) + "\n"` with keys in the order below.

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
| `findings_schema` | integer; the return version the log was written under (`1`). Log lines carry no such field; the tool refuses any return that is not 1. |
| `item` | the item, as in the folder name. |
| `log.lines` | non-empty lines in `findings.jsonl` when the report was written; a different count means the report is stale. |
| `log.events` | count of lines per event kind. Their sum equals `lines`. |
| `summarises.events` | the event kinds this report accounts for; a kind in the log that is not listed means the log is newer than the report. |
| `summarises.fields` | for each kind, the fields the report reads (provenance only; a reader does not check log lines against it). |
| `sequences[]` | one per review sequence, in order: its ordinal (1-based), first and last log round, and the stage of its first round. |
| `rounds[]` | optional; present only when at least one `round` event has `readers`, then one entry per such round, in log order: the log round and the readers' slugs in the event's order (verdicts stay in the log). It sits after `sequences` and before `findings`. A log with no `readers` has no `rounds` key and its bytes are as before; `summarises` is unchanged. |
| `findings[]` | one per `finding` event, in log order: log id, log round, the sequence ordinal, `effective` (`blocking` or `note`), `relation` (the latest label, or `null` for a note or an unlabelled finding), `outcome` (the latest disposition: `fixed`, `rejected`, `residual`, or `null`), `has_component` (from the finding or its latest label). |
| `stuck[]` | one per component firing, in order: the sequence, the log round and review round it fired at, and `skipped` (no `redesign` for that component at or after that round). Two components firing at one round give two entries; the names stay out. |
| `counts` | `needs_component`: effectively-blocking findings with no component; `undisposed_blocking`: effectively-blocking findings with no outcome; `skipped_redesigns`: `stuck` entries with `skipped` true. |
| `state` | `passed` when the last `round` event's verdict is `pass`, else `open`. An item with no `round` event has no report. |

A change to a field, a name or a meaning is a new `report_schema`; adding the optional `rounds` is not (no field a v1 reader validates changes). The golden log pairs (a `findings.jsonl` and its `report.json`) live in the kit and in dotfiles (the reader's test), vendored byte for byte and pinned by a manifest sha256; they change together, in one change set, as with the fixture. The set covers a treadmill (stuck at review round 3), a clean pass, a design-then-diff pair (sequence boundary), a redesign switch (`--new-sequence`), a missing component then a label that supplies it, an interleaved design/diff history (stuck at the third design round) with its old-way control (no `new_sequence`: no stuck), and a hand-written log.

## Version

v1. A change to a field, a rule or a record shape is a new version of this file and of the fixture, and both implementations move together. These belong to v1: the owner-intent block (a brief requirement; the return, the log and the fixture are unchanged); the log-record additions made before any tool wrote the log (`review_round`, `stage`, `model`, `duration_ms`, `escape.of`, the round folder, the `<folder>:<document>` item form); `report.json` and its `report_schema` (1), added before any tool writes it; and three additive amendments. Several readers in one round (see its section) was made before any tool writes it; a log with one reader per round is read and written as before. The per-stage review round (`new_sequence`, the sequence rule, the stuck and churn reading by stage) leaves `report.json` and `report_schema` unchanged, and a round without `new_sequence` is read under the earlier rule. The disposition `artifact` field (a `fixed` disposition whose fix lives outside the diff carries an `artifact` reference; `disposition-check`, a dotfiles script, enforces it; no tool writes the field yet) is the third. The return and the fixture are unchanged.
