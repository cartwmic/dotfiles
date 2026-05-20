# Findings Document Schema

Single markdown document. Section order and headings are a contract — downstream spec-driven tools key off them. Do not reorder, rename, or merge.

## Template

```markdown
# Clean Architecture Audit: <repo>

**Date:** <fill with actual ISO date, e.g. 2026-05-11>
**Mode:** audit | analyze | refactor-plan | bootstrap
**Scope:** <paths or modules audited>
**Project vocabulary:** <hexagonal | onion | clean | DDD | custom | none — and the project's term for each neutral layer>

## Summary

<2–4 sentences. State of the repo. Top concern. Whether layering is appropriate at all.>

## Repo Shape Check

<Why this repo is / isn't a fit for the audit. If not, stop here under "No Audit Performed" with a specific criterion cited from workflow.md Step 0.>

## Layer Map

| Module | Neutral layer | Project term | Notes |
|--------|---------------|--------------|-------|
| <path> | inner / outbound-adapter / inbound-adapter / delivery / mixed | <e.g. "Core" / "Service" / "Controller"> | <observation> |

## Findings

### F1. <short title>
- **Corollary:** C<n> (e.g. C3 boundary-data-plain)
- **Tier:** D | H | J (matches the corollary's tier in `corollaries.md`)
- **Detected by:** <analyzer name (e.g. `dependency-cruiser 16.x`) | `heuristic (ripgrep import scan)` | `heuristic (LOC ratio, threshold 2.0)` | `auditor judgment`>
- **Layer(s):** <neutral layers involved; project terms in parens>
- **Locations:** <file:line, file:line>
- **Evidence:** <minimal excerpt — no diffs; for heuristic findings, state the threshold used>
- **Why it violates:** <one sentence>
- **Suggested fix:** <one prose sentence — no diffs, no fenced code, no inline code beyond a single identifier>
- **Severity:** blocker | major | minor | informational
- **Merit gate (C15, C21, C22 only):** <which gate applied, "none — promoted", or "skipped because <gate>">

(repeat for F2, F3, ...)

## Cross-cutting Observations

<systemic patterns spanning multiple findings; sampled operations from workflow Step 5 listed here; merit-gate outcomes (including omissions) recorded here for reproducibility; analyzer probe result from workflow Step 1.5 — tool name + version + config path if found, or recommended-but-uninstalled tool if not found>

## Remediation Plan
(refactor-plan mode only — ordered prose list; each item references finding IDs. No diffs, no file lists, no commands. The downstream spec framework owns sequencing of actual work.)

## Bootstrap Skeleton
(bootstrap mode only — **prose path list** describing: where each layer lives (e.g. "inner core at `src/domain/`; outbound adapters at `src/infrastructure/`"), per-layer responsibilities, composition-root location, build-system enforcement plan. **Path list is flat or single-level bullets only — do not nest bullets to imply a tree.** **No ASCII directory trees.** **No fenced code blocks.** **No commands.** The downstream framework decides whether to materialise anything.)

## Out of Scope

<concerns observed but intentionally not flagged here — e.g. duplication, comment hygiene — with a pointer to the appropriate code-quality skill>
```

## Rules

- **`Fn` IDs are document-scoped stable handles.** Downstream tools reference them. Do not collapse or renumber within a document.
- **One corollary cite per finding (primary only).** Real violations often implicate multiple corollaries (e.g. a framework-type leak that also breaks plain-domain-objects). Cite the **primary** corollary — the root cause — only; downstream corollaries are implied by the prose evidence and do not require explicit citation. If two corollaries are genuinely independent for the same locations, file two findings.
- **Suggested fix is one prose sentence, ≤30 words.** If you can't, the finding is too coarse — split it. No diffs. No fenced code anywhere in fixes or skeletons. No inline backtick-quoted code beyond a single bare identifier (e.g. `UserId` is fine; `find_booking(id)` is not — no parens, no operators, no string literals).
- **One violation per `Fn`.** Bundling reduces downstream granularity.
- **Severity is required on every finding.** Use the rubric in `SKILL.md`. `informational` is for trade-offs, not indecision.
- **Merit-gated findings (C15, C21, C22)** must state which merit gate applied (filtered or promoted), even if the gate skipped the finding to informational.
- **Date must be a real ISO date.** Never emit the literal placeholder `<YYYY-MM-DD>`.
- **Mode declared explicitly** in the header. Don't leave blank, don't assume the downstream tool will infer it.
- **Empty audit** still uses the full schema. An empty `## Findings` section is parsable; a missing one breaks downstream tooling.
- **All modes emit prose only.** Refactor-plan and bootstrap are still prose findings, not executable artifacts. Bootstrap especially: no trees, no scaffolds, no commands.
- **C-IDs are an open catalog maintained by skill update.** Never invented in a finding. Unmappable observations go in Cross-cutting Observations and trigger a skill-update request.
- **Absence of a `**Trade-off:**` note on a corollary means no legitimate exception in scope.** Do not invent softeners to downgrade a finding.
- **Single markdown document.** No source edits, no companion diffs, no scaffolded files.
- **Detection method required.** Every finding records **Tier** and **Detected by**. Downstream tools weight tier-D analyzer-derived findings differently from tier-J auditor-judgment findings.
- **Inputs to the audit are unconstrained; outputs remain prose.** Analyzer output is evidence; cite the analyzer by name in **Detected by**. Do not embed analyzer config, JSON output, or invocation commands in findings.
- **When no tier-D analyzer covers a corollary** (no analyzer installed, or installed analyzer's rules don't cover this corollary), the audit still produces tier-D findings via fallback (ripgrep / manual scan); the **Detected by** field declares the fallback method, and **Cross-cutting Observations** records the recommendation to adopt or extend the stack-appropriate tool.
- **Tier-H threshold defense required.** Every tier-H finding records the threshold *and* a stated rationale (language norm, codebase scale, prior-art citation) for choosing it. Bare threshold without rationale is rejected — the threshold can be engineered to produce zero findings, so the rationale is the rule.
- **Tier-J evidence required.** Tier-J findings still require **Locations** and a quoted evidence excerpt. Judgmental means *interpretation* is the auditor's; evidence is not optional. Prose-only output does not license evidence-less findings.

