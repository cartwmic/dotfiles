#!/usr/bin/env python3
"""opnsense-phone.php takes both subnet prefixes from its caller and refuses without them.

Runs the real PHP against a stub OPNsense config (config.inc/util.inc), so it needs `php` on PATH
(or PHP_BIN). Without php they are skipped.
Only documentation address ranges (192.0.2.x, 198.51.100.x, 203.0.113.x) appear here.
"""
import base64
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHP_SCRIPT = ROOT / "termux" / "opnsense-phone.php"
PHP = os.environ.get("PHP_BIN") or shutil.which("php")
PUBKEY = base64.b64encode(bytes([3]) * 32).decode()
LAN, WG = "192.0.2.", "198.51.100."

CONFIG_INC = f"""<?php
$config = ['OPNsense' => ['wireguard' => [
    'client' => ['clients' => ['client' => [
        ['@attributes' => ['uuid' => 'old-uuid'], 'enabled' => '1', 'name' => 'cartwmic-ssh-phone',
         'pubkey' => '{PUBKEY}', 'tunneladdress' => '{WG}7/32'],
    ]]],
    'server' => ['servers' => [
        ['server' => ['instance' => '1', 'name' => 'cartwmic-homelab', 'pubkey' => '{PUBKEY}', 'peers' => 'old-uuid']],
    ]],
]], 'dhcpd' => ['lan' => ['staticmap' => [
    ['hostname' => 'ssh-phone', 'ipaddr' => '{LAN}88', 'mac' => '5e:51:a2:24:38:79'],
]]]];
function write_config($message) {{}}
"""



def spec(action, **extra):
    value = {"action": action, "mode": extra.pop("mode", "inspect"), **extra}
    return base64.b64encode(json.dumps(value).encode()).decode()


@unittest.skipUnless(PHP, "php not installed (set PHP_BIN to run the PHP tests)")
class OpnsensePhoneTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="opnsense-php-test-")
        self.addCleanup(temp.cleanup)
        self.inc = Path(temp.name)
        (self.inc / "config.inc").write_text(CONFIG_INC)
        (self.inc / "util.inc").write_text("<?php\n")

    def run_php(self, request, **env):
        full = {k: v for k, v in os.environ.items() if not k.startswith("HOMELAB_")}
        full.update(env, PHONE_SPEC_B64=request)
        return subprocess.run([PHP, "-d", f"include_path={self.inc}", str(PHP_SCRIPT)],
                              env=full, capture_output=True, text=True, timeout=60)

    def test_matching_prefixes_accept_the_existing_peer(self):
        for action in ("inspect", "plan"):
            with self.subTest(action=action):
                extra = {} if action == "inspect" else dict(
                    mode="stage", mac="5e:51:a2:24:38:7a", lan=f"{LAN}89", address=f"{WG}8/32",
                    public_key=base64.b64encode(bytes([2]) * 32).decode())
                result = self.run_php(spec(action, **extra), HOMELAB_LAN_PREFIX=LAN, HOMELAB_WG_PREFIX=WG)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["old_peer"]["address"], f"{WG}7/32")

    def test_missing_or_malformed_prefix_is_refused_loudly_for_every_action(self):
        bad = {"missing": {}, "empty": {"HOMELAB_LAN_PREFIX": "", "HOMELAB_WG_PREFIX": WG},
               "no trailing dot": {"HOMELAB_LAN_PREFIX": "192.0.2", "HOMELAB_WG_PREFIX": WG},
               "wildcard": {"HOMELAB_LAN_PREFIX": LAN, "HOMELAB_WG_PREFIX": ".*"},
               "octet over 255": {"HOMELAB_LAN_PREFIX": "999.0.2.", "HOMELAB_WG_PREFIX": WG},
               "trailing newline": {"HOMELAB_LAN_PREFIX": LAN + "\n", "HOMELAB_WG_PREFIX": WG},
               "wg only": {"HOMELAB_WG_PREFIX": WG}, "lan only": {"HOMELAB_LAN_PREFIX": LAN}}
        for name, env in bad.items():
            for action in ("inspect", "plan", "apply"):
                with self.subTest(case=name, action=action):
                    result = self.run_php(spec(action), **env)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("HOMELAB_LAN_PREFIX and HOMELAB_WG_PREFIX are required", result.stderr)
                    self.assertEqual(result.stdout, "")

    def test_prefix_that_does_not_match_the_router_is_refused_not_ignored(self):
        other = "203.0.113."
        for env in ({"HOMELAB_LAN_PREFIX": other, "HOMELAB_WG_PREFIX": WG},
                    {"HOMELAB_LAN_PREFIX": LAN, "HOMELAB_WG_PREFIX": other}):
            with self.subTest(env=env):
                result = self.run_php(spec("inspect"), **env)
                self.assertEqual(result.returncode, 2)
                self.assertIn("unsupported address/key", result.stderr)

    def test_prefix_dots_are_literal(self):
        # preg_quote: '198x51x100.' must not match '198.51.100.7'.
        result = self.run_php(spec("inspect"), HOMELAB_LAN_PREFIX=LAN, HOMELAB_WG_PREFIX="198.51.1.")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
