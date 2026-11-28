#!/usr/bin/env python3
"""Run the Linux unittest suites in parallel (CI).

usage: ci-par.py [--per-test DIR]... [--shards N DIR [--hold ID]... [--hold-file FILE]] [SUITE[:PATTERN]]...

--per-test DIR   every test id that `unittest discover -s DIR` finds runs in its own process,
                 16 at a time, with DIR as the working directory.
--shards N DIR   the test ids that `unittest discover -s DIR` finds run in N processes (every Nth id to each, so slow tests spread),
                 with DIR as the working directory, in the suite pool. For a suite whose start-up is dear (a process per test
                 would pay it 600 times) and whose tests share nothing on disk. Its counts are summed under DIR. It prints the selection first, e.g.
                 `tests/kgate: 612 ids, 1 held, the other 611 dealt round-robin to 4 parts: 153, 153, 153, 152`.
--hold ID        with --shards: leave this test id out of the shards (a timing-bound test that fails under load). The caller runs
                 it, and an id that DIR does not hold is an error, so a stale name cannot drop a test unseen.
--hold-file FILE one test id a line, each held as --hold ID holds it (blank lines are skipped).
SUITE[:PATTERN]  one `python3 -m unittest discover -s SUITE [-p PATTERN] -v` process, one per CPU at a time
                 run from the current directory (the repo root in CI).

Both pools run at once. Prints the wall time and, for each failure, its name and its full output.
Exits 1 if anything fails, including a per-test directory whose tests cannot be listed or are empty.
"""
import argparse
import concurrent.futures as cf
import os
import re
import subprocess
import sys
import time

TEST_PROCESSES = 16


def read(path):
    with open(path) as f:
        return f.read()


