# openspec-archive-change under schema: opsx-superpowers

Loaded when step 2.5 detects `schemaName == "opsx-superpowers"`. Adds: HARD-GATE A (opsx archive-check), HARD-GATE 0 (opsx gate green), HARD-GATE 1 (verify.md), HARD-GATE 2 (AC↔test mapping re-run), HARD-GATE 3 (code-review.md), HARD-GATE 4 (doneness re-check), worktree merge/cleanup, ADR promotion, retrospective-driven hindsight memory promotion, post-archive consolidation cleanup.

## HARD-GATE A: opsx archive-check (land-path currency)

Before ANY archive action — immediately before `openspec archive` — run the
deterministic land-path verb and QUOTE its output back to the user verbatim:

```bash
opsx archive-check <name>
```

It asserts land-base currency (`git merge-base opsx/<name> main` == `git rev-parse
main`; branch-absent ⇒ satisfied same-tree exemption), an ADR duplicate-number scan,
and an advisory multi-dir-commit detector (advisory only — it never affects the exit
code). If `opsx archive-check` exits NON-ZERO, REFUSE archive and print the quoted
output plus the remedy it names (typically rebase `opsx/<name>` onto `main`):

```
⛔ Archive refused.
opsx archive-check <name> exited non-zero:
  <quoted archive-check output>
Resolve (e.g. rebase the change branch onto main) and re-run before archiving.
```

Do NOT proceed to HARD-GATE 0 until archive-check exits 0 (or a human records an
explicit override via the Override path below).

## HARD-GATE 0: opsx gate green (primary)

Run `opsx gate <name> --worktree <Worktree Path>` (read Worktree Path from review.md). If it exits non-zero, REFUSE archive and print the `GATE-FAIL` lines — this is the primary, deterministic check. The HARD-GATEs below re-assert specific fields as defense-in-depth (a human may archive without the gate).

## HARD-GATE 1: verify.md green

Read `openspec/changes/<name>/review.md` `Verification Mode`. If `retained-required`:

1. Check `openspec/changes/<name>/verify.md` exists. If missing, REFUSE archive:
   ```
   ⛔ Archive refused.
   Verification Mode = retained-required but verify.md is missing.
   Run /opsx-apply <name> to completion first; the apply skill produces
   verify.md when Verification Mode is retained-*.
   ```

2. Parse `Completion Decision` line. If not `green`, REFUSE:
   ```
   ⛔ Archive refused.
   verify.md Completion Decision = <red | pending>.
   Failing checks:
     <list from verify.md table>
   Resolve and re-run /opsx-apply <name>, OR explicitly override with
   /opsx-archive <name> --override (you'll be asked to record the
   reason in the change's history).
   ```

If `Verification Mode = retained-recommended`, warn but allow:
```
⚠ verify.md is missing or red. Proceeding anyway because
Verification Mode = retained-recommended. (Use retained-required
to block on this in future.)
```

If `Verification Mode = inline-only`, skip verify check entirely.

## HARD-GATE 2: AC↔test mapping (re-run as defense-in-depth)

Even when verify.md says green, re-run the AC↔test grep one more time as the final check before archive (catches drift between apply and archive):

```bash
# Forward: each AC has ≥1 test reference
for capability in openspec/changes/<name>/specs/*/; do
  for req in $(grep -E "^### Requirement:" "$capability/spec.md"); do
    slug=<compute slug from req>
    id="<basename($capability)>.${slug}"
    if ! git diff --name-only <base-sha>..HEAD | xargs grep -l "$id" >/dev/null; then
      echo "MISSING: $id has no test reference"
    fi
  done
done
```

If any AC has no test reference, list them and prompt:
```
N acceptance criteria have no test references:
  <list>
Options:
  A) Block archive — add tests first
  B) Allow archive — these ACs are documentation-only (you'll record
     the rationale in retrospective.md)
```

## HARD-GATE 3: ADR promotion candidates (full_rigor only)

Read `full_rigor` from review.md front-matter. This gate runs ONLY when
`full_rigor: true` (the former L/XL). At plain M, S, or XS, ADR promotion is
optional — SKIP this gate (the user may still promote a decision by hand); it
is never keyed on a Scale label. When `full_rigor: true`:

Parse `openspec/changes/<name>/design.md` for `### D<n>:` Decision blocks. For each, apply the 4-point test using the schema's `templates/adr.md` rubric:

1. Multiple viable approaches mentioned?
2. Lasting consequences described?
3. Disagreement potential noted in rationale?
4. Future constraints discussed?

If a decision passes ≥3 of 4, surface to user:
```
Decision D<n>: <title>
4-point score: <score>/4

Promote to <repo>/adr/ADR-NNNN-<slug>.md before archive? (Y/n)
```

For each `Y`, find the next available `<repo>/adr/ADR-NNNN-` number (scan existing files), generate the file from `templates/adr.md` populated with:
- Title from D<n>
- Status: Accepted
- Date: today
- Source change: `openspec/changes/<name>/`
- Decision Drivers + Considered Options + Decision Outcome + Consequences: extracted from D<n>'s text

Commit each ADR path-scoped to the ADR file(s) on the integration checkout —
never a bare `git commit`/`git add -A`, so an unrelated dirty file cannot ride
along into the archive history:
```bash
git add <repo>/adr/ADR-NNNN-<slug>.md
git commit -- <repo>/adr/ADR-NNNN-<slug>.md -m "docs(adr): ADR-NNNN <title>"
```

