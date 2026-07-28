# Design gate regression matrix

The `design-semantic` gate is judged by language models, so its behaviour cannot
be pinned by unit tests. This directory holds the documents that stand in for
them: a set of designs whose verdict is known, and a runner that re-measures all
of them against the deployed binary.

It exists to answer one question — **did this wording change break something that
used to work?** — without which every rubric edit is an argument from taste.

## Running it

    ./run.sh                       # every case, serially, ~2 min each
    ./run.sh good hollow-asserted  # named cases only

Exit status is 0 only when every case matched `expectations.tsv`. Artifacts and
raw replies land in `$SC_OUT` (default `$TMPDIR/sc-design-matrix`), so a
surprising verdict can be read afterwards:

    python3 report.py --reasons "$TMPDIR/sc-design-matrix/out-good.json"

Judge models come from the environment (`SC_JUDGE_MODEL`, `SC_DECIDER_MODEL`,
`SC_JUDGE_EXT`) rather than a checked-in config, because the matrix is a
measurement of the rubrics, not of one provider's availability. A judge that
returns no determinate verdict is retried once and then reported as
INDETERMINATE, which is not a pass; bridge timeouts are common enough that this
must be distinguished from a real failure.

## The cases

`intent.json` is the intent every case is judged against, and is the same
excerpt the static design guidance shows the author. Each case in `cases/` is a
`design.json` written against it. `expectations.tsv` records, for each, whether
the binding gate must pass or fail, which axis must carry a failure, and whether
that behaviour is settled or contested.

`enforced` rows are regressions if they flip. `contested` rows are current
behaviour that is deliberately under review — flipping one is a decision to be
made on purpose, and the row updated in the same change.

## The rule this directory exists to enforce

**A new rubric rule may only be added with a case that currently gets the wrong
verdict and that the rule fixes, and it must not flip any other row.**

Four rounds of adversarial review added rules faster than they were measured,
and two of them turned out to reject documents the gate exists to accept. A rule
argued from what *could* slip through, with no document that does, is how a gate
grows expensive without getting better.

## Cost

Each case is 6 model calls and roughly 2 minutes, plus the gap between cases and
any retry. Measured: two cases in 8.5 minutes, so the full matrix is roughly an
hour of wall clock and should be run once per rubric change, not
per edit. Deterministic schema and coverage rejections cost no model calls, so
`design-ready` behaviour belongs in the unit tests in `src/gates/design.rs`, not
here.
