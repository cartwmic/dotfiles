"""mutate.py runs the suite against a broken copy of workstream-rank. A copy that loops forever, or leaves a process
behind, must not outlive its run: the run is over a time limit, over, or interrupted, and nothing started for it may be
left running afterwards. Counted as the processes whose command line names a path under the run's temporary folder."""
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import mutate

HERE = Path(__file__).resolve().parent
LOOPS_FOREVER = "while :; do :; done\n"
# Starts a background copy of itself and answers nothing: the suite fails fast and the copy outlives it (30 s, then it ends alone).
LEAVES_A_PROCESS = 'case $1 in --child) sleep 30 ;; *) sh "$0" --child </dev/null >/dev/null 2>&1 & ;; esac\n'


def leftovers(folder, wait=5):
    """The processes whose command line names a path under folder, once they have had up to `wait` seconds to go."""
    deadline = time.monotonic() + wait
    while True:
        out = subprocess.run(["ps", "-A", "-ww", "-o", "command="], capture_output=True, text=True, check=True).stdout
        found = [line for line in out.splitlines() if str(folder) in line]
        if not found or time.monotonic() > deadline:
            return found
        time.sleep(0.05)


class NothingLeftRunning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="workstream-rank-mutate-")
        self.addCleanup(self.tmp.cleanup)

    def test_a_mutant_that_loops_forever_is_killed_at_the_time_limit(self):
        started = time.monotonic()
        killed = mutate.run_suite(self.tmp.name, LOOPS_FOREVER, limit=3)    # under the suite's own 20 s per call
        self.assertTrue(killed)
        self.assertLess(time.monotonic() - started, 15)
        self.assertEqual(leftovers(self.tmp.name), [])

    def test_a_process_the_mutant_starts_does_not_outlive_the_run(self):
        self.assertTrue(mutate.run_suite(self.tmp.name, LEAVES_A_PROCESS))
        self.assertEqual(leftovers(self.tmp.name), [])

    def test_an_interrupted_run_leaves_nothing_running(self):
        """A child Python runs the suite on a mutant that loops and is sent SIGINT once the mutant is running."""
        code = ("import sys; sys.path.insert(0, %r); import mutate\n"
                "mutate.run_suite(%r, %r)\n") % (str(HERE), self.tmp.name, LOOPS_FOREVER)
        child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(child.kill)
        deadline = time.monotonic() + 30
        while not leftovers(Path(self.tmp.name) / "bin" / "mutant", wait=0):    # the child's own command line names the folder too
            self.assertLess(time.monotonic(), deadline, "the mutant never started")
            self.assertIsNone(child.poll(), "the child ended before the mutant started")
            time.sleep(0.05)
        child.send_signal(signal.SIGINT)
        child.wait(timeout=30)
        self.assertEqual(leftovers(self.tmp.name), [])


if __name__ == "__main__":
    unittest.main()
