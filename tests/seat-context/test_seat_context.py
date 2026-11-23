"""seat-context (dot_local/bin/executable_seat-context): what Claude Code really loads for a seat in a folder.

The parser and the settings handling run everywhere. The end-to-end tests run the installed Claude Code against the stand-in API (no network, no key) and
skip when no claude binary is found (CI has none); CLAUDE_BINARY names one. They prove the tool reports what the binary loaded, not what the config says:
the same folder gives a different list once the seat file excludes AGENTS.md, and an AGENTS.md imported by a CLAUDE.md is excluded too.
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "dot_local/bin/executable_seat-context"


def load():
    loader = importlib.machinery.SourceFileLoader("seat_context", str(SCRIPT))
    spec = importlib.util.spec_from_loader("seat_context", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


sc = load()


def find_binary():
    return sc.find_binary()


def request(files, system="s" * 100, tools=("Bash", "Read"), skills=("alpha", "beta")):
    """A request shaped like Claude Code 2.1.330's: the instruction files in one system-reminder block, the skill list in another."""
    body = "<system-reminder>\nCodebase and user instructions are shown below. Be sure to adhere to these instructions.\n\n"
    body += "\n\n".join("Contents of %s (%s):\n\n%s" % (path, kind, text) for path, kind, text in files)
    body += "\n</system-reminder>\n"
    listing = "<system-reminder>\n" + sc.SKILL_LIST_HEAD + "\n" + "\n".join("- %s: does a thing" % s for s in skills) + "\n</system-reminder>"
    return {"system": [{"type": "text", "text": system}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": body}, {"type": "text", "text": listing}, {"type": "text", "text": "hi"}]}],
            "tools": [{"name": t, "description": "d"} for t in tools]}


class ParseRequestTest(unittest.TestCase):
    def test_files_sizes_tools_skills_and_system(self):
        parsed = sc.parse_request(request([("/h/.claude/CLAUDE.md", "user's private global instructions for all projects", "a" * 10),
                                           ("/r/CLAUDE.md", "project instructions, checked into the codebase", "@AGENTS.md"),
                                           ("/r/AGENTS.md", "project instructions, checked into the codebase", "b" * 25)]))
        self.assertEqual([(f["path"], f["chars"]) for f in parsed["files"]], [("/h/.claude/CLAUDE.md", 10), ("/r/CLAUDE.md", 10), ("/r/AGENTS.md", 25)])
        self.assertEqual([t["name"] for t in parsed["tools"]], ["Bash", "Read"])
        self.assertEqual(parsed["skills"], ["alpha", "beta"])
        self.assertEqual(parsed["system_chars"], 100)

    def test_a_request_with_no_instruction_file_lists_none(self):
        self.assertEqual(sc.parse_request(request([]))["files"], [])

    def test_the_hook_text_is_not_guessed_from_the_request(self):
        # a hook's output opens a block that holds other context too: its size comes from a second launch without hooks (main), never from the request alone
        self.assertNotIn("hook_chars", sc.parse_request(request([])))


class SettingsTest(unittest.TestCase):
    def test_excludes_under_the_real_home_name_the_throwaway_path_too_and_the_real_user_file_is_always_excluded(self):
        real, home = Path("/home/u"), Path("/tmp/x/home")
        worker = sc.sanitize_settings({"claudeMdExcludes": ["/home/u/.claude/CLAUDE.md", "**/AGENTS.md"], "apiKeyHelper": "x", "hooks": {"Stop": []}, "env": {"COORDINATOR_SEAT": "builder", "ANTHROPIC_BASE_URL": "u"}},
                                      home, real, False)
        self.assertEqual(worker["claudeMdExcludes"], ["/home/u/.claude/CLAUDE.md", "**/AGENTS.md", "/tmp/x/home/.claude/CLAUDE.md"])
        self.assertNotIn("apiKeyHelper", worker)
        self.assertNotIn("hooks", worker)
        self.assertEqual(worker["env"], {"COORDINATOR_SEAT": "builder"})
        lead = sc.sanitize_settings({}, home, real, True)
        self.assertEqual(lead["claudeMdExcludes"], ["/home/u/.claude/CLAUDE.md"])  # the user file is the throwaway link, so only the ancestor copy is left out
        self.assertIn("hooks", sc.sanitize_settings({"hooks": {"Stop": []}}, home, real, True))

    def test_the_instance_gives_the_settings_file_add_dirs_prompt_file_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"providerInstances": {"seat-builder": {
                "config": {"launchArgs": "--settings /h/.claude/fleet/seat-builder.json --add-dir /h/.claude/fleet/worker --strict-mcp-config --mcp-config /h/.claude/fleet/mcp.json"},
                "environment": [{"name": "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD", "value": "1"}]},
                "coordinator": {"config": {"launchArgs": "--append-system-prompt-file '/s/seat.md' --settings '/s/settings.json'"}}}}))
            builder = sc.read_instance(path, "seat-builder")
            self.assertEqual((builder["settings"], builder["add_dirs"], builder["env"]), ("/h/.claude/fleet/seat-builder.json", ["/h/.claude/fleet/worker"], {"CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD": "1"}))
            self.assertEqual(builder["ignored"], ["--strict-mcp-config", "--mcp-config /h/.claude/fleet/mcp.json"])
            coordinator = sc.read_instance(path, "coordinator")
            self.assertEqual((coordinator["settings"], coordinator["append_system_prompt_file"]), ("/s/settings.json", "/s/seat.md"))
            with self.assertRaises(SystemExit):
                sc.read_instance(path, "seat-nobody")

    def test_one_entry_per_file_and_paths_in_tilde_form(self):
        files = [{"path": "/tmp/t/home/.claude/CLAUDE.md", "kind": "user", "chars": 5}, {"path": "/home/u/.claude/CLAUDE.md", "kind": "project", "chars": 5},
                 {"path": "/home/u/r/AGENTS.md", "kind": "project", "chars": 7}]
        out = sc.collapse(files, "/tmp/t/home", Path("/home/u"))
        self.assertEqual([(f["path"], f["chars"]) for f in out], [("~/.claude/CLAUDE.md", 5), ("~/r/AGENTS.md", 7)])

    def test_the_project_slug_is_the_folder_with_every_other_character_a_dash(self):
        self.assertEqual(sc.project_slug("/home/agent/git/cartwmic-homelab-v2"), "-home-agent-git-cartwmic-homelab-v2")
        self.assertEqual(sc.project_slug("/home/agent/.t3/x"), "-home-agent--t3-x")


