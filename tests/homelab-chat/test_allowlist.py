"""The homelab-chat PreToolUse hook (dot_local/share/agent-harness/hooks/homelab_chat_allowlist.py), run as a process the way Claude Code runs it:
the hook JSON on stdin, exit 0 to allow, exit 2 and a reason on stderr to deny. The payloads have the shape of recorded PreToolUse input (tests/agent-kill-guard/fixtures).
The seat file's hook command (fail-closed on a missing script or python3) is tested in tests/t3-hub, HomelabChatSeatTest. check_payloads.py is the same process run over payloads/.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / "dot_local/share/agent-harness/hooks/homelab_chat_allowlist.py"
BOT = "~/git/cartwmic-homelab-v2/scripts/homelab-bot/homelab_bot.py"
BOT_ABS = "/home/cartwmic/git/cartwmic-homelab-v2/scripts/homelab-bot/homelab_bot.py"
COORDINATOR = "mcp:5496141f-7b8c-4f3c-afd1-d87a70d69c56"
MULTILINE = "Done: added it.\nPrice was $5 \\o/ & more; (ok) > fine"  # a chat reply: newline, $, backslash, & ; ( ) >


def call(tool, **args):
    return {"session_id": "s", "cwd": "/x", "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": args, "tool_use_id": "t"}


def bash(command):
    return call("Bash", command=command, description="x")


class HookCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.log = Path(self._tmp.name) / "state" / "hook.jsonl"

    def run_hook(self, stdin, log=None):
        r = subprocess.run([sys.executable, "-I", str(HOOK)], input=stdin if isinstance(stdin, str) else json.dumps(stdin), capture_output=True, text=True, timeout=30,
                           env=dict(os.environ, HOMELAB_CHAT_HOOK_LOG=str(log or self.log)))
        return r.returncode, r.stderr

    def allowed(self, payload):
        rc, err = self.run_hook(payload)
        self.assertEqual(rc, 0, (payload, err))

    def denied(self, payload, why=None):
        rc, err = self.run_hook(payload)
        self.assertEqual(rc, 2, payload)
        self.assertIn("homelab-chat tool list: denied.", err, "a denial comes from the hook and states its reason (not from python failing to find the script)")
        if why:
            self.assertIn(why, err)


class BashTest(HookCase):
    def test_every_listed_bot_verb_passes_in_both_path_forms(self):
        verbs = ["sonarr lookup 'Graham Norton'", "sonarr add --tvdb-id 80660", "sonarr monitor 5 --all-seasons", "sonarr episodes 5 --season 2", "sonarr episode-search 11 12",
                 "radarr lookup Dune", "radarr add --tmdb-id 5", "radarr monitor 3 --search", "readarr lookup --kind ebook 'The Good Daughter'", "readarr add --kind ebook --foreign-book-id 1", "readarr kindle --book-id 3474 --to reader@kindle.com",
                 "yamtrack lookup --type book --query 'Slaughterhouse-Five'", "yamtrack add --type book --source hardcover --id 122240 --status Planning", "yamtrack status --type book --source hardcover --id 122240",
                 "queue", "download status", "download status Dune", "jellyfin search Dune",
                 "kube get pods -n sonarr", "kube describe pod x -n sonarr", "kube logs x -n sonarr --tail 50", "kube top pods", "kube events -n sonarr"]
        for path in (BOT, BOT_ABS):
            for verb in verbs:
                with self.subTest(path=path, verb=verb):
                    self.allowed(bash("python3 %s %s" % (path, verb)))

    def test_readarr_kindle_to_passes_unquoted(self):
        self.allowed(bash("python3 %s readarr kindle --book-id 3474 --to reader@kindle.com" % BOT))

    def test_readarr_kindle_to_passes_quoted(self):
        self.allowed(bash("python3 %s readarr kindle --book-id 3474 --to 'reader@kindle.com'" % BOT))

    def test_unlisted_yamtrack_verbs_are_refused(self):
        for verb in ("yamtrack delete --type book --source hardcover --id 1", "yamtrack edit --type book --source hardcover --id 1", "yamtrack", "yamtrack import x"):
            with self.subTest(verb=verb):
                self.denied(bash("python3 %s %s" % (BOT, verb)))

    def test_the_event_id_prefix_passes_only_with_digits(self):
        self.allowed(bash("HOMELAB_BOT_EVENT_ID=123456 python3 %s queue" % BOT))
        for bad in ("HOMELAB_BOT_EVENT_ID=12a", "HOMELAB_BOT_EVENT_ID=", "HOMELAB_BOT_EVENT_ID=1;2", "OTHER_ID=1", "PYTHONPATH=/x", "HOMELAB_BOT_EVENT_ID=1 HOMELAB_BOT_EVENT_ID=2"):
            with self.subTest(bad=bad):
                self.denied(bash("%s python3 %s queue" % (bad, BOT)))

    def test_verbs_off_the_list_are_refused_with_and_without_apply(self):
        for verb in ("board add t --note n", "tracker list", "tracker get x", "files ls /x", "files get /x", "sonarr rolling 5 --on", "arr preferences", "arr preferences --apply",
                     "kube delete pod x", "kube apply -f x", "kube exec x -- sh", "kube", "download", "download cancel 1", "jellyfin delete 1", "readarr monitor 1", "radarr episodes 1", "bogus", ""):
            with self.subTest(verb=verb):
                self.denied(bash(("python3 %s %s" % (BOT, verb)).strip()))

    def test_the_script_path_and_the_interpreter_must_be_exact(self):
        for command in ("python3 homelab_bot.py queue", "python3 /tmp/homelab_bot.py queue", "python3 %s/../homelab_bot.py queue" % BOT.rsplit("/", 1)[0], "python3 -c 'print(1)'",
                        "python3 -I %s queue" % BOT, "python %s queue" % BOT, "python3 %s2 queue" % BOT, "sh %s queue" % BOT, "/usr/bin/python3 %s queue" % BOT, "python3", "%s queue" % BOT,
                        "python3 ~root/git/cartwmic-homelab-v2/scripts/homelab-bot/homelab_bot.py queue", "python3 /home/other/git/cartwmic-homelab-v2/scripts/homelab-bot/homelab_bot.py queue"):
            with self.subTest(command=command):
                self.denied(bash(command))

    def test_other_commands_are_refused(self):
        for command in ("kubectl delete pod x", "git -C ~/git/cartwmic-homelab-v2 push", "rm -rf ~", "ls", "cat /etc/passwd", "curl http://x", "ssh x ls", "op read op://x/y", "env", "echo hi", "coordinator lead send HomelabChat hi",
                        "coordinator ledger open x", "ledger open x", "claude -p x"):
            with self.subTest(command=command):
                self.denied(bash(command))

    def test_shell_injection_forms_are_refused(self):
        injections = [
            "python3 %s queue; rm -rf ~", "python3 %s queue;rm x", "python3 %s queue && rm x", "python3 %s queue || rm x", "python3 %s queue | tee /tmp/x", "python3 %s queue & sleep 1",
            "python3 %s queue > /tmp/x", "python3 %s queue >> /tmp/x", "python3 %s queue < /etc/passwd", "python3 %s queue 2>&1", "python3 %s queue\nrm x", "python3 %s queue\rrm x",
            "python3 %s queue `id`", "python3 %s queue $(id)", "python3 %s queue $HOME", "python3 %s queue ${HOME}", "python3 %s queue $((1+1))", "python3 %s queue <(id)", "python3 %s queue >(tee x)",
            "python3 %s queue (id)", "(python3 %s queue)", "{ python3 %s queue; }", "python3 %s queue {a,b}", "python3 %s queue *", "python3 %s queue ?", "python3 %s queue [a]", "python3 %s queue *(e:id:)",
            "python3 %s queue =(id)", "python3 %s queue \\; id", "python3 %s queue !!", "python3 %s queue # comment", "python3 %s queue ^x", "FOO=1 python3 %s queue", "python3 %s queue &",
            "python3 %s queue 'unterminated", 'python3 %s queue "unterminated', "python3 %s \"$(id)\"", "python3 %s sonarr lookup \"a $HOME\"", "python3 %s sonarr lookup \"a `id`\"",
            "python3 %s sonarr lookup \"a \\\" b\"", "python3 %s sonarr lookup \"a\nb\"",
        ]
        for template in injections:
            command = template % BOT if "%s" in template else template
            with self.subTest(command=command):
                self.denied(bash(command))

    def test_quoted_text_passes_where_it_is_literal(self):
        self.allowed(bash("python3 %s sonarr lookup \"Tom & Jerry\"" % BOT))
        self.allowed(bash("python3 %s sonarr lookup 'Law & Order; SVU (1999) > 2000 | x'" % BOT))
        self.allowed(bash("python3 %s sonarr lookup '%s'" % (BOT, MULTILINE)))
        self.allowed(bash("python3 %s sonarr lookup \"a;b|c<d>e(f)\"" % BOT))

    def test_the_same_text_in_double_quotes_or_bare_is_refused(self):
        self.denied(bash("python3 %s sonarr lookup \"%s\"" % (BOT, MULTILINE)))
        self.denied(bash("python3 %s sonarr lookup %s" % (BOT, MULTILINE)))
        for ch in ("$", "`", "\\", "\n"):
            with self.subTest(ch=repr(ch)):
                self.denied(bash("python3 %s sonarr lookup \"a%sb\"" % (BOT, ch)))
                self.denied(bash("python3 %s sonarr lookup a%sb" % (BOT, ch)))

    def test_a_single_quote_cannot_be_closed_early_to_inject(self):
        self.denied(bash("python3 %s sonarr lookup 'x'; rm -rf ~; echo 'y'" % BOT))
        self.denied(bash("python3 %s sonarr lookup 'x'$(id)'y'" % BOT))
        self.denied(bash("python3 %s sonarr lookup 'x' ; id" % BOT))

    def test_coordinator_lead_post(self):
        for command in ("coordinator lead post HomelabChat --key k --text hi", "coordinator lead post HomelabChat --key k --text=hi", "coordinator lead post HomelabChat --key=k --text='two words'",
                        "coordinator lead post HomelabChat --text hi --key k", "coordinator lead post HomelabChat --key k --text '%s'" % MULTILINE, "coordinator lead post HomelabChat --key k --text=\"Tom & Jerry\"",
                        "COORDINATOR_EVENT_ID=ev-123:abc coordinator lead post HomelabChat --key k --text hi", "coordinator lead post HomelabChat --key k"):
            with self.subTest(command=command):
                self.allowed(bash(command))

    def test_coordinator_lead_post_refusals(self):
        for command in ("coordinator lead post HomelabChat --key k --text hi --buttons 'A,B'", "coordinator lead post HomelabChat --key k --text hi --reply-to x", "coordinator lead post Homelab --key k --text hi",
                        "coordinator lead post homelabchat --key k --text hi", "coordinator lead post Board --key k --text hi", "coordinator lead post HomelabChat --key k --key j --text hi",
                        "coordinator lead post HomelabChat --key", "coordinator lead post HomelabChat k hi", "coordinator lead post HomelabChat --key k --text \"$HOME\"", "coordinator lead post HomelabChat --key k --text \"%s\"" % MULTILINE,
                        "coordinator lead post HomelabChat --key k --text hi; coordinator lead send Board x", "coordinator lead post HomelabChat --key k --text hi && id", "coordinator lead post HomelabChat --key k --text `id`",
                        "COORDINATOR_EVENT_ID= coordinator lead post HomelabChat --key k --text hi", "COORDINATOR_EVENT_ID=a;b coordinator lead post HomelabChat --key k --text hi",
                        "HOMELAB_BOT_EVENT_ID=1 coordinator lead post HomelabChat --key k --text hi", "COORDINATOR_EVENT_ID=1 python3 %s queue" % BOT, "coordinator lead", "coordinator lead post",
                        "/usr/bin/coordinator lead post HomelabChat --key k --text hi", "coordinator lead status HomelabChat"):
            with self.subTest(command=command):
                self.denied(bash(command))

    def test_bash_without_a_command_is_refused(self):
        self.denied(call("Bash"))
        self.denied(call("Bash", command=["queue"]))
        self.denied(bash(""))
        self.denied(bash("   "))


class OtherToolsTest(HookCase):
    def test_the_listed_tools_pass(self):
        for tool, args in (("WebSearch", {"query": "x"}), ("WebFetch", {"url": "https://x.test", "prompt": "p"}), ("ToolSearch", {"query": "select:mcp__hindsight__recall", "max_results": 1}),
                           ("mcp__hindsight__recall", {"query": "x"}), ("mcp__hindsight__reflect", {"query": "x"}), ("mcp__hindsight__retain", {"content": "x"})):
            with self.subTest(tool=tool):
                self.allowed(call(tool, **args))

    def test_t3_thread_send_passes_only_to_the_coordinator_thread(self):
        send = "mcp__t3-code__t3_thread_send"
        self.allowed(call(send, threadId=COORDINATOR, message="m"))
        self.allowed(call(send, threadId=COORDINATOR, message="m", mode="steer", clientRequestId="c"))
        for args in ({"threadId": "mcp:launch:other", "message": "m"}, {"threadId": COORDINATOR + "x", "message": "m"}, {"message": "m"}, {"threadId": None, "message": "m"}, {"threadId": [COORDINATOR], "message": "m"},
                     {"threadId": COORDINATOR, "message": "m", "environmentId": "other-machine"},
                     {"threadId": COORDINATOR, "message": "m", "mode": "restart"}, {"threadId": COORDINATOR, "message": "m", "freshContext": True}):
            with self.subTest(args=args):
                self.denied(call(send, **args))

    def test_everything_else_is_refused(self):
        for tool, args in (("Edit", {"file_path": "/x", "old_string": "a", "new_string": "b"}), ("Write", {"file_path": "/x", "content": "c"}), ("Read", {"file_path": "/etc/passwd"}),
                           ("Read", {"file_path": "/home/cartwmic/git/coordinator/leads/homelab-chat.md"}), ("Agent", {"prompt": "p"}), ("Grep", {"pattern": "x"}), ("Glob", {"pattern": "*"}),
                           ("Skill", {"skill": "x"}), ("NotebookEdit", {}), ("TodoWrite", {}), ("Monitor", {}), ("Workflow", {}), ("AskUserQuestion", {}), ("SomethingNew", {}),
                           ("mcp__t3-code__delegate_task", {"task": "t"}), ("mcp__t3-code__schedule_task", {}), ("mcp__t3-code__t3_thread_launch", {}), ("mcp__t3-code__create_threads", {}),
                           ("mcp__t3-code__t3_thread_read", {"threadId": COORDINATOR}), ("mcp__t3-code__t3_thread_list", {}), ("mcp__t3-code__task_cancel", {}),
                           ("mcp__hindsight__delete_bank", {}), ("mcp__hindsight__clear_memories", {}), ("mcp__hindsight__sync_retain", {}), ("mcp__shartifacts__create_artifact", {}),
                           ("bash", {"command": "ls"}), ("WebFetchX", {})):
            with self.subTest(tool=tool):
                self.denied(call(tool, **args), why="not on the homelab-chat tool list")


class FailClosedTest(HookCase):
    def test_input_it_cannot_read_is_refused(self):
        for stdin in ("", "not json", "[]", "null", '"Bash"', "{}", '{"tool_name": "Bash"}', '{"tool_name": 5, "tool_input": {}}', '{"tool_name": "WebSearch", "tool_input": []}', '{"tool_name": "WebSearch"}', "\x00"):
            with self.subTest(stdin=stdin):
                self.denied(stdin)


class LogTest(HookCase):
    def lines(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    def test_each_decision_adds_one_line_with_tool_decision_and_reason(self):
        self.allowed(bash("python3 %s queue" % BOT))
        self.denied(call("Edit", file_path="/x"))
        self.denied(bash("rm -rf ~"))
        lines = self.lines()
        self.assertEqual([(l["tool"], l["decision"]) for l in lines], [("Bash", "allowed"), ("Edit", "denied"), ("Bash", "denied")])
        self.assertEqual(lines[0]["reason"], "bot:queue")
        for l in lines:
            self.assertEqual(set(l), {"ts", "tool", "decision", "reason"})
            self.assertRegex(l["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_the_log_never_holds_the_command_or_a_message(self):
        secret = "S3CRET-TOKEN-xyz"
        self.allowed(bash("python3 %s sonarr lookup '%s'" % (BOT, secret)))
        self.denied(bash("python3 %s queue; echo %s" % (BOT, secret)))
        self.denied(bash("python3 %s board add %s" % (BOT, secret)))
        self.allowed(bash("coordinator lead post HomelabChat --key k --text '%s'" % secret))
        self.allowed(call("mcp__t3-code__t3_thread_send", threadId=COORDINATOR, message=secret))
        self.denied(call("mcp__t3-code__t3_thread_send", threadId=secret, message=secret))
        self.denied(call("Edit", file_path=secret, command=secret))
        self.assertNotIn(secret, self.log.read_text())

    def test_a_log_that_cannot_be_written_changes_no_decision(self):
        blocked = Path(self._tmp.name) / "file"
        blocked.write_text("x")
        rc, err = self.run_hook(bash("python3 %s queue" % BOT), log=blocked / "no" / "hook.jsonl")
        self.assertEqual(rc, 0)
        self.assertIn("log not written", err)
        rc, err = self.run_hook(call("Edit"), log=blocked / "no" / "hook.jsonl")
        self.assertEqual(rc, 2)

    def test_the_default_log_is_under_the_state_folder(self):
        state = Path(self._tmp.name) / "xdg"
        env = {k: v for k, v in os.environ.items() if k != "HOMELAB_CHAT_HOOK_LOG"}
        r = subprocess.run([sys.executable, "-I", str(HOOK)], input=json.dumps(call("WebSearch", query="x")), capture_output=True, text=True, env=dict(env, XDG_STATE_HOME=str(state)), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((state / "homelab-chat" / "hook.jsonl").read_text())["tool"], "WebSearch")


class PayloadsTest(unittest.TestCase):
    def test_the_recorded_payloads_do_what_their_names_say(self):
        r = subprocess.run([sys.executable, "-I", str(Path(__file__).parent / "check_payloads.py")], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.count("REFUSED"), 5)
        self.assertEqual(r.stdout.count(" allowed "), 3)


if __name__ == "__main__":
    unittest.main()
