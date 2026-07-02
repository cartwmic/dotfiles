# opsx Workflow Audit — 2026-07-02

**Scope:** the full opsx spec-driven autonomous-loop stack in this repo — `opsx` CLI (gate/models/loop), the `opsx-loop` pi extension, the `opsx-superpowers` schema + templates, the 7 canonical skills + mode references, `.pi/prompts/opsx-*`, all 11 permanent opsx specs, ADR-0001–0012, and live gate config — cross-referenced against mid-2026 best practices for spec-driven development (Spec Kit, Kiro, OpenSpec, Tessl/Fowler) and autonomous looping (Ralph loop, Anthropic harness guidance, LLM-as-judge practice).

**Method:** three independent audits (implementation review with tests executed; design-coherence cross-reference; web best-practices research), synthesized here. Full appendices in `docs/audits/2026-07-02-opsx-appendices/` — `code-audit.md`, `design-audit.md`, `best-practices.md` (with source URLs).

**Baseline health:** all existing tests pass (17 CLI + 25 models + 52 gate + 45 helper). The enforcement spine — gate exit-code contract, cheap-before-expensive ordering, green-state kickoff exit, re-entrancy guard, budget semantics, stall detection + doneness gap-set ratchet, intent sha256 immutability, human-owned archive — is implemented correctly and matches its specs on every point spot-checked.

---

## 1. Verdict in three sentences

The **architecture is ahead of the curve**: your gate-layer design (deterministic gate as sole judge, LLM doneness as sealed backstop, blind multi-model review, worktree isolation, bounded loop with stall ratchet, human-owned archive) matches or exceeds the 2026 consensus pattern almost item-for-item. The **implementation has one real correctness cluster** (worktree artifact-source split-brain, env leakage, no subprocess timeouts, parser hangs) that can silently defeat the loop on exactly the worktree-required changes the system exists for. The **documentation layer has drifted three generations behind** the spec-of-record (stale schema.yaml instructions, forked `.pi/prompts`, retired mcp-memory pipeline), and since the schema instructions are what OpenSpec actually feeds the model, doc rot here is a live behavioral bug, not cosmetics.

---

## 2. Scorecard vs 2026 best practices

| Best-practice axis (see appendix for sources) | opsx status | Grade |
|---|---|---|
| Spec before code, right-sized per change (XS→XL tiers) | Scale tiers, per-tier artifact reduction | ✅ strong |
| EARS ACs, 5 quality properties, error-path IF…THEN | Schema mandates it; **own permanent specs violate it** (TBD Purposes, WHEN-on-error, no checklists) | ⚠️ partial |
| Constitution / steering files | constitution.md + domain.md wired into proposal | ✅ strong |
| Deterministic gates beat self-assessment | Gate is sole loop judge (ADR-0005); doneness LLM is backstop-only, sealed gate-read (ADR-0012) | ✅ exemplary |
| Agent cannot modify gates without approval | Gate manifest read path pinned to integration checkout (`MANIFEST="$ROOT/..."`, verified) — but in-session agent still has write access to ROOT; only diff review catches tampering | ⚠️ partial |
| AC↔test linkage enforced | verify.md Check 5 exists but **self-satisfying as written** (H4) | ❌ broken |
| Blind multi-model adversarial review, GO/NO-GO | code-review adversarial-multimodel ≥2 models, blind | ✅ strong |
| Judge sees spec/diff/evidence, not builder narrative; verdict logged | Doneness judge sealed; review_mode vocabulary gap for single judge (M1) | ⚠️ partial |
| Worktree/branch isolation, never main | worktree-required default (ADR-0008) | ✅ strong |
| Worktree lifecycle owned by runtime | **Prose-owned, not runtime-owned**; no creation/reuse/cleanup enforcement or tests (P2) | ⚠️ partial |
| Hard max iterations | loop_max_iterations budget, correct off-by-one | ✅ |
| Per-command timeout / wall-clock timeout | **None** — hung gate or validator wedges loop forever (P1) | ❌ missing |
| Token/cost caps, cost reporting, spend alerts | **None anywhere in the stack** | ❌ missing |
| Stall / no-progress / repeated-error detection | lastDirs guard + failure-key + gap-set ratchet | ✅ strong |
| Fresh context per iteration (Ralph/Anthropic) | **Same-session loop** via sendUserMessage — context accumulates across turns | ⚠️ deliberate trade-off, undocumented |
| State in files/git, not chat | review.md front-matter, tasks.md, verdict files, git SHAs | ✅ strong |
| Human owns spec approval, merge, release | intent frozen by human; loop never archives; archive prompt-guarded | ✅ (two leaks: M5, H2) |
| Emit "needs human" report on stop | ntfy notify on stop/green | ✅ |
| Drift control: specs updated with behavior | **This audit is the counter-evidence** — 3 generations of doc drift | ❌ failing |

