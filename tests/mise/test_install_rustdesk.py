"""The install-rustdesk mise task, run as written in config.toml with scripted chezmoi, uname, pacman, yay and brew on a PATH that has
nothing else (so a real apt-get or brew on the CI host is never reached). Personal Arch installs rustdesk-bin with yay; the work Mac
installs the cask (client only); work on Linux and other profiles skip."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
TASK = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())["tasks"]["install-rustdesk"]["run"]


@unittest.skipUnless(shutil.which("jq") and not Path("/Applications/RustDesk.app").exists(), "jq is required; host must not have RustDesk.app")
class InstallRustdesk(unittest.TestCase):
    def run_task(self, profile, system, *, pacman_has=None, yay=True):
        with tempfile.TemporaryDirectory(prefix="rustdesk-task-") as tmp:
            t = Path(tmp)
            bin_ = t / "bin"
            bin_.mkdir()
            for tool in ("sh", "jq", "grep", "cat", "head"):
                (bin_ / tool).symlink_to(shutil.which(tool))
            scripts = {
                "chezmoi": "#!/bin/sh\necho '%s'\n" % json.dumps({"profile": profile}),
                "uname": "#!/bin/sh\necho %s\n" % system,
                "brew": '#!/bin/sh\necho "brew $*" >> "$T/calls"\n',
                "pacman": '#!/bin/sh\n[ "$2" = "%s" ] && echo "$2 1.5.1-1"\n' % (pacman_has or "none"),
            }
            if yay:
                scripts["yay"] = '#!/bin/sh\necho "yay $*" >> "$T/calls"\n'
            for name, body in scripts.items():
                (bin_ / name).write_text(body)
                (bin_ / name).chmod(0o755)
            done = subprocess.run([str(bin_ / "sh"), "-c", TASK], env={"PATH": str(bin_), "T": str(t), "HOME": str(t)},
                                  text=True, capture_output=True, timeout=30)
            calls = (t / "calls").read_text().splitlines() if (t / "calls").exists() else []
            return done, calls

    def test_personal_arch_installs_rustdesk_bin_with_yay(self):
        done, calls = self.run_task("personal", "Linux")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(calls, ["yay -S --noconfirm --needed rustdesk-bin"])

    def test_personal_arch_with_rustdesk_installed_does_nothing(self):
        done, calls = self.run_task("personal", "Linux", pacman_has="rustdesk-bin")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(calls, [])
        self.assertIn("already installed", done.stdout)

    def test_personal_arch_without_yay_fails_with_a_pointer(self):
        done, calls = self.run_task("personal", "Linux", yay=False)
        self.assertEqual(done.returncode, 1)
        self.assertIn("needs yay", done.stdout)

    def test_work_mac_installs_the_cask(self):
        done, calls = self.run_task("axon-work-computer", "Darwin")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(calls, ["brew install --cask rustdesk"])

    def test_work_linux_and_other_profiles_skip(self):
        for profile, system in (("axon-work-computer", "Linux"), ("termux", "Linux"), ("", "Darwin")):
            done, calls = self.run_task(profile, system)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            self.assertEqual(calls, [])
            self.assertIn("Skipping RustDesk", done.stdout)


if __name__ == "__main__":
    unittest.main()
