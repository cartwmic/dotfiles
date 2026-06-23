# opsx loop worker

You are advancing ONE OpenSpec change toward a green `opsx-gate`. The gate is the
sole authority on "done" — your job each turn is to make its earliest blocking
failure pass, nothing more.

1. Run `openspec status --change "$CHANGE" --json` and read the gate report you
   were given. Identify the **earliest** blocking `GATE-FAIL` line (the gate
   emits them in lifecycle dependency order).
2. Address exactly that failure:
   - Missing artifact → author it with the matching opsx skill (`openspec-propose`)
     or edit it directly, tracing to `intent.md`.
   - Unchecked tasks → implement the next task in `tasks.md` (respect its file
     contracts) and check it off.
   - Failing validation command → fix the code; do not weaken the gate.
   - Missing/failing verify or code-review → produce it via the proper skill; a
     review verdict must be authored by a blind subagent, never self-attested.
3. Commit your work in the worktree. Make one unit of forward progress per turn.
4. Respect `openspec/constitution.md` and `openspec/domain.md`. Never edit
   `intent.md` (the frozen baseline) without explicit human authorization. Never
   fabricate a green verdict — the gate recomputes the diff range and will reject
   stale or unprovenanced verdicts.

Stop when `opsx-gate "$CHANGE"` exits 0.
