"""Instances: LaunchAgent units, the opt-in flag, and the reconcile script that starts and stops them.

Three layers, none of which touches the real home, the real chezmoi state, launchd or Herdr:

  RenderTests    the unit templates render byte-identical to the deployed units (golden files); local data changes only the checkout path.
  MatrixTests    the reconcile script run directly in a scratch HOME with a stub launchctl that keeps loaded/not-loaded state and records every
                 call. Each case asserts the EXACT list of launchctl calls (the safety rules: no restart because a unit changed, opt-out acts
                 only on what dotfiles started or adopted, a Mac that never opted in sees no call).
  ApplyTests     (macOS) chezmoi apply into a scratch HOME with the same stub: the flags in chezmoi.yaml reach the script.

    python3 -m unittest discover -s tests/instances -v
    python3 tests/instances/mutate.py        # each mutation of the reconcile script must make this suite fail

INSTANCES_SCRIPT_UNDER_TEST points the suite at a mutated copy of the script (mutate.py uses it).
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
UNIT_DIR = ROOT / "dot_local" / "share" / "instances" / "launchd"
COORD_UNIT = UNIT_DIR / "local.coordinatord.plist.tmpl"
RETRO_UNIT = UNIT_DIR / "local.retrod.plist.tmpl"
WRAPPER = ROOT / "run_after_75_instances_reconcile.sh.tmpl"
IGNORE = ROOT / ".chezmoiignore"
SCRIPT = Path(os.environ.get("INSTANCES_SCRIPT_UNDER_TEST") or ROOT / "dot_local" / "user_scripts" / "executable_instances_reconcile.sh")
GOLDEN_COORD = HERE / "golden" / "local.coordinatord.plist"
GOLDEN_RETRO = HERE / "golden" / "local.retrod.plist"
COORD_PATH = "/Volumes/Workshop/macbook/git/coordinator"
RETRO_PATH = "/Volumes/Workshop/macbook/git/retro"
HAVE_CHEZMOI = shutil.which("chezmoi") is not None
DOMAIN = "gui/%d" % os.getuid()


def render(template, data, home="/Users/test"):
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "chezmoi.yaml"
        config.write_text("{}\n")  # no hooks from the developer's own config
        env = dict(os.environ, HOME=home)
        result = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(config), "execute-template", "--override-data", json.dumps(data)],
            input=template.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120, env=env,
        )
    assert result.returncode == 0, result.stderr
    return result.stdout


@unittest.skipUnless(HAVE_CHEZMOI, "chezmoi not installed")
class RenderTests(unittest.TestCase):
    def test_default_coordinator_render_is_byte_identical_to_the_deployed_unit(self):
        self.assertEqual(render(COORD_UNIT, {"profile": "personal"}), GOLDEN_COORD.read_text(encoding="utf-8"))

    def test_default_retro_render_is_byte_identical_to_the_golden_unit(self):
        self.assertEqual(render(RETRO_UNIT, {"profile": "personal"}), GOLDEN_RETRO.read_text(encoding="utf-8"))

    def test_empty_repo_value_falls_back_to_the_default_path(self):
        data = {"profile": "personal", "instances": {"coordinator": {"repo": ""}, "retro": {"repo": ""}}}
        self.assertEqual(render(COORD_UNIT, data), GOLDEN_COORD.read_text(encoding="utf-8"))
        self.assertEqual(render(RETRO_UNIT, data), GOLDEN_RETRO.read_text(encoding="utf-8"))

    def test_local_data_changes_only_the_checkout_path(self):
        data = {"profile": "personal", "instances": {"coordinator": {"repo": "/srv/co"}, "retro": {"repo": "/srv/re"}}}
        self.assertEqual(render(COORD_UNIT, data), GOLDEN_COORD.read_text(encoding="utf-8").replace(COORD_PATH, "/srv/co"))
        self.assertEqual(render(RETRO_UNIT, data), GOLDEN_RETRO.read_text(encoding="utf-8").replace(RETRO_PATH, "/srv/re"))
        self.assertIn("<key>WorkingDirectory</key><string>/srv/co</string>", render(COORD_UNIT, data))

    def test_work_profile_default_checkouts_are_under_home_git(self):
        data = {"profile": "axon-work-computer"}
        self.assertIn("<string>/Users/test/git/retro/src/retrod/main.ts</string>", render(RETRO_UNIT, data))
        self.assertIn("<string>/Users/test/git/coordinator/src/coordinatord/main.ts</string>", render(COORD_UNIT, data))

    def test_wrapper_hands_the_flags_and_the_same_default_repo_to_the_script(self):
        text = render(WRAPPER, {"profile": "personal", "instances": {"retro": {"enabled": True, "channelId": "123", "opItem": "op://V/I/bot_token"}}})
        self.assertIn("export INSTANCES_RETRO_ENABLED='true'", text)
        self.assertIn("export INSTANCES_COORDINATOR_ENABLED=''", text)
        self.assertIn("export INSTANCES_COORDINATOR_REPO='%s'" % COORD_PATH, text)
        self.assertIn("export INSTANCES_RETRO_REPO='%s'" % RETRO_PATH, text)
        self.assertIn("export INSTANCES_RETRO_CHANNEL_ID='123'", text)
        self.assertNotIn("launchctl", text)


def write_exec(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


# A launchctl that keeps state (which labels are loaded) and records every call. Exit 113 for print of a service that is not loaded,
# as the real one does. FAIL_<VERB> files make that verb fail.
STUB_LAUNCHCTL = """#!/bin/sh
D="$STUB_DIR"
echo "$@" >> "$D/calls"
verb=$1
case $verb in
  print) label=${2##*/}; if grep -qx "$label" "$D/loaded" 2>/dev/null; then exit 0; else echo "Could not find service" >&2; exit 113; fi;;
  bootstrap) [ -e "$D/FAIL_BOOTSTRAP" ] && { echo "Bootstrap failed: 5: Input/output error" >&2; exit 5; }
             f=$3; label=$(basename "$f" .plist); echo "$label" >> "$D/loaded"; exit 0;;
  bootout) [ -e "$D/FAIL_BOOTOUT" ] && { echo "Boot-out failed: 5" >&2; exit 5; }
           label=${2##*/}; grep -vx "$label" "$D/loaded" > "$D/loaded.new" 2>/dev/null; mv "$D/loaded.new" "$D/loaded"; exit 0;;
  *) echo "stub launchctl: unexpected verb $verb" >&2; exit 64;;
