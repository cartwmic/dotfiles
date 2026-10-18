"""Tests that execute the documentation (README.md, SPEC.md, examples/).

Run (from the repository root):

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
        -s dot_local/share/agent-alert/tests -p 'test_docs.py'

* The shell blocks of README.md (Usage, the Herdr section, the doorbell section)
  are extracted from the file and run literally (with `sh -c`) against one scratch
  Herdr 0.9.1 server at a time: the deployed tree is copied to
  `$HOME/.local/share/agent-alert` of a scratch home, so the README's own
  `~`-relative paths are the ones used. The pane procedure (`tail -F` in a pane)
  and the next-sequence `herdr pane wait-output` command run as written, with the
  pane and without it, and with hand-made partial lines in the inbox.
* The doorbell section's config JSON and session-id block run in a scratch HOME
  with a scripted `claude` on PATH.
* The two Python examples are extracted from the fenced blocks of SPEC.md, shown
  to equal the files in examples/, and run as written, including a hand-written
  line of a kind they have never heard of.
* The two adapter READMEs are gone; README.md has a section for each adapter,
  and its wait expression is the one SPEC.md gives.

Nothing here touches the live Herdr, home or `claude`; every path is scratch.
"""

import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from test_herdr import HERDR_REQUIRED, ScratchHerdr, adapter_copy  # noqa: E402

TOOL = common.TOOL_SOURCE_DIR
README = TOOL / "README.md"
SPEC = TOOL / "SPEC.md"

# A hand-written line of a kind this tree has never heard of, with a member nobody knows.
UNKNOWN_KIND_LINE = '{"version":1,"seq":%d,"time":"2026-10-17T12:30:05.123Z","worker":"pane-9","kind":"paused","extra":{"a":1}}'


def sections(markdown):
    """Map each level-2 heading to its text (level-3 subsections stay inside it)."""
    found = {}
    current = None
    for line in markdown.splitlines(keepends=True):
        if line.startswith("## "):
            current = line[3:].strip()
            found[current] = ""
        elif current is not None:
            found[current] += line
    return found


def fenced_blocks(markdown, language):
    """The text of every ```<language> fenced block, in order; list-item indentation is removed."""
    pattern = r"^[ ]*```" + re.escape(language) + r"\n(.*?)^[ ]*```$"
    return [textwrap.dedent(block) for block in re.findall(pattern, markdown, re.S | re.M)]


def readme_blocks(section, language="sh"):
    return fenced_blocks(sections(README.read_text(encoding="utf-8"))[section], language)


def heading_slugs(markdown):
    """GitHub-style anchors of every heading, for link checking."""
    slugs = set()
    for line in markdown.splitlines():
        match = re.match(r"^#{1,6}\s+(.*?)\s*$", line)
        if match:
            text = re.sub(r"[`*]", "", match.group(1)).lower()
            text = re.sub(r"[^\w\- ]", "", text)
            slugs.add(text.replace(" ", "-"))
    return slugs


