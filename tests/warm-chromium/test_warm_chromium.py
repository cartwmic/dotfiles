"""scripts/warm-chromium.sh reads Chromium's binary and the data files beside it, and nothing when there is no Chromium.

A fake `cat` in front of PATH records which files the script reads, then reads them for real."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "warm-chromium.sh"
MB = 1024 * 1024


class WarmChromiumTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        install = self.root / "install"
        install.mkdir()
        (install / "chrome").write_bytes(b"x" * 1000)
        (install / "chrome").chmod(0o755)
        (install / "resources.pak").write_bytes(b"x" * (MB + 1))
        (install / "icudtl.dat").write_bytes(b"x" * (MB + 1))
        (install / "v8_context_snapshot.bin").write_bytes(b"x" * 1000)  # under 1 MB, and read on every start
        (install / "notes.txt").write_bytes(b"x" * (MB + 1))
        self.install = install
        (self.root / "bin").mkdir()
        (self.root / "bin" / "chromium").symlink_to(install / "chrome")
        self.log = self.root / "cat.log"
        (self.root / "fake").mkdir()
        fake_cat = self.root / "fake" / "cat"
        fake_cat.write_text('#!/bin/sh\nprintf "%s\\n" "$@" >> "$CAT_LOG"\nexec /bin/cat "$@"\n')
        fake_cat.chmod(0o755)

    def tearDown(self):
        self.tmp.cleanup()

    def warm(self, path_dirs, **env):
        e = {"PATH": ":".join([str(self.root / "fake"), *path_dirs, "/usr/bin", "/bin"]), "CAT_LOG": str(self.log), **env}
        r = subprocess.run([str(SCRIPT)], env=e, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.log.read_text().split() if self.log.exists() else []

    def test_reads_the_binary_and_the_data_files_beside_it(self):
        read = self.warm([str(self.root / "bin")])
        self.assertEqual(sorted(read), sorted(str(self.install / n) for n in ("chrome", "icudtl.dat", "resources.pak", "v8_context_snapshot.bin")))

    def test_shx_chromium_picks_the_chromium(self):
        other = self.root / "other"
        other.mkdir()
        (other / "chrome").write_bytes(b"x" * 10)
        (other / "chrome").chmod(0o755)
        read = self.warm([str(self.root / "bin")], SHX_CHROMIUM=str(other / "chrome"))
        self.assertEqual(read, [str(other / "chrome")])

    def test_no_chromium_reads_nothing_and_succeeds(self):
        self.assertEqual(self.warm([]), [])


if __name__ == "__main__":
    unittest.main()
