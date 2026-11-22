#!/bin/sh
# Live proof for kgate Docker jobs (docs/kgate.md, "Docker jobs"). It is P3 of the Docker-for-kgate plan: run it ONCE, after the homelab pieces are applied
# (PriorityClass `kgate-docker`, the scoped ResourceQuota `kgate-docker` in namespace kgate, the kgate image variant that has the docker CLI) and chezmoi has
# applied ~/.local/bin/kgate from this change. It is not part of any test suite and nothing runs it on its own.
#
# What it does, all through the real client against the real cluster:
#   A. One Docker job per candidate node, all at once. Each job runs the steps the campaign needs: `docker info` (a copy-on-write driver, not vfs), a `docker build`
#      that fails without TARGETARCH and needs the network (apt-get, curl), create/start/exec/cp/inspect, `docker run -d --cpus --memory` then `rm -f`,
#      `docker compose up -d` with cpus and mem_limit, exec, down, and a result file in /out that the client copies back.
#      Per node it prints: pass or fail, wall time, docker_peak, `docker system df`, and the node's free ephemeral bytes before, during and after.
#   RED controls, each one fails if the code is broken:
#      (a) the same job, profile without the service: no daemon, the job fails.
#      (b) ephemeral_storage_limit = 2Gi and a pull of an image bigger than that: exit 69, reason `evicted: ...` (the Docker root counts against the limit:
#          its emptyDir has a sizeLimit equal to that limit, and every container has a disk limit, so the kubelet enforces it).
#      (c) the daemon is killed in the sidecar after CMD started: kgate's exit equals CMD's exit (/out/rc), is not 0 and not 69; the note is printed;
#          the record has docker_sidecar.restarts >= 1 (the job waits after the failure so the kubelet's restart has happened). Control: the same job with no kill exits 0, no note, no docker_sidecar.
#      (c2) the sidecar cannot start (the docker:29.9.3-cli image in its place): exit 69, the sidecar named, a log tail from the sidecar, CMD not run.
#           Control: the real dind image runs CMD and exits 0. Needs the P2 client: on an older client the service is refused before any pod exists.
#      (d) after pass, fail, cancel and eviction the job's pod and Secrets are gone; the scoped quota reads back 0 only after ALL jobs have ended.
#      (e) three Docker jobs whose requests exceed the scoped quota: the third queues, refused by the scoped quota (`queued: waiting for quota: exceeded quota:
#          kgate-docker`; a refusal by the general quota proves nothing, so that attempt is cancelled and retried); an ordinary job submitted after it starts
#          without being queued behind that third job (it may still wait for other work); a fourth Docker job waits behind the third. After the first two are
#          cancelled (exit 143) the third and fourth run and end 0. The scoped quota's `used` is exactly the Docker job's CPU while an ordinary job runs beside it.
#      (f) the pod spec of a running Docker job: only the sidecar is privileged; it has no hostPath and no docker.sock; the job container has /cache
#          and is not privileged.
#   Note (n7): while (e) runs, some ordinary kgate jobs on this cluster may wait for namespace quota. The cluster is shared, so (f) and (e) wait for room on
#   both quotas before they start, hold their pods for five minutes at most, and are cancelled as soon as their checks are done (and by a trap on any exit).
#
# It changes the cluster only through kgate jobs and reads it with kubectl (over the same ssh host kgate uses). It prints PASS or FAIL per check and
# exits 1 if any failed. Syntax check only before the cluster is ready: `sh -n docs/kgate-docker-live-proof.sh`.
#
# Inputs (environment):
#   KGATE_DOCKER_JOB_IMAGE    the kgate image variant `docker` (job container), pinned by digest (default: the one homelab#597 built, kgate image run 44986480504)
#   KGATE_DOCKER_DIND_IMAGE   the dind sidecar image, pinned by digest (default: docker:29.9.3-dind's digest)
#   KGATE_DOCKER_CLI_IMAGE    an image that cannot start dockerd, for (c2) (default: docker:29.9.3-cli's digest)
#   KGATE_PROOF_NODES         nodes for A, space separated (default: agent-1, agent-2, the G14; the client refuses --node for the overflow node agent-4)
#   KGATE_PROOF_BIG_IMAGE     an image over 4 GiB uncompressed for (b) (default nvidia/cuda:12.4.1-devel-ubuntu22.04)
#   KGATE_SSH, KGATE_SSH_KEY  as for kgate itself
#   KGATE_PROOF_QUIET_WAIT    seconds to wait, before (f) and (e), for the scoped quota to be idle and the general kgate-cpu quota to have room (default 7200)
#   KGATE_PROOF_E_TRIES, KGATE_PROOF_E_GAP   attempts at (e) (default 3) and the least seconds between two (default 1800)
#   KGATE_PROOF_KEEP          set to anything to keep the temp dir (every job's output and exit code) after the run
set -u

