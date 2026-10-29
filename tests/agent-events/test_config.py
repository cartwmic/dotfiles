"""The always-on agent-events exporter's chezmoi setting (data agentEvents: enabled, machine, endpoint).

Rendered from the real source with a throwaway config (no hooks) and a scratch HOME/destination: the plist, its load script and
.chezmoiignore. The load script also runs against a fake launchctl and uname. Nothing here calls the real launchctl or touches a
live file. Run: python3 -m unittest discover -s tests/agent-events
"""
import os
import platform
import plistlib
import re
import subprocess
import tempfile
import unittest
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PLIST = REPO / "Library/LaunchAgents/local.agent-events.plist.tmpl"
LOADER = REPO / "run_onchange_after_70_agent_events_launchd.sh.tmpl"
IGNORE = REPO / ".chezmoiignore"
CONFIG = REPO / ".chezmoitemplates/agent_events_config"
DARWIN = platform.system() == "Darwin"
SYS = "/usr/bin:/bin:/usr/sbin:/sbin"
DEST_PLIST = "Library/LaunchAgents/local.agent-events.plist"
SCRIPT = "70_agent_events_launchd.sh"
DEFAULT_ENDPOINT = "http://otel-collector.internal.cartwmic.com/v1/metrics"
WORK = "axon-work-computer"


class Chezmoi:
    """chezmoi against the repo with a minimal config (no hooks), extra local data as YAML lines, and a throwaway HOME."""

    def __init__(self, profile="personal", data=""):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        (self.home / "Library/LaunchAgents").mkdir(parents=True)
        self.cfg = Path(self.tmp.name) / "chezmoi.yaml"
        self.set(profile, data)
        self.env = dict(os.environ, HOME=str(self.home))

    def set(self, profile="personal", data=""):
        self.cfg.write_text("data:\n  profile: %s\n%s" % (profile, "".join("  %s\n" % l for l in data.splitlines())))

    def run(self, *args, stdin=None, check=True):
        r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(self.cfg), "--config-format", "yaml",
                            "--destination", str(self.home), "--no-tty", *args],
                           input=stdin, capture_output=True, text=True, env=self.env, timeout=120)
        if check and r.returncode:
            raise AssertionError("chezmoi %s failed: %s" % (args, r.stderr))
        return r

    def render(self, path, check=True):
        return self.run("execute-template", stdin=path.read_text(), check=check)

    def managed(self):
        return set(self.run("managed", "--include", "files,scripts").stdout.split())

    def close(self):
        self.tmp.cleanup()


def render(path, profile="personal", data="", check=True):
    c = Chezmoi(profile, data)
    try:
        return c.render(path, check=check), str(c.home)
    finally:
        c.close()


def plist(profile="personal", data=""):
    r, home = render(PLIST, profile, data)
    return plistlib.loads(r.stdout.encode()), home


BAD = (
    # machine
    "agentEvents: {machine: Work}", "agentEvents: {machine: my mac}", "agentEvents: {machine: ''}", "agentEvents: {machine: -x}",
    "agentEvents: {machine: 1mac}", "agentEvents: {machine: work_mac}", "agentEvents: {machine: mac.local}",
    "agentEvents: {machine: %s}" % ("a" * 33), "agentEvents: {machine: '<x>'}", "agentEvents: {machine: null}",
    # endpoint
    "agentEvents: {endpoint: 'otel-collector.internal.cartwmic.com/v1/metrics'}",
    "agentEvents: {endpoint: 'ftp://otel-collector.internal.cartwmic.com/v1/metrics'}",
    "agentEvents: {endpoint: 'http://otel-collector.internal.cartwmic.com/'}",
    "agentEvents: {endpoint: 'http://otel-collector.internal.cartwmic.com/v1/traces'}",
    "agentEvents: {endpoint: 'http://a&b/v1/metrics'}", "agentEvents: {endpoint: 'http://x/v1/metrics</string>'}",
    "agentEvents: {endpoint: 'http://x/v1/metrics?token=1'}", "agentEvents: {endpoint: ''}",
    "agentEvents: {endpoint: 'http://localhost:99999/v1/metrics'}", "agentEvents: {endpoint: 'http://localhost:65536/v1/metrics'}",
    "agentEvents: {endpoint: 'http://localhost:0/v1/metrics'}", "agentEvents: {endpoint: 'http://localhost:08080/v1/metrics'}",
    "agentEvents: {endpoint: 'http://localhost:/v1/metrics'}",
    # enabled, keys, shape
    'agentEvents: {enabled: "yes"}', "agentEvents: {enabled: 1}", "agentEvents: {enabled: null}",
    "agentEvents: {enabeld: false}", "agentEvents: {privacy: strict}", "agentEvents: on", "agentEvents: [personal]",
)


