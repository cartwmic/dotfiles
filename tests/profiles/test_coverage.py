"""Every path that lands on one desktop profile only has a row in docs/profiles.md, and every row is still one-profile.

Runs `chezmoi managed` against the real source for personal and axon-work-computer with a minimal config
(no read-source-state hook, no secrets) and a throwaway HOME. Gates that also need darwin only show up on macOS;
rows marked "(macOS)" are skipped elsewhere.
"""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs/profiles.md"
PROFILES = ("personal", "axon-work-computer")
NEEDED = "reason needed (owner)"
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


def rows():
    """(paths, profile, macos_only, reason) for each table row in docs/profiles.md."""
    out = []
    for line in DOC.read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) != 3 or not cells[0].startswith("`"):
            continue
        profile = cells[1].split()[0]
        if profile not in PROFILES:
            raise AssertionError("row %r: profile must be one of %s" % (line, PROFILES))
        out.append((re.findall(r"`([^`]+)`", cells[0]), profile, "(macOS)" in cells[1], cells[2]))
    return out


def covers(row_path, path):
    return path == row_path or path.startswith(row_path + "/")


class CoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        m = {p: managed(p) for p in PROFILES}
        cls.only = {"personal": m["personal"] - m["axon-work-computer"],
                    "axon-work-computer": m["axon-work-computer"] - m["personal"]}
        cls.rows = rows()

    def test_table_parses(self):
        self.assertTrue(self.rows, "no rows found in %s" % DOC)
        for paths, _, _, reason in self.rows:
            self.assertTrue(paths and reason, paths)

    def test_every_one_profile_path_has_a_row(self):
        missing = sorted("%s: %s" % (profile, p) for profile, paths in self.only.items() for p in paths
                         if not any(rp == profile and any(covers(x, p) for x in xs) for xs, rp, _, _ in self.rows))
        self.assertEqual(missing, [], "one-profile paths with no row in docs/profiles.md (add a row with the reason)")

    def test_every_row_is_still_one_profile(self):
        stale, skipped = [], 0
        for paths, profile, macos, _ in self.rows:
            if macos and not DARWIN:
                skipped += 1
                continue
            stale += ["%s: %s" % (profile, x) for x in paths if not any(covers(x, p) for p in self.only[profile])]
        if skipped:
            print("\nprofiles: skipped %d (macOS) rows off darwin" % skipped, file=sys.stderr)
        self.assertEqual(stale, [], "rows in docs/profiles.md whose path is gone or no longer one-profile")

    def test_reasons_needed_are_counted(self):
        n = sum(1 for *_, reason in self.rows if reason == NEEDED)
        print("\nprofiles: %d of %d rows say %r" % (n, len(self.rows), NEEDED), file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
