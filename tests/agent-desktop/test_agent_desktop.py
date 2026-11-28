"""dot_local/bin/executable_agent-desktop: the exact argv each tool receives, the exit 69 path, the session lookup and the log.
Also dot_local/share/agent-desktop/session.sh (the lookup agent-desktop, agent-chrome and dot_zshenv share), through the script and
through a real `zsh -c` with dot_zshenv as ~/.zshenv.

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
SESSION_LIB = REPO / "dot_local/share/agent-desktop/session.sh"
ZSHENV = REPO / "dot_zshenv"
ZSH = shutil.which("zsh")
LINUX = Path("/proc").is_dir()   # session.sh decides liveness from /proc/<pid>
TOOLS = ("hyprctl", "wlrctl", "wtype", "grim")
# Real tools the script and the fakes run. python3 is needed by `windows`, `save` and `restore`; tr by the record name.
REAL = ("cat", "date", "mkdir", "python3", "rm", "tr")

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
      activewindow) cat "$FAKE_FIXTURES/activewindow.json" ;;
      dispatch)
        if [ -n "${FAKE_DISPATCH_EXIT:-}" ]; then echo "error: lua syntax" >&2; exit "$FAKE_DISPATCH_EXIT"; fi
        case $2 in *hl.dsp.focus*) if [ -n "${FAKE_FOCUS_OUT:-}" ]; then printf '%s\\n' "$FAKE_FOCUS_OUT"; exit 0; fi ;; esac
        # Like Hyprland: a focus by address makes that window active; FAKE_MOVE_FOCUS is a window follow_mouse hands focus to
        case $2 in *hl.dsp.focus*address:*) a=${2#*address:}; a=${a%%\\"*}; printf '{"address": "%s", "class": "x"}' "$a" > "$FAKE_FIXTURES/activewindow.json" ;; esac
        case $2 in *hl.dsp.cursor.move*) if [ -n "${FAKE_MOVE_FOCUS:-}" ]; then printf '{"address": "%s", "class": "x"}' "$FAKE_MOVE_FOCUS" > "$FAKE_FIXTURES/activewindow.json"; fi ;; esac
        printf '%s\\n' "${FAKE_DISPATCH_OUT:-ok}" ;;
      *) echo "fake hyprctl: unexpected $*" >&2; exit 99 ;;
    esac ;;
  wlrctl) exit "${FAKE_WLRCTL_EXIT:-0}" ;;
  wtype|grim) exit 0 ;;
esac
"""

