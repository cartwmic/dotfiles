"""install_t3.sh in pinned mode (container mode, run_onchange_after_05_container_tools.sh.tmpl): install exactly the pinned T3 release.

The real script runs in a private HOME with the real curl and sha256sum against a file:// mirror of the release (T3CODE_RELEASE_BASE_URL, the installer's
own variable) and a stand-in for https://t3.codes/install.sh (T3_INSTALL_URL) that records what it was asked for and installs a `t3` that prints
`t3 v<T3CODE_VERSION>`. Unpinned mode (script 74) is covered by tests/t3-service.
"""
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/user_scripts/executable_install_t3.sh"
TEMPLATE = ROOT / "run_onchange_after_05_container_tools.sh.tmpl"
PIN = "0.1.10-nightly.20261116.4800"
ARCH = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}[os.uname().machine]
ARCHIVE = f"t3-{PIN}-linux-{ARCH}.tar.gz"
# What the stand-in installer does: note it ran and with which version, then write the launcher the real one writes (a `t3` that reports that version).
INSTALLER = '''#!/bin/sh
echo "installer version=${T3CODE_VERSION:-}" >> "$CALLS"
mkdir -p "$HOME/.local/bin"
v=${FAKE_INSTALLS:-${T3CODE_VERSION:-stable}}
printf '#!/bin/sh\\necho "t3 v%s"\\n' "$v" > "$HOME/.local/bin/t3"
chmod 755 "$HOME/.local/bin/t3"
'''


def write_exec(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class PinnedInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home, self.calls = root / "home", root / "calls"
        self.home.mkdir()
        self.calls.write_text("")
        mirror = root / "mirror" / f"v{PIN}"
        mirror.mkdir(parents=True)
        (mirror / ARCHIVE).write_bytes(b"the release archive")
        self.sha = hashlib.sha256(b"the release archive").hexdigest()
        self.mirror = root / "mirror"
        write_exec(root / "installer.sh", INSTALLER)
        self.installer = root / "installer.sh"

    def have_t3(self, version):
        write_exec(self.home / ".local/bin/t3", f'#!/bin/sh\necho "t3 v{version}"\n')

    def run_script(self, sha=None, **extra):
        sha = self.sha if sha is None else sha
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "CALLS": str(self.calls), "T3_PIN_VERSION": PIN,
               "T3_PIN_SHA256_X64": sha, "T3_PIN_SHA256_ARM64": sha,
               "T3CODE_RELEASE_BASE_URL": f"file://{self.mirror}", "T3_INSTALL_URL": f"file://{self.installer}", **extra}
        return subprocess.run(["/bin/sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)

    def installed(self):
        return self.calls.read_text().splitlines()

    def version(self):
        return subprocess.run([str(self.home / ".local/bin/t3"), "--version"], capture_output=True, text=True).stdout.strip()

    def test_a_pod_on_an_older_version_is_moved_to_the_pin(self):
        self.have_t3("0.1.9")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.installed(), [f"installer version={PIN}"])
        self.assertEqual(self.version(), f"t3 v{PIN}")

    def test_a_fresh_pod_gets_the_pin_not_the_latest_stable(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.installed(), [f"installer version={PIN}"])
        self.assertEqual(self.version(), f"t3 v{PIN}")

    def test_a_pod_already_on_the_pin_downloads_and_installs_nothing(self):
        self.have_t3(PIN)
        shutil.rmtree(self.mirror)   # a download would fail
        r = self.run_script(T3_INSTALL_URL="file:///nonexistent")
        self.assertEqual((r.returncode, self.installed()), (0, []), r.stdout + r.stderr)

    def test_an_archive_that_does_not_match_the_pinned_sha256_installs_nothing_and_fails(self):
        self.have_t3("0.1.9")
        r = self.run_script(sha="0" * 64)
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not match the pinned sha256", r.stdout)
        self.assertEqual(self.installed(), [])
        self.assertEqual(self.version(), "t3 v0.1.9")

    def test_a_cpu_with_no_pinned_sha256_fails_rather_than_installing_unchecked(self):
        r = self.run_script(sha="", T3_PIN_SHA256_X64="", T3_PIN_SHA256_ARM64="")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no sha256 pinned", r.stdout)
        self.assertEqual(self.installed(), [])

    def test_a_release_that_is_not_there_fails(self):
        shutil.rmtree(self.mirror / f"v{PIN}")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not download", r.stdout)
        self.assertEqual(self.installed(), [])

    def test_an_install_that_leaves_a_different_version_fails(self):
        self.have_t3("0.1.9")
        r = self.run_script(FAKE_INSTALLS="0.1.9")
        self.assertEqual(r.returncode, 1)
        self.assertIn(f'not "t3 v{PIN}"', r.stdout)


class PinInTheTools(unittest.TestCase):
    """The pin is data, script 05 carries it into install_t3.sh, and a changed pin changes script 05's text so chezmoi runs it again."""

    @staticmethod
    def render(**t3pin):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "c.yaml"
            cfg.write_text("{}\n")
            data = {"profile": "personal", "container": {"enabled": True}, "chezmoi": {"os": "linux", "homeDir": "/home/agent", "sourceDir": str(ROOT)}}
            if t3pin:
                data["t3Pin"] = t3pin
            return subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "execute-template", "--override-data", json.dumps(data)],
                                  input=TEMPLATE.read_text(), text=True, capture_output=True, timeout=60, check=True).stdout

    def pin(self):
        return tomllib.loads((ROOT / ".chezmoidata.toml").read_text())["t3Pin"]

    def test_the_pin_has_a_version_and_a_sha256_for_each_cpu(self):
        pin = self.pin()
        self.assertRegex(pin["version"], r"^\d+\.\d+\.\d+(-nightly\.\d+\.\d+)?$")
        for key in ("sha256X64", "sha256Arm64"):
            self.assertRegex(pin[key], r"^[0-9a-f]{64}$")

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
    def test_script_05_hands_the_pin_to_the_installer(self):
        pin, text = self.pin(), self.render()
        self.assertIn(f"T3_PIN_VERSION='{pin['version']}' T3_PIN_SHA256_X64='{pin['sha256X64']}' T3_PIN_SHA256_ARM64='{pin['sha256Arm64']}'", text)

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
    def test_changing_the_pin_changes_script_05_so_chezmoi_reruns_it(self):
        pin = self.pin()
        base = self.render(**{k: pin[k] for k in pin})
        for key in pin:
            self.assertNotEqual(self.render(**{**pin, key: pin[key] + "x"}), base, key)


if __name__ == "__main__":
    unittest.main()
