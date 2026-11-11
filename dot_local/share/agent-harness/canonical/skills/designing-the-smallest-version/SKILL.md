---
name: designing-the-smallest-version
description: Use when asked to design the clean, minimal version of something knowing what we know now — a new capability or feature built from the owner's requirements and what the system it plugs into already does, or a redesign of what an existing repo or component already does. Gives the smallest elegant, maintainable, separable, composable design plus a staged path, as one DESIGN.md with a principles table. Needs no other skill; takes a requirements report, PRD, tested facts, review-map pages or validation points when present. Not for auditing dependency-rule drift only (auditing-clean-architecture), a code-quality cleanup plan (desloppify), explaining a PR (review-map) or extracting requirements (distilling-requirements).
---

# Designing the smallest version

Turn what we know into the smallest design that meets the goal, plus the smallest path to build it. The bar is `~/.local/share/agent-harness/design-principles.md`: read it first and measure against it by section number. Do not copy or reword it.

Read-only against the repo and any live system. Write `DESIGN.md` (and `facts.json` if you ran the script) outside the repo: the path the user gives, else a scratch folder. Scratch clones and small scripts against an extracted copy are allowed when the caller bars builds and tests; name what you ran. Assume a private, local, one-owner setting; add no security or threat sections.

## Pick the mode

| | A. Redesign what exists | B. New capability |
|---|---|---|
| When | Code exists and the job is to give it a better shape | The thing does not exist yet; the input is the owner's words and what it plugs into |
| "What exists" is | The parts as found (Step 2A) | What we lean on: existing code, the integrated system's own features, the in-repo pattern to copy (Step 2B) |
| Problems are | Failures, ranked and reproduced | Gaps: a requirement with no home, ranked by consequence |

A redesign that adds a capability uses A for the part that exists and B for the new part, in one document. Steps 0, 1, 3, 5, 6 and 7 are shared.

## Inputs (all optional except the goal and the repo)

Use what exists; name in the output which you used.

| Input | Use |
|---|---|
| Owner's requirements, in their words | `given`, one `OR-n` row each (Step 3) |
| A `REQUIREMENTS.md` with header `shape: requirements/1` (distilling-requirements) | Replaces inference in Step 3; see below |
| Repo documents: `docs/PRD.md`, a component's `CONTRACT.md`, specs, ADRs, a `prd-candidate.md` | `given`, even when the caller says "bare" |
| Tested facts, probe notes, the integrated system's source, docs and live state | The facts a design rests on (Step 1) |
| Validation points, journeys, e2e tests | Behaviour without rediscovery from code |
| review-map pages | What recently moved and what it reaches |

A bare repo must still work: infer from README, `AGENTS.md`, manifests, entry points and tests, and label every such claim `inferred`.

Reading a `requirements/1` file: cite its ids, never re-mint them. Take requirements from `R-n` (ignore `incidental` rows when drawing boundaries), state machines from `SM-n` with their `writers:` lines, invariants from `I-n`, reachable defects from `F-n` and unenforced invariants from `U-n` (Step 4 failures), `fit` and `enforced` gaps as Step 6 proof gaps only where a decision depends on them, `Q-n` as candidates for Step 8. Check its `commit` against the pinned rev and its `not-read` against your scope. **It is an input, not a fact: re-check every item a ranked failure or decision rests on against the code** (it can be wrong, stale or encode the bug as a requirement) and record each refutation with its command in a Re-check table in Section 3. Findings you add get ids `DF-n`. Any other shape version: read it as free text and say so.

## Steps

**0. Frame.** Write the mode, the goal in one sentence, the scope, the inputs found, and any parts or names the caller uses. Check every named path, part and artifact against the pinned rev and report the ones that do not exist before designing. If the goal is "make it better" with no pull, get the one pain that matters (slow to change, hard to test, hard to reuse). Do not design without a pull (§4).