esac
"""


class Scratch:
    """A scratch HOME, stub launchctl and tools, fake checkouts and a unit directory."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.stub = self.base / "stub"
        self.stub.mkdir()
        (self.stub / "loaded").write_text("")
        (self.stub / "calls").write_text("")
        self.bin = self.base / "bin"
        write_exec(self.bin / "launchctl", STUB_LAUNCHCTL)
        self.tools = self.base / "tools"
        for tool in ("node", "herdr", "op", "git"):
            write_exec(self.tools / tool, "#!/bin/sh\nexit 0\n")
        self.co = self.base / "co"
        write_exec(self.co / "src" / "coordinatord" / "main.ts", "")
        self.re = self.base / "re"
        write_exec(self.re / "src" / "retrod" / "main.ts", "")
        self.units = self.base / "units"
        self.units.mkdir()
        self.set_unit("local.coordinatord", "coordinator-v1")
        self.set_unit("local.retrod", "retro-v1")
        self.agents = self.home / "Library" / "LaunchAgents"
        self.state_root = self.home / ".local" / "state" / "instances"
        self.coordinator_state = self.home / ".local" / "share" / "coordinator"
        self.retro_state = self.home / ".local" / "share" / "retro"
        self.last = None

    def cleanup(self):
        self.tmp.cleanup()

    def set_unit(self, label, version):
        (self.units / (label + ".plist")).write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict><key>Label</key><string>%s</string>'
            "<key>Version</key><string>%s</string></dict></plist>\n" % (label, version))

    def unit_text(self, label):
        return (self.units / (label + ".plist")).read_text()

    def have_config(self, state):
        state.mkdir(parents=True, exist_ok=True)
        (state / "config.json").write_text("{}\n")

    def load(self, label):
        """Pretend launchd already runs this label."""
        with open(self.stub / "loaded", "a") as f:
            f.write(label + "\n")

    def loaded(self):
        return [line for line in (self.stub / "loaded").read_text().splitlines() if line]

    def fail(self, verb, on=True):
        flag = self.stub / ("FAIL_" + verb.upper())
        if on:
            flag.write_text("")
        elif flag.exists():
            flag.unlink()

    def calls(self):
        return [line for line in (self.stub / "calls").read_text().splitlines() if line]

    def reset_calls(self):
        (self.stub / "calls").write_text("")

    def run(self, coordinator=None, retro=None, reload=None, **extra):
        env = dict(os.environ)
        env.update(
            HOME=str(self.home), PATH=str(self.bin) + os.pathsep + os.environ["PATH"], STUB_DIR=str(self.stub),
            INSTANCES_UNIT_DIR=str(self.units), INSTANCES_TOOL_PATH=str(self.tools), TMPDIR=str(self.base),
            INSTANCES_COORDINATOR_ENABLED="" if coordinator is None else str(coordinator).lower(), INSTANCES_COORDINATOR_REPO=str(self.co),
            INSTANCES_RETRO_ENABLED="" if retro is None else str(retro).lower(), INSTANCES_RETRO_REPO=str(self.re),
            INSTANCES_RETRO_CHANNEL_ID="", INSTANCES_RETRO_OP_ITEM="",
        )
        env.pop("INSTANCES_RELOAD", None)
        if reload:
            env["INSTANCES_RELOAD"] = reload
        env.update({k: str(v) for k, v in extra.items()})
        self.last = subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True, timeout=120, env=env, cwd=str(self.base))
        return self.last

    def output(self):
        return self.last.stdout + self.last.stderr

    def status(self, name):
        path = self.state_root / (name + ".status")
        return path.read_text().strip() if path.exists() else None


