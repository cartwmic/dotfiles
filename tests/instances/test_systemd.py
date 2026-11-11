"""Instances on Linux: the coordinator's systemd user unit and the reconcile script that starts and stops it (the macOS tests are test_instances.py).

    python3 -m unittest discover -s tests/instances -v

  RenderTests   the unit template renders to the golden unit; local data changes only the checkout; the wrapper picks the right script per OS
                and the macOS wrapper render is what it was.
  MatrixTests   instances_reconcile_systemd.sh run directly in a scratch HOME with a stub systemctl that keeps active/not-active state and
                records every call. Each case asserts the EXACT list of calls (the safety rules: no restart because a unit changed, opt-out
                acts only on what dotfiles started or adopted, a machine that never opted in sees no call).
Nothing here reads or writes the real home, the real chezmoi state or the real systemd.
"""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
UNIT_TEMPLATE = ROOT / "dot_local" / "share" / "instances" / "systemd" / "coordinatord.service.tmpl"
WRAPPER = ROOT / "run_after_75_instances_reconcile.sh.tmpl"
SCRIPT = Path(os.environ.get("INSTANCES_SYSTEMD_SCRIPT_UNDER_TEST") or ROOT / "dot_local" / "user_scripts" / "executable_instances_reconcile_systemd.sh")
GOLDEN = HERE / "golden" / "coordinatord.service"
HAVE_CHEZMOI = shutil.which("chezmoi") is not None
HAVE_TIMEOUT = shutil.which("timeout") is not None


def render(template, data, home="/home/test", chezmoi_os="linux"):
    data = {**data, "chezmoi": {"os": chezmoi_os, "homeDir": home}}
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "chezmoi.yaml"
        config.write_text("{}\n")
        result = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(config), "execute-template", "--override-data", json.dumps(data)],
            input=template.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=home),
        )
    assert result.returncode == 0, result.stderr
    return result.stdout


@unittest.skipUnless(HAVE_CHEZMOI, "chezmoi not installed")
class RenderTests(unittest.TestCase):
    def test_default_render_is_the_golden_unit(self):
        self.assertEqual(render(UNIT_TEMPLATE, {"profile": "personal"}), GOLDEN.read_text(encoding="utf-8"))

    def test_the_unit_says_what_the_plist_says(self):
        text = render(UNIT_TEMPLATE, {"profile": "personal"})
        self.assertIn("ExecStart=/usr/bin/env node --experimental-strip-types --disable-warning=ExperimentalWarning /home/test/git/coordinator/src/coordinatord/main.ts\n", text)
        self.assertIn("WorkingDirectory=%h\n", text)                    # home, not the checkout, as in the plist
        self.assertIn("Environment=PATH=/home/test/.local/share/mise/shims:", text)
        self.assertIn("Restart=on-failure\n", text)                     # KeepAlive SuccessfulExit=false
        self.assertIn("RestartSec=10\n", text)                          # ThrottleInterval 10
        self.assertIn("WantedBy=default.target\n", text)

    def test_local_data_changes_only_the_checkout_path(self):
        data = {"profile": "personal", "instances": {"coordinator": {"repo": "/srv/co"}}}
        self.assertEqual(render(UNIT_TEMPLATE, data), GOLDEN.read_text(encoding="utf-8").replace("/home/test/git/coordinator", "/srv/co"))

    def test_a_percent_in_a_path_is_escaped_for_systemd(self):
        text = render(UNIT_TEMPLATE, {"profile": "personal", "instances": {"coordinator": {"repo": "/srv/50%/co"}}})
        self.assertIn("/srv/50%%/co/src/coordinatord/main.ts", text)

    def test_wrapper_runs_the_systemd_script_on_linux_and_the_launchd_one_elsewhere(self):
        data = {"profile": "personal", "instances": {"coordinator": {"enabled": True}}}
        linux = render(WRAPPER, data)
        self.assertIn('SCRIPT="$HOME/.local/user_scripts/instances_reconcile_systemd.sh"', linux)
        self.assertNotIn('instances_reconcile.sh"', linux)
        self.assertIn("export INSTANCES_COORDINATOR_ENABLED='true'", linux)
        self.assertIn("export INSTANCES_COORDINATOR_REPO='/home/test/git/coordinator'", linux)
        mac = render(WRAPPER, data, home="/Users/test", chezmoi_os="darwin")
        self.assertIn('SCRIPT="$HOME/.local/user_scripts/instances_reconcile.sh"', mac)
        self.assertNotIn("systemd", mac)
        self.assertIn("export INSTANCES_COORDINATOR_REPO='/Volumes/Workshop/macbook/git/coordinator'", mac)

    def test_the_macos_wrapper_render_has_no_trace_of_linux(self):
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile):
                text = render(WRAPPER, {"profile": profile}, home="/Users/test", chezmoi_os="darwin")
                self.assertTrue(text.startswith("#!/bin/sh\n# Runs on every apply"))
                self.assertIn('SCRIPT="$HOME/.local/user_scripts/instances_reconcile.sh"\nif [ ! -x "$SCRIPT" ]; then\n', text)