JOB_IMAGE=${KGATE_DOCKER_JOB_IMAGE:-ghcr.io/cartwmic/kgate@sha256:be170720691c03c7edca206d34220863142de522d32ae3c52306d94a117aa69b}
DIND_IMAGE=${KGATE_DOCKER_DIND_IMAGE:-docker@sha256:7bf70dcb85c822e3fa6f2d332143e474b99147b9d7b39102b0cfe8b04a7dd61b}
CLI_IMAGE=${KGATE_DOCKER_CLI_IMAGE:-docker@sha256:5a7af0dcb0e46c803efe9b45371dd21cb500e5b4453250394ac6f06d49b6e6f1}
NODES=${KGATE_PROOF_NODES:-"ubuntu-server-k8s-agent-1 ubuntu-server-k8s-agent-2 cartwmic-g14-wsl"}
BIG_IMAGE=${KGATE_PROOF_BIG_IMAGE:-nvidia/cuda:12.4.1-devel-ubuntu22.04}
STATE=${XDG_STATE_HOME:-$HOME/.local/state}/kgate
KEY=${KGATE_SSH_KEY:-$HOME/.ssh/homelab}

work=$(mktemp -d /tmp/kgate-docker-proof.XXXXXX)
pids=""
fails=0
all_ids=""
cleanup() {
  # A job that has not ended (no exit code yet) is stopped, whatever way the script leaves, so no pod outlives the run and no job keeps the quota. The client
  # itself is sent SIGTERM (what `kgate cancel` does): it takes its own pod and Secrets down and writes its end line. That reaches a job that has not printed its
  # pod line yet, which `kgate cancel ID` cannot.
  for f in "$work"/*.pid; do
    [ -e "$f" ] || continue
    nm=$(basename "$f" .pid)
    [ -f "$work/$nm.rc" ] && continue
    kill -TERM "$(cat "$f")" 2>/dev/null
  done
  for f in "$work"/*.pid; do
    [ -e "$f" ] || continue
    n=0; while kill -0 "$(cat "$f")" 2>/dev/null && [ "$n" -lt 90 ]; do sleep 1; n=$((n + 1)); done
  done
  for p in $pids; do kill "$p" 2>/dev/null; done
  if [ -n "${KGATE_PROOF_KEEP:-}" ]; then echo "kept: $work"; else rm -rf "$work"; fi
}
# cleanup runs once, on EXIT. A signal ends the script (130, 143): in dash a trap on INT or TERM that only returns would let the script carry on submitting jobs.
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# nap N: sleep N seconds the signal can cut short. dash runs a trap only after the foreground command ends, so a plain `sleep 60` would delay INT or TERM by up to a minute.
nap() { sleep "$1" & wait $!; }

ok()   { echo "PASS  $*"; }
bad()  { echo "FAIL  $*"; fails=$((fails + 1)); }
check() { # check "what" cmd...   (cmd run with sh -c, so it can be a test expression)
  what=$1; shift
  if sh -c "$*" >/dev/null 2>&1; then ok "$what"; else bad "$what"; fi
}

# ---- helpers ---------------------------------------------------------------------------------------------------------------------------------

host() { # the first host kgate would use
  h=${KGATE_SSH:-$(cat "$HOME/.config/kgate/host" 2>/dev/null)}
  printf '%s\n' "$h" | tr ', ' '\n\n' | sed -n '/./{p;q;}'
}
HOST=$(host)
[ -n "$HOST" ] || { echo "no cluster host: set KGATE_SSH" >&2; exit 64; }
kc() { # kubectl in namespace kgate, the way the client runs it. Every argument is single-quoted for the remote shell (no empty argument is added)
  q=""
  for a in "$@"; do q="$q '$(printf '%s' "$a" | sed "s/'/'\\\\''/g")'"; done
  ssh -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=8 -i "$KEY" "$HOST" "sudo kubectl --kubeconfig /etc/kubernetes/admin.conf -n kgate$q"
}
pyj() { python3 -I -c "$@"; }

# mkrepo NAME  -> a git repo $work/NAME with kgate.toml from stdin plus the scripts in $work/scripts; prints the dir
mkrepo() {
  d=$work/$1
  mkdir -p "$d"
  cat > "$d/kgate.toml"
  cp "$work"/scripts/* "$d/"
  ( cd "$d" && git init -q && git add -A && git -c user.name=proof -c user.email=proof@example.invalid commit -q -m proof )
  printf '%s\n' "$d"
}

# profile TABLE_EXTRA... writes a docker profile on stdout: size line options come as arguments (already TOML)
docker_profile() { # docker_profile "job lines" "docker lines" ["image override"] ["disk lines"]
  # every Docker pod has a disk request and limit (the profile's disk is the pod's total, the sidecar takes a share); the limit also sizes the data root's emptyDir
  disk=${4:-'ephemeral_storage = "6Gi"
ephemeral_storage_limit = "12Gi"'}
  cat <<TOML
image  = "$JOB_IMAGE"
cpu    = 1
memory = "1Gi"
memory_limit = "2Gi"
services = ["docker"]
$disk
$1

[docker]
image  = "${3:-$DIND_IMAGE}"
cpu    = 3
memory = "2Gi"
memory_limit = "4Gi"
$2
TOML
}
plain_profile() {
  cat <<TOML
image  = "$JOB_IMAGE"
cpu    = 1
memory = "512Mi"
$1
TOML
}

# run NAME REPO [kgate args...] -- CMD...   foreground; output in $work/NAME.out, exit code in $work/NAME.rc
run() {
  name=$1; repo=$2; shift 2
  # the client runs in the background of this subshell so its pid is known (cleanup signals it, not the subshell)
  ( cd "$repo" && { kgate --profile kgate.toml "$@" > "$work/$name.out" 2>&1 & echo $! > "$work/$name.pid"; wait $!; echo $? > "$work/$name.rc"; } )
}
# start NAME REPO ... -> same, in the background; wait with wait_job NAME
start() { run "$@" & pids="$pids $!"; eval "pid_$1=$!"; }
wait_job() { eval "wait \$pid_$1" 2>/dev/null; } # waits for a job started with start; call it in this shell, never inside $(...), where wait cannot see the job. Read the exit with rc_of
rc_of() { cat "$work/$1.rc" 2>/dev/null || echo 255; }
jobid() { sed -n 's/^kgate: pod \([^ ]*\) on .*/\1/p' "$work/$1.out" 2>/dev/null | head -1; }
running() { grep -q '^kgate: pod running on ' "$work/$1.out" 2>/dev/null; } # the pod exists and CMD is about to run (the "kgate: pod ID on NODE" line comes first, before any queueing)
wait_running() { # wait up to $2 s for NAME's pod to be running
  n=0
  while [ "$n" -lt "${2:-120}" ]; do running "$1" && return 0; [ -f "$work/$1.rc" ] && return 1; nap 2; n=$((n + 2)); done
  return 1
}
rec() { # rec ID KEY -> the record's value as JSON ("null" when absent)
  grep -aF "\"id\": \"$1\"" "$STATE/log.jsonl" 2>/dev/null | tail -1 | pyj 'import json,sys; r=json.loads(sys.stdin.read() or "{}"); print(json.dumps(r.get(sys.argv[1])))' "$2"
}
out_file() { cat "$STATE/$1.out/$2" 2>/dev/null; } # out_file ID NAME
node_free() { # free ephemeral bytes on a node, from the kubelet's stats summary
  kc get --raw "/api/v1/nodes/$1/proxy/stats/summary" 2>/dev/null | pyj 'import json,sys; print(json.load(sys.stdin)["node"]["fs"]["availableBytes"])' 2>/dev/null || echo unknown
}
gone() { # gone ID: the job's pod and Secrets no longer exist. A failed read is not "gone": it fails the check
  left=$(kc get pods,secrets -l "kgate-job=$1" -o name 2>/dev/null) || return 1
  [ -z "$left" ]
}
quota_hard_cpu() { kc get resourcequota "$1" -o jsonpath='{.status.hard.requests\.cpu}' 2>/dev/null; }
quota_cpu() { # quota_cpu NAME -> the CPU requests counted against the quota now (a whole number; 0 when none), or nothing when it cannot be read
  v=$(kc get resourcequota "$1" -o jsonpath='{.status.used.requests\.cpu}' 2>/dev/null) || return 1
  case $v in '') echo 0;; *[!0-9]*) return 1;; *) echo "$v";; esac
}
quiet() { # quiet SCOPED_MAX GENERAL_MAX [WAIT_S]: wait until the scoped Docker quota has at most SCOPED_MAX CPU in use and the general kgate-cpu quota at most GENERAL_MAX
  # The cluster is shared: other agents' jobs use both quotas, and a Docker job refused by the general quota is not a test of the scoped one. Nothing is submitted while waiting.
  n=0
  while :; do
    s=$(quota_cpu kgate-docker) && g=$(quota_cpu kgate-cpu) || { echo "    cannot read the quotas"; return 1; }
    if [ "$s" -le "$1" ] && [ "$g" -le "$2" ]; then return 0; fi
    [ "$n" -ge "${3:-${KGATE_PROOF_QUIET_WAIT:-7200}}" ] && { echo "    the cluster stayed busy: scoped quota $s cpu (want <= $1), kgate-cpu $g (want <= $2)"; return 1; }
    [ $((n % 600)) = 0 ] && echo "    waiting for a quiet cluster: scoped quota $s cpu (want <= $1), kgate-cpu $g (want <= $2)"
    nap 60; n=$((n + 60))
  done
}
quota_used() { # the scoped quota's used, as JSON; prints nothing and fails when it cannot be read
  q=$(kc get resourcequota kgate-docker -o json 2>/dev/null) || return 1
  printf '%s' "$q" | pyj 'import json,sys; print(json.dumps(json.load(sys.stdin)["status"].get("used", {})))'
}

