#!/bin/sh
# Live proof for kgate Docker jobs (docs/kgate.md, "Docker jobs"). It is P3 of the Docker-for-kgate plan: run it ONCE, after the homelab pieces are applied
# (PriorityClass `kgate-docker`, the scoped ResourceQuota `kgate-docker` in namespace kgate, the kgate image variant that has the docker CLI) and chezmoi has
# applied ~/.local/bin/kgate from this change. It is not part of any test suite and nothing runs it on its own.
#
# What it does, all through the real client against the real cluster:
#   A. One Docker job per candidate node, all four at once. Each job runs the steps the campaign needs: `docker info` (overlay2, not vfs), a `docker build`
#      that fails without TARGETARCH and needs the network (apt-get, curl), create/start/exec/cp/inspect, `docker run -d --cpus --memory` then `rm -f`,
#      `docker compose up -d` with cpus and mem_limit, exec, down, and a result file in /out that the client copies back.
#      Per node it prints: pass or fail, wall time, docker_peak, `docker system df`, and the node's free ephemeral bytes before, during and after.
#   RED controls, each one fails if the code is broken:
#      (a) the same job, profile without the service: no daemon, the job fails.
#      (b) ephemeral_storage_limit = 2Gi and a pull of an image bigger than that: exit 69, reason `evicted: ...` (the Docker root counts against the limit:
#          its emptyDir has a sizeLimit equal to that limit, and every container has a disk limit, so the kubelet enforces it).
#      (c) the daemon is killed in the sidecar after CMD started: kgate's exit equals CMD's exit (/out/rc), is not 0 and not 69; the note is printed;
#          the record has docker_sidecar.restarts >= 1. Control: the same job with no kill exits 0, no note, no docker_sidecar.
#      (c2) the sidecar cannot start (the docker:29.9.3-cli image in its place): exit 69, the sidecar named, a log tail from the sidecar, CMD not run.
#           Control: the real dind image runs CMD and exits 0. Needs the P2 client: on an older client the service is refused before any pod exists.
#      (d) after pass, fail, cancel and eviction the job's pod and Secrets are gone; the scoped quota reads back 0 only after ALL jobs have ended.
#      (e) three Docker jobs whose requests exceed the scoped quota: the third queues (`queued: waiting for quota`) and then runs; an ordinary job
#          submitted after it starts at once with no `queued: behind` line; a fourth Docker job waits behind the third. The scoped quota's `used`
#          moves for the Docker jobs and not for the ordinary one.
#      (f) the pod spec of a running Docker job: only the sidecar is privileged; it has no hostPath and no docker.sock; the job container has /cache
#          and is not privileged.
#   Note (n7): while (e) runs, some ordinary kgate jobs on this cluster may wait for namespace quota. Run it when that is acceptable.
#
# It changes the cluster only through kgate jobs and reads it with kubectl (over the same ssh host kgate uses). It prints PASS or FAIL per check and
# exits 1 if any failed. Syntax check only before the cluster is ready: `sh -n docs/kgate-docker-live-proof.sh`.
#
# Inputs (environment):
#   KGATE_DOCKER_JOB_IMAGE    the kgate image variant `docker` (job container), pinned by digest (default: the one homelab#597 built, kgate image run 44986480504)
#   KGATE_DOCKER_DIND_IMAGE   the dind sidecar image, pinned by digest (default: docker:29.9.3-dind's digest)
#   KGATE_DOCKER_CLI_IMAGE    an image that cannot start dockerd, for (c2) (default: docker:29.9.3-cli's digest)
#   KGATE_PROOF_NODES         nodes for A, space separated (default: agent-1, agent-2, agent-4, the G14)
#   KGATE_PROOF_BIG_IMAGE     an image over 4 GiB uncompressed for (b) (default nvidia/cuda:12.4.1-devel-ubuntu22.04)
#   KGATE_SSH, KGATE_SSH_KEY  as for kgate itself
set -u

