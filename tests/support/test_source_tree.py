"""tests/support/source_tree.py: the source copy that tests run chezmoi on has no way to reach the network, and leaves the repo alone."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_tree  # noqa: E402


OFFLINE = source_tree.REPO / "scripts/ci-offline"


def run_chezmoi(source, home, env):
    cfg = Path(home) / "chezmoi.yaml"
    cfg.write_text("data:\n  profile: personal\n")
    return subprocess.run(["chezmoi", "--source", str(source), "--config", str(cfg), "--config-format", "yaml", "--destination", str(Path(home) / "dest"), "managed"],
                          capture_output=True, text=True, env=env, timeout=120)


def managed(source, home):
    return run_chezmoi(source, home, source_tree.chezmoi_env(home))


class SourceTreeTest(unittest.TestCase):
    def test_no_archive_url_in_the_copy_points_at_the_network_and_the_repo_file_is_unchanged(self):
        copy = (source_tree.source() / source_tree.EXTERNALS).read_text()
        self.assertEqual(re.findall(r'url\s*=\s*"https?://', copy), [])
        self.assertEqual(len(re.findall(r'url = "file://', copy)), len(source_tree.ARCHIVE.findall((source_tree.REPO / source_tree.EXTERNALS).read_text())))
        self.assertIn("https://github.com/", (source_tree.REPO / source_tree.EXTERNALS).read_text())

    def test_chezmoi_reads_the_copy_with_every_connection_refused(self):
        with tempfile.TemporaryDirectory() as home:
            r = managed(source_tree.source(), home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(".local/share/agent-harness/external-skills/pstack/statechart/SKILL.md", r.stdout.split())

    def test_the_real_source_fails_on_the_refused_connection_and_names_the_address(self):
        """The guard: a test that gives chezmoi the repo itself instead of the copy fails on every run, not only when GitHub is down."""
        with tempfile.TemporaryDirectory() as home:
            r = managed(source_tree.REPO, home)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("https://github.com/", r.stderr)

    def test_the_chezmoi_of_the_linux_run_fails_a_test_that_reads_the_real_source_and_passes_one_that_reads_the_copy(self):
        """The guard: scripts/ci-linux.sh puts scripts/ci-offline first on PATH, so a test that forgets the copy fails on every run, whatever its own environment says."""
        env_for = lambda home: {**{k: v for k, v in os.environ.items() if k.upper() not in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")},
                                "HOME": str(home), "PATH": "%s:%s" % (OFFLINE, os.environ["PATH"]), "NO_PROXY": "github.com,127.0.0.1"}
        for source, ok in ((source_tree.REPO, False), (source_tree.source(), True)):
            with tempfile.TemporaryDirectory() as home:
                r = run_chezmoi(source, home, env_for(home))
            if ok:
                self.assertEqual(r.returncode, 0, r.stderr)
            else:
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("https://github.com/", r.stderr)
                self.assertIn("127.0.0.1:1", r.stderr)

    def test_ci_linux_puts_the_offline_chezmoi_first_on_path_and_the_wrapper_runs(self):
        text = (source_tree.REPO / "scripts/ci-linux.sh").read_text()
        path_at = text.index('PATH="$(pwd)/scripts/ci-offline:$PATH"')
        self.assertIn("CI_OFFLINE_REAL_CHEZMOI", text)
        self.assertLess(path_at, text.index("python3 scripts/ci-par.py"), "the guard must be on PATH before the first suite starts")
        self.assertTrue(os.access(OFFLINE / "chezmoi", os.X_OK))

    def test_the_offline_chezmoi_linked_into_a_folder_of_its_own_still_finds_the_real_one_and_still_refuses(self):
        """tests/container-mode links the chezmoi it finds on PATH into a folder that holds nothing else."""
        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / "bin"
            bare.mkdir()
            (bare / "chezmoi").symlink_to(OFFLINE / "chezmoi")
            env = {"PATH": str(bare), "HOME": tmp, "CI_OFFLINE_REAL_CHEZMOI": shutil.which("chezmoi", path=os.environ["PATH"].replace(str(OFFLINE) + ":", ""))}
            ok = subprocess.run([str(bare / "chezmoi"), "--version"], capture_output=True, text=True, env=env)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertIn("chezmoi version", ok.stdout)
            bad = run_chezmoi(source_tree.REPO, tmp, {**env, "PATH": str(bare)})
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("127.0.0.1:1", bad.stderr)

    def test_the_offline_chezmoi_says_so_when_there_is_no_chezmoi_behind_it(self):
        r = subprocess.run([str(OFFLINE / "chezmoi"), "--version"], capture_output=True, text=True, env={"PATH": str(OFFLINE) + ":/nonexistent"})
        self.assertEqual(r.returncode, 127)
        self.assertIn("no chezmoi on PATH", r.stderr)

    def test_an_include_pattern_of_an_unknown_shape_is_refused_by_name(self):
        with self.assertRaisesRegex(AssertionError, "cannot build an archive"):
            source_tree._stand_in_archive("skills/**")

    def test_env_drops_proxy_exemptions_and_keeps_the_rest(self):
        with unittest.mock.patch.dict(os.environ, {"NO_PROXY": "github.com", "HTTPS_PROXY": "http://elsewhere", "KEEP_ME": "1"}):
            env = source_tree.chezmoi_env("/h")
        self.assertNotIn("NO_PROXY", env)
        self.assertEqual((env["HOME"], env["HTTPS_PROXY"], env["KEEP_ME"]), ("/h", "http://127.0.0.1:1", "1"))


if __name__ == "__main__":
    unittest.main()
