"""Rendering of the lazy stand-in entries for Claude Code, Codex and Pi. Runs the apply script against temporary roots and a
temporary HOME with a fake stand-in; never touches ~/.pi, ~/.claude or ~/.codex."""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local" / "user_scripts" / "executable_apply_harness_config.sh"
TMPL = ROOT / "dot_local" / "share" / "agent-harness" / "canonical" / "mcp" / "servers.json.tmpl"
LIST = ROOT / "dot_local" / "share" / "pi-mcp-lazy" / "servers.list.tmpl"
SEED = ROOT / "dot_local" / "share" / "pi-mcp-lazy" / "seed"
STANDIN = ROOT / "dot_local" / "bin" / "executable_pi-mcp-lazy"
LAZY = ("rea",)  # the local server every desktop profile lists (browse is not lazy on either profile)
IDLE = {"rea": "600"}
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


# The local data keys the work profile requires (docs/profiles.md, "Local data keys"); placeholder values.
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}


def render_list(profile="personal"):
    """servers.list.tmpl as chezmoi renders it for a profile (the one conditional block is the only template syntax)."""
    t = LIST.read_text()
    keep = (lambda m: m.group(1)) if profile == "axon-work-computer" else (lambda m: "")
    return re.sub(r'\{\{ if eq \.profile "axon-work-computer" -\}\}\n(.*?)\{\{ end -\}\}\s*', keep, t, flags=re.S)


