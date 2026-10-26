"""Mutation check: every mutation below must make the suite fail. Run: python3 tests/instances/mutate.py [substring of a mutation name]

Each mutation breaks one rule of the reconcile script (see its header) or of a source file that feeds it (the work unit template, the wrapper,
.chezmoiignore). A mutation that the suite does not catch is a hole in the suite. Script mutations run against a temporary copy of the script
(INSTANCES_SCRIPT_UNDER_TEST); the others edit the file in place for the duration of the run and always restore it.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "dot_local" / "user_scripts" / "executable_instances_reconcile.sh"

ROOT = HERE.parents[1]
IGNORE = ".chezmoiignore"
WRAPPER = "run_after_75_instances_reconcile.sh.tmpl"
WORK_UNIT = "dot_local/share/instances/launchd/local.coordinatord.work.plist.tmpl"

# (name, old text, new text[, file relative to the repo root; default: the reconcile script])
MUTATIONS = [
    ("a changed unit restarts a running service without being asked", "reload_requested() {\n", "reload_requested() {\n  return 0\n"),
    ("opt-out acts on an instance dotfiles never started or adopted", '  if [ ! -f "$M_MANAGED" ]; then say "$NAME: not opted in"; return 0; fi\n', ""),
    ("an already-running service is bootstrapped again (adoption restarts it)", '  if [ "$LOADED" = no ]; then\n    if ! printf', '  if true; then\n    if ! printf'),
    ("opt-out deletes the instance state", '  rm -f "$M_MANAGED" "$M_SHA"', '  rm -rf "$STATE"; rm -f "$M_MANAGED" "$M_SHA"'),
    ("opt-out never boots the service out", 'if [ "$LOADED" = yes ]; then\n    if ! run_lc bootout', 'if [ "$LOADED" = nope ]; then\n    if ! run_lc bootout'),
    ("opt-out forgets the unit and markers even when bootout failed", 'unit and markers kept, will retry"; return 0; fi\n  fi', 'unit and markers kept, will retry"; fi\n  fi'),
    ("a setup script exit 3 is treated as success", '    3) _why=', '    3) return 0;;\n    9) _why='),
    ("a half-written config from a failed setup run is trusted on the next apply", '[ -e "$M_CONFIGURING" ] || [ -L "$M_CONFIGURING" ] || ', ''),
    ("ownership is recorded only for adopted services, not for ones we start (R1)", '  if [ ! -f "$M_MANAGED" ]; then\n    if [ "$LOADED" = yes ]; then _adopted=yes', '  if [ ! -f "$M_MANAGED" ] && [ "$LOADED" = yes ]; then\n    if [ "$LOADED" = yes ]; then _adopted=yes'),
    ("opt-out reports success and drops ownership when the unit cannot be removed (R2)", 'if [ -e "$DST" ] || [ -L "$DST" ]; then finish "STOP FAILED: cannot remove', 'if false; then finish "STOP FAILED: cannot remove'),
    ("adoption records the unit as it is after replacement, not as it was loaded (R4)", '_own=$_before', '_own=$_want'),
    ("the setup script gets the caller's PATH, not the daemon's (R6)", 'env PATH="$ITP:$PATH" RETRO', 'env RETRO'),
    ("a timed-out setup script leaves its children running (R7)", 'kill "TERM", -$pid; select(undef, undef, undef, 1); kill "KILL", -$pid;', 'kill "TERM", $pid; select(undef, undef, undef, 1); kill "KILL", $pid;'),
    ("cancelling the apply leaves the setup script's group running (R10)", '$SIG{INT} = sub { $stop->(130) }; $SIG{TERM} = sub { $stop->(143) }; $SIG{HUP} = sub { $stop->(129) };', ''),
    ("a dangling-symlink unit counts as removed (R12)", '  if [ -e "$DST" ] || [ -L "$DST" ]; then', '  if [ -e "$DST" ]; then'),
    ("cancellation is treated as an ordinary failed step (R13)", 'case $_r in 129|130|143)', 'case $_r in 999)'),
    ("a directory marker counts as ownership (R14)", '&& touch "$M_MANAGED" && [ -f "$M_MANAGED" ]', '&& touch "$M_MANAGED"'),
    ("a directory .configuring marker is ignored (R14)", 'if [ -e "$M_CONFIGURING" ] || [ -L "$M_CONFIGURING" ]', 'if [ -f "$M_CONFIGURING" ]'),
    ("the unit is installed even when the checkout is missing", '  if [ -n "$_miss" ]; then finish "NOT READY: missing$_miss"; return 0; fi\n', '  if [ -n "$_miss" ]; then mkdir -p "$AGENTS_DIR"; cp "$SRC" "$DST"; finish "NOT READY: missing$_miss"; return 0; fi\n'),
    ("a service that is not running is never started", '  if [ "$LOADED" = no ]; then\n    if ! printf', '  if [ "$LOADED" = never ]; then\n    if ! printf'),
    ("opt-out of a half-started instance stops whatever is loaded", '  if [ ! -f "$M_MANAGED" ]; then say "$NAME: not opted in"; return 0; fi\n', '  if [ ! -f "$M_MANAGED" ]; then run_lc bootout "$DOMAIN/$LABEL"; return 0; fi\n'),
    ("the reload switch reloads an instance whose unit did not change", '  _loaded_sha=$(cat "$M_SHA" 2>/dev/null || true)\n  if [ "$_loaded_sha" = "$_want" ]; then', '  _loaded_sha=$(cat "$M_SHA" 2>/dev/null || true)\n  if [ "$_loaded_sha" = "$_want" ] && ! reload_requested; then'),
    # --- the work coordinator (PR 3)
    ("work: the setup script is not asked for the config half only, so it installs and starts its own unit", '--yes-this-is-the-work-computer --config-only', '--yes-this-is-the-work-computer'),
    ("work: the setup script is not told which commit the checkout is", '--rev "$_rev" --state-dir', '--state-dir'),
    ("work: the setup script gets a different state directory", '--state-dir "$STATE" >', '--state-dir "$HOME_DIR/.local/share/coordinator" >'),
    ("work: the setup script cannot find agent-alert (its directory is not on its PATH)", 'env PATH="$ITP:$AGENT_ALERT_DIR:$PATH" bash', 'env PATH="$ITP:$PATH" bash'),
    ("work: a checkout that is not a git repository still runs the setup script", 'cannot read its commit)"; return 1; }', 'cannot read its commit)"; }'),
    ("work: the work instance is managed under the personal label", 'LABEL=local.coordinatord.work;', 'LABEL=local.coordinatord;'),
    ("work: the work instance logs into the personal log directory", 'LOGDIR=$HOME_DIR/Library/Logs/coordinator-work', 'LOGDIR=$HOME_DIR/Library/Logs/coordinator'),
    ("work: the work instance uses the personal state directory", 'STATE=$HOME_DIR/.local/share/coordinator-work', 'STATE=$HOME_DIR/.local/share/coordinator'),
    ("work: the owner's extra tool directories are ignored", 'ITP=$TOOL_PATH; [ -z "$EXTRA_PATH" ] || ITP=$EXTRA_PATH:$TOOL_PATH', 'ITP=$TOOL_PATH'),
    ("work: the work instance's extra directories leak to the next instance", "CFGNAME=retro; EXTRA_PATH='';", "CFGNAME=retro;"),
    ("work: a reload asked for the personal coordinator reloads the work one", '*,all,*|*,"$NAME",*)', '*,all,*|*,"$CFGNAME",*)'),
    ("work: a failed setup shows the first line of its narration, not its [FAIL] line", '_why=$(grep -m1 \'^\\[FAIL\\]\' "$TMP/cfg.out" | cut -c9-210);', '_why="";'),
    ("work: not-ready messages name the instance, not the flag key the owner sets", 'instances.$CFGNAME.repo', 'instances.$NAME.repo'),
    # --- the source files around the script
    ("work: the work unit is deployed on a personal Mac", '{{- if or (ne .profile "axon-work-computer") (ne .chezmoi.os "darwin") }}', '{{- if false }}', IGNORE),
    ("work: the work unit is never deployed to the work Mac", '{{- if or (ne .profile "axon-work-computer") (ne .chezmoi.os "darwin") }}', '{{- if true }}', IGNORE),
    ("work: the work wrapper also runs Retro", "export INSTANCES_LIST='coordinator-work'", "export INSTANCES_LIST='coordinator-work retro'", WRAPPER),
    ("work: the work wrapper drops the owner's extra tool directories", 'export INSTANCES_COORDINATOR_WORK_EXTRA_PATH={{ includeTemplate "shquote" (dig "instances" "coordinator" "extraPath" "" . | printf "%v") }}', 'export INSTANCES_COORDINATOR_WORK_EXTRA_PATH=', WRAPPER),
    ("work: the work wrapper reads another flag than instances.coordinator.enabled", 'export INSTANCES_COORDINATOR_WORK_ENABLED={{ includeTemplate "shquote" (dig "instances" "coordinator" "enabled"', 'export INSTANCES_COORDINATOR_WORK_ENABLED={{ includeTemplate "shquote" (dig "instances" "coordinatorWork" "enabled"', WRAPPER),
    ("work: the work unit points at the personal state directory", 'printf "%s/.local/share/coordinator-work"', 'printf "%s/.local/share/coordinator"', WORK_UNIT),
    ("work: the work unit differs from what the setup script renders (PATH order)", '<key>PATH</key><string>{{ $extra }}{{ $home }}/.local/share/mise/shims', '<key>PATH</key><string>{{ $home }}/.local/share/mise/shims:{{ $extra }}', WORK_UNIT),
    ("work: the work unit ignores the checkout path from local data", '{{- $repo := includeTemplate "instance_repo" (dict "root" . "name" "coordinator") | html -}}', '{{- $repo := printf "%s/git/coordinator" .chezmoi.homeDir | html -}}', WORK_UNIT),
]


def run_suite(env):
    return subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(HERE)], capture_output=True, text=True, env=env, timeout=900)


def main():
    survived = []
    only = sys.argv[1] if len(sys.argv) > 1 else ""
    ran = 0
    for name, old, new, *rest in MUTATIONS:
        if only not in name:
            continue
        ran += 1
        target = ROOT / rest[0] if rest else SCRIPT
        original = target.read_text()
        if original.count(old) != 1:
            print("MUTATION DOES NOT APPLY (%d matches): %s" % (original.count(old), name))
            return 2
        if rest:
            try:
                target.write_text(original.replace(old, new))
                result = run_suite(dict(os.environ))
            finally:
                target.write_text(original)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                mutated = Path(tmp) / "mutated.sh"
                mutated.write_text(original.replace(old, new))
                result = run_suite(dict(os.environ, INSTANCES_SCRIPT_UNDER_TEST=str(mutated)))
        failed = result.returncode != 0
        tail = [line for line in result.stderr.splitlines() if line.startswith("FAIL:") or line.startswith("ERROR:")]
        print("%s  %s%s" % ("CAUGHT  " if failed else "SURVIVED", name, ("  (%d tests failed)" % len(tail)) if failed else ""))
        if not failed:
            survived.append(name)
    print("\n%d mutations, %d caught, %d survived" % (ran, ran - len(survived), len(survived)))
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