GENERAL_CPU=$(quota_hard_cpu kgate-cpu)   # the general quota's CPU limit: the room the proof needs is checked against it
case $GENERAL_CPU in ''|*[!0-9]*) echo "cannot read the kgate-cpu quota's CPU limit ('$GENERAL_CPU')" >&2; exit 64;; esac

# ---- the scripts the pods run ----------------------------------------------------------------------------------------------------------------
mkdir -p "$work/scripts"

# The campaign's calls. Stops at the first failing step; writes /out/result last.
cat > "$work/scripts/steps.sh" <<'SH'
set -eu
mkdir -p /out
echo "== 1 docker info"
docker info > /out/info.txt
cat /out/info.txt | sed -n '/Storage Driver/p;/Docker Root Dir/p;/Architecture/p'
# a copy-on-write driver, not vfs: Docker 29 with the containerd image store reports overlayfs, older setups overlay2
grep -Eq 'Storage Driver: (overlay2|overlayfs)' /out/info.txt
echo "== 2 docker build (needs TARGETARCH and the network)"
mkdir -p ctx && cat > ctx/Dockerfile <<'EOF'
FROM debian:12-slim
ARG TARGETARCH
RUN test -n "$TARGETARCH" && apt-get update -qq && apt-get install -y -qq curl >/dev/null && curl -fsSI https://deb.debian.org >/dev/null
EOF
docker build -q -t proof:1 ctx
echo "== 3 create/start/exec/cp/inspect"
docker create --name p3 proof:1 sleep 60 >/dev/null
docker start p3 >/dev/null
docker exec p3 true
docker cp p3:/usr/lib/os-release /out/os-release   # a regular file: /etc/os-release is a symlink out of the tree, which the client refuses to copy back
docker inspect -f '{{.State.Running}}' p3 | grep -qx true
docker rm -f p3 >/dev/null
echo "== 4 run -d --cpus --memory"
docker run -d --name p4 --cpus 1 --memory 512m proof:1 sleep infinity >/dev/null
test "$(docker inspect -f '{{.HostConfig.NanoCpus}} {{.HostConfig.Memory}}' p4)" = "1000000000 536870912"
docker rm -f p4 >/dev/null
echo "== 5 compose with cpus and mem_limit"
cat > compose.yaml <<'EOF'
services:
  s:
    image: proof:1
    command: sleep infinity
    cpus: 0.5
    mem_limit: 256m
