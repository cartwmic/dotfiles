"""Pi-only rendering of the lazy stand-in entries. Runs the apply script against temporary roots and a
temporary HOME with a fake stand-in; never touches ~/.pi, ~/.claude or ~/.codex."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local" / "user_scripts" / "executable_apply_harness_config.sh"
TMPL = ROOT / "dot_local" / "share" / "agent-harness" / "canonical" / "mcp" / "servers.json.tmpl"
LIST = ROOT / "dot_local" / "share" / "pi-mcp-lazy" / "servers.list.tmpl"
SEED = ROOT / "dot_local" / "share" / "pi-mcp-lazy" / "seed"
STANDIN = ROOT / "dot_local" / "bin" / "executable_pi-mcp-lazy"
BASELINE_COMMIT = "d6118aba8a06f5dfd84dbae62d9483068cbf7349"
PRE_JIRA_COMMIT = "728e6d5d272d151445f5f2c9809a7bde9be4d3c4"  # last main before jira joined servers.list
SECRET_MARK = "SECRET-HEADER-VALUE-DO-NOT-LOG"

FAKE_BIN = """#!/bin/sh
# fake stand-in: --refresh succeeds (or fails for names in $FAKE_REFRESH_FAIL) and logs its argv;
# --check always passes unless the name is in $FAKE_CHECK_FAIL
echo "$@" >> "$FAKE_LOG"
if [ "$1" = "--refresh" ]; then
  case " $FAKE_REFRESH_FAIL " in *" $2 "*) echo "refresh exploded for $2 args: $*" >&2; exit 1;; esac
  exit 0
fi
if [ "$1" = "--check" ]; then
  case " $FAKE_CHECK_FAIL " in *" $2 "*) exit 1;; esac
  exit 0
