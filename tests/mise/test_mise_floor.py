"""run_onchange_after_10_mise_bootstrap.sh upgrades a mise older than its floor before it installs tools, and does nothing when mise is current.

The real script is rendered with chezmoi and run with a fake mise, brew and uname first on PATH, in a throwaway HOME. The fake mise keeps its
version in a file and logs every call; a fake `brew upgrade mise` raises that version. Nothing touches a real mise or brew.
Run: python3 -m unittest discover -s tests/mise
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "run_onchange_after_10_mise_bootstrap.sh.tmpl"
FLOOR = "2026.11.8"

FAKE_MISE = """#!/bin/sh
echo "mise $*" >> "$FAKE_LOG"
case "$1" in
  --version) echo "$(cat "$FAKE_STATE/version") macos-arm64 (2026-11-13)" ;;
  self-update) [ "$FAKE_SELF_UPDATE" = ok ] && echo "$FAKE_NEW_VERSION" > "$FAKE_STATE/version"; [ "$FAKE_SELF_UPDATE" = ok ] ;;
  *) : ;;
esac
"""
FAKE_BREW = """#!/bin/sh
echo "brew $*" >> "$FAKE_LOG"
[ "$1 $2" = "upgrade mise" ] && echo "$FAKE_NEW_VERSION" > "$FAKE_STATE/version"
exit 0
"""
FAKE_UNAME = """#!/bin/sh
[ "$1" = -s ] && echo "$FAKE_OS" || /usr/bin/uname "$@"
"""


class MiseFloorTest(unittest.TestCase):
    def run_script(self, version, *, os_name="Darwin", brew=True, self_update="refused", new_version=FLOOR):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home, bin_dir, state = root / "home", root / "bin", root / "state"
            for d in (home, bin_dir, state):
                d.mkdir()
            cfg = root / "chezmoi.yaml"
            cfg.write_text("data:\n  profile: personal\n")
            rendered = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home),
                                       "execute-template"], input=SCRIPT.read_text(), capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), check=True).stdout
            script = root / "script.sh"
            script.write_text(rendered)
            for name, text in (("mise", FAKE_MISE), ("uname", FAKE_UNAME)) + ((("brew", FAKE_BREW),) if brew else ()):
                (bin_dir / name).write_text(text)
                (bin_dir / name).chmod(0o755)
            (state / "version").write_text(version)
            log = root / "calls.log"
            log.write_text("")
            env = dict(os.environ, HOME=str(home), PATH="%s:/usr/bin:/bin" % bin_dir, FAKE_LOG=str(log), FAKE_STATE=str(state), FAKE_OS=os_name,
                       FAKE_SELF_UPDATE=self_update, FAKE_NEW_VERSION=new_version)
            r = subprocess.run(["sh", str(script)], capture_output=True, text=True, env=env)
            return r, log.read_text().splitlines(), (state / "version").read_text().strip()

    def test_a_current_mise_is_left_alone(self):
        for v in (FLOOR, "2026.11.9", "2026.12.0", "2027.1.1", "2026.11.10"):  # 2026.11.10 is newer than 2026.11.8: compared as numbers, not text
            with self.subTest(version=v):
                r, calls, _ = self.run_script(v)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertNotIn("brew upgrade mise", calls)
                self.assertNotIn("mise self-update --yes", calls)
                self.assertIn("mise install", calls)

    def test_an_old_mise_on_macos_with_homebrew_is_upgraded_by_brew_before_tools_install(self):
        r, calls, version = self.run_script("2026.3.9")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mise 2026.3.9 is older than %s; upgrading it" % FLOOR, r.stderr)
        self.assertLess(calls.index("brew upgrade mise"), calls.index("mise install"))
        self.assertEqual(version, FLOOR)
        self.assertIn("mise is now %s" % FLOOR, r.stderr)

    def test_a_mise_that_updates_itself_does_not_need_brew(self):
        r, calls, version = self.run_script("2026.10.1", os_name="Linux", brew=False, self_update="ok")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(version, FLOOR)
        self.assertLess(calls.index("mise self-update --yes"), calls.index("mise install"))

    def test_an_old_package_owned_mise_on_linux_warns_and_the_script_goes_on(self):
        r, calls, version = self.run_script("2026.11.0", os_name="Linux", brew=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(version, "2026.11.0")
        self.assertIn("WARN: could not upgrade mise 2026.11.0", r.stderr)
        self.assertIn("mise install", calls)

    def test_an_unreadable_version_is_reported_and_not_acted_on(self):
        r, calls, _ = self.run_script("not-a-version")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("could not read the mise version", r.stderr)
        self.assertNotIn("brew upgrade mise", calls)


if __name__ == "__main__":
    unittest.main()
