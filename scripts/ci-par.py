# PROTOTYPE (CI plan, not for merge): run every unittest test id from the given suites in its own process, N at a time.
# usage: ci-par.py N DIR [DIR ...]   Each test runs with its suite dir as cwd and top-level dir, as `unittest discover -s DIR` does. Exit 1 if any fails.
import subprocess, sys, time, unittest, concurrent.futures as cf, os
n, dirs = int(sys.argv[1]), sys.argv[2:]
def ids(s):
    for t in s:
        if isinstance(t, unittest.TestSuite): yield from ids(t)
        else: yield t.id()
jobs = []
for d in dirs:
    found = list(ids(unittest.TestLoader().discover(os.path.abspath(d), top_level_dir=os.path.abspath(d))))
    sys.path[:] = [p for p in sys.path if p != os.path.abspath(d)]
    for k in [m for m in sys.modules if m.startswith('test')]: del sys.modules[k]
    jobs += [(d, t) for t in found]
t0 = time.time()
def run(job):
    d, tid = job
    s = time.time()
    r = subprocess.run([sys.executable, '-m', 'unittest', tid], cwd=d, capture_output=True, text=True)
    return d, tid, r.returncode, r.stderr[-1500:], time.time() - s
bad, times = [], []
with cf.ThreadPoolExecutor(n) as ex:
    for d, tid, rc, err, dt in ex.map(run, jobs):
        times.append((dt, tid))
        if rc: bad.append((tid, err))
print(f"{len(dirs)} suites, {len(jobs)} tests, {n} at a time, wall {time.time()-t0:.0f}s, serial sum {sum(t for t,_ in times):.0f}s, failed {len(bad)}")
for dt, tid in sorted(times, reverse=True)[:8]: print(f"  {dt:5.1f}s {tid}")
for tid, err in bad: print('FAIL', tid, '\n', err)
sys.exit(1 if bad else 0)
