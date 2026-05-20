# Audit Workflow

14 steps total (Step 0 through Step 12, with one fractional step — Step 1.5 — inserted for stack detection). Step 0 is mandatory. Steps 1–11 produce findings; Step 12 emits the document.

Corollary IDs cited per step refer to [corollaries.md](corollaries.md). Output schema in [output-format.md](output-format.md). Skill uses neutral vocabulary; translate to the project's terms in findings.

**Detection-tier reminder.** Each corollary is tagged `[D]` deterministic, `[H]` heuristic, or `[J]` judgmental in `corollaries.md`. Tier governs *how* the corollary is checked:
- Tier D — if an analyzer is installed (see Step 1.5), consume its output as ground truth.
- Tier H — analyzer can flag candidates; auditor calibrates the threshold and records it in evidence.
- Tier J — auditor reads source. No analyzer decides.

Findings record the detection method in **Detected by** (analyzer name / `heuristic` / `auditor judgment`).

## Step 0 — Repo Shape Check (mandatory)

Before any other check, confirm the repo benefits from layered architecture. Bail with an explicit, written `No Audit Performed` finding if **any** apply:

- Single-purpose script / glue / cron
- CRUD wrapper without domain rules
- Code-gen output dominates the tree
- Library / SDK / framework where technical role *is* the domain
- Data / ETL pipeline where stages are the architecture
- Event-sourced system where the event log is the system of record and CQRS handlers are intentionally thin
- Project so small that layering would dominate the codebase

Output a one-paragraph `No Audit Performed` section explaining **specifically** which criterion was met and why this repo matches it. Stop.

If the project's README / `CLAUDE.md` / architecture doc claims clean architecture but the repo matches one of the shapes above, bail anyway — claimed style doesn't earn an audit.

**For multi-subsystem repos / monorepos:** run Repo Shape Check **per subsystem**, not whole-repo. The findings doc's `Scope` field can list a strict subset; subsystems that fail Step 0 are recorded as omitted with the criterion cited.

**Bailing without justification is a red flag — see `SKILL.md`.**

## Step 1 — Map

**Audit the imports, not the project's self-description.** Architecture docs lag reality; the import graph is the source of truth. Use the README / `CLAUDE.md` to learn vocabulary and stated intent, but never as authority about what the code actually does.

List top-level modules. Tag each with a candidate neutral layer: inner / outbound adapter / inbound adapter / delivery / mixed / unknown. Note ambiguous ones. Use the project's own term in the Notes column for translation.

Also detect the **primary language / stack** during this step (used by Step 1.5).

## Step 1.5 — Analyzer detection & invocation (deterministic-tier prep)

Before manual scanning, **probe for an installed architecture-test tool** that fits the stack. See the deterministic-validator ladder in `SKILL.md` for the stack → tool mapping.

**Probe order (canonical filenames):**

1. Analyzer config files: `.dependency-cruiser.js` / `.dependency-cruiser.cjs` / `.dependency-cruiser.json` / `dependency-cruiser.config.js`; `deptrac.yaml` / `deptrac.toml`; `importlinter.cfg` / `.importlinter` / `setup.cfg` (`[importlinter]` section) / `pyproject.toml` (`[tool.importlinter]`); `packwerk.yml`; `go-arch-lint.yml`; `*ArchTest.kt` / `*ArchTest.java` files; `archunit.properties` (optional — ArchUnit works without it, so absence is not signal).
2. Build-manifest dependency declarations: `package.json` (dependency-cruiser, ts-arch), `composer.json` (Deptrac), `requirements*.txt` / `pyproject.toml` (import-linter), `Gemfile` (packwerk), `pom.xml` / `build.gradle` / `build.gradle.kts` (ArchUnit, Konsist), `go.mod` (go-arch-lint).
3. CI invocations of any of the above.

