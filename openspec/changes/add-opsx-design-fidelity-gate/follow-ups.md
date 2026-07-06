# Follow-ups — add-opsx-design-fidelity-gate

<!--
Non-blocking items routed out of the analyze rounds (residual numbering from
analyze.md) and the apply phase. None gate this change.
-->

## F1 — Pre-worktree `.git/index.lock` contention under concurrent orchestrators (analyze residual 4)

Two orchestrators sharing the integration checkout pre-worktree can race
`git commit` / `git status` on the same `.git` (index.lock). Git's lock is
safe (loud error, no corruption); the miss is ergonomic — the loser sees a raw
git failure instead of the deterministic voided-round path. Candidate: a small
bounded retry (2–3 attempts, ~200ms backoff) around the snapshot/bookkeeping
git calls in the loop skill prose. Operational note only; no spec change.

## F2 — Manifest Validation cwd mechanism named only generally (analyze residual 6)

The `Manifest Validation Execution` worktree-cwd guarantee is entailed by D7's
general worktree-only principle rather than a separately named design
mechanism (R9 sonnet Part B row 5, advisory). If a future change touches the
validation stage, name the cwd/`OPSX_*` export mechanism explicitly in its
design rather than inheriting the general citation.

## F3 — Read-only-window carve-out candidate: operator commits disjoint from every change's blast radius (R9 incident)

During this change's own analyze R9 window, an operator commit (`bdce1c2`,
`dot_pi/agent/settings.json.tmpl` — unrelated tooling config) advanced the
shared integration HEAD. Under the shipped rule the round voids (commit
touches paths outside every change dir); the round was counted as a logged
dogfood deviation because judged inputs were untouched and both attestations
matched the dispatched head. Candidate refinement: exempt intervening commits
whose paths are disjoint from the dispatched change's judged inputs AND from
all opsx-governed surfaces (gate/schema/skills/tests), keeping specs/templates
/code voids intact. Needs care — do not widen into a self-serve hole;
fail-closed default stands until a change takes this up.

## F4 — `fm()`/`bodyfield()` legacy readers now unused in the gate path

Task 1.3 left the live-disk readers defined (documentation value, low risk).
A cleanup change may remove or fold them once nothing else references them.

## F6 — Forward digest grep lacks comment-strip symmetry (code-review R1, opus F3, P3)

The forward `grep -F "**Digest sha256 (…)"` match reads raw committed content
while the reverse set-equality scan strips `<!-- -->` fences. A commented
digest line with a correct hash satisfies the forward leg only. Loosens only
(cannot forge without the true hash — inside the sealer trust boundary);
align both scans on comment stripping for symmetry.

## F7 — `tests/opsx-gate/test_author_marker.sh` legacy fixture writes the abolished key (code-review R1, sonnet method note, P3)

Still passes (assertions grep the author-marker check id, not exit code), but
the fixture should drop `worktree_mode: same-tree` at next touch.

## F5 — `sha256_stdin` / `sha256_file` helper duplication

Task 1.1 added a stdin variant local to the cheap phase; the shipped
`sha256_file` lives later in the file. A cleanup may hoist one shared helper
above both consumers.
