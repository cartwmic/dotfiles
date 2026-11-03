"""Mutation check for the memory watchdog: break the daemon (or heavy-gate's report of its stop) one rule at a time and check that the test
named for the rule fails. Run by hand: python3 tests/heavy-gate/mutate_watchdog.py [substring of a mutation name]. Exit 1 if a mutant survives.

The mutants are copies; HEAVY_GATE_WATCHDOG_SCRIPT and HEAVY_GATE_SCRIPT point test_watchdog.py at them.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
FILES = {"d": (REPO / "dot_local/bin/executable_heavy-gate-watchdog", "HEAVY_GATE_WATCHDOG_SCRIPT"),
         "g": (REPO / "dot_local/bin/executable_heavy-gate", "HEAVY_GATE_SCRIPT")}
W = "test_watchdog.Watchdog."
# (file, what is broken, text, replacement, the test that must fail); text may be a list of (text, replacement) pairs.
# Not here: not ignoring SIGPIPE, and log() writing from the main shell instead of a subshell. Neither changes what the daemon does in these
# tests (bash 3.2 can leave a failed write's text in its buffer and flush it into a later $( ), but no test here could see it in the full
# daemon); the subshell and the trap stay as protection.
MUTANTS = [
    ("d", "one low reading stops", '[ "$lows" -ge 2 ] || continue', '[ "$lows" -ge 1 ] || continue', "test_a_single_low_reading_does_nothing"),
    ("d", "an unreadable reading counts as low", 'low() { number "$1" && awk', 'low() { ! number "$1" || awk', "test_an_unreadable_reading_does_nothing_and_breaks_a_run_of_low_ones"),
    ("d", "no KILL", '[ -z "$pids" ] || kill -KILL $pids 2>/dev/null || true', ":", "test_a_process_that_ignores_term_is_killed_after_the_grace_period"),
    ("d", "no TERM", '[ -z "$pids" ] || kill -TERM $pids 2>/dev/null || true', ":", "test_a_job_that_handles_term_runs_its_trap"),
    ("d", "no grace period", 'while [ "$t" -lt "$GRACE" ]; do', "while false; do", "test_a_job_that_handles_term_runs_its_trap"),
    ("d", "a child re-parented by its parent's death is forgotten", 'if ((x[1] in P) && I[x[1]] == x[2] && !(x[1] in have))', "if (0)",
     "test_a_child_whose_parent_died_on_term_is_still_killed"),
    ("d", "pid plus start time identity check removed", 'if ((x[1] in P) && I[x[1]] == x[2] && !(x[1] in have))', 'if ((x[1] in P) && !(x[1] in have))',
     "test_a_process_that_is_not_the_one_named_but_has_its_pid_is_not_signalled"),
    ("d", "gate_pid accepts any live pid", "    END { exit !ok }'\n}\n# start_of", "    END { exit 0 }'\n}\n# start_of",
     "test_a_forged_slot_link_to_any_other_process_is_not_followed_either"),
    ("d", "gate_pid accepts a second word that is the script (an editor)", 'if (b1 == "heavy-gate") ok = 1', 'if (b1 == "heavy-gate" || b2 == "executable_heavy-gate") ok = 1',
     "test_a_forged_slot_link_to_a_process_that_is_not_heavy_gate_is_not_followed"),
    ("d", "the daemon reads start times in the caller's zone and locale", 'start_of() { LC_ALL=C TZ=UTC0 ps -o lstart=', "start_of() { ps -o lstart=",
     "test_a_callers_time_zone_or_locale_does_not_hide_a_job_from_the_daemon"),
    ("g", "heavy-gate records its start time in the caller's zone and locale", 'GATE_START=$(LC_ALL=C TZ=UTC0 ps -o lstart=', 'GATE_START=$(ps -o lstart=',
     "test_a_callers_time_zone_or_locale_does_not_hide_a_job_from_the_daemon"),
    ("d", "waiting entries count as holders", '[ "$st" = running ] && printf', '[ -n "$st" ] && printf', "test_a_waiting_entry_is_not_a_holder_but_a_running_one_is"),
    ("d", "start time not required to match", '[ -z "$want" ] || [ "$(start_of "$1")" = "$want" ]', "true",
     "test_a_holder_whose_start_time_is_not_the_recorded_one_is_not_touched"),
    ("d", "always pick the first tree", 'if (best == "" || total > bestrss) {', 'if (best == "") {', "test_only_the_largest_tree_stops_while_memory_stays_low"),
    ("d", "lows not reset after a stop", "  lows=0\n  pick=", "  pick=", "test_after_a_stop_the_next_one_needs_two_more_low_readings"),
    ("d", "marker not written", '  write_marker "$h" "$reason"\n', "", "test_heavy_gate_says_the_watchdog_stopped_the_job_and_exits_137"),
    ("d", "marker written through a symlink", '  if [ -L "$m" ]; then log WARN "not writing $m: it is a symlink"; return 0; fi\n', "",
     "test_a_marker_that_is_a_symlink_is_not_written_through"),
    ("d", "heavy-gate itself is signalled", [('m = split(nxt[h], kids, " "); for (j = 1; j <= m; j++) Q[++tail] = kids[j]\n  while', 'm = split(h " " nxt[h], kids, " "); for (j = 1; j <= m; j++) Q[++tail] = kids[j]\n  while'),
                                              ('c = Q[head++]; if (c in seen || c == h) continue', 'c = Q[head++]; if (c in seen) continue')],
     "", "test_heavy_gate_says_the_watchdog_stopped_the_job_and_exits_137"),
    ("d", "an idle daemon looks for holders", "  any_trace || { lows=0; continue; }\n", "", "test_an_idle_daemon_forks_nothing_but_sleep"),
    ("d", "no heartbeat", 'beat() { [ -L "$HEARTBEAT" ] ||', "beat() { true ||", "test_the_daemon_rewrites_a_heartbeat_every_poll"),
    ("g", "a stop is not reported as 137", '  exit 137\nfi\nexit "$status"', '  exit "$status"\nfi\nexit "$status"', "test_heavy_gate_reports_a_stop_by_the_watchdog_and_exits_137"),
    ("g", "a job that exited 0 is reported as stopped", 'if [ "$status" -eq 0 ]; then', "if false; then", "test_a_job_that_exited_0_keeps_0_even_if_the_marker_is_there"),
    ("g", "an old marker is not removed at start", 'rm -f "$LOCK.stopped.$$"\nif ! watchdog_alive', "if ! watchdog_alive",
     "test_a_stale_marker_of_an_earlier_process_does_not_turn_the_exit_into_137"),
    ("g", "the marker is left behind", "unregister; rm -f \"$LOCK.stopped.$$\"' EXIT", "unregister' EXIT", "test_heavy_gate_reports_a_stop_by_the_watchdog_and_exits_137"),
    ("g", "a symlink marker is read", 'if [ -f "$LOCK.stopped.$$" ] && [ ! -L "$LOCK.stopped.$$" ]; then', 'if [ -f "$LOCK.stopped.$$" ]; then',
     "test_a_marker_that_is_a_symlink_is_not_written_through"),
    ("g", "no warning for a missing heartbeat", "if ! watchdog_alive; then", "if false; then", "test_heavy_gate_warns_when_the_heartbeat_is_missing_or_older_than_three_polls"),
    ("g", "a stale heartbeat is fine", '[ "$age" -le $((hb * 3)) ]', "true", "test_heavy_gate_warns_when_the_heartbeat_is_missing_or_older_than_three_polls"),
]


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    survived = 0
    for part, name, old, new, killer in MUTANTS:
        if only not in name:
            continue
        path, var = FILES[part]
        text = path.read_text()
        pairs = old if isinstance(old, list) else [(old, new)]
        bad = [o for o, _ in pairs if text.count(o) != 1]
        if bad:
            print(f"BAD MUTANT (text not found exactly once): {name}")
            survived += 1
            continue
        for o, n in pairs:
            text = text.replace(o, n)
        with tempfile.TemporaryDirectory() as tmp:
            mutant = Path(tmp) / path.name
            mutant.write_text(text)
            env = {**os.environ, var: str(mutant), "PYTHONDONTWRITEBYTECODE": "1"}
            proc = subprocess.Popen([sys.executable, "-m", "unittest", "-f", W + killer], cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    text=True, start_new_session=True)
            try:
                _, err = proc.communicate(timeout=240)
                failed = proc.returncode != 0
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, 9)
                _, err = proc.communicate()
                failed = True
        if not failed:
            survived += 1
        print(("killed   " if failed else "SURVIVED ") + f"{name}  [{killer}]", flush=True)
    print(f"{survived} survived")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
