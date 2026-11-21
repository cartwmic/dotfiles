# Agent record: deriving-readable-docs

Branch `readable-docs-recall-climb`, bar `cartwmic/dotfiles = personal`. No PR is open. This file is under `docs/`, which chezmoi does not deploy.

## Coverage pass and repair to 98% (builder, Sonnet 5.5 high)

What changed: a coverage pass in the skill (one lister, one grader, `scripts/coverage.py`, writers who add what is missing), run after round-1 assembly and again on the shipped draft; a full-guide precision check as a repair step; the final grade measured last. Steps are now 1 to 16.

| Step | What | Where |
|---|---|---|
| 8 | Coverage (first): lister, grader, `coverage.py --label first`, writers add, assemble and gate again | `SKILL.md`, `references/coverage.md` |
| 12 | Coverage (repair): fresh grader, same `facts.txt`, `--label repair`, add what is missing | same |
| 13 | Full check of the whole guide, repair rule (add the condition; cut only a wrong claim no true version helps), `GUIDE.full.cut.md` kept | `SKILL.md`, `references/fix-rounds.md` |
| 15 | Final re-check, `--was GUIDE.full.cut.md`: every new or changed line, coverage lines included | `SKILL.md`, `references/fix-rounds.md` |
| 16 | Final grade (`--label final --min 98`), then report | `SKILL.md` |

New files: `scripts/coverage.py`, `references/coverage.md`, `references/coverage-lister.md`, `references/coverage-grader.md`, `tests/deriving-readable-docs/test_coverage.py`.

### Proof

| Claim | Evidence | Kind |
|---|---|---|
| The skill's tests pass | `python3 -I -m unittest discover -s tests/deriving-readable-docs -p 'test_*.py'`: 539 tests before, 591 after (52 new, all in `test_coverage.py`), OK | ran |
| `coverage.py` turns a grade file into a to-do and a record | dry run on a hand-made repo, facts and grades (one grade row with a note after the quote): `first: 5 facts, covered 1, partial 1, missing 3: 20.0% covered ...`, `BELOW 98%` exit 1, to-do grouped by section with a `Files:` line, the core facts and Part 1 room, `coverage.md` row; a rerun of the same label was refused | ran |
| The new tests can fail | six breaks of `coverage.py` (skip the quote check, allow a label twice, count PARTIAL as covered, parse a grade note into the quote, key sections by heading, keep citations in a quote) each failed the tests; script restored | ran |
| Bugs found by driving the script with brief-shaped input | a cite to line 41 of a 40-line file passed (trailing newline counted as a line); a grade row with a note after the quote lost its quote; a fact could be sent to a gathered table section that has no file; a quote that left out a mid-line citation did not match. All fixed, each with a test | ran |
| The lister, grader and writer sessions work as written | not run: the briefs and the steps were read and tested for wiring only. A real climb run is the first proof | assumed |
| The Part 1 guard holds on a real guide | not run on a real guide; `coverage.py` reports Part 1 words by `lint_main`'s own count (test asserts the two agree) and the existing `lint_main.py` gate is unchanged | tested, not driven |

The tests ran locally (about 30 s): `kgate.toml` lists only the heavy-gate and workstream-rank suites. GitHub CI's `tests` job (`scripts/ci-linux.sh`) runs `tests/deriving-readable-docs` on a pull request, but no PR is open, so there is no CI receipt yet. This is not a `heavy-gate` job.

### Design principles

| Principle | Result | Evidence |
|---|---|---|
| 1 Composable components | pass | `coverage.py` does one job (facts + grades + guide to to-do and record); other scripts unchanged; reused `claims.py` and `lint_main.WORDS_MAX` |
| 2 Kernel and adapters | pass (n/a) | a stdlib CLI in a skill; no runtime or transport to separate |
| 3 Clean architecture | pass (n/a) | small script: pure functions (`read_facts`, `verify`, `build`, `todo_text`) and one `record` writer; scaled to size per §4 |
| 4 YAGNI and KISS | pass | one script, no merge helper (writers put lines into section files; `assemble.py` already refuses a bad block); `--facts` is the only extra mode and exists to stop a bad list before a grader runs |
| 5 Contracts and invariants | pass | the row formats are written in the script docstring and the two briefs; a label is recorded once; each fact has one row |
| 6 Conformance suites | n/a | no adapters |
| 7 No cross-component imports | pass | imports only the skill's own `claims.py` and `lint_main.py`, as sibling scripts already do |
| 8 Judgment in agents, mechanism in code | pass | what counts as COVERED, PARTIAL or core is decided by the grader and lister prompts; the script counts, checks that quotes and cites exist, and lists |
| 9 Fix the cause; no arbitrary caps | pass | the 1,000-word coverage allowance is a stated budget line (logged), not a cover for a defect; `--min` is the owner's 98% target, an option |
| 10 Good enough (personal) | not cited | no shortcut taken on this basis |
| 11 Prior art | pass | extends the existing checker, `slice.py` and `final_recheck.py` flow; no new library |
| 12 Verified from the outside | partial | script driven through its CLI end to end and mutation-checked; the LLM sessions were not run (see Proof) |
| 13 Intent tensions | pass | the goal "keep Part 1 plain and short while recall rises" is handled by the core-only Part 1 rule, the word room figure and the drop-first rule; the budget conflict is logged |
| 14 Logs that replay | n/a | no acting component; the record (`coverage-<label>.json`, `coverage.md`) lists each grade |
| 15 Fast proof | pass | 52 new tests run in under 1 s; the suite takes about 30 s |
| 16 Built to last | pass | the old "no full final check" test was rewritten, not bypassed; steps renumbered so lists render; every doc that named a step number was updated |

### Harness note (playbook 096ec3a0)

The skill is canonical and is linked into Claude Code, Cursor and Pi by the existing skill link step; nothing here is Claude-only.

Decisions: #5138 #5139 #5140
