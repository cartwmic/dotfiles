"""run_onchange_after_74_t3_service_linux.sh.tmpl: install T3 and its service on a Linux host that has none, reload (never restart) one that has.

The real script (its two template hash comments dropped) and the install_t3.sh it calls run in a private HOME with scripted systemctl, t3 and curl that record every call.
"""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "run_onchange_after_74_t3_service_linux.sh.tmpl"
HELPER = ROOT / "dot_local/user_scripts/executable_install_t3.sh"   # the installer step the script calls from ~/.local/user_scripts
SYSTEMCTL = '''#!/bin/sh
[ "$1" = --user ] || exit 2
shift
echo "systemctl $*" >> "$CALLS"
[ ! -e "$STUB/FAIL_$(echo "$1" | tr a-z- A-Z_)" ] || { echo "boom" >&2; exit 1; }
[ "$1" != show-environment ] || [ ! -e "$STUB/NO_MANAGER" ]
'''
T3 = '''#!/bin/sh
echo "t3 $*" >> "$CALLS"
[ ! -e "$STUB/FAIL_T3_INSTALL" ] || exit 1
mkdir -p "$HOME/.config/systemd/user"; : > "$HOME/.config/systemd/user/t3code.service"
'''
CURL = '''#!/bin/sh
echo "curl $*" >> "$CALLS"
[ ! -e "$STUB/FAIL_CURL" ] || exit 22
# the "installer" (written to the -o file): puts a t3 in ~/.local/bin
while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
printf '%s\\n' 'mkdir -p "$HOME/.local/bin"' "cp '$STUB_T3' \\"\\$HOME/.local/bin/t3\\"" > "$out"
'''


def write_exec(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class T3Service(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home, self.stub, self.bin = root / "home", root / "stub", root / "bin"
        self.home.mkdir()
        self.stub.mkdir()
        self.calls = root / "calls"
        self.calls.write_text("")
        write_exec(self.bin / "systemctl", SYSTEMCTL)
        write_exec(self.stub / "t3-binary", T3)
        write_exec(self.bin / "curl", CURL)
        write_exec(self.home / ".local/user_scripts/install_t3.sh", HELPER.read_text())
        self.script = root / "script.sh"
        self.script.write_text("".join(line for line in TEMPLATE.read_text().splitlines(True) if "{{" not in line))
        self.unit = self.home / ".config/systemd/user/t3code.service"

    def have_t3(self):
        write_exec(self.home / ".local/bin/t3", T3)

    def flag(self, name):
        (self.stub / name).write_text("")

    def run_script(self, **extra):
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home), "CALLS": str(self.calls), "STUB": str(self.stub), "STUB_T3": str(self.stub / "t3-binary"),
               "T3_WSL_MARKER": str(Path(self.tmp.name) / "no-wsl"), **extra}
        return subprocess.run(["/bin/sh", str(self.script)], env=env, capture_output=True, text=True, timeout=60)

    def log(self):
        return self.calls.read_text().splitlines()

    def test_a_host_with_t3_and_its_unit_is_reloaded_not_restarted(self):
        self.have_t3()
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text("")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log(), ["systemctl show-environment", "systemctl daemon-reload"])
        self.assertIn("a running T3 keeps its old PATH", r.stdout)

    def test_a_host_with_t3_and_no_unit_installs_the_service_then_reloads_and_restarts(self):
        self.have_t3()
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log(), ["systemctl show-environment", "t3 service install", "systemctl daemon-reload", "systemctl restart t3code.service"])
        self.assertTrue(self.unit.exists())

    def test_a_host_without_t3_runs_the_installer_first(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        log = self.log()
        self.assertTrue(log[1].startswith("curl -fsSL https://t3.codes/install.sh -o "), log)
        self.assertEqual(log[2:], ["t3 service install", "systemctl daemon-reload", "systemctl restart t3code.service"])

    def test_wsl_and_a_host_with_no_user_manager_do_nothing_and_exit_0(self):
        marker = Path(self.tmp.name) / "wsl"
        marker.write_text("")
        r = self.run_script(T3_WSL_MARKER=str(marker))
        self.assertEqual((r.returncode, self.log()), (0, []))
        self.assertIn("WSL", r.stdout)
        self.flag("NO_MANAGER")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.log(), ["systemctl show-environment"])
        self.assertIn("no systemd user manager", r.stdout)

    def test_a_failed_daemon_reload_warns_and_does_not_fail_the_apply(self):
        self.have_t3()
        self.unit.parent.mkdir(parents=True)
        self.unit.write_text("")
        self.flag("FAIL_DAEMON_RELOAD")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("WARN: systemctl --user daemon-reload failed", r.stdout)
        self.assertNotIn("systemctl restart t3code.service", self.log())

    def test_a_failed_restart_of_a_fresh_install_warns_and_does_not_fail_the_apply(self):
        self.have_t3()
        self.flag("FAIL_RESTART")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("WARN: could not restart t3code.service", r.stdout)

    def test_a_failed_install_fails_so_the_next_apply_retries(self):
        self.flag("FAIL_CURL")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("T3 install failed: could not download the installer", r.stdout)
        self.assertEqual(self.log()[-1].split()[0], "curl")
        self.assertFalse(self.unit.exists())
        self.have_t3()
        self.flag("FAIL_T3_INSTALL")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("t3 service install failed", r.stdout)


