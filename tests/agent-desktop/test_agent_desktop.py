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
        self.calls_file = self.tmp / "calls"
        self.env_file = self.tmp / "env"
        self.bin = make_bin(self.tmp / "bin", TOOLS)
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
        for marker in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "T3CODE_THREAD_ID", "HERDR_ENV", "CODEX_SANDBOX", "CODEX_THREAD_ID"):
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
