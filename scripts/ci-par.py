# PROTOTYPE (CI plan, not for merge): run each unittest test id in its own process, N at a time; exit 1 if any fails
import subprocess, sys, time, unittest, concurrent.futures as cf, os
start_dir, n = sys.argv[1], int(sys.argv[2])
def ids(s):
    for t in s:
        if isinstance(t, unittest.TestSuite): yield from ids(t)
        else: yield t.id()
suite = unittest.TestLoader().discover(start_dir)
tests = list(ids(suite))
t0 = time.time()
def run(tid):
    r = subprocess.run([sys.executable, '-m', 'unittest', tid], cwd=start_dir, capture_output=True, text=True)
    return tid, r.returncode, r.stderr[-400:]
bad = []
with cf.ThreadPoolExecutor(n) as ex:
    for tid, rc, err in ex.map(run, tests):
        if rc: bad.append((tid, err))
print(f"{start_dir}: {len(tests)} tests, {n} at a time, wall {time.time()-t0:.0f}s, failed {len(bad)}")
for tid, err in bad[:5]: print('FAIL', tid, err[-200:])
sys.exit(1 if bad else 0)