STUB_SYSTEMCTL = r'''#!/bin/sh
# Stub systemctl --user. State: $STUB_DIR/active (exists = the unit runs). Every call is recorded, one line, after "--user".
[ "$1" = --user ] || { echo "stub: expected --user" >&2; exit 2; }
shift
echo "$*" >> "$STUB_DIR/calls"
verb=$1
[ ! -e "$STUB_DIR/FAIL_$(echo "$verb" | tr a-z A-Z | tr - _)" ] || { echo "Failed to $verb: boom" >&2; exit 1; }
case $verb in
  show-environment) [ ! -e "$STUB_DIR/NO_MANAGER" ] || { echo "Failed to connect to bus: No medium found" >&2; exit 1; } ;;
  is-active) [ -e "$STUB_DIR/active" ] ;;
  daemon-reload) ;;
  enable) touch "$STUB_DIR/active" ;;            # enable --now
  disable) rm -f "$STUB_DIR/active" ;;           # disable --now
  restart) touch "$STUB_DIR/active" ;;
  *) echo "stub: unexpected $verb" >&2; exit 2 ;;
esac
'''


def write_exec(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class Scratch:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.stub = self.base / "stub"
        self.stub.mkdir()
        (self.stub / "calls").write_text("")
        self.bin = self.base / "bin"
        write_exec(self.bin / "systemctl", STUB_SYSTEMCTL)
        self.tools = self.base / "tools"
        for tool in ("node", "herdr", "op", "git"):
            write_exec(self.tools / tool, "#!/bin/sh\nexit 0\n")
        self.co = self.base / "co"
        write_exec(self.co / "src" / "coordinatord" / "main.ts", "")
        self.units = self.base / "units"
        self.units.mkdir()
        self.set_unit("v1")
        self.systemd = self.home / ".config" / "systemd" / "user"
        self.state_root = self.home / ".local" / "state" / "instances"
        self.state = self.home / ".local" / "share" / "coordinator"
        self.last = None

    def cleanup(self):
        self.tmp.cleanup()

    def set_unit(self, version):
        (self.units / "coordinatord.service").write_text("[Service]\nExecStart=/bin/true\n# %s\n" % version)

    def have_config(self):
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "config.json").write_text("{}\n")

    def running(self, on=True):
        flag = self.stub / "active"
        if on:
            flag.write_text("")
        elif flag.exists():
            flag.unlink()

    def is_running(self):
        return (self.stub / "active").exists()

    def flag(self, name, on=True):
        path = self.stub / name
        if on:
            path.write_text("")
        elif path.exists():
            path.unlink()

    def calls(self):
        return [line for line in (self.stub / "calls").read_text().splitlines() if line]

    def reset_calls(self):
        (self.stub / "calls").write_text("")

    def run(self, enabled=None, reload=None, **extra):
        env = dict(os.environ)
        env.update(
            HOME=str(self.home), PATH=str(self.bin) + os.pathsep + os.environ["PATH"], STUB_DIR=str(self.stub),
            INSTANCES_UNIT_DIR=str(self.units), INSTANCES_TOOL_PATH=str(self.tools), TMPDIR=str(self.base),
            INSTANCES_COORDINATOR_ENABLED="" if enabled is None else str(enabled).lower(), INSTANCES_COORDINATOR_REPO=str(self.co),
        )
        env.pop("INSTANCES_RELOAD", None)
        if reload:
            env["INSTANCES_RELOAD"] = reload
        env.update({k: str(v) for k, v in extra.items()})
        self.last = subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True, timeout=120, env=env, cwd=str(self.base))
        return self.last

    def output(self):
        return self.last.stdout + self.last.stderr

    def status(self):
        path = self.state_root / "coordinator.status"
        return path.read_text().strip() if path.exists() else None


