---
name: designing-from-a-repo
description: Use when asked to design, redesign or plan the architecture of an existing repository or one of its components — to turn what the code already does into the smallest elegant, maintainable, separable and composable design, with a staged path to get there. Works on a bare repo; gets sharper when given a requirements report, a PRD, review-map pages or validation points. Output is one DESIGN.md with a principles table. Not for auditing dependency-rule drift only (auditing-clean-architecture), a code-quality cleanup plan (desloppify), explaining a PR (review-map) or extracting requirements (the requirements skill).
---

# Designing from a repo

Turn what a repo already is and does into the design it should have, plus the smallest path from one to the other. The bar is `~/.local/share/agent-harness/design-principles.md`: read it first and measure against it by section number. Do not copy or reword it.

Read-only against the repo. Write `DESIGN.md` and `facts.json` outside it (the path the user gives, else a scratch folder). Scratch clones and small scripts against an extracted copy are allowed when the caller bars builds and tests; name what you ran. Assume a private, local, one-owner setting; add no security or threat sections.

## Inputs (all optional except the repo)

Use what exists and name in the output which you used.

| Input | Where | Use |
|---|---|---|
| Requirements report | a `REQUIREMENTS.md` whose header says `shape: requirements/1` (the requirements skill) | Replaces Step 3 inference; see below |
| Repo's own documents | `docs/PRD.md`, a component's `CONTRACT.md`, specs, ADRs, a `prd-candidate.md` from using-generate-prd | `given` requirements, even when the caller says "bare" |
| Validation points, journeys, e2e tests | `tests/`, `journeys/` | Behaviour without rediscovery from code |
| review-map pages | the caller's links | What recently moved and what it reaches |
| Owner intent | the prompt | The goal in Step 0 |

Reading a `requirements/1` file: cite its ids, never re-mint them. Requirements come from the register (`R-n`; ignore `incidental` rows when drawing boundaries), state machines from `SM-n` (reference; redraw only to add what you found) with their `writers:` lines, invariants from `I-n`, reachable defects from `F-n` and unenforced invariants from `U-n` (Step 4 failures), `fit` and `enforced` gaps as Step 6 proof gaps only where a decision depends on them, and `Q-n` as candidates for Step 8. Check its `commit` against the pinned rev and its `not-read` against your scope. **It is an input, not a fact: re-check every item a ranked failure or decision rests on against the code** (it can be wrong, stale or encode the bug as a requirement). Findings you add get ids `DF-n`. For any other shape version, read it as free text and say so.

A bare repo must still work: infer from README, `AGENTS.md`, manifests, entry points and tests, and label every such claim `inferred`.

## Steps

**0. Frame.** Write the goal in one sentence, the scope (whole repo or named component), the inputs found, and any parts the caller names. Check every named path, part and artifact against the pinned rev and report the ones that do not exist before designing. If the goal is "make it better" with no pull, get the one pain that matters (slow to change, hard to test, hard to reuse). Do not design without a pull (§4).

**1. Orient and gather facts.** Pin the rev (`git rev-parse HEAD`; again at the end; if it moved, say so). Extract what you will read once (`git archive REV PATHS | tar -x -C SCRATCH`) and read from there; in zsh write `${REV}:path`. Then run the bundled script, which does every count so you do not:

```sh
python3 <skill-dir>/scripts/repo_facts.py REPO --rev REV [--scope 'GLOB' ...] [--parts parts.tsv] --out facts.json
```

Use `--scope` for a named slice. Do not read the JSON whole; query the keys you need. It analyses the pinned rev: sizes (code and tests apart, excluded trees named), imports and cycles (TypeScript/JavaScript and Python only; says what it did not parse), path references between files, fan-in, co-change, in-flight branches touching scope, the repo's own architecture gate and proof commands, and the documents found.

