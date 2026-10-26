"""Mutation check: break one rule of workstream-rank at a time; the suite must fail each time.

    python3 tests/workstream-rank/mutate.py

Not part of CI. It proves the tests pin every rule rather than just exercising the script.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "dot_local/bin/executable_workstream-rank"

MUTATIONS = [
    ("unranked is not 1000", "UNRANKED=1000", "UNRANKED=999"),
    ("shared pane: first row wins instead of best", '(!found || $1 + 0 < best)', '(!found)'),
    ("shared pane: best compared as text", '(!found || $1 + 0 < best)', '(!found || $1 "" < best "")'),
    ("shared pane: worst wins", '(!found || $1 + 0 < best)', '(!found || $1 + 0 > best)'),
    ("pane matches by prefix", '$3 "" == ENVIRON["PANE"] ""', 'index($3 "", ENVIRON["PANE"]) == 1'),
    ("pane default ignores HERDR_PANE_ID", 'pane=${HERDR_PANE_ID:-}', 'pane='),
    ("--pane ignored", 'if [ "$1" = --pane ]; then pane=$2; fi', ':'),
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
    ("non-integer rank accepted", ' || rank !~ /^[0-9]+$/', ''),
    ("zero rank accepted (leading zeros not stripped)", '{ rank = $1; sub(/^0+/, "", rank) }', '{ rank = $1 }'),
    ("huge rank accepted", ' || length(rank) > 15', ''),
    ("rank cap too small", 'length(rank) > 15', 'length(rank) > 9'),
    ("CR not stripped", '{ sub(/\\r$/, "") }', '{ }'),
    ("pane compared numerically when both look like numbers", '$3 "" == ENVIRON["PANE"] ""', '$3 == ENVIRON["PANE"]'),
    ("rows with <2 fields accepted", 'NF < 2 ||', 'NF < 1 ||'),
    ("extra fields break the row", '{ pane = (NF', 'NF > 3 { next }\n        { pane = (NF'),
    ("show not sorted by number", 'sort -s -n -t', 'sort -s -t'),
    ("show not sorted at all", 'rows | sort -s -n -t "$(printf \'\\t\')" -k1,1', 'rows'),
    ("env file ignored", 'file=${WORKSTREAM_RANK_FILE:-${HOME:-}/.local/share/coordinator/rank}', 'file=${HOME:-}/.local/share/coordinator/rank'),
    ("default path wrong", '${HOME:-}/.local/share/coordinator/rank}', '${HOME:-}/.local/share/coordinator/ranks}'),
    ("--cwd not accepted", '--pane | --cwd | --cmd)', '--pane | --cmd)'),
    ("--cmd not accepted", '--pane | --cwd | --cmd)', '--pane | --cwd)'),
    ("--cwd value used as pane", 'if [ "$1" = --pane ]; then pane=$2; fi', 'pane=$2'),
    ("usage error exits 0", 'warn "$*"; usage >&2; exit 2', 'warn "$*"; usage >&2; exit 0'),
    ("no arguments is not a usage error", '[ $# -ge 1 ] || { usage >&2; exit 2; }', '[ $# -ge 1 ] || { usage >&2; exit 0; }'),
    ("show: bad file prints rows anyway", '    usable || return 0\n', '    usable || :\n'),
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
            env = {**os.environ, "WORKSTREAM_RANK_SCRIPT": str(mutant), "PYTHONDONTWRITEBYTECODE": "1"}
            r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(HERE)], env=env,
                               capture_output=True, text=True)
            killed = r.returncode != 0
            print(("killed  " if killed else "SURVIVED"), name)
            if not killed:
                survived.append(name)
    print(f"{len(MUTATIONS) - len(survived)}/{len(MUTATIONS)} mutations killed")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()
