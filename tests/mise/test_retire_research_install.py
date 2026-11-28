"""Script 69 removes the mise install of the retired `research` program and nothing else.

The real script runs in a scratch HOME with a fake mise data directory (no mise, no network). Each case builds the directory
tree mise leaves behind: versions, the version links that mise adds, the download cache and the shim.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "run_once_after_69_retire_research_mise_install.sh"
KEPT = ("loop-engine", "lean-change", "policy-document", "bookends-check")


def build(data, research_versions=(), dangling_only=False, downloads=False, shim=False):
    """A mise data directory: the four kept Loop Engine tools, plus `research` as the arguments say."""
    for tool in KEPT:
        (data / "installs" / tool / "0.72.0").mkdir(parents=True)
        (data / "installs" / tool / "0.72.0" / tool).write_text("binary\n")
        (data / "installs" / tool / "latest").symlink_to("./0.72.0")
        (data / "downloads" / tool).mkdir(parents=True)
        (data / "shims").mkdir(exist_ok=True)
        (data / "shims" / tool).write_text("shim\n")
    research = data / "installs" / "research"
    if research_versions or dangling_only:
        research.mkdir(parents=True)
    for version in research_versions:
        (research / version).mkdir()
        (research / version / "research").write_text("binary\n")
    if dangling_only:   # what `mise uninstall` leaves: the version links without their targets
        (research / "0.71").symlink_to("./0.71.2")
        (research / "latest").symlink_to("./0.71.2")
    elif research_versions:
        (research / "latest").symlink_to("./" + research_versions[-1])
    if downloads:
        (data / "downloads" / "research").mkdir(parents=True)
        (data / "downloads" / "research" / "0.71.2.tar.gz").write_text("archive\n")
    if shim:
        (data / "shims").mkdir(exist_ok=True)
        (data / "shims" / "research").write_text("shim\n")


def run(home, **env):
    base = {"PATH": "/usr/bin:/bin", "HOME": str(home)}
    base.update(env)
    return subprocess.run(["sh", str(SCRIPT)], env=base, capture_output=True, text=True)


def snapshot(data):
    """Every path under the data directory, links included, as a sorted list."""
    return sorted(str(p.relative_to(data)) for p in data.rglob("*"))


class RetireResearchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        self.data = self.home / ".local/share/mise"

    def kept_tools_intact(self):
        for tool in KEPT:
            self.assertTrue((self.data / "installs" / tool / "0.72.0" / tool).is_file(), tool)
            self.assertTrue((self.data / "installs" / tool / "latest").is_symlink(), tool)
            self.assertTrue((self.data / "downloads" / tool).is_dir(), tool)
            self.assertTrue((self.data / "shims" / tool).is_file(), tool)

    def test_removes_every_installed_version_the_download_cache_and_the_shim(self):
        build(self.data, research_versions=("0.70.2", "0.71.2", "0.72.0"), downloads=True, shim=True)
        r = run(self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse((self.data / "installs" / "research").exists())
        self.assertFalse((self.data / "downloads" / "research").exists())
        self.assertFalse((self.data / "shims" / "research").exists())
        self.kept_tools_intact()
        self.assertEqual(r.stderr, "")
        self.assertIn("[retire_research_mise_install] INFO: removed the retired research install (versions: 0.70.2 0.71.2 0.72.0)", r.stdout)

    def test_removes_the_links_mise_leaves_after_an_uninstall(self):
        build(self.data, dangling_only=True, shim=True)
        r = run(self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.lexists(self.data / "installs" / "research"))
        self.assertFalse(os.path.lexists(self.data / "shims" / "research"))
        self.kept_tools_intact()
        self.assertIn("removed the retired research install from", r.stdout)

    def test_does_nothing_quietly_when_research_is_not_installed(self):
        build(self.data)
        before = snapshot(self.data)
        r = run(self.home)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertEqual(snapshot(self.data), before)

    def test_does_nothing_quietly_with_no_mise_data_directory(self):
        r = run(self.home)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertFalse(self.data.exists())

    def test_a_second_run_finds_nothing_and_says_nothing(self):
        build(self.data, research_versions=("0.71.2",))
        self.assertIn("removed", run(self.home).stdout)
        again = run(self.home)
        self.assertEqual((again.returncode, again.stdout, again.stderr), (0, "", ""))

    def test_follows_mise_data_dir_and_xdg_data_home(self):
        elsewhere = self.home / "elsewhere"
        build(elsewhere, research_versions=("0.71.2",))
        build(self.data, research_versions=("0.71.2",))   # the default location is left alone when MISE_DATA_DIR names another
        self.assertEqual(run(self.home, MISE_DATA_DIR=str(elsewhere)).returncode, 0)
        self.assertFalse((elsewhere / "installs" / "research").exists())
        self.assertTrue((self.data / "installs" / "research" / "0.71.2").is_dir())
        xdg = self.home / "xdg"
        build(xdg / "mise", research_versions=("0.71.2",))
        self.assertEqual(run(self.home, XDG_DATA_HOME=str(xdg)).returncode, 0)
        self.assertFalse((xdg / "mise" / "installs" / "research").exists())
        self.assertTrue((self.data / "installs" / "research" / "0.71.2").is_dir())


if __name__ == "__main__":
    unittest.main()
