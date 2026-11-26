# Checks per section

Where to look for evidence on each section of `design-principles.md`. Section numbers are as of the file this was written against; if the file has moved a rule, follow the file and note the drift. These are ways to find evidence, not extra rules: a finding cites the section and quotes its sentence.

## Contents
- [§1 Composable components](#1-composable-components)
- [§2 Kernel and adapters](#2-kernel-and-adapters)
- [§3 Clean architecture inside each component](#3-clean-architecture-inside-each-component)
- [§4 YAGNI and KISS](#4-yagni-and-kiss)
- [§5 Written contracts and invariants](#5-written-contracts-and-invariants) · [§6 Conformance suites](#6-conformance-suites) · [§7 No cross-component imports](#7-no-cross-component-imports)
- [§8 Judgment in agents](#8-judgment-in-agents-mechanism-in-code) · [§9 Fix the cause](#9-fix-the-cause-no-arbitrary-caps) · [§10 Good enough](#10-good-enough-for-personal-software) · [§11 Prior art](#11-prior-art-before-building)
- [§12 Verified from the outside](#12-verified-from-the-outside) · [§13 Intent tensions](#13-resolve-intent-tensions) · [§14 Logs](#14-logs) · [§15 Fast proof](#15-fast-proof) · [§16 Built to last](#16-built-to-last)
- [Analyzer ladder](#analyzer-ladder)

## 1. Composable components
For each component, name a second real use outside the project that made it. A component that only makes sense inside one feature is a boundary drawn around a feature. Look for use-specific words (one product, one budget, one agent setup) inside a component instead of in the composition.

## 2. Kernel and adapters
- Does the core import a runtime, transport or adapter (an HTTP framework, a chat SDK, the Pi API, a CLI parser)? Facts-script edges or `rg` on the core's import lines.
- Can the core be used alone as a library plus a CLI? Find its public entry and its CLI, or note their absence.
- Gate: is there a dependency check in CI that would fail on such an import? The file scopes the Gate to new components and boundaries; on an old component a missing gate is a note.

## 3. Clean architecture inside each component
Judge layers by import direction, not folder names. Scale to the component (§3 says so, and §4 applies): a small component with a few files per layer, or none split at all, can pass.

Checks, with the old catalog id kept as a label:
- **Direction (C1).** No inner file imports an outer one. Ports (interfaces) are defined by the inner code that uses them, not beside their single implementation in an adapter.
- **No cycles (C2).** The facts script and most analyzers report cycles; `rg` cannot.
- **Plain data across boundaries (C3, C4, C5).** No ORM rows, HTTP requests, framework handles, serialization annotations or third-party model types in domain or use-case code. A third-party model is translated at its adapter.
- **Own types for meaningful values (C12).** Ids, amounts and similar values are types, parsed from outside data at the boundary, derived from the schema that owns the data. Look for domain signatures full of bare strings and ints that mean different things. Calibrate to the language: cheap newtypes (Rust, Kotlin, TypeScript branded types) raise the bar.
- **Errors translate at boundaries (C6).** Framework exceptions do not reach the domain; domain errors do not reach callers raw.
- **Use cases own outcomes (C7).** A handler that branches on a use case's result to make a business decision means the decision leaked out.
- **Domain and use cases split (C9)** where the component is big enough that the split pays; in a small component its absence passes.
- **Policy lives inward (C11).** Retention, retry, validation, naming and cache rules are decided in the domain or use cases; adapters carry them out.
- **Thin delivery, humble shells (C13, C14).** Views, handlers, FFI and lifecycle hooks capture input and render; they do not decide. A large outer layer (C15) is only a lead: sample it, and flag decisions, not rendering or glue. UI-heavy products legitimately have big outer layers.
- **One composition root (C16).** Concrete adapters are built once, at the edge, not inside domain code.
- **Swap test (C18).** For each adapter, write the sentence "to replace X with Y I would change …". A swap that touches domain code is a leak.
- **Testable without real I/O.** Domain and use cases run in tests with in-memory fakes of their ports. Tests that mock the domain itself point at the wrong dependency (also §12).
- **Shared boundary types (C8)** are a note at most: flag a write-side DTO shared by several use cases only when field changes have actually cascaded.
- **Healthy feature flow (C10).** Sample recent features in `git log`: one that had to change outer layers first suggests a missing inner abstraction.
- Gate: as in §2.

## 4. YAGNI and KISS
- Interfaces with one implementation, no test double and no written reason (C20).
- Config keys nobody sets to anything but the default; flags with one value; layers that only forward calls; plugins with one plugin.
- Code, scripts or files nothing calls (`rg` for the name; the facts script's `path_refs`).
- Count operator burden too: services to run, recovery paths, harnesses.
Every item goes to "Removable machinery" with its evidence.

## 5. Written contracts and invariants
For each core, find a contract: schema, operations, invariants it guarantees, and the log records it emits, versioned with the code. Check one stated invariant against the code that should enforce it.

## 6. Conformance suites
For each port with adapters, find a suite every adapter runs, and whether CI runs it. A contract with no suite is unfinished.

## 7. No cross-component imports
Facts script with `--parts` (edges between parts), an analyzer, or `rg` for one component's package name inside another. Components meet only in the composition package. Cycles between components always count. Gate scope as in §2.

## 8. Judgment in agents, mechanism in code
- Keyword lists, regexes or score thresholds that classify meaning (intent, sentiment, "is this a question", priority) in code. That judgment belongs with an agent given the information and a tool.
- The reverse: an LLM called for deterministic work (formatting, parsing a known shape, a fixed transform), or recurring judgment left as an ad-hoc prompt rather than a skill.

## 9. Fix the cause; no arbitrary caps
`rg -n -i 'max_?(retries|attempts|items|len)|limit|cap|threshold|budget|throttle|debounce|sleep'` and read each hit: does it reflect a real external limit (an API's documented size or rate), or does it hide wrong behaviour? Also look for stacked guards (try/except around try/except, the same check in three layers) where one visible failure would be easier to fix.

## 10. Good enough for personal software
- Both bars: committed secrets. Use `gitleaks` or `trufflehog` if installed; else `rg` for key-shaped strings, `.env` files and private keys in the tree and in `git log -p` for the scope. A real secret is blocking at either bar.
- At `personal`: do not raise hardening, scale or hostile-operator findings that do not fail in ordinary single-user use.
- At `shared`: the repo's own rules, CI and conventions bind; a shortcut defended only by "good enough" is a finding.

## 11. Prior art before building
Look for a recorded adopt / wrap / borrow / build decision for each component (design docs, ADRs, README). Look for a component that rebuilds something a dependency or the integrated system already does (its history, undo, jobs, records). With no record, the verdict is usually `unknown`.

## 12. Verified from the outside
- Is there a test or journey that drives the real entry point (the CLI, the page, the public API) to a finished outcome? Run it if it is cheap and safe.
- Sample 3–5 tests and apply the two imagined edits from §12: break the behaviour (would it fail?) and change only internals (would it still pass?). Report tests that fail either.
- Mock counts per test file targeting the code's own modules (C19). State the threshold and why.
- External systems in tests should be dummies or scripted backends, unless the test is about that system.

## 13. Resolve intent tensions
Look for a record of owner-required guarantees versus agent-chosen mechanisms (design docs, PRDs, decision logs). Check one owner guarantee against what is built. Usually `unknown` from the repo alone; say what record would settle it.

## 14. Logs
- List the user actions in scope (commands, flags, refusals, pages, jobs, hook steps; the facts script's `surfaces` lists many).
- For each sampled action, find the line that writes a record that outlives the terminal. Screen output, stderr and exit codes do not count.
- Check the record: one structured line, a named action and outcome, one id tying the action's records together, UTC time, duration.
- If safe, run one action and read the record back: can you replay it, place a seeded fault and count uses and failures? Never log secrets.
- The file says do not retrofit untouched components: missing logs on code nobody is changing are "when next touched:" notes.

## 15. Fast proof
Run the suite and record its wall time. `rg -n 'sleep\(|time\.sleep|setTimeout|Thread\.sleep'` in tests: a fixed wait where a fact could be awaited is a finding. Note serial tests that could run in parallel, a fixture rebuilt per test, and whether one test per command starts it for real.

## 16. Built to last
Duplicated logic across files, workarounds, special cases bolted on, "TODO: clean up later", unused code left behind, structure that no longer fits. On code no change is touching, these are "when next touched:" notes. Local style and naming belong to desloppify.

## Analyzer ladder
Use one only if it is already installed and configured; check its config covers the rule before you treat its silence as a pass. If none exists, recommend the one for the stack in a finding.

| Stack | Tool |
|---|---|
| TypeScript / JavaScript | dependency-cruiser; ts-arch (ts-morph based) |
| Python | import-linter |
| JVM | ArchUnit; Konsist for Kotlin |
| .NET | ArchUnitNET / NetArchTest |
| Go | go-arch-lint |
| PHP | Deptrac |
| Ruby | packwerk |
| Rust | workspace crate boundaries and `pub` visibility; cargo-modules |
| Any | `rg` over import lines (no cycle detection) |

Config files to probe: `.dependency-cruiser.*`, `importlinter.cfg`, `.importlinter`, `[tool.importlinter]` in `pyproject.toml`, `deptrac.yaml`, `packwerk.yml`, `go-arch-lint.yml`, `*ArchTest.kt` / `*ArchTest.java`, and their calls in CI. A tool declared in a manifest but not installed counts as not installed.
