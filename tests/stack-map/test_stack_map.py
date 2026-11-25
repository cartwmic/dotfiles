"""Black-box tests for dot_local/user_scripts/executable_stack_map.py (the agent stack map generator).

Each test runs the real script against a scratch world: four small git repositories (a bare origin and a clone each, named dotfiles,
coordinator, agent-kit and loop-engine) holding just the files the script reads, and a content.md in the dotfiles one. Nothing reads the
real ~/git or the network. Edits are committed and pushed, because the script reads origin/main, never the working tree.

    python3 -m unittest discover -s tests/stack-map -v
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/user_scripts/executable_stack_map.py"
HARNESS = "dot_local/share/agent-harness"
FAKE_KEY = "sk-FAKE-do-not-print-0123456789"

FILES = {
    "dotfiles": {
        "README.md": "# Dotfiles\n\nPersonal dotfiles managed with [chezmoi](https://www.chezmoi.io/) and mise. More words.\n",
        "AGENTS.md": "# Agents\n\nProfiles (`~/.config/chezmoi/chezmoi.yaml` → `data.profile`): `personal`, `axon-work-computer`,\n`termux`.\n",
        "dot_local/share/agent-kit/package.json": '{\n  "name": "agent-kit-install",\n  "dependencies": {\n    "@cartwmic/agent-kit": "0.72.0"\n  }\n}\n',
        "dot_config/mise/config.toml": (
            '[tool_alias]\nloop-engine = "github:cartwmic/loop-engine"\nbookends-check = "github:cartwmic/loop-engine"\n\n[tools]\nripgrep = "latest"\n'
            'loop-engine = { version = "0.71.2", matching_regex = "^loop-cli-" }\nbookends-check = { version = "0.71.2" }\n'),
        HARNESS + "/canonical/instructions/profile-personal.md": (
            "# Profile\n\n## Agent seats and models\n\n| Seat | Model |\n|---|---|\n| Coordinator | Opus 5.5 medium |\n| Builder | Sonnet 5.5 high |\n\n- a note\n\n## Bar table\n"),
        HARNESS + "/canonical/skills/no-ai-slop/SKILL.md": "x\n",
        HARNESS + "/canonical/skills/hill-climb/SKILL.md": "x\n",
        HARNESS + "/canonical/mcp/servers.json.tmpl": '{\n  "mcpServers": {\n    "hindsight": {\n      "type": "http"\n    },\n    "shartifacts": {\n      "type": "http"\n    }\n  }\n}\n',
        HARNESS + "/hooks/bash_rules.py": "x\n",
        HARNESS + "/adapters/claude/a.py": "x\n",
        HARNESS + "/adapters/pi/a.py": "x\n",
        "dot_cursor/mcp.json": "{}\n",
        "dot_t3/private_userdata/modify_settings.json.tmpl": (
            '{{- $owned := list "claude-hub" }}\n'
            '{{- $seats := list (dict "id" "lead" "window" "200000" "advisor" false "subagent" true "mcp" "mcp") (dict "id" "reviewer" "window" "300000" "advisor" false "cache5m" true "mcp" "mcp") }}\n'
            '{{- $owned = append $owned "pi" }}\n'),
        "dot_pi/private_agent/private_models.json.tmpl": (
            '{\n  "providers": {\n    "deepseek": {\n      "baseUrl": "https://api.deepseek.com",\n      "apiKey": "' + FAKE_KEY + '",\n      "models": [\n        {\n'
            '          "id": "deepseek-v4-pro",\n          "name": "DeepSeek V4 Pro"\n        }\n      ]\n    }\n  }\n}\n'),
        "run_once_after_00_install_mise.sh": "#!/bin/sh\n# Install mise.\necho hi\n",
        "run_onchange_after_10_two.sh.tmpl": "{{ if true }}\n#!/bin/sh\n# Second step, runs later.\n",
        "docs/stack-map/content.md": None,  # filled in by CONTENT below
    },
    "coordinator": {
        "package.json": '{\n  "name": "coordinator",\n  "version": "0.0.1",\n  "dependencies": {\n    "@cartwmic/agent-kit": "0.72.0"\n  }\n}\n',
        "README.md": "# coordinator\n\nA coordinator for a fleet of agents. It does more.\n\nThe daemon writes wrappers to `<state>/pane-bin` when it runs.\n",
        "docs/README.md": "# Docs\n\n- Module notes: [coordinatord](../src/coordinatord/README.md).\n",
        "src/coordinatord/README.md": "# coordinatord\n\nThe composition and the CLI. More.\n",
        "playbook.md": "# Playbook\n\n## aaaaaaaa · both\n\nrule\n\n## bbbbbbbb · personal\n\nrule\n\n## cccccccc\n\nold rule\n",
        "src/ledger/index.ts": "const SQL = `\nCREATE TABLE IF NOT EXISTS asks (\n  id TEXT\n);\nCREATE TABLE IF NOT EXISTS decisions (\n  id TEXT\n);\n`;\n",
        "src/coordinatord/config.ts": "export const CONFIG_KEYS = {\n  pane_cwd: {\n    doc: 'x',\n  },\n  t3_cli: {\n    doc: 'y',\n  },\n} as const;\n",
        "src/coordinatord/cli.ts": (
            "//   coordinator config get KEY\n//   coordinator kill [--why T]   create $COORDINATOR_STATE_DIR/KILL\n// the rank file is <state dir>/rank\n"  # a stale header: it lacks `jobs`
            "export const USAGE = `usage: coordinator <command>\n  config get [KEY]   print one value\n  config set KEY V   store a value\n  kill [--why T]   stop sends\n"
            "  jobs list|add   the kit's jobs\n\nconfig keys:\n  not_a_command   x\n`;\n"),
        "src/config-file.ts": "export const configPathOf = (s: string) => join(s, 'config.json');\n",
        "scripts/journeys/010-a.journey.ts": "x\n",
        "scripts/journeys/020-b.journey.ts": "x\n",
        "docs/PRD.md": "# PRD\n\n### LE-1 first\n\n### LE-2 second\n",
        "bookends.toml": "[bookends]\n",
    },
    "agent-kit": {
        "package.json": '{\n  "name": "@cartwmic/agent-kit",\n  "version": "0.72.0",\n  "exports": {\n    ".": {},\n    "./chat": {},\n    "./chat/discord-order": {},\n    "./inbox": {}\n  }\n}\n',
        "README.md": "# agent-kit\n\nShared libraries for agents. Each does one job:\n",
    },
    "loop-engine": {
        "Cargo.toml": '[workspace]\nmembers = ["crates/cli", "crates/core"]\n\n[workspace.package]\nversion = "0.71.2"\n',
        "README.md": "# Loop Engine\n\n## Purpose\n\nLoop Engine stores workflow state. It never runs agents.\n",
        "crates/cli/Cargo.toml": '[package]\nname = "loop-cli"\n\n[[bin]]\nname = "loop-engine"\npath = "src/main.rs"\n',
        "crates/core/Cargo.toml": '[package]\nname = "loop-core"\n',
    },
}

CONTENT = """<!-- fixture content -->
# Agent stack map

