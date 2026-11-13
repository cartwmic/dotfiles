"""dot_local/bin/executable_agent-desktop: the exact argv each tool receives, the exit 69 path, the session lookup and the log.

Fake hyprctl, wlrctl, wtype and grim are shell scripts on a hermetic PATH, so the real tools in /usr/bin (on an Omarchy box
they exist and would act on the live desktop) are never reachable. Each fake appends one line per call: the tool name and
each argument in brackets, so an argument boundary is exact. Nothing here sends input to a real desktop.
"""
import json
import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "dot_local/bin/executable_agent-desktop"
TOOLS = ("hyprctl", "wlrctl", "wtype", "grim")
# Real tools the script and the fakes run. python3 is needed only by `windows`.
REAL = ("cat", "date", "mkdir", "python3")

FAKE = """#!/bin/sh
name=${0##*/}
line=$name
for a in "$@"; do line="$line [$a]"; done
echo "$line" >> "$FAKE_CALLS"
echo "$name HYPRLAND_INSTANCE_SIGNATURE=${HYPRLAND_INSTANCE_SIGNATURE:-unset} WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-unset}" >> "$FAKE_ENV"
case $name in
  hyprctl)
    case $1 in
      cursorpos) cat "$FAKE_FIXTURES/cursorpos" ;;
      clients) cat "$FAKE_FIXTURES/clients.json" ;;
      dispatch)
        if [ -n "${FAKE_DISPATCH_EXIT:-}" ]; then echo "error: lua syntax" >&2; exit "$FAKE_DISPATCH_EXIT"; fi
        printf '%s\\n' "${FAKE_DISPATCH_OUT:-ok}" ;;
      *) echo "fake hyprctl: unexpected $*" >&2; exit 99 ;;
    esac ;;
  wlrctl) exit "${FAKE_WLRCTL_EXIT:-0}" ;;
  wtype|grim) exit 0 ;;
esac
"""

CLIENTS = [
    {"class": "com.onepassword.OnePassword", "title": "1Password\tVault", "at": [967, 38], "size": [941, 1030],
     "workspace": {"id": 42, "name": "42"}, "xwayland": False},
    {"class": "Steam", "title": "Steam", "at": [-20, 0], "size": [1280, 720],
     "workspace": {"id": -99, "name": "special:scratchpad"}, "xwayland": True},
]
WINDOWS_OUT = (
    "class\ttitle\tat\tsize\tworkspace\txwayland\n"
    "com.onepassword.OnePassword\t1Password Vault\t967,38\t941x1030\t42\tfalse\n"
    "Steam\tSteam\t-20,0\t1280x720\tspecial:scratchpad\ttrue\n"
)
MOVE_737 = "hyprctl [dispatch] [hl.dsp.cursor.move({x=737,y=277})]"


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


def make_socket(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(path))
    s.close()


class DesktopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ad-"))
        self.home = self.tmp / "home"
        self.runtime = self.tmp / "runtime"
        self.fixtures = self.tmp / "fixtures"
        for d in (self.home, self.runtime, self.fixtures):
            d.mkdir()
        (self.fixtures / "cursorpos").write_text("961, 553\n")
        (self.fixtures / "clients.json").write_text(json.dumps(CLIENTS))
        self.calls_file = self.tmp / "calls"
        self.env_file = self.tmp / "env"
        self.bin = make_bin(self.tmp / "bin", TOOLS)

    def env(self, unset=(), **extra):
        e = {
            "PATH": str(self.bin),
            "HOME": str(self.home),
            "XDG_STATE_HOME": str(self.home / ".state"),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "WAYLAND_DISPLAY": "wayland-1",
            "HYPRLAND_INSTANCE_SIGNATURE": "sig_test",
            "FAKE_CALLS": str(self.calls_file),
            "FAKE_ENV": str(self.env_file),
            "FAKE_FIXTURES": str(self.fixtures),
        }
        for k in unset:
            e.pop(k, None)
        e.update(extra)
        return e

    def run_script(self, *args, unset=(), **extra):
        return subprocess.run(["/bin/sh", str(SCRIPT), *args], env=self.env(unset, **extra),
                              capture_output=True, text=True, timeout=30)

    def calls(self):
        return self.calls_file.read_text().splitlines() if self.calls_file.exists() else []

    def log_lines(self):
        log = self.home / ".state" / "agent-desktop" / "agent-desktop.log"
        return log.read_text().splitlines() if log.exists() else []

    # shot
    def test_shot_writes_the_file_and_prints_its_path(self):
        r = self.run_script("shot", "/x/shot.png")
        self.assertEqual((r.returncode, r.stdout), (0, "/x/shot.png\n"), r.stderr)
        self.assertEqual(self.calls(), ["grim [/x/shot.png]"])

    def test_shot_region_is_one_argument_after_dash_g(self):
        r = self.run_script("shot", "/x/a.png", "100,200 300x400")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["grim [-g] [100,200 300x400] [/x/a.png]"])

    def test_shot_refuses_an_empty_file_name(self):
        r = self.run_script("shot", "")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.calls(), [])

    # windows
    def test_windows_lists_class_title_at_size_workspace_xwayland(self):
        r = self.run_script("windows")
        self.assertEqual((r.returncode, r.stdout), (0, WINDOWS_OUT), r.stderr)
        self.assertEqual(self.calls(), ["hyprctl [clients] [-j]"])

    # focus
    def test_focus_dispatches_the_lua_string_with_the_class_quoted(self):
        r = self.run_script("focus", "com.onepassword.OnePassword")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [
            'hyprctl [dispatch] [hl.dsp.focus({window="class:com.onepassword.OnePassword"})]'])

    def test_focus_refuses_a_double_quote_or_backslash(self):
        for cls in ('a"b', "a\\b", ""):
            with self.subTest(cls=cls):
                r = self.run_script("focus", cls)
                self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.calls(), [])

    def test_focus_miss_is_a_failure_even_though_hyprctl_exits_zero(self):
        r = self.run_script("focus", "Steam", FAKE_DISPATCH_OUT="warning: =[C]:-1: hl.focus: window not found")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("window not found", r.stderr)

    # move
    def test_move_dispatches_cursor_move_in_logical_coordinates(self):
        r = self.run_script("move", "737", "277")
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)
        self.assertEqual(self.calls(), [MOVE_737])

    def test_move_accepts_negative_coordinates(self):
        r = self.run_script("move", "-5", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["hyprctl [dispatch] [hl.dsp.cursor.move({x=-5,y=0})]"])

    def test_move_refuses_non_integers_before_any_call(self):
        for args in (("1.5", "2"), ("1,2", "3"), ("1", ""), ("1)", "2")):
            with self.subTest(args=args):
                r = self.run_script("move", *args)
                self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_failed_dispatch_is_exit_one_with_the_lua_error(self):
        r = self.run_script("move", "1", "2", FAKE_DISPATCH_EXIT="7")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("lua syntax", r.stderr)

    # click
    def test_click_moves_then_clicks_left_by_default(self):
        r = self.run_script("click", "737", "277")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [MOVE_737, "wlrctl [pointer] [click] [left]"])

    def test_click_takes_the_button(self):
        r = self.run_script("click", "10", "20", "right")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls()[-1], "wlrctl [pointer] [click] [right]")

    def test_click_refuses_an_unknown_button(self):
        r = self.run_script("click", "1", "2", "double")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.calls(), [])

    def test_click_does_not_click_when_the_move_fails(self):
        r = self.run_script("click", "1", "2", FAKE_DISPATCH_EXIT="7")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(self.calls(), ["hyprctl [dispatch] [hl.dsp.cursor.move({x=1,y=2})]"])

    def test_click_reports_a_wlrctl_failure(self):
        r = self.run_script("click", "1", "2", FAKE_WLRCTL_EXIT="3")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("wlrctl pointer click left failed", r.stderr)

    # type and key
    def test_type_passes_the_text_as_one_argument_after_double_dash(self):
        r = self.run_script("type", "hello world")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["wtype [--] [hello world]"])

    def test_type_text_that_starts_with_a_dash_is_still_text(self):
        r = self.run_script("type", "-n")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["wtype [--] [-n]"])

    def test_type_log_records_the_length_not_the_text(self):
        r = self.run_script("type", "typed phrase")
        self.assertEqual(r.returncode, 0, r.stderr)
        log = "\n".join(self.log_lines())
        self.assertIn("type length=12", log)
        self.assertNotIn("typed phrase", log)

    def test_key_with_one_modifier(self):
        r = self.run_script("key", "comma", "ctrl")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["wtype [-M] [ctrl] [-k] [comma] [-m] [ctrl]"])

    def test_key_with_two_modifiers_presses_then_releases_both(self):
        r = self.run_script("key", "a", "ctrl", "shift")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [
            "wtype [-M] [ctrl] [-M] [shift] [-k] [a] [-m] [ctrl] [-m] [shift]"])

    def test_key_without_modifiers(self):
        r = self.run_script("key", "Return")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["wtype [-k] [Return]"])

    def test_key_refuses_names_that_are_not_plain_words(self):
        for args in (("comma;rm",), ("a", "ctrl+shift"), ("",)):
            with self.subTest(args=args):
                r = self.run_script("key", *args)
                self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.calls(), [])

    # cursor
    def test_cursor_prints_x_and_y_space_separated(self):
        r = self.run_script("cursor")
        self.assertEqual((r.returncode, r.stdout), (0, "961 553\n"), r.stderr)
        self.assertEqual(self.calls(), ["hyprctl [cursorpos]"])

    # usage
    def test_usage_errors_exit_two(self):
        for args in ((), ("nope",), ("move", "1"), ("windows", "extra"), ("cursor", "x")):
            with self.subTest(args=args):
                r = self.run_script(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.calls(), [])

    # exit 69: a missing tool stops the command before any tool runs
    def test_a_missing_tool_exits_69_naming_its_package_before_acting(self):
        cases = [
            (["shot", "/x/a.png"], "grim", "Arch package grim"),
            (["windows"], "hyprctl", "Arch package hyprland"),
            (["windows"], "python3", "Arch package python"),
            (["focus", "Steam"], "hyprctl", "Arch package hyprland"),
            (["move", "1", "2"], "hyprctl", "Arch package hyprland"),
            (["click", "1", "2"], "hyprctl", "Arch package hyprland"),
            (["click", "1", "2"], "wlrctl", "AUR: yay -S --needed wlrctl"),
            (["type", "x"], "wtype", "Arch package wtype"),
            (["key", "a"], "wtype", "Arch package wtype"),
            (["cursor"], "hyprctl", "Arch package hyprland"),
        ]
        for i, (args, missing, hint) in enumerate(cases):
            with self.subTest(args=args, missing=missing):
                self.calls_file.unlink(missing_ok=True)
                self.bin = make_bin(self.tmp / f"bin-{i}", [t for t in TOOLS if t != missing], skip=(missing,))
                r = self.run_script(*args)
                self.assertEqual(r.returncode, 69, r.stderr)
                self.assertIn(f"{missing} is not on PATH", r.stderr)
                self.assertIn(hint, r.stderr)
                self.assertEqual(self.calls(), [], "a tool ran before the missing one was reported")

    # session lookup: agent shells can lack WAYLAND_DISPLAY and HYPRLAND_INSTANCE_SIGNATURE
    def test_wayland_and_hyprland_are_found_when_the_shell_has_neither(self):
        make_socket(self.runtime / "wayland-1")
        (self.runtime / "wayland-1.lock").write_text("")
        make_socket(self.runtime / "hypr" / "sig_found" / ".socket.sock")
        r = self.run_script("cursor", unset=("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.env_file.read_text().splitlines(),
                         ["hyprctl HYPRLAND_INSTANCE_SIGNATURE=sig_found WAYLAND_DISPLAY=wayland-1"])

    def test_a_set_session_is_left_alone(self):
        r = self.run_script("cursor")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.env_file.read_text().splitlines(),
                         ["hyprctl HYPRLAND_INSTANCE_SIGNATURE=sig_test WAYLAND_DISPLAY=wayland-1"])

    # log: one line per step, in order
    def test_click_logs_the_dispatch_then_the_click(self):
        r = self.run_script("click", "737", "277")
        self.assertEqual(r.returncode, 0, r.stderr)
        steps = [line.split(" ", 3)[3] for line in self.log_lines()]
        self.assertEqual(steps, [
            "hyprctl dispatch hl.dsp.cursor.move({x=737,y=277}) ok",
            "click 737 277 left",
        ])


if __name__ == "__main__":
    unittest.main()
