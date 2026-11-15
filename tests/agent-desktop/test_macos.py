"""The macOS agent-desktop script (.chezmoitemplates/agent-desktop-macos.sh): the eight actions, run under /bin/sh on Linux.

The only tools on the script's PATH are fakes (screencapture, osascript) plus a few coreutils, so a call to any other tool fails
the test. Each fake appends one line per call: the tool name and each argument in brackets, so an argument boundary is exact. The
osascript fake shows its script text as the fixed token <jxa>, so the tests pin which action and arguments reach it and not the
JavaScript. A fake Vercel program sits at the default and the override path and must record zero calls. Nothing here touches a
real desktop. What these tests cannot show (that the JavaScript does the right thing on a Mac, that the permission pre-checks answer
right for an ssh session) is the live proof's job.
Run: python3 -m unittest discover -s tests/agent-desktop -p 'test_macos.py'
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BODY = REPO / ".chezmoitemplates/agent-desktop-macos.sh"
TOOLS = ("screencapture", "osascript")
REAL = ("cat", "date", "mkdir", "rm", "tr")  # what the script and the fakes run; the script uses nothing else
ACTIONS = ("shot", "windows", "focus", "move", "click", "type", "key", "cursor")

FAKE = """#!/bin/sh
name=${0##*/}
line=$name
prev=
for a in "$@"; do
  shown=$a
  if [ "$prev" = -e ]; then shown='<jxa>'; fi
  line="$line [$shown]"
  prev=$a
done
printf '%s\n' "$line" >> "$FAKE_CALLS"  # not echo: dash's echo turns a backslash-c in an argument into text
case $name in
  screencapture)
    if [ -n "${FAKE_SC_EXIT:-}" ]; then echo "screencapture: could not create image from display" >&2; exit "$FAKE_SC_EXIT"; fi
    for a in "$@"; do last=$a; done
    if [ -z "${FAKE_SC_NOFILE:-}" ]; then echo png > "$last"; fi
    exit 0 ;;
  osascript)
    # osascript -l JavaScript -e SCRIPT ACTION [ARG...]
    case ${5:-} in
      preflight)
        case ${6:-} in
          screen) echo "${FAKE_SCREEN:-granted}" ;;
          accessibility) echo "${FAKE_AX:-granted}" ;;
        esac
        exit 0 ;;
    esac
    if [ -n "${FAKE_OSA_EXIT:-}" ]; then echo "${FAKE_OSA_ERR:-osascript failed}" >&2; exit "$FAKE_OSA_EXIT"; fi
    case ${5:-} in
      windows) cat "$FAKE_FIXTURES/windows" ;;
      cursor) cat "$FAKE_FIXTURES/cursor" ;;
    esac
    exit 0 ;;
  agent-desktop) # the Vercel program
    printf 'out-of-vercel\\n'
    exit "${FAKE_UI_EXIT:-0}" ;;
