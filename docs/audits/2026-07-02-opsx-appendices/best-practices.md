# Best-Practices Brief: Spec-Driven Development + Autonomous Agent Looping (mid-2026)

## Executive summary

AI coding practice has converged on **bounded autonomy**: give agents durable intent artifacts, small executable tasks, deterministic gates, isolated workspaces, and human checkpoints at phase boundaries. Best systems do not trust prompts, chat history, or model self-assessment as source of truth.

Spec-driven development works when specs are **right-sized, reviewable, test-linked, and kept live**. Autonomous loops work when loop progress lives in **files/git/tests**, not context windows, and when budgets, stall detection, and independent review can stop bad or wasteful runs.

---

# 1. Spec-driven development with AI coding agents

## Consensus as of mid-2026

1. **Spec before code, but not ceremony before value.** GitHub Spec Kit frames SDD as specs becoming primary development artifacts: `/specify`, `/plan`, `/tasks`, then implementation; project constitution stores governing principles that every feature inherits. This pattern became common because ad-hoc prompting drifts from intent. [GitHub Spec Kit docs](https://github.github.com/spec-kit/) [GitHub blog](https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/) [Spec Kit repo](https://github.com/github/spec-kit)

2. **Persistent project context belongs in constitution/steering files.** Spec Kit uses `.specify/memory/constitution.md`; Kiro uses workspace/global steering files under `.kiro/steering/` or `~/.kiro/steering/`, with auto, pattern, and manual inclusion modes. Good steering documents encode product, structure, tech, standards, security rules, and known traps. [Spec Kit spec-driven.md](https://github.com/github/spec-kit/blob/main/spec-driven.md) [Kiro steering docs](https://kiro.dev/docs/steering/) [Kiro CLI steering docs](https://kiro.dev/docs/cli/steering/)

3. **Feature specs should separate WHAT/WHY from HOW.** Spec Kit and Kiro both split requirements from design and tasks. Kiro formalizes specs as `requirements.md`, `design.md`, and `tasks.md`; Spec Kit uses generated markdown artifacts across phases. This reduces prompt ambiguity and helps agents resume work. [Kiro specs docs](https://kiro.dev/docs/specs/) [Kiro feature specs](https://kiro.dev/docs/specs/feature-specs/) [Spec Kit quickstart](https://github.com/github/spec-kit/blob/main/docs/quickstart.md/)

4. **EARS-style requirements are useful because agents need testable obligations.** EARS gives constrained forms such as “WHEN [event] THE SYSTEM SHALL [response]” and variants for state, optional features, and unwanted behavior. Kiro uses EARS in generated requirements; practitioners use it because it turns vague feature text into acceptance criteria and test targets. [Kiro feature specs](https://kiro.dev/docs/specs/feature-specs/) [Alistair Mavin EARS guide](https://alistairmavin.com/ears/) [Jama EARS guide](https://www.jamasoftware.com/requirements-management-guide/writing-requirements/adopting-the-ears-notation-to-improve-requirements-engineering/)

5. **OpenSpec converged toward lighter change-scoped governance.** OpenSpec puts each change in its own folder with proposal/spec/design/tasks and then archives accepted changes back into living specs. It is less phase-rigid than Spec Kit, aimed at AI assistants across many CLIs/editors. [OpenSpec repo](https://github.com/Fission-AI/OpenSpec) [OpenSpec concepts](https://github.com/Fission-AI/OpenSpec/blob/main/docs/concepts.md) [OpenSpec docs](https://github.com/Fission-AI/OpenSpec/tree/main/docs)

6. **Kiro popularized “specs as unit of work” inside IDE workflow.** Kiro’s spec mode generates requirements, design, tasks, and uses steering files plus hooks for project discipline. Its docs now include quick plans and bugfix specs, signaling community pressure to right-size process for smaller work. [Kiro blog: From chat to specs](https://kiro.dev/blog/from-chat-to-specs-deep-dive/) [Kiro specs best practices](https://kiro.dev/docs/specs/best-practices/) [Kiro quick plan](https://kiro.dev/docs/specs/quick-plan/)

7. **Tessl represents the more ambitious spec-as-source direction.** Martin Fowler’s SDD analysis distinguishes spec-first, spec-anchored, and spec-as-source. Kiro and Spec Kit mostly support spec-first/spec-anchored workflows; Tessl explicitly explores spec-as-source, where generated code may be marked not to edit manually. [Martin Fowler / Thoughtworks analysis](https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html)

8. **Right-sizing is the practical convergence.** Teams increasingly use lightweight specs for small work, full gated specs for ambiguous or high-risk work, and living specs only where future evolution matters. Fowler’s critique: heavy upfront specs conflict with iterative development if every small task gets a large markdown bundle. [Martin Fowler / Thoughtworks analysis](https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html) [Thoughtworks SDD analysis](https://www.thoughtworks.com/en-us/insights/blog/agile-engineering-practices/spec-driven-development-unpacking-2025-new-engineering-practices)

## What is contested

1. **Spec-as-source vs spec-anchored.** Some argue specs should become true source, with humans editing specs and generated code treated as disposable. Others argue code remains ground truth for behavior, while specs guide intent and review. Tessl is pushing spec-as-source; Kiro/Spec Kit/OpenSpec mostly remain pragmatic spec-first/spec-anchored. [Martin Fowler / Thoughtworks analysis](https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html)

2. **How much upfront design is healthy.** Spec-first reduces drift, but overlong specs recreate waterfall. Community trend: front-load ambiguity resolution, not exhaustive design. Use progressive elaboration and small change packages.

3. **Whether AI-generated markdown is trustworthy.** Specs can become “spec theater”: plausible documents nobody reviews. Best teams treat spec text like code: diffed, reviewed, tested against implementation, and pruned.

4. **How formal EARS should be.** EARS improves testability, but rigid notation can be awkward for exploratory UX, research spikes, and non-functional qualities. QRA and requirements-practice sources warn not every requirement benefits from EARS. [QRA: When not to use EARS](https://qracorp.com/when-not-to-use-ears/)

## Common failure modes

1. **Spec drift.** Code changes bypass spec updates; living spec becomes stale.
2. **Spec-code divergence.** Implementation passes tests but no longer satisfies written acceptance criteria, or specs describe features not shipped.
3. **Over-ceremony.** Tiny fixes require proposal/design/tasks/review/archive overhead larger than work.
4. **Spec theater.** Agent emits large markdown nobody reads; false sense of alignment.
5. **Ambiguity laundering.** Agent converts vague prompt into confident spec without marking unknowns.
6. **Context bloat.** Constitution/steering files become too large and drown useful task context.
7. **Task chunks too large.** Agent gets broad implementation task, loses intent, and creates tangled changes.
8. **Unmapped acceptance criteria.** Requirements exist but no tests or verification steps prove them.
9. **Human checkpoint skipped.** Agent moves from requirements to design to implementation without stakeholder review at ambiguity points.

## Best-practices checklist

### Scope and sizing

- [ ] Classify change size before workflow starts.
  - XS: typo/mechanical refactor → no spec; maybe task note only.
  - S: local behavior change → short spec with goal, acceptance criteria, tests.
  - M: feature/bug with ambiguity → requirements + design + tasks + review gate.
  - L/XL: cross-system or risky change → full proposal, spec, design, tasks, threat/rollback plan, archived living spec.
- [ ] Require spec only when it reduces ambiguity or future maintenance cost.
- [ ] Keep one change per spec package unless architectural roadmap needs higher-level umbrella.

### Requirements

- [ ] Use EARS-like acceptance criteria for observable behavior.
- [ ] Mark unknowns explicitly: `NEEDS CLARIFICATION`, not agent guesses.
- [ ] Include non-goals and out-of-scope items.
- [ ] Include edge cases and failure behavior, not only happy path.
- [ ] Link every acceptance criterion to at least one verification method.

### Constitution / steering

- [ ] Keep project constitution short enough to load every session.
- [ ] Put stable rules in constitution/steering; put feature details in spec.
- [ ] Split steering by scope/pattern where tool supports it.
- [ ] Version steering files and review changes like code.
- [ ] Include security, test commands, architecture boundaries, style, and known failure modes.

### Planning and tasking

- [ ] Separate WHAT/WHY from HOW.
- [ ] Break tasks into single-session, independently verifiable units.
- [ ] For each task, define allowed files or expected touchpoints where possible.
- [ ] Add “do not implement yet” gates between requirements/design/tasks for non-trivial work.
- [ ] Generate cross-artifact consistency checks before implementation.

### Verification and drift control

- [ ] Require PRs that change behavior to update specs in same change.
- [ ] CI checks spec links or AC IDs against tests for M+ changes.
- [ ] Run a convergence/reconciliation pass after implementation.
- [ ] Archive or consolidate completed change specs into living docs where useful.
- [ ] Delete obsolete spec text; stale detail is worse than absent detail.

---

# 2. Autonomous agent looping

## Consensus as of mid-2026

1. **Looping works because fresh context beats heroic long sessions.** Geoff Huntley’s Ralph Wiggum loop popularized a simple pattern: run an agent repeatedly, one task per loop, with state in files and git history rather than relying on growing chat context. [Huntley: Ralph Wiggum as a software engineer](https://ghuntley.com/ralph/) [Huntley: everything is a ralph loop](https://ghuntley.com/loop/) [Huntley: CURSED loop story](https://ghuntley.com/cursed/)

2. **Production loops need harnesses, not faith.** Anthropic’s long-running agent harness guidance uses initializer and coding agents, progress files, git commits, isolated worktrees/VMs, and structured summaries so each fresh session can resume safely. [Anthropic: Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents) [Anthropic: Harness design for long-running apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)

3. **Stop conditions must be explicit before loop starts.** Best practice layers success, failure, and budget stops: max iterations, token/cost ceiling, elapsed time, no-progress threshold, failing deterministic gate, and human checkpoint. Ralph-style loops without caps can spin forever or rack up spend. [Addy Osmani: Self-improving coding agents](https://addyosmani.com/blog/self-improving-agents/) [Agent Contracts paper](https://arxiv.org/html/2601.08815v1)

4. **Deterministic gates beat model self-assessment where possible.** For software, tests, build, typecheck, lint, static analysis, property tests, and replay suites are preferred. LLM-as-judge is useful for subjective quality, spec interpretation, review completeness, and UX/language dimensions, but should not replace executable checks. [Anthropic: Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) [Braintrust: LLM-as-a-judge vs deterministic evals](https://www.braintrust.dev/articles/what-is-llm-as-a-judge) [MLflow LLM-as-judge](https://mlflow.org/llm-as-a-judge)

5. **LLM judges need calibration and narrow rubrics.** Agent evaluation now commonly looks at final output plus trajectory/tool use, but judge prompts must be stable, versioned, calibrated against human labels, and separated from deterministic checks. [DeepEval agent eval guide](https://deepeval.com/guides/guides-ai-agent-evaluation) [DeepEval LLM-as-judge guide](https://deepeval.com/guides/guides-llm-as-a-judge) [LangChain eval framework](https://www.langchain.com/resources/llm-evaluation-framework)

6. **Independent review catches context-correlated errors.** Multi-model or separate-context adversarial review is now common for high-risk changes: builder agent produces patch, reviewer agent audits against spec, sometimes a third adjudicator gives GO/NO-GO. Blind review reduces contamination from builder reasoning.

7. **Sandbox/worktree isolation is non-negotiable for autonomy.** Agents that can run commands need disposable environments, isolated file systems, restricted secrets, network egress controls, and branch/worktree isolation. Containers are useful but not always enough for untrusted generated code; gVisor, Firecracker, Kata, or managed VMs are used for stronger isolation. [Anthropic: How we contain Claude](https://www.anthropic.com/engineering/how-we-contain-claude) [Northflank sandboxing guide](https://northflank.com/blog/how-to-sandbox-ai-agents) [BeyondScale sandboxing guide](https://beyondscale.tech/blog/ai-agent-sandboxing-enterprise-security-guide)

8. **Humans own architecture, risk, and merge.** The emerging role is “orchestrator,” not passive approver: humans set objective/spec, approve plan, review risky diffs, and decide merge/release. Agents can self-loop on implementation details, but irreversible actions need checkpoints. [Addy Osmani: Future of agentic coding](https://addyosmani.com/blog/future-agentic-coding/) [Addy Osmani: Agentic engineering](https://addyosmani.com/blog/agentic-engineering/)

9. **Token economics are architecture, not accounting.** Long-running agents spend mostly on repeated input context. Controls include model-tier routing, prompt caching, context pruning, summarization artifacts, per-run budgets, per-user budgets, and cost alerts. [Augment: AI agent loop token costs](https://www.augmentcode.com/guides/ai-agent-loop-token-cost-context-constraints) [Waxell token budget enforcement](https://waxell.ai/blog/ai-agent-token-budget-enforcement) [Unblocked auto-loop tax](https://getunblocked.com/blog/agent-auto-loop-token-cost/)

## What is contested

1. **Simple Ralph loop vs complex multi-agent orchestration.** Huntley-style loops argue simple bash-loop persistence beats elaborate agent frameworks. Others favor planner/generator/evaluator teams for complex apps. Consensus: start simple; add agents only for distinct responsibilities.

2. **Model self-critique usefulness.** Self-reflection helps debug local mistakes, but research and practice show agents overestimate completion. Self-assessment should be advisory, never sole doneness gate. [Exploring autonomous agents failure paper](https://arxiv.org/abs/2508.13143)

3. **How much autonomy to permit.** Fully autonomous YOLO mode improves throughput but raises security/cost risk. Conservative teams auto-approve reads/tests, require approval for writes, shell commands outside allowlist, network, secrets, migrations, deploys, deletes, and commits/pushes.

4. **LLM-as-judge reliability.** Judge models scale evaluation, but can be biased, non-deterministic, prompt-sensitive, and model-correlated with builder. Best practice is layered eval, not judge-only eval. [Braintrust](https://www.braintrust.dev/articles/what-is-llm-as-a-judge) [Anthropic evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

5. **Trajectory grading vs outcome grading.** Anthropic notes path/tool-order assertions can be brittle; outcome grading is often better. But regulated or security-critical systems may still require trajectory/tool-policy checks. [Anthropic evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)

## Common failure modes

1. **Infinite loop / thrashing.** Agent repeatedly edits same files or reruns failing tests without new hypothesis.
2. **Plateau.** Metrics stop improving; agent makes cosmetic changes to appear productive.
3. **False done.** Agent declares success despite failing tests, skipped acceptance criteria, or unrun checks.
4. **Context rot.** Long session accumulates stale assumptions; reviewer shares builder’s mistaken context.
5. **Budget runaway.** Loop lacks token/cost/time caps.
6. **Unsafe tool use.** Agent deletes files, leaks secrets, hits external services, or runs destructive commands.
7. **Spec gaming.** Agent changes tests/specs to fit implementation rather than fixing code.
8. **Review collusion.** Reviewer sees builder rationale and rubber-stamps.
9. **Merge risk.** Good isolated patch fails when integrated with mainline drift.
10. **Silent regressions.** Agent passes narrow task tests but breaks broader behavior.

## Best-practices checklist

### Loop contract

- [ ] Define objective, scope, non-goals, allowed tools, allowed files, and forbidden actions before run.
- [ ] Define success gates, failure gates, and budget gates before run.
- [ ] Require one task per loop iteration.
- [ ] Persist state in files/git: task list, progress log, test output, decisions, commit history.
- [ ] Start each iteration from fresh context where feasible.

### Budgets and stopping

- [ ] Hard max iterations.
- [ ] Hard token/cost cap per run.
- [ ] Wall-clock timeout.
- [ ] Per-command timeout.
- [ ] Stop after N consecutive no-progress iterations.
- [ ] Stop if same error signature repeats after attempted fixes.
- [ ] Stop if diff churn exceeds threshold without gate improvement.
- [ ] Emit “needs human” report on stop, not another speculative fix.

### Deterministic gates

- [ ] Build passes.
- [ ] Unit/integration tests pass.
- [ ] Typecheck/lint/static analysis pass.
- [ ] Security checks run for dependency/auth/input-sensitive changes.
- [ ] Acceptance criteria mapped to tests or explicit verification.
- [ ] Regression suite/replay suite passes before merge.
- [ ] Agent cannot modify gates without human approval.

### LLM-as-judge gates

- [ ] Use judge only for subjective/spec-semantic dimensions.
- [ ] Judge sees spec, diff, test evidence, and rubric; not builder chain-of-thought.
- [ ] Require structured verdict: `GO`, `NO-GO`, or `NEEDS HUMAN` with cited evidence.
- [ ] Calibrate judge against human-reviewed examples.
- [ ] Use different model/family or at least separate context for high-risk review.
- [ ] Log judge prompt/version/model/output for audit.

### Stall / plateau detection

- [ ] Track objective metric: tests passed, ACs satisfied, failing error count, uncovered tasks.
- [ ] Hash repeated failures and repeated diffs.
- [ ] Detect file churn: edits revert same lines repeatedly.
- [ ] Detect non-substantive commits: formatting/comment-only changes after failures.
- [ ] Escalate when no metric improves across threshold.

### Multi-model adversarial review

- [ ] Builder and reviewer run in separate contexts.
- [ ] Reviewer gets clean checkout plus spec/diff/evidence, not builder narrative.
- [ ] Reviewer must produce GO/NO-GO with blocking issues.
- [ ] Optional second reviewer uses different model for security/high-impact changes.
- [ ] Adjudicator or human resolves reviewer disagreement.

### Sandboxing and isolation

- [ ] Run in feature branch/worktree, never main.
- [ ] Use disposable workspace/VM/container per run.
- [ ] Restrict secrets; inject only per-task minimum credentials.
- [ ] Restrict network egress by default.
- [ ] Deny destructive filesystem commands or require approval.
- [ ] Snapshot before run; support rollback.
- [ ] Separate agent-generated artifacts from trusted source until review.

### Human checkpoints

- [ ] Human approves spec for M+ work.
- [ ] Human approves design for cross-system/security/data changes.
- [ ] Human approves permission escalation, migrations, deletes, deploys, external calls, and pushes.
- [ ] Human reviews NO-GO loops and repeated stalls.
- [ ] Human owns final merge/release decision.

### Cost controls

- [ ] Use cheap model for routing/summarization/simple review; frontier model for hard design/debug.
- [ ] Cache stable system prompts/steering/spec context.
- [ ] Prune context; prefer progress files and git diffs over full transcript replay.
- [ ] Summarize tool outputs; store full logs outside model context.
- [ ] Emit cost estimate before long run and final cost after run.
- [ ] Alert on abnormal spend or iteration count.

---

# Practical combined pattern

For serious AI coding systems in 2026, best combined architecture looks like this:

1. **Spec layer:** constitution/steering + change-scoped spec + EARS acceptance criteria.
2. **Task layer:** atomic tasks with allowed files and deterministic verification.
3. **Loop layer:** one task per fresh-context iteration, progress persisted in git/files.
4. **Gate layer:** build/test/typecheck/security first; LLM judge only for judgment calls.
5. **Review layer:** independent adversarial review with GO/NO-GO verdict.
6. **Control layer:** sandbox, budgets, stall detection, and human checkpoints.
7. **Drift layer:** every behavior-changing PR updates spec/tests; completed specs archived/consolidated.

---

# Sources

## Kept

- GitHub Spec Kit docs — primary docs for Spec Kit workflow and constitution. https://github.github.com/spec-kit/
- GitHub Spec Kit repo — primary source for commands, templates, AGENTS.md, workflows. https://github.com/github/spec-kit
- GitHub blog on Spec Kit — launch rationale and SDD framing. https://github.blog/ai-and-ml/generative-ai/spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/
- OpenSpec repo/docs — primary source for Fission-AI OpenSpec workflow. https://github.com/Fission-AI/OpenSpec
- Kiro specs/steering docs — primary source for Kiro spec mode, EARS usage, steering files. https://kiro.dev/docs/specs/ and https://kiro.dev/docs/steering/
- Martin Fowler / Thoughtworks SDD analysis — high-signal critique of Kiro, Spec Kit, Tessl and SDD maturity levels. https://martinfowler.com/articles/exploring-gen-ai/sdd-3-tools.html
- Alistair Mavin EARS guide — original/authoritative EARS notation reference. https://alistairmavin.com/ears/
- Jama EARS guide — practical requirements-engineering use of EARS. https://www.jamasoftware.com/requirements-management-guide/writing-requirements/adopting-the-ears-notation-to-improve-requirements-engineering/
- QRA “When Not to Use EARS” — counterweight against over-formalizing requirements. https://qracorp.com/when-not-to-use-ears/
- Geoff Huntley Ralph posts — primary source for Ralph loop pattern and philosophy. https://ghuntley.com/ralph/ and https://ghuntley.com/loop/
- Anthropic long-running harness articles — primary source for fresh-context, git/worktree, initializer/coding agent patterns. https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Anthropic agent evals — primary source for deterministic vs LLM eval guidance. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic containment — primary source for sandbox/isolation practices in deployed AI agents. https://www.anthropic.com/engineering/how-we-contain-claude
- Addy Osmani self-improving/agentic coding posts — practitioner synthesis for loops, gates, orchestration role. https://addyosmani.com/blog/self-improving-agents/ and https://addyosmani.com/blog/future-agentic-coding/
- Braintrust LLM-as-judge article — clear practical distinction between deterministic evals and judge models. https://www.braintrust.dev/articles/what-is-llm-as-a-judge
- MLflow / DeepEval / LangChain eval docs — current eval tooling guidance for agents and judges. https://mlflow.org/llm-as-a-judge https://deepeval.com/guides/guides-ai-agent-evaluation https://www.langchain.com/resources/llm-evaluation-framework
- Agent Contracts paper — formal framing for bounded resource constraints. https://arxiv.org/html/2601.08815v1
- Northflank/BeyondScale sandboxing guides — implementation detail for agent isolation tradeoffs. https://northflank.com/blog/how-to-sandbox-ai-agents https://beyondscale.tech/blog/ai-agent-sandboxing-enterprise-security-guide
- Augment/Waxell/Unblocked cost guides — token/cost-control patterns for long-running loops. https://www.augmentcode.com/guides/ai-agent-loop-token-cost-context-constraints https://waxell.ai/blog/ai-agent-token-budget-enforcement https://getunblocked.com/blog/agent-auto-loop-token-cost/

## Dropped or de-emphasized

- Generic “best AI tools” listicles — useful for discovery, weak as evidence.
- Medium reposts and summaries when primary docs existed — redundant.
- SEO-heavy 2026 “complete guide” pages — often repeated claims without primary evidence.
- YouTube/podcast-only sources — harder to verify and cite precisely for implementation rules.
- Vendor claims about productivity multipliers — treated as anecdotal unless tied to reproducible benchmark or primary implementation detail.

---

# Gaps and uncertainty

- Exact quantitative productivity/cost gains remain mostly anecdotal or vendor-reported; few public controlled studies compare SDD/loop workflows across real teams.
- Tessl’s spec-as-source maturity is still evolving; public details show direction more than settled practice.
- LLM-as-judge reliability varies by model, rubric, and domain; teams need local calibration.
- Sandboxing recommendations depend on threat model; regulated workloads need stronger isolation than personal coding loops.
