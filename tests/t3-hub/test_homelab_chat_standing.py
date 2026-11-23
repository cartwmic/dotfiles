"""Standing check on the homelab chat seat (ledger ask #1233, guard G5): the seat can only do what the golden list says, and CI fails when that stops being true.

The tool limit is Michael's requirement (ask #1228; tool set decision #3441). Everything here goes through the real files: the seat settings file rendered from its
chezmoi template (`dot_claude/fleet/seat-homelab-chat.json.tmpl`), the hook command that file names, and the instance's launch arguments rendered by the T3 settings
script. Nothing is a hand copy of the template output.

  1. the denial set (kubectl delete, git push, board add, `queue; rm -rf ~`, Edit, Write, delegate_task, schedule_task, t3_thread_send to another thread) is refused by that command
  2. what the command allows, over every tool name, bot verb and other Bash command in the golden file's `seen` lists, equals the golden `allowed` list; the hook's own constants equal it too,
     so a tool, verb, thread or post flag added to the hook without a change to homelab_chat_allowed.golden.json fails; and the check fails on a hook that gained one (tested on a copy)
  3. the instance's launch arguments keep --strict-mcp-config and an MCP file that holds hindsight only

Runs in CI as the `tests` job of .github/workflows/ci.yml: scripts/ci-linux.sh runs tests/t3-hub.
"""
import importlib.util
import json
import shlex
import shutil
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import test_t3_hub as hub

HERE = Path(__file__).resolve().parent
GOLDEN = json.loads((HERE / "homelab_chat_allowed.golden.json").read_text())
ALLOWED, SEEN = GOLDEN["allowed"], GOLDEN["seen"]
SEND = ALLOWED["t3_thread_send"]["tool"]
THREADS = ALLOWED["t3_thread_send"]["threads"]
COORDINATOR = THREADS[0]
SCHEDULE = ALLOWED["schedule"]
BOT = "~/git/cartwmic-homelab-v2/scripts/homelab-bot/homelab_bot.py"
DENIAL_SET = {
    "kubectl delete pod x": hub.bash_call("kubectl delete pod x"),
    "git -C ~/git/cartwmic-homelab-v2 push": hub.bash_call("git -C ~/git/cartwmic-homelab-v2 push"),
    "homelab_bot.py board add t --note n": hub.bash_call("python3 %s board add t --note n" % BOT),
    "homelab_bot.py queue; rm -rf ~": hub.bash_call("python3 %s queue; rm -rf ~" % BOT),
    "Edit": {"tool_name": "Edit", "tool_input": {"file_path": "/x", "old_string": "a", "new_string": "b"}},
    "Write": {"tool_name": "Write", "tool_input": {"file_path": "/x", "content": "c"}},
    "delegate_task": {"tool_name": "mcp__t3-code__delegate_task", "tool_input": {"task": "t"}},
    "schedule_task": {"tool_name": "mcp__t3-code__schedule_task", "tool_input": {"prompt": "p"}},
    "run_scheduled_task_now": {"tool_name": "mcp__t3-code__run_scheduled_task_now", "tool_input": {}},
    "a wake of another lead": hub.bash_call("coordinator jobs wake Homelab --at 2026-12-01T17:00:00Z --text t --id wake-HomelabChat-x"),
    "an approval under another grant": hub.bash_call("~/%s/%s approve-schedule wake-HomelabChat-x --cron '0 9 * * 1' --zone UTC --grant 38 --why w" % (SCHEDULE["state_dirs"][0], SCHEDULE["ledger_script"])),
    "t3_thread_send to another thread": {"tool_name": SEND, "tool_input": {"threadId": "mcp:launch:someone-else", "message": "m"}},
}