**If found AND present in the local environment:**
- Run the tool with its existing configuration (never modify config; never add a new tool to the repo).
- **Verify per-corollary coverage:** read the analyzer's config and identify which tier-D corollaries its rules actually enforce. A dep-cruiser config containing only `no-circular` covers C2 only — it says nothing about C1, C3, C4, C5, or C16. Treat its silence as ground truth **only for corollaries its rules cover.**
- For covered corollaries: consume JSON / SARIF / text output as **ground truth**. Cite the tool by name and the specific rule name in the **Detected by** field. Note tool name, version, config path, and the per-corollary coverage map in **Cross-cutting Observations** for reproducibility.
- For uncovered tier-D corollaries: fall back to ripgrep as if no analyzer were installed; record the gap in Cross-cutting Observations and recommend the team extend the analyzer's config to cover them.

**If declared in a manifest but not present in the local environment:** treat as not-installed. `npm install`, `pip install`, `bundle install`, etc. is **installation and forbidden by the contract.** Fall back to ripgrep and record the declared-but-not-materialised tool in Cross-cutting Observations.

**If not found at all:**
- Fall back to ripgrep over hand-crafted import patterns for tier-D corollaries. Note in evidence that detection was by fallback (`Detected by: heuristic (ripgrep import scan)`).
- **Recommend** (do not install) the stack-appropriate analyzer in Cross-cutting Observations. Name the tool by its canonical name; do not emit installation commands.
- **C17 fires by construction** when Step 1.5 finds no analyzer (Step 7 will record it). This is intentional: enforcement-absence *is* the C17 violation.

**Do not install tooling during the audit.** Installation is a recommendation for the team to act on after reviewing findings; the audit is read-only by contract.

**Tier-D pass does not reduce tier-H/J obligation.** A clean analyzer run on tier-D corollaries says nothing about Steps 4–11. Run the full workflow regardless of analyzer outcome.

**Ripgrep fallback recipes** (when no analyzer covers the corollary):
- **C1** (DIP): `rg -n --type-add 'src:*.{rs,ts,js,py,go,java,kt,cs,rb,php}' --type src '^(use|import|from|require|include) .*(adapters|infrastructure|providers|consumers)' <inner-package-paths>` — any hit in an inner package is a candidate violation.
- **C2** (cycles): no ripgrep equivalent. Mark as detection-degraded and strongly recommend the stack analyzer.
- **C3, C4, C5** (boundary data / plain domain / ACL): grep inner-package files for framework / third-party type names; the list of framework types is auditor-curated and recorded in Cross-cutting Observations.
- **C16** (composition root): `rg -n '(new |::new\(|\.create\()<AdapterTypeNames>' <inner-package-paths>` with the adapter type names enumerated by hand from the Layer Map. Imperfect (misses factory indirection); mark detection-degraded in evidence.

**Tier-H corollaries** (C6, C7, C8, C12, C15, C19, C20) can also benefit from analyzer output when the analyzer expresses thresholds; record the threshold used in the finding evidence.

**Tier-J corollaries** (C9, C10, C11, C13, C14, C18, C21, C22) are not affected by this step — auditor reads source.

## Step 2 — Vocabulary translation

Note whether the project uses hexagonal, onion, clean, DDD, custom, or **no architectural vocabulary at all** (many real codebases just have `controllers/services/repositories/` with no intent statement). Map to the skill's neutral vocabulary using the glossary in `SKILL.md`. Record the mapping in the findings doc header so downstream tools can re-translate.

Skill applies even when the project has no clean-arch vocabulary. The dependency rule is structural, not nominal.

## Step 3 — Verify direction (C1 [D], C2 [D])

**If an analyzer ran in Step 1.5, its output is ground truth.** Convert each reported violation to an `Fn` finding citing the analyzer in **Detected by**. Skip the manual pass for these corollaries.

**If no analyzer:** for each module, list imports via ripgrep / IDE / language-native tooling. Flag:
- Inner-from-outer edges
- Import cycles (transitive)

Mark **Detected by** as `heuristic (ripgrep import scan)` or `auditor judgment` per the actual method used.

## Step 4 — Boundary scan (C3 [D], C4 [D], C5 [D], C6 [H], C7 [H], C8 [H])

**Tier-D corollaries in this step** (C3, C4, C5) consume analyzer output from Step 1.5 when available.

