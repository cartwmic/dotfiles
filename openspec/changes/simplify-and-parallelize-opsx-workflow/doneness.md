# Doneness

**Doneness:** satisfied

**Judge:** claude-bridge/claude-opus-4-8 via pi-subagents dispatch
**review_mode:** blind-single-judge
**Frozen-Intent SHA:** 7b6a626d2ff2536753cf7dc06cc768c4a72268c4d35b0b534b4b97ddc88f1d8b
**Diff Base SHA:** 726d18023c96f93378fd10b22f44613af4efec1c
**Reviewed Range:** 726d180..b52aec2
**Date:** 2026-07-03

# Doneness Judgment: simplify-and-parallelize-opsx-workflow

## Verdict

**satisfied** — every in-scope commitment (A1–A5, B1–B4) is delivered with
diff/test evidence; every non-goal is respected; every listed constraint holds.
No gaps.

## Baseline integrity

- Frozen intent.md sha256 recomputed = `7b6a626d2ff2536753cf7dc06cc768c4a72268c4d35b0b534b4b97ddc88f1d8b` — **matches** the required value.
- `intent.md` does **NOT** appear in `git diff 726d180..b52aec2 --name-only` (0 matches) — baseline unaltered.
- Judged strictly against the frozen intent + the 13 delta specs under `specs/`; authoring conversation, code-review.md, review.md Execution Notes, /tmp, and archive/ were not consulted.

## Validator sweep (all green)

| Command | Result |
|---|---|
| `bash -n dot_local/bin/executable_opsx` | rc=0 |
| `bun test dot_pi/agent/extensions/opsx-loop/` | 60 pass / 0 fail (108 expect) |
| `bash tests/opsx-cli/test_opsx_cli.sh` | 47 passed / 0 failed |
| `bash tests/opsx-gate/test_opsx_gate.sh` | 113 passed / 0 failed |
| `bash tests/opsx-gate/test_author_marker.sh` | 4 passed / 0 failed |
| `bash tests/opsx-models/test_opsx_models.sh` | 34 passed / 0 failed |
| `bash tests/opsx-review-convergence/test_review_convergence_surfaces.sh` | 109 passed / 0 failed |
| `openspec validate simplify-and-parallelize-opsx-workflow --strict` | rc=0 (valid) |
| `openspec validate --specs --strict` | rc=0 (14 passed / 0 failed) |

## Decision-by-decision evidence table

### A. Concurrency (audit-lean)

| Commitment | Evidence | Ruling |
|---|---|---|
| **A1 land-base-current** — landing/archive requires `merge-base(opsx/<change>, main) == main HEAD`; rebase-then-fresh-review remedy | `executable_opsx:1313-1326` archive-check (a): computes `merge-base($BRANCH, main)` vs `main HEAD`, fails `ARCHIVE-CHECK-FAIL base-currency` with rebase remedy prose; same-tree exemption when no branch (1329). Deterministic git plumbing, no model. | **met** |
| **A2 path-scoped commits + detector** — `git commit -- <paths>` discipline; deterministic detector flags any main commit touching ≥2 change dirs (detection, not prevention) | Discipline embedded in skills: `openspec-loop/SKILL.md:40-42`, `openspec-apply-change/.../opsx-superpowers-mode.md:45`, and schema-level rule `specs/opsx-workflow-schema/spec.md:119`. Detector: `executable_opsx:1349-1382` advisory multi-dir scan over `DIFF_BASE..main` first-parent (merges included / evil-merge), never affects rc; spec `specs/opsx-cli/spec.md:134`; tests confirm advisory exit-0 behavior. | **met** |
| **A3 duplicate-ADR scan at archive** | `executable_opsx:1332-1348` archive-check (b): derives `ADR-NNNN` from `adr/` filenames, fails `ARCHIVE-CHECK-FAIL adr-dup` on duplicates. | **met** |
| **A4 worktree ensure refuse/reuse** — reuse iff valid on branch `opsx/<change>`; refuse loudly; never auto-delete | `executable_opsx:389 opsx_wt_valid_for_change`; `worktree ensure` 1090-1108 reuse path preserves recorded Diff Base, HALTs for human repair when base missing or non-ancestor (never deletes); creation path guarded. Consumed by status 1247. | **met** |
| **A5 opsx status fleet view** — read-only, model-free; per change: gate summary + last failing check, Scale, worktree path+health, loop_hold+reason, base staleness (commits behind) | `executable_opsx:1178-1285` `opsx_status`: prints Scale (+full_rigor), `gate(cheap)` green/`red [earliest]`, worktree `valid|invalid|none`, `loop_hold` + reason, `base: N behind main`. No side effects. Spec `specs/opsx-cli` status-fleet-view. | **met** |

### B. Simplification

