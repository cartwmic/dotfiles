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
        if self.path.startswith(API + "/pulls/") and "/reviews" in self.path:
            parts = self.path.split("?")[0].split("/reviews")[1].strip("/").split("/")   # [] (the reviews), or [id, "comments"]
            reviews = state.get("reviews", [])
            if parts == [""]:
                return self.send(200, [{"id": r["id"], "state": r.get("state", "COMMENT")} for r in reviews])
            review = next((r for r in reviews if str(r["id"]) == parts[0]), None)
            return self.send(200, review["comments"]) if review else self.send(404, {"message": "no such review"})
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
                    "CI_MAIN_STATUS_GITEA_TOKEN": TOKEN, "CI_MAIN_STATUS_KGATE_LOG": str(self.kgate_log),
                    "CI_MAIN_STATUS_GITEA_LOG": str(t / "gitea.jsonl")}
        self.gitea_log = t / "gitea.jsonl"
        self.threads_log = t / "threads.jsonl"
        self.env["CI_MAIN_STATUS_THREADS_LOG"] = str(self.threads_log)

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
        if self.gitea_log.exists():
            self.assertNotIn(TOKEN, self.gitea_log.read_text())   # nor logged
        return r.returncode, out

    def logged(self):
        return [json.loads(line) for line in self.gitea_log.read_text().splitlines()] if self.gitea_log.exists() else []

    # ---- review threads (the PR gate runs ci-main-status --threads after its own evidence passes)
    def comment(self, resolved=False, path="app.ts", position=4, body="Rename this\nplease", **extra):
        return {"path": path, "original_position": position, "body": body, "html_url": f"http://gitea/pulls/7#issuecomment-{path}{position}",
                "resolver": {"login": "someone"} if resolved else None, **extra}

    def reviews(self, *reviews):
        self.server.state["reviews"] = [{"id": i + 1, **r} for i, r in enumerate(reviews)]

    def test_a_pass_with_no_review_comments_prints_the_threads_line_too(self):
        self.record(self.head_tree)
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn("cartwmic/budget-steward#7: GREEN  no unresolved review threads", out)

    def test_an_unresolved_conversation_refuses_the_gate_and_is_listed(self):
        self.record(self.head_tree)
        self.reviews({"comments": [self.comment()]})
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertTrue(out.startswith("budget-steward: RED"), out)   # the verdict line is first, and it is not GREEN
        self.assertIn("the evidence passed (kgate kgate-1 exit 0", out)
        self.assertIn("cartwmic/budget-steward#7: RED  1 unresolved review thread", out)
        self.assertEqual([r["verdict"] for r in self.logged()], ["RED"])   # the gitea.jsonl row says RED too, never GREEN with exit 1
        self.assertEqual(self.logged()[0]["exit"], 1)
        self.assertIn("    app.ts  Rename this  http://gitea/pulls/7#issuecomment-app.ts4", out)

    def test_the_threads_log_gets_one_line_per_run_for_the_gate_and_the_standalone_check(self):
        self.record(self.head_tree)
        self.reviews({"comments": [self.comment()]})
        self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.status("--threads", "budget-steward", "7")
        rows = [json.loads(line) for line in self.threads_log.read_text().splitlines()]
        self.assertEqual([(r["repo"], r["pr"], r["forge"], r["result"], r["unresolved"]) for r in rows], [("cartwmic/budget-steward", 7, "gitea", "refused", 1)] * 2)
        self.assertEqual(rows[0]["threads"], [{"where": "app.ts", "url": "http://gitea/pulls/7#issuecomment-app.ts4"}])

    def test_an_unreadable_thread_state_is_error_in_the_gate_line_and_in_both_logs(self):
        self.record(self.head_tree)
        old = self.comment()
        del old["resolver"]
        self.reviews({"comments": [old]})
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertTrue(out.startswith("budget-steward: ERROR"), out)
        self.assertEqual([r["verdict"] for r in self.logged()], ["ERROR"])
        self.assertEqual([json.loads(line)["result"] for line in self.threads_log.read_text().splitlines()], ["error"])

    def test_a_review_with_many_comments_is_read_in_one_call_because_the_comments_endpoint_has_no_paging(self):
        self.record(self.head_tree)
        self.reviews({"comments": [self.comment(resolved=True, path=f"f{i}.ts") for i in range(120)]})
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len([c for c in self.server.calls if c.split("?")[0].endswith("/reviews/1/comments")]), 1)

    def test_a_resolved_conversation_passes(self):
        self.record(self.head_tree)
        self.reviews({"comments": [self.comment(resolved=True)]})
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 0, out)

    def test_a_reply_in_a_resolved_conversation_does_not_reopen_it_and_a_pending_draft_is_skipped(self):
        self.record(self.head_tree)
        self.reviews({"comments": [self.comment(resolved=True)]}, {"comments": [self.comment()]},
                     {"state": "PENDING", "comments": [self.comment(path="draft.ts")]})
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 0, out)

    def test_a_comment_with_no_resolver_field_fails_closed(self):
        self.record(self.head_tree)
        old = self.comment()
        del old["resolver"]
        self.reviews({"comments": [old]})
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR  cannot read review threads", out)

    def test_a_failed_pass_does_not_read_threads_and_the_standalone_check_reads_them(self):
        self.reviews({"comments": [self.comment()]})
        rc, out = self.status("--merge-gate", "budget-steward", "--pr", "7")   # no evidence: RED before any thread read
        self.assertEqual(rc, 1, out)
        self.assertFalse(any("/reviews" in c for c in self.server.calls))
        rc, out = self.status("--threads", "budget-steward", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("1 unresolved review thread", out)

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
        fake = Path(self.tmp.name) / "bin"
        fake.mkdir()
        (fake / "gh").write_text("#!/bin/sh\necho 'fake gh: no network' >&2\nexit 1\n")
        (fake / "gh").chmod(0o755)
        self.env["PATH"] = f"{fake}{os.pathsep}{self.env['PATH']}"
        self.env["CI_MAIN_STATUS_GITEA_API"] = "http://127.0.0.1:1/api/v1"   # nothing listens: reading it would be an ERROR
        rc, out = self.status("--all")
        self.assertNotIn("budget-steward", out)
        self.assertEqual(self.server.calls, [])
        self.assertEqual(self.logged(), [])   # --all never ran the Gitea gate

    # ---- the log: one structured line per call, never the token
    def test_a_pass_writes_one_line_with_its_evidence(self):
        self.record(self.head_tree)
        self.assertEqual(self.status("--merge-gate", "budget-steward", "--pr", "7")[0], 0)
        (row,) = self.logged()
        self.assertEqual((row["action"], row["repo"], row["pr"], row["sha"], row["tree"], row["verdict"], row["exit"]),
                         ("merge-gate", "cartwmic/budget-steward", 7, self.head, self.head_tree, "GREEN", 0))
        self.assertEqual(row["evidence"], {"gitea_status": None, "kgate_job": "kgate-1"})
        self.assertRegex(row["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIsInstance(row["duration_ms"], int)

    def test_a_gitea_status_is_the_evidence_it_names(self):
        self.server.state["status"][self.head] = {"state": "success", "total_count": 1}
        self.status("--merge-gate", "budget-steward", "--pr", "7")
        self.assertEqual(self.logged()[0]["evidence"], {"gitea_status": "success", "kgate_job": None})

    def test_a_refusal_writes_a_red_line(self):
        rc, _ = self.status("--merge-gate", "budget-steward", "--pr", "7")
        (row,) = self.logged()
        self.assertEqual((rc, row["verdict"], row["exit"], row["sha"]), (1, "RED", 1, self.head))
        self.assertEqual(row["evidence"], {"gitea_status": None, "kgate_job": None})

    def test_a_closed_pr_logs_its_head_and_no_evidence(self):
        self.server.state["pulls"]["7"]["state"] = "closed"
        self.status("--merge-gate", "budget-steward", "--pr", "7")
        (row,) = self.logged()
        self.assertEqual((row["verdict"], row["sha"], row["tree"], row["evidence"]), ("RED", self.head, None, None))

    def test_an_error_writes_a_line_and_not_the_token(self):
        self.env["CI_MAIN_STATUS_GITEA_API"] = "http://127.0.0.1:1/api/v1"
        rc, _ = self.status("--merge-gate", "budget-steward", "--pr", "7")
        (row,) = self.logged()
        self.assertEqual((rc, row["verdict"], row["exit"], row["pr"], row["sha"]), (1, "ERROR", 1, 7, None))
        self.assertIn("Gitea GET", row["detail"])

    def test_no_pr_number_logs_an_error(self):
        self.status("--merge-gate", "budget-steward")
        (row,) = self.logged()
        self.assertEqual((row["verdict"], row["exit"], row["pr"], row["action"]), ("ERROR", 1, None, "merge-gate"))

    def test_status_and_tip_log_their_action(self):
        self.record(self.tip_tree)
        self.status("budget-steward")
        self.status("--tip", "budget-steward")
        self.assertEqual([(r["action"], r["verdict"], r["exit"], r["sha"]) for r in self.logged()],
                         [("status", "GREEN", 0, self.tip), ("tip", "GREEN", 0, self.tip)])
        self.records.clear()
        self.assertEqual(self.status("budget-steward")[0], 2)
        self.assertEqual(self.logged()[-1]["verdict"], "UNTESTED")
        self.assertEqual(self.logged()[-1]["exit"], 2)

    def test_the_token_is_never_in_the_log_even_from_a_git_credential(self):
        counter = Path(self.tmp.name) / "fills"
        helper = Path(self.tmp.name) / "helper.sh"
        helper.write_text(f"#!/bin/sh\necho x >> {counter}\necho username=u\necho password={TOKEN}\n")
        helper.chmod(0o755)
        cfg = Path(self.tmp.name) / "gitconfig"
        cfg.write_text(f"[credential]\n\thelper = {helper}\n")
        self.env["GIT_CONFIG_GLOBAL"] = str(cfg)
        del self.env["CI_MAIN_STATUS_GITEA_TOKEN"]
        self.record(self.head_tree)
        self.assertEqual(self.status("--merge-gate", "budget-steward", "--pr", "7")[0], 0)
        self.assertEqual(len(self.logged()), 1)
        self.assertNotIn(TOKEN, self.gitea_log.read_text())
        self.assertEqual(len(counter.read_text().splitlines()), 1)   # the credential is filled once per run, not once per Gitea call
        self.assertGreater(len(self.server.calls), 1)

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
