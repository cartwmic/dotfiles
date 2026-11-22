"""Unit test for FrontSampler with a fake lsappinfo: a front that blips to another app and comes back must
be caught, with when it happened and how long it lasted. Never runs a real lsappinfo."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from front_sampler import FrontSampler

FAKE_LSAPPINFO = """#!%s
import os, sys
args = sys.argv[1:]
if args == ["front"]:
    value = open(os.environ["FAKE_FRONT_FILE"]).read().strip()
    with open(os.environ["FAKE_FRONT_LOG"], "a") as log:   # one line per read, so a test can tell the sampler has looked
        log.write(value + "\\n")
    print(value)
elif args[:3] == ["info", "-only", "name"]:
    print('"LSDisplayName"="Fake App %%s"' %% args[3])
""" % sys.executable

A, B = "ASN:0x0-0x1-0xA:", "ASN:0x0-0x1-0xB:"
WAIT = 5.0   # generous deadline for the sampler to see a state; a poll returns as soon as it does


class FrontSamplerUnit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="front-sampler-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.front_file = self.root / "front"
        self.front_log = self.root / "front.log"
        self.front_log.touch()
        self.set_front(A)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        tool = self.bin / "lsappinfo"
        tool.write_text(FAKE_LSAPPINFO)
        tool.chmod(0o755)
        old_path = os.environ["PATH"]
        os.environ["PATH"] = str(self.bin) + os.pathsep + old_path
        self.addCleanup(os.environ.__setitem__, "PATH", old_path)
        os.environ["FAKE_FRONT_FILE"] = str(self.front_file)   # the fake lsappinfo subprocesses read this
        self.addCleanup(os.environ.pop, "FAKE_FRONT_FILE")
        os.environ["FAKE_FRONT_LOG"] = str(self.front_log)
        self.addCleanup(os.environ.pop, "FAKE_FRONT_LOG")

    def set_front(self, asn):
        """Switch the fake front app atomically: the sampler's lsappinfo subprocess reads the file at any moment,
        so it must never see it truncated or half-written. A temp file in the same folder, then a rename."""
        tmp = self.root / "front.tmp"
        tmp.write_text(asn)
        os.replace(tmp, self.front_file)

    def wait_for(self, what, condition):
        """Poll until condition() is true, up to WAIT seconds; fail naming what never happened."""
        deadline = time.monotonic() + WAIT
        while not condition():
            if time.monotonic() > deadline:
                self.fail("the sampler did not %s within %.0f s" % (what, WAIT))
            time.sleep(0.01)

    def wait_for_reads(self, count):
        """Wait until the fake lsappinfo has answered `front` at least `count` times (the baseline read in start() counts)."""
        self.wait_for("read the front %d times" % count,
                      lambda: len(self.front_log.read_text().splitlines()) >= count)

    def test_a_blip_that_comes_back_is_caught_and_timed(self):
        """The front blips to another app for well under a second and comes back: a before/after check
        would see the baseline both times; the sampler must catch the blip, name the app and time it."""
        sampler = FrontSampler(interval=0.02)
        sampler.start()
        self.addCleanup(sampler.stop)
        self.wait_for_reads(4)           # a few samples on the baseline
        self.set_front(B)                # the blip
        self.wait_for("see the front leave", lambda: sampler.excursions())
        time.sleep(0.4)                  # hold the blip: the sampler saw it start before this, so it lasts at least this long
        self.set_front(A)                # back to the baseline
        self.wait_for("see the front come back", lambda: all(e["end"] is not None for e in sampler.excursions()))
        sampler.stop()
        excursions = sampler.excursions()
        self.assertEqual(len(excursions), 1, excursions)
        e = excursions[0]
        self.assertEqual(e["to"], B)
        self.assertEqual(e["to_name"], "Fake App " + B)
        self.assertIsNotNone(e["end"])   # it came back
        duration = e["end"] - e["start"]
        self.assertGreaterEqual(duration, 0.4)   # held for 0.4 s after the sampler saw it start, so it was timed at least that
        # no upper bound: on a loaded runner the sampler may notice the return arbitrarily late
        # and it is reported, with when it happened and how long it lasted
        message = sampler.describe()
        self.assertIn("Fake App " + B, message)
        self.assertIn("for", message)
        with self.assertRaises(AssertionError):
            sampler.assert_unchanged("the blip")
        sampler.assert_returned("the blip")   # it came back, so the weaker check passes

    def test_a_front_that_never_comes_back_fails_the_assert(self):
        """The front leaves the baseline and never returns (the old launcher keeps it, or a setfront does
        nothing): the assert must fail while the change is still open, without waiting for stop() to
        close it, and name the app and when it started."""
        sampler = FrontSampler(interval=0.02)
        sampler.start()
        self.addCleanup(sampler.stop)
        self.wait_for_reads(4)           # a few samples on the baseline
        self.set_front(B)                # the front leaves and never comes back
        self.wait_for("see the front leave", lambda: sampler.excursions())
        with self.assertRaises(AssertionError) as caught:
            sampler.assert_unchanged("the steal")   # asserted while the front is still away
        message = str(caught.exception)
        self.assertIn("Fake App " + B, message)
        self.assertIn("still away", message)
        with self.assertRaises(AssertionError) as caught:
            sampler.assert_returned("the steal")
        self.assertIn("left the frontmost app away", str(caught.exception))
        sampler.stop()
        # and the open change survives stop() as a recorded excursion with no end
        excursions = sampler.excursions()
        self.assertEqual(len(excursions), 1, excursions)
        self.assertEqual(excursions[0]["to"], B)
        self.assertIsNone(excursions[0]["end"])

    def test_no_change_means_no_excursions(self):
        sampler = FrontSampler(interval=0.02)
        sampler.start()
        self.addCleanup(sampler.stop)
        self.wait_for_reads(6)           # several samples, all on the baseline
        sampler.stop()
        self.assertEqual(sampler.excursions(), [])
        sampler.assert_unchanged("quiet")   # must not raise


if __name__ == "__main__":
    unittest.main()
