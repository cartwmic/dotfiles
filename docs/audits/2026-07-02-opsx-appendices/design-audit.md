# opsx Workflow Design-Coherence Audit

**Date:** 2026-07-02 · **Scope:** schema (`dot_local/share/openspec/schemas/opsx-superpowers/`), 7 canonical skills + mode refs, `.pi/prompts/opsx-*.md`, 11 permanent capability specs + `goal-loop`, ADR-0001…0012, live `openspec/opsx-gates.yaml`, `dot_local/bin/executable_opsx` (spot-checked against specs). Read-only.

**Verdict in one line:** The enforcement spine (gate ↔ specs ↔ loop skill ↔ doneness judge) is coherent and impressively cross-referenced, but the *older documentation layer* (schema.yaml apply/tasks instructions, README, `.pi/prompts`, memory-promotion pipeline) has drifted behind three generations of later changes (loop-harness, model-config, cli-consolidation, doneness-judge) and now contradicts the spec-of-record in several load-bearing places.

Positive note up front: the two known past gaps — worktree creation-failure and cleanup-on-gate-failure — are now covered (`opsx-workflow-schema` "Worktree Lifecycle Ownership" scenarios: creation-failure aborts, reuse preserves base, budget exhaustion preserves worktree; `opsx-loop-kickoff` stall detector). Gate implementation (`executable_opsx`) matches the gate/doneness specs on every point spot-checked (lifecycle ordering, doneness suppression as sole-remaining-failure, waiver-rationale content check, provenance/freshness checks, author-marker conditionality).

---

## SEVERITY 1 — HIGH (contradictions on load-bearing contracts)

### H1. Two incompatible diff-base contracts: schema.yaml says "Worktree Base SHA = rev-parse HEAD", spec says "Diff Base SHA = merge-base; no such field exists"

- `dot_local/share/openspec/schemas/opsx-superpowers/schema.yaml` — **apply instruction**: "Capture base SHA: `git -C <worktree-path> rev-parse HEAD` → write to review.md **"Worktree Base SHA"** field. Used by all subsequent file-contract diffs."
- Same file — **tasks instruction**: "`git diff --name-only <worktree-base-sha>..HEAD` where `<worktree-base-sha>` is captured at apply start (review.md **Worktree Base SHA** field)."
- `README.md` capability table: "Pre-flight commit before worktree … apply step captures **Worktree Base SHA** for file-contract diffs."

versus:

- `openspec/specs/opsx-workflow-schema/spec.md` ("Worktree Mode forces isolation" scenario): "file-contract diffs SHALL use the single immutable `Diff Base SHA` … **there is no separate apply-start `Worktree Base SHA`**"; and ("Diff base is immutable"): "`Diff Base SHA` as the **integration-branch merge-base (not apply-start HEAD)**".
- `templates/review.md` has only a `Diff Base SHA` field; `openspec-apply-change/references/opsx-superpowers-mode.md` implements merge-base and explicitly says "NOT apply-start HEAD".
- The gate (`executable_opsx` line ~499) reads only `Diff Base SHA`.

**Failure mode:** `openspec instructions apply/tasks --json` serves the *schema.yaml* text to the agent. An agent following it verbatim writes a `Worktree Base SHA` field the gate and template never read, and on branch reuse computes contract diffs from current HEAD instead of the immutable merge-base — exactly the "commits made earlier in the apply session vanish from the diff" bug the spec was amended to prevent. The skill ref is correct; the schema instruction — the thing OpenSpec actually feeds the model — is the stale copy.

**Fix direction:** rewrite the base-SHA prose in schema.yaml's apply + tasks instructions and README's table row to the Diff-Base-SHA/merge-base contract.

### H2. `.pi/prompts/opsx-*.md` are stale forks of the skills — missing the entire opsx-superpowers branch

- `.pi/prompts/opsx-explore.md` — lacks the skill's "Schema awareness (opsx-superpowers)" section and, critically, the **"freeze intent.md"** section (`openspec-explore/SKILL.md` end). intent.md is the loop's precondition and the gate's required artifact at Scale ≥ M.
- `.pi/prompts/opsx-propose.md`, `opsx-apply.md`, `opsx-archive.md` — none contain step 2.5 (branch on `schemaName == "opsx-superpowers"` → load `references/opsx-superpowers-mode.md`). Grep for `opsx-superpowers` across all four prompts: zero hits.

