"""Container mode (the agent host pod): what a personal Linux home keeps when `container.enabled` is true. docs/container-mode.md.

The real chezmoi renders the real source into a throwaway HOME (`apply --exclude=scripts,externals`: files only, no run script, no network). Nothing
touches the real HOME. The checks are the pod's own: the Claude settings the c5 check reads, the exact run scripts that stay (so plain `chezmoi verify`
has no always-pending script), the paths left out, the lean mise set, and the hook entries (which need node at render time).

    python3 -m unittest discover -s tests/container-mode -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEAN = {"node", "python", "gh", "jq", "chezmoi", "loop-engine", "lean-change", "bookends-check", "policy-document", "research", "aqua:1password/cli"}
SCRIPTS = {"05_container_tools.sh", "20_apply_harness_config.sh", "65_agent_kit_install.sh", "76_git_credential_linux.sh", "77_git_identity_linux.sh"}
URL = "http://cliproxyapi.cliproxyapi.svc.cluster.local"
KEY_FILE = "/run/secrets/cliproxy/api-key"
LEFT_OUT = [".codex", ".config/systemd", ".config/hypr", ".config/kitty", ".config/zellij", ".config/nvim", ".local/share/instances", ".ssh", "Library",
            ".config/mise/config.toml", ".config/mise/conf.d/linux.toml", ".local/bin/agent-chrome", ".local/bin/agent-desktop", ".local/bin/agent-session-copy",
            ".local/share/initramfs-ssh-unlock",
            ".config/mise/conf.d/browse.toml", ".local/bin/agent-download", ".local/bin/agent-login", ".local/share/agent-harness/canonical/skills/using-browse"]
HOOK_PRINT = json.dumps({"schema": 1, "entries": [{"event": "PreToolUse", "matcher": "^AskUserQuestion$", "args": [], "failClosed": False, "t3Only": False}]})
HOOK = "console.log(process.argv.includes('--print-settings-json') ? %s : '');\n" % json.dumps(HOOK_PRINT)
IMAGE_TOOLS = ("sh bash cat sed awk grep egrep tr head tail cut sort uniq dirname basename mktemp rm mkdir cp mv chmod ln wc tee uname env date sleep tar gzip find xargs "
               "readlink realpath expr test true false printf echo id whoami printenv diff cmp od sha256sum stat touch rmdir ls git curl jq unzip chezmoi mise").split()
CONFIG = "data:\n  profile: %s\n  container:\n    enabled: true\n%s"


def chezmoi(config, home, *args, path=None):
    env = {k: v for k, v in os.environ.items() if k != "OP_SERVICE_ACCOUNT_TOKEN"}   # no 1Password token: the hub key read fails and warns, as on a CI runner
    env["HOME"] = str(home)
    if path is not None:
        env["PATH"] = path
    return subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(config), "--config-format", "yaml", "--destination", str(home), *args],
                          capture_output=True, text=True, env=env, timeout=180)


class Scratch(unittest.TestCase):
    """One throwaway HOME with a stub coordinator checkout, applied once with container mode on."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.home = cls.tmp / "home"
        (cls.home / "git/coordinator/src/t3-hook").mkdir(parents=True)
        (cls.home / "git/coordinator/src/t3-hook/hook.ts").write_text(HOOK)
        cls.config = cls.tmp / "chezmoi.yaml"
        cls.config.write_text(CONFIG % ("personal", ""))
        r = chezmoi(cls.config, cls.home, "apply", "--exclude=scripts,externals")
        assert r.returncode == 0, r.stderr
        cls.settings = json.loads((cls.home / ".claude/settings.json").read_text())
        cls.managed = set(chezmoi(cls.config, cls.home, "managed").stdout.split())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)


