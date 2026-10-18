"""Black-box tests of the Herdr source adapter (adapters/herdr).

Run (from the repository root):

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
        -s dot_local/share/agent-alert/tests -p 'test_herdr.py'

Two kinds of test, both against the deployed-layout copy that chezmoi archives
(adapters/ kept; nothing is applied):

* HookDirectTests run adapters/herdr/hook.py itself, as Herdr would, with
  crafted event environments, in chosen orders and concurrently, with a fake
  `herdr` binary that records any call (the hook must make none). This is how
  reordered and concurrent events are proved: Herdr cannot be told to run two
  hooks of one pane in a given order.
* HerdrServerTests start one real scratch Herdr 0.9.1 server at a time (its
  own HOME, config path and sockets, all under a short scratch directory),
  link and enable the plugin there, and drive it with `herdr pane
  report-agent` and `herdr pane close`. Nothing touches the live Herdr.

Every run uses scratch HOME, inbox, log and config paths.
"""

import datetime
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

HERDR_REQUIRED = shutil.which("herdr") is not None


def adapter_copy():
    """The deployed-layout copy with adapters/ kept."""
    return common.deployed_copy(delete_adapters=False)


def utc_now_string():
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


# ------------------------------------------------------------ direct hook runs

FAKE_HERDR = """#!/bin/sh
# Stand-in for the herdr binary: the hook must never call it, so any call is recorded.
echo "$*" >> "$FAKE_HERDR_CALLS"
exit 64
"""