EOF
docker compose up -d
docker compose exec -T s true
docker compose down
echo "== 6 result"
docker system df > /out/df.txt
echo ok > /out/result
SH

# (c): pull, run a container that outlives the kill, report the client's exit status in /out/rc and exit with it. $1 = seconds the container sleeps, $2 = how long a
# failed run waits before exiting (0: it does not).
cat > "$work/scripts/hold.sh" <<'SH'
mkdir -p /out
docker pull busybox >/dev/null 2>&1
docker run --rm busybox sleep "${1:-120}"
rc=$?
echo "$rc" > /out/rc
# A daemon that died is restarted by the kubelet only after its restart delay; stay up until that has happened, so the client reads a restart, not the
# moment between the daemon's end and its restart. A job that did not fail does not wait.
[ "$rc" = 0 ] || sleep "${2:-40}"
exit "$rc"
SH

cat > "$work/scripts/ran.sh" <<'SH'
mkdir -p /out
echo ran > /out/ran
SH

cat > "$work/scripts/sleep.sh" <<'SH'
mkdir -p /out
sleep "${1:-45}"
SH

cat > "$work/scripts/pull.sh" <<'SH'
docker pull "$1"
SH

cat > "$work/scripts/info.sh" <<'SH'
set -e
docker info >/dev/null
SH

# ---- A. one Docker job per node, all at once ---------------------------------------------------------------------------------------------------
echo "=== A. the campaign's steps on each node (together)"
repoA=$(docker_profile "" "" | mkrepo A)
i=0
for node in $NODES; do
  i=$((i + 1))
  echo "$(node_free "$node")" > "$work/free-before-$i"
  start "A$i" "$repoA" --node "$node" -- sh ./steps.sh