class Seat:
    """The real hook command from the rendered seat file, with the hook script installed where that command looks for it."""

    def __init__(self, script=None):
        self.env = hub.fleet_env("personal")
        seat = json.loads(self.env.render("dot_claude/fleet/seat-homelab-chat.json.tmpl"))
        self.command = seat["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.target = self.env.home / ".local/share/agent-harness/hooks/homelab_chat_allowlist.py"
        self.target.parent.mkdir(parents=True)
        if script is None:
            shutil.copy(hub.HOOK_SCRIPT, self.target)
        else:
            self.target.write_text(script)

    def close(self):
        self.env.close()

    def allows(self, payload):
        """True when the command exits 0, False when it exits 2 with the hook's reason; anything else is an error."""
        rc, err = hub.HomelabChatSeatTest().run_hook_command(self.command, dict(payload, hook_event_name="PreToolUse"), home=self.env.home)
        if rc == 0:
            return True
        if rc != 2 or "homelab-chat tool list: denied." not in err:
            raise AssertionError("the hook command exited %s without a denial from the hook: %s" % (rc, err))
        return False

    def which_allowed(self, probes):
        """The probes (name, payload) the command allows. The calls are independent processes, so they run eight at a time."""
        with ThreadPoolExecutor(8) as pool:
            answers = list(pool.map(lambda p: self.allows(p[1]), probes))
        return {name for (name, _), ok in zip(probes, answers) if ok}

    def allowed_tools(self):
        probes = [(t, {"tool_name": t, "tool_input": {"query": "x"}}) for t in SEEN["tools"] if t not in ("Bash", SEND)]
        return self.which_allowed(probes + [(SEND, {"tool_name": SEND, "tool_input": {"threadId": COORDINATOR, "message": "m"}})])

    def allowed_bash_commands(self):
        """The Bash commands in the golden file's `seen` list and its allowed `bash_commands` that the command allows. Only the golden allowed ones may run: any other that does is a new command form."""
        return self.which_allowed([(c, hub.bash_call(c)) for c in SEEN["bash_commands"] + ALLOWED["bash_commands"]])

    def allowed_threads(self):
        probes = THREADS + ["mcp:launch:someone-else", ""] + [t + "x" for t in THREADS]
        return self.which_allowed([(t, {"tool_name": SEND, "tool_input": {"threadId": t, "message": "m"}}) for t in probes])

    def allowed_bot_verbs(self):
        return self.which_allowed([(v, hub.bash_call("python3 %s %s x" % (BOT, v))) for v in SEEN["bot_verbs"]])

    def allowed_post_flags(self):
        post = "coordinator lead post %s" % ALLOWED["post"]["lead"]
        flags = self.which_allowed([(f, hub.bash_call("%s %s v" % (post, f))) for f in ("--key", "--text", "--buttons", "--reply-to", "--thread", "--channel", "--lead", "--as", "--force")])
        other = self.which_allowed([("a", hub.bash_call("coordinator lead post Homelab --key k --text t")), ("b", hub.bash_call("coordinator lead send %s hi" % ALLOWED["post"]["lead"]))])
        return flags, bool(other)


def differences(seat):
    """What the command allows that the golden list does not, and the other way round; empty when they agree."""
    found = []
    for name, got, want in (("tools", seat.allowed_tools(), set(ALLOWED["tools"]) | {SEND}),
                            ("t3_thread_send threads", seat.allowed_threads(), set(ALLOWED["t3_thread_send"]["threads"])),
                            ("bot verbs", seat.allowed_bot_verbs(), set(ALLOWED["bot_verbs"]))):
        found += ["%s: allowed but not in the golden list: %s" % (name, sorted(got - want))] * bool(got - want)
        found += ["%s: in the golden list but refused: %s" % (name, sorted(want - got))] * bool(want - got)
    got, want = seat.allowed_bash_commands(), set(ALLOWED["bash_commands"])
    found += ["bash commands: allowed but not in the golden list: %s" % sorted(got - want)] * bool(got - want)
    found += ["bash commands: in the golden list but refused: %s" % sorted(want - got)] * bool(want - got)
    flags, other = seat.allowed_post_flags()
    found += ["post flags: allowed %s, golden %s" % (sorted(flags), ALLOWED["post"]["flags"])] * (sorted(flags) != sorted(ALLOWED["post"]["flags"]))
    found += ["a post to another lead, or another coordinator lead command, is allowed"] * other
    return found


def hook_module(path):
    spec = importlib.util.spec_from_file_location("homelab_chat_hook_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def launch_args(script):
    """The seat instance's launch arguments, from the rendered T3 settings script."""
    inst = json.loads(hub.run_script(script, hub.FIXTURE))["providerInstances"][hub.HOMELAB_CHAT]
    return shlex.split(inst["config"]["launchArgs"])


def launch_args_problems(args, home):
    """What is wrong with the launch arguments; empty when --strict-mcp-config is there and the one MCP file is the seat's own."""
    if args.count("--strict-mcp-config") != 1:
        return ["no --strict-mcp-config: the seat would load every MCP server of the machine"]
    if args.count("--mcp-config") != 1:
        return ["not exactly one --mcp-config"]
    mcp = Path(args[args.index("--mcp-config") + 1])
    return [] if (mcp.name, str(mcp.parent)) == ("mcp-homelab-chat.json", "%s/.claude/fleet" % home) else ["the MCP file is %s, not the seat's own" % mcp]


class StandingTest(unittest.TestCase):
    def test_the_denial_set_is_refused_by_the_command_in_the_rendered_seat_file(self):
        seat = Seat()
        try:
            for name, payload in DENIAL_SET.items():
                with self.subTest(call=name):
                    self.assertFalse(seat.allows(payload), "the homelab chat seat's hook command allowed: %s" % name)
            # the same command allows what the golden list allows, so the denials above are the hook's answer and not a broken command
            self.assertTrue(seat.allows(hub.bash_call("python3 %s queue" % BOT)))
            self.assertTrue(seat.allows({"tool_name": SEND, "tool_input": {"threadId": COORDINATOR, "message": "m"}}))
        finally:
            seat.close()

    def test_what_the_command_allows_is_exactly_the_golden_list(self):
        seat = Seat()
        try:
            self.assertEqual(differences(seat), [], "the hook's allowed list changed: Michael's tool set is pinned in tests/t3-hub/homelab_chat_allowed.golden.json (ask #1228); change that file only with his approval")
        finally:
            seat.close()

    def test_the_hooks_constants_equal_the_golden_list(self):
        hook = hook_module(hub.HOOK_SCRIPT)
        verbs = {"%s %s" % (v, a) if a else v for v, actions in hook.BOT_VERBS.items() for a in (actions or (None,))}
        self.assertEqual(sorted(hook.SIMPLE_TOOLS), sorted(ALLOWED["tools"]))
        self.assertEqual(hook.SEND_TOOL, SEND)
        self.assertEqual(list(hook.COORDINATOR_THREADS), ALLOWED["t3_thread_send"]["threads"])
        self.assertEqual(sorted(verbs), sorted(ALLOWED["bot_verbs"]))
        self.assertEqual((hook.LEAD, sorted(hook.POST_FLAGS)), (ALLOWED["post"]["lead"], sorted(ALLOWED["post"]["flags"])))
        self.assertEqual((hook.LEAD, hook.JOB_PREFIX, hook.GRANT, list(hook.STATE_DIRS), hook.LEDGER_SCRIPT, sorted(hook.WAKE_FLAGS), sorted(hook.APPROVE_FLAGS)),
                         (SCHEDULE["lead"], SCHEDULE["job_id_prefix"], SCHEDULE["grant"], SCHEDULE["state_dirs"], SCHEDULE["ledger_script"], SCHEDULE["wake_flags"], SCHEDULE["approve_flags"]))

    def test_the_golden_file_is_consistent(self):
        self.assertTrue(set(ALLOWED["tools"]) | {SEND} <= set(SEEN["tools"]) | {SEND})
        self.assertTrue(set(ALLOWED["bot_verbs"]) <= set(SEEN["bot_verbs"]))
        self.assertFalse(set(ALLOWED["bash_commands"]) & set(SEEN["bash_commands"]))
        self.assertTrue(SCHEDULE["job_id_prefix"].startswith("wake-%s-" % SCHEDULE["lead"]))
        self.assertTrue({"mcp__t3-code__schedule_task", "mcp__t3-code__run_scheduled_task_now"} <= set(SEEN["tools"]) - set(ALLOWED["tools"]))
        for names in (ALLOWED["tools"], ALLOWED["bot_verbs"], ALLOWED["bash_commands"], SEEN["tools"], SEEN["bot_verbs"], SEEN["bash_commands"]):
            self.assertEqual(len(names), len(set(names)))

    def test_the_check_fails_on_a_hook_that_gained_a_tool_a_verb_a_thread_or_a_flag(self):
        """Break the hook (a copy under the same command): each addition must be reported. A check that passes here would pass on any hook."""
        original = hub.HOOK_SCRIPT.read_text()
        for name, old, new, expect in (
                ("a tool", 'SIMPLE_TOOLS = ("WebSearch",', 'SIMPLE_TOOLS = ("Read", "WebSearch",', "tools: allowed but not in the golden list: ['Read']"),
                ("a bot verb", '    "queue": None,', '    "queue": None,\n    "board": ("add",),', "bot verbs: allowed but not in the golden list: ['board add']"),
                ("a thread", 'COORDINATOR_THREADS = (', 'COORDINATOR_THREADS = ("mcp:launch:someone-else", ',
                 "t3_thread_send threads: allowed but not in the golden list: ['mcp:launch:someone-else']"),
                ("a post flag", 'POST_FLAGS = ("--key", "--text")', 'POST_FLAGS = ("--key", "--text", "--buttons")', "post flags: allowed ['--buttons', '--key', '--text']"),
                ("an action", '"kube": ("get",', '"kube": ("delete", "get",', "bot verbs: allowed but not in the golden list: ['kube delete']"),
                ("a new Bash command form", '    raise Deny("Bash runs only homelab_bot.py calls', '    if words[:2] == ["kubectl", "get"]:\n        return "kubectl"\n    raise Deny("Bash runs only homelab_bot.py calls',
                 "bash commands: allowed but not in the golden list: ['kubectl get pods', 'kubectl get pods -A']"),
                ("a new rule for a tool outside the constants", '    if tool == "Bash":', '    if tool == "MultiEdit":\n        return tool, "multiedit"\n    if tool == "Bash":',
                 "tools: allowed but not in the golden list: ['MultiEdit']"),
                ("a wake of another lead", "    if rest[:1] != [LEAD]:", "    if False:", "bash commands: allowed but not in the golden list: ['coordinator jobs wake Homelab "),
                ("a wake without the seat's id prefix", '    job_id(got.get("--id"), shape)\n', "", "coordinator jobs wake HomelabChat --at 2026-12-01T17:00:00Z --text t --id wake-Homelab-x"),
                ("a remove of any job", "        job_id(rest[1], shape)\n", "", "coordinator jobs remove board-reconcile --words w"),
                ("an approval under another grant", 'or got["--grant"] != GRANT', "", "--grant 38 --why w"),
                ("an approval of any job", "    job_id(rest[0], shape)\n    got = flags_of(rest[1:], APPROVE_FLAGS", "    got = flags_of(rest[1:], APPROVE_FLAGS", "approve-schedule watchdog:leads"),
                ("another jobs verb", '    if rest == ["list"]:', '    if rest[:1] in (["list"], ["pause"]):', "coordinator jobs pause wake-HomelabChat-x --words w"),
                ("another ledger verb", 'words[1] == "approve-schedule"', 'words[1] in ("approve-schedule", "revoke-schedule")', "revoke-schedule wake-HomelabChat-x")):
            with self.subTest(change=name):
                self.assertIn(old, original)
                seat = Seat(original.replace(old, new, 1))
                try:
                    self.assertTrue(any(expect in line for line in differences(seat)), (name, differences(seat)))
                finally:
                    seat.close()

    def test_the_launch_arguments_keep_strict_mcp_config_and_a_hindsight_only_file(self):
        script, home = hub.LinuxSettingsTest().render("linux")
        args = launch_args(script)
        self.assertEqual(launch_args_problems(args, home), [])
        mcp = Path(args[args.index("--mcp-config") + 1])
        settings = Path(args[args.index("--settings") + 1])
        self.assertEqual(settings.name, "seat-homelab-chat.json")
        for profile in ("personal", "axon-work-computer"):
            env = hub.fleet_env(profile)
            try:
                servers = json.loads(env.render("dot_claude/fleet/%s.tmpl" % mcp.name))["mcpServers"]
                self.assertEqual(list(servers), ["hindsight"], profile)
            finally:
                env.close()

    def test_the_check_fails_on_launch_arguments_without_strict_mcp_config_or_with_a_wider_file(self):
        script, home = hub.LinuxSettingsTest().render("linux")
        for name, old, new in (("no strict flag", " --strict-mcp-config", ""), ("the shared file", "mcp-homelab-chat.json", "mcp.json")):
            with self.subTest(change=name):
                self.assertIn(old, script)
                self.assertNotEqual(launch_args_problems(launch_args(script.replace(old, new)), home), [])


if __name__ == "__main__":
    unittest.main()
