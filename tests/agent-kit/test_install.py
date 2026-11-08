"""The pinned agent-kit install: the agentKit.enabled gate, the agent-traces wrapper's exit 3, and the install script's account choice and failure.

Real chezmoi against this source with a throwaway HOME and destination, no read-source-state hook, no token and no network:
a fake npm, a fake gh with two accounts and a loopback registry (answers 200 only to the good token) stand in. Needs chezmoi, sh, curl.
"""
import http.server
import os
import shutil
import stat
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RETRY = "cd ~/.local/share/agent-kit && NODE_AUTH_TOKEN=$(gh auth token --user ACCOUNT) npm ci"
SCRIPT_RETRY = "chezmoi apply ~/65_agent_kit_install.sh"


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
        home = Home(self, "axon-work-computer")
        self.assertFalse(home.script_managed())
        r = home.install_wrapper()
        self.assertEqual(r.returncode, 3)
        self.assertIn("not installed here; keep the review log by hand (playbook 58fdb05d)", r.stderr)
        self.assertNotIn(RETRY, r.stderr)
        self.assertTrue((home.home / ".local/share/agent-kit/package.json").is_file())

    def test_personal_with_the_kit_off_fails_the_render_because_agent_events_always_runs_the_port(self):
        # Personal defaults agentEvents.engine to ts, the only engine since the Python collector was retired, and ts needs the kit.
        r = Home(self, "personal", "  agentKit: {enabled: false}\n").chezmoi("managed")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("agentKit.enabled is false", r.stderr)

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

    # --- the install itself: which gh account is used, and what a failure leaves behind ---

    def setup_install(self, accounts, npm_keeps_old_on_fail=None):
        """A personal HOME with the kit files in place, fake gh/npm on PATH and a loopback registry. Returns (home, run)."""
        home = Home(self, "personal")
        script = home.chezmoi("cat", str(home.home / "65_agent_kit_install.sh"))
        self.assertEqual(script.returncode, 0, script.stderr)
        kit = home.home / ".local/share/agent-kit"
        kit.mkdir()
        (kit / "package.json").write_text("{}")
        (kit / "package-lock.json").write_text("{}")
        (kit / "node_modules/@cartwmic/agent-kit").mkdir(parents=True)
        (kit / "node_modules/@cartwmic/agent-kit/previous-install").write_text("1")
        bindir = home.root / "bin"
        bindir.mkdir()
        # gh: `auth status` lists the accounts (the first is active); `auth token [--user X]` prints token-<name>.
        listing = "".join("github.com\n  \u2713 Logged in to github.com account %s (keyring)\n  - Active account: %s\n" % (n, "true" if i == 0 else "false")
                          for i, n in enumerate(accounts))
        self.write_exe(bindir / "gh", """#!/bin/sh
if [ "$1 $2" = "auth status" ]; then printf '%%b' '%s'; exit 0; fi
if [ "$1 $2" = "auth token" ]; then
  if [ "${3:-}" = "--user" ]; then echo "token-$4"; else echo "token-%s"; fi; exit 0
fi
exit 1
""" % (listing, accounts[0] if accounts else ""))
        # npm: like the real one it removes node_modules first; it succeeds only with the good token.
        self.write_exe(bindir / "npm", """#!/bin/sh
rm -rf node_modules
echo "npm ci token: $NODE_AUTH_TOKEN" >> "$NPM_LOG"
if [ "$NODE_AUTH_TOKEN" != token-cartwmic ]; then echo "npm error code E403: 403 Forbidden - GET https://npm.pkg.github.com/@cartwmic%2fagent-kit" >&2; exit 1; fi
mkdir -p node_modules/@cartwmic/agent-kit && echo new > node_modules/@cartwmic/agent-kit/new-install
""")
        # curl: records its argv (what `ps` would show) and hands over to the real one.
        self.write_exe(bindir / "curl", "#!/bin/sh\necho \"$@\" >> \"$CURL_ARGS\"\nexec %s \"$@\"\n" % shutil.which("curl"))
        registry = http.server.HTTPServer(("127.0.0.1", 0), self.handler())
        threading.Thread(target=registry.serve_forever, daemon=True).start()
        self.addCleanup(registry.server_close)
        self.addCleanup(registry.shutdown)
        npm_log = home.root / "npm.log"
        env = dict(os.environ, HOME=str(home.home), PATH="%s:%s" % (bindir, os.environ["PATH"]), NPM_LOG=str(npm_log), CURL_ARGS=str(home.root / "curl.args"),
                   COORDINATOR_PACKAGE_REGISTRY="http://127.0.0.1:%d" % registry.server_address[1])
        env.pop("NODE_AUTH_TOKEN", None)

        def run(text=script.stdout, extra_env=None):
            return subprocess.run(["sh", "-c", text], capture_output=True, text=True, timeout=60, env=dict(env, **(extra_env or {})))
        return home, kit, run, npm_log

    @staticmethod
    def write_exe(path, text):
        path.write_text(text)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    @staticmethod
    def handler():
        class Registry(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                ok = self.path == "/@cartwmic%2Fagent-kit" and self.headers.get("Authorization") == "Bearer token-cartwmic"
                self.send_response(200 if ok else 403)
                self.end_headers()

            def log_message(self, *args):
                pass
        return Registry

    def test_when_the_active_account_cannot_read_the_package_the_next_logged_in_account_is_used(self):
        home, kit, run, npm_log = self.setup_install(["work", "cartwmic"])
        r = run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("npm ci token: gh account cartwmic", r.stdout)
        self.assertEqual(npm_log.read_text().strip(), "npm ci token: token-cartwmic")  # the work account's token never reached npm
        self.assertTrue((kit / "node_modules/@cartwmic/agent-kit/new-install").is_file())
        self.assertFalse((kit / "node_modules/@cartwmic/agent-kit/previous-install").exists())
        self.assertEqual(sorted(p.name for p in kit.iterdir()), ["node_modules", "package-lock.json", "package.json"])  # no staging or .previous left

    def test_no_token_is_ever_on_a_command_line(self):
        home, kit, run, npm_log = self.setup_install(["work", "cartwmic"])
        self.assertEqual(run().returncode, 0)
        args = (home.root / "curl.args").read_text()
        self.assertIn("/@cartwmic%2Fagent-kit", args)  # the probe ran
        self.assertNotIn("token-", args)  # round 1 f1: the token went to curl on stdin, not in argv where `ps` shows it

    def test_the_active_account_is_tried_first_and_a_given_NODE_AUTH_TOKEN_wins(self):
        _, kit, run, npm_log = self.setup_install(["cartwmic", "work"])
        self.assertEqual(run().returncode, 0)
        self.assertEqual(npm_log.read_text().strip(), "npm ci token: token-cartwmic")
        r = run(extra_env={"NODE_AUTH_TOKEN": "token-cartwmic"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("npm ci token: gh account", r.stdout)

    def test_no_account_can_read_it_fails_loudly_and_keeps_the_previous_install(self):
        home, kit, run, npm_log = self.setup_install(["work", "other"])
        r = run()
        self.assertEqual(r.returncode, 1)
        self.assertIn("[agent_kit_install] ERROR: npm ci failed, so", r.stderr)
        self.assertIn("node_modules was left as it was", r.stderr)
        self.assertIn("tried: work other", r.stderr)
        self.assertIn(SCRIPT_RETRY, r.stderr)
        self.assertNotIn("NODE_AUTH_TOKEN=$(gh auth token)", r.stderr)  # the old advice empties node_modules with the work account (round 1 f2)
        self.assertNotIn("token-", r.stderr.replace("token-ed", ""))  # accounts are named, tokens are not printed
        self.assertTrue((kit / "node_modules/@cartwmic/agent-kit/previous-install").is_file())  # the old install is still there
        self.assertFalse((kit / ".install-staging").exists())

    def test_red_control_the_previous_script_empties_node_modules_and_exits_0(self):
        # The pre-fix install step, verbatim: default gh account, npm ci in place, WARN and exit 0.
        _, kit, run, _ = self.setup_install(["work", "cartwmic"])
        stock = """set -eu
dir="$HOME/.local/share/agent-kit"
cd "$dir"
if NODE_AUTH_TOKEN="$(gh auth token 2>/dev/null || true)" npm ci --no-audit --no-fund; then echo installed; else echo "WARN npm ci failed"; fi
exit 0
"""
        r = run(stock)
        self.assertEqual(r.returncode, 0)
        self.assertFalse((kit / "node_modules").exists())  # E21: the install is gone and nothing said so
        self.assertIn("WARN", r.stdout)

    def test_npm_missing_is_also_an_error_not_a_quiet_exit(self):
        _, kit, run, _ = self.setup_install(["cartwmic"])
        r = run(extra_env={"PATH": "/usr/bin:/bin", "HOME": str(kit.parents[2])})
        self.assertEqual(r.returncode, 1)
        self.assertIn("ERROR: npm not found", r.stderr)

if __name__ == "__main__":
    unittest.main()