**Net:** control-plane design A; implementation robustness B−; documentation freshness D.

---

## 3. Top findings (merged, deduplicated, ranked)

Severity: P0 none found. P1 = can silently break the loop's core promise. P2 = wrong under realistic conditions / policy gap. P3 = rot, ceremony, hygiene.

### P1 — correctness cluster (fix as one change)

| # | Finding | Anchor |
|---|---|---|
| 1 | **Gate `--worktree` split-brain:** validation cwd + HEAD come from the worktree, but `tasks.md`, `verify.md`, `code-review.md`, `doneness.md` are read from the integration checkout — worktree-required changes can red-loop forever despite a correct worktree. `OPSX_CHANGE_DIR` exported to validators also points at root. Zero tests cover a real worktree with divergent artifacts. | `executable_opsx:381-384, 436-463, 597, 607, 673` |
| 2 | **CLI hangs on missing option values:** `opsx gate foo --worktree`, `opsx models author --change` spin forever (reproduced, `timeout` exit 124) — a malformed generated command wedges the judge subprocess and the loop. | `executable_opsx:371-374, 52-68` |
| 3 | **Model-env leaks across loops:** `exportModelEnv()` never clears stale `OPSX_*` keys from `process.env`; loop B inherits loop A's author/review models, and gate author-marker enforcement sees source `env`. | `opsx-loop/index.ts:117-125` |
| 4 | **No timeouts anywhere:** extension `runGate()`, gate validator execution, and the bash fallback loop all lack timeouts; budget/stall guards only run *after* gate returns, so they can't rescue a hang. | `index.ts:146-160`; `executable_opsx:533-540, 792-810` |
| 5 | **verify.md Check 5 is self-satisfying (design H4):** forward AC↔test grep has no test-file filter, so clarify.md/analyze.md/verify.md in the diff satisfy it by construction — the one deterministic AC-coverage check proves nothing. Spec has the filter; template + apply ref dropped it. | `templates/verify.md`; apply mode-ref; `opsx-spec-quality/spec.md` |

### P1 — documentation-as-behavior cluster (the model reads these)

| # | Finding | Anchor |
|---|---|---|
| 6 | **schema.yaml teaches a dead diff-base contract:** apply/tasks instructions (served verbatim by `openspec instructions --json`) say capture "Worktree Base SHA" via `rev-parse HEAD`; spec/template/gate use immutable merge-base `Diff Base SHA` and explicitly prohibit the former. Agent following schema text reintroduces the vanishing-commits bug the spec was amended to kill. | `schema.yaml` apply+tasks; `opsx-workflow-schema/spec.md` |
| 7 | **`.pi/prompts/opsx-*.md` are stale forks:** zero references to opsx-superpowers; no Scale, no worktree, no intent freeze, no verify/code-review/gate hard-gates. `/opsx-archive` run directly performs plain mv-archive — **bypasses every opsx control including gate-green**. Highest-leverage human-control defect found. | `.pi/prompts/opsx-{explore,propose,apply,archive}.md` |
| 8 | **Memory-promotion pipeline targets retired mcp-memory backend** (9-type taxonomy, `mcp_memory_store_memory`, dead hostname) vs live hindsight contract (no taxonomy, retain/recall/reflect). XL archive path degrades to a permanent `retrospective-promote-pending.md` loop. Spec-of-record itself inconsistent (says 6 types vs 9). | `templates/retrospective.md`; archive mode-ref; `capability-hooks.md`; constitution X |

