# openspec-apply-change under schema: opsx-superpowers

Loaded when step 2.5 detects `schemaName == "opsx-superpowers"`. Adds mode dispatch, file contracts, intent-aware repair, and post-apply skill artifacts.

## Pre-apply: read modes from review.md

Parse `openspec/changes/<name>/review.md` to extract:

```
Scale                  = <XS | S | M>
full_rigor             = <false | true>   (true = the former L/XL extras)
Execution Mode         = <standard | tdd-preferred | tdd-required>
Verification Mode      = <inline-only | retained-recommended | retained-required>
Debug Mode             = <standard | systematic-debugging>
Review Status          = <not-requested | requested | findings-received | resolved>
Delegation Mode        = <single-agent | subagent-eligible | subagent-required>
Code Review Mode       = <none | advisory | gating-required>
Loop Max Iterations    = <positive integer or unset>
Validation Source Mode = <required | waived>
Doneness Mode          = <required | waived>
Spec Level             = <spec-anchored | spec-first | spec-as-source>
Model keys (optional)  = author_model / review_models / impl_model /
                         author_in_session / provider / *_provider
```

If `review.md` is missing, STOP and author it first (the gate hard-fails on a
missing/unparseable Scale — there is no implicit-XS fallback; the README
default Scale for a new review.md is S).

## Pre-flight commit (unconditional — worktree is the only model)

```bash
cd <project root>
git status --porcelain openspec/changes/<name>/
```

If any unstaged or uncommitted files under that subtree, stage + commit ONLY that subtree on the integration branch:

```bash
git add openspec/changes/<name>/
git commit -m "chore(opsx): pre-flight commit for apply of <name>" -- openspec/changes/<name>/
```

The commit is path-scoped (`git commit -m "<msg>" -- <paths>` — message flag BEFORE the `--` pathspec terminator) — never a bare `git commit`/`git add -A` — so an unrelated dirty file in the integration checkout cannot ride along into workflow-driven history.

Then create the worktree on branch `opsx/<name>` per the pi-subagents convention.

## Worktree lifecycle + immutable Diff Base SHA

Worktree execution is the ONLY model at EVERY Scale including XS — apply ALWAYS creates/reuses the `opsx/<name>` worktree via `opsx worktree ensure` before any implementation task, runs ensure → locator capture → implement → review → merge → cleanup, and there is no same-tree path, no tier derivation, and no `worktree_mode` switchboard key (a `worktree_mode` key in review.md front-matter is a fail-closed gate red naming the delete-the-key remedy).

**Creation/reuse is runtime-owned**: call the deterministic lifecycle command instead of hand-rolling git worktree commands — it implements the exact spec semantics (create with immutable merge-base, reuse with base-ancestry check, abort on failure):

```bash
opsx worktree ensure <name> [--integration-branch <b>]
# On success prints the locator fields to write into review.md body:
#   WORKTREE-OK <created|reused>
#   Diff Base SHA: <sha>          # immutable merge-base (NOT apply-start HEAD)
#   Worktree Path: <path>
#   Integration Branch: <branch>
```

**Locator publication (MANDATORY, at worktree creation)**: write the printed locator fields (`Diff Base SHA`, `Worktree Path`, `Integration Branch`) into review.md and COMMIT that edit ON THE INTEGRATION BRANCH (the integration checkout), not solely the change branch. The gate and the loop host resolve review.md from the integration checkout — a locator that exists only on `opsx/<name>` split-brains them into judging the wrong tree (observed red-loop). The resulting non-fast-forward archive merge is the accepted cost. The gate's convention-path fallback covers only pre-publication changes and default-path worktrees — it is a backstop, not a substitute. (opsx-gate-enforcement.worktree-locator-published-to-the-integration-checkout)

**On reuse** (branch `opsx/<name>` already exists from a prior aborted apply): the command PRESERVES the recorded `Diff Base SHA`; if it is absent or not an ancestor of `opsx/<name>`, it exits 1 — HALT for human repair rather than re-recording a base that would exclude unverified commits.

