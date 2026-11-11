"""Run the real install-pi mise task on Linux where Omarchy's system mise has already installed Pi.

The official installer refuses to replace a mise-installed Pi (exit 1). The task must remove that copy first, then install the managed one.
mise, curl and the installer are scripted; HOME is private."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
MISE = shutil.which("mise")

# The stub stands in for the `mise` the task calls. State: $T/mise-pi exists while Omarchy's copy is installed.
MISE_STUB = """#!/bin/sh
echo "mise $*" >> "$T/calls"
case "$1 $2 $3" in
  "ls --installed pi") [ -f "$T/mise-pi" ] && echo "pi  1.5.2  /etc/mise/conf.d/omarchy-tools.toml  latest"; exit 0 ;;
esac
case "$1" in
  uninstall) rm -f "$T/mise-pi" "$T/bin/pi"; exit 0 ;;
  reshim) exit 0 ;;
  run) exit 0 ;;   # apply-pi-patches
esac
exit 91
"""

# Stands in for pi.dev/install.sh: refuses like the real one when a mise-installed pi is on PATH, else installs the managed copy.
INSTALLER = """set -eu
found=$(command -v pi 2>/dev/null || true)
case "$found" in
  */mise/*|"$T"/bin/pi) echo "Managed install refused to replace Pi at $found. Uninstall it first." >&2; exit 1 ;;
esac
mkdir -p "$HOME/.pi/agent/bin" "$HOME/.pi/agent/install"
printf '#!/bin/sh\\necho 1.2.0\\n' > "$HOME/.pi/agent/bin/pi"; chmod +x "$HOME/.pi/agent/bin/pi"
echo 1.2.0 > "$HOME/.pi/agent/install/current-version"
echo installed >> "$T/calls"
"""

CURL = """#!/bin/sh
while [ $# -gt 0 ]; do [ "$1" = -o ] && out=$2; shift; done
cp "$T/installer.sh" "$out"
"""


@unittest.skipUnless(MISE and sys.platform.startswith("linux"), "Linux and mise are required")
class InstallPiMiseCopyTests(unittest.TestCase):
    def run_task(self, *, omarchy_pi, runs=1, deploy_linux_conf=True):
        with tempfile.TemporaryDirectory(prefix="install-pi-test-") as temporary:
            t = Path(temporary)
            home, project, mock = t / "home", t / "project", t / "bin"
            for d in (home, project, mock):
                d.mkdir()
            task = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())["tasks"]["install-pi"]
            (project / "mise.toml").write_text("[tasks.install-pi]\nrun = " + json.dumps(task["run"]) + "\n")
            (t / "config/mise").mkdir(parents=True, exist_ok=True)
            (t / "config/mise/config.toml").write_text("")
            if deploy_linux_conf:
                (t / "config/mise/conf.d").mkdir(parents=True)
                shutil.copy2(ROOT / "dot_config/mise/conf.d/linux.toml", t / "config/mise/conf.d/linux.toml")
            for name, text in (("mise", MISE_STUB), ("curl", CURL)):
                (mock / name).write_text(text)
                (mock / name).chmod(0o700)
            (t / "installer.sh").write_text(INSTALLER)
            if omarchy_pi:
                (t / "mise-pi").write_text("")
                (mock / "pi").write_text("#!/bin/sh\necho omarchy\n")   # lives in the PATH at <test>/bin, the stand-in for mise's install dir
                (mock / "pi").chmod(0o700)
            (t / "etc/conf.d").mkdir(parents=True)   # stands in for /etc/mise: Omarchy's lazy Pi
            (t / "etc/conf.d/omarchy-tools.toml").write_text('[tools]\npi = { version = "latest", lazy = true }\n')
            env = {"MISE_SYSTEM_CONFIG_DIR": str(t / "etc"), "HOME": str(home), "PATH": f"{mock}:/usr/bin:/bin", "T": str(t), "TMPDIR": str(t),
                   "XDG_CONFIG_HOME": str(t / "config"),
                   "MISE_DATA_DIR": str(t / "mise-data"), "MISE_CACHE_DIR": str(t / "mise-cache"),
                   "MISE_TRUSTED_CONFIG_PATHS": str(project), "MISE_YES": "1"}
            outputs = []
            for _ in range(runs):
                done = subprocess.run([MISE, "run", "install-pi"], cwd=project, env=env, text=True, capture_output=True, timeout=60)
                outputs.append(done)
            calls = (t / "calls").read_text().splitlines() if (t / "calls").exists() else []
            return outputs, calls, (home / ".pi/agent/bin/pi").exists()

    def test_omarchy_copy_is_removed_then_the_managed_install_succeeds(self):
        (done,), calls, managed = self.run_task(omarchy_pi=True)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(managed)
        self.assertLess(calls.index("mise uninstall --all --yes pi"), calls.index("installed"))
        self.assertIn("mise reshim", calls)

    def test_without_a_mise_copy_nothing_is_uninstalled(self):
        (done,), calls, managed = self.run_task(omarchy_pi=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(managed)
        self.assertFalse([c for c in calls if c.startswith("mise uninstall")], calls)

    def pi_seen_by_a_task(self, deploy_linux_conf):
        """Real mise only: Omarchy's Pi is installed under the data dir; what does `command -v pi` see inside `mise run`?"""
        with tempfile.TemporaryDirectory(prefix="install-pi-visible-") as temporary:
            t = Path(temporary)
            project = t / "project"
            for d in (project, t / "etc/conf.d", t / "config/mise/conf.d"):
                d.mkdir(parents=True)
            (t / "etc/conf.d/omarchy-tools.toml").write_text('[tools]\npi = { version = "latest", lazy = true }\n')
            installed = t / "data/installs/pi/1.5.2/pi"
            installed.mkdir(parents=True)
            (installed / "pi").write_text("#!/bin/sh\n")
            (installed / "pi").chmod(0o755)
            (t / "data/installs/pi/latest").symlink_to("1.5.2")
            (t / "config/mise/config.toml").write_text("")
            if deploy_linux_conf:
                shutil.copy2(ROOT / "dot_config/mise/conf.d/linux.toml", t / "config/mise/conf.d/linux.toml")
            (project / "mise.toml").write_text('[tasks.t]\nrun = "command -v pi || echo none"\n')
            env = {"HOME": str(t / "home"), "PATH": "/usr/bin:/bin", "XDG_CONFIG_HOME": str(t / "config"), "MISE_SYSTEM_CONFIG_DIR": str(t / "etc"),
                   "MISE_DATA_DIR": str(t / "data"),
                   "MISE_CACHE_DIR": str(t / "cache"), "MISE_TRUSTED_CONFIG_PATHS": str(project), "MISE_YES": "1"}
            done = subprocess.run([MISE, "run", "t"], cwd=project, env=env, text=True, capture_output=True, timeout=30)
            return done.stdout + done.stderr

    def test_the_linux_setting_hides_the_installed_system_pi_from_tasks(self):
        self.assertIn("/installs/pi/", self.pi_seen_by_a_task(deploy_linux_conf=False))   # old behavior: the installer would refuse this
        self.assertNotIn("/installs/pi/", self.pi_seen_by_a_task(deploy_linux_conf=True))

    def test_a_second_run_leaves_the_managed_install_alone(self):
        (first, second), calls, _ = self.run_task(omarchy_pi=True, runs=2)
        self.assertEqual((first.returncode, second.returncode), (0, 0), second.stdout + second.stderr)
        self.assertEqual(calls.count("installed"), 1)
        self.assertEqual(len([c for c in calls if c.startswith("mise uninstall")]), 1)


if __name__ == "__main__":
    unittest.main()
