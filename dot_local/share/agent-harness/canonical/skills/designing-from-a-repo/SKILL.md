---
name: designing-from-a-repo
description: Use when asked to design, redesign or plan the architecture of an existing repository or one of its components — to turn what the code already does into the smallest elegant, maintainable, separable and composable design, with a staged path to get there. Works on a bare repo; gets sharper when given a requirements report, a PRD, review-map pages or validation points. Output is one DESIGN.md with a principles table. Not for auditing dependency-rule drift only (auditing-clean-architecture), a code-quality cleanup plan (desloppify), explaining a PR (review-map) or extracting requirements (the requirements skill).
---

# Designing from a repo

Turn what a repo already is and does into the design it should have, plus the smallest path from one to the other. The bar is `~/.local/share/agent-harness/design-principles.md`: read it first and measure against it by section number. Do not copy or reword it.

Read-only against the repo. Write one file: `DESIGN.md` (default `<scratch or docs/design>/<scope>-DESIGN.md`, or the path the user gives), plus `facts.json` beside it. Assume a private, local, one-owner setting; do not add security or threat sections.

## Inputs (all optional except the repo)

Use what exists and name in the output which you used.

| Input | Where | Use |
|---|---|---|
| Requirements report | a `REQUIREMENTS.md` whose header says `shape: requirements/1` (the requirements skill) | Replaces Step 3 inference; see below |
| Repo's own documents | `docs/PRD.md`, `CONTRACT.md`, specs, ADRs, a `prd-candidate.md` from using-generate-prd | `given` requirements, even when the caller says "bare" |
| Validation points, journeys, e2e tests | `tests/`, `journeys/` | Behaviour without rediscovery from code |
| review-map pages | the caller's links | What recently moved and what it reaches |
| Owner intent | the prompt | The goal in Step 0 |

Reading a `requirements/1` file: cite its ids, never mint new ones. Requirements come from the register (`R-n`; ignore `incidental` rows when drawing boundaries), state machines and invariants from `SM-n` / `I-n`, reachable defects from `F-n` and unenforced invariants from `U-n` (these are Step 4 failures), `fit` of `partial`, `title` or `none` and `enforced` of `partial` or `no` as proof gaps for Step 6, and `Q-n` as candidates for Step 8. Compare its `commit` with the pinned rev and its `not-read` with your scope; say what is stale or uncovered. For any other shape version, read it as free text and say so.

A bare repo must still work: infer from README, `AGENTS.md`, manifests, entry points and tests, and label every such claim `inferred`.

## Steps

**0. Frame.** Write the goal in one sentence, the scope (whole repo or named component), the inputs found, and any named "parts" the caller uses. If the goal is "make it better" with no pull, get the one pain that matters (slow to change, hard to test, hard to reuse) from the caller. Do not design without a pull (§4).

**1. Orient and gather facts.** Pin the rev (`git rev-parse HEAD`, again at the end; if it moved, say so). Run the bundled script, which does every count so you do not:

```sh
python3 <skill-dir>/scripts/repo_facts.py REPO [--rev REV] [--parts parts.tsv] --out facts.json
```

It analyses the pinned rev, never the working tree, and writes sizes (code and tests apart, fixtures and generated trees excluded and named), the import graph and cycles, fan-in, co-change, work in flight, the repo's own architecture gates and the documents found. It parses TypeScript/JavaScript and Python imports; other languages get sizes and co-change only, which it says. Then read: README, `AGENTS.md`, manifests, entry points (CLI, server, extension, cron), and **how a change is proven here** (the gate and test commands and what each costs). Read the repo's own architecture gate first: it is the repo's statement of its layout.

**Work already in flight is prior art (§11).** Read `in_flight` from the facts: branches, worktrees, recent plan-shaped commits. Record each move's state (merged, unmerged, reviewed) and adopt, extend or reject it with a reason. A design that ignores a half-finished move in the same repo is wrong.

Write a ≤1-page orientation a cold agent could read instead of the repo.

**2. Inventory components as found.** If the caller's named parts are not units in the code, propose a glob-to-part table as a hypothesis, run `repo_facts.py --parts`, and revise until the leftover cross-part edges are explained; put the final table in the output. For each part: its job in one sentence, public interface, what it depends on and what depends on it, what it changes with, and which kind it is: **component** (reusable, no sibling imports), **use-case folder** (behaviour over a shared component) or **entry-point adapter** (CLI, server, UI). Record cycles, cross-component imports, cores that import adapters, and logic sitting in an entry point. Treat the model as a hypothesis: confirm a doubtful edge in the code and list what you did not look at.

**3. Requirements.** From the inputs if present, else infer: the user journeys the entry points serve, and the invariants the code relies on (note which nothing enforces). Separate enduring obligations from incidental implementation. Mark each `given` (cite the id or document) or `inferred` (id `IR-n` for requirements, `II-n` for invariants). Reuse given state machines; where a component is a state machine in disguise and none is given, draw it as a Mermaid `stateDiagram-v2`.

