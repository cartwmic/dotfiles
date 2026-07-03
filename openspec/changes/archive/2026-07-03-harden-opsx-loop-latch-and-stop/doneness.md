# Doneness

**Doneness:** satisfied

**Judge:** claude-bridge/claude-opus-4-8 via pi-subagents dispatch
**review_mode:** blind-single-judge
**Frozen-Intent SHA:** bd9fe801c5219e6f7457674e3090659102479c619831806b857dd353f35ba6ba
**Diff Base SHA:** d84a2e4f9ed0aeef52529ab14c00db8fe4e7c15a
**Reviewed Range:** d84a2e4..863192d

## Verdict rationale

Every frozen design decision (1-6) and every invariant in intent.md maps to
delivered, test-covered state in the diff: explicit-resume-only latch with no
goal↔name matching, kickoff-only active-change inventory, distill-scoped
autonomy, the `loop_hold` landing channel with named-re-arm-only clearing, and
single-source locator publication + convention fallback across gate, CLI, and
extension. No decision demands beyond-scope work to be considered met.

<!--
Decision → evidence mapping (blind, diff d84a2e4..863192d):

1. Explicit-resume-only latch (G-A). SPEC opsx-loop-kickoff "Goal and
   conversation kickoff": goal/conversation NEVER latch; `/opsx-loop <change>`
   sole latch path; NO goal-text↔change-name matching (scenario "Goal mode
   never latches a pre-existing change"). CODE index.ts goal/set split — goal
   arm just distills, no name comparison anywhere; Guard-1 turn-0 short-circuit
   handles green resume. SATISFIED.

2. Active-change inventory in the distill KICKOFF directive (G-A mitigation).
   CODE helpers.ts listIntentChanges (readdirSync + intent.md exists + injected
   isCommitted predicate; scale via front-matter parse only, no gate/model) +
   formatInventory (helpers.ts:386); index.ts distillDirective builds inventory
   from committedIntentNames (git ls-tree HEAD, excludes archive/staged);
   distillContinuation is terse WITHOUT inventory (kickoff-vs-continuation split
   preserved). Test: helpers.test.ts "formatInventory renders directive lines;
   empty → (none)". SATISFIED.

3. Distill-scoped autonomy blurb (G-B). CODE index.ts DISTILL_AUTONOMY (draft
   autonomously, do NOT implement, STOP after announcement) replaces generic
   AUTONOMY on the distill directive; worker/continuation directives keep the
   drive-to-green AUTONOMY. SPEC scenario "Distill directive autonomy is
   distill-scoped". SATISFIED.

4. `loop_hold` front-matter field (G-C). CODE helpers.ts parseLoopHold
   (anchored loop_hold: true, honored with empty reason); index.ts agent_end
   checks hold FIRST and lands (clearLoop + preserve worktree + notify reason)
   before any continuation injection. SKILL.md landing prose updated to "set
   loop_hold + reason on integration-checkout review.md". Template documents
   keys (gate ignores them). Tests: helpers.test.ts hold-with-reason,
   empty-reason-fail-safe, YAML True. SPEC ADDED "Loop hold blocks continuation"
   + opsx-workflow-schema "Loop hold front-matter keys" (gate-ignores scenario).
   SATISFIED.

5. Hold clearing = explicit named re-arm only (D5). CODE helpers.ts
   stripLoopHold + clearHoldText (strips fields, appends auditable Execution
   Notes line, line-anchored heading, $-safe replacement fn); index.ts set path
   clears hold BEFORE turn-0 gate regardless of outcome, surfaces "hold was
   set… cleared by re-arm" in arm notify; goal kickoff never touches holds.
   Tests: clearHoldText appends note, creates heading when absent, survives
   $-patterns, anchors exact heading. SPEC scenarios "Named re-arm clears the
   hold…", "Goal kickoff never clears a hold". SATISFIED.

6. Locator publication + convention fallback (G-D). CODE executable_opsx:
   single-source opsx_wt_convention_path/opsx_wt_for_branch/opsx_wt_valid_for_change
   (normalized to MAIN worktree root for integration↔worktree parity); gate
   validates explicit --worktree loud, else recorded locator, else convention
   fallback; `opsx worktree path` read-only emit (no side effects). index.ts
   resolveWorktree validates locator on branch then conventionWorktree via
   `opsx worktree path` (never re-derived). apply-mode reference: MANDATORY
   locator commit on integration branch. Tests: opsx-gate convention-fallback +
   explicit-worktree; opsx-cli read-only path emit, no side effects,
   convention-only after --path override. SPEC opsx-cli "Read-only worktree path
   emit", opsx-gate-enforcement "Worktree locator published to the integration
   checkout" + convention-fallback scenario, opsx-loop-kickoff "Worktree
   resolution convention fallback". SATISFIED.

Invariants:
- Set-hold no-privilege / clear = human act → D4/D5 code, no agent-reachable
  clear (clear only in human-only /opsx-loop <change> set path). MET.
- Green pre-existing change never silent re-kickoff → Guard-1 turn-0
  short-circuit (index.ts set) + goal mode ignores by construction. MET.
- Gate result identical from integration checkout vs worktree → single-source
  convention path normalized to main root + branch validation on both surfaces.
  MET.
- Continuation nudges terse; inventory/autonomy ride kickoff only →
  distillContinuation carries neither. MET.

Constraints: extension/gate stay deterministic + model-free (dir listing +
front-matter parse + git plumbing only); keyword grammar unchanged (goal still
offered in completions, no new parse heuristics); ADR-0014 / Guard-1 / Guard-2 /
kickoff-vs-continuation split preserved; all stop paths land in notify + disarm,
never a merge. D7 stall-baseline seeding at arm time (lastDirs seeded from
preChangeDirs) makes STALL_LIMIT mean exactly STALL_LIMIT turns. MET.
-->
