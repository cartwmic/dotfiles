"""Where the lead's turn-end Stop hook is registered, and which sessions the script skips.

- dot_claude/modify_settings.json.tmpl installs one Stop group running hooks/lead_turn_end.py in the user-level settings.json, which every T3 provider instance reads (the
  default `claudeAgent` instance has no seat file). It is rendered per profile and run over settings text, as chezmoi runs it.
- No seat file registers the hook, so a thread on seat-lead gets the user-level group only.
- lead_turn_end.py makes no call and writes nothing for the sessions that name themselves as something else in COORDINATOR_SEAT.
Skipped where chezmoi is not installed (the rendering tests only).

    python3 -m unittest discover -s tests/lead-turn-end -p test_global_stop.py -v
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "dot_local/share/agent-harness/hooks/lead_turn_end.py"
MODIFY = ROOT / "dot_claude/modify_settings.json.tmpl"
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}
PROFILES = (("personal", "git/coordinator", "coordinator"), ("axon-work-computer", "coordinator-work", "coordinator-work"))
SEATS = ("lead", "builder", "planner", "reviewer", "scout", "computer", "coordinator", "homelab-chat")
SKIPPED = ("builder", "planner", "reviewer", "scout", "computer", "coordinator", "homelab-chat")
MARK = "lead_turn_end.py"
USER_STOP = {"hooks": [{"type": "command", "command": "echo user stop"}]}

# A coordinator checkout whose hook prints one entry, so the modify script has hook entries of its own to keep next to the Stop group.
PRINTING_HOOK = ("if (process.argv.includes('--print-settings-json')) {\n"
                 "  process.stdout.write(JSON.stringify({ schema: 1, rulesPages: 0, entries: [{ event: 'PreToolUse', matcher: '^AskUserQuestion$', args: [], failClosed: false, t3Only: false }] }));\n"
                 "  process.exit(0);\n}\n")

# The stub coordinator: records its arguments, one JSON line per call, and answers allow.
STUB = """
import { appendFileSync } from "node:fs";
appendFileSync(process.env.STUB_RECORD, JSON.stringify(process.argv.slice(2)) + "\\n");
console.log(JSON.stringify({ answer: "allow", reason: "stub" }));
"""


# A stub coordinator that refuses, the way the real one refuses a lead's first bare end.
REFUSING_STUB = """
console.log(JSON.stringify({ answer: "refuse", message: "Do the work, start a waker, or open an ask." }));
"""


def group_commands(settings):
    return [h["command"] for g in settings.get("hooks", {}).get("Stop", []) for h in g.get("hooks", []) if MARK in h.get("command", "")]


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def checkout(self):
        repo = self.root / "coordinator-checkout"
        (repo / "src/t3-hook").mkdir(parents=True, exist_ok=True)
        (repo / "src/t3-hook/hook.ts").write_text(PRINTING_HOOK)
        return repo

    def script(self, profile, extra=None):
        """The modify script rendered for a profile, as a file under this test's folder (HOME is the folder, so the paths in it are this test's own)."""
        cfg = self.root / "chezmoi.yaml"
        cfg.write_text(json.dumps({"data": {"profile": profile, "hub": {"enabled": False}, **(WORK_DATA if profile == "axon-work-computer" else {}), **(extra or {})}}))
        done = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                              input=MODIFY.read_text(), capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=str(self.root)))
        self.assertEqual(done.returncode, 0, done.stderr)
        path = self.root / f"modify-{profile}-{abs(hash(json.dumps(extra, sort_keys=True)))}.sh"
        path.write_text(done.stdout)
        return path

    def apply(self, script, settings):
        text = settings if isinstance(settings, str) else json.dumps(settings)
        done = subprocess.run(["sh", str(script)], input=text, capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def render_seat(self, seat, profile):
        cfg = self.root / "seat.yaml"
        cfg.write_text(json.dumps({"data": {"profile": profile}}))
        done = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                              input=(ROOT / f"dot_claude/fleet/seat-{seat}.json.tmpl").read_text(), capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=str(self.root)))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_global_stop_group(self):
        for profile, repo, state in PROFILES:
            with self.subTest(profile=profile):
                script = self.script(profile, {"instances": {"coordinator": {"repo": str(self.checkout())}}})
                first = self.apply(script, {"theme": "dark", "hooks": {"Stop": [USER_STOP]}})
                commands = group_commands(first)
                self.assertEqual(len(commands), 1, commands)
                self.assertIn(f"--repo '{self.root / 'coordinator-checkout'}'", commands[0])
                self.assertIn(f"--state '{self.root}/.local/share/{state}'", commands[0])
                self.assertEqual(first["hooks"]["Stop"][0], USER_STOP)           # the user's own Stop group stays, and stays first
                self.assertEqual(first["theme"], "dark")
                self.assertIn("PreToolUse", first["hooks"])                        # the coordinator hook's own entries are still installed
                self.assertEqual(self.apply(script, first), first)                 # applying again changes nothing
        script = self.script("personal")
        self.assertIn(f"--repo '{self.root}/git/coordinator'", group_commands(self.apply(script, {}))[0])   # the profile's default checkout

    def test_global_stop_group_removed(self):
        # The switch exists on the personal profile only (agent_host_config fails on any other).
        installed = self.apply(self.script("personal"), {"hooks": {"Stop": [USER_STOP]}})
        self.assertEqual(len(group_commands(installed)), 1)
        off = self.script("personal", {"agentHost": {"removeCoordinatorHook": True}})
        self.assertEqual(group_commands(self.apply(off, {})), [])
        kept = self.apply(off, installed)
        self.assertEqual(group_commands(kept), [])
        self.assertEqual(kept["hooks"]["Stop"], [USER_STOP])                   # only our group goes

    def test_no_seat_file_registers_the_lead_stop(self):
        for profile, _, _ in PROFILES:
            for seat in SEATS:
                with self.subTest(profile=profile, seat=seat):
                    rendered = self.render_seat(seat, profile)
                    self.assertNotIn(MARK, json.dumps(rendered))
                    if seat == "lead":
                        self.assertNotIn("hooks", rendered)

    def test_the_group_command_passes_exit_2_through_and_fails_open(self):
        script = self.script("personal")
        command = group_commands(self.apply(script, {}))[0]
        home = self.root / "home"
        env = {k: v for k, v in os.environ.items() if k not in ("T3CODE_THREAD_ID", "COORDINATOR_STATE_DIR", "COORDINATOR_SEAT")}
        env.update({"HOME": str(home), "T3CODE_THREAD_ID": "thread:lead", "LEAD_TURN_END_PS": "/nonexistent/ps"})
        run = lambda: subprocess.run(["sh", "-c", command.replace(str(self.root), str(home))], input="{}", capture_output=True, text=True, env=env, timeout=60)
        home.mkdir()
        self.assertEqual(run().returncode, 0)                                      # script not installed: allowed
        hooks = home / ".local/share/agent-harness/hooks"
        hooks.mkdir(parents=True)
        shutil.copy(HOOK, hooks / MARK)
        self.assertEqual(run().returncode, 0)                                      # installed, no coordinator checkout: allowed
        (home / "git/coordinator/src/coordinatord").mkdir(parents=True)
        (home / "git/coordinator/src/coordinatord/cli.ts").write_text(REFUSING_STUB)
        (home / ".local/share/coordinator").mkdir(parents=True, exist_ok=True)     # the failed check above left its log line here
        done = run()
        self.assertEqual(done.returncode, 2, done.stderr)                          # the coordinator's refusal reaches Claude Code as exit 2
        self.assertIn("Do the work", done.stderr)


class SeatGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo = root / "coordinator"
        (self.repo / "src/coordinatord").mkdir(parents=True)
        (self.repo / "src/coordinatord/cli.ts").write_text(STUB)
        self.state = root / "state"
        self.state.mkdir()
        self.record = root / "record"
        self.ps = root / "ps"
        self.chain([])

    def chain(self, lines):
        """A stub `ps -o ppid=,args= -p PID` that answers the n-th call with the n-th line of `lines` ("PPID args", walking up from the hook's parent); a call past the end fails like a missing process."""
        (self.ps.parent / "ps-lines").write_text("\n".join(lines) + ("\n" if lines else ""))
        self.ps.write_text('#!/bin/sh\nd=$(dirname "$0")\nn=$(cat "$d/ps-n" 2>/dev/null || echo 0)\nn=$((n+1))\necho $n > "$d/ps-n"\nline=$(sed -n "${n}p" "$d/ps-lines")\n[ -n "$line" ] || exit 1\necho "$line"\n')
        self.ps.chmod(0o755)
        (self.ps.parent / "ps-n").unlink(missing_ok=True)

    def run_hook(self, seat, repo=None):
        env = {k: v for k, v in os.environ.items() if k not in ("T3CODE_THREAD_ID", "COORDINATOR_STATE_DIR", "COORDINATOR_SEAT")}
        env.update({"T3CODE_THREAD_ID": "thread:x", "LEAD_TURN_END_PS": str(self.ps), "STUB_RECORD": str(self.record), "RUN_AND_WAKE_STATE": str(Path(self.tmp.name) / "rw"), "KGATE_STATE": str(Path(self.tmp.name) / "kg")})
        if seat is not None:
            env["COORDINATOR_SEAT"] = seat
        return subprocess.run([sys.executable, str(HOOK), "--repo", str(repo or self.repo), "--state", str(self.state)], input="{}", capture_output=True, text=True, env=env, timeout=60)

    def calls(self):
        return self.record.read_text().splitlines() if self.record.exists() else []

    def test_seat_guard(self):
        for seat in SKIPPED:
            with self.subTest(seat=seat):
                done = self.run_hook(seat, repo=self.state / "no-such-checkout")   # a call would fail and leave a line in the adapter log
                self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
                self.assertEqual(self.calls(), [])
                self.assertEqual(list(self.state.rglob("*")), [])
        for seat in ("lead", None, "a-seat-that-does-not-exist"):
            with self.subTest(seat=seat):
                before = len(self.calls())
                self.assertEqual(self.run_hook(seat).returncode, 0)
                self.assertEqual(len(self.calls()), before + 1)
                self.assertIn('"t3","turn-end","--thread","thread:x"', self.calls()[-1].replace(" ", ""))
        failed = self.run_hook("lead", repo=self.state / "no-such-checkout")
        self.assertEqual(failed.returncode, 0)
        self.assertTrue((self.state / "t3-hook/turn-end-adapter.jsonl").exists())  # a lead's failed check is still logged

    def ledger(self, conversations):
        db = sqlite3.connect(self.state / "ledger.sqlite")
        db.execute("CREATE TABLE workstreams (name TEXT, conversation TEXT)")
        db.executemany("INSERT INTO workstreams VALUES (?, ?)", [("ws", c) for c in conversations])
        db.commit()
        db.close()

    def test_no_seat_session_that_is_not_a_lead_workstream_is_skipped(self):
        self.ledger(["t3:some-other-thread", None])
        for seat in (None, "a-seat-that-does-not-exist"):
            with self.subTest(seat=seat):
                done = self.run_hook(seat, repo=self.state / "no-such-checkout")   # a call would fail and leave a line in the adapter log
                self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
                self.assertEqual(self.calls(), [])
                self.assertFalse((self.state / "t3-hook").exists())
        self.assertEqual(self.run_hook("lead").returncode, 0)                    # a seat that names itself a lead is asked whatever the ledger says
        self.assertEqual(len(self.calls()), 1)

    def test_no_seat_session_that_is_a_lead_workstream_is_asked(self):
        self.ledger(["t3:thread:x"])
        self.assertEqual(self.run_hook(None).returncode, 0)
        self.assertEqual(len(self.calls()), 1)

    def test_an_unreadable_ledger_never_hides_a_lead(self):
        (self.state / "ledger.sqlite").write_text("not a database")
        self.assertEqual(self.run_hook(None).returncode, 0)
        self.assertEqual(len(self.calls()), 1)
        (self.state / "ledger.sqlite").unlink()
        self.assertEqual(self.run_hook(None).returncode, 0)                      # no ledger file at all
        self.assertEqual(len(self.calls()), 2)


    def test_a_one_shot_claude_p_started_from_a_shell_is_skipped(self):
        self.ledger(["t3:thread:x"])   # the lead's own thread: the nested run carries its id and passes the ledger check
        T3 = "/home/agent/.local/bin/claude --output-format stream-json --verbose --input-format stream-json --model m --resume=abc"
        nested = "/home/agent/.local/bin/claude -p --tools Read --model claude-haiku-5-5"
        for name, seat, lines, skipped in (
                ("claude -p", "lead", ["10 " + nested], True),
                ("claude -p under sh", None, ["10 sh -c hook", "11 " + nested], True),
                ("claude --print", "lead", ["10 claude --print --model m"], True),
                ("T3's streaming claude", "lead", ["10 " + T3], False),
                ("streaming claude with -p", "lead", ["10 claude -p --input-format=stream-json --output-format stream-json"], False),
                ("T3's claude under sh", None, ["10 sh -c hook", "11 " + T3], False),
                ("no claude in the chain", "lead", ["10 sh", "11 zsh", "1 init"], False),
                ("ps cannot read it", "lead", [], False)):
            with self.subTest(name):
                self.chain(lines)
                self.record.unlink(missing_ok=True)
                shutil.rmtree(self.state / "t3-hook", ignore_errors=True)
                done = self.run_hook(seat, repo=self.state / "no-such-checkout")   # a call would fail and leave a line in the adapter log
                self.assertEqual(done.returncode, 0)
                self.assertEqual((self.state / "t3-hook/turn-end-adapter.jsonl").exists(), not skipped)

    def test_the_nearest_claude_decides_not_one_further_up(self):
        self.chain(["10 sh", "11 claude --input-format stream-json", "12 sh", "13 claude -p"])    # T3's session, started under some other claude's shell
        self.assertEqual(self.run_hook("lead", repo=self.state / "no-such-checkout").returncode, 0)
        self.assertTrue((self.state / "t3-hook/turn-end-adapter.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
