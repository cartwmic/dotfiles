---
name: deriving-readable-docs
description: Use when you need one plain-English guide to any repo, whether or not it has tests, docs, a PRD or any ids. The code is the source; the repo's own words and its tests, when it has them, are evidence. Produces one file, GUIDE.md: Part 1 in plain English that a newcomer reads cold, then an appendix of surfaces, evidence and precise behaviours, each cited as `path:line` and checked by scripts and by fresh checker sessions. Not for reviewing a PR (review-map), not for a register of requirements with state machines and coverage gaps (distilling-requirements), not for designing a new smaller version (designing-the-smallest-version).
---

# Deriving readable docs

Turn any repo into one guide a person can read cold. Code is the source: what a sentence says about the product rests on the code line that defines it. The repo's own words (README, `docs/`, help text, comments) give intent and names. Tests are optional evidence: they confirm a behaviour when the repo has them, and nothing needs them.

Output: `GUIDE.md` in a folder outside the repo, default `~/.local/share/derived-docs/<repo-name>/`, or the caller's path. Part 1 is about 1,000 words of plain English, each sentence tagged `[A4.2]` to the appendix sentence it restates. Part 2 is the appendix: A1 surfaces and A2 evidence (printed by scripts), A3 the product as a whole, A4 and on one section per capability, A-last what nobody read.

Every mechanical step below is a script call. Agents write sentences and judge claims; scripts count, cut, join and score. `<skill>` is this skill's folder.

## Rules for every sentence

The cited lines must show everything the sentence says. `references/drafting.md` is the method the writers follow.

- One behaviour per sentence, at most 18 words, citations excluded. A longer one is split, and each part keeps its condition.
- Every claim ends with a citation in exactly this form: backticked `path/to/file.ext:LINE` or `path/to/file.ext:START-END`, relative to the repo root; several may share one pair of backticks. Cite the line that defines the behaviour, with its flags, branches and early exits. Nothing else in backticks may look like `word:number`.
- A claim that rests on a README, doc, comment or test title says so in the sentence ("README", "code comment", "in the test"). A claim taken from a name or the layout, without reading its body, is labelled **inferred**.
- A rule too long or spread out to read end to end is not described as a behaviour. State the surface only: "`--foo` takes a number (help text)".
- "No test covers X" is never written. `assemble.py` prints what tests cover.
- Add no security, privacy or threat sections unless the caller asks. No sentence about the document itself.

## Procedure

1. **Orient.** Record the repo name and `git rev-parse HEAD` (no git: say so). Make a work folder outside the repo. Read the README and `docs/` only for names and users.
2. **Surfaces.** Run `python3 -I <skill>/scripts/surfaces.py <repo> --json > surfaces.json`. It lists commands, flags, routes, config, entry points and the rest, each a real `path:line`. It misses registries, hand-parsed arguments and UI code. One scout session reads the README, `docs/` and `surfaces.json` and writes `scout.txt`: the capabilities a user would name, one per line, as the name appears in the code. Run `python3 -I <skill>/scripts/surfaces.py <repo> --resolve scout.txt > scout.resolved`. A name it cannot find is dropped.
3. **Tests, if any.** Run `python3 -I <skill>/scripts/harvest_points.py <repo> > points.json`. `assemble.py` reads it for A2: tests found, surfaces named in tests, surfaces never named. With no tests, the file is `[]` and A2 says so.
4. **Budgets.** Whole guide 6,000 words; Part 1 1,000; A3 600; A4 and on 3,900 shared by capability. Under 30k lines, halve all three. Printed rows are not counted.
5. **Frame and section writers.** One fresh session per writer, never one for the whole repo: a frame writer for A3 and one per capability for A4 and on, briefed as the last part of `references/drafting.md` says. Each audits its own sentences and runs `python3 -I <skill>/scripts/check_citations.py draft.md <repo> --max-words <budget> --max-sentence-words 18 --audit audit.md`. Load `no-ai-slop` in each writer.
6. **Part 1.** Put the appendix parts in the work folder as `A3.md`, `A4.md` and so on, then run `python3 -I <skill>/scripts/assemble.py <work> <repo> --index`. A separate front writer gets that index and nothing else, and writes `part1.md`.
7. **Assemble and gate.** `python3 -I <skill>/scripts/assemble.py <work> <repo> -o GUIDE.md --clean` prints the header, A1, A2 and A-last, joins the parts, and writes `GUIDE.clean.md` without tags. Then `python3 -I <skill>/scripts/lint_main.py GUIDE.md <repo> --surfaces surfaces.json` gates Part 1. Send every FAIL back to the front writer and assemble again.
8. **Check citations.** `python3 -I <skill>/scripts/check_citations.py GUIDE.md <repo> --max-words 6000 --max-sentence-words 18`. A missing line, a number or quoted name not in the cited lines, or a sentence over 18 words fails. Fix and rerun until it exits 0.
9. **Check every claim.** The script cannot tell whether a line supports a sentence. Run `python3 -I <skill>/scripts/slice.py GUIDE.md <repo> --out slices`. Start one fresh checker session per slice (not a writer), and hand it `references/check-brief.md` as written, its line range, the repo and its `slice-K.flags.txt`. Part 1 slices go in files named `part1-*.md` so the score keeps them apart. A fix takes the checker's own wording or cuts the sentence; only changed sentences go back to a fresh checker, until all HOLD.
10. **Score.** `python3 -I <skill>/scripts/score.py <name>=<reports folder> --doc GUIDE.md --repo <repo> --out score`. It checks each report's counts add up, then prints the rate, errors per 1,000 words, words per claim and claims by cause. The rate uses the checkers' claim count and prints any difference from the script's.
11. **Reader check.** Follow `references/reader-check.md`: a fresh reader sees Part 1 only (`python3 -I <skill>/scripts/score.py --reader GUIDE.md`), answers five questions with quotes, and `score.py --reader GUIDE.md --answers answers.md` verifies the quotes; a fresh grader marks the answers against the code. A guide that fails the pass bar there is not finished.
12. **Publish and report.** Publish to shartifacts (skill `using-shartifacts`) only when the caller says the guide is for Michael to review. Report the folder, the words against each budget, the score line, the reader-check result and what was not read.