class BinaryTest(unittest.TestCase):
    """The installed Claude Code, against the stand-in API."""

    def setUp(self):
        self.binary = find_binary()
        if self.binary is None:
            self.skipTest("no claude binary found (set CLAUDE_BINARY to check one)")
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        (self.home / ".claude").mkdir(parents=True)
        (self.home / ".claude/CLAUDE.md").write_text("user instructions " * 5)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        (self.repo / "AGENTS.md").write_text("repo agents instructions.\n" * 20)

    def run_tool(self, settings, folder=None, extra=()):
        seat_file = self.tmp / "seat.json"
        seat_file.write_text(json.dumps(settings))
        r = subprocess.run([sys.executable, str(SCRIPT), "--seat-file", str(seat_file), "--folder", str(folder or self.repo), "--home", str(self.home),
                            "--binary", str(self.binary), "--json", *extra], capture_output=True, text=True, timeout=300, env={**os.environ, "CLAUDE_BINARY": str(self.binary)})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def paths(self, report):
        return [f["path"] for f in report["instruction_files"]]

    def test_agents_md_loads_until_the_seat_file_excludes_it_and_the_user_file_follows_its_exclude(self):
        loaded = self.run_tool({})
        self.assertIn(str(self.repo / "AGENTS.md"), self.paths(loaded))
        self.assertIn("~/.claude/CLAUDE.md", [p.replace(str(self.home), "~") for p in self.paths(loaded)])
        agents = [f for f in loaded["instruction_files"] if f["path"].endswith("AGENTS.md")][0]
        self.assertEqual(agents["chars"], len(("repo agents instructions.\n" * 20).rstrip()))
        excluded = self.run_tool({"claudeMdExcludes": ["**/AGENTS.md", str(self.home / ".claude/CLAUDE.md")]})
        self.assertEqual(self.paths(excluded), [])
        self.assertLess(excluded["instruction_chars"], loaded["instruction_chars"])

    def test_an_agents_md_imported_by_claude_md_is_excluded_too(self):
        (self.repo / "CLAUDE.md").write_text("@AGENTS.md\n")
        loaded = self.run_tool({})
        self.assertEqual(sorted(p.rsplit("/", 1)[1] for p in self.paths(loaded) if str(self.repo) in p), ["AGENTS.md", "CLAUDE.md"])
        excluded = self.run_tool({"claudeMdExcludes": ["**/AGENTS.md"]})
        self.assertEqual(sorted(p.rsplit("/", 1)[1] for p in self.paths(excluded) if str(self.repo) in p), ["CLAUDE.md"])

    def test_denied_tools_are_gone_from_the_tool_list_and_an_added_dir_loads_its_claude_md(self):
        worker = self.tmp / "worker"
        worker.mkdir()
        (worker / "CLAUDE.md").write_text("worker instructions")
        plain = self.run_tool({})
        self.assertIn("Workflow", plain["tools"])
        denied = self.run_tool({"permissions": {"deny": ["Workflow", "ScheduleWakeup"]}}, extra=["--add-dir", str(worker), "--env", "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD=1"])
        self.assertNotIn("Workflow", denied["tools"])
        self.assertNotIn("ScheduleWakeup", denied["tools"])
        self.assertIn(str(worker / "CLAUDE.md"), self.paths(denied))

    def test_a_hook_that_runs_is_counted_and_a_dropped_one_is_not(self):
        settings = {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "printf 'hook output %s' $(seq 1 100)"}]}]}}
        self.assertEqual(self.run_tool(settings)["hook_chars"], 0)
        kept = self.run_tool(settings, extra=["--keep-hooks"])
        self.assertGreater(kept["hook_chars"], len("hook output "))
        self.assertEqual(kept["hook_events"], ["SessionStart"])


if __name__ == "__main__":
    unittest.main()
