"""Traces stage 2, piece D2: the shadow and seed LaunchAgents, and the arm check (plan 3.3, finding f3).

Each arm plist is rendered with real chezmoi, the pieces it runs are deployed into a scratch HOME with real `chezmoi apply`, and its exact
ProgramArguments and EnvironmentVariables are run under `env -i` with HOME and the state dirs in the scratch dir and
AGENT_EVENTS_OTLP_ENDPOINT pointed at a scripted receiver, on a fixture whose calls sit 5 to 25 minutes before wall-clock now. It asserts:
a payload arrives, no metric name starts with `pi_cache_`, `machine` is the arm's test label, and the arm runs on its own files (the Python
arm: shadow_py_run.py at the path named, the database at $XDG_DATA_HOME/agent-events/events.sqlite and not under $HOME/.local/share, the lock
in its own state dir; the TS arms: the database under the arm's own AGENT_TRACES_DIR). A control step runs the unwrapped command on the same
fixture and requires `pi_cache_*` points, so the assertion cannot pass on an empty fixture.

The Python half needs only python3 and chezmoi and runs in CI. The TS half (the ts and seed arms) needs the installed kit: set
AGENT_TRACES_KIT_INSTALL to a directory that holds node_modules/@cartwmic/agent-kit (for example `npm install @cartwmic/agent-kit@0.27.0` in a
scratch dir), and AGENT_TRACES_NODE_BIN to a node 22.19 or later (default: node on PATH). Without them those tests are skipped and say so.
Nothing here touches the live agent-events directories, calls the real launchctl or applies on the real home.

Run: python3 -m unittest discover -s tests/agent_traces_shadow
"""
import difflib
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "dot_local/share/agent-events"
sys.path.insert(0, str(REPO / "tests/traces-reference"))
sys.path.insert(0, str(TOOLS))
sys.dont_write_bytecode = True
import reference_common as rc  # noqa: E402  (the scripted receiver)
import synth_corpus as sc  # noqa: E402  (the collector's own fixture builder)

DARWIN = platform.system() == "Darwin"
KIT_INSTALL = os.environ.get("AGENT_TRACES_KIT_INSTALL")
NODE_BIN = os.environ.get("AGENT_TRACES_NODE_BIN") or shutil.which("node")
SYS = "/usr/bin:/bin:/usr/sbin:/sbin"  # launchd's PATH
AGENTS = "Library/LaunchAgents"
ARMS = {  # kind -> (label, plist template, test label suffix or fixed label)
    "ts": ("local.agent-traces-shadow", "test-personal-ts"),
    "py": ("local.agent-traces-shadow-py", "test-personal-py"),
    "seed": ("local.agent-traces-seed", "test-seed"),
}


class Chezmoi:
    """chezmoi against the repo with a minimal config (no hooks), extra local data as YAML lines, and a throwaway HOME."""

    def __init__(self, test, profile="personal", data=""):
        tmp = tempfile.TemporaryDirectory(prefix="d2-")
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        self.cfg = self.root / "chezmoi.yaml"
        self.set(profile, data)
        self.state = self.root / "state.boltdb"

    def set(self, profile="personal", data=""):
        self.cfg.write_text("data:\n  profile: %s\n%s" % (profile, "".join("  %s\n" % l for l in data.splitlines())))

    def run(self, *args, stdin=None, check=True, home=None):
        home = home or self.home
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(self.cfg), "--config-format", "yaml", "--destination", str(home),
                            "--persistent-state", str(self.state), "--no-tty", *args],
                           input=stdin, capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=180)
        if check and r.returncode:
            raise AssertionError("chezmoi %s failed: %s" % (args, r.stderr))
        return r

    def render(self, rel, check=True):
        return self.run("execute-template", stdin=(REPO / rel).read_text(), check=check)

    def plist(self, kind):
        return plistlib.loads(self.render("%s/%s.plist.tmpl" % (AGENTS, ARMS[kind][0])).stdout.encode())

    def managed(self):
        return set(self.run("managed", "--include", "files,scripts").stdout.split())


def render(test, rel, profile="personal", data="", check=True):
    return Chezmoi(test, profile, data).render(rel, check)


CONFIG = ".chezmoitemplates/agent_traces_shadow_config"
EVENTS_CONFIG = ".chezmoitemplates/agent_events_config"
LOADER = "run_onchange_after_73_agent_traces_shadow_launchd.sh.tmpl"
SHIM = "dot_local/bin/executable_agent-events.tmpl"
PROD_PLIST = "%s/local.agent-events.plist.tmpl" % AGENTS
WORK = "axon-work-computer"
ENDPOINT = "http://otel-collector.internal.cartwmic.com/v1/metrics"


