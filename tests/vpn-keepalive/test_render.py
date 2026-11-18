"""Render tests for the VPN keepalive: the work profile renders the agent, personal does not.

chezmoi execute-template against the real source with --override-data, so the profile and the OS are chosen per
test and the suite runs on any host (no apply, no launchd, no macOS needed). Covers the plist, its load script,
the setting template and the .chezmoiignore patterns for: work with the block set, work without it, and personal.
Run: python3 -m unittest discover -s tests/vpn-keepalive
"""
import json
import os
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLIST = REPO / "Library/LaunchAgents/local.vpn-keepalive.plist.tmpl"
LOADER = REPO / "run_onchange_after_79_vpn_keepalive_launchd.sh.tmpl"
CONFIG = REPO / ".chezmoitemplates/vpn_keepalive_config"
IGNORE = REPO / ".chezmoiignore"
WORK = "axon-work-computer"
BLOCK = {"connection": "Test VPN", "host": "vpn.example.com", "mode": "reconnect", "intervalSeconds": 120}
PATHS = (".local/bin/vpn-keepalive", "Library/LaunchAgents/local.vpn-keepalive.plist", "79_vpn_keepalive_launchd.sh")


def render(path, profile=WORK, block=BLOCK, os_="darwin", check=True):
    """Render one source template with the given profile, OS and vpnKeepalive block (None: unset)."""
    data = {"profile": profile, "chezmoi": {"os": os_, "homeDir": "/Users/test", "sourceDir": str(REPO)}}
    if block is not None:
        data["vpnKeepalive"] = block
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("data:\n  profile: personal\n")
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml",
                            "execute-template", "--override-data", json.dumps(data)],
                           input=path.read_text(), capture_output=True, text=True, timeout=120,
                           env={**os.environ, "HOME": str(tmp)})
        if check and r.returncode:
            raise AssertionError("chezmoi execute-template failed: %s" % r.stderr)
        return r


class PlistRenderTest(unittest.TestCase):
    def test_work_renders_the_agent(self):
        r = render(PLIST)
        p = plistlib.loads(r.stdout.encode())
        self.assertEqual(p["Label"], "local.vpn-keepalive")
        self.assertEqual(p["StartInterval"], 120)
        self.assertEqual(p["ProgramArguments"], ["/usr/bin/python3", "/Users/test/.local/bin/vpn-keepalive"])
        env = p["EnvironmentVariables"]
        self.assertEqual(env["VPN_KEEPALIVE_CONNECTION"], "Test VPN")
        self.assertEqual(env["VPN_KEEPALIVE_HOST"], "vpn.example.com")
        self.assertEqual(env["VPN_KEEPALIVE_MODE"], "reconnect")
        self.assertNotIn("VPN_KEEPALIVE_ALERT_COMMAND", env)

    def test_without_the_block_the_plist_template_renders_empty(self):
        # The load script hashes this render; empty keeps the hash stable while the feature is off.
        self.assertEqual(render(PLIST, block=None).stdout, "")