class ContainerHome(Scratch):
    def test_claude_goes_through_the_in_cluster_cliproxy_with_the_key_read_from_a_file(self):   # c5, files side
        self.assertEqual(self.settings["env"]["ANTHROPIC_BASE_URL"], URL)
        self.assertEqual(self.settings["apiKeyHelper"], "cat '%s'" % KEY_FILE)
        self.assertNotIn("ANTHROPIC_API_KEY", self.settings["env"])
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", self.settings["env"])
        self.assertFalse((self.home / ".claude/.credentials.json").exists())

    def test_only_the_five_run_scripts_stay_and_none_runs_on_every_apply(self):   # c6: plain `chezmoi verify` has no always-pending script
        scripts = {p for p in self.managed if p[:2].isdigit() and p.endswith(".sh") and "/" not in p}
        self.assertEqual(scripts, SCRIPTS)
        for name in SCRIPTS:   # run_onchange: recorded after the first success, so `chezmoi verify` is clean after it
            self.assertTrue(list(ROOT.glob("run_onchange_after_" + name.removesuffix(".sh") + ".sh*")), name)

    def test_desktop_systemd_launchd_and_unused_tool_files_are_left_out(self):
        for left in LEFT_OUT:
            self.assertFalse([p for p in self.managed if p == left or p.startswith(left + "/")], left)

    def test_the_files_that_stay_verify_clean(self):
        r = chezmoi(self.config, self.home, "verify", "--exclude=scripts,externals")
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertIn("could not read the hub management key", r.stderr)   # the hub switch is on (f1): the read ran, failed and only warned
        for line in r.stderr.splitlines():   # the hub switch stays on in container mode; its key read cannot succeed here and only warns (f1)
            self.assertTrue(line.startswith(("[modify_settings] WARN: could not read the hub management key", "[op_read_cached.sh]")), line)
        status = chezmoi(self.config, self.home, "status", "--exclude=externals").stdout.split("\n")
        self.assertEqual({line.split()[-1] for line in status if line}, SCRIPTS)   # exactly the kept scripts are still to run

    def test_the_five_seat_instances_exist_on_a_pod_where_t3_has_not_written_its_settings_yet(self):   # playbook 05f37568
        instances = json.loads((self.home / ".t3/userdata/settings.json").read_text())["providerInstances"]
        self.assertEqual({k for k in instances if k.startswith("seat-")}, {"seat-lead", "seat-builder", "seat-planner", "seat-reviewer", "seat-scout"})
        self.assertFalse({"pi", "pi-lead"} & set(instances))   # Pi is not in the pod's tool set
        for seat in ("lead", "builder", "planner", "reviewer", "scout"):
            self.assertIn("--settings %s/.claude/fleet/seat-%s.json" % (self.home, seat), instances["seat-" + seat]["config"]["launchArgs"])
            self.assertTrue((self.home / ".claude/fleet" / ("seat-%s.json" % seat)).exists())

    def test_linked_environments_is_on_in_a_fresh_pods_t3_settings_with_no_script_run(self):   # a peer's `t3 environment link` fails while it is off
        self.assertIs(json.loads((self.home / ".t3/userdata/settings.json").read_text())["linkedEnvironmentsEnabled"], True)

    def test_hook_entries_are_installed_when_node_is_there(self):
        self.assertEqual([g["matcher"] for g in self.settings["hooks"]["PreToolUse"] if "hook.ts" in json.dumps(g)], ["^AskUserQuestion$"])