**Tier-H corollaries** (C6, C7, C8) require auditor calibration. Pick boundary signatures (inner port definitions, outbound-adapter impl returns, inbound-adapter entry points). Flag:
- Framework types in domain code (C3 — analyzer-driven if available)
- ORM rows / HTTP / transport handles crossing into inner core (C3, C4 — analyzer-driven if available)
- Raw exceptions / errors crossing layers untranslated (C6 — calibrate threshold)
- Use-case return shapes that force the caller to branch on success / failure (C7 — sample and decide)
- DTOs shared across multiple use cases (C8 — record sharing-count threshold in evidence)

## Step 5 — Inner-layer scan (C9 [J], C10 [J], C11 [J], C12 [H])

Sample 3–5 user-facing operations. Trace each end-to-end. Record the sample set in the findings doc's **Cross-cutting Observations** **and** cite specific operations as evidence on relevant findings. Flag:
- Policy decisions outside the inner core (cache paths, retention, retry, validation)
- Anemic entities (primitive obsession) — calibrate severity per C12 trade-off note
- Missing use-case orchestration (multi-step logic living in an adapter)
- Features that required outer-layer changes first

## Step 6 — Outer-layer scan (C13 [J], C14 [J], C15 [H])

Sample views, handlers, transport entry points. Measure logic depth. Flag:
- Decisions in untestable shells (humble object failure)
- Delivery making business decisions
- Fat outer layers — **apply the C15 merit gate** before promoting to minor / major. Sample inside the fat layer: are decisions happening there, or just rendering / capture / glue?

## Step 7 — Wiring scan (C16 [D], C17 [D])

Locate the composition root. Check build configuration for enforcement (visibility, lint, arch-tests, workspace deps). Flag:
- Concrete instantiation scattered through inner modules (C16 — analyzer-driven if available; constructor-call AST scan; ripgrep fallback recipe in Step 1.5 is detection-degraded)
- Dependency rule unenforced (C17 — meta-check: absence of analyzer / lint / arch-test from Step 1.5 *is* the C17 violation). **C17 fires by construction** when Step 1.5 found no analyzer — record it here as the construction-derived finding.

When the C17 finding fires, **name the stack-appropriate tool in the suggested fix** (e.g. "Add a dep-cruiser config and wire it into CI"; "Adopt ArchUnit in the existing JUnit suite"). Naming the tool is prose; emitting its config is not.

## Step 8 — Independence test (C18 [J])

For each outer layer, articulate the swap in writing: *"to replace `<this adapter>` with `<alternative>`, I would change …"*. Note any swap that cannot be made without touching the inner core.

## Step 9 — Test posture (C19 [H])

Sample test files. Flag mock-heavy inner-core tests; flag tests that mock the inner core's collaborators rather than using real or test-double adapters. Per C19 trade-off note, in-memory fakes implementing inner-defined interfaces are acceptable.

## Step 10 — Discipline scan (C20 [H])

Count single-impl interfaces. Investigate any without a test double, swap rationale, or contract justification. Recommend removal in finding text (still prose, no diff). Accept a written rationale near the interface as sufficient defense.

## Step 11 — Layout (C21 [J], C22 [J]) and outer-fattening (C15 [H])

Apply the merit gate (flowchart in `corollaries.md`). When team preference for domain visibility / inner leanness is **unknown**, **omit the finding** rather than emit informational — `informational` is reserved for trade-offs where team preference is explicitly known and being surfaced for the record. Record every merit-gate outcome (`skipped` for out-of-scope shapes, `downgraded` to informational, `promoted` to minor/major, or `omitted` for unknown preference) in Cross-cutting Observations as "considered but [outcome] under merit gate" so the audit is reproducible.

## Step 12 — Emit findings

Use the schema in [output-format.md](output-format.md). Hand to the spec-driven framework.

**No source edits. No diffs. No fenced code anywhere — including bootstrap-mode skeletons (use prose path lists instead of ASCII trees). One prose sentence per fix.**

**Inputs to the audit are unconstrained** (analyzer output, AST scans, ripgrep), but **outputs remain prose**. Cite analyzer name in **Detected by** when consuming its output, but do not embed analyzer config, JSON, or commands in findings.

Empty audit (zero findings) still uses the full schema with an empty Findings section. Downstream tooling parses by section, not by length.
