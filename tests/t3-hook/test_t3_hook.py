"""dot_claude/modify_settings.json.tmpl installs the coordinator's T3 hook on both desktop profiles (personal and axon-work-computer;
<repo>/src/t3-hook/hook.ts exists at apply time) from the entries the hook prints (`hook.ts --print-settings-json`), and removes them
otherwise. A checkout that cannot print its entries keeps the ones already installed.

Renders the template with the real chezmoi for each profile against fixture coordinator checkouts: a hook that prints entries (plain,
new, prompt), an older hook that exits 1 for the flag, a hook that prints junk or another schema, and a checkout with no hook file.
Each result runs as the modify script over a settings.json that already holds a user hook, a stale t3-hook entry and other keys.
T3_HOOK_REPO=<coordinator checkout> adds a test that installs the entries that real checkout prints. No real HOME, no network.

    python3 -m unittest discover -s tests/t3-hook -v
    T3_HOOK_REPO=/path/to/coordinator python3 -m unittest discover -s tests/t3-hook -v
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
MATCHER = "^mcp__t3-code__(t3_thread_send|t3_thread_send_attachments|delegate_task|t3_thread_launch|create_threads|schedule_task)$"
ASK = "^AskUserQuestion$"
GUARD = '[ -n "$T3CODE_THREAD_ID" ] || exit 0; '
MARK = "src/t3-hook/hook.ts"
STATE = {PERSONAL: "$HOME/.local/share/coordinator", WORK: "$HOME/.local/share/coordinator-work"}

# The entries the hook prints (src/t3-hook/settings-entries.ts): the shape of each hook checkout the fixtures stand for.


def gated(event):
    return {"event": event, "matcher": MATCHER, "args": [], "failClosed": True, "t3Only": False}


ASK_ENTRY = {"event": "PreToolUse", "matcher": ASK, "args": [], "failClosed": False, "t3Only": False}
DEFAULT_START = {"event": "SessionStart", "args": [], "failClosed": True, "t3Only": True}
PROMPT_CHECK = {"event": "UserPromptSubmit", "args": [], "failClosed": False, "t3Only": True}


def rules_pages(n):
    return [{"event": "SessionStart", "args": ["--part", "rules", "--page", str(k), "--of", str(n)], "failClosed": True, "t3Only": True}
            for k in range(1, n + 1)]


def printed(entries, pages=3):
    return {"schema": 1, "rulesPages": pages, "entries": entries}


GATED3 = [gated("PreToolUse"), gated("PostToolUse"), gated("PostToolUseFailure")]
PLAIN_PRINTED = printed(GATED3 + [DEFAULT_START], pages=0)  # the oldest shape: no ask gate, no rules pages
NEW_PRINTED = printed(GATED3 + [ASK_ENTRY, DEFAULT_START] + rules_pages(3))  # 8 entries: the H1 shape
PROMPT_PRINTED = printed(NEW_PRINTED["entries"] + [PROMPT_CHECK])  # 9 entries: the H3 shape, with the per-prompt check


def printing_hook(payload):
    """A hook source that prints `payload` for --print-settings-json and does nothing else."""
    return ("if (process.argv.includes('--print-settings-json')) {\n"
            "  process.stdout.write(%s);\n  process.exit(0);\n}\n" % json.dumps(json.dumps(payload)))


OLDER_SRC = ("if (process.argv.includes('--print-settings-json')) {\n"
             "  process.stderr.write('t3-hook: unknown option --print-settings-json\\n');\n  process.exit(1);\n}\n")
JUNK_SRC = "if (process.argv.includes('--print-settings-json')) process.stdout.write('not json');\n"


def checkout(name, hook_src=None):
    """A coordinator checkout under SCRATCH. hook_src is its src/t3-hook/hook.ts, or None for no hook file."""
    repo = SCRATCH / name
    if hook_src is None:
        repo.mkdir(parents=True)
    else:
        (repo / "src/t3-hook").mkdir(parents=True)
        (repo / "src/t3-hook/hook.ts").write_text(hook_src)
    return str(repo)


PLAIN = checkout("plain", printing_hook(PLAIN_PRINTED))
NEW = checkout("new", printing_hook(NEW_PRINTED))
PROMPT = checkout("prompt", printing_hook(PROMPT_PRINTED))
OLDER = checkout("older", OLDER_SRC)
JUNK = checkout("junk", JUNK_SRC)
SCHEMA2 = checkout("schema2", printing_hook({"schema": 2, "rulesPages": 0, "entries": []}))
ODD = checkout("it's here", printing_hook(PLAIN_PRINTED))  # the path needs quoting
MISSING = checkout("nohook")


def sq(text):
    return "'" + text.replace("'", "'\\''") + "'"


def base(repo, profile):
    """The hook command without any args, the fail-closed part or the guard."""
    return 'COORDINATOR_STATE_DIR="%s" node --experimental-strip-types --disable-warning=ExperimentalWarning %s' % (
        STATE[profile], sq(repo + "/src/t3-hook/hook.ts"))


def command_for(repo, profile, entry):
    """What one printed entry installs: the hook with its args, "|| exit 2" when failClosed, the guard in front when t3Only."""
    cmd = base(repo, profile)
    if entry["args"]:
        cmd += " " + " ".join(entry["args"])
    if entry["failClosed"]:
        cmd += " || exit 2"
    return GUARD + cmd if entry["t3Only"] else cmd


def expected(repo, profile, printed_settings):
    """The (event, matcher, command) entries one install must hold, in printed order."""
    return [(e["event"], e.get("matcher"), command_for(repo, profile, e)) for e in printed_settings["entries"]]


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


def without_guard(settings):
    """The settings without the pattern-kill guard hook, which every render adds (tests/agent-kill-guard covers it)."""
    pre = [g for g in settings.get("hooks", {}).get("PreToolUse", [])
           if not any("refuse_pattern_kill.py" in h.get("command", "") for h in g.get("hooks", []))]
    if "hooks" in settings:
        if pre:
            settings["hooks"]["PreToolUse"] = pre
        else:
            settings["hooks"].pop("PreToolUse", None)
        if not settings["hooks"]:
            del settings["hooks"]
    return settings


def tearDownModule():
    shutil.rmtree(SCRATCH, ignore_errors=True)


CASES = {
    "on": {"profile": PERSONAL, "instances": {"coordinator": {"repo": PLAIN}}},  # the enabled flag is not read
    "flag_off": {"profile": PERSONAL, "instances": {"coordinator": {"enabled": False, "repo": PLAIN}}},
    "missing": {"profile": PERSONAL, "instances": {"coordinator": {"repo": MISSING}}},
    "older": {"profile": PERSONAL, "instances": {"coordinator": {"repo": OLDER}}},
    "junk": {"profile": PERSONAL, "instances": {"coordinator": {"repo": JUNK}}},
    "schema2": {"profile": PERSONAL, "instances": {"coordinator": {"repo": SCHEMA2}}},
    "new": {"profile": PERSONAL, "instances": {"coordinator": {"repo": NEW}}},
    "prompt": {"profile": PERSONAL, "instances": {"coordinator": {"repo": PROMPT}}},
    "custom": {"profile": PERSONAL, "instances": {"coordinator": {"repo": ODD}}},
    "work_on": {"profile": WORK, "instances": {"coordinator": {"enabled": True, "repo": PLAIN}}},
    "work_missing": {"profile": WORK, "instances": {"coordinator": {"repo": MISSING}}},
    "work_older": {"profile": WORK, "instances": {"coordinator": {"repo": OLDER}}},
    "work_new": {"profile": WORK, "instances": {"coordinator": {"repo": NEW}}},
    "work_prompt": {"profile": WORK, "instances": {"coordinator": {"repo": PROMPT}}},
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

    def run_modify(self, case, text):
        """The modify script's own run over settings text: the process, not parsed."""
        return subprocess.run(["sh", str(self.scripts[case])], input=text, capture_output=True, text=True, timeout=30)

    def modify(self, case, settings):
        """A run that must install or change silently: exit 0, nothing on stderr, parsed without the guard."""
        text = settings if isinstance(settings, str) else json.dumps(settings)
        r = self.run_modify(case, text)
        self.assertEqual((r.returncode, r.stderr), (0, ""), case)
        return without_guard(json.loads(r.stdout))

    def ours(self, case, text="{}"):
        return t3(self.modify(case, text))

    def assertSameEntries(self, got, want, msg=""):
        """Same entries, and the entries of each event in the same order (the printed order)."""
        self.assertEqual(sorted(got, key=repr), sorted(want, key=repr), msg)
        for event in dict.fromkeys(e for e, _, _ in want):
            self.assertEqual([x for x in got if x[0] == event], [x for x in want if x[0] == event], msg + " " + event)

    def test_plain_hook_has_exactly_the_four_entries_and_keeps_everything_else(self):
        for case, profile in (("on", PERSONAL), ("work_on", WORK)):
            s = self.modify(case, stale())
            self.assertSameEntries(t3(s), expected(PLAIN, profile, PLAIN_PRINTED), case)
            self.assertEqual((s["theme"], s["cleanupPeriodDays"]), ("dark", 365), case)
            self.assertEqual(s["hooks"]["PreToolUse"][0], USER_HOOK, case)
            self.assertEqual(s["hooks"]["Stop"], USER["hooks"]["Stop"], case)
            self.assertEqual(s["hooks"]["SessionStart"][0], USER["hooks"]["SessionStart"][0], case)
            commands = [h["command"] for g in s["hooks"]["SessionStart"] for h in g["hooks"]]
            self.assertIn("echo mixed", commands, case)  # the neighbour in the stale group survives
            self.assertNotIn("/old/", " ".join(c for _, _, c in t3(s)), case)

    def test_plain_hook_is_idempotent_and_works_from_empty(self):
        once = self.modify("on", stale())
        self.assertEqual(self.modify("on", once), once)
        for text in ("", "{}"):
            s = self.modify("on", text)
            self.assertEqual(len(t3(s)), 4)
            self.assertEqual(s["cleanupPeriodDays"], 365)
            self.assertEqual(self.modify("on", s), s)

    def test_new_hook_gets_the_ask_entry_and_three_rules_pages_on_each_profile(self):
        for case, profile in (("new", PERSONAL), ("work_new", WORK)):
            s = self.modify(case, stale())
            want = expected(NEW, profile, NEW_PRINTED)
            self.assertSameEntries(t3(s), want, case)
            self.assertEqual(len(want), 8, case)  # three gated events, ask, default SessionStart, three rules pages
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

    def test_plain_hook_gets_neither_rules_nor_ask_on_each_profile(self):
        for case, profile in (("on", PERSONAL), ("work_on", WORK)):
            self.assertSameEntries(self.ours(case), expected(PLAIN, profile, PLAIN_PRINTED), case)

    def test_no_hook_file_removes_ours_and_keeps_the_rest_on_each_profile(self):
        for case in ("missing", "work_missing", "termux"):
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
        self.assertEqual(self.modify("missing", ""), {"cleanupPeriodDays": 365, "model": "claude-opus-5-5", "promptCacheTtl": "1h", "advisorModel": "claude-fable-5-2", "modelSettings": OPUS_MEDIUM})

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

    def test_repo_override_is_used_and_quoted(self):
        s = self.modify("custom", "{}")
        self.assertEqual(len(t3(s)), 4)
        command = t3(s)[0][2]
        self.assertIn("it'\\''s here/src/t3-hook/hook.ts'", command)

    def test_session_start_does_nothing_outside_t3_and_a_missing_hook_blocks(self):
        repo = self.tmp / "repo with space"
        (repo / "src/t3-hook").mkdir(parents=True)
        (repo / "src/t3-hook/hook.ts").write_text(printing_hook(PLAIN_PRINTED))  # present at render time; removed before the commands run
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
        (repo / "src/t3-hook/hook.ts").write_text(printing_hook(NEW_PRINTED))
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

    # --- h2-c1: the entries come from the hook's printed output, for both profiles ---

    def test_print_settings_h2c1_each_profile_installs_the_printed_entries_in_order(self):
        cases = (("new", PERSONAL, NEW, NEW_PRINTED), ("work_new", WORK, NEW, NEW_PRINTED),
                 ("prompt", PERSONAL, PROMPT, PROMPT_PRINTED), ("work_prompt", WORK, PROMPT, PROMPT_PRINTED),
                 ("on", PERSONAL, PLAIN, PLAIN_PRINTED), ("work_on", WORK, PLAIN, PLAIN_PRINTED))
        for case, profile, repo, printed_settings in cases:
            s = self.modify(case, stale())
            self.assertSameEntries(t3(s), expected(repo, profile, printed_settings), case)
            self.assertEqual(self.modify(case, s), s, case)  # idempotent
            self.assertEqual(s["hooks"]["PreToolUse"][0], USER_HOOK, case)  # user hooks are kept, in place

    def test_print_settings_h2c1_commands_are_the_exact_contract_strings(self):
        s = self.modify("new", "{}")
        self.assertIn(("PreToolUse", MATCHER, "COORDINATOR_STATE_DIR=\"$HOME/.local/share/coordinator\" node --experimental-strip-types "
                       "--disable-warning=ExperimentalWarning '%s/src/t3-hook/hook.ts' || exit 2" % NEW), t3(s))
        self.assertIn(("PreToolUse", ASK, "COORDINATOR_STATE_DIR=\"$HOME/.local/share/coordinator\" node --experimental-strip-types "
                       "--disable-warning=ExperimentalWarning '%s/src/t3-hook/hook.ts'" % NEW), t3(s))
        self.assertIn(("SessionStart", None, "[ -n \"$T3CODE_THREAD_ID\" ] || exit 0; COORDINATOR_STATE_DIR=\"$HOME/.local/share/coordinator\" "
                       "node --experimental-strip-types --disable-warning=ExperimentalWarning '%s/src/t3-hook/hook.ts' || exit 2" % NEW), t3(s))
        self.assertIn(("SessionStart", None, "[ -n \"$T3CODE_THREAD_ID\" ] || exit 0; COORDINATOR_STATE_DIR=\"$HOME/.local/share/coordinator\" "
                       "node --experimental-strip-types --disable-warning=ExperimentalWarning '%s/src/t3-hook/hook.ts' --part rules --page 2 "
                       "--of 3 || exit 2" % NEW), t3(s))
        w = self.modify("work_new", "{}")
        self.assertTrue(all(c.startswith(GUARD + 'COORDINATOR_STATE_DIR="$HOME/.local/share/coordinator-work" ')
                            for e, _, c in t3(w) if e == "SessionStart"))
        self.assertTrue(all(c.startswith('COORDINATOR_STATE_DIR="$HOME/.local/share/coordinator-work" ')
                            for e, _, c in t3(w) if e != "SessionStart"))

    def test_print_settings_h2c1_prompt_check_reaches_both_profiles_without_a_template_edit(self):
        for case, profile in (("prompt", PERSONAL), ("work_prompt", WORK)):
            s = self.modify(case, "{}")
            prompt = [(e, m, c) for e, m, c in t3(s) if e == "UserPromptSubmit"]
            self.assertEqual(prompt, [("UserPromptSubmit", None, GUARD + base(PROMPT, profile))], case)
            self.assertNotIn("exit 2", prompt[0][2], case)  # a failing check must not block a prompt

    def test_print_settings_h2c1_custom_checkout_path_with_a_quote_is_quoted(self):
        s = self.modify("custom", "{}")
        self.assertSameEntries(t3(s), expected(ODD, PERSONAL, PLAIN_PRINTED), "custom")

    def test_print_settings_h2c1_work_profile_uses_its_own_state_dir_and_repo_default(self):
        # Without an instances.coordinator.repo override the work repo is $HOME/coordinator-work (docs/work-instance-handoff.md).
        def prepare(home):
            (home / "coordinator-work/src/t3-hook").mkdir(parents=True)
            (home / "coordinator-work/src/t3-hook/hook.ts").write_text(printing_hook(NEW_PRINTED))
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

    @unittest.skipUnless(os.environ.get("T3_HOOK_REPO"), "T3_HOOK_REPO names a coordinator checkout to run the real hook from")
    def test_print_settings_h2c1_real_hook_installs_the_entries_that_checkout_prints(self):
        # The coordinator checkout named by T3_HOOK_REPO, run for real: the install must hold exactly what it prints, on both profiles.
        repo = str(Path(os.environ["T3_HOOK_REPO"]).resolve())
        r = subprocess.run(["node", "--experimental-strip-types", "--disable-warning=ExperimentalWarning", repo + "/src/t3-hook/hook.ts",
                            "--print-settings-json"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        real = json.loads(r.stdout)
        self.assertEqual(real["schema"], 1)
        self.assertTrue(real["entries"])
        for profile in (PERSONAL, WORK):
            script = self.tmp / ("real-" + profile)
            script.write_text(render({"profile": profile, "instances": {"coordinator": {"repo": repo}}}))
            r = subprocess.run(["sh", str(script)], input="{}", capture_output=True, text=True, timeout=30)
            self.assertEqual((r.returncode, r.stderr), (0, ""), profile)
            s = without_guard(json.loads(r.stdout))
            self.assertSameEntries(t3(s), expected(repo, profile, real), profile)
            self.assertEqual(s["cleanupPeriodDays"], 365, profile)

    # --- h2-c2: a second apply changes no bytes; a checkout that cannot print its entries keeps them ---

    def test_print_settings_h2c2_second_apply_changes_no_bytes(self):
        for case in CASES:
            for start in ("", "{}", json.dumps(stale()), json.dumps(USER)):
                first = self.run_modify(case, start)
                self.assertEqual(first.returncode, 0, case)
                second = self.run_modify(case, first.stdout)
                self.assertEqual(second.stdout, first.stdout, case)  # identical bytes

    def test_print_settings_h2c2_older_hook_keeps_its_entries_and_says_why_once_on_stderr(self):
        for case in ("older", "work_older"):
            before = stale()
            r = self.run_modify(case, json.dumps(before))
            self.assertEqual(r.returncode, 0, r.stderr)
            after = without_guard(json.loads(r.stdout))
            self.assertEqual(t3(after), t3(before), case)  # the stale entries are still there, in place: nothing added or removed
            self.assertEqual(after["hooks"]["PreToolUse"][0], USER_HOOK, case)
            self.assertEqual(len(r.stderr.splitlines()), 1, case)
            self.assertIn("WARN", r.stderr, case)
            self.assertIn("--print-settings-json", r.stderr, case)
            r = self.run_modify(case, "{}")
            self.assertEqual((r.returncode, t3(without_guard(json.loads(r.stdout)))), (0, []), case)  # nothing added
            self.assertEqual(len(r.stderr.splitlines()), 1, case)

    def test_print_settings_h2c2_unreadable_output_counts_as_an_older_checkout(self):
        for case in ("junk", "schema2"):
            r = self.run_modify(case, json.dumps(stale()))
            self.assertEqual(r.returncode, 0, case)
            self.assertEqual(t3(without_guard(json.loads(r.stdout))), t3(stale()), case)
            self.assertEqual(len(r.stderr.splitlines()), 1, case)

    def test_print_settings_h2c2_checkout_moving_between_versions_converges(self):
        # new -> older -> prompt -> plain -> none -> new: an older checkout keeps what is there; the removal leaves nothing behind.
        for profile, prefix in ((PERSONAL, ""), (WORK, "work_")):
            original = self.modify(prefix + "missing", USER)
            s = self.modify(prefix + "new", original)
            self.assertSameEntries(t3(s), expected(NEW, profile, NEW_PRINTED), prefix + "new")
            r = self.run_modify(prefix + "older", json.dumps(s))
            self.assertEqual(r.returncode, 0, r.stderr)
            kept = without_guard(json.loads(r.stdout))
            self.assertEqual(t3(kept), t3(s), prefix + "older")
            s = self.modify(prefix + "prompt", kept)
            self.assertSameEntries(t3(s), expected(PROMPT, profile, PROMPT_PRINTED), prefix + "prompt")
            s = self.modify(prefix + "on", s)
            self.assertSameEntries(t3(s), expected(PLAIN, profile, PLAIN_PRINTED), prefix + "on")
            self.assertEqual(self.modify(prefix + "missing", s), original, prefix + "missing")
            self.assertSameEntries(t3(self.modify(prefix + "new", original)), expected(NEW, profile, NEW_PRINTED), prefix + "new")


if __name__ == "__main__":
    unittest.main()
