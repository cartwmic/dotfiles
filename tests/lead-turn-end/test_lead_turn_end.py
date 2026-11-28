"""The lead's turn-end check on Claude Code and Pi, for both desktop profiles.

- hooks/lead_turn_end.py is run as a process, the way Claude Code runs it, against a stub coordinator checkout whose cli.ts answers from the arguments it was given.
- Where the Stop hook is registered, and which seats the script skips, is tests/lead-turn-end/test_global_stop.py.
- The Pi extension's config.json renders per profile and deploys on both; its test file does not.
Skipped where chezmoi is not installed (the rendering tests only).

    python3 -m unittest discover -s tests/lead-turn-end -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
HOOK = ROOT / "dot_local/share/agent-harness/hooks/lead_turn_end.py"
EXT = ROOT / "dot_pi/private_agent/extensions/lead-turn-end"
HOME = "/home/someone"
WORK_DATA = {"workGitHost": "git.example.test", "workGlmBaseUrl": "https://gateway.test", "workGlmKeyRef": "op://test/gateway",
             "workGlmModelId": "test-model", "workAwsProfile": "test-aws", "workDevportalMcpUrlRef": "op://test/devportal"}

# The stub coordinator: prints a refusal unless it was asked with --continued; records its arguments one JSON line per call.
STUB = """
import { appendFileSync } from "node:fs";
const args = process.argv.slice(2);
appendFileSync(process.env.STUB_RECORD, JSON.stringify(args) + "\\n");
if (process.env.STUB_MODE === "garbage") { console.log("not json"); process.exit(0); }
if (process.env.STUB_MODE === "crash") process.exit(1);
if (process.env.STUB_MODE === "unknown") { console.error("unknown command: t3 turn-end"); process.exit(2); }
if (process.env.STUB_MODE === "hang") await new Promise((resolve) => setTimeout(resolve, 20000));
if (process.env.STUB_MODE === "always-refuse") { console.log(JSON.stringify({ answer: "refuse", message: "Do the work again." })); process.exit(0); }
console.log(JSON.stringify(args.includes("--continued") ? { answer: "let-through", reason: "x", reported: true } : { answer: "refuse", message: "Do the work, start a waker, ledger open, or state-note." }));
"""


class HookTest(unittest.TestCase):
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
        # The jobs counter beside the hook: a copy of the real one, with empty state folders, so it counts 0 unless a test says otherwise.
        self.hooks = root / "hooks"
        self.hooks.mkdir()
        shutil.copy(HOOK, self.hooks / "lead_turn_end.py")
        shutil.copy(ROOT / "dot_local/share/agent-harness/hooks/stop_running_jobs.py", self.hooks / "stop_running_jobs.py")

    def run_hook(self, hook_input="{}", thread="thread:lead", extra=None, repo=None, state=None):
        env = {k: v for k, v in os.environ.items() if k not in ("T3CODE_THREAD_ID", "COORDINATOR_STATE_DIR", "COORDINATOR_SEAT")}
        env.update({"LEAD_TURN_END_PS": "/nonexistent/ps", "STUB_RECORD": str(self.record), "RUN_AND_WAKE_STATE": str(Path(self.tmp.name) / "rw"), "KGATE_STATE": str(Path(self.tmp.name) / "kg"), **(extra or {})})
        if thread:
            env["T3CODE_THREAD_ID"] = thread
        return subprocess.run([sys.executable, str(self.hooks / "lead_turn_end.py"), "--repo", str(repo or self.repo), "--state", str(state or self.state)],
                              input=hook_input, capture_output=True, text=True, env=env, timeout=60)

    def asked(self):
        return [json.loads(line) for line in self.record.read_text().splitlines()] if self.record.exists() else []

    def test_a_first_end_is_refused_with_exit_2_and_the_message_on_stderr(self):
        done = self.run_hook("{}")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("Do the work", done.stderr)
        args = self.asked()[0]
        self.assertIn("turn-end", args)
        self.assertEqual(args[args.index("--thread") + 1], "thread:lead")
        self.assertEqual(args[args.index("--jobs") + 1], "0")
        self.assertNotIn("--continued", args)

    def test_a_stop_that_follows_the_refusal_is_asked_with_continued_and_let_through(self):
        done = self.run_hook(json.dumps({"stop_hook_active": True}))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("--continued", self.asked()[0])

    def test_the_running_jobs_are_counted_and_passed(self):
        sleeper = subprocess.Popen(["sleep", "60"], env={**os.environ, "RUN_AND_WAKE_JOB": "j1"})
        self.addCleanup(lambda: (sleeper.kill(), sleeper.wait()))
        rw = Path(self.tmp.name) / "rw"
        rw.mkdir()
        (rw / "log.jsonl").write_text(json.dumps({"event": "start", "job": "j1", "thread": "thread:lead", "pid": sleeper.pid, "cmd": ["sleep", "60"], "ts": "t"}) + "\n")
        self.run_hook("{}")
        args = self.asked()[0]
        self.assertEqual(args[args.index("--jobs") + 1], "1")

    def test_it_fails_open(self):
        self.assertEqual(self.run_hook("{}", thread=None).returncode, 0)                       # not a T3 session
        self.assertEqual(self.run_hook("{}", repo="/nowhere").returncode, 0)                   # no checkout
        self.assertEqual(self.run_hook("{}", state="/nowhere").returncode, 0)                  # no state directory
        self.assertEqual(self.run_hook("{}", extra={"STUB_MODE": "garbage"}).returncode, 0)    # unreadable answer
        self.assertEqual(self.run_hook("{}", extra={"STUB_MODE": "crash"}).returncode, 0)      # the coordinator crashed
        self.assertEqual(self.run_hook("not json at all").returncode, 0)                       # unreadable hook input
        self.assertEqual(self.run_hook("{}", extra={"LEAD_TURN_END_NODE": "/nonexistent/node"}).returncode, 0)

    def adapter_log(self):
        path = self.state / "t3-hook" / "turn-end-adapter.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_a_check_that_cannot_run_lets_the_end_through_and_leaves_one_line_saying_why(self):
        cases = [
            ("a timeout", {"STUB_MODE": "hang", "LEAD_TURN_END_TIMEOUT": "1"}, "timed out after 1 s"),
            ("a crash", {"STUB_MODE": "crash"}, "no readable answer (exit 1)"),
            ("output that is not JSON", {"STUB_MODE": "garbage"}, "no readable answer (exit 0)"),
            ("a missing t3 turn-end command", {"STUB_MODE": "unknown"}, "unknown command: t3 turn-end"),
            ("a node that is not there", {"LEAD_TURN_END_NODE": "/nonexistent/node"}, "could not start"),
        ]
        for name, extra, reason in cases:
            with self.subTest(name):
                before = len(self.adapter_log())
                done = self.run_hook("{}", extra=extra)
                self.assertEqual(done.returncode, 0, done.stderr)
                self.assertEqual(done.stderr, "")
                lines = self.adapter_log()
                self.assertEqual(len(lines), before + 1)
                line = lines[-1]
                self.assertEqual((line["outcome"], line["cause"], line["thread"], line["adapter"]), ("allowed", "check-failed", "thread:lead", "claude-stop-hook"))
                self.assertIn(reason, line["reason"])
                self.assertIsInstance(line["duration_ms"], int)
                self.assertTrue(line["ts"].endswith("+00:00"))

    def test_a_missing_checkout_or_state_directory_is_a_failed_check_too(self):
        done = self.run_hook("{}", repo="/nowhere")
        self.assertEqual(done.returncode, 0)
        self.assertIn("coordinator checkout not found", self.adapter_log()[-1]["reason"])
        gone = Path(self.tmp.name) / "no-state-yet"
        self.assertEqual(self.run_hook("{}", state=gone).returncode, 0)
        self.assertIn("state directory not found", json.loads((gone / "t3-hook" / "turn-end-adapter.jsonl").read_text().splitlines()[-1])["reason"])

    def test_an_end_that_is_not_a_failure_writes_no_adapter_line(self):
        self.assertEqual(self.run_hook("{}", thread=None).returncode, 0)                        # not a T3 session
        self.assertEqual(self.run_hook("{}").returncode, 2)                                     # a refusal
        self.assertEqual(self.run_hook(json.dumps({"stop_hook_active": True})).returncode, 0)   # the let-through the coordinator reports itself
        self.assertEqual(self.adapter_log(), [])

    def test_a_refusal_is_never_issued_on_a_stop_that_follows_one(self):
        done = self.run_hook(json.dumps({"stop_hook_active": True}), extra={"STUB_MODE": "always-refuse"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, "")
        line = self.adapter_log()[-1]
        self.assertEqual((line["outcome"], line["cause"]), ("allowed", "after-refusal"))
        self.assertIn("--continued", self.asked()[0])

    def test_the_sessions_own_state_directory_wins(self):
        other = Path(self.tmp.name) / "other-state"
        other.mkdir()
        done = self.run_hook("{}", extra={"COORDINATOR_STATE_DIR": str(other)}, state="/nowhere")
        self.assertEqual(done.returncode, 2, done.stderr)


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class RenderTest(unittest.TestCase):
    @staticmethod
    def data(profile, extra=None):
        return {"profile": profile, "chezmoi": {"homeDir": HOME, "os": "linux"}, **(WORK_DATA if profile == "axon-work-computer" else {}), **(extra or {})}

    def chezmoi(self, args, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "chezmoi.yaml"
            cfg.write_text("{}\n")
            return subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(cfg), *args(tmp)], capture_output=True, text=True, timeout=300, env=source_tree.chezmoi_env(tmp), **kw)

    def render_config(self, profile, extra=None):
        done = self.chezmoi(lambda tmp: ["execute-template", "--override-data", json.dumps(self.data(profile, extra))], input=(EXT / "config.json.tmpl").read_text())
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_the_pi_config_points_each_profile_at_its_own_coordinator(self):
        jobs = f"{HOME}/.local/share/agent-harness/hooks/stop_running_jobs.py"
        self.assertEqual(self.render_config("personal"), {"enabled": True, "coordinatorRepo": f"{HOME}/git/coordinator", "stateDir": f"{HOME}/.local/share/coordinator", "jobsHook": jobs})
        self.assertEqual(self.render_config("axon-work-computer"), {"enabled": True, "coordinatorRepo": f"{HOME}/coordinator-work", "stateDir": f"{HOME}/.local/share/coordinator-work", "jobsHook": jobs})
        self.assertEqual(self.render_config("personal", {"instances": {"coordinator": {"repo": "/srv/coordinator"}}})["coordinatorRepo"], "/srv/coordinator")
        self.assertFalse(self.render_config("personal", {"agentHost": {"removeCoordinatorHook": True}})["enabled"])

    def managed(self, profile):
        done = self.chezmoi(lambda tmp: ["--destination", tmp, "managed", "--include=files", "--path-style=relative", "--override-data", json.dumps(self.data(profile))])
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def test_the_extension_and_the_hook_deploy_on_both_profiles_and_the_extension_test_does_not(self):
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile=profile):
                files = self.managed(profile)
                for name in ("index.ts", "config.json", "README.md"):
                    self.assertIn(f".pi/agent/extensions/lead-turn-end/{name}", files)
                self.assertNotIn(".pi/agent/extensions/lead-turn-end/index.test.ts", files)
                self.assertIn(".local/share/agent-harness/hooks/lead_turn_end.py", files)


if __name__ == "__main__":
    unittest.main()
