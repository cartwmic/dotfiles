"""configure_rustdesk.sh on Linux with a systemd service: a fresh install has no running service, so `rustdesk --password` never prints "Done!".

The real helper (rendered by chezmoi) runs in a private HOME with scripted sudo, systemctl, pgrep, op and rustdesk. The scripted `rustdesk --password`
prints "Done!" only once the scripted service has been started, as the real one needs a running `rustdesk --server`. `tests/rustdesk/configure_rustdesk-before.sh.tmpl`
is the helper as it was on main before the fix (RED control)."""
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CHEZMOI = shutil.which("chezmoi")
CFG = Path(tempfile.gettempdir()) / "rustdesk-test-chezmoi.yaml"
CFG.write_text("{}\n")
HELPER = ROOT / "dot_local/user_scripts/executable_configure_rustdesk.sh.tmpl"
BEFORE = Path(__file__).parent / "configure_rustdesk-before.sh.tmpl"
STAGE60 = ROOT / "run_onchange_after_60_configure_rustdesk.sh.tmpl"
DATA = {"profile": "personal", "rustdesk": {"server": "rd.test", "port": 21116, "publicKey": "PUBKEY", "passwordReference": "op://test/rustdesk/password"},
        "chezmoi": {"os": "linux"}}

# sudo: record, then run the command (systemctl goes to the scripted one on PATH; `-H -- sh -c` runs as the user).
SUDO = '''#!/bin/sh
echo "sudo $*" >> "$T/calls"
while [ $# -gt 0 ]; do case "$1" in -H|-E|--) shift ;; *) break ;; esac; done
exec "$@"
'''
# systemctl: `cat` succeeds (the unit exists); `enable --now` starts the service, whose `rustdesk --server` child appears after $SERVER_DELAY pgrep polls.
SYSTEMCTL = '''#!/bin/sh
echo "systemctl $*" >> "$T/calls"
case "$1" in
  cat) exit 0 ;;
  is-active) [ -f "$T/service-started" ] ;;
  enable) case " $* " in *" --now "*) : > "$T/service-started" ;; esac ;;
  restart|start) : > "$T/service-started" ;;
esac
exit 0
'''
PGREP = '''#!/bin/sh
echo "pgrep $*" >> "$T/calls"
case "$*" in
  *"-x rustdesk"*) exit 1 ;;   # no GUI running
  *"rustdesk --server"*)
    [ -f "$T/service-started" ] || exit 1
    n=$(cat "$T/polls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$T/polls"
    [ "$n" -gt "${SERVER_DELAY:-0}" ] ;;
  *) exit 1 ;;
esac
'''
OP = '#!/bin/sh\nprintf "s3cret"\n'
RUSTDESK = '''#!/bin/sh
echo "rustdesk $1" >> "$T/calls"
# the real CLI needs a running --server to answer; without one it prints nothing useful (and exits 0)
if [ "$1" = --password ] && [ -f "$T/service-started" ] && [ "$(cat "$T/polls" 2>/dev/null || echo 0)" -gt "${SERVER_DELAY:-0}" ]; then echo "Done!"; else echo "connection refused"; fi
'''