done
i=0
for node in $NODES; do
  i=$((i + 1))
  wait_job "A$i"
  rc=$(rc_of "A$i")
  id=$(jobid "A$i")
  free_after=$(node_free "$node")
  if [ "$rc" = 0 ] && [ "$(out_file "$id" result)" = ok ]; then ok "A $node: passed (kgate job $id)"; else bad "A $node: exit $rc (kgate job $id), see $work/A$i.out"; tail -n 15 "$work/A$i.out"; fi
  echo "    $node: wall $(rec "$id" duration_s) s, docker_peak $(rec "$id" docker_peak) bytes, node free ephemeral before $(cat "$work/free-before-$i") after $free_after"
  [ -f "$STATE/$id.out/df.txt" ] && sed 's/^/    df: /' "$STATE/$id.out/df.txt"
  if [ "$(rec "$id" docker_sidecar)" = null ]; then ok "A $node: no daemon death recorded"; else bad "A $node: docker_sidecar recorded: $(rec "$id" docker_sidecar)"; fi
  all_ids="$all_ids $id"
done

# ---- (a) no service ------------------------------------------------------------------------------------------------------------------------
echo "=== (a) the same job without the service"
repoa=$(plain_profile "" | mkrepo a)
run a "$repoa" -- sh ./info.sh
if [ "$(rc_of a)" != 0 ] && grep -Eqi 'failed to connect|cannot connect' "$work/a.out"; then ok "(a) no daemon: the job failed, and the docker CLI said it could not connect (Docker 29 says 'failed to connect')"; else bad "(a) expected a non-zero exit and a docker 'failed to connect' line, got exit $(rc_of a)"; fi
all_ids="$all_ids $(jobid a)"

# ---- (b) eviction ----------------------------------------------------------------------------------------------------------------------------
echo "=== (b) a pull larger than ephemeral_storage_limit"
repob=$(docker_profile "" "" "" 'ephemeral_storage = "1Gi"
ephemeral_storage_limit = "2Gi"' | mkrepo b)
run b "$repob" --wait 1800 -- sh ./pull.sh "$BIG_IMAGE"
idb=$(jobid b)
reasonb=$(rec "$idb" reason)
if [ "$(rc_of b)" = 69 ] && case $reasonb in '"evicted:'*) true;; *) false;; esac; then ok "(b) exit 69, reason $reasonb"; else bad "(b) expected exit 69 with reason 'evicted: ...', got exit $(rc_of b), reason $reasonb"; fi
all_ids="$all_ids $idb"

# ---- (c) the daemon dies after CMD started ---------------------------------------------------------------------------------------------------
repoc=$(docker_profile "" "" | mkrepo c)
kill_case() { # kill_case NAME HOLD_S: run hold.sh, stop dockerd in the sidecar while its container runs, check what the client says. HOLD_S = how long CMD waits after the failure
  nm=$1; hold=$2
  start "$nm" "$repoc" -- sh ./hold.sh 120 "$hold"
  if wait_running "$nm" 3600; then
    id=$(jobid "$nm")
    n=0
    until [ -n "$(kc exec "$id" -c dind -- docker ps -q 2>/dev/null)" ] || [ "$n" -ge 240 ]; do nap 2; n=$((n + 2)); done
    # PID 1 in the sidecar is docker-init, which hands SIGTERM to dockerd; dockerd stops and the container ends. (SIGKILL would do nothing: PID 1 ignores it from inside its own namespace.)
    err=$(kc exec "$id" -c dind -- kill -TERM 1 2>&1) || bad "($nm) could not signal dockerd in $id: $err"
  else
    bad "($nm) the job never ran (see $work/$nm.out)"
  fi
  wait_job "$nm"
  rcc=$(rc_of "$nm")
  id=$(jobid "$nm")
  cmdrc=$(out_file "$id" rc | tr -d '[:space:]')
  if [ -n "$cmdrc" ] && [ "$rcc" = "$cmdrc" ] && [ "$rcc" != 0 ] && [ "$rcc" != 69 ]; then ok "(c) $nm: kgate's exit $rcc equals CMD's (/out/rc), non-zero and not 69"; else bad "(c) $nm: kgate exit $rcc, /out/rc '$cmdrc' (want equal, non-zero, not 69)"; fi
  if grep -Eq 'kgate: the docker daemon (restarted|stopped) during the job' "$work/$nm.out"; then ok "(c) $nm: the note was printed"; else bad "(c) $nm: no 'the docker daemon restarted' note"; fi
  sc=$(rec "$id" docker_sidecar)
  if [ "$hold" -gt 0 ]; then   # the kubelet had time to restart it: the record must say so
    if [ "$(printf '%s' "$sc" | pyj 'import json,sys; v=json.loads(sys.stdin.read() or "null"); print(1 if v and v.get("restarts",0)>=1 else 0)')" = 1 ]; then ok "(c) $nm: docker_sidecar.restarts >= 1: $sc"; else bad "(c) $nm: docker_sidecar not recorded with restarts >= 1: $sc"; fi
  else   # CMD failed the moment the daemon died: the client's own wait for the kubelet's status must still see the daemon end, restarted or stopped
    if [ "$(printf '%s' "$sc" | pyj 'import json,sys; v=json.loads(sys.stdin.read() or "null"); print(1 if v and v.get("exit") is not None else 0)')" = 1 ]; then ok "(c) $nm: docker_sidecar recorded with the daemon's exit: $sc"; else bad "(c) $nm: docker_sidecar not recorded: $sc"; fi
  fi
  all_ids="$all_ids $id"
}
echo "=== (c) kill dockerd in the sidecar while CMD's container runs (CMD waits for the restart)"
kill_case c 40
echo "=== (c) the same, CMD exits at once: the client's own wait for the daemon's end"
kill_case c3 0

