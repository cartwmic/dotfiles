#!/bin/sh
# Live proof for the kgate record keys (dotfiles PR "kgate-record-keys"). Run after the PR is merged and chezmoi has applied ~/.local/bin/kgate.
# One short homelab job with priority_class = "kgate-first" and cpu_limit = 1 in a scratch repo; prints the job's pod line and its log.jsonl record.
# Expected: the pod line ends "..., 1 cpu limit, priority class kgate-first" and the record has "priority_class": "kgate-first", "cpu_limit": 1.
# The image comes from the coordinator profile (KGATE_PROOF_IMAGE overrides it): any image the homelab profile accepts works.
set -eu
image=${KGATE_PROOF_IMAGE:-$(sed -n 's/^image *= *"\(.*\)"/\1/p' "$HOME/git/coordinator/kgate.toml" | head -1)}
[ -n "$image" ] || { echo "no image: set KGATE_PROOF_IMAGE" >&2; exit 64; }
repo=$(mktemp -d /tmp/kgate-record-keys-proof.XXXXXX)
trap 'rm -rf "$repo"' EXIT
cd "$repo"
git init -q
cat > kgate.toml <<TOML
image = "$image"
cpu = 1
memory = "256Mi"
cpu_limit = 1
priority_class = "kgate-first"
TOML
git add kgate.toml
git -c user.name=proof -c user.email=proof@example.invalid commit -q -m proof
out=$(mktemp)
kgate -- true 2>&1 | tee "$out"
id=$(sed -n 's/^kgate: pod \([^ ]*\) on .*/\1/p' "$out" | head -1)
rm -f "$out"
echo "--- pod line"
echo "(above: the line starting 'kgate: pod $id')"
echo "--- log.jsonl record"
grep -F "\"id\": \"$id\"" "${XDG_STATE_HOME:-$HOME/.local/state}/kgate/log.jsonl" | tail -1 | python3 -c 'import json,sys; r=json.loads(sys.stdin.read()); print(json.dumps({k: r.get(k) for k in ("id","cluster","exit","cpu","cpu_limit","priority_class")}))'