class SettingTest(unittest.TestCase):
    def cfg(self, profile="personal", data=""):
        return json.loads(render(self, CONFIG, profile, data).stdout)

    def test_defaults_personal_runs_all_three_and_work_none_but_names_py_only_if_turned_on(self):
        self.assertEqual(self.cfg(), {"enabled": True, "machine": "test-personal", "arm": ["ts", "py", "seed"]})
        self.assertEqual(self.cfg(WORK), {"enabled": False, "machine": "test-work", "arm": ["py"]}, "work: off, and the kit is not on by default there")
        self.assertEqual(self.cfg(WORK, "agentTracesShadow: {enabled: true}")["arm"], ["py"])
        self.assertEqual(self.cfg(WORK, "agentTracesShadow: {enabled: true}\nagentKit: {enabled: true}")["arm"], ["ts", "py", "seed"])

    def test_the_settings_are_read(self):
        c = self.cfg(data="agentTracesShadow: {machine: test-abc-1, arm: [seed, ts]}")
        self.assertEqual(c, {"enabled": True, "machine": "test-abc-1", "arm": ["ts", "seed"]}, "arms come out in the fixed order")
        self.assertEqual(self.cfg(data="agentTracesShadow: {arm: []}")["arm"], [])
        self.assertFalse(self.cfg(data="agentTracesShadow: {enabled: false}")["enabled"])

    def test_a_bad_value_fails_every_render_that_reads_it(self):
        bad = ("agentTracesShadow: {enabled: maybe}", "agentTracesShadow: {version: 1}", "agentTracesShadow: {machine: personal}",
               "agentTracesShadow: {machine: test-}", "agentTracesShadow: {machine: test-%s}" % ("a" * 25), "agentTracesShadow: {machine: Test-x}",
               "agentTracesShadow: {arm: ts}", "agentTracesShadow: {arm: [rust]}", "agentTracesShadow: {arm: [ts, bogus]}",
               "agentTracesShadow: on", "agentTracesShadow: {arm: [ts]}\nagentKit: {enabled: false}\nagentEvents: {engine: python}",
               "agentTracesShadow: {arm: [seed]}\nagentKit: {enabled: false}\nagentEvents: {engine: python}")
        # engine python: on personal the events default is ts, which fails first with a message about agentEvents when agentKit is off.
        for data in bad:
            for rel in (CONFIG, LOADER, ".chezmoiignore", "%s/%s.plist.tmpl" % (AGENTS, ARMS["py"][0])):
                with self.subTest(data=data, file=rel):
                    r = render(self, rel, data=data, check=False)
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn("agentTracesShadow", r.stderr)

    def test_the_longest_machine_label_plus_its_suffix_is_still_a_valid_agent_events_label(self):
        label = "test-" + "a" * 24
        for kind, suffix in (("ts", "-ts"), ("py", "-py")):
            env = Chezmoi(self, data="agentTracesShadow: {machine: %s}" % label).plist(kind)["EnvironmentVariables"]
            self.assertEqual(env["AGENT_EVENTS_MACHINE"], label + suffix)
            self.assertRegex(env["AGENT_EVENTS_MACHINE"], r"^[a-z][a-z0-9-]{0,31}$")

    def test_engine_defaults_to_ts_on_personal_and_python_elsewhere(self):
        self.assertEqual(render(self, EVENTS_CONFIG).stdout, '{"enabled":true,"endpoint":"%s","engine":"ts","machine":"personal"}' % ENDPOINT)
        self.assertEqual(render(self, EVENTS_CONFIG, data="agentEvents: {engine: ts}").stdout, render(self, EVENTS_CONFIG).stdout)
        self.assertEqual(render(self, EVENTS_CONFIG, data="agentEvents: {engine: python}").stdout,
                         '{"enabled":true,"endpoint":"%s","machine":"personal"}' % ENDPOINT, "explicit python: no engine key")
        self.assertEqual(render(self, EVENTS_CONFIG, WORK).stdout, '{"enabled":false,"endpoint":"%s","machine":"work"}' % ENDPOINT,
                         "work: no engine key, so its output is what it was before the key existed")

    def test_engine_rejects_other_values_and_ts_without_the_kit(self):
        for data in ("agentEvents: {engine: rust}", "agentEvents: {engine: ''}", "agentEvents: {engine: null}", "agentEvents: {engine: TS}",
                     "agentEvents: {engine: ts}\nagentKit: {enabled: false}"):
            for rel in (EVENTS_CONFIG, SHIM, PROD_PLIST, ".chezmoiignore"):
                with self.subTest(data=data, file=rel):
                    r = render(self, rel, data=data, check=False)
                    self.assertNotEqual(r.returncode, 0)
                    self.assertIn("agentEvents.engine", r.stderr)
        r = render(self, SHIM, WORK, "agentEvents: {engine: ts}", check=False)
        self.assertNotEqual(r.returncode, 0, "work has no kit by default, so ts is refused there until agentKit is set")
        ok = render(self, SHIM, WORK, "agentEvents: {engine: ts}\nagentKit: {enabled: true}")
        self.assertIn('exec "$script_dir/agent-traces" pi "$@"', ok.stdout)

    def test_personal_with_the_kit_off_fails_every_render_until_it_names_python(self):
        """The default is ts on personal, so a personal machine with agentKit off fails each render that reads engine, until it sets python."""
        for rel in (EVENTS_CONFIG, SHIM, PROD_PLIST, ".chezmoiignore"):
            with self.subTest(file=rel):
                r = render(self, rel, data="agentKit: {enabled: false}", check=False)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("agentEvents.engine is ts", r.stderr)
                self.assertTrue(render(self, rel, data="agentKit: {enabled: false}\nagentEvents: {engine: python}").stdout)