Then read, in this order: a component scope's `CONTRACT.md`, the repo's architecture gate (it is the repo's statement of its layout), the sections of README and `AGENTS.md` that say how a change is proven here (commands and what each costs), manifests and entry points. If the repo has no architecture gate, the gate is whatever proves a change.

**Work already in flight is prior art (§11).** From `in_flight` / `branches_touching_scope`, read what touches scope. Record each move's state (merged, unmerged, reviewed) and adopt, extend or reject it with a reason. A design that ignores a half-finished move in the same repo is wrong. A history-clean copy has no branches; say so and look for the move in the code's own plan words.

Write a ≤1-page orientation a cold agent could read instead of the repo.

**2. Inventory components as found.** If the caller's parts are not units in the code, propose a glob-to-part table (`**` crosses `/`; `*` does not) as a hypothesis, run `--parts`, and revise until the leftover cross-part edges are explained; keep the final table. For each part: its job in one sentence, public interface, what it depends on and what depends on it, what it changes with, and its kind: **component** (reusable, no sibling imports), **use-case folder** (behaviour over a shared component), **entry-point adapter** (CLI, server, UI) or, in a manifest repo, **composition root** (what wires the rest), **deployable unit** or **overlay**. No import edges is not separation: in manifest and script repos coupling is by path strings and names; use `path_refs` and write the edges the script cannot see by hand, labelled "found by reading". Record cycles, cross-component imports, cores that import adapters, and logic in an entry point.

**3. Requirements.** From the inputs if present, else infer: the journeys the entry points serve and the invariants the code relies on (note which nothing enforces). Separate enduring obligations from incidental implementation. Mark each `given` (cite the id or document) or `inferred` (`IR-n` requirements, `II-n` invariants). Where a component is a state machine in disguise and none is given, draw it as Mermaid `stateDiagram-v2`.

**4. Diagnose.** For each principle 1–15 give a verdict with its **scope** (pass at module level, fail inside one module: write both) and evidence from `facts.json` or a command. An `n/a` row needs one sentence, no more. Then name the 3–5 tensions that matter (§13) and rank the failures by proven harm. **Reproduce each ranked failure** with a small script against the extracted pin (symlink `node_modules`; no installs) or a scratch clone, and say so; otherwise label it `read only`, and make the experiment the first increment in Step 6. Check that each test double the proof relies on does what the real adapter does (a fake that records nothing the real one records hides the race). Where the owner's goal is "separable" or "testable on its own", that is not reuse: satisfy it with a contract-level test and an import fence, not a folder, unless a second user exists.

**5. Design the target.** The smallest design that meets the goal and the requirements:
- The kind of each part and its single job. A component needs a second real use (§1); without one it stays inside its neighbour or becomes a use-case folder.
- When the owner's goal asks for reuse and §1's test fails, do not pick a side silently. Define reuse as "folder with a public entry, a CLI if any, and a contract", record the tension, and list packaging as an owner decision with your recommendation.
- Kernel and adapters (§2), layers inside a component only where it is big enough to need them (§3, §4). A large component that works and shows no harm is `fail (accepted)` by default.
- Ports, contracts, invariants and log records (§5, §14); a conformance suite per adapter (§6); one composition root (§7).
- Prior art per component, including what the repo is already doing to itself (§11).
- **External systems the design leans on** (a controller, database, CLI, shim): read their behaviour at the pinned version from source or docs, not from memory, and list every claim only the live system can settle (ordering at start-up, what a resume or retry does, what a race leaves behind) under Section 8 as "unverified until run", with the experiment. A design that sequences steps around another system's behaviour and states it as settled is the commonest way a good-looking design fails.
- What stays as it is, and why.
Every new boundary, layer or abstraction needs a concrete requirement or a demonstrated failure; if it only reads well, cut it (§4). Before changing any key, name or format, count its literal uses. Before finalising, ask what can be deleted and still meet the requirements.

**6. Path.** Ordered increments, each shippable alone and proved from outside the way this repo proves changes (§12, §15). Say which can run in parallel and which must be serial, one line why. Start with the increment that removes the worst proven failure. For a race, the proof places the interleaving at every `await` window, not one; and tie a record to the thing it was made for by an identity (a key or id carrying it), never by comparing timestamps written by different processes. Add build gates in the increment that creates the boundary, not before.

**7. Write `DESIGN.md`** in the shape below, then verify:
- every `fail` maps to a decision, or is `fail (accepted)` and tied to a Section 7 item with the trigger that would reopen it;
- every decision maps to a requirement or a failure;
- nothing inferred is presented as given;
- **every number comes from a command you saw: cite the `facts.json` key or keep the command in Section 1's Evidence list (a re-runnable script is best); re-run them at the end and fix any that moved. Quote `lines` for one file and `code_lines` for sums, and say which.**

## Output shape (keep it stable; other tools read it)

```markdown
# Design: <scope>
Goal · Scope · Rev (start / end) · Inputs used (given / inferred) · In-flight work relied on (and its state) · Top 3 decisions

## 1. Orientation            (≤1 page: what it is, entry points, size, how a change is proven, where to start; Evidence: the commands behind every number)
## 2. As found               (parts table with kind; edge list; Mermaid diagram; excluded trees)
## 3. Requirements and invariants   (given: cite ids; inferred: IR-n / II-n; enforced? yes/no/partial)
## 4. Diagnosis              (tensions T1…; ranked failures F/DF-n each with evidence, "reproduced by" or "read only", cost of leaving it)
## 5. Target design          (decisions D1…: what, why, requirement or failure it answers, rejected alternative; Mermaid diagram)
## 6. Path                   (increments S1…: change, proof from outside, depends on, parallel?)
## 7. Not doing              (considered and cut, and the trigger that would reopen it; accepted fails live here)
## 8. Open for the owner     (changes to promised outcomes or unresolved product trade-offs only, each with a recommendation)
## 9. Principles table
| # | Principle | As found | Target | Evidence |
|---|---|---|---|---|
| 1 | Composable components | fail | pass | scope: …; key or decision id; read / sampled / untested |
… one row for each of 1 to 15; keep each Evidence cell to about 40 words and point to the Section 4 item …
```

Verdicts: `pass`, `fail`, `n/a`; Target may also say `fail (accepted)`; Evidence says what you read and what you did not, and `untested` where the test needs a live run (§14's replay). **Target means after the last increment in Section 6.** The table is required; a design without it is not finished.

## How this differs from nearby skills

- `auditing-clean-architecture`: finds dependency-rule drift and emits prose findings only. This designs the whole target and the path, and its bar is design-principles.md, not the clean-architecture family alone. Run the audit for a narrow architectural question; use its findings as input to Step 4.
- `desloppify`: a many-phase plan for code-quality decay (duplication, naming, dead code). This works one altitude up (components, seams, contracts) and writes one document. Use desloppify for cleanup the increments do not cover.
- `review-map`: explains one PR. Use its pages as input; this skill does not read diffs.
- `using-generate-prd` and the requirements skill: they say what the product must do. This says how it should be built. Their output is input here; this skill needs neither.
- `/statechart` (poteto, pstack): proves state-machine models with TLA+. Borrowed ideas only: treat the model as wrong until the code confirms it, label diagrams in the reader's words, declare what you left out. No TLA+ is required.

## Done when

`DESIGN.md` and `facts.json` exist, every section is filled or marked n/a with a reason, the principles table has 15 rows with evidence, and the first increment could start today without a further question. Report the file path, the three decisions that matter most, anything left for the owner, and which proofs you observed versus only planned (a design is not proof).
