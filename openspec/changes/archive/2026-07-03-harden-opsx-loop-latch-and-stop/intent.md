# Intent — harden-opsx-loop-latch-and-stop

Status: explore-frozen

## Intent

Close the four residual opsx-loop gaps catalogued in the 2026-07-03 session
(oxide-clone treadmill follow-up; both review-convergence changes archived at
`379d635`), where the deployed extension re-prompted through a green terminal
state and the orchestrator misread a machine re-prompt as human archive
authorization. Post-`chezmoi apply` triage confirmed most observed misbehavior
was deployment drift (ADR-0014 draft-only distill, Guard 1 `pre.met`
short-circuit, and the distill stall guard already existed in source); this
change fixes only the gaps that are real in **current source**:

- **G-A — latch ambiguity.** Goal/conversation kickoff prose says "if an
  active change captures this work, use it as-is," but the extension has no
  latch path for pre-existing changes: no new change dir → distill directive
  re-injected until the stall guard fires. Green-vs-goal matching is
  undecidable by a deterministic extension (Scene A "green change IS the
  goal" and Scene B "green bystander" are indistinguishable repo states).
- **G-B — directive self-contradiction.** `distillDirective` ends "then STOP:
  the loop pauses for the user…" while the appended generic `AUTONOMY` blurb
  says "do NOT pause… keep going… the gate is the arbiter of done" — inviting
  the agent to treat the distill turn as license to drive the whole workflow.
- **G-C — no agent-invokable loop-stop.** `clear` is a TUI slash command;
  agents cannot invoke it. The review-convergence decision-audit landing's
  "halt loop continuation" is unenforceable agent-side; landing depends on
  agent prose plus stall-guard burn.
- **G-D — worktree-locator split-brain.** `resolveWorktree` (index.ts:205)
  and `opsx gate` read `Worktree Path` from the integration checkout only,
  while apply records it on the change branch → gate-from-main and
  gate-from-worktree disagree (red-loop observed this session; hot-patched by
  `750fd1a` for one change, unfixed as convention).

## Frozen design decisions

1. **Explicit-resume-only latch (G-A).** `goal <text>` and conversation-mode
   kickoff NEVER latch a pre-existing change — goal mode is new-change
   distillation by construction. Latching an existing change requires the
   explicit resume spelling `/opsx-loop <change-name>`, where Guard 1
   (turn-0 gate, `pre.met` → "ready to archive" notify without arming)
   already handles the green case. NO goal-text↔change-name matching
   anywhere — exact/substring matching was considered and rejected as a
   false-latch footgun (successor goals naturally reference predecessor
   change names as context, e.g. "fix the follow-ups from
   add-opsx-review-convergence"). This extends the existing
   explicit-keywords-over-heuristics grammar decision from parse-time to
   latch-time.
2. **Active-change inventory in the distill kickoff directive (G-A
   mitigation).** The distill kickoff enumerates `openspec/changes/*` entries
   having a committed `intent.md` (name + cheap front-matter status;
   directory listing + front-matter parse only — no gate runs, no model) and
   instructs: if one already covers the goal, do NOT create a new change —
   tell the user to resume via `/opsx-loop <name>` and stop. The distill
   stall guard (no change-dir delta for 3 turns) remains the deterministic
   landing. Inventory appears in the KICKOFF directive only, never the
   continuation nudge (kickoff-vs-continuation split is load-bearing).
3. **Distill-scoped autonomy blurb (G-B).** The distill directive carries a
   distill-specific autonomy text — draft the intent autonomously, do NOT
   implement, STOP after announcing the frozen intent — replacing the generic
   drive-to-green `AUTONOMY` blurb on that directive. Worker/continuation
   directives keep the drive-to-green blurb unchanged.
4. **`loop_hold` front-matter field (G-C).** review.md front-matter gains
   `loop_hold: true` + mandatory `loop_hold_reason`. Orchestrator-writable
   from any harness — setting a hold is the fail-safe direction and needs no
   privilege. The extension checks it at `agent_end` before re-injecting a
   continuation and, when set, stops the loop surfacing the reason. This is
   the agent-invokable landing channel the decision-audit outcome requires;
   openspec-loop skill landing prose updates from "halt via host loop-stop"
   to "set loop_hold with the audit reason."
5. **Hold clearing = explicit named re-arm only.** `/opsx-loop <change>` is a
   human-only slash command, so re-arm is itself the human-authorization
   channel — the same property that stops agents from halting the loop stops
   them from un-halting it. On named re-arm of a held change the extension
   clears the hold, surfaces "hold was set: <reason> — cleared by re-arm" in
   the arm notification, and records an Execution Notes line. Goal/
   conversation kickoff NEVER clears any hold. Single hold kind; soft/hard
   tiers explicitly deferred (front-matter cannot verify an audit ruling
   happened anyway — the reason string carries the audit pointer).
6. **Locator publication + convention fallback (G-D).** Primary: the apply
   skill records `Worktree Path` + `Diff Base SHA` in review.md **committed
   to the integration checkout** at worktree-creation time (non-ff archive
   merges are the accepted, proven cost). Backstop: `opsx gate` and
   `resolveWorktree` gain a convention-path fallback — when the locator is
   empty/stale, probe the canonical `opsx worktree` path and use it iff it is
   a valid worktree for the change. Both surfaces stay deterministic.

## Constraints

- Extension stays deterministic and model-free: no semantic matching, no LLM
  in any extension or gate path (ADR-0007 lineage).
- Keyword grammar unchanged (`goal <text>` | `goal` | `<change-name>` |
  status/clear/models); no new heuristics at parse time.
- Preserve ADR-0014 draft-only distill + confirm pause, Guard 1, Guard 2, and
  the kickoff-vs-continuation directive split (architectural principle:
  collapsing them breaks in-session loop behavior).
- Constitution IX: this change edits existing skills → adversarial
  multi-model gating review; review-convergence discipline (verdict contract,
  severity floor, round ledger, `review_max_rounds`) applies to this change
  itself.
- Loop never archives; all stop paths land in notify + disarm, never a merge.

## Invariants

- Setting `loop_hold` requires no privilege; clearing requires a human act
  (named re-arm). No agent-reachable clear path.
- A green pre-existing change can never cause silent re-kickoff (Guard 1 on
  resume; goal mode ignores it by construction).
- Gate result for a change is identical whether resolved from the integration
  checkout or the worktree (locator convergence).
- Continuation nudges stay terse; inventory and autonomy text ride the
  kickoff directive only.

## Non-goals

- Soft/hard hold tiers (deferred seam; reason string suffices in v1).
- Semantic goal↔change latch or any green-sweep/memoization machinery — the
  earlier G-A1 sweep proposal is superseded by decision 1.
- Gate/extension mechanization of the review-convergence round ledger
  (separate deferred hardening).
- Reconciling the adversarial-review-cycle skill's convergent-findings table
  with the no-matching rule (P3, queued in the archived polish change's
  follow-ups.md).
- Any change to archive behavior or push policy.

## Supersedes

- The G-A1 "gate-at-distill-agent_end green-sweep with intent.md filter and
  progress-token memoization" proposal (this session, pre-decision) —
  replaced by explicit-resume-only latch + kickoff inventory.
- The kickoff prose "if an active change with a frozen intent.md already
  captures this work, use it as-is" as an *extension-observable* contract —
  under decision 1 that sentence moves from latch semantics to advisory
  guidance backed by the inventory + resume instruction.
