# Checks per section

Where to look for evidence on each section of `design-principles.md`. These are ways to find evidence, not extra rules: a finding cites the file's section and quotes its sentence. Section numbers are as of writing; if the file has moved a rule, follow the file. For a section not listed here, take the evidence to look for from that section's own text (its Test or Gate line when it has one).

## Contents
- [§1](#1-composable-components) · [§2](#2-kernel-and-adapters) · [§3](#3-clean-architecture-inside-each-component) · [§4](#4-yagni-and-kiss) · [§5](#5-written-contracts-and-invariants) · [§6](#6-conformance-suites) · [§7](#7-no-cross-component-imports) · [§8](#8-judgment-in-agents-mechanism-in-code)
- [§9](#9-fix-the-cause) · [§10](#10-good-enough-for-personal-software) · [§11](#11-prior-art-before-building) · [§12](#12-verified-from-the-outside) · [§13](#13-resolve-intent-tensions) · [§14](#14-logs) · [§15](#15-fast-proof) · [§16](#16-built-to-last)
- [Analyzer ladder](#analyzer-ladder)

## 1. Composable components
Apply the section's own Test to each component. Look for use-specific words (one product, one budget, one agent setup) inside a component instead of in the composition.

## 2. Kernel and adapters
- Does a core import a runtime, transport or adapter (an HTTP framework, a chat SDK, the Pi API, a CLI parser)? Facts-script edges, `external_packages`, an analyzer, or `rg` on the core's import lines.
- Find each core's public entry and its CLI, or note their absence.
- Gate: find the dependency check in CI that would fail on such an import. The Enforcement section scopes Gates to new components and boundaries; on an old component a missing Gate is a "when next touched:" note.

## 3. Clean architecture inside each component
Judge layers by import direction, not folder names, and scale to the component, as §3 says.
- **Direction.** No inner file imports an outer one. Ports (interfaces) are defined by the inner code that uses them, not beside their single implementation in an adapter.
- **No cycles.** The facts script and most analyzers report cycles; `rg` cannot.
- **Shared grab-bags.** A `util`, `common` or `shared` module that inner and outer code both import often carries outer dependencies inward.
- **Plain data across boundaries.** ORM rows, HTTP requests, framework handles, serialization annotations or third-party model types in domain or use-case code. A third-party model should be translated at its adapter.
- **Own types for meaningful values.** Domain signatures full of bare strings and ints that mean different things; outside data used raw inside instead of parsed at the boundary.
- **Errors at boundaries.** Framework exceptions reaching the domain; domain errors reaching callers raw.
- **Decisions in delivery.** A handler or view that branches on business state or on a use case's result to make a business decision. A large outer layer is only a lead: sample it and flag decisions, not rendering or glue; UI-heavy products legitimately have big outer layers.
- **Humble shells.** Code that is hard to test (views, DB drivers, FFI handles, framework lifecycle hooks) only wires and renders; any decision in it belongs in a testable inner object.
- **Shared boundary types.** A write-side DTO shared by several use cases couples them. A note at most, and only when field changes have actually cascaded; read-side sharing is routine.
- **Policy in adapters.** Retention, retry, validation, naming or cache rules decided in adapter code.
- **Domain and use cases split** where the component is big enough that the split pays.
- **Composition root.** Concrete adapters built inside domain code instead of once at the edge.
- **Swap test.** For each adapter, write "to replace X with Y I would change …". A swap that touches domain code is a leak.
- **Testable without real I/O.** Domain and use cases tested with in-memory fakes of their ports. Tests that mock the domain itself point at the wrong dependency (also §12).
- **Feature flow.** If history allows, sample recent features in `git log`: one that had to change outer layers first suggests a missing inner abstraction.
- Gate: as in §2.

## 4. YAGNI and KISS
- Interfaces with one implementation, no test double and no written reason.
- Config keys never set to anything but the default; flags with one value; layers that only forward calls; plugin systems with one plugin.
- Unused code: an installed dead-code tool (ruff or vulture for Python, knip or ts-prune for TypeScript), else a short AST script or `rg` for each candidate name.
- Operator burden: services to run, recovery paths, harnesses.
Each item goes to "Removable machinery" with its evidence.

## 5. Written contracts and invariants
For each core, find its contract and compare it with the section's list of what a contract holds. Check one stated invariant against the code that should enforce it, and the contract's log records against what the code emits.

## 6. Conformance suites
For each port with adapters, find the suite every adapter runs and whether CI runs it.

## 7. No cross-component imports
Facts script with `--parts` plus `external_packages` (components often import each other by package name), an analyzer, or `rg` for one component's package name inside another. Gate scope as in §2.

## 8. Judgment in agents, mechanism in code
- Keyword lists, regexes or score thresholds in code that classify meaning (intent, sentiment, priority, "is this a question").
- The reverse: an LLM called for deterministic work, or recurring judgment left as an ad-hoc prompt rather than a skill.

## 9. Fix the cause
`rg -n -i -w 'max_retries|max_attempts|retries|limit|cap|threshold|budget|throttle|debounce|sleep|timeout'` and read each hit: does it reflect a real external limit (a documented API size or rate), or hide wrong behaviour? Also look for stacked guards (the same check in several layers) where one visible failure would be easier to fix.

## 10. Good enough for personal software
- Secrets, at both bars: `gitleaks` or `trufflehog` if installed; else `rg` for key-shaped strings, `.env` files and private keys in the tree and in `git log -p HEAD` for the scope. Also secrets the code writes into the working tree at a path `.gitignore` does not cover. Cite `file:line`, never the value.
- At `personal`: raise no hardening, scale or hostile-operator finding that does not fail in ordinary single-user use.
- At `shared`: the repo's own rules, CI and conventions bind; a shortcut defended only by "good enough" is a finding.

## 11. Prior art before building
Look for a recorded adopt / wrap / borrow / build decision per component (design docs, ADRs, README). With none in the repo the verdict is `unknown`. A component that rebuilds what a dependency or the integrated system already does (its history, undo, jobs, records) is `fail` with evidence.

## 12. Verified from the outside
- Find a test or journey that drives the real entry point (the CLI, the page, the public API) to a finished outcome. Run it in the scratch worktree.
- Sample 3–5 tests and apply the section's two imagined edits. Report tests that fail either.
- Count mocks or monkeypatches of the repo's own modules per test file; state the threshold and why.
- External systems in tests should be dummies or scripted backends unless the test is about that system.

## 13. Resolve intent tensions
Look for a record of owner-required guarantees versus agent-chosen mechanisms (design docs, PRDs, decision logs). Check one owner guarantee against what is built. Usually `unknown` from the repo alone; say what record would settle it.

## 14. Logs
- List the user actions in scope, including refusals and errors (bad arguments, bad input): the facts script's `surfaces` lists many.
- Run each sampled action with `~/.local/share/agent-harness/bin/log-probe -- <command>` (`--help` explains seeding a config, watching a folder outside HOME and `--expect` for one path's line). It exits 1 when nothing was written as a JSON line. Do not decide "is there a record" by reading code alone.
- Check the records against the section's list of what a record carries, and its Test (replay one action, place a fault, count uses and failures). Never log secrets.

## 15. Fast proof
Run the suite and record its wall time; if it cannot run, the verdict is `unknown` with the reason, plus a timing of one real command. `rg -n 'sleep\(|time\.sleep|setTimeout|Thread\.sleep'` in tests finds fixed waits. Note serial tests that could run in parallel, a fixture rebuilt per test, and whether each command has one test that starts it for real.

## 16. Built to last
Duplicated logic across files, workarounds, special cases bolted on, "clean up later" notes, unused code left behind, structure that no longer fits. On code no change is touching these are "when next touched:" notes. Local style and naming belong to desloppify.

## Analyzer ladder
Use one only if it is already installed and configured in the repo; recommend the one for the stack otherwise.

| Stack | Tool |
|---|---|
| TypeScript / JavaScript | dependency-cruiser; ts-arch |
| Python | import-linter |
| JVM | ArchUnit; Konsist for Kotlin |
| .NET | ArchUnitNET / NetArchTest |
| Go | go-arch-lint |
| PHP | Deptrac |
| Ruby | packwerk |
| Rust | workspace crate boundaries and `pub` visibility; cargo-modules |
| Any | `rg` over import lines (no cycle detection) |

Config files to probe: `.dependency-cruiser.*`, `importlinter.cfg`, `.importlinter`, `[tool.importlinter]` in `pyproject.toml`, `deptrac.yaml`, `packwerk.yml`, `go-arch-lint.yml`, `*ArchTest.kt` / `*ArchTest.java`, and their calls in CI. A tool declared in a manifest but not installed counts as not installed. A repo may enforce boundaries with its own test (an import fence); read and run it.
