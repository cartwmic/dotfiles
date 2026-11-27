---
name: auditing-design-principles
description: Use when asked to audit, review or check an existing repo, component or folder against Michael's design principles (~/.local/share/agent-harness/design-principles.md), including clean, hexagonal, onion or ports-and-adapters architecture and the dependency rule, or when a codebase shows drift from them — logic in the wrong layer, outward or cross-component imports, framework types in domain code, mock-heavy tests, speculative abstraction, arbitrary caps, missing contracts, conformance suites or action logs, slow or sleep-based tests. Reads the live principles file and gives every section a verdict with evidence, plus findings that cite the section they break, as one PRINCIPLES-AUDIT.md. Read-only. Not for reviewing one change or PR (reviewer-brief.md, reviewing-prs), designing the target and path (designing-the-smallest-version), or a general code-quality cleanup plan (desloppify).
---

# Auditing design principles

## Outcome

One `PRINCIPLES-AUDIT.md` that says, for every section of the live principles file, whether the audited code follows it, with evidence a reader can check, and lists each real breach as a finding that names the section it breaks, the proof and what it costs.

The authority is `~/.local/share/agent-harness/design-principles.md` (or the copy the caller names). This skill does not restate its rules; it says where to find evidence for them. Section numbers below are as of writing: when the file has moved or changed a rule, follow the file and note the drift in the audit's last section.

## Contract

- **Read-only.** Do not edit, create or delete anything in the audited checkout (the scratch worktree's own git metadata is the one exception), and do not change analyzer, lint or build config. Do not install new tools; recommend a missing one in a finding.
- **Run things.** Read any file, run the repo's own tests, journeys and installed analyzers, time them, and read the logs they write. Work in a detached scratch worktree (`git -C <repo> worktree add --detach <scratch>/<name> HEAD`, removed when done), never against live data, real accounts or a shared service. Installing the repo's own locked dependencies into that scratch worktree (for example `uv sync`, `npm ci`) is allowed so its tests can run; if they still cannot run, say so.
- **Write the audit outside the repo** (your scratch directory) unless the caller names a place.

## Workflow

**1. Frame.** Record in the audit header:
- The repo, the commit (`git rev-parse HEAD`) and the scope (the whole repo, or the components or paths asked for).
- The repo's bar, found the way the global instructions say (a brief's `Bar:` line, else the bar table against `git remote get-url origin`). If it is not known and you may ask, ask; otherwise audit at `shared` and say so. §10 depends on it.
- The principles file's path and `sha256sum`, so the audit can be repeated against the same rules.