## Start here

Five plain sentences live here.[[coordinator:package.json:2|"name": "coordinator"]]

## The one-minute picture

The **coordinator** runs `ledger open` for you.

## What each repository is for

| Repo | Job |
|---|---|
| dotfiles | the machines [[dotfiles:README.md:1|# Dotfiles]] |
| agent-kit | libraries [[agent-kit:package.json:3|"version": "0.72.0"]] |

## How a piece of work moves

```flow
1. Michael | asks [[coordinator:README.md:1|# coordinator]] | coordinator:README.md
2. Coordinator | opens a ledger ask `ledger open` | coordinator:docs
3. Builder | opens a pull request | gh pr create
```

## Where do I change X?

| Change | Where |
|---|---|
| bump agent-kit | `dot_local/share/agent-kit/package.json` [[dotfiles:dot_local/share/agent-kit/package.json:4|"@cartwmic/agent-kit"]] |

## Glossary

- **seat**: the role an agent plays.
"""
FILES["dotfiles"]["docs/stack-map/content.md"] = CONTENT


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


class World:
    """Four clones under root/ with a bare origin each. `change` commits and pushes, which moves origin/main."""

    def __init__(self, base):
        self.base = Path(base)
        self.root = self.base / "git"
        for name, files in FILES.items():
            origin, work = self.base / "origins" / (name + ".git"), self.root / name
            origin.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
            work.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
            git(work, "remote", "add", "origin", str(origin))
            for path, text in files.items():
                self.write(name, path, text)
            git(work, "add", "-A")
            git(work, "commit", "-q", "-m", "seed")
            git(work, "push", "-q", "origin", "main")
            git(work, "fetch", "-q", "origin", "main")

    def write(self, name, path, text):
        target = self.root / name / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def change(self, name, path, text=None, push=True):
        """Write (or, with text None, remove) a file, commit it and push it to the bare origin."""
        work = self.root / name
        if text is None:
            git(work, "rm", "-q", path)
        else:
            self.write(name, path, text)
            git(work, "add", path)
        git(work, "commit", "-q", "-m", "change " + path)
        if push:
            git(work, "push", "-q", "origin", "main")
            git(work, "fetch", "-q", "origin", "main")

    def read(self, name, path):
        return (self.root / name / path).read_text(encoding="utf-8")


class StackMapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.world = World(self.tmp.name)
        self.state = Path(self.tmp.name) / "state"

    def run_script(self, *extra, out="page.html"):
        page = Path(self.tmp.name) / out
        env = {k: v for k, v in os.environ.items() if k != "STACK_MAP_LOG"}
        env["XDG_STATE_HOME"] = str(self.state)
        done = subprocess.run([sys.executable, str(SCRIPT), "--out", str(page), "--repos-root", str(self.world.root), *extra], capture_output=True, text=True, env=env)
        return done, page

    def test_clean_run_writes_a_page_with_the_facts(self):
        done, page = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        html = page.read_text(encoding="utf-8")
        self.assertIn("facts: seats=2", done.stdout)
        self.assertIn("citations verified: 5", done.stdout)
        for want in ("Opus 5.5 medium", "seat-reviewer", "5-minute prompt cache", "deepseek-v4-pro", "bookends-check", "no-ai-slop", "run_once_after_00_install_mise.sh", "Second step, runs later.",
                     "personal, axon-work-computer, termux", "loop-engine"):
            self.assertIn(want, html)
        sha = subprocess.run(["git", "-C", str(self.world.root / "coordinator"), "rev-parse", "origin/main"], capture_output=True, text=True).stdout.strip()
        self.assertIn("github.com/cartwmic/coordinator/blob/%s/package.json#L2" % sha, html)  # a citation links to the file at the commit
        self.assertNotIn(self.tmp.name, html)  # no absolute path leaks into the page

    def test_same_commits_give_the_same_bytes(self):
        first, page = self.run_script()
        one = page.read_bytes()
        second, page2 = self.run_script(out="again.html")
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertEqual(one, page2.read_bytes())

    def test_reads_origin_main_not_the_working_tree(self):
        self.world.write("agent-kit", "package.json", self.world.read("agent-kit", "package.json").replace("0.72.0", "9.9.9"))  # uncommitted
        done, page = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("9.9.9", page.read_text(encoding="utf-8"))

    def test_changed_snippet_fails_naming_the_citation(self):
        self.world.change("dotfiles", "docs/stack-map/content.md", CONTENT.replace('"name": "coordinator"', '"name": "coordinatorX"'))
        done, page = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertRegex(done.stderr, r"coordinator:package\.json:2: .*coordinatorX.*content\.md line \d+")
        self.assertFalse(page.exists())

    def test_citation_in_a_table_cell_and_in_a_flow_step_keeps_its_pipe(self):
        done, page = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        html = page.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r'<td data-label="Job">the machines', html)), 1)
        self.assertIn("libraries", html)
        self.assertRegex(html, r'<tr><td data-label="Repo">dotfiles</td><td data-label="Job">the machines<sup class="cite"><a href="[^"]+" title="dotfiles README\.md:1">\d+</a></sup></td></tr>')
        self.assertRegex(html, r'<summary>Sources \(2\)</summary><ol><li><a href="[^"]+">dotfiles README\.md:1</a></li><li><a href="[^"]+">agent-kit package\.json:3</a></li></ol>')  # one list per section, in marker order
        self.assertIn("coordinator:README.md", html)  # the flow step's where-cell survived the split

    def test_missing_fact_source_is_a_hard_failure(self):
        self.world.change("dotfiles", "dot_config/mise/config.toml", None)
        done, page = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertIn("dotfiles:dot_config/mise/config.toml:0: missing at origin/main", done.stderr)
        self.assertFalse(page.exists())

    def test_an_extractor_that_finds_nothing_fails(self):
        self.world.change("coordinator", "src/ledger/index.ts", "const nothing = 1;\n")
        done, _ = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertIn("coordinator:src/ledger/index.ts:0: no CREATE TABLE statements found", done.stderr)

    def test_flow_step_naming_a_missing_path_fails(self):
        self.world.change("dotfiles", "docs/stack-map/content.md", CONTENT.replace("coordinator:docs", "coordinator:docs/nope.md"))
        done, _ = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertIn("coordinator:docs/nope.md:0: flow step 2 names a path missing", done.stderr)

    def test_missing_section_fails(self):
        self.world.change("dotfiles", "docs/stack-map/content.md", CONTENT.replace("## Glossary", "## Notes"))
        done, _ = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertIn("no `## ` section for 'Glossary'", done.stderr)

    def test_headings_with_the_word_repo_still_find_their_own_section(self):
        content = CONTENT.replace("## How a piece of work moves", "## How a piece of work moves through the repos").replace("## Where do I change X?", "## Where do I change X in each repo?")
        content = content.replace("Five plain sentences live here.", "See [the glossary](docs/glossary.md) and [the web](https://example.com/x).")
        self.world.change("dotfiles", "docs/stack-map/content.md", content)
        done, page = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        html = page.read_text(encoding="utf-8")
        self.assertIn("See the glossary and", html)  # a link to a repository file keeps only its words
        self.assertIn('<a href="https://example.com/x">the web</a>', html)
        self.assertIn("<h2>How a piece of work moves through the repos</h2>", html)

    def test_a_flow_step_naming_a_folder_links_to_the_tree(self):
        done, page = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(page.read_text(encoding="utf-8"), r'github\.com/cartwmic/coordinator/tree/[0-9a-f]{40}/docs"')

    def test_no_content_file_at_origin_main_fails(self):
        self.world.change("dotfiles", "docs/stack-map/content.md", None)
        done, _ = self.run_script()
        self.assertEqual(done.returncode, 1)
        self.assertIn("dotfiles:docs/stack-map/content.md:0: missing at origin/main", done.stderr)

    def test_content_flag_overrides_the_file_in_dotfiles(self):
        self.world.change("dotfiles", "docs/stack-map/content.md", None)
        alt = Path(self.tmp.name) / "alt.md"
        alt.write_text(CONTENT, encoding="utf-8")
        done, _ = self.run_script("--content", str(alt))
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_a_mismatched_pin_is_flagged_in_red_words(self):
        self.world.change("dotfiles", "dot_local/share/agent-kit/package.json", self.world.read("dotfiles", "dot_local/share/agent-kit/package.json").replace("0.72.0", "0.71.0"))
        done, page = self.run_script()
        self.assertEqual(done.returncode, 0, done.stderr)
        html = page.read_text(encoding="utf-8")
        self.assertIn("MISMATCH: the two pins differ", html)
        self.assertIn("pin 0.72.0 vs 0.71.0", html)

    def test_keys_never_reach_the_page_or_the_facts(self):
        done, page = self.run_script("--facts-json")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn(FAKE_KEY, page.read_text(encoding="utf-8"))
        self.assertNotIn(FAKE_KEY, done.stdout)
        self.assertNotIn("api.deepseek.com", done.stdout)

    def test_facts_json_lists_what_was_parsed(self):
        done, _ = self.run_script("--facts-json")
        facts = json.loads(done.stdout)
        self.assertEqual([r["seat"] for r in facts["seats"]["table"]["rows"]], ["Coordinator", "Builder"])
        self.assertEqual([i["id"] for i in facts["seats"]["t3"]["instances"]], ["seat-lead", "seat-reviewer", "claude-hub", "pi"])
        self.assertEqual(facts["providers"]["pi"]["providers"][0]["models"], ["deepseek-v4-pro"])
        self.assertEqual(facts["coordinator"]["playbook"]["rules"], 3)
        self.assertEqual(facts["coordinator"]["config_keys"]["count"], 2)
        self.assertEqual(facts["coordinator"]["cli"]["commands"], ["config", "kill", "jobs"])  # read from USAGE, not the stale header comment
        self.assertEqual(facts["agent_kit"]["groups"], {"chat": ["chat", "chat/discord-order"], "inbox": ["inbox"]})
        self.assertEqual(facts["pins"]["loop_engine"]["tools"][0], {"name": "bookends-check", "version": "0.71.2", "line": 8})
        self.assertEqual(facts["loop_engine"]["members"][0], {"path": "crates/cli", "bins": ["loop-engine"]})

    def test_fetch_moves_the_page_to_the_new_main(self):
        self.world.change("agent-kit", "README.md", "# agent-kit\n\nNew words here.\n", push=False)  # committed locally, not pushed
        self.world.change("agent-kit", "extra.md", "x\n", push=True)  # pushes both; origin/main moves
        git(self.world.root / "agent-kit", "reset", "-q", "--hard", "HEAD~2")  # the clone is behind its own origin now
        git(self.world.root / "agent-kit", "update-ref", "refs/remotes/origin/main", "HEAD")
        behind, page = self.run_script()
        self.assertNotIn("New words here.", page.read_text(encoding="utf-8"))
        fresh, page = self.run_script("--fetch", out="fresh.html")
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertIn("New words here.", page.read_text(encoding="utf-8"))

    def test_every_run_appends_one_log_line(self):
        self.run_script()
        self.world.change("dotfiles", "dot_config/mise/config.toml", None)
        self.run_script()
        lines = [json.loads(line) for line in (self.state / "stack-map" / "log.jsonl").read_text().splitlines()]
        self.assertEqual([(r["action"], r["outcome"]) for r in lines], [("stack-map", "ok"), ("stack-map", "failed")])
        self.assertEqual(lines[1]["failures"], 1)
        # a failed run's record says which failure it was and what the run was asked to do, so a failed refresh can be located from the log alone
        self.assertEqual(len(lines[1]["failed"]), 1)
        self.assertRegex(lines[1]["failed"][0], r"^dotfiles:dot_config/mise/config\.toml:")
        self.assertEqual(lines[1]["args"]["fetch"], False)
        self.assertTrue(lines[1]["args"]["out"].endswith(".html"))


if __name__ == "__main__":
    unittest.main()
