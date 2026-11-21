"""`apply_harness_config.sh cursor` writes every canonical MCP server (except those in cursor-exclude.txt) into ~/.cursor/mcp.json in
Cursor's own form, on both profiles, and gives Cursor the canonical skills. Real chezmoi renders the canonical files; the real script runs
under sh in a scratch HOME with a fake op (tests/cursor/cursor_apply.py).

    python3 -m unittest discover -s tests/cursor -p 'test_apply_cursor.py' -v
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cursor_apply import PROFILES, Apply, canonical_servers, dummy  # noqa: E402

FOREIGN = {"command": "npx", "args": ["x"], "env": {"A": "${env:A}"}}
JIRA_REF = "op://developer/jira - mcp url/credential"
CONTEXT7_REF = "op://developer/context7 - api key/credential"
SECRET = "resolved-test-value-0600"
# Generated files that can hold a resolved value, with the mode each must have (the script is executable, so 0700).
RESOLVED = {
    "claude/mcp-resolved.json": 0o600,
    "claude/setup-mcp.sh": 0o700,
    "codex/mcp-resolved.json": 0o600,
    "codex/mcp.toml": 0o600,
    "cursor/mcp-resolved.json": 0o600,
    "pi/mcp-resolved.json": 0o600,
}
# Generated files that hold only server names, so nothing resolved: their mode is left as it is.
NAMES_ONLY = ("cursor/mcp-managed.json", "pi/mcp-managed.json")


def secret_apply(test, profile):
    """A scratch apply for `profile` whose canonical input has a server that reads ${TEST_SECRET} in its env and in a header."""
    a = Apply(test, profile)
    (a.tmp / "canonical/mcp/servers.json").write_text(json.dumps({"mcpServers": {
        "local": {"command": "example-server", "args": ["--stdio"], "env": {"TOKEN": "${TEST_SECRET}"}},
        "remote": {"url": "https://remote.example.test/mcp", "headers": {"Authorization": "Bearer ${TEST_SECRET}"}},
    }}))
    a.env["TEST_SECRET"] = SECRET
    a.env["AGENT_HARNESS_APPLY_CLAUDE_MCP"] = "0"  # the Claude script is written, not run
    return a


def plant_old_generated_files(a):
    """Generated files an earlier apply left world-readable (the script 0755), with stale content."""
    for rel in list(RESOLVED) + list(NAMES_ONLY):
        path = a.tmp / "generated" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale\n")
        path.chmod(0o755 if rel.endswith(".sh") else 0o644)


def assert_generated_modes(test, a):
    """Every generated file is there. The resolved ones are owner-only and hold the value; the names-only ones hold no value."""
    generated = a.tmp / "generated"
    found = {p.relative_to(generated).as_posix() for p in generated.rglob("*") if p.is_file()}
    test.assertEqual(found, set(RESOLVED) | set(NAMES_ONLY))
    for rel, mode in RESOLVED.items():
        path = generated / rel
        test.assertEqual(stat.S_IMODE(path.stat().st_mode), mode, rel)
        test.assertIn(SECRET, path.read_text(), rel)
    for rel in NAMES_ONLY:
        test.assertNotIn(SECRET, (generated / rel).read_text(), rel)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi needed")
class ApplyCursor(unittest.TestCase):
    def test_every_canonical_server_is_written_in_cursors_form_on_both_profiles(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                a = Apply(self, profile)
                a.run()
                got = a.servers()
                self.assertEqual(set(got), set(canonical_servers(profile)))
                for name, entry in got.items():
                    self.assertTrue(set(entry) <= {"url", "headers", "command", "args", "env"}, (name, entry))
                    self.assertNotIn("type", entry)
                    self.assertNotIn("${T3CODE_THREAD_ID:-}", json.dumps(entry))  # the shell form is never written
                self.assertEqual(got["shartifacts"]["headers"]["X-Thread"], "${env:T3CODE_THREAD_ID}")
                self.assertEqual(got["shartifacts"]["headers"]["X-Origin"], "work" if profile == "axon-work-computer" else "personal")
                self.assertEqual(got["context7"]["headers"]["CONTEXT7_API_KEY"], dummy(CONTEXT7_REF))
                self.assertTrue(got["rea"]["command"].endswith("/.local/share/mise/shims/rea"))
                self.assertEqual(got["rea"]["args"], ["mcp"])

    def test_work_has_jira_with_the_claude_sides_reference_and_personal_does_not(self):
        work = Apply(self, "axon-work-computer")
        work.run()
        self.assertEqual(work.servers()["jira"], {"url": dummy(JIRA_REF)})
        personal = Apply(self, "personal")
        personal.run()
        self.assertNotIn("jira", personal.servers())

    def test_the_secret_is_never_printed(self):
        a = Apply(self, "axon-work-computer")
        r = a.run()
        self.assertNotIn("secret.example.test", r.stdout + r.stderr)

    def test_foreign_servers_and_other_keys_are_kept_and_ours_are_replaced(self):
        a = Apply(self, "axon-work-computer")
        a.mcp.write_text(json.dumps({"theme": {"a": [1]}, "mcpServers": {"mine": FOREIGN, "hindsight": {"url": "https://old", "extra": 1}}}))
        a.run()
        out = json.loads(a.mcp.read_text())
        self.assertEqual(out["theme"], {"a": [1]})
        self.assertEqual(out["mcpServers"]["mine"], FOREIGN)
        self.assertTrue(out["mcpServers"]["hindsight"]["url"].endswith("/mcp/work/"))
        self.assertNotIn("extra", out["mcpServers"]["hindsight"])

    def test_a_missing_or_empty_file_is_created(self):
        for existing in (None, "  \n"):
            with self.subTest(existing=existing):
                a = Apply(self, "personal")
                if existing is not None:
                    a.mcp.write_text(existing)
                a.run()
                self.assertEqual(set(a.servers()), set(canonical_servers("personal")))

    def test_a_second_run_changes_nothing(self):
        a = Apply(self, "axon-work-computer")
        a.mcp.write_text(json.dumps({"mcpServers": {"mine": FOREIGN}}))
        a.run()
        once = a.mcp.read_text()
        r = a.run()
        self.assertEqual(a.mcp.read_text(), once)
        self.assertNotIn("Updated Cursor MCP config", r.stdout)

    def test_a_server_whose_secret_is_unavailable_is_left_out_and_the_rest_are_written(self):
        for kw in ({"token": False}, {"op": False}):
            with self.subTest(**kw):
                a = Apply(self, "axon-work-computer", **kw)
                a.run()
                got = a.servers()
                self.assertNotIn("jira", got)
                self.assertNotIn("context7", got)
                self.assertIn("hindsight", got)  # the servers with no secret still land
                self.assertIn("shartifacts", got)

    def test_a_file_that_is_not_json_is_left_as_it_is_with_a_message(self):
        for existing in ("{not json\n", '["a"]', '{"mcpServers": "x"}'):
            with self.subTest(existing=existing):
                a = Apply(self, "personal")
                a.mcp.write_text(existing)
                r = a.run()
                self.assertEqual(a.mcp.read_text(), existing)
                self.assertIn("left as it is", r.stdout)

    def test_an_excluded_server_is_not_written_and_a_newly_excluded_one_is_pruned(self):
        a = Apply(self, "personal", exclude="# why\nticktick\n")
        a.run()
        self.assertNotIn("ticktick", a.servers())
        self.assertIn("hindsight", a.servers())
        b = Apply(self, "personal")
        b.run()
        self.assertIn("ticktick", b.servers())
        (b.tmp / "canonical/mcp/cursor-exclude.txt").write_text("ticktick\n")
        r = b.run()
        self.assertNotIn("ticktick", b.servers())
        self.assertIn("Pruned Cursor MCP server no longer in canonical: ticktick", r.stdout)

    def test_a_server_dropped_from_canonical_is_pruned_but_a_foreign_one_stays(self):
        a = Apply(self, "personal")
        a.mcp.write_text(json.dumps({"mcpServers": {"mine": FOREIGN}}))
        a.run()
        canonical = a.tmp / "canonical/mcp/servers.json"
        data = json.loads(canonical.read_text())
        del data["mcpServers"]["ticktick"]
        canonical.write_text(json.dumps(data))
        a.run()
        self.assertNotIn("ticktick", a.servers())
        self.assertEqual(a.servers()["mine"], FOREIGN)

    def test_the_canonical_skills_are_linked_where_cursor_reads_them(self):
        a = Apply(self, "personal")
        a.run()
        from cursor_apply import canonical_skills
        linked = {p.name for p in (a.home / ".agents/skills").iterdir()}
        self.assertEqual(set(canonical_skills()) - linked, set())
        self.assertFalse((a.home / ".cursor/skills").exists(), "no second copy: Cursor would list each skill twice")

    def test_the_mcp_file_is_only_readable_by_its_owner_new_or_existing(self):
        # Pin the umask: a runner with a tighter umask would pass even without the fix.
        old_umask = os.umask(0o022)
        self.addCleanup(os.umask, old_umask)

        with self.subTest(case="new file"):
            new = Apply(self, "personal")
            new.run()
            self.assertEqual(stat.S_IMODE(new.mcp.stat().st_mode), 0o600)

        with self.subTest(case="existing 0644 file whose content changes"):
            changed = Apply(self, "personal")
            changed.mcp.write_text(json.dumps({"mcpServers": {"mine": FOREIGN}}))
            changed.mcp.chmod(0o644)
            changed.run()
            self.assertEqual(stat.S_IMODE(changed.mcp.stat().st_mode), 0o600)

        with self.subTest(case="existing 0644 file whose content is already current"):
            unchanged = Apply(self, "personal")
            unchanged.run()
            unchanged.mcp.chmod(0o644)
            unchanged.run()  # nothing is rewritten, but the mode is still set
            self.assertEqual(stat.S_IMODE(unchanged.mcp.stat().st_mode), 0o600)

    def test_pi_mcp_file_is_only_readable_by_its_owner(self):
        old_umask = os.umask(0o022)
        self.addCleanup(os.umask, old_umask)
        a = Apply(self, "personal")
        r = subprocess.run(["sh", str(a.script), "pi"], env=a.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        pi_mcp = a.home / ".pi/agent/mcp.json"
        self.assertIn("context7", json.loads(pi_mcp.read_text())["mcpServers"])
        self.assertEqual(stat.S_IMODE(pi_mcp.stat().st_mode), 0o600)

    def test_generated_files_that_can_hold_a_resolved_value_are_owner_only(self):
        # Pin the umask: a runner with a tighter umask would pass even without the fix.
        old_umask = os.umask(0o022)
        self.addCleanup(os.umask, old_umask)
        for profile in PROFILES:
            with self.subTest(profile=profile, case="new files"):
                a = secret_apply(self, profile)
                a.run("all")
                assert_generated_modes(self, a)
            with self.subTest(profile=profile, case="existing files left world-readable"):
                b = secret_apply(self, profile)
                plant_old_generated_files(b)
                b.run("all")
                assert_generated_modes(self, b)

    def test_the_codex_config_is_only_readable_by_its_owner_new_or_existing(self):
        # It holds the resolved MCP block, such as the context7 key. Pin the umask as the test above does.
        old_umask = os.umask(0o022)
        self.addCleanup(os.umask, old_umask)
        for profile in PROFILES:
            with self.subTest(profile=profile, case="new file"):
                a = Apply(self, profile)
                a.run("codex")
                self.assertEqual(stat.S_IMODE((a.home / ".codex/config.toml").stat().st_mode), 0o600)
            with self.subTest(profile=profile, case="existing 0644 file whose content changes"):
                b = Apply(self, profile)
                config = b.home / ".codex/config.toml"
                config.parent.mkdir(parents=True)
                config.write_text('model = "x"\n')
                config.chmod(0o644)
                b.run("codex")
                self.assertIn("# BEGIN CHEZMOI AGENT HARNESS MCP", config.read_text())
                self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)
            with self.subTest(profile=profile, case="existing 0644 file whose content is already current"):
                c = Apply(self, profile)
                config = c.home / ".codex/config.toml"
                c.run("codex")
                config.chmod(0o644)
                once = config.read_bytes()
                c.run("codex")  # nothing is rewritten, but the mode is still set
                self.assertEqual(config.read_bytes(), once)
                self.assertEqual(stat.S_IMODE(config.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