| Commitment | Evidence | Ruling |
|---|---|---|
| **B1 M-tier thinning** — doneness rides code-review dispatch at M (no separate dispatch) but verdict still written to separate doneness.md; clarify folded into proposal open-questions; analyze thinned; full independent stack retained at top tier; doneness.md exists at every tier ≥ M | schema.yaml `doneness.md` block 551-575: at Scale M **without** full_rigor the doneness question RIDES the blind code-review dispatch, verdict STILL sealed to a SEPARATE doneness.md; full_rigor → independently dispatched blind judge. Clarify → proposal Open Questions (`specs/opsx-adversarial-review/spec.md:30`, schema clarify 153-154 XS skip / S ambiguity-only). Analyze thinned to deterministic checks (schema 201-266, `specs/opsx-adversarial-review` M-Tier Review Stack Thinning:23-35). Standing every-Scale≥M-requires-doneness.md unchanged (schema 551, gate binding). | **met** |
| **B2 Scale collapse 5→3 + full_rigor** — XS/S/M gate-real tiers; ADR promotion / adversarial-on-analyze / retrospective become explicit `full_rigor` opt-in flag; former L/XL → "M + flag" | schema.yaml 273 `Scale: XS | S | M`; `full_rigor` capability hooks 253/186, retrospective 543 ("former L/XL"), loop_max 296-297 (`M+full_rigor~80`). `specs/opsx-skill-integration/spec.md:5-8` retires L/XL, maps to "M + full_rigor: true". SKILL/README updated (R4-A lineage). | **met** |
| **B3 spec consolidation 12→~8** — merge kickoff+orchestration → opsx-loop; merge review-convergence+post-impl (+doneness fold) → opsx-adversarial-review; every requirement preserved-verbatim or explicitly retired | New `specs/opsx-loop/spec.md` (608 ln, ADDED reqs) consolidates opsx-loop-kickoff (12 reqs) + opsx-loop-orchestration (9 reqs). New `specs/opsx-adversarial-review/spec.md` (508 ln, ADDED reqs) consolidates opsx-review-convergence (11) + opsx-post-impl-review (4) + opsx-doneness-judge (5). Retired specs each carry `## REMOVED Requirements` listing every prior requirement name, header "consolidated verbatim into the new …". Surviving surface = goal-loop, opsx-adversarial-review, opsx-cli, opsx-gate-enforcement, opsx-loop, opsx-model-config, opsx-skill-integration, opsx-workflow-schema = **8**. Documentation topology only; `openspec validate --strict` rc=0. | **met** |
| **B4a XS/S same-tree downgrade** (worktree-required stays default at M+) | schema.yaml 289-291: worktree_mode DERIVED when absent — `XS/S ⇒ same-tree, M ⇒ worktree-required`. review.md template worktree_mode commented so derivation applies (R4-B lineage). | **met** |
| **B4b drop project-layer models yaml** — resolution env > front-matter > user > default | `templates/opsx-models.yaml:10-19` RETIRED project layer, ignored + one-time warning. `executable_opsx:88` rejects `--layer project` (exit 2); 109-114 lingering project yaml ignored with stderr warning. `specs/opsx-model-config` retired `project` source; test "models template drops the project-scope location" green. | **met** |
| **B4c goal-loop deprecation note** (no removal) | `specs/goal-loop/spec.md:8-25` ADDED "Deprecation and Fallback Status": goal-loop = generic fallback, opsx-loop = primary host; behavior unchanged; removal explicitly out of scope. | **met** |

### Non-goals (respected)

| Non-goal | Evidence | Ruling |
|---|---|---|
| Per-change flock / lock files / PID stale-heal | grep for `flock`/`.opsx-control`/`PID stale`/`stale-lock` in gate + extension = **none**. | respected |
| Distill session nonce | grep `nonce` in gate + extension = **none**. | respected |
| Branch-first authoring + `.opsx-control` | absent (deferred per intent audit record); no control file introduced. | respected |
| In-session multi-loop | extension keeps one active loop per session (opsx-loop ADDED reqs: new change replaces active loop). | respected |
| Weakening adversarial code review | `specs/opsx-adversarial-review/spec.md:39` — 2-model blind review SHALL remain gating-required with verdict contract, rubric, ledger, trajectory/budget stop, disclosure round, freshness/provenance all unchanged; `degraded-single-model` still does NOT satisfy gating. | respected |
| Auto-archive / merge / push / deploy | grep `auto-archive`/`auto.deploy`/`git push` in gate = **none**; loop never archives/deploys. | respected |

### Constraints (held)

| Constraint | Evidence | Ruling |
|---|---|---|
| Extension + gate deterministic & model-free (ADR-0007) | gate is pure bash (`bash -n` clean); all A1–A5 checks are git plumbing / filename greps; extension is a model consumer (loop tests 60/0). No LLM calls in gate/extension paths. | held |
| ADR-scarred guards preserved untouched (loop_hold ADR-0022, resume latch ADR-0021, distill confirm ADR-0014, trajectory stop/review_max ADR-0017, disclosure round ADR-0018, locator single-source ADR-0023, verdict freshness/provenance, fail-closed modes, budget/stall, AC↔test gate) | Preserved verbatim in consolidated specs (opsx-loop + opsx-adversarial-review ADDED reqs enumerate loop_hold, latch, distill confirm, trajectory/budget stop, disclosure round, worktree locator fallback, freshness/provenance); regression-covered green: author-marker 4/0, gate 113/0, review-convergence 109/0, loop 60/0. | held |
| Keyword grammar unchanged | opsx-loop status/clear/models subcommand reqs retained (spec `Status and clear`, `Model config subcommand`). | held |
| Loop never archives/deploys; human retains | no archive/deploy path in loop; archive is a separate human-invoked skill/CLI. | held |
| Constitution VIII / IX / II | VIII: `openspec/` schema changes are delta specs, not chezmoi-deployed runtime; IX: this Scale-≥M skill change is itself under 2-model adversarial review (blind judge dispatched); II: skills at canonical `dot_local/share/agent-harness/canonical/skills/`. | held |
| Backward compat at cutover | migration applies to changes created after land; no archive rewriting introduced. | held |

## Advisory (non-blocking, not an intent gap)

- A 0-byte tracked stray file `tests/opsx-review-convergence/test_review_convergence_surfaces.sh.tmp` is present in the range (`git ls-files` confirms tracked, `wc -c` = 0). It violates no intent commitment, non-goal, or constraint and does not affect any test or gate. Recommend deleting before land for tree cleanliness; does **not** change the `satisfied` verdict.

## Gap list

None — verdict is `satisfied`.
