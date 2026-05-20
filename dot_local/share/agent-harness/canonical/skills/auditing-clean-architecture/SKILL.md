---
name: auditing-clean-architecture
description: Use when a repository shows symptoms of clean / hexagonal / onion / ports-and-adapters / domain-driven architecture drift — business logic spread across UI / DB / transport, framework types leaking into domain code, mock-heavy tests of internal modules, anemic domain model, primitive obsession, missing anti-corruption layer, dependency-inversion violations, humble-object failures, features touching every layer in lockstep, or contested top-level layout (screaming-architecture vs framework-organized).
---

# Auditing Clean Architecture

## Overview

This skill audits the **architectural family** — hexagonal (Cockburn), onion (Palermo), clean (Martin), DDD-layered — not the Uncle Bob brand specifically. They share one rule: **dependencies point inward**. Layer count, ring count, and naming are projections of that rule, not the rule itself. **Layer count is contingent; the dependency rule is the invariant.**

**The single tenet:** an inner core defines abstractions; outer adapters implement them. Source dependencies cross boundaries inward only. Everything else in this skill is a corollary.

**Output is prose findings only.** Every mode — audit, analyze, refactor-plan, bootstrap — emits a markdown findings document. **No mode produces files, diffs, edits, executable steps, ASCII directory trees, or any fenced code.** Hand findings to a downstream spec-driven framework; that framework decides whether to materialise anything.

**Inputs to the audit are not constrained.** Running deterministic validators — dep-graph analyzers, AST scanners, arch-test tools (ArchUnit, dependency-cruiser, Deptrac, import-linter, etc.) — to inform findings is **permitted and preferred** where they fit the stack. Tool output is *evidence*; the findings document remains prose. The prose-only contract governs what the skill *emits*, not how the skill *thinks*.

### Contract (state once)

Four parts, non-negotiable:

1. **Inputs unconstrained.** Read source, run installed analyzers, ripgrep import graphs — whatever informs the finding.
2. **Outputs prose.** Single markdown document; no diffs, no fenced code, no executable artifacts.
3. **No installation.** Never install, upgrade, or download tooling as part of the audit. Recommend in Cross-cutting Observations; do not act.
4. **No config modification.** Never edit analyzer config, lint rules, build manifests, or any repository file. The audit is read-only against the working tree.

## When to Use

- Repo has business logic scattered across UI, DB, transport
- Adding a feature touches many layers in lockstep
- Tests dominated by mocks of internal modules
- Same validation / parse / cache-key in multiple places
- Framework types (ORM rows, HTTP requests, framework decorators) appear in domain code
- Domain types are mostly `string` / `int` (anemic domain model / primitive obsession)
- Team is asking which way to organize the top-level tree (by feature vs by technical role)
- User explicitly wants an architectural review, refactor plan, or new-repo layer skeleton

### Do NOT use

- For single-purpose scripts, intentionally thin CRUD wrappers, code-gen output, or libraries whose technical role *is* the domain
- When the user wants execution rather than findings
- When mid-implementation and the user wants the change shipped, not audited

Always run **Repo Shape Check** (Step 0 of [workflow.md](workflow.md)) before continuing — bail honestly if the repo doesn't benefit from layering.

## Out of Scope

This skill audits **architecture only**. The following are general code-quality concerns; reach for other skills (e.g. `desloppify`):

- DRY / duplication within a layer
- Self-documenting code, comment hygiene, naming
- No-fallback-by-default error handling philosophy
- Lint, formatting, dead code

Findings unrelated to the dependency rule or its corollaries belong in those skills' outputs.

## Quick Reference

### Modes (pick one)

| Mode | Trigger language | Extra output sections |
|------|------------------|-----------------------|
| audit | "review / audit / check this repo" | — |
| analyze | "where does X belong?", "is this a violation?" | — |
| refactor-plan | "make this clean", "plan the refactor" | Remediation Plan |
| bootstrap | "set up new repo", "skeleton for X" | Bootstrap Skeleton (**prose path list only** — no ASCII trees, no fenced code, no commands) |

If multiple modes plausibly fit the user's request, **confirm with the user before emitting**. Wrong-mode output silently omits sections the user wanted.

### Severity rubric

