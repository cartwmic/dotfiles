<!-- authored: in-session -->
## Context

The 2026-07-03 session drove two changes to green through the opsx loop and exposed
four gaps in the loop host itself (catalogued in intent.md as G-A..G-D). The deployed
extension was also drift-stale — ADR-0014 (draft-only distill + confirm pause), Guard 1
(turn-0 `pre.met`), and the distill stall guard already existed in source — so this
change fixes only what is real in current source. Constitution: deterministic
extension/gate (no model in any decision path, ADR-0007 lineage); kickoff-vs-continuation
directive split is load-bearing (2026-07-01 drift incident); Constitution IX applies
(existing-skill edits).

## Goals / Non-Goals

**Goals:**
- Goal-mode kickoff has a defined, deterministic relationship to pre-existing changes.
- The distill directive cannot be read as license to implement.
- Agents can land the loop deterministically; only humans can un-land it.
- Gate and extension resolve the same worktree from either checkout.
- Stall guard fires after exactly its configured turn count.

**Non-Goals:**
- Soft/hard hold tiers; semantic goal↔change matching; green-sweep/memoization
  (superseded by D1); round-ledger mechanization; archive/push behavior.

## Decisions

### D1: Explicit-resume-only latch; no goal-text matching

**Choice:** `goal`/conversation kickoff never latches a pre-existing change; the sole
latch spelling is `/opsx-loop <change-name>` (Guard 1 already handles green). No exact
or substring goal-text↔change-name matching anywhere.
**Rejected:** (a) green-sweep at distill agent_end with memoization — cost/staleness
machinery for a tie (green vs goal-match) the extension cannot decide; (b) semantic
latch — model in the extension path, ADR-0007 violation; (c) text matching — successor
goals reference predecessor names as context ("fix the follow-ups from
add-opsx-review-convergence") → false latch.
**Consequence:** Scene "user forgot the change exists" degrades to inventory advice
(D2) + stall landing, never a wrong latch. Extends the explicit-keywords-over-heuristics
grammar decision from parse-time to latch-time.

### D2: Deterministic active-change inventory in the distill kickoff

**Choice:** kickoff directive lists changes with committed intent.md (name +
front-matter status) via directory listing + front-matter parse; instructs stop + advise
`/opsx-loop <name>` on coverage. Kickoff directive only — continuation nudge stays terse.
**Rejected:** per-turn gate runs for status (cost, and green≠match anyway); omitting the
inventory (duplicate-distillation risk unmitigated).

### D3: Distill-scoped autonomy text

**Choice:** distill directive carries "draft autonomously; do NOT implement; STOP after
announcing"; the drive-to-green AUTONOMY blurb remains on worker/continuation directives
only. Fixes the observed self-contradiction (directive says STOP, blurb says keep going).

### D4: `loop_hold` front-matter as the landing channel

**Choice:** `loop_hold: true` + mandatory `loop_hold_reason` in review.md front-matter,
written to the integration-checkout copy (the copy the loop host resolves — clarify I2),
checked at `agent_end` before continuation injection. Gate stays ignorant of hold state.
**Rejected:** sentinel file (unversioned, outside structured-field convention); pi
keyword/tool (harness-coupled, ADR-0007); relying on prose landings + stall burn
(observed failing this session).
**Fail-safe:** hold honored even with an empty reason (clarify C1) — a malformed landing
must still land.

### D5: Hold cleared only by explicit named re-arm

**Choice:** `/opsx-loop <change>` — human-only slash command — clears the hold, surfaces
the stored reason in the arm notification, appends an Execution Notes line, then proceeds
with normal kickoff evaluation (Guard 1 may still short-circuit green — clarify I3).
Goal kickoff never clears any hold. Agents have no clear path.
**Rejected:** manual front-matter edit (ceremony mismatch; only prose stops the agent
from self-clearing); soft/hard tiers (doubles the state machine; front-matter cannot
verify an audit ruling happened — deferred seam).
**Rationale:** the same human-only channel property that prevents agents from halting
the loop prevents them from un-halting it — symmetry is the security argument.

### D6: Locator publication + convention fallback

**Choice:** primary — apply records `Worktree Path` + `Diff Base SHA` in review.md
committed to the integration checkout at worktree creation; backstop — gate CLI and
extension `resolveWorktree` probe the canonical `opsx worktree` path when the recorded
locator is absent/invalid (validated as a worktree on `opsx/<change>`). Explicit
`--worktree` that fails validation fails loudly — the fallback covers the recorded
locator only (clarify C3).
**Rejected:** publication-only (pre-rule changes keep split-braining); fallback-only
(locator field becomes decorative; convention path silently load-bearing).
**Cost accepted:** archive merges become non-ff (proven survivable twice this session).

### D7: Stall baseline seeded at arm

**Choice:** seed `lastDirs` from the `preChangeDirs` snapshot already captured at arm
(index.ts:404), so the turn-1 evaluation counts and STALL_LIMIT=3 costs exactly 3
distill turns; notify wording stays truthful. Observed live: the pre-arm distill for
this very change burned 4 turns.

## Implementation notes

- Extension: `dot_pi/agent/extensions/opsx-loop/index.ts` — distill directive builder
  (~line 331: inventory + scoped autonomy), distill stall block (~487: seeding),
  `agent_end` continuation path (hold check before inject), named-arm path (hold clear +
  surfacing), `resolveWorktree` (~205: fallback). Pure helpers (inventory formatting,
  hold parsing, canonical path) land in `helpers.ts` with unit tests.
- Gate: `dot_local/bin/executable_opsx` — worktree resolution fallback next to the
  existing locator read; `fm()` front-matter reader untouched (gate never reads hold).
- Skills: openspec-loop SKILL.md landing prose → set `loop_hold`; apply-mode reference →
  locator publication step at worktree creation.
- Template: review.md commented `loop_hold` / `loop_hold_reason` keys.

## Risks / Trade-offs

- **Non-ff archive merges** from locator publication — accepted, observed survivable.
- **Hold parse divergence** between extension (TS) and any future gate reader — bounded:
  gate is specced to ignore hold fields entirely.
- **Residual duplicate distillation** if the agent ignores the inventory — stall guard
  remains the landing; severity drops from wrong-work to wasted-turns.
- **Convention-path fallback picking a stale worktree** — bounded by branch validation
  (`opsx/<change>`) and locator-first ordering.

## Migration

Additive. Absent `loop_hold` ⇒ unchanged behavior; empty locator + no convention
worktree ⇒ unchanged behavior. No data migration; pre-rule changes served by fallback.
