"""Render tests for the session keepalive: any macOS profile with the block renders the agent, a
profile without it does not.

chezmoi execute-template against the real source with --override-data, so the profile, the OS and the block are chosen
per test and the suite runs on any host (no apply, no launchd, no macOS needed). Covers the plist, its load script,
the setting template and the .chezmoiignore patterns for: work and personal, each with and without the block.
Run: python3 -m unittest discover -s tests/session-keepalive
"""
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
PLIST = REPO / "Library/LaunchAgents/local.session-keepalive.plist.tmpl"
LOADER = REPO / "run_onchange_after_79_session_keepalive_launchd.sh.tmpl"
CONFIG = REPO / ".chezmoitemplates/session_keepalive_config"
IGNORE = REPO / ".chezmoiignore"
WORK = "axon-work-computer"
CHECKS = [
    {"label": "Example VPN", "kind": "viscosity", "mode": "refresh", "connection": "Example VPN",
     "host": "git.example.com"},
    {"label": "example-cloud", "kind": "command", "mode": "alert",
     "probe": "aws sts get-caller-identity --profile example"},
]
BLOCK = {"intervalSeconds": 120, "checks": CHECKS}
PATHS = (".local/bin/session-keepalive", "Library/LaunchAgents/local.session-keepalive.plist",
         "79_session_keepalive_launchd.sh")


def render(path, profile=WORK, block=BLOCK, os_="darwin", check=True):
    """Render one source template with the given profile, OS and sessionKeepalive block (None: unset)."""
    data = {"profile": profile, "chezmoi": {"os": os_, "homeDir": "/Users/test", "sourceDir": str(REPO)}}
    if block is not None:
        data["sessionKeepalive"] = block
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
        self.assertEqual(p["Label"], "local.session-keepalive")
        self.assertEqual(p["StartInterval"], 120)
        self.assertEqual(p["ProgramArguments"], ["/usr/bin/python3", "/Users/test/.local/bin/session-keepalive"])
        checks = json.loads(p["EnvironmentVariables"]["SESSION_KEEPALIVE_CHECKS"])
        self.assertEqual(checks, [
            dict(CHECKS[0]),
            dict(CHECKS[1], probeTimeoutSeconds=20, refreshTimeoutSeconds=120),
        ])

    def test_without_the_block_the_plist_template_renders_empty(self):
        # The load script hashes this render; empty keeps the hash stable while the feature is off.
        self.assertEqual(render(PLIST, block=None).stdout, "")

    def test_a_check_list_with_shell_metacharacters_still_renders_a_valid_plist(self):
        # & < > and quotes must be escaped, or launchd refuses the plist and the agent never runs;
        # and the values must come out byte-identical after the escape round trip.
        checks = [
            dict(CHECKS[0]),
            dict(CHECKS[1],
                 probe='curl -s -H "X: a&b<c>" https://grafana.example.com/api/health && echo \'done\' >/dev/null',
                 refresh="aws sso login --profile example 2>&1 | tee /tmp/x",
                 alertCommand='/Users/you/bin/page "aws" & echo \'paged\''),
        ]
        r = render(PLIST, block={"intervalSeconds": 120, "checks": checks})
        p = plistlib.loads(r.stdout.encode())
        self.assertEqual(json.loads(p["EnvironmentVariables"]["SESSION_KEEPALIVE_CHECKS"]),
                         [dict(checks[0]),
                          dict(checks[1], probeTimeoutSeconds=20, refreshTimeoutSeconds=120)])