fi
exit 0
"""


def render_list(profile="personal"):
    """servers.list.tmpl as chezmoi renders it for a profile (the one conditional block is the only template syntax)."""
    t = LIST.read_text()
    keep = (lambda m: m.group(1)) if profile == "axon-work-computer" else (lambda m: "")
    return re.sub(r'\{\{ if eq \.profile "axon-work-computer" -\}\}\n(.*?)\{\{ end -\}\}\s*', keep, t, flags=re.S)


def render_canonical(profile="personal"):
    t = TMPL.read_text()
    work = "axon-work-computer"
    t = t.replace('{{ if eq .profile "axon-work-computer" }}work{{ else }}cartwmic{{ end }}', "work" if profile == work else "cartwmic")
    t = re.sub(r'\{\{ if eq \.chezmoi\.os "darwin" \}\},(.*?)\{\{ end \}\}', lambda m: "," + m.group(1), t, flags=re.S)  # rendered as on macOS
    t = re.sub(r'\{\{ if eq \.profile "axon-work-computer" \}\},(.*?)\{\{ end \}\}', (lambda m: "," + m.group(1)) if profile == work else "", t, flags=re.S)
    return json.loads(t)


class World:
    def __init__(self, profile="personal", script=SCRIPT, with_list=True, bin_body=FAKE_BIN):
        self.tmp = Path(tempfile.mkdtemp(prefix="pml-render-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.canon = self.tmp / "canonical"
        (self.canon / "mcp").mkdir(parents=True)
        (self.canon / "skills").mkdir()
        canonical = render_canonical(profile)
        canonical["mcpServers"]["context7"]["headers"] = {"CONTEXT7_API_KEY": SECRET_MARK}
        (self.canon / "mcp" / "servers.json").write_text(json.dumps(canonical, indent=2))
        self.canonical = canonical
        (self.tmp / "adapters").mkdir()
        self.bin = self.tmp / "bin" / "pi-mcp-lazy"
        self.bin.parent.mkdir()
        self.bin.write_text(bin_body)
        self.bin.chmod(0o755)
        self.list = self.tmp / "servers.list"
        if with_list:
            self.list.write_text(render_list(profile))
        self.log = self.tmp / "fake.log"
        self.script = script

    def run(self, *harnesses, fail="", extra=None):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "AGENT_HARNESS_CANONICAL_ROOT": str(self.canon),
               "AGENT_HARNESS_GENERATED_ROOT": str(self.tmp / "generated"), "AGENT_HARNESS_ADAPTERS_ROOT": str(self.tmp / "adapters"),
               "AGENT_HARNESS_EXTERNAL_ROOT": str(self.tmp / "external"), "AGENT_HARNESS_APPLY_CLAUDE_MCP": "0",
               "PI_MCP_LAZY_LIST": str(self.list), "PI_MCP_LAZY_BIN": str(self.bin), "FAKE_LOG": str(self.log),
               "FAKE_REFRESH_FAIL": fail}
        env.update(extra or {})
        return subprocess.run(["sh", str(self.script), *harnesses], capture_output=True, text=True, env=env, timeout=120)

    def pi_servers(self):
        return json.loads((self.home / ".pi" / "agent" / "mcp.json").read_text())["mcpServers"]

    def generated(self, *rel):
        return (self.tmp / "generated" / Path(*rel)).read_text()

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class RenderTests(unittest.TestCase):
    def world(self, **k):
        w = World(**k)
        self.addCleanup(w.cleanup)
        return w

    def test_two_servers_wrapped_remote_unchanged(self):
        w = self.world()
        r = w.run("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = w.pi_servers()
        c = w.canonical["mcpServers"]
        for name in ("playwright", "rea"):
            self.assertEqual(s[name]["command"], str(w.bin))
            self.assertEqual(s[name]["args"], [name, "600", "--", c[name]["command"], *c[name]["args"]])
        for name in ("hindsight", "context7", "ticktick"):
            self.assertEqual(s[name], c[name])
        self.assertEqual(set(s), set(c))
        refreshed = w.log.read_text().splitlines()
        self.assertEqual([l.split()[1] for l in refreshed if l.startswith("--refresh")], ["playwright", "rea"])

    def test_failed_refresh_is_logged_by_name_and_entry_still_wrapped(self):
        w = self.world()
        r = w.run("pi", fail="playwright")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("refresh of playwright failed", r.stdout)
        self.assertIn("refresh exploded for playwright", r.stdout)
        s = w.pi_servers()
        for name in ("playwright", "rea"):
            self.assertEqual(s[name]["command"], str(w.bin), name)
        self.assertIn("refreshed rea", r.stdout)

    def test_idle_argument_is_configurable(self):
        w = self.world()
        w.run("pi", extra={"PI_MCP_LAZY_IDLE": "300"})
        self.assertEqual(w.pi_servers()["rea"]["args"][1], "300")

    def test_claude_and_codex_output_untouched(self):
        w = self.world()
        r = w.run("claude", "codex", "pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        claude = json.loads(w.generated("claude", "mcp-resolved.json"))["mcpServers"]
        self.assertEqual(claude["rea"], w.canonical["mcpServers"]["rea"])
        self.assertEqual(claude["playwright"], w.canonical["mcpServers"]["playwright"])
        for rel in (("claude", "mcp-resolved.json"), ("claude", "setup-mcp.sh"), ("codex", "mcp-resolved.json"), ("codex", "mcp.toml")):
            self.assertNotIn("pi-mcp-lazy", w.generated(*rel), rel)
        self.assertNotIn("pi-mcp-lazy", (w.home / ".codex" / "config.toml").read_text())

    def test_claude_and_codex_output_identical_to_baseline_script(self):
        old = subprocess.run(["git", "-C", str(ROOT), "show", BASELINE_COMMIT + ":dot_local/user_scripts/executable_apply_harness_config.sh"],
                             capture_output=True, text=True)
        if old.returncode != 0:
            self.skipTest("baseline commit not available in this checkout")
        w_new = self.world()
        w_old = self.world()
        # The baseline script stores a server's env only for the registering process; the Claude adapter now uses
        # `claude mcp add -e` (tests/agent-browser), so the one canonical server with an env stays out of this comparison.
        for w in (w_new, w_old):
            servers = {k: v for k, v in w.canonical["mcpServers"].items() if k != "browser-harness"}
            (w.canon / "mcp" / "servers.json").write_text(json.dumps({"mcpServers": servers}, indent=2))
        oldfile = w_old.tmp / "old_apply.sh"
        oldfile.write_text(old.stdout)
        w_old.script = oldfile
        self.assertEqual(w_new.run("claude", "codex").returncode, 0)
        self.assertEqual(w_old.run("claude", "codex").returncode, 0)
        for rel in (("claude", "mcp-resolved.json"), ("claude", "setup-mcp.sh"), ("codex", "mcp-resolved.json"), ("codex", "mcp.toml")):
            self.assertEqual(w_new.generated(*rel), w_old.generated(*rel), rel)
        self.assertEqual((w_new.home / ".codex" / "config.toml").read_text(), (w_old.home / ".codex" / "config.toml").read_text())

    def test_idempotent(self):
        w = self.world()
        w.run("pi")
        first = (w.home / ".pi" / "agent" / "mcp.json").read_text()
        w.run("pi")
        self.assertEqual((w.home / ".pi" / "agent" / "mcp.json").read_text(), first)

    def test_no_secret_value_in_logs(self):
        w = self.world()
        r = w.run("pi", fail="rea")
        self.assertNotIn(SECRET_MARK, r.stdout + r.stderr)
        self.assertNotIn(SECRET_MARK, w.log.read_text())

    def test_rollback_by_removing_list_entry(self):
        w = self.world()
        w.run("pi")
        w.list.write_text("playwright\n")
        w.run("pi")
        s = w.pi_servers()
        self.assertEqual(s["rea"], w.canonical["mcpServers"]["rea"])
        self.assertEqual(s["playwright"]["command"], str(w.bin))

    def test_missing_list_or_binary_leaves_entries_as_rendered_and_exits_zero(self):
        w = self.world(with_list=False)
        r = w.run("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(w.pi_servers()["rea"], w.canonical["mcpServers"]["rea"])
        w2 = self.world()
        w2.bin.unlink()
        r2 = w2.run("pi")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(w2.pi_servers()["rea"], w2.canonical["mcpServers"]["rea"])


class PruneTests(unittest.TestCase):
    """Pi's mcp.json: servers the script wrote earlier and canonical no longer has are pruned; others are kept."""

    def world(self, **k):
        w = World(**k)
        self.addCleanup(w.cleanup)
        return w

    @staticmethod
    def set_canonical(w, **extra):
        servers = dict(w.canonical["mcpServers"], **extra)
        (w.canon / "mcp" / "servers.json").write_text(json.dumps({"mcpServers": servers}, indent=2))

    @staticmethod
    def seed_pi(w, servers):
        p = w.home / ".pi" / "agent" / "mcp.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"mcpServers": servers, "settings": {"keep": True}}))

    def test_removed_canonical_server_is_pruned_and_user_entries_kept(self):
        w = self.world()
        self.set_canonical(w, gone={"command": "npx", "args": ["gone-mcp"]})
        self.seed_pi(w, {"mine": {"command": "my-tool", "args": ["x"]}})
        r = w.run("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(w.pi_servers()["gone"], {"command": "npx", "args": ["gone-mcp"]})
        self.set_canonical(w)  # "gone" is removed from the canonical file
        r = w.run("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = w.pi_servers()
        self.assertNotIn("gone", s)
        self.assertEqual(s["mine"], {"command": "my-tool", "args": ["x"]})
        self.assertEqual(set(s), set(w.canonical["mcpServers"]) | {"mine"})
        self.assertIn("Pruned Pi MCP server no longer in canonical: gone", r.stdout)
        self.assertEqual(json.loads((w.home / ".pi" / "agent" / "mcp.json").read_text())["settings"], {"keep": True})

    def test_retired_names_from_before_the_record_are_pruned(self):
        w = self.world()
        self.seed_pi(w, {"furi": {"command": "furi"}, "automation-mcp": {"command": "am"}, "mine": {"command": "m"}})
        r = w.run("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = w.pi_servers()
        self.assertNotIn("furi", s)
        self.assertNotIn("automation-mcp", s)
        self.assertIn("mine", s)

    def test_user_entry_never_in_canonical_survives_repeated_applies(self):
        w = self.world()
        self.seed_pi(w, {"mine": {"command": "m"}})
        for _ in range(3):
            self.assertEqual(w.run("pi").returncode, 0)
        self.assertEqual(w.pi_servers()["mine"], {"command": "m"})

    def test_record_lists_exactly_the_rendered_names_and_second_apply_is_identical(self):
        w = self.world()
        w.run("pi")
        rec = json.loads(w.generated("pi", "mcp-managed.json"))
        self.assertEqual(rec, sorted(w.canonical["mcpServers"]))
        first = (w.home / ".pi" / "agent" / "mcp.json").read_text()
        w.run("pi")
        self.assertEqual((w.home / ".pi" / "agent" / "mcp.json").read_text(), first)

    def test_unreadable_record_prunes_nothing_but_retired_names(self):
        w = self.world()
        self.set_canonical(w, gone={"command": "npx", "args": ["gone-mcp"]})
        w.run("pi")
        self.set_canonical(w)
        (w.tmp / "generated" / "pi" / "mcp-managed.json").write_text("not json")
        r = w.run("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("gone", w.pi_servers())  # conservative: unknown ownership is kept
        w.run("pi")  # the record is rewritten, so ownership is known again from here on

    def test_work_profile_servers_pruned_after_switch_to_personal_render(self):
        w = self.world(profile="axon-work-computer")
        w.run("pi")
        self.assertIn("jira", w.pi_servers())
        self.set_canonical(w)  # replace with the personal render
        personal = render_canonical("personal")
        (w.canon / "mcp" / "servers.json").write_text(json.dumps(personal))
        w.run("pi")
        self.assertNotIn("jira", w.pi_servers())


JIRA_URL = "https://jira.example.invalid/mcp/SECRET-JIRA-URL-DO-NOT-LOG"


class JiraTests(unittest.TestCase):
    """jira is lazy on the work profile only, and an unseeded or failed one falls back to starting at session start."""

    def world(self, profile="axon-work-computer", **k):
        w = World(profile=profile, **k)
        self.addCleanup(w.cleanup)
        return w

    def run_work(self, w, **k):
        extra = {"JIRA_MCP_URL": JIRA_URL}
        extra.update(k.pop("extra", {}))
        return w.run("pi", extra=extra, **k)

    def test_list_renders_per_profile(self):
        names = lambda p: [l for l in render_list(p).splitlines() if l and not l.startswith("#")]
        self.assertEqual(names("personal"), ["playwright", "rea"])
        self.assertEqual(names("axon-work-computer"), ["playwright", "rea", "jira"])

    def test_chezmoi_renders_the_same_list_for_both_profiles(self):
        if not shutil.which("chezmoi"):
            self.skipTest("chezmoi not installed")
        for profile in ("personal", "axon-work-computer"):
            r = subprocess.run(["chezmoi", "--source", str(ROOT), "execute-template", "--override-data", json.dumps({"profile": profile})],
                               input=LIST.read_text(), capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, render_list(profile), profile)

    def test_work_profile_wraps_and_refreshes_jira(self):
        w = self.world()
        r = self.run_work(w)
        self.assertEqual(r.returncode, 0, r.stderr)
        s = w.pi_servers()
        c = w.canonical["mcpServers"]["jira"]
        self.assertEqual(s["jira"]["command"], str(w.bin))
        self.assertEqual(s["jira"]["args"], ["jira", "600", "--", "npx", "-y", "mcp-remote", JIRA_URL])
        self.assertEqual(c["command"], "npx")
        self.assertIn("--refresh jira", w.log.read_text())
        self.assertIn("refreshed jira", r.stdout)
        self.assertNotIn(JIRA_URL, r.stdout + r.stderr)

    def test_personal_profile_has_no_jira_and_pi_output_is_unchanged(self):
        old = subprocess.run(["git", "-C", str(ROOT), "show", PRE_JIRA_COMMIT + ":dot_local/user_scripts/executable_apply_harness_config.sh"],
                             capture_output=True, text=True)
        if old.returncode != 0:
            self.skipTest("pre-jira commit not available in this checkout")
        new = self.world(profile="personal")
        before = self.world(profile="personal")
        before.script = before.tmp / "old_apply.sh"
        before.script.write_text(old.stdout)
        before.list.write_text("playwright\nrea\n")
        self.assertEqual(new.run("pi").returncode, 0)
        self.assertEqual(before.run("pi").returncode, 0)
        self.assertNotIn("jira", new.pi_servers())
        self.assertEqual((new.home / ".pi" / "agent" / "mcp.json").read_text().replace(str(new.bin), "BIN"),
                         (before.home / ".pi" / "agent" / "mcp.json").read_text().replace(str(before.bin), "BIN"))
        self.assertEqual([l.split()[1] for l in new.log.read_text().splitlines() if l.startswith("--refresh")], ["playwright", "rea"])

    def test_unseeded_and_failed_refresh_leaves_jira_eager_and_hides_the_url(self):
        w = self.world()
        r = self.run_work(w, fail="jira", extra={"FAKE_CHECK_FAIL": "jira"})
        self.assertEqual(r.returncode, 0, r.stderr)
        s = w.pi_servers()
        self.assertEqual(s["jira"], {"command": "npx", "args": ["-y", "mcp-remote", JIRA_URL]})
        self.assertIn("jira has no saved tool list; left as rendered", r.stdout)
        self.assertIn("refresh of jira failed", r.stdout)
        self.assertNotIn(JIRA_URL, r.stdout + r.stderr)
        self.assertNotIn("SECRET-JIRA", r.stdout + r.stderr)
        for name in ("playwright", "rea"):
            self.assertEqual(s[name]["command"], str(w.bin), name)

    def test_failed_refresh_with_an_existing_saved_list_still_wraps(self):
        w = self.world()
        r = self.run_work(w, fail="jira")  # the fake --check passes: a state copy or seed exists
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(w.pi_servers()["jira"]["command"], str(w.bin))
        self.assertIn("refresh of jira failed", r.stdout)
        self.assertNotIn("left as rendered", r.stdout)

    def test_jira_missing_from_the_work_render_is_skipped(self):
        w = self.world()
        r = w.run("pi")  # JIRA_MCP_URL unset and no secrets adapter: the placeholder stays literal
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("jira", w.pi_servers())


class CheckModeTests(unittest.TestCase):
    """The real stand-in's --check: exit 0 only when serving would show Pi at least one tool."""

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from harness import Env
        self.env = Env()
        self.addCleanup(self.env.cleanup)

    def check(self, name="jira", cmd=("npx", "-y", "mcp-remote", "u")):
        return subprocess.run([sys.executable, str(STANDIN), "--check", name, "--", *cmd], capture_output=True, text=True,
                              env=self.env.env(), timeout=60)

    def test_no_copy_fails(self):
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("no saved tool list", r.stderr)

    def test_seed_or_state_copy_with_tools_passes(self):
        from harness import write_copy
        key = json.dumps(["npx", "-y", "mcp-remote", "u"])
        write_copy(self.env.seed, "jira", key)
        self.assertEqual(self.check().returncode, 0)
        shutil.rmtree(self.env.seed)
        write_copy(self.env.state, "jira", key)
        self.assertEqual(self.check().returncode, 0)

    def test_copy_with_no_tools_fails(self):
        from harness import write_copy
        write_copy(self.env.state, "jira", json.dumps(["npx", "-y", "mcp-remote", "u"]), tools=())
        self.assertEqual(self.check().returncode, 1)

    def test_stale_copy_still_has_tools_and_passes_with_a_note(self):
        from harness import write_copy
        write_copy(self.env.state, "jira", json.dumps(["npx", "-y", "mcp-remote", "other-url"]))
        r = self.check()
        self.assertEqual(r.returncode, 0)
        self.assertIn("stale", r.stderr)

    def test_unreadable_copy_fails(self):
        self.env.state.mkdir(parents=True)
        (self.env.state / "jira.json").write_text("not a saved copy\n")
        self.assertEqual(self.check().returncode, 1)


class RealStandInApplyTests(unittest.TestCase):
    """The apply script with the real stand-in and a scripted server standing in for jira."""

    def setUp(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from harness import Env, FAKE
        self.fake = FAKE
        self.e = Env()
        self.addCleanup(self.e.cleanup)
        self.w = World(profile="axon-work-computer")
        self.addCleanup(self.w.cleanup)
        shutil.copy(STANDIN, self.w.bin)
        self.w.bin.chmod(0o755)
        self.w.list.write_text("jira\n")

    def run_with(self, jira):
        servers = dict(self.w.canonical["mcpServers"], jira=jira)
        (self.w.canon / "mcp" / "servers.json").write_text(json.dumps({"mcpServers": servers}))
        extra = {k: v for k, v in self.e.env().items() if k.startswith("PI_MCP_LAZY_")}
        return self.w.run("pi", extra=extra)

    def test_scripted_server_is_refreshed_saved_and_wrapped(self):
        jira = {"command": sys.executable, "args": [self.fake, "--dir", str(self.e.fdir), "--marker", self.e.marker]}
        r = self.run_with(jira)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("refreshed jira", r.stdout)
        self.assertTrue((self.e.state / "jira.json").exists())
        entry = self.w.pi_servers()["jira"]
        self.assertEqual(entry["command"], str(self.w.bin))
        self.assertEqual(entry["args"][:3], ["jira", "600", "--"])

    def test_server_that_cannot_start_and_has_no_seed_stays_eager(self):
        jira = {"command": sys.executable, "args": ["-c", "import sys; sys.exit(3)", JIRA_URL]}
        r = self.run_with(jira)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(self.w.pi_servers()["jira"], jira)
        self.assertIn("left as rendered", r.stdout)
        self.assertFalse((self.e.state / "jira.json").exists())
        self.assertNotIn(JIRA_URL, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