class SettingTest(unittest.TestCase):
    def test_personal_default_is_todays_agent_plus_the_machine_label(self):
        p, home = plist()
        self.assertEqual(p, {
            "Label": "local.agent-events",
            "ProgramArguments": ["/bin/sh", home + "/.local/bin/agent-events", "run"],
            "RunAtLoad": True, "StartInterval": 120, "Nice": 10,
            "EnvironmentVariables": {"AGENT_EVENTS_OTLP_ENDPOINT": DEFAULT_ENDPOINT, "AGENT_EVENTS_MACHINE": "personal"},
            "StandardOutPath": home + "/.local/state/agent-events/launchd.out",
            "StandardErrorPath": home + "/.local/state/agent-events/launchd.err"})

    def test_work_defaults_to_the_work_label(self):
        self.assertEqual(plist(WORK)[0]["EnvironmentVariables"],
                         {"AGENT_EVENTS_OTLP_ENDPOINT": DEFAULT_ENDPOINT, "AGENT_EVENTS_MACHINE": "work"})

    def test_overrides_render(self):
        env = plist(WORK, "agentEvents: {enabled: true, machine: work-laptop, endpoint: 'https://otel-collector.internal.cartwmic.com/v1/metrics'}")[0]["EnvironmentVariables"]
        self.assertEqual(env, {"AGENT_EVENTS_OTLP_ENDPOINT": "https://otel-collector.internal.cartwmic.com/v1/metrics",
                               "AGENT_EVENTS_MACHINE": "work-laptop"})
        env = plist(data="agentEvents: {endpoint: 'http://10.19.1.201:4318/otlp/v1/metrics', machine: %s}" % ("a" * 32))[0]["EnvironmentVariables"]
        self.assertEqual(env["AGENT_EVENTS_OTLP_ENDPOINT"], "http://10.19.1.201:4318/otlp/v1/metrics")
        self.assertEqual(env["AGENT_EVENTS_MACHINE"], "a" * 32)
        for port in (1, 80, 4318, 9999, 10000, 59999, 64999, 65499, 65529, 65535):  # every branch of the port check
            url = "http://localhost:%d/v1/metrics" % port
            self.assertEqual(plist(data="agentEvents: {endpoint: '%s'}" % url)[0]["EnvironmentVariables"]["AGENT_EVENTS_OTLP_ENDPOINT"], url)
            urllib.parse.urlsplit(url).port  # the exporter's urllib accepts it too
        (a, ha), (b, hb) = plist(data="agentEvents: {enabled: true, machine: personal}"), plist()
        self.assertEqual(str(a).replace(ha, "~"), str(b).replace(hb, "~"), "spelling out the defaults changes nothing")

    def test_a_bad_value_fails_every_render(self):
        # Fail closed: a typo stops the apply (the plist, the load script and .chezmoiignore all include the setting).
        for data in BAD:
            for path in (PLIST, LOADER, IGNORE):
                r, _ = render(path, data=data, check=False)
                self.assertNotEqual(r.returncode, 0, (path.name, data))
                self.assertIn("agentEvents", r.stderr, (path.name, data))

    def test_enabled_without_a_machine_fails_where_there_is_no_default(self):
        for path in (PLIST, LOADER, IGNORE):
            r, _ = render(path, "termux", "agentEvents: {enabled: true}", check=False)
            self.assertNotEqual(r.returncode, 0, path.name)
            self.assertIn("agentEvents.machine is required", r.stderr)
        self.assertEqual(plist("termux", "agentEvents: {enabled: true, machine: phone}")[0]["EnvironmentVariables"]["AGENT_EVENTS_MACHINE"], "phone")

    def test_the_setting_template_is_the_one_source_of_the_values(self):
        out = render(CONFIG)[0].stdout
        self.assertEqual(out, '{"enabled":true,"endpoint":"%s","machine":"personal"}' % DEFAULT_ENDPOINT)
        self.assertEqual(render(CONFIG, WORK)[0].stdout, '{"enabled":false,"endpoint":"%s","machine":"work"}' % DEFAULT_ENDPOINT)
        self.assertEqual(render(CONFIG, "termux")[0].stdout, '{"enabled":false,"endpoint":"%s","machine":""}' % DEFAULT_ENDPOINT)
        self.assertEqual(render(CONFIG, data="agentEvents: {enabled: false}")[0].stdout,
                         '{"enabled":false,"endpoint":"%s","machine":"personal"}' % DEFAULT_ENDPOINT)
        self.assertEqual(render(CONFIG, data='agentEvents: {enabled: "false"}')[0].stdout,
                         '{"enabled":false,"endpoint":"%s","machine":"personal"}' % DEFAULT_ENDPOINT)


