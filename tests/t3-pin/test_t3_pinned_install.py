"""install_t3.sh in pinned mode (container mode, run_onchange_after_05_container_tools.sh.tmpl): install exactly the pinned T3 release.

The real script runs in a private HOME with the real curl, tar and sha256sum against a file:// mirror of the release (T3CODE_RELEASE_BASE_URL, the
installer's own variable; the real installer needs http(s), the stand-in does not download) and a stand-in for https://t3.codes/install.sh
(T3_INSTALL_URL). The stand-in behaves like the real one for a version that is already unpacked and marked .install-complete: it writes the `t3` launcher
and downloads nothing. Unpinned mode (script 74) is covered by tests/t3-service.
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
# The stand-in installer. Like the real one it skips a version that is marked complete and writes the launcher; FAKE_REDOWNLOAD makes it fetch the release
# itself instead (as the real one would if its layout changed); FAKE_REEXTRACT unpacks the same bytes again into the same folder (a fresh folder, so any
# file added to it is gone); FAKE_RELOCATE unpacks different bytes in another folder and points the launcher there; FAKE_INSTALLS makes the launcher
# report another version.
INSTALLER = '''#!/bin/sh
echo "installer version=${T3CODE_VERSION:-}" >> "$CALLS"
dir=${T3CODE_HOME:-$HOME/.t3}/runtime/versions/$T3CODE_VERSION
if [ -n "${FAKE_REEXTRACT:-}" ]; then cp "$dir/t3" /tmp/same-t3.$$; rm -rf "$dir"; mkdir -p "$dir"; mv /tmp/same-t3.$$ "$dir/t3"; echo "$T3CODE_VERSION" > "$dir/.install-complete"; fi
if [ -n "${FAKE_RELOCATE:-}" ]; then
  dir=${T3CODE_HOME:-$HOME/.t3}/runtime/v2/versions/$T3CODE_VERSION
  mkdir -p "$dir"; printf '#!/bin/sh\\necho "t3 v%s"\\n# unchecked bytes\\n' "$T3CODE_VERSION" > "$dir/t3"; chmod 755 "$dir/t3"; echo "$T3CODE_VERSION" > "$dir/.install-complete"
fi
if [ -n "${FAKE_REDOWNLOAD:-}" ] || [ "$(cat "$dir/.install-complete" 2>/dev/null)" != "$T3CODE_VERSION" ]; then
  mkdir -p "$dir"; printf '#!/bin/sh\\necho "t3 v%s"\\n# other bytes\\n' "$T3CODE_VERSION" > "$dir/t3"; chmod 755 "$dir/t3"; echo "$T3CODE_VERSION" > "$dir/.install-complete"
fi
mkdir -p "$HOME/.local/bin"
if [ -n "${FAKE_INSTALLS:-}" ]; then printf '#!/bin/sh\\necho "t3 v%s"\\n' "$FAKE_INSTALLS" > "$HOME/.local/bin/t3"
else printf "#!/bin/sh\\nexec '%s/t3' \\"\\$@\\"\\n" "$dir" > "$HOME/.local/bin/t3"; fi
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
        # The release archive: one folder holding the t3 binary (the installer unpacks it with --strip-components=1).
        build = root / "build" / f"t3-{PIN}-linux-{ARCH}"
        write_exec(build / "t3", f'#!/bin/sh\necho "t3 v{PIN}"\n')
        self.mirror = root / "mirror"
        (self.mirror / f"v{PIN}").mkdir(parents=True)
        subprocess.run(["tar", "-czf", str(self.mirror / f"v{PIN}" / ARCHIVE), "-C", str(build.parent), build.name], check=True)
        self.sha = hashlib.sha256((self.mirror / f"v{PIN}" / ARCHIVE).read_bytes()).hexdigest()
        other_arch = "arm64" if ARCH == "x64" else "x64"   # the same bytes under the other CPU's name, so either CPU can be tested on any machine
        shutil.copy(self.mirror / f"v{PIN}" / ARCHIVE, self.mirror / f"v{PIN}" / f"t3-{PIN}-linux-{other_arch}.tar.gz")
        write_exec(root / "bin" / "uname", '#!/bin/sh\n[ "$1" = -m ] && [ -n "${FAKE_UNAME_M:-}" ] && echo "$FAKE_UNAME_M" || exec /usr/bin/uname "$@"\n')
        self.other = "1" * 64   # a well-formed sha256 that matches nothing
        write_exec(root / "installer.sh", INSTALLER)
        self.installer = root / "installer.sh"
        self.versions = self.home / ".t3/runtime/versions"

    def have_t3(self, version):
        write_exec(self.home / ".local/bin/t3", f'#!/bin/sh\necho "t3 v{version}"\n')

    def run_script(self, x64=None, arm64=None, **extra):
        env = {"PATH": f"{Path(self.tmp.name) / 'bin'}:/usr/bin:/bin", "HOME": str(self.home), "T3CODE_HOME": str(self.home / ".t3"), "CALLS": str(self.calls), "T3_PIN_VERSION": PIN,
               "T3_PIN_SHA256_X64": self.sha if x64 is None else x64, "T3_PIN_SHA256_ARM64": self.sha if arm64 is None else arm64,
               "T3CODE_RELEASE_BASE_URL": f"file://{self.mirror}", "T3_INSTALL_URL": f"file://{self.installer}", **extra}
        return subprocess.run(["/bin/sh", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)

    def run_with(self, cpu, cpu_sha, other_cpu_sha, **extra):
        """Run as CPU `cpu` (x64 or arm64) with `cpu_sha` pinned for it and `other_cpu_sha` for the other one."""
        pair = {"x64": cpu_sha, "arm64": other_cpu_sha} if cpu == "x64" else {"x64": other_cpu_sha, "arm64": cpu_sha}
        return self.run_script(FAKE_UNAME_M={"x64": "x86_64", "arm64": "aarch64"}[cpu], **pair, **extra)

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

    def test_the_installed_bytes_are_the_bytes_that_were_checked(self):
        # The installer here downloads nothing: what runs is the unpacked archive that passed the sha256 check.
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.versions / PIN / "t3").read_text(), f'#!/bin/sh\necho "t3 v{PIN}"\n')
        self.assertEqual((self.versions / PIN / ".install-complete").read_text().strip(), PIN)

    def test_an_installer_that_replaces_the_checked_binary_fails(self):
        r = self.run_script(FAKE_REDOWNLOAD="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("replaced the checked files", r.stdout)

    def test_an_installer_that_installs_somewhere_else_fails(self):
        # The launcher would run bytes the sha256 never covered; the checked copy is left untouched, so only the launcher check can see it.
        self.have_t3("0.1.9")
        r = self.run_script(FAKE_RELOCATE="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("put T3 somewhere else", r.stdout)
        self.assertEqual((self.versions / PIN / "t3").read_text(), f'#!/bin/sh\necho "t3 v{PIN}"\n')

    def test_an_installer_that_unpacks_the_same_bytes_again_fails(self):
        # t3 is identical afterwards, so only the marker written into the checked folder shows that the folder was replaced.
        r = self.run_script(FAKE_REEXTRACT="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("replaced the checked files", r.stdout)

    def test_the_marker_is_gone_after_a_good_install(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse((self.versions / PIN / ".checked-by-install_t3").exists())

    def test_a_pod_already_on_the_pin_downloads_and_installs_nothing(self):
        self.have_t3(PIN)
        shutil.rmtree(self.mirror)   # a download would fail
        r = self.run_script(T3_INSTALL_URL="file:///nonexistent")
        self.assertEqual((r.returncode, self.installed()), (0, []), r.stdout + r.stderr)

    def test_a_version_that_only_starts_with_the_pin_is_not_the_pin(self):
        # A substring or prefix compare would treat these as already installed and skip the install.
        for installed in (PIN + "1", PIN + "-rc1", "9" + PIN):
            with self.subTest(installed=installed):
                self.calls.write_text("")
                self.have_t3(installed)
                r = self.run_script()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.installed(), [f"installer version={PIN}"])
                self.assertEqual(self.version(), f"t3 v{PIN}")

    def test_an_archive_that_does_not_match_the_pinned_sha256_installs_nothing_and_fails(self):
        self.have_t3("0.1.9")
        r = self.run_script(x64="0" * 64, arm64="0" * 64)
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not match the pinned sha256", r.stdout)
        self.assertEqual(self.installed(), [])
        self.assertFalse(self.versions.exists() and any(self.versions.iterdir()), "nothing is unpacked")
        self.assertEqual(self.version(), "t3 v0.1.9")

    def test_the_sha256_for_this_cpu_is_the_one_that_counts(self):
        # Right for the running CPU and wrong for the other: installs. The reverse (a swapped pair) must fail. Both CPUs, on any machine.
        for cpu in ("x64", "arm64"):
            with self.subTest(cpu=cpu):
                self.calls.write_text("")
                self.have_t3("0.1.9")
                r = self.run_with(cpu, self.sha, self.other)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.version(), f"t3 v{PIN}")
                self.calls.write_text("")
                self.have_t3("0.1.9")
                r = self.run_with(cpu, self.other, self.sha)
                self.assertEqual(r.returncode, 1)
                self.assertIn("does not match the pinned sha256", r.stdout)
                self.assertEqual((self.installed(), self.version()), ([], "t3 v0.1.9"))

    def test_a_cpu_with_no_pinned_sha256_fails_rather_than_installing_unchecked(self):
        r = self.run_script(x64="", arm64="")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no sha256 pinned", r.stdout)
        self.assertEqual(self.installed(), [])

    def test_a_release_that_is_not_there_fails(self):
        shutil.rmtree(self.mirror / f"v{PIN}")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertIn("could not download", r.stdout)
        self.assertEqual(self.installed(), [])

    def test_a_launcher_that_does_not_run_the_checked_copy_fails(self):
        self.have_t3("0.1.9")
        r = self.run_script(FAKE_INSTALLS="0.1.9")
        self.assertEqual(r.returncode, 1)
        self.assertIn("does not run the checked", r.stdout)


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