DROPIN = ROOT / "dot_config/systemd/user/t3code.service.d/10-path.conf.tmpl"


def chezmoi_render(path):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "c.yaml"
        cfg.write_text("{}\n")
        return subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "execute-template", "--override-data",
                               json.dumps({"profile": "personal", "chezmoi": {"os": "linux", "homeDir": "/home/test", "sourceDir": str(ROOT)}})],
                              input=path.read_text(), text=True, capture_output=True, timeout=60, check=True).stdout


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class DropInShell(unittest.TestCase):
    """The agents' Bash tool runs $SHELL; the 1Password token and the op shim are in ~/.zshenv, which only zsh reads."""

    def test_the_drop_in_sets_shell_to_zsh_and_keeps_the_path(self):
        out = chezmoi_render(DROPIN)
        self.assertEqual(re.findall(r"^Environment=SHELL=(.*)$", out, re.M), ["/usr/bin/zsh"])
        self.assertIn("Environment=PATH=/home/test/.local/share/gh-wrapper/bin:/home/test/.local/share/mise/shims:", out)
        self.assertEqual(out.count("[Service]"), 1)

    def test_changing_the_drop_in_changes_the_install_scripts_hash_so_chezmoi_reruns_it(self):
        script = chezmoi_render(TEMPLATE)
        recorded = re.search(r"^# drop-in: ([0-9a-f]{64})$", script, re.M).group(1)
        self.assertEqual(recorded, hashlib.sha256(DROPIN.read_bytes()).hexdigest())


class AgentFence(unittest.TestCase):
    """dot_config/systemd/user/app-t3code.slice.d/90-agent-fence.conf: the agents' parent slice may only be throttled, never made to kill."""
    DROPIN = ROOT / "dot_config/systemd/user/app-t3code.slice.d/90-agent-fence.conf"

    def settings(self):
        return dict(line.split("=", 1) for line in self.DROPIN.read_text().splitlines() if re.match(r"^[A-Za-z]+=", line))

    def test_it_throttles_with_a_memory_high_and_a_low_cpu_weight(self):
        s = self.settings()
        self.assertRegex(s.get("MemoryHigh", ""), r"^\d+[KMGT]?$")
        self.assertLess(int(s["CPUWeight"]), 100)

    def test_it_sets_nothing_that_can_kill_a_process(self):
        # MemoryMax, MemorySwapMax, TasksMax and an OOM policy can end an agent; T3 owns its own MemoryMax on the child slice and this file must not add to it.
        self.assertEqual(set(self.settings()), {"MemoryHigh", "CPUWeight"}, "this drop-in only throttles: use MemoryHigh and CPUWeight")

    def test_its_name_sorts_after_t3s_runtime_drop_ins(self):
        self.assertGreater(self.DROPIN.name, "50-MemoryHigh.conf")   # T3's set-property --runtime writes 50-*.conf; the later name wins at each reload

    def test_the_service_script_reloads_when_it_changes(self):
        self.assertIn('include "dot_config/systemd/user/app-t3code.slice.d/90-agent-fence.conf"', TEMPLATE.read_text())


if __name__ == "__main__":
    unittest.main()