JOB_IMAGE=${KGATE_DOCKER_JOB_IMAGE:-ghcr.io/cartwmic/kgate@sha256:be170720691c03c7edca206d34220863142de522d32ae3c52306d94a117aa69b}
DIND_IMAGE=${KGATE_DOCKER_DIND_IMAGE:-docker@sha256:7bf70dcb85c822e3fa6f2d332143e474b99147b9d7b39102b0cfe8b04a7dd61b}
CLI_IMAGE=${KGATE_DOCKER_CLI_IMAGE:-docker@sha256:5a7af0dcb0e46c803efe9b45371dd21cb500e5b4453250394ac6f06d49b6e6f1}
NODES=${KGATE_PROOF_NODES:-"ubuntu-server-k8s-agent-1 ubuntu-server-k8s-agent-2 ubuntu-server-k8s-agent-4 cartwmic-g14-wsl"}
BIG_IMAGE=${KGATE_PROOF_BIG_IMAGE:-nvidia/cuda:12.4.1-devel-ubuntu22.04}
STATE=${XDG_STATE_HOME:-$HOME/.local/state}/kgate
KEY=${KGATE_SSH_KEY:-$HOME/.ssh/homelab}

work=$(mktemp -d /tmp/kgate-docker-proof.XXXXXX)
pids=""
fails=0
all_ids=""
cleanup() {
  for p in $pids; do kill "$p" 2>/dev/null; done
  rm -rf "$work"
}
trap cleanup EXIT INT TERM

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
kc() { # kubectl in namespace kgate, the way the client runs it
  ssh -o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=8 -i "$KEY" "$HOST" \
    "sudo kubectl --kubeconfig /etc/kubernetes/admin.conf -n kgate $(printf '%s ' "$@" | sed 's/[^ ]*/"&"/g')"
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
  ( cd "$repo" && kgate --profile kgate.toml "$@" > "$work/$name.out" 2>&1; echo $? > "$work/$name.rc" )
}
# start NAME REPO ... -> same, in the background; wait with wait_job NAME
start() { run "$@" & pids="$pids $!"; eval "pid_$1=$!"; }
wait_job() { eval "wait \$pid_$1" 2>/dev/null; cat "$work/$1.rc" 2>/dev/null || echo 255; }
rc_of() { cat "$work/$1.rc" 2>/dev/null || echo 255; }
jobid() { sed -n 's/^kgate: pod \([^ ]*\) on .*/\1/p' "$work/$1.out" 2>/dev/null | head -1; }
wait_id() { # wait up to $2 s for NAME's pod line
  n=0
  while [ "$n" -lt "${2:-120}" ]; do [ -n "$(jobid "$1")" ] && return 0; sleep 2; n=$((n + 2)); done
  return 1
}
rec() { # rec ID KEY -> the record's value as JSON ("null" when absent)
  grep -F "\"id\": \"$1\"" "$STATE/log.jsonl" 2>/dev/null | tail -1 | pyj 'import json,sys; r=json.loads(sys.stdin.read() or "{}"); print(json.dumps(r.get(sys.argv[1])))' "$2"
}
out_file() { cat "$STATE/$1.out/$2" 2>/dev/null; } # out_file ID NAME
node_free() { # free ephemeral bytes on a node, from the kubelet's stats summary
  kc get --raw "/api/v1/nodes/$1/proxy/stats/summary" 2>/dev/null | pyj 'import json,sys; print(json.load(sys.stdin)["node"]["fs"]["availableBytes"])' 2>/dev/null || echo unknown
}
gone() { # gone ID: the job's pod and Secrets no longer exist
  [ -z "$(kc get pods,secrets -l "kgate-job=$1" -o name 2>/dev/null)" ]
}
quota_used() { kc get resourcequota kgate-docker -o json | pyj 'import json,sys; print(json.dumps(json.load(sys.stdin)["status"].get("used", {})))'; }

# ---- the scripts the pods run ----------------------------------------------------------------------------------------------------------------
mkdir -p "$work/scripts"

