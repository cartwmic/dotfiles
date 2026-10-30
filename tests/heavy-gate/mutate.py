"""Mutation check for heavy-gate: break one rule at a time; the tests for that part must fail each time.

    python3 tests/heavy-gate/mutate.py [rank|gate]      (both by default; MUTATE_ONLY=text runs the mutations whose name has it)

Not part of CI. It proves the tests pin every rule rather than just exercising them:
  rank  resolve_priority and rank_on (the central workstream rank);
  gate  the admission rules: the two kept memory-pressure checks (each broken in turn), and the three removed checks
        (load1, the swap floor, Swapouts), each put back, which the "no longer gates" tests must catch.
Only the tests for that part run for each mutant, and the first failure stops the run (the whole suite takes minutes); the full
suite runs unmutated in CI/by hand.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "dot_local/bin/executable_heavy-gate"
SELECT = {
    "rank": ["-k", "rank", "-k", "reader", "-k", "workstream"],
    "gate": [arg for name in ("test_each_rule", "test_level_2", "test_the_edges", "test_the_removed", "test_a_host_that", "test_a_check_says", "test_the_usage_text",
                              "test_a_third_start", "test_every_rule_still", "test_every_broken_rule", "test_waits_for", "test_does_not_run",
                              "test_the_two_readings", "test_starts_do_not_share", "test_a_bad_window") for arg in ("-k", name)],
}

ENV_LINE = 'if [ -n "${HEAVY_GATE_PRIORITY:-}" ]; then printf \'%s\' "$HEAVY_GATE_PRIORITY"; return 0; fi\n  base=0'
SHOW = 'rank_on() { rk=$(rank_read show) && [ -n "$rk" ]; }'
MAPPED = '    if [ -n "$r" ]; then r=$(cap "$r"); if [ "$r" -lt "$UNRANKED" ]; then printf \'%s\' "$r"; return 0; fi; fi'

RANK_MUTATIONS = [
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

PRESSURE = '  v=$(pressure_level); level_ok "$v"                      || {'
MAXLEVEL = "MAX_PRESSURE_LEVEL=2  #"
LEVEL_OK = "level_ok() { case $1 in '' | *[!0-9]*) return 1 ;; esac; awk -v v=\"$1\" -v m=\"$MAX_PRESSURE_LEVEL\" 'BEGIN { exit !(v + 0 >= 1 && v + 0 <= m + 0) }'; }"
MEMORY = '  v=$(mem_free_pct);   meets "$v" ge "$MEM_FREE_MIN_PCT"  || {'
TRY = "  if memory_rules && wait_window && memory_rules && {"
BROKEN0 = "  broken=0\n" + PRESSURE
WAIT = '  sleep "$CHECK_WINDOW" || { refuse "could not wait out the ${CHECK_WINDOW}s check window"; return 1; }'
# the three removed checks, as they were before this change
LOAD_BACK = ('  broken=0\n  v=$(sysctl -n vm.loadavg 2>/dev/null | awk \'{print $2}\'); meets "$v" lt 8 || { refuse "load1 ${v:-unreadable} (needs < 8)"; broken=1; }\n'
             + PRESSURE)
SWAP_BACK = ('  broken=0\n  v=$(sysctl -n vm.swapusage 2>/dev/null | awk \'{for (i = 1; i <= NF; i++) if ($i == "free") { v = $(i + 2); if (v !~ /^[0-9]+(\\.[0-9]+)?[KMG]$/) next; '
             'u = substr(v, length(v)); n = substr(v, 1, length(v) - 1) + 0; if (u == "G") n *= 1024; else if (u == "K") n /= 1024; printf "%d", n } }\'); '
             'meets "$v" ge 500 || { refuse "swap free ${v:-unreadable} MB (needs >= 500)"; broken=1; }\n' + PRESSURE)
SWAPOUTS_BACK = ('  a=$(vm_stat | awk \'/^Swapouts:/ {sub(/\\.$/, "", $2); print $2}\'); sleep "$CHECK_WINDOW"; b=$(vm_stat | awk \'/^Swapouts:/ {sub(/\\.$/, "", $2); print $2}\')\n'
                 '  [ "$a" = "$b" ] || { refuse "Swapouts rose over ${CHECK_WINDOW}s (the machine is swapping)"; return 1; }')

GATE_MUTATIONS = [
    ("the pressure level is not checked", PRESSURE, '  v=$(pressure_level); true || {'),
    ("level 2 refuses again (the rule before 2026-10-30)", MAXLEVEL, "MAX_PRESSURE_LEVEL=1  #"),
    ("level 3 is admitted", MAXLEVEL, "MAX_PRESSURE_LEVEL=3  #"),
    ("level 4 (critical) is admitted", MAXLEVEL, "MAX_PRESSURE_LEVEL=4  #"),
    ("level 0 is admitted", LEVEL_OK, LEVEL_OK.replace("v + 0 >= 1 &&", "v + 0 >= 0 &&")),
    ("a level that is not a whole number is read as one", LEVEL_OK, LEVEL_OK.replace("'' | *[!0-9]*) return 1", "'') return 1")),
    ("an unreadable pressure level counts as normal", PRESSURE, PRESSURE.replace('level_ok "$v"', 'level_ok "${v:-1}"')),
    ("memory free is not checked", MEMORY, '  v=$(mem_free_pct);   true || {'),
    ("memory free must be above 30%, not at it", ': v + 0 >= l + 0)', ': v + 0 > l + 0)'),
    ("memory free needs only 20%", "MEM_FREE_MIN_PCT=30", "MEM_FREE_MIN_PCT=20"),
    ("memory free needs 31%", "MEM_FREE_MIN_PCT=30", "MEM_FREE_MIN_PCT=31"),
    ("an unreadable memory free counts as fine", MEMORY, '  v=$(mem_free_pct);   meets "${v:-100}" ge "$MEM_FREE_MIN_PCT"  || {'),
    ("the first reading is skipped", TRY, "  if wait_window && memory_rules && {"),
    ("the second reading is skipped", TRY, "  if memory_rules && wait_window && {"),
    ("the readings are not apart", WAIT, '  sleep 0 || { refuse "x"; return 1; }'),
    ("the readings are 60 seconds apart", "CHECK_WINDOW=${HEAVY_GATE_CHECK_WINDOW:-20}", "CHECK_WINDOW=${HEAVY_GATE_CHECK_WINDOW:-60}"),
    ("the check mode does not say the rule", '  log INFO "check: a start is admitted on memory pressure only', '  : log INFO "check: a start is admitted on memory pressure only'),
    ("the load1 check is back", BROKEN0, LOAD_BACK),
    ("the swap floor is back", BROKEN0, SWAP_BACK),
    ("the Swapouts check is back", WAIT, SWAPOUTS_BACK),
]


def main():
    which = sys.argv[1:] or ["rank", "gate"]
    mutations = {"rank": RANK_MUTATIONS, "gate": GATE_MUTATIONS}
    if any(w not in mutations for w in which):
        sys.exit("usage: mutate.py [rank|gate]")
    text = SCRIPT.read_text()
    survived = []
    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        for part, name, old, new in [(w, *m) for w in which for m in mutations[w]]:
            if os.environ.get("MUTATE_ONLY") and os.environ["MUTATE_ONLY"] not in name:
                continue
            total += 1
            if text.count(old) != 1:
                sys.exit(f"mutation {name!r}: pattern found {text.count(old)} times, want 1")
            mutant = Path(tmp) / "mutant"
            mutant.write_text(text.replace(old, new))
            if subprocess.run(["sh", "-n", str(mutant)], capture_output=True).returncode != 0:
                sys.exit(f"mutation {name!r} is not valid shell, so a failure would prove nothing")
            env = {**os.environ, "HEAVY_GATE_SCRIPT": str(mutant), "PYTHONDONTWRITEBYTECODE": "1"}
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(HERE), "-p", "test_heavy_gate.py", "-f", *SELECT[part]], env=env,
                               capture_output=True, text=True)
            killed = r.returncode != 0
            print(("killed  " if killed else "SURVIVED"), name, flush=True)
            if not killed:
                survived.append(name)
    print(f"{total - len(survived)}/{total} mutations killed")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()