class DocsHerdr(ScratchHerdr):
    """A scratch Herdr whose HOME holds the deployed tree and uses default paths."""

    def __init__(self, test_case):
        super().__init__(test_case)
        # No AGENT_ALERT_* variable: the README's default paths under the scratch HOME are used.
        self.env.pop("AGENT_ALERT_CONFIG", None)
        self.installed = self.home / ".local" / "share" / "agent-alert"
        shutil.copytree(adapter_copy(), self.installed, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        (self.home / ".zshrc").write_text("")  # keeps zsh from asking its first-run questions
        self.inbox_path = self.home / ".local" / "share" / "coordinator" / "inbox.jsonl"
        self.core = self.installed / "core" / "agent-alert"

    def sh(self, block, timeout=60, **extra):
        environment = dict(self.env)
        environment.update({key: str(value) for key, value in extra.items()})
        return subprocess.run(
            ["sh", "-c", block],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=timeout,
            text=True,
            encoding="utf-8",
        )

    def spawn_sh(self, block, **extra):
        environment = dict(self.env)
        environment.update({key: str(value) for key, value in extra.items()})
        return subprocess.Popen(
            ["sh", "-c", block],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            text=True,
            encoding="utf-8",
        )

    def emit(self, worker, kind):
        result = subprocess.run(
            [str(self.core), "emit", "--worker", worker, "--kind", kind],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
            timeout=60,
            text=True,
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise AssertionError("emit failed: " + result.stderr)

    def inbox_lines(self):
        try:
            return self.inbox_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []

    def parsed_events(self):
        events = []
        for line in self.inbox_lines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and type(event.get("seq")) is int:
                events.append(event)
        return events

    def pane_text(self, pane):
        return self.herdr("pane", "read", pane, "--source", "recent-unwrapped", "--lines", "200", check=False).stdout

    def append_raw(self, text):
        with open(self.inbox_path, "ab") as inbox:
            inbox.write(text.encode("utf-8"))

    def wait_for_pane_text(self, pane, text):
        deadline = time.monotonic() + 20
        while text not in self.pane_text(pane):
            if time.monotonic() > deadline:
                raise AssertionError("the pane never showed " + text)
            time.sleep(0.2)


class ReadmeProcedureTests(unittest.TestCase):
    """The README's steps, run as written against a scratch Herdr server."""

    def setUp(self):
        if not HERDR_REQUIRED:
            self.skipTest("herdr is not installed")
        self.server = DocsHerdr(self)
        self.server.start()
        self.assertEqual(self.server.version, "0.9.1")
        self.assertEqual(readme_blocks("Install", "sh"), [])  # the install step is `chezmoi apply`, never run here
        self.basic_block, self.pane_block, self.wait_block = readme_blocks("Usage")
        herdr_blocks = readme_blocks("Herdr source adapter")
        self.install_block, = [b for b in herdr_blocks if "herdr plugin link" in b]
        self.read_block, = [b for b in herdr_blocks if "herdr pane read" in b]

    def install(self):
        # `set -e` makes every command of the block, not only the last, have to succeed
        result = self.server.sh("set -e\n" + self.install_block)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        listed = self.server.herdr("plugin", "list").stdout
        self.assertIn("agent-alert", listed)
        self.assertIn("enabled", listed)

    def start_follower(self, pane):
        """Run the README's pane procedure, then prove the follower is live by its first event."""
        self.server.emit("follower-check", "finished")
        result = self.server.sh(self.pane_block, PANE=pane)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        first = self.server.parsed_events()[-1]["seq"]
        waited = self.server.sh(self.wait_block, PANE=pane, NEXT=first, timeout=60)
        self.assertEqual(waited.returncode, 0, waited.stdout + waited.stderr)

    def wait_started(self, pane, next_seq):
        return self.server.spawn_sh(self.wait_block, PANE=pane, NEXT=next_seq)

    def finish(self, process, expect_success=True, timeout=60):
        stdout, stderr = process.communicate(timeout=timeout)
        if expect_success:
            self.assertEqual(process.returncode, 0, stdout + stderr)
        else:
            self.assertNotEqual(process.returncode, 0, stdout + stderr)

    def short_wait(self, pane, next_seq):
        """The README's wait command with its 30 s limit cut to 2 s, for a case that must time out."""
        self.assertIn("--timeout 30000", self.wait_block)
        block = self.wait_block.replace("--timeout 30000", "--timeout 2000")
        return self.server.sh(block, PANE=pane, NEXT=next_seq, timeout=30)

    def test_herdr_install_block_links_and_enables_the_plugin_and_status_reports_reach_the_inbox(self):
        self.install()
        pane, _ = self.server.new_pane("docs-herdr")
        self.server.report(pane, "working")
        self.server.report(pane, "blocked")
        self.server.report(pane, "idle")
        self.server.settle()
        events = [e for e in self.server.parsed_events() if e["worker"] == pane]
        self.assertEqual(sorted(e["kind"] for e in events), ["blocked", "finished"])
        for event in events:
            self.assertEqual(list(event), ["version", "seq", "time", "worker", "kind", "context"])  # no message text
        # the README's own check after the first event: every run succeeded with empty stderr
        shown = self.server.sh("herdr plugin log list")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        for entry in self.server.api("plugin", "log", "list")["logs"]:
            self.assertEqual((entry["status"], entry["exit_code"], entry["stderr"]), ("succeeded", 0, ""), entry)
        # the coordinator reads the named pane, as the section shows
        read = self.server.sh(self.read_block, PANE=pane)
        self.assertEqual(read.returncode, 0, read.stdout + read.stderr)

    def test_basic_usage_block_emits_reads_and_acknowledges_without_any_pane(self):
        result = self.server.sh(self.basic_block)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, result.stdout)
        event = json.loads(lines[0])
        self.assertEqual((event["seq"], event["worker"], event["kind"]), (1, "my-pane", "finished"))
        self.assertEqual(self.server.inbox_lines(), [lines[0]])
        self.assertEqual(json.loads((self.server.inbox_path.parent / "inbox.jsonl.ack").read_text()), {"acked": 1})
        self.assertEqual(self.server.sh('"$HOME/.local/share/agent-alert/core/agent-alert" tail').stdout, "")

    def test_pane_follower_and_next_sequence_wait_see_hook_and_direct_events(self):
        self.install()
        pane, _ = self.server.new_pane("docs-pane")
        self.start_follower(pane)
        # the next event comes from the Herdr plugin, through a real status change
        waiting = self.wait_started(pane, self.server.parsed_events()[-1]["seq"] + 1)
        self.server.report(pane, "working")
        self.server.report(pane, "idle")
        self.finish(waiting)
        self.server.settle()
        by_hook = self.server.parsed_events()[-1]
        self.assertEqual((by_hook["worker"], by_hook["kind"]), (pane, "finished"))
        # the next event is written directly and is longer than the pane is wide
        next_seq = by_hook["seq"] + 1
        waiting = self.wait_started(pane, next_seq)
        self.server.emit("direct-" + "x" * 300, "blocked")
        self.finish(waiting)
        # an event that has not happened is not matched: a later number does not satisfy the wait
        self.assertNotEqual(self.short_wait(pane, next_seq + 1).returncode, 0)
        for entry in self.server.api("plugin", "log", "list")["logs"]:
            self.assertEqual((entry["status"], entry["exit_code"], entry["stderr"]), ("succeeded", 0, ""), entry)

    def test_inbox_is_the_same_with_the_pane_closed_and_a_pane_without_the_follower_never_satisfies_the_wait(self):
        self.install()
        silent_pane, _ = self.server.new_pane("docs-silent")
        self.server.emit("w1", "finished")
        # no follower in this pane: the wait fails, the inbox is unaffected
        self.assertNotEqual(self.short_wait(silent_pane, 1).returncode, 0)
        self.assertEqual([e["seq"] for e in self.server.parsed_events()], [1])
        pane, _ = self.server.new_pane("docs-closing")
        self.start_follower(pane)
        before = self.server.inbox_path.read_bytes()
        self.server.herdr("pane", "close", pane)
        self.server.emit("w1", "finished")
        after = self.server.inbox_path.read_bytes()
        self.assertTrue(after.startswith(before), "the inbox changed anything but its end")
        self.assertEqual([e["seq"] for e in self.server.parsed_events()], [1, 2, 3])
        self.assertEqual(self.server.sh('"$HOME/.local/share/agent-alert/core/agent-alert" tail --since 2').stdout.count("\n"), 1)

    def test_partial_line_with_the_next_number_does_not_satisfy_the_wait_and_the_next_event_does(self):
        self.install()
        pane, _ = self.server.new_pane("docs-fragment")
        self.start_follower(pane)
        last = self.server.parsed_events()[-1]["seq"]
        fragment = '{"version":1,"seq":%d,"time":"2026-10-17T12:30:05.123Z","worker":"torn","kind":"fin' % (last + 1)
        self.server.append_raw(fragment)  # a media fault: no closing brace, no newline
        self.server.wait_for_pane_text(pane, '"kind":"fin')
        self.assertNotEqual(self.short_wait(pane, last + 1).returncode, 0)
        waiting = self.wait_started(pane, last + 1)
        self.server.emit("intact", "finished")
        self.finish(waiting)
        events = self.server.parsed_events()
        self.assertEqual([e["seq"] for e in events], list(range(1, last + 2)))
        self.assertEqual(events[-1]["worker"], "intact")
        self.assertEqual(self.server.inbox_lines()[-2], fragment)

    def test_a_torn_line_ending_in_a_brace_wakes_the_wait_and_the_reader_skips_it(self):
        self.install()
        pane, _ = self.server.new_pane("docs-wake")
        self.start_follower(pane)
        last = self.server.parsed_events()[-1]["seq"]
        # the line is cut just before its last brace: it ends like a complete line but does not parse
        torn = '{"version":1,"seq":%d,"time":"2026-10-17T12:30:05.123Z","worker":"torn","kind":"finished","context":{"a":"b"}' % (last + 1)
        self.server.append_raw(torn)
        self.server.wait_for_pane_text(pane, '"context":{"a":"b"}')
        self.finish(self.wait_started(pane, last + 1))  # a match is a wake-up ...
        self.assertEqual([e["seq"] for e in self.server.parsed_events()], list(range(1, last + 1)))  # ... the line is not an event
        tailed = self.server.sh('"$HOME/.local/share/agent-alert/core/agent-alert" tail --since %d' % last)
        self.assertEqual((tailed.returncode, tailed.stdout), (0, ""))


class DoorbellReadmeTests(unittest.TestCase):
    """The doorbell section: its config JSON and session-id block as written, default paths."""

    def setUp(self):
        self.server = DocsHerdr(self)  # only for its scratch HOME holding the deployed tree; no server is started
        self.fake_bin = self.server.root / "fakebin"
        self.fake_bin.mkdir()
        self.record = self.server.root / "claude-record.txt"
        claude = self.fake_bin / "claude"
        claude.write_text('#!/bin/sh\nfor argument in "$@"; do printf \'%s\\n\' "$argument" >> "$FAKE_CLAUDE_RECORD"; done\nexit 0\n')
        claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
        self.server.env["PATH"] = "%s:%s" % (self.fake_bin, self.server.env["PATH"])
        self.server.env["FAKE_CLAUDE_RECORD"] = str(self.record)

    def test_config_json_and_session_id_block_as_written_ring_the_fake_claude_on_emit(self):
        config_block, = readme_blocks("Claude doorbell sink", "json")
        id_block, = readme_blocks("Claude doorbell sink", "sh")
        self.assertIn("PASTE-THE-SESSION-ID-HERE", id_block)
        self.assertEqual(list(json.loads(config_block)), ["sink"])
        home = self.server.home
        # step 1: the JSON block is the core config file, written as printed
        config_path = home / ".config" / "agent-alert" / "config.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(config_block, encoding="utf-8")
        # step 2: the shell block, with a made-up session id
        result = self.server.sh(id_block.replace("PASTE-THE-SESSION-ID-HERE", "fake-session-0000"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        doorbell_config = home / ".config" / "agent-alert" / "claude-doorbell.json"
        self.assertEqual(json.loads(doorbell_config.read_text()), {"session_id": "fake-session-0000"})
        self.assertEqual(stat.S_IMODE(doorbell_config.stat().st_mode), 0o600)
        # the real core, default paths: the event is in the default inbox and claude was rung
        self.server.emit("readme-worker", "finished")
        [event] = self.server.parsed_events()
        self.assertEqual((event["worker"], event["kind"]), ("readme-worker", "finished"))
        arguments = self.record.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(arguments), 4, arguments)
        self.assertEqual(arguments[0], "-p")
        self.assertIn("readme-worker", arguments[1])
        self.assertIn("finished", arguments[1])
        self.assertEqual(arguments[2:], ["--cloud", "fake-session-0000"])
        log = home / ".local" / "state" / "agent-alert" / "agent-alert.log"
        self.assertEqual(log.read_text() if log.exists() else "", "")


class ExampleTests(unittest.TestCase):
    """The examples as SPEC.md shows them."""

    def setUp(self):
        spec = SPEC.read_text(encoding="utf-8")
        self.spec_blocks = fenced_blocks(sections(spec)["Worked examples"], "python")
        self.assertEqual(len(self.spec_blocks), 2)
        self.source_text, self.consumer_text = self.spec_blocks
        # a deployed-layout copy that holds the examples exactly as SPEC.md prints them
        self.copy = Path(tempfile.mkdtemp(prefix="agent-alert-docs-"))
        self.addCleanup(shutil.rmtree, self.copy, ignore_errors=True)
        shutil.copytree(adapter_copy(), self.copy / "tree", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        self.tree = self.copy / "tree"
        self.source_example = self.tree / "examples" / "source-example.py"
        self.consumer_example = self.tree / "examples" / "consumer-example.py"
        self.source_example.write_text(self.source_text, encoding="utf-8")
        self.consumer_example.write_text(self.consumer_text, encoding="utf-8")
        self.scratch = common.Scratch(cli=self.tree / "core" / "agent-alert")
        self.addCleanup(self.scratch.cleanup)

    def run_example(self, path, stdin, env=None):
        return subprocess.run(
            [sys.executable, str(path)],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env or self.scratch.env(),
            timeout=60,
            text=True,
            encoding="utf-8",
        )

    def test_spec_includes_both_example_files_verbatim(self):
        self.assertEqual(self.source_text, (TOOL / "examples" / "source-example.py").read_text(encoding="utf-8"))
        self.assertEqual(self.consumer_text, (TOOL / "examples" / "consumer-example.py").read_text(encoding="utf-8"))

    def test_source_example_is_at_most_thirty_lines_calls_emit_and_names_nothing_from_herdr(self):
        lines = self.source_text.splitlines()
        self.assertLessEqual(len(lines), 30)
        self.assertIn('"emit"', self.source_text)
        self.assertIn('"--worker"', self.source_text)
        self.assertIn('"--kind"', self.source_text)
        self.assertNotIn("herdr", self.source_text.lower())
        self.assertNotIn("open(", self.source_text)  # a source never touches the inbox file

    def test_source_example_as_written_in_spec_emits_events_and_survives_a_failed_emit(self):
        feed = (
            "job-1 idle\n"
            "job-2 waiting\n"
            "job-3 failed\n"
            "job-4 closed\n"
            "nonsense\n"
            "job-5 sparkling\n"
            "job-6 idle extra words\n"
        )
        result = self.run_example(self.source_example, feed)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("skipped:"), 3, result.stderr)
        events = self.scratch.events()
        self.assertEqual([(e["seq"], e["worker"], e["kind"]) for e in events], [(1, "job-1", "finished"), (2, "job-2", "blocked"), (3, "job-3", "errored"), (4, "job-4", "exited")])
        # an unwritable inbox: each failure is reported, nothing crashes, the feed is still read to its end
        blocker = self.scratch.root / "not-a-directory"
        blocker.write_text("x")
        broken = self.scratch.env(AGENT_ALERT_INBOX=str(blocker / "inbox.jsonl"))
        result = self.run_example(self.source_example, "job-1 idle\njob-2 idle\n", env=broken)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("not recorded"), 2, result.stderr)

    def hand_written_inbox(self):
        """Real events around a hand-written unknown-kind line, a torn line and two non-event lines."""
        self.scratch.emit(worker="pane-1", kind="finished")
        with open(self.scratch.inbox, "a", encoding="utf-8") as inbox:
            inbox.write(UNKNOWN_KIND_LINE % 2 + "\n")
            inbox.write("this line is not json\n")
            inbox.write("[1, 2, 3]\n")
            inbox.write('{"version":1,"seq":"seven","kind":"finished"}\n')
            inbox.write('{"version":1,"seq":99,"time":"2026-10-17T12:30:05.123Z","worker":"torn","kind":"fin')
        self.scratch.emit(worker="pane-2", kind="blocked")

    def test_consumer_example_as_written_in_spec_reads_tail_and_raw_inbox_with_unknown_kind_and_junk(self):
        self.hand_written_inbox()
        tailed = self.scratch.run("tail", "--since", "0")
        self.assertEqual(tailed.returncode, 0, tailed.stderr)
        self.assertEqual([json.loads(line)["seq"] for line in tailed.stdout.splitlines()], [1, 2, 3])
        for name, feed in (("tail output", tailed.stdout), ("raw inbox", self.scratch.inbox_bytes().decode("utf-8"))):
            with self.subTest(name):
                result = self.run_example(self.consumer_example, feed)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")
                self.assertEqual(
                    result.stdout.splitlines(),
                    [
                        "1 pane-1 finished",
                        "2 pane-9 paused (kind unknown to this reader, shown anyway)",
                        "3 pane-2 blocked",
                    ],
                )

    def test_core_continues_after_the_hand_written_unknown_kind_line_and_can_acknowledge_past_it(self):
        self.hand_written_inbox()
        events = self.scratch.inbox_bytes().decode("utf-8").splitlines()
        self.assertEqual(json.loads(events[-1])["seq"], 3)  # the fragment's number 99 is not a sequence number
        self.assertEqual(self.scratch.run("ack", "3").returncode, 0)
        self.assertEqual(self.scratch.run("tail").stdout, "")


class ReadmeStructureTests(unittest.TestCase):
    def setUp(self):
        self.readme = README.read_text(encoding="utf-8")

    def test_the_two_adapter_readmes_are_gone_and_the_readme_has_a_section_for_each_adapter(self):
        self.assertFalse((TOOL / "adapters" / "herdr" / "README.md").exists())
        self.assertFalse((TOOL / "adapters" / "claude-doorbell" / "README.md").exists())
        self.assertEqual(sorted(p.name for p in TOOL.rglob("README.md")), ["README.md"])
        found = sections(self.readme)
        for heading in ("Herdr source adapter", "Claude doorbell sink", "Add an adapter", "Failure modes"):
            self.assertIn(heading, found)

    def test_readme_links_the_spec_and_every_link_resolves(self):
        self.assertIn("](./SPEC.md", self.readme)
        self.assertNotIn("adapters/herdr/README.md", self.readme)
        self.assertNotIn("adapters/claude-doorbell/README.md", self.readme)
        for path in re.findall(r"\]\((\./[^)#]+)", self.readme):
            self.assertTrue((TOOL / path).is_file(), path)
        for path, anchor in re.findall(r"\]\((\./[^)#]+)#([^)]+)\)", self.readme):
            slugs = heading_slugs((TOOL / path).read_text(encoding="utf-8"))
            self.assertIn(anchor, slugs, "%s has no heading for #%s" % (path, anchor))
        for anchor in re.findall(r"\]\(#([^)]+)\)", self.readme):
            self.assertIn(anchor, heading_slugs(self.readme), anchor)

    def test_readme_restates_none_of_the_format(self):
        for fragment in (
            '"time"',
            '"context"',
            "| `version`",
            "| `seq`",
            "| Kind |",
            "| Member |",
            "sink_timeout_seconds",
            "inbox_path",
            "RFC 2119",
        ):
            self.assertNotIn(fragment, self.readme)

    def test_readme_states_the_herdr_and_doorbell_facts(self):
        herdr = " ".join(re.sub(r"[`*]", "", sections(self.readme)["Herdr source adapter"]).split())
        for phrase in ("herdr plugin link", "errored is never emitted", "no error status", "no message text", "reads the named pane", "Duplicate and late events are accepted"):
            self.assertIn(phrase, herdr)
        doorbell = sections(self.readme)["Claude doorbell sink"]
        for phrase in ('"sink"', "AGENT_ALERT_DOORBELL_SESSION", "fixed 4 seconds", "claude exited with status N"):
            self.assertIn(phrase, doorbell)
        self.assertNotIn("timeout_seconds", doorbell)

    def test_readme_names_each_required_failure_mode_and_the_pane_procedure(self):
        text = self.readme.lower()
        for phrase in ("lost ring", "login expired or missing", "herdr not relaunched", "unwritable inbox", "ran before presence was recorded"):
            self.assertIn(phrase, text)
        self.assertIn("tail -n 20 -F", self.readme)
        self.assertIn("herdr pane wait-output", self.readme)
        self.assertIn("--source recent-unwrapped", self.readme)
        self.assertIn("a wake-up", self.readme)
        self.assertIn("parse the line and acknowledge only parsed events", self.readme.replace("\n", " "))

    def wait_expression(self, number):
        wait_block, = [b for b in readme_blocks("Usage") if "wait-output" in b]
        pattern = re.search(r"--regex '(.*?)'\"\$NEXT\"'(.*?)'", wait_block, re.S)
        return pattern.group(1) + str(number) + pattern.group(2)

    def test_readme_wait_expression_is_the_simple_wake_up_and_the_one_in_the_spec(self):
        self.assertEqual(self.wait_expression("N"), r'^\{"version":1,"seq":N,.*\}$')
        spec_section = sections(SPEC.read_text(encoding="utf-8"))["Inbox file"]
        spec_block, = [b for b in fenced_blocks(spec_section, "") if b.startswith("^")]
        self.assertEqual(spec_block.strip(), self.wait_expression(12))
        self.assertIn("a wake-up", spec_section)

    def test_readme_wait_expression_wakes_on_the_next_sequence_number_only(self):
        compiled = re.compile(self.wait_expression(12), re.M)
        complete = '{"version":1,"seq":12,"time":"2026-10-17T12:30:05.123Z","worker":"w","kind":"finished"}'
        with_context = complete[:-1] + ',"context":{"workspace":"main"}}'
        for whole in (complete, with_context):
            self.assertTrue(compiled.search("older\n" + whole + "\nnewer\n"), whole)
            self.assertIsNotNone(json.loads(whole))
        self.assertFalse(compiled.search(complete.replace('"seq":12,', '"seq":123,')))
        self.assertFalse(compiled.search(complete[:-1]))  # no closing brace yet
        self.assertFalse(compiled.search('{"version":1,"seq":12,"time":"2026-10-17T12:30:05.123Z","worker":"w","kind":"fin'))
        # a torn line that ends in a brace is a wake-up that the reader then rejects by parsing it
        torn = with_context[:-1]
        self.assertTrue(compiled.search(torn))
        with self.assertRaises(ValueError):
            json.loads(torn)


if __name__ == "__main__":
    unittest.main()
