"""The `66` install step (run_onchange_after_66_agent_desktop_macos.sh.tmpl) on a Mac.

The real chezmoi renders the real template for a Mac (personal and work profile). The rendered script runs under /bin/sh in a scratch
HOME, with a PATH of stubs only: curl (serves fixture files, records the URL), tar and shasum (record the call, then do the real
work), uname (says which processor), plus a few coreutils. Nothing is downloaded and the real ~/.local/bin is never reachable.
Run: python3 -m unittest discover -s tests/agent-desktop -p 'test_macos_install.py'
"""
import hashlib
import io
import json
import os
import plistlib
import re
import shutil
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
BODY = REPO / ".chezmoitemplates/agent-desktop-macos.sh"
STEP = REPO / "run_onchange_after_66_agent_desktop_macos.sh.tmpl"
RELAY = REPO / ".chezmoitemplates/agent-desktop-relay.sh"
LAUNCHD_LIB = REPO / "dot_local/share/launchd-reload/launchd_reload.sh"
LABEL = "com.cartwmic.agent-desktop-relay"
PROFILES = ("personal", "axon-work-computer")
VERSION = "v1.3.1"
RELEASES = "https://github.com/vercel-labs/agent-desktop/releases/download/"
# gzip: GNU tar on Linux runs it to unpack a .tar.gz; the tar on a Mac does not need it.
REAL = ("awk", "cat", "chmod", "cmp", "cp", "cut", "date", "gzip", "head", "id", "ln", "mkdir", "mkfifo", "mktemp", "mv", "nohup", "ps",
        "rm", "sleep", "tr")
ASSET_ARCH = {"arm64": "aarch64-apple-darwin", "x86_64": "x86_64-apple-darwin"}

FAKE = """#!/bin/sh
name=${0##*/}
line=$name
for a in "$@"; do line="$line [$a]"; done
echo "$line" >> "$FAKE_CALLS"
case $name in
  uname)
    case ${1:-} in -m) echo "$FAKE_ARCH" ;; *) echo Darwin ;; esac ;;
  curl)
    if [ -n "${FAKE_CURL_EXIT:-}" ]; then exit "$FAKE_CURL_EXIT"; fi
    out=
    prev=
    for a in "$@"; do
      if [ "$prev" = -o ]; then out=$a; fi
      prev=$a
      url=$a
    done
    src="$FAKE_FIXTURES/${url##*/}"
    [ -f "$src" ] || { echo "curl: (22) 404 for $url" >&2; exit 22; }
    if [ -n "$out" ]; then cp "$src" "$out"; else cat "$src"; fi ;;
  tar) exec "$REAL_TAR" "$@" ;;
  shasum) shift 2; exec "$REAL_SHA256SUM" "$@" ;;
esac
"""


# What the kitty helper needs on a Mac: launchctl (remembers whether the job is loaded), open (a fake kitty: starts what kitty is told
# to run, in the background) and osascript (the one tool the script calls for `cursor`).
FAKE_MAC = """#!/bin/sh
name=${0##*/}
echo "$name $*" >> "$FAKE_CALLS"
case $name in
  launchctl)
    case $1 in
      print) [ -f "$FAKE_LOADED" ] ;;
      bootstrap) [ -z "${FAKE_BOOTSTRAP_FAIL:-}" ] || { echo "Bootstrap failed: 5: Input/output error" >&2; exit 5; }; cp "$3" "$FAKE_LOADED" ;;
      bootout) rm -f "$FAKE_LOADED" ;;
    esac ;;
  open)
    [ -z "${FAKE_OPEN_NOOP:-}" ] || exit 0
    shift 4
    while :; do case ${1:-} in --*=*) shift ;; *) break ;; esac; done
    nohup "$@" >/dev/null 2>&1 & ;;
  osascript) echo "1 2" ;;
esac
"""


