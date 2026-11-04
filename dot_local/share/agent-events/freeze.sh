#!/bin/sh
# freeze.sh: the Python-only part of `traces pi proof freeze` (traces stage 2, plan 3.0): make a frozen copy of the
# corpus and state that G1 and G2 compare, without touching the originals.
#
#   freeze.sh --out F [--sessions-src DIR] [--state-src DIR] [--machine LABEL] [--roots DIRS] [--per-stratum N]
#
# Writes into the new directory F:
#   sessions/            clone of the sessions corpus (cp -c on APFS, else cp -Rp)
#   strata.txt           about 1,500 corpus-relative paths for the mutation runs: forks, children, codemode-heavy,
#                        untimed, a line over 2 MB, plain top-level (per-stratum N, default 250)
#   state/<machine>/     export_state.json and status.json, copied (read, never moved)
#   approved.txt         the approved-project list, one name per line
#   roots/<name>/.git    a roots fixture for exactly that list, so the fingerprint reproduces without the live directories
#   FREEZE.json          the recorded fp, the reference hashes, versions, and collector processes seen at freeze time
# Exits 1 and says "re-freeze" if the fingerprint computed from the live environment is not the one recorded in the
# state file, or if the roots fixture gives a different fingerprint. The live corpus and state are only read.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
out= sessions_src="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/sessions"
state_src="${AGENT_EVENTS_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/agent-events}"
machine=personal roots= per=250
while [ $# -gt 0 ]; do
  case $1 in
    --out) out=$2 ;; --sessions-src) sessions_src=$2 ;; --state-src) state_src=$2 ;;
    --machine) machine=$2 ;; --roots) roots=$2 ;; --per-stratum) per=$2 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "freeze.sh: unknown argument $1" >&2; exit 64 ;;
  esac
  shift 2 || { echo "freeze.sh: $1 needs a value" >&2; exit 64; }
done
[ -n "$out" ] || { echo "freeze.sh: --out is required" >&2; exit 64; }
[ -d "$sessions_src" ] || { echo "freeze.sh: no sessions directory at $sessions_src" >&2; exit 64; }
[ ! -e "$out" ] || [ -z "$(ls -A "$out" 2>/dev/null)" ] || { echo "freeze.sh: $out is not empty" >&2; exit 64; }
# The default roots are the collector's own default when AGENT_EVENTS_PROJECT_ROOTS is unset.
[ -n "$roots" ] || roots=${AGENT_EVENTS_PROJECT_ROOTS-$HOME/git:/Volumes/Workshop/macbook/git}
mkdir -p "$out"
trap 'rm -f "$out/fp-live.json" "$out/fp-fixture.json" "$out/strata-counts.txt"; rm -rf "$out/.strata"; rmdir "$out" 2>/dev/null || true' EXIT

echo "freeze: fingerprint from the live environment ($roots, machine $machine)"
PYTHONDONTWRITEBYTECODE=1 python3 "$here/parity_dump.py" fp --roots "$roots" --machine "$machine" > "$out/fp-live.json"
fp_live=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["fp"])' "$out/fp-live.json")

state_file="$state_src/export_state.json"
if [ -f "$state_file" ]; then
  fp_state=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("fp") or "")' "$state_file")
  if [ "$fp_state" != "$fp_live" ]; then
    echo "freeze.sh: the live fingerprint $fp_live is not the one in $state_file ($fp_state); re-freeze after the next tick" >&2
    exit 1
  fi
fi

echo "freeze: cloning the corpus"
if [ "$(uname)" = Darwin ] && cp -cRp "$sessions_src" "$out/sessions" 2>/dev/null; then clone=apfs-clone; else rm -rf "$out/sessions"; cp -Rp "$sessions_src" "$out/sessions"; clone=copy; fi

echo "freeze: state"
mkdir -p "$out/state/$machine"
for f in export_state.json status.json; do [ -f "$state_src/$f" ] && cp -p "$state_src/$f" "$out/state/$machine/$f" || true; done

