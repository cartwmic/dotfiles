"""The managed ~/.local/bin/chromium wrapper (viz and Pi launch_browser find it on PATH).

The real template is rendered with real chezmoi for each desktop profile, then run with a fake `npx`
and a fake Playwright cache in a scratch HOME. No real Playwright install runs and no real cache is touched.
RED control: the wrapper as it was before this change (vendored below) fails with exit 126 on a missing build."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TMPL = ROOT / "dot_local/bin/executable_chromium.tmpl"
PROFILES = ("personal", "axon-work-computer")
DARWIN = sys.platform == "darwin"
VERSION, BUILD = "1.64.1", "1248"
EXE = "Library/Caches/ms-playwright/chromium-%s/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" % BUILD
INSTALL_ARGS = ["-y", "playwright@" + VERSION, "install", "chromium"]

# The wrapper as it was before it was managed (~/.local/bin/chromium, 2026-10-24): no install step.
OLD_WRAPPER = """#!/bin/sh
# Pi's launch_browser looks for "chromium" on PATH; point it at the Playwright Chrome for Testing build.
exec "$HOME/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing" "$@"
"""

# Placeholder values for the keys the work profile requires (docs/profiles.md, "Local data keys").
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}

# Fake npx: records argv and PLAYWRIGHT_BROWSERS_PATH; fails when FAKE_NPX=fail; does nothing when FAKE_NPX=noop;
# otherwise "installs" the build by writing the fake browser into the fake cache (temp file, then rename).
FAKE_NPX = """#!/bin/sh
printf 'npx %s\\n' "$*" >> "$FAKE_LOG"
printf 'browsers_path %s\\n' "${PLAYWRIGHT_BROWSERS_PATH-unset}" >> "$FAKE_LOG"
printf 'pgid %s\\n' "$(ps -o pgid= -p $$ | tr -d ' ')" >> "$FAKE_LOG"
case "${FAKE_NPX-}" in
	fail) echo "fake npx: network down" >&2; exit 1 ;;
	noop) exit 0 ;;
esac
dir="$HOME/Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS"
mkdir -p "$dir"
cp "$FAKE_BROWSER_SRC" "$dir/.tmp-browser"
chmod 755 "$dir/.tmp-browser"
mv "$dir/.tmp-browser" "$dir/Google Chrome for Testing"
cache="$HOME/Library/Caches/ms-playwright"
mkdir -p "$cache/chromium_headless_shell-1248"
touch "$cache/chromium_headless_shell-1248/INSTALLATION_COMPLETE" "$cache/chromium-1248/INSTALLATION_COMPLETE"
"""

FAKE_BROWSER = """#!/bin/sh
printf 'browser %s\\n' "$*" >> "$FAKE_LOG"
"""


def write_atomic(path, text, mode=0o755):
    """Write beside the target, then rename, so a reader never sees a half-written script."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    tmp.chmod(mode)
    os.rename(tmp, path)


def chezmoi(profile, *args, stdin=None):
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: %s\n" % profile + "".join("  %s: %s\n" % kv for kv in (WORK_DATA.items() if profile == "axon-work-computer" else ())))
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml",
                            "--destination", str(home), *args],
                           input=stdin, capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=120)
    if r.returncode:
        raise AssertionError("chezmoi %s (%s) failed: %s" % (args[0], profile, r.stderr))
    return r.stdout