## Worked example finding

**Read this first:** the block below is fenced as ` ```markdown ` **for legibility on this page only**. **Actual findings in your output document are emitted UNFENCED** — directly as the body of the `## Findings` section. **Do not copy the surrounding fence into your output.** This worked example is illustrative only — a fictional Rails repo demonstrating prose-only fix style and the merit-gate field.

```markdown
### F3. ORM rows returned from booking lookup
- **Corollary:** C3 boundary-data-plain
- **Tier:** D
- **Detected by:** dependency-cruiser 16.x (configured at `.dependency-cruiser.js`, rule `no-orm-into-domain`)
- **Layer(s):** inner (project: "domain"), outbound-adapter (project: "repository")
- **Locations:** src/repository/booking_repo.rb:42, src/domain/booking_service.rb:18
- **Evidence:** `find_booking` returns `ActiveRecord::Booking`; `BookingService#cancel` accesses `.attributes` directly on that object.
- **Why it violates:** ActiveRecord (framework type) crosses the adapter→inner boundary, dragging Rails into the domain layer and breaking inner-core compilability without the framework.
- **Suggested fix:** Translate ActiveRecord rows to a plain `Booking` value object at the repository boundary and return that to the domain service.
- **Severity:** blocker
- **Merit gate:** n/a
```

A tier-H heuristic finding includes the threshold used:

```markdown
### F7. Booking DTO shared across five write-side use cases
- **Corollary:** C8 boundary-types-per-use-case-not-shared
- **Tier:** H
- **Detected by:** heuristic (DTO-sharing count, threshold = 3 write-side use cases; rationale: codebase has ~40 use cases total, threshold chosen at >5% sharing per Vernon's "behavioural cohesion" guidance, and recent commits show three field-addition cascades caused by sharing at this scale)
- **Layer(s):** inner ports (project: "application services"), outbound-adapter (project: "repository")
- **Locations:** src/application/booking_dto.rb:1, plus 5 use case files (see evidence)
- **Evidence:** `BookingDto` referenced by `CreateBookingService`, `CancelBookingService`, `RebookService`, `MoveBookingService`, `RefundBookingService` — 5 use cases share the type (above threshold of 3); recent commits show field additions cascading recompiles across all five.
- **Why it violates:** Cross-use-case DTO sharing on the write side couples consumers; each field addition forces unrelated paths to retest.
- **Suggested fix:** Define one DTO per write-side use case, named after the use case it serves.
- **Severity:** minor
- **Merit gate:** n/a
```

A tier-J judgmental finding records auditor reasoning:

```markdown
### F11. Validation logic in cancel-booking controller
- **Corollary:** C13 delivery-is-thin
- **Tier:** J
- **Detected by:** auditor judgment (sampled 3 controller endpoints)
- **Layer(s):** delivery (project: "controllers"), inner ports (project: "application services")
- **Locations:** app/controllers/bookings_controller.rb:24-58
- **Evidence:** Controller's `cancel` action branches on booking status, hotel policy, and refund eligibility before delegating to the service; service-layer `CancelBookingService` exists but is bypassed for the non-trivial decisions.
- **Why it violates:** Business decisions live in the delivery layer; the service layer cannot be exercised through tests without the controller's branching, and a new transport (CLI, FFI) would have to reproduce the logic.
- **Suggested fix:** Move the status / policy / eligibility decisions into `CancelBookingService` so the controller only captures input and renders the result.
- **Severity:** major
- **Merit gate:** n/a
```