class DirectHarness:
    """Runs the deployed hook.py with the environment Herdr would give it."""

    def __init__(self, test_case, copy=None):
        self.copy = copy or adapter_copy()
        self.hook = self.copy / "adapters" / "herdr" / "hook.py"
        self.scratch = common.Scratch(cli=self.copy / "core" / "agent-alert")
        test_case.addCleanup(self.scratch.cleanup)
        self.state_dir = self.scratch.root / "plugin-state"
        self.calls_file = self.scratch.root / "herdr-calls.txt"
        self.fake_herdr = self.scratch.root / "herdr"
        self.fake_herdr.write_text(FAKE_HERDR)
        self.fake_herdr.chmod(self.fake_herdr.stat().st_mode | stat.S_IXUSR)

    def environment(self, event, pane, status=None, agent="pi", workspace="w1", label="main-ws", released=False):
        name = event.replace(".", "_")
        data = {"type": name, "pane_id": pane, "workspace_id": workspace}
        if status is not None:
            data["agent_status"] = status
        if agent is not None:
            data["agent"] = agent
        if released:
            data["released"] = True
            data["final_status"] = "done"
        environment = self.scratch.env(
            HERDR_PLUGIN_ID="agent-alert",
            HERDR_PLUGIN_EVENT=event,
            HERDR_PLUGIN_EVENT_JSON=json.dumps({"event": name, "data": data}),
            HERDR_PANE_ID=pane,
            HERDR_WORKSPACE_ID=workspace,
            HERDR_PLUGIN_CONTEXT_JSON=json.dumps({"workspace_id": workspace, "workspace_label": label}),
            HERDR_PLUGIN_STATE_DIR=str(self.state_dir),
            HERDR_BIN_PATH=str(self.fake_herdr),
            FAKE_HERDR_CALLS=str(self.calls_file),
        )
        environment["PATH"] = str(self.scratch.root) + os.pathsep + environment["PATH"]
        return environment

    def command(self, hook=None):
        return [sys.executable, str(hook or self.hook)]

    def run(self, event, pane, hook=None, environment=None, **options):
        environment = environment if environment is not None else self.environment(event, pane, **options)
        return subprocess.run(
            self.command(hook),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=60,
            text=True,
            encoding="utf-8",
        )

    def spawn(self, event, pane, **options):
        return subprocess.Popen(
            self.command(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.environment(event, pane, **options),
            text=True,
            encoding="utf-8",
        )

    def status(self, pane, status, **options):
        return self.run("pane.agent_status_changed", pane, status=status, **options)

    def detected(self, pane, **options):
        return self.run("pane.agent_detected", pane, **options)

    def closed(self, pane, **options):
        return self.run("pane.closed", pane, agent=None, **options)

    def exited(self, pane, **options):
        return self.run("pane.exited", pane, agent=None, **options)

    def events(self):
        return self.scratch.events()

    def kinds(self, pane=None):
        return [e["kind"] for e in self.events() if pane is None or e["worker"] == pane]


class HookDirectTests(unittest.TestCase):
    def setUp(self):
        self.h = DirectHarness(self)

    def assertQuietSuccess(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_status_maps_to_kind_and_worker_and_context(self):
        for status in ("working", "unknown", "something-new"):
            self.assertQuietSuccess(self.h.status("w1:p1", status))
        self.assertEqual(self.h.events(), [])
        for pane, status in (("w1:p2", "blocked"), ("w1:p3", "idle"), ("w1:p4", "done")):
            self.assertQuietSuccess(self.h.status(pane, status))
        by_pane = {e["worker"]: e for e in self.h.events()}
        self.assertEqual({p: e["kind"] for p, e in by_pane.items()}, {"w1:p2": "blocked", "w1:p3": "finished", "w1:p4": "finished"})
        event = by_pane["w1:p3"]
        self.assertEqual(list(event), ["version", "seq", "time", "worker", "kind", "context"])  # no message member
        self.assertEqual(event["version"], 1)
        self.assertEqual(event["context"], {"workspace_id": "w1", "workspace_label": "main-ws", "agent": "pi"})
        self.assertEqual([e["seq"] for e in self.h.events()], [1, 2, 3])
        self.assertNotIn("errored", self.h.kinds())

    def test_working_and_unknown_reports_add_no_event_but_record_presence(self):
        for status in ("working", "unknown"):
            pane = "w1:" + status
            self.assertQuietSuccess(self.h.status(pane, status))
            self.assertTrue((self.h.state_dir / "panes" / quote(pane, safe="")).is_file())
        self.assertEqual(self.h.events(), [])
        self.assertQuietSuccess(self.h.closed("w1:working"))
        self.assertQuietSuccess(self.h.exited("w1:unknown"))
        self.assertEqual(sorted((e["worker"], e["kind"]) for e in self.h.events()), [("w1:unknown", "exited"), ("w1:working", "exited")])

    def test_agentless_pane_emits_nothing(self):
        self.assertQuietSuccess(self.h.status("w1:p1", "idle", agent=None))
        self.assertQuietSuccess(self.h.status("w1:p1", "blocked", agent=None))
        self.assertQuietSuccess(self.h.closed("w1:p1"))
        self.assertQuietSuccess(self.h.exited("w1:p1"))
        self.assertEqual(self.h.events(), [])
        self.assertEqual(self.h.scratch.inbox_bytes(), b"")

    def test_idle_hook_before_working_hook_still_emits_finished(self):
        self.assertQuietSuccess(self.h.status("w1:p1", "idle"))
        self.assertQuietSuccess(self.h.status("w1:p1", "working"))
        self.assertEqual(self.h.kinds(), ["finished"])
        # the opposite order, and a second turn behind it
        self.assertQuietSuccess(self.h.status("w1:p1", "working"))
        self.assertQuietSuccess(self.h.status("w1:p1", "idle"))
        self.assertQuietSuccess(self.h.status("w1:p1", "idle"))  # a late duplicate hook is accepted
        self.assertEqual(self.h.kinds(), ["finished", "finished", "finished"])

    def test_blocked_then_idle_in_both_orders_emits_both(self):
        self.assertQuietSuccess(self.h.status("w1:p1", "idle"))
        self.assertQuietSuccess(self.h.status("w1:p1", "blocked"))
        self.assertQuietSuccess(self.h.status("w1:p2", "blocked"))
        self.assertQuietSuccess(self.h.status("w1:p2", "idle"))
        self.assertEqual(self.h.kinds("w1:p1"), ["finished", "blocked"])
        self.assertEqual(self.h.kinds("w1:p2"), ["blocked", "finished"])

    def test_exit_before_detection_emits_nothing_and_exit_after_it_emits_once(self):
        self.assertQuietSuccess(self.h.closed("w1:p1"))  # no hook has shown the pane had an agent
        self.assertEqual(self.h.events(), [])
        self.assertQuietSuccess(self.h.detected("w1:p1"))
        self.assertQuietSuccess(self.h.closed("w1:p1"))
        self.assertEqual(self.h.kinds(), ["exited"])
        self.assertEqual(self.h.events()[0]["context"]["agent"], "pi")
        # Herdr can fire both pane.exited and pane.closed for one pane: one exited event.
        self.assertQuietSuccess(self.h.exited("w1:p1"))
        self.assertQuietSuccess(self.h.closed("w1:p1"))
        self.assertEqual(self.h.kinds(), ["exited"])

    def test_any_event_naming_an_agent_records_presence(self):
        self.assertQuietSuccess(self.h.status("w1:p1", "working"))
        self.assertQuietSuccess(self.h.exited("w1:p1"))
        self.assertEqual(self.h.kinds(), ["exited"])

    def test_released_agent_detection_is_not_presence(self):
        self.assertQuietSuccess(self.h.detected("w1:p1", released=True))
        self.assertQuietSuccess(self.h.closed("w1:p1"))
        self.assertEqual(self.h.events(), [])

    def test_six_panes_at_once_all_reach_the_inbox_intact(self):
        panes = ["w1:p%d" % n for n in range(1, 7)]
        wave = []
        for pane in panes:
            for event, status in (("pane.agent_detected", None), ("pane.agent_status_changed", "working"), ("pane.agent_status_changed", "idle")):
                wave.append(self.h.spawn(event, pane, status=status))
        for process in wave:
            _, stderr = process.communicate(timeout=120)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stderr, "")
        self.assertEqual(sorted(e["worker"] for e in self.h.events()), panes)
        gone = [self.h.spawn("pane.closed", pane, agent=None) for pane in panes]
        for process in gone:
            _, stderr = process.communicate(timeout=120)
            self.assertEqual(process.returncode, 0, stderr)
        events = self.h.events()  # raises if a line is torn or does not end in a newline
        self.assertEqual(len(events), 12)
        self.assertEqual([e["seq"] for e in events], list(range(1, 13)))
        self.assertEqual(sorted(e["worker"] for e in events if e["kind"] == "finished"), panes)
        self.assertEqual(sorted(e["worker"] for e in events if e["kind"] == "exited"), panes)

    def test_no_pane_is_read_and_no_message_is_sent(self):
        self.h.detected("w1:p1")
        self.h.status("w1:p1", "idle")
        self.h.status("w1:p1", "blocked")
        self.h.closed("w1:p1")
        self.assertEqual(self.h.kinds(), ["finished", "blocked", "exited"])
        for event in self.h.events():
            self.assertNotIn("summary", event)
        self.assertFalse(self.h.calls_file.exists())  # the fake herdr was never called

    def test_hook_source_has_no_pane_read_call(self):
        source = self.h.hook.read_text(encoding="utf-8")
        for forbidden in ("agent read", '"read"', "pane read", "recent-unwrapped", "--summary", "HERDR_BIN_PATH", "PLACEHOLDER"):
            self.assertNotIn(forbidden, source)
        self.assertEqual(re.findall(r"subprocess\.run", source), ["subprocess.run"])  # the one emit call
        self.assertEqual(source.count('"emit"'), 1)

    # ---------------------------------------------------------- containment

    def test_unwritable_inbox_is_reported_on_stderr_exit_zero_and_not_retried(self):
        blocker = self.h.scratch.root / "not-a-directory"
        blocker.write_text("x")
        self.h.scratch.inbox = blocker / "inbox.jsonl"
        started = time.monotonic()
        result = self.h.status("w1:p1", "idle")
        self.assertEqual(result.returncode, 0)
        self.assertIn("emit", result.stderr)
        self.assertIn("event was not delivered", result.stderr)
        self.assertLess(time.monotonic() - started, 30)
        self.assertFalse(self.h.calls_file.exists())
        self.assertIn("core: emit failed", self.h.scratch.log_text())

    def test_core_missing_is_reported_and_exits_zero(self):
        lone = self.h.scratch.root / "lone" / "adapters" / "herdr"
        lone.mkdir(parents=True)
        shutil.copy(self.h.hook, lone / "hook.py")
        result = self.h.run("pane.agent_status_changed", "w1:p1", hook=lone / "hook.py", status="idle")
        self.assertEqual(result.returncode, 0)
        self.assertIn("cannot find the core", result.stderr)
        self.assertEqual(self.h.events(), [])

    def test_bad_event_input_exits_zero_with_a_message(self):
        environment = self.h.environment("pane.closed", "w1:p1", agent=None)
        environment["HERDR_PLUGIN_EVENT_JSON"] = "{not json"
        result = self.h.run(None, None, environment=environment)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stderr.strip())
        del environment["HERDR_PLUGIN_EVENT_JSON"]
        result = self.h.run(None, None, environment=environment)
        self.assertEqual(result.returncode, 0)
        self.assertIn("HERDR_PLUGIN_EVENT_JSON", result.stderr)

    def test_missing_state_dir_does_not_stop_a_finished_alert(self):
        environment = self.h.environment("pane.agent_status_changed", "w1:p1", status="idle")
        del environment["HERDR_PLUGIN_STATE_DIR"]
        result = self.h.run(None, None, environment=environment)
        self.assertEqual(result.returncode, 0)
        self.assertIn("HERDR_PLUGIN_STATE_DIR", result.stderr)
        self.assertEqual(self.h.kinds(), ["finished"])


