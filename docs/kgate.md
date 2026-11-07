# kgate

`kgate` runs a heavy gate (a repo's slow test or lint command) on the personal homelab Kubernetes cluster instead of on this Mac. One Python file, `dot_local/bin/executable_kgate`, installed as `~/.local/bin/kgate`. It takes heavy-gate's command line and meets `run-and-wake` and `heavy-gate` only on the command line:

The cluster host is not in this repo. `KGATE_SSH` (`user@address`) wins; otherwise `kgate` reads the one line in `~/.config/kgate/host`, which chezmoi renders from the local data key `sshHosts.kgate` (`address`, `user`; see [profiles.md](profiles.md), "Local data keys"). With neither set, `kgate` exits 69 and the message names the key.

```sh
run-and-wake -- kgate -- sh -c 'npm ci && npm run typecheck && npm test'
```

The pane that started the job is woken when it ends, with the exit code and the log path. The cluster side (image, `kgate` namespace, pull token) is in the homelab repo, `docs/kgate.md`.

## CLI

```
kgate [--profile FILE] [--wait SECONDS] [--cpu N] [--mem SIZE] [--mem-limit SIZE] [--image REF] [--node NODE] -- CMD [ARGS...]
```

- `--profile FILE`: the gate's profile. Default `kgate.toml` at the worktree root. A repo with several gates keeps one profile per gate next to its script and passes `--profile`.
- `--wait`: how long to wait for the pod to start (default 3600).
- `--cpu`, `--mem`, `--mem-limit`, `--image`: override the profile. `--mem` sets the memory request, `--mem-limit` the limit (see "Memory: request and limit"). `--node`: pin one node (never an excluded one).
- CMD runs in the same directory, at the same absolute path, inside the pod.

## What it does

1. Ships the git worktree of the current directory to one pod: tracked and untracked non-ignored files, the `.git` file and the shared git folder, all at the same absolute path. Ignored files (`node_modules`, `target`) stay here. A submodule is refused.
2. **Tree hash.** Before sending, it computes the git tree hash of the shipped files (what `git write-tree` gives for an index of exactly those files). The pod recomputes it after unpacking. If they differ, the job fails and CMD never runs.
3. **Version preflight.** The pod checks each tool in the profile. A mismatch fails the job and prints the tool, expected and found.
4. Runs CMD with the output streaming back live. CMD's exit code is kgate's.
5. **`/out`.** Whatever CMD writes to `/out` (also `$KGATE_OUT`) in the pod is copied to `<state>/<id>.out/` before the pod is deleted, whether CMD passed or failed.
6. Deletes the pod and its Secrets. At each start it also removes what a client that died left behind.

The pod's first process is `tini` (`tini -- sleep infinity`), so processes a gate orphans are reaped, not left as zombies. The pod's memory request is `memory` and its limit is `memory_limit`, which equals `memory` unless the profile sets it (see "Memory: request and limit"). `CARGO_BUILD_JOBS`, `RAYON_NUM_THREADS` and `MAKEFLAGS=-jN` are set to the CPU request. The image is pinned by digest. The scheduler is the queue. Pods run on amd64 nodes other than agent-4, the control plane and the Mac mini (`EXCLUDED_NODES` in the script). The G14 laptop (`cartwmic-g14-wsl`) is schedulable again since 2026-11-06; `--node cartwmic-g14-wsl` pins a job there. Until homelab#101 (9f6ef66, 2026-11-05, systemd-timesyncd off) its WSL2 wall clock stepped back about 2.8 s every 30 s (a probe on 2026-11-05: 11 s of drift in two minutes; agent-1 had none), so tests that compare times flaked there (an agent-kit watchdog test, a heavy-gate 20-second check). It now follows the Windows clock, which slews up to 8% for about 15 s roughly every 9 h, and it can read up to about 2 s ahead of other nodes.

## No fallback; exit codes

| Exit | Meaning |
|---|---|
| CMD's code | CMD ran to its end. |
| 64 | Bad command line. |
| 69 | The job could not start or finish on the cluster. The reason is printed and in the record. |

69 covers: cluster unreachable, no or bad profile, image not pinned by digest, a secret or the pull token unreadable, a service the gate needs that the pod cannot provide, pod never started (wait ran out, image pull failed), tree hash differs, tool version differs, and a lost connection to a pod after CMD started.

**kgate never runs CMD on this Mac, and never reruns a job that started.** A cluster outage shows as failed gates. A CMD that itself exits 69 looks the same by code; the record's `reason` tells them apart (it is JSON `null` when CMD ran to its end, and a text reason otherwise).

## When the cluster is full

When no node has room for the pod's CPU or memory request, the pod stays `Pending`. kgate waits for room and then gives up with exit 69. It never runs the job on the Mac.

- A full cluster leaves the pod `Pending`, with `PodScheduled` `False` and reason `Unschedulable`. The client waits by itself. It prints `kgate: waiting for the pod: Unschedulable` to the job log when that state first appears.
- It keeps waiting until `--wait` seconds (default 3600) after the job started.
- If the wait runs out, it exits 69. The record's `reason` is `pod did not start within <N>s: Unschedulable <scheduler message>`. kgate copies the scheduler message unchanged, up to 300 characters. Kubernetes scheduler messages look like `0/N nodes are available: ... Insufficient memory`.

The reason tells a full cluster apart from the other ways a job fails to start. These are the prefixes kgate writes:

| `reason` starts with | Cause | Capacity? |
|---|---|---|
| `pod did not start within <N>s: Unschedulable` | No node had room for the whole wait. | Yes |
| `pod did not start: ` (for example `ErrImagePull`, `ImagePullBackOff`, `CreateContainerConfigError`, or a pod phase of `Failed`) | The pod failed before CMD ran. | No |
| `cluster unreachable (` | The cluster or its ssh route is down. | No |
| `could not create the pod: ` | The cluster refused to create the pod. | No |

Every other exit-69 reason (a bad profile, a tree hash or tool version mismatch, an unreadable secret) is not a capacity problem either.

**What callers do.**

- Wait. Pass `--wait 1200` for short gates.
- On exit 69 whose `reason` starts `pod did not start within` and contains `Unschedulable`, the caller may run heavy-gate once, but only when the profile fits some kgate node (see the node table in "How many jobs at once"). Every committed profile does. Then it must report "(2) no kgate capacity" and quote the reason.
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

Profile sizes in use, from each repo's `kgate.toml` on origin/main (2026-11-06):

| Gate | Repo | cpu | memory |
|---|---|---|---|
| agent-kit unit gate | `agent-kit` | 2 | `3584Mi` (3.5 Gi) |
| coordinator unit gate | `coordinator` | 4 | `3Gi` |
| budget-steward unit gate | `budget-steward` (gitea) | 4 | `7Gi` |
| homelab static checks | `cartwmic-homelab-v2` | 2 | `1Gi` |
| dotfiles heavy suites | `dotfiles` | 2 | `1Gi` |
| Loop Engine baseline | `loop-engine` | 12 | `8Gi` |

Before you change a profile's size, check it against the node table above.

Jobs that only wait for model API calls (evals) are not heavy. They should not use heavy-gate or kgate slots; they run as plain background jobs.

## Record

One JSON line per job in `${XDG_STATE_HOME:-~/.local/state}/kgate/log.jsonl`; the full output is `<id>.log` beside it. The older lines from before this version (with a `fallback` field) have a different shape.

| Field | Meaning |
|---|---|
| `id` | kgate's job id, also the pod's name |
| `job` | the run-and-wake job id (`RUN_AND_WAKE_JOB`), or null |
| `start`, `end`, `duration_s` | UTC times and seconds |
| `repo`, `cwd`, `head` | repo name, working directory, Mac HEAD |
| `tree` | the tree hash of what was shipped |
| `node`, `image`, `profile`, `cpu`, `mem`, `mem_limit` | where and how it ran; `mem` is the memory request and `mem_limit` the limit |
| `peak_bytes`, `peak_source` | the container's peak memory: `cgroup` (`memory.peak`, kernel 5.19 and later) or `sampled` (highest `memory.current` seen every 0.5 s, on older kernels). It includes page cache. |
| `ran` | CMD started |
| `exit`, `reason` | exit code; the reason when it is 69 |
| `out_files`, `cleanup`, `output`, `cmd` | files copied back; pod and Secrets confirmed deleted; log file; the command |

## Gate profile

A TOML file in the gate's repo. Keep it small.

```toml
image  = "ghcr.io/cartwmic/kgate@sha256:..."   # required, pinned by digest
cpu    = 2                                      # whole CPUs; default 2
memory = "4Gi"                                  # the request, what the scheduler reserves; default 4Gi
memory_limit = "8Gi"                             # optional: the limit, the OOM-kill line; default equal to memory
user   = "1000:1000"                            # uid:gid CMD runs as; default 1000:1000; "0:0" for root

[tools]                                          # exact versions; checked in the pod before CMD
node = "24.22.2"                                 # runs `node --version`
helm = { version = "4.2.3", cmd = "helm version --short" }   # a tool whose version flag differs

[secrets]                                        # env var in the pod = 1Password reference
NODE_AUTH_TOKEN = "op://developer/kgate-github-packages-read/password"

services = ["docker"]                            # optional; see below
```

- **Tools.** The pod runs the command and the expected version must appear in its output as a whole version (`1.98.0` does not match `11.98.0` or `1.98.01`). Any tool with a version command fits without changing kgate: `cargo`, `rustc`, `helm`, `kustomize`, `ansible-lint`, `python3`.
- **Secrets.** Read with `op read` on this Mac at run time into a temporary pod Secret and passed as environment variables. Never in the image, a profile value or the log. `op` runs only with the 1Password service-account token (`OP_SERVICE_ACCOUNT_TOKEN`, else `~/.config/agent-harness/op-service-token`); with neither, the job exits 69 before `op` runs, so it never reaches the desktop app. If `op read` fails the job exits 69.
- **User.** The pod's exec starts as root to unpack. kgate then gives the shipped tree, `/out`, a home and the caches (`/cache/u<uid>`: npm and Cargo, with `CARGO_HOME=/cache/u<uid>/cargo`, because the image's own `/usr/local/cargo` is root-owned) to `user` and runs the version checks and CMD as it, as on a developer's Mac. (As root, `chmod 000` tests pass that a user fails.)
- **Services.** If the gate needs something the image cannot provide (Docker, a database), list it. kgate refuses the job with 69; that gate is not a kgate gate.
- **Image pull.** The image registry `ghcr.io` is private; kgate reads the 1Password item `kgate-github-packages-read` for each job's temporary pull Secret (expires about 2026-12-02; see the homelab `docs/kgate.md`).
- The image needs `tini` (the pod's first process) and `python3` (3.11 or later): the same script runs in the pod to verify the hash and check versions. The version commands run in the job's directory, so per-directory tools (rustup with a `rust-toolchain.toml`) report what CMD will use. `git` is needed when the gate itself uses it.

## Memory: request and limit

- `memory` is the pod's **request**: what the scheduler reserves on a node to place it. It decides where a job fits.
- `memory_limit` is the pod's **limit**: the line at which the pod is OOM-killed. It is optional. When set, it must be at least `memory`, and it takes the same format (`Gi` or `Mi`). Without it the limit equals the request, which is how every profile ran before this key existed.
- A pod whose request is below its limit is Burstable. Under node memory pressure Kubernetes evicts pods that use more than their request first. Above the limit the pod is killed whatever the node has free.
- Rule of thumb for a profile: set `memory` to about 1.2 times the highest measured peak, and `memory_limit` to at least the peak plus a margin. The peak kgate records (`peak_bytes`) is the container's cgroup peak, and it includes page cache. The kernel can reclaim page cache, so the peak overstates what the job needs; read it as an upper bound.
- Overrides: `--mem` sets the request. `--mem-limit` sets the limit. A `--mem` above the profile's `memory_limit` is refused unless `--mem-limit` is given too.

## Switching a gate: the parity run

A gate moves to kgate one at a time, each with its profile in its own repo:

1. Write the profile. Take the image digest from the homelab image build and the tool versions from `/usr/local/share/kgate/versions.txt` in the image.
2. Run the gate on the Mac and through `kgate` on the same commit. Results must match: same pass or fail, same counts. Record both in the PR.
3. Only with Michael's approval does the gate's script switch to `kgate`.
4. When the image or a tool version changes, change the pin and the profile and repeat the parity run.

## Profiles

Personal only: kgate uses the personal homelab cluster (`.chezmoiignore`; row in [profiles.md](./profiles.md)). The work profile is left out for that reason, and nothing is applied on the work Mac.

## Tests

`python3 -m unittest discover -s tests/kgate -v`: the tree hash against real `git write-tree`, the profile, the version match and the pod spec directly (the memory request and limit, and a byte-identical default render); and the real script as a process against a fake `ssh` (a scripted cluster whose "pod" runs on this machine) and a fake `op`: pass, CMD failure, `/out`, hash mismatch, wrong version, unreachable cluster with nothing run locally, image pull failure, pod never scheduled, unreadable secret, secrets kept out of the pod spec and the logs.

## Gates in this repo

`kgate.toml` is the profile of the dotfiles heavy suites (`tests/heavy-gate`, `tests/workstream-rank`); the command is in `AGENTS.md`. Parity at 141c0d04 on the Mac and on agent-1: 115 + 35 tests, OK on both (tests only: Mac 550.7 s, kgate 466.6 s; 2 tests skip on kgate because the image has no chezmoi, CI runs them). At 26726636 the counts are 138 + 35 on agent-1 and on the G14 (2 skip on both), OK on both (agent-1 495.9 s, G14 477.7 s for heavy-gate). The first runs on the G14 failed on process-table and clock tests while its clock stepped (before homelab#101); the G14 is back in the pool since 2026-11-06 with the same counts.
