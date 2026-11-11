#!/usr/bin/env python3
"""Run the Linux unittest suites in parallel (CI).

usage: ci-par.py [--per-test DIR]... [SUITE[:PATTERN]]...

--per-test DIR   every test id that `unittest discover -s DIR` finds runs in its own process,
                 16 at a time, with DIR as the working directory.
SUITE[:PATTERN]  one `python3 -m unittest discover -s SUITE [-p PATTERN] -v` process, 8 at a time,
                 run from the current directory (the repo root in CI).

Both pools run at once. Prints the wall time and, for each failure, its name and its full output.
Exits 1 if anything fails, including a per-test directory whose tests cannot be listed or are empty.
"""
import argparse
import concurrent.futures as cf
import os
import subprocess
import sys
import time

TEST_PROCESSES = 16
SUITE_PROCESSES = 8
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


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--per-test", action="append", default=[], metavar="DIR")
    ap.add_argument("suites", nargs="*", metavar="SUITE[:PATTERN]")
    args = ap.parse_args()

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
        jobs += [(tid, [sys.executable, "-m", "unittest", tid], d, "test") for tid in ids]
    for spec in args.suites:
        suite, _, pattern = spec.partition(":")
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", suite, "-v"]
        if pattern:
            cmd += ["-p", pattern]
        jobs.append((spec, cmd, None, "suite"))

    start = time.monotonic()
    results = []   # (name, rc, output, secs)
    with cf.ThreadPoolExecutor(TEST_PROCESSES) as tests_pool, cf.ThreadPoolExecutor(SUITE_PROCESSES) as suite_pool:
        pending = {}
        for name, cmd, cwd, kind in jobs:
            pool = tests_pool if kind == "test" else suite_pool
            pending[pool.submit(run, cmd, cwd or os.getcwd())] = name
        for fut in cf.as_completed(pending):
            rc, out, secs = fut.result()
            results.append((pending[fut], rc, out, secs))
    wall = time.monotonic() - start

    for name, secs, output in failures:
        print(f"FAIL {name} ({secs:.1f}s)\n{output}")
    for name, rc, output, secs in results:
        if rc:
            print(f"FAIL {name} (exit {rc}, {secs:.1f}s)\n{output}")
    failed = len(failures) + sum(1 for _, rc, _, _ in results if rc)
    serial = sum(secs for _, _, _, secs in results)
    slowest = sorted(results, key=lambda r: r[3], reverse=True)[:3]
    print(f"ci-par: {len(args.suites)} suites, {test_count} per-test ids, wall {wall:.1f}s, "
          f"serial sum {serial:.0f}s, {failed} failed")
    print("slowest: " + ", ".join(f"{name} {secs:.0f}s" for name, _, _, secs in slowest))
    sys.stdout.flush()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