class ProductionUnchangedTest(unittest.TestCase):
    """The production plist renders to what it did before D2 on every profile. The shim does on work and with engine python; personal's
    default is ts now (EngineDefaultTest). Copies of the pre-D2 files are in fixtures/ (origin/main a0f35206)."""

    ORIGINAL_SHIM = REPO / "tests/agent_traces_shadow/fixtures/agent-events.sh"
    ORIGINAL_PLIST = REPO / "tests/agent_traces_shadow/fixtures/local.agent-events.plist.rendered"

    def test_the_shim_renders_to_the_bytes_it_had_before(self):
        want = self.ORIGINAL_SHIM.read_bytes()
        self.assertEqual(render(self, SHIM, WORK).stdout.encode(), want, WORK)
        self.assertEqual(render(self, SHIM, data="agentEvents: {engine: python}").stdout.encode(), want)

    def test_the_shim_with_engine_ts_differs_by_exactly_the_one_branch(self):
        base = self.ORIGINAL_SHIM.read_text().splitlines(keepends=True)
        ts = render(self, SHIM, data="agentEvents: {engine: ts}").stdout.splitlines(keepends=True)
        diff = [l for l in difflib.ndiff(base, ts) if l[0] in "+-"]
        self.assertEqual([l for l in diff if l[0] == "-"], [], "nothing of the python shim is lost")
        extra = [l[2:] for l in diff]
        self.assertEqual(len(extra), 4, diff)
        self.assertIn('exec "$script_dir/agent-traces" pi "$@"', "".join(extra))
        # branch order: the override first, then ts, then the Python file
        i = ts.index(base[base.index("implementation=${AGENT_EVENTS_IMPLEMENTATION:-}\n")])
        self.assertTrue(ts[i + 1].startswith("# engine ts"))

    def test_the_production_plist_renders_to_the_bytes_it_had_before(self):
        c = Chezmoi(self)
        home = c.home
        got = c.render(PROD_PLIST).stdout.replace(str(home), "HOME")
        self.assertEqual(got, self.ORIGINAL_PLIST.read_text())
        c.set(data="agentEvents: {engine: python}")
        self.assertEqual(c.render(PROD_PLIST).stdout.replace(str(home), "HOME"), self.ORIGINAL_PLIST.read_text())

    def test_engine_ts_leaves_the_production_plist_alone_too(self):
        c = Chezmoi(self, data="agentEvents: {engine: ts}")
        self.assertEqual(c.render(PROD_PLIST).stdout.replace(str(c.home), "HOME"), self.ORIGINAL_PLIST.read_text(),
                         "the shim is the only switch: ProgramArguments and the env vars stay")

    def test_the_production_plist_never_carries_the_cache_switch(self):
        prod = plistlib.loads(Chezmoi(self).render(PROD_PLIST).stdout.encode())
        self.assertNotIn("AGENT_EVENTS_CACHE_GAUGES", prod["EnvironmentVariables"])


class EngineDefaultTest(unittest.TestCase):
    """D3: the default engine is ts on personal and python on every other profile. The shim follows the engine; the setting's JSON carries
    "engine" only when it is ts, so work's output is unchanged; engine python on personal gives the Python shim back."""

    PRE_D2_SHIM = ProductionUnchangedTest.ORIGINAL_SHIM

    def test_personal_default_is_ts_and_the_shim_execs_the_agent_kit_port(self):
        shim = render(self, SHIM).stdout
        self.assertEqual(shim, render(self, SHIM, data="agentEvents: {engine: ts}").stdout)
        self.assertIn('exec "$script_dir/agent-traces" pi "$@"', shim)
        self.assertEqual(json.loads(render(self, EVENTS_CONFIG).stdout)["engine"], "ts")

    def test_work_renders_no_engine_key_and_the_shim_has_no_ts_branch(self):
        self.assertNotIn("engine", render(self, EVENTS_CONFIG, WORK).stdout)
        shim = render(self, SHIM, WORK).stdout.encode()
        self.assertNotIn(b"agent-traces", shim)
        self.assertEqual(shim, self.PRE_D2_SHIM.read_bytes(), "work: the shim is byte-identical to the pre-D2 rendering")

    def test_personal_with_explicit_python_renders_the_python_shim(self):
        data = "agentEvents: {engine: python}"
        self.assertNotIn("engine", render(self, EVENTS_CONFIG, data=data).stdout)
        self.assertEqual(render(self, SHIM, data=data).stdout.encode(), self.PRE_D2_SHIM.read_bytes())