def available_cpus(cgroup="/sys/fs/cgroup"):
    """CI_PAR_JOBS (a positive integer) wins. Otherwise the CPUs this process may use: the smallest of the cgroup CPU quota (rounded up), the affinity mask and os.cpu_count().
    In a pod os.cpu_count() is the node's CPUs, not the pod's limit, and a kgate pod has a CPU request but no limit, so set CI_PAR_JOBS there. No quota or no cgroup file: no cap from that source."""
    forced = os.environ.get("CI_PAR_JOBS", "")
    if forced.isdigit() and int(forced) > 0:
        return int(forced)
    n = os.cpu_count() or 1
    if hasattr(os, "sched_getaffinity"):
        n = min(n, len(os.sched_getaffinity(0)) or n)
    try:  # cgroup v2: "max 100000" or "<quota> <period>"
        quota, period = read(os.path.join(cgroup, "cpu.max")).split()[:2]
    except (OSError, ValueError):
        try:  # cgroup v1: -1 means no quota
            quota = read(os.path.join(cgroup, "cpu/cpu.cfs_quota_us")).strip()
            period = read(os.path.join(cgroup, "cpu/cpu.cfs_period_us")).strip()
        except OSError:
            return n
    if quota in ("max", "-1") or not quota.isdigit() or not period.isdigit() or int(period) == 0:
        return n
    return max(1, min(n, -(-int(quota) // int(period))))


# Suites are CPU-bound, so one per available CPU (4 on the GitHub runner, the pod's limit on kgate). Per-test heavy-gate stays at 16: those tests sleep.
SUITE_PROCESSES = available_cpus()
LIST_TESTS = """
import sys, unittest
def ids(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from ids(t)
        else:
            yield t.id()
for tid in ids(unittest.TestLoader().discover('.')):
    print(tid)
"""


def list_tests(d):
    """The test ids `discover -s d` finds, or raise with the listing's output."""
    r = subprocess.run([sys.executable, "-c", LIST_TESTS], cwd=d, capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        raise RuntimeError(f"could not list tests in {d} (exit {r.returncode}):\n{r.stdout}{r.stderr}")
    return r.stdout.split()


def run(cmd, cwd):
    start = time.monotonic()
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return r.returncode, r.stdout, time.monotonic() - start


def counts(output):
    """(tests run, tests skipped) from the LAST `Ran N tests` line and the result line after it: unittest's own summary of
    this process. Earlier lines can be a test's echo of a child run, which must not count."""
    ran = re.findall(r"^Ran (\d+) tests?", output, re.M)
    if not ran:
        return 0, 0
    tail = output[output.rindex("\nRan " if "\nRan " in output else "Ran "):]
    skipped = re.search(r"^(?:OK|FAILED) \(.*?skipped=(\d+)", tail, re.M)
    return int(ran[-1]), int(skipped.group(1)) if skipped else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--per-test", action="append", default=[], metavar="DIR")
    ap.add_argument("--shards", nargs=2, metavar=("N", "DIR"))
    ap.add_argument("--hold", action="append", default=[], metavar="ID")
    ap.add_argument("--hold-file", metavar="FILE")
    ap.add_argument("suites", nargs="*", metavar="SUITE[:PATTERN]")
    args = ap.parse_args()
    if args.hold_file:
        try:
            args.hold += [line.strip() for line in open(args.hold_file) if line.strip()]
        except OSError as e:
            ap.error(f"--hold-file: {e}")
    if args.hold and not args.shards:
        ap.error("--hold and --hold-file need --shards")
    if args.shards and not (args.shards[0].isdigit() and int(args.shards[0]) > 0):
        ap.error("--shards N must be a positive integer")

    # name, command, cwd, pool
    jobs = []
    failures = []   # (name, secs, output) for work that never started
    test_count = 0
    for d in args.per_test:
        try:
            ids = list_tests(d)
        except RuntimeError as e:
            failures.append((d, 0.0, str(e)))
            continue
        test_count += len(ids)
        jobs += [(tid, [sys.executable, "-m", "unittest", tid], d, "test", d) for tid in ids]
    if args.shards:
        n, d = int(args.shards[0]), args.shards[1]
        try:
            ids = list_tests(d)
            if [h for h in args.hold if h not in ids]:
                raise RuntimeError(f"--hold names tests that {d} does not hold: {[h for h in args.hold if h not in ids]}")
        except RuntimeError as e:
            failures.append((d, 0.0, str(e)))
        else:
            listed = len(ids)
            ids = [i for i in ids if i not in args.hold]
            print(f"{d}: {listed} ids, {len(args.hold)} held, the other {len(ids)} dealt round-robin to {n} parts: "
                  + ", ".join(str(len(ids[k::n])) for k in range(n)), flush=True)
            for k in range(n):
                part = ids[k::n]
                if part:   # no ids would make unittest discover everything in DIR
                    jobs.append((f"{d} [part {k + 1} of {n}]", [sys.executable, "-m", "unittest", "-v", *part], d, "suite", d))
    for spec in args.suites:
        suite, _, pattern = spec.partition(":")
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", suite, "-v"]
        if pattern:
            cmd += ["-p", pattern]
        jobs.append((spec, cmd, None, "suite", spec))

    start = time.monotonic()
    results = []   # (name, rc, output, secs)
    with cf.ThreadPoolExecutor(TEST_PROCESSES) as tests_pool, cf.ThreadPoolExecutor(SUITE_PROCESSES) as suite_pool:
        pending = {}
        for name, cmd, cwd, kind, group in jobs:
            pool = tests_pool if kind == "test" else suite_pool
            pending[pool.submit(run, cmd, cwd or os.getcwd())] = (name, group)
        for fut in cf.as_completed(pending):
            rc, out, secs = fut.result()
            results.append((pending[fut][0], rc, out, secs, pending[fut][1]))
    wall = time.monotonic() - start

    for name, secs, output in failures:
        print(f"FAIL {name} ({secs:.1f}s)\n{output}")
    for name, rc, output, secs, _ in results:
        if rc:
            print(f"FAIL {name} (exit {rc}, {secs:.1f}s)\n{output}")
    # Per-suite counts, so a run on another machine can be compared with this one: a pass that skips tests is not the same check.
    # Per-test ids are summed under their suite directory.
    totals = {}
    for _, _, output, _, group in results:
        r, k = counts(output)
        t = totals.setdefault(group, [0, 0])
        t[0] += r
        t[1] += k
    print("suite counts (ran, skipped):")
    for key in sorted(totals):
        print(f"  {key}: {totals[key][0]} ran, {totals[key][1]} skipped")
    failed = len(failures) + sum(1 for _, rc, _, _, _ in results if rc)
    serial = sum(r[3] for r in results)
    slowest = sorted(results, key=lambda r: r[3], reverse=True)[:3]
    print(f"ci-par: {len(args.suites)} suites ({SUITE_PROCESSES} at a time), {test_count} per-test ids ({TEST_PROCESSES} at a time), "
          f"wall {wall:.1f}s, serial sum {serial:.0f}s, {failed} failed")
    print("slowest: " + ", ".join(f"{name} {secs:.0f}s" for name, _, _, secs, _ in slowest))
    sys.stdout.flush()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