### P2 — policy decisions needed (yours to make, not bugs)

| # | Finding | Decision to make |
|---|---|---|
| 9 | **Goal-mode self-freezes intent.md** with no human confirm — for bare `/opsx-loop goal` the immutable baseline every reviewer and the doneness judge score against is fully agent-inferred. Dilutes your stated explore→intent(human)→loop model. | Accept + document as an ADR trade-off, or require one-shot intent confirmation before adoption. |
| 10 | **Same-session looping vs fresh-context consensus.** Ralph/Anthropic harness practice: fresh context per iteration, state in files. Your loop re-injects into one growing session — context rot and review-contamination risk on long red streaks. Your file/git state discipline already makes fresh-per-iteration feasible. | Keep (simpler, pi-native) and document; or move worker turns to fresh subagent sessions with the gate as re-entry point. |
| 11 | **No cost layer at all:** no token/cost cap, no per-run cost estimate/report, no spend alert. Iteration budget is the only economic bound; an ∞-budget loop with expensive models has no backstop but stall detection. | Add per-run cost ceiling + end-of-run cost report to the extension, or explicitly accept iteration-budget-only. |
| 12 | **Worktree lifecycle is prose-owned:** no runtime component performs creation/reuse-base-check/cleanup; the loop proceeds only insofar as the agent obeys skill text. Also: no cleanup path for *abandoned* changes ever (orphaned worktrees/branches with uncommitted verdict files). | Add `opsx worktree ensure` / `opsx clean <change>` runtime commands, or document skill-ownership + add gate ancestry check on `Diff Base SHA`. |
| 13 | **Mode values fail open:** typo `worktree_requred` silently disables worktree validation; same for verify/code-review modes. Gate should fail closed on unknown enum values. | One-line enum validation + `GATE-FAIL mode`. |
| 14 | **doneness `review_mode` vocabulary gap:** single blind judge is neither `adversarial-multimodel` (≥2 models) nor `degraded-single-model`; template pre-fills the wrong value and the gate passes any non-degraded string. | Define `blind-single-judge` (or scope ≥2-model rule to code-review). |
| 15 | **Schema activation is folklore in this repo:** propose skill never passes `--schema opsx-superpowers` (AC unimplemented), and live `openspec/config.yaml` says `spec-driven` — a fresh `/opsx-propose` here silently creates a non-opsx change. | Implement the AC + flip config.yaml. |
| 16 | **Budget parsing divergence:** extension accepts `80junk`→80 (regex unanchored); bash fallback mangles `-1`→1, `abc80`→80, and defaults to 40 where extension/spec say unbounded. Goal-mode pre-change budget branch is dead code (`maxTurns` always undefined before adoption). | Single strict parser semantics; delete or implement the dead branch. |
| 17 | **Gate self-modification — partially resolved during audit:** verified the gate reads `opsx-gates.yaml` from `$ROOT` (integration checkout), never the worktree, so the agent under test cannot weaken its gate from inside the worktree. Residual risk: the in-session agent also has write access to ROOT; nothing but diff review detects a manifest edit there. | Accept residual risk + add manifest-diff check to code-review rubric, or gate-fail if manifest changed since change creation. |

### P3 — rot / ceremony / hygiene (batch cleanup)

