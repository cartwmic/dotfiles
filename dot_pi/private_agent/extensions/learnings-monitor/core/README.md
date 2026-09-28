# Learnings monitor core

`index.mjs` is the source-neutral opportunity/review operation. It has no Pi,
Hindsight, filesystem, or other runtime imports. Adapters provide bounded,
privacy-filtered activity and proposals; the core checks evidence references,
merges records, derives truthful evidence claims, and returns changes without
writing them.

## Stable contract

- An activity has a stable opaque `source.id` and evidence items with stable
  IDs, short summaries, outcomes, and opaque provenance pointers. `context`
  may carry producer-specific information such as a branch label; the core does
  not interpret it.
- A proposal is `type: "friction" | "improvement"`, an observation, an
  optional recommendation (required for improvements), and one or more IDs
  from the accompanying activity. Unsupported evidence references are
  rejected.
- `reviewActivity({ activity, proposals, records, relatedEvidence })` returns
  `{ changes, suppressed, rejected }`. `changes` contains only new or changed
  records, so a store can preserve untouched records and owner edits.
- Records are keyed by source plus normalized type/observation/recommendation.
  Re-use a stable source ID and stable proposal wording when continuing a
  source. Keep `record.id` / `proposalKey` opaque; do not use them as paths.
- One cited event yields an `observed` friction record or a `prospective`
  improvement claim. An improvement becomes `recurring` only with at least two
  distinct evidence references. Failed and incomplete outcomes remain explicit
  on their evidence.
- Dismissals remain suppressed when only known evidence is cited. New source
  evidence reopens the record without removing its dismissal history. A
  different recommendation is a distinct proposal and leaves the old
  dismissal intact.
- Related evidence is stored only under `analogues`, marked
  `possible-analogue` / `verifiedOccurrence: false`; it never proves
  recurrence. `reviewPatterns(...)` is a separate, explicitly requested
  grouping operation and accepts a group only when its local records contain
  evidence from at least two distinct sources.

The core bounds each evidence excerpt to 240 characters but does not redact
secrets. Producers must filter content before calling it. A `pointer` is opaque
and `availability: "unavailable"` lets an adapter state that the original
source can no longer be opened without deleting the surviving evidence record.

## Minimal producer example

```js
import { reviewActivity } from "./index.mjs";

const result = reviewActivity({
  activity: {
    source: { id: "producer:work-item-17", label: "work item 17" },
    evidence: [{
      id: "event-1",
      summary: "A report was assembled manually.",
      outcome: "completed",
      provenance: { pointer: "opaque://work-item-17/event-1", context: "experiment" },
    }],
  },
  proposals: [{
    type: "improvement",
    observation: "Report setup was manual.",
    recommendation: "Consider a reusable setup script.",
    evidenceIds: ["event-1"],
  }],
  records: [],
});

// result.changes[0].evidenceAssessment.claim === "prospective"
// result.changes[0].status === "open"
```

To build recurrence across later batches, pass the same `source.id`, the
previous returned record in `records`, and a proposal citing the new evidence
ID. `setReviewStatus(record, "kept" | "dismissed", { at })` records an explicit
review decision.

## Handoff examples for T2-T6

- **T2 — Pi activity bridge:** translate a primary session/tree event to the
  generic `Activity` shape. Use opaque source/evidence pointers and retain
  branch context; keep all Pi APIs outside this directory.
- **T3 — observer/proposer:** return `OpportunityProposal` values that cite
  only supplied activity IDs. Do not write a record or claim recurrence in
  free text; the core derives the evidence assessment.
- **T4 — optional related lookup and cross-source review:** pass lookup hits as
  `relatedEvidence` and associate them with `relatedEvidenceIds`; they remain
  labelled analogues. Call `reviewPatterns({ records, proposals })` only from
  the explicit cross-source review action.
- **T5 — local record store:** persist each item in `changes`, re-read current
  Markdown before applying it, and retain `reviewHistory`. Do not replace
  untouched or hand-edited records with the whole result.
- **T6 — Pi operator surface:** render the same records/status the local store
  uses; use `setReviewStatus` for keep/dismiss. There is no Pi-specific core
  wrapper or second review implementation.

## Portability check

From this directory, the fixture is a direct standalone producer using the
same operation (not a Pi wrapper):

```sh
node portable-fixture.mjs
node --test
```

The fixture runs in a separate Node process and prints an open friction record,
a one-event prospective suggestion, and a two-event recurring suggestion.