# pgrep prints FAKE_CHROME_PIDS, one per line, only when asked for the agent Chrome profile's command-line pattern
# (what agent-chrome matches on), so a restore that asks the wrong question sees no agent Chrome.
FAKE_PGREP = """#!/bin/sh
case "$*" in
  *"--user-data-dir=$HOME/.local/share/agent-chrome-profile"*) printf '%s\\n' ${FAKE_CHROME_PIDS:-} ;;
  *) exit 1 ;;
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
WIN_A = "0xaaaa1111"   # the window Michael is using
WIN_CHROME = "0xbbbb2222"   # the agent Chrome
WIN_B = "0xcccc3333"   # another window Michael switches to
CHROME_PID = 4242   # the agent Chrome's process; every other window is pid 1000
MOVE_CURSORPOS = "hyprctl [dispatch] [hl.dsp.cursor.move({x=961,y=553})]"
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


def dead_pid():
    """A pid that belonged to a process that has exited."""
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def make_instance(runtime, sig, pid, display="wayland-1", lock=True):
    """One $XDG_RUNTIME_DIR/hypr/<sig>/ folder as Hyprland leaves it: a socket and a lock holding the pid and the display name.
    The display socket itself is made too."""
    make_socket(runtime / "hypr" / sig / ".socket.sock")
    if lock:
        (runtime / "hypr" / sig / "hyprland.lock").write_text(f"{pid}\n{display}\n")
    if not (runtime / display).exists():
        make_socket(runtime / display)


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
        self.set_active(WIN_A)
        self.calls_file = self.tmp / "calls"
        self.env_file = self.tmp / "env"
        self.bin = make_bin(self.tmp / "bin", TOOLS)
        pgrep = self.bin / "pgrep"
        pgrep.write_text(FAKE_PGREP)
        pgrep.chmod(0o755)
        lib = self.home / ".local/share/agent-desktop"
        lib.mkdir(parents=True)
        shutil.copy(SESSION_LIB, lib / "session.sh")

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
            "FAKE_CHROME_PIDS": str(CHROME_PID),
        }
        for k in unset:
            e.pop(k, None)
        e.update(extra)
        return e

    def run_script(self, *args, unset=(), **extra):
        return subprocess.run(["/bin/sh", str(SCRIPT), *args], env=self.env(unset, **extra),
                              capture_output=True, text=True, timeout=30)

    def set_active(self, address):
        """What `hyprctl activewindow -j` prints: a window object, `{}` (None) or nothing at all ("")."""
        pid = CHROME_PID if address == WIN_CHROME else 1000
        body = "" if address == "" else "{}" if address is None else json.dumps({"address": address, "class": "x", "pid": pid})
        (self.fixtures / "activewindow.json").write_text(body)

    def saved_file(self, caller=None):
        """The record: with no caller the shared one, otherwise the caller's own (the key goes after a dot)."""
        return self.home / ".state" / "agent-desktop" / ("saved-focus" if caller is None else f"saved-focus.{caller}")

    def set_cursor(self, x, y):
        (self.fixtures / "cursorpos").write_text(f"{x}, {y}\n")

    def dispatches(self, what):
        """The recorded hyprctl dispatch calls that contain `what`."""
        return [c for c in self.calls() if c.startswith("hyprctl [dispatch]") and what in c]

    def calls(self):
        return self.calls_file.read_text().splitlines() if self.calls_file.exists() else []

    def log_file(self):
        return self.home / ".state" / "agent-desktop" / "agent-desktop.log"

    def log_lines(self):
        log = self.log_file()
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
        for args in ((), ("nope",), ("move", "1"), ("windows", "extra"), ("cursor", "x"), ("save", "x"), ("restore", "x")):
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
            (["save"], "hyprctl", "Arch package hyprland"),
            (["save"], "python3", "Arch package python"),
            (["restore"], "hyprctl", "Arch package hyprland"),
            (["restore"], "python3", "Arch package python"),
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
    def seen(self, **kw):
        r = self.run_script("cursor", unset=("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"), **kw)
        self.assertEqual(r.returncode, 0, r.stderr)
        return self.env_file.read_text().splitlines()[-1]

    @unittest.skipUnless(LINUX, "needs /proc")
    def test_wayland_and_hyprland_are_found_when_the_shell_has_neither(self):
        make_instance(self.runtime, "abc_1000_1", os.getpid())
        self.assertEqual(self.seen(), "hyprctl HYPRLAND_INSTANCE_SIGNATURE=abc_1000_1 WAYLAND_DISPLAY=wayland-1")

    @unittest.skipUnless(LINUX, "needs /proc")
    def test_a_stale_folder_that_sorts_first_is_passed_over_for_the_live_one(self):
        # After a Hyprland restart the old folder stays. "aaa" sorts before "bbb", so a first-match lookup takes the dead one.
        make_instance(self.runtime, "aaa_1000_1", dead_pid(), display="wayland-0")
        make_instance(self.runtime, "bbb_2000_1", os.getpid())
        self.assertEqual(self.seen(), "hyprctl HYPRLAND_INSTANCE_SIGNATURE=bbb_2000_1 WAYLAND_DISPLAY=wayland-1")

    @unittest.skipUnless(LINUX, "needs /proc")
    def test_a_newer_stale_folder_does_not_beat_an_older_live_one(self):
        make_instance(self.runtime, "aaa_1000_1", os.getpid())
        make_instance(self.runtime, "bbb_2000_1", dead_pid(), display="wayland-2")
        self.assertEqual(self.seen(), "hyprctl HYPRLAND_INSTANCE_SIGNATURE=aaa_1000_1 WAYLAND_DISPLAY=wayland-1")

    @unittest.skipUnless(LINUX, "needs /proc")
    def test_of_two_live_instances_the_newest_start_wins_not_the_first_name(self):
        make_instance(self.runtime, "zzz_1000_1", os.getpid(), display="wayland-0")
        make_instance(self.runtime, "aaa_2000_1", os.getpid(), display="wayland-1")
        self.assertEqual(self.seen(), "hyprctl HYPRLAND_INSTANCE_SIGNATURE=aaa_2000_1 WAYLAND_DISPLAY=wayland-1")

    @unittest.skipUnless(LINUX, "needs /proc")
    def test_a_folder_with_a_socket_but_no_lock_is_not_live(self):
        make_instance(self.runtime, "abc_1000_1", os.getpid(), lock=False)
        self.assertEqual(self.seen(), "hyprctl HYPRLAND_INSTANCE_SIGNATURE=unset WAYLAND_DISPLAY=unset")

    def test_no_session_at_all_sets_nothing_and_says_nothing(self):
        self.assertEqual(self.seen(), "hyprctl HYPRLAND_INSTANCE_SIGNATURE=unset WAYLAND_DISPLAY=unset")
        (self.runtime / "hypr").mkdir()   # the folder with no instance in it
        r = self.run_script("cursor", unset=("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE"))
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    @unittest.skipUnless(LINUX, "needs /proc")
    def test_a_set_signature_whose_instance_is_dead_is_replaced_with_the_display_too(self):
        # t3code started under an earlier Hyprland (the shell inherits its pair), then Hyprland restarted.
        make_instance(self.runtime, "old_1000_1", dead_pid(), display="wayland-0")
        make_instance(self.runtime, "new_2000_1", os.getpid(), display="wayland-1")
        r = self.run_script("cursor", HYPRLAND_INSTANCE_SIGNATURE="old_1000_1", WAYLAND_DISPLAY="wayland-0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.env_file.read_text().splitlines(),
                         ["hyprctl HYPRLAND_INSTANCE_SIGNATURE=new_2000_1 WAYLAND_DISPLAY=wayland-1"])

    @unittest.skipUnless(LINUX, "needs /proc")
    def test_a_set_signature_with_no_folder_is_replaced(self):
        make_instance(self.runtime, "new_2000_1", os.getpid())
        r = self.run_script("cursor", HYPRLAND_INSTANCE_SIGNATURE="gone_1000_1", WAYLAND_DISPLAY="wayland-9")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.env_file.read_text().splitlines(),
                         ["hyprctl HYPRLAND_INSTANCE_SIGNATURE=new_2000_1 WAYLAND_DISPLAY=wayland-1"])

    @unittest.skipUnless(LINUX, "needs /proc")
    def test_a_set_signature_whose_instance_is_live_is_kept_even_when_a_newer_one_exists(self):
        make_instance(self.runtime, "old_1000_1", os.getpid(), display="wayland-0")
        make_instance(self.runtime, "new_2000_1", os.getpid(), display="wayland-1")
        r = self.run_script("cursor", HYPRLAND_INSTANCE_SIGNATURE="old_1000_1", WAYLAND_DISPLAY="wayland-0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.env_file.read_text().splitlines(),
                         ["hyprctl HYPRLAND_INSTANCE_SIGNATURE=old_1000_1 WAYLAND_DISPLAY=wayland-0"])

    @unittest.skipUnless(LINUX, "needs /proc")
    def test_a_live_signature_with_no_display_gets_that_instances_display(self):
        make_instance(self.runtime, "old_1000_1", os.getpid(), display="wayland-0")
        make_instance(self.runtime, "new_2000_1", os.getpid(), display="wayland-1")
        r = self.run_script("cursor", unset=("WAYLAND_DISPLAY",), HYPRLAND_INSTANCE_SIGNATURE="old_1000_1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.env_file.read_text().splitlines(),
                         ["hyprctl HYPRLAND_INSTANCE_SIGNATURE=old_1000_1 WAYLAND_DISPLAY=wayland-0"])

    def test_a_set_signature_is_kept_when_no_session_is_live(self):
        # Nothing to replace it with: keep what is set, say nothing.
        for dead in (False, True):
            with self.subTest(dead_folder=dead):
                if dead:
                    make_instance(self.runtime, "old_1000_1", dead_pid(), display="wayland-0")
                r = self.run_script("cursor", HYPRLAND_INSTANCE_SIGNATURE="old_1000_1", WAYLAND_DISPLAY="wayland-0")
                self.assertEqual((r.returncode, r.stderr), (0, ""))
                self.assertEqual(self.env_file.read_text().splitlines()[-1],
                                 "hyprctl HYPRLAND_INSTANCE_SIGNATURE=old_1000_1 WAYLAND_DISPLAY=wayland-0")

    @unittest.skipUnless(LINUX, "needs /proc")
    def test_a_set_live_session_is_left_alone(self):
        make_instance(self.runtime, "sig_test", os.getpid())
        r = self.run_script("cursor")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.env_file.read_text().splitlines(),
                         ["hyprctl HYPRLAND_INSTANCE_SIGNATURE=sig_test WAYLAND_DISPLAY=wayland-1"])

    def test_a_set_session_with_nothing_running_is_left_alone(self):
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

    # save and restore: give back the focus and the pointer an agent run used (Linux only; see docs/agent-desktop.md)
    def test_save_restore_round_trip(self):
        r = self.run_script("save")
        self.assertEqual((r.returncode, r.stdout), (0, f"saved window {WIN_A} pointer 961,553\n"), r.stderr)
        self.assertEqual(self.calls(), ["hyprctl [activewindow] [-j]", "hyprctl [cursorpos]"])
        self.calls_file.unlink()
        self.set_active(WIN_CHROME)   # the agent's work moved focus
        r = self.run_script("restore")
        self.assertEqual((r.returncode, r.stdout), (0, f"restored window {WIN_A}, pointer 961,553\n"), r.stderr)
        self.assertEqual(self.calls(), [
            "hyprctl [activewindow] [-j]",
            f'hyprctl [dispatch] [hl.dsp.focus({{window="address:{WIN_A}"}})]',   # the window first, by address
            MOVE_CURSORPOS,                               # then the pointer, so a workspace-change warp cannot undo it
            "hyprctl [activewindow] [-j]",                # focus is checked again after the pointer move
        ])
        self.assertFalse(self.saved_file().exists(), "the record is deleted after a restore")

    def test_restore_refocuses_when_the_pointer_move_hands_focus_away(self):
        self.assertEqual(self.run_script("save").returncode, 0)
        self.calls_file.unlink()
        self.set_active(WIN_CHROME)
        r = self.run_script("restore", FAKE_MOVE_FOCUS=WIN_CHROME)   # follow_mouse: the window under the pointer takes focus
        self.assertEqual(r.returncode, 0, r.stderr)
        focus = f'hyprctl [dispatch] [hl.dsp.focus({{window="address:{WIN_A}"}})]'
        self.assertEqual(self.calls(), ["hyprctl [activewindow] [-j]", focus, MOVE_CURSORPOS, "hyprctl [activewindow] [-j]", focus])

    def test_restore_with_nothing_saved_exits_1(self):
        r = self.run_script("restore")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("nothing saved: run agent-desktop save first", r.stderr)
        self.assertEqual(self.calls(), [], "restore with nothing saved made a Hyprland call")

    def test_restore_when_the_window_is_gone_exits_1(self):
        self.assertEqual(self.run_script("save").returncode, 0)
        self.calls_file.unlink()
        self.set_active(WIN_CHROME)
        r = self.run_script("restore", FAKE_FOCUS_OUT="warning: =[C]:-1: hl.focus: window not found")   # hyprctl exits 0
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn(WIN_A, r.stderr)
        self.assertIn(MOVE_CURSORPOS, self.calls(), "the pointer still moves")
        self.assertFalse(self.saved_file().exists(), "the record is deleted even when the window is gone")

    def test_save_with_no_active_window_restores_the_pointer_only(self):
        for none in (None, ""):   # `{}` and no output at all
            with self.subTest(active=none):
                self.calls_file.unlink(missing_ok=True)
                self.set_active(none)
                self.set_cursor(961, 553)
                r = self.run_script("save")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.run_script("move", "10", "20").returncode, 0)   # the agent moved the pointer
                self.set_cursor(10, 20)
                self.calls_file.unlink()
                self.set_active(WIN_CHROME)
                r = self.run_script("restore")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("no window to refocus", r.stdout)
                self.assertEqual(self.calls(), ["hyprctl [activewindow] [-j]", "hyprctl [cursorpos]", MOVE_CURSORPOS,
                                                "hyprctl [activewindow] [-j]"], "only the pointer moves, then focus is checked")
                self.assertFalse(self.saved_file().exists())

    def test_second_save_keeps_the_first(self):
        self.assertEqual(self.run_script("save").returncode, 0)
        self.set_active(WIN_CHROME)
        r = self.run_script("save")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"^already saved \d+s ago; first record kept\n$")
        self.calls_file.unlink()
        r = self.run_script("restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f'hyprctl [dispatch] [hl.dsp.focus({{window="address:{WIN_A}"}})]', self.calls())

    def test_restore_when_already_focused_makes_no_focus_dispatch(self):
        self.assertEqual(self.run_script("save").returncode, 0)
        self.calls_file.unlink()
        r = self.run_script("restore")   # focus never moved, and the agent did not move the pointer
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["hyprctl [activewindow] [-j]"])
        self.assertIn(f"restored: {WIN_A} was already active; pointer left", r.stdout)
        self.assertFalse(self.saved_file().exists())

    def test_save_and_restore_log_one_line_each(self):
        self.assertEqual(self.run_script("save").returncode, 0)
        self.set_active(WIN_CHROME)
        self.assertEqual(self.run_script("restore").returncode, 0)
        lines = self.log_lines()
        saves = [x for x in lines if x.split(" ", 3)[3].startswith("save ")]
        restores = [x for x in lines if x.split(" ", 3)[3].startswith("restore ")]
        self.assertEqual(len(saves), 1, lines)
        self.assertEqual(len(restores), 1, lines)
        self.assertRegex(saves[0], rf"^\S+ run=\d{{8}}T\d{{6}}Z-\d+ elapsed=\d+s save window={WIN_A} pointer=961,553$")
        self.assertRegex(restores[0], rf"^\S+ run=\d{{8}}T\d{{6}}Z-\d+ elapsed=\d+s restore window={WIN_A} pointer=961,553 refocused$")

    # restore puts back only what the agent moved
    def test_restore_keeps_a_window_michael_switched_to(self):
        self.assertEqual(self.run_script("save").returncode, 0)
        self.calls_file.unlink()
        self.set_active(WIN_B)   # not the agent's: not agent Chrome, not focused by the agent
        self.set_cursor(300, 400)   # and the pointer is not where the agent left it
        r = self.run_script("restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp."), [], "restore dispatched focus or a pointer move over Michael's window")
        self.assertIn(f"kept focus on {WIN_B}", r.stdout)
        self.assertFalse(self.saved_file().exists())
        restores = [x.split(" ", 3)[3] for x in self.log_lines() if x.split(" ", 3)[3].startswith("restore ")]
        self.assertEqual(restores, [f"restore window={WIN_A} kept focus on {WIN_B} pointer=left"])

    def test_restore_refocuses_a_window_the_agent_focused(self):
        self.assertEqual(self.run_script("save").returncode, 0)
        self.set_active(WIN_B)   # not agent Chrome; only the focus verb says it is the agent's
        self.assertEqual(self.run_script("focus", "Steam").returncode, 0)
        self.assertIn(f"agent_window={WIN_B}", self.saved_file().read_text().splitlines())
        self.calls_file.unlink()
        r = self.run_script("restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp.focus"), [f'hyprctl [dispatch] [hl.dsp.focus({{window="address:{WIN_A}"}})]'])
        self.assertIn(MOVE_CURSORPOS, self.calls())

    def test_restore_keeps_a_window_michael_took_after_an_agent_focus(self):
        self.assertEqual(self.run_script("save").returncode, 0)
        self.set_active(WIN_B)
        self.assertEqual(self.run_script("focus", "Steam").returncode, 0)
        self.set_active("0xdddd4444")   # Michael switched again
        self.calls_file.unlink()
        r = self.run_script("restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp."), [])

    def test_restore_moves_the_pointer_back_when_it_is_where_the_agent_put_it(self):
        self.assertEqual(self.run_script("save").returncode, 0)
        self.assertEqual(self.run_script("move", "10", "20").returncode, 0)
        self.assertIn("agent_pointer=10,20", self.saved_file().read_text().splitlines())
        self.set_cursor(10, 20)
        self.set_active(WIN_B)   # Michael's window has focus: it stays, the untouched pointer goes back
        self.calls_file.unlink()
        r = self.run_script("restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp."), [MOVE_CURSORPOS])

    def test_restore_leaves_a_pointer_michael_moved(self):
        self.assertEqual(self.run_script("save").returncode, 0)
        self.assertEqual(self.run_script("click", "10", "20").returncode, 0)
        self.assertIn("agent_pointer=10,20", self.saved_file().read_text().splitlines())   # the last move or click counts
        self.set_cursor(300, 400)   # Michael moved it elsewhere
        self.set_active(WIN_B)
        self.calls_file.unlink()
        r = self.run_script("restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp."), [])

    # the pointer-only paths check focus after the pointer move, like the refocus path (follow_mouse may hand focus away)
    def agent_moved_pointer(self):
        """save, then the agent moves the pointer to 10,20, where it stays."""
        self.assertEqual(self.run_script("save").returncode, 0)
        self.assertEqual(self.run_script("move", "10", "20").returncode, 0)
        self.set_cursor(10, 20)

    def active_address(self):
        return json.loads((self.fixtures / "activewindow.json").read_text())["address"]

    def test_restore_gives_michael_his_window_back_when_the_pointer_move_hands_focus_away(self):
        self.agent_moved_pointer()
        self.set_active(WIN_B)   # Michael switched to WIN_B; the pointer is still the agent's, so it goes back
        self.calls_file.unlink()
        r = self.run_script("restore", FAKE_MOVE_FOCUS=WIN_CHROME)   # follow_mouse hands focus to the window under the pointer
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp.focus"), [f'hyprctl [dispatch] [hl.dsp.focus({{window="address:{WIN_B}"}})]'])
        self.assertEqual(self.active_address(), WIN_B, "Michael's window has focus again")
        self.assertIn(f"kept focus on {WIN_B}", r.stdout)

    def test_restore_keeps_the_saved_window_focused_when_the_pointer_move_hands_focus_away(self):
        self.agent_moved_pointer()   # the saved window never lost focus
        self.calls_file.unlink()
        r = self.run_script("restore", FAKE_MOVE_FOCUS=WIN_CHROME)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp.focus"), [f'hyprctl [dispatch] [hl.dsp.focus({{window="address:{WIN_A}"}})]'])
        self.assertEqual(self.active_address(), WIN_A)

    def test_restore_gives_back_the_window_in_use_when_no_window_was_saved_and_the_pointer_move_hands_focus_away(self):
        self.set_active(None)
        self.agent_moved_pointer()
        self.set_active(WIN_B)
        self.calls_file.unlink()
        r = self.run_script("restore", FAKE_MOVE_FOCUS=WIN_CHROME)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.active_address(), WIN_B)

    def test_restore_makes_no_focus_dispatch_when_the_pointer_move_hands_focus_nowhere(self):
        self.agent_moved_pointer()
        self.set_active(WIN_B)
        self.calls_file.unlink()
        r = self.run_script("restore")   # focus stays on WIN_B after the pointer move
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp."), [MOVE_CURSORPOS])

    # no active window when restore runs
    def test_restore_with_no_active_window_says_so_and_does_not_refocus(self):
        for none in (None, ""):   # `{}` and no output at all
            with self.subTest(active=none):
                self.saved_file().unlink(missing_ok=True)
                self.log_file().unlink(missing_ok=True)
                self.set_active(WIN_A)
                self.assertEqual(self.run_script("save").returncode, 0)
                self.set_active(none)   # for example an empty workspace
                self.calls_file.unlink(missing_ok=True)
                r = self.run_script("restore")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.dispatches("hl.dsp."), [], "restore refocused the saved window with nothing active")
                self.assertIn("no active window", r.stdout)
                self.assertNotIn("kept focus", r.stdout)
                self.assertFalse(self.saved_file().exists())
                restores = [x.split(" ", 3)[3] for x in self.log_lines() if x.split(" ", 3)[3].startswith("restore ")]
                self.assertEqual(restores, [f"restore window={WIN_A} no active window pointer=left"])

    def test_restore_with_no_active_window_still_puts_back_the_pointer_the_agent_moved(self):
        self.agent_moved_pointer()
        self.set_active(None)
        self.calls_file.unlink()
        r = self.run_script("restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp."), [MOVE_CURSORPOS])
        self.assertIn("no active window", r.stdout)

    # one record per caller: two agents running save and restore at the same time do not touch each other's record
    def as_caller(self, key, *args, **extra):
        return self.run_script(*args, T3CODE_THREAD_ID=key, **extra)

    def focus_dispatch(self, address):
        return f'hyprctl [dispatch] [hl.dsp.focus({{window="address:{address}"}})]'

    def test_two_callers_each_get_their_own_window_back(self):
        self.set_active(WIN_A)
        self.assertEqual(self.as_caller("thread-one", "save").returncode, 0)
        self.set_active(WIN_B)
        r = self.as_caller("thread-two", "save")
        self.assertEqual((r.returncode, r.stdout), (0, f"saved window {WIN_B} pointer 961,553\n"), "the second caller's save is its own")
        self.set_active(WIN_CHROME)   # both agents' work moved focus
        self.calls_file.unlink()
        r = self.as_caller("thread-one", "restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp.focus"), [self.focus_dispatch(WIN_A)])
        self.assertTrue(self.saved_file("thread-two").exists(), "the first caller's restore left the second caller's record")
        self.set_active(WIN_CHROME)
        self.calls_file.unlink()
        r = self.as_caller("thread-two", "restore")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.dispatches("hl.dsp.focus"), [self.focus_dispatch(WIN_B)])
        self.assertFalse(self.saved_file("thread-one").exists())
        self.assertFalse(self.saved_file("thread-two").exists())

    def test_a_caller_with_no_record_of_its_own_gets_nothing_saved(self):
        self.assertEqual(self.as_caller("thread-one", "save").returncode, 0)
        self.calls_file.unlink()
        r = self.as_caller("thread-two", "restore")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("nothing saved", r.stderr)
        self.assertEqual(self.calls(), [], "the second caller's restore acted on the first caller's record")
        self.assertTrue(self.saved_file("thread-one").exists())

    def test_a_second_save_by_the_same_caller_keeps_its_first_record(self):
        self.assertEqual(self.as_caller("thread-one", "save").returncode, 0)
        self.set_active(WIN_CHROME)
        r = self.as_caller("thread-one", "save")   # a separate call of the same agent: same thread id
        self.assertRegex(r.stdout, r"^already saved \d+s ago; first record kept\n$")

    def test_focus_and_move_note_the_agent_in_the_callers_own_record(self):
        self.assertEqual(self.as_caller("thread-one", "save").returncode, 0)
        self.assertEqual(self.as_caller("thread-two", "save").returncode, 0)
        self.set_active(WIN_B)
        self.assertEqual(self.as_caller("thread-one", "focus", "Steam").returncode, 0)
        self.assertEqual(self.as_caller("thread-one", "move", "10", "20").returncode, 0)
        one = self.saved_file("thread-one").read_text().splitlines()
        self.assertIn(f"agent_window={WIN_B}", one)
        self.assertIn("agent_pointer=10,20", one)
        two = self.saved_file("thread-two").read_text()
        self.assertNotIn("agent_", two, "thread-one's focus and move were written into thread-two's record")

    def test_a_caller_and_a_plain_call_do_not_share_a_record(self):
        self.assertEqual(self.run_script("save").returncode, 0)   # no key: the shared record
        self.assertEqual(self.as_caller("thread-one", "save").returncode, 0)
        self.assertTrue(self.saved_file().exists())
        self.assertTrue(self.saved_file("thread-one").exists())
        self.assertEqual(self.run_script("restore").returncode, 0)
        self.assertTrue(self.saved_file("thread-one").exists(), "a plain restore removed a caller's record")

    def test_the_claude_code_session_is_the_key_when_there_is_no_t3_thread(self):
        r = self.run_script("save", CLAUDE_CODE_SESSION_ID="sess-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.saved_file("sess-1").exists())
        self.assertEqual(self.run_script("restore", CLAUDE_CODE_SESSION_ID="sess-1").returncode, 0)
        r = self.run_script("save", T3CODE_THREAD_ID="thread-one", CLAUDE_CODE_SESSION_ID="sess-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.saved_file("thread-one").exists(), "the T3 thread comes first")
        self.assertFalse(self.saved_file("sess-1").exists())

    def test_a_key_with_slashes_and_colons_stays_one_file_in_the_state_folder(self):
        key = "mcp:launch:../../x/y z"
        self.assertEqual(self.as_caller(key, "save").returncode, 0)
        files = sorted(p.name for p in (self.home / ".state" / "agent-desktop").iterdir() if p.name.startswith("saved-focus"))
        self.assertEqual(files, ["saved-focus.mcp_launch_.._.._x_y_z"])
        self.assertEqual(self.as_caller(key, "restore").returncode, 0)

    def test_focus_move_and_click_write_no_record_when_nothing_is_saved(self):
        for args in (("focus", "Steam"), ("move", "10", "20"), ("click", "10", "20")):
            with self.subTest(verb=args[0]):
                r = self.run_script(*args)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertFalse(self.saved_file().exists())
        self.assertNotIn("hyprctl [activewindow] [-j]", self.calls(), "focus asked for the active window with no record")


@unittest.skipUnless(ZSH and LINUX, "needs zsh and /proc")
class ZshenvTest(unittest.TestCase):
    """The block in dot_zshenv, in a real non-interactive `zsh -c` (what T3, Claude Code and Codex start) with HOME holding
    dot_zshenv as ~/.zshenv and session.sh where chezmoi puts it."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ad-zsh-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.runtime = self.tmp / "runtime"
        lib = self.home / ".local/share/agent-desktop"
        lib.mkdir(parents=True)
        self.runtime.mkdir()
        shutil.copy(ZSHENV, self.home / ".zshenv")
        shutil.copy(SESSION_LIB, lib / "session.sh")

    def session(self, marker="T3CODE_THREAD_ID", **env):
        e = {"HOME": str(self.home), "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "XDG_RUNTIME_DIR": str(self.runtime)}
        if marker:
            e[marker] = "x"
        e.update(env)
        r = subprocess.run([ZSH, "-c", 'printf "%s %s" "${WAYLAND_DISPLAY-unset}" "${HYPRLAND_INSTANCE_SIGNATURE-unset}"'],
                           env=e, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.stderr, "")
        return r.stdout

    def test_an_agent_shell_gets_the_live_session_with_no_exports(self):
        make_instance(self.runtime, "aaa_1000_1", dead_pid(), display="wayland-0")
        make_instance(self.runtime, "bbb_2000_1", os.getpid())
        self.assertEqual(self.session(), "wayland-1 bbb_2000_1")

    def test_a_restart_is_followed_because_each_shell_looks_again(self):
        make_instance(self.runtime, "aaa_1000_1", os.getpid())
        self.assertEqual(self.session(), "wayland-1 aaa_1000_1")
        shutil.rmtree(self.runtime / "hypr" / "aaa_1000_1")
        make_instance(self.runtime, "bbb_2000_1", os.getpid())
        self.assertEqual(self.session(), "wayland-1 bbb_2000_1")

    def test_every_agent_marker_counts(self):
        make_instance(self.runtime, "aaa_1000_1", os.getpid())
        for marker in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "T3CODE_THREAD_ID", "CODEX_SANDBOX", "CODEX_THREAD_ID"):
            with self.subTest(marker=marker):
                self.assertEqual(self.session(marker=marker), "wayland-1 aaa_1000_1")

    def test_a_shell_that_is_not_an_agent_is_left_alone(self):
        make_instance(self.runtime, "aaa_1000_1", os.getpid())
        self.assertEqual(self.session(marker=None), "unset unset")

    def test_a_live_set_session_is_kept_and_a_dead_one_is_replaced(self):
        make_instance(self.runtime, "old_1000_1", os.getpid(), display="wayland-0")
        make_instance(self.runtime, "new_2000_1", os.getpid(), display="wayland-1")
        self.assertEqual(self.session(WAYLAND_DISPLAY="wayland-0", HYPRLAND_INSTANCE_SIGNATURE="old_1000_1"), "wayland-0 old_1000_1")
        # t3code outlived a Hyprland restart: its shells inherit the dead pair.
        self.assertEqual(self.session(WAYLAND_DISPLAY="wayland-7", HYPRLAND_INSTANCE_SIGNATURE="dead_1_1"), "wayland-1 new_2000_1")
        self.assertEqual(self.session(WAYLAND_DISPLAY="wayland-9"), "wayland-1 new_2000_1")

    def test_a_set_pair_is_kept_when_nothing_is_live(self):
        self.assertEqual(self.session(WAYLAND_DISPLAY="wayland-7", HYPRLAND_INSTANCE_SIGNATURE="dead_1_1"), "wayland-7 dead_1_1")

    def test_no_live_session_is_silent(self):
        self.assertEqual(self.session(), "unset unset")                        # no hypr folder at all
        (self.runtime / "hypr").mkdir()
        self.assertEqual(self.session(), "unset unset")                        # an empty one
        make_instance(self.runtime, "aaa_1000_1", dead_pid())
        self.assertEqual(self.session(), "unset unset")                        # only a dead one

    def test_a_host_without_session_sh_is_untouched(self):
        # The work Mac and every non-personal profile: chezmoi does not deploy the file, and ~/.zshenv does nothing.
        (self.home / ".local/share/agent-desktop/session.sh").unlink()
        make_instance(self.runtime, "aaa_1000_1", os.getpid())
        self.assertEqual(self.session(), "unset unset")


if __name__ == "__main__":
    unittest.main()