class PlistShapeTest(unittest.TestCase):
    def test_each_arm_has_its_label_its_own_places_and_no_production_path(self):
        c = Chezmoi(self)
        home = str(c.home)
        prod_state, prod_data = home + "/.local/state/agent-events", home + "/.local/share/agent-events"
        for kind, (label, machine) in ARMS.items():
            with self.subTest(kind=kind):
                p = c.plist(kind)
                env = p["EnvironmentVariables"]
                self.assertEqual(p["Label"], label)
                self.assertEqual(env["AGENT_EVENTS_MACHINE"], machine)
                self.assertTrue(machine.startswith("test-"))
                self.assertEqual(env["AGENT_EVENTS_OTLP_ENDPOINT"], ENDPOINT)
                self.assertEqual((p["StartInterval"], p["RunAtLoad"], p["Nice"]), (120, True, 10))
                state = env["AGENT_EVENTS_STATE_DIR"]
                self.assertNotIn(state, (prod_state, home + "/.local/state"))
                self.assertTrue(state.startswith(home + "/.local/state/agent-traces-"), state)
                self.assertTrue(p["StandardOutPath"].startswith(state + "/") and p["StandardErrorPath"].startswith(state + "/"))
                for k in ("AGENT_EVENTS_STATE_DIR", "AGENT_TRACES_DIR", "XDG_DATA_HOME"):
                    if k in env:
                        self.assertFalse(env[k] == prod_data or env[k].startswith(prod_data + "/") or env[k] == prod_state, (k, env[k]))
        self.assertEqual(len({c.plist(k)["EnvironmentVariables"]["AGENT_EVENTS_STATE_DIR"] for k in ARMS}), 3, "each arm has its own state dir")

    def test_ts_and_seed_run_the_wrapper_with_the_cache_switch_off(self):
        c = Chezmoi(self)
        for kind in ("ts", "seed"):
            p = c.plist(kind)
            self.assertEqual(p["ProgramArguments"], ["/bin/sh", str(c.home) + "/.local/bin/agent-traces", "pi", "run"])
            self.assertEqual(p["EnvironmentVariables"]["AGENT_EVENTS_CACHE_GAUGES"], "0")
            self.assertTrue(p["EnvironmentVariables"]["AGENT_TRACES_DIR"].startswith(str(c.home) + "/.local/share/agent-traces-"))
            self.assertNotIn("AGENT_EVENTS_IMPLEMENTATION", p["EnvironmentVariables"])

    def test_no_arm_names_a_node(self):
        """The ts and seed arms reach node only through the wrapper (which prefers mise's shim: under launchd an install-path node hangs on the
        external disk). No arm sets AGENT_TRACES_NODE or a PATH, and nothing in a plist names a node binary."""
        c = Chezmoi(self)
        for kind in ARMS:
            with self.subTest(kind=kind):
                p = c.plist(kind)
                self.assertNotIn("AGENT_TRACES_NODE", p["EnvironmentVariables"])
                self.assertNotIn("PATH", p["EnvironmentVariables"])
                self.assertNotIn("/mise/installs/", json.dumps(p))
                self.assertNotRegex(json.dumps(p["ProgramArguments"]), r"/node\b")

    def test_py_runs_the_shim_into_shadow_py_run_with_its_own_data_dir(self):
        c = Chezmoi(self)
        p = c.plist("py")
        self.assertEqual(p["ProgramArguments"], ["/bin/sh", str(c.home) + "/.local/bin/agent-events", "run"])
        env = p["EnvironmentVariables"]
        self.assertEqual(env["AGENT_EVENTS_IMPLEMENTATION"], str(c.home) + "/.local/share/agent-events/shadow_py_run.py")
        self.assertEqual(env["XDG_DATA_HOME"], str(c.home) + "/.local/share/agent-traces-shadow-py/data")
        self.assertEqual(env["AGENT_EVENTS_STATE_DIR"], str(c.home) + "/.local/state/agent-traces-shadow-py")
        self.assertNotIn("AGENT_EVENTS_CACHE_GAUGES", env, "shadow_py_run.py drops the gauges in memory; the collector has no such switch")

    def test_py_points_mise_at_its_real_data_dir_outside_the_moved_xdg_dir(self):
        """XDG_DATA_HOME moves mise's default data dir, so the shim's mise python would lose its installs and the shim would find no tomllib."""
        for profile, data in (("personal", ""), (WORK, "")):
            with self.subTest(profile=profile):
                c = Chezmoi(self, profile, data)
                env = c.plist("py")["EnvironmentVariables"]
                self.assertEqual(env["MISE_DATA_DIR"], str(c.home) + "/.local/share/mise")
                self.assertFalse(env["MISE_DATA_DIR"].startswith(env["XDG_DATA_HOME"] + "/"), env["MISE_DATA_DIR"])

    def test_the_work_label_and_the_endpoint_follow_the_settings(self):
        c = Chezmoi(self, WORK, "agentTracesShadow: {enabled: true}\nagentEvents: {endpoint: 'https://x.example/v1/metrics'}")
        self.assertEqual(c.plist("py")["EnvironmentVariables"]["AGENT_EVENTS_MACHINE"], "test-work-py")
        self.assertEqual(c.plist("py")["EnvironmentVariables"]["AGENT_EVENTS_OTLP_ENDPOINT"], "https://x.example/v1/metrics")
        self.assertEqual(c.plist("seed")["EnvironmentVariables"]["AGENT_EVENTS_MACHINE"], "test-seed")

    @unittest.skipUnless(Path("/usr/bin/plutil").exists(), "plutil is macOS only")
    def test_plutil_lints_each_arm(self):
        c = Chezmoi(self)
        for kind, (label, _) in ARMS.items():
            f = c.root / (label + ".plist")
            f.write_text(c.render("%s/%s.plist.tmpl" % (AGENTS, label)).stdout)
            subprocess.run(["/usr/bin/plutil", "-lint", str(f)], check=True, capture_output=True)