@unittest.skipUnless(shutil.which("node"), "node is needed to print the hook entries")
class FirstApplyHasNoNode(unittest.TestCase):
    """The pod has no node when chezmoi renders settings.json on its first apply: the hook entries are skipped with a warning and the second apply adds them."""
    def test_the_second_apply_installs_the_hook_entries_the_first_could_not_print(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        home, bare = tmp / "home", tmp / "bin"
        (home / "git/coordinator/src/t3-hook").mkdir(parents=True)
        (home / "git/coordinator/src/t3-hook/hook.ts").write_text(HOOK)
        bare.mkdir()
        for tool in IMAGE_TOOLS:   # what the first apply's PATH has here: shell, coreutils, git, curl, jq, unzip, chezmoi, mise. No node, no python3 (the PATH leaves them out so the test shows the no-node first apply).
            if shutil.which(tool) and not os.path.lexists(bare / tool):
                (bare / tool).symlink_to(shutil.which(tool))
        config = tmp / "chezmoi.yaml"
        config.write_text(CONFIG % ("personal", ""))
        first = chezmoi(config, home, "apply", "--exclude=scripts,externals", path=str(bare))
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("did not print its settings entries", first.stderr)
        self.assertNotIn("hooks", {k for k in json.loads((home / ".claude/settings.json").read_text()) if "hook.ts" in json.dumps(json.loads((home / ".claude/settings.json").read_text())[k])})
        node_dir = tmp / "node-bin"
        node_dir.mkdir()
        (node_dir / "node").symlink_to(shutil.which("node"))
        second = chezmoi(config, home, "apply", "--exclude=scripts,externals", path="%s:%s" % (bare, node_dir))
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("hook.ts", (home / ".claude/settings.json").read_text())


class T3SettingsMerge(unittest.TestCase):
    """The T3 settings file is merge-managed: what T3 wrote stays, and linkedEnvironmentsEnabled is turned on whatever T3 or someone set."""
    def cat(self, config, home):
        r = chezmoi(config, home, "cat", str(home / ".t3/userdata/settings.json"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def setup_home(self, extra, live):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        config, home = tmp / "chezmoi.yaml", tmp / "home"
        config.write_text("data:\n  profile: personal\n" + extra)
        (home / ".t3/userdata").mkdir(parents=True)
        (home / ".t3/userdata/settings.json").write_text(json.dumps(live))
        return config, home

    def test_t3s_own_keys_stay_and_a_switched_off_setting_is_turned_back_on(self):
        config, home = self.setup_home("  container:\n    enabled: true\n", {"linkedEnvironmentsEnabled": False, "compactIdleThreads": True, "usageLimitSources": {"x": {"kind": "cliproxy"}}})
        out = self.cat(config, home)
        self.assertIs(out["linkedEnvironmentsEnabled"], True)
        self.assertIs(out["compactIdleThreads"], True)
        self.assertEqual(out["usageLimitSources"]["x"], {"kind": "cliproxy"})

    def test_outside_container_mode_the_key_is_not_added(self):
        config, home = self.setup_home("", {"compactIdleThreads": True})
        self.assertNotIn("linkedEnvironmentsEnabled", self.cat(config, home))


class LeanMiseSet(Scratch):
    def lean(self):
        return tomllib.loads((self.home / ".config/mise/conf.d/container.toml").read_text())

    def test_the_set_is_exactly_the_lean_tools_with_the_pins_of_config_toml(self):
        lean = self.lean()
        full = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())
        self.assertEqual(set(lean["tools"]), LEAN)
        for name in LEAN - {"aqua:1password/cli"}:
            self.assertEqual(lean["tools"][name], full["tools"][name], name)
        self.assertEqual(lean["tool_alias"], {k: v for k, v in full["tool_alias"].items() if k in LEAN})
        self.assertEqual(lean["tasks"]["install-claude"], full["tasks"]["install-claude"])

    @unittest.skipUnless(shutil.which("mise"), "mise is not installed")
    def test_mise_reads_exactly_the_lean_tools_from_the_one_file_on_an_empty_home(self):   # c6: `mise ls --missing` lists these until the install, then nothing
        home = self.tmp / "misehome"
        (home / ".config/mise/conf.d").mkdir(parents=True)
        shutil.copy(self.home / ".config/mise/conf.d/container.toml", home / ".config/mise/conf.d/container.toml")
        env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / "data"), "XDG_CACHE_HOME": str(home / "cache"),
               "XDG_STATE_HOME": str(home / "state"), "MISE_CONFIG_DIR": str(home / ".config/mise"), "MISE_SYSTEM_CONFIG_DIR": str(home / "sys"), "MISE_OFFLINE": "1"}
        r = subprocess.run(["mise", "config", "ls"], capture_output=True, text=True, env=env, cwd=home, timeout=120)
        rows = [line.split(None, 1) for line in r.stdout.splitlines() if line.strip() and not line.startswith("mise ")]
        self.assertEqual([row[0] for row in rows], ["~/.config/mise/conf.d/container.toml"], r.stdout + r.stderr)
        self.assertEqual({t.strip() for t in rows[0][1].split(",")}, LEAN)


class OffAndWrong(unittest.TestCase):
    def render(self, profile, extra="", os_name=None):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        config = tmp / "chezmoi.yaml"
        config.write_text(CONFIG % (profile, extra))
        return chezmoi(config, tmp / "home", "managed", *(["--override-data", json.dumps({"chezmoi": {"os": os_name}})] if os_name else []))

    def test_without_the_setting_nothing_changes_for_personal(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        config = tmp / "chezmoi.yaml"
        config.write_text("data:\n  profile: personal\n")
        managed = set(chezmoi(config, tmp / "home", "managed").stdout.split())
        self.assertIn(".config/mise/config.toml", managed)
        self.assertNotIn(".config/mise/conf.d/container.toml", managed)
        self.assertNotIn("05_container_tools.sh", managed)
        self.assertTrue({"10_mise_bootstrap.sh", "75_instances_reconcile.sh", "99_report_pi_patch_failures.sh"} <= managed)

    def test_the_work_profile_refuses_container_mode(self):
        r = self.render("axon-work-computer")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("container.enabled needs profile personal", r.stderr)

    def test_a_typo_in_the_settings_fails_the_render(self):
        r = self.render("personal", "    cliproxyUrll: x\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("container.cliproxyUrll is not a setting", r.stderr)

    def test_the_url_and_key_file_can_be_set(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        config = tmp / "chezmoi.yaml"
        config.write_text(CONFIG % ("personal", "    cliproxyUrl: http://cp.test:8317\n    cliproxyKeyFile: /k/key\n"))
        home = tmp / "home"
        (home / ".claude").mkdir(parents=True)
        (home / ".claude/settings.json").write_text("{}")
        r = chezmoi(config, home, "cat", str(home / ".claude/settings.json"))
        settings = json.loads(r.stdout)
        self.assertEqual((settings["env"]["ANTHROPIC_BASE_URL"], settings["apiKeyHelper"]), ("http://cp.test:8317", "cat '/k/key'"))


if __name__ == "__main__":
    unittest.main()
