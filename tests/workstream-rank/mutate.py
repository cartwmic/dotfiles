"""Mutation check: break one rule of workstream-rank at a time; the suite must fail each time.

    python3 tests/workstream-rank/mutate.py

Not part of CI. It proves the tests pin every rule rather than just exercising the script.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "dot_local/bin/executable_workstream-rank"

MUTATIONS = [
    ("unranked is not 1000", "UNRANKED=1000", "UNRANKED=999"),
    ("shared pane: first row wins instead of best", '(!found || $1 < blen ||', '(!found ||  0 ||'),
    ("shared pane: worst wins", '(!found || $1 < blen ||', '(!found || $1 > blen ||'),
    ("pane matches by prefix", '$4 "" == ENVIRON["PANE"] ""', 'index($4 "", ENVIRON["PANE"]) == 1'),
    ("pane default ignores T3CODE_THREAD_ID", 'if [ -z "$explicit" ] && [ -n "${T3CODE_THREAD_ID:-}" ]; then', 'if false; then'),
    ("pane default drops the t3: prefix", 'pane=t3:$thread', 'pane=$thread'),
    ("pane default falls back to HERDR_PANE_ID", '    thread=\n', '    thread=\n    [ -n "$explicit" ] || pane=${HERDR_PANE_ID:-}\n'),
    ("empty --pane falls back to the thread default", 'if [ "$1" = --pane ]; then pane=$2; explicit=1; fi', 'if [ "$1" = --pane ] && [ -n "$2" ]; then pane=$2; fi'),
    ("thread walk skipped", 'if [ -n "$thread" ] && [ "$best" = "$UNRANKED" ]; then', 'if false; then'),
    ("walk also runs for an explicit --pane", 'if [ -z "$explicit" ] && [ -n "${T3CODE_THREAD_ID:-}" ]; then\n        thread=$T3CODE_THREAD_ID\n        pane=t3:$thread', 'if [ -n "${T3CODE_THREAD_ID:-}" ]; then\n        thread=$T3CODE_THREAD_ID\n        pane=${pane:-t3:$thread}'),
    ("walk result used without a rank lookup", 'if [ -n "$found" ]; then best=$(best_of "$found"); fi', 'if [ -n "$found" ]; then best=1; fi'),
    ("walk failure is silent", 'rows | cut -f4 | python3 "$helper" "$1" || warn', 'rows | cut -f4 | python3 "$helper" "$1" 2>/dev/null || :; true || warn'),
    ("--pane ignored", 'if [ "$1" = --pane ]; then pane=$2; explicit=1; fi', ':'),
    ("-/empty pane can match", '|| [ -z "$pane" ] || [ "$pane" = - ]', ''),
    ("row without pane gets a matchable empty pane", '(NF >= 3 && $3 != "") ? $3 : "-"', '$3'),
    ("header check removed", 'case $first in', 'case x in'),
    ("header accepts any v1 prefix", '"#workstream-rank v1" | "#workstream-rank v1"[[:space:]]*) return 0 ;;', '"#workstream-rank v1"*) return 0 ;;'),
    ("header accepts v2", '"#workstream-rank v1" | "#workstream-rank v1"[[:space:]]*) return 0 ;;', '"#workstream-rank v"*) return 0 ;;'),
    ("header with trailing text rejected", '"#workstream-rank v1" | "#workstream-rank v1"[[:space:]]*) return 0 ;;', '"#workstream-rank v1") return 0 ;;'),
    ("missing file is an error", 'if [ ! -f "$file" ] || [ ! -r "$file" ]; then\n        warn', 'if [ ! -f "$file" ] || [ ! -r "$file" ]; then\n        exit 1; warn'),
    ("corrupt file is an error", "ignoring the file (unranked = $UNRANKED)\"\n    return 1", "ignoring the file (unranked = $UNRANKED)\"\n    exit 1"),
    ("warning printed twice", 'warn "$file: line 1', 'warn "$file: line 1 (again)"; warn "$file: line 1'),
    ("corrupt file warns not at all", 'warn "$file: line 1 is not', ': "$file: line 1 is not'),
    ("non-integer rank accepted", 'NF < 2 || rank !~ /^[0-9]+$/ { next }', 'NF < 2 { next }'),
    ("zero rank accepted (leading zeros not stripped)", '{ rank = $1; sub(/^0+/, "", rank) }', '{ rank = $1 }'),
    ("rank compared by text only (length ignored)", '$1 < blen || ($1 == blen && $2 "" < best "")', '$2 "" < best ""'),
    ("rank compared as float", '($1 == blen && $2 "" < best "")', '($1 == blen && $2 + 0 < best + 0)'),
    ("rank capped", 'NF < 2 || rank !~ /^[0-9]+$/ { next }', 'NF < 2 || rank !~ /^[0-9]+$/ || length(rank) > 15 { next }'),
    ("show sorts by text within a length only on length", '-k1,1n -k2,2', '-k1,1n'),
    ("show sorts rank text before length", '-k1,1n -k2,2', '-k2,2 -k1,1n'),
    ("CR not stripped", '{ sub(/\\r$/, "") }', '{ }'),
    ("pane compared numerically when both look like numbers", '$4 "" == ENVIRON["PANE"] ""', '$4 == ENVIRON["PANE"]'),
    ("rows with <2 fields accepted", 'NF < 2 ||', 'NF < 1 ||'),
    ("extra fields break the row", '{ pane = (NF', 'NF > 3 { next }\n        { pane = (NF'),
    ("show sorts length as text", '-k1,1n -k2,2', '-k1,1 -k2,2'),
    ("show not sorted at all", 'LC_ALL=C sort -s -t "$(printf \'\\t\')" -k1,1n -k2,2 | cut -f2-', 'cut -f2-'),
    ("env file ignored", 'file=${WORKSTREAM_RANK_FILE:-${HOME:-}/.local/share/coordinator/rank}', 'file=${HOME:-}/.local/share/coordinator/rank'),
    ("default path wrong", '${HOME:-}/.local/share/coordinator/rank}', '${HOME:-}/.local/share/coordinator/ranks}'),
    ("--cwd not accepted", '--pane | --cwd | --cmd)', '--pane | --cmd)'),
    ("--cmd not accepted", '--pane | --cwd | --cmd)', '--pane | --cwd)'),
    ("--cwd value used as pane", 'if [ "$1" = --pane ]; then pane=$2; explicit=1; fi', 'pane=$2'),
    ("usage error exits 0", 'warn "$*"; usage >&2; exit 2', 'warn "$*"; usage >&2; exit 0'),
    ("no arguments is not a usage error", '[ $# -ge 1 ] || { usage >&2; exit 2; }', '[ $# -ge 1 ] || { usage >&2; exit 0; }'),
    ("show: bad file prints rows anyway", '    usable || return 0\n', '    usable || :\n'),
]


HELPERS = HERE.parents[1] / "dot_local/share/workstream-rank"
# Mutations of the thread walk, in the helper files: (name, file, old, new)
WALK_MUTATIONS = [
    ("walk: a thread's parent is never read", "t3_lineage.py", "thread = parent.get(thread)", "thread = None"),
    ("walk: the farthest owner wins, not the nearest", "t3_lineage.py", "        if thread in owners:\n            return owners[thread]\n        seen.add(thread)\n        thread = parent.get(thread)\n    return None", "        if thread in owners:\n            hit = owners[thread]\n        seen.add(thread)\n        thread = parent.get(thread)\n    return hit if 'hit' in dir() else None"),
    ("walk: loops are not stopped", "t3_lineage.py", "while thread and thread not in seen:", "while thread:"),
    ("lineage: the parent id is read from the wrong key", "t3_lineage.py", "get('parentThreadId')", "get('rootThreadId')"),
    ("helper: an unreadable database is not reported", "thread_rank.py", "return 3", "return 0"),
    ("helper: only the first pane value is an owner", "thread_rank.py", "owners.setdefault(ref[3:], ref)", "owners = owners or {ref[3:]: ref}"),
]


def run_suite(tmp, script_text, helper_edit=None):
    """Lay out tmp/bin/mutant beside tmp/share/workstream-rank (the layout the script finds its helper in), run the suite on it. True when it fails."""
    root = Path(tmp)
    (root / "bin").mkdir(parents=True, exist_ok=True)
    (root / "bin" / "mutant").write_text(script_text)
    share = root / "share" / "workstream-rank"
    if share.exists():
        shutil.rmtree(share)
    shutil.copytree(HELPERS, share, ignore=shutil.ignore_patterns("__pycache__"))
    if helper_edit:
        name, old, new = helper_edit
        text = (share / name).read_text()
        if text.count(old) != 1:
            sys.exit(f"mutation on {name}: pattern found {text.count(old)} times, want 1: {old!r}")
        (share / name).write_text(text.replace(old, new))
    env = {**os.environ, "WORKSTREAM_RANK_SCRIPT": str(root / "bin" / "mutant"), "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(HERE)], env=env, capture_output=True, text=True)
    return r.returncode != 0


def main():
    text = SCRIPT.read_text()
    survived = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, old, new in MUTATIONS:
            if text.count(old) != 1:
                sys.exit(f"mutation {name!r}: pattern found {text.count(old)} times, want 1")
            killed = run_suite(tmp, text.replace(old, new))
            print(("killed  " if killed else "SURVIVED"), name)
            if not killed:
                survived.append(name)
        for name, file, old, new in WALK_MUTATIONS:
            killed = run_suite(tmp, text, (file, old, new))
            print(("killed  " if killed else "SURVIVED"), name)
            if not killed:
                survived.append(name)
    total = len(MUTATIONS) + len(WALK_MUTATIONS)
    print(f"{total - len(survived)}/{total} mutations killed")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()
