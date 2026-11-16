"""agent-download: the real script against a scratch download folder and a scratch HOME (its marks and log go under the scratch XDG_STATE_HOME).
A background thread plays Chrome: it writes `.crdownload` files and renames them, the way a download lands."""
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/bin/executable_agent-download"


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="agent-download-test-")
        self.root = Path(self.tmp.name)
        self.dl = self.root / "Downloads"
        self.dl.mkdir()
        self.state = self.root / "state"
        self.env = {"PATH": os.environ["PATH"], "HOME": str(self.root), "XDG_STATE_HOME": str(self.state), "AGENT_DOWNLOAD_DIR": str(self.dl)}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, timeout=30, env=None):
        return subprocess.run(["sh", str(SCRIPT), *args], env=env or self.env, capture_output=True, text=True, timeout=timeout)

    def mark(self):
        r = self.run_cli("mark")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def test_a_file_that_was_there_before_the_mark_is_ignored_and_a_new_one_is_returned(self):
        (self.dl / "old.zip").write_bytes(b"old")
        mark = self.mark()
        (self.dl / "new.zip").write_bytes(b"new!")
        r = self.run_cli("wait", "--mark", mark, "--timeout", "10")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, str(self.dl / "new.zip")), r.stderr)

    def test_only_the_old_file_means_timeout_exit_1_that_names_the_folder(self):
        (self.dl / "old.zip").write_bytes(b"old")
        mark = self.mark()
        r = self.run_cli("wait", "--mark", mark, "--timeout", "1")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("no new file in %s within 1s" % self.dl, r.stderr)

    def test_a_file_with_the_same_name_but_a_new_size_counts_as_new(self):   # the same download saved over an older one
        (self.dl / "a.zip").write_bytes(b"1")
        mark = self.mark()
        (self.dl / "a.zip").write_bytes(b"12345")
        r = self.run_cli("wait", "--mark", mark, "--timeout", "10")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, str(self.dl / "a.zip")), r.stderr)

    def test_a_crdownload_is_not_returned_until_it_is_renamed(self):
        mark = self.mark()
        (self.dl / "x.zip.crdownload").write_bytes(b"part")
        (self.dl / "x.zip").write_bytes(b"half")   # Chrome has a sibling .crdownload while it still writes

        def finish():
            time.sleep(1.5)
            (self.dl / "x.zip.crdownload").unlink()
        threading.Thread(target=finish).start()
        start = time.time()
        r = self.run_cli("wait", "--mark", mark, "--timeout", "15")
        self.assertEqual((r.returncode, r.stdout.strip()), (0, str(self.dl / "x.zip")), r.stderr)
        self.assertGreaterEqual(time.time() - start, 1.4, "returned before the .crdownload was gone")

    def test_a_file_still_growing_is_not_returned_until_its_size_settles(self):
        mark = self.mark()
        path = self.dl / "big.zip"
        path.write_bytes(b"a")
        grown = []

        def grow():
            for _ in range(6):
                time.sleep(0.3)
                with open(path, "ab") as f:
                    f.write(b"b")
                grown.append(1)
        t = threading.Thread(target=grow)
        t.start()
        r = self.run_cli("wait", "--mark", mark, "--timeout", "15")
        done = len(grown)   # before join: how far the download had got when wait answered
        t.join()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(done, 6, "returned while the file was still growing")

    def test_hidden_and_part_files_are_not_returned(self):
        mark = self.mark()
        (self.dl / ".com.google.Chrome.abc123").write_bytes(b"tmp")
        (self.dl / "y.zip.part").write_bytes(b"tmp")
        r = self.run_cli("wait", "--mark", mark, "--timeout", "1")
        self.assertEqual(r.returncode, 1, r.stdout)

    def test_two_marks_keep_separate_handles(self):
        first = self.mark()
        (self.dl / "one.zip").write_bytes(b"1")
        second = self.mark()   # taken after one.zip landed
        self.assertNotEqual(first, second)
        self.assertEqual(self.run_cli("wait", "--mark", first, "--timeout", "10").stdout.strip(), str(self.dl / "one.zip"))
        self.assertEqual(self.run_cli("wait", "--mark", second, "--timeout", "1").returncode, 1)   # for this mark one.zip is old

    def test_marks_live_outside_the_download_folder_and_a_day_old_mark_is_deleted(self):
        old = self.mark()
        self.assertFalse(Path(old).is_relative_to(self.dl))
        two_days = time.time() - 2 * 86400
        os.utime(old, (two_days, two_days))
        fresh = self.mark()
        self.assertFalse(Path(old).exists())
        self.assertTrue(Path(fresh).exists())

    def test_no_mark_or_an_unreadable_mark_exits_2_and_names_the_fix(self):
        for args in (("wait",), ("wait", "--mark", str(self.root / "nope"))):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("run agent-download mark before the click and pass its path", r.stderr)

    def test_the_wait_uses_the_folder_recorded_at_the_mark(self):
        other = self.root / "Elsewhere"
        other.mkdir()
        env = dict(self.env, AGENT_DOWNLOAD_DIR=str(other))
        mark = self.run_cli("mark", env=env).stdout.strip()
        (other / "z.zip").write_bytes(b"z")
        waiting = {k: v for k, v in self.env.items() if k != "AGENT_DOWNLOAD_DIR"}   # no folder given to wait
        r = self.run_cli("wait", "--mark", mark, "--timeout", "10", env=dict(waiting, HOME=str(self.root / "nohome")))
        self.assertEqual((r.returncode, r.stdout.strip()), (0, str(other / "z.zip")), r.stderr)

    def test_the_log_has_one_line_per_call_and_never_the_file_contents(self):
        mark = self.mark()
        (self.dl / "secret.zip").write_bytes(b"TOP-SECRET-CONTENT")
        self.run_cli("wait", "--mark", mark, "--timeout", "10")
        log = (self.state / "agent-download/agent-download.log").read_text().splitlines()
        self.assertEqual(len(log), 2)
        self.assertIn("marked", log[0])
        self.assertIn("found", log[1])
        self.assertIn("file=secret.zip", log[1])
        self.assertNotIn("TOP-SECRET", "".join(log))
        self.assertRegex(log[1], r"^\d{4}-\d\d-\d\dT[\d:]+Z run=\S+ elapsed=\d+s wait found dir=")


if __name__ == "__main__":
    unittest.main()