**4. Diagnose.** For each principle 1–15 record a verdict with a **scope** (a principle can pass at module level and fail inside one module: write both), evidence from facts.json or a command, and whether it was checked in `full` or by `sampled N of M`. Then name the 3–5 tensions that matter (§13): where requirements, simplicity and reuse pull apart, and what leaving each costs. Prefer a few proven failures over a list of preferences. Section 4 of the output holds tensions and ranked failures; per-principle verdicts live only in the table.

**5. Design the target.** The smallest design that meets the goal and the requirements:
- The kind of each part (Step 2) and its single job. A component needs a second real use (§1); without one it stays inside its neighbour or becomes a use-case folder.
- **When the owner's goal asks for reuse and §1's test fails**, do not silently pick a side. Define reuse as "folder with a public entry, a CLI if any, and a contract", record the tension, and list packaging as an owner decision with your recommendation.
- Kernel and adapters (§2), layers inside a component only where it is big enough to need them (§3, §4).
- Ports, contracts, invariants and the log records each component emits (§5, §14); a conformance suite per adapter (§6); one composition root (§7).
- Prior art per component, including what the repo is already doing to itself: adopt, wrap, borrow or build, with the reason (§11).
- What stays as it is, and why.
Every new boundary, layer or abstraction needs a concrete requirement or a demonstrated failure. If it only reads well, cut it (§4). Before finalising, ask what can be deleted and still meet the requirements.

**6. Path.** Ordered increments, each shippable alone and proved from the outside the way this repo proves changes (§12, §15). Say which can run in parallel and which must be serial, with one line why. Start with the increment that removes the worst proven failure. Add the build gates (dependency and layer checks) in the increment that creates the boundary, not before.

**7. Write `DESIGN.md`** in the shape below, then verify before you finish:
- every `fail` maps to a decision or is marked `fail (accepted)` and tied to an Open item;
- every decision maps to a requirement or a failure;
- nothing inferred is presented as given;
- **every number in the document comes from a command output you saw (cite the `facts.json` key or the command); re-run the commands at the end and fix any that moved.**

## Output shape (keep it stable; other tools read it)

```markdown
# Design: <scope>
Goal · Scope · Rev (start / end) · Inputs used (given / inferred) · In-flight work relied on (and its state) · Top 3 decisions

## 1. Orientation            (≤1 page: what it is, entry points, size, how a change is proven, where to start)
## 2. As found               (parts table and kind; edge list; Mermaid diagram; excluded trees)
## 3. Requirements and invariants   (given: cite ids; inferred: IR-n / II-n; enforced? yes/no/partial)
## 4. Diagnosis              (tensions T1…, ranked failures; each with evidence and cost of leaving it)
## 5. Target design          (decisions D1…: what, why, requirement or failure it answers, rejected alternative; Mermaid diagram)
## 6. Path                   (increments S1…: change, proof from outside, depends on, parallel?)
## 7. Not doing              (considered and cut, and what would change that)
## 8. Open for the owner     (changes to promised outcomes or unresolved product trade-offs only, each with a recommendation)
## 9. Principles table
| # | Principle | As found | Target | Evidence |
|---|---|---|---|---|
| 1 | Composable components | fail | pass | scope: …; facts.json key or decision id; (full) or (sampled N of M) |
… one row for each of 1 to 15 …
```

Verdicts: `pass`, `fail`, `n/a`; Target may also say `fail (accepted)`. **Target means after the last increment in Section 6.** The table is required; a design without it is not finished.

## How this differs from nearby skills

- `auditing-clean-architecture`: finds dependency-rule drift and emits prose findings only. This designs the whole target and the path, and its bar is design-principles.md, not the clean-architecture family alone. Run the audit for a narrow architectural question; use its findings as input to Step 4.
- `desloppify`: a many-phase plan for code-quality decay (duplication, naming, dead code). This works one altitude up (components, seams, contracts) and writes one document. Use desloppify for cleanup the increments do not cover.
- `review-map`: explains one PR. Use its pages as input; this skill does not read diffs.
- `using-generate-prd` and the requirements skill: they say what the product must do. This says how it should be built. Their output is input here; this skill needs neither.
- `/statechart` (poteto, pstack): proves state-machine models with TLA+. Borrowed ideas only: treat the model as wrong until the code confirms it, label diagrams in the reader's words, and declare what you left out. No TLA+ is required.

## Done when

`DESIGN.md` and `facts.json` exist, every section is filled or marked n/a with a reason, the principles table has 15 rows with evidence, and the first increment could start today without a further question. Report the file path, the three decisions that matter most, and anything left for the owner.
