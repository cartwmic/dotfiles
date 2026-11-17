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
# The stand-in installer. Like the real one it works in $T3CODE_HOME (made absolute, no trailing slash), skips a version that is marked complete and writes the
# launcher. FAKE_MODE makes it behave badly, the ways a changed upstream installer might:
#   redownload  fetches the release itself: different bytes written over t3 in the checked folder
#   reextract   unpacks the same bytes again into a fresh folder (so anything else in the folder is gone)
#   relocate    unpacks different bytes in another folder and points the launcher there
#   wrong       writes a launcher that runs something else
#   suffix      writes the right launcher line followed by more text on the same line
INSTALLER = '''#!/bin/sh
echo "installer version=${T3CODE_VERSION:-}" >> "$CALLS"
h=${T3CODE_HOME:-$HOME/.t3}; case "$h" in /*) ;; *) h=$(pwd -P)/$h ;; esac; while [ "${h%/}" != "$h" ]; do h=${h%/}; done
dir=$h/runtime/versions/$T3CODE_VERSION
unpack() { mkdir -p "$1"; printf '#!/bin/sh\\necho "t3 v%s"\\n# %s\\n' "$T3CODE_VERSION" "$2" > "$1/t3"; chmod 755 "$1/t3"; echo "$T3CODE_VERSION" > "$1/.install-complete"; }
case "${FAKE_MODE:-good}" in
  reextract) cp "$dir/t3" "$dir.t3"; rm -rf "$dir"; mkdir -p "$dir"; mv "$dir.t3" "$dir/t3"; echo "$T3CODE_VERSION" > "$dir/.install-complete" ;;
  relocate) dir=$h/runtime/v2/versions/$T3CODE_VERSION; unpack "$dir" "unchecked bytes" ;;
  redownload) unpack "$dir" "other bytes" ;;
  *) [ "$(cat "$dir/.install-complete" 2>/dev/null)" = "$T3CODE_VERSION" ] || unpack "$dir" "downloaded" ;;
esac
mkdir -p "$HOME/.local/bin"
case "${FAKE_MODE:-good}" in
  wrong) printf '#!/bin/sh\\necho "t3 v0.1.9"\\n' > "$HOME/.local/bin/t3" ;;
  suffix) printf "#!/bin/sh\\nexec '%s/t3' \\"\\$@\\" ; true\\n" "$dir" > "$HOME/.local/bin/t3" ;;
  *) printf "#!/bin/sh\\nexec '%s/t3' \\"\\$@\\"\\n" "$dir" > "$HOME/.local/bin/t3" ;;
esac
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
        (build / "lib").mkdir()
        (build / "lib" / "data.bin").write_bytes(b"library bytes" * 100)   # what the real archive holds besides t3: client/, lib/, node_modules/
        self.mirror = root / "mirror"
        (self.mirror / f"v{PIN}").mkdir(parents=True)
        subprocess.run(["tar", "-czf", str(self.mirror / f"v{PIN}" / ARCHIVE), "-C", str(build.parent), build.name], check=True)
        self.sha = hashlib.sha256((self.mirror / f"v{PIN}" / ARCHIVE).read_bytes()).hexdigest()
        other_arch = "arm64" if ARCH == "x64" else "x64"   # the same bytes under the other CPU's name, so either CPU can be tested on any machine
        shutil.copy(self.mirror / f"v{PIN}" / ARCHIVE, self.mirror / f"v{PIN}" / f"t3-{PIN}-linux-{other_arch}.tar.gz")
        # `date` that never repeats, so two moves-aside in the same second get different names (as they would minutes apart on a restarting pod).
        write_exec(root / "bin" / "date", '#!/bin/sh\nn=$(cat "$DATE_COUNTER" 2>/dev/null || echo 0); n=$((n + 1)); echo $n > "$DATE_COUNTER"; printf "2026111700%04d\\n" $n\n')
        write_exec(root / "bin" / "uname", '#!/bin/sh\n[ "$1" = -m ] && [ -n "${FAKE_UNAME_M:-}" ] && echo "$FAKE_UNAME_M" || exec /usr/bin/uname "$@"\n')
        self.other = "1" * 64   # a well-formed sha256 that matches nothing
        write_exec(root / "installer.sh", INSTALLER)
        self.installer = root / "installer.sh"
        self.versions = self.home / ".t3/runtime/versions"

    def have_t3(self, version):
        write_exec(self.home / ".local/bin/t3", f'#!/bin/sh\necho "t3 v{version}"\n')

    def run_script(self, x64=None, arm64=None, **extra):
        env = {"PATH": f"{Path(self.tmp.name) / 'bin'}:/usr/bin:/bin", "HOME": str(self.home), "T3CODE_HOME": str(self.home / ".t3"), "CALLS": str(self.calls), "DATE_COUNTER": str(Path(self.tmp.name) / "date-counter"), "T3_PIN_VERSION": PIN,
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

    def stamp(self):
        folder = self.versions / PIN
        files = [f for f in folder.rglob("*") if f.is_file() and f.name != ".verified-by-install_t3"]
        return f"{PIN} {hashlib.sha256((folder / 't3').read_bytes()).hexdigest()} {len(files)} {sum(f.stat().st_size for f in files)}"

    def asides(self):
        return sorted(p.name for p in self.versions.glob(f"{PIN}.corrupt-*"))

    def assert_checked_copy_in_place(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.versions / PIN / "t3").read_text(), f'#!/bin/sh\necho "t3 v{PIN}"\n')
        self.assertEqual((self.versions / PIN / "lib/data.bin").read_bytes(), b"library bytes" * 100)
        self.assertEqual((self.versions / PIN / ".verified-by-install_t3").read_text().strip(), self.stamp())
        self.assertEqual(self.version(), f"t3 v{PIN}")

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
        # The installer here downloads nothing: what runs is the unpacked archive that passed the sha256 check, and the stamp records its hash.
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.versions / PIN / "t3").read_text(), f'#!/bin/sh\necho "t3 v{PIN}"\n')
        self.assertEqual((self.versions / PIN / ".install-complete").read_text().strip(), PIN)
        self.assertEqual((self.versions / PIN / ".verified-by-install_t3").read_text().strip(), self.stamp())

    def test_a_good_install_followed_by_a_rerun_is_a_quiet_no_op(self):
        self.assertEqual(self.run_script().returncode, 0)
        self.calls.write_text("")
        shutil.rmtree(self.mirror)   # a download would fail
        r = self.run_script(T3_INSTALL_URL="file:///nonexistent")
        self.assertEqual((r.returncode, r.stdout, r.stderr, self.installed()), (0, "", "", []))

    BAD_INSTALLERS = {
        "redownload": "replaced the checked t3 in the same folder",
        "reextract": "re-extracted the same bytes into a fresh folder",
        "relocate": "unpacked elsewhere and pointed the launcher there",
        "wrong": "wrote a launcher that runs something else",
        "suffix": "wrote the launcher line with more on the same line",
    }

    def test_a_bad_installer_fails_the_first_run_and_every_later_one(self):
        # A pod restart runs the script again. The second run must not find "already on the pin" and exit 0 on bytes that were never checked.
        for mode, what in self.BAD_INSTALLERS.items():
            with self.subTest(mode=mode, installer=what):
                shutil.rmtree(self.home / ".t3", ignore_errors=True)
                self.have_t3("0.1.9")
                for n in (1, 2, 3):
                    r = self.run_script(FAKE_MODE=mode)
                    self.assertEqual(r.returncode, 1, f"run {n}: {r.stdout}{r.stderr}")
                    self.assertIn("did not use the checked copy", r.stdout, f"run {n}")
                self.assertLessEqual(len(self.asides()), 1, "a pod that restarts again and again keeps one bad copy, not one per start")

    def test_after_a_bad_installer_a_good_run_repairs_to_the_checked_bytes(self):
        for mode in self.BAD_INSTALLERS:
            with self.subTest(mode=mode):
                shutil.rmtree(self.home / ".t3", ignore_errors=True)
                self.have_t3("0.1.9")
                self.assertEqual(self.run_script(FAKE_MODE=mode).returncode, 1)
                r = self.run_script()
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual((self.versions / PIN / "t3").read_text(), f'#!/bin/sh\necho "t3 v{PIN}"\n')
                self.assertIn(f"exec '{self.versions / PIN / 't3'}'", (self.home / ".local/bin/t3").read_text())

    def test_a_pod_on_the_pin_from_before_the_stamp_existed_is_installed_again_through_the_checked_path(self):
        # What a pod looks like after the earlier version of this script: the pin installed, the launcher right, but no stamp. Its bytes were never
        # checked against the pinned sha256 here, so they are replaced, not trusted.
        folder = self.versions / PIN
        folder.mkdir(parents=True)
        write_exec(folder / "t3", f'#!/bin/sh\necho "t3 v{PIN}"\n# unchecked\n')
        (folder / ".install-complete").write_text(PIN + "\n")
        write_exec(self.home / ".local/bin/t3", f"#!/bin/sh\nexec '{folder / 't3'}' \"$@\"\n")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.installed(), [f"installer version={PIN}"])
        self.assertEqual((folder / "t3").read_text(), f'#!/bin/sh\necho "t3 v{PIN}"\n')
        self.assertEqual((folder / ".verified-by-install_t3").read_text().strip(), self.stamp())
        self.calls.write_text("")
        self.assertEqual((self.run_script().returncode, self.installed()), (0, []))

    def test_a_folder_cut_short_by_an_unclean_detach_is_moved_aside_and_replaced(self):
        # What an unclean volume detach left on agent-host: .install-complete and the launcher are there, t3 is truncated, other files are zero bytes.
        # The installer would call this "already downloaded"; here it is never accepted, and the bad folder is kept, not deleted.
        folder = self.versions / PIN
        (folder / "lib").mkdir(parents=True)
        write_exec(folder / "t3", '#!/bin/sh\necho "t3 v')   # cut short
        (folder / "lib/data.bin").write_bytes(b"")           # zero bytes
        (folder / ".install-complete").write_text(PIN + "\n")
        write_exec(self.home / ".local/bin/t3", f"#!/bin/sh\nexec '{folder / 't3'}' \"$@\"\n")
        r = self.run_script()
        self.assert_checked_copy_in_place(r)
        self.assertEqual(self.installed(), [f"installer version={PIN}"])
        aside = self.asides()
        self.assertEqual(len(aside), 1, aside)
        self.assertEqual((self.versions / aside[0] / "t3").read_text(), '#!/bin/sh\necho "t3 v')
        self.calls.write_text("")
        self.assertEqual((self.run_script().returncode, self.installed(), self.asides()), (0, [], aside))

    def test_a_stamped_folder_that_is_damaged_afterwards_is_replaced_whatever_file_it_is(self):
        # The stamp is checked against the folder every time: a cut-short t3, a zeroed library file and a missing file each fail it.
        damages = {
            "t3 cut short": lambda f: (f / "t3").write_bytes((f / "t3").read_bytes()[:10]),
            "library zeroed": lambda f: (f / "lib/data.bin").write_bytes(b""),
            "library file missing": lambda f: (f / "lib/data.bin").unlink(),
            "library cut short": lambda f: (f / "lib/data.bin").write_bytes(b"library"),
        }
        for what, damage in damages.items():
            with self.subTest(damage=what):
                shutil.rmtree(self.home / ".t3", ignore_errors=True)
                self.assertEqual(self.run_script().returncode, 0)
                damage(self.versions / PIN)
                self.calls.write_text("")
                r = self.run_script()
                self.assert_checked_copy_in_place(r)
                self.assertEqual(self.installed(), [f"installer version={PIN}"])
                self.assertEqual(len(self.asides()), 1)

    def test_a_folder_that_is_fine_is_not_moved_aside_when_the_installer_keeps_failing(self):
        # A good checked copy is replaced in place; only an unverified folder is kept aside, so a pod that restarts again and again does not fill the volume.
        self.have_t3("0.1.9")
        for _ in range(3):
            self.assertEqual(self.run_script(FAKE_MODE="relocate").returncode, 1)
        self.assertEqual(self.asides(), [])

    def test_a_checked_t3_that_was_changed_afterwards_is_replaced(self):
        self.assertEqual(self.run_script().returncode, 0)
        (self.versions / PIN / "t3").write_text('#!/bin/sh\necho "t3 v' + PIN + '"\n# edited\n')
        self.calls.write_text("")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.installed(), [f"installer version={PIN}"])
        self.assertEqual((self.versions / PIN / "t3").read_text(), f'#!/bin/sh\necho "t3 v{PIN}"\n')

    def test_a_t3_home_with_a_trailing_slash_or_a_relative_path_works_as_the_installer_reads_it(self):
        r = self.run_script(T3CODE_HOME=str(self.home / ".t3") + "//")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        shutil.rmtree(self.home / ".t3")
        self.calls.write_text("")
        r = subprocess.run(["/bin/sh", str(SCRIPT)], cwd=self.home, capture_output=True, text=True, timeout=60, env={
            "PATH": f"{Path(self.tmp.name) / 'bin'}:/usr/bin:/bin", "HOME": str(self.home), "T3CODE_HOME": ".t3", "CALLS": str(self.calls), "T3_PIN_VERSION": PIN,
            "T3_PIN_SHA256_X64": self.sha, "T3_PIN_SHA256_ARM64": self.sha, "T3CODE_RELEASE_BASE_URL": f"file://{self.mirror}", "T3_INSTALL_URL": f"file://{self.installer}"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.versions / PIN / ".verified-by-install_t3").exists())

    def test_a_pod_already_on_the_pin_downloads_and_installs_nothing(self):
        self.assertEqual(self.run_script().returncode, 0)
        self.calls.write_text("")
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
                shutil.rmtree(self.home / ".t3", ignore_errors=True)
                self.calls.write_text("")
                self.have_t3("0.1.9")
                r = self.run_with(cpu, self.sha, self.other)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.version(), f"t3 v{PIN}")
                shutil.rmtree(self.home / ".t3", ignore_errors=True)
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
