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
    ("an already-running service is bootstrapped again (adoption restarts it)", '  if [ "$LOADED" = no ]; then\n    if ! run_lc bootstrap', '  if true; then\n    if ! run_lc bootstrap'),
    ("opt-out deletes the instance state", '  rm -f "$DST" "$M_MANAGED"', '  rm -rf "$STATE"; rm -f "$DST" "$M_MANAGED"'),
    ("opt-out never boots the service out", 'if [ "$LOADED" = yes ]; then\n    if ! run_lc bootout', 'if [ "$LOADED" = nope ]; then\n    if ! run_lc bootout'),
    ("opt-out forgets the unit and markers even when bootout failed", 'unit and markers kept, will retry"; return 0; fi\n  fi', 'unit and markers kept, will retry"; fi\n  fi'),
    ("a setup script exit 3 is treated as success", '    3) _why=', '    3) return 0;;\n    9) _why='),
    ("the setup script runs on every apply, not once", '  if [ ! -f "$M_SEEDED" ]; then\n    if [ ! -f "$STATE/config.json" ]; then configure || return 0; fi', '  if true; then\n    configure || return 0'),
    ("a bootstrap failure still marks the instance managed", '    if ! run_lc bootstrap "$DOMAIN" "$DST"; then finish "NOT READY: launchctl bootstrap failed', '    : >"$M_MANAGED"\n    if ! run_lc bootstrap "$DOMAIN" "$DST"; then finish "NOT READY: launchctl bootstrap failed'),
    ("the unit is installed even when the checkout is missing", '  if [ -n "$_miss" ]; then finish "NOT READY: missing$_miss"; return 0; fi\n', '  if [ -n "$_miss" ]; then mkdir -p "$AGENTS_DIR"; cp "$SRC" "$DST"; finish "NOT READY: missing$_miss"; return 0; fi\n'),
    ("a service that is not running is never started", '  if [ "$LOADED" = no ]; then\n    if ! run_lc bootstrap', '  if [ "$LOADED" = never ]; then\n    if ! run_lc bootstrap'),
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
