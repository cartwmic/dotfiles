"""run_onchange_after_87_tmp_on_disk_linux.sh: masks tmp.mount once, and not again.

The script is plain sh, so it runs as it ships. `systemctl` and `sudo` are stubs on PATH backed by a state file, so nothing here touches
the real system. The profile half renders the real source with chezmoi in a throwaway HOME: the script is managed on personal and absent on work.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
SCRIPT = ROOT / "run_onchange_after_87_tmp_on_disk_linux.sh"
NAME = "87_tmp_on_disk_linux.sh"

SYSTEMCTL = """#!/bin/sh
state="$STUB_DIR/state"
echo "systemctl $*" >> "$STUB_DIR/calls"
case "$1" in
  cat) [ -z "${STUB_NO_UNIT:-}" ] ;;
  is-enabled) cat "$state" 2>/dev/null || echo static ;;
  mask) [ -z "${STUB_MASK_FAILS:-}" ] && echo masked > "$state" ;;
esac
"""
SUDO = """#!/bin/sh
echo "sudo $*" >> "$STUB_DIR/calls"
[ "$1" = -n ] && shift
exec "$@"
"""


class TmpOnDisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        self.stub = d / "stub"
        (self.stub / "bin").mkdir(parents=True)
        for name, body in (("systemctl", SYSTEMCTL), ("sudo", SUDO)):
            f = self.stub / "bin" / name
            f.write_text(body)
            f.chmod(0o755)
        (d / "systemd").mkdir()
        self.env = {"PATH": f"{self.stub / 'bin'}:{os.environ['PATH']}", "STUB_DIR": str(self.stub),
                    "TMP_ON_DISK_SYSTEMD_DIR": str(d / "systemd"), "TMP_ON_DISK_WSL_MARKER": str(d / "no-wsl")}

    def run_script(self, **extra):
        return subprocess.run(["/bin/sh", str(SCRIPT)], env={**self.env, **extra}, capture_output=True, text=True, timeout=60)

    def calls(self):
        f = self.stub / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def masks(self):
        return [c for c in self.calls() if c.startswith("systemctl mask")]

    @unittest.skipIf(os.getuid() == 0, "as root the script does not use sudo")
    def test_masks_tmp_mount_through_sudo_and_a_second_run_does_nothing(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.masks(), ["systemctl mask tmp.mount"])
        self.assertIn("sudo -n systemctl mask tmp.mount", self.calls())
        self.assertIn("masked", (self.stub / "state").read_text())
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already masked", r.stdout)
        self.assertEqual(self.masks(), ["systemctl mask tmp.mount"])   # still just the first run's mask

    def test_a_failed_mask_fails_the_script_so_the_next_apply_retries(self):
        r = self.run_script(STUB_MASK_FAILS="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ERROR", r.stdout)

    def test_no_running_systemd_or_no_unit_is_a_clean_exit_with_no_mask(self):
        r = self.run_script(TMP_ON_DISK_SYSTEMD_DIR=str(self.stub / "missing"))
        self.assertEqual((r.returncode, self.masks()), (0, []))
        r = self.run_script(STUB_NO_UNIT="1")
        self.assertEqual((r.returncode, self.masks()), (0, []))

    def test_wsl_is_left_alone(self):
        marker = self.stub / "wsl"
        marker.write_text("")
        r = self.run_script(TMP_ON_DISK_WSL_MARKER=str(marker))
        self.assertEqual((r.returncode, self.calls()), (0, []))

    def test_script_is_managed_on_personal_linux_and_absent_on_work(self):
        def managed(profile):
            with tempfile.TemporaryDirectory() as t:
                home = Path(t) / "home"
                home.mkdir()
                cfg = Path(t) / "chezmoi.yaml"
                cfg.write_text("data:\n  profile: %s\n" % profile)
                r = subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home), "managed"],
                                   capture_output=True, text=True, env=source_tree.chezmoi_env(home), timeout=120)
                self.assertEqual(r.returncode, 0, r.stderr)
                return set(r.stdout.split())
        self.assertIn(NAME, managed("personal"))
        self.assertNotIn(NAME, managed("axon-work-computer"))


if __name__ == "__main__":
    unittest.main()
