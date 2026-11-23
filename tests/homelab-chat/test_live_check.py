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


class ScriptTest(unittest.TestCase):
    def test_it_exits_2_when_the_machine_has_no_seat_instance(self):
        with tempfile.TemporaryDirectory() as home:
            r = subprocess.run([sys.executable, "-I", str(SCRIPT)], capture_output=True, text=True, timeout=60, env=dict(os.environ, HOME=home))
        self.assertIn(r.returncode, (2, 1))  # SystemExit with a message exits 1; 2 when claude is missing
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue("no seat-homelab-chat instance" in r.stderr or "claude is not on PATH" in r.stderr, r.stderr)

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
