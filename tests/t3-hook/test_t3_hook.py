"""dot_claude/modify_settings.json.tmpl installs the coordinator's T3 hook on both desktop profiles (personal and axon-work-computer;
<repo>/src/t3-hook/hook.ts exists at apply time) and removes it otherwise.

Renders the template with the real chezmoi for each profile against fixture hook sources (new: pages and the ask gate; older: --part
only; plain: neither; none: no hook file) and runs each result as the modify script over a settings.json that already holds a user
hook, a stale t3-hook entry and other keys. No real HOME, no network.

    python3 -m unittest discover -s tests/t3-hook -v
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = ROOT / "dot_claude/modify_settings.json.tmpl"
WORK, PERSONAL = "axon-work-computer", "personal"
SCRATCH = Path(tempfile.mkdtemp())
PLAIN = str(SCRATCH / "coord")  # holds src/t3-hook/hook.ts with neither --part nor ask-gate (the oldest hook)
MISSING = str(SCRATCH / "nohook")  # exists, but has no hook file
ODD = str(SCRATCH / "it's here")  # holds the hook file; path needs quoting
OLDER = str(SCRATCH / "older")  # hook source supports --part only: one bare rules entry
NEW = str(SCRATCH / "new")  # hook source supports --page/--of and the ask gate (coordinator 4cd7bb3)
for _d in (PLAIN, ODD):
    os.makedirs(_d + "/src/t3-hook")
    Path(_d + "/src/t3-hook/hook.ts").write_text("")
os.makedirs(OLDER + "/src/t3-hook")
Path(OLDER + "/src/t3-hook/hook.ts").write_text("// supports --part rules\n")
os.makedirs(NEW + "/src/t3-hook")
Path(NEW + "/src/t3-hook/hook.ts").write_text(
    "import { ASK_TOOL } from './ask-gate.ts';\nconst USAGE = 'usage: hook.ts [--part default | --part rules [--page N --of M]]';\n")
os.makedirs(MISSING)
MATCHER = "^mcp__t3-code__(t3_thread_send|t3_thread_send_attachments|delegate_task|t3_thread_launch|create_threads|schedule_task)$"
ASK = "^AskUserQuestion$"
GUARD = '[ -n "$T3CODE_THREAD_ID" ] || exit 0; '
MARK = "src/t3-hook/hook.ts"
STATE = {"personal": "$HOME/.local/share/coordinator", "work": "$HOME/.local/share/coordinator-work"}


def base(repo, profile):
    """The hook command without its `|| exit 2`."""
    return 'COORDINATOR_STATE_DIR="%s" node --experimental-strip-types --disable-warning=ExperimentalWarning \'%s/src/t3-hook/hook.ts\'' % (STATE[profile], repo)


def expected(repo, profile, ask=False, rules=None):
    """The exact t3-hook entries one render must install. rules: None (no rules entry), 0 (bare --part rules) or N pages."""
    b = base(repo, profile)
    run = b + " || exit 2"
    out = [("PreToolUse", MATCHER, run), ("PostToolUse", MATCHER, run), ("PostToolUseFailure", MATCHER, run)]
    if ask:
        out.append(("PreToolUse", ASK, b))  # no || exit 2: a hook that cannot load must not block the question tool
    out.append(("SessionStart", None, GUARD + run))
    if rules == 0:
        out.append(("SessionStart", None, GUARD + b + " --part rules || exit 2"))
    elif rules:
        out += [("SessionStart", None, GUARD + b + " --part rules --page %d --of %d || exit 2" % (n, rules)) for n in range(1, rules + 1)]
    return out


CASES = {
    "on": {"profile": PERSONAL, "instances": {"coordinator": {"repo": PLAIN}}},  # the enabled flag is not read
    "flag_off": {"profile": PERSONAL, "instances": {"coordinator": {"enabled": False, "repo": PLAIN}}},
    "missing": {"profile": PERSONAL, "instances": {"coordinator": {"repo": MISSING}}},
    "older": {"profile": PERSONAL, "instances": {"coordinator": {"repo": OLDER}}},
    "new": {"profile": PERSONAL, "instances": {"coordinator": {"repo": NEW}}},
    "custom": {"profile": PERSONAL, "instances": {"coordinator": {"repo": ODD}}},
    "work_on": {"profile": WORK, "instances": {"coordinator": {"enabled": True, "repo": PLAIN}}},
    "work_missing": {"profile": WORK, "instances": {"coordinator": {"repo": MISSING}}},
    "work_older": {"profile": WORK, "instances": {"coordinator": {"repo": OLDER}}},
    "work_new": {"profile": WORK, "instances": {"coordinator": {"repo": NEW}}},
    "termux": {"profile": "termux", "instances": {"coordinator": {"repo": NEW}}},
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


def render(data, prepare=None):
    with tempfile.TemporaryDirectory() as tmp:
        if prepare:
            prepare(Path(tmp))
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

    def ours(self, case, text="{}"):
        return t3(self.modify(case, text))

    def test_plain_hook_has_exactly_the_four_entries_and_keeps_everything_else(self):
        s = self.modify("on", stale())
        self.assertEqual(sorted(t3(s)), sorted(expected(PLAIN, "personal")))
        self.assertEqual((s["theme"], s["cleanupPeriodDays"]), ("dark", 365))
        self.assertEqual(s["hooks"]["PreToolUse"][0], USER_HOOK)
        self.assertEqual(s["hooks"]["Stop"], USER["hooks"]["Stop"])
        self.assertEqual(s["hooks"]["SessionStart"][0], USER["hooks"]["SessionStart"][0])
        commands = [h["command"] for g in s["hooks"]["SessionStart"] for h in g["hooks"]]
        self.assertIn("echo mixed", commands)  # the neighbour in the stale group survives
        self.assertNotIn("/old/", " ".join(c for _, _, c in t3(s)))

    def test_plain_hook_is_idempotent_and_works_from_empty(self):
        once = self.modify("on", stale())
        self.assertEqual(self.modify("on", once), once)
        for text in ("", "{}"):
            s = self.modify("on", text)
            self.assertEqual(len(t3(s)), 4)
            self.assertEqual(s["cleanupPeriodDays"], 365)
            self.assertEqual(self.modify("on", s), s)

    def test_new_hook_gets_the_ask_entry_and_three_rules_pages_on_each_profile(self):
        # The entries the coordinator README's Settings snippet shows (4cd7bb3), per profile: its own repo and state dir.
        for case, profile in (("new", "personal"), ("work_new", "work")):
            s = self.modify(case, stale())
            want = expected(NEW, profile, ask=True, rules=3)
            self.assertEqual(sorted(t3(s)), sorted(want), case)
            self.assertEqual(len(want), 8, case)  # three gated events, ask, default SessionStart, three rules pages
            for event in ("PreToolUse", "SessionStart"):  # order matters: gated before ask, default before pages 1, 2, 3
                self.assertEqual([x for x in t3(s) if x[0] == event], [x for x in want if x[0] == event], case)
            ask = [x for x in t3(s) if x[1] == ASK]
            self.assertEqual(len(ask), 1, case)
            self.assertNotIn("exit 2", ask[0][2], case)
            self.assertNotIn("T3CODE_THREAD_ID", ask[0][2], case)  # the hook itself allows a non-T3 session
            self.assertTrue(all(c.endswith("|| exit 2") for e, m, c in t3(s) if m != ASK), case)
            self.assertTrue(all(c.startswith(GUARD) for e, m, c in t3(s) if e == "SessionStart"), case)
            groups = [g for g in s["hooks"]["SessionStart"] if any(MARK in h["command"] for h in g["hooks"])]
            self.assertEqual([len(g["hooks"]) for g in groups], [1, 1, 1, 1], case)  # each its own group, so its own budget
            self.assertEqual(s["hooks"]["PreToolUse"][0], USER_HOOK, case)
            self.assertEqual(s["hooks"]["Stop"], USER["hooks"]["Stop"], case)
            self.assertIn("echo mixed", [h["command"] for g in s["hooks"]["SessionStart"] for h in g["hooks"]], case)
            self.assertEqual(self.modify(case, s), s, case)  # idempotent

    def test_older_hook_gets_one_bare_rules_entry_and_no_ask_entry_on_each_profile(self):
        for case, profile in (("older", "personal"), ("work_older", "work")):
            s = self.modify(case, stale())
            self.assertEqual(sorted(t3(s)), sorted(expected(OLDER, profile, rules=0)), case)
            self.assertNotIn("--page", " ".join(c for _, _, c in t3(s)), case)
            self.assertEqual([x[1] for x in t3(s) if x[1] == ASK], [], case)
            self.assertEqual(self.modify(case, s), s, case)

    def test_plain_hook_gets_neither_rules_nor_ask_on_each_profile(self):
        for case, profile in (("on", "personal"), ("work_on", "work")):
            self.assertEqual(sorted(self.ours(case)), sorted(expected(PLAIN, profile)), case)

    def test_no_hook_file_removes_ours_and_keeps_the_rest_on_each_profile(self):
        for case in ("missing", "work_missing", "termux"):
            s = self.modify(case, stale())
            self.assertEqual(t3(s), [], case)
            self.assertEqual(s["hooks"]["PreToolUse"], [USER_HOOK], case)
            self.assertEqual(s["hooks"]["Stop"], USER["hooks"]["Stop"], case)
            self.assertNotIn("PostToolUse", s["hooks"], case)  # emptied by us, so pruned
            self.assertIn("echo mixed", [h["command"] for g in s["hooks"]["SessionStart"] for h in g["hooks"]], case)
            self.assertEqual(self.modify(case, s)["hooks"], s["hooks"], case)

    def test_a_checkout_moving_between_versions_converges_on_each_profile(self):
        # new -> older -> plain -> none -> new: the stripped entries leave nothing behind and the user's hooks never move.
        for new, older, plain, none, profile in (("new", "older", "on", "missing", "personal"),
                                                 ("work_new", "work_older", "work_on", "work_missing", "work")):
            original = self.modify(none, USER)
            s = self.modify(new, original)
            self.assertEqual(len(t3(s)), 8, new)
            s = self.modify(older, s)
            self.assertEqual(sorted(t3(s)), sorted(expected(OLDER, profile, rules=0)), older)
            s = self.modify(plain, s)
            self.assertEqual(sorted(t3(s)), sorted(expected(PLAIN, profile)), plain)
            self.assertEqual(self.modify(none, s), original, none)
            self.assertEqual(sorted(t3(self.modify(new, original))), sorted(expected(NEW, profile, ask=True, rules=3)), new)

    def test_file_gone_after_on_restores_the_original(self):
        original = self.modify("missing", USER)
        self.assertEqual(self.modify("missing", self.modify("on", original)), original)
        self.assertEqual(self.modify("missing", ""), {"cleanupPeriodDays": 365, "model": "claude-opus-5-5", "promptCacheTtl": "1h", "modelSettings": OPUS_MEDIUM})

    def test_default_model_is_opus_at_medium_on_both_profiles_and_a_saved_level_is_kept(self):
        # Claude Code ignores a top-level effortLevel for Opus 5.5; the level it reads lives under modelSettings.
        for case in ("on", "work_on"):
            s = self.modify(case, {"model": "sonnet", "modelSettings": {"claude-sonnet-5-5": {"effortLevel": "high"}}})
            self.assertEqual(s["model"], "claude-opus-5-5", case)
            self.assertEqual(s["modelSettings"]["claude-opus-5-5"], {"effortLevel": "medium"}, case)
            self.assertEqual(s["modelSettings"]["claude-sonnet-5-5"], {"effortLevel": "high"}, case)  # other models untouched
            self.assertNotIn("effortLevel", s, case)
            saved = {"modelSettings": {"claude-opus-5-5": {"effortLevel": "high"}}}
            self.assertEqual(self.modify(case, saved)["modelSettings"], saved["modelSettings"], case)  # a later pick wins

    def test_flag_is_not_read(self):
        self.assertEqual(len(self.ours("flag_off")), 4)

    def test_work_profile_uses_its_own_state_dir_and_repo_default(self):
        # Without an instances.coordinator.repo override the work repo is $HOME/coordinator-work (docs/work-instance-handoff.md).
        def prepare(home):
            (home / "coordinator-work/src/t3-hook").mkdir(parents=True)
            (home / "coordinator-work/src/t3-hook/hook.ts").write_text("./ask-gate.ts --of")
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "modify"
            script.write_text(render({"profile": WORK}, prepare))
            s = json.loads(subprocess.run(["sh", str(script)], input="{}", capture_output=True, text=True, timeout=30).stdout)
        commands = [c for _, _, c in t3(s)]
        self.assertEqual(len(commands), 8)
        self.assertTrue(all('COORDINATOR_STATE_DIR="$HOME/.local/share/coordinator-work"' in c for c in commands))
        self.assertTrue(all("/coordinator-work/src/t3-hook/hook.ts'" in c for c in commands))
        # The hook and the work unit take the checkout from the same instance_repo default.
        repo = re.search(r"'(/[^']*)/src/t3-hook/hook.ts'", commands[0]).group(1)
        home = repo[: -len("/coordinator-work")]
        cfg = SCRATCH / "unit.yaml"
        cfg.write_text(json.dumps({"data": {"profile": WORK}}))
        unit = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                              input=(ROOT / "dot_local/share/instances/launchd/local.coordinatord.work.plist.tmpl").read_text(),
                              capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=home)).stdout
        self.assertIn("<key>WorkingDirectory</key><string>%s</string>" % repo, unit)
        # Personal and work never share a state dir.
        for c in (c for _, _, c in t3(self.modify("new", "{}"))):
            self.assertIn('COORDINATOR_STATE_DIR="$HOME/.local/share/coordinator"', c)
            self.assertNotIn("coordinator-work", c)

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

    def test_rules_and_ask_commands_when_the_hook_is_missing(self):
        repo = self.tmp / "rules repo"
        (repo / "src/t3-hook").mkdir(parents=True)
        (repo / "src/t3-hook/hook.ts").write_text("--of ./ask-gate.ts")
        script = self.tmp / "modify-rules-run"
        script.write_text(render({"profile": PERSONAL, "instances": {"coordinator": {"repo": str(repo)}}}))
        s = json.loads(subprocess.run(["sh", str(script)], input="{}", capture_output=True, text=True, timeout=30).stdout)
        rules = [c for e, _, c in t3(s) if e == "SessionStart" and "--part rules" in c][0]
        ask = [c for e, m, c in t3(s) if m == ASK][0]
        (repo / "src/t3-hook/hook.ts").unlink()
        env = {"PATH": os.environ["PATH"], "HOME": str(self.tmp)}
        r = subprocess.run(["sh", "-c", rules], env=env, capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        r = subprocess.run(["sh", "-c", rules], env=dict(env, T3CODE_THREAD_ID="t"), capture_output=True, text=True,
                           timeout=30, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2)
        r = subprocess.run(["sh", "-c", ask], env=dict(env, T3CODE_THREAD_ID="t"), capture_output=True, text=True,
                           timeout=30, stdin=subprocess.DEVNULL)
        self.assertNotEqual(r.returncode, 2)  # the ask entry never blocks: a missing hook lets the question tool run


if __name__ == "__main__":
    unittest.main()
