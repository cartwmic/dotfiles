# Reviewer examples

The bar is in `reviewer-brief.md`. These twelve real cases are for calibration: six that blocked and six that did not. Each says what happened, the call, and why, using the brief's four fields (obligation, evidence, consequence, component) or naming the one that was missing.

## Blocking

**B1. agent-kit #24: blocking.** A change folded old wake records using deltas against the newest stored wake, not the newest delivered one.
Why: data loss, so it always blocks. Evidence: a run that lost 2 of 3 parked records. Obligation: the approved change to fold old wakes. Consequence: parked records vanish. Component: wake folding.

**B2. coordinator #195: blocking.** The change broke journey 152, the acceptance journey for the seat text. The builder had run only its own new journeys.
Why: evidence is the reviewer's own run of 152, which failed on the head and passed on main. Obligation: the requirement that journey proves. Consequence: the regression would have merged. Component: seat text.

**B3. homelab #93: blocking.** A script dismissed every unscheduled-reboot alert on every re-apply. The approved intent was a one-time cleanup.
Why: obligation is the approved intent (once, not always). Evidence: the code lines that dismiss on every default run. Consequence: a real reboot alert is dismissed on a routine re-run, with output that looks normal. Component: alert cleanup.

**B4. coordinator #203: blocking.** Dropping the "Reading more" tail also dropped the only runnable ledger-bearings command that other instances had.
Why: a named promise broke (that command must stay runnable). Evidence: the diff. Consequence: other instances could no longer run it. Component: seat text.

**B5. homelab #94, round 2: blocking.** The round-1 fix made the read-only check crash whenever the snapshot task had drifted, which is when you run it.
Why: the reviewer reproduced it by wrapping the host call and driving the check to the crash. Obligation: the documented check must work. Consequence: no plan or preview exactly when drift exists. Component: read-only check. A fix can break what it touched, so a fix is read as new code.

**B6. coordinator #207, design review: blocking.** Before any code existed, the review found a delivery handover race: a drain check cannot stop a send aimed at the old thread.
Why: obligation is the approved redirect design. Evidence: the design text. Consequence: a message can still go to the old thread after the handover. Component: delivery handover. Design problems block while they are cheap to fix.

## Notes

**N1. coordinator design review D38, round 2: note.** A PR-body principles table marked principle 6 "Partial" instead of pass or fail.
Why: the obligation is real (one row per principle, pass or fail), but the consequence is a label in the table. No user hits it. Put it in the residuals.

**N2. homelab #94, round 3: note.** A code comment and a doc sentence said an update flag keeps removal dates when the lifetime shortens. The code was right; the sentence was not.
Why: the code and the guard that lists every snapshot that would expire were safe, and the fix was text only.

**N3. coordinator #206, design review: note.** The review also raised the wording of one requirement (LE-55) and a prose claim about smoke-test coverage.
Why: both were text fixes in the build brief and changed no behaviour. The same review's stall risk (an unacknowledged prompt row would block every later event) did block.

**N4. Eight small homelab PRs (#83, #84, #85, #87, #88, #89, #90, #92): notes.** Each got 3 to 6 findings (unverified post-rollout state, an undo that restores the earlier exposure, test gaps) and all passed in round 1 under "the bar is good enough".
Why: the reviewers found no merge blocker in any of them. List them. Do not hold the pass.

**N5. A Pi-host run, diff review: not raised.** A reviewer called the proof weak because the old-tree runs failed at start-up on a missing module, not on behaviour. The driver rejected it.
Why: the approved intent set the old behaviour as absent, and each fix had a failing-first test shown separately. No obligation was broken. At most a note.

**N6. The R3 intent check, round 10: note.** A finding on the exit code and output when a decision write fails after the write, in an intent document for a mechanism not yet built.
Why: a wording gap in a document, with no user to hit it. It was a follow-on of the round-9 fix to the same wording.
