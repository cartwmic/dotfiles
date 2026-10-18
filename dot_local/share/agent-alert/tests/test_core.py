"""Black-box tests of the agent-alert core CLI.

Run (from the repository root):

    python3 -m unittest discover -s dot_local/share/agent-alert/tests -p 'test_core.py'

Every test runs the real core/agent-alert from a deployed-layout copy that
chezmoi archived (adapters/ and examples/ deleted) with a scratch HOME.
"""

import importlib.machinery
import importlib.util
import itertools
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

TIME_PATTERN = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


class CoreTestCase(unittest.TestCase):
    def setUp(self):
        self.scratch = common.Scratch()
        self.addCleanup(self.scratch.cleanup)

    def emit_ok(self, **kwargs):
        result = self.scratch.emit(**kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def write_script(self, name, body):
        path = self.scratch.root / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path


class DeployedLayoutTests(CoreTestCase):
    def test_copy_has_no_adapters_and_core_names_no_adapter(self):
        copy = common.deployed_copy()
        self.assertFalse((copy / "adapters").exists())
        self.assertTrue(os.access(copy / "core" / "agent-alert", os.X_OK))
        for path in (copy / "core").rglob("*"):
            if path.is_file():
                text = path.read_text(encoding="utf-8", errors="replace").lower()
                self.assertNotIn("herdr", text, str(path))
                self.assertNotIn("claude", text, str(path))

    def test_exactly_three_commands(self):
        helped = self.scratch.run("--help")
        self.assertEqual(helped.returncode, 0)
        self.assertIn("{emit,tail,ack}", helped.stdout)
        for name in ("follow", "watch", "list"):
            self.assertEqual(self.scratch.run(name).returncode, 2)


class EmitFormatTests(CoreTestCase):
    def test_all_four_kinds_are_valid_lines_with_consecutive_seq(self):
        for kind in ("finished", "blocked", "errored", "exited"):
            self.emit_ok(worker="pane-" + kind, kind=kind, summary="done with " + kind)
        events = self.scratch.events()
        self.assertEqual([e["seq"] for e in events], [1, 2, 3, 4])
        self.assertEqual([e["kind"] for e in events], ["finished", "blocked", "errored", "exited"])
        for event in events:
            self.assertEqual(event["version"], 1)
            self.assertRegex(event["time"], TIME_PATTERN)
            self.assertTrue(event["worker"])
            self.assertIsInstance(event["summary"], str)
            self.assertNotIn("context", event)
        first_line = self.scratch.inbox_bytes().splitlines()[0]
        self.assertTrue(first_line.startswith(b'{"version":1,"seq":1,"time":"'), first_line)

    def test_default_inbox_and_config_locations_under_home(self):
        environment = {"HOME": str(self.scratch.home), "PATH": os.environ["PATH"]}
        result = self.scratch.run("emit", "--worker", "w", "--kind", "finished", env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        default_inbox = self.scratch.home / ".local" / "share" / "coordinator" / "inbox.jsonl"
        self.assertEqual(json.loads(default_inbox.read_text())["seq"], 1)

        config_dir = self.scratch.home / ".config" / "agent-alert"
        config_dir.mkdir(parents=True)
        moved = self.scratch.root / "moved.jsonl"
        (config_dir / "config.json").write_text(json.dumps({"inbox_path": str(moved)}))
        result = self.scratch.run("emit", "--worker", "w", "--kind", "finished", env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(moved.read_text())["seq"], 1)

    def test_environment_overrides_config_file(self):
        configured = self.scratch.root / "from-config.jsonl"
        self.scratch.write_config(inbox_path=str(configured))
        self.emit_ok()
        self.assertTrue(self.scratch.inbox.exists())
        self.assertFalse(configured.exists())

    def test_summary_from_stdin_and_whitespace_collapse(self):
        self.emit_ok(summary="-", stdin="line one\n\n  line\ttwo \x07 end\n")
        self.assertEqual(self.scratch.events()[0]["summary"], "line one line two end")

    def test_context_stored_as_short_strings(self):
        self.emit_ok(summary="x")  # seq 1, no context
        result = self.scratch.run(
            "emit", "--worker", "w1", "--kind", "blocked", "--context", "workspace=main label", "--context-json", '{"agent":"pi"}'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.scratch.events()[1]["context"], {"agent": "pi", "workspace": "main label"})


class EmitConcurrencyTests(CoreTestCase):
    def burst(self, count, kind="finished"):
        barrier = threading.Barrier(count)
        results = [None] * count

        def worker(index):
            barrier.wait()
            results[index] = self.scratch.emit(worker="burst-%d" % index, kind=kind, summary="burst %d" % index)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_simultaneous_emits_are_intact_and_seq_continues_across_runs(self):
        self.burst(12)
        events = self.scratch.events()
        self.assertEqual(sorted(e["seq"] for e in events), list(range(1, 13)))
        self.assertEqual([e["seq"] for e in events], list(range(1, 13)), "file order must follow seq")
        self.assertEqual(sorted(e["worker"] for e in events), sorted("burst-%d" % i for i in range(12)))
        self.burst(6, kind="blocked")
        events = self.scratch.events()
        self.assertEqual([e["seq"] for e in events], list(range(1, 19)))

    def test_two_rapid_emits_same_worker_and_kind_give_two_lines(self):
        self.emit_ok(worker="same", kind="finished", summary="turn")
        self.emit_ok(worker="same", kind="finished", summary="turn")
        events = self.scratch.events()
        self.assertEqual([(e["seq"], e["worker"], e["kind"]) for e in events], [(1, "same", "finished"), (2, "same", "finished")])


class EmitRefusalTests(CoreTestCase):
    def test_unwritable_inbox_exits_nonzero_with_nothing_written(self):
        blocker = self.scratch.root / "blocked"
        blocker.write_text("a file where a directory is needed")
        env = self.scratch.env(AGENT_ALERT_INBOX=str(blocker / "inbox.jsonl"))
        result = self.scratch.emit(env=env)
        self.assertEqual(result.returncode, 3)
        self.assertIn("agent-alert:", result.stderr)
        self.assertEqual(blocker.read_text(), "a file where a directory is needed")
        self.assertIn("emit failed", self.scratch.log_text())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root ignores directory modes")
    def test_read_only_inbox_directory_exits_nonzero_with_nothing_written(self):
        directory = self.scratch.root / "readonly"
        directory.mkdir()
        directory.chmod(0o500)
        self.addCleanup(directory.chmod, 0o700)
        env = self.scratch.env(AGENT_ALERT_INBOX=str(directory / "inbox.jsonl"))
        result = self.scratch.emit(env=env)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(os.listdir(directory), [])

    def assert_rejected(self, *args, stdin=None):
        self.emit_ok(summary="baseline")
        before = self.scratch.inbox_bytes()
        result = self.scratch.run("emit", *args, stdin=stdin)
        self.assertNotEqual(result.returncode, 0, args)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("agent-alert", result.stderr)
        self.assertEqual(self.scratch.inbox_bytes(), before)

    def test_unknown_kind_is_rejected(self):
        self.assert_rejected("--worker", "w1", "--kind", "paused")

    def test_empty_or_blank_worker_is_rejected(self):
        self.assert_rejected("--worker", "", "--kind", "finished")
        self.assert_rejected("--worker", "   ", "--kind", "finished")

    def test_missing_worker_is_rejected(self):
        self.assert_rejected("--kind", "finished")

    def test_non_string_context_value_is_rejected(self):
        self.assert_rejected("--worker", "w1", "--kind", "finished", "--context-json", '{"count": 3}')
        self.assert_rejected("--worker", "w1", "--kind", "finished", "--context-json", '{"nested": {"a": "b"}}')
        self.assert_rejected("--worker", "w1", "--kind", "finished", "--context-json", '["a"]')
        self.assert_rejected("--worker", "w1", "--kind", "finished", "--context-json", "not json")

    def test_context_beyond_limits_is_rejected(self):
        many = json.dumps({"k%d" % i: "v" for i in range(9)})
        self.assert_rejected("--worker", "w1", "--kind", "finished", "--context-json", many)
        self.assert_rejected("--worker", "w1", "--kind", "finished", "--context", "x" * 33 + "=v")

    def test_secret_shaped_worker_is_rejected(self):
        self.assert_rejected("--worker", "sk-abcdefghijklmnop", "--kind", "finished")

    def test_bad_configuration_is_rejected_before_writing(self):
        self.scratch.config.write_text("{not json")
        result = self.scratch.emit()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.scratch.inbox_bytes(), b"")

    def test_margin_above_available_space_refuses_with_inbox_unchanged(self):
        self.emit_ok(summary="before")
        before = self.scratch.inbox_bytes()
        self.scratch.write_config(free_space_margin_bytes=2**62)
        result = self.scratch.emit(summary="refused")
        self.assertEqual(result.returncode, 3)
        self.assertIn("free space", result.stderr)
        self.assertEqual(self.scratch.inbox_bytes(), before)
        self.assertIn("not enough free space", self.scratch.log_text())
        # With the margin removed the same call succeeds: the refusal was the margin.
        self.scratch.write_config(free_space_margin_bytes=0)
        self.emit_ok(summary="accepted")
        self.assertEqual(self.scratch.events()[-1]["seq"], 2)


class FragmentTests(CoreTestCase):
    def test_hand_made_fragment_then_emit_gives_own_line_and_next_seq(self):
        self.emit_ok(summary="first")
        fragment = b'{"version":1,"seq":2,"time":"2026-01-01T00:00:00.000Z","wor'
        with open(self.scratch.inbox, "ab") as handle:
            handle.write(fragment)
        before = self.scratch.inbox_bytes()
        # tail and ack skip the fragment
        tailed = self.scratch.run("tail", "--since", "0")
        self.assertEqual(tailed.returncode, 0)
        self.assertEqual([json.loads(l)["seq"] for l in tailed.stdout.splitlines()], [1])
        self.assertEqual(self.scratch.run("ack", "1").returncode, 0)
        self.assertEqual(self.scratch.run("ack", "2").returncode, 2)
        self.assertEqual(self.scratch.inbox_bytes(), before)

        self.emit_ok(summary="after fragment")
        after = self.scratch.inbox_bytes()
        self.assertTrue(after.startswith(before + b"\n"), "emit must first end the fragment with a newline")
        new_line = after[len(before) + 1:]
        self.assertTrue(new_line.endswith(b"\n"))
        decoded = json.loads(new_line)
        self.assertEqual(decoded["seq"], 2)
        self.assertEqual(decoded["summary"], "after fragment")
        tailed = self.scratch.run("tail", "--since", "0")
        self.assertEqual([json.loads(l)["seq"] for l in tailed.stdout.splitlines()], [1, 2])

    def file_size_limit_bytes(self):
        """What `ulimit -f 1` allows on this system (the unit of ulimit -f differs by shell)."""
        probe = self.scratch.root / "limit-probe"
        script = "import os; fd = os.open(%r, os.O_WRONLY | os.O_CREAT); os.write(fd, bytes(65536))" % str(probe)
        subprocess.run(["sh", "-c", 'ulimit -f 1; exec "$@"', "sh", sys.executable, "-c", script], stderr=subprocess.DEVNULL)
        return probe.stat().st_size

    def test_short_write_under_file_size_limit_leaves_next_emit_intact(self):
        limit = self.file_size_limit_bytes()
        self.assertGreater(limit, 0)
        self.emit_ok(summary="first")
        first_size = len(self.scratch.inbox_bytes())
        with open(self.scratch.inbox, "ab") as handle:
            handle.write(b"x" * (limit - first_size - 100) + b"\n")  # not an event: readers skip it
        before = self.scratch.inbox_bytes()
        self.assertLess(len(before), limit)
        result = self.scratch.emit(worker="w2", summary="y" * 150, wrapper="ulimit -f 1;")
        self.assertNotEqual(result.returncode, 0)
        partial = self.scratch.inbox_bytes()
        self.assertGreater(len(partial), len(before), "the limit should have cut the write short")
        self.assertTrue(partial.startswith(before))
        self.assertFalse(partial.endswith(b"\n"))

        self.emit_ok(worker="w3", summary="recovered")
        final = self.scratch.inbox_bytes()
        self.assertTrue(final.startswith(partial + b"\n"))
        last = json.loads(final[len(partial) + 1:])
        self.assertEqual((last["seq"], last["worker"]), (2, "w3"))
        tailed = self.scratch.run("tail", "--since", "0")
        self.assertEqual([json.loads(l)["seq"] for l in tailed.stdout.splitlines()], [1, 2])


class SummaryTests(CoreTestCase):
    SECRETS = [
        "sk-ant-api03-FAKEFAKEFAKE1234567890",
        "ghp_FAKEFAKEFAKEFAKE1234567890abcd",
        "FAKEbearerTOKEN1234567890",
        "hunter2hunter2",
        "FAKEAPIKEYVALUE99XYZ",
    ]
    QUESTION = "Should I go ahead and delete the staging branch now?"

    def assert_masked(self, text):
        for secret in self.SECRETS:
            self.assertNotIn(secret, text)
            for start in range(0, len(secret) - 9):
                self.assertNotIn(secret[start:start + 10], text, "secret fragment leaked")

    def test_long_multi_paragraph_message_keeps_the_end_and_masks_secrets(self):
        preamble = "I started by reading the repository layout and the existing tests. " * 6
        message = "\n\n".join(
            [
                preamble,
                "Config note: use sk-ant-api03-FAKEFAKEFAKE1234567890 for the client.",
                "Then I pushed with ghp_FAKEFAKEFAKEFAKE1234567890abcd and Authorization: Bearer FAKEbearerTOKEN1234567890 in the header.",
                "The settings file has password=hunter2hunter2 and api_key: FAKEAPIKEYVALUE99XYZ in it.",
                "Everything else passed.",
                self.QUESTION,
            ]
        )
        self.assertGreater(len(message), 600)
        self.emit_ok(summary=message)
        summary = self.scratch.events()[0]["summary"]
        self.assertLessEqual(len(summary), 200)
        self.assertNotIn("\n", summary)
        self.assertTrue(summary.endswith(self.QUESTION), summary)
        self.assert_masked(summary)
        self.assertNotIn("repository layout", summary)
        self.assert_masked(self.scratch.inbox_bytes().decode("utf-8"))

    def test_secrets_are_masked_before_the_cut_so_a_split_secret_cannot_survive(self):
        secret = "ghp_" + "Q" * 30
        tail = " ".join(["word"] * 34)  # about 170 characters after the secret
        self.emit_ok(summary="start " * 40 + secret + " " + tail)
        summary = self.scratch.events()[0]["summary"]
        self.assertLessEqual(len(summary), 200)
        self.assertNotIn("QQQQQ", summary)
        self.assertNotIn("ghp_", summary)

    def test_secret_shaped_context_values_are_stored_masked(self):
        self.emit_ok(summary="ok")
        result = self.scratch.run(
            "emit", "--worker", "w", "--kind", "finished",
            "--context", "workspace=ghp_FAKEFAKEFAKEFAKE1234567890abcd",
            "--context-json", json.dumps({"label": "sk-ant-api03-FAKEFAKEFAKE1234567890", "note": "password=hunter2hunter2"}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        raw = self.scratch.inbox_bytes().decode("utf-8")
        self.assert_masked(raw)
        context = self.scratch.events()[1]["context"]
        self.assertEqual(context["workspace"], "***")
        self.assertEqual(context["label"], "***")
        self.assertEqual(context["note"], "password=***")

    TAIL = "FAKE_PRIVATE_TAIL_99"

    def assert_tail_masked(self, stored_text):
        self.assertNotIn(self.TAIL, stored_text)
        self.assertNotIn("FAKE_PRIVATE", stored_text)
        self.assertIn("***", stored_text)

    def test_json_style_escaped_double_quote_in_summary_is_fully_masked(self):
        self.emit_ok(summary='{"password":"a\\"%s"}' % self.TAIL)
        self.assert_tail_masked(self.scratch.inbox_bytes().decode("utf-8"))
        self.assertEqual(self.scratch.events()[0]["summary"], '{"password":***}')

    def test_json_style_escaped_double_quote_in_context_value_is_fully_masked(self):
        result = self.scratch.run(
            "emit", "--worker", "w", "--kind", "finished", "--summary", "ok",
            "--context-json", json.dumps({"payload": '{"password":"a\\"%s"}' % self.TAIL}),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_tail_masked(self.scratch.inbox_bytes().decode("utf-8"))
        self.assertEqual(self.scratch.events()[0]["context"]["payload"], '{"password":***}')

    def test_single_quoted_value_with_escaped_single_quote_is_fully_masked(self):
        self.emit_ok(summary="token='it\\'s %s' and ordinary words" % self.TAIL)
        self.assert_tail_masked(self.scratch.inbox_bytes().decode("utf-8"))
        self.assertEqual(self.scratch.events()[0]["summary"], "token=*** and ordinary words")

    def test_escaped_backslash_before_the_closing_quote_ends_the_value(self):
        # "a\\" is a complete value: the text after it is not part of the secret.
        self.emit_ok(summary='password="%s\\\\" and ordinary words' % self.TAIL)
        self.assert_tail_masked(self.scratch.inbox_bytes().decode("utf-8"))
        self.assertEqual(self.scratch.events()[0]["summary"], "password=*** and ordinary words")

    def test_escaped_backslash_followed_by_escaped_quote_stays_inside_the_value(self):
        self.emit_ok(summary='{"password":"a\\\\\\"%s"} done' % self.TAIL)
        self.assert_tail_masked(self.scratch.inbox_bytes().decode("utf-8"))
        self.assertEqual(self.scratch.events()[0]["summary"], '{"password":***} done')

    def test_plain_assignments_mask_exactly_as_before(self):
        cases = {
            "password=%s" % self.TAIL: "password=***",
            'password: "%s"' % self.TAIL: "password: ***",
            "token = '%s' next" % self.TAIL: "token = *** next",
            '{"api_key": "%s"}' % self.TAIL: '{"api_key": ***}',
            "secret: %s, other" % self.TAIL: "secret: ***, other",
            'password="two words %s" end' % self.TAIL: "password=*** end",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.emit_ok(summary=text)
                self.assertEqual(self.scratch.events()[-1]["summary"], expected)

    def test_short_summary_and_ordinary_words_are_kept(self):
        self.emit_ok(summary="Updated the monkey keyboard; what key should be used?")
        self.assertEqual(self.scratch.events()[0]["summary"], "Updated the monkey keyboard; what key should be used?")


# The _ASSIGNED pattern as it was before commit 63ff38a ("quoted value ends at the
# first quote"). Copied verbatim as the baseline the current pattern must never
# leak more than: whatever it masked, the current pattern must also mask.
OLD_ASSIGNED_SOURCE = r"""(?<![A-Za-z0-9_.-])
        ((?:[A-Za-z0-9_.-]*(?:token|secret|password|passwd|api[_-]?key)|(?:[A-Za-z0-9]+[_.-])*key)
         ["']?\s*[:=]\s*)
        ("[^"]*"|'[^']*'|[^\s,;]+)"""
OLD_ASSIGNED = re.compile(OLD_ASSIGNED_SOURCE, re.IGNORECASE | re.VERBOSE)

MARKER = "FAKE_PRIVATE_TAIL_99"


def load_deployed_core():
    """Import the deployed-layout core/agent-alert (no .py suffix) as a module."""
    path = str(common.deployed_copy() / "core" / "agent-alert")
    loader = importlib.machinery.SourceFileLoader("agent_alert_core_under_test", path)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def is_unterminated_quote(text):
    """True when the first quoted assignment in text has no unescaped closing quote."""
    match = re.search(r"[:=]\s*([\"'])", text)
    if not match:
        return False
    quote, index = match.group(1), match.end()
    while index < len(text):
        if text[index] == "\\":
            index += 2
        elif text[index] == quote:
            return False
        else:
            index += 1
    return True


def hostile_corpus():
    """Deterministic hostile assignments; each value contains MARKER."""
    names = ["password", '"password"', "token", "api_key", "key"]
    separators = ["=", ":", " = ", ": "]
    quotes = ["", '"', "'"]
    fragments = [
        MARKER, "a", "\\", "\\\\", '\\"', "\\'", '"', "'",
        "\n", "\r", "\r\n", "\t", "\u2028", "\u2029", "\u0085", " ",
    ]
    prefixes = list(itertools.product(names, separators, quotes))
    short = [seq for n in range(3) for seq in itertools.product(fragments, repeat=n)]
    long_ = [seq for n in (3, 4) for seq in itertools.product(fragments, repeat=n)]
    # Every prefix x every sequence of length 0-2; length 3-4 sampled by a fixed stride.
    sequences = [(p, seq) for p in prefixes for seq in short]
    sequences += [(prefixes[i % len(prefixes)], seq) for i, seq in enumerate(long_) if i % 7 == 0]
    cases = []
    for index, ((name, separator, quote), seq) in enumerate(sequences):
        value = "".join(seq)
        if MARKER not in value:
            value += MARKER
        closing = quote if (quote and index % 2 == 0) else ""
        trailer = " and ordinary words" if index % 3 == 0 else ""
        cases.append(name + separator + quote + value + closing + trailer)
    return cases


class MaskRegressionTests(CoreTestCase):
    """The quoted-assignment mask must never leak a tail the previous mask hid."""

    BACKSLASH_BREAK_VALUES = {
        "backslash-LF": "first\\\n" + MARKER,
        "backslash-CRLF": "first\\\r\n" + MARKER,
        "backslash-CR": "first\\\r" + MARKER,
        "backslash-U+2028": "first\\\u2028" + MARKER,
        "backslash-U+2029": "first\\\u2029" + MARKER,
        "backslash-U+0085": "first\\\u0085" + MARKER,
        "backslash-TAB": "first\\\t" + MARKER,
        "escaped-quote-then-LF": 'first\\"\n' + MARKER,
        "escaped-backslash-then-LF": "first\\\\\n" + MARKER,
        "plain-LF": "first\n" + MARKER,
    }

    def old_masked_marker_but_current_leaks(self, cases):
        core = load_deployed_core()
        compared = 0
        regressions = []
        for text in cases:
            if MARKER in OLD_ASSIGNED.sub(r"\1***", text):
                continue
            compared += 1
            if MARKER in core._ASSIGNED.sub(r"\1***", text):
                regressions.append(text)
        return compared, regressions

    def test_new_pattern_masks_everything_the_old_pattern_masked(self):
        cases = hostile_corpus()
        self.assertGreaterEqual(len(cases), 3000)
        compared, regressions = self.old_masked_marker_but_current_leaks(cases)
        self.assertGreater(compared, 500)
        self.assertEqual(
            len(regressions), 0,
            "%d of %d corpus cases (%d compared): old pattern masked the marker, current "
            "pattern leaks it; first: %r" % (len(regressions), len(cases), compared, regressions[:10]),
        )

    def test_unterminated_quote_ending_in_an_escaped_quote_is_still_masked_like_before(self):
        # `password="two words\\"` has no unescaped closing quote. The old mask ended at
        # the escaped quote and hid everything; the current mask must too.
        cases = [text for text in hostile_corpus() if is_unterminated_quote(text)]
        compared, regressions = self.old_masked_marker_but_current_leaks(cases)
        self.assertGreater(compared, 0)
        self.assertEqual(len(regressions), 0, "%d of %d: %r" % (len(regressions), compared, regressions[:10]))

    def test_backslash_line_breaks_in_quoted_values_never_reach_the_inbox_summary(self):
        for quote in ('"', "'"):
            for label, value in self.BACKSLASH_BREAK_VALUES.items():
                with self.subTest(quote=quote, case=label):
                    scratch = common.Scratch()
                    self.addCleanup(scratch.cleanup)
                    text = "password=" + quote + value + quote + " and ordinary words"
                    result = scratch.emit(summary=text)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    stored = scratch.inbox_bytes().decode("utf-8")
                    self.assertNotIn(MARKER, stored)
                    self.assertNotIn("FAKE_PRIVATE", stored)
                    self.assertEqual(scratch.events()[0]["summary"], "password=*** and ordinary words")

    def test_backslash_line_breaks_in_quoted_values_never_reach_the_inbox_context(self):
        for label, value in self.BACKSLASH_BREAK_VALUES.items():
            with self.subTest(case=label):
                scratch = common.Scratch()
                self.addCleanup(scratch.cleanup)
                payload = '{"password": "' + value + '"} done'
                result = scratch.run(
                    "emit", "--worker", "w", "--kind", "finished", "--summary", "ok",
                    "--context-json", json.dumps({"payload": payload}),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                stored = scratch.inbox_bytes().decode("utf-8")
                self.assertNotIn(MARKER, stored)
                self.assertNotIn("FAKE_PRIVATE", stored)
                self.assertEqual(scratch.events()[0]["context"]["payload"], '{"password": ***} done')

    UNTERMINATED_QUOTE_TEXTS = [
        'password="two words ' + MARKER + '\\"',
        "token='it is " + MARKER + "\\'",
        'password="two words\\"',
    ]

    def test_unterminated_quoted_values_never_reach_the_inbox_summary(self):
        for text in self.UNTERMINATED_QUOTE_TEXTS:
            with self.subTest(text=text):
                scratch = common.Scratch()
                self.addCleanup(scratch.cleanup)
                result = scratch.emit(summary=text)
                self.assertEqual(result.returncode, 0, result.stderr)
                stored = scratch.inbox_bytes().decode("utf-8")
                self.assertNotIn(MARKER, stored)
                self.assertNotIn("FAKE_PRIVATE", stored)
                self.assertEqual(scratch.events()[0]["summary"], text.split("=")[0] + "=***")

    def test_unterminated_quoted_values_never_reach_the_inbox_context(self):
        for text in self.UNTERMINATED_QUOTE_TEXTS:
            with self.subTest(text=text):
                scratch = common.Scratch()
                self.addCleanup(scratch.cleanup)
                result = scratch.run(
                    "emit", "--worker", "w", "--kind", "finished", "--summary", "ok",
                    "--context-json", json.dumps({"payload": text}),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                stored = scratch.inbox_bytes().decode("utf-8")
                self.assertNotIn(MARKER, stored)
                self.assertNotIn("FAKE_PRIVATE", stored)


class ReadAndAckTests(CoreTestCase):
    def seqs(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line)["seq"] for line in result.stdout.splitlines()]

    def test_tail_since_ack_and_lower_ack(self):
        for index in range(5):
            self.emit_ok(worker="w%d" % index, summary="event %d" % (index + 1))
        raw_lines = self.scratch.inbox_bytes().decode("utf-8").splitlines()

        self.assertEqual(self.seqs(self.scratch.run("tail", "--since", "0")), [1, 2, 3, 4, 5])
        self.assertEqual(self.scratch.run("tail", "--since", "0").stdout.splitlines(), raw_lines)
        self.assertEqual(self.seqs(self.scratch.run("tail", "--since", "2")), [3, 4, 5])
        self.assertEqual(self.scratch.run("tail", "--since", "3").stdout.splitlines(), raw_lines[3:])
        self.assertEqual(self.seqs(self.scratch.run("tail", "--since", "5")), [])
        self.assertEqual(self.seqs(self.scratch.run("tail", "--since", "99")), [])
        self.assertEqual(self.seqs(self.scratch.run("tail")), [1, 2, 3, 4, 5], "no ack yet")

        before = self.scratch.inbox_bytes()
        self.assertEqual(self.scratch.run("ack", "3").returncode, 0)
        self.assertEqual(self.scratch.inbox_bytes(), before, "ack must not touch the inbox")
        self.assertEqual(self.seqs(self.scratch.run("tail")), [4, 5])

        self.assertEqual(self.scratch.run("ack", "2").returncode, 0)
        self.assertEqual(self.scratch.inbox_bytes(), before)
        self.assertEqual(self.seqs(self.scratch.run("tail")), [4, 5], "a lower ack must not move the ack back")

        self.assertEqual(self.scratch.run("ack", "5").returncode, 0)
        self.assertEqual(self.seqs(self.scratch.run("tail")), [])
        self.assertEqual(self.seqs(self.scratch.run("tail", "--since", "0")), [1, 2, 3, 4, 5])

        beyond = self.scratch.run("ack", "6")
        self.assertEqual(beyond.returncode, 2)
        self.assertEqual(self.scratch.inbox_bytes(), before)
        self.assertEqual(self.scratch.run("tail", "--since", "-1").returncode, 2)

    def test_tail_without_inbox_exits_zero(self):
        result = self.scratch.run("tail", "--since", "0")
        self.assertEqual((result.returncode, result.stdout), (0, ""))
        self.assertFalse(self.scratch.inbox.exists())

    def test_unknown_kind_line_passes_through_tail_unchanged(self):
        self.emit_ok(summary="first")
        hand_written = '{"version":2,"seq":2,"time":"2030-01-01T00:00:00Z","worker":"w9","kind":"paused","summary":"a later kind","extra":[1,2]}'
        with open(self.scratch.inbox, "ab") as handle:
            handle.write(b"not json at all\n[1,2]\n" + b'{"no":"seq"}\n' + hand_written.encode() + b"\n")
        tailed = self.scratch.run("tail", "--since", "1")
        self.assertEqual(tailed.stdout.splitlines(), [hand_written])
        self.assertEqual(self.scratch.run("ack", "2").returncode, 0)
        # emit continues from the last parseable line
        self.emit_ok(summary="after")
        self.assertEqual(json.loads(self.scratch.inbox_bytes().splitlines()[-1])["seq"], 3)


class SinkTests(CoreTestCase):
    def setUp(self):
        super().setUp()
        self.received = self.scratch.root / "received.jsonl"
        self.ok_sink = self.write_script(
            "sink-ok.sh",
            'cat >> "%s"\necho "log=$AGENT_ALERT_LOG inbox=$AGENT_ALERT_INBOX" >> "%s.env"\n' % (self.received, self.received),
        )
        self.failing_sink = self.write_script("sink-fail.sh", "cat >/dev/null\nexit 3\n")
        self.pid_file = self.scratch.root / "sleeper.pid"
        self.sleeping_sink = self.write_script("sink-sleep.sh", 'echo $$ > "%s"\nexec sleep 30\n' % self.pid_file)
        self.missing_sink = self.scratch.root / "no-such-sink"

    def assert_event_kept(self, kind="finished"):
        events = self.scratch.events()
        self.assertEqual(events[-1]["kind"], kind)

    def test_ok_sink_receives_every_kind_once_and_sees_resolved_paths(self):
        self.scratch.write_config(sinks=[str(self.ok_sink)])
        for kind in ("finished", "blocked", "errored", "exited"):
            self.emit_ok(kind=kind, summary="for the sink")
        received = [json.loads(line) for line in self.received.read_text().splitlines()]
        self.assertEqual([e["kind"] for e in received], ["finished", "blocked", "errored", "exited"])
        self.assertEqual(received, self.scratch.events())
        environment = self.received.with_name("received.jsonl.env").read_text().splitlines()[0]
        self.assertEqual(environment, "log=%s inbox=%s" % (self.scratch.log, self.scratch.inbox))
        self.assertEqual(self.scratch.log_text(), "")

    def test_sink_argument_list_form(self):
        self.scratch.write_config(sinks=[["sh", "-c", 'cat > "$1"', "sh", str(self.received)]])
        self.emit_ok()
        self.assertEqual(json.loads(self.received.read_text())["seq"], 1)

    def run_timed(self, **kwargs):
        started = time.monotonic()
        result = self.scratch.emit(**kwargs)
        return result, time.monotonic() - started

    def test_nonzero_sink_is_logged_and_event_kept(self):
        self.scratch.write_config(sinks=[str(self.failing_sink)])
        result, _ = self.run_timed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_event_kept()
        self.assertIn("exited with status 3", self.scratch.log_text())
        self.assertIn(str(self.failing_sink), self.scratch.log_text())

    def test_missing_sink_is_logged_and_event_kept(self):
        self.scratch.write_config(sinks=[str(self.missing_sink)])
        result, _ = self.run_timed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_event_kept()
        self.assertIn("cannot start", self.scratch.log_text())
        self.assertIn("no-such-sink", self.scratch.log_text())

    def test_sink_sleeping_past_the_bound_is_killed_and_emit_returns_within_bound(self):
        self.scratch.write_config(sinks=[str(self.sleeping_sink)], sink_timeout_seconds=1)
        result, elapsed = self.run_timed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(elapsed, 0.9)
        self.assertLess(elapsed, 4.0)
        self.assert_event_kept()
        self.assertIn("timed out after 1 seconds", self.scratch.log_text())
        pid = int(self.pid_file.read_text())
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("the timed-out sink is still running")

    def test_all_sinks_run_together_under_one_bound(self):
        self.scratch.write_config(
            sinks=[str(self.sleeping_sink), str(self.missing_sink), str(self.failing_sink), str(self.ok_sink)],
            sink_timeout_seconds=1,
        )
        result, elapsed = self.run_timed(summary="all at once")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(elapsed, 4.0)
        self.assertEqual(len(self.scratch.events()), 1)
        self.assertEqual(json.loads(self.received.read_text())["summary"], "all at once")
        log = self.scratch.log_text()
        for cause in ("timed out", "cannot start", "exited with status 3"):
            self.assertIn(cause, log)

    def test_sink_that_ignores_its_stdin_still_lets_emit_finish(self):
        quiet = self.write_script("sink-quiet.sh", "exit 0\n")
        self.scratch.write_config(sinks=[str(quiet)])
        result, _ = self.run_timed()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.scratch.log_text(), "")


if __name__ == "__main__":
    unittest.main()