echo "=== (c) control: the same job without the kill"
run c0 "$repoc" -- sh ./hold.sh 5
idc0=$(jobid c0)
if [ "$(rc_of c0)" = 0 ] && ! grep -q 'the docker daemon' "$work/c0.out" && [ "$(rec "$idc0" docker_sidecar)" = null ]; then ok "(c) control: exit 0, no note, no docker_sidecar"; else bad "(c) control: exit $(rc_of c0), see $work/c0.out"; fi
all_ids="$all_ids $idc0"

# ---- (c2) the sidecar cannot start -----------------------------------------------------------------------------------------------------------
echo "=== (c2) start failure: the cli image where dind goes"
repoc2=$(docker_profile "" "" "$CLI_IMAGE" | mkrepo c2)
run c2 "$repoc2" --wait 600 -- sh ./ran.sh
idc2=$(jobid c2)
tail_text=$(sed -n '/its last log lines:/,$p' "$work/c2.out" | sed '1s/.*its last log lines://' | grep -v '^kgate:' | tr -d '[:space:]')
if [ "$(rc_of c2)" = 69 ] && grep -q 'docker sidecar did not become ready' "$work/c2.out" && [ -n "$tail_text" ] && [ -z "$(out_file "$idc2" ran)" ]; then ok "(c2) exit 69, the docker sidecar named, a log tail from it, CMD not run"; else bad "(c2) exit $(rc_of c2); tail '$tail_text'; see $work/c2.out"; fi
echo "=== (c2) control: the real dind image runs CMD"
run c2ok "$repoc" -- sh ./ran.sh
idc2ok=$(jobid c2ok)
if [ "$(rc_of c2ok)" = 0 ] && [ "$(out_file "$idc2ok" ran | tr -d '[:space:]')" = ran ]; then ok "(c2) control: CMD ran, exit 0"; else bad "(c2) control: exit $(rc_of c2ok)"; fi
all_ids="$all_ids $idc2 $idc2ok"

# ---- (f) the pod spec, and (d) cancel ----------------------------------------------------------------------------------------------------------
echo "=== (f) the pod spec of a running Docker job; (d) cancel"
repoN=$(plain_profile "" | mkrepo N)
# The Docker job and an ordinary job are submitted together and both hold for five minutes at most; they are cancelled as soon as the checks are done (and by the
# trap if the script leaves early). A try needs room on the general quota for both, and the scoped quota idle; if they do not both run, it is cancelled and tried once more.
fok=no; ftry=0
while [ "$ftry" -lt 2 ] && [ "$fok" = no ]; do
  quiet 0 $((GENERAL_CPU - 12)) || break
  ftry=$((ftry + 1))
  start f "$repoc" --wait 900 -- sh ./sleep.sh 280
  start N0 "$repoN" --wait 900 -- sh ./sleep.sh 280
  if wait_running f 950 && wait_running N0 950 && [ ! -f "$work/f.rc" ]; then fok=yes; break; fi
  echo "    try $ftry: the Docker job and the ordinary job did not run together (cluster busy)"
  for j in f N0; do kgate cancel "$(jobid $j)" >/dev/null 2>&1; wait_job "$j"; all_ids="$all_ids $(jobid $j)"; done
  rm -f "$work"/f.out "$work"/f.rc "$work"/N0.out "$work"/N0.rc
done
if [ "$fok" = yes ]; then
  idf=$(jobid f)
  nap 5
  kc get pod "$idf" -o json > "$work/f.json" 2>/dev/null
  if pyj '