@unittest.skipUnless(DARWIN, "the agents are managed on macOS only")
class GateTest(unittest.TestCase):
    """.chezmoiignore: macOS, agentTracesShadow.enabled and the arm list, not the profile."""

    PLISTS = {k: "%s/%s.plist" % (AGENTS, ARMS[k][0]) for k in ARMS}
    SCRIPT = "73_agent_traces_shadow_launchd.sh"

    def managed(self, profile="personal", data="", installed=()):
        c = Chezmoi(self, profile, data)
        for kind in installed:
            (c.home / self.PLISTS[kind]).parent.mkdir(parents=True, exist_ok=True)
            (c.home / self.PLISTS[kind]).write_text("<plist/>")
        return c.managed()

    def test_personal_default_manages_all_three_and_the_script(self):
        m = self.managed()
        self.assertTrue(set(self.PLISTS.values()) | {self.SCRIPT} <= m)
        self.assertIn(".local/share/agent-events/shadow_py_run.py", m)

    def test_work_default_manages_none_of_them_but_still_gets_the_shim_and_wrapper(self):
        m = self.managed(WORK)
        self.assertFalse((set(self.PLISTS.values()) | {self.SCRIPT}) & m)
        self.assertNotIn(".local/share/agent-events/shadow_py_run.py", m)
        self.assertTrue({".local/bin/agent-events", ".local/bin/agent-traces"} <= m)

    def test_the_arm_list_picks_the_plists(self):
        m = self.managed(data="agentTracesShadow: {arm: [py]}")
        self.assertIn(self.PLISTS["py"], m)
        self.assertFalse({self.PLISTS["ts"], self.PLISTS["seed"]} & m)
        self.assertIn(self.SCRIPT, m)

    def test_disabled_keeps_only_the_unload_script_while_a_plist_is_installed(self):
        off = "agentTracesShadow: {enabled: false}"
        m = self.managed(data=off, installed=["seed"])
        self.assertFalse(set(self.PLISTS.values()) & m, "chezmoi leaves the plists alone; the script removes them after the unload")
        self.assertIn(self.SCRIPT, m)
        self.assertNotIn(self.SCRIPT, self.managed(data=off))
        self.assertIn(self.SCRIPT, self.managed(WORK, installed=["ts"]), "a plist left on a disabled machine is cleaned up")

    def test_enabled_on_work_with_the_kit_manages_the_agents(self):
        m = self.managed(WORK, "agentTracesShadow: {enabled: true}\nagentKit: {enabled: true}")
        self.assertTrue(set(self.PLISTS.values()) | {self.SCRIPT} <= m)

    def test_termux_manages_none(self):
        m = self.managed("termux")
        self.assertFalse((set(self.PLISTS.values()) | {self.SCRIPT}) & m)


# A stateful launchctl: "loaded" is a file per label; every call is recorded in full.
FAKE_LAUNCHCTL = r"""#!/bin/sh
echo "launchctl $*" >> "$FAKE/calls"
label=${2##*/}
case $1 in
  print) [ -f "$FAKE/loaded.$label" ] || exit 113 ;;
  bootout) [ -f "$FAKE/loaded.$label" ] || exit 3; case " ${FAKE_STUCK:-} " in *" $label "*) exit 5 ;; esac; rm -f "$FAKE/loaded.$label" ;;
  bootstrap) label=$(basename "$3" .plist); [ "${FAKE_BOOTSTRAP_RC:-0}" = 0 ] || exit "$FAKE_BOOTSTRAP_RC"; [ ! -f "$FAKE/loaded.$label" ] || exit 5; : > "$FAKE/loaded.$label" ;;
  *) exit 64 ;;
esac
"""