**2. Read the principles file whole.** Take the section numbers and titles from it. The table has one row per numbered section. Note each section's own scope: which parts apply only to new components or boundaries, which say not to retrofit untouched code, which depend on the bar. Also note the unnumbered Enforcement section's checkable items (for example, whether the repo's AGENTS.md points at the file) and report them under Map.

**3. Map the code.** List the components, the composition (wiring) and any loose scripts. Leave generated and vendored code out of every later check except §10. Mark each component's layers by what its files import, not by folder names: a feature-organised repo, or a framework that dictates folders (Rails, Next.js, Android), is not "missing layers". Gather deterministic facts:
- An architecture analyzer already configured in the repo (ladder in [checks.md](checks.md)): run it first; it is also the Gate evidence. Check its config covers a rule before you count its silence as a pass.
- For any git repo, run the facts script from the sibling skill, adding `--summary` to print its keys: `python3 ~/.local/share/agent-harness/canonical/skills/designing-the-smallest-version/scripts/repo_facts.py REPO --rev HEAD [--parts parts.tsv] --out <scratch>/facts.json --force --summary`. `--force` is there because a rerun of the audit (a new rev or a new `parts.tsv`) regenerates the same scratch file from the repo, so replacing the old one loses nothing; without it the script refuses a file that already exists. `parts.tsv`, which you write, maps each component name to its globs; with it the script also reports edges between parts. Then read only the keys you need from `facts.json`. It reads the committed tree at REV (uncommitted work is ignored) and needs `deriving-readable-docs` installed beside it.
  - Import `edges` and cycles cover TypeScript, JavaScript and Python relative imports, and Rust `mod x;`, `use crate::`/`self::`/`super::`/workspace-crate paths and Cargo workspace dependencies (`mod_edges` are kept out of cycles). Imports by TypeScript workspace package name or tsconfig alias appear under `external_packages`: check those for the repo's own package names before you pass §2, §3 or §7.
  - `gates`, `proof_commands`, `surfaces` and `path_refs` work for any stack. `path_refs` is capped, so absence there does not prove a file is unused.
- Otherwise, or for what neither covers: `rg` over import lines. Say which source each Evidence cell rests on.

**4. Check every section** with [checks.md](checks.md). Sample where the code is large (3–5 user actions traced end to end is usually enough) and say what you sampled. Run what you doubt instead of guessing.

**5. Judge applicability per section, not for the whole repo.** A one-file script still answers to most sections (YAGNI, judgment in agents, caps, secrets, verification, logs, fast proof, built to last). The structural sections (kernel and adapters, layers, contracts, conformance, cross-component imports) may be `n/a` for it, or for a repo with one component, with one sentence why. A claim in the README or AGENTS.md is a lead; verify it in the code.

**6. Write findings.** One breach per finding (F1, F2, …), with the fields in the template.
- **blocking**: it has an obligation (the section and the sentence the code plainly misses), evidence (`file:line`, or a command and what it printed), a consequence someone hits in ordinary use at this repo's bar, and a component. Missing any one makes it a note.
- **note**: everything else worth saying. A breach the file scopes away from existing code (a Gate on an old component; the do-not-retrofit parts of §14, and §16 outside Loop Engine) is always a note that starts "when next touched:". In Loop Engine, a §16 breach in existing code is a finding to fix now, not a note.
- A heuristic finding (a size ratio, a mock count) states its threshold and why that threshold.
- Each finding ends with one fix sentence, or a deferral naming the trigger that would make it worth fixing. A fix that adds machinery the need does not require fails §4.
- Never quote a secret's value; cite `file:line` only.

Also list **removable machinery**: code, config, layers or checks that could be deleted with every required behaviour kept (§4, §12).

**7. Emit** the document below. Report its path and the three findings that matter most.

## Template

```markdown
# Design principles audit: <repo>

**Date:** <real ISO date>  **Commit:** <sha>  **Scope:** <what was audited>
**Bar:** <personal | shared> (<how found>)
**Principles file:** <path> sha256 <hash>

## Summary
<2–4 sentences: the state, the worst problem, what to do first.>

## Map
| Path | Kind | Layer by imports | Project term | Notes |
<Kind: component, composition, script or generated. Layer: domain, use cases, adapter, delivery, mixed, or none. Then one line on the Enforcement items.>

## Principles table
| § | Title (from the file) | Verdict | Evidence |
<One row per numbered section. Verdicts: pass, partial, fail, n/a, unknown (the repo cannot show it either way; say what record would). partial and unknown are specific to this audit. The verdict states the fact; a breach the file scopes away is still fail, and its finding is a "when next touched:" note (in Loop Engine, a §16 breach in existing code is a finding to fix now). Evidence: a short cell (`file:line`, the command run, "read", "sampled N of M", "ran"); details go in the findings, cited by id.>

## Findings
### F1. <short title>
- **Severity:** blocking | note
- **Obligation:** §<n> <title>: "<the sentence it breaks>"
- **Component:** <part of the system, in plain words>
- **Evidence:** <file:line, excerpt or command and output; detected by: analyzer / facts script / rg / log-probe / reading>
- **Consequence:** <what a user or the next maintainer hits>
- **Fix or deferral:** <one sentence; a deferral names its trigger>

## Removable machinery
<what could go, with every required behaviour kept, and the evidence it is unused or unneeded>

## Run versus read
<commands run and what they showed; verdicts that rest on reading alone; what could not run and why; tools recommended but not installed>

## Out of scope
<seen but not a principles matter (naming, formatting, local duplication: desloppify); drift between this skill and the principles file>
```

An audit with no findings still has every section, with `## Findings` empty.

## Mistakes to avoid

| Mistake | Instead |
|---|---|
| Listing the sections from memory or from this skill | Read the file each run; its numbering and titles are the table. |
| Citing a principle in general terms | Quote the sentence the code breaks. |
| Counting an empty edge list as "no cross-component imports" | Check `external_packages` and the analyzer's coverage first. |
| `fail` on §11 or §13 only because the repo holds no record | `unknown`: the record may live elsewhere. Say what record would settle it. |
| Demanding hardening at `personal` | §10 sets the bar; never committing secrets holds at both bars. |
| Editing code you found broken | Findings only. |
