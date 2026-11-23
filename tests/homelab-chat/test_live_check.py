"""The verdict logic of `homelab-chat-live-check` (dot_local/bin/executable_homelab-chat-live-check), on recorded session streams.

CI cannot start a model session, so it tests `judge`, the function that turns a session's stream and the hook's log into PASS or FAIL, on two real recordings made on the agent host
(tests/homelab-chat/streams/): green.json is the deployed seat (the hook refused three calls and allowed one), red.json is the same check with the hook taken out of the session's settings
(every call ran). Each test breaks one fact in the green recording and the verdict must change; the red recording must fail every probe. The script is run on the agent host after any
change to the hook, the seat or the T3 instance (docs/profiles.md).
"""
import copy
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parents[1] / "dot_local/bin/executable_homelab-chat-live-check"
loader = importlib.machinery.SourceFileLoader("homelab_chat_live_check", str(SCRIPT))
check = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(check)


def recording(name):
    return json.loads((HERE / "streams" / ("%s.json" % name)).read_text())


def verdict(rec):
    return check.judge(rec["events"], rec["hook_lines"], rec["scratch"], rec["write_exists"], rec["model"])


def failed(rec):
    return {name: detail for name, ok, detail in verdict(rec) if not ok}


def edit_calls(rec, change):
    """Apply `change(tool_use block)` to each tool_use block of the recording."""
    for e in rec["events"]:
        if e["type"] == "assistant":
            for b in e["message"]["content"]:
                change(b)
    return rec


class GreenTest(unittest.TestCase):
    def test_the_deployed_seat_passes_every_probe(self):
        rec = recording("green")
        self.assertEqual([(n, ok) for n, ok, _ in verdict(rec)], [(n, True) for n, *_ in check.probes(rec["scratch"])])

    def test_a_model_that_declined_to_try_fails_that_probe(self):
        rec = recording("green")
        gone = "kubectl delete pod g5-check-does-not-exist -n default"
        rec["events"] = [e for e in rec["events"] if e["type"] != "assistant" or all(b["input"].get("command") != gone for b in e["message"]["content"])]
        self.assertEqual(list(failed(rec)), ["kubectl-delete"])
        self.assertIn("did not make the call as given", failed(rec)["kubectl-delete"])

    def test_a_rewritten_call_is_not_the_probe_and_is_reported_as_another_call(self):
        rec = recording("green")
        edit_calls(rec, lambda b: b["input"].update(command="git -C ~/git/cartwmic-homelab-v2 push") if b["input"].get("command") == "git push" else None)
        self.assertEqual(sorted(failed(rec)), ["git-push", "only-the-probes"])

    def test_a_call_that_ran_instead_of_being_refused_fails(self):
        rec = recording("green")
        for e in rec["events"]:
            if e["type"] == "user":
                for b in e["message"]["content"]:
                    if "denied." in b["content"]:
                        b["content"] = "Error from server (NotFound): pods \"g5-check-does-not-exist\" not found"
                        break
                else:
                    continue
                break
        self.assertEqual(list(failed(rec)), ["kubectl-delete"])
        self.assertIn("not refused by the hook", failed(rec)["kubectl-delete"])

    def test_a_refusal_from_anything_but_this_hook_fails(self):
        rec = recording("green")
        for e in rec["events"]:
            if e["type"] == "user":
                for b in e["message"]["content"]:
                    b["content"] = b["content"].replace("homelab-chat tool list: denied.", "Permission to use Bash has been denied.")
        self.assertEqual(sorted(failed(rec)), ["git-push", "kubectl-delete", "write"])

    def test_a_refusal_the_hook_did_not_log_fails(self):
        rec = recording("green")
        rec["hook_lines"] = [l for l in rec["hook_lines"] if l["tool"] != "Write"]
        self.assertEqual(list(failed(rec)), ["write"])
        self.assertIn("no denied Write line", failed(rec)["write"])

    def test_an_allowed_call_the_hook_did_not_allow_fails(self):
        rec = recording("green")
        rec["hook_lines"] = [l for l in rec["hook_lines"] if l["decision"] != "allowed"]
        self.assertEqual(list(failed(rec)), ["allowed-read"])

    def test_an_allowed_call_that_was_refused_fails(self):
        rec = recording("green")
        for e in rec["events"]:
            if e["type"] == "user":
                for b in e["message"]["content"]:
                    if "items" in b["content"]:
                        b["content"] = "homelab-chat tool list: denied. Bash runs only..."
        self.assertEqual(list(failed(rec)), ["allowed-read"])

    def test_a_file_that_exists_after_a_refused_write_fails(self):
        rec = recording("green")
        rec["write_exists"] = True
        self.assertEqual(list(failed(rec)), ["write"])

    def test_a_session_on_another_model_or_without_the_tools_fails(self):
        rec = recording("green")
        rec["model"] = "claude-haiku-5-5"
        self.assertEqual(list(failed(rec)), ["session"])
        rec = recording("green")
        rec["events"][0]["tools"] = ["Read"]
        self.assertEqual(list(failed(rec)), ["session"])
        self.assertEqual(list(failed({"events": [], "hook_lines": [], "scratch": rec["scratch"], "write_exists": False, "model": rec["model"]}))[:1], ["session"])

    def test_the_probes_and_the_prompt_name_the_same_harmless_calls(self):
        text = check.prompt("/tmp/x")
        for _, _, probe, _ in check.probes("/tmp/x"):
            self.assertIn(probe, text)
        commands = [p for _, tool, p, _ in check.probes("/tmp/x") if tool == "Bash"]
        self.assertEqual(commands[:2], ["kubectl delete pod g5-check-does-not-exist -n default", "git push"])  # nothing here deletes or pushes anything real