import json,sys
p=json.load(open(sys.argv[1])); s=p["spec"]
inits={c["name"]:c for c in s.get("initContainers",[])}; mains={c["name"]:c for c in s["containers"]}
priv=lambda c: bool((c.get("securityContext") or {}).get("privileged"))
hp={v["name"]:v["hostPath"]["path"] for v in s.get("volumes",[]) if "hostPath" in v}
assert list(inits)==["dind"] and priv(inits["dind"]), "dind must be the one privileged init container"
assert not any(priv(c) for c in mains.values()), "the job container must not be privileged"
vm={m["name"] for m in inits["dind"].get("volumeMounts",[])}
assert not (vm & set(hp)), "the sidecar mounts a hostPath: %r" % (vm & set(hp))
assert not any("docker.sock" in str(v) for v in s.get("volumes",[])), "docker.sock in the volumes"
job=next(iter(mains.values()))
assert any(m["mountPath"]=="/cache" and m["name"] in hp for m in job["volumeMounts"]), "the job container lost /cache"
assert p["spec"].get("priorityClassName")=="kgate-docker", p["spec"].get("priorityClassName")
' "$work/f.json" 2>"$work/f.err"; then ok "(f) pod spec: only dind privileged, no hostPath or docker.sock on it, /cache on the job container, class kgate-docker"; else bad "(f) pod spec: $(cat "$work/f.err")"; fi
  used=$(quota_used)
  echo "    quota used while a Docker job and an ordinary job run: $used"
  # the Docker job asks 4 CPU (job 1 + sidecar 3); the ordinary job asks 4 more, on the general quota only
  if printf '%s' "$used" | pyj 'import json,sys; u=json.loads(sys.stdin.read()); assert u.get("requests.cpu") == "4", u'; then ok "(d,e) the scoped quota counts the Docker job (4 cpu) and not the ordinary job running beside it"; else bad "(d,e) the scoped quota is not exactly the Docker job's 4 cpu: $used"; fi
  kgate cancel "$idf" >/dev/null 2>&1
  kgate cancel "$(jobid N0)" >/dev/null 2>&1
  wait_job f
  wait_job N0
  rcf=$(rc_of f)
  if [ "$rcf" = 143 ]; then ok "(d) cancel: exit 143"; else bad "(d) cancel: exit $rcf"; fi
  all_ids="$all_ids $idf $(jobid N0)"
else
  bad "(f) the job never ran"
fi

