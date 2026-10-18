"""Tests that execute the documentation (README.md, SPEC.md, examples/).

Run (from the repository root):

    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
        -s dot_local/share/agent-alert/tests -p 'test_docs.py'

* The shell blocks under "Install" and "Usage" in README.md are extracted from
  the file and run literally (with `sh -c`) against one scratch Herdr 0.9.1
  server at a time: the deployed tree is copied to `$HOME/.local/share/agent-alert`
  of a scratch home, so the README's own `~`-relative paths are the ones used.
  The README's pane procedure (`tail -F` in a pane) and its next-sequence
  `herdr pane wait-output` command run as written, with the pane and without it,
  and with a hand-made partial line in the inbox.
* The two Python examples are extracted from the fenced blocks of SPEC.md, shown
  to equal the files in examples/, and run as written, including a hand-written
  line of a kind they have never heard of.
* The README is checked to link SPEC.md and the adapter READMEs and not to restate
  the format.

Nothing here touches the live Herdr, home or `claude`; every path is scratch.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from test_herdr import HERDR_REQUIRED, ScratchHerdr, adapter_copy  # noqa: E402

TOOL = common.TOOL_SOURCE_DIR
README = TOOL / "README.md"
SPEC = TOOL / "SPEC.md"

# SPEC's example event line, used to prove a hand-written line of an unknown kind.
UNKNOWN_KIND_LINE = '{"version":1,"seq":%d,"time":"2026-10-17T12:30:05.123Z","worker":"pane-9","kind":"paused","summary":"a kind this reader never heard of","extra":{"a":1}}'


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
    """Return the text of every ```<language> fenced block, in order."""
    pattern = r"^```" + re.escape(language) + r"\n(.*?)^```$"
    return re.findall(pattern, markdown, re.S | re.M)


def readme_blocks(section):
    return fenced_blocks(sections(README.read_text(encoding="utf-8"))[section], "sh")


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

    def emit(self, worker, kind, summary):
        result = subprocess.run(
            [str(self.core), "emit", "--worker", worker, "--kind", kind, "--summary", summary],
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


class ReadmeProcedureTests(unittest.TestCase):
    """The README's steps, run as written against a scratch Herdr server."""

    def setUp(self):
        if not HERDR_REQUIRED:
            self.skipTest("herdr is not installed")
        self.server = DocsHerdr(self)
        self.server.start()
        self.assertEqual(self.server.version, "0.9.1")
        self.install_block, = readme_blocks("Install")
        blocks = readme_blocks("Usage")
        self.assertEqual(len(blocks), 4)
        self.basic_block, self.pane_block, self.read_block, self.wait_block = blocks

    def install(self):
        result = self.server.sh(self.install_block)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        listed = self.server.herdr("plugin", "list").stdout
        self.assertIn("agent-alert", listed)
        self.assertIn("enabled", listed)

    def start_follower(self, pane):
        """Run the README's pane procedure, then prove the follower is live by its first event."""
        self.server.emit("follower-check", "finished", "follower is live")
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
        return stdout, stderr

    def short_wait(self, pane, next_seq):
        """The README's wait command with its 30 s limit cut to 2 s, for a case that must time out."""
        self.assertIn("--timeout 30000", self.wait_block)
        block = self.wait_block.replace("--timeout 30000", "--timeout 2000")
        return self.server.sh(block, PANE=pane, NEXT=next_seq, timeout=30)

    def test_install_block_links_and_enables_the_plugin(self):
        self.install()
        logs = self.server.api("plugin", "log", "list")["logs"]
        self.assertIsInstance(logs, list)

    def test_basic_usage_block_emits_reads_and_acknowledges_without_any_pane(self):
        result = self.server.sh(self.basic_block)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 1, result.stdout)
        event = json.loads(lines[0])
        self.assertEqual((event["seq"], event["worker"], event["kind"]), (1, "my-pane", "finished"))
        self.assertEqual(event["summary"], "Should I delete the staging branch?")
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
        long_summary = "Tests pass. " * 20 + "Shall I merge it now?"
        self.server.emit("direct", "blocked", long_summary)
        self.finish(waiting)
        self.assertIn("Shall I merge it now?", self.server.pane_text(pane))
        # an event that has not happened is not matched: a later number does not satisfy the wait
        self.assertNotEqual(self.short_wait(pane, next_seq + 1).returncode, 0)
        # read, as the README shows
        shown = self.server.sh(self.read_block, PANE=pane)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertIn('"seq":%d,' % next_seq, shown.stdout)
        for entry in self.server.api("plugin", "log", "list")["logs"]:
            self.assertEqual((entry["status"], entry["exit_code"], entry["stderr"]), ("succeeded", 0, ""), entry)

    def test_inbox_is_the_same_with_the_pane_closed_and_a_pane_without_the_follower_never_satisfies_the_wait(self):
        self.install()
        silent_pane, _ = self.server.new_pane("docs-silent")
        self.server.emit("w1", "finished", "first")
        # no follower in this pane: the wait fails, the inbox is unaffected
        self.assertNotEqual(self.short_wait(silent_pane, 1).returncode, 0)
        self.assertEqual([e["seq"] for e in self.server.parsed_events()], [1])
        pane, _ = self.server.new_pane("docs-closing")
        self.start_follower(pane)
        before = self.server.inbox_path.read_bytes()
        self.server.herdr("pane", "close", pane)
        self.server.emit("w1", "finished", "second, with the pane gone")
        after = self.server.inbox_path.read_bytes()
        self.assertTrue(after.startswith(before), "the inbox changed anything but its end")
        self.assertEqual([e["seq"] for e in self.server.parsed_events()], [1, 2, 3])
        self.assertEqual(self.server.sh('"$HOME/.local/share/agent-alert/core/agent-alert" tail --since 2').stdout.count("\n"), 1)

    def test_partial_line_with_the_next_number_does_not_satisfy_the_wait_and_the_next_event_does(self):
        self.install()
        pane, _ = self.server.new_pane("docs-fragment")
        self.start_follower(pane)
        last = self.server.parsed_events()[-1]["seq"]
        fragment = '{"version":1,"seq":%d,"time":"2026-10-17T12:30:05.123Z","worker":"torn","kind":"finished","summary":"cut off here' % (last + 1)
        with open(self.server.inbox_path, "ab") as inbox:
            inbox.write(fragment.encode("utf-8"))  # a media fault: no closing brace, no newline
        deadline = time.monotonic() + 20
        while "cut off here" not in self.server.pane_text(pane):
            self.assertLess(time.monotonic(), deadline, "the pane never showed the fragment")
            time.sleep(0.2)
        self.assertNotEqual(self.short_wait(pane, last + 1).returncode, 0)
        waiting = self.wait_started(pane, last + 1)
        self.server.emit("w1", "finished", "intact after the fragment")
        self.finish(waiting)
        events = self.server.parsed_events()
        self.assertEqual([e["seq"] for e in events], list(range(1, last + 2)))
        self.assertEqual(events[-1]["summary"], "intact after the fragment")
        self.assertEqual(self.server.inbox_lines()[-2], fragment)


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

    def test_source_example_is_at_most_thirty_lines_and_calls_emit(self):
        lines = self.source_text.splitlines()
        self.assertLessEqual(len(lines), 30)
        self.assertIn('"emit"', self.source_text)
        self.assertNotIn("open(", self.source_text)  # a source never touches the inbox file

    def test_source_example_as_written_in_spec_emits_events_and_survives_a_failed_emit(self):
        feed = (
            "job-1 done Build finished. Deploy now?\n"
            "job-2 waiting Need an approval for the migration\n"
            "job-3 failed Rate limited by the API\n"
            "job-4 gone\n"
            "nonsense\n"
            "job-5 sparkling not a status\n"
            "job-6 done token=abcdef123456 was in the log\n"
        )
        result = self.run_example(self.source_example, feed)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("skipped:"), 2, result.stderr)
        events = self.scratch.events()
        self.assertEqual([(e["seq"], e["worker"], e["kind"]) for e in events], [(1, "job-1", "finished"), (2, "job-2", "blocked"), (3, "job-3", "errored"), (4, "job-4", "exited"), (5, "job-6", "finished")])
        self.assertEqual(events[0]["summary"], "Build finished. Deploy now?")
        self.assertEqual(events[0]["context"], {"source": "example"})
        self.assertEqual(events[3]["summary"], "")
        self.assertNotIn("abcdef123456", self.scratch.inbox_bytes().decode())
        # an unwritable inbox: each failure is reported, nothing crashes, the feed is still read to its end
        blocker = self.scratch.root / "not-a-directory"
        blocker.write_text("x")
        broken = self.scratch.env(AGENT_ALERT_INBOX=str(blocker / "inbox.jsonl"))
        result = self.run_example(self.source_example, "job-1 done a\njob-2 done b\n", env=broken)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr.count("not recorded"), 2, result.stderr)

    def hand_written_inbox(self):
        """Real events around a hand-written unknown-kind line, a torn line and two non-event lines."""
        self.scratch.emit(worker="pane-1", kind="finished", summary="first")
        with open(self.scratch.inbox, "a", encoding="utf-8") as inbox:
            inbox.write(UNKNOWN_KIND_LINE % 2 + "\n")
            inbox.write("this line is not json\n")
            inbox.write("[1, 2, 3]\n")
            inbox.write('{"version":1,"seq":"seven","kind":"finished"}\n')
            inbox.write('{"version":1,"seq":99,"time":"2026-10-17T12:30:05.123Z","worker":"torn","kind":"fin')
        self.scratch.emit(worker="pane-2", kind="blocked", summary="after the damage")

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
                        "1 pane-1 finished: first",
                        "2 pane-9 paused (kind unknown to this reader, shown anyway): a kind this reader never heard of",
                        "3 pane-2 blocked: after the damage",
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

    def test_readme_links_the_spec_and_both_adapter_readmes_and_every_link_resolves(self):
        for target in ("./SPEC.md", "./adapters/herdr/README.md", "./adapters/claude-doorbell/README.md"):
            self.assertIn("](%s" % target, self.readme)
        for path in re.findall(r"\]\((\./[^)#]+)", self.readme):
            self.assertTrue((TOOL / path).is_file(), path)
        for path, anchor in re.findall(r"\]\((\./[^)#]+)#([^)]+)\)", self.readme):
            slugs = heading_slugs((TOOL / path).read_text(encoding="utf-8"))
            self.assertIn(anchor, slugs, "%s has no heading for #%s" % (path, anchor))

    def test_readme_restates_none_of_the_format(self):
        for fragment in (
            '"time"',
            '"summary"',
            '"context"',
            "| `version`",
            "| `seq`",
            "| `finished`",
            "| `blocked`",
            "| `errored`",
            "| `exited`",
            "free_space_margin_bytes",
            "sink_timeout_seconds",
            "inbox_path",
            "RFC 2119",
        ):
            self.assertNotIn(fragment, self.readme)
        self.assertNotIn('{"version":1,"seq":1,', self.readme)

    def test_readme_names_each_required_failure_mode_and_the_pane_procedure(self):
        text = self.readme.lower()
        for phrase in ("lost ring", "login expired or missing", "herdr not relaunched", "inbox not writable", "ran before presence was recorded"):
            self.assertIn(phrase, text)
        self.assertIn("tail -n 20 -F", self.readme)
        self.assertIn("herdr pane wait-output", self.readme)
        self.assertIn("--source recent-unwrapped", self.readme)

    def test_readme_wait_expression_matches_a_complete_event_line_and_not_a_partial_one(self):
        wait_block, = [b for b in readme_blocks("Usage") if "wait-output" in b]
        pattern = re.search(r"--regex '(.*?)'\"\$NEXT\"'(.*?)'", wait_block, re.S)
        expression = pattern.group(1) + "12" + pattern.group(2)
        compiled = re.compile(expression.replace("(?m)", ""), re.M)
        complete = '{"version":1,"seq":12,"time":"2026-10-17T12:30:05.123Z","worker":"w","kind":"finished","summary":"x"}'
        self.assertTrue(compiled.search("older\n" + complete + "\nnewer\n"))
        self.assertFalse(compiled.search(complete[:-1]))
        self.assertFalse(compiled.search(complete.replace('"seq":12,', '"seq":123,')))
        self.assertFalse(compiled.search('{"version":1,"seq":12,"time":"2026-10-17T12:30:05.123Z","worker":"w","kind":"fin'))


if __name__ == "__main__":
    unittest.main()
