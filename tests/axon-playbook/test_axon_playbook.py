"""Sync wiring for the private Axon agents playbook (work profile only).

Covers, with throwaway dirs and a hook-free chezmoi config (no 1Password, no network, no real HOME):
- the git-repo external renders only on axon-work-computer with axonPlaybook.repo set, and never names a URL itself;
- apply_harness_config.sh links <repo>/skills/<skill> next to <repo>/<skill>, cleans stale links, canonical wins;
- the coordinator's model-fit skill is a chezmoi symlink into the coordinator checkout (both desktop profiles) that the linker follows;
- dot_claude/modify_settings.json.tmpl keeps exactly one SessionStart hook on work, removes only its own elsewhere;
- the instruction fragment is included into Claude, Codex and Pi on work and not on personal.

    python3 -m unittest discover -s tests/axon-playbook -v
"""
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLY = ROOT / "dot_local/user_scripts/executable_apply_harness_config.sh"
EXTERNAL = ROOT / ".chezmoiexternal.toml"
SETTINGS = ROOT / "dot_claude/modify_settings.json.tmpl"
FRAGMENT = ROOT / "dot_local/share/agent-harness/canonical/instructions/axon-playbook.md"
TARGET = ".local/share/agent-harness/external-skills/axon-agents-playbook"
REPO_URL = "https://example.invalid/someone/axon-agents-playbook.git"
WORK, PERSONAL = "axon-work-computer", "personal"
MODEL_FIT = ROOT / "dot_local/share/agent-harness/external-skills/coordinator/symlink_model-fit.tmpl"


