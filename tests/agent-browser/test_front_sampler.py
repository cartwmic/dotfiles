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
    print(open(os.environ["FAKE_FRONT_FILE"]).read().strip())
elif args[:3] == ["info", "-only", "name"]:
    print('"LSDisplayName"="Fake App %%s"' %% args[3])
""" % sys.executable

A, B = "ASN:0x0-0x1-0xA:", "ASN:0x0-0x1-0xB:"


class FrontSamplerUnit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="front-sampler-test-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.front_file = self.root / "front"
        self.front_file.write_text(A)
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

    def test_a_blip_that_comes_back_is_caught_and_timed(self):
        """The front blips to another app for well under a second and comes back: a before/after check
        would see the baseline both times; the sampler must catch the blip, name the app and time it."""
        sampler = FrontSampler(interval=0.02)
        sampler.start()
        self.addCleanup(sampler.stop)
        time.sleep(0.15)                 # a few samples on the baseline
        self.front_file.write_text(B)    # the blip
        time.sleep(0.4)
        self.front_file.write_text(A)    # back to the baseline
        time.sleep(0.15)
        sampler.stop()
        excursions = sampler.excursions()
        self.assertEqual(len(excursions), 1, excursions)
        e = excursions[0]
        self.assertEqual(e["to"], B)
        self.assertEqual(e["to_name"], "Fake App " + B)
        self.assertIsNotNone(e["end"])   # it came back
        duration = e["end"] - e["start"]
        self.assertGreaterEqual(duration, 0.2)   # the sampler saw it away for at least this long
        self.assertLess(duration, 1.0)   # a 0.4 s blip; the macOS runner read it as 0.68 s, so 1.0 s keeps margin
        # and it is reported, with when it happened and how long it lasted
        message = sampler.describe()
        self.assertIn("Fake App " + B, message)
        self.assertIn("for", message)
        with self.assertRaises(AssertionError):
            sampler.assert_unchanged("the blip")

    def test_a_front_that_never_comes_back_fails_the_assert(self):
        """The front leaves the baseline and never returns (the old launcher keeps it, or a setfront does
        nothing): the assert must fail while the change is still open, without waiting for stop() to
        close it, and name the app and when it started."""
        sampler = FrontSampler(interval=0.02)
        sampler.start()
        self.addCleanup(sampler.stop)
        time.sleep(0.15)                 # a few samples on the baseline
        self.front_file.write_text(B)    # the front leaves and never comes back
        time.sleep(0.3)
        with self.assertRaises(AssertionError) as caught:
            sampler.assert_unchanged("the steal")   # asserted while the front is still away
        message = str(caught.exception)
        self.assertIn("Fake App " + B, message)
        self.assertIn("still away", message)
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
        time.sleep(0.2)
        sampler.stop()
        self.assertEqual(sampler.excursions(), [])
        sampler.assert_unchanged("quiet")   # must not raise


if __name__ == "__main__":
    unittest.main()
