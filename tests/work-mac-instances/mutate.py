"""Mutation check for work-mac-instances.sh: every safety property gets at least one mutation, and the tests must catch each one.
Run: python3 mutate.py   (exit 0 only if every mutation is CAUGHT; a mutation that no longer applies is an error)"""
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent.parent / "docs/work-mac/work-mac-instances.sh"

# (property, name, old, new)
MUTATIONS = [
    # stops on a dirty source
    ("dirty", "dirty source is ignored", 'if [ -n "$DIRTY" ]; then', 'if false; then'),
    ("dirty", "dirty check also lists nothing (status ignores tracked changes)", '--untracked-files=no 2>/dev/null)', '--untracked-files=no HEAD 2>/dev/null | head -n 0)'),
    # stops on non-fast-forward
    ("non-ff", "diverged source only warns", 'fail "the dotfiles source and $UPSTREAM have diverged (not a fast-forward); not touching it."', 'info "diverged but continuing"; true "$UPSTREAM"; : '),
    ("non-ff", "diverged source is merged, not fast-forwarded", 'merge --ff-only --quiet "$UPSTREAM"', 'merge --no-ff --no-edit --quiet "$UPSTREAM"'),
    ("non-ff", "ancestor test is inverted", 'elif git -C "$TOP" merge-base --is-ancestor "$LOCAL" "$UP"; then', 'elif ! git -C "$TOP" merge-base --is-ancestor "$LOCAL" "$UP"; then'),
    ("non-ff", "a detached HEAD is accepted", 'fail "the dotfiles source is on a detached HEAD."', 'BRANCH=main; info "detached"; true '),
    # no overwrite of existing data
    ("no-overwrite", "repo is always written", 'if [ -z "$DATA_REPO" ]; then\n  yaml_edit add', 'if true; then\n  yaml_edit add'),
    ("no-overwrite", "an existing repo that differs is accepted", 'fail "instances.coordinator.repo is already $DATA_REPO in $CONFIG, but you asked for $COORD_REAL."', 'info "differs"; true '),
    ("no-overwrite", "a different profile is accepted", 'fail "the profile in your chezmoi data is', 'info "the profile in your chezmoi data is'),
    ("no-overwrite", "the changed-lines guard is gone", '[ "$_gone" = "$1" ] || fail', '[ "$_gone" -ge 0 ] || fail'),
    ("no-overwrite", "the edit comment is dropped on a flip", 'print spaces(mind) K[n] ": " val cm; else print L[i]', 'print spaces(mind) K[n] ": " val; else print L[i]'),
    ("no-overwrite", "an existing enabled value is flipped even if already true", 'if [ "$ENABLED" = true ]; then\n  ok "instances.coordinator.enabled is already true"', 'if false; then\n  ok "instances.coordinator.enabled is already true"'),
    # backup
    ("backup", "no backup is made", '  backup_config\n  cmp -s', '  cmp -s'),
    ("backup", "the backup is not verified", 'cmp -s "$CONFIG" "$_b" || fail "the backup $_b does not match $CONFIG; not editing it."', 'true'),
    ("backup", "a backup failure is ignored", 'cp -p "$CONFIG" "$_b" || { rm -f "$_b"; fail "cannot back up $CONFIG to $_b; not editing it."; }', 'cp -p "$CONFIG" "$_b" 2>/dev/null; true'),
    ("backup", "the backup is made after the write", '  backup_config\n  cmp -s "$CONFIG" "$ORIG" || fail "$CONFIG changed while this script was running; not writing it." "Nothing was changed by this script except the backup file. Re-run."\n  install_config "$CUR" wmi-new || fail "cannot write $CONFIG; it was not changed (backup: $BACKUP)."', '  install_config "$CUR" wmi-new || fail "cannot write $CONFIG."\n  backup_config'),
    ("backup", "a bad edit is not undone", '    if restore_config; then fail "after the edit', '    if false; then fail "after the edit'),
    ("backup", "a failed restore is called a success", '    fail "after the edit chezmoi reads $_lab as [$_got], not [$_exp], AND RESTORING', '    fail "after the edit chezmoi reads $_lab as [$_got], not [$_exp]; $CONFIG was restored from $BACKUP (checked)." "AND RESTORING'),
    ("backup", "the restore is not checked", 'restore_config() { cmp -s "$CONFIG" "$ORIG" && install_config "$BACKUP" wmi-restore && cmp -s "$BACKUP" "$CONFIG"; }', 'restore_config() { install_config "$BACKUP" wmi-restore; true; }'),
    ("backup", "the backup file is created without checking it is new", "until ( set -C; : >\"$_b\" ) 2>/dev/null; do", "until true; do"),
    ("transaction", "a concurrent edit is overwritten", 'write_config() {\n  cmp -s "$CONFIG" "$ORIG" || fail "$CONFIG changed while this script was running; not writing it." "Nothing was changed by this script. Re-run."', 'write_config() {\n  true'),
    ("transaction", "the lock is not taken", '  mkdir "$LOCKDIR" 2>/dev/null || fail "another run', '  true || fail "another run'),
    ("transaction", "a failed write is ignored", 'install_config "$CUR" wmi-new || fail "cannot write $CONFIG; it was not changed (backup: $BACKUP)."', 'install_config "$CUR" wmi-new; true'),
    ("transaction", "aliases and block scalars are edited", 'then EDIT_STATUS=manual; return 3; fi\n  awk -v mode', 'then true; fi\n  awk -v mode'),
    ("transaction", "a symlinked config is replaced by a file", '  CONFIG=$_lt\n', '  true\n'),
    # reconcile step must not run the setup script or restart
    ("reconcile", "a stale setup marker is accepted", 'if [ -e "$MARKER" ] || [ -L "$MARKER" ]; then', 'if false; then'),
    ("reconcile", "a dangling marker link is accepted", 'if [ -e "$MARKER" ] || [ -L "$MARKER" ]; then', 'if [ -e "$MARKER" ]; then'),
    ("reconcile", "INSTANCES_RELOAD is accepted", 'for _v in INSTANCES_RELOAD INSTANCES_STATE_ROOT', 'for _v in INSTANCES_X INSTANCES_STATE_ROOT'),
    ("reconcile", "INSTANCES_STATE_ROOT is accepted", 'INSTANCES_RELOAD INSTANCES_STATE_ROOT INSTANCES_AGENTS_DIR', 'INSTANCES_RELOAD INSTANCES_X INSTANCES_AGENTS_DIR'),
    ("reconcile", "INSTANCES_AGENTS_DIR is accepted", 'INSTANCES_STATE_ROOT INSTANCES_AGENTS_DIR INSTANCES_UNIT_DIR; do', 'INSTANCES_STATE_ROOT INSTANCES_X INSTANCES_UNIT_DIR; do'),
    ("reconcile", "INSTANCES_UNIT_DIR is accepted", 'INSTANCES_AGENTS_DIR INSTANCES_UNIT_DIR; do', 'INSTANCES_AGENTS_DIR INSTANCES_X; do'),
    ("reconcile", "a service that is not loaded is adopted", '[ "$LIVE_STATE" = loaded ] || fail', 'true || fail'),
    # hooks
    ("hooks", "unknown hooks are accepted", '[ -z "$BADHOOK" ] || fail', 'true || fail'),
    ("hooks", "the installer hook is accepted without op", 'else BADHOOK="$BADHOOK $_h (would run brew', 'else true "$_h (would run brew'),
    ("hooks", "an unknown hook is run by reading the source first", 'chezmoi dump-config --format json >"$TMP/cfg.json"', 'chezmoi source-path >/dev/null 2>&1; chezmoi dump-config --format json >"$TMP/cfg.json"'),
    ("hooks", "an installer-named hook anywhere is trusted", '[ "$_hd" != "$DEFAULT_SRC" ] || ', 'false || '),
    ("hooks", "a non-default chezmoi source is trusted", '[ "$(rp "$SRCDIR")" != "$DEFAULT_SRC" ] || ', 'false || '),
    ("transaction", "a restore overwrites a later change", 'restore_config() { cmp -s "$CONFIG" "$ORIG" && install_config', 'restore_config() { true && install_config'),
    # derived from the live unit: extraPath and the checkout
    ("derive", "the derived extraPath is not read back", '      verify_config instances.coordinator.extraPath "$_prefix" instances coordinator extraPath\n', ''),
    ("derive", "the unit is not applied again after extraPath", '      chezmoi apply --no-tty -P --recursive=false "$T_UNIT" >"$TMP/apply1b.out" 2>&1; _rc=$?', '      true >"$TMP/apply1b.out" 2>&1; _rc=$?'),
    ("derive", "a prefix with characters that need escaping is written", '  safe_chars "$1" || return 1\n  case $1 in', '  case $1 in'),
    ("derive", "a relative prefix directory is written", 'for _d in $1; do case $_d in /*) ;; *) IFS=$_oifs; set +f; return 1;; esac; done', 'for _d in $1; do case $_d in *) ;; esac; done'),
    ("derive", "the dry run applies the unit again", '    if [ "$DRY" = 1 ]; then\n      would "chezmoi apply ~/$UNIT_REL again, then compare again"', '    if false; then\n      would "chezmoi apply ~/$UNIT_REL again, then compare again"'),
    ("derive", "any live directory is used as the checkout", '    elif coord_ok "$_lwd"; then COORD=$_lwd', '    elif [ -n "$_lwd" ]; then COORD=$_lwd'),
    ("derive", "a live directory with odd characters is used", '  safe_chars "$1" || return 1\n  [ -d "$1" ]', '  [ -d "$1" ]'),
    ("derive", "the live unit beats existing chezmoi data", 'elif [ -n "$DATA_REPO" ]; then COORD=$DATA_REPO;', 'elif [ -n "$DATA_REPO" ] && [ ! -f "$LIVE" ]; then COORD=$DATA_REPO;'),
    ("derive", "a valid default beats the live unit", '    elif coord_ok "$_lwd"; then COORD=$_lwd', '    elif coord_ok "$_lwd" && [ ! -d "$COORD" ]; then COORD=$_lwd'),
    ("derive", "the dry run needs --override-data", 'chezmoi --config "$CUR" execute-template <"$TEMPLATE"', "chezmoi execute-template --override-data '{}' <\"$TEMPLATE\""),
    ("derive", "the dry run renders against the unedited config", 'chezmoi --config "$CUR" execute-template', 'chezmoi --config "$CONFIG" execute-template'),
    ("derive", "hook output is kept in the rendered unit", "sed -n '/^<?xml/,/^<\\/plist>/p' \"$TMP/render.out\" >\"$RENDERED\"", 'cp "$TMP/render.out" "$RENDERED"'),
    # failures are not ignored
    ("failures", "a failing git status is read as clean", '2>/dev/null) || fail "cannot read the git status of $TOP."', '2>/dev/null) || true'),
    ("failures", "a failed copy of the rendered unit is ignored", 'cp "$T_UNIT" "$RENDERED" || fail "cannot copy the rendered unit $T_UNIT for the comparison."', 'cp "$T_UNIT" "$RENDERED"'),
    ("failures", "the flag is claimed off when it is on", 'if [ "$ENABLED" = true ]; then say "   instances.coordinator.enabled is ALREADY true', 'if false; then say "   instances.coordinator.enabled is ALREADY true'),
    ("backup", "the read-back check is skipped", '  _got=$(cdata "$@")\n  if [ "$_got" != "$_exp" ]; then', '  _got=$_exp\n  if [ "$_got" != "$_exp" ]; then'),
    # --enable gate
    ("enable-gate", "step 5 always runs", 'if [ "$ENABLE" != 1 ]; then\n  step "Done (steps 1 to 4)', 'if false; then\n  step "Done (steps 1 to 4)'),
    ("enable-gate", "--dry-run turns on --enable", '--dry-run) DRY=1;;', '--dry-run) DRY=1; ENABLE=1;;'),
    ("enable-gate", "the first apply includes the reconcile step", 'chezmoi apply --no-tty -P --recursive=false "$T_UNIT" "$T_SCRIPT" >"$TMP/apply.out"', 'chezmoi apply --no-tty -P --recursive=false "$T_UNIT" "$T_SCRIPT" "$T_WRAPPER" >"$TMP/apply.out"'),
    ("enable-gate", "the flag is written without the instance being set up", '[ -f "$STATE_CFG" ] || fail', 'true || fail'),
    ("enable-gate", "nothing to adopt is accepted", '[ -f "$LIVE" ] || fail "there is no live unit at $LIVE: nothing to adopt."', 'true || fail "x"'),
    ("enable-gate", "NOT READY exits 0", 'exit 5;;', 'exit 0;;'),
    # dry run
    ("dry-run", "--dry-run is ignored", '--dry-run) DRY=1;;', '--dry-run) DRY=0;;'),
    ("dry-run", "the config is written in a dry run", 'if [ "$DRY" = 1 ]; then would "back up $CONFIG, then write the lines above"; return 0; fi', ''),
    ("dry-run", "the dry run applies", 'if [ "$DRY" = 1 ]; then\n  would "chezmoi apply -P', 'if false; then\n  would "chezmoi apply -P'),
    ("dry-run", "the dry run fetches", '_tip=$(git -C "$TOP" ls-remote "$_rem" "$_mrg"', 'git -C "$TOP" fetch --quiet; _tip=$(git -C "$TOP" ls-remote "$_rem" "$_mrg"'),
    ("dry-run", "the dry run fast-forwards", '  if [ "$DRY" = 1 ]; then would "fast-forward $_n commit(s)"', '  if false; then would "fast-forward $_n commit(s)"'),
    ("dry-run", "the dry run stops before step 5 only when not enabling (step 5 writes)", 'if [ "$DRY" = 1 ]; then\n  would "chezmoi apply (the three targets', 'if false; then\n  would "chezmoi apply (the three targets'),
    # only the instances files, no silent extraPath, no setup script
    ("scope", "the first apply is not limited to targets", 'chezmoi apply --no-tty -P --recursive=false "$T_UNIT" "$T_SCRIPT" >"$TMP/apply.out"', 'chezmoi apply --no-tty >"$TMP/apply.out"'),
    ("scope", "a unit difference beyond PATH is ignored", '  action "the rendered unit differs from the live unit in more than PATH', '  [ "$TMP" ] && exit 0; action "the rendered unit differs from the live unit in more than PATH'),
    ("scope", "the PATH-only difference is ignored", '      *":$BASE") _prefix=', '      *":$BASE") exit 0; _prefix='),
    ("scope", "root is allowed", '[ "$(id -u)" != 0 ] || fail', 'true || fail'),
]


