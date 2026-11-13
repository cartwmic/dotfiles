# kgate

`kgate` runs a heavy gate (a repo's slow test or lint command) on a Kubernetes cluster instead of on this Mac: the personal homelab cluster by default, or a second cluster reached through kubectl for a profile with `cluster = "<name>"` (see "A second cluster, reached through kubectl" below). One Python file, `dot_local/bin/executable_kgate`, installed as `~/.local/bin/kgate`. It takes heavy-gate's command line and meets `run-and-wake` and `heavy-gate` only on the command line:

The cluster host is not in this repo. `KGATE_SSH` (`user@address`) wins; otherwise `kgate` reads `~/.config/kgate/host`, which chezmoi renders from the local data key `sshHosts.kgate` (`address`, `user`) plus the optional list `sshHosts.kgateFallback` (same fields per entry; see [profiles.md](profiles.md), "Local data keys"). With neither set, `kgate` exits 69 and the message names the key.

Control-plane failover. `KGATE_SSH` and the host file each take one `user@address` (the old form, unchanged) or an ordered list, separated by commas or lines (`#` lines are skipped). With a list, `kgate` tries each host in order with a bare `ssh ... true` (ConnectTimeout 8 s) at job start, uses the first that answers, and prints `kgate: control plane user@address` in the job output. If none answers it exits 69. A single host is not probed first, so its behaviour is as before. Failover happens only at job start: a job whose host dies mid-run still fails (69, unknown), and a rerun picks the next host. This is the homelab path only; a kubectl cluster is unchanged.

```sh
run-and-wake -- kgate -- sh -c 'npm ci && npm run typecheck && npm test'
```

The pane that started the job is woken when it ends, with the exit code and the log path. The cluster side (image, `kgate` namespace, pull token) is in the homelab repo, `docs/kgate.md`.

## CLI

```
kgate [--profile FILE] [--wait SECONDS] [--cpu N] [--mem SIZE] [--mem-limit SIZE] [--image REF] [--node NODE] [--sched-wait SECONDS] -- CMD [ARGS...]
```

- `--profile FILE`: the gate's profile. Default `kgate.toml` at the worktree root. A repo with several gates keeps one profile per gate next to its script and passes `--profile`.
- `--wait`: how long to wait for the pod to start (default 3600).
- `--sched-wait`: how long the pod may stay unschedulable before kgate gives up with exit 75 (default 600; env `KGATE_SCHED_WAIT`, the flag wins). Homelab only. See "When the cluster is full".
- `--cpu`, `--mem`, `--mem-limit`, `--image`: override the profile. `--mem` sets the memory request, `--mem-limit` the limit (see "Memory: request and limit"). `--node`: pin one node (never an excluded one).
- CMD runs in the same directory, at the same absolute path, inside the pod.
- `kgate cancel [--wait SECONDS] JOB_ID` and `kgate cancel --list` stop one job and list the running ones; see "Cancelling a job".

## What it does

1. Ships the git worktree of the current directory to one pod: tracked and untracked non-ignored files, the `.git` file and the shared git folder (on a kubectl cluster no `.git`: see "A second cluster"), all at the same absolute path. Ignored files (`node_modules`, `target`) stay here. Git submodules are skipped (see below).
2. **Tree hash.** Before sending, it computes the git tree hash of the shipped files (what `git write-tree` gives for an index of exactly those files). The pod recomputes it after unpacking. If they differ, the job fails and CMD never runs.
3. **Version preflight.** The pod checks each tool in the profile. A mismatch fails the job and prints the tool, expected and found.
4. Runs CMD with the output streaming back live. CMD's exit code is kgate's.
5. **`/out`.** Whatever CMD writes to `/out` (also `$KGATE_OUT`) in the pod is copied to `<state>/<id>.out/` before the pod is deleted, whether CMD passed or failed.
6. Deletes the pod and its Secrets. At each start it also removes what a client that died left behind.

**A file outside the worktree is refused.** The pod gets only the worktree, so a CMD element that names an existing local file or directory outside it would not be found there and the job would fail after waiting for scheduling (2026-11-13: `kgate -- sh /tmp/.../unit.sh`, twice). Before anything is submitted, kgate checks each element after `--`. If it resolves, relative to the current directory, to a path that exists here, is outside the worktree root and lies under the home folder, `/tmp`, `$TMPDIR`, `/var/tmp` or `/run/user`, kgate prints `kgate: refused: PATH is outside the worktree ROOT; ...` and exits 64 with no log record and no cluster call. System paths (`/bin/sh`), pod-only paths (`/out`, `/cache`: they do not exist here), the folders themselves (`/tmp`) and options (`-x`) pass. The text inside `sh -c '...'` is one element and is not read. `--profile FILE` may be anywhere: kgate reads it here. A path that the pod would create (such as `--out /tmp/jout`) is refused when a file of that name happens to exist here; use `/out` or another name. The shared git folder of a linked worktree is shipped on the homelab but is not part of the worktree root, so a path inside it is refused too. A script the check misses (a path inside a `sh -c` string, or `--flag=/tmp/x`) still fails in the pod. To fix a refusal, put the file in the worktree or run the command inline.

**Submodules are skipped, not shipped.** A submodule is a gitlink (mode 160000) in the index, and it shows up in the file list as a directory, empty when it was never initialised. kgate leaves every gitlink out of the file list, so it is neither in the tar nor in the tree hash. The Mac and the pod hash the same list, so the check matches whether the submodule is initialised or not, and a real mismatch still fails it. kgate prints one line, `kgate: not shipping submodules: a, b`. On the homelab, where `.git` ships too, the gitlinks stay in the shipped HEAD and index, so kgate adds an empty directory at each skipped path to the tar: that is what a clone without `--recurse-submodules` leaves, and `git status` in the pod is clean. A submodule's own repository (`.git/modules/<name>`, also `worktrees/<name>/modules` of a linked worktree) is left out of the tar, since its files are not shipped and git does not need it for a clean status. A kubectl cluster has no `.git` in the pod, so it needs neither. A job that needs a submodule's files cannot run on kgate. Any other directory in the list, such as a nested repo that is not a submodule, is still refused with exit 69.

The pod's first process is `tini` (`tini -- sleep infinity`), so processes a gate orphans are reaped, not left as zombies. The pod's memory request is `memory` and its limit is `memory_limit`, which equals `memory` unless the profile sets it (see "Memory: request and limit"). `CARGO_BUILD_JOBS`, `RAYON_NUM_THREADS` and `MAKEFLAGS=-jN` are set to the CPU request. The image is pinned by digest. The scheduler is the queue. Pods run on amd64 nodes other than the control plane and the Mac mini (`NEVER_NODES` in the script: a required `NotIn`, and both also carry a taint kgate pods do not tolerate). agent-4, the GPU node, takes jobs only as overflow (`OVERFLOW_NODES`): the pod has a `preferredDuringScheduling` node affinity of weight 100 for every other node, so agent-4 is eligible but scores lowest and is used only when no other node has room for the pod's requests (Michael, ask 742, 2026-11-08). The G14 (`cartwmic-g14-wsl`) is preferred (`PREFER_NODES`, a second weight-100 term): it runs the same gate about twice as fast, so a job goes there first when it is up and has room, else to agents 1 to 3, and agent-4 last (Michael, ask 765, 2026-11-08). A pinned `--node` ignores the preference. The preference applies to every unpinned job, journeys included (Michael, ask 775, 2026-11-09: journeys may use the G14; the coordinator-session race that once kept them off it was fixed in coordinator #299. Their run time there varies with the load on the laptop: the median in the kgate log is about 770 s against 1280 to 1600 s on the agents, but one run on 2026-11-09 beside other jobs took 1239 s). A profile with `prefer_nodes = false` leaves the G14 term out; no profile sets it today. `--node` still refuses agent-4, the control plane and the Mac mini. The G14 laptop (`cartwmic-g14-wsl`) is schedulable again since 2026-11-06; `--node cartwmic-g14-wsl` pins a job there. Until homelab#101 (9f6ef66, 2026-11-05, systemd-timesyncd off) its WSL2 wall clock stepped back about 2.8 s every 30 s (a probe on 2026-11-05: 11 s of drift in two minutes; agent-1 had none), so tests that compare times flaked there (an agent-kit watchdog test, a heavy-gate 20-second check). It now follows the Windows clock, which slews up to 8% for about 15 s roughly every 9 h, and it can read up to about 2 s ahead of other nodes.

## Cancelling a job

```sh
kgate cancel --list                     # the jobs running now: id, run-and-wake job id, pid, node, age, cwd, command
kgate cancel [--wait SECONDS] JOB_ID    # stop that one job (default wait 120)
```

**Never `pkill`, `killall` or `kill $(pgrep ...)` to stop a kgate job.** A pattern kills every seat's job that matches it, on every node. `kgate cancel` is the only supported way, and a caller cancels **its own job id only**.

How it works:

- Each running client has an entry in `<state>/active/<kgate id>.json` (id, run-and-wake job id, pid, the process's start time and command, cwd, node once known). It is written when the job starts and removed when the job ends, including when kgate fails with an unexpected error.
- `JOB_ID` is kgate's id (`kgate-<epoch>-<pid>`, printed in the job log and the record) or the run-and-wake job id (`RUN_AND_WAKE_JOB`, `job` in the record). The match is exact. A prefix, a pattern, or an id that matches no job or more than one job is refused with exit 64, and nothing is signalled. There is no cancel-all.
- Before signalling, cancel checks that the pid is still the same process (same start time and command as the entry). Then it writes `<state>/active/<id>.cancel` and sends SIGTERM to that one pid: not a process group, not a parent, not a child, not the `run-and-wake` wrapper. The client's SIGTERM path runs as it always did: copy `/out` back, delete the pod and both Secrets, write the record, exit 143. Because the marker is there, the record's `reason` is `cancelled by kgate cancel` (and `"cancelled": true`), not `interrupted (SIGTERM)`.
- Cancel waits up to `--wait` seconds for that job's end line in `log.jsonl`, prints it, and exits 0. The job's own exit code (143) is in the line. If the job has not ended by then, cancel exits 69, prints the client's pid and says it did not force it. Cancel never escalates to SIGKILL by itself; the caller decides (`kill -9 <that pid>`).
- **Orphan.** If the client is already gone (killed -9, or the Mac rebooted) and left no end line, cancel deletes exactly that job's `pod/<id>`, `secret/<id>-env` and `secret/<id>-pull` (after checking that the pod, if it exists, carries the `app=kgate` label), writes an end line with exit 143, `reason` `cancelled by kgate cancel (client already gone)`, `cleanup` true or false and `"cancelled": true`, and removes the entry. If the cluster is unreachable it exits 69 and keeps the entry so you can run it again.
- A job that ended on its own but left its entry behind is reported from its end line and the entry is removed.

| Exit | Meaning |
|---|---|
| 0 | The job ended. Its end line is printed. |
| 64 | Bad command line, or the id matched no running job or more than one. Nothing was signalled. |
| 69 | The job was signalled and did not end in `--wait` seconds, or the orphan cleanup could not reach the cluster. |

## The CI `tests` check on kgate (the fallback)

When GitHub's runners fail twice the same infrastructure way, the same check runs on kgate at the same commit; if that run is green, the PR merges with `--admin` (ask #849=A). The check is `scripts/ci-linux.sh`, the command the CI `tests` job runs. The kgate image carries what it needs (chezmoi, zsh, rsync, sqlite3, jq, lsof; `images/kgate` in the homelab repo), and `kgate.toml` pins it. From the PR's worktree:

```sh
run-and-wake -- kgate --cpu 4 --mem 4Gi --mem-limit 6Gi --wait 1800 -- env CI_PAR_JOBS=4 scripts/ci-linux.sh
```

`CI_PAR_JOBS` is the width of `scripts/ci-par.py`'s suite pool. A homelab pod has a CPU request and no CPU limit, so the pool cannot read its size from the cgroup and would use the node's CPU count; set it to the `--cpu` value. `ci-par` prints `suite counts (ran, skipped)` at the end. Compare it with the same block in the GitHub `tests` log at the same commit: a pass that skips tests GitHub runs is not the same check. Only the exception below may differ. When you merge on kgate's green run, say so in the PR: the two failed GitHub runs, the kgate job id and log path, the head it ran, and the counts comparison; then merge with `--admin`.

**The one exception (CI-plan lead's decision under #849=A).** kgate runs the same `tests` check except `RestartJourneyTest` in `tests/agent-browser/test_login_unit.py`. It starts the real `agent-chrome.service` unit under the user systemd manager and restarts it ten times, and a pod has no user manager (and no `ss`). It skips there: one extra skipped test in `tests/agent-browser`.

**The guard.** The fallback does not apply to a PR that changes any of the code that test runs:

- `dot_config/systemd/user/agent-chrome.service`
- `dot_local/bin/executable_agent-chrome`
- `tests/agent-browser/test_login_unit.py`

For such a PR, wait for GitHub's run, or run that one test on the host desktop machine (`python3 -m unittest discover -s tests/agent-browser -p test_login_unit.py`, where a user systemd manager runs), and say which in the PR.

## No fallback; exit codes

| Exit | Meaning |
|---|---|
| CMD's code | CMD ran to its end. |
| 64 | Bad command line, or CMD names a file that is not in the worktree (see "A file outside the worktree"). Nothing was submitted. |
| 69 | The job could not start or finish on the cluster. The reason is printed and in the record. |
| 75 | The pod was still unschedulable when `--sched-wait` ran out. The pod is deleted, CMD never ran. |

69 covers: cluster unreachable, no or bad profile, image not pinned by digest, a secret or the pull token unreadable, a service the gate needs that the pod cannot provide, pod never started (wait ran out, image pull failed), tree hash differs, tool version differs, and a lost connection to a pod after CMD started (on a kubectl cluster, one the cluster did not evict, or a second eviction).

**kgate never runs CMD on this Mac, and never reruns a job that started, except once on a kubectl cluster when the cluster evicted its pod ("Eviction" below).** A cluster outage shows as failed gates. A CMD that itself exits 69 looks the same by code; the record's `reason` tells them apart (it is JSON `null` when CMD ran to its end, and a text reason otherwise).

## When the cluster is full

When no node has room for the pod's CPU or memory request, the pod stays `Pending`. kgate waits for room and then gives up: exit 75 after `--sched-wait` (default 600 s), or exit 69 if `--wait` runs out first. It never runs the job on the Mac.

- A full cluster leaves the pod `Pending`, with `PodScheduled` `False` and reason `Unschedulable`. The client waits by itself. It prints `kgate: waiting for the pod: Unschedulable` to the job log when that state first appears.
- **Scheduling deadline (homelab).** `--sched-wait SECONDS` (default 600; env `KGATE_SCHED_WAIT`; the flag wins; whole seconds, at least 1) counts from the moment the pod is created. If the pod is still `PodScheduled=False` with reason `Unschedulable` when it passes, kgate deletes the pod, prints one line and exits **75**: `kgate: pod not scheduled within <N>s: <scheduler message> (pinned to node <NODE>); exit 75, CMD was not run on this Mac` (the pin part only when `--node` was given). The record's `reason` is `pod not scheduled within <N>s: <scheduler message>[ (pinned to node <NODE>)]`. There is no retry. 75 is `EX_TEMPFAIL`; kgate uses it for nothing else, though a CMD that itself exits 75 looks the same by code (as with 69, `reason` tells them apart). A pod that is already scheduled and is pulling its image or running an init container is not unschedulable: the deadline does not apply to it, and only `--wait` ends it. A kubectl cluster is not covered (its autoscaler can take longer to add a node); there only `--wait` applies.
- Otherwise it keeps waiting until `--wait` seconds (default 3600) after the job started.
- If the wait runs out, it exits 69. The record's `reason` is `pod did not start within <N>s: Unschedulable <scheduler message>`. kgate copies the scheduler message unchanged, up to 300 characters. Kubernetes scheduler messages look like `0/N nodes are available: ... Insufficient memory`.

The reason tells a full cluster apart from the other ways a job fails to start. These are the prefixes kgate writes:

| `reason` starts with | Cause | Capacity? |
|---|---|---|
| `pod not scheduled within <N>s:` (exit 75) | No node had room for the `--sched-wait` deadline. | Yes |
| `pod did not start within <N>s: Unschedulable` | No node had room for the whole `--wait` (a kubectl cluster, or `--sched-wait` set above `--wait`). | Yes |
| `pod did not start: ` (for example `ErrImagePull`, `ImagePullBackOff`, `CreateContainerConfigError`, or a pod phase of `Failed`) | The pod failed before CMD ran. | No |
| `cluster unreachable (` | The cluster or its ssh route is down. | No |
| `could not create the pod: ` | The cluster refused to create the pod. | No |

Every other exit-69 reason (a bad profile, a tree hash or tool version mismatch, an unreadable secret) is not a capacity problem either.

**What callers do.**

- Wait. Pass `--wait 1200` for short gates.
- On exit 75, or exit 69 whose `reason` starts `pod did not start within` and contains `Unschedulable`, the caller may run heavy-gate once, but only when the profile fits some kgate node (see the node table in "How many jobs at once"). Every committed profile does. Then it must report "(2) no kgate capacity" and quote the reason.
- A profile bigger than every node is a profile bug. Report it as one, with the reason quoted. Never run heavy-gate for it as (2).
- Every other exit 69 is not a capacity problem. Report it as it is. Never report it as a Mac run in disguise.
- The client never falls back to the Mac. A fallback inside the client would make a result's origin ambiguous.

**The limit.** `Unschedulable` means no node can take the pod now. It does not say that no node ever could. A profile bigger than every node gets the same prefix, with `Insufficient memory` or `Insufficient cpu` in the scheduler message, and so does a `--node` that matches no node. The reason alone cannot separate those cases from a full cluster, so the caller's fit check does.

## How many jobs at once

Measured on 2026-11-06 from one day's node requests (`kubectl describe node`) and Prometheus. Re-measure when the coordinator's journey tests move to kgate. The scheduler places pods by their requests, not by real use: real CPU use was 5 to 12%.

| Node | CPU | Memory (allocatable) |
|---|---|---|
| agent-1 | 16 | 15.5 GiB |
| agent-2 | 8 | 7.7 GiB |
| agent-3 | 8 | 7.7 GiB |
| `cartwmic-g14-wsl` (G14) | 16 | 23.4 GiB |

At that time about 41 CPU and 40 GiB were unrequested across the four nodes.

Planning count:

- **About 8 jobs of mixed sizes.** At most 2 of them big: a Loop Engine job (12 cpu, 8Gi) fits only agent-1 or the G14. A steward job (4 cpu, 7Gi) is big too: at the measured requests it fits only agent-1 or the G14. The rest are small or medium gates of 1 to 4 GiB, about 6 of them.
- **Up to about 12 when every job is small.**
- **Past that, pods queue.** That is fine; the scheduler is the queue.

Profile sizes after the 2026-11-08 right-sizing: `memory` is the request the scheduler reserves, `memory_limit` the OOM limit. Each request is about 1.2 times the highest cache-free (working-set) peak in kgate's log and Prometheus, rounded up to 0.5 GiB. The limit stays above the highest peak that includes page cache. CPU is the p95 of the per-job average cores, never above the old value, and where a job is CPU-bound it is left alone (loop-engine, agent-kit, the unit gate: they use more cores than they book because there is no CPU limit).

| Gate | Repo | cpu | memory (request) | memory_limit (limit) | Highest working set (n runs) |
|---|---|---|---|---|---|
| Loop Engine baseline | `loop-engine` | 12 | `5632Mi` (5.5 Gi) | `8Gi` | 4.56 GiB (14) |
| coordinator journeys gate | `coordinator` | 3 | `3584Mi` (3.5 Gi) | `4Gi` | 2.50 GiB (96) |
| coordinator unit gate | `coordinator` | 4 | `3Gi` | `3Gi` | 1.76 GiB (230) |
| agent-kit unit gate | `agent-kit` | 2 | `2560Mi` (2.5 Gi) | `3584Mi` (3.5 Gi) | 1.79 GiB (63) |
| budget-steward unit gate | `budget-steward` (gitea) | 4 | `5632Mi` (5.5 Gi) | `7Gi` | 4.24 GiB (11) |
| homelab static checks | `cartwmic-homelab-v2` | 1 | `512Mi` | `1Gi` | 0.25 GiB (28) |
| dotfiles heavy suites | `dotfiles` | 1 | `512Mi` | `1Gi` | 0.27 GiB (66) |

What changed on 2026-11-08 and why: journeys 6Gi to 3.5Gi, limit 6Gi to 4Gi, cpu 4 to 3 (it averages 2.0 cores, at most 3.3); loop-engine request up from 3.5Gi to 5.5Gi, because its working set is 3.6 to 4.5 GiB and the old request sat below it, which makes the pod the first to be evicted (its "8.00 GiB peak" in the record is page cache filling the limit, not use); agent-kit and steward 0.5 GiB down; homelab and dotfiles cpu 2 to 1 (0.6 and 0.1 cores used). The coordinator unit gate stays at 3Gi: its peak including cache is 2.52 GiB, which would not fit 2.5Gi.

One measured run per profile after the change, no OOM, no exit 137 (2026-11-08; peak is the cgroup peak including page cache):

| Gate | Job | Node | Exit | Time | Peak | Working set |
|---|---|---|---|---|---|---|
| journeys | `kgate-1794109545-95978` | agent-1 | 0 | 984 s | 1.64 GiB (sampled) | 1.29 GiB |
| loop-engine | `kgate-1794109540-95546` | G14 | 0 | 222 s | 8.00 GiB (cache at the limit) | 4.56 GiB |
| agent-kit | `kgate-1794110539-64647` | G14 | 0 | 74 s | 2.14 GiB | 1.49 GiB |
| coordinator unit | `kgate-1794110612-67987` | G14 | 0 | 213 s | 2.13 GiB | 1.34 GiB |
| budget-steward | `kgate-1794109421-86375` | G14 | 0 | 86 s | 5.07 GiB | n/a |
| homelab | `kgate-1794109465-91020` | G14 | 0 | 36 s | 0.40 GiB | n/a |
| dotfiles | `kgate-1794109465-91022` | G14 | 0 | 544 s | 0.34 GiB | n/a |

Two gates failed when four jobs ran on agent-1 at once (2026-11-08): agent-kit on 5 tests that hit their 5 s limit (peak 1.79 GiB), and the coordinator unit gate on one test, the evals `other-modules` chunk, at its old 60 s limit (peak 1.96 GiB). Both passed alone. The unit failure is not a node problem: that chunk takes about 53 s alone on agent-1 and on agent-4, and the tree those runs used lacked coordinator 756c8955 (2026-11-07), which gives the chunk tests a 180 s limit. The scheduler counts requests, but agent-kit and the unit gate burst to 8 to 16 cores, so several of them on one 8-core node can still starve each other and run slower. That is a CPU effect, not a memory one.

Packing by request, read again on 2026-11-08 (the other pods' load as it was; the pod request trims and the ZFS cap were not applied): the realistic mix of 11 jobs (1 loop-engine, 1 steward, 2 journeys, 3 unit, 2 agent-kit, 1 homelab, 1 dotfiles) fits 4 jobs on the three agents with the old profiles and 5 with the new ones. Journeys alone: 2, then 4. Homelab or dotfiles alone: 12, then 25. With agent-4 as overflow the new profiles fit 9 of 11 (7 if 8 GiB of agent-4 is kept free for GPU pods; nothing enforces that reserve). With the G14 awake: 9 before, 10 after, 11 with agent-4 as well. Jobs do wait: in Prometheus 46 kgate pods sat Unschedulable, 6.2 hours in all, the longest 56 minutes. Nothing gave up waiting.

## agent-4 as overflow (measured 2026-11-08)

Agent-4 has 31.2 GiB allocatable, about 14 GiB and 10 CPU unrequested, and runs frigate (about 1.3 to 1.6 cores all day), jellyfin, immich, hindsight and ollama. Overflow was forced with a placeholder pod on the G14 (requests only, ended itself after 25 minutes) and gates that asked for 13 GiB, so agent-4 was the only node that fit them. Frigate's own stats were read every 5 s (`/api/stats` through `kubectl exec`) with nothing else running against it.

- agent-kit gate x3 in a row (clean run), plus agent-kit and the coordinator unit gate in two earlier runs, all on agent-4. Node CPU reached 94% for 15 s windows and averaged 50% during the gates; CPU pressure peaked at 28%; frigate's container CPU was 1.5 cores against 1.6 before, with no throttling.
- Frigate detection: inference 51.1 ms against 50.9 ms before; camera 15.2 fps; skipped frames at most 1.4 fps (9%), the same size as blips before any job started (0.9 to 1.4 fps). One earlier run showed a 3.2 fps dip while two probes were hitting its stats API at once. Ten idle minutes showed no dip.
- Recordings: continuous in both checked windows (154 and 85 segments per camera, longest gap 1.2 s, none over 5 s). No warnings in frigate's log.
- Gates on agent-4: 2 of 3 agent-kit runs passed (115 s each); the failing one was the kt34 watchdog test, which also fails 7 of 15 agent-kit runs on agent-1 and 4 of 21 on the G14. Raw CPU, process spawn, file I/O, fsync, DNS, HTTPS and local TCP timings are the same on agent-4 and agent-1. The first run on a node also pays an image pull and a cold npm cache.
- The first real jobs after the change (5 from other work) all ran on the G14, agent-1 and agent-2, none on agent-4.

Before you change a profile's size, check it against the node table above.

Jobs that only wait for model API calls (evals) are not heavy. They should not use heavy-gate or kgate slots; they run as plain background jobs.

## Record

One JSON line per job in `${XDG_STATE_HOME:-~/.local/state}/kgate/log.jsonl`; the full output is `<id>.log` beside it. The older lines from before this version (with a `fallback` field) have a different shape.

| Field | Meaning |
|---|---|
| `id` | kgate's job id, also the pod's name |
| `cluster` | `homelab`, or the name of the cluster file |
| `cache` | kubectl clusters only: `pvc`, `fallback` or `none` (see "The cache claim") |
| `services`, `pod_start_s`, `service_ready_s`, `service_peak_bytes` | kubectl clusters with a sidecar only: the services, seconds until the pod ran, seconds until the sidecar's startup probe passed, and the sidecar's peak memory |
| `cpu_limit`, `quota_wait_s` | kubectl clusters only: the effective CPU limit (`cpu` when the profile sets none), and the seconds spent waiting for namespace quota (0 when none) |
| `job` | the run-and-wake job id (`RUN_AND_WAKE_JOB`), or null |
| `start`, `end`, `duration_s` | UTC times and seconds |
| `repo`, `cwd`, `head` | repo name, working directory, Mac HEAD |
| `tree` | the tree hash of what was shipped |
| `node`, `image`, `profile`, `cpu`, `mem`, `mem_limit` | where and how it ran; `mem` is the memory request and `mem_limit` the limit |
| `peak_bytes`, `peak_source` | the container's peak memory: `cgroup` (`memory.peak`, kernel 5.19 and later) or `sampled` (highest `memory.current` seen every 0.5 s, on older kernels). It includes page cache. |
| `ran` | CMD started |
| `exit`, `reason` | exit code; the reason when it is 69 |
| `out_files`, `cleanup`, `output`, `cmd` | files copied back; pod and Secrets confirmed deleted; log file; the command |
| `cancelled` | only on a job stopped by `kgate cancel`: `true` |

## A second cluster, reached through kubectl

A profile with `cluster = "<name>"` runs the same contract (ship the worktree, verify the tree hash, stream output, copy `/out` back, delete the pod, one record, `kgate cancel`) on a second Kubernetes cluster that this machine reaches through local `kubectl`. Only the cluster adapter and the pod side differ. The homelab path is untouched and stays the default: a profile with no `cluster` key, or `cluster = "homelab"`, is a homelab job.

Everything about the second cluster is in a file on the machine, not in this repo: `~/.config/kgate/clusters/<name>.toml`. A machine without that file cannot reach the cluster. The profiles for it live next to the repo they gate, or in `~/.config/kgate/profiles/` (`--profile FILE`).

```toml
# ~/.config/kgate/clusters/example.toml   (invented values)
kind = "kubectl"                      # the only kind besides the built-in homelab one
kubeconfig = "~/.kube/kgate-example"  # a kubeconfig that holds only the one context below
context = "example-ctx"
namespace = "jobs"
registries = ["registry.example"]     # image hosts (or host/path prefixes, see below) a profile may use here (still pinned by digest)
tree_roots = ["Users", "Volumes", "private"]   # top-level directories the shipped tree may live under
user = "65532:65532"                  # uid:gid the pod runs as (never root); a profile's own `user` overrides it
deadline_s = 7200                     # activeDeadlineSeconds
cache_claim_default = "my-cache"      # optional: a persistent cache claim used unless the profile names its own cache_pvc

[pod_labels]                          # optional: what the cluster's admission policy requires on every pod
"example.org/owner" = "team-a"
[pod_annotations]                     # optional
"example.org/evict-ok" = "true"
```

A missing or invalid file is exit 69, and the reason names the file and the key (`cluster file <path> is missing the key 'namespace'`). Unknown keys are refused.

**Setup, once.** `kgate cluster-setup <name> --from-context <ctx> [--namespace NS] [--from-kubeconfig FILE] [--kubeconfig-out FILE]` writes a kubeconfig that holds only that context (mode 600). It writes to the `kubeconfig` the cluster file names when that file exists (`--kubeconfig-out` must then match it, and so must `--from-context` and `--namespace` match the file's `context` and `namespace`, or the command refuses and leaves the working kubeconfig alone); otherwise to `--kubeconfig-out`, default `~/.kube/kgate-<name>`. It marks the file as kgate's, never replaces a file it did not write (or one with more than one context), and never writes `~/.kube/config` or the file it reads from. It switches an exec login of `kubelogin` to `--login azurecli` (only when the source context uses it, so the token comes from the cli login and there is no browser sign-in per job). If no cluster file exists yet it also writes a skeleton (mode 600, values escaped) with `registries = []`, which kgate refuses until you fill it in; it never overwrites an existing cluster file.

**Where the files come from on a machine.** `run_onchange_after_45_kgate_cluster_files.sh.tmpl` writes the cluster and profile files from the machine's own chezmoi data, on any profile that has it: `kgate.clusters.<name>` and `kgate.profiles.<name>` hold the TOML text, and the file names are the keys. With no `kgate` data nothing is written. **Removing a key from the data does not remove the file the step already wrote**; delete `~/.config/kgate/clusters/<name>.toml` or `~/.config/kgate/profiles/<name>.toml` by hand (a cluster file that is gone makes kgate refuse that cluster with exit 69; a stale one keeps working). See `example.chezmoi.yaml` and [profiles.md](./profiles.md).

**Constants.** `kubectl --kubeconfig <kubeconfig> --context <context> -n <namespace>`, always all three, from the cluster file. kgate never reads the current context. The reachability check is `kubectl auth can-i create pods` answering `yes`; anything else is exit 69 with a hint to sign in and kubectl's message. A missing kubeconfig is exit 69 naming `kgate cluster-setup`.

**What kgate does there.** It needs only pods (get, list, watch, create, delete), `pods/exec`, `pods/log` and events. kgate creates a bare pod, execs into it and deletes it. No Secrets, ConfigMaps or Jobs. The sweep at each start deletes finished `app=kgate` pods only.

**Pod spec.**

- Labels `app=kgate`, `kgate-job=<id>`, plus the cluster file's `pod_labels` (which may not set kgate's own `app` or `kgate-job`), and its `pod_annotations`.
- Non-root: `runAsNonRoot`, `runAsUser` and `runAsGroup` from the profile's `user`, else the cluster file's (`0:0` is refused). seccomp `RuntimeDefault`, `allowPrivilegeEscalation: false`, drop `ALL`, no service account token. The exec-as-root-then-drop path is not used.
- Requests and limits for cpu, memory and ephemeral-storage, from the profile: `cpu` (request), `cpu_limit` (limit, what the pod may burst to; default `cpu`; must be at least `cpu`), `memory` (request), `memory_limit` (limit), `ephemeral_storage` (request and limit; default `10Gi`). `GOMAXPROCS`, `CARGO_BUILD_JOBS`, `RAYON_NUM_THREADS` and `MAKEFLAGS` follow the CPU limit, not the request.
- `activeDeadlineSeconds` from the cluster file. The container runs `sleep 86400` (no `tini` needed), so the deadline ends a pod whose client died.
- emptyDirs at the top directory of the shipped tree (`/Users` for `/Users/me/git/repo`, so the Mac's absolute paths unpack as the non-root user), at `/cache` and at `/out`. Only trees under the cluster file's `tree_roots` are accepted (an allow-list, so no emptyDir hides anything in the image); any other top directory is refused.
- `cache_pvc = "<claim>"` in the profile (or `cache_claim_default` in the cluster file) makes `/cache` that persistent claim instead of an emptyDir (see "The cache claim"). The pod then also gets `fsGroup` (the gid) with `fsGroupChangePolicy: OnRootMismatch`, so the non-root user can write a new disk.
- Env: kgate's usual set, plus `HOME=/cache/<job id>/home` (per job, removed with the job's directory at the end, so nothing a job writes to HOME, such as `~/.gitconfig` or `~/.npmrc`, reaches a later job on a shared disk), `GOCACHE=/cache/go-build`, `GOMODCACHE=/cache/gomod`, `npm_config_cache=/cache/npm` and `npm_config_store_dir=/cache/pnpm-store`. Only those caches live on the claim.
- No hostPath, affinity, tolerations, Secrets or imagePullSecrets (nodes pull with their own identity). `--node` is refused.

**Sidecar and mounts (all optional, kubectl clusters only).**

A `registries` entry is a host (`registry.example`) or a host plus a path prefix (`registry.example/team/db`). An image matches an entry when it starts with `entry + "/"`, or when its repository (the part before `@sha256:`) equals the entry. The same rule applies to job images, the sidecar image and image volumes. A host entry admits every repository on that host; a path-scoped entry admits that repository and anything under it, and refuses a sibling repository on the same host. Use a path-scoped entry to admit only the sidecar image.

- `services = ["mssql"]` with an `[mssql]` table adds a SQL Server container to the pod. It is a native sidecar (an init container with `restartPolicy: Always`) with a startup probe, so the job container starts only once the database accepts a login. The sidecar runs as uid 10001 (the image's `mssql` user) with group 0, because the image's data directory is group-owned by root, and with `drop: [ALL]` plus `add: [NET_BIND_SERVICE]` only on this container, because `sqlservr` carries that file capability and cannot be started without it. These are fixed, not profile settings. kgate generates a throwaway SA password for each job (`Aa1_` and 32 hex characters), puts it in the pod spec of both containers (`MSSQL_SA_PASSWORD`, `SA_PASSWORD`) and tells CMD where the database is (`MSSQL_HOST=localhost`, `MSSQL_PORT=1433`). The password is never written to the log, the record, the console or an error message: anything that would print it prints `***`. `[mssql]` keys: `image` (required, by digest, host in the cluster file's `registries`), `cpu` (2), `cpu_limit`, `memory` (4Gi), `memory_limit`, `ephemeral_storage` (4Gi), `ready_s` (300, how long the startup probe may take). The sidecar's requests count toward the namespace quota. If it crashes or restarts, kgate exits 69 with the last 15 lines of its log (password masked) and CMD does not run.
- `[[image_volumes]]` with `image` and `path` mounts an image read-only at `path` (a Kubernetes image volume). The image is pinned by digest and must match `registries`, the same rule as the job image. `path` must be absolute and normalized (`posixpath.normpath(path) == path`: no `.`, `..`, `//` or trailing `/`; `/./usr`, `/a/../usr` and `/usr/` are refused). It may not be `/`, `/cache`, `/out`, a tree root, or `/usr`, `/etc`, `/bin`, `/sbin`, `/lib*`, `/proc`, `/sys` or `/dev` (or anything under them).
- `local_hostnames = ["db"]` makes those names resolve to `127.0.0.1` in the pod (`hostAliases`), for a repo whose own configuration names the database by host. Plain host names only; an address is refused.
- **Running a tool from an image volume.** A volume brings only the image's files, not its environment, and absolute symlinks and paths inside it point at the job container's own root. So: call the tool by its path under the mount (`/mnt/tool/usr/share/.../tool`), link only the few binaries the job needs into `$HOME/bin` and put that first on `PATH`, and never put a mounted image's `/usr/bin` on `PATH` (its coreutils need that image's libraries and fail with `error while loading shared libraries`). For a Java tool in a FIPS image, set `FLYWAY_JAVA_CMD`-style launcher variables to the mounted JVM and give the JVM the provider jars explicitly (`JAVA_ARGS="-p /mnt/tool/usr/share/java/bouncycastle-fips"`); without that module path the JVM has no BouncyCastle FIPS provider and fails with `SHA-1 not available`. FIPS stays on. The working command for a profile belongs in that profile's comments.
- **SQL Server client notes.** `sqlcmd` from the Go-based go-sqlcmd rejects the SQL Server 2019 image's self-signed certificate (a negative serial number) even with `-C`; set `GODEBUG=x509negativeserial=1` for it. That certificate is a throwaway one on localhost inside the pod, so this is safe here. Encryption stays on and the server is unchanged. The sidecar's own startup probe uses the image's ODBC `sqlcmd`, which does not need it.
- With a sidecar the pod has two containers, so kgate sends its `exec` calls to the container named `job`. The record gains `services`, `pod_start_s`, `service_ready_s` (seconds from pod creation to the sidecar's first pass) and `service_peak_bytes` (the sidecar's own peak memory). The log says `SQL Server ready after Ns` and `peak mssql N cgroup`.

**Refused with exit 69, before anything is created:** a profile with `[secrets]` or a service other than `mssql`, an image whose host is not in the cluster file's `registries` (or that is not pinned by digest), a root user, an invalid cluster file. The record names the profile's cluster even for these refusals, and no homelab connection is made.

**The cache claim.** With a claim, `GOCACHE`, `GOMODCACHE` and the package-manager caches are warm after the first job. The claim is created by whoever runs the cluster, not by kgate, and mounting a claim in the pod's own namespace needs no PVC rights. A claim with access mode ReadWriteOncePod lets one pod use it:

- **One job holds the cache; a second runs cold.** A second job's pod stays `Pending` (`Unschedulable`, "node has pod using PersistentVolumeClaim with the same name and ReadWriteOncePod access mode"). If it is still Pending on that reason after about 10 s (`CACHE_BUSY_S`), kgate deletes the pod, creates the same pod again with an emptyDir `/cache` (no claim, no `fsGroup`), prints `kgate: cache in use by another job; running without it`, and the job runs cold. The record's `cache` field says which: `pvc`, `fallback`, or `none` (no claim; kubectl-cluster records only). Any other Pending reason (quota, capacity) keeps the existing waits, with the cache.
- **Zone.** A disk lives in one availability zone, so a pod that mounts the claim is scheduled in that zone; a pod that falls back to the emptyDir can go anywhere.
- **A dead client's pod.** If a client dies, its pod keeps running until the deadline and can hold the disk that long; other jobs then run cold. `kgate cancel` deletes it sooner.
- **Cleanup.** The pod side removes `/cache/<job id>` (the job's own script, file list, error file and HOME) at the end of every job, pass or fail, and at its start removes any other `/cache/kgate-*` directory older than a day (a dead client's leftover). The caches stay.
- **Missing claim.** The pod would stay `Pending` with `persistentvolumeclaim "<name>" not found`. kgate sees that at once and exits 69 with `the cache claim <name> does not exist in <namespace> (cache_pvc in the profile)`; the pod is deleted.

**Quota.** A shared namespace can have a ResourceQuota. A create call that the quota refuses is not fatal: kgate prints `kgate: waiting for quota: <the quota message>` (and a new line when the message changes), retries the create with backoff (5 s, doubling to 60 s) until the job's `--wait` deadline, and records the time spent as `quota_wait_s` (0 when it did not wait; kubectl-cluster records only). At the deadline it exits 69 with `quota not available within <N>s: <message>`. Only the API server's ResourceQuota refusal is waited for: `Error from server (Forbidden): ... pods "x" is forbidden: exceeded quota: <name>, requested: ..., used: ..., limited: ...`. Any other text that merely says `exceeded quota` (an admission-webhook denial, say) is an immediate 69. The whole message is parsed; only what is printed and recorded is cut to 300 characters. If a requested amount in that message is above the quota's own limit for it (`requested` greater than `limited`), waiting can never succeed, and kgate exits 69 at once with `request exceeds the namespace quota: <message>`. Any other create error is also an immediate 69. `kgate cancel` works while a job waits for quota. Requests small and limits large (`cpu` small, `cpu_limit` large) let more jobs fit a quota; size a profile from its measured working set (cgroup anon, not the cgroup peak, which includes page cache).

**Eviction.** The cluster's autoscaler can take a pod away (it consolidates an underused node), and so can the taint manager or the scheduler. kgate's pods carry the eviction-ok annotation the cluster's policy requires and nothing that resists eviction. When kgate loses the pod before CMD finishes, it checks whether the cluster evicted it: the pod's status (`reason: Evicted`, or a `DisruptionTarget` condition) if the pod still exists, and the namespace events for that pod name (`Evicted`, `TaintManagerEviction` with a "Marking for deletion" message only, `Preempted`, `Disrupted`; nothing else, so the node autoscaler's `DisruptionBlocked`, `FailedScheduling` and `Nominated` give no rerun). Only a confirmed eviction is rerun, once: kgate deletes what is left of the pod, prints `kgate: pod <id> was evicted by the cluster (<reason>); rerunning once`, and starts the same tree, profile and CMD in a new pod `<id>-r2` of the same job (the quota wait and the cache fallback work as before; the job's `/out` is the second pod's). The record gains `attempts` and `evicted` (a list of `attempt`, `pod`, `reason`). A second eviction is exit 69 naming both reasons. The clocks are not reset: kgate reruns only while the job's `--wait` has not passed, and the new pod's `activeDeadlineSeconds` is what is left of the cluster file's `deadline_s` since the first pod was created (no time left: exit 69, not rerun). The pod's own status comes first: a pod that still exists, is Running or Pending, is not being deleted and has no true `DisruptionTarget` was not evicted, and its events are not read. The taint manager also emits `TaintManagerEviction` for "Cancelling deletion of Pod ..." (the taint cleared and the pod was not deleted), so that message is no eviction. Any other lost pod keeps exit 69 and its text, `the result is unknown and the job is not rerun`, because CMD may have had effects; so does an eviction before the pod is running. The deadline covers the whole job on purpose, so a job whose `--wait` has passed when its pod is evicted gets no rerun. The record's `cache` is the cache mode of the pod that ended the job. The homelab is unchanged.

**Pod side, no Python.** The image need not have `python3`, so the pod runs `sh /cache/<id>/kgate.sh` (the `POD_SH` constant in the script) instead of `kgate.py --pod`. It prints the same `kgate[<id>]: start|hash|preflight|running|peak|end` markers, so the Mac side reads them unchanged.

- Repo and hash: no `.git` is shipped. The script makes a fresh repo at the tree root, adds exactly the shipped file list (`files.nul`) to its index hashed as bytes (`core.autocrlf=false`, `safe.directory=*`, and an `info/attributes` that turns text, eol, filter, ident and working-tree-encoding conversion off), and compares `git write-tree` with the Mac's hash. Only on a match it makes one commit (author and committer `kgate`, date 2000-01-01, so the same tree gives the same commit) on `main`. Tools then find a working `HEAD` (`git rev-parse`, VCS stamping in builds). The Mac's real HEAD is in `KGATE_HEAD` in CMD's env and in the record's `head`. If git cannot commit, the pod prints `commit FAILED git commit failed: ...` and exits 69, and kgate fails the job with that reason, CMD not run.
- If the image lacks `git` or `tar`, the pod side stops first with `image FAILED image lacks <tool>; kgate's pod side needs git, tar and sh`; kgate exits 69 with `image lacks <tool>; ... (CMD not run)`, not a hash mismatch.
- If the image lacks `git` or `tar`, the exec checks for them first and prints `image FAILED image lacks <tool>; kgate's pod side needs git, tar and sh` (exit 69); if the container cannot start `sh` at all, kgate reads the runtime's message and gives the same reason for `sh`. kgate exits 69 with `image lacks <tool>; ... (CMD not run)`, never a hash mismatch or a lost-pod error.
- Tools: as the Python side. The expected version must appear in the command's output as a whole version. A tool whose version flag differs needs `cmd` (for example `go version`, since `go --version` is not a flag).
- CMD runs in the same directory. Peak memory is read from `memory.peak` (`unknown` when the kernel has none). The end line carries CMD's exit code.
- Exit codes inside the pod: CMD's, 70 for a hash mismatch, 71 for a tool mismatch, 69 for a missing tool or a failed commit. The Mac side checks that kubectl's exit code equals the reported one.
- Only POSIX features are used, so a busybox userland works.

**What differs from the homelab.**

| | homelab | second cluster |
|---|---|---|
| Reach | `ssh` + `kubectl` on a control plane | local `kubectl` + the cluster file's kubeconfig, context and namespace |
| Secrets, pull credential | `[secrets]` as a pod Secret; ghcr pull Secret | none; `[secrets]` refused |
| Pod user | root to unpack, then `user` | non-root `user` throughout |
| Pod side | `kgate.py --pod` (python3) | `kgate.sh` (POSIX sh, git) |
| Tree location | the pod's filesystem | emptyDir at the tree's top directory |
| Git history | `.git` and the shared git folder shipped | none shipped; one synthetic commit built in the pod |
| Caches | hostPath | emptyDir `/cache` (cold each job), or a claim (warm; one job holds it, a second runs cold) |
| Deadline | 8 h | the cluster file's `deadline_s` |
| Scheduling | node affinity | the cluster's |
| Cleanup | pod and two Secrets | pod only |
| Image needs | `tini`, `python3` 3.11+ | `sh`, `tar`, `git` |

On a kubectl cluster the history is a single synthetic commit, and the Mac's uncommitted and untracked shipped files are in it, so `git status` and `git diff` in the pod show a clean tree (use the Mac's `git status` to see what changed). `git log`, `git describe`, `git blame` and tags show nothing of the real history. A command that needs history must run locally or on the homelab (which still ships `.git`). Exit codes are the same (CMD's code, 64, 69). When the cluster is unreachable or the sign-in has lapsed, the job exits 69 with the sign-in hint; kgate never falls back to the Mac.

**Costs on the Mac.** kgate ships every tracked file on every job and builds that tar in memory, so a very large repo costs the client memory (about the size of the tar) and a minute or more to the pod-side start. A warm pod with diff sync, or shipping only what a package needs, is the next improvement.

## Gate profile

A TOML file in the gate's repo (a profile for a second cluster can live in `~/.config/kgate/profiles/`, see above). Keep it small.

```toml
image  = "ghcr.io/cartwmic/kgate@sha256:..."   # required, pinned by digest
cpu    = 2                                      # whole CPUs; default 2
memory = "4Gi"                                  # the request, what the scheduler reserves; default 4Gi
memory_limit = "8Gi"                             # optional: the limit, the OOM-kill line; default equal to memory
user   = "1000:1000"                            # uid:gid CMD runs as; default 1000:1000; "0:0" for root (a kubectl cluster: default from its cluster file, never root)
cluster = "homelab"                              # optional: "homelab" (default), or the name of ~/.config/kgate/clusters/<name>.toml
cache_pvc = "my-cache"                           # kubectl clusters only: mount this claim at /cache instead of an emptyDir
ephemeral_storage = "20Gi"                       # kubectl clusters only: the pod's ephemeral-storage request and limit; default 10Gi
cpu_limit = 8                                    # kubectl clusters only: the CPU limit and build parallelism; default cpu
local_hostnames = ["db"]                         # kubectl clusters only: names that resolve to 127.0.0.1 in the pod
prefer_nodes = false                             # optional: leave the G14 preference out (default true); no profile sets it today

[tools]                                          # exact versions; checked in the pod before CMD
node = "24.22.2"                                 # runs `node --version`
helm = { version = "4.2.3", cmd = "helm version --short" }   # a tool whose version flag differs

[secrets]                                        # env var in the pod = 1Password reference
NODE_AUTH_TOKEN = "op://developer/kgate-github-packages-read/password"

services = ["docker"]                            # optional; see below
```

- **Tools.** The pod runs the command and the expected version must appear in its output as a whole version (`1.98.0` does not match `11.98.0` or `1.98.01`). Any tool with a version command fits without changing kgate: `cargo`, `rustc`, `helm`, `kustomize`, `ansible-lint`, `python3`.
- **Secrets.** Read with `op read` on this Mac at run time into a temporary pod Secret and passed as environment variables. Never in the image, a profile value or the log. `op` runs only with the 1Password service-account token (`OP_SERVICE_ACCOUNT_TOKEN`, else `~/.config/agent-harness/op-service-token`); with neither, the job exits 69 before `op` runs, so it never reaches the desktop app. If `op read` fails the job exits 69.
- **Secret cache.** Each reference is read with `op` at most once in 24 hours on a host (2026-11-13: 637 jobs in a day used up the service account's 1000 daily reads). The value is kept in `${XDG_CACHE_HOME:-~/.cache}/kgate/`, one file per reference named by the SHA-256 of the reference, files mode 0600 in a 0700 directory, written through a temp file and a rename. A job finds a file under 24 hours old (by its modification time) and uses it without running `op`, and without needing the token. An older or missing file means `op read`, then a new file. A failed read writes nothing. Jobs that start together take turns on `.lock` in that directory, so only the first reads. If the directory cannot be used, `op` is read for every job as before. To force a fresh read, delete the file (or the directory).
- **User.** The pod's exec starts as root to unpack. kgate then gives the shipped tree, `/out`, a home and the caches (`/cache/u<uid>`: npm and Cargo, with `CARGO_HOME=/cache/u<uid>/cargo`, because the image's own `/usr/local/cargo` is root-owned) to `user` and runs the version checks and CMD as it, as on a developer's Mac. (As root, `chmod 000` tests pass that a user fails.)
- **Services.** If the gate needs something the image cannot provide (Docker, a database), list it. On the homelab kgate refuses the job with 69; that gate is not a kgate gate. A kubectl cluster offers `mssql` (see "Sidecar and mounts").
- **Image pull.** The image registry `ghcr.io` is private; kgate reads the 1Password item `kgate-github-packages-read` for each job's temporary pull Secret (expires about 2026-12-02; see the homelab `docs/kgate.md`).
- The image needs `tini` (the pod's first process) and `python3` (3.11 or later): the same script runs in the pod to verify the hash and check versions. The version commands run in the job's directory, so per-directory tools (rustup with a `rust-toolchain.toml`) report what CMD will use. `git` is needed when the gate itself uses it.

## Memory: request and limit

- `memory` is the pod's **request**: what the scheduler reserves on a node to place it. It decides where a job fits.
- `memory_limit` is the pod's **limit**: the line at which the pod is OOM-killed. It is optional. When set, it must be at least `memory`, and it takes the same format (`Gi` or `Mi`). Without it the limit equals the request, which is how every profile ran before this key existed.
- A pod whose request is below its limit is Burstable. Under node memory pressure Kubernetes evicts pods that use more than their request first. Above the limit the pod is killed whatever the node has free.
- Sizing rule for a profile: set `memory` (the request) to 1.2 times the highest measured peak, rounded up to 0.5 GiB, with a floor of 0.5 GiB. Keep `memory_limit` as the OOM guard: sizing the request does not raise or lower the limit. The peak kgate records (`peak_bytes`) is the container's cgroup peak, and it includes page cache. The kernel can reclaim page cache, so the peak overstates what the job needs; read it as an upper bound.
- Overrides: `--mem` sets the request. `--mem-limit` sets the limit. A `--mem` above the profile's `memory_limit` is refused unless `--mem-limit` is given too.

## Switching a gate: the parity run

A gate moves to kgate one at a time, each with its profile in its own repo:

1. Write the profile. Take the image digest from the homelab image build and the tool versions from `/usr/local/share/kgate/versions.txt` in the image.
2. Run the gate on the Mac and through `kgate` on the same commit. Results must match: same pass or fail, same counts. Record both in the PR.
3. Only with Michael's approval does the gate's script switch to `kgate`.
4. When the image or a tool version changes, change the pin and the profile and repeat the parity run.

## Profiles

The `kgate` binary lands on both desktop profiles. The homelab host file (`~/.config/kgate/host`) is personal only, so a work machine has no homelab address. The second-cluster files (`~/.config/kgate/clusters/`, `~/.config/kgate/profiles/`) come from a machine's own chezmoi data on any profile that has it, so a machine without that data cannot reach a second cluster. Rows in [profiles.md](./profiles.md).

## Tests

`python3 -m unittest discover -s tests/kgate -v`: for a kubectl cluster, the cluster file (a missing file or key, invalid values, labels, annotations, deadline and user from it, a registry not on its list, the default cache claim) and `cluster-setup`; the pod spec; the archive (no `.git` entry on a kubectl cluster, unchanged on the homelab); the repo the pod side builds (one commit, tree equal to the Mac's hash, clean status, `KGATE_HEAD`); the cache claim (pod spec with and without it, refusal on the homelab, per-job cleanup and the old-directory sweep, a job queued on capacity keeping the cache, a claim held by another job falling back to a cold pod, a brief hold not falling back, a missing claim); the sh pod side run against a real temp git tree (its hash equal to the Python `tree_hash` and to plain git, with an executable file, symlinks and CRLF files under a converting `.gitattributes`; mismatch, tool mismatch, exit code, peak); and the same journeys as the homelab, for a kubectl cluster, against a fake `kubectl` (including a quota refusal waited out, a quota that never frees, another create error failing at once, `cpu_limit`) (pass, CMD failure, `/out`, hash mismatch, tool version, refusals, missing kubeconfig, reachability failure, orphan cancel, the record's `cluster`); the chezmoi step that writes the cluster and profile files from local data (`tests/kgate/test_cluster_files.py`: nothing written without data, exact text, mode 600, bad names refused). For the homelab: the tree hash against real `git write-tree`, the profile, the version match and the pod spec directly (the memory request and limit, and a byte-identical default render); and `kgate cancel` (by kgate id and by run-and-wake id, exactly one pid signalled and a second live client untouched, a bystander in the same process group untouched, prefixes and double matches refused, a dead or recycled pid not signalled, the orphan path's three delete names, `--list`, the registry entry gone after normal and failed finishes, and a real client cancelled end to end against the fake cluster); and the real script as a process against a fake `ssh` (a scripted cluster whose "pod" runs on this machine) and a fake `op`: pass, CMD failure, `/out`, hash mismatch, wrong version, unreachable cluster with nothing run locally, image pull failure, pod never scheduled, unreadable secret, secrets kept out of the pod spec and the logs.

## Gates in this repo

`kgate.toml` is the profile of the dotfiles heavy suites (`tests/heavy-gate`, `tests/workstream-rank`); the command is in `AGENTS.md`. Parity at 141c0d04 on the Mac and on agent-1: 115 + 35 tests, OK on both (tests only: Mac 550.7 s, kgate 466.6 s; 2 tests skip on kgate because the image has no chezmoi, CI runs them). At 26726636 the counts are 138 + 35 on agent-1 and on the G14 (2 skip on both), OK on both (agent-1 495.9 s, G14 477.7 s for heavy-gate). The first runs on the G14 failed on process-table and clock tests while its clock stepped (before homelab#101); the G14 is back in the pool since 2026-11-06 with the same counts.
