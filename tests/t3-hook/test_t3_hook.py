"""dot_claude/modify_settings.json.tmpl installs the coordinator's T3 hook (personal profile, <repo>/src/t3-hook/hook.ts exists at apply time) and removes it otherwise.

Renders the template with the real chezmoi for three cases and runs each result as the modify script over a settings.json that
already holds a user hook, a stale t3-hook entry and other keys. No real HOME, no network.

    python3 -m unittest discover -s tests/t3-hook -v
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "dot_claude/modify_settings.json.tmpl"
WORK, PERSONAL = "axon-work-computer", "personal"
SCRATCH = Path(tempfile.mkdtemp())
REPO = str(SCRATCH / "coord")  # holds src/t3-hook/hook.ts
MISSING = str(SCRATCH / "nohook")  # exists, but has no hook file
ODD = str(SCRATCH / "it's here")  # holds the hook file; path needs quoting
RULES = str(SCRATCH / "rules")  # hook source supports --part, so the second SessionStart entry is installed
for _d in (REPO, ODD):
    os.makedirs(_d + "/src/t3-hook")
    Path(_d + "/src/t3-hook/hook.ts").write_text("")
os.makedirs(RULES + "/src/t3-hook")
Path(RULES + "/src/t3-hook/hook.ts").write_text("// supports --part rules\n")
os.makedirs(MISSING)
MATCHER = "^mcp__t3-code__(t3_thread_send|t3_thread_send_attachments|delegate_task|t3_thread_launch|create_threads|schedule_task)$"
RUN = ('COORDINATOR_STATE_DIR="$HOME/.local/share/coordinator" node --experimental-strip-types '
       "'%s/src/t3-hook/hook.ts' || exit 2")
MARK = "src/t3-hook/hook.ts"
CASES = {
    "on": {"profile": PERSONAL, "instances": {"coordinator": {"repo": REPO}}},  # the enabled flag is not read
    "flag_off": {"profile": PERSONAL, "instances": {"coordinator": {"enabled": False, "repo": REPO}}},
    "missing": {"profile": PERSONAL, "instances": {"coordinator": {"repo": MISSING}}},
    "work": {"profile": WORK, "instances": {"coordinator": {"enabled": True, "repo": REPO}}},
    "rules": {"profile": PERSONAL, "instances": {"coordinator": {"repo": RULES}}},
    "rules_work": {"profile": WORK, "instances": {"coordinator": {"enabled": True, "repo": RULES}}},
    "custom": {"profile": PERSONAL, "instances": {"coordinator": {"repo": ODD}}},
}
OPUS_MEDIUM = {"claude-opus-5-5": {"effortLevel": "medium"}}
USER_HOOK = {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo user"}]}
USER = {
    "theme": "dark",
    "hooks": {
        "PreToolUse": [USER_HOOK],
        "SessionStart": [{"hooks": [{"type": "command", "command": "echo start"}]}],
        "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
    },
}


def stale():
    s = json.loads(json.dumps(USER))
    s["hooks"]["PreToolUse"].append({"matcher": "old", "hooks": [{"type": "command", "command": "node /old/src/t3-hook/hook.ts"}]})
    s["hooks"]["PostToolUse"] = [{"matcher": "old", "hooks": [{"type": "command", "command": "node /old/src/t3-hook/hook.ts"}]}]
    s["hooks"]["SessionStart"].append({"hooks": [{"type": "command", "command": "node /old/src/t3-hook/hook.ts"},
                                                 {"type": "command", "command": "echo mixed"}]})
    return s


def render(data):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text(json.dumps({"data": dict(data, hub={"enabled": False})}))  # the hub keys are tests/hub-claude's
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                           input=SETTINGS.read_text(), capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=tmp))
    assert r.returncode == 0, r.stderr
    return r.stdout


def t3(settings):
    return [(event, g.get("matcher"), h["command"]) for event, groups in settings.get("hooks", {}).items()
            for g in groups for h in g.get("hooks", []) if MARK in h.get("command", "")]


def tearDownModule():
    shutil.rmtree(SCRATCH, ignore_errors=True)


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("jq"), "chezmoi and jq needed")
class T3HookSettingsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.scripts = {}
        for name, data in CASES.items():
            cls.scripts[name] = cls.tmp / ("modify-" + name)
            cls.scripts[name].write_text(render(data))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def modify(self, case, settings):
        text = settings if isinstance(settings, str) else json.dumps(settings)
        r = subprocess.run(["sh", str(self.scripts[case])], input=text, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_on_has_exactly_the_four_entries_and_keeps_everything_else(self):
        s = self.modify("on", stale())
        run = RUN % REPO
        self.assertEqual(sorted(t3(s)), sorted([
            ("PreToolUse", MATCHER, run), ("PostToolUse", MATCHER, run), ("PostToolUseFailure", MATCHER, run),
            ("SessionStart", None, '[ -n "$T3CODE_THREAD_ID" ] || exit 0; ' + run)]))
        self.assertEqual((s["theme"], s["cleanupPeriodDays"]), ("dark", 365))
        self.assertEqual(s["hooks"]["PreToolUse"][0], USER_HOOK)
        self.assertEqual(s["hooks"]["Stop"], USER["hooks"]["Stop"])
        self.assertEqual(s["hooks"]["SessionStart"][0], USER["hooks"]["SessionStart"][0])
        commands = [h["command"] for g in s["hooks"]["SessionStart"] for h in g["hooks"]]
        self.assertIn("echo mixed", commands)  # the neighbour in the stale group survives
        self.assertNotIn("/old/", " ".join(c for _, _, c in t3(s)))

    def test_on_is_idempotent_and_works_from_empty(self):
        once = self.modify("on", stale())
        self.assertEqual(self.modify("on", once), once)
        for text in ("", "{}"):
            s = self.modify("on", text)
            self.assertEqual(len(t3(s)), 4)
            self.assertEqual(s["cleanupPeriodDays"], 365)
            self.assertEqual(self.modify("on", s), s)

    def test_missing_file_and_work_remove_ours_and_keep_the_rest(self):
        for case in ("missing", "work"):
            s = self.modify(case, stale())
            self.assertEqual(t3(s), [], case)
            self.assertEqual(s["hooks"]["PreToolUse"], [USER_HOOK], case)
            self.assertEqual(s["hooks"]["Stop"], USER["hooks"]["Stop"], case)
            self.assertNotIn("PostToolUse", s["hooks"], case)  # emptied by us, so pruned
            self.assertIn("echo mixed", [h["command"] for g in s["hooks"]["SessionStart"] for h in g["hooks"]], case)
            self.assertEqual(self.modify(case, s)["hooks"], s["hooks"], case)

    def test_file_gone_after_on_restores_the_original(self):
        original = self.modify("missing", USER)
        self.assertEqual(self.modify("missing", self.modify("on", original)), original)
        self.assertEqual(self.modify("missing", ""), {"cleanupPeriodDays": 365, "model": "claude-opus-5-5", "modelSettings": OPUS_MEDIUM})

    def test_default_model_is_opus_at_medium_on_both_profiles_and_a_saved_level_is_kept(self):
        # Claude Code ignores a top-level effortLevel for Opus 5.5; the level it reads lives under modelSettings.
        for case in ("on", "work"):
            s = self.modify(case, {"model": "sonnet", "modelSettings": {"claude-sonnet-5-5": {"effortLevel": "high"}}})
            self.assertEqual(s["model"], "claude-opus-5-5", case)
            self.assertEqual(s["modelSettings"]["claude-opus-5-5"], {"effortLevel": "medium"}, case)
            self.assertEqual(s["modelSettings"]["claude-sonnet-5-5"], {"effortLevel": "high"}, case)  # other models untouched
            self.assertNotIn("effortLevel", s, case)
            saved = {"modelSettings": {"claude-opus-5-5": {"effortLevel": "high"}}}
            self.assertEqual(self.modify(case, saved)["modelSettings"], saved["modelSettings"], case)  # a later pick wins

    def test_flag_is_not_read(self):
        self.assertEqual(len(t3(self.modify("flag_off", "{}"))), 4)

    def test_work_profile_never_gets_the_hook_even_with_the_file(self):
        self.assertEqual(t3(self.modify("work", "{}")), [])

    def test_repo_override_is_used_and_quoted(self):
        s = self.modify("custom", "{}")
        self.assertEqual(len(t3(s)), 4)
        command = t3(s)[0][2]
        self.assertIn("it'\\''s here/src/t3-hook/hook.ts'", command)

    def test_session_start_does_nothing_outside_t3_and_a_missing_hook_blocks(self):
        repo = self.tmp / "repo with space"
        (repo / "src/t3-hook").mkdir(parents=True)
        (repo / "src/t3-hook/hook.ts").write_text("")  # present at render time; removed before the commands run
        script = self.tmp / "modify-run"
        script.write_text(render({"profile": PERSONAL, "instances": {"coordinator": {"repo": str(repo)}}}))
        s = json.loads(subprocess.run(["sh", str(script)], input="{}", capture_output=True, text=True, timeout=30).stdout)
        entries = {e: c for e, _, c in t3(s)}
        (repo / "src/t3-hook/hook.ts").unlink()
        env = {"PATH": os.environ["PATH"], "HOME": str(self.tmp)}
        r = subprocess.run(["sh", "-c", entries["SessionStart"]], env=env, capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        r = subprocess.run(["sh", "-c", entries["PreToolUse"]], env=env, capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2)  # hook.ts is gone, so node fails and the call is blocked
        r = subprocess.run(["sh", "-c", entries["SessionStart"]], env=dict(env, T3CODE_THREAD_ID="t"), capture_output=True,
                           text=True, timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2)

    def test_rules_entry_only_when_the_hook_supports_part(self):
        run = RUN % RULES
        guard = '[ -n "$T3CODE_THREAD_ID" ] || exit 0; '
        rules = guard + run.replace(" || exit 2", " --part rules || exit 2")
        s = self.modify("rules", stale())
        self.assertEqual(sorted(t3(s)), sorted([
            ("PreToolUse", MATCHER, run), ("PostToolUse", MATCHER, run), ("PostToolUseFailure", MATCHER, run),
            ("SessionStart", None, guard + run), ("SessionStart", None, rules)]))
        groups = [g for g in s["hooks"]["SessionStart"] if any(MARK in h["command"] for h in g["hooks"])]
        self.assertEqual([len(g["hooks"]) for g in groups], [1, 1])  # its own group, so its own context budget
        self.assertIn("echo mixed", [h["command"] for g in s["hooks"]["SessionStart"] for h in g["hooks"]])
        self.assertEqual(s["hooks"]["SessionStart"][0], USER["hooks"]["SessionStart"][0])
        self.assertEqual(s["hooks"]["PreToolUse"][0], USER_HOOK)
        self.assertEqual(self.modify("rules", s), s)  # idempotent
        # a plain hook (no --part) gets exactly one SessionStart entry, and re-applying with --part adds the second
        plain = self.modify("on", "{}")
        self.assertEqual(len([x for x in t3(plain) if x[0] == "SessionStart"]), 1)
        both = self.modify("rules", plain)
        self.assertEqual(len([x for x in t3(both) if x[0] == "SessionStart"]), 2)
        # and falling back to a hook without --part drops the second entry again
        self.assertEqual(self.modify("on", both), plain)
        self.assertEqual(t3(self.modify("rules_work", both)), [])

    def test_rules_command_is_silent_outside_t3_and_blocks_when_the_hook_is_missing(self):
        repo = self.tmp / "rules repo"
        (repo / "src/t3-hook").mkdir(parents=True)
        (repo / "src/t3-hook/hook.ts").write_text("--part")
        script = self.tmp / "modify-rules-run"
        script.write_text(render({"profile": PERSONAL, "instances": {"coordinator": {"repo": str(repo)}}}))
        s = json.loads(subprocess.run(["sh", str(script)], input="{}", capture_output=True, text=True, timeout=30).stdout)
        command = [c for e, _, c in t3(s) if e == "SessionStart" and "--part rules" in c][0]
        (repo / "src/t3-hook/hook.ts").unlink()
        env = {"PATH": os.environ["PATH"], "HOME": str(self.tmp)}
        r = subprocess.run(["sh", "-c", command], env=env, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        r = subprocess.run(["sh", "-c", command], env=dict(env, T3CODE_THREAD_ID="t"), capture_output=True, text=True,
                           timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