def render(template, data):
    """Render a source template with the real chezmoi and the given data (no hooks, no override-data flag needed)."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text(json.dumps({"data": data}))
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml",
                            "execute-template"], input=Path(template).read_text(), capture_output=True, text=True,
                           timeout=120, env=dict(os.environ, HOME=tmp))
    assert r.returncode == 0, r.stderr
    return r.stdout


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class ExternalTest(unittest.TestCase):
    def test_work_with_repo_renders_the_git_repo_external(self):
        ext = tomllib.loads(render(EXTERNAL, {"profile": WORK, "axonPlaybook": {"repo": REPO_URL}}))[TARGET]
        self.assertEqual(ext["type"], "git-repo")
        self.assertEqual(ext["url"], REPO_URL)
        self.assertEqual(ext["refreshPeriod"], "24h")
        self.assertEqual(ext["pull"]["args"], ["--ff-only"])

    def test_nothing_renders_without_the_key_or_off_the_work_profile(self):
        for data in ({"profile": WORK}, {"profile": WORK, "axonPlaybook": {}}, {"profile": WORK, "axonPlaybook": {"repo": ""}},
                     {"profile": PERSONAL, "axonPlaybook": {"repo": REPO_URL}}, {"profile": PERSONAL}):
            self.assertNotIn(TARGET, tomllib.loads(render(EXTERNAL, data)), data)

    def test_the_public_source_holds_no_playbook_url(self):
        urls = [l for l in EXTERNAL.read_text().splitlines() if "http" in l and not l.lstrip().startswith("#")]
        self.assertEqual([u for u in urls if "wyeworks" not in u], [])  # the playbook url comes from chezmoi data only
        self.assertIn("{{ $axonPlaybookRepo | toJson }}", EXTERNAL.read_text())


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class ModelFitLinkTest(unittest.TestCase):
    def target(self, data):
        return render(MODEL_FIT, dict({"chezmoi": {}}, **data)).strip()

    def test_points_at_the_coordinator_checkout_on_both_desktop_profiles(self):
        self.assertEqual(self.target({"profile": PERSONAL}), "/Volumes/Workshop/macbook/git/coordinator/skills/model-fit")
        self.assertTrue(self.target({"profile": WORK}).endswith("/git/coordinator/skills/model-fit"))

    def test_the_instances_repo_value_wins_on_both_profiles(self):
        for profile in (PERSONAL, WORK):
            data = {"profile": profile, "instances": {"coordinator": {"repo": "/x/coordinator-work"}}}
            self.assertEqual(self.target(data), "/x/coordinator-work/skills/model-fit", profile)


class LinkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.home = self.tmp / "home"
        self.canon = self.tmp / "canonical"
        self.ext = self.tmp / "external"
        self.skill(self.canon / "skills/alpha")
        self.skill(self.ext / "archive-repo/gamma")  # flat layout (archive externals)
        self.skill(self.ext / "playbook/skills/beta")  # whole-repo layout
        self.skill(self.ext / "playbook/skills/alpha")  # collides with canonical
        (self.ext / "playbook/skills/not-a-skill").mkdir()  # no SKILL.md
        (self.ext / "playbook/bin").mkdir()

    @staticmethod
    def skill(path):
        path.mkdir(parents=True)
        (path / "SKILL.md").write_text("x\n")

    def link(self):
        env = {"PATH": os.environ["PATH"], "HOME": str(self.home), "AGENT_HARNESS_CANONICAL_ROOT": str(self.canon),
               "AGENT_HARNESS_EXTERNAL_ROOT": str(self.ext), "AGENT_HARNESS_GENERATED_ROOT": str(self.tmp / "gen")}
        r = subprocess.run(["sh", str(APPLY), "skills"], env=env, capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def links(self, harness=".claude/skills"):
        d = self.home / harness
        return {p.name: os.readlink(p) for p in d.iterdir() if p.is_symlink()}

    def test_a_symlinked_skill_dir_is_linked_and_a_dangling_one_is_not(self):
        checkout = self.tmp / "checkout"
        self.skill(checkout / "skills/model-fit")
        (self.ext / "coordinator").mkdir()
        (self.ext / "coordinator/model-fit").symlink_to(checkout / "skills/model-fit")
        (self.ext / "coordinator/gone").symlink_to(self.tmp / "missing")
        self.link()
        for harness in (".claude/skills", ".codex/skills", ".pi/agent/skills", ".agents/skills"):
            links = self.links(harness)
            self.assertEqual(links["model-fit"], str(self.ext / "coordinator/model-fit"), harness)
            self.assertNotIn("gone", links)
        self.assertEqual((self.home / ".claude/skills/model-fit/SKILL.md").read_text(), "x\n")

    def test_links_flat_and_skills_subdir_and_canonical_wins(self):
        self.link()
        for harness in (".claude/skills", ".codex/skills", ".pi/agent/skills", ".agents/skills"):
            self.assertEqual(self.links(harness), {
                "alpha": str(self.canon / "skills/alpha"),
                "gamma": str(self.ext / "archive-repo/gamma"),
                "beta": str(self.ext / "playbook/skills/beta"),
            }, harness)

    def test_rerun_is_stable_and_stale_links_are_removed(self):
        self.link()
        before = self.links()
        self.link()
        self.assertEqual(self.links(), before)
        shutil.rmtree(self.ext / "playbook/skills/beta")
        self.link()
        self.assertNotIn("beta", self.links())
        self.assertIn("gamma", self.links())

    def test_a_new_playbook_skill_is_linked_on_the_next_run(self):
        self.link()
        self.skill(self.ext / "playbook/skills/delta")
        self.link()
        self.assertEqual(self.links()["delta"], str(self.ext / "playbook/skills/delta"))

    def test_user_owned_skill_path_is_not_replaced(self):
        mine = self.home / ".claude/skills/beta"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("mine\n")
        self.link()
        self.assertFalse(mine.is_symlink())
        self.assertEqual((mine / "SKILL.md").read_text(), "mine\n")


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("jq"), "chezmoi and jq needed")
class SettingsHookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.scripts = {}
        for profile in (WORK, PERSONAL):
            path = cls.tmp / ("modify-" + profile)
            # No coordinator checkout here: the T3 hook is installed when <repo>/src/t3-hook/hook.ts exists (tests/t3-hook).
            path.write_text(render(SETTINGS, {"profile": profile, "instances": {"coordinator": {"repo": "/nonexistent/coordinator"}}}))
            cls.scripts[profile] = path

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_modify(self, profile, text):
        r = subprocess.run(["sh", str(self.scripts[profile])], input=text, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def ours(self, settings):
        return [h for g in settings.get("hooks", {}).get("SessionStart", []) for h in g.get("hooks", [])
                if "axon-agents-playbook/bin/playbook-context" in h.get("command", "")]

    USER = {"theme": "dark", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "x"}]}],
                                       "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo user"}]},
                                                        {"hooks": []}]}}

    def test_work_adds_exactly_one_hook_from_empty_or_blank(self):
        for text in ("", "{}"):
            s = self.run_modify(WORK, text)
            self.assertEqual(s["cleanupPeriodDays"], 365)
            self.assertEqual(len(self.ours(s)), 1)
            self.assertEqual(self.ours(s)[0]["type"], "command")

    def test_work_is_idempotent_and_keeps_user_hooks(self):
        once = self.run_modify(WORK, json.dumps(self.USER))
        twice = self.run_modify(WORK, json.dumps(once))
        self.assertEqual(once, twice)
        self.assertEqual(len(self.ours(twice)), 1)
        self.assertEqual(twice["theme"], "dark")
        self.assertEqual(twice["hooks"]["PreToolUse"], self.USER["hooks"]["PreToolUse"])
        self.assertEqual(twice["hooks"]["SessionStart"][:2], self.USER["hooks"]["SessionStart"])

    def test_work_collapses_duplicates_and_stale_entries_but_keeps_neighbours(self):
        messy = json.loads(json.dumps(self.USER))
        messy["hooks"]["SessionStart"] += [
            {"hooks": [{"type": "command", "command": "/old/axon-agents-playbook/bin/playbook-context", "timeout": 5},
                       {"type": "command", "command": "echo keepme"}]},
            {"hooks": [{"type": "command", "command": "/older/axon-agents-playbook/bin/playbook-context"}]}]
        s = self.run_modify(WORK, json.dumps(messy))
        self.assertEqual(len(self.ours(s)), 1)
        commands = [h["command"] for g in s["hooks"]["SessionStart"] for h in g["hooks"]]
        self.assertIn("echo user", commands)
        self.assertIn("echo keepme", commands)

    def test_other_profiles_remove_only_our_entry(self):
        with_ours = self.run_modify(WORK, json.dumps(self.USER))
        s = self.run_modify(PERSONAL, json.dumps(with_ours))
        self.assertEqual(self.ours(s), [])
        self.assertEqual(s["hooks"], self.USER["hooks"])

    def test_other_profiles_prune_keys_they_emptied_and_touch_nothing_else(self):
        s = self.run_modify(PERSONAL, json.dumps(self.run_modify(WORK, '{"a": 1}')))
        owned = {"cleanupPeriodDays": 365, "model": "claude-opus-5-5", "modelSettings": {"claude-opus-5-5": {"effortLevel": "medium"}}}  # keys the script sets on every apply
        self.assertEqual(s, {"a": 1, **owned})
        untouched = {"hooks": {"Stop": []}, **owned}
        self.assertEqual(self.run_modify(PERSONAL, json.dumps(untouched)), untouched)

    def test_non_object_input_fails(self):
        r = subprocess.run(["sh", str(self.scripts[WORK])], input="[1]", capture_output=True, text=True, timeout=30)
        self.assertNotEqual(r.returncode, 0)

    def test_hook_command_is_silent_without_the_clone_and_prints_with_it(self):
        command = self.ours(self.run_modify(WORK, ""))[0]["command"]
        home = self.tmp / "hookhome"
        home.mkdir(exist_ok=True)
        r = subprocess.run(["sh", "-c", command], env={"PATH": os.environ["PATH"], "HOME": str(home)},
                           capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        script = home / TARGET / "bin/playbook-context"
        script.parent.mkdir(parents=True)
        script.write_text("#!/bin/sh\necho CONTEXT\n")
        r = subprocess.run(["sh", "-c", command], env={"PATH": os.environ["PATH"], "HOME": str(home)},
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")  # not executable yet
        script.chmod(0o755)
        r = subprocess.run(["sh", "-c", command], env={"PATH": os.environ["PATH"], "HOME": str(home)},
                           capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stdout), (0, "CONTEXT\n"))


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class FragmentTest(unittest.TestCase):
    TEMPLATES = ("dot_claude/CLAUDE.md.tmpl", "dot_codex/modify_AGENTS.md.tmpl", "dot_pi/private_agent/literal_AGENTS.md.tmpl")

    def test_fragment_is_includable_and_plain(self):
        text = FRAGMENT.read_text()
        self.assertTrue(text.startswith("## "))
        self.assertNotIn("\n# ", "\n" + text)
        self.assertIn("axon-pr-preflight", text)
        self.assertIn("playbook-context", text)

    def test_included_on_work_only(self):
        body = FRAGMENT.read_text().strip()
        for t in self.TEMPLATES:
            self.assertIn(body, render(ROOT / t, {"profile": WORK}), t)
            self.assertNotIn("Axon playbook", render(ROOT / t, {"profile": PERSONAL}), t)

    def test_codex_fragment_sits_inside_the_managed_block(self):
        out = render(ROOT / self.TEMPLATES[1], {"profile": WORK})
        self.assertLess(out.index("## Axon playbook"), out.index("chezmoi:mcp-memory-guidance:end"))


if __name__ == "__main__":
    unittest.main()
