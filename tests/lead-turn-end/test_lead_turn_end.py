"""The lead's turn-end check on Claude Code and Pi, for both desktop profiles (weak-model floor, piece S4).

- hooks/lead_turn_end.py is run as a process, the way Claude Code runs it, against a stub coordinator checkout whose cli.ts answers from the arguments it was given.
- The lead seat file (both profiles) carries the Stop hook with this profile's own coordinator checkout and state directory; no other seat does.
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
        env = {k: v for k, v in os.environ.items() if k not in ("T3CODE_THREAD_ID", "COORDINATOR_STATE_DIR")}
        env.update({"STUB_RECORD": str(self.record), "RUN_AND_WAKE_STATE": str(Path(self.tmp.name) / "rw"), "KGATE_STATE": str(Path(self.tmp.name) / "kg"), **(extra or {})})
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
            return subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), *args(tmp)], capture_output=True, text=True, timeout=300, **kw)

    def render_config(self, profile, extra=None):
        done = self.chezmoi(lambda tmp: ["execute-template", "--override-data", json.dumps(self.data(profile, extra))], input=(EXT / "config.json.tmpl").read_text())
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def render_seat(self, seat, profile, extra=None):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "chezmoi.yaml"
            cfg.write_text(json.dumps({"data": {"profile": profile, **(extra or {})}}))
            done = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(cfg), "--config-format", "yaml", "execute-template"],
                                  input=(ROOT / f"dot_claude/fleet/seat-{seat}.json.tmpl").read_text(), capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=tmp))
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout), tmp

    def test_the_pi_config_points_each_profile_at_its_own_coordinator(self):
        jobs = f"{HOME}/.local/share/agent-harness/hooks/stop_running_jobs.py"
        self.assertEqual(self.render_config("personal"), {"enabled": True, "coordinatorRepo": f"{HOME}/git/coordinator", "stateDir": f"{HOME}/.local/share/coordinator", "jobsHook": jobs})
        self.assertEqual(self.render_config("axon-work-computer"), {"enabled": True, "coordinatorRepo": f"{HOME}/coordinator-work", "stateDir": f"{HOME}/.local/share/coordinator-work", "jobsHook": jobs})
        self.assertEqual(self.render_config("personal", {"instances": {"coordinator": {"repo": "/srv/coordinator"}}})["coordinatorRepo"], "/srv/coordinator")
        self.assertFalse(self.render_config("personal", {"agentHost": {"removeCoordinatorHook": True}})["enabled"])

    def test_only_the_lead_seat_file_has_the_lead_stop_hook(self):
        for profile in ("personal", "axon-work-computer"):
            for seat in ("lead", "builder", "planner", "reviewer", "scout", "coordinator"):
                hooks, _ = self.render_seat(seat, profile)
                hooks = hooks.get("hooks")
                with self.subTest(profile=profile, seat=seat):
                    if seat == "lead":
                        self.assertEqual(list(hooks), ["Stop"])
                        self.assertIn("lead_turn_end.py", hooks["Stop"][0]["hooks"][0]["command"])
                    else:
                        self.assertNotIn("lead_turn_end.py", json.dumps(hooks))

    def test_the_lead_seat_hook_names_this_profiles_coordinator(self):
        for profile, repo, state in (("personal", "git/coordinator", "coordinator"), ("axon-work-computer", "coordinator-work", "coordinator-work")):
            seat, tmp = self.render_seat("lead", profile)
            command = seat["hooks"]["Stop"][0]["hooks"][0]["command"]
            with self.subTest(profile=profile):
                self.assertIn(f"{tmp}/{repo}'", command)
                self.assertIn(f"{tmp}/.local/share/{state}'", command)

    def test_the_lead_seat_hook_is_left_out_when_the_coordinator_runs_elsewhere(self):
        seat, _ = self.render_seat("lead", "personal", {"agentHost": {"removeCoordinatorHook": True}})
        self.assertNotIn("hooks", seat)

    def test_the_seat_command_passes_exit_2_through_and_fails_open(self):
        seat, tmp = self.render_seat("lead", "personal")
        command = seat["hooks"]["Stop"][0]["hooks"][0]["command"]
        home = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(home, ignore_errors=True))
        env = {k: v for k, v in os.environ.items() if k not in ("T3CODE_THREAD_ID", "COORDINATOR_STATE_DIR")}
        env.update({"HOME": str(home), "T3CODE_THREAD_ID": "thread:lead", "STUB_RECORD": str(home / "rec")})
        run = lambda: subprocess.run(["sh", "-c", command.replace(tmp, str(home))], input="{}", capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(run().returncode, 0)   # script not installed: allowed
        hooks = home / ".local/share/agent-harness/hooks"
        hooks.mkdir(parents=True)
        shutil.copy(HOOK, hooks / "lead_turn_end.py")
        self.assertEqual(run().returncode, 0)   # installed, no coordinator checkout: allowed
        (home / "git/coordinator/src/coordinatord").mkdir(parents=True)
        (home / "git/coordinator/src/coordinatord/cli.ts").write_text(STUB)
        (home / ".local/share/coordinator").mkdir(parents=True)
        done = run()
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("Do the work", done.stderr)

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