class WrapperTest(unittest.TestCase):
    def setUp(self):
        self.fresh()

    def fresh(self):
        """A new scratch HOME, fake bin and call log (a test that loops over profiles calls this per profile)."""
        self.tmp = tempfile.TemporaryDirectory(prefix="chromium-wrapper-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.log = self.root / "calls.log"
        self.browser_src = self.root / "fake-browser"
        write_atomic(self.browser_src, FAKE_BROWSER)
        self.bin = self.root / "bin"
        write_atomic(self.bin / "npx", FAKE_NPX)

    def install_build(self, markers=True):
        write_atomic(self.home / EXE, FAKE_BROWSER)
        if markers:
            cache = self.home / "Library/Caches/ms-playwright"
            (cache / ("chromium_headless_shell-%s" % BUILD)).mkdir(parents=True, exist_ok=True)
            for d in ("chromium-%s" % BUILD, "chromium_headless_shell-%s" % BUILD):
                (cache / d / "INSTALLATION_COMPLETE").touch()

    def run_wrapper(self, text, *args, **env):
        script = self.root / "chromium"
        write_atomic(script, text)
        full = {"PATH": "%s:/usr/bin:/bin" % self.bin, "HOME": str(self.home), "FAKE_LOG": str(self.log),
                "FAKE_BROWSER_SRC": str(self.browser_src)}
        full.update(env)
        return subprocess.run(["/bin/sh", str(script), *args], env=full, capture_output=True, text=True, timeout=60)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class NewWrapperTest(WrapperTest):
    @classmethod
    def setUpClass(cls):
        cls.rendered = {p: chezmoi(p, "execute-template", stdin=TMPL.read_text()) for p in PROFILES}

    def each_profile(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                self.fresh()
                yield self.rendered[profile]

    def test_present_build_runs_with_no_install(self):
        for text in self.each_profile():
            self.install_build()
            r = self.run_wrapper(text, "--headless", "about:blank")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.calls(), ["browser --headless about:blank"])
            self.assertEqual(r.stderr, "")

    def test_missing_build_installs_once_then_runs(self):
        for text in self.each_profile():
            r = self.run_wrapper(text, "--headless", "about:blank")
            self.assertEqual(r.returncode, 0, r.stderr)
            calls = self.calls()
            self.assertEqual([c for c in calls if not c.startswith("pgid ")], [
                "npx " + " ".join(INSTALL_ARGS),
                "browsers_path %s/Library/Caches/ms-playwright" % self.home,
                "browser --headless about:blank"])
            pgid = [c for c in calls if c.startswith("pgid ")]
            self.assertEqual(len(pgid), 1)
            self.assertNotEqual(int(pgid[0].split()[1]), os.getpgrp(), "the install runs in its own process group")
            self.assertFalse((self.home / "Library/Caches/ms-playwright/.chromium-install.lock").exists(), "lock released")
            lines = r.stderr.splitlines()
            self.assertEqual(len(lines), 1, r.stderr)
            self.assertTrue(lines[0].startswith("[chromium] INFO: "), lines[0])
            self.assertIn("npx -y playwright@%s install chromium" % VERSION, lines[0])
            # The second run finds the build the install left: no second install.
            self.log.unlink()
            r2 = self.run_wrapper(text, "--version")
            self.assertEqual(r2.returncode, 0, r2.stderr)
            self.assertEqual(self.calls(), ["browser --version"])

    def test_ensure_installs_a_missing_build_and_does_not_launch(self):
        for text in self.each_profile():
            r = self.run_wrapper(text, "--ensure")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual([c for c in self.calls() if c.startswith(("npx ", "browser "))], ["npx " + " ".join(INSTALL_ARGS)])
            # Present again: --ensure is a no-op.
            self.log.unlink()
            r2 = self.run_wrapper(text, "--ensure")
            self.assertEqual((r2.returncode, r2.stderr, self.calls()), (0, "", []))

    def test_ensure_restores_a_pruned_headless_shell_alone(self):
        for text in self.each_profile():
            self.install_build()
            shutil.rmtree(self.home / "Library/Caches/ms-playwright" / ("chromium_headless_shell-%s" % BUILD))
            r = self.run_wrapper(text, "--ensure")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len([c for c in self.calls() if c.startswith("npx ")]), 1)

    def test_executable_without_the_completion_marker_is_not_present(self):
        for text in self.each_profile():
            self.install_build(markers=False)  # a half-extracted install: the file is there, the marker is not
            r = self.run_wrapper(text, "--version")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len([c for c in self.calls() if c.startswith("npx ")]), 1)

    def test_a_live_lock_makes_the_second_caller_wait_instead_of_installing(self):
        for text in self.each_profile():
            cache = self.home / "Library/Caches/ms-playwright"
            lock = cache / ".chromium-install.lock"
            lock.mkdir(parents=True)
            (lock / "pid").write_text(str(os.getpid()))  # this test process stands in for the installer: alive

            def finish():
                self.install_build()
                (lock / "pid").unlink()
                lock.rmdir()
            timer = threading.Timer(1.5, finish)
            timer.start()
            try:
                r = self.run_wrapper(text, "--version")
            finally:
                timer.join()
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.calls(), ["browser --version"], "no second install")

    def test_a_stale_lock_is_taken_over(self):
        for text in self.each_profile():
            dead = subprocess.Popen(["/bin/sh", "-c", "exit 0"])
            dead.wait()
            lock = self.home / "Library/Caches/ms-playwright/.chromium-install.lock"
            lock.mkdir(parents=True)
            (lock / "pid").write_text(str(dead.pid))
            r = self.run_wrapper(text, "--version")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(len([c for c in self.calls() if c.startswith("npx ")]), 1)
            self.assertFalse(lock.exists())

    def test_failed_install_prints_one_error_line_and_exits_nonzero(self):
        for text in self.each_profile():
            r = self.run_wrapper(text, "--headless", FAKE_NPX="fail")
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual([c for c in self.calls() if c.startswith("browser ")], [], "the browser must not run")
            errors = [l for l in r.stderr.splitlines() if "ERROR" in l]
            self.assertEqual(len(errors), 1, r.stderr)
            self.assertTrue(errors[0].startswith("[chromium] ERROR: "), errors[0])
            self.assertIn("playwright@%s" % VERSION, errors[0])
            self.assertIn("npx -y playwright@%s install chromium" % VERSION, errors[0])

    def test_install_that_leaves_no_build_is_the_same_error(self):
        for text in self.each_profile():
            r = self.run_wrapper(text, FAKE_NPX="noop")
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(len([l for l in r.stderr.splitlines() if "ERROR" in l]), 1, r.stderr)

    def test_missing_npx_is_the_same_error(self):
        for text in self.each_profile():
            (self.bin / "npx").unlink()
            r = self.run_wrapper(text)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(len([l for l in r.stderr.splitlines() if "ERROR" in l]), 1, r.stderr)

    def test_pin_in_chezmoidata_is_what_the_wrapper_uses(self):
        data = (ROOT / ".chezmoidata.toml").read_text()
        self.assertIn('[playwrightChromium]\nversion = "%s"\nbuild = "%s"' % (VERSION, BUILD), data)
        for text in self.each_profile():
            self.assertIn('VERSION="%s"' % VERSION, text)
            self.assertIn('BUILD="%s"' % BUILD, text)

    def test_deploys_on_macos_for_both_profiles_and_nowhere_else(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                managed = set(chezmoi(profile, "managed").split())
                self.assertEqual(".local/bin/chromium" in managed, DARWIN)


class RedControlTest(WrapperTest):
    def test_old_wrapper_without_an_install_step_fails_126_on_a_missing_build(self):
        r = self.run_wrapper(OLD_WRAPPER, "--headless")
        self.assertEqual(r.returncode, 126, r.stderr)
        self.assertEqual(self.calls(), [], "the old wrapper never installs")

    def test_old_wrapper_does_not_know_ensure(self):
        r = self.run_wrapper(OLD_WRAPPER, "--ensure")
        self.assertEqual(r.returncode, 126)

    def test_old_wrapper_runs_a_present_build(self):
        self.install_build()
        r = self.run_wrapper(OLD_WRAPPER, "--headless")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), ["browser --headless"])


if __name__ == "__main__":
    unittest.main()