# ------------------------------------------------------- real scratch server


class ScratchHerdr:
    """One real Herdr 0.9.1 server with its own HOME, config path and sockets.

    Everything lives under a short directory in /tmp (socket paths have a
    length limit). The environment is built from scratch values and never
    carries a HERDR_* variable from the caller, so the live server is never
    addressed; start() refuses to go on unless the server reports our socket.
    """

    def __init__(self, test_case):
        self.test_case = test_case
        self.root = Path(tempfile.mkdtemp(prefix="t2h-", dir="/tmp")).resolve()
        self.home = self.root / "home"
        (self.home / ".config" / "herdr").mkdir(parents=True)
        self.socket = self.root / "s.sock"
        self.core_scratch = common.Scratch(cli=adapter_copy() / "core" / "agent-alert")
        test_case.addCleanup(self.core_scratch.cleanup)
        self.core_scratch.write_config(inbox_path=str(self.core_scratch.inbox), log_path=str(self.core_scratch.log))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR_", "AGENT_ALERT_"))}
        self.env.update(
            HOME=str(self.home),
            XDG_CONFIG_HOME=str(self.home / ".config"),
            XDG_STATE_HOME=str(self.home / ".local" / "state"),
            LANG="en_US.UTF-8",
            HERDR_CONFIG_PATH=str(self.home / ".config" / "herdr" / "config.toml"),
            HERDR_SOCKET_PATH=str(self.socket),
            HERDR_CLIENT_SOCKET_PATH=str(self.root / "c.sock"),
            AGENT_ALERT_CONFIG=str(self.core_scratch.config),
        )
        for name in ("HERDR_CONFIG_PATH", "HERDR_SOCKET_PATH", "HERDR_CLIENT_SOCKET_PATH"):
            assert self.env[name].startswith(str(self.root) + os.sep), name
        self.process = None
        self.plugin_dir = None
        self.witness_file = self.root / "witness.txt"
        self.sleep_marker = self.root.name
        test_case.addCleanup(self.stop)

    # ---- lifecycle

    def herdr(self, *args, check=True, timeout=30):
        result = subprocess.run(
            ["herdr"] + [str(a) for a in args],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            timeout=timeout,
            text=True,
            encoding="utf-8",
        )
        if check and result.returncode != 0:
            raise AssertionError("herdr %s failed: %s %s" % (" ".join(map(str, args)), result.stdout, result.stderr))
        return result

    def api(self, *args):
        return json.loads(self.herdr(*args).stdout)["result"]

    def start(self):
        with open(self.root / "server.out", "wb") as server_output:
            self.process = subprocess.Popen(
                ["herdr", "server"],
                stdin=subprocess.DEVNULL,
                stdout=server_output,
                stderr=subprocess.STDOUT,
                env=self.env,
                start_new_session=True,
            )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            status = self.herdr("status", "server", check=False)
            found = re.search(r"version: (\S+)", status.stdout)
            # The server can say "running" a moment before it prints its version: keep polling.
            if status.returncode == 0 and "running" in status.stdout and found:
                if "socket: %s" % self.socket not in status.stdout:
                    self.stop()
                    raise AssertionError("scratch server reports a socket that is not ours: " + status.stdout)
                self.version = found.group(1)
                return
            time.sleep(0.2)
        raise AssertionError("scratch Herdr server did not start")

    def stop(self):
        """Stop our server, kill what our panes left behind, and remove the scratch directory."""
        if self.process is not None:
            if self.process.poll() is None:
                self.herdr("server", "stop", check=False, timeout=20)
                try:
                    self.process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=10)
            self.test_case.assertIsNotNone(self.process.poll())
            with self.test_case.assertRaises(ProcessLookupError):
                os.kill(self.process.pid, 0)
            self.process = None
        leftovers = self.leftover_pids()
        deadline = time.monotonic() + 5
        while leftovers and time.monotonic() < deadline:
            time.sleep(0.2)
            leftovers = self.leftover_pids()
        for pid in leftovers:
            os.kill(pid, signal.SIGKILL)
        shutil.rmtree(self.root, ignore_errors=True)
        self.test_case.assertEqual(leftovers, [], "processes of the scratch server survived its stop")

    def leftover_pids(self):
        found = subprocess.run(["pgrep", "-f", str(self.root)], stdout=subprocess.PIPE, text=True)
        return [int(pid) for pid in found.stdout.split()]

    # ---- plugins

    def copy_tool(self):
        """A scratch copy of the deployed tool; returns the adapters/herdr directory of the copy."""
        target = self.root / "agent-alert"
        shutil.copytree(adapter_copy(), target, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        self.plugin_dir = target / "adapters" / "herdr"
        return self.plugin_dir

    def link_adapter(self, delay_seconds=None):
        plugin = self.plugin_dir or self.copy_tool()
        if delay_seconds:
            manifest = plugin / "herdr-plugin.toml"
            text = manifest.read_text().replace('command = ["python3", "hook.py"]', 'command = ["sh", "-c", "sleep %s; exec python3 hook.py"]' % delay_seconds)
            manifest.write_text(text)
        self.herdr("plugin", "link", plugin)
        self.herdr("plugin", "enable", "agent-alert")

    def link_witness(self):
        """A second plugin on the same four events; it records every event it runs for."""
        plugin = self.root / "witness"
        plugin.mkdir()
        lines = ['id = "witness"', 'name = "Witness"', 'version = "0.0.1"', 'min_herdr_version = "0.9.1"', 'description = "records events"', 'platforms = ["macos", "linux"]', ""]
        for event in ("pane.agent_status_changed", "pane.agent_detected", "pane.exited", "pane.closed"):
            lines += ["[[events]]", 'on = "%s"' % event, "command = [\"sh\", \"-c\", 'echo \"$HERDR_PLUGIN_EVENT $HERDR_PANE_ID\" >> %s']" % self.witness_file, ""]
        (plugin / "herdr-plugin.toml").write_text("\n".join(lines))
        self.herdr("plugin", "link", plugin)
        self.herdr("plugin", "enable", "witness")

    def plugin_logs(self, plugin_id="agent-alert"):
        logs = self.api("plugin", "log", "list")["logs"]
        return [entry for entry in logs if entry["plugin_id"] == plugin_id]

    def settle(self, quiet_seconds=1.5, timeout=40):
        """Wait until no hook is running and the plugin log has stopped growing."""
        deadline = time.monotonic() + timeout
        signature = None
        stable_since = time.monotonic()
        while time.monotonic() < deadline:
            logs = self.api("plugin", "log", "list")["logs"]
            current = (len(logs), all(entry["status"] != "running" for entry in logs))
            if current != signature:
                signature = current
                stable_since = time.monotonic()
            elif current[1] and time.monotonic() - stable_since >= quiet_seconds:
                return
            time.sleep(0.25)
        raise AssertionError("plugin hooks did not settle")

    # ---- panes

    def new_pane(self, label):
        result = self.api("workspace", "create", "--cwd", self.root, "--label", label, "--no-focus")
        return result["root_pane"]["pane_id"], result["workspace"]["workspace_id"]

    def report(self, pane, state):
        self.herdr("pane", "report-agent", pane, "--source", "t2h", "--agent", "pi", "--state", state)

    def show_text(self, pane, text, wait_for):
        """Make the pane's terminal show `text` (written to a file and cat'ed), and wait until it does."""
        fixture = self.root / ("fixture-%s.txt" % quote(pane, safe=""))
        fixture.write_text(text, encoding="utf-8")
        self.herdr("pane", "send-text", pane, "exec sh -c 'cat %s; sleep 3601' %s" % (fixture, self.sleep_marker))
        self.herdr("pane", "send-keys", pane, "Enter")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            shown = self.herdr("pane", "read", pane, "--source", "recent-unwrapped", "--lines", "200", check=False).stdout
            if wait_for in shown:
                return
            time.sleep(0.2)
        raise AssertionError("pane %s never showed %r" % (pane, wait_for))

    def server_answers(self):
        return self.herdr("workspace", "list", check=False).returncode == 0

    def witness_lines(self):
        try:
            return self.witness_file.read_text().splitlines()
        except FileNotFoundError:
            return []

    def inbox_events(self):
        return self.core_scratch.events()


@unittest.skipUnless(HERDR_REQUIRED, "herdr is not installed")
class HerdrServerTests(unittest.TestCase):
    def setUp(self):
        self.server = ScratchHerdr(self)
        self.server.start()
        self.assertEqual(self.server.version, "0.9.1")

    def events_for(self, pane):
        return [e for e in self.server.inbox_events() if e["worker"] == pane]

    def test_manifest_lists_the_four_events(self):
        self.server.link_adapter()
        listed = self.server.herdr("plugin", "list").stdout
        self.assertIn("agent-alert", listed)
        self.assertIn("enabled", listed)
        manifest = (self.server.plugin_dir / "herdr-plugin.toml").read_text()
        self.assertIn('min_herdr_version = "0.9.1"', manifest)
        for event in ("pane.agent_status_changed", "pane.agent_detected", "pane.exited", "pane.closed"):
            self.assertIn('on = "%s"' % event, manifest)
        self.assertEqual(manifest.count("[[events]]"), 4)

    def test_ordinary_sequences_through_a_real_server(self):
        server = self.server
        server.link_adapter()
        working_times = {}
        panes = {}
        for name in ("blk", "idl", "quick", "repeat", "agentless", "workonly", "closing"):
            panes[name], _ = server.new_pane("ws-" + name)

        def turn(name, states):
            for state in states:
                if state == "working":
                    working_times.setdefault(name, []).append(utc_now_string())
                server.report(panes[name], state)

        turn("blk", ["working", "unknown", "blocked", "idle"])
        turn("idl", ["idle", "blocked", "idle"])
        turn("quick", ["working", "idle", "working", "idle", "working", "idle"])
        turn("repeat", ["working", "idle", "idle"])
        turn("workonly", ["working"])
        turn("closing", ["working"])
        server.herdr("pane", "close", panes["closing"])
        server.herdr("pane", "close", panes["agentless"])  # a pane that never had an agent
        server.settle()

        def kinds(name):
            return sorted(e["kind"] for e in self.events_for(panes[name]))

        self.assertEqual(kinds("blk"), ["blocked", "finished"])
        self.assertEqual(kinds("idl"), ["blocked", "finished", "finished"])
        self.assertEqual(kinds("repeat"), ["finished"])  # the unchanged repeat gave one event
        self.assertEqual(kinds("workonly"), [])  # working alone adds no event
        self.assertEqual(kinds("agentless"), [])  # no agent: not even an exit
        self.assertEqual(kinds("closing"), ["exited"])
        # every turn that ended in idle has a finished event after its last working report
        finished_times = sorted(e["time"] for e in self.events_for(panes["quick"]) if e["kind"] == "finished")
        started = working_times["quick"]
        for index, started_at in enumerate(started):
            later = [t for t in finished_times if t >= started_at]
            self.assertGreaterEqual(len(later), len(started) - index, (started, finished_times))
        self.assertGreaterEqual(len(finished_times), 3)
        blk_finished = [e for e in self.events_for(panes["blk"]) if e["kind"] == "finished"]
        self.assertTrue(all(e["time"] >= working_times["blk"][-1] for e in blk_finished))
        # context and worker id
        sample = self.events_for(panes["blk"])[0]
        self.assertEqual(sample["worker"], panes["blk"])
        self.assertEqual(sample["context"]["workspace_label"], "ws-blk")
        self.assertEqual(sample["context"]["agent"], "pi")
        self.assertTrue(re.fullmatch(r"w\d+", sample["context"]["workspace_id"]))
        # whole inbox intact, consecutive, and every hook ran cleanly
        everything = server.inbox_events()
        self.assertEqual([e["seq"] for e in everything], list(range(1, len(everything) + 1)))
        self.assertTrue(server.plugin_logs())
        for entry in server.plugin_logs():
            self.assertEqual((entry["status"], entry["exit_code"], entry["stderr"]), ("succeeded", 0, ""), entry)
        self.assertTrue(server.server_answers())

    def test_agent_pane_whose_process_exits_emits_exited(self):
        server = self.server
        server.link_adapter()
        pane, _ = server.new_pane("ws-exit")
        server.report(pane, "working")
        server.settle()
        server.herdr("pane", "send-text", pane, "exit")
        server.herdr("pane", "send-keys", pane, "Enter")
        server.settle()
        self.assertIn("exited", [e["kind"] for e in self.events_for(pane)])
        for entry in server.plugin_logs():
            self.assertEqual((entry["status"], entry["exit_code"]), ("succeeded", 0), entry)
        self.assertTrue(server.server_answers())

    def test_pane_showing_a_distinctive_marker_gives_a_marker_free_inbox_with_context(self):
        server = self.server
        server.link_adapter()
        pane, workspace = server.new_pane("ws-marker")
        server.report(pane, "working")
        marker = "MARKER-" + "Q7w8E9r0" * 3
        server.show_text(pane, "\u276f earlier request\nThe answer holds %s and password=correcthorse1.\n" % marker, marker)
        server.report(pane, "idle")
        server.settle()
        [event] = [e for e in self.events_for(pane) if e["kind"] == "finished"]
        self.assertEqual(list(event), ["version", "seq", "time", "worker", "kind", "context"])
        self.assertEqual(event["context"], {"workspace_id": workspace, "workspace_label": "ws-marker", "agent": "pi"})
        raw = server.core_scratch.inbox_bytes().decode()
        for text in (marker, "MARKER-", "correcthorse1", "earlier request"):
            self.assertNotIn(text, raw)
        for entry in server.plugin_logs():
            self.assertEqual((entry["status"], entry["exit_code"], entry["stderr"]), ("succeeded", 0, ""), entry)

    def test_error_ending_turn_and_error_mentioning_turn_are_both_finished_never_errored(self):
        # Herdr 0.9.1 has no error status and the adapter never reads the pane, so both turns
        # are `finished`.
        server = self.server
        server.link_adapter()
        failed_pane, _ = server.new_pane("ws-failed")
        passing_pane, _ = server.new_pane("ws-passing")
        failed_text = "Request failed: 429 rate limit exceeded. Stopping here, nothing was changed."
        passing_text = "I fixed the error handling in the parser and all checks pass now."
        started = {}
        for pane in (failed_pane, passing_pane):
            started[pane] = utc_now_string()
            server.report(pane, "working")
        server.show_text(failed_pane, "\u276f fix the build\n" + failed_text + "\n", "nothing was changed.")
        server.show_text(passing_pane, "\u276f tidy the parser\n" + passing_text + "\n", "all checks pass now.")
        for pane in (failed_pane, passing_pane):
            server.report(pane, "idle")
        server.settle()
        for pane, text in ((failed_pane, failed_text), (passing_pane, passing_text)):
            events = self.events_for(pane)
            self.assertNotIn("errored", [e["kind"] for e in events], events)
            finished = [e for e in events if e["kind"] == "finished" and e["time"] >= started[pane]]
            self.assertTrue(finished, events)
            self.assertNotIn(text[:20], server.core_scratch.inbox_bytes().decode())
        self.assertNotIn("errored", [e["kind"] for e in server.inbox_events()])
        for entry in server.plugin_logs():
            self.assertEqual((entry["status"], entry["exit_code"], entry["stderr"]), ("succeeded", 0, ""), entry)

    def test_unwritable_inbox_leaves_server_and_second_plugin_running(self):
        server = self.server
        server.link_adapter()
        server.link_witness()
        pane, _ = server.new_pane("ws-bad-inbox")
        blocker = server.root / "not-a-directory"
        blocker.write_text("x")
        server.core_scratch.write_config(inbox_path=str(blocker / "inbox.jsonl"), log_path=str(server.core_scratch.log))
        server.report(pane, "idle")
        server.settle()
        self.assertFalse((blocker / "inbox.jsonl").exists())
        failing = [e for e in server.plugin_logs() if e["event"] == "pane.agent_status_changed"]
        self.assertTrue(failing)
        for entry in failing:
            self.assertEqual((entry["status"], entry["exit_code"]), ("succeeded", 0), entry)
            self.assertIn("event was not delivered", entry["stderr"])
            self.assertIn("agent-alert emit", entry["stderr"])
        self.assertIn("pane.agent_status_changed %s" % pane, server.witness_lines())
        for entry in server.plugin_logs("witness"):
            self.assertEqual((entry["status"], entry["exit_code"]), ("succeeded", 0), entry)
        self.assertTrue(server.server_answers())
        # repaired: the lost event is not retried, a new event is delivered
        server.core_scratch.write_config(inbox_path=str(server.core_scratch.inbox), log_path=str(server.core_scratch.log))
        server.report(pane, "blocked")
        server.settle()
        self.assertEqual([e["kind"] for e in server.inbox_events()], ["blocked"])

    def test_closed_pane_leaves_server_and_second_plugin_running(self):
        server = self.server
        server.link_adapter(delay_seconds=1)  # the hook starts after the pane is gone
        server.link_witness()
        pane, _ = server.new_pane("ws-closed")
        server.report(pane, "idle")
        server.herdr("pane", "close", pane)
        server.settle(quiet_seconds=2.5)
        status_runs = [e for e in server.plugin_logs() if e["event"] == "pane.agent_status_changed"]
        self.assertTrue(status_runs)
        for entry in server.plugin_logs() + server.plugin_logs("witness"):
            self.assertEqual((entry["status"], entry["exit_code"], entry["stderr"]), ("succeeded", 0, ""), entry)
        # the late status hook still delivers finished (the close hook may or may not find the
        # presence marker yet: a missed exit is an accepted risk)
        kinds = [e["kind"] for e in server.inbox_events() if e["worker"] == pane]
        self.assertIn("finished", kinds)
        self.assertTrue(set(kinds) <= {"finished", "exited"}, kinds)
        self.assertIn("pane.closed %s" % pane, server.witness_lines())
        self.assertIn("pane.agent_status_changed %s" % pane, server.witness_lines())
        self.assertTrue(server.server_answers())

    def test_missing_python3_is_a_failed_log_entry_and_the_server_keeps_answering(self):
        server = self.server
        plugin = server.copy_tool()
        manifest = plugin / "herdr-plugin.toml"
        manifest.write_text(manifest.read_text().replace('"python3"', '"python3-not-installed"'))
        server.link_adapter()
        server.link_witness()
        pane, _ = server.new_pane("ws-no-python")
        server.report(pane, "idle")
        server.settle()
        entries = server.plugin_logs()
        self.assertTrue(entries)
        for entry in entries:
            self.assertEqual(entry["status"], "failed", entry)
            self.assertIn("No such file or directory", entry["error"])
        self.assertEqual(server.inbox_events(), [])
        self.assertIn("pane.agent_status_changed %s" % pane, server.witness_lines())
        self.assertTrue(server.server_answers())


if __name__ == "__main__":
    unittest.main()
