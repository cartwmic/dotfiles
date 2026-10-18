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
LIST = ROOT / "dot_local" / "share" / "pi-mcp-lazy" / "servers.list"
BASELINE_COMMIT = "d6118aba8a06f5dfd84dbae62d9483068cbf7349"
SECRET_MARK = "SECRET-HEADER-VALUE-DO-NOT-LOG"

FAKE_BIN = """#!/bin/sh
# fake stand-in: --refresh succeeds (or fails for names in $FAKE_REFRESH_FAIL) and logs its argv
echo "$@" >> "$FAKE_LOG"
if [ "$1" = "--refresh" ]; then
  case " $FAKE_REFRESH_FAIL " in *" $2 "*) echo "refresh exploded for $2" >&2; exit 1;; esac
  exit 0
fi
exit 0
"""


def render_canonical(profile="personal"):
    t = TMPL.read_text()
    work = "axon-work-computer"
    t = t.replace('{{ if eq .profile "axon-work-computer" }}work{{ else }}cartwmic{{ end }}', "work" if profile == work else "cartwmic")
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
            shutil.copy(LIST, self.list)
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

    def test_three_servers_wrapped_remote_unchanged(self):
        w = self.world()
        r = w.run("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = w.pi_servers()
        c = w.canonical["mcpServers"]
        for name in ("furi", "playwright", "rea"):
            self.assertEqual(s[name]["command"], str(w.bin))
            self.assertEqual(s[name]["args"], [name, "600", "--", c[name]["command"], *c[name]["args"]])
        for name in ("hindsight", "context7", "ticktick"):
            self.assertEqual(s[name], c[name])
        self.assertEqual(set(s), set(c))
        refreshed = w.log.read_text().splitlines()
        self.assertEqual([l.split()[1] for l in refreshed if l.startswith("--refresh")], ["furi", "playwright", "rea"])

    def test_failed_refresh_is_logged_by_name_and_entry_still_wrapped(self):
        w = self.world()
        r = w.run("pi", fail="playwright")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("refresh of playwright failed", r.stdout)
        self.assertIn("refresh exploded for playwright", r.stdout)
        s = w.pi_servers()
        for name in ("furi", "playwright", "rea"):
            self.assertEqual(s[name]["command"], str(w.bin), name)
        self.assertIn("refreshed furi", r.stdout)
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
        w.list.write_text("furi\nplaywright\n")
        w.run("pi")
        s = w.pi_servers()
        self.assertEqual(s["rea"], w.canonical["mcpServers"]["rea"])
        self.assertEqual(s["furi"]["command"], str(w.bin))

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

    def test_work_profile_servers_outside_list_untouched(self):
        w = self.world(profile="axon-work-computer")
        r = w.run("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = w.pi_servers()
        self.assertEqual(s["jira"], w.canonical["mcpServers"]["jira"])
        self.assertEqual(s["rea"]["command"], str(w.bin))


if __name__ == "__main__":
    unittest.main()