| Severity | Definition |
|----------|-----------|
| blocker | Inner-from-outer import; framework type in domain; build-passes-but-rule-broken. |
| major | Logic in wrong layer with no shielding; missing translation at boundary; outer concrete leaks via signature. |
| minor | Discipline drift (over-abstraction, anemic Core, single-use DTO sharing) — works, but signals erosion. |
| informational | Trade-off finding emitted **only when team preference is explicitly known** and the trade-off is being surfaced for the record (e.g. "team values feature-folders; this layout is consistent with that"). Default for an unknown-preference trade-off is **omission**, not informational. |

Severity is required on every finding. `informational` is **not** a default-emit and **not** a dumping ground for hard-to-decide findings — if you can't decide between minor and informational, treat that uncertainty as evidence to omit the finding entirely and record "considered but omitted" in Cross-cutting Observations.

### Trade-off notes vs merit gates (two tiers)

- **Merit gate (full flowchart):** C15, C21, C22 only. Layout / outer-fattening findings. Default outcome: skip or downgrade unless team preference is explicit. See `corollaries.md`.
- **Trade-off note:** C8, C9, C12, C19, C20. Inline note in the corollary entry calibrates severity to language / domain / context.
- **Hard rules (no soft gate):** all other corollaries. Absence of a trade-off note means **no legitimate exception in scope** — do not invent softeners to downgrade a finding.

### Vocabulary glossary

Skill uses **neutral** terms internally. Map to the audited project's vocabulary in findings.

| Hexagonal | Onion | Clean (Uncle Bob) | DDD-layered | This skill (neutral) |
|-----------|-------|-------------------|-------------|----------------------|
| Hexagon / domain | Domain model | Entities + Use Cases | Domain + Application | **Inner core** |
| Driving port / driven port | Application service interfaces | Use case interactors | Application service interfaces | **Inner ports** (interfaces *defined* by inner core) |
| Driven adapter | Infrastructure | Interface adapters (gateways) | Infrastructure | **Outbound adapters** (impls of inner ports) |
| Driving adapter | Infrastructure | Interface adapters (controllers) | Application controllers | **Inbound adapters** (transport, FFI, RPC, message bus) |
| (frameworks layer) | (frameworks) | Frameworks & Drivers | UI / Presentation | **Delivery** (UI / CLI / API surface) |

For one concrete worked example showing how these terms land in a real Rust+Flutter repo, see [exemplar-oxide.md](exemplar-oxide.md). Treat the exemplar as illustration, not authority.

## The Tenet — Corollaries Index

Full corollary catalog with smells, trade-off notes, tier tags, and the merit-gate flowchart: [corollaries.md](corollaries.md). Indexed by ID for stable downstream reference.

**C-IDs are an open catalog maintained by skill update.** Stable handles — never renumbered, never invented in a finding. If a finding doesn't map to an existing `Cn`, file it under Cross-cutting Observations and request a skill update; do not coin `C23+` ad-hoc.

### Detection tiers

Every corollary is tagged with one of three tiers. Tier governs **how the corollary is checked**, not the output format (findings remain prose regardless).

| Tier | Meaning | Workflow expectation |
|------|---------|----------------------|
| **D** deterministic | Provable by import-graph / AST rules. Analyzer output is ground truth. | Run an analyzer if installed (see workflow Step 1.5). If none installed, fall back to ripgrep / manual scan and recommend the stack-appropriate tool in Cross-cutting Observations. |
| **H** heuristic | Threshold-driven pattern. Analyzers can express it with calibrated thresholds; LLM can spot the smell. | Tier-D analyzer output may surface candidates; final calibration is auditor's. Surface threshold choice in finding evidence. |
| **J** judgmental | Requires reasoning about intent / context. No tool decides. | Auditor reads source. Prose evidence carries the finding. |