SHOW, ACTIVE = "show-environment", "is-active --quiet coordinatord.service"
RELOAD_DAEMON, START = "daemon-reload", "enable --now coordinatord.service"
RESTART, STOP = "restart coordinatord.service", "disable --now coordinatord.service"


@unittest.skipUnless(HAVE_TIMEOUT, "needs coreutils timeout (Linux)")
class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.s = Scratch()
        self.addCleanup(self.s.cleanup)

    def assertCalls(self, expected):
        self.assertEqual(self.s.calls(), expected, self.s.output())

    def ok(self):
        self.assertEqual(self.s.last.returncode, 0, self.s.output())

    @property
    def dst(self):
        return self.s.systemd / "coordinatord.service"

    # --- a machine that never opted in ---
    def test_never_opted_in_makes_no_call_even_with_the_live_service_running(self):
        self.s.running()
        self.s.have_config()
        self.s.run()
        self.ok()
        self.assertCalls([])
        self.assertFalse(self.dst.exists())
        self.assertTrue(self.s.is_running())
        self.assertIn("not opted in", self.s.output())

    def test_opt_in_adopts_a_running_service_and_does_not_restart_it(self):
        self.s.running()
        self.s.have_config()
        self.s.systemd.mkdir(parents=True)
        self.dst.write_text("[Service]\nExecStart=/helper/written\n")   # what the hand-made setup left
        self.s.run(enabled=True)
        self.ok()
        self.assertCalls([SHOW, ACTIVE, RELOAD_DAEMON])   # the file is replaced and systemd told; nothing restarted
        self.assertTrue(self.s.is_running())
        self.assertEqual(self.dst.read_text(), (self.s.units / "coordinatord.service").read_text())
        self.assertIn("the unit file changed and the daemon was NOT restarted", self.s.output())
        self.assertIn("INSTANCES_RELOAD=coordinator", self.s.output())
        self.assertTrue((self.s.state_root / "coordinator.managed").exists())

    def test_opt_in_adopts_a_running_service_whose_unit_is_already_ours(self):
        self.s.running()
        self.s.have_config()
        self.s.systemd.mkdir(parents=True)
        shutil.copy(self.s.units / "coordinatord.service", self.dst)
        self.s.run(enabled=True)
        self.ok()
        self.assertCalls([SHOW, ACTIVE])
        self.assertIn("READY (adopted: running, not touched)", self.s.output())

    def test_first_opt_in_installs_the_unit_and_starts_it_once(self):
        self.s.have_config()
        self.s.run(enabled=True)
        self.ok()
        self.assertCalls([SHOW, ACTIVE, RELOAD_DAEMON, START, SHOW, ACTIVE])
        self.assertEqual(self.dst.read_text(), (self.s.units / "coordinatord.service").read_text())
        self.assertEqual(oct(self.dst.stat().st_mode & 0o777), "0o644")
        self.assertTrue(self.s.is_running())
        self.assertEqual(self.s.status(), "READY (started)")

    def test_reapply_makes_read_only_calls_only(self):
        self.s.have_config()
        self.s.run(enabled=True)
        self.s.reset_calls()
        self.s.run(enabled=True)
        self.ok()
        self.assertCalls([SHOW, ACTIVE])
        self.assertEqual(self.s.status(), "READY (running)")

    def test_a_daemon_that_is_not_running_is_started_again_by_the_next_apply(self):
        self.s.have_config()
        self.s.run(enabled=True)
        self.s.running(False)
        self.s.reset_calls()
        self.s.run(enabled=True)
        self.ok()
        self.assertCalls([SHOW, ACTIVE, START, SHOW, ACTIVE])
        self.assertTrue(self.s.is_running())

    def test_a_changed_unit_on_a_running_service_is_reported_never_restarted(self):
        self.s.have_config()
        self.s.run(enabled=True)
        self.s.set_unit("v2")
        self.s.reset_calls()
        self.s.run(enabled=True)
        self.ok()
        self.assertCalls([SHOW, ACTIVE, RELOAD_DAEMON])
        self.assertNotIn(RESTART, self.s.calls())
        self.assertIn("the unit file changed and the daemon was NOT restarted", self.s.output())
        self.assertIn("# v2", self.dst.read_text())

    def test_reload_restarts_a_changed_unit_once_and_only_when_it_changed(self):
        self.s.have_config()
        self.s.run(enabled=True)
        self.s.reset_calls()
        self.s.run(enabled=True, reload="coordinator")             # nothing changed: no restart
        self.assertCalls([SHOW, ACTIVE])
        self.s.set_unit("v2")
        self.s.reset_calls()
        self.s.run(enabled=True, reload="coordinator")
        self.ok()
        self.assertCalls([SHOW, ACTIVE, RELOAD_DAEMON, RESTART, SHOW, ACTIVE])
        self.assertEqual(self.s.status(), "READY (reloaded with the changed unit)")
        self.s.reset_calls()
        self.s.run(enabled=True, reload="all")                      # recorded now: a second reload does nothing
        self.assertCalls([SHOW, ACTIVE])

    def test_reload_for_another_name_does_not_restart(self):
        self.s.have_config()
        self.s.run(enabled=True)
        self.s.set_unit("v2")
        self.s.reset_calls()
        self.s.run(enabled=True, reload="retro")
        self.assertNotIn(RESTART, self.s.calls())

    def test_a_failed_restart_says_so_and_the_next_apply_reports_the_unit_again(self):
        self.s.have_config()
        self.s.run(enabled=True)
        self.s.set_unit("v2")
        self.s.flag("FAIL_RESTART")
        self.s.run(enabled=True, reload="coordinator")
        self.ok()
        self.assertIn("RELOAD FAILED: systemctl restart", self.s.output())

    # --- opt out ---
    def test_opt_out_stops_it_once_keeps_state_and_removes_the_unit(self):
        self.s.have_config()
        self.s.run(enabled=True)
        (self.s.state / "token").write_text("secret-stays")
        self.s.reset_calls()
        self.s.run(enabled=False)
        self.ok()
        self.assertCalls([SHOW, ACTIVE, STOP, RELOAD_DAEMON])
        self.assertFalse(self.dst.exists())
        self.assertFalse(self.s.is_running())
        self.assertTrue((self.s.state / "config.json").exists() and (self.s.state / "token").exists())
        self.assertFalse((self.s.state_root / "coordinator.managed").exists())
        self.s.reset_calls()
        self.s.run(enabled=False)                                   # and again: not opted in, no call
        self.assertCalls([])

    def test_opt_out_of_an_adopted_service_stops_it(self):
        self.s.running()
        self.s.have_config()
        self.s.run(enabled=True)
        self.s.reset_calls()
        self.s.run()                                                # the flag removed
        self.assertCalls([SHOW, ACTIVE, STOP, RELOAD_DAEMON])
        self.assertFalse(self.s.is_running())

    def test_opt_out_that_cannot_stop_keeps_the_unit_and_markers_and_retries(self):
        self.s.have_config()
        self.s.run(enabled=True)
        self.s.flag("FAIL_DISABLE")
        self.s.run(enabled=False)
        self.ok()
        self.assertIn("STOP FAILED", self.s.output())
        self.assertTrue(self.dst.exists() and (self.s.state_root / "coordinator.managed").exists())
        self.s.flag("FAIL_DISABLE", False)
        self.s.run(enabled=False)
        self.assertFalse(self.dst.exists())

    # --- not ready ---
    def test_no_user_manager_is_not_ready_and_installs_nothing(self):
        self.s.have_config()
        self.s.flag("NO_MANAGER")
        self.s.run(enabled=True)
        self.ok()
        self.assertCalls([SHOW])
        self.assertIn("NOT READY: no systemd user manager", self.s.output())
        self.assertFalse(self.dst.exists())

    def test_missing_checkout_names_the_path_and_installs_nothing(self):
        self.s.have_config()
        self.s.run(enabled=True, INSTANCES_COORDINATOR_REPO=self.s.base / "nowhere")
        self.ok()
        self.assertIn("NOT READY: missing checkout(", self.s.output())
        self.assertCalls([])

    def test_missing_repo_value_names_the_data_key(self):
        self.s.run(enabled=True, INSTANCES_COORDINATOR_REPO="")
        self.assertIn("instances.coordinator.repo", self.s.output())
        self.assertCalls([])

    def test_a_tool_missing_from_the_daemons_path_is_not_ready(self):
        self.s.have_config()
        (self.s.tools / "herdr").unlink()
        self.s.run(enabled=True)
        self.assertIn("herdr-on-PATH", self.s.output())
        self.assertCalls([])

    def test_a_flag_that_is_not_true_or_false_does_nothing(self):
        self.s.run(enabled="maybe")
        self.ok()
        self.assertIn("must be true or false", self.s.output())
        self.assertCalls([])

    def test_failed_start_is_not_ready_and_the_next_apply_starts_it(self):
        self.s.have_config()
        self.s.flag("FAIL_ENABLE")
        self.s.run(enabled=True)
        self.ok()
        self.assertIn("NOT READY: systemctl enable --now failed", self.s.output())
        self.s.flag("FAIL_ENABLE", False)
        self.s.run(enabled=True)
        self.assertEqual(self.s.status(), "READY (started)")

    # --- the config half ---
    def test_no_config_and_no_setup_script_is_not_ready(self):
        self.s.run(enabled=True)
        self.assertIn("NOT READY: no config in", self.s.output())
        self.assertCalls([])

    def test_setup_script_runs_once_with_the_state_dir_and_the_daemons_path(self):
        script = self.s.co / "scripts" / "instance-setup.sh"
        write_exec(script, '#!/bin/sh\nmkdir -p "$COORDINATOR_STATE_DIR"; echo "{}" > "$COORDINATOR_STATE_DIR/config.json"\n'
                           'echo "$PATH" > "$COORDINATOR_STATE_DIR/seen-path"\necho "$COORDINATOR_STATE_DIR" >> "$COORDINATOR_STATE_DIR/runs"\n')
        self.s.run(enabled=True)
        self.s.run(enabled=True)
        self.ok()
        self.assertEqual((self.s.state / "runs").read_text().splitlines(), [str(self.s.state)])
        self.assertTrue((self.s.state / "seen-path").read_text().startswith(str(self.s.tools)))
        self.assertEqual(self.s.status(), "READY (running)")

    def test_setup_script_exit_3_is_not_ready_with_its_reason_and_the_next_apply_retries(self):
        script = self.s.co / "scripts" / "instance-setup.sh"
        write_exec(script, '#!/bin/sh\necho "NOT-READY: no Discord token yet"\nexit 3\n')
        self.s.run(enabled=True)
        self.assertIn("NOT READY: no Discord token yet", self.s.output())
        self.assertTrue((self.s.state_root / "coordinator.configuring").exists())
        self.assertCalls([])

    def test_nothing_the_script_prints_or_stores_contains_the_op_reference(self):
        self.s.have_config()
        self.s.run(enabled=True)
        stored = "".join(p.read_text() for p in self.s.state_root.iterdir())
        self.assertNotIn("op://", stored + self.s.output())


if __name__ == "__main__":
    unittest.main()
