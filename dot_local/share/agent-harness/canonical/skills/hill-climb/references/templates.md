# Card and report layouts

- [The card](#the-card)
- [The report](#the-report)

## The card

Send it as Markdown, not in a code block, so it renders.

> ### Climb card: `build-speed`
> **Goal:** cold build of the app 2x faster, same output
>
> | Score | Now | Bar |
> | --- | --- | --- |
> | Median build seconds, lower is better | **47.0s** | **23.5s** (2x) |
>
> | Setting | Recommended | Default | Why |
> | --- | --- | --- | --- |
> | Check | `./scripts/bench-build.sh` | none | Builds from clean, prints seconds |
> | Kit | new | none | No saved kit fits |
> | Runs per score | **3** | 1 | Score drifts 1.2s between runs |
> | Paired | **yes** | no | Shared machine, so old and new run in turns |
> | Min gain | **3%** | 0 | Above the drift, so luck can't win |
> | Guards | `npm test`, `npm run typecheck` | none | Faster must still be correct |
> | Holdout | 3 of the 12 sample apps | none | Catches overfitting |
> | Locked | `scripts/bench-build.sh`, `test/`, `samples/` | none | So no step can edit the check |
> | Timeout | 1800s | 1800s | |
> | Budget | no limit | no limit | About 2 min a step, so 40 steps is about 1.5 hours |
> | After the bar | **stop** | stop | |
> | Branch | `climb/build-speed` | `climb/<name>` | One commit per kept step |
>
> **Needs your answer:** none
>
> Reply **go** to start, or change a line, like "runs 5".

## The report

A headline, one table, short bullets, no paragraphs.

> ### Climb `build-speed`: bar reached
> **47.1s → 18.7s**, 2.5x faster (bar 23.5s, reached at step 41)
>
> | | |
> | --- | --- |
> | Holdout | 51.0s → 20.2s, moved with the score |
> | Steps | 19 kept of 52 |
> | Safety | Guards passed on every kept step. Full suite and final review clean |
> | Time | 1h 50m, about 2 min a step |
> | Branch | `climb/build-speed`, 19 commits |
>
> **What worked**
> - Incremental type cache: −12s
> - Parallel emit: −9s
>
> **Tried and undone** (never landed)
> - swc swap: broke 3 guards
>
> **Your move**
> - Review: `git log --oneline 1a2b3c4..climb/build-speed`
> - Next climb: cache `node_modules` in the bench (check 2 min → about 35s)