class LoaderTest(unittest.TestCase):
    def run_loader(self, data="", profile="personal", installed=("ts", "py", "seed"), loaded=(), **env):
        script = render(self, LOADER, profile, data).stdout
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        h, fake, bin_ = root / "home", root / "fake", root / "bin"
        for d in (h / AGENTS, fake, bin_):
            d.mkdir(parents=True)
        (bin_ / "launchctl").write_text(FAKE_LAUNCHCTL)
        (bin_ / "uname").write_text("#!/bin/sh\necho Darwin\n")
        for f in bin_.iterdir():
            f.chmod(0o755)
        for kind in installed:
            (h / AGENTS / (ARMS[kind][0] + ".plist")).write_text("<plist/>")
        for kind in loaded:
            (fake / ("loaded." + ARMS[kind][0])).write_text("")
        p = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, timeout=30,
                           env=dict(env, HOME=str(h), FAKE=str(fake), PATH="%s:%s" % (bin_, SYS)))
        calls = (fake / "calls").read_text().splitlines() if (fake / "calls").exists() else []
        self.now_loaded = {k for k in ARMS if (fake / ("loaded." + ARMS[k][0])).exists()}
        self.home = h
        return p, calls

    def plist_of(self, kind):
        return self.home / AGENTS / (ARMS[kind][0] + ".plist")

    def test_enabled_loads_only_the_ts_arm_and_leaves_the_others_for_the_lead(self):
        p, calls = self.run_loader()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.now_loaded, {"ts"}, "the control and seed arms are bootstrapped by hand, one at a time")
        self.assertTrue(all("agent-traces-shadow-py" not in c and "agent-traces-seed" not in c for c in calls), calls)
        self.assertEqual([c.split()[1] for c in calls], ["bootout", "bootstrap"])
        for kind in ("ts", "py", "seed"):
            self.assertTrue(self.plist_of(kind).exists())
            self.assertTrue((self.home / (".local/state/" + re.sub(r"^local\.", "", ARMS[kind][0]))).is_dir(), "launchd's log dir exists")
        self.assertIn("not loaded", p.stdout)

    def test_a_reapply_reloads_the_ts_arm_and_never_touches_a_running_control_arm(self):
        p, calls = self.run_loader(loaded=("ts", "py"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.now_loaded, {"ts", "py"})
        self.assertFalse([c for c in calls if "shadow-py" in c])

    def test_disabled_unloads_every_arm_and_removes_the_plists(self):
        p, calls = self.run_loader("agentTracesShadow: {enabled: false}", loaded=("ts", "py", "seed"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.now_loaded, set())
        self.assertFalse(any(self.plist_of(k).exists() for k in ARMS))
        self.assertEqual({c.split()[1] for c in calls}, {"bootout", "print"})

    def test_an_arm_left_out_of_the_list_is_unloaded_and_the_others_stay(self):
        p, calls = self.run_loader("agentTracesShadow: {arm: [ts, py]}", loaded=("ts", "seed"))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.now_loaded, {"ts"}, "seed unloaded; ts reloaded")
        self.assertFalse(self.plist_of("seed").exists())
        self.assertTrue(self.plist_of("py").exists() and self.plist_of("ts").exists())

    def test_a_failed_unload_fails_the_apply_and_keeps_that_plist_so_it_is_retried(self):
        p, calls = self.run_loader("agentTracesShadow: {enabled: false}", loaded=("ts", "py"), FAKE_STUCK="local.agent-traces-shadow-py")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("could not unload local.agent-traces-shadow-py", p.stdout)
        self.assertTrue(self.plist_of("py").exists())
        self.assertFalse(self.plist_of("ts").exists(), "one stuck arm does not stop the others being cleaned up")

    def test_no_plist_yet_warns_and_exits_0(self):
        p, _ = self.run_loader(installed=())
        self.assertEqual(p.returncode, 0)
        self.assertIn("is not installed yet", p.stdout)

    def test_the_script_changes_with_each_setting_so_chezmoi_reruns_it(self):
        outs = {render(self, LOADER, data=d).stdout for d in ("", "agentTracesShadow: {enabled: false}", "agentTracesShadow: {machine: test-x}",
                                                             "agentTracesShadow: {arm: [py]}", "agentEvents: {endpoint: 'http://a.example/v1/metrics'}")}
        self.assertEqual(len(outs), 5)
        s = render(self, LOADER).stdout
        self.assertIn('# setting: {"arm":["ts","py","seed"],"enabled":true,"machine":"test-personal"}\n', s)
        self.assertEqual(len(re.findall(r"# plist (?:ts|py|seed): [0-9a-f]{64}\n", s)), 3)

    def test_the_real_apply_into_a_scratch_home_writes_the_plists_and_runs_the_script_against_the_stub(self):
        if not DARWIN:
            self.skipTest("macOS only: the gate needs darwin")
        c = Chezmoi(self)
        fake = c.root / "fake"
        bin_ = c.root / "bin"
        fake.mkdir()
        bin_.mkdir()
        (bin_ / "launchctl").write_text(FAKE_LAUNCHCTL)
        (bin_ / "launchctl").chmod(0o755)
        (c.home / AGENTS).mkdir(parents=True)
        env = dict(os.environ, HOME=str(c.home), FAKE=str(fake), PATH="%s:%s" % (bin_, os.environ["PATH"]))

        def apply(*targets):
            r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(c.cfg), "--config-format", "yaml", "--destination", str(c.home),
                                "--persistent-state", str(c.state), "--no-tty", "apply", *map(str, targets)], capture_output=True, text=True, timeout=120, env=env)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            return r

        # Two applies, in this order. A scoped apply sorts its targets by name, so a script named 73_* would run before Library/* and find no plist
        # (and run_onchange would then count it as done); a full apply runs after-scripts last.
        apply(*(c.home / AGENTS / (label + ".plist") for label, _ in ARMS.values()))
        self.assertEqual(list(fake.iterdir()), [], "the plists alone load nothing")
        r = apply(c.home / "73_agent_traces_shadow_launchd.sh")
        self.assertIn("loaded local.agent-traces-shadow (every 2 minutes, label test-personal-ts)", r.stdout)
        for kind, (label, _) in ARMS.items():
            self.assertTrue((c.home / AGENTS / (label + ".plist")).exists(), label)
        self.assertEqual({p.name for p in fake.glob("loaded.*")}, {"loaded.local.agent-traces-shadow"})


# ---- the arm check ----

def resource_machine(receiver):
    """The `machine` resource attribute of the first payload."""
    for body in receiver.bodies:
        for rm in body["resourceMetrics"]:
            for a in rm.get("resource", {}).get("attributes", []):
                if a["key"] == "machine":
                    return a["value"].get("stringValue")
    return None


def arm_corpus(root, now=None):
    """Calls 25, 15 and 5 minutes before wall-clock now: inside the 30-minute window the cache gauges are made from."""
    now = int((now or time.time()) * 1000)
    fx = sc.Fixture(sc.S1, "/work/proj", now - 40 * sc.MIN)
    fx.user(now - 40 * sc.MIN + 1000)
    for off in (25.0, 15.0, 5.0):
        end = now - int(off * sc.MIN)
        fx.llm(end - 20_000, end=end, cr=20_000, cw=2_000, fresh=100)
    sc.save(root, "--work-proj--", "2026-10-01T00-00-00-000Z_%s.jsonl" % sc.S1, fx)


