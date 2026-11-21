"""`apply_harness_config.sh cursor` writes every canonical MCP server (except those in cursor-exclude.txt) into ~/.cursor/mcp.json in
Cursor's own form, on both profiles, and gives Cursor the canonical skills. Real chezmoi renders the canonical files; the real script runs
under sh in a scratch HOME with a fake op (tests/cursor/cursor_apply.py).

    python3 -m unittest discover -s tests/cursor -p 'test_apply_cursor.py' -v
"""
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cursor_apply import PROFILES, Apply, canonical_servers, dummy  # noqa: E402

FOREIGN = {"command": "npx", "args": ["x"], "env": {"A": "${env:A}"}}
JIRA_REF = "op://developer/jira - mcp url/credential"
CONTEXT7_REF = "op://developer/context7 - api key/credential"


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


if __name__ == "__main__":
    unittest.main()