**On creation failure** (path conflict / detached HEAD / no space / permission): the command exits 1 with an actionable error — ABORT; do NOT proceed to any implementation task.

**Abandoned change**: `opsx clean <name>` removes the worktree + `opsx/<name>` branch (refuses a dirty worktree without `--force` — unsealed verdict files live uncommitted there).

ALL file-contract diffs use the immutable `Diff Base SHA`, NOT `HEAD`, so per-task commits stay in the diff:

```bash
git -C <worktree-path> diff --name-only <Diff Base SHA>..HEAD
```

## Per-task workflow

For each task `- [ ] X.Y <description>` in `tasks.md`:

1. **Read contract fields** (sub-bullets under the task):
   - `intent`: fix | feature | refactor | infra (default: feature)
   - `files_allowed`: minimatch globs list (default: unrestricted)
   - `files_forbidden`: minimatch globs list (default: empty)
   - `allow_new_files`: bool (default: true)

2. **Read covering plan steps** from `plan.md`. Filter to plan steps whose `Covers:` line includes `T<X.Y>`.

3. **Dispatch:**
   - If Delegation Mode = single-agent: execute inline.
   - If Delegation Mode = subagent-eligible | subagent-required:
     - Use the `pi-subagents` skill (capability hook: subagent-driven-implementation).
     - Pass: task description, contract fields, covering plan steps, intent.
     - **Model (armed loop):** WHILE `/opsx-loop` is armed, dispatch via
       `opsx_dispatch({ role: "impl", task })` — role is sole model source;
       do NOT soft-honor `model:` on generic `subagent` (muted). Unset impl →
       `opsx_dispatch` refuses; treat refusal as correct (no session fallback).
     - **Model (disarmed):** MAY use generic `subagent` with configured `impl`
       (`OPSX_IMPL_MODEL` / `opsx models impl --change <name>`) as `model:`
       (already provider-qualified). Unset → skill default.
     - Subagent returns a structured handoff; main agent does writeback.

4. **Execute the work.** If Execution Mode = tdd-required, the plan steps' 5-step micro-task structure applies (failing test first).

5. **Run validators.** Use the project's `project.md` validator list (typecheck / lint / unit tests / integration). If any fail:

   Build the repair prompt:
   ```
   ## Validation failures

   <task description>

   ## Constraints (intent: <intent>)

   <constraints block per intent — see below>

   ## Issues

   <one row per validator failure:>
   - [error] <validator>:<rule-id> (<file>:<line>): <message>
   ```

   Intent-specific constraints:

   - `fix`:
     ```
     Fix only failing validators. Do NOT refactor unrelated code.
     Do NOT add new features. Tests MAY be added when TDD mode is on.
     Checkpoint after every iteration.
     ```
   - `feature`:
     ```
     Stay within files_allowed; no scope creep.
     ```
   - `refactor`:
     ```
     Stay within files_allowed; unrelated cleanup permitted.
     ```
   - `infra`:
     ```
     Stay within files_allowed; dependency / build / CI changes
     permitted.
     ```

   Re-run the implementer with the repair prompt. Repeat until validators pass or user halts.

6. **Contract check.** Run:
   ```bash
   git -C <worktree-path> diff --name-only <Diff Base SHA>..HEAD
   ```

   For each touched file, check against `files_allowed`, `files_forbidden`, `allow_new_files`.

   **TDD exemption:** if Execution Mode = tdd-required AND `allow_new_files = false`, ALSO permit new files matching `tests/**/*`, `**/*.test.*`, `**/*_test.*`, `**/__tests__/**`.

   Report any `scope_violation` findings. Block task completion until resolved (or user amends the contract).

7. **Mark task complete** in `tasks.md`: change `- [ ]` to `- [x]`. Task checkboxes
   land on the `opsx/<name>` WORKTREE branch (the gate reads tasks.md worktree-side),
   alongside the implementation diff.