**Failure mode:** a user who enters the workflow via the repo-local slash commands (the natural pi entry point) gets the upstream spec-driven flow: no Scale prompt, no worktree, no Diff Base SHA capture, no verify.md/code-review.md production, no verify/code-review/gate HARD-GATEs at archive, no intent freeze at explore. The deterministic gate would eventually catch apply/archive omissions *if* the loop is used, but `/opsx-archive` run directly performs the plain `mv`-to-archive with only soft warnings — bypassing every opsx control including gate-green.

**Fix direction:** either make the prompts thin wrappers that invoke the skills, or delete them; duplicated prose guarantees recurring rot (this is the "duplicate sources of truth" failure class, instance #1).

### H3. Memory-promotion pipeline references a retired backend (mcp-memory) — XL archive path depends on a tool that no longer exists

- `templates/retrospective.md` — "9 canonical mcp-memory types", ≥300/≥600-char rules, `mcp_memory_store_memory` calls.
- `openspec-archive-change/references/opsx-superpowers-mode.md` HARD-GATE 4 — parses candidates, calls `mcp_memory_store_memory`, "Per the mcp-memory contract…".
- `capability-hooks.md` `memory-promotion` — "mcp-memory MCP server (host: `mcp-memory.internal.cartwmic.com`)… see CLAUDE.md 'Memory: mcp-memory MCP server'".
- `openspec/constitution.md` Principle X + See-also — same references.
- The live memory contract (CLAUDE.md) is now **hindsight** (`hindsight-api.internal.cartwmic.com`): *no memory-type taxonomy* ("Don't classify"), `retain`/`recall`/`reflect`, different tagging rules (no `memory_type`, no type-name-as-tag).

**Failure mode:** at Scale XL the archive skill *refuses* to archive without retrospective.md, then drives a promotion loop against a nonexistent tool; the graceful fallback (write `retrospective-promote-pending.md`) fires on every archive forever. Additionally the taxonomy is internally inconsistent even before the migration: `openspec/specs/opsx-skill-integration/spec.md` ("Retrospective promote-candidates ingested") lists **6** types; the template and archive ref list **9**.

**Fix direction:** port the promotion contract to hindsight (`retain` with `project:`/`topic:` tags, drop type/char-count validation), update constitution X wording, capability-hooks entry, retrospective template, and the skill-integration spec scenario in one change.

### H4. verify.md Check 5 (forward AC↔test grep) is self-satisfying as written — spec and template disagree

- `openspec/specs/opsx-spec-quality/spec.md` (forward scenario): "at least one **test file** (heuristic: paths matching `/(^|/)tests?/` or `/\.(test|spec)\.[^.]+$/`) SHALL contain the ID".
- `templates/verify.md` + `openspec-apply-change/references/opsx-superpowers-mode.md` implement: `git diff --name-only <base>..HEAD | xargs grep -l "$id"` — **no test-file filter**; "Pass if any match".

**Failure mode:** the change's own artifacts sit in the diff and contain canonical AC IDs by construction — `clarify.md` (AC-ref column), `analyze.md` (Check 3 table), and `verify.md` itself (forward-coverage table). Forward coverage therefore passes with zero tests. The reverse check doesn't compensate (it only inspects files already classified as tests). This is the one deterministic teeth-check whose documented procedure doesn't implement its own spec.

**Fix direction:** pipe the diff list through the same test-file heuristic before grepping (one-line fix in template + apply ref), and note artifact files are excluded.

---

## SEVERITY 2 — MEDIUM

### M1. Doneness `review_mode` vocabulary is undefined for a single judge

- `opsx-doneness-judge/spec.md` mandates **one** "independent blind subagent" on the `review` role; gate fails the verdict if `review_mode` is missing or `degraded-single-model` (`executable_opsx` ~726).
- The only non-degraded value defined anywhere is `adversarial-multimodel`, which `openspec-apply-change/references/opsx-superpowers-mode.md` defines for code-review as "requires ≥ 2 distinct models".
- `templates/doneness.md` pre-fills `**review_mode:** adversarial-multimodel` — for an artifact that is by-spec authored by a *single* judge.

**Issue:** a single blind judge is neither "adversarial-multimodel" (per the ≥2-model definition) nor "degraded-single-model" (which the spec reserves for *inline, no-adapter* review). The gate passes on any non-degraded string, so in practice the template value works — but the semantics are incoherent and a future stricter gate (or a literal-minded adapter) has no correct value to stamp. Define a third value (e.g. `blind-single-judge`) or scope the multimodel≥2 rule to code-review explicitly.

### M2. Schema activation path is broken in the dogfood repo: propose never passes `--schema`, and `openspec/config.yaml` says `spec-driven`

- `openspec/specs/opsx-skill-integration/spec.md` ("Schema detection at change creation"): the skill "SHALL pass `--schema opsx-superpowers` to `openspec new change`".
- `openspec-propose/SKILL.md` step 2: `openspec new change "<name>"` — no `--schema` flag anywhere; step 2.5 only *detects* after creation.
- Live `openspec/config.yaml`: `schema: spec-driven` (README activation says the project opts in via this field; archived changes carry per-change `.openspec.yaml: schema: opsx-superpowers`, so opt-in evidently happened per-change by hand).

**Failure mode:** a fresh `/opsx-propose` in this repo creates a spec-driven change; every opsx branch (worktree, gate, doneness, intent) silently stays off — the exact "silent feature-off" the step-2.5 log line was designed to surface, except here the log will truthfully say "[feature off]" and the user must know to care. AC is unimplemented; config contradicts the README's stated activation model.

### M3. Loop-runtime narrative not updated after `add-opsx-loop-kickoff`

- `README.md` "Driving a change (the loop)" and `capability-hooks.md` `loop-continuation` still present the **goal extension with `PI_GOAL_JUDGE_CMD='opsx gate <change>'`** as the primary loop runtime, with `opsx loop` bash as fallback.
- The actual primary is the dedicated **opsx-loop pi extension** (`openspec/specs/opsx-loop-kickoff/spec.md`; "Goal extension is not modified… both extensions SHALL operate independently"), which adds things the goal-judge path lacks entirely: worktree re-resolution per turn, stall detection, the doneness gap-set ratchet, model-env export, goal/distill kickoff.

**Issue:** a reader following the README wires up the goal extension and silently loses the stall backstop that ADR-0012 calls load-bearing ("needs a doneness-aware backstop under ∞ budget"). Docs should present opsx-loop extension → goal-cmd-judge → bash driver as the actual adapter ladder.

### M4. Archive defense-in-depth re-asserts verify and code-review but not doneness

- `openspec-archive-change/references/opsx-superpowers-mode.md` rationale: "a human may archive without the gate", hence HARD-GATEs 1–2 re-check verify.md and code-review.md fields. There is no doneness re-check.

**Issue:** in the human-archives-without-gate path (the very case the defense-in-depth exists for), the newest enforcement axis (ADR-0012) is the only one with no archive-side backstop. Either add a doneness HARD-GATE mirroring code-review, or drop the "human may skip the gate" rationale and make HARD-GATE 0 unconditional.

### M5. Goal-mode kickoff lets the agent author *and freeze* intent.md autonomously

- `opsx-loop-orchestration/spec.md` "Frozen Intent Baseline": intent.md written by explore "WHEN the user finishes an explore session **and confirms** the intent".
- `opsx-loop-kickoff/spec.md` "Goal and conversation kickoff" + `dot_pi/agent/extensions/opsx-loop/index.ts` (~280): distill directive tells the agent to create the change and freeze intent.md itself, and the injected-directives requirement explicitly instructs *not* to pause for confirmation.

**Issue:** the immutable baseline every blind reviewer and the doneness judge is scored against can be self-authored by the loop being scored, with no human confirm gate — a real dilution of the "explore → intent (human) → loop-to-done" control model. For `/opsx-loop goal <text>` the goal text is at least human-supplied; for bare `/opsx-loop goal` (distill from conversation) the baseline is fully inferred. Worth an explicit ADR-style decision: either accept (document that goal-mode trades the intent checkpoint for autonomy) or require a one-shot intent confirmation before adoption.

### M6. clarify.md template comment orders the exact anti-pattern the schema forbids

- `templates/clarify.md` Pass 3 comment: "Enumerate **cartesian product** of declared events × states. Each uncovered combination → finding."
- `schema.yaml` clarify instruction, `clarify-spec/SKILL.md`, and `opsx-spec-quality/spec.md` all say: "Do **NOT** enumerate the full cartesian product… cap at 10."

Also minor sibling drift: the skill caps Pass 2 at 20 findings/file; schema and spec mention only prioritization, no cap.

---

## SEVERITY 3 — LOW (doc rot, ceremony, spec hygiene)

### L1. README internal contradictions (three in one file)

- Comparison table says review.md has "**8 modes** (…Spec-Level)" — there are 13 front-matter-relevant modes in `schema.yaml`; the README's own Mode-reference table lists 11 and **omits `Doneness Mode`** entirely (the newest gate check is invisible in the schema's primary doc).
- "Authoring notes" bullet: "`adr` artifact's `generates: ../../../adr/ADR-*.md` is intentional" — there is **no** adr artifact; the same README (and schema.yaml D11 rationale, and `opsx-workflow-schema` spec) explain at length why ADR is skill-managed *because* that glob is a bug. Leftover from a pre-decision draft.
- Scale-tier table marks clarify/design/analyze "Optional" at S, while schema.yaml/propose-ref define S as clarify-ambiguity-only + analyze-checks-1,2,7 (reduced, not optional).

