"""Client-only RustDesk on the work Mac: configure_rustdesk_client.sh and 61_configure_rustdesk_client.sh.

The helper is rendered by chezmoi for axon-work-computer on darwin and run with RUSTDESK_OS=Darwin in a private HOME, with a scripted
pgrep (RustDesk running or not) and plist paths in the temp dir. Checks: RustDesk's own settings that keep it from being reachable are
written; a rerun changes nothing; an installed launchd service or a running app stops it; the rendered scripts never call sudo, op,
`--password` or launchctl; and .chezmoiignore gives the client files to work macOS only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
CHEZMOI = shutil.which("chezmoi")
CFG = Path(tempfile.gettempdir()) / "rustdesk-client-test-chezmoi.yaml"
CFG.write_text("{}\n")
HELPER = ROOT / "dot_local/user_scripts/executable_configure_rustdesk_client.sh.tmpl"
STAGE61 = ROOT / "run_onchange_after_61_configure_rustdesk_client.sh.tmpl"
WORK = {"profile": "axon-work-computer", "chezmoi": {"os": "darwin", "homeDir": "/Users/test"}}
CLIENT_ONLY = {"stop-service": "Y", "direct-server": "N", "enable-lan-discovery": "N", "approve-mode": "click",
               "verification-method": "use-temporary-password"}


def render(text, data):
    return subprocess.run([CHEZMOI, "--source", str(ROOT), "--config", str(CFG), "--config-format", "yaml", "execute-template",
                           "--override-data", json.dumps(data)], input=text, text=True, capture_output=True, timeout=60, check=True).stdout


@unittest.skipUnless(CHEZMOI, "chezmoi is required")
class ClientHelper(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="rustdesk-client-")
        self.addCleanup(tmp.cleanup)
        self.t = Path(tmp.name)
        (self.t / "bin").mkdir()
        self.pgrep(running=False)
        self.config = self.t / "prefs" / "RustDesk2.toml"

    def pgrep(self, running):
        p = self.t / "bin" / "pgrep"
        p.write_text("#!/bin/sh\nexit %d\n" % (0 if running else 1))
        p.chmod(0o755)

    def run_helper(self, data=WORK):
        helper = self.t / "configure_rustdesk_client.sh"
        helper.write_text(render(HELPER.read_text(), data))
        env = {"PATH": f"{self.t / 'bin'}:/usr/bin:/bin", "HOME": str(self.t), "TMPDIR": str(self.t), "RUSTDESK_OS": "Darwin",
               "RUSTDESK_CONFIG_DIR": str(self.config.parent), "RUSTDESK_AGENT_PLIST": str(self.t / "agent.plist"),
               "RUSTDESK_DAEMON_PLIST": str(self.t / "daemon.plist"), "PYTHON_BIN": sys.executable}
        return subprocess.run(["sh", str(helper)], env=env, text=True, capture_output=True, timeout=60)

    def options(self):
        return tomllib.loads(self.config.read_text())

    def test_fresh_machine_gets_the_client_only_settings_and_no_server(self):
        done = self.run_helper()
        self.assertEqual(done.returncode, 0, done.stderr)
        cfg = self.options()
        self.assertEqual({k: cfg["options"][k] for k in CLIENT_ONLY}, CLIENT_ONLY)
        self.assertNotIn("rendezvous_server", cfg)
        self.assertNotIn("custom-rendezvous-server", cfg["options"])
        self.assertEqual(oct(self.config.stat().st_mode & 0o777), "0o600")

    def test_relay_from_local_data_and_other_keys_kept(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text("nat_type = 1\n\n[options]\nstop-service = ''\nlocal-ip-addr = '10.0.0.5'\n")
        done = self.run_helper({**WORK, "rustdesk": {"server": "rd.test"}})
        self.assertEqual(done.returncode, 0, done.stderr)
        cfg = self.options()
        self.assertEqual(cfg["rendezvous_server"], "rd.test:21116")
        self.assertEqual(cfg["options"]["relay-server"], "rd.test")
        self.assertEqual(cfg["options"]["stop-service"], "Y")
        self.assertEqual(cfg["options"]["local-ip-addr"], "10.0.0.5")
        self.assertEqual(cfg["nat_type"], 1)
        self.assertTrue(Path(str(self.config) + ".chezmoi-backup").exists())

    def test_rerun_is_a_no_op_even_while_rustdesk_runs(self):
        self.assertEqual(self.run_helper().returncode, 0)
        before = self.config.read_text()
        self.pgrep(running=True)
        done = self.run_helper()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("already current", done.stderr)
        self.assertEqual(self.config.read_text(), before)

    def test_service_turned_back_on_while_running_stops_with_quit_message(self):
        self.assertEqual(self.run_helper().returncode, 0)
        self.config.write_text(self.config.read_text().replace('stop-service = "Y"', 'stop-service = ""'))
        self.pgrep(running=True)
        done = self.run_helper()
        self.assertEqual(done.returncode, 1)
        self.assertIn("quit RustDesk", done.stderr)
        self.pgrep(running=False)
        self.assertEqual(self.run_helper().returncode, 0)
        self.assertEqual(self.options()["options"]["stop-service"], "Y")

    def test_installed_launchd_service_stops_it(self):
        for name in ("agent.plist", "daemon.plist"):
            (self.t / name).write_text("<plist/>")
            done = self.run_helper()
            self.assertEqual(done.returncode, 1)
            self.assertIn("launchd service is installed", done.stderr)
            self.assertFalse(self.config.exists())
            (self.t / name).unlink()

    def test_rendered_scripts_call_no_server_side_command(self):
        for text in (render(HELPER.read_text(), {**WORK, "rustdesk": {"server": "rd.test"}}), render(STAGE61.read_text(), WORK)):
            code = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
            for word in ("sudo ", "op read", "op://", "--password", "launchctl ", "systemctl"):
                self.assertFalse([c for c in code if word in c and not c.startswith("die ")], word)


@unittest.skipUnless(CHEZMOI, "chezmoi is required")
class Gates(unittest.TestCase):
    def ignored(self, profile, os_name):
        return render((ROOT / ".chezmoiignore").read_text(), {"profile": profile, "chezmoi": {"os": os_name}}).splitlines()

    def test_client_files_land_on_work_macos_only(self):
        files = (".local/user_scripts/configure_rustdesk_client.sh", "61_configure_rustdesk_client.sh")
        for f in files:
            self.assertNotIn(f, self.ignored("axon-work-computer", "darwin"))
            self.assertIn(f, self.ignored("personal", "darwin"))
            self.assertIn(f, self.ignored("personal", "linux"))
        self.assertIn(".local/user_scripts/configure_rustdesk.sh", self.ignored("axon-work-computer", "darwin"))

    def test_stage61_reruns_when_settings_or_plists_change(self):
        out = render(STAGE61.read_text(), WORK)
        for line in ("# Settings hash: none", "# Agent plist: absent", "# Daemon plist: absent"):
            self.assertIn(line, out)

    def test_stage61_hash_follows_the_settings_file(self):
        with tempfile.TemporaryDirectory() as home:
            cfg = Path(home) / "Library/Preferences/com.carriez.RustDesk/RustDesk2.toml"
            cfg.parent.mkdir(parents=True)
            data = {**WORK, "chezmoi": {"os": "darwin", "homeDir": home}}
            cfg.write_text('[options]\nstop-service = "Y"\n')
            first = render(STAGE61.read_text(), data)
            cfg.write_text('[options]\nstop-service = ""\n')
            second = render(STAGE61.read_text(), data)
        hashes = [line for out in (first, second) for line in out.splitlines() if line.startswith("# Settings hash: ")]
        self.assertEqual(len(hashes), 2)
        self.assertNotIn("none", hashes[0])
        self.assertNotEqual(hashes[0], hashes[1])


if __name__ == "__main__":
    unittest.main()