PRINT_CO = "print %s/local.coordinatord" % DOMAIN
PRINT_RE = "print %s/local.retrod" % DOMAIN


class MatrixTests(unittest.TestCase):
    def setUp(self):
        self.s = Scratch()
        self.addCleanup(self.s.cleanup)

    def assertCalls(self, expected):
        self.assertEqual(self.s.calls(), expected, self.s.output())

    def ok(self):
        self.assertEqual(self.s.last.returncode, 0, self.s.output())

    def dst(self, label="local.coordinatord"):
        return self.s.agents / (label + ".plist")

    def bootstrap(self, label="local.coordinatord"):
        return "bootstrap %s %s" % (DOMAIN, self.dst(label))

    # --- a Mac that never opted in -------------------------------------------------------------------------------------------------

    def test_never_opted_in_makes_no_call_even_with_the_live_service_loaded(self):
        self.s.load("local.coordinatord")
        self.s.have_config(self.s.coordinator_state)
        self.s.run()
        self.ok()
        self.assertCalls([])
        self.assertEqual(self.s.loaded(), ["local.coordinatord"])
        self.assertFalse(self.s.agents.exists())
        self.assertFalse(self.s.state_root.exists())
        self.assertIn("coordinator: not opted in", self.s.output())

    # --- adopting a service that is already running (this Mac's live coordinator) -----------------------------------------------------

    def test_opt_in_adopts_a_running_service_with_one_read_only_call(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.load("local.coordinatord")
        self.s.agents.mkdir(parents=True)
        self.dst().write_text(self.s.unit_text("local.coordinatord"))  # the unit it was loaded from, byte-identical
        before = self.dst().read_bytes()
        self.s.run(coordinator=True)
        self.ok()
        self.assertCalls([PRINT_CO])
        self.assertEqual(self.dst().read_bytes(), before)
        self.assertEqual(self.s.loaded(), ["local.coordinatord"])
        self.assertIn("READY (adopted", self.s.status("coordinator"))
        self.assertTrue((self.s.state_root / "coordinator.managed").exists())

    def test_opt_in_with_a_running_service_and_a_different_unit_reports_and_does_not_restart(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.load("local.coordinatord")
        self.s.agents.mkdir(parents=True)
        self.dst().write_text("<plist>older unit the daemon was loaded from</plist>\n")
        self.s.run(coordinator=True)
        self.ok()
        self.assertCalls([PRINT_CO])
        self.assertIn("NOT restarted", self.s.status("coordinator"))
        self.assertIn("INSTANCES_RELOAD=coordinator", self.s.status("coordinator"))

    # --- first opt-in, re-apply ---------------------------------------------------------------------------------------------------

    def test_first_opt_in_starts_once(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.run(coordinator=True)
        self.ok()
        self.assertCalls([PRINT_CO, self.bootstrap(), PRINT_CO])
        self.assertEqual(self.dst().read_text(), self.s.unit_text("local.coordinatord"))
        self.assertEqual(self.s.loaded(), ["local.coordinatord"])
        self.assertEqual(self.s.status("coordinator"), "READY (started)")
        self.assertTrue((self.s.home / "Library" / "Logs" / "coordinator").is_dir())

    def test_reapply_makes_one_read_only_call_and_nothing_else(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.run(coordinator=True)
        self.s.reset_calls()
        self.s.run(coordinator=True)
        self.ok()
        self.assertCalls([PRINT_CO])
        self.assertEqual(self.s.status("coordinator"), "READY (running)")

    def test_daemon_that_is_not_loaded_is_started_again_by_the_next_apply(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.run(coordinator=True)
        (self.s.stub / "loaded").write_text("")  # e.g. a bootout by hand
        self.s.reset_calls()
        self.s.run(coordinator=True)
        self.assertCalls([PRINT_CO, self.bootstrap(), PRINT_CO])

    # --- a changed unit on a running service -------------------------------------------------------------------------------------

    def test_changed_unit_on_a_running_service_is_reported_never_restarted(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.run(coordinator=True)
        self.s.set_unit("local.coordinatord", "coordinator-v2")
        self.s.reset_calls()
        self.s.run(coordinator=True)
        self.ok()
        self.assertCalls([PRINT_CO])
        self.assertEqual(self.s.loaded(), ["local.coordinatord"])
        self.assertIn("NOT restarted", self.s.status("coordinator"))
        self.assertEqual(self.dst().read_text(), self.s.unit_text("local.coordinatord"))  # the file is current; the daemon is not reloaded
        self.s.reset_calls()
        self.s.run(coordinator=True)
        self.assertCalls([PRINT_CO])  # still just reported, every apply, until a reload is asked for
        self.assertIn("NOT restarted", self.s.status("coordinator"))

    def test_reload_switch_boots_out_then_in_and_only_when_the_unit_changed(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.run(coordinator=True)
        self.s.reset_calls()
        self.s.run(coordinator=True, reload="coordinator")  # unit unchanged: nothing to reload
        self.assertCalls([PRINT_CO])
        self.s.set_unit("local.coordinatord", "coordinator-v2")
        self.s.reset_calls()
        self.s.run(coordinator=True, reload="coordinator")
        self.ok()
        self.assertCalls([PRINT_CO, "bootout %s/local.coordinatord" % DOMAIN, self.bootstrap(), PRINT_CO])
        self.assertEqual(self.s.status("coordinator"), "READY (reloaded with the changed unit)")
        self.s.reset_calls()
        self.s.run(coordinator=True)
        self.assertCalls([PRINT_CO])  # settled: no longer reported
        self.assertEqual(self.s.status("coordinator"), "READY (running)")

    def test_reload_for_another_instance_does_not_reload_this_one(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.run(coordinator=True)
        self.s.set_unit("local.coordinatord", "coordinator-v2")
        self.s.reset_calls()
        self.s.run(coordinator=True, reload="retro")
        self.assertCalls([PRINT_CO])

    def test_reload_all_reloads_a_changed_instance(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.run(coordinator=True)
        self.s.set_unit("local.coordinatord", "coordinator-v2")
        self.s.reset_calls()
        self.s.run(coordinator=True, reload="all")
        self.assertIn("bootout %s/local.coordinatord" % DOMAIN, self.s.calls())

    def test_failed_reload_says_so_and_the_next_apply_starts_it(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.run(coordinator=True)
        self.s.set_unit("local.coordinatord", "coordinator-v2")
        self.s.fail("bootstrap")
        self.s.run(coordinator=True, reload="coordinator")
        self.ok()
        self.assertIn("RELOAD FAILED", self.s.status("coordinator"))
        self.s.fail("bootstrap", False)
        self.s.reset_calls()
        self.s.run(coordinator=True)
        self.assertCalls([PRINT_CO, self.bootstrap(), PRINT_CO])

    # --- opt out -----------------------------------------------------------------------------------------------------------------

    def started(self):
        self.s.have_config(self.s.coordinator_state)
        (self.s.coordinator_state / "keep.txt").write_text("state")
        self.s.run(coordinator=True)
        self.s.reset_calls()

    def check_opted_out(self, **kw):
        self.s.run(**kw)
        self.ok()
        self.assertCalls([PRINT_CO, "bootout %s/local.coordinatord" % DOMAIN])
        self.assertEqual(self.s.loaded(), [])
        self.assertFalse(self.dst().exists())
        self.assertEqual([p.name for p in self.s.state_root.iterdir()], [])
        self.assertTrue((self.s.coordinator_state / "config.json").exists())
        self.assertTrue((self.s.coordinator_state / "keep.txt").exists())
        self.assertTrue((self.s.home / "Library" / "Logs" / "coordinator").is_dir())
        self.assertIn("Pi pane keeps running", self.s.output())
        self.s.reset_calls()
        self.s.run(**kw)
        self.assertCalls([])  # nothing managed any more: nothing to do

    def test_opt_out_with_the_flag_false_stops_it_once_and_keeps_state(self):
        self.started()
        self.check_opted_out(coordinator=False)

    def test_opt_out_with_the_flag_removed_stops_it_too(self):
        self.started()
        self.check_opted_out()

    def test_opt_out_of_an_adopted_service_stops_it(self):
        self.s.have_config(self.s.coordinator_state)
        (self.s.coordinator_state / "keep.txt").write_text("state")
        self.s.load("local.coordinatord")
        self.s.agents.mkdir(parents=True)
        self.dst().write_text(self.s.unit_text("local.coordinatord"))
        self.s.run(coordinator=True)
        self.s.reset_calls()
        self.check_opted_out()

    def test_instance_that_never_started_is_not_ours_to_stop(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.fail("bootstrap")
        self.s.run(coordinator=True)
        self.assertFalse((self.s.state_root / "coordinator.managed").exists())
        self.s.reset_calls()
        self.s.run()
        self.assertCalls([])

    def test_opt_out_that_cannot_boot_out_keeps_the_unit_and_retries(self):
        self.started()
        self.s.fail("bootout")
        self.s.run()
        self.ok()
        self.assertIn("STOP FAILED", self.s.status("coordinator"))
        self.assertTrue(self.dst().exists())
        self.assertTrue((self.s.state_root / "coordinator.managed").exists())
        self.assertEqual(self.s.loaded(), ["local.coordinatord"])
        self.s.fail("bootout", False)
        self.s.reset_calls()
        self.s.run()
        self.assertCalls([PRINT_CO, "bootout %s/local.coordinatord" % DOMAIN])
        self.assertEqual(self.s.loaded(), [])

    def test_opt_out_of_an_instance_that_is_no_longer_loaded_just_cleans_up(self):
        self.started()
        (self.s.stub / "loaded").write_text("")
        self.s.run()
        self.assertCalls([PRINT_CO])
        self.assertFalse(self.dst().exists())

    # --- not ready ---------------------------------------------------------------------------------------------------------------

    def assertNotReady(self, name, *words):
        self.ok()
        status = self.s.status(name)
        self.assertTrue(status.startswith("NOT READY"), status)
        for word in words:
            self.assertIn(word, status)
        self.assertCalls([])
        self.assertFalse(self.dst("local.coordinatord" if name == "coordinator" else "local.retrod").exists())
        self.assertFalse((self.s.state_root / (name + ".managed")).exists())

    def test_missing_checkout_is_not_ready_and_installs_nothing(self):
        self.s.have_config(self.s.coordinator_state)
        shutil.rmtree(self.s.co)
        self.s.run(coordinator=True)
        self.assertNotReady("coordinator", "checkout")

    def test_missing_checkout_path_is_named_as_missing_local_data(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.run(coordinator=True, INSTANCES_COORDINATOR_REPO="")
        self.assertNotReady("coordinator", "instances.coordinator.repo")

    def test_missing_tool_on_the_daemons_path_is_not_ready(self):
        self.s.have_config(self.s.coordinator_state)
        (self.s.tools / "op").unlink()
        self.s.run(coordinator=True)
        self.assertNotReady("coordinator", "op-on-PATH")

    def test_missing_unit_file_is_not_ready(self):
        self.s.have_config(self.s.coordinator_state)
        (self.s.units / "local.coordinatord.plist").unlink()
        self.s.run(coordinator=True)
        self.assertNotReady("coordinator", "unit(")

    def test_no_config_and_no_setup_script_is_not_ready(self):
        self.s.run(coordinator=True)
        self.assertNotReady("coordinator", "no config", "instance-setup.sh")

    def setup_script(self, repo, name, body):
        write_exec(repo / "scripts" / name, body)

    def test_setup_script_exit_3_is_not_ready_with_its_reason_and_the_next_apply_retries(self):
        self.setup_script(self.s.co, "instance-setup.sh", "#!/bin/sh\necho 'NOT-READY: owner has not joined the room'\nexit 3\n")
        self.s.run(coordinator=True)
        self.assertNotReady("coordinator", "owner has not joined the room")
        self.setup_script(self.s.co, "instance-setup.sh", '#!/bin/sh\nmkdir -p "$COORDINATOR_STATE_DIR"\necho "{}" > "$COORDINATOR_STATE_DIR/config.json"\nexit 0\n')
        self.s.run(coordinator=True)
        self.assertCalls([PRINT_CO, self.bootstrap(), PRINT_CO])
        self.assertEqual(self.s.status("coordinator"), "READY (started)")

    def test_setup_script_failure_is_not_ready(self):
        self.setup_script(self.s.co, "instance-setup.sh", "#!/bin/sh\necho 'boom'\nexit 1\n")
        self.s.run(coordinator=True)
        self.assertNotReady("coordinator", "exit 1", "boom")

    def test_setup_script_that_claims_success_without_a_config_is_not_ready(self):
        self.setup_script(self.s.co, "instance-setup.sh", "#!/bin/sh\nexit 0\n")
        self.s.run(coordinator=True)
        self.assertNotReady("coordinator", "config.json")

    def test_setup_script_runs_once_and_not_again_after_the_instance_is_seeded(self):
        marker = self.s.base / "ran"
        self.setup_script(self.s.co, "instance-setup.sh", '#!/bin/sh\necho x >> "%s"\nmkdir -p "$COORDINATOR_STATE_DIR"\necho "{}" > "$COORDINATOR_STATE_DIR/config.json"\n' % marker)
        self.s.run(coordinator=True)
        self.s.run(coordinator=True)
        self.s.run(coordinator=True)
        self.assertEqual(marker.read_text().split(), ["x"])

    def test_bootstrap_failure_is_not_ready_not_managed_and_retried(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.fail("bootstrap")
        self.s.run(coordinator=True)
        self.ok()
        self.assertIn("NOT READY: launchctl bootstrap failed", self.s.status("coordinator"))
        self.assertFalse((self.s.state_root / "coordinator.managed").exists())
        self.s.fail("bootstrap", False)
        self.s.reset_calls()
        self.s.run(coordinator=True)
        self.assertEqual(self.s.status("coordinator"), "READY (started)")

    def test_a_flag_that_is_not_true_or_false_does_nothing(self):
        self.s.have_config(self.s.coordinator_state)
        self.s.run(INSTANCES_COORDINATOR_ENABLED="yes")
        self.ok()
        self.assertCalls([])
        self.assertIn("must be true or false", self.s.output())

    def test_a_failure_in_one_instance_does_not_stop_the_other(self):
        self.s.have_config(self.s.retro_state)
        self.s.run(coordinator=True, retro=True)  # coordinator has no config and no script
        self.assertTrue(self.s.status("coordinator").startswith("NOT READY"))
        self.assertEqual(self.s.status("retro"), "READY (started)")
        self.assertEqual(self.s.loaded(), ["local.retrod"])

    # --- retro -------------------------------------------------------------------------------------------------------------------

    def test_retro_off_by_default_even_with_a_loaded_service(self):
        self.s.load("local.retrod")
        self.s.run()
        self.assertCalls([])

    def test_retro_without_its_local_data_is_not_ready_and_names_the_keys(self):
        self.s.run(retro=True)
        self.assertNotReady("retro", "instances.retro.channelId", "instances.retro.opItem")

    def test_retro_configures_itself_once_from_local_data_then_starts(self):
        self.setup_script(self.s.re, "configure.sh",
                          '#!/bin/sh\n: "${RETRO_CHANNEL_ID:?}" "${RETRO_OP_ITEM:?}"\nmkdir -p "$HOME/.local/share/retro"\n'
                          'printf "%s %s\\n" "$RETRO_CHANNEL_ID" "$RETRO_OP_ITEM" > "$HOME/.local/share/retro/config.json"\n')
        self.s.run(retro=True, INSTANCES_RETRO_CHANNEL_ID="C123", INSTANCES_RETRO_OP_ITEM="op://V/I/bot_token")
        self.ok()
        self.assertCalls([PRINT_RE, self.bootstrap("local.retrod"), PRINT_RE])
        self.assertEqual((self.s.retro_state / "config.json").read_text().strip(), "C123 op://V/I/bot_token")
        self.assertTrue((self.s.home / "Library" / "Logs" / "retro").is_dir())

    def test_retro_that_already_has_a_config_never_runs_configure(self):
        self.s.have_config(self.s.retro_state)
        self.setup_script(self.s.re, "configure.sh", "#!/bin/sh\necho ran >> '%s'\n" % (self.s.base / "ran"))
        self.s.run(retro=True)
        self.assertEqual(self.s.status("retro"), "READY (started)")
        self.assertFalse((self.s.base / "ran").exists())

    def test_nothing_the_script_prints_or_stores_contains_the_op_reference(self):
        self.s.have_config(self.s.retro_state)
        self.s.run(retro=True, INSTANCES_RETRO_OP_ITEM="op://V/I/bot_token")
        everything = self.s.output() + "".join(p.read_text() for p in self.s.state_root.rglob("*") if p.is_file())
        self.assertNotIn("op://V/I/bot_token", everything)


@unittest.skipUnless(HAVE_CHEZMOI and sys.platform == "darwin", "needs chezmoi on macOS (launchd units and the reconcile script are darwin-only)")
class ApplyTests(unittest.TestCase):
    """chezmoi apply into a scratch HOME. Real home, real chezmoi state and real launchd are never involved."""

    def setUp(self):
        self.s = Scratch()
        self.addCleanup(self.s.cleanup)
        self.source = self.s.base / "src"
        (self.source / "dot_local" / "user_scripts").mkdir(parents=True)
        shutil.copytree(UNIT_DIR, self.source / "dot_local" / "share" / "instances" / "launchd")
        shutil.copytree(ROOT / ".chezmoitemplates", self.source / ".chezmoitemplates")
        shutil.copy(SCRIPT, self.source / "dot_local" / "user_scripts" / "executable_instances_reconcile.sh")
        shutil.copy(WRAPPER, self.source / WRAPPER.name)
        shutil.copy(IGNORE, self.source / ".chezmoiignore")

    def apply(self, data, **env_extra):
        config = self.s.base / "chezmoi.yaml"
        config.write_text(json.dumps({"sourceDir": str(self.source), "destDir": str(self.s.home), "cacheDir": str(self.s.base / "cache"),
                                      "persistentState": str(self.s.base / "state.boltdb"), "data": data}))
        env = dict(os.environ, HOME=str(self.s.home), PATH=str(self.s.bin) + os.pathsep + os.environ["PATH"], STUB_DIR=str(self.s.stub),
                   INSTANCES_TOOL_PATH=str(self.s.tools))
        env.pop("INSTANCES_RELOAD", None)
        env.update(env_extra)
        result = subprocess.run(["chezmoi", "--config", str(config), "apply", "--no-tty", "--verbose"], capture_output=True, text=True,
                                timeout=240, env=env, cwd=str(self.s.base))
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout + result.stderr

    def test_first_apply_with_no_flag_installs_inert_units_and_makes_no_launchctl_call(self):
        self.s.load("local.coordinatord")
        out = self.apply({"profile": "personal"})
        self.assertEqual(self.s.calls(), [])
        self.assertEqual(self.s.loaded(), ["local.coordinatord"])
        self.assertTrue((self.s.home / ".local/share/instances/launchd/local.coordinatord.plist").exists())
        self.assertFalse((self.s.home / "Library" / "LaunchAgents").exists())
        self.assertFalse((self.s.home / "Library" / "Logs").exists())
        self.assertIn("coordinator: not opted in", out)

    def test_the_inert_units_are_the_golden_units(self):
        self.apply({"profile": "personal"})
        d = self.s.home / ".local/share/instances/launchd"
        self.assertEqual((d / "local.coordinatord.plist").read_text(), GOLDEN_COORD.read_text().replace("/Users/test", str(self.s.home)))
        self.assertEqual((d / "local.retrod.plist").read_text(), GOLDEN_RETRO.read_text().replace("/Users/test", str(self.s.home)))

    def test_opt_in_in_chezmoi_yaml_starts_the_instance_and_a_second_apply_only_reads(self):
        co = self.s.co
        self.s.have_config(self.s.coordinator_state)
        data = {"profile": "personal", "instances": {"coordinator": {"enabled": True, "repo": str(co)}}}
        out = self.apply(data)
        self.assertEqual(self.s.calls()[:1], [PRINT_CO])
        self.assertEqual(sum(1 for c in self.s.calls() if c.startswith("bootstrap")), 1)
        self.assertEqual(self.s.loaded(), ["local.coordinatord"])
        self.assertIn("coordinator: READY (started)", out)
        started = (self.s.home / "Library/LaunchAgents/local.coordinatord.plist").read_text()
        self.assertIn(str(co) + "/src/coordinatord/main.ts", started)
        self.s.reset_calls()
        self.apply(data)
        self.assertEqual(self.s.calls(), [PRINT_CO])

    def test_removing_the_flag_stops_it_once(self):
        data = {"profile": "personal", "instances": {"coordinator": {"enabled": True, "repo": str(self.s.co)}}}
        self.s.have_config(self.s.coordinator_state)
        self.apply(data)
        self.s.reset_calls()
        out = self.apply({"profile": "personal", "instances": {"coordinator": {"repo": str(self.s.co)}}})
        self.assertEqual(self.s.calls(), [PRINT_CO, "bootout %s/local.coordinatord" % DOMAIN])
        self.assertIn("opted out", out)
        self.assertTrue((self.s.coordinator_state / "config.json").exists())

    def test_work_profile_has_no_coordinator_unit_so_the_flag_ends_not_ready(self):
        self.s.have_config(self.s.coordinator_state)
        out = self.apply({"profile": "axon-work-computer", "instances": {"coordinator": {"enabled": True, "repo": str(self.s.co)}}})
        self.assertEqual(self.s.calls(), [])
        self.assertIn("NOT READY", out)


@unittest.skipUnless(HAVE_CHEZMOI, "chezmoi not installed")
class IgnoreTests(unittest.TestCase):
    def managed(self, data, os_name=None):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"
            source.mkdir()
            shutil.copy(IGNORE, source / ".chezmoiignore")
            shutil.copytree(UNIT_DIR, source / "dot_local" / "share" / "instances" / "launchd")
            (source / "dot_local" / "user_scripts").mkdir(parents=True)
            shutil.copy(SCRIPT, source / "dot_local" / "user_scripts" / "executable_instances_reconcile.sh")
            shutil.copytree(ROOT / ".chezmoitemplates", source / ".chezmoitemplates")
            shutil.copy(WRAPPER, source / WRAPPER.name)
            config = Path(tmp) / "chezmoi.yaml"
            config.write_text(json.dumps({"sourceDir": str(source), "destDir": str(Path(tmp) / "h"), "data": data}))
            result = subprocess.run(["chezmoi", "--config", str(config), "managed", "--include=files"], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_work_profile_manages_no_unit(self):
        out = self.managed({"profile": "axon-work-computer"})
        self.assertNotIn("local.coordinatord.plist", out)
        self.assertNotIn("local.retrod.plist", out)

    @unittest.skipUnless(sys.platform == "darwin", "the units are managed on personal macOS only")
    def test_personal_macos_manages_both_inert_units_and_the_script(self):
        out = self.managed({"profile": "personal"})
        self.assertIn(".local/share/instances/launchd/local.coordinatord.plist", out)
        self.assertIn(".local/share/instances/launchd/local.retrod.plist", out)
        self.assertIn(".local/user_scripts/instances_reconcile.sh", out)

    def test_chezmoi_never_places_a_unit_in_launch_agents(self):
        out = self.managed({"profile": "personal"})
        for line in out.splitlines():
            if "Library/LaunchAgents" in line:
                self.assertIn("agent-events", line)


if __name__ == "__main__":
    unittest.main()
