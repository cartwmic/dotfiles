"""The pinned agent-kit install: the agentKit.enabled gate, the agent-traces wrapper's exit 3, and the install script's WARN.

Real chezmoi against this source with a throwaway HOME and destination, no read-source-state hook, no token and no network:
a fake npm stands in for the registry. Needs chezmoi, sh.
"""
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RETRY = "cd ~/.local/share/agent-kit && NODE_AUTH_TOKEN=$(gh auth token) npm ci"


class Home:
    """A throwaway HOME with a chezmoi config for one profile and optional extra data."""

    def __init__(self, test, profile, extra=""):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        (self.home / ".local/bin").mkdir(parents=True)
        (self.home / ".local/share").mkdir(parents=True)
        self.config = self.root / "chezmoi.yaml"
        self.config.write_text("data:\n  profile: %s\n%s" % (profile, extra))

    def chezmoi(self, *args, env=None):
        cmd = ["chezmoi", "--source", str(REPO), "--config", str(self.config), "--config-format", "yaml",
               "--destination", str(self.home), "--persistent-state", str(self.root / "state.boltdb"), "--no-tty", *args]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=str(self.home), **(env or {})))

    def script_managed(self):
        return "65_agent_kit_install.sh" in self.chezmoi("managed", "--include=scripts").stdout

    def install_wrapper(self):
        r = self.chezmoi("apply", str(self.home / ".local/bin/agent-traces"), str(self.home / ".local/share/agent-kit"))
        assert r.returncode == 0, r.stderr
        return subprocess.run([str(self.home / ".local/bin/agent-traces"), "review", "normalize", "x"], capture_output=True,
                              text=True, env=dict(os.environ, HOME=str(self.home)))


class AgentKitInstallTest(unittest.TestCase):
    def test_disabled_has_no_install_script_and_wrapper_exits_3(self):
        # Personal defaults agentEvents.engine to ts, and ts needs the kit, so with the kit off personal must name python.
        for profile, extra in (("personal", "  agentKit: {enabled: false}\n  agentEvents: {engine: python}\n"), ("axon-work-computer", "")):
            with self.subTest(profile=profile):
                home = Home(self, profile, extra)
                self.assertFalse(home.script_managed())
                r = home.install_wrapper()
                self.assertEqual(r.returncode, 3)
                self.assertIn("not installed here; keep the review log by hand (playbook 58fdb05d)", r.stderr)
                self.assertNotIn(RETRY, r.stderr)
                self.assertTrue((home.home / ".local/share/agent-kit/package.json").is_file())

    def test_enabled_by_default_on_personal_and_wrapper_prints_the_retry_line(self):
        home = Home(self, "personal")
        self.assertTrue(home.script_managed())
        r = home.install_wrapper()
        self.assertEqual(r.returncode, 3)
        self.assertIn(RETRY, r.stderr)

    def test_enabled_on_work_when_set(self):
        self.assertTrue(Home(self, "axon-work-computer", "  agentKit: {enabled: true}\n").script_managed())

    def test_bad_setting_fails_the_render(self):
        for extra in ("  agentKit: {enabled: maybe}\n", "  agentKit: {version: 1}\n"):
            with self.subTest(extra=extra):
                self.assertNotEqual(Home(self, "personal", extra).chezmoi("managed").returncode, 0)

    def test_failed_install_warns_with_the_retry_line_and_exits_0(self):
        home = Home(self, "personal")
        script = home.chezmoi("cat", str(home.home / "65_agent_kit_install.sh"))
        self.assertEqual(script.returncode, 0, script.stderr)
        kit = home.home / ".local/share/agent-kit"
        kit.mkdir()
        (kit / "package-lock.json").write_text("{}")
        fake = home.root / "bin"
        fake.mkdir()
        npm = fake / "npm"
        npm.write_text("#!/bin/sh\necho 'npm error: registry unreachable' >&2\nexit 1\n")
        npm.chmod(npm.stat().st_mode | stat.S_IXUSR)
        r = subprocess.run(["sh", "-c", script.stdout], capture_output=True, text=True,
                           env=dict(os.environ, HOME=str(home.home), PATH="%s:%s" % (fake, os.environ["PATH"])))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[agent_kit_install] WARN: npm ci failed", r.stdout)
        self.assertIn(RETRY, r.stdout)


if __name__ == "__main__":
    unittest.main()
