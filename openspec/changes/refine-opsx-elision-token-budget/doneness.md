# Doneness

**Doneness:** satisfied

**Judge:** pi-subagents delegate — claude-bridge/claude-opus-4-8 (designated reviewer = first `review` role model; combined code-review dispatch)
**review_mode:** blind-single-judge
**Frozen-Intent SHA:** 35c7b5c52708c9234dbca1f1629c5ce325b70432f5bf6f79687dedd4859cd161
**Attested HEAD:** 0d1bf1ab4ce2ef3c4aee92657dc49a5d5ea9bb1f
**Diff Base SHA:** 3b3fc2a768690b653ddad3875608d25a6d2ad5aa
**Reviewed Range:** 3b3fc2a768690b653ddad3875608d25a6d2ad5aa..0d1bf1ab4ce2ef3c4aee92657dc49a5d5ea9bb1f

## Verdict rationale

The diff meets every frozen intent outcome over the reviewed range: token-budget
boundary snapped to turn edges replacing the turn-count boundary (decision 1);
`maxKeep = 40% of the live window` with no absolute floor (decision 2); 5%-of-window
band hysteresis with a band-quantized shed floor keeping the window bytes-bounded
regardless of turn sizes (decision 3); the separate activation threshold and all
turn-count / `OPSX_ELIDE_AT_*` knobs plus their helpers removed, elision firing when
the estimate exceeds `maxKeep+band` (decision 4); deterministic char/4 estimate with no
tokenizer/model call (decision 5); and the two folded-in advisories (the
`session.compacting` guard and distill-path consumption of `session.elided` via the
shared compaction-aware inject). All carried-over invariants — active-loop scope,
no history mutation, fail-closed structural/pairing guards, newest turn + system prompt
preserved, coupling consumed once per run, degrade-safe guards, auto-compaction stays
off — are intact. The one bound that cannot be met literally (`[maxKeep, maxKeep+band]`
lower half) is unsatisfiable in the frozen intent itself given the "never split a turn"
non-goal; the implementation resolves it toward the change's stated bytes-bounded-window
purpose (upper ceiling always holds), which the disclosure-consensus round accepted.
92 tests pass; each delta AC is backed by a non-tautological test.