def script(path, data):
    return subprocess.run([CHEZMOI, "--source", str(ROOT), "--config", str(CFG), "--config-format", "yaml", "execute-template", "--override-data", json.dumps(data)],
                          input=path.read_text(), text=True, capture_output=True, timeout=60, check=True).stdout


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("python3"), "chezmoi and python3 are required")
class RustdeskLinux(unittest.TestCase):
    def run_helper(self, template=HELPER, delay=0):
        tmp = tempfile.TemporaryDirectory(prefix="rustdesk-test-")
        self.addCleanup(tmp.cleanup)
        t = Path(tmp.name)
        bin_, home = t / "bin", t / "home"
        bin_.mkdir()
        home.mkdir()
        (t / "calls").write_text("")
        for name, text in (("sudo", SUDO), ("systemctl", SYSTEMCTL), ("pgrep", PGREP), ("op", OP), ("rustdesk", RUSTDESK)):
            (bin_ / name).write_text(text)
            (bin_ / name).chmod(0o755)
        helper = t / "configure_rustdesk.sh"
        helper.write_text(script(template, DATA))
        env = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(home), "T": str(t), "TMPDIR": str(t), "SERVER_DELAY": str(delay),
               "RUSTDESK_OS": "Linux", "RUSTDESK_BIN": str(bin_ / "rustdesk"), "RUSTDESK_SKIP_ROOT_CONFIG": "1", "RUSTDESK_SERVER_WAIT": "20",
               "OP_SERVICE_ACCOUNT_TOKEN": "test-token", "PYTHON_BIN": sys.executable, "XDG_CONFIG_HOME": str(home / ".config")}
        done = subprocess.run(["sh", str(helper)], env=env, text=True, capture_output=True, timeout=60)
        return done, (t / "calls").read_text().splitlines()

    def test_the_service_is_enabled_and_running_before_the_password_is_applied(self):
        done, calls = self.run_helper(delay=2)   # the --server child shows up on the third check
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        enable = calls.index("sudo systemctl enable --now rustdesk.service")
        polls = [i for i, c in enumerate(calls) if c.startswith("pgrep") and "rustdesk --server" in c]
        password = calls.index("rustdesk --password")
        self.assertEqual(len(polls), 3, calls)
        self.assertTrue(enable < polls[0] < polls[-1] < password, calls)
        self.assertIn("sudo systemctl restart rustdesk.service", calls)   # the existing restart at the end stays
        self.assertIn("applied permanent password", done.stderr)

    def test_a_service_that_never_runs_fails_with_a_bound_and_a_pointer_not_a_hang(self):
        done, calls = self.run_helper(delay=10 ** 6)
        self.assertEqual(done.returncode, 1)
        self.assertIn("rustdesk --server did not start within 20 checks", done.stderr)
        self.assertNotIn("rustdesk --password", calls)

    def test_RED_control_the_helper_from_main_dies_with_the_confirm_error(self):
        done, calls = self.run_helper(template=BEFORE)
        self.assertEqual(done.returncode, 1)
        self.assertIn("RustDesk did not confirm permanent-password update", done.stderr)
        self.assertLess(calls.index("rustdesk --password"), len(calls))
        self.assertNotIn("sudo systemctl enable --now rustdesk.service", calls)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required")
class Stage60Hash(unittest.TestCase):
    """Installing rustdesk after the first apply must re-run the configure stage: whether it is installed is in the rendered script."""

    def rendered(self, os_name, with_rustdesk):
        with tempfile.TemporaryDirectory() as tmp:
            bin_ = Path(tmp) / "bin"
            bin_.mkdir()
            if with_rustdesk:
                (bin_ / "rustdesk").write_text("#!/bin/sh\n")
                (bin_ / "rustdesk").chmod(0o755)
            data = {**DATA, "chezmoi": {"os": os_name, "sourceDir": str(ROOT)}}
            return subprocess.run([CHEZMOI, "--source", str(ROOT), "--config", str(CFG), "--config-format", "yaml", "execute-template", "--override-data", json.dumps(data)],
                                  input=STAGE60.read_text(), text=True, capture_output=True, timeout=60, check=True,
                                  env={**os.environ, "PATH": str(bin_)}).stdout

    def test_linux_render_changes_when_rustdesk_appears_on_path(self):
        before, after = self.rendered("linux", False), self.rendered("linux", True)
        self.assertNotEqual(before, after)
        self.assertIn("# RustDesk installed: no", before)
        self.assertIn("# RustDesk installed: yes", after)

    def test_macos_render_is_independent_of_rustdesk_on_path(self):
        self.assertEqual(self.rendered("darwin", False), self.rendered("darwin", True))
        self.assertNotIn("RustDesk installed", self.rendered("darwin", True))


if __name__ == "__main__":
    unittest.main()
