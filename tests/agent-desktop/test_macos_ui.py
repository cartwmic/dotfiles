"""`agent-desktop ui ARGS...` on a Mac: it hands ARGS to Vercel's agent-desktop and returns its output and exit code unchanged.

A fake Vercel program records each argument in brackets, prints fixed output (no trailing newline, a tab, text on stderr) and
exits with a chosen code. `ui` needs neither screencapture nor osascript, so the PATH here holds neither.
Run: python3 -m unittest discover -s tests/agent-desktop -p 'test_macos_ui.py'
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BODY = REPO / ".chezmoitemplates/agent-desktop-macos.sh"
REAL = ("cat", "date", "mkdir", "tr")

FAKE_UI = """#!/bin/sh
line=vercel
for a in "$@"; do line="$line [$a]"; done
echo "$line" >> "$FAKE_CALLS"
printf 'snapshot\\tout'
printf 'warn\\n' >&2
exit "${FAKE_UI_EXIT:-0}"
"""


class UiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="adu-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name in REAL:
            (self.bin / name).symlink_to(shutil.which(name))
        self.ui = self.tmp / "vercel-agent-desktop"
        self.ui.write_text(FAKE_UI)
        self.ui.chmod(0o755)
        self.calls_file = self.tmp / "calls"

    def run_ui(self, *args, ui_bin=None, **extra):
        env = {"PATH": str(self.bin), "HOME": str(self.home), "XDG_STATE_HOME": str(self.home / ".state"),
               "FAKE_CALLS": str(self.calls_file)}
        if ui_bin is not False:
            env["AGENT_DESKTOP_UI_BIN"] = str(ui_bin or self.ui)
        env.update(extra)
        return subprocess.run(["/bin/sh", str(BODY), "ui", *args], env=env, capture_output=True, text=True, timeout=30)

    def calls(self):
        return self.calls_file.read_text().splitlines() if self.calls_file.exists() else []

    def test_the_script_exists(self):
        self.assertTrue(BODY.is_file(), "%s is missing" % BODY.relative_to(REPO))

    def test_ui_hands_its_arguments_to_vercels_program_and_returns_its_output(self):
        r = self.run_ui("snapshot", "-i", "--compact")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "snapshot\tout", "warn\n"))
        self.assertEqual(self.calls(), ["vercel [snapshot] [-i] [--compact]"])

    def test_ui_returns_vercels_exit_code(self):
        for code in (3, 1, 42):
            with self.subTest(code=code):
                r = self.run_ui("click", "@e5", FAKE_UI_EXIT=str(code))
                self.assertEqual(r.returncode, code)
                self.assertEqual(r.stdout, "snapshot\tout")

    def test_ui_arguments_that_look_like_options_are_passed_on(self):
        r = self.run_ui("--help", "-x", "a b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["vercel [--help] [-x] [a b]"])

    def test_ui_with_no_arguments_still_reaches_vercels_program(self):
        r = self.run_ui()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["vercel"])

    def test_ui_uses_the_installed_default_path_when_no_override_is_set(self):
        default = self.home / ".local/share/agent-desktop/vercel/agent-desktop"
        default.parent.mkdir(parents=True)
        shutil.copy(self.ui, default)
        r = self.run_ui("snapshot", ui_bin=False)
        self.assertEqual((r.returncode, r.stdout), (0, "snapshot\tout"), r.stderr)
        self.assertEqual(self.calls(), ["vercel [snapshot]"])

    def test_ui_without_the_program_exits_69_and_says_how_to_install_it(self):
        for ui_bin in (self.tmp / "nothing-here", False):
            with self.subTest(ui_bin=ui_bin):
                r = self.run_ui("snapshot", ui_bin=ui_bin)
                self.assertEqual((r.returncode, r.stdout), (69, ""), r.stderr)
                self.assertIn("66_agent_desktop_macos", r.stderr)
                self.assertIn("docs/agent-desktop.md", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_ui_leaves_one_log_line_with_a_run_id_and_the_exit_code(self):
        self.run_ui("snapshot", FAKE_UI_EXIT="3")
        log_file = self.home / ".state/agent-desktop/agent-desktop.log"
        self.assertTrue(log_file.is_file(), "ui wrote no log")
        log = log_file.read_text().splitlines()
        self.assertEqual(len(log), 1, log)
        self.assertRegex(log[0], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ run=\S+ elapsed=\d+s ui .*exit=3")


if __name__ == "__main__":
    unittest.main()
