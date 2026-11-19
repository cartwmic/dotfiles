# kgate-split

`kgate-split` runs a slow suite of independent tests across several [kgate](kgate.md) pods, longest test first, and proves that every test ran exactly once. One Python file, `dot_local/bin/executable_kgate-split`, installed as `~/.local/bin/kgate-split` on the personal profile only (the work profile has no way for its second cluster's pods to reach the queue; `docs/profiles.md`). It needs a `kgate` on PATH and runs from a git worktree, like `kgate`.

It generalises the coordinator's journey queue (coordinator#1098, #1101). The coordinator's own numbers decided the design: on a calm cluster the slowest of 7 journey pods took 225 to 236 s with a shared queue against 260 to 288 s for a fixed 6-pod split, and 267 to 285 s against 351 s on a busy one. A per-pod claim cap was needed: without it, staggered pod starts let early pods drain the queue (428 s).

## Settings

A `[split]` table in the repo's `kgate.toml` (or the file given with `--profile`). `kgate` ignores the table; every other key in the file is kgate's own.

```toml
[split]
list          = "python3 scripts/journeys.py --list"   # prints one test id per line; runs here, in the current directory, on the tree the pods get
run           = "python3 scripts/journeys.py --only-from {items}"   # runs the test(s) in the file {items}
setup         = "sh scripts/pod-setup.sh"   # optional; runs first in each pod; if it fails the pod "did not run" (69)
pods          = 6      # default 1
lanes         = 4      # tests at once inside one pod; default 1
durations     = "test-durations.json"   # optional; {"test id": seconds}; an id missing from it counts as the median
claim_seconds = 225    # optional; a pod stops claiming this many seconds after its first claim; 0 or absent is no cap
```

- `{items}` is the path of a file that holds the id(s) for this one invocation, one per line (today one id, so a `run` that takes one test reads `$(cat {items})`). The path is shell-quoted. The pod also sets `KGATE_SPLIT_ID` (the id), `KGATE_SPLIT_POD` (the pod's number) and `KGATE_SPLIT_LANE` (0 to lanes-1), so a test can keep a port or a folder of its own per lane.
- An id is a line: it cannot hold a newline. `list` must print each id once; an empty list or a repeated id is refused (exit 64) before any pod starts.
- The `run` command's exit code is the test's: 0 passes.
- `durations` is resolved next to the profile. A missing file means no records yet (every id counts as the median of 1 s, so the first run deals in the seed's order). Write it with `kgate-split durations`.

## Commands

```
kgate-split run [--profile FILE] [--seed N] [--pods N] [--lanes N] [-- KGATE_ARGS...]
kgate-split check RUN_DIR
kgate-split durations [--profile FILE] [--runs N]
```

`--pods` and `--lanes` override the profile (`--pods 1 --lanes 1` is the way to get an exactly reproducible order). Arguments after `--` go to every kgate job (for example `--node cartwmic-g14-wsl`).

### `run`

1. Runs `list` here, makes the deal from the durations file and the seed, and starts a queue on this host: the first free port of 47390 to 47399 (`KGATE_SPLIT_PORTS` changes the range; the host firewall opens that range to the cluster's LAN, homelab#524), with a random token per run. The pods reach it at this host's address toward the kgate control plane, or `KGATE_SPLIT_HOST`. The run directory is `<kgate state>/split-<epoch>-<pid>/`.
2. Starts the pods two seconds apart, each a plain `kgate` job (`kgate -- env KGATE_SPLIT_URL=... KGATE_SPLIT_TOKEN=... KGATE_SPLIT_POD=K python3 -c <bootstrap>`). The bootstrap fetches the worker (this same file) from the queue server, so nothing is added to the tree and the command in kgate's log stays short. The pod needs `python3` (the profile's `[tools]` pins it).
3. In the pod: run `setup`, then `lanes` threads each claim the next id from the queue, run `run` on it, and write its result to `/out/results.jsonl` and its output to `/out/logs/`. A failed test prints its last 20 lines in the pod output (shown live with a `[pod K/N]` prefix). Everything else the test leaves in `/out` comes back too, per pod, under `pods/K/` in the run directory.
4. A pod stops claiming once its `claim_seconds` have passed since its first claim; tests it already holds run to the end. When every capped pod has ended and ids remain unclaimed, one more pod, with no cap, takes them (the leftover pod, number pods+1).
5. A pod that never started (kgate exit 75, or 69 with `"ran": false` in kgate's record) is started once more. A pod whose command ran and failed is not.
6. When every pod has ended: copy each pod's `/out` into the run directory, judge the run (below), print the receipt, save it as `receipt.txt`.

On TERM, INT or HUP every pod's kgate client is sent TERM (each client is its own process group; a client deletes its pod on TERM), `kgate-split` waits until none is left, prints `stopped by <signal>`, merges nothing and exits 143, 130 or 129.

### The verdict

A pure function of the run directory (`kgate-split check RUN_DIR` reads only that and prints the receipt again). Every id from `list` must be reported exactly once.

| Exit | Meaning |
|---|---|
| 0 | every test passed and the run is complete |
| 1 | a test failed, or the run is INCOMPLETE: an id reported twice or not in the list, an id handed out twice, or an id with no report that no pod's failure explains (every pod ended normally and still left it out) |
| 64 | bad usage or settings, or `list` printed nothing or an id twice |
| 69 | nothing failed, and a pod did not run to its end: ids handed to it have no result (`lost:`), or ids nobody took because a pod did not run (`missing:`); also `list` failed, no port was free, or this host's address is unknown. A setup failure is "did not run" |

1 wins over 69. A pod that did not run, took nothing, and whose ids all ran elsewhere is left out of the verdict with a `note:` line. This is the coordinator's `journeys-complete.py` rule, except that an id lost by a pod that ended normally is INCOMPLETE (1), not 69: a pod that ran to its end and did not report an id has a reporting fault, not an outage.

Finding lines: `FAIL <id>: ...`, `INCOMPLETE: dup: ...`, `INCOMPLETE: lost: <id> handed out to pod K, no result`, `NOT RUN: pod K did not run to its end (...)`.

### The seed (the order-and-split check)

Each run picks a random seed (`--seed N` sets it) and prints `seed: N` and `rerun with: kgate-split run --seed N [--pods ..] [--lanes ..]` in the receipt. The seed fixes the **hand-out sequence**: ids longer than the median recorded time are handed out roughly longest first (each recorded time is multiplied by a seeded jitter, exp of 0.5 x a normal draw, before sorting: a test twice as long as its neighbour still goes first about 5 times in 6, and one far longer than the rest always goes first), and the others (at or below the median, or with no record, which counts as the median) in the seed's random order. So with full records the order still changes from run to run, a one-pod one-lane run is shuffled, and the long tests, which set the wall time, are never held back far (simulated on the coordinator's 212 durations over 200 seeds: with 7, 14 and 28 slots the worst wall time was 1.5%, 2.9% and 0% over the best possible, the same as shuffling only the short half). The sequence is a pure function of the seed, the list and the durations, whichever pod asks.

What the seed does **not** fix: which pod and lane gets a given id. That depends on timing. A test that only fails when two particular tests share a pod may need more than one rerun with the seed; `--pods 1 --lanes 1` makes the whole order exact.

### The stuck-test kill

The pod kills a test at `max(10 x its recorded median, 120 s)`. An id with no record is judged against the suite's median (the same ten times, the same 120 s floor). The test's process group gets TERM, then KILL after 5 s, and the test is reported as failed: `killed after N s; its recorded time is M s` (`it has no recorded time (the median is M s)` for an unknown id). The receipt lists, as `slow:`, every test that ran over 3 x its record (and was not killed), the biggest overrun first. A test that goes over only needs the durations file refitted: that stays an ordinary PR.

### `durations`

`kgate-split durations` refits the durations file from the last green runs of this repo in the kgate state directory (`--runs N`, default 5; a run is green when its verdict is exit 0): the median seconds per id of the latest green run's tests. It writes the file longest first and prints the plan against actual: per pod, the tests it was handed, their recorded seconds, and what the pod took; and the total estimate against the lanes and the wall time.

## Receipt

```
kgate-split run split-1795...-1234: repo 0123abcd4567
seed: 101
plan: 20 tests, 2 pods x 3 lanes, median 1 s, 20 with a recorded time, queue at http://10.19.1.200:47390
pod 1/2: kgate-... exit 0 node cartwmic-g14-wsl: 11 tests, 37 est s, took 38 s
...
FAIL stuck.sh: killed after 120 s; its recorded time is 1 s (pod 2)
VERDICT: FAILED: 19 PASS, 1 FAIL of 20 (131 s)
run dir: <kgate state>/split-...
rerun with: kgate-split run --seed 101
```

## Moving a repo onto it

- `list` must run on the host, with what the host has (it runs where you type `kgate-split run`, in the current directory). If listing needs an install (a vitest list), `list` has to run on a tree with it.
- A test that is split into parts (journeys with rows) needs one id per part.
- A pod gets only what the `run` command line, the tree and `setup` give it: environment a pod needs (a core binary, a token) goes into `setup` or the profile's `[secrets]`, not through `kgate-split`.
- Tests run side by side in one pod (`lanes`) share its home and ports. `KGATE_SPLIT_LANE` is there for that.
- The shared queue and the pods' results do not know about a tool-specific verdict file. A repo that needs a merged artifact (a summary, kept scratch) reads `pods/K/` in the run directory.

## Tests

`tests/kgate-split` (`python3 -m unittest discover -s tests/kgate-split`): the deal, limits, settings and verdict as units; the real tool as a process against a fake `kgate` on PATH that runs the pod command here, over a real HTTP queue on an ephemeral port. `tests/kgate` checks that the client accepts a `[split]` table.
