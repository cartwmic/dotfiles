"""The phone `Match ... exec` reachability probe in ~/.ssh/config: BSD nc on macOS (unchanged), a portable probe elsewhere."""
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
CHEZMOI = shutil.which("chezmoi")


def ssh_hosts(address):
    phone = {"wgAddress": address, "lanAddress": address, "user": "u"}
    return {"dailyPhone": phone, "sshPhone": phone, "server": {"address": "s", "user": "u"}, "laptop": {"address": "l", "user": "u"}}


def probes(chezmoi_os, address="127.0.0.1"):
    data = {"profile": "personal", "chezmoi": {"os": chezmoi_os, "homeDir": "/h"}, "sshHosts": ssh_hosts(address)}
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "c.yaml"
        cfg.write_text("{}\n")
        script = subprocess.run([CHEZMOI, "--source", str(ROOT), "--config", str(cfg), "execute-template", "--override-data", json.dumps(data)],
                                input=(ROOT / "private_dot_ssh/modify_config.tmpl").read_text(), text=True, capture_output=True, timeout=60, check=True).stdout
        out = subprocess.run(["sh", "-c", script], input="", text=True, capture_output=True, timeout=30, check=True).stdout
    return out, re.findall(r'^Match host \S+ exec "(.*)"$', out, re.M)


@unittest.skipUnless(CHEZMOI, "chezmoi is required")
class SshProbeTests(unittest.TestCase):
    def test_macos_keeps_the_bsd_nc_probe_byte_for_byte(self):
        _, found = probes("darwin", "10.0.0.7")
        self.assertEqual(len(found), 4)
        self.assertEqual(set(found), {"/usr/bin/nc -z -G 1 -w 1 10.0.0.7 8022 >/dev/null 2>&1"})

    def test_linux_probe_has_no_bsd_only_flag_and_needs_no_nc(self):
        _, found = probes("linux")
        self.assertEqual(len(found), 4)
        for probe in found:
            self.assertEqual(probe.split()[:2], ["/usr/bin/timeout", "1"])
            self.assertIn("/usr/bin/bash -c ': </dev/tcp/127.0.0.1/8022'", probe)   # explicit bash: ssh runs exec via the login shell (zsh), which has no /dev/tcp
            self.assertNotIn("-G", probe)
            self.assertNotIn("nc ", probe)

    @unittest.skipUnless(Path("/usr/bin/bash").exists() and Path("/usr/bin/timeout").exists(), "/usr/bin/bash and /usr/bin/timeout are required")
    def test_linux_probe_succeeds_on_an_open_port_and_fails_fast_on_a_closed_one(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        try:
            _, (probe, *_) = probes("linux")
            command = probe.replace("8022", str(port))
            self.assertEqual(subprocess.run(["zsh" if shutil.which("zsh") else "sh", "-c", command], timeout=10).returncode, 0)   # the login shell is zsh where installed
        finally:
            server.close()
        started = time.monotonic()
        self.assertNotEqual(subprocess.run(["zsh" if shutil.which("zsh") else "sh", "-c", command], timeout=10).returncode, 0)
        self.assertLess(time.monotonic() - started, 3)


OURS = "AAAAC3NzaC1lZDI1NTE5AAAAIIe/9P7N9fERnMuJZoaiKQToUkAie/ktc6xz1QoNp5uH"
FOREIGN = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIfake pi-agent@mac\n"


def authorized_keys(chezmoi_os, existing, profile="personal"):
    data = {"profile": profile, "chezmoi": {"os": chezmoi_os, "homeDir": "/h"}}
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "c.yaml"
        cfg.write_text("{}\n")
        script = subprocess.run([CHEZMOI, "--source", str(ROOT), "--config", str(cfg), "execute-template", "--override-data", json.dumps(data)],
                                input=(ROOT / "private_dot_ssh/modify_authorized_keys.tmpl").read_text(), text=True, capture_output=True, timeout=60, check=True).stdout
        return subprocess.run(["sh", "-c", script], input=existing, text=True, capture_output=True, timeout=30, check=True).stdout


@unittest.skipUnless(CHEZMOI, "chezmoi is required")
class AuthorizedKeysTests(unittest.TestCase):
    def test_every_os_appends_the_dotfiles_key_once_and_keeps_existing_lines(self):
        # Michael's decision on ask 845: Linux gets the key too.
        for os_name in ("darwin", "linux"):
            once = authorized_keys(os_name, FOREIGN)
            self.assertTrue(once.startswith(FOREIGN), os_name)
            self.assertEqual(once.count(OURS), 1, os_name)
            self.assertEqual(authorized_keys(os_name, once), once, os_name)   # idempotent: appended once
            self.assertEqual(authorized_keys(os_name, "").count(OURS), 1, os_name)

    def test_a_file_without_a_final_newline_still_gets_the_key_on_its_own_line(self):
        out = authorized_keys("linux", FOREIGN.rstrip("\n"))
        self.assertEqual(out.splitlines()[0] + "\n", FOREIGN)
        self.assertEqual(out.count(OURS), 1)


if __name__ == "__main__":
    unittest.main()