def archive(version, arch, tag):
    """A release archive holding the two files the real one holds; `tag` makes the content tell the archives apart."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for name in ("agent-desktop", "agent-desktop-macos-helper"):
            data = ("#!/bin/sh\n# fake %s %s %s %s\n" % (name, version, arch, tag)).encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def write_release(fixtures, version, tag="", bad_checksum=False):
    sums = []
    for arch in ASSET_ARCH.values():
        data = archive(version, arch, tag)
        name = "agent-desktop-%s-%s.tar.gz" % (version, arch)
        (fixtures / name).write_bytes(data)
        digest = "0" * 64 if bad_checksum else hashlib.sha256(data).hexdigest()
        # Lines that a loose match on the asset name would pick up first: a look-alike asset with a wrong hash.
        sums.append("%s  agent-desktop-ffi-%s-%s.tar.gz" % ("f" * 64, version, arch))
        sums.append("%s  %s.sig" % ("e" * 64, name))
        sums.append("%s  %s" % (digest, name))
    (fixtures / "checksums.txt").write_text("\n".join(sums) + "\n")


def chezmoi(*args, system="darwin", profile="personal", stdin=None):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile)
        override = json.dumps({"profile": profile, "chezmoi": {"os": system}})
        r = subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home),
                            "--override-data", override, *args], input=stdin, capture_output=True, text=True,
                           env=source_tree.chezmoi_env(home), timeout=120)
    if r.returncode:
        raise AssertionError("chezmoi %s (%s, %s) failed: %s" % (args[0], system, profile, r.stderr))
    return r.stdout


def snapshot(root):
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = (st.st_mtime_ns, st.st_mode, p.read_bytes())
    return out


class InstallTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not STEP.is_file() or not BODY.is_file():
            raise AssertionError("the 66 install step (%s) and the macOS script body (%s) must exist" % (STEP.name, BODY.name))
        text = STEP.read_text()
        cls.rendered = {p: chezmoi("execute-template", profile=p, stdin=text) for p in PROFILES}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="adi-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.scratch = self.tmp / "tmp"
        self.fixtures = self.tmp / "fixtures"
        for d in (self.home, self.scratch, self.fixtures):
            d.mkdir()
        write_release(self.fixtures, VERSION)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name in ("uname", "curl", "tar", "shasum"):
            (self.bin / name).write_text(FAKE)
            (self.bin / name).chmod(0o755)
        for name in ("launchctl", "open", "osascript"):
            (self.bin / name).write_text(FAKE_MAC)
            (self.bin / name).chmod(0o755)
        self.install_launchd_lib()
        for name in REAL:
            (self.bin / name).symlink_to(shutil.which(name))
        self.calls_file = self.tmp / "calls"
        self.script_path = self.home / ".local/bin/agent-desktop"
        self.vercel = self.home / ".local/share/agent-desktop/vercel"
        self.relay = self.home / ".local/bin/agent-desktop-relay"
        self.plist = self.home / "Library/LaunchAgents" / (LABEL + ".plist")
        self.addCleanup(self.stop_helper)

    def install_launchd_lib(self):
        lib = self.home / ".local/share/launchd-reload"  # a full apply installs this before the 66 step runs
        lib.mkdir(parents=True)
        shutil.copy(LAUNCHD_LIB, lib / "launchd_reload.sh")

    def fresh_home(self):
        """A Mac nothing was applied to yet."""
        self.stop_helper()
        shutil.rmtree(self.home)
        self.home.mkdir()
        self.calls_file.unlink(missing_ok=True)
        self.install_launchd_lib()

    def stop_helper(self):
        pid = self.home / ".local/state/agent-desktop/relay/pid"
        if pid.exists():
            try:
                os.kill(int(pid.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass

    def helper_pid(self):
        return int((self.home / ".local/state/agent-desktop/relay/pid").read_text())

    def run_step(self, profile="personal", arch="arm64", text=None, **extra):
        env = {"PATH": str(self.bin), "HOME": str(self.home), "TMPDIR": str(self.scratch), "FAKE_CALLS": str(self.calls_file),
               "FAKE_FIXTURES": str(self.fixtures), "FAKE_ARCH": arch, "REAL_TAR": shutil.which("tar"),
               "REAL_SHA256SUM": shutil.which("sha256sum"), "FAKE_LOADED": str(self.tmp / "loaded"),
               "LAUNCHD_RETRIES": "1", "LAUNCHD_RETRY_SLEEP": "0", "AGENT_DESKTOP_RELAY_START_WAIT": "10"}
        env.update(extra)
        return subprocess.run(["/bin/sh", "-c", text or self.rendered[profile]], env=env, capture_output=True, text=True, timeout=60)

    def calls(self, tool):
        lines = self.calls_file.read_text().splitlines() if self.calls_file.exists() else []
        return [l for l in lines if l.startswith(tool + " ")]

    def urls(self):
        return [re.findall(r"\[([^\]]*)\]", l)[-1] for l in self.calls("curl")]

    # a fresh Mac
    def test_a_fresh_apply_installs_the_script_and_vercels_program_on_both_profiles(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                self.fresh_home()
                r = self.run_step(profile)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.script_path.read_bytes(), BODY.read_bytes())
                self.assertEqual(stat.S_IMODE(self.script_path.stat().st_mode), 0o755)
                for name in ("agent-desktop", "agent-desktop-macos-helper"):
                    f = self.vercel / name
                    self.assertTrue(f.is_file() and os.access(f, os.X_OK), "%s is not installed and executable" % f)
                self.assertIn("aarch64-apple-darwin", (self.vercel / "agent-desktop").read_text())

    def test_it_downloads_the_pinned_version_for_this_processor_and_checks_its_checksum(self):
        for arch, asset in ASSET_ARCH.items():
            with self.subTest(arch=arch):
                self.fresh_home()
                r = self.run_step(arch=arch)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(sorted(self.urls()), sorted([
                    RELEASES + "%s/agent-desktop-%s-%s.tar.gz" % (VERSION, VERSION, asset), RELEASES + "%s/checksums.txt" % VERSION]))
                self.assertTrue(self.calls("shasum"), "the download was not checked against the release checksums")
                self.assertIn(asset, (self.vercel / "agent-desktop").read_text())

    def test_a_processor_it_has_no_build_for_is_an_error_that_names_it(self):
        r = self.run_step(arch="riscv64")
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stderr, r"(?m)^\[agent_desktop_macos\] ERROR: .*riscv64")
        self.assertFalse(self.vercel.exists())
        self.assertEqual(self.calls("curl"), [])

    # applying again
    def test_applying_again_downloads_nothing_and_changes_nothing(self):
        self.assertEqual(self.run_step().returncode, 0)
        before = snapshot(self.home)
        self.calls_file.unlink()
        r = self.run_step()
        self.assertEqual(r.returncode, 0, r.stderr)
        for tool in ("curl", "tar", "shasum"):
            self.assertEqual(self.calls(tool), [], "a second apply must not run %s" % tool)
        self.assertEqual(snapshot(self.home), before)

    def test_a_changed_or_unexecutable_script_copy_is_put_back_without_a_download(self):
        self.assertEqual(self.run_step().returncode, 0)
        self.script_path.write_text("edited\n")
        self.script_path.chmod(0o644)
        self.calls_file.unlink()
        r = self.run_step()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.script_path.read_bytes(), BODY.read_bytes())
        self.assertEqual(stat.S_IMODE(self.script_path.stat().st_mode), 0o755)
        self.assertEqual(self.calls("curl"), [])

    def test_a_missing_vercel_program_is_fetched_again_and_the_script_copy_is_left_alone(self):
        self.assertEqual(self.run_step().returncode, 0)
        script_before = snapshot(self.script_path.parent)
        shutil.rmtree(self.vercel)
        r = self.run_step()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.vercel / "agent-desktop").is_file())
        self.assertEqual(snapshot(self.script_path.parent), script_before)

    def test_raising_the_pinned_version_installs_the_new_one(self):
        self.assertEqual(self.run_step().returncode, 0)
        write_release(self.fixtures, "v1.3.2", tag="new")
        self.calls_file.unlink()
        r = self.run_step(text=self.rendered["personal"].replace(VERSION, "v1.3.2"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("v1.3.2", "".join(self.urls()))
        self.assertIn("v1.3.2", (self.vercel / "agent-desktop").read_text())

    # failures
    def test_a_failed_download_is_an_error_but_the_eight_actions_are_already_in_place(self):
        r = self.run_step(FAKE_CURL_EXIT="22")
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stderr, r"(?m)^\[agent_desktop_macos\] ERROR: ")
        self.assertEqual(self.script_path.read_bytes(), BODY.read_bytes())
        self.assertFalse((self.vercel / "agent-desktop").exists())

    def test_a_checksum_mismatch_installs_nothing_from_the_download(self):
        write_release(self.fixtures, VERSION, bad_checksum=True)
        r = self.run_step()
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stderr, r"(?mi)^\[agent_desktop_macos\] ERROR: .*checksum")
        self.assertFalse((self.vercel / "agent-desktop").exists())

    def test_a_run_leaves_no_temp_files_behind_even_when_it_fails(self):
        self.assertEqual(self.run_step().returncode, 0)
        self.assertEqual(list(self.scratch.iterdir()), [])
        shutil.rmtree(self.vercel)
        write_release(self.fixtures, VERSION, bad_checksum=True)
        self.assertEqual(self.run_step().returncode, 1)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_progress_lines_use_the_shared_log_prefix(self):
        r = self.run_step()
        lines = [l for l in (r.stdout + r.stderr).splitlines() if l.strip()]
        self.assertTrue(lines)
        for l in lines:
            self.assertRegex(l, r"^\[agent_desktop_macos\] (INFO|WARN|ERROR): ")

    # the kitty helper and its login item: personal profile only
    def other_calls(self, tool):
        return [l for l in self.calls_file.read_text().splitlines() if l.startswith(tool + " ")] if self.calls_file.exists() else []

    def test_personal_gets_the_helper_a_login_item_and_a_running_helper(self):
        r = self.run_step("personal")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.relay.read_bytes(), RELAY.read_bytes())
        self.assertEqual(stat.S_IMODE(self.relay.stat().st_mode), 0o755)
        plist = plistlib.loads(self.plist.read_bytes())
        self.assertEqual(plist["Label"], LABEL)
        self.assertIs(plist["RunAtLoad"], True)
        self.assertEqual(plist["ProgramArguments"][-2:], [str(self.relay), "start"])
        self.assertEqual(len(self.other_calls("launchctl bootstrap")), 1, self.calls_file.read_text())
        self.assertIn(str(self.plist), self.other_calls("launchctl bootstrap")[0])
        status = subprocess.run(["/bin/sh", str(self.relay), "status"], env={"PATH": str(self.bin), "HOME": str(self.home)}, capture_output=True, text=True)
        self.assertEqual(status.returncode, 0, "the helper is not running after the step: " + status.stdout)

    def test_the_helper_is_started_in_kitty_with_the_helper_loop(self):
        self.assertEqual(self.run_step("personal").returncode, 0)
        opens = self.other_calls("open")
        self.assertEqual(len(opens), 1, opens)
        self.assertRegex(opens[0], r"^open -na \S*kitty\.app --args .*/bin/sh %s serve$" % re.escape(str(self.relay)))

    def test_after_the_step_an_ssh_call_works_without_a_login(self):
        self.assertEqual(self.run_step("personal").returncode, 0)
        r = subprocess.run(["/bin/sh", str(self.script_path), "cursor"], capture_output=True, text=True, timeout=30,
                           env={"PATH": str(self.bin), "HOME": str(self.home), "SSH_CONNECTION": "a 1 b 22"})
        self.assertEqual((r.stdout, r.returncode), ("1 2\n", 0), r.stderr)

    def test_work_gets_no_helper_and_no_login_item(self):
        r = self.run_step("axon-work-computer")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.relay.exists())
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.other_calls("launchctl"), [])
        self.assertEqual(self.other_calls("open"), [])
        self.assertTrue(self.script_path.is_file(), "the rest of the setup stays on the work profile")
        self.assertTrue((self.vercel / "agent-desktop").is_file())

    def test_applying_again_touches_neither_the_login_item_nor_the_helper(self):
        self.assertEqual(self.run_step().returncode, 0)
        before, pid = snapshot(self.home), self.helper_pid()
        self.calls_file.unlink()
        r = self.run_step()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.other_calls("launchctl"), [])
        self.assertEqual(self.other_calls("open"), [])
        self.assertEqual(self.helper_pid(), pid)
        self.assertEqual(snapshot(self.home), before)

    def test_a_changed_helper_copy_is_put_back_and_the_helper_restarts_on_the_new_one(self):
        self.assertEqual(self.run_step().returncode, 0)
        old = self.helper_pid()
        self.relay.write_text(RELAY.read_text() + "# edited\n")
        self.calls_file.unlink()
        r = self.run_step()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.relay.read_bytes(), RELAY.read_bytes())
        self.assertEqual(self.other_calls("curl"), [])
        self.assertNotEqual(self.helper_pid(), old)
        with self.assertRaises(OSError):
            os.kill(old, 0)

    def test_the_helper_is_installed_even_when_vercels_program_is_already_there(self):
        self.assertEqual(self.run_step().returncode, 0)
        self.relay.unlink()
        self.plist.unlink()
        r = self.run_step()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.relay.is_file() and self.plist.is_file())

    def test_a_changed_login_item_is_unloaded_and_loaded_again(self):
        self.assertEqual(self.run_step().returncode, 0)
        self.plist.write_text("<plist/>")
        self.calls_file.unlink()
        self.assertEqual(self.run_step().returncode, 0)
        self.assertEqual([l.split()[1] for l in self.other_calls("launchctl") if not l.startswith("launchctl print")], ["bootout", "bootstrap"])
        self.assertEqual(plistlib.loads(self.plist.read_bytes())["Label"], LABEL)

    def test_a_helper_that_cannot_start_or_a_login_item_that_cannot_load_is_a_warning_not_a_failed_apply(self):
        for extra in ({"FAKE_OPEN_NOOP": "1", "AGENT_DESKTOP_RELAY_START_WAIT": "1"}, {"FAKE_BOOTSTRAP_FAIL": "1"}):
            with self.subTest(extra=extra):
                self.fresh_home()
                r = self.run_step(**extra)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("WARN", r.stdout + r.stderr)
                self.assertTrue(self.relay.is_file() and self.plist.is_file(), "the files stay in place so the next login or start works")
                self.assertTrue((self.vercel / "agent-desktop").is_file(), "the Vercel program is still installed")

    def test_without_the_launchd_library_the_login_item_is_written_but_not_loaded(self):
        (self.home / ".local/share/launchd-reload/launchd_reload.sh").unlink()
        r = self.run_step()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("WARN", r.stdout + r.stderr)
        self.assertTrue(self.plist.is_file())
        self.assertEqual(self.other_calls("launchctl"), [])

    # which systems run it
    def test_linux_and_windows_do_not_run_the_step_and_a_mac_does_on_both_profiles(self):
        for profile in PROFILES:
            for system, expected in (("darwin", True), ("linux", False), ("windows", False)):
                with self.subTest(system=system, profile=profile):
                    got = chezmoi("managed", "--include=scripts", system=system, profile=profile).split()
                    self.assertEqual("66_agent_desktop_macos.sh" in got, expected)


if __name__ == "__main__":
    unittest.main()
