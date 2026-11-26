---
name: auditing-design-principles
description: Use when asked to audit, review or check an existing repo, component or folder against Michael's design principles (~/.local/share/agent-harness/design-principles.md), or when a codebase shows drift from them — logic in the wrong layer, outward or cross-component imports, framework types in domain code, mock-heavy tests, speculative abstraction, arbitrary caps, missing contracts, conformance suites or action logs, slow or sleep-based tests. Reads the live principles file and gives every section a verdict with evidence, plus findings that cite the section they break, as one PRINCIPLES-AUDIT.md. Read-only. Not for reviewing one change or PR (reviewer-brief.md, reviewing-prs), designing the target and path (designing-the-smallest-version), or a general code-quality cleanup plan (desloppify).
---

# Auditing design principles

## Outcome

One `PRINCIPLES-AUDIT.md` that says, for every section of the live principles file, whether the audited code follows it, with evidence a reader can check, and lists each real breach as a finding that names the section it breaks, the proof and what it costs.

The authority is `~/.local/share/agent-harness/design-principles.md`. This skill never restates its rules. It says how to find evidence for them. When the file and this skill disagree, the file wins; report the drift in the audit's last section.

## Contract

- **Read-only.** Do not edit, create or delete anything in the audited repo. Do not install, upgrade or download tools, and do not change analyzer, lint or build config. Recommend a missing tool in a finding; do not add it.
- **Inputs are free.** Read any file, run the repo's own tests, journeys and installed analyzers, time them, and read the logs they write. Run in a scratch copy or worktree when a command writes to the tree; never against live data or a shared service.
- **Write the audit outside the repo** (your scratch directory) unless the caller names a place.

## Workflow

**1. Frame.** Record, in the audit header:
- The repo, the commit (`git rev-parse HEAD`) and the scope (the whole repo, or the components or paths asked for).
- The repo's bar, found the way the global instructions say (a brief's `Bar:` line, else the bar table against `git remote get-url origin`). If it is not known and you may ask, ask; otherwise audit at `shared` and say so. §10 depends on it.
- The principles file's path and `sha256sum`, so the audit can be repeated against the same rules.

**2. Read the principles file whole.** Take the section numbers and titles from it, not from memory or this skill. The audit has one table row per numbered section in the file, however many there are now. Note each section's own scope: which parts apply only to new components or boundaries, which say "do not retrofit", which depend on the bar.

**3. Map the code.** List the components, the composition (wiring) and any loose scripts. For each component, mark its layers by what its files import, not by folder names: a feature-organised repo is not "missing layers". Use the project's own words beside each. Gather deterministic facts first:
- TypeScript, JavaScript or Python: run the sibling skill's facts script, `python3 <skills-dir>/designing-the-smallest-version/scripts/repo_facts.py REPO --rev HEAD --out <scratch>/facts.json` (add `--parts parts.tsv` mapping each component to its globs to get cross-part edges). Read it with `--summary` first, not whole. It gives import edges, cycles, sizes, `gates`, `proof_commands` and `surfaces`.
- Other stacks, or rules the script does not cover: an installed architecture analyzer (see the ladder in [checks.md](checks.md)), else `rg` over import lines. Say which in each Evidence cell.

**4. Check every section.** Use [checks.md](checks.md) for what evidence answers each section. Sample where the code is large (3–5 user actions traced end to end is usually enough) and say what you sampled. Run what you doubt instead of guessing: the test suite and its time for §12 and §15; one real user action and the log it leaves for §14.

**5. Decide applicability per section, not for the whole repo.** A one-file script still answers to §4, §8, §9, §12, §14 and §16; §2, §3, §5, §6 and §7 may be `n/a` for it with one sentence why. A claim in the README or AGENTS.md is a lead, not evidence: verify it in the code.

**6. Write findings.** One breach per finding (F1, F2, …). Each has the fields in the template. Severity:
- **blocking**: it has an obligation (a § and the sentence it breaks), evidence (`file:line`, or a command and what it printed), a consequence someone hits in ordinary use at this repo's bar, and a component. Missing any one makes it a note.
- **note**: everything else worth saying, including breaches the file scopes away from existing code (a Gate on an old component, §14 or §16 on code nobody is touching). Start those with "when next touched:".
- A heuristic finding (a size ratio, a mock count, a sharing count) states its threshold and why that threshold. A threshold picked to make findings vanish is the failure this rule stops.
- Every finding ends with one fix sentence, or a deferral with the trigger that would make it worth fixing.

Also list **removable machinery**: code, config, layers or checks that could be deleted with every required behaviour kept (§4, §12). This is often the most useful part of an audit.

**7. Emit** the document below, then report its path, the three findings that matter most, and which verdicts you observed by running something versus only read.

## Template

```markdown
# Design principles audit: <repo>

**Date:** <real ISO date>  **Commit:** <sha>  **Scope:** <what was audited>
**Bar:** <personal | shared> (<how found>)
**Principles file:** <path> sha256 <hash>

## Summary
<2–4 sentences: the state, the worst problem, what to do first.>

## Map
| Path | Kind (component / composition / script) | Layer by imports | Project term | Notes |

## Principles table
| § | Title (from the file) | Verdict | Evidence |
<one row per numbered section. Verdict: pass, fail, n/a, or unknown (the repo cannot show it either way; say what record would). Evidence: about 40 words, `file:line` or the command run, "read", "sampled N of M" or "ran"; point to findings by id.>

## Findings
### F1. <short title>
- **Severity:** blocking | note
- **Obligation:** §<n> <title>: "<the sentence it breaks>"
- **Component:** <part of the system, in plain words>
- **Evidence:** <file:line, excerpt or command and output; detected by: script / analyzer name / rg / reading>
- **Consequence:** <what a user or the next maintainer hits>
- **Fix or deferral:** <one sentence; a deferral names its trigger>

## Removable machinery
<what could go, with every required behaviour kept, and the evidence it is unused or unneeded>

## Run versus read
<commands run and what they showed; verdicts that rest on reading alone; tools recommended but not installed>

## Out of scope
<seen but not a principles matter (naming, formatting, local duplication: desloppify); drift between this skill and the principles file>
```

An audit with no findings still has every section, with `## Findings` empty.

## Mistakes to avoid

| Mistake | Instead |
|---|---|
| Listing the sections from memory or from this skill | Read the file each run; its numbering and titles are the table. |
| One verdict for the repo ("not layered, so skip") | Judge each section; most apply to a script too. |
| Flagging old code under a rule the file says not to retrofit | Report it as a "when next touched:" note, never blocking. |
| Citing a principle in general terms | Quote the sentence the code breaks. |
| Trusting the README's architecture | Check the imports. |
| Calling an analyzer's silence a pass | Check its config covers the rule first. |
| `fail` on §11 or §13 because no record exists | `unknown`, and say what record would settle it, unless the file requires the record for this code. |
| Demanding hardening at `personal` | §10 sets the bar; never committed secrets hold at both bars. |
| Adding abstraction as a fix | A fix that adds machinery the need does not require fails §4. |
| Editing code you found broken | Findings only. |