- README triple-contradiction: mode count (8 vs 11 vs 13 actual), phantom "adr artifact glob is intentional" note, Scale-S table vs schema (design L1). README + capability-hooks still present the goal-extension judge as primary loop runtime; the opsx-loop extension (stall detector, gap ratchet) is the real primary (M3).
- Archive mode-ref: two sections both labeled "HARD-GATE 2"; `docs/adr/` vs `adr/` path slip (L2). Archive defense-in-depth re-checks verify + code-review but not doneness — the newest axis has no archive-side backstop (M4).
- clarify.md template comment orders the exact cartesian-product enumeration the schema/spec/skill forbid (M6).
- Own specs violate own rules: `TBD` Purposes across all 12 specs after six archives; WHEN-on-error ACs; `yellow` verdict vocabulary in skill-integration spec; 40-line 10-SHALL stall-detector requirement (L3/L4).
- Apply mode-ref pre-flight mode list stale (8 of 13 modes); "missing review.md → assume XS defaults" contradicts gate + README default S (L5).
- Live `opsx-gates.yaml` is thin: syntax checks only, `shell-syntax` optional, no `bun test` despite `helpers.test.ts` existing — the "mechanical doneness" premise of ADR-0012 is mostly unexercised in the workflow's own home repo (L7).
- `/opsx-loop models` wrapper forces `OPSX_ROOT=ctx.cwd`, breaking ancestor discovery from subdirectories (P2 in code audit).
- `opsx models list` uses jq without checking for it (P3).
- Duplication watchlist (rot generators): mode vocabulary in 5 places; prompt/skill fork (finding 7) is the systemic instance; capability-hooks indirection now degenerate — collapse it (L8).

---

## 4. Recommended action bundles

**Bundle A — correctness patch (one opsx change, highest urgency).** Findings 1–5: gate worktree artifact-source unification, argv validation (exit 2), env cleanup on export, subprocess timeouts, test-file filter in verify Check 5. Plus finding 13 (fail-closed modes) and 16 (parser parity) — same code surface. Add the 9 tests listed at the end of `code-audit.md` (worktree divergent-artifact integration test first).

**Bundle B — doc de-drift (one change, mostly mechanical).** Findings 6–8 + P3 batch: rewrite schema.yaml base-SHA prose to merge-base contract; make `.pi/prompts` thin skill-invoking wrappers (or delete them); port memory promotion to hindsight; fix README/mode tables/archive-ref/clarify-comment; update own specs to own EARS rules.

**Bundle C — policy ADRs (decisions, then small diffs).** Findings 9–12, 14, 17: intent-confirmation in goal mode; fresh-context vs same-session loop; cost layer; worktree lifecycle ownership; `blind-single-judge` vocabulary; gate-manifest read-path pinning. Each is a one-paragraph ADR + a targeted edit.

**Bundle D — teeth for the home repo (15 minutes).** Finding 15 + L7: flip `openspec/config.yaml` to `opsx-superpowers`, add `--schema` to propose skill, add required `bun test` + `bash -n` (required) gates to live `opsx-gates.yaml`.

Suggested order: **D → A → B → C** (D is trivial and makes A's fixes self-verifying through your own loop; A protects the loop; B stops re-teaching agents the dead contracts; C at leisure).

---

## 5. What is genuinely good (keep, don't churn)

- Exit-code-as-contract gate (ADR-0005) with cheap-before-expensive ordering — cleaner than most published gate designs.
- Doneness as sealed, gate-read LLM backstop that can only *block*, never *pass* (ADR-0012) — textbook "judge for semantics, determinism for mechanics".
- Stall detection sophistication (failure-key normalization + worktree HEAD/content progress + doneness gap-set ratchet) exceeds anything in the published Ralph-loop literature.
- Intent sha256 freeze + loop-never-archives + prompt-guarded archive: correct human-checkpoint placement per 2026 consensus.
- Scale tiers with per-tier artifact reduction directly implement the "right-sizing" convergence Fowler/Kiro arrived at.
- Blind adversarial multi-model review with GO/NO-GO predates and matches the now-standard pattern.

---

## Appendices

- `2026-07-02-opsx-appendices/code-audit.md` — full implementation findings with file:line evidence, reproduction commands, 9 prioritized test additions.
- `2026-07-02-opsx-appendices/design-audit.md` — full coherence findings H1–H4, M1–M6, L1–L8 with per-file anchors.
- `2026-07-02-opsx-appendices/best-practices.md` — sourced 2026 state-of-the-art brief: SDD consensus/contested/failure modes + autonomous-looping checklists (all URLs).