class DeployTest(unittest.TestCase):
    """What chezmoi would actually deploy, through managed with the profile, OS and block overridden."""

    def managed(self, profile=WORK, block=BLOCK, os_="darwin"):
        data = {"profile": profile, "chezmoi": {"os": os_, "homeDir": "/Users/test", "sourceDir": str(REPO)}}
        if block is not None:
            data["sessionKeepalive"] = block
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "chezmoi.yaml"
            cfg.write_text("data:\n  profile: personal\n")
            r = subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(cfg), "--config-format", "yaml",
                                "managed", "--override-data", json.dumps(data)],
                               capture_output=True, text=True, timeout=120, env=source_tree.chezmoi_env(tmp))
            self.assertEqual(r.returncode, 0, r.stderr)
            return set(r.stdout.split())

    def test_work_deploys_the_agent(self):
        managed = self.managed()
        for path in PATHS:
            self.assertIn(path, managed)

    def test_personal_with_the_block_deploys_the_agent_too(self):
        # No profile gate: any macOS profile with the block gets the agent (a homelab VPN, say).
        managed = self.managed(profile="personal")
        for path in PATHS:
            self.assertIn(path, managed)

    def test_personal_without_the_block_deploys_the_tick_but_not_the_plist(self):
        # The tick and its load script deploy on every macOS profile and are inert without the
        # block; only the plist is gated on the block.
        managed = self.managed(profile="personal", block=None)
        self.assertIn(".local/bin/session-keepalive", managed)
        self.assertIn("79_session_keepalive_launchd.sh", managed)
        self.assertNotIn("Library/LaunchAgents/local.session-keepalive.plist", managed)

    def test_work_without_the_block_deploys_the_tick_but_not_the_plist(self):
        managed = self.managed(block=None)
        self.assertIn(".local/bin/session-keepalive", managed)
        self.assertIn("79_session_keepalive_launchd.sh", managed)
        self.assertNotIn("Library/LaunchAgents/local.session-keepalive.plist", managed)

    def test_linux_deploys_none_of_it(self):
        managed = self.managed(os_="linux")
        for path in PATHS:
            self.assertNotIn(path, managed)


class LoaderRenderTest(unittest.TestCase):
    def test_work_with_the_block_loads_the_agent(self):
        out = render(LOADER).stdout
        self.assertIn("launchctl bootstrap", out)
        self.assertNotIn("rm -f", out)

    def test_without_the_block_the_loader_unloads_and_removes(self):
        out = render(LOADER, block=None).stdout
        self.assertIn("launchctl bootout", out)
        self.assertIn("rm -f", out)

    def test_the_loader_embeds_only_hashes_never_the_setting(self):
        # R4-N3: the loader carries a SHA-256 of the plist render and of the setting, so no command
        # or host lands in the repo through it.
        out = render(LOADER).stdout
        hashes = re.findall(r"^# (?:plist|setting): ([0-9a-f]{64})$", out, re.MULTILINE)
        self.assertEqual(len(hashes), 2, out)
        self.assertNotIn("aws sts", out)
        self.assertNotIn("git.example.com", out)
        self.assertNotIn("Example VPN", out)