class ArmCheck:
    """Deploys what an arm runs into a scratch HOME with real `chezmoi apply`, runs its plist command under env -i, and returns the problems."""

    def __init__(self, test, kind, data=""):
        self.test, self.kind = test, kind
        self.c = Chezmoi(test, "personal", data)
        self.home = self.c.home
        self.plist = self.c.plist(kind)
        self.pi = self.c.root / "pi"
        arm_corpus(self.pi / "sessions")
        (self.c.root / "roots").mkdir()
        self.deploy()

    def deploy(self):
        (self.home / ".local/bin").mkdir(parents=True)
        (self.home / ".local/share").mkdir(parents=True)
        targets = [self.home / ".local/bin/agent-events", self.home / ".local/share/agent-events"]
        if self.kind != "py":
            targets += [self.home / ".local/bin/agent-traces"]
        self.c.run("apply", "--exclude=scripts", *map(str, targets))
        if self.kind != "py":
            kit = self.home / ".local/share/agent-kit"
            if kit.exists():
                shutil.rmtree(kit)
            shutil.copytree(KIT_INSTALL, kit, symlinks=True)

    def env(self, plist_env, receiver, **extra):
        env = {"PATH": SYS, "HOME": str(self.home), "TZ": "UTC", "PI_CODING_AGENT_DIR": str(self.pi), "PYTHONDONTWRITEBYTECODE": "1",
               "AGENT_EVENTS_PROJECTS": "proj", "AGENT_EVENTS_PROJECT_ROOTS": str(self.c.root / "roots"), "AGENT_EVENTS_PYTHON": sys.executable,
               "AGENT_TRACES_NODE": NODE_BIN or ""}
        env.update(plist_env)
        env["AGENT_EVENTS_OTLP_ENDPOINT"] = receiver.url
        env.update(extra)
        return {k: v for k, v in env.items() if v != ""}

    def run(self, args, env):
        return subprocess.run(["/usr/bin/env", "-i", *["%s=%s" % kv for kv in env.items()], *args], capture_output=True, text=True, timeout=300)

    def check(self, mutate=None):
        """The problems the arm check finds; `mutate(plist)` seeds a failure into the plist first (M21)."""
        plist = json.loads(json.dumps(self.plist))
        if mutate:
            mutate(plist)
        env, args, problems = plist["EnvironmentVariables"], plist["ProgramArguments"], []
        label = self.plist["EnvironmentVariables"]["AGENT_EVENTS_MACHINE"]  # the arm's test label as rendered, not as mutated
        with rc.Receiver() as arm:
            r = self.run(args, self.env(env, arm))
            if r.returncode != 0:
                problems.append("the arm's command exited %d: %s" % (r.returncode, (r.stderr.strip().splitlines() or [""])[-1]))
            if not arm.bodies:
                problems.append("no payload arrived")
            cache = [n for n in arm.names() if n.startswith("pi_cache_")]
            if cache:
                problems.append("the arm sent %d pi_cache_* metric(s): %s" % (len(cache), ", ".join(cache)))
            if resource_machine(arm) != label:
                problems.append("machine is %r, not the arm's %r" % (resource_machine(arm), label))
        if self.kind == "py":
            impl = env.get("AGENT_EVENTS_IMPLEMENTATION", "")
            if not impl.endswith("shadow_py_run.py") or not Path(impl).is_file():
                problems.append("shadow_py_run.py does not exist at the path the plist names (%s)" % (impl or "AGENT_EVENTS_IMPLEMENTATION unset"))
            xdg = env.get("XDG_DATA_HOME", "")
            if not xdg or not (Path(xdg) / "agent-events/events.sqlite").exists():
                problems.append("the Python database is not at $XDG_DATA_HOME/agent-events/events.sqlite (%s)" % (xdg or "XDG_DATA_HOME unset"))
            if (self.home / ".local/share/agent-events/events.sqlite").exists():
                problems.append("a database was made at $HOME/.local/share/agent-events/events.sqlite, the default the arm must not fall back to")
            if not (Path(env["AGENT_EVENTS_STATE_DIR"]) / "lock").exists():
                problems.append("its lock is not in its own state dir (%s)" % env["AGENT_EVENTS_STATE_DIR"])
        else:
            data = env.get("AGENT_TRACES_DIR", "")
            if not data or not (Path(data) / "pi/events.sqlite").exists():
                problems.append("the TS database is not under the arm's own AGENT_TRACES_DIR (%s)" % (data or "unset"))
        problems += self.control(plist)
        return problems

    def control(self, plist):
        """The same fixture without what keeps the cache gauges out must send them, or the assertions above prove nothing."""
        env = dict(plist["EnvironmentVariables"])
        state, data = self.c.root / "control-state", self.c.root / "control-data"
        env["AGENT_EVENTS_STATE_DIR"] = str(state)
        if self.kind == "py":
            env.pop("AGENT_EVENTS_IMPLEMENTATION", None)
            env["XDG_DATA_HOME"] = str(data)
            args = [sys.executable, str(self.home / ".local/share/agent-events/agent_events.py"), "run"]
        else:
            env.pop("AGENT_EVENTS_CACHE_GAUGES", None)
            env["AGENT_TRACES_DIR"] = str(data)
            args = plist["ProgramArguments"]
        with rc.Receiver() as control:
            r = self.run(args, self.env(env, control))
            points = [n for n in control.names() if n.startswith("pi_cache_")]
        if r.returncode != 0 or not points:
            return ["the control run (%s) did not send pi_cache_* points (exit %d): the check above could pass on an empty fixture"
                    % ("unwrapped Python" if self.kind == "py" else "the switch removed", r.returncode)]
        return []