@unittest.skipUnless(DARWIN, "the agent is managed on macOS only")
class GateTest(unittest.TestCase):
    """.chezmoiignore: macOS and agentEvents.enabled, not the profile. A disabled agent whose plist is still installed keeps its
    load script, which unloads it."""

    def managed(self, profile="personal", data="", installed=False):
        c = Chezmoi(profile, data)
        try:
            if installed:
                (c.home / DEST_PLIST).write_text("<plist/>")
            return c.managed()
        finally:
            c.close()

    def test_personal_default_manages_the_agent(self):
        m = self.managed()
        self.assertIn(DEST_PLIST, m)
        self.assertIn(SCRIPT, m)

    def test_work_default_manages_neither_so_work_is_unchanged(self):
        m = self.managed(WORK)
        self.assertNotIn(DEST_PLIST, m)
        self.assertNotIn(SCRIPT, m)
        self.assertIn(".local/bin/agent-events", m, "the CLI is already on work; only the LaunchAgent is gated")

    def test_work_enabled_manages_the_agent(self):
        m = self.managed(WORK, "agentEvents: {enabled: true}")
        self.assertIn(DEST_PLIST, m)
        self.assertIn(SCRIPT, m)

    def test_disabled_keeps_only_the_unload_script_while_the_plist_is_installed(self):
        m = self.managed(data="agentEvents: {enabled: false}", installed=True)
        self.assertNotIn(DEST_PLIST, m, "chezmoi leaves the plist alone; the script removes it after the unload")
        self.assertIn(SCRIPT, m)
        m = self.managed(data="agentEvents: {enabled: false}")
        self.assertNotIn(DEST_PLIST, m)
        self.assertNotIn(SCRIPT, m)
        m = self.managed(WORK, installed=True)
        self.assertIn(SCRIPT, m, "a plist left behind on a disabled machine is cleaned up")

    def test_termux_manages_neither(self):
        m = self.managed("termux")
        self.assertNotIn(DEST_PLIST, m)
        self.assertNotIn(SCRIPT, m)

    def test_a_bad_value_stops_chezmoi_before_it_reads_anything_else(self):
        c = Chezmoi(data="agentEvents: {machine: Bad Mac}")
        try:
            r = c.run("managed", check=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("agentEvents.machine must be a slug", r.stderr)
            r = c.run("apply", "--dry-run", "--exclude=scripts", str(c.home / "Library/LaunchAgents"), check=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertFalse((c.home / DEST_PLIST).exists())
        finally:
            c.close()

    def test_apply_writes_the_plist_into_a_scratch_home(self):
        c = Chezmoi()
        try:
            agents = c.home / "Library/LaunchAgents"
            c.run("apply", "--exclude=scripts", str(agents))
            p = plistlib.loads((c.home / DEST_PLIST).read_bytes())
            self.assertEqual(p["EnvironmentVariables"]["AGENT_EVENTS_MACHINE"], "personal")
            if Path("/usr/bin/plutil").exists():
                subprocess.run(["/usr/bin/plutil", "-lint", str(c.home / DEST_PLIST)], check=True, capture_output=True)
            self.assertEqual(c.run("diff", "--exclude=scripts", str(agents)).stdout, "")
            c.set(data="agentEvents: {enabled: false}")
            c.run("apply", "--exclude=scripts", str(agents))
            self.assertTrue((c.home / DEST_PLIST).exists(), "disabled: chezmoi does not delete it; the load script does, after the unload")
        finally:
            c.close()


# A stateful launchctl: "loaded" is a file (as in tests/qmd/test_schedule.py).
FAKE_LAUNCHCTL = r"""#!/bin/sh
echo "launchctl $*" >> "$FAKE/calls"
case $1 in
  print) [ -f "$FAKE/loaded" ] || exit 113 ;;
  bootout) [ -f "$FAKE/loaded" ] || exit 3; [ -z "${FAKE_BOOTOUT_STUCK:-}" ] || exit 5; rm -f "$FAKE/loaded" ;;
  bootstrap) [ "${FAKE_BOOTSTRAP_RC:-0}" = 0 ] || exit "$FAKE_BOOTSTRAP_RC"; [ ! -f "$FAKE/loaded" ] || exit 5; : > "$FAKE/loaded" ;;
  *) exit 64 ;;
esac
"""


class LoaderTest(unittest.TestCase):
    def run_loader(self, data="", profile="personal", installed=True, loaded=False, **env):
        script = render(LOADER, profile, data)[0].stdout
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        h, fake, bin_ = root / "home", root / "fake", root / "bin"
        for d in (h / "Library/LaunchAgents", fake, bin_):
            d.mkdir(parents=True)
        (bin_ / "launchctl").write_text(FAKE_LAUNCHCTL)
        (bin_ / "uname").write_text("#!/bin/sh\necho Darwin\n")
        for f in bin_.iterdir():
            f.chmod(0o755)
        p_ = h / DEST_PLIST
        if installed:
            p_.write_text("<plist/>")
        if loaded:
            (fake / "loaded").write_text("")
        p = subprocess.run(["/bin/sh", "-c", script], capture_output=True, text=True, timeout=30,
                           env=dict(env, HOME=str(h), FAKE=str(fake), PATH="%s:%s" % (bin_, SYS)))
        calls = (fake / "calls").read_text().splitlines() if (fake / "calls").exists() else []
        self.loaded = (fake / "loaded").exists()
        return p, [c.split()[1] for c in calls], p_, h

    def test_enabled_reloads_as_before(self):
        p, calls, plist_, h = self.run_loader(loaded=True)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(calls, ["bootout", "bootstrap"])
        self.assertTrue(self.loaded)
        self.assertTrue((h / ".local/state/agent-events").is_dir())

    def test_disabled_unloads_and_removes_the_plist(self):
        for loaded in (True, False):
            p, calls, plist_, _ = self.run_loader("agentEvents: {enabled: false}", loaded=loaded)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(calls, ["bootout", "print"])
            self.assertFalse(self.loaded)
            self.assertFalse(plist_.exists())
            self.assertIn("unloaded", p.stdout)

    def test_a_failed_unload_fails_the_apply_and_keeps_the_plist_so_it_is_retried(self):
        p, calls, plist_, _ = self.run_loader("agentEvents: {enabled: false}", loaded=True, FAKE_BOOTOUT_STUCK="1")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("could not unload", p.stdout)
        self.assertTrue(self.loaded)
        self.assertTrue(plist_.exists(), "the plist stays, so .chezmoiignore keeps this script and the next apply retries")

    def test_the_script_changes_with_the_setting_so_chezmoi_reruns_it(self):
        outs = {render(LOADER, data=d)[0].stdout for d in ("", "agentEvents: {enabled: false}", "agentEvents: {machine: laptop}",
                                                          "agentEvents: {endpoint: 'https://otel-collector.internal.cartwmic.com/v1/metrics'}")}
        self.assertEqual(len(outs), 4)
        s = render(LOADER)[0].stdout
        self.assertIn('# setting: {"enabled":true,"endpoint":"%s","machine":"personal"}\n' % DEFAULT_ENDPOINT, s)
        self.assertRegex(s, r"# plist: [0-9a-f]{64}\n")
        self.assertEqual(set(re.findall(r"launchctl (\w+)", render(LOADER, data="agentEvents: {enabled: false}")[0].stdout)), {"bootout", "print"})


if __name__ == "__main__":
    unittest.main()
