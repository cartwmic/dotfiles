"""Mutation check for the central-rank part of heavy-gate: break one rule at a time; the rank tests must fail each time.

    python3 tests/heavy-gate/mutate.py

Not part of CI. It proves the tests pin every rule of resolve_priority and rank_on rather than just exercising them.
Only the tests that name the rank run for each mutant (the whole suite takes minutes); the full suite runs unmutated in CI/by hand.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "dot_local/bin/executable_heavy-gate"
SELECT = ["-k", "rank", "-k", "reader", "-k", "workstream"]

ENV_LINE = 'if [ -n "${HEAVY_GATE_PRIORITY:-}" ]; then printf \'%s\' "$HEAVY_GATE_PRIORITY"; return 0; fi\n  base=0'
SHOW = 'rank_on() { rk=$(rank_read show) && [ -n "$rk" ]; }'
MAPPED = '    if [ -n "$r" ]; then r=$(cap "$r"); if [ "$r" -lt "$UNRANKED" ]; then printf \'%s\' "$r"; return 0; fi; fi'

MUTATIONS = [
    ("the rank is never used", '  if rank_on; then\n    r=$(rank_read of', '  if false; then\n    r=$(rank_read of'),
    ("the environment no longer beats the rank", ENV_LINE, 'base=0'),
    ("rank is on without a valid file", SHOW, 'rank_on() { true; }'),
    ("rank is never on", SHOW, 'rank_on() { false; }'),
    ("a rank of 1000 counts as a workstream", '[ "$r" -lt "$UNRANKED" ]', '[ "$r" -le "$UNRANKED" ]'),
    ("every ranked job is unmapped", '[ "$r" -lt "$UNRANKED" ]', '[ "$r" -lt 0 ]'),
    ("no offset for jobs with no workstream", '    base=$UNRANKED\n', '    base=0\n'),
    ("offset is 100, not 1000", 'UNRANKED=1000 ', 'UNRANKED=100 '),
    ("offset is applied when the rank is off", 'base=0\n  if rank_on', 'base=$UNRANKED\n  if rank_on'),
    ("rules ignored after the stack", 'r=$(cap "${r:-$DEFAULT_PRIORITY}")', 'r=$(cap "$DEFAULT_PRIORITY")'),
    ("leading zero read as octal", '  r=${r#"${r%%[!0]*}"}   # no leading zeros', '  : # no leading zeros'),
    ("offset number not capped", '  cap "$((base + ${r:-0}))"', '  printf \'%s\' "$((base + ${r:-0}))"'),
    ("a non-number from the reader is used", "case $r in '' | *[!0-9]*) r= ;; esac", "case $r in '') r= ;; esac"),
    ("the reader's stderr reaches the gate's", '"$RANK_TIMEOUT" workstream-rank "$@" 2>/dev/null', '"$RANK_TIMEOUT" workstream-rank "$@"'),
    ("the reader is never cut off", 'alarm $t;', 'alarm 0;'),
    ("only the reader's shell is killed, not its children", 'sub { kill 9, -$p;', 'sub { kill 9, $p;'),
    ("the reader is not in its own group", 'if (!$p) { setpgrp(0, 0); exec @ARGV; exit 127 }\n    setpgrp($p, $p);', 'if (!$p) { exec @ARGV; exit 127 }'),
    ("the timeout is ignored", '"$RANK_TIMEOUT" workstream-rank', '30 workstream-rank'),
    ("a bad timeout, 0 or 00 is used as it is", '[ "$RANK_TIMEOUT" -gt 0 ] 2>/dev/null || RANK_TIMEOUT=2', ':'),
    ("a child left behind by an exited reader is not killed", 'my $s = $?; kill 9, -$p;', 'my $s = $?;'),
    ("a failed reader's status is lost", "exit($s == 0 ? 0 : ($s >> 8) || 1)", "exit 0"),
    ("a failed of's rank is used", 'r=$(rank_read of) || r=', 'r=$(rank_read of) || :'),
    ("a failed show counts as a valid file", 'rk=$(rank_read show) && [ -n "$rk" ]', 'rk=$(rank_read show); [ -n "$rk" ]'),
    ("a ranked job is off by one", MAPPED, MAPPED.replace('"$r"; return', '"$((r + 1))"; return')),
    ("priorities always says on", "  if rank_on; then printf 'central rank: on", "  if true; then printf 'central rank: on"),
    ("priorities always says off", "  if rank_on; then printf 'central rank: on", "  if false; then printf 'central rank: on"),
]


def main():
    text = SCRIPT.read_text()
    survived = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, old, new in MUTATIONS:
            if text.count(old) != 1:
                sys.exit(f"mutation {name!r}: pattern found {text.count(old)} times, want 1")
            mutant = Path(tmp) / "mutant"
            mutant.write_text(text.replace(old, new))
            env = {**os.environ, "HEAVY_GATE_SCRIPT": str(mutant), "PYTHONDONTWRITEBYTECODE": "1"}
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(HERE), "-p", "test_heavy_gate.py", *SELECT], env=env,
                               capture_output=True, text=True)
            killed = r.returncode != 0
            print(("killed  " if killed else "SURVIVED"), name, flush=True)
            if not killed:
                survived.append(name)
    print(f"{len(MUTATIONS) - len(survived)}/{len(MUTATIONS)} mutations killed")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()
