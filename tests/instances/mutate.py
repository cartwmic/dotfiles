"""Mutation check for the reconcile script: every mutation below must make the suite fail. Run: python3 tests/instances/mutate.py [substring of a mutation name]

Each mutation breaks one safety rule (see the header of the script). A mutation that the suite does not catch is a hole in the suite.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "dot_local" / "user_scripts" / "executable_instances_reconcile.sh"

MUTATIONS = [
    ("a changed unit restarts a running service without being asked", "reload_requested() {\n", "reload_requested() {\n  return 0\n"),
    ("opt-out acts on an instance dotfiles never started or adopted", '  if [ ! -f "$M_MANAGED" ]; then say "$NAME: not opted in"; return 0; fi\n', ""),
    ("an already-running service is bootstrapped again (adoption restarts it)", '  if [ "$LOADED" = no ]; then\n    printf', '  if true; then\n    printf'),
    ("opt-out deletes the instance state", '  rm -f "$M_MANAGED" "$M_SHA"', '  rm -rf "$STATE"; rm -f "$M_MANAGED" "$M_SHA"'),
    ("opt-out never boots the service out", 'if [ "$LOADED" = yes ]; then\n    if ! run_lc bootout', 'if [ "$LOADED" = nope ]; then\n    if ! run_lc bootout'),
    ("opt-out forgets the unit and markers even when bootout failed", 'unit and markers kept, will retry"; return 0; fi\n  fi', 'unit and markers kept, will retry"; fi\n  fi'),
    ("a setup script exit 3 is treated as success", '    3) _why=', '    3) return 0;;\n    9) _why='),
    ("a half-written config from a failed setup run is trusted on the next apply", '[ -f "$M_CONFIGURING" ] || ', ''),
    ("ownership is recorded only for adopted services, not for ones we start (R1)", '  if [ ! -f "$M_MANAGED" ]; then\n    if [ "$LOADED" = yes ]; then _adopted=yes', '  if [ ! -f "$M_MANAGED" ] && [ "$LOADED" = yes ]; then\n    if [ "$LOADED" = yes ]; then _adopted=yes'),
    ("opt-out reports success and drops ownership when the unit cannot be removed (R2)", 'if [ -e "$DST" ]; then finish "STOP FAILED: cannot remove', 'if false; then finish "STOP FAILED: cannot remove'),
    ("adoption records the unit as it is after replacement, not as it was loaded (R4)", '_own=$_before', '_own=$_want'),
    ("the setup script gets the caller's PATH, not the daemon's (R6)", 'env PATH="$TOOL_PATH:$PATH" RETRO', 'env RETRO'),
    ("a timed-out setup script leaves its children running (R7)", 'kill "TERM", -$pid; select(undef, undef, undef, 1); kill "KILL", -$pid;', 'kill "TERM", $pid; select(undef, undef, undef, 1); kill "KILL", $pid;'),
    ("the unit is installed even when the checkout is missing", '  if [ -n "$_miss" ]; then finish "NOT READY: missing$_miss"; return 0; fi\n', '  if [ -n "$_miss" ]; then mkdir -p "$AGENTS_DIR"; cp "$SRC" "$DST"; finish "NOT READY: missing$_miss"; return 0; fi\n'),
    ("a service that is not running is never started", '  if [ "$LOADED" = no ]; then\n    printf', '  if [ "$LOADED" = never ]; then\n    printf'),
    ("opt-out of a half-started instance stops whatever is loaded", '  if [ ! -f "$M_MANAGED" ]; then say "$NAME: not opted in"; return 0; fi\n', '  if [ ! -f "$M_MANAGED" ]; then run_lc bootout "$DOMAIN/$LABEL"; return 0; fi\n'),
    ("the reload switch reloads an instance whose unit did not change", '  _loaded_sha=$(cat "$M_SHA" 2>/dev/null || true)\n  if [ "$_loaded_sha" = "$_want" ]; then', '  _loaded_sha=$(cat "$M_SHA" 2>/dev/null || true)\n  if [ "$_loaded_sha" = "$_want" ] && ! reload_requested; then'),
]


def main():
    original = SCRIPT.read_text()
    survived = []
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    ran = 0
    for name, old, new in MUTATIONS:
        if only not in name:
            continue
        ran += 1
        if original.count(old) != 1:
            print("MUTATION DOES NOT APPLY (%d matches): %s" % (original.count(old), name))
            return 2
        with tempfile.TemporaryDirectory() as tmp:
            mutated = Path(tmp) / "mutated.sh"
            mutated.write_text(original.replace(old, new))
            env = dict(os.environ, INSTANCES_SCRIPT_UNDER_TEST=str(mutated))
            result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(HERE)], capture_output=True, text=True, env=env, timeout=900)
        failed = result.returncode != 0
        tail = [line for line in result.stderr.splitlines() if line.startswith("FAIL:") or line.startswith("ERROR:")]
        print("%s  %s%s" % ("CAUGHT  " if failed else "SURVIVED", name, ("  (%d tests failed)" % len(tail)) if failed else ""))
        if not failed:
            survived.append(name)
    print("\n%d mutations, %d caught, %d survived" % (ran, ran - len(survived), len(survived)))
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
