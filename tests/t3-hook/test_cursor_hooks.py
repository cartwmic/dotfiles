"""dot_cursor/modify_hooks.json.tmpl installs the coordinator's Cursor T3 hooks on both desktop profiles
from `src/t3-hook/hook.ts --print-cursor-hooks-json`, keeping unrelated hooks and older checkouts intact.

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
HOOKS_TMPL = ROOT / "dot_cursor/modify_hooks.json.tmpl"
WORK, PERSONAL = "axon-work-computer", "personal"
STATE = {PERSONAL: "$HOME/.local/share/coordinator", WORK: "$HOME/.local/share/coordinator-work"}
SCRATCH = Path(tempfile.mkdtemp())


def printing_hook(payload):
    return ("if (process.argv.includes('--print-cursor-hooks-json')) {\n"
            "  process.stdout.write(%s);\n  process.exit(0);\n}\n" % json.dumps(json.dumps(payload)))


OLDER_SRC = "process.exit(1);\n"

PRINTED = {
    "schema": 1,
    "rulesPages": 3,
    "reseatPages": 3,
    "entries": [
        {"event": "preToolUse", "matcher": "^(MCP:(t3_thread_send)|CallDynamicTool)$", "args": ["--cursor"], "failClosed": True, "target": "hook"},
        {"event": "sessionStart", "args": ["--cursor"], "failClosed": True, "target": "hook"},
        {"event": "sessionStart", "args": ["--cursor"], "failClosed": False, "target": "coordinator"},
        {"event": "beforeSubmitPrompt", "args": ["--cursor"], "failClosed": True, "target": "coordinator"},
        {"event": "stop", "args": ["--cursor"], "failClosed": False, "target": "coordinator"},
    ],
}


def checkout(name, src):
    repo = SCRATCH / name
    (repo / "src/t3-hook").mkdir(parents=True)
    (repo / "src/t3-hook/hook.ts").write_text(src)
    return str(repo)


NEW = checkout("new", printing_hook(PRINTED))
OLDER = checkout("older", OLDER_SRC)
MISSING = str(SCRATCH / "missing")


def render(data):
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "chezmoi.yaml"
        cfg.write_text(json.dumps({"data": dict(data, hub={"enabled": False})}))
        r = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
            input=HOOKS_TMPL.read_text(),
            capture_output=True,
            text=True,
            timeout=120,
            env=dict(os.environ, HOME=tmp),
        )
    assert r.returncode == 0, r.stderr
    return r.stdout


def tearDownModule():
    shutil.rmtree(SCRATCH, ignore_errors=True)


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("jq"), "chezmoi and jq needed")
class CursorHooksModifyTest(unittest.TestCase):
    def test_installs_printed_cursor_hooks_on_both_profiles_and_preserves_user_hooks(self):
        user = {"version": 1, "hooks": {"beforeSubmitPrompt": [{"command": "echo user"}], "preToolUse": [{"command": "node /old/src/t3-hook/hook.ts"}]}}
        for profile in (PERSONAL, WORK):
            script = render({"profile": profile, "instances": {"coordinator": {"repo": NEW}}})
            r = subprocess.run(["sh", "-c", script], input=json.dumps(user), capture_output=True, text=True, timeout=30)
            self.assertEqual((r.returncode, r.stderr), (0, ""), profile)
            out = json.loads(r.stdout)
            self.assertEqual(out["version"], 1)
            self.assertEqual(out["hooks"]["beforeSubmitPrompt"][0], {"command": "echo user"})
            cmds = [h["command"] for arr in out["hooks"].values() for h in arr]
            self.assertFalse(any("/old/" in c for c in cmds))
            self.assertTrue(any("src/t3-hook/hook.ts" in c and STATE[profile] in c for c in cmds))
            self.assertTrue(any("src/t3-coordinator/hook.ts" in c and STATE[profile] in c for c in cmds))
            # Idempotent on second apply
            r2 = subprocess.run(["sh", "-c", script], input=r.stdout, capture_output=True, text=True, timeout=30)
            self.assertEqual(r2.stdout, r.stdout)

    def test_older_checkout_keeps_existing_and_warns_once(self):
        existing = {"version": 1, "hooks": {"sessionStart": [{"command": "echo keep"}]}}
        script = render({"profile": WORK, "instances": {"coordinator": {"repo": OLDER}}})
        r = subprocess.run(["sh", "-c", script], input=json.dumps(existing), capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)
        self.assertIn("WARN", r.stderr)
        self.assertEqual(json.loads(r.stdout), existing)

    def test_missing_or_removed_cleans_only_ours(self):
        existing = {"version": 1, "hooks": {"beforeSubmitPrompt": [{"command": "echo user"}, {"command": "node /x/src/t3-coordinator/hook.ts --cursor"}]}}
        script = render({"profile": PERSONAL, "instances": {"coordinator": {"repo": MISSING}}})
        r = subprocess.run(["sh", "-c", script], input=json.dumps(existing), capture_output=True, text=True, timeout=30)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(json.loads(r.stdout), {"version": 1, "hooks": {"beforeSubmitPrompt": [{"command": "echo user"}]}})


if __name__ == "__main__":
    unittest.main()