| Theme | Corollaries (tier in brackets) |
|-------|--------------------------------|
| Direction | C1 dependency-inversion **[D]** · C2 acyclic-dependencies **[D]** |
| Boundaries | C3 boundary-data-is-plain **[D]** · C4 plain-domain-objects **[D]** · C5 anti-corruption-layer **[D]** · C6 errors-translate-at-boundaries **[H]** · C7 use-case-return-value-leak **[H]** · C8 boundary-types-per-use-case-not-shared **[H]** |
| Inner | C9 use-case-application-service-split **[J]** · C10 healthy-feature-flow **[J]** · C11 policy-lives-in-the-inner-core **[J]** · C12 primitive-obsession-at-domain-layer **[H]** |
| Outer | C13 delivery-is-thin **[J]** · C14 humble-object-at-boundaries **[J]** · C15 outer-layer-fattening **[H]** *(merit-gated)* |
| Wiring | C16 composition-root **[D]** · C17 build-system-enforcement **[D]** |
| Testability | C18 independence-axes **[J]** · C19 integration-tests-as-seam-checks **[H]** |
| Discipline | C20 over-abstraction **[H]** |
| Layout | C21 screaming-architecture **[J]** *(merit-gated)* · C22 layer-≠-folder **[J]** *(merit-gated)* |

### Deterministic-validator ladder by stack

When a tier-D analyzer is configured in the repo, consume its output as ground truth. When none is configured, recommend the stack-appropriate one in Cross-cutting Observations.

