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
            self.assertNotIn("-G", probe)
            self.assertNotIn("nc ", probe)

    @unittest.skipUnless(shutil.which("bash") and shutil.which("timeout"), "bash and timeout are required")
    def test_linux_probe_succeeds_on_an_open_port_and_fails_fast_on_a_closed_one(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        try:
            _, (probe, *_) = probes("linux")
            # ssh hands the quoted string to the user's shell; undo the config-file escape of the inner quotes the way ssh does.
            command = probe.replace('\\"', '"').replace("8022", str(port))
            self.assertEqual(subprocess.run(["sh", "-c", command], timeout=10).returncode, 0)
        finally:
            server.close()
        started = time.monotonic()
        self.assertNotEqual(subprocess.run(["sh", "-c", command], timeout=10).returncode, 0)
        self.assertLess(time.monotonic() - started, 3)


if __name__ == "__main__":
    unittest.main()