class DeployTest(unittest.TestCase):
    """What chezmoi would actually deploy, through managed with the profile, OS and block overridden."""

    def managed(self, profile=WORK, block=BLOCK):
        data = {"profile": profile, "chezmoi": {"os": "darwin", "homeDir": "/Users/test", "sourceDir": str(REPO)}}
        if block is not None:
            data["vpnKeepalive"] = block
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "chezmoi.yaml"
            cfg.write_text("data:\n  profile: personal\n")
            r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml",
                                "managed", "--override-data", json.dumps(data)],
                               capture_output=True, text=True, timeout=120, env={**os.environ, "HOME": str(tmp)})
            self.assertEqual(r.returncode, 0, r.stderr)
            return set(r.stdout.split())

    def test_work_deploys_the_agent(self):
        managed = self.managed()
        for path in PATHS:
            self.assertIn(path, managed)

    def test_personal_deploys_none_of_it(self):
        managed = self.managed(profile="personal")
        for path in PATHS:
            self.assertNotIn(path, managed)

    def test_work_without_the_block_deploys_the_tick_but_not_the_plist(self):
        managed = self.managed(block=None)
        self.assertIn(".local/bin/vpn-keepalive", managed)
        self.assertIn("79_vpn_keepalive_launchd.sh", managed)
        self.assertNotIn("Library/LaunchAgents/local.vpn-keepalive.plist", managed)

    def test_an_optional_alert_command_renders_into_the_environment(self):
        r = render(PLIST, block=dict(BLOCK, alertCommand="/Users/you/bin/notify-vpn"))
        p = plistlib.loads(r.stdout.encode())
        self.assertEqual(p["EnvironmentVariables"]["VPN_KEEPALIVE_ALERT_COMMAND"], "/Users/you/bin/notify-vpn")

    def test_an_alert_command_with_shell_metacharacters_still_renders_a_valid_plist(self):
        # & < > and quotes must be escaped, or launchd refuses the plist and the agent never runs.
        cmd = '/Users/you/bin/notify "vpn" && echo \'done\' > /dev/null 2>&1 < /dev/null'
        r = render(PLIST, block=dict(BLOCK, alertCommand=cmd))
        p = plistlib.loads(r.stdout.encode())
        self.assertEqual(p["EnvironmentVariables"]["VPN_KEEPALIVE_ALERT_COMMAND"], cmd)


class LoaderRenderTest(unittest.TestCase):
    def test_work_with_the_block_loads_the_agent(self):
        out = render(LOADER).stdout
        self.assertIn("launchctl bootstrap", out)
        self.assertNotIn("rm -f", out)

    def test_without_the_block_the_loader_unloads_and_removes(self):
        out = render(LOADER, block=None).stdout
        self.assertIn("launchctl bootout", out)
        self.assertIn("rm -f", out)


class SettingTemplateTest(unittest.TestCase):
    def test_the_block_renders_the_json_the_other_templates_read(self):
        out = json.loads(render(CONFIG).stdout)
        self.assertEqual(out, dict(BLOCK, enabled=True))

    def test_no_block_renders_enabled_false(self):
        self.assertEqual(json.loads(render(CONFIG, block=None).stdout), {"enabled": False})

    def test_defaults(self):
        out = json.loads(render(CONFIG, block={"connection": "Test VPN", "host": "vpn.example.com",
                                               "mode": "reconnect"}).stdout)
        self.assertEqual(out["intervalSeconds"], 120)
        self.assertNotIn("alertCommand", out)

    def test_bad_values_fail_the_render(self):
        bad = [dict(BLOCK, mode="restart"), dict(BLOCK, intervalSeconds=10), dict(BLOCK, intervalSeconds=4000),
               dict(BLOCK, connection='Bad"Name'), dict(BLOCK, connection="A,B"), dict(BLOCK, host="not a host"),
               dict(BLOCK, extra=1), {"connection": "Test VPN"}]
        for block in bad:
            r = render(CONFIG, block=block, check=False)
            self.assertNotEqual(r.returncode, 0, block)


class IgnoreTest(unittest.TestCase):
    def test_personal_ignores_every_path(self):
        out = render(IGNORE, profile="personal").stdout
        for path in PATHS:
            self.assertIn(path, out)

    def test_work_with_the_block_ignores_none_of_them(self):
        out = render(IGNORE).stdout
        for path in PATHS:
            self.assertNotIn(path, out)

    def test_work_without_the_block_ignores_the_plist_only(self):
        out = render(IGNORE, block=None).stdout
        self.assertNotIn(".local/bin/vpn-keepalive", out)
        self.assertNotIn("79_vpn_keepalive_launchd.sh", out)
        self.assertIn("Library/LaunchAgents/local.vpn-keepalive.plist", out)


if __name__ == "__main__":
    unittest.main()
