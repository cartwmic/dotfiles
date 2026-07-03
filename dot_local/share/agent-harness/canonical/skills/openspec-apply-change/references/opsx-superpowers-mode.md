# openspec-apply-change under schema: opsx-superpowers

Loaded when step 2.5 detects `schemaName == "opsx-superpowers"`. Adds mode dispatch, file contracts, intent-aware repair, and post-apply skill artifacts.

## Pre-apply: read modes from review.md

Parse `openspec/changes/<name>/review.md` to extract:

```
Scale                  = <XS | S | M | L | XL>
Execution Mode         = <standard | tdd-preferred | tdd-required>
Verification Mode      = <inline-only | retained-recommended | retained-required>
Debug Mode             = <standard | systematic-debugging>
Review Status          = <not-requested | requested | findings-received | resolved>
Delegation Mode        = <single-agent | subagent-eligible | subagent-required>
Worktree Mode          = <same-tree | worktree-eligible | worktree-required>
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

## Pre-flight commit (when Worktree Mode != same-tree)

```bash
cd <project root>
git status --porcelain openspec/changes/<name>/
```

If any unstaged or uncommitted files under that subtree, stage + commit ONLY that subtree on the integration branch:

```bash
git add openspec/changes/<name>/
git commit -m "chore(opsx): pre-flight commit for apply of <name>"
```

Then create the worktree on branch `opsx/<name>` per the pi-subagents convention.

## Worktree lifecycle + immutable Diff Base SHA

Worktree Mode defaults to `worktree-required` for ALL Scales (the loop's blast-radius sandbox); `same-tree` is an explicit override.

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

**Same-tree override**: record `Diff Base SHA` = pre-apply HEAD before the first task; leave `Worktree Path` empty.

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
     - **Model:** dispatch the impl subagent with the configured `impl` model
       (`OPSX_IMPL_MODEL` / `opsx models impl --change <name>`), passed verbatim
       as the subagent `model:` (already provider-qualified). Unset → skill default.
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

7. **Mark task complete** in `tasks.md`: change `- [ ]` to `- [x]`.

8. **Optional: append Execution Notes** to `review.md` if a non-trivial decision was made during the task.

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

- **Authored by a blind review SUBAGENT** (capability hook `subagent-dispatch` / `adversarial-review-postimpl`), NEVER self-authored by the orchestrator. The subagent reviews the diff `<Diff Base SHA>..<implementation HEAD>` against the baseline: `intent.md` + proposal + specs + design + plan + tasks status.
- **Reviewer models:** dispatch one blind reviewer per configured `review` model (`OPSX_REVIEW_MODELS` / `opsx models review --change <name>`, newline/comma-delimited), each passed verbatim as the subagent `model:`. Adversarial-multimodel requires ≥ 2 distinct models; unset → the skill's default review set.
- The subagent stamps: `Verdict` (pass|fail), `review_mode` (adversarial-multimodel | disclosure-consensus | degraded-single-model), `reviewer-provenance`, `Diff Base SHA`, and `Reviewed Range`.
- **Constitution IX**: when the change edits an existing skill, the review MUST be multi-model — `adversarial-multimodel`, or `disclosure-consensus` when the disclosure round consolidated ≥2 distinct reviewer models; a `degraded-single-model` verdict does NOT satisfy the gate.
- Code Review Mode `none` → skip production. `advisory` → produce, non-blocking. `gating-required` → archive blocks unless Verdict = pass.
- **Convergence discipline (opsx-review-convergence)** — gating rounds converge or land:
  - Every reviewer dispatch prompt embeds the template's **verdict contract + severity rubric** (fail only on frozen-baseline violation or objective correctness/security defect; taste/beyond-scope → advisory). `Verdict: pass ⇔ no open P0/P1`; open P2/P3 recorded as warnings, never another fix round.
  - The ORCHESTRATOR seals the **Round tracker** ledger after every round (round #, mode, consolidated counts = max across reviewers per severity, per-reviewer verdicts, reviewed HEAD) — covering every round including any disclosure round. Never include the ledger or prior findings in a blind prompt. A sealed multi-round Verdict with no ledger row is a provenance defect — repair the ledger before archive.
  - **Stop before re-dispatching**: converged (P0+P1 = 0 → seal pass) · treadmill (P0+P1 flat/rising across the two most recent rounds) · budget (rounds ≥ `review_max_rounds`, default 5). Persistent split (2 rounds, or a stop with a split) → ONE `disclosure-consensus` round (max 1/change; satisfies multi-model gating only with ≥2 distinct models). Still-open P0/P1 → decision-audit landing; a user **waive** ruling re-seals `Verdict: pass` with `waived_by_user` (reviewed range unchanged; never self-authored), a **fix** ruling grants a recorded budget extension.
  - **Out-of-scope findings**: required to meet the frozen intent (evidence) → widen scope + log a review.md `Scope Expansions` entry before fixing; otherwise → route to `follow-ups.md` (create from `templates/follow-ups.md` on first routing; advisory, never gates; archive surfaces a non-empty queue as successor-change explore input).

## Completion gate: opsx gate

The change is complete when `opsx gate <name> --worktree <worktree-path>` exits 0. It is the single (primary) source of enforcement truth; archive re-checks the same fields as defense-in-depth. Leave `verify.md` / `code-review.md` UNCOMMITTED until the gate passes, then archive commits/merges (committing a verdict advances HEAD and would self-stale the recorded range).

## Schema-only fallback

If any required capability hook (subagent-driven-implementation, verification-before-completion, etc.) cannot resolve, log `[DEGRADED MODE] no <capability> skill available; running manual fallback` and execute inline. Never silently skip.