echo "freeze: roots fixture"
python3 -c 'import json,sys; print("\n".join(json.load(open(sys.argv[1]))["approved_projects"]))' "$out/fp-live.json" > "$out/approved.txt"
mkdir -p "$out/roots"
while IFS= read -r name; do [ -n "$name" ] && mkdir -p "$out/roots/$name/.git"; done < "$out/approved.txt"
PYTHONDONTWRITEBYTECODE=1 python3 "$here/parity_dump.py" fp --roots "$out/roots" --machine "$machine" > "$out/fp-fixture.json"
fp_fix=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["fp"])' "$out/fp-fixture.json")
if [ "$fp_fix" != "$fp_live" ]; then
  echo "freeze.sh: the roots fixture gives fp $fp_fix, the live environment $fp_live; re-freeze" >&2
  exit 1
fi

echo "freeze: strata"
c="$out/sessions"
list() { sort | head -n "$per"; }
tmp="$out/.strata"; mkdir -p "$tmp"
find "$c" -type f -name '*.jsonl' | sort > "$tmp/all"
grep '/run-[0-9]*/session\.jsonl$' "$tmp/all" > "$tmp/children" || true
grep -v '/run-[0-9]*/session\.jsonl$' "$tmp/all" > "$tmp/top" || true
list < "$tmp/children" > "$tmp/s-children"
xargs -r grep -l '"parentSession"' < "$tmp/top" 2>/dev/null | list > "$tmp/s-forks" || true
xargs -r grep -c codemode < "$tmp/top" 2>/dev/null | awk -F: '$NF > 0 { print $NF "\t" $0 }' | sort -rn | head -n "$per" | cut -f2- | sed 's/:[0-9]*$//' > "$tmp/s-codemode" || true
xargs -r grep -L -e pi-stamp -e durationMs < "$tmp/top" 2>/dev/null | list > "$tmp/s-untimed" || true
find "$c" -type f -name '*.jsonl' -size +2000k | sort | while IFS= read -r f; do
  awk 'length($0) > 2000000 { found = 1; exit } END { exit !found }' "$f" && echo "$f"
done | list > "$tmp/s-bigline" || true
list < "$tmp/top" > "$tmp/s-plain"
cat "$tmp"/s-* | sort -u | sed "s|^$c/||" > "$out/strata.txt"
n_strata=$(wc -l < "$out/strata.txt" | tr -d ' ')
for s in children forks codemode untimed bigline plain; do printf '%s=%s ' "$s" "$(wc -l < "$tmp/s-$s" | tr -d ' ')"; done > "$out/strata-counts.txt"
rm -rf "$tmp"

echo "freeze: versions"
{
  echo "python: $(python3 --version 2>&1)"
  echo "node: $(node --version 2>&1 || echo none)"
  echo "sqlite (python): $(python3 -c 'import sqlite3; print(sqlite3.sqlite_version)')"
  echo "sqlite (cli): $(sqlite3 --version 2>&1 | cut -d' ' -f1 || echo none)"
  echo "collector processes:"
  ps -axo pid,etime,command | awk 'NR > 1 && $3 !~ /(^|\/)(ba|z|da|k)?sh$/ && /agent[_-]events|agent-traces|shadow_py_run/' | cut -c1-200 || true
} > "$out/versions.txt"
ref_sha=$(shasum -a 256 "$here/reference.sha256" | cut -d' ' -f1)

python3 - "$out" "$fp_live" "$machine" "$clone" "$n_strata" "$ref_sha" "$here/reference.sha256" <<'PY'
import json, sys
out, fp, machine, clone, n, ref_sha, manifest = sys.argv[1:]
counts = open(out + "/strata-counts.txt").read().strip()
json.dump({"fp": fp, "machine": machine, "clone": clone, "strata": int(n), "strata_counts": counts,
           "reference_sha256": ref_sha, "reference_files": dict(reversed(l.split()) for l in open(manifest) if l.strip()),
           "approved_projects": open(out + "/approved.txt").read().split()},
          open(out + "/FREEZE.json", "w"), indent=1, sort_keys=True)
PY
rm -f "$out/strata-counts.txt" "$out/fp-live.json" "$out/fp-fixture.json"
echo "freeze: done: $out ($clone, $n_strata files in strata.txt, fp $fp_live)"