8. **Optional: append Execution Notes** to `review.md` if a non-trivial decision was
   made during the task.

**Writeback-owner discipline (keeps sealed verdicts fresh).** Sealed verdicts bind to
the worktree branch HEAD, so split writeback by owner:
- **Worktree branch:** tasks.md checkboxes and the implementation diff.
- **Integration checkout:** `loop_hold`/`loop_hold_reason`, follow-ups.md routing,
  Execution Notes, and every ledger (Round Ledger, `Fidelity Round Ledger`) —
  orchestrator bookkeeping, so it never moves the verdict-bound worktree HEAD.
- **Backstop:** a bookkeeping commit MISPLACED onto the `opsx/<name>` worktree branch
  moves the verdict-bound HEAD and STALES sealed verdicts via range-freshness — a loud
  fail-closed gate red, remedy re-review; never silently green.
- **Judged inputs committed first:** intent.md/design.md/`specs/**` edits land COMMITTED
  on the integration checkout BEFORE any fidelity dispatch (digests bind committed
  integration-checkout content); editing a judged input on the worktree branch is a
  writeback-owner-discipline violation.

## Post-apply: produce verify.md (Verification Mode = retained-required or retained-recommended)

When all tasks are checked, author `openspec/changes/<name>/verify.md` using the template at `~/.local/share/openspec/schemas/opsx-superpowers/templates/verify.md`.

Run all 6 checks:

1. **Structural validation:** `openspec validate <name> --strict --json`. Pass if exit 0 and `valid: true`.

2. **Task completion:** `grep -c "^- \[ \]" tasks.md`. Pass if zero matches.

3. **Delta vs current spec coherence:** for each modified capability, diff:
   ```bash
   diff -u openspec/specs/<cap>/spec.md openspec/changes/<name>/specs/<cap>/spec.md
   ```
   Pass if the delta is parseable as ADDED/MODIFIED/REMOVED/RENAMED.

4. **Commit hygiene:** `git log --format="%H|%s|%b" <base-sha>..HEAD`. For each commit, check subject ≤72 chars; body explains why. Fail with list of offending commits.

