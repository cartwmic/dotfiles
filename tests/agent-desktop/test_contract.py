"""c5: one list of bad calls, three scripts. The same command means the same thing on every computer.

The Linux script (dot_local/bin/executable_agent-desktop, stub Hyprland tools), the macOS script
(.chezmoitemplates/agent-desktop-macos.sh, stub screencapture and osascript) and the Windows script (windows/agent-desktop.ps1,
under PowerShell 7 with the stub task module) all get the same bad calls. Each must exit 2, run no tool and write nothing.

Two kinds of bad call, and what is asserted for each:
  * WRONG SHAPE (no arguments, an unknown action, a missing or extra argument): exit 2 and the usage on stderr, which names all
    eight actions. All three scripts print the usage for these.
  * BAD VALUE (`move` with a non-integer, `click` with an unknown button, `key` with a bad word): exit 2 and an error line that
    starts with the action's name. The Linux and macOS scripts print only that line here, not the usage; the Windows script
    prints the line and the usage. The usage is therefore not asserted for bad values: it would pin Windows to a behaviour the
    other two do not have, and the Linux script may not change (c2). Decision logged in the lane W report.
Each script owns its detail tests (test_agent_desktop.py, test_macos.py, test_windows_bridge.py); this file only holds what the
three must agree on.
Run: mise exec aqua:PowerShell/PowerShell@7.7.0 -- python3 -m unittest discover -s tests/agent-desktop -p test_contract.py
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_agent_desktop as linux
import test_macos as mac
import windows_testlib as wt

# The eight actions every script names in its usage.
EIGHT = wt.EIGHT

# Wrong shape: exit 2 and the usage.
SHAPE_CALLS = [
    [],
    ["frobnicate"],
    ["focus"],
    ["shot"],
    ["windows", "extra"],
    ["move", "1"],
    ["click"],
    ["type"],
    ["key"],
    ["cursor", "extra"],
]

# Bad value: exit 2 and an error line "<action>: ...". One entry per bad value the contract names.
VALUE_CALLS = [
    ["move", "x", "2"],
    ["move", "1", "2.5"],
    ["click", "1", "2", "wheel"],
    ["click", "1", "2", "RIGHT"],  # buttons are lower case everywhere; the G14 once took RIGHT and did a left click
    ["click", "a", "2"],
    ["key", "bad word!"],
    ["key", "comma", "ct rl"],
]


def check_contract(case, run, nothing_happened):
    """The one test body. `run(argv)` runs a script and returns a CompletedProcess; `nothing_happened()` returns a problem or ''."""
    for argv in SHAPE_CALLS:
        with case.subTest(kind="shape", argv=argv):
            r = run(argv)
            case.assertEqual(r.returncode, 2, (r.stdout, r.stderr))
            case.assertIn("usage:", r.stderr)
            for action in EIGHT:
                case.assertIn(action, r.stderr, "usage must name %s" % action)
            case.assertEqual(nothing_happened(), "")
    for argv in VALUE_CALLS:
        with case.subTest(kind="value", argv=argv):
            r = run(argv)
            case.assertEqual(r.returncode, 2, (r.stdout, r.stderr))
            case.assertIn("%s:" % argv[0], r.stderr, "the error must name the action")
            case.assertEqual(r.stdout, "")
            case.assertEqual(nothing_happened(), "")


class ContractTest(unittest.TestCase):
    def test_linux_script(self):
        tmp = Path(tempfile.mkdtemp(prefix="adc-linux-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        home, runtime, fixtures = tmp / "home", tmp / "runtime", tmp / "fixtures"
        for d in (home, runtime, fixtures):
            d.mkdir()
        calls = tmp / "calls"
        bin_dir = linux.make_bin(tmp / "bin", linux.TOOLS)
        env = {
            "PATH": str(bin_dir), "HOME": str(home), "XDG_STATE_HOME": str(home / ".state"), "XDG_RUNTIME_DIR": str(runtime),
            "WAYLAND_DISPLAY": "wayland-1", "HYPRLAND_INSTANCE_SIGNATURE": "sig_test",
            "FAKE_CALLS": str(calls), "FAKE_ENV": str(tmp / "env"), "FAKE_FIXTURES": str(fixtures),
        }

        def run(argv):
            return subprocess.run(["/bin/sh", str(linux.SCRIPT), *argv], env=env, capture_output=True, text=True, timeout=30)

        def nothing_happened():
            return "a tool was called" if calls.exists() else ""

        check_contract(self, run, nothing_happened)

    def test_macos_script(self):
        tmp = Path(tempfile.mkdtemp(prefix="adc-mac-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        home, fixtures = tmp / "home", tmp / "fixtures"
        for d in (home, fixtures):
            d.mkdir()
        calls = tmp / "calls"
        bin_dir = mac.make_bin(tmp / "bin", mac.TOOLS)
        env = {
            "PATH": str(bin_dir), "HOME": str(home), "XDG_STATE_HOME": str(home / ".state"),
            "FAKE_CALLS": str(calls), "FAKE_FIXTURES": str(fixtures),
        }

        def run(argv):
            return subprocess.run(["/bin/sh", str(mac.BODY), *argv], env=env, capture_output=True, text=True, timeout=30)

        def nothing_happened():
            return "a tool was called" if calls.exists() else ""

        check_contract(self, run, nothing_happened)


class WindowsContractTest(wt.WindowsTestCase):
    def test_windows_script(self):
        box = wt.Sandbox(self)
        script = wt.WINDOWS / "agent-desktop.ps1"
        env = box.env(AD_STUB_MODE="answer")

        def run(argv):
            return box.run(script, *argv, env=env)

        def nothing_happened():
            if box.state_files():
                return "files written: %s" % box.state_files()
            if box.calls():
                return "the task was started: %s" % box.calls()
            return ""

        check_contract(self, run, nothing_happened)


if __name__ == "__main__":
    unittest.main()