### L2. Archive mode-ref numbering/path slips

- `openspec-archive-change/references/opsx-superpowers-mode.md` has **two sections labeled "HARD-GATE 2"** (AC↔test mapping; code-review pass) — a first-red-wins reader can't cite gates unambiguously.
- ADR-promotion prompt text says "Promote to **docs/adr/**ADR-NNNN…" while every other reference (including two lines above it) says `<repo>/adr/`. Repo uses `adr/`.

### L3. `opsx-skill-integration` spec cites a forbidden verify value

"Red verify blocks archive" scenario: "Completion Decision is `red` **or `yellow`**" — `opsx-spec-quality` and `templates/verify.md` both mandate binary green/red and explicitly prohibit yellow. Dead vocabulary in the spec-of-record.

### L4. The permanent specs violate the schema's own quality rules

- All 11 opsx specs + goal-loop carry `## Purpose  TBD — … Update Purpose after archive` — never updated, across six archived changes.
- No permanent spec carries the 5-property checklist the schema mandates "at the bottom of each spec.md" (only relevant to deltas by the letter, but the spec-of-record is what future changes diff against).
- Error-path ACs written with WHEN: `opsx-skill-integration/spec.md` ("WHEN **validators fail** during apply…", ×2) and `opsx-workflow-schema/spec.md` ("WHEN a task declares `intent: fix` and **validators fail**") — true positives under the schema's own analyze-check-2 regex, which mandates IF…THEN for error/failure conditions.
- Testability: the `opsx-loop-kickoff` stall-detector requirement is a ~40-line compound paragraph containing ≥10 SHALLs (gap-set ratchet, sentinel, resets, oscillation) — the scenarios rescue it, but as a *requirement* it flunks the schema's Unambiguous/Testable properties and would be flagged by its own clarify pass.