5. **AC↔test mapping (canonical IDs):**
   - **Forward:** for each `### Requirement: <name>` in specs/**/spec.md, compute canonical AC ID `<capability>.<slug>`. Run:
     ```bash
     git diff --name-only <base-sha>..HEAD \
       | grep -E '(^|/)tests?/|\.(test|spec)\.[^.]+$' \
       | xargs grep -l "<canonical-id>"
     ```
     Pass if ≥1 match **in a TEST file** (the filter is mandatory — the change's own artifacts like clarify.md/analyze.md/verify.md carry AC IDs by construction and must not self-satisfy this check).
   - **Reverse:** list test files in diff (`/(^|/)tests?/` or `/\.(test|spec)\.[^.]+$/`). For each:
     ```bash
     grep -E '<capability>\.[a-z0-9-]+' <test-file>
     ```
     Pass if ≥1 match OR file contains `# spec-exempt: <reason>` in first 10 lines.

6. **Constitution compliance audit:** sample N changed files (N=all if changed ≤10, all if ≤50 with note, stratified 1-per-top-level-dir+5-random if >50). For each, audit against `openspec/constitution.md` principles. Fail with list of violations.

Compute **Completion Decision**:
- All 6 pass → `green`
- Any fail → `red`

Write `verify.md`. If Completion Decision = red AND Verification Mode = retained-required, BLOCK archive (the archive skill will refuse to proceed).

## Post-apply: produce code-review.md (Code Review Mode != none)

WHEN the pre-review checks are green (tasks complete, structural checks pass, required validation commands pass, and any retained-required verify is green) — NOT keyed to verify specifically, so gating-required + advisory verify cannot deadlock — produce `code-review.md` from `templates/code-review.md`.

- **Findings file is the sole verdict source (opsx-adversarial-review.findings-file-sole-verdict-source)**: derive the verdict, findings, AND attestation EXCLUSIVELY from the subagent's findings OUTPUT FILE; the conversational reply is NEVER a verdict input. An absent findings file, or one lacking the verdict line/attestation fields, consolidates as INVALID (not fail) — excluded from gating, the ledger, and the round budget; record the incident and re-dispatch. Never infer a verdict from a partial file or the reply.
- **Authored by a blind review SUBAGENT** (capability hook `subagent-dispatch` / `adversarial-review-postimpl`), NEVER self-authored by the orchestrator. The subagent reviews the diff `<Diff Base SHA>..<implementation HEAD>` against the baseline: `intent.md` + proposal + specs + design + plan + tasks status.
- **Reviewer models:** WHILE `/opsx-loop` is armed, ONE `opsx_dispatch({ role: "review", task })` — tool auto fan-outs one spawn per configured review model in order (do NOT callerside-loop + soft-honor `subagent` `model:`). WHILE disarmed, dispatch one blind reviewer per configured `review` model (`OPSX_REVIEW_MODELS` / `opsx models review --change <name>`, newline/comma-delimited), each as the subagent `model:`. Adversarial-multimodel requires ≥ 2 distinct models; unset → skill defaults on the disarmed path only (armed unset → `opsx_dispatch` refuse).
- The subagent stamps: `Verdict` (pass|fail), `review_mode` (adversarial-multimodel | disclosure-consensus | degraded-single-model), `reviewer-provenance`, `Diff Base SHA`, and `Reviewed Range`.
- **Tree-identity attestation (opsx-adversarial-review.reviewer-tree-identity-attestation)**: pin every dispatch `cwd` to the reviewed tree; the prompt requires the reviewer's FIRST findings-output lines to be `Attested HEAD: <verbatim git rev-parse HEAD — full 40-hex>` and `Attested Path: <verbatim git rev-parse --show-toplevel>`. Count a verdict only when the attested HEAD literal equals the dispatched range head's full SHA and the attested path realpath-equals the dispatched tree root. Code review and doneness are POST-IMPLEMENTATION dispatches: the dispatched tree is the `opsx/<name>` WORKTREE (worktree execution is the only implementation model, so the path check always discriminates it from the integration checkout) — an integration-checkout attestation is INVALID for them. (Proposal-phase judgments — clarify, analyze, design fidelity — use the purpose-keyed carve-out and attest the integration checkout always; those never dispatch from here.) Missing/non-40-hex/mismatched ⇒ verdict **INVALID, not fail** — excluded from gating, the ledger, and `review_max_rounds`; record + re-dispatch; TWO consecutive all-invalid attempts of a round ⇒ decision-audit landing with a dispatch-integrity error. Seal `**Attested HEAD:**` (gate-read, fail-closed under gating-required) only when every counted reviewer attested the same value; under full_rigor the independent doneness judge attests likewise into doneness.md.
- **Read-only round window — DUAL-TREE (opsx-adversarial-review.read-only-reviewer-dispatch)**: snapshot (`git rev-parse HEAD` + `git status --porcelain=v1`) the REVIEWED WORKTREE AND (worktree-always norm — a different tree) the INTEGRATION CHECKOUT, immediately before the round's first dispatch and after the last return. The ONLY excluded paths are the dispatched change's own bookkeeping files — `openspec/changes/<change>/review.md` and `openspec/changes/<change>/follow-ups.md` (the only permitted in-window writes); the change's judged inputs and other artifacts are NEVER excluded. For the integration checkout, an intervening commit or porcelain delta does NOT void WHEN it exclusively touches OTHER changes' `openspec/changes/<other-change>/` paths (sibling authoring — committed OR uncommitted) OR the dispatched change's own bookkeeping files (committed OR uncommitted); anything else voids. Any voiding delta ⇒ ALL round verdicts INVALID; restore surgically and SYMMETRICALLY (`git restore` only status-changed tracked paths; delete only untracked paths introduced in-window; restore/delete sets EXCLUDE other changes' `openspec/changes/<other-change>/` paths and the dispatched change's excluded paths; never blanket `git clean`, never pre-existing untracked/ignored state); record the incident.
- **Constitution IX**: when the change edits an existing skill, the review MUST be multi-model — `adversarial-multimodel`, or `disclosure-consensus` when the disclosure round consolidated ≥2 distinct reviewer models; a `degraded-single-model` verdict does NOT satisfy the gate.
- Code Review Mode `none` → skip production. `advisory` → produce, non-blocking. `gating-required` → archive blocks unless Verdict = pass.
- **Convergence discipline (opsx-adversarial-review)** — gating rounds converge or land:
  - Every reviewer dispatch prompt embeds the template's **verdict contract + severity rubric** (fail only on frozen-baseline violation or objective correctness/security defect; taste/beyond-scope → advisory). `Verdict: pass ⇔ no open P0/P1`; open P2/P3 recorded as warnings, never another fix round.
  - The ORCHESTRATOR seals the **Round tracker** ledger after every round (round #, mode, consolidated counts = max across reviewers per severity, per-reviewer verdicts, reviewed HEAD) — covering every round including any disclosure round. Never include the ledger or prior findings in a blind prompt. A sealed multi-round Verdict with no ledger row is a provenance defect — repair the ledger before archive.
  - **After each round — land the fixes FIRST, then evaluate IN ORDER (quiet-round default)**: (a) quiet round (P0+P1 = 0 → seal pass, stop) · (b) converging (findings open + change-scoped fixes landed + rounds < `review_max_rounds` → dispatch the next round autonomously, NO human ruling; the disclosure trigger still governs the round's TYPE) · (c) thrash guard (findings open + no fix landed → disclosure/landing) · (d) hard cap (rounds ≥ `review_max_rounds`, default 5 → disclosure/landing regardless of trajectory). The progress signal is change-scoped per round type: post-apply — the reviewed worktree branch HEAD moved (bookkeeping artifacts never commit on the reviewed branch); analyze-type — a commit touching the change's authored fix surfaces (proposal/design/specs/tasks/plan; ledger seals, follow-ups routing, and sibling-change commits never count). WHERE `review_budget_mode: land-on-stop` is set (opt-in; unknown values read as land-on-stop), stop instead on flat-or-rising P0+P1 across the two most recent rounds or on budget exhaustion. Persistent split (2 rounds, or a stop with a split) → ONE `disclosure-consensus` round (max 1/change; satisfies multi-model gating only with ≥2 distinct models). Still-open P0/P1 → decision-audit landing; a user **waive** ruling re-seals `Verdict: pass` with `waived_by_user` (reviewed range unchanged; never self-authored), a **fix** ruling grants a recorded budget extension. Quiet-round automates CONTINUE only — a stop with open P0/P1 never seals pass.
  - **Out-of-scope findings**: required to meet the frozen intent (evidence) → widen scope + log a review.md `Scope Expansions` entry before fixing; otherwise → route to `follow-ups.md` (create from `templates/follow-ups.md` on first routing; advisory, never gates; archive surfaces a non-empty queue as successor-change explore input).

## Completion gate: opsx gate

The change is complete when `opsx gate <name> --worktree <worktree-path>` exits 0. It is the single (primary) source of enforcement truth; archive re-checks the same fields as defense-in-depth. Leave `verify.md` / `code-review.md` UNCOMMITTED until the gate passes, then archive commits/merges (committing a verdict advances HEAD and would self-stale the recorded range).

## Schema-only fallback

If any required capability hook (subagent-driven-implementation, verification-before-completion, etc.) cannot resolve, log `[DEGRADED MODE] no <capability> skill available; running manual fallback` and execute inline. Never silently skip.
