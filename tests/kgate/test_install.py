"""The cached `npm ci` (profile [install] npm = true): INSTALL_SH, the script the pod puts first on PATH as `npm`.

The script runs for real here with a fake `npm` and `node` behind it (the fake npm counts its calls and writes a node_modules), so each test reads what the
wrapper did from outside: which real npm calls were made, what is in node_modules, what is on the node cache, and the result line the pod side reads.
The pod side and the job record are in test_kgate.py (PodSh, Black).
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_kgate  # noqa: E402  (renders and loads kgate)

K = test_kgate.K
FAKE_NPM, FAKE_NODE = test_kgate.FAKE_NPM, test_kgate.FAKE_NODE

class CachedNpmCi(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ki-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.real, self.wrap = self.tmp / "real", self.tmp / "wrap"
        for d in (self.real, self.wrap):
            d.mkdir()
        for name, text in (("npm", FAKE_NPM), ("node", FAKE_NODE)):
            (self.real / name).write_text(text)
            (self.real / name).chmod(0o755)
        (self.wrap / "npm").write_text(K.INSTALL_SH)
        (self.wrap / "npm").chmod(0o755)
        self.log = self.tmp / "npm.log"
        self.result = self.tmp / "install.result"
        self.result.write_text("")
        self.root = self.tmp / "tree"
        self.repo_cache = self.tmp / "cache" / "u1000" / "nm" / "alert-steward"
        self.project(self.root)

    def project(self, path, lock="lock v1"):
        path.mkdir(parents=True, exist_ok=True)
        (path / "package.json").write_text('{"name": "x"}\n')
        (path / "package-lock.json").write_text(lock)

    def npm(self, *args, cwd=None, cache=None, env=None):
        e = {**os.environ, "PATH": "%s:%s:%s" % (self.wrap, self.real, os.environ["PATH"]), "FAKE_LOG": str(self.log), "KGATE_INSTALL_BIN": str(self.wrap),
             "KGATE_INSTALL_ROOT": str(self.root), "KGATE_INSTALL_DIR": str(cache or self.repo_cache), "KGATE_INSTALL_RESULT": str(self.result), "TMPDIR": str(self.tmp), **(env or {})}
        return subprocess.run(["npm", *args], cwd=cwd or self.root, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)

    def calls(self, word):
        return [l for l in (self.log.read_text().splitlines() if self.log.exists() else []) if l.startswith("npm " + word)]

    def rows(self):
        return [l.split()[0] for l in self.result.read_text().splitlines()]

    def test_the_first_npm_ci_installs_and_keeps_the_result_and_the_second_unpacks_it(self):
        first = self.npm("ci")
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertIn("kgate-install: miss", first.stdout)
        self.assertEqual(len(self.calls("ci --prefer-offline --no-audit --no-fund")), 1)
        self.assertEqual(len(list(self.repo_cache.glob("*.tar"))), 1)
        shutil.rmtree(self.root / "node_modules")
        second = self.npm("ci")
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertIn("kgate-install: hit", second.stdout)
        self.assertEqual(len(self.calls("ci")), 1, "the second npm ci was served from the cache: the real npm ci ran once")
        self.assertEqual((self.root / "node_modules" / "pkg" / "index.js").read_text(), "built by npm ci\n")
        self.assertFalse((self.root / "node_modules" / ".kgate-install-done").exists())
        self.assertEqual(self.rows(), ["miss", "hit"])
        for line in self.result.read_text().splitlines():
            self.assertRegex(line, r"^(hit|miss) [0-9]+(\.[0-9])?$")

    def test_a_changed_lock_file_is_a_miss(self):
        self.npm("ci")
        (self.root / "package-lock.json").write_text("lock v2")
        self.npm("ci")
        self.assertEqual(self.rows(), ["miss", "miss"])
        self.assertEqual(len(list(self.repo_cache.glob("*.tar"))), 2)

    def test_arguments_after_ci_are_part_of_the_key_and_reach_npm(self):
        self.npm("ci")
        self.npm("ci", "--omit=dev")
        self.assertEqual(self.rows(), ["miss", "miss"])
        self.assertTrue(any("--omit=dev" in l for l in self.calls("ci")))

    def test_a_damaged_tar_is_removed_and_the_install_runs_for_real(self):
        self.npm("ci")
        tar = next(self.repo_cache.glob("*.tar"))
        tar.write_bytes(tar.read_bytes()[:700])   # cut: the marker, added last, is gone
        done = self.npm("ci")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("did not unpack", done.stdout)
        self.assertEqual(self.rows(), ["miss", "miss"])
        self.assertEqual(len(self.calls("ci")), 2)
        self.assertEqual((self.root / "node_modules" / "pkg" / "index.js").read_text(), "built by npm ci\n")
        self.assertEqual(self.npm("ci").returncode, 0)
        self.assertEqual(self.rows()[-1], "hit", "the rebuilt tar is used by the next one")

    def test_a_failed_install_fails_the_command_and_keeps_nothing(self):
        done = self.npm("ci", env={"FAKE_NPM_FAIL": "1"})
        self.assertEqual(done.returncode, 1)
        self.assertIn("npm error broke", done.stdout)
        self.assertEqual(list(self.repo_cache.glob("*.tar")), [])
        self.assertEqual(self.rows(), [])

    def test_every_other_npm_command_goes_straight_to_the_real_npm(self):
        done = self.npm("run", "typecheck")
        self.assertEqual((done.returncode, done.stdout), (0, "ran npm run typecheck\n"))
        self.assertEqual(self.rows(), [])
        self.assertFalse(self.repo_cache.exists())
        self.assertEqual(self.npm("-v").stdout, "11.0.0\n")

    def test_outside_the_shipped_tree_or_without_a_lock_file_npm_ci_runs_as_typed(self):
        other = self.tmp / "elsewhere"
        self.project(other)
        self.assertEqual(self.npm("ci", cwd=other).returncode, 0)
        (self.root / "package-lock.json").unlink()
        self.assertEqual(self.npm("ci").returncode, 0)
        self.assertEqual(self.rows(), [])
        self.assertEqual(len(self.calls("ci")), 2)
        self.assertTrue(all(l == "npm ci" for l in self.calls("ci")), "plain npm ci, no cache flags")
        self.assertFalse(self.repo_cache.exists())

    def test_no_cache_folder_means_npm_ci_as_typed(self):
        done = self.npm("ci", env={"KGATE_INSTALL_DIR": ""})
        self.assertEqual((done.returncode, self.rows()), (0, []))
        self.assertEqual(self.calls("ci"), ["npm ci"])

    def test_a_clone_in_another_folder_hits_the_same_repo_cache(self):
        self.npm("ci")
        elsewhere = self.tmp / "other-clone"
        self.project(elsewhere)
        done = self.npm("ci", cwd=elsewhere, env={"KGATE_INSTALL_ROOT": str(elsewhere)})
        self.assertIn("kgate-install: hit", done.stdout)
        self.assertEqual(len(self.calls("ci")), 1)

    def test_each_repo_keeps_its_own_two_newest_keys(self):
        mine, theirs = self.repo_cache, self.repo_cache.parent / "budget-steward"
        theirs.mkdir(parents=True)
        (theirs / "aaaaaaaaaaaaaaaa.tar").write_bytes(b"x")
        for n in range(3):
            (self.root / "package-lock.json").write_text("lock v%d" % n)
            self.npm("ci")
            for i, t in enumerate(sorted(mine.glob("*.tar"), key=lambda p: p.stat().st_mtime)):
                os.utime(t, (1000 + n * 10 + i, 1000 + n * 10 + i))   # a clear order: mtimes are close together in a fast test
        self.assertEqual(len(list(mine.glob("*.tar"))), 2)
        self.assertEqual([p.name for p in theirs.glob("*.tar")], ["aaaaaaaaaaaaaaaa.tar"], "another repo's folder is not pruned by this repo's installs")

    def test_the_real_npm_and_what_it_starts_never_meet_the_wrapper_again(self):
        (self.real / "npm").write_text('#!/bin/sh\ncommand -v npm > "$FAKE_SEEN"\n')
        self.npm("run", "x", env={"FAKE_SEEN": str(self.tmp / "seen")})
        self.assertEqual((self.tmp / "seen").read_text().strip(), str(self.real / "npm"))

    def test_the_two_pod_sides_agree_on_the_result_lines(self):
        path = self.tmp / "r"
        for text, want in (("", "none 0.0"), ("hit 3.1\n", "hit 3.1"), ("miss 24.2\nhit 3.0\n", "miss 27.2"), ("garbage\n", "none 0.0")):
            path.write_text(text)
            self.assertEqual(K.install_result(str(path)), want)
        self.assertEqual(K.install_result(None), "none 0.0")


class InstallProfile(unittest.TestCase):
    def test_install_npm_parses_and_is_off_without_the_table(self):
        self.assertEqual(K.parse_profile("[install]\nnpm = true\n")["install"], {"npm": True})
        self.assertEqual(K.parse_profile("")["install"], {"npm": False})

    def test_anything_else_in_the_table_is_refused(self):
        for bad in ('[install]\nnpm = "yes"\n', "[install]\nyarn = true\n", '[install]\npip = "requirements.txt"\n', "install = 1\n"):
            with self.assertRaises(K.Unavailable, msg=bad):
                K.parse_profile(bad)


if __name__ == "__main__":
    unittest.main()
