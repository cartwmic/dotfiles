"""The Windows install files under windows/ have rows in docs/profiles.md, and chezmoi never deploys them.

chezmoi does not manage these files (they are the source of a script run by hand on the G14), so test_coverage.py skips
rows flagged "(Windows)". This test checks them instead: every file under windows/ has its own row (the exact file, not a
folder row) that names its profile and gives a reason, every row names one path and it is an existing file, and no system or
profile gets anything under windows/ from chezmoi. The checks are plain functions, tried on made-up inputs first so a broken check cannot pass by finding nothing,
then run on the real tree. The old Linux row for agent-desktop is one row, not two.
Run: python3 -m unittest discover -s tests/profiles -p 'test_windows_rows.py'
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_coverage import DOC, PROFILES, covers
import source_tree  # noqa: E402  (test_coverage has put tests/support on the path)

REPO = Path(__file__).resolve().parents[2]
SYSTEMS = ("linux", "darwin", "windows")


def windows_rows(text):
    """(paths, profile, reason) for each coverage-table row flagged "(Windows)" in the text of docs/profiles.md."""
    out = []
    for line in text.split("\n## Local data keys")[0].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) != 3 or not cells[0].startswith("`") or "(Windows)" not in cells[1]:
            continue
        out.append(([c for c in cells[0].replace("`", "").split(", ")], cells[1].split()[0], cells[2]))
    return out


def files_without_a_row(files, rows):
    """Files with no row of their own. A row for a folder does not cover the files under it."""
    named = {p for paths, _, _ in rows for p in paths}
    return sorted(f for f in files if f not in named)


def rows_for_missing_paths(rows, is_file):
    """Paths named by a row that are not an existing file (gone, or a folder)."""
    return sorted(p for paths, _, _ in rows for p in paths if not is_file(p))


def rows_naming_more_than_one_path(rows):
    return sorted(", ".join(paths) for paths, _, _ in rows if len(paths) != 1)


def deployed_windows_paths(managed):
    return sorted(p for p in managed if p == "windows" or p.startswith("windows/"))


def chezmoi_managed(source, system, profile):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile)
        override = json.dumps({"profile": profile, "chezmoi": {"os": system}})
        r = subprocess.run(["chezmoi", "--source", str(source), "--config", str(cfg), "--config-format", "yaml",
                            "--destination", str(home), "--override-data", override, "managed"],
                           capture_output=True, text=True, env=source_tree.chezmoi_env(home), timeout=120)
    if r.returncode:
        raise AssertionError("chezmoi managed (%s, %s) failed: %s" % (system, profile, r.stderr))
    return set(r.stdout.split())


SAMPLE = """| Path or feature | Profiles | Reason the other profile is left out |
|---|---|---|
| `windows/a.ps1` | personal (Windows) | The work profile has no Windows machine. |
| `.local/bin/agent-desktop` | personal (Linux) | Omarchy only. |

## Local data keys
| `windows/ignored.ps1` | personal (Windows) | after the table, so not read |
"""


class CheckLogicTest(unittest.TestCase):
    def test_windows_rows_reads_only_flagged_rows_before_the_local_data_keys(self):
        self.assertEqual(windows_rows(SAMPLE), [(["windows/a.ps1"], "personal", "The work profile has no Windows machine.")])

    def test_a_file_with_no_row_is_found(self):
        rows = [(["windows/install.ps1"], "personal", "x")]
        self.assertEqual(files_without_a_row(["windows/install.ps1", "windows/extra.ps1"], rows), ["windows/extra.ps1"])

    def test_a_folder_row_does_not_cover_the_files_under_it(self):
        self.assertEqual(files_without_a_row(["windows/a.ps1", "windows/b.cmd"], [(["windows"], "personal", "x")]),
                         ["windows/a.ps1", "windows/b.cmd"])

    def test_a_row_for_a_folder_is_found(self):
        rows = [(["windows"], "personal", "x"), (["windows/a.ps1"], "personal", "x")]
        self.assertEqual(rows_for_missing_paths(rows, lambda p: p == "windows/a.ps1"), ["windows"])

    def test_a_row_naming_two_paths_is_found(self):
        rows = [(["windows/a.ps1", "windows/b.cmd"], "personal", "x"), (["windows/c.ps1"], "personal", "x")]
        self.assertEqual(rows_naming_more_than_one_path(rows), ["windows/a.ps1, windows/b.cmd"])

    def test_a_row_for_a_gone_file_is_found(self):
        rows = [(["windows/install.ps1", "windows/gone.ps1"], "personal", "x")]
        self.assertEqual(rows_for_missing_paths(rows, lambda p: p != "windows/gone.ps1"), ["windows/gone.ps1"])

    def test_a_deployed_windows_path_is_found(self):
        self.assertEqual(deployed_windows_paths({".zshrc", "windows/install.ps1", "windowsfoo"}), ["windows/install.ps1"])

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
    def test_the_chezmoi_check_sees_a_leak_when_nothing_ignores_the_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src"
            (src / "windows").mkdir(parents=True)
            (src / "windows" / "install.ps1").write_text("")
            self.assertEqual(deployed_windows_paths(chezmoi_managed(src, "windows", "personal")), ["windows", "windows/install.ps1"])


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
class RealTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = DOC.read_text()
        cls.rows = windows_rows(cls.text)
        cls.files = sorted(str(p.relative_to(REPO)) for p in (REPO / "windows").rglob("*") if p.is_file()) if (REPO / "windows").is_dir() else []

    def test_the_windows_folder_exists_and_has_a_windows_row(self):
        self.assertTrue(self.files, "windows/ must exist and hold files")
        self.assertTrue(self.rows, "docs/profiles.md has no row flagged (Windows)")

    def test_every_file_under_windows_has_a_row(self):
        self.assertEqual(files_without_a_row(self.files, self.rows), [])

    def test_every_windows_row_names_one_path_and_it_is_an_existing_file(self):
        self.assertEqual(rows_naming_more_than_one_path(self.rows), [])
        self.assertEqual(rows_for_missing_paths(self.rows, lambda p: (REPO / p).is_file()), [])

    def test_every_windows_row_names_its_profile_and_why_the_other_is_left_out(self):
        for paths, profile, reason in self.rows:
            self.assertIn(profile, PROFILES, paths)
            self.assertGreater(len(reason.split()), 5, paths)
            other = [p for p in PROFILES if p != profile][0]
            self.assertTrue("work profile" in reason or other in reason, "row %s must say why the %s profile is left out" % (paths, other))

    def test_chezmoi_deploys_nothing_under_windows_on_any_system_or_profile(self):
        for system in SYSTEMS:
            for profile in PROFILES:
                self.assertEqual(deployed_windows_paths(chezmoi_managed(source_tree.source(), system, profile)), [], (system, profile))

    def test_the_agent_desktop_linux_row_is_one_row_and_points_at_the_doc(self):
        lines = [l for l in self.text.splitlines() if l.startswith("| `.local/bin/agent-desktop`")]
        self.assertEqual(len(lines), 1)
        self.assertIn("docs/agent-desktop.md", lines[0])


if __name__ == "__main__":
    unittest.main()
