"""ci-main-status for a Gitea table repo (budget-steward), against a fake Gitea API on a local port, a real git repo
(the tree hash comes from a one-commit fetch) and a kgate log fixture. No gh, no network.

The gate must not fail open: every state it cannot read, and every state with no evidence, exits 1 under --merge-gate.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "dot_local/bin/executable_ci-main-status"
TOKEN = "tok-secret-0123456789"
SUITE = "sh -c 'npm ci && npm run typecheck && npm test'"
API = "/api/v1/repos/cartwmic/budget-steward"


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, check=True).stdout.strip()


class FakeGitea(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.calls.append(self.path)
        if self.server.require_token and self.headers.get("Authorization") != "token " + TOKEN:
            return self.send(404, {"message": "not found"})   # a private repo answers 404 to no token
        state = self.server.state
        if self.path == API + "/branches/main":
            return self.send(200, {"commit": {"id": state["tip"]}})
        if self.path.startswith(API + "/pulls/"):
            pull = state["pulls"].get(self.path.rsplit("/", 1)[1])
            return self.send(200, pull) if pull else self.send(404, {"message": "no such pr"})
        if self.path.startswith(API + "/commits/") and self.path.endswith("/status"):
            sha = self.path.split("/commits/")[1].split("/")[0]
            return self.send(200, state["status"].get(sha, {"state": "pending", "total_count": 0}))
        self.send(404, {"message": "unrouted " + self.path})

    def send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class GiteaGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.src = t / "src"
        self.src.mkdir()
        git(self.src, "init", "-q", "-b", "main")
        git(self.src, "config", "user.email", "t@example.com")
        git(self.src, "config", "user.name", "t")
        git(self.src, "config", "uploadpack.allowAnySHA1InWant", "true")
        (self.src / "a.txt").write_text("one\n")
        git(self.src, "add", "-A")
        git(self.src, "commit", "-qm", "main commit")
        self.tip = git(self.src, "rev-parse", "HEAD")
        git(self.src, "switch", "-qc", "pr")
        (self.src / "b.txt").write_text("two\n")
        git(self.src, "add", "-A")
        git(self.src, "commit", "-qm", "pr commit")
        self.head = git(self.src, "rev-parse", "HEAD")
        self.head_tree = git(self.src, "rev-parse", "HEAD^{tree}")
        self.tip_tree = git(self.src, "rev-parse", self.tip + "^{tree}")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGitea)
        self.server.calls = []
        self.server.require_token = True
        self.server.state = {"tip": self.tip, "status": {}, "pulls": {"7": {"state": "open", "head": {"sha": self.head}, "base": {"ref": "main"}}}}
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.kgate_log = t / "kgate.jsonl"
        self.records = []
        home = t / "home"
        home.mkdir()
        self.env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                    "CI_MAIN_STATUS_GITEA_API": f"http://127.0.0.1:{self.server.server_port}/api/v1",
                    "CI_MAIN_STATUS_GITEA_GIT": "file://" + str(self.src),
                    "CI_MAIN_STATUS_GITEA_TOKEN": TOKEN, "CI_MAIN_STATUS_KGATE_LOG": str(self.kgate_log)}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def record(self, tree, exit=0, cmd=SUITE, ran=True, **extra):
        self.records.append({"id": f"kgate-{len(self.records) + 1}", "repo": "budget-steward", "tree": tree, "cmd": cmd, "ran": ran, "exit": exit, **extra})

    def status(self, *args):
        self.kgate_log.write_text("".join(json.dumps(r) + "\n" for r in self.records))
        r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=self.env, timeout=120)
        out = r.stdout + r.stderr
        self.assertNotIn(TOKEN, out)   # the token is never printed
        return r.returncode, out

    # ---- the PR gate
    def test_a_full_suite_kgate_pass_on_the_head_tree_passes_the_gate(self):
        self.record(self.head_tree)
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn("budget-steward: GREEN", out)
        self.assertIn("kgate-1 exit 0", out)

    def test_the_full_name_is_the_same_gate(self):
        self.record(self.head_tree)
        rc, out = self.status("--merge-gate", "cartwmic/budget-steward", "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn("budget-steward: GREEN", out)

    def test_a_gitea_status_success_alone_passes(self):
        self.server.state["status"][self.head] = {"state": "success", "total_count": 1}
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn("Gitea commit status success", out)

    def test_no_evidence_is_red_and_exits_1(self):
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("no evidence", out)

    def test_an_empty_gitea_status_is_no_evidence_not_a_pass(self):
        self.server.state["status"][self.head] = {"state": "pending", "total_count": 0}
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)

    def test_a_pending_gitea_status_is_not_a_pass(self):
        self.server.state["status"][self.head] = {"state": "pending", "total_count": 1}
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)

    def test_a_run_on_another_tree_is_no_evidence(self):
        self.record(self.tip_tree)
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)

    def test_a_failed_kgate_run_is_red(self):
        self.record(self.head_tree, exit=1)
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)

    def test_the_newest_full_suite_run_decides(self):
        self.record(self.head_tree, exit=1)
        self.record(self.head_tree, exit=0)
        self.assertEqual(self.status("--merge-gate", "budget-steward", "--pr", "7")[0], 0)
        self.records.reverse()
        self.assertEqual(self.status("--merge-gate", "budget-steward", "--pr", "7")[0], 1)

    def test_a_failed_gitea_status_beats_a_kgate_pass(self):
        self.record(self.head_tree)
        self.server.state["status"][self.head] = {"state": "failure", "total_count": 1}
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)

    def test_a_run_of_a_few_proof_tests_is_not_the_suite(self):
        self.record(self.head_tree, cmd="sh -c 'npm ci && npx vitest run test/proof/fa05.test.ts'")
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)

    def test_a_partial_run_that_failed_does_not_turn_a_pass_red(self):
        self.record(self.head_tree)
        self.record(self.head_tree, exit=1, cmd="sh -c 'npm ci && npx vitest run test/proof/fa05.test.ts'")
        self.assertEqual(self.status("--merge-gate", "budget-steward", "--pr", "7")[0], 0)

    def test_a_cancelled_or_unstarted_run_is_not_evidence(self):
        self.record(self.head_tree, cancelled=True)
        self.record(self.head_tree, ran=False)
        self.record(self.head_tree, exit=None)
        self.record(self.head_tree, exit=True)   # a bool is not an exit code
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)

    def test_a_run_of_another_repo_is_not_evidence(self):
        self.record(self.head_tree, repo="coordinator")
        self.assertEqual(self.status("--merge-gate", "budget-steward", "--pr", "7")[0], 1)

    def test_a_torn_log_line_is_skipped(self):
        self.record(self.head_tree)
        self.kgate_log.write_text(json.dumps(self.records[0]) + "\n{\"id\": \"kgate-2\", \"repo\": \"bud")
        r = subprocess.run([sys.executable, str(SCRIPT), "--merge-gate", "budget-steward", "--pr", "7"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_missing_log_is_no_evidence(self):
        self.env["CI_MAIN_STATUS_KGATE_LOG"] = str(Path(self.tmp.name) / "none.jsonl")
        r = subprocess.run([sys.executable, str(SCRIPT), "--merge-gate", "budget-steward", "--pr", "7"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_no_pr_number_is_1_and_reads_nothing(self):
        rc, out = self.status("--merge-gate", "budget-steward")
        self.assertEqual(rc, 1, out)
        self.assertIn("--pr N", out)
        self.assertEqual(self.server.calls, [])

    def test_a_closed_pr_is_red(self):
        self.record(self.head_tree)
        self.server.state["pulls"]["7"]["state"] = "closed"
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("not open", out)

    def test_a_pr_aimed_at_another_branch_is_red(self):
        self.record(self.head_tree)
        self.server.state["pulls"]["7"]["base"]["ref"] = "release"
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)

    def test_a_pr_gitea_does_not_know_is_1(self):
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "9")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)

    def test_a_malformed_pr_is_1(self):
        self.server.state["pulls"]["7"] = {"state": "open", "head": {"sha": "nope"}, "base": {"ref": "main"}}
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)

    # ---- unreadable is never a pass
    def test_a_private_repo_with_no_token_is_an_error_not_no_evidence(self):
        self.env["CI_MAIN_STATUS_GITEA_TOKEN"] = ""
        for args in (["--merge-gate", "budget-steward", "--pr", "7"], ["budget-steward"], ["--tip", "budget-steward"]):
            with self.subTest(args=args):
                rc, out = self.status(*args)
                self.assertEqual(rc, 1, out)
                self.assertIn("ERROR", out)
                self.assertIn("no Gitea token", out)

    def test_an_unreachable_gitea_is_1(self):
        self.env["CI_MAIN_STATUS_GITEA_API"] = "http://127.0.0.1:1/api/v1"
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)

    def test_a_commit_git_cannot_fetch_is_1(self):
        self.env["CI_MAIN_STATUS_GITEA_GIT"] = "file://" + str(Path(self.tmp.name) / "nowhere")
        self.record(self.head_tree)
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)

    # ---- main's state
    def test_plain_status_is_green_when_main_s_tip_has_a_full_suite_pass(self):
        self.record(self.tip_tree)
        rc, out = self.status("budget-steward")
        self.assertEqual(rc, 0, out)
        self.assertIn("budget-steward: GREEN", out)

    def test_tip_names_the_whole_sha(self):
        self.record(self.tip_tree)
        rc, out = self.status("--tip", "budget-steward")
        self.assertEqual(rc, 0, out)
        self.assertIn("tip " + self.tip, out)

    def test_plain_status_with_no_evidence_is_untested_2(self):
        rc, out = self.status("budget-steward")
        self.assertEqual(rc, 2, out)
        self.assertIn("UNTESTED", out)

    def test_plain_status_with_a_failed_run_is_red_1(self):
        self.record(self.tip_tree, exit=1)
        rc, out = self.status("budget-steward")
        self.assertEqual(rc, 1, out)
        self.assertIn("RED", out)

    # ---- the table
    def test_all_leaves_it_out_so_an_unreachable_gitea_cannot_fail_it(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("cms", str(SCRIPT))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("cms", loader))
        loader.exec_module(mod)
        self.assertIn("budget-steward", mod.REPOS)
        self.assertNotIn("budget-steward", mod.ORDER)

    def test_the_usage_line_names_it(self):
        rc, out = self.status("--merge-gate")
        self.assertEqual(rc, 1, out)
        self.assertIn("budget-steward", out)

    def test_a_plain_pr_flag_is_still_a_usage_error(self):
        rc, out = self.status("budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("usage:", out)


if __name__ == "__main__":
    unittest.main()