def run(item):
    prop, name, old, new = item
    text = SCRIPT.read_text()
    if text.count(old) != 1:
        return prop, name, "ERROR (pattern found %d times)" % text.count(old)
    with tempfile.TemporaryDirectory() as d:
        mutant = Path(d) / "work-mac-instances.sh"
        mutant.write_text(text.replace(old, new))
        if subprocess.run(["sh", "-n", str(mutant)], capture_output=True).returncode != 0:
            return prop, name, "ERROR (the mutant does not parse)"
        env = dict(os.environ, WORK_MAC_SCRIPT=str(mutant))
        r = subprocess.run([sys.executable, "-m", "unittest", "-f", "test_work_mac_instances"], cwd=str(HERE), env=env, capture_output=True, text=True, timeout=900)
    return prop, name, "CAUGHT" if r.returncode != 0 else "SURVIVED"


def main():
    with ThreadPoolExecutor(max_workers=int(os.environ.get("MUTATE_JOBS", "4"))) as pool:
        results = list(pool.map(run, MUTATIONS))
    bad = 0
    for prop, name, res in results:
        print("%-12s %-8s %s" % (prop, res, name))
        bad += res != "CAUGHT"
    props = sorted({p for p, _, _ in results})
    print("\n%d mutations, %d caught, properties: %s" % (len(results), len(results) - bad, ", ".join(props)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