# The campaign's calls. Stops at the first failing step; writes /out/result last.
cat > "$work/scripts/steps.sh" <<'SH'
set -eu
mkdir -p /out
echo "== 1 docker info"
docker info > /out/info.txt
cat /out/info.txt | sed -n '/Storage Driver/p;/Docker Root Dir/p;/Architecture/p'
grep -q 'Storage Driver: overlay2' /out/info.txt
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
docker cp p3:/etc/os-release /out/os-release
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

# (c): pull, run a container that outlives the kill, report the client's exit status in /out/rc and exit with it. $1 = seconds the container sleeps.
cat > "$work/scripts/hold.sh" <<'SH'
mkdir -p /out
docker pull busybox >/dev/null 2>&1
docker run --rm busybox sleep "${1:-120}"
rc=$?
echo "$rc" > /out/rc
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
  rc=$(wait_job "A$i")
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
echo "=== (c) kill dockerd in the sidecar while CMD's container runs"
repoc=$(docker_profile "" "" | mkrepo c)
start c "$repoc" -- sh ./hold.sh 120
if wait_id c 600; then
  idc=$(jobid c)
  n=0
  until [ -n "$(kc exec "$idc" -c dind -- docker ps -q 2>/dev/null)" ] || [ "$n" -ge 240 ]; do sleep 2; n=$((n + 2)); done
  # PID 1 ignores a signal from inside its own namespace unless it handles it: SIGTERM, not SIGKILL
  kc exec "$idc" -c dind -- kill -TERM 1 >/dev/null 2>&1 || bad "(c) could not signal dockerd in $idc"
fi
rcc=$(wait_job c)
idc=$(jobid c)
cmdrc=$(out_file "$idc" rc | tr -d '[:space:]')
if [ -n "$cmdrc" ] && [ "$rcc" = "$cmdrc" ] && [ "$rcc" != 0 ] && [ "$rcc" != 69 ]; then ok "(c) kgate's exit $rcc equals CMD's (/out/rc), non-zero and not 69"; else bad "(c) kgate exit $rcc, /out/rc '$cmdrc' (want equal, non-zero, not 69)"; fi
if grep -Eq 'kgate: the docker daemon (restarted|stopped) during the job' "$work/c.out"; then ok "(c) the note was printed"; else bad "(c) no 'the docker daemon restarted' note"; fi
if [ "$(rec "$idc" docker_sidecar | pyj 'import json,sys; v=json.loads(sys.stdin.read() or "null"); print(1 if v and v.get("restarts",0)>=1 else 0)')" = 1 ]; then ok "(c) docker_sidecar.restarts >= 1: $(rec "$idc" docker_sidecar)"; else bad "(c) docker_sidecar not recorded with restarts >= 1: $(rec "$idc" docker_sidecar)"; fi
all_ids="$all_ids $idc"

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
start f "$repoc" -- sh ./sleep.sh 300
if wait_id f 600; then
  idf=$(jobid f)
  sleep 20
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
  echo "    quota used while a Docker job runs: $used"
  if printf '%s' "$used" | pyj 'import json,sys; u=json.loads(sys.stdin.read()); assert any(k.startswith("requests.cpu") or k=="cpu" for k in u) and any(v not in ("0","0m") for k,v in u.items() if "cpu" in k)'; then ok "(d,e) the scoped quota counts the running Docker job"; else bad "(d,e) the scoped quota shows no use for a running Docker job: $used"; fi
  # an ordinary job running now must not move the scoped quota
  start N0 "$repoN" -- sh ./sleep.sh 20
  wait_id N0 300 || true
  used2=$(quota_used)
  if [ "$used" = "$used2" ]; then ok "(e) an ordinary job running beside it leaves the scoped quota's used unchanged"; else bad "(e) the scoped quota moved for an ordinary job: $used -> $used2"; fi
  wait_job N0 >/dev/null
  kgate cancel "$idf" >/dev/null 2>&1
  rcf=$(wait_job f)
  if [ "$rcf" = 143 ]; then ok "(d) cancel: exit 143"; else bad "(d) cancel: exit $rcf"; fi
  all_ids="$all_ids $idf $(jobid N0)"