| Stack | Primary tool | CLI? |
|-------|--------------|------|
| JVM (Java/Kotlin/Scala) | ArchUnit | No (JUnit-embedded) |
| Kotlin (modern) | Konsist | No (JUnit-embedded) |
| .NET (C#/F#) | ArchUnitNET / NetArchTest | No (test-embedded) |
| TypeScript / JavaScript | **dependency-cruiser** | Yes |
| TypeScript (typed) | ts-arch | Yes (ts-morph-based) |
| PHP | Deptrac | Yes |
| Python | import-linter | Yes |
| Go | go-arch-lint | Yes |
| Ruby | packwerk | Yes |
| Rust | cargo-modules, crate visibility, workspace deps | Partial (no full equivalent) |
| Fallback (any stack) | ripgrep over hand-crafted import patterns | Yes |

**ts-arch correction:** ts-arch is built on **ts-morph** (TypeScript AST), not on dependency-cruiser. Use ts-arch when team prefers fluent ArchUnit-style rules in TypeScript; use dependency-cruiser when team prefers config-driven layer rules with JSON/SVG output.

**Probe order (canonical filenames):**

1. Analyzer config files: `.dependency-cruiser.js` / `.dependency-cruiser.cjs` / `.dependency-cruiser.json` / `dependency-cruiser.config.js`; `deptrac.yaml` / `deptrac.toml`; `importlinter.cfg` / `.importlinter` / `setup.cfg` (`[importlinter]` section) / `pyproject.toml` (`[tool.importlinter]`); `packwerk.yml`; `go-arch-lint.yml`; `*ArchTest.kt` / `*ArchTest.java` / `archunit.properties` (optional — ArchUnit works without it).
2. Build-manifest dependency declarations: `package.json`, `composer.json`, `requirements*.txt`, `pyproject.toml`, `Gemfile`, `pom.xml`, `build.gradle` / `build.gradle.kts`, `go.mod`.
3. CI invocations of any of the above.

If the tool is **declared in a manifest but not present in the local environment**, treat as not-installed: fall back to ripgrep and recommend in Cross-cutting Observations. `npm install` / `pip install` / etc. is installation and forbidden by the contract.

## Workflow & Output

- **How to run an audit:** [workflow.md](workflow.md) — 12 steps with Step 0 Repo Shape Check
- **Findings document schema:** [output-format.md](output-format.md) — section contract + worked finding example
- **Worked exemplar (one repo's concrete instantiation):** [exemplar-oxide.md](exemplar-oxide.md)

## Common Mistakes

### When applying this skill

| Excuse | Reality |
|--------|---------|
| "Found a one-line fix while reading, just merging it" | Findings doc only. Drift starts here. |
| "I'll attach a diff to the suggested fix" | Prose sentence only. No diffs, no fenced code, no inline backtick-quoted code beyond a single identifier. |
| "I'll include an ASCII directory tree in the bootstrap section — it's a skeleton, not a fix" | No fenced blocks anywhere. Bootstrap describes layout in prose path list ("inner core lives at `src/domain/`; outbound adapters at `src/infrastructure/`"). |
| "Bundling related issues into one finding is cleaner" | One violation per `Fn`. Downstream needs granularity. |
| "Severity is subjective, I'll mark it informational" | `informational` is for trade-offs, not indecision. Decide, or omit. |
| "This finding doesn't fit any C-ID, I'll add C23" | C-IDs are closed to ad-hoc invention. File under Cross-cutting Observations and request a skill update. |
| "The corollary doesn't list a trade-off, but I think this case is special" | Absence of a trade-off note means no legitimate exception. Don't invent softeners. |
| "Mode could be audit or refactor-plan, I'll just pick one" | Confirm with user. Wrong mode silently drops sections. |
| "Layout looks framework-y, definitely a violation" | Apply merit gate. C21 / C22 are informational by default; **omit entirely** when team preference is unknown — don't pile up informational findings nobody reads. |
| "Outer layer is fat → anemic inner" | Apply C15 merit gate. UI-heavy domains (media, CAD, IDE) legitimately fatten outer layers. |
| "Project doesn't use clean/hexagonal vocabulary, skill doesn't apply" | Skill applies anyway. The dependency rule is structural, not nominal. Map the project's own terms via the glossary. |
| "The README / CLAUDE.md already describes the architecture, trust it" | Audit the imports, not the self-description. Architecture docs lag reality. |
| "Step 0 says no audit needed — easy out" | Bail must be honest. Justify the no-op in writing. If you can't, run the audit. |
| "Step 0 fails but I'll audit anyway just to be thorough" | Inverse loophole. If Step 0 says bail, bail. The audit is noise on the wrong shape. |
| "Mode is obvious from the prompt, skip the header field" | Downstream tools parse the header, not your inference. Always declare. |
| "Audit found nothing — emit a one-line all-clear" | Empty audit still uses the full schema; empty Findings section is parsable. |
| "Filing a C15 / C21 / C22 finding without running the merit gate" | Always state which gate filtered (or that none did and the finding was promoted). |
| "Skipping a layout finding without naming the gate that filtered it" | Same contract in reverse. Record the gate that skipped, so the audit is reproducible. |
| "Reordering output sections improves readability" | Sections are a contract. |
| "DRY duplication counts as architecture" | Out of scope. Refer to general code-quality skill. |
| "Oxide-exemplar pattern is the right answer" | Exemplar illustrates; doesn't prescribe. Cite the corollary, not the exemplar. |
| "I'll eyeball the import graph instead of running the analyzer" | For tier-D corollaries (C1, C2, C3, C4, C5, C16, C17), an installed analyzer is ground truth. Eyeballing introduces error the analyzer would not. Run it. |
| "No analyzer is installed, so I can't audit tier-D corollaries" | Fall back to ripgrep over hand-crafted import patterns. Imperfect but strictly better than skipping. Recommend the stack-appropriate analyzer in Cross-cutting Observations. |
| "Analyzer says no violation, so there's no violation" | Analyzers are ground truth for tier D *only*. Tier H findings need calibrated thresholds; tier J needs the auditor's reasoning. "Clean per analyzer" is not "clean per audit." |
| "I'll install dependency-cruiser to run the audit" | Probe for existing config. Do not install tooling as part of an audit — recommend installation in Cross-cutting Observations and proceed with fallback. |
| "Tier classification is implicit, no need to record detection method" | Record the **Detected by** field on every finding. Downstream tools weight tier-D findings differently from tier-J findings. |
| "Analyzer is installed and passing — tier-D corollaries are clean" | Verify the analyzer's **configured rules cover the corollary** before treating its silence as truth. A dep-cruiser config with only `no-circular` configured says nothing about C1; uncovered tier-D corollaries fall back to ripgrep + Cross-cutting recommendation. |
| "Tier-D analyzer ran clean, I can skip tier-H/J scans" | Tier-D pass does not reduce tier-H/J obligation. Run Steps 4–11 in full regardless of analyzer outcome. |
| "Threshold for the tier-H finding is whatever I pick" | Threshold requires a **stated rationale** (language norm, codebase scale, prior-art citation) recorded in the finding evidence. Picking a threshold to produce zero findings is the loophole; defending the threshold is the rule. |
| "Tier-J is judgmental, so prose suffices without locations" | Tier-J means interpretation is judgmental — *evidence is not optional*. Every tier-J finding still requires **Locations** and a quoted evidence excerpt. |
| "Tool is declared in `package.json` / `pom.xml` but not installed locally — I'll just `npm install` to run it" | Installation changes the environment and is forbidden by the contract. Declared-but-not-present = not installed; fall back to ripgrep and recommend the team materialise the tool. |

### When auditing — rationalizations the codebase author offers

| Excuse | Reality |
|--------|---------|
| "Just one helper, easier in the UI" | Helpers compound. Next contributor follows precedent. |
| "Inner can import this enum from the provider, it's just data" | Once inner imports outward, the rule is dead. Move it inward. |
| "This interface belongs with its implementation" | Interface is a contract owned by the consumer — the inner core. |
| "We mock the inner core in tests because it's faster" | Mock-heavy suites lie about what the inner core depends on. |
| "Adding a layer is overengineering" | Maybe. Run the Repo Shape Check honestly. If layering fits, the cost is real but pays back. |
| "It's idiomatic in this language/framework" | Idiom ≠ architecture. Cite the corollary. |
| "Violating the letter still satisfies the spirit" | Violating the letter is violating the spirit. |
| "We'll fix it in the next PR" | File a finding. "Next PR" means never. |

## Red Flags — STOP and re-audit

- Justifying why an inner module imports from an outbound adapter
- A `util` / `helper` / `common` / `shared` module everyone imports from, including inner
- Tests mocking the thing under test
- One feature touching every layer because each holds a fragment of one rule
- Composition wiring scattered across inner modules
- Build allows the dependency-rule violation to compile and ship
- Suggested fix wants to become a diff, an ASCII tree, or any fenced code block
- Filing C15 / C21 / C22 findings without running the merit gate (or skipping one without naming which gate filtered)
- Bailing at Step 0 without a written, defensible justification
- Auditing despite a clean Step 0 fail (inverse loophole — proceed-anyway is also a violation)
- Marking findings `informational` because severity is hard to call (severity is not a dumping ground)
- Inventing a new `Cn` ID for a finding that doesn't fit existing corollaries
- Softening a finding by inventing a trade-off the corollary doesn't list
- Mode left blank or inferred-implicitly in the header
- Citing the worked exemplar as canon instead of citing the corollary
- Skipping an installed tier-D analyzer in favour of LLM eyeballing
- Installing new tooling during an audit (recommend, do not install)
- Treating clean analyzer output as a green-light for tier-H or tier-J corollaries
- Treating analyzer silence on an uncovered tier-D corollary as ground truth (verify the analyzer's config covers each tier-D rule)
- Picking a tier-H threshold to engineer findings to zero (threshold requires stated rationale)
- Emitting a tier-J finding without **Locations** and a quoted evidence excerpt
- Materialising a declared-but-not-installed tool by running its package manager

## Checklist

- [ ] Mode declared explicitly in header (not inferred); confirmed with user if ambiguous
- [ ] Repo Shape Check section present, honest, and justified if bailing (or proceeding past a near-bail)
- [ ] Date filled with actual ISO date (no placeholder)
- [ ] Project vocabulary noted; glossary applied; skill uses neutral terms internally
- [ ] Layer map covers every top-level module
- [ ] Each finding cites an **existing** corollary ID + locations + evidence + one prose-sentence fix + severity
- [ ] Merit-gated findings (C15, C21, C22) ran the merit gate and recorded the outcome (filtered, promoted, or omitted)
- [ ] No invented `Cn` IDs; unmappable observations live in Cross-cutting
- [ ] No invented trade-offs softening findings without a corollary trade-off note
- [ ] One violation per `Fn`
- [ ] Cross-cutting section identifies systemic issues
- [ ] Remediation plan iff refactor-plan mode (prose only)
- [ ] Bootstrap skeleton iff bootstrap mode (prose path list only — no ASCII trees, no fenced code)
- [ ] Out-of-scope section names what was deferred and to which skill
- [ ] Single markdown document, no source edits, no diffs, no fenced code in fixes
- [ ] Tier-D analyzer probed (`Step 1.5` in workflow); if installed, its output consumed as ground truth; if not, stack-appropriate tool recommended in Cross-cutting Observations
- [ ] Every finding records **Detected by** (analyzer name / heuristic / auditor judgment)
