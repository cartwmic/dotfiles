"""pnpm's store-dir on /Volumes/Workshop: the two config files, who gets them, and what real pnpm reads from them.

pnpm 11 reads the global config from $XDG_CONFIG_HOME/pnpm/config.yaml when XDG_CONFIG_HOME is set and from
~/Library/Preferences/pnpm/config.yaml when it is not, so both files must say the same thing. The real-pnpm checks run in a
throwaway HOME and skip when pnpm is not installed.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
XDG_FILE = ".config/pnpm/config.yaml"
LIB_FILE = "Library/Preferences/pnpm/config.yaml"
STORE = "/Volumes/Workshop/macbook/pnpm-store"
DARWIN = sys.platform == "darwin"


def managed(profile):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile)
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml",
                            "--destination", str(home), "managed"],
                           capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=120)
    if r.returncode:
        raise AssertionError("chezmoi managed (%s) failed: %s" % (profile, r.stderr))
    return set(r.stdout.split())


class SourceFilesTest(unittest.TestCase):
    def test_both_files_set_the_same_store_on_workshop(self):
        a = (REPO / "dot_config/pnpm/config.yaml").read_text()
        b = (REPO / "Library/Preferences/pnpm/config.yaml").read_text()
        self.assertEqual(a, b)
        self.assertEqual(a, "storeDir: %s\n" % STORE)

    @unittest.skipUnless(DARWIN, "the files are gated to macOS")
    def test_only_personal_macos_gets_them(self):
        self.assertLessEqual({XDG_FILE, LIB_FILE}, managed("personal"))
        self.assertTrue(not ({XDG_FILE, LIB_FILE} & managed("axon-work-computer")))


@unittest.skipUnless(shutil.which("pnpm"), "pnpm is not installed")
class RealPnpmTest(unittest.TestCase):
    def store_path(self, rel, xdg):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            dest = home / rel
            dest.parent.mkdir(parents=True)
            shutil.copy(REPO / ("dot_config/pnpm/config.yaml" if rel == XDG_FILE else LIB_FILE), dest)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("XDG_", "PNPM_", "npm_config_"))}
            env["HOME"] = str(home)
            if xdg:
                env["XDG_CONFIG_HOME"] = str(home / ".config")
            r = subprocess.run(["pnpm", "store", "path"], capture_output=True, text=True, env=env, cwd=tmp, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout.strip()

    @unittest.skipUnless(DARWIN, "the macOS config location")
    def test_pnpm_reads_the_xdg_file_when_xdg_is_set(self):
        self.assertTrue(self.store_path(XDG_FILE, xdg=True).startswith(STORE), "XDG file ignored")

    @unittest.skipUnless(DARWIN, "the macOS config location")
    def test_pnpm_reads_the_library_file_when_xdg_is_unset(self):
        self.assertTrue(self.store_path(LIB_FILE, xdg=False).startswith(STORE), "Library file ignored")


if __name__ == "__main__":
    unittest.main()