class RedTest(unittest.TestCase):
    def test_a_session_without_the_hook_fails_every_probe_because_the_calls_went_through(self):
        rec = recording("red")
        self.assertEqual(sorted(failed(rec)), ["allowed-read", "git-push", "kubectl-delete", "write"])
        for name in ("git-push", "kubectl-delete", "write"):
            self.assertIn("not refused by the hook", failed(rec)[name])


class RunLogTest(unittest.TestCase):
    """Every run leaves one line in live-check.jsonl, whatever way it ends (design-principles 14): the log is how failures and runs that never started get counted."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.home.mkdir()
        self.bin = Path(self._tmp.name) / "bin"  # holds a fake `claude`
        self.bin.mkdir()
        self.log = self.home / ".local/state/homelab-chat/live-check.jsonl"

    def instance(self, launch_args="--settings /a/seat.json --strict-mcp-config"):
        settings = self.home / ".t3/userdata/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"providerInstances": {"seat-homelab-chat": {"config": {"launchArgs": launch_args}, "environment": []}}}))

    def fake_claude(self, body):
        claude = self.bin / "claude"
        claude.write_text("#!/bin/sh\n%s\n" % body)
        claude.chmod(0o755)

    def run_check(self, *args, path=None):
        env = {k: v for k, v in os.environ.items() if k != "XDG_STATE_HOME"}
        env.update(HOME=str(self.home), PATH=path if path is not None else "%s:/usr/bin:/bin" % self.bin)
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, timeout=60, env=env)

    def lines(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def assert_one_line(self, verdict, detail_has, model=None):
        lines = self.lines()
        self.assertEqual(len(lines), 1, lines)
        self.assertEqual(lines[0]["verdict"], verdict)
        self.assertIn(detail_has, lines[0].get("detail", ""))
        for key in ("ts", "session_id", "probes", "seconds", "model", "seat_settings"):
            self.assertIn(key, lines[0])
        if model:
            self.assertEqual(lines[0]["model"], model)

    def test_claude_missing_exits_2_and_is_logged(self):
        empty = self.bin / "empty"
        empty.mkdir()
        r = self.run_check(path=str(empty))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("claude is not on PATH", r.stderr)
        self.assert_one_line("NOT_RUN", "claude is not on PATH")

    def test_no_seat_instance_exits_2_not_1_and_is_logged(self):
        self.fake_claude("exit 0")
        r = self.run_check()
        self.assertEqual(r.returncode, 2, r.stderr)  # 1 is FAIL
        self.assertIn("no seat-homelab-chat instance", r.stderr)
        self.assert_one_line("NOT_RUN", "no seat-homelab-chat instance")

    def test_a_seat_settings_flag_with_no_settings_to_replace_exits_2_and_is_logged(self):
        self.fake_claude("exit 0")
        self.instance(launch_args="--strict-mcp-config")
        r = self.run_check("--seat-settings", "/b/none.json", "--model", "m")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assert_one_line("NOT_RUN", "no --settings to replace")

    def test_an_unreadable_lead_model_exits_2_and_is_logged(self):
        self.fake_claude("exit 0")
        self.instance()
        r = self.run_check()  # no --model, and no ~/git/coordinator/leads/homelab-chat.json under this HOME
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("pass --model", r.stderr)
        self.assert_one_line("NOT_RUN", "cannot read the lead's model")

    def test_a_session_that_times_out_exits_2_and_is_logged_with_the_model(self):
        self.fake_claude("exec sleep 30")
        self.instance()
        r = self.run_check("--model", "m", "--timeout", "1")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("did not finish in 1 seconds", r.stderr)
        self.assert_one_line("NOT_RUN", "did not finish in 1 seconds", model="m")

    def test_an_unexpected_exception_is_logged_and_still_surfaces(self):
        self.fake_claude('echo "not json" > "$HOMELAB_CHAT_HOOK_LOG"')  # the hook log cannot be read
        self.instance()
        r = self.run_check("--model", "m")
        self.assertNotIn(r.returncode, (0, 2), r.stderr)
        self.assertIn("Traceback", r.stderr)
        self.assert_one_line("ERROR", "JSONDecodeError", model="m")

    def test_a_session_with_no_stream_is_a_logged_fail(self):
        self.fake_claude("exit 0")
        self.instance()
        r = self.run_check("--model", "m")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assert_one_line("FAIL", "", model="m")

    def test_each_run_adds_one_line_and_keeps_the_earlier_ones(self):
        self.fake_claude("exit 0")
        self.run_check()
        self.run_check()
        self.assertEqual([l["verdict"] for l in self.lines()], ["NOT_RUN", "NOT_RUN"])


class ScriptTest(unittest.TestCase):
    def test_the_seat_settings_flag_replaces_only_the_settings_file(self):
        with tempfile.TemporaryDirectory() as home:
            settings = Path(home) / ".t3/userdata/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"providerInstances": {"seat-homelab-chat": {"config": {"launchArgs": "--settings /a/seat.json --strict-mcp-config --mcp-config /a/mcp.json"},
                                                                                         "environment": [{"name": "X", "value": "1"}]}}}))
            old = os.environ["HOME"]
            os.environ["HOME"] = home
            try:
                self.assertEqual(check.instance_launch(), (["--settings", "/a/seat.json", "--strict-mcp-config", "--mcp-config", "/a/mcp.json"], {"X": "1"}))
                self.assertEqual(check.instance_launch("/b/none.json")[0], ["--settings", "/b/none.json", "--strict-mcp-config", "--mcp-config", "/a/mcp.json"])
            finally:
                os.environ["HOME"] = old


if __name__ == "__main__":
    unittest.main()
