"""Tests that execute the documentation (README.md, SPEC.md, examples/).

Run (from the repository root):

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
        -s dot_local/share/agent-alert/tests -p 'test_docs.py'

* The shell blocks of README.md (Usage, the doorbell section)
  are extracted from the file and run literally (with `sh -c`): the deployed tree
  is copied to `$HOME/.local/share/agent-alert` of a scratch home, so the README's
  own `~`-relative paths are the ones used.
* The doorbell section's config JSON and session-id block run in a scratch HOME
  with a scripted `claude` on PATH.
* The two Python examples are extracted from the fenced blocks of SPEC.md, shown
  to equal the files in examples/, and run as written, including a hand-written
  line of a kind they have never heard of.
* The two adapter READMEs are gone; README.md has a section for each adapter,
  and its wait expression is the one SPEC.md gives.

Nothing here touches the live home or `claude`; every path is scratch.
"""

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

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


def adapter_copy():
    """The deployed-layout copy of the tree (adapters/ kept)."""
    return common.deployed_copy(delete_adapters=False)


class ScratchHome:
    """A scratch HOME that holds the deployed tree and uses the default paths."""

    def __init__(self, test_case):
        self.root = Path(tempfile.mkdtemp(prefix="agent-alert-docs-")).resolve()
        test_case.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.home = self.root / "home"
        self.home.mkdir()
        # No AGENT_ALERT_* variable: the README's default paths under the scratch HOME are used.
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_ALERT_")}
        self.env.update(
            HOME=str(self.home),
            XDG_CONFIG_HOME=str(self.home / ".config"),
            XDG_STATE_HOME=str(self.home / ".local" / "state"),
            LANG="en_US.UTF-8",
        )
        self.installed = self.home / ".local" / "share" / "agent-alert"
        shutil.copytree(adapter_copy(), self.installed, ignore=shutil.ignore_patterns("tests", "__pycache__"))
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


class ReadmeUsageTests(unittest.TestCase):
    """The README's Usage block, run as written."""

    def setUp(self):
        self.server = ScratchHome(self)
        self.assertEqual(readme_blocks("Install", "sh"), [])  # the install step is `chezmoi apply`, never run here
        self.basic_block, = readme_blocks("Usage")

    def test_basic_usage_block_emits_reads_and_acknowledges(self):
        result = self.server.sh(self.basic_block)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, result.stdout)
        event = json.loads(lines[0])
        self.assertEqual((event["seq"], event["worker"], event["kind"]), (1, "my-pane", "finished"))
        self.assertEqual(self.server.inbox_lines(), [lines[0]])
        self.assertEqual(json.loads((self.server.inbox_path.parent / "inbox.jsonl.ack").read_text()), {"acked": 1})
        self.assertEqual(self.server.sh('"$HOME/.local/share/agent-alert/core/agent-alert" tail').stdout, "")


class DoorbellReadmeTests(unittest.TestCase):
    """The doorbell section: its config JSON and session-id block as written, default paths."""

    def setUp(self):
        self.server = ScratchHome(self)
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
        self.assertEqual(len(arguments), 6, arguments)
        self.assertEqual(arguments[:3], ["--safe-mode", "--no-session-persistence", "-p"])
        self.assertIn("readme-worker", arguments[3])
        self.assertIn("finished", arguments[3])
        self.assertEqual(arguments[4:], ["--cloud", "fake-session-0000"])
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
        self.assertFalse((TOOL / "adapters" / "herdr").exists())
        self.assertFalse((TOOL / "adapters" / "claude-doorbell" / "README.md").exists())
        self.assertEqual(sorted(p.name for p in TOOL.rglob("README.md")), ["README.md"])
        found = sections(self.readme)
        for heading in ("Claude doorbell sink", "Add an adapter", "Failure modes"):
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

    def test_readme_states_the_doorbell_facts(self):
        doorbell = sections(self.readme)["Claude doorbell sink"]
        for phrase in ('"sink"', "AGENT_ALERT_DOORBELL_SESSION", "fixed 4 seconds", "claude exited with status N",
                       "none is dropped", "doorbell.py --flush", "+N more"):
            self.assertIn(phrase, doorbell)
        self.assertNotIn("timeout_seconds", doorbell)

    def test_readme_names_each_required_failure_mode_and_how_to_watch_and_wait(self):
        text = self.readme.lower()
        for phrase in ("lost ring", "login expired or missing", "unwritable inbox"):
            self.assertIn(phrase, text)
        self.assertIn("tail -n 20 -F", self.readme)
        self.assertIn("a wake-up", self.readme)
        self.assertIn("parse the line and acknowledge only parsed events", self.readme.replace("\n", " "))

    def wait_expression(self, number):
        spec_section = sections(SPEC.read_text(encoding="utf-8"))["Inbox file"]
        spec_block, = [b for b in fenced_blocks(spec_section, "") if b.startswith("^")]
        return spec_block.strip().replace("12", str(number))

    def test_readme_wait_expression_is_the_simple_wake_up_and_the_one_in_the_spec(self):
        self.assertEqual(self.wait_expression("N"), r'^\{"version":1,"seq":N,.*\}$')
        self.assertIn(r'`^\{"version":1,"seq":N,.*\}$`', self.readme)
        self.assertIn("a wake-up", sections(SPEC.read_text(encoding="utf-8"))["Inbox file"])

    def test_spec_wait_expression_wakes_on_the_next_sequence_number_only(self):
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