def render_canonical(profile="personal"):
    """servers.json.tmpl as real chezmoi renders it, as on macOS (so every canonical gate in the template is evaluated, not re-implemented here)."""
    work = "axon-work-computer"
    data = {"profile": profile, "chezmoi": {"os": "darwin", "homeDir": "/Users/test"}, **(WORK_DATA if profile == work else {})}
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text("{}\n")
        rendered = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template", "--override-data", json.dumps(data)],
                                  input=TMPL.read_text(), text=True, capture_output=True, timeout=120, check=True).stdout
    return json.loads(rendered)


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

    def claude_servers(self):
        return json.loads(self.generated("claude", "mcp-resolved.json"))["mcpServers"]

    def codex_servers(self):
        """The servers Codex is given: the generated block, parsed."""
        return tomllib.loads(self.generated("codex", "mcp.toml"))["mcp_servers"]

    def refreshed(self):
        return [l.split()[1] for l in self.log.read_text().splitlines() if l.startswith("--refresh")]

    def generated(self, *rel):
        return (self.tmp / "generated" / Path(*rel)).read_text()

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class RenderTests(unittest.TestCase):
    def world(self, **k):
        w = World(**k)
        self.addCleanup(w.cleanup)
        return w

    def wrapped(self, w, name, idle):
        c = w.canonical["mcpServers"][name]
        return {"command": str(w.bin), "args": [name, idle, "--", c["command"], *c.get("args", [])]}

    def test_local_servers_wrapped_for_every_harness_remote_unchanged(self):
        w = self.world()
        r = w.run("claude", "codex", "pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        c = w.canonical["mcpServers"]
        for harness, s in (("claude", w.claude_servers()), ("codex", w.codex_servers()), ("pi", w.pi_servers())):
            for name in LAZY:
                want = self.wrapped(w, name, IDLE[name])
                self.assertEqual(s[name]["command"], want["command"], (harness, name))
                self.assertEqual(s[name]["args"], want["args"], (harness, name))
            self.assertEqual(s["browse"], c["browse"], harness)  # browse is a plain stdio entry: not wrapped, not lazy
        for name in ("hindsight", "context7", "ticktick"):
            self.assertEqual(w.claude_servers()[name], c[name])
            self.assertEqual(w.pi_servers()[name], c[name])
            self.assertEqual(set(w.codex_servers()[name]), {"url"} | ({"http_headers"} if "headers" in c[name] else set()))  # not wrapped: still a url entry
        self.assertEqual(set(w.claude_servers()), set(c))
        self.assertEqual(set(w.pi_servers()), set(c))

    def test_claude_registers_the_stand_in_with_the_server_command_after_the_double_dash(self):
        w = self.world()
        self.assertEqual(w.run("claude").returncode, 0)
        script = w.generated("claude", "setup-mcp.sh")
        self.assertIn('mcp add -s user "rea" -- "%s" "rea" "600" "--" "/Users/test/.local/share/mise/shims/rea" "mcp"' % w.bin, script)
        self.assertIn('mcp add -s user "browse" -- "/Users/test/.local/share/mise/shims/browse" "mcp"', script)   # direct, no stand-in in front

    def test_each_name_is_refreshed_once_per_full_apply_and_once_when_a_harness_runs_alone(self):
        w = self.world()
        self.assertEqual(w.run("claude", "codex", "pi").returncode, 0)
        self.assertEqual(sorted(w.refreshed()), sorted(LAZY))
        w2 = self.world()
        self.assertEqual(w2.run("codex").returncode, 0)
        self.assertEqual(sorted(w2.refreshed()), sorted(LAZY))

    def test_failed_refresh_is_logged_by_name_and_entry_still_wrapped(self):
        w = self.world()
        r = w.run("claude", "codex", "pi", fail="rea")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("refresh of rea failed", r.stdout)
        self.assertIn("refresh exploded for rea", r.stdout)
        for s in (w.claude_servers(), w.codex_servers(), w.pi_servers()):
            for name in LAZY:
                self.assertEqual(s[name]["command"], str(w.bin), name)

    def test_server_with_no_saved_list_stays_as_rendered_in_every_harness_and_others_are_still_wrapped(self):
        w = self.world()
        r = w.run("claude", "codex", "pi", extra={"FAKE_CHECK_FAIL": "rea"})
        self.assertEqual(r.returncode, 0, r.stderr)
        c = w.canonical["mcpServers"]
        for s in (w.claude_servers(), w.pi_servers()):
            self.assertEqual(s["rea"], c["rea"])
            self.assertEqual(s["browse"], c["browse"])
        self.assertEqual(w.codex_servers()["rea"]["command"], c["rea"]["command"])

    def test_idle_default_is_configurable_and_a_per_server_value_wins(self):
        w = self.world()
        w.run("claude", "codex", "pi", extra={"PI_MCP_LAZY_IDLE": "300"})
        for s in (w.claude_servers(), w.codex_servers(), w.pi_servers()):
            self.assertEqual(s["rea"]["args"][1], "300")

    def test_comments_and_blank_lines_in_the_list_are_ignored(self):
        w = self.world()
        w.list.write_text("# a comment\n\n  rea   900  # trailing comment\n")
        w.run("pi")
        self.assertEqual(w.pi_servers()["rea"]["args"][:2], ["rea", "900"])

    def test_idempotent(self):
        w = self.world()
        w.run("pi")
        first = (w.home / ".pi" / "agent" / "mcp.json").read_text()
        w.run("pi")
        self.assertEqual((w.home / ".pi" / "agent" / "mcp.json").read_text(), first)

    def test_no_secret_value_in_logs(self):
        w = self.world()
        r = w.run("claude", "codex", "pi", fail="rea")
        self.assertNotIn(SECRET_MARK, r.stdout + r.stderr)
        self.assertNotIn(SECRET_MARK, w.log.read_text())

    def test_rollback_by_removing_list_entry(self):
        w = self.world()
        w.run("claude", "codex", "pi")
        w.list.write_text("# no lazy servers\n")
        w.run("claude", "codex", "pi")
        c = w.canonical["mcpServers"]
        self.assertEqual(w.claude_servers()["rea"], c["rea"])
        self.assertEqual(w.pi_servers()["rea"], c["rea"])
        self.assertEqual(w.codex_servers()["rea"]["command"], c["rea"]["command"])

    def test_missing_list_or_binary_leaves_entries_as_rendered_and_exits_zero(self):
        for broken in ("list", "bin"):
            w = self.world(with_list=broken != "list")
            if broken == "bin":
                w.bin.unlink()
            r = w.run("claude", "codex", "pi")
            self.assertEqual(r.returncode, 0, (broken, r.stderr))
            c = w.canonical["mcpServers"]
            for name in LAZY:
                self.assertEqual(w.claude_servers()[name], c[name], (broken, name))
                self.assertEqual(w.pi_servers()[name], c[name], (broken, name))
                self.assertEqual(w.codex_servers()[name]["command"], c[name]["command"], (broken, name))
            self.assertNotIn("pi-mcp-lazy", w.generated("claude", "setup-mcp.sh") + w.generated("codex", "mcp.toml"))
            self.assertNotIn("pi-mcp-lazy", (w.home / ".codex" / "config.toml").read_text())


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
    """jira is a remote HTTP server on the work profile (no local process to start), so the stand-in does not wrap it."""

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
        self.assertEqual(names("personal"), ["rea"])   # browse, the browser tool on both profiles, is not lazy
        self.assertEqual(names("axon-work-computer"), ["rea"])   # jira left the list: remote HTTP now, nothing to wrap

    def test_chezmoi_renders_the_same_list_for_both_profiles(self):
        if not shutil.which("chezmoi"):
            self.skipTest("chezmoi not installed")
        for profile in ("personal", "axon-work-computer"):
            r = subprocess.run(["chezmoi", "--source", str(ROOT), "execute-template", "--override-data", json.dumps({"profile": profile, **(WORK_DATA if profile == "axon-work-computer" else {})})],
                               input=LIST.read_text(), capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, render_list(profile), profile)

    def test_work_profile_runs_browse_plain_in_all_three_harnesses_and_has_no_browser_harness(self):
        w = self.world()
        r = w.run("claude", "codex", "pi", extra={"JIRA_MCP_URL": JIRA_URL})
        self.assertEqual(r.returncode, 0, r.stderr)
        c = w.canonical["mcpServers"]
        self.assertNotIn("browser-harness", c)
        for harness, s in (("claude", w.claude_servers()), ("codex", w.codex_servers()), ("pi", w.pi_servers())):
            self.assertEqual((s["browse"]["command"], s["browse"]["args"]), (c["browse"]["command"], c["browse"]["args"]), harness)  # not wrapped, not lazy
            self.assertNotIn("browser-harness", s, harness)
        self.assertNotIn("browser-harness", w.refreshed())

    def test_jira_is_a_remote_http_server_for_every_harness(self):
        w = self.world()
        r = w.run("claude", "codex", "pi", extra={"JIRA_MCP_URL": JIRA_URL})
        self.assertEqual(r.returncode, 0, r.stderr)
        want = {"type": "http", "url": JIRA_URL}
        self.assertEqual(w.claude_servers()["jira"], want)
        self.assertEqual(w.codex_servers()["jira"], {"url": JIRA_URL})
        self.assertEqual(w.pi_servers()["jira"], want)
        self.assertNotIn("jira", w.refreshed())   # nothing to wrap: no local process, no refresh
        script = w.generated("claude", "setup-mcp.sh")
        self.assertIn('--transport http "jira"', script)
        self.assertNotIn(JIRA_URL, r.stdout + r.stderr)

    def test_personal_profile_has_no_jira(self):
        w = self.world(profile="personal")
        self.assertEqual(w.run("claude", "codex", "pi").returncode, 0)
        for s in (w.claude_servers(), w.codex_servers(), w.pi_servers()):
            self.assertNotIn("jira", s)
        self.assertEqual(sorted(w.refreshed()), sorted(LAZY))

    def test_jira_without_its_url_stays_literal_like_the_other_url_servers(self):
        w = self.world()
        r = w.run("claude", "codex", "pi")  # JIRA_MCP_URL unset and no secrets adapter: the placeholder stays literal, as for slack and the rest
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(w.claude_servers()["jira"], {"type": "http", "url": "${JIRA_MCP_URL}"})
        self.assertEqual(w.codex_servers()["jira"], {"url": "${JIRA_MCP_URL}"})   # the Codex block records the url only
        self.assertEqual(w.pi_servers()["jira"], {"type": "http", "url": "${JIRA_MCP_URL}"})


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