else
  bad "(f) the job never made a pod"
fi

# ---- (e) the queue rule ------------------------------------------------------------------------------------------------------------------------
echo "=== (e) quota wait and the queue rule"
hard=$(kc get resourcequota kgate-docker -o json | pyj 'import json,sys; h=json.load(sys.stdin)["status"]["hard"]; print(h.get("requests.cpu") or h.get("cpu") or "")')
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
    start e1 "$repoE" --wait 1200 -- sh ./sleep.sh 60
    start e2 "$repoE" --wait 1200 -- sh ./sleep.sh 60
    wait_id e1 300; wait_id e2 300
    start e3 "$repoE" --wait 1200 -- sh ./ran.sh
    n=0; until grep -q 'queued: waiting for quota' "$work/e3.out" 2>/dev/null || [ "$n" -ge 120 ]; do sleep 2; n=$((n + 2)); done
    if grep -q 'queued: waiting for quota' "$work/e3.out"; then ok "(e) the third Docker job queued: $(grep -m1 'queued: waiting for quota' "$work/e3.out" | cut -c1-160)"; else bad "(e) the third Docker job did not queue for quota"; fi
    # an ordinary job submitted after it: starts at once, no 'behind' line, and it ends while e3 is still waiting
    start eN "$repoN" --wait 1200 -- sh ./sleep.sh 5
    rcN=$(wait_job eN)
    if [ "$rcN" = 0 ] && ! grep -q 'queued: behind' "$work/eN.out" && [ -z "$(jobid e3)" ]; then ok "(e) the ordinary job ran at once, with no 'queued: behind' line, while the third Docker job waited"; else bad "(e) ordinary job: exit $rcN, behind-line '$(grep 'queued: behind' "$work/eN.out" | head -1)', e3 pod '$(jobid e3)' (see $work/eN.out)"; fi
    # a fourth Docker job submitted after the third waits behind it
    start e4 "$repoE" --wait 1200 -- sh ./ran.sh
    n=0; until grep -q 'behind' "$work/e4.out" 2>/dev/null || [ "$n" -ge 60 ]; do sleep 2; n=$((n + 2)); done
    if grep -q 'queued: behind' "$work/e4.out"; then ok "(e) the fourth Docker job waits behind the third: $(grep -m1 'queued: behind' "$work/e4.out" | cut -c1-160)"; else bad "(e) the fourth Docker job did not queue behind the third"; fi
    for j in e1 e2 e3 e4; do
      rcj=$(wait_job $j)
      if [ "$rcj" = 0 ]; then ok "(e) $j ended 0 (a queued job runs, it does not fail)"; else bad "(e) $j exit $rcj"; fi
      all_ids="$all_ids $(jobid $j)"
    done
    all_ids="$all_ids $(jobid eN)"
  fi
fi

# ---- (d) after everything: cleanup and the quota at zero ------------------------------------------------------------------------------------------
echo "=== (d) every job's pod and Secrets are gone; the scoped quota is back to zero"
for id in $all_ids; do
  [ -n "$id" ] || continue
  if gone "$id"; then ok "(d) $id: pod and Secrets gone"; else bad "(d) $id: pod or Secrets left"; fi
done
used=$(quota_used)
if printf '%s' "$used" | pyj 'import json,re,sys; u=json.loads(sys.stdin.read()); assert all(re.fullmatch(r"0[A-Za-z]*", str(v)) for v in u.values()), u'; then ok "(d) the scoped quota's used is 0 after all jobs: $used"; else bad "(d) the scoped quota still shows use: $used"; fi

echo
if [ "$fails" = 0 ]; then echo "ALL CHECKS PASSED"; exit 0; else echo "$fails CHECK(S) FAILED"; exit 1; fi
