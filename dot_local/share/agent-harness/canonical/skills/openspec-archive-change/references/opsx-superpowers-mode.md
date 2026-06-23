# openspec-archive-change under schema: opsx-superpowers

Loaded when step 2.5 detects `schemaName == "opsx-superpowers"`. Adds verify HARD-GATE, code-review HARD-GATE, opsx-gate confirmation, worktree merge/cleanup, AC↔test mapping check, ADR promotion, retrospective-driven mcp-memory ingestion.

## HARD-GATE 0: opsx-gate green (primary)

Run `opsx-gate <name> --worktree <Worktree Path>` (read Worktree Path from review.md). If it exits non-zero, REFUSE archive and print the `GATE-FAIL` lines — this is the primary, deterministic check. The HARD-GATEs below re-assert specific fields as defense-in-depth (a human may archive without the gate).

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

## HARD-GATE 3: ADR promotion candidates

Parse `openspec/changes/<name>/design.md` for `### D<n>:` Decision blocks. For each, apply the 4-point test using the schema's `templates/adr.md` rubric:

1. Multiple viable approaches mentioned?
2. Lasting consequences described?
3. Disagreement potential noted in rationale?
4. Future constraints discussed?

If a decision passes ≥3 of 4, surface to user:
```
Decision D<n>: <title>
4-point score: <score>/4

Promote to docs/adr/ADR-NNNN-<slug>.md before archive? (Y/n)
```

For each `Y`, find the next available `<repo>/adr/ADR-NNNN-` number (scan existing files), generate the file from `templates/adr.md` populated with:
- Title from D<n>
- Status: Accepted
- Date: today
- Source change: `openspec/changes/<name>/`
- Decision Drivers + Considered Options + Decision Outcome + Consequences: extracted from D<n>'s text

Commit each ADR with subject `docs(adr): ADR-NNNN <title>`.

## HARD-GATE 4: retrospective Promote-candidates

Check for `openspec/changes/<name>/retrospective.md`.

If present, parse the `## Promote candidates` section. For each candidate row:

```
Candidate <n>:
  type:    <decision | bug | error | convention | learning | implementation | context | important | code>
  tags:    <comma-separated>
  content: <quoted block>

Promote to mcp-memory? (Y/n/skip-all)
```

Validate per type:
- `code`: content ≥600 chars; reject otherwise.
- All other types: content ≥300 chars; reject otherwise.

For each `Y`, call `mcp_memory_store_memory` with:
- `content`: as written
- `tags`: parsed list (ensure type-name is included as a tag)
- `memory_type`: the canonical type
- `metadata`: { source_change: <name>, source_artifact: retrospective.md }

Per the mcp-memory contract, NEVER auto-store; ALWAYS prompt per candidate.

If `retrospective.md` is missing:
- Scale = XL → REFUSE archive (retrospective is required at XL):
  ```
  ⛔ Archive refused.
  Scale = XL requires retrospective.md before archive.
  Run the schema's retrospective template to capture wins, misses,
  and Promote-candidates. Template:
    ~/.local/share/openspec/schemas/opsx-superpowers/templates/retrospective.md
  ```
- Scale = L → warn, allow:
  ```
  ⚠ Scale = L; retrospective.md missing. Recommended but not required.
  Skipping mcp-memory promotion.
  ```
- Scale = M / S / XS → silent skip.

## HARD-GATE 2: code-review.md pass (Code Review Mode = gating-required)

Read `Code Review Mode` from review.md front-matter. If `gating-required`:
1. `code-review.md` must exist with `Verdict: pass`. If absent or not pass, REFUSE archive.
2. If `review_mode: degraded-single-model` AND the change edits an existing skill (Constitution IX), REFUSE archive — a degraded review does not satisfy the multi-model adversarial requirement.

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
