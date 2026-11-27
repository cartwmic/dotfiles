"""tests/support/source_tree.py: the source copy that tests run chezmoi on has no way to reach the network, and leaves the repo alone."""
import os
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_tree  # noqa: E402


def managed(source, home):
    cfg = Path(home) / "chezmoi.yaml"
    cfg.write_text("data:\n  profile: personal\n")
    return subprocess.run(["chezmoi", "--source", str(source), "--config", str(cfg), "--config-format", "yaml", "--destination", str(Path(home) / "dest"), "managed"],
                          capture_output=True, text=True, env=source_tree.chezmoi_env(home), timeout=120)


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