class SettingTemplateTest(unittest.TestCase):
    def test_the_block_renders_the_json_the_other_templates_read(self):
        out = json.loads(render(CONFIG).stdout)
        self.assertEqual(out, {"enabled": True, "intervalSeconds": 120, "checks": [
            dict(CHECKS[0]),
            dict(CHECKS[1], probeTimeoutSeconds=20, refreshTimeoutSeconds=120),
        ]})

    def test_no_block_renders_enabled_false(self):
        self.assertEqual(json.loads(render(CONFIG, block=None).stdout), {"enabled": False})

    def test_defaults(self):
        out = json.loads(render(CONFIG, block={"checks": [
            {"label": "Example VPN", "kind": "viscosity", "connection": "Example VPN", "host": "git.example.com"},
            {"label": "example-cloud", "kind": "command", "probe": "aws sts get-caller-identity --profile example"},
        ]}).stdout)
        self.assertEqual(out["intervalSeconds"], 120)   # the tick interval, default 120
        self.assertEqual(out["checks"][0]["mode"], "alert")   # alert is the default for every kind
        self.assertEqual(out["checks"][1]["probeTimeoutSeconds"], 20)
        self.assertEqual(out["checks"][1]["refreshTimeoutSeconds"], 120)
        self.assertNotIn("intervalSeconds", out["checks"][0])
        self.assertNotIn("alertCommand", out["checks"][0])

    def test_bad_values_fail_the_render(self):
        viscosity = dict(CHECKS[0])
        command = dict(CHECKS[1], probeTimeoutSeconds=20, refreshTimeoutSeconds=120)
        bad = [
            dict(BLOCK, intervalSeconds=10),            # global interval out of range
            dict(BLOCK, intervalSeconds=4000),
            dict(BLOCK, checks=[]),                     # empty check list
            dict(BLOCK, checks="nope"),                 # not a list
            dict(BLOCK, extra=1),                       # unknown top-level key
            dict(BLOCK, checks=[dict(command, extra=1)]),          # unknown per-check key
            dict(BLOCK, checks=[dict(command, kind="http")]),      # unknown kind
            dict(BLOCK, checks=[dict(command, mode="restart")]),   # unknown mode
            dict(BLOCK, checks=[dict(command, mode="refresh")]),   # refresh mode without a refresh command
            dict(BLOCK, checks=[dict(command, label="Bad,Label")]),  # label charset: comma
            dict(BLOCK, checks=[dict(command, label='Bad"Label')]),  # label charset: quote
            dict(BLOCK, checks=[dict(command, label="")]),         # label charset: empty
            dict(BLOCK, checks=[dict(command, probe="")]),         # command check without a probe
            dict(BLOCK, checks=[dict(command, probeTimeoutSeconds=3)]),   # probe timeout under 5
            dict(BLOCK, checks=[dict(command, probeTimeoutSeconds=200)]), # probe timeout over 120
            dict(BLOCK, checks=[dict(command, mode="refresh", refresh="x", refreshTimeoutSeconds=5)]),   # under 10
            dict(BLOCK, checks=[dict(command, mode="refresh", refresh="x", refreshTimeoutSeconds=700)]), # over 600
            dict(BLOCK, checks=[dict(command, intervalSeconds=10)]),      # per-check interval under 30
            dict(BLOCK, checks=[dict(command, intervalSeconds=4000)]),    # per-check interval over 3600
            dict(BLOCK, checks=[dict(viscosity, probe="x")]),      # a viscosity check has no probe
            dict(BLOCK, checks=[dict(command, connection="x")]),   # a command check has no connection
            dict(BLOCK, checks=[dict(viscosity, connection='Bad"Name')]),
            dict(BLOCK, checks=[dict(viscosity, connection="A,B")]),
            dict(BLOCK, checks=[dict(viscosity, host="not a host")]),
            dict(BLOCK, checks=[dict(viscosity, host="")]),
            # Labels are unique case-insensitively (R4-N5).
            dict(BLOCK, checks=[dict(command, label="AWS"), dict(command, label="aws", probe="x2")]),
        ]
        for block in bad:
            r = render(CONFIG, block=block, check=False)
            self.assertNotEqual(r.returncode, 0, block)

    def test_refresh_mode_with_a_refresh_command_renders(self):
        out = json.loads(render(CONFIG, block={"checks": [
            dict(CHECKS[1], mode="refresh", refresh="aws sso login --profile example"),
        ]}).stdout)
        self.assertEqual(out["checks"][0]["mode"], "refresh")
        self.assertEqual(out["checks"][0]["refresh"], "aws sso login --profile example")


class IgnoreTest(unittest.TestCase):
    def test_personal_without_the_block_ignores_the_plist_only(self):
        out = render(IGNORE, profile="personal", block=None).stdout
        self.assertIn("Library/LaunchAgents/local.session-keepalive.plist", out)
        self.assertNotIn(".local/bin/session-keepalive", out)
        self.assertNotIn("79_session_keepalive_launchd.sh", out)

    def test_work_with_the_block_ignores_none_of_them(self):
        out = render(IGNORE).stdout
        for path in PATHS:
            self.assertNotIn(path, out)

    def test_personal_with_the_block_ignores_none_of_them(self):
        # No profile gate: personal with the block gets the agent too.
        out = render(IGNORE, profile="personal").stdout
        for path in PATHS:
            self.assertNotIn(path, out)

    def test_work_without_the_block_ignores_the_plist_only(self):
        out = render(IGNORE, block=None).stdout
        self.assertNotIn(".local/bin/session-keepalive", out)
        self.assertNotIn("79_session_keepalive_launchd.sh", out)
        self.assertIn("Library/LaunchAgents/local.session-keepalive.plist", out)

    def test_linux_ignores_every_path(self):
        out = render(IGNORE, os_="linux").stdout
        for path in PATHS:
            self.assertIn(path, out)


if __name__ == "__main__":
    unittest.main()
