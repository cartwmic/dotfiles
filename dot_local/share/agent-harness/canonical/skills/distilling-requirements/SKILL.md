---
name: distilling-requirements
description: Use when you need to know what a repo is required to do, from its code, tests, docs and behavior, not from a diff. Produces one REQUIREMENTS.md with a requirements register (explicit and implicit, product, behavioral and technical), the repo's state machines and invariants, invariants it relies on but never enforces, reachable invalid states with evidence, and which test covers each requirement. Use for backfilling a PRD, auditing an unfamiliar or agent-written repo, or finding hidden bugs. Not for reviewing a PR (review-map), not for a Loop Engine PRD candidate (using-generate-prd), not for designing.
---

# Distilling Requirements

Read a repo and write down what it must do, including what nobody wrote down, with evidence for every line and the test that covers it. The output is one file in a fixed shape ([references/output-shape.md](references/output-shape.md)) so a person, another skill or a later run reads it the same way.

**How it differs from neighbours.** `using-generate-prd` drives a Loop Engine research run to a schema-valid `LE-n` PRD candidate; it needs the engine and covers product obligations only. `review-map` explains a diff. This skill needs only the repo, covers three lenses, and adds state machines, unenforced invariants and test-coverage gaps. Its register can seed a PRD candidate later; it mints no `LE-n` ids.

## Inputs

- Repo path (required), optionally a scope. For a repo over ~20k lines, scope it. Scope means the named files, their first ring of callees, and the callers that write the state you model; list both in the header `scope:`, and write `path (lines)` for a callee you read only in part. Never silently sample.
- Output path. Default: a scratch folder outside the repo. Write inside the repo only if asked.
- Record the commit SHA at the start. At the end run `git diff --stat <sha> -- <scope paths>`; if the scope moved, re-read what changed and say so in the header. With no git history (an archive), set `source: archive` in the header instead.
- Read the repo's own docs and `AGENTS.md`/`CLAUDE.md` first.
- A scope path that does not exist: say so in the header and an open question; write no rows from it.
- Depth: this is a first pass. Read test bodies for the rows that matter most (high impact, or ones a finding rests on) and judge the rest `title`. Stop when new reads stop producing new rows; merge rows that share one source and one check.

## Rules for every row

- **Evidence or it does not go in.** Cite `path:line` you opened. Never infer from a name.
- **Outcome, not mechanism.** Write each requirement as what the user or caller needs, not as how the code does it. A row that restates the code can never be violated, so buggy code passes as "intended". Treat "by design" as a claim to check against stated intent (docs, PRD, names, error text), not a reason to drop a finding; if intent is unstated, ask a Q.
- **One obligation per row.** If a check covers only one clause of a row, `fit` is `partial`; split a row that joins two obligations.
- **Code vs intent.** A behavior only the code shows is `implicit`. A stated source (doc, contract, test name, comment, issue, the owner) makes it `explicit`; name the source kind in `note` when it is only a comment or a test title. Status is `proposed` until the owner accepts it; never set `accepted` yourself.
- **Enduring or incidental.** Do not promote every implementation detail to a requirement. Mark `durability`, and use `unclear` plus an open question when you cannot tell.
- **Conflicts stay visible.** If doc, test and code disagree, write one row per claim, status `disputed`, and leave the choice to the owner.
- **Say what you did not read**, including test bodies you judged from titles (`fit: title`).
- **One fact, one table.** Link by id (`I-3`, `F-2`) instead of repeating it. If you looked at something and found it intentional, say so in `note` or an open question.

## Procedure

1. **Orient.** Entry points, docs, tests, config, schema, and how tests run. Run only what is cheap and safe; heavy jobs go where the owner says.
2. **Explicit requirements.** Pull stated obligations from docs, README, `AGENTS.md`, issue text, CLI help, schemas, contracts, test names and assertions. One row each, as an observable "shall" sentence.
3. **Product lens.** Who uses this, for what outcome; the user-visible journeys, inputs, outputs, and what a user would call broken.
4. **Behavioral lens: state machines.** Trevin Chow's prompt, word for word:

   > Find the app's explicit and implicit state machines and document their states, invariants, and transition tables in one file. Identify invalid states or transitions the code can actually reach, with evidence, including through retries and concurrency. Prioritize confirmed bugs by impact, group related fixes into issues, then fix them with regression tests and keep the document updated.

   This step does its first two sentences. Sentences three and four are "Acting on findings" below.

   Look for status/phase/enum fields, booleans that combine into a mode, lifecycle columns, queues, retries, locks, caches, and "if X then skip" guards. For each machine write its states, invariants and transition table, and list every process or caller that writes the state and whether each uses a stale-write guard. Then walk the code for transitions the table does not allow but the code can reach: a retry repeating a side effect, two writers racing, a crash between two writes, a read-then-write with no guard, a state with no way out, a startup migration that checks then changes (a second process can run between the two). A finding is `confirmed` only with a reproducible path or an unambiguous code path, after you have read the callee that would do the write (not just the caller); `likely` when the code path is certain but a library's or system's behavior is assumed; otherwise `suspected`.
5. **Technical lens.** Constraints the code depends on: runtime and versions, storage and schema, layering and import rules, interfaces to other systems, limits, configuration. Source: manifests, build/CI config, boundary tests, comments.
6. **Unenforced invariants.** Find every invariant the repo relies on but does not explicitly enforce: a consumer that assumes a field is set, ordered, unique, non-empty or in a range, with no type, check, constraint or test that makes it so. Check both directions: a consumer that trusts a value nothing guarantees, and a validator stricter or looser than the values the system really produces (ids, names, paths: compare every boundary check against real examples in tests, fixtures, docs and other components). Give the place that relies on it, the missing guard, and whether a violation is reachable. If it is reachable and does harm, also add an `F` row that cites the `U` id.
7. **Coverage per requirement.** For each register row, name the check that covers it (test, type, schema, CI gate; at most three, `+N more` if more) and compare what it asserts with what the requirement says. `full`, `partial` (name what is not asserted in `note`, for example "requirement: title or description; test: title only"), `none`, or `title` (judged from the test name; bodies not read). Set `enforced` from the code, apart from tests, and judge only the row's own claim: `yes` means the code makes the claim hold on every path that can break it; a different writer skipping the mechanism is a separate row or an F row, not `partial` here.
8. **Write the file** in the shape in [references/output-shape.md](references/output-shape.md), then run `python3 -I <skill dir>/scripts/check_shape.py REQUIREMENTS.md`. Fix what it reports and rerun until it prints `ok`. It checks structure only, not truth.
9. **Report** in plain words: counts by lens and kind, the top findings by impact, the biggest coverage gaps, and what you did not read.

## Acting on findings

Stop after step 9 unless asked. When asked to act (sentences three and four of the prompt): group related findings into issues, fix confirmed ones with a regression test that fails before the fix, and update the file (status, coverage, changelog). Confirm before opening issues or pushing.