# ---- (e) the queue rule ------------------------------------------------------------------------------------------------------------------------
echo "=== (e) quota wait and the queue rule"
hard=$(kc get resourcequota kgate-docker -o json 2>/dev/null | pyj 'import json,sys; h=json.load(sys.stdin)["status"]["hard"]; print(h.get("requests.cpu") or h.get("cpu") or "")')
case $hard in ''|*[!0-9]*) bad "(e) cannot read the quota's CPU limit ('$hard'): size the jobs by hand"; hard="";; esac
if [ -n "$hard" ]; then
  # sizes sound under the slot rounding: the pod asks for a whole number of 4-CPU slots (sidecar cpu + job cpu, rounded up as one), so choose that
  # total P with 2P <= hard < 3P. job cpu = 1, so the sidecar gets P-1 and the total is exactly P.
  P=4
  while [ $((3 * P)) -le "$hard" ]; do P=$((P + 4)); done
  if [ $((2 * P)) -gt "$hard" ]; then
    bad "(e) the quota's CPU ($hard) cannot hold two pods of whole slots with a third refused; size the proof by hand"
  else
    side=$((P - 1))
    # small disk, to be kind to the nodes' root disks (the quota counts pods, CPU and memory, not disk)
    repoE=$(docker_profile "" "" "" 'ephemeral_storage = "2Gi"
ephemeral_storage_limit = "4Gi"' | sed "s/^cpu    = 3/cpu    = $side/" | mkrepo E)
    echo "    quota requests.cpu $hard; each Docker job asks $P cpu (job 1 + sidecar $side)"
    # The third job must be refused by the SCOPED quota: a refusal by the general kgate-cpu quota (other work fills it) says nothing about the scoped one, and
    # the queue rule cannot be seen then. The cluster is shared, so this is careful with it:
    #  - an attempt starts only when the general quota has room for all three Docker jobs (3P CPU) and the scoped quota is idle;
    #  - at most one attempt every KGATE_PROOF_E_GAP seconds (default 1800);
    #  - the first two jobs hold their pods for five minutes at most, and are cancelled as soon as the checks that need them are done, or when the third
    #    job was not refused by the scoped quota, and by the script's trap on any way out.
    scoped=no; try=0; last=0
    while [ "$try" -lt "${KGATE_PROOF_E_TRIES:-3}" ]; do
      wait_for=$((last + ${KGATE_PROOF_E_GAP:-1800} - $(date +%s)))
      [ "$wait_for" -gt 0 ] && nap "$wait_for"
      quiet 0 $((GENERAL_CPU - 3 * P)) || break
      try=$((try + 1)); last=$(date +%s)
      start e1 "$repoE" --wait 3600 -- sh ./sleep.sh 300
      start e2 "$repoE" --wait 3600 -- sh ./sleep.sh 300
      if ! { wait_running e1 3700 && wait_running e2 3700; }; then
        echo "    attempt $try: the first two Docker jobs did not start (cluster busy)"
      else
        start e3 "$repoE" --wait 900 -- sh ./ran.sh
        n=0; until grep -q 'queued: waiting for quota' "$work/e3.out" 2>/dev/null || running e3 || [ -f "$work/e3.rc" ] || [ "$n" -ge 120 ]; do nap 2; n=$((n + 2)); done
        if grep -q 'queued: waiting for quota: exceeded quota: kgate-docker' "$work/e3.out"; then scoped=yes; break; fi
        echo "    attempt $try: the third Docker job was not refused by the scoped quota ($(grep -m1 'queued: waiting for quota' "$work/e3.out" | cut -c1-140))"
      fi
      for j in e3 e1 e2; do [ -f "$work/$j.out" ] && { kgate cancel "$(jobid $j)" >/dev/null 2>&1; wait_job "$j"; all_ids="$all_ids $(jobid $j)"; }; done
      rm -f "$work"/e[123].out "$work"/e[123].rc
    done
    if [ "$scoped" = yes ]; then ok "(e) the third Docker job queued on the scoped quota: $(grep -m1 'queued: waiting for quota' "$work/e3.out" | cut -c1-160)"; else bad "(e) the third Docker job was never refused by the kgate-docker quota in $try attempts (the cluster was too busy; run it when it is quiet)"; fi
    if [ "$scoped" = yes ]; then
    # an ordinary job submitted after it: starts at once, no 'behind' line, and it ends while e3 is still waiting
    start eN "$repoN" --wait 900 -- sh ./sleep.sh 5
    wait_running eN 150 || { bad "(e) the ordinary job did not start within 150 s (see $work/eN.out)"; kgate cancel "$(jobid eN)" >/dev/null 2>&1; }
    if running e3; then e3_waiting=no; else e3_waiting=yes; fi   # read when the ordinary job starts: it must not have had to wait for the third Docker job
    # a fourth Docker job submitted after the third waits behind it
    start e4 "$repoE" --wait 900 -- sh ./ran.sh
    n=0; until grep -q "queued: behind $(jobid e3)" "$work/e4.out" 2>/dev/null || [ "$n" -ge 60 ]; do nap 2; n=$((n + 2)); done
    if grep -q "queued: behind $(jobid e3)" "$work/e4.out"; then ok "(e) the fourth Docker job waits behind the third: $(grep -m1 "queued: behind $(jobid e3)" "$work/e4.out" | cut -c1-160)"; else bad "(e) the fourth Docker job did not queue behind the third"; fi
    wait_job eN
    rcN=$(rc_of eN)
    if [ "$rcN" = 0 ] && ! grep -q "queued: behind $(jobid e3)" "$work/eN.out" && [ "$e3_waiting" = yes ]; then ok "(e) the ordinary job ran while the third Docker job waited, and was not queued behind it"; else bad "(e) ordinary job: exit $rcN, behind-line '$(grep "queued: behind $(jobid e3)" "$work/eN.out" | head -1)', third Docker job still waiting when it started: $e3_waiting (see $work/eN.out)"; fi
    # the first two end (cancelled), which frees the scoped quota: the queued jobs then run, in order, and end 0
    kgate cancel "$(jobid e1)" >/dev/null 2>&1
    kgate cancel "$(jobid e2)" >/dev/null 2>&1
    for j in e1 e2; do
      wait_job "$j"
      if [ "$(rc_of "$j")" = 143 ]; then ok "(e) $j cancelled: exit 143"; else bad "(e) $j exit $(rc_of "$j"), want 143"; fi
      all_ids="$all_ids $(jobid $j)"
    done
    for j in e3 e4; do
      wait_job "$j"
      rcj=$(rc_of "$j")
      if [ "$rcj" = 0 ]; then ok "(e) $j ended 0 (a queued job runs, it does not fail)"; else bad "(e) $j exit $rcj"; fi
      all_ids="$all_ids $(jobid $j)"
    done
    all_ids="$all_ids $(jobid eN)"
    fi
  fi
fi

# ---- (d) after everything: cleanup and the quota at zero ------------------------------------------------------------------------------------------
echo "=== (d) every job's pod and Secrets are gone; the scoped quota is back to zero"
for id in $all_ids; do
  [ -n "$id" ] || continue
  if gone "$id"; then ok "(d) $id: pod and Secrets gone"; else bad "(d) $id: pod or Secrets left"; fi
done
quiet 0 999 600 >/dev/null   # the quota is released a little after the last pod goes: give it ten minutes
used=$(quota_used)
if printf '%s' "$used" | pyj 'import json,re,sys; u=json.loads(sys.stdin.read()); assert all(re.fullmatch(r"0[A-Za-z]*", str(v)) for v in u.values()), u'; then ok "(d) the scoped quota's used is 0 after all jobs: $used"; else bad "(d) the scoped quota still shows use: $used"; fi

echo
if [ "$fails" = 0 ]; then echo "ALL CHECKS PASSED"; exit 0; else echo "$fails CHECK(S) FAILED"; exit 1; fi