## HARD-GATE 4: retrospective Promote-candidates

Check for `openspec/changes/<name>/retrospective.md`.

If present, parse the `## Promote candidates` section. For each candidate row:

```
Candidate <n>:
  tags:    <comma-separated>
  content: <quoted block>

Promote to memory? (Y/n/skip-all)
```

Validate: content is self-contained prose (no conversation-context
dependence); exact identifiers (SHAs, versions, paths, ADR/AC IDs)
verbatim; no secrets/credential values. There is NO type taxonomy and
NO minimum length — hindsight does its own extraction/consolidation.

For each `Y`, call the hindsight `retain` tool with:
- `content`: as written
- `tags`: parsed list — `project:<name>` always; optional `topic:<x>`
  facets (short, lowercase; no memory_type tag, no harness tag)

Per the memory contract (CLAUDE.md "Memory: hindsight MCP server"),
NEVER auto-store; ALWAYS prompt per candidate. `retain` is async: do
not expect the fact to be recallable in the same turn.

If `retrospective.md` is missing, key the decision on `full_rigor` (read from
review.md front-matter), NOT on a Scale label:
- `full_rigor: true` → REFUSE archive (retrospective is required at full_rigor,
  the former L/XL):
  ```
  ⛔ Archive refused.
  full_rigor: true requires retrospective.md before archive.
  Run the schema's retrospective template to capture wins, misses,
  and Promote-candidates. Template:
    ~/.local/share/openspec/schemas/opsx-superpowers/templates/retrospective.md
  ```
- full_rigor absent/false (plain M / S / XS) → silent skip (retrospective is
  optional without full_rigor).

## HARD-GATE 3: code-review.md pass (Code Review Mode = gating-required)

Read `Code Review Mode` from review.md front-matter. If `gating-required`:
1. `code-review.md` must exist with `Verdict: pass`. If absent or not pass, REFUSE archive.
2. If `review_mode: degraded-single-model` AND the change edits an existing skill (Constitution IX), REFUSE archive — a degraded review does not satisfy the multi-model adversarial requirement.

## HARD-GATE 4: doneness verdict (Scale ≥ M, doneness_mode != waived)

Defense-in-depth mirror of the gate's doneness check (the newest enforcement
axis must not be the only one without an archive-side backstop when a human
archives without the gate). Read `Scale` and `doneness_mode` from review.md
front-matter. If Scale is M and `doneness_mode` is not `waived`:
1. `doneness.md` must exist with `Doneness: satisfied`. If absent or not
   satisfied, REFUSE archive.
2. It must carry a `Judge` provenance field and a non-degraded `review_mode`.
If `doneness_mode: waived`, require a non-empty `doneness_waiver_rationale`
in review.md front-matter (a bare waiver does not pass the gate either).

## Worktree merge + cleanup (Worktree Mode != same-tree)

After all HARD-GATEs pass and ONLY then:
1. Land `opsx/<name>` onto the Integration Branch (read from review.md) using the configured strategy.
2. **If the merge conflicts** (integration branch advanced): ABORT archive with an actionable error; PRESERVE the worktree + `opsx/<name>` branch; do NOT move the change to archive.
3. On clean merge: `git worktree remove <Worktree Path>` and delete the branch.
4. Same-tree override: skip merge/remove.

**chezmoi guard:** never run `chezmoi apply` against real `$HOME` from the loop worktree; deploy-affecting verification runs post-merge or with `CHEZMOI_SOURCE_DIR`/`--source`.

## Then: proceed with existing archive steps

After all HARD-GATEs pass (or are overridden) and the worktree is merged+removed, continue with the existing skill's steps 3-6:
- Check task completion
- Assess delta spec sync
- Perform the archive (`mv openspec/changes/<name> openspec/changes/archive/YYYY-MM-DD-<name>`)
- Display summary

## Post-archive: consolidation cleanup (D8)

`openspec archive` applies this change's ADDED/REMOVED deltas into the spec-of-record;
no spec content is hand-migrated (the deltas carry everything). A REMOVED delta can
leave an empty `openspec/specs/<cap>/` directory behind. AFTER the archive move and
BEFORE the archive commit:

1. Delete any now-empty `openspec/specs/<cap>/` directories the archive left behind
   (a capability whose spec was fully removed):
   ```bash
   find openspec/specs -type d -empty -delete
   ```
2. Re-run the spec validator and require it GREEN before committing:
   ```bash
   openspec validate --specs --strict
   ```
   If it is not green, do NOT commit the archive — investigate the dangling/removed
   spec first. Only commit the archive (path-scoped to the moved change dir + the
   touched `openspec/specs/**`) once `openspec validate --specs --strict` is green.

Summary should additionally show:
```
ADRs promoted: N (paths)
Memory entries created: M (hashes)
```

## Override path

If the user wants to archive despite a red verify or other gate failure, they must invoke:
```
/opsx-archive <name> --override
```

The skill then prompts:
```
Recording override:
  - Which gate failed: <…>
  - Why is archive acceptable now: <user-supplied rationale>
  - Follow-up action: <e.g., "addressed in change Y">

The override + rationale will be written into the archived change's
verify.md (in the `## Override (if archiving despite red)` section).
```

After recording, archive proceeds. No silent overrides.