class PythonArmTest(unittest.TestCase):
    """The Python half: runs in CI."""

    def setUp(self):
        if not shutil.which("chezmoi"):
            self.skipTest("no chezmoi")

    def test_the_control_arm_passes_and_its_control_run_sees_pi_cache_points(self):
        arm = ArmCheck(self, "py")
        self.assertEqual(arm.check(), [])

    def test_the_arm_runs_the_deployed_shim_and_shadow_py_run_on_its_own_files(self):
        arm = ArmCheck(self, "py")
        self.assertEqual(arm.check(), [])
        state = Path(arm.plist["EnvironmentVariables"]["AGENT_EVENTS_STATE_DIR"])
        data = Path(arm.plist["EnvironmentVariables"]["XDG_DATA_HOME"])
        self.assertTrue((data / "agent-events/events.sqlite").is_file())
        self.assertTrue((state / "status.json").is_file() and (state / "lock").exists())
        self.assertFalse((arm.home / ".local/share/agent-events/events.sqlite").exists())
        self.assertFalse((arm.home / ".local/state/agent-events").exists(), "the live state dir is never made")
        self.assertEqual(json.loads((state / "status.json").read_text()).get("machine"), "test-personal-py")

    def test_M21_the_wrapper_replaced_by_agent_events_py_exits_non_zero_naming_pi_cache(self):
        arm = ArmCheck(self, "py")

        def unwrapped(plist):
            plist["EnvironmentVariables"]["AGENT_EVENTS_IMPLEMENTATION"] = str(arm.home / ".local/share/agent-events/agent_events.py")

        problems = arm.check(unwrapped)
        self.assertTrue(problems)
        self.assertTrue(any("pi_cache_" in p and "5 pi_cache_" in p or "pi_cache_hit_ratio_30m" in p for p in problems), problems)
        self.assertTrue(any("shadow_py_run.py does not exist at the path the plist names" in p for p in problems), problems)

    def test_the_arm_without_xdg_data_home_is_caught_by_the_database_assertion(self):
        arm = ArmCheck(self, "py")

        def no_xdg(plist):
            del plist["EnvironmentVariables"]["XDG_DATA_HOME"]

        problems = arm.check(no_xdg)
        self.assertTrue(any("not at $XDG_DATA_HOME" in p or "XDG_DATA_HOME unset" in p for p in problems), problems)
        self.assertTrue(any("$HOME/.local/share/agent-events/events.sqlite" in p or "exited" in p for p in problems), problems)

    def test_a_wrong_label_is_caught(self):
        arm = ArmCheck(self, "py")

        def live_label(plist):
            plist["EnvironmentVariables"]["AGENT_EVENTS_MACHINE"] = "personal"

        self.assertTrue(any("machine is" in p for p in arm.check(live_label)))

    def test_a_control_on_an_empty_fixture_fails_the_check(self):
        arm = ArmCheck(self, "py")
        shutil.rmtree(arm.pi / "sessions")
        (arm.pi / "sessions").mkdir()
        problems = arm.check()
        self.assertTrue(any("control run" in p for p in problems), problems)


class PyArmMiseTest(unittest.TestCase):
    """The Python arm's shim finds a python with tomllib through mise, under the arm's own env, on the real home.

    The plist is rendered against the real home (execute-template writes nothing), so MISE_DATA_DIR names mise's real data dir. The only thing
    run is the shim's python with `import tomllib`, under env -i with exactly the plist's EnvironmentVariables plus HOME. Skipped where mise or its
    python3 shim is absent (CI).
    """

    def test_the_arm_env_reaches_a_python_with_tomllib_through_the_real_mise_shim(self):
        if not shutil.which("mise"):
            self.skipTest("no mise on PATH: the mise python3 shim cannot be checked here")
        home = Path.home()
        shim = home / ".local/share/mise/shims/python3"
        if not shim.is_file():
            self.skipTest("no mise python3 shim at %s: nothing to check here" % shim)
        c = Chezmoi(self)
        rendered = c.run("execute-template", stdin=(REPO / AGENTS / ("%s.plist.tmpl" % ARMS["py"][0])).read_text(), home=home).stdout
        env = plistlib.loads(rendered.encode())["EnvironmentVariables"]
        argv = ["/usr/bin/env", "-i", *("%s=%s" % kv for kv in env.items()), "HOME=%s" % home, str(shim), "-c", "import tomllib"]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, "the arm's env does not reach a python with tomllib through mise: %s" % (r.stderr.strip() or r.stdout.strip()))


@unittest.skipUnless(KIT_INSTALL and NODE_BIN, "the TS half needs AGENT_TRACES_KIT_INSTALL (an installed kit) and node 22.19 or later")
class TsArmTest(unittest.TestCase):
    """The TS half: the lead runs it on the personal Mac, with the installed kit."""

    def test_the_ts_arm_passes(self):
        self.assertEqual(ArmCheck(self, "ts").check(), [])

    def test_the_seed_arm_passes(self):
        self.assertEqual(ArmCheck(self, "seed").check(), [])

    def test_M21_the_ts_arm_without_its_cache_switch_exits_non_zero_naming_pi_cache(self):
        arm = ArmCheck(self, "ts")

        def no_switch(plist):
            del plist["EnvironmentVariables"]["AGENT_EVENTS_CACHE_GAUGES"]

        problems = arm.check(no_switch)
        self.assertTrue(any("pi_cache_" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