### L5. Apply mode-ref's "Pre-apply: read modes" list is stale

`openspec-apply-change/references/opsx-superpowers-mode.md` opening parse list enumerates only the original 8 modes — missing `Code Review Mode`, `Loop Max Iterations`, `Validation Source Mode`, `Doneness Mode`, model keys — all of which later sections of the same file (and the gate) depend on. Also "If review.md is missing OR all defaults (Scale=XS likely), use the defaults from the schema README" contradicts the gate's posture that a missing/unparseable Scale is a hard failure, and the README default is S, not XS.

### L6. Gap: no cleanup path for abandoned changes

Specs deliberately preserve the worktree + `opsx/<change>` branch on budget exhaustion, stall, interrupt, and merge-conflict abort — correct. But **no spec/skill covers ever removing them when a change is abandoned** (user runs `/opsx-loop clear` and walks away). Only the archive merge path removes worktrees. Over time: orphaned worktrees/branches with uncommitted verdict files (apply ref says keep verify/code-review *uncommitted* until gate-green, so they're also easy to lose). A `opsx clean <change>` or documented manual procedure would close this.

### L7. Live gate manifest is thin relative to the machinery above it

`openspec/opsx-gates.yaml` (this repo): `openspec validate` + `bash -n` syntax checks only; `shell-syntax` is `required: false`. The entire deterministic "mechanical doneness" for the dotfiles repo is structural — no test execution (`templates/opsx-gates.yaml` models `mise run test`). Given ADR-0012's premise that the gate proves mechanical doneness, the mechanical layer here is mostly the LLM-authored artifacts plus syntax. If `tests/**` exists for extensions (`opsx-loop/helpers.test.ts` does), wiring a required test gate would give the loop real teeth in its home repo.

### L8. Ceremony/duplication watchlist (would-rot list)

- **Prompt/skill duplication** (H2) is the systemic instance; same pattern risk between `opsx-PROMPT.md` (bash-driver worker prompt) and `openspec-loop/SKILL.md` "The cycle" — currently consistent, but two hand-synced statements of the turn algorithm.
- **review.md prose table vs front-matter**: spec correctly makes front-matter sole machine source, but every mode now must be maintained in *three* places (front-matter, prose table, Manual Adjustments) plus README table plus schema instruction — 5 copies of the mode vocabulary. The prose table's value over a comment is marginal.
- **capability-hooks indirection**: self-acknowledged degenerate (one candidate per capability). Fine per its own "collapse later" note; flagging that "later" is probably now — every table row except `subagent-dispatch` has exactly one real candidate.
- Gate lifecycle order (review first) vs artifact DAG (review sixth): deliberate (Scale must be read first) and mostly harmless because the loop delegates missing-artifact work to `openspec-propose` (which walks the DAG), but the worker prompt's "address exactly the earliest failure" would, taken literally, direct authoring review.md before proposal.md. A sentence in `opsx-PROMPT.md`/loop skill ("missing-artifact failures are resolved in DAG order via openspec-propose, not gate-report order") would remove the trap.

---

## (e) Human-control assessment — mostly holds

- **Loop never archives:** consistent across `openspec-loop/SKILL.md` ("ready to archive — the loop does not itself archive"), `opsx-PROMPT.md` ("Stop when gate exits 0"), kickoff spec (green → clear loop + notify), and the extension. ✔
- **Archive is human-initiated and prompt-guarded:** archive skill refuses to auto-select a change, prompts per ADR/memory promotion, `--override` requires recorded rationale. ✔
- **intent.md immutability:** enforced by prompt, skill, orchestration spec, and gate (sha256 check). ✔
- **Two caveats:** (1) goal-mode kickoff self-freezes intent (M5); (2) the stale `/opsx-archive` prompt (H2) is a direct bypass of every archive gate — the highest-leverage human-control defect found.

## Ranked summary

| # | Sev | Finding | Anchor |
|---|-----|---------|--------|
| H1 | High | schema.yaml apply/tasks + README teach dead "Worktree Base SHA"/rev-parse contract vs spec's immutable merge-base Diff Base SHA | `schema.yaml` apply instr.; `opsx-workflow-schema/spec.md` |
| H2 | High | `.pi/prompts/opsx-*.md` stale forks — no schema branch, no intent freeze; `/opsx-archive` bypasses all gates | `.pi/prompts/opsx-explore.md` et al. |
| H3 | High | mcp-memory promotion pipeline (9 types, `mcp_memory_store_memory`) vs live hindsight contract; spec says 6 types | `templates/retrospective.md`; archive ref; `capability-hooks.md`; constitution X |
| H4 | High | verify Check-5 forward grep unfiltered → self-satisfied by clarify/analyze/verify artifacts | `templates/verify.md`; apply ref; `opsx-spec-quality/spec.md` |
| M1 | Med | doneness `review_mode` has no defined value for a single blind judge; template pre-fills `adversarial-multimodel` | `templates/doneness.md`; `opsx-doneness-judge/spec.md` |
| M2 | Med | propose never passes `--schema`; repo config.yaml is `spec-driven` — activation is manual folklore | `openspec-propose/SKILL.md`; `openspec/config.yaml` |
| M3 | Med | README/capability-hooks still name goal-cmd-judge as loop runtime; opsx-loop extension (stall detector, gap ratchet) is the real primary | `README.md`; `capability-hooks.md` |
| M4 | Med | archive defense-in-depth omits doneness re-check | archive mode ref |
| M5 | Med | goal-mode kickoff self-authors the frozen intent baseline, no human confirm | `opsx-loop-kickoff/spec.md`; extension |
| M6 | Med | clarify template comment mandates the forbidden cartesian product | `templates/clarify.md` |
| L1–L8 | Low | README mode-count/adr-glob/Scale-table contradictions; duplicate HARD-GATE 2 + docs/adr path; 'yellow' vocabulary; TBD Purposes + WHEN-on-error in own specs; stale mode parse list; abandoned-worktree cleanup gap; thin live manifest; duplication watchlist | as cited |
