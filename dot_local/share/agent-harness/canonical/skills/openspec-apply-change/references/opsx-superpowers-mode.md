# openspec-apply-change under schema: opsx-superpowers

Loaded when step 2.5 detects `schemaName == "opsx-superpowers"`. Adds mode dispatch, file contracts, intent-aware repair, and post-apply skill artifacts.

## Pre-apply: read modes from review.md

Parse `openspec/changes/<name>/review.md` to extract:

```
Scale              = <XS | S | M | L | XL>
Execution Mode     = <standard | tdd-preferred | tdd-required>
Verification Mode  = <inline-only | retained-recommended | retained-required>
Debug Mode         = <standard | systematic-debugging>
Review Status      = <not-requested | requested | findings-received | resolved>
Delegation Mode    = <single-agent | subagent-eligible | subagent-required>
Worktree Mode      = <same-tree | worktree-eligible | worktree-required>
Spec Level         = <spec-anchored | spec-first | spec-as-source>
```

If `review.md` is missing OR all defaults (Scale=XS likely), use the defaults from the schema README.

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

**On first worktree creation** record the IMMUTABLE diff base = integration-branch merge-base (NOT apply-start HEAD), plus the locator fields, into `review.md`:

```bash
git worktree add -B opsx/<name> <worktree-path>            # create
base=$(git merge-base <integration-branch> opsx/<name>)    # immutable base
# write to review.md body:  **Diff Base SHA:** $base
#                           **Worktree Path:** <worktree-path>
#                           **Integration Branch:** <integration-branch>
```

**On reuse** (branch `opsx/<name>` already exists from a prior aborted apply): PRESERVE the recorded `Diff Base SHA`. If it is absent or not an ancestor of `opsx/<name>`, HALT for human repair rather than re-recording a base that would exclude unverified commits.

**On creation failure** (path conflict / detached HEAD / no space / permission): ABORT with an actionable error; do NOT proceed to any implementation task.

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
   git -C <worktree-path> diff --name-only <worktree-base-sha>..HEAD
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
- The subagent stamps: `Verdict` (pass|fail), `review_mode` (adversarial-multimodel | degraded-single-model), `reviewer-provenance`, `Diff Base SHA`, and `Reviewed Range`.
- **Constitution IX**: when the change edits an existing skill, the review MUST be adversarial-multimodel; a `degraded-single-model` verdict does NOT satisfy the gate.
- Code Review Mode `none` → skip production. `advisory` → produce, non-blocking. `gating-required` → archive blocks unless Verdict = pass.

## Completion gate: opsx gate

The change is complete when `opsx gate <name> --worktree <worktree-path>` exits 0. It is the single (primary) source of enforcement truth; archive re-checks the same fields as defense-in-depth. Leave `verify.md` / `code-review.md` UNCOMMITTED until the gate passes, then archive commits/merges (committing a verdict advances HEAD and would self-stale the recorded range).

## Schema-only fallback

If any required capability hook (subagent-driven-implementation, verification-before-completion, etc.) cannot resolve, log `[DEGRADED MODE] no <capability> skill available; running manual fallback` and execute inline. Never silently skip.
