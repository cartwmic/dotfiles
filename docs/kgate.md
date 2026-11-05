# kgate

`kgate` runs a heavy gate (a repo's slow test or lint command) on the personal homelab Kubernetes cluster instead of on this Mac. One Python file, `dot_local/bin/executable_kgate`, installed as `~/.local/bin/kgate`. It takes heavy-gate's command line and meets `run-and-wake` and `heavy-gate` only on the command line:

```sh
run-and-wake -- kgate -- sh -c 'npm ci && npm run typecheck && npm test'
```

The pane that started the job is woken when it ends, with the exit code and the log path. The cluster side (image, `kgate` namespace, pull token) is in the homelab repo, `docs/kgate.md`.

## CLI

```
kgate [--profile FILE] [--wait SECONDS] [--cpu N] [--mem SIZE] [--image REF] [--node NODE] -- CMD [ARGS...]
```

- `--profile FILE`: the gate's profile. Default `kgate.toml` at the worktree root. A repo with several gates keeps one profile per gate next to its script and passes `--profile`.
- `--wait`: how long to wait for the pod to start (default 3600).
- `--cpu`, `--mem`, `--image`: override the profile. `--node`: pin one node (never an excluded one).
- CMD runs in the same directory, at the same absolute path, inside the pod.

## What it does

1. Ships the git worktree of the current directory to one pod: tracked and untracked non-ignored files, the `.git` file and the shared git folder, all at the same absolute path. Ignored files (`node_modules`, `target`) stay here. A submodule is refused.
2. **Tree hash.** Before sending, it computes the git tree hash of the shipped files (what `git write-tree` gives for an index of exactly those files). The pod recomputes it after unpacking. If they differ, the job fails and CMD never runs.
3. **Version preflight.** The pod checks each tool in the profile. A mismatch fails the job and prints the tool, expected and found.
4. Runs CMD with the output streaming back live. CMD's exit code is kgate's.
5. **`/out`.** Whatever CMD writes to `/out` (also `$KGATE_OUT`) in the pod is copied to `<state>/<id>.out/` before the pod is deleted, whether CMD passed or failed.
6. Deletes the pod and its Secrets. At each start it also removes what a client that died left behind.

The pod's first process is `tini` (`tini -- sleep infinity`), so processes a gate orphans are reaped, not left as zombies. The pod's memory limit equals its request. `CARGO_BUILD_JOBS`, `RAYON_NUM_THREADS` and `MAKEFLAGS=-jN` are set to the CPU request. The image is pinned by digest. The scheduler is the queue. Pods run on amd64 nodes other than agent-4, the control plane, the Mac mini and the G14 laptop (`EXCLUDED_NODES` in the script). The G14's WSL2 wall clock steps back about 2.8 s every 30 s (a probe on 2026-11-05: 11 s of drift in two minutes; agent-1 had none), so tests that compare times flaked there (an agent-kit watchdog test, a heavy-gate 20-second check).

## No fallback; exit codes

| Exit | Meaning |
|---|---|
| CMD's code | CMD ran to its end. |
| 64 | Bad command line. |
| 69 | The job could not start or finish on the cluster. The reason is printed and in the record. |

69 covers: cluster unreachable, no or bad profile, image not pinned by digest, a secret or the pull token unreadable, a service the gate needs that the pod cannot provide, pod never started (wait ran out, image pull failed), tree hash differs, tool version differs, and a lost connection to a pod after CMD started.

**kgate never runs CMD on this Mac, and never reruns a job that started.** A cluster outage shows as failed gates. A CMD that itself exits 69 looks the same by code; the record's `reason` tells them apart (it is empty when CMD ran to its end).

## Record

One JSON line per job in `${XDG_STATE_HOME:-~/.local/state}/kgate/log.jsonl`; the full output is `<id>.log` beside it. The older lines from before this version (with a `fallback` field) have a different shape.

| Field | Meaning |
|---|---|
| `id` | kgate's job id, also the pod's name |
| `job` | the run-and-wake job id (`RUN_AND_WAKE_JOB`), or null |
| `start`, `end`, `duration_s` | UTC times and seconds |
| `repo`, `cwd`, `head` | repo name, working directory, Mac HEAD |
| `tree` | the tree hash of what was shipped |
| `node`, `image`, `profile`, `cpu`, `mem` | where and how it ran |
| `peak_bytes`, `peak_source` | the container's peak memory: `cgroup` (`memory.peak`, kernel 5.19 and later) or `sampled` (highest `memory.current` seen every 0.5 s, on older kernels). It includes page cache. |
| `ran` | CMD started |
| `exit`, `reason` | exit code; the reason when it is 69 |
| `out_files`, `cleanup`, `output`, `cmd` | files copied back; pod and Secrets confirmed deleted; log file; the command |

## Gate profile

A TOML file in the gate's repo. Keep it small.

```toml
image  = "ghcr.io/cartwmic/kgate@sha256:..."   # required, pinned by digest
cpu    = 2                                      # whole CPUs; default 2
memory = "4Gi"                                  # default 4Gi; the limit equals it
user   = "1000:1000"                            # uid:gid CMD runs as; default 1000:1000; "0:0" for root

[tools]                                          # exact versions; checked in the pod before CMD
node = "24.22.2"                                 # runs `node --version`
helm = { version = "4.2.3", cmd = "helm version --short" }   # a tool whose version flag differs

[secrets]                                        # env var in the pod = 1Password reference
NODE_AUTH_TOKEN = "op://developer/kgate-github-packages-read/password"

services = ["docker"]                            # optional; see below
```

- **Tools.** The pod runs the command and the expected version must appear in its output as a whole version (`1.98.0` does not match `11.98.0` or `1.98.01`). Any tool with a version command fits without changing kgate: `cargo`, `rustc`, `helm`, `kustomize`, `ansible-lint`, `python3`.
- **Secrets.** Read with `op read` on this Mac at run time into a temporary pod Secret and passed as environment variables. Never in the image, a profile value or the log. If `op read` fails the job exits 69.
- **User.** The pod's exec starts as root to unpack. kgate then gives the shipped tree, `/out`, a home and the caches (`/cache/u<uid>`: npm and Cargo, with `CARGO_HOME=/cache/u<uid>/cargo`, because the image's own `/usr/local/cargo` is root-owned) to `user` and runs the version checks and CMD as it, as on a developer's Mac. (As root, `chmod 000` tests pass that a user fails.)
- **Services.** If the gate needs something the image cannot provide (Docker, a database), list it. kgate refuses the job with 69; that gate is not a kgate gate.
- **Image pull.** The image registry `ghcr.io` is private; kgate reads the 1Password item `kgate-github-packages-read` for each job's temporary pull Secret (expires about 2026-12-02; see the homelab `docs/kgate.md`).
- The image needs `tini` (the pod's first process) and `python3` (3.11 or later): the same script runs in the pod to verify the hash and check versions. The version commands run in the job's directory, so per-directory tools (rustup with a `rust-toolchain.toml`) report what CMD will use. `git` is needed when the gate itself uses it.

## Switching a gate: the parity run

A gate moves to kgate one at a time, each with its profile in its own repo:

1. Write the profile. Take the image digest from the homelab image build and the tool versions from `/usr/local/share/kgate/versions.txt` in the image.
2. Run the gate on the Mac and through `kgate` on the same commit. Results must match: same pass or fail, same counts. Record both in the PR.
3. Only with Michael's approval does the gate's script switch to `kgate`.
4. When the image or a tool version changes, change the pin and the profile and repeat the parity run.

## Profiles

Personal only: kgate uses the personal homelab cluster (`.chezmoiignore`; row in [profiles.md](./profiles.md)). The work profile is left out for that reason, and nothing is applied on the work Mac.

## Tests

`python3 -m unittest discover -s tests/kgate -v`: the tree hash against real `git write-tree`, the profile, the version match and the pod spec directly; and the real script as a process against a fake `ssh` (a scripted cluster whose "pod" runs on this machine) and a fake `op`: pass, CMD failure, `/out`, hash mismatch, wrong version, unreachable cluster with nothing run locally, image pull failure, pod never scheduled, unreadable secret, secrets kept out of the pod spec and the logs.

## Gates in this repo

`kgate.toml` is the profile of the dotfiles heavy suites (`tests/heavy-gate`, `tests/workstream-rank`); the command is in `AGENTS.md`. Parity at 141c0d04 on the Mac and on agent-1: 115 + 35 tests, OK on both (Mac 571.8 s, kgate 466.6 s + 0.2 s). The first runs on the G14 failed on process-table and clock tests; the G14's clock steps back (see above), and with it excluded the suite passes.