esac
"""

OSA = "osascript [-l] [JavaScript] [-e] [<jxa>]"
PREFLIGHT_SCREEN = OSA + " [preflight] [screen]"
PREFLIGHT_AX = OSA + " [preflight] [accessibility]"
WINDOWS_HEADER = "app\ttitle\tat\tsize\tpid\n"
WINDOWS_ROWS = "Calculator\tCalculator\t100,80\t232x408\t511\nTextEdit\tUntitled\t340,120\t640x480\t620\n"
LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ run=(\S+) elapsed=\d+s (.+)$")


def make_bin(bin_dir, fakes, skip=()):
    """A PATH dir with the fake tools named in `fakes`, plus symlinks to REAL tools not in `skip`."""
    bin_dir.mkdir()
    for name in fakes:
        p = bin_dir / name
        p.write_text(FAKE)
        p.chmod(0o755)
    for name in REAL:
        real = shutil.which(name)
        if real and name not in skip:
            (bin_dir / name).symlink_to(real)
    return bin_dir


class MacTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="adm-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.fixtures = self.tmp / "fixtures"
        for d in (self.home, self.fixtures):
            d.mkdir()
        (self.fixtures / "windows").write_text(WINDOWS_ROWS)
        (self.fixtures / "cursor").write_text("961 553\n")
        self.calls_file = self.tmp / "calls"
        self.bin = make_bin(self.tmp / "bin", TOOLS)
        # A fake Vercel program at the default install path and at an override path: the eight actions must never start it.
        self.ui_default = self.home / ".local/share/agent-desktop/vercel/agent-desktop"
        self.ui_default.parent.mkdir(parents=True)
        self.ui_default.write_text(FAKE)
        self.ui_default.chmod(0o755)
        self.shot_file = self.tmp / "shot.png"

    def env(self, **extra):
        e = {
            "PATH": str(self.bin),
            "HOME": str(self.home),
            "XDG_STATE_HOME": str(self.home / ".state"),
            "FAKE_CALLS": str(self.calls_file),
            "FAKE_FIXTURES": str(self.fixtures),
            "AGENT_DESKTOP_UI_BIN": str(self.ui_default),
        }
        e.update(extra)
        return e

    def run_script(self, *args, **extra):
        return subprocess.run(["/bin/sh", str(BODY), *args], env=self.env(**extra), capture_output=True, text=True, timeout=30)

    def calls(self, tool=None):
        lines = self.calls_file.read_text().splitlines() if self.calls_file.exists() else []
        return [l for l in lines if tool is None or l == tool or l.startswith(tool + " ")]

    def log_lines(self):
        log = self.home / ".state" / "agent-desktop" / "agent-desktop.log"
        return log.read_text().splitlines() if log.exists() else []

    def test_the_script_exists(self):
        self.assertTrue(BODY.is_file(), "%s is missing" % BODY.relative_to(REPO))

    # shot
    def test_shot_takes_a_silent_screenshot_and_prints_the_file_name(self):
        r = self.run_script("shot", str(self.shot_file))
        self.assertEqual((r.returncode, r.stdout), (0, "%s\n" % self.shot_file), r.stderr)
        self.assertEqual(self.calls("screencapture"), ["screencapture [-x] [%s]" % self.shot_file])
        self.assertTrue(self.shot_file.exists())

    def test_shot_region_becomes_screencapture_rect(self):
        r = self.run_script("shot", str(self.shot_file), "100,200 300x400")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls("screencapture"), ["screencapture [-x] [-R] [100,200,300,400] [%s]" % self.shot_file])

    def test_shot_refuses_a_bad_region_or_an_empty_file_name(self):
        for args in (("shot", ""), ("shot", "/x/a.png", "nonsense"), ("shot", "/x/a.png", "1,2 3"), ("shot", "/x/a.png", "1.5,2 3x4")):
            with self.subTest(args=args):
                r = self.run_script(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.calls(), [])

    def test_shot_checks_screen_recording_before_it_captures(self):
        r = self.run_script("shot", str(self.shot_file), FAKE_SCREEN="denied")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Screen Recording", r.stderr)
        self.assertIn("docs/agent-desktop.md", r.stderr)
        self.assertEqual(self.calls("screencapture"), [])
        self.assertFalse(self.shot_file.exists())

    def test_a_failing_screencapture_is_exit_one_naming_screen_recording(self):
        r = self.run_script("shot", str(self.shot_file), FAKE_SC_EXIT="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Screen Recording", r.stderr)
        self.assertIn("docs/agent-desktop.md", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_a_screenshot_that_wrote_no_file_is_a_failure_not_success(self):
        r = self.run_script("shot", str(self.shot_file), FAKE_SC_NOFILE="1")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertEqual(r.stdout, "")

    def test_the_screen_permission_check_is_bound_before_it_is_called(self):
        # A seam test: JavaScript for Automation on macOS 27 has no CGPreflightScreenCaptureAccess until it is bound, so every
        # shot and windows failed with "is not a function" on the Mac mini while the stubbed tests passed. The live check is the proof.
        text = BODY.read_text()
        self.assertIn('ObjC.bindFunction("CGPreflightScreenCaptureAccess", ["bool", []]);', text)
        self.assertLess(text.index("bindFunction"), text.index("$.CGPreflightScreenCaptureAccess()"))

    # windows
    def test_windows_prints_a_header_then_the_tab_separated_rows(self):
        r = self.run_script("windows")
        self.assertEqual((r.returncode, r.stdout), (0, WINDOWS_HEADER + WINDOWS_ROWS), r.stderr)
        self.assertEqual(self.calls("osascript"), [PREFLIGHT_SCREEN, OSA + " [windows]"])

    def test_windows_without_screen_recording_says_so_instead_of_printing_blank_titles(self):
        r = self.run_script("windows", FAKE_SCREEN="denied")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("Screen Recording", r.stderr)
        self.assertIn("docs/agent-desktop.md", r.stderr)
        self.assertEqual(self.calls("osascript"), [PREFLIGHT_SCREEN])

    def test_windows_rejects_extra_arguments(self):
        self.assertEqual(self.run_script("windows", "extra").returncode, 2)
        self.assertEqual(self.calls(), [])

    # focus
    def test_focus_passes_the_app_name_as_one_argument(self):
        r = self.run_script("focus", "Google Chrome")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertEqual(self.calls("osascript"), [PREFLIGHT_AX, OSA + " [focus] [Google Chrome]"])

    def test_focus_name_with_quotes_and_backslashes_arrives_unchanged(self):
        r = self.run_script("focus", 'A"b\\c')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls("osascript")[-1], OSA + ' [focus] [A"b\\c]')

    def test_focus_refuses_an_empty_name_and_extra_arguments(self):
        for args in (("focus", ""), ("focus",), ("focus", "a", "b")):
            with self.subTest(args=args):
                self.assertEqual(self.run_script(*args).returncode, 2)
        self.assertEqual(self.calls(), [])

    # move
    def test_move_passes_the_coordinates(self):
        r = self.run_script("move", "737", "277")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertEqual(self.calls("osascript"), [PREFLIGHT_AX, OSA + " [move] [737] [277]"])

    def test_move_accepts_negative_coordinates(self):
        r = self.run_script("move", "-5", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls("osascript")[-1], OSA + " [move] [-5] [0]")

    def test_move_refuses_non_integers_before_any_call(self):
        for args in (("1.5", "2"), ("1,2", "3"), ("1", ""), ("1)", "2"), ("x", "y")):
            with self.subTest(args=args):
                self.assertEqual(self.run_script("move", *args).returncode, 2)
        self.assertEqual(self.run_script("move", "1").returncode, 2)
        self.assertEqual(self.calls(), [])

    # click
    def test_click_is_one_call_with_the_button_left_by_default(self):
        r = self.run_script("click", "737", "277")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls("osascript"), [PREFLIGHT_AX, OSA + " [click] [737] [277] [left]"])

    def test_click_takes_the_button(self):
        for button in ("left", "right", "middle"):
            with self.subTest(button=button):
                self.calls_file.unlink(missing_ok=True)
                r = self.run_script("click", "10", "20", button)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.calls("osascript")[-1], OSA + " [click] [10] [20] [%s]" % button)

    def test_click_refuses_a_bad_button_or_coordinates(self):
        for args in (("1", "2", "double"), ("a", "2"), ("1", "2", "left", "extra")):
            with self.subTest(args=args):
                self.assertEqual(self.run_script("click", *args).returncode, 2)
        self.assertEqual(self.calls(), [])

    # type
    def test_type_passes_the_text_as_one_argument(self):
        r = self.run_script("type", "hello world")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls("osascript"), [PREFLIGHT_AX, OSA + " [type] [hello world]"])

    def test_type_text_that_starts_with_a_dash_is_still_text(self):
        r = self.run_script("type", "-n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls("osascript")[-1], OSA + " [type] [-n]")

    def test_type_log_records_the_length_not_the_text(self):
        r = self.run_script("type", "typed phrase")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = "\n".join(self.log_lines())
        self.assertIn("type length=12", log)
        self.assertNotIn("typed phrase", log)

    def test_type_takes_exactly_one_argument(self):
        self.assertEqual(self.run_script("type").returncode, 2)
        self.assertEqual(self.run_script("type", "a", "b").returncode, 2)
        self.assertEqual(self.calls(), [])

    # key: the script turns the key name into a macOS key code and gives the JavaScript the modifier names (what it posts: test_macos_input.py)
    def test_key_comma_with_ctrl_is_the_docs_example(self):
        r = self.run_script("key", "comma", "ctrl")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls("osascript"), [PREFLIGHT_AX, OSA + " [key] [43] [control]"])

    def test_key_with_two_modifiers(self):
        r = self.run_script("key", "a", "cmd", "shift")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls("osascript")[-1], OSA + " [key] [0] [command] [shift]")

    def test_key_without_modifiers_and_with_named_keys(self):
        cases = {"Return": "36", "tab": "48", "space": "49", "Escape": "53", "BackSpace": "51", "Left": "123", "z": "6", "9": "25", "F5": "96"}
        for key, code in cases.items():
            with self.subTest(key=key):
                self.calls_file.unlink(missing_ok=True)
                r = self.run_script("key", key)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.calls("osascript")[-1], OSA + " [key] [%s]" % code)

    def test_key_modifier_names_option_and_alt_are_the_same_modifier(self):
        for mod in ("alt", "option"):
            with self.subTest(mod=mod):
                self.calls_file.unlink(missing_ok=True)
                self.assertEqual(self.run_script("key", "a", mod).returncode, 0)
                self.assertEqual(self.calls("osascript")[-1], OSA + " [key] [0] [option]")

    def test_key_refuses_unknown_names_before_any_call(self):
        for args in (("comma;rm",), ("a", "ctrl+shift"), ("",), ("nosuchkey",), ("a", "banana"), ()):
            with self.subTest(args=args):
                self.assertEqual(self.run_script("key", *args).returncode, 2)
        self.assertEqual(self.calls(), [])

    # cursor
    def test_cursor_prints_x_and_y_and_needs_no_permission(self):
        r = self.run_script("cursor", FAKE_SCREEN="denied", FAKE_AX="denied")
        self.assertEqual((r.returncode, r.stdout), (0, "961 553\n"), r.stderr)
        self.assertEqual(self.calls("osascript"), [OSA + " [cursor]"])

    def test_cursor_output_that_is_not_two_integers_is_a_failure(self):
        (self.fixtures / "cursor").write_text("nonsense\n")
        r = self.run_script("cursor")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")

    # denied: the message points at the app that runs the session (kitty, through the helper), not at ssh's own program
    def test_a_denied_message_names_kitty_and_the_permission_and_no_longer_sshd_keygen_wrapper(self):
        for args, env, what in ((("shot", str(self.shot_file)), {"FAKE_SCREEN": "denied"}, "Screen Recording"),
                                (("move", "1", "2"), {"FAKE_AX": "denied"}, "Accessibility"),
                                (("shot", str(self.shot_file)), {"FAKE_SC_EXIT": "1"}, "Screen Recording")):
            with self.subTest(args=args, env=env):
                r = self.run_script(*args, **env)
                self.assertEqual(r.returncode, 1)
                self.assertIn(what, r.stderr)
                self.assertIn("kitty", r.stderr)
                self.assertNotIn("sshd-keygen-wrapper", r.stderr)

    # denied accessibility
    def test_actions_that_send_input_stop_with_a_message_when_accessibility_is_denied(self):
        for args in (("focus", "Safari"), ("move", "1", "2"), ("click", "1", "2"), ("type", "x"), ("key", "a")):
            with self.subTest(args=args):
                self.calls_file.unlink(missing_ok=True)
                r = self.run_script(*args, FAKE_AX="denied")
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn("Accessibility", r.stderr)
                self.assertIn("docs/agent-desktop.md", r.stderr)
                self.assertEqual(self.calls("osascript"), [PREFLIGHT_AX])

    def test_osascripts_own_denial_error_is_classified_too(self):
        r = self.run_script("type", "x", FAKE_OSA_EXIT="1", FAKE_OSA_ERR="execution error: osascript is not allowed to send keystrokes. (1002)")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Accessibility", r.stderr)
        self.assertIn("docs/agent-desktop.md", r.stderr)

    def test_another_osascript_failure_is_exit_one_with_its_error(self):
        r = self.run_script("focus", "Nothing", FAKE_OSA_EXIT="1", FAKE_OSA_ERR="execution error: no running app named Nothing")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no running app named Nothing", r.stderr)

    # usage
    def test_usage_errors_exit_two_and_the_usage_names_every_action_and_ui(self):
        for args in ((), ("nope",), ("move", "1"), ("cursor", "x")):
            with self.subTest(args=args):
                r = self.run_script(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                for action in ACTIONS + ("ui",):
                    self.assertIn(action, r.stderr, "usage must name %s" % action)
        self.assertEqual(self.calls(), [])

    # exit 69
    def test_a_missing_tool_exits_69_naming_it_before_any_tool_runs(self):
        cases = [(["shot", str(self.shot_file)], "screencapture"), (["windows"], "osascript"), (["focus", "x"], "osascript"),
                 (["move", "1", "2"], "osascript"), (["click", "1", "2"], "osascript"), (["type", "x"], "osascript"),
                 (["key", "a"], "osascript"), (["cursor"], "osascript")]
        for i, (args, missing) in enumerate(cases):
            with self.subTest(args=args, missing=missing):
                self.calls_file.unlink(missing_ok=True)
                self.bin = make_bin(self.tmp / ("bin-%d" % i), [t for t in TOOLS if t != missing])
                r = self.run_script(*args)
                self.assertEqual(r.returncode, 69, r.stderr)
                self.assertIn("%s is not on PATH" % missing, r.stderr)
                self.assertEqual(self.calls(), [], "a tool ran before the missing one was reported")

    # log
    def test_every_step_writes_one_log_line_with_a_run_id(self):
        for args in (("shot", str(self.shot_file)), ("windows",), ("focus", "Safari"), ("move", "1", "2"), ("click", "1", "2"),
                     ("type", "x"), ("key", "a"), ("cursor",)):
            with self.subTest(args=args):
                before = len(self.log_lines())
                self.assertEqual(self.run_script(*args).returncode, 0)
                new = self.log_lines()[before:]
                self.assertEqual(len(new), 1, new)
                m = LOG_LINE.match(new[0])
                self.assertTrue(m, "log line does not have the shared shape: %r" % new[0])
                self.assertTrue(m.group(2).startswith(args[0]), "the step should start with the action name: %r" % m.group(2))

    def test_one_run_uses_one_run_id_and_two_runs_use_two(self):
        self.run_script("move", "1", "2")
        self.run_script("move", "3", "4")
        ids = [LOG_LINE.match(l).group(1) for l in self.log_lines()]
        self.assertEqual(len(ids), 2)
        self.assertNotEqual(ids[0], ids[1])

    def test_a_failing_step_is_logged_as_a_failure(self):
        self.run_script("focus", "Nothing", FAKE_OSA_EXIT="1")
        self.assertTrue(any("FAIL" in l for l in self.log_lines()), self.log_lines())

    def test_the_log_goes_under_home_local_state_when_xdg_state_home_is_unset(self):
        env = self.env()
        env.pop("XDG_STATE_HOME")
        r = subprocess.run(["/bin/sh", str(BODY), "move", "1", "2"], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.home / ".local/state/agent-desktop/agent-desktop.log").is_file())

    # Vercel's program is only for `ui`
    def test_none_of_the_eight_actions_starts_vercels_program(self):
        for args in (("shot", str(self.shot_file)), ("windows",), ("focus", "Safari"), ("move", "1", "2"), ("click", "1", "2"),
                     ("type", "x"), ("key", "a"), ("cursor",)):
            self.assertEqual(self.run_script(*args).returncode, 0, args)
        self.assertEqual(self.calls("agent-desktop"), [])


if __name__ == "__main__":
    unittest.main()
