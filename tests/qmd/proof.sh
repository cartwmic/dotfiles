#!/bin/sh
# Real-qmd proof for docs/qmd.md. Needs the qmd binary on PATH and the three models (qmd pull); not run in CI.
# Everything runs in a throwaway config and cache dir, never in ~/.config/qmd or ~/.cache/qmd.
#   1. render index.yml from this source (personal profile) and run qmd against it: the file must stay byte-identical
#   2. update the index, then run the skill's own commands: qmd search, qmd get, qmd query
# Usage: tests/qmd/proof.sh [CACHE_DIR_WITH_MODELS]   (default: a fresh cache, so models are downloaded)
# Heavy (hybrid query loads 2.1 GB of models): run as  nice -n 10 heavy-gate --wait 3600 -- tests/qmd/proof.sh
set -eu
here=$(cd "$(dirname "$0")/../.." && pwd)
T=$(cd "$(mktemp -d "${TMPDIR:-/tmp}/qmd-proof.XXXXXX")" && pwd -P)
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/config/qmd" "$T/cache/qmd" "$T/chezmoi"
printf 'data:\n  profile: personal\n' > "$T/chezmoi/chezmoi.yaml"
chezmoi --source "$here" --config "$T/chezmoi/chezmoi.yaml" --config-format yaml execute-template < "$here/dot_config/qmd/index.yml.tmpl" > "$T/rendered.yml"
cp "$T/rendered.yml" "$T/config/qmd/index.yml"
[ -n "${1:-}" ] && ln -s "$1/models" "$T/cache/qmd/models"
unset INDEX_PATH
export QMD_CONFIG_DIR="$T/config/qmd" XDG_CACHE_HOME="$T/cache"
cd "$T"   # qmd prefers a .qmd/index.yaml found in the cwd or an ancestor; start from a directory that has none
command -v qmd >/dev/null || { echo "FAIL: qmd not on PATH" >&2; exit 1; }
pin=$(sed -n 's/.*"npm:@tobilu\/qmd" = "\(.*\)"/\1/p' "$here/dot_config/mise/conf.d/qmd.toml")
qmd --version | grep -q "^qmd $pin " || { echo "FAIL: qmd is $(qmd --version), pin is $pin" >&2; exit 1; }
same() { cmp -s "$T/rendered.yml" "$T/config/qmd/index.yml" || { echo "FAIL: qmd rewrote index.yml after: $1" >&2; diff "$T/rendered.yml" "$T/config/qmd/index.yml" >&2; exit 1; }; echo "ok: index.yml unchanged after $1"; }

st=$(qmd status); echo "$st" | grep -q "Index: $T/cache/qmd/index.sqlite" || { echo "FAIL: qmd is not using the throwaway index" >&2; exit 1; }
echo "ok: pinned version, throwaway index"
qmd status >/dev/null;               same status
qmd update >/dev/null;               same update
hits=$(qmd search "session-recap" -n 3 -c repo-dotfiles); same search
echo "$hits" | grep -q "qmd://repo-dotfiles/" || { echo "FAIL: search found nothing" >&2; exit 1; }
echo "ok: search hit"
qmd collection list >/dev/null;      same "collection list"
doc=$(echo "$hits" | grep -o 'qmd://[^ :]*' | head -1)
qmd get "$doc" -l 5 | grep -q . || { echo "FAIL: get returned nothing" >&2; exit 1; }
same get
echo "ok: get $doc"

# Semantic path: embed only the dotfiles docs (-c; without it qmd embeds every collection), then the documented hybrid command.
QMD_EMBED_PARALLELISM=1 qmd embed -c repo-dotfiles --timeout 0 --max-docs-per-batch 50 --max-batch-mb 8 >/dev/null
ans=$(qmd query "where are session recaps stored and how are they published" -n 3 -c repo-dotfiles)
echo "$ans" | grep -q "qmd://" || { echo "FAIL: query returned no hit" >&2; echo "$ans" >&2; exit 1; }
same query
echo "ok: query answered"
echo "$ans" | head -12