**1. Gather.** Pin the rev (`git rev-parse HEAD`; again at the end; if it moved, say so; the JSON's `head_start` and `head_end` are about `--rev`, not the live checkout). Extract what you will read once (`git archive REV PATHS | tar -x -C SCRATCH`) and read from there, unless the copy you were given is already a read-only checkout of the pin; in zsh write `${REV}:path`. Then:
- **Facts script.** `python3 <skill-dir>/scripts/repo_facts.py REPO --rev REV [--scope GLOB ...] [--parts parts.tsv] --out facts.json` does every count so you do not. `--scope` takes many globs and may repeat. Do not read the JSON whole: `--summary` lists the keys. It parses TypeScript/JavaScript and Python imports (tsconfig aliases and workspace names show as external packages), and reports sizes, `path_refs` between any files, co-change, `branches_touching_scope` (with `unmerged_patches`), `proof_commands`, `gates` (`gates_note` says when there is no architecture gate), `docs_found` and `globs_matched` (a zero shows a wrong glob). `plan_word_commits_touching_scope` lists only commits with a plan word in the subject. **Run it for mode A, and for mode B in a repo with real code. In a mostly YAML or script repo the facts a new capability rests on are outside the repo; use only `path_refs` and the branches there, and skip the rest (`proof_commands` is for proving a redesign).**
- **Read in this order:** a component's `CONTRACT.md`; the repo's architecture gate (it states the layout; if none, the gate is whatever proves a change); the parts of README and `AGENTS.md` that say how a change is proven here (commands and cost); manifests and entry points.
- **Work already in flight is prior art (§11).** Read what touches scope, settle each move's state with `git cherry REV BRANCH` and its review record, and adopt, extend or reject it with a reason. A design that ignores a half-finished move in the same repo is wrong. A history-clean copy has history but no branches; say so and look in the commits touching scope.
- **Systems the design leans on** (a controller, hub, database, CLI, shim): read their behaviour at the pinned version from source or docs, not from memory. List every claim only the live system can settle (start-up order, what a retry or resume does, what a race leaves behind, retention defaults, what a second reader does to a queue) under Section 8 as "unverified until run", with the experiment. This is the most decisive step in a new-capability design and the commonest way a good-looking design fails.

Write a ≤1-page orientation a cold agent could read instead of the repo.

**2A. Inventory the parts as found (mode A).** For a scope under about 5 files, one row per file plus its callers is enough; skip `--parts`. If the caller's parts are not units in the code, propose a glob-to-part table (`**` crosses `/`; `*` does not) as a hypothesis, run `--parts`, and revise until leftover cross-part edges are explained. For each part: its job in one sentence, public interface, what it depends on and what depends on it, what it changes with, and its kind: **component** (reusable, no sibling imports), **use-case folder** (behaviour over a shared component), **entry-point adapter** (CLI, server, UI) or, in a manifest repo, **composition root**, **deployable unit** or **overlay**. No import edges is not separation: in manifest and script repos coupling is by path strings; use `path_refs` and write the edges the script cannot see, labelled "found by reading". Record cycles, cross-component imports, cores that import adapters, and logic in an entry point.

**2B. List what we lean on (mode B).** A short table of what already exists and the design will use or copy: the integrated system's features (one row each: feature, source or test that shows it), the existing code or in-repo pattern to copy (and why that one), and what is absent, where the requirement has no home. Prior art for the whole capability goes here too: adopt, wrap, borrow or build, with the reason (§11).

**3. Requirements.** The owner's words are `given`: one `OR-n` row per requirement, quoting or tightly paraphrasing, with "enforced today?". Take ids from a `requirements/1` file or a repo document if present. Infer the rest from the journeys the entry points serve and the invariants the code or the integrated system relies on, marked `inferred` (`IR-n` requirements, `II-n` invariants; note which nothing enforces). Separate enduring obligations from incidental implementation. Where a component is a state machine in disguise and none is given, draw it as Mermaid `stateDiagram-v2`.

**4. Diagnose.** Name the 3–5 tensions that matter (§13): where requirements, simplicity, accuracy and reuse pull apart, and what each resolution costs. That is usually the most valuable part. Then:
- **A:** give each principle 1–15 a verdict with its **scope** (pass at module level, fail inside one module: write both) and evidence; rank failures by proven harm; **reproduce each** with a small script against the extracted pin (symlink `node_modules`; no installs; on Node 22.18+ a `.ts` or `.mjs` script runs and imports `.ts` directly) or a scratch clone, else label it `read only` and make the experiment the first increment. Check that each test double the proof relies on does what the real adapter does, and re-run the reproduction with the double the unit tests use.
- **B:** list gaps (a requirement with no home, a fact still unverified), ranked by consequence. Reproduce or cite the fact each rests on, else `read only`.
- Where the owner's goal is "separable" or "testable on its own", that is not reuse: use a contract-level test and an import fence, not a folder, unless a second user exists.

**5. Design the target.** The smallest design that meets the goal and the requirements:
- The kind of each part and its single job. A component needs a second real use (§1); without one it stays inside its neighbour or becomes a use-case folder.
- When the owner's goal asks for reuse and §1's test fails, do not pick a side silently. Define reuse as "folder with a public entry, a CLI if any, and a contract", record the tension, and list packaging as an owner decision with your recommendation.
- Kernel and adapters (§2), layers inside a component only where it is big enough (§3, §4). A large component that works and shows no harm is `fail (accepted)` by default.
- Ports, contracts, invariants and log records (§5, §14); a conformance suite per adapter (§6); one composition root (§7).
- Prior art for each part, including what the repo and the integrated system already do (§11). What stays as it is, and why.
- What each owner requirement costs in machinery, so the owner can trade (§13): say plainly when one requirement is most of the design.
Every new boundary, layer or abstraction needs a concrete requirement or a demonstrated failure; if it only reads well, cut it (§4). Before changing any key, name or format, count its literal uses. Before finalising, ask what can be deleted and still meet the requirements.

**6. Path.** Ordered increments, each shippable alone and proved from outside the way this repo proves changes (§12, §15). Say which can run in parallel and which must be serial, one line why. Start with the increment that removes the worst proven failure (A) or settles the biggest unverified claim (B). For a race, list the awaits with one grep and place the interleaving at every `await` window, not one; tie a record to the thing it was made for by an identity (a key or id), never by comparing timestamps written by different processes. Add build gates in the increment that creates the boundary, not before.

**7. Write `DESIGN.md`** in the shape below, then verify:
- every `fail` maps to a decision, or is `fail (accepted)` tied to a Section 7 item with the trigger that would reopen it;
- every decision maps to a requirement, failure or gap;
- nothing inferred is presented as given;
- **every number comes from a command you saw: cite the `facts.json` key or keep the command in Section 1's Evidence list; re-run at the end. Quote `lines` for one file and `code_lines` for sums, and say which.**

## Output shape (keep it stable; other tools read it)

```markdown
# Design: <scope>
Mode (A redesign | B new capability) · Goal · Scope · Names in the goal that do not exist in the repo · Rev (start / end) · Inputs used (given / inferred) · In-flight work relied on (and its state) · Top 3 decisions

## 1. Orientation            (≤1 page: what it is, entry points, size, how a change is proven, where to start; Evidence: the commands behind every number)
## 2. What exists            (A: parts table with kind, edge list, diagram, excluded trees. B: what we lean on, the pattern to copy, what is absent)
## 3. Requirements and invariants   (OR-n owner words; cited ids; IR-n / II-n inferred; enforced? yes/no/partial; Re-check table)
## 4. Tensions and problems  (tensions T1…; A: ranked failures F/DF-n with "reproduced by" or "read only"; B: gaps G1…; each with evidence and cost of leaving it)
## 5. Target design          (decisions D1…: what, why, requirement/failure/gap it answers, rejected alternative; diagram; what could be deleted and still meet the requirements)
## 6. Path                   (increments S1…: change, proof from outside, depends on, parallel?)
## 7. Not doing              (considered and cut, with the trigger that would reopen it; accepted fails live here)
## 8. Open for the owner     (two sub-lists: Decide — changed promised outcomes and unresolved product trade-offs, each with a recommendation; Run — claims "unverified until run", each with its experiment)
## 9. Principles table
| # | Principle | As found | Target | Evidence |
|---|---|---|---|---|
| 1 | Composable components | fail | pass | scope: …; key or decision id; read / sampled / untested |
… one row for each of 1 to 15; keep each Evidence cell to about 40 words and point to the Section 4 item …
```

Verdicts: `pass`, `fail`, `n/a`; Target may also say `fail (accepted)`. In mode B, write `new` once for the whole As found column unless a row has something real today (say what); an `n/a` row takes one sentence at most. Evidence says what you read and what you did not, and `untested` where the test needs a live run (§14's replay). **Target means after the last increment in Section 6.** The table is required; a design without it is not finished.

## How this differs from nearby skills

- `auditing-clean-architecture`: finds dependency-rule drift and emits prose findings only. This designs the target and the path; its bar is design-principles.md. Run the audit for a narrow architectural question; use its findings as input to Step 4.
- `desloppify`: a many-phase plan for code-quality decay. This works one altitude up (components, seams, contracts) and writes one document.
- `review-map`: explains one PR. Use its pages as input; this skill does not read diffs.
- `using-generate-prd` and `distilling-requirements`: they say what the product must do; this says how to build it. Their output is input here; this skill needs neither.
- `/statechart` (poteto, pstack): proves state-machine models with TLA+. Borrowed ideas only: treat the model as wrong until the code confirms it, label diagrams in the reader's words, declare what you left out.

## Done when

`DESIGN.md` exists, every section is filled or marked n/a with a reason, the principles table has 15 rows with evidence, and the first increment could start today without a further question. Report the file path, the three decisions that matter most, anything left for the owner, and which proofs you observed versus only planned (a design is not proof).
