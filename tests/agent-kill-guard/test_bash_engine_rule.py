"""The bash-engine rule of bash_rules.py: a hand-typed `loop-engine start|append|event|terminate` on a lead's run (`lead-<slug>-<digits>`) or the coordinator's run
(`coordinator-loop-...`) is refused and names the workflow command; reads, other runs and ids that only look close pass; one command takes the refusal with a logged reason.

Most cases call bash_rules.refusal with a Context (pure). The log lines and exit codes go through the real hook script in a temp copy, with the guard log in a temp file.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_bash_rules as base

bash_rules = base.bash_rules
HOOKS = base.HOOKS

LEAD = "lead-ship-it-3"
LEADS = ["lead-a-1", "lead-ship-it-3", "lead-Foo_bar.baz-12", "lead-a-b-4", "lead-a-1-2"]  # slug made safe as one path component, then the number of the run
COORDINATORS = ["coordinator-loop-1", "coordinator-loop-2026-11-27-ab12"]
WRITES = [  # (verb, the command text for a run id)
    ("start", "loop-engine start lean-change '{}' --id %s"),
    ("start", "loop-engine start --id %s lean-change '{}' label"),
    ("start", "loop-engine start lean-change '{}' --id=%s"),
    ("append", "loop-engine append %s note '{\"a\":1}'"),
    ("event", "loop-engine event %s approve"),
    ("terminate", "loop-engine terminate %s"),
    ("terminate", "loop-engine terminate %s 'stuck for a day'"),
]


def verdict(text, **kw):
    """(rule, message) or None."""
    found = bash_rules.refusal(text, bash_rules.Context(**dict(base.ctx(**kw)._asdict(), platform="linux")))
    return (found[0], str(found[1])) if found else None


def refused(text, **kw):
    found = verdict(text, **kw)
    return found is not None and found[0] == "bash_engine"


class Refused(unittest.TestCase):
    def test_every_write_on_a_lead_run_and_on_the_coordinator_run(self):
        for run in LEADS + COORDINATORS:
            for verb, template in WRITES:
                with self.subTest(run=run, verb=verb, template=template):
                    found = verdict(template % run)
                    self.assertEqual(found[0] if found else None, "bash_engine")
                    self.assertIn("refused in agent sessions", found[1])
                    self.assertIn(run, found[1])

    def test_each_refusal_names_the_workflow_command_for_the_verb(self):
        fixes = {
            ("lead", "start"): "workflows lead enrol", ("lead", "append"): "workflows lead catch-up", ("lead", "event"): "workflows lead catch-up",
            ("lead", "terminate"): "workflows lead cancel RUN --why TEXT", ("coordinator", "start"): "workflows coordinator enrol",
            ("coordinator", "append"): "workflows coordinator release", ("coordinator", "event"): "workflows coordinator release",
            ("coordinator", "terminate"): "workflows coordinator retire",
        }
        runs = {"lead": "lead-a-1", "coordinator": "coordinator-loop-1"}
        for (kind, verb), fix in fixes.items():
            template = next(t for v, t in WRITES if v == verb)
            with self.subTest(kind=kind, verb=verb):
                self.assertIn(fix, verdict(template % runs[kind])[1])

    def test_the_refusal_names_the_way_past_with_a_reason(self):
        message = verdict("loop-engine event lead-a-1 go")[1]
        self.assertIn("BASH_ENGINE_OVERRIDE='<why>' loop-engine event", message)
        self.assertIn("logged", message)

    def test_on_every_profile(self):
        for profile in ("personal", "axon-work-computer", "termux", None):
            with self.subTest(profile=profile):
                self.assertTrue(refused("loop-engine event lead-a-1 go", profile=profile))

    def test_through_wrappers_shells_and_the_package_manager(self):
        inner = "loop-engine event %s go" % LEAD
        for text in [
            "env FOO=1 " + inner, "sudo -u agent " + inner, "timeout 30 " + inner, "nohup " + inner + " &", "time " + inner, "run-and-wake -- " + inner,
            "sh -c '%s'" % inner, "bash -lc \"%s\"" % inner, "env -S '%s'" % inner, "sudo sh -c '%s'" % inner,
            "mise exec -- " + inner, "mise x -- " + inner, "mise exec loop-engine@0.72.0 -- " + inner, "mise x loop-engine@0.72.0 node@24 -- " + inner,
            "mise -C /x exec -- " + inner, "mise exec --yes -j 2 -- " + inner, "mise exec -c '%s'" % inner, "mise x -c \"%s\"" % inner, "mise exec -- sh -c '%s'" % inner,
            "cd /x && " + inner, "true; " + inner, "false || " + inner, "echo go | " + inner, "(" + inner + ")", "x=$(%s)" % inner, "echo `%s`" % inner,
            "/home/agent/.local/share/mise/installs/loop-engine/0.72.0/loop-engine event %s go" % LEAD, "~/bin/loop-engine event %s go" % LEAD,
            "sh <<EOF\n%s\nEOF" % inner, "find . -maxdepth 0 -exec %s \\;" % inner, "xargs -n1 " + inner,
            "FOO=1 " + inner, "LOOP_ENGINE_DATABASE=/scratch/x.db " + inner,
        ]:
            with self.subTest(text=text):
                self.assertTrue(refused(text))

    def test_every_flag_spelling_before_and_after_the_verb(self):
        for text in [
            "loop-engine --json event %s go" % LEAD, "loop-engine -j event %s go" % LEAD, "loop-engine event -j %s go" % LEAD, "loop-engine event %s go --json" % LEAD,
            "loop-engine --database /x/y.db event %s go" % LEAD, "loop-engine --database=/x/y.db event %s go" % LEAD, "loop-engine event --database /x/y.db %s go" % LEAD,
            "loop-engine --config c.toml --timeout-ms 5 event %s go" % LEAD, "loop-engine --timeout-ms=5 -j terminate %s" % LEAD,
            "loop-engine terminate -- %s" % LEAD, "loop-engine event --advice-exception '{}' %s go" % LEAD, "loop-engine append --record-id r1 %s note '{}'" % LEAD,
            "loop-engine append --record-id=r1 %s note '{}'" % LEAD, "loop-engine start --label l --id %s p '{}'" % LEAD, "loop-engine start p '{}' --id=%s --label=l" % LEAD,
            "loop-engine event --run %s go" % LEAD, "loop-engine event --run=%s go" % LEAD, "loop-engine terminate --run-id %s" % LEAD, "loop-engine append --id %s note '{}'" % LEAD,
            "loop-engine --run %s event go" % LEAD, "loop-engine -- terminate %s" % LEAD, "loop-engine -j -- event %s go" % LEAD,
            "loop-engine -d /x/y.db event %s go" % LEAD, "loop-engine --db /x/y.db event %s go" % LEAD, "loop-engine -c c.toml terminate %s" % LEAD,
            "loop-engine --human terminate --run=%s" % LEAD, "loop-engine --machine-readable event --run-id=%s go" % LEAD, "loop-engine event --run=%s --event go --format json" % LEAD,
            "loop-engine terminate --run-id=coordinator-loop-1 --output json", "loop-engine append --run=%s --context-kind note --context-data '{}'" % LEAD,
            "loop-engine start --provider lean-change --initial-input '{}' --id=%s" % LEAD, "loop-engine --provider-config p.toml --provider-timeout-ms 5 event %s go" % LEAD,
            "loop-engine --config-path=c.toml event %s go" % LEAD, "loop-engine --database-path /x.db event %s go" % LEAD,
        ]:
            with self.subTest(text=text):
                self.assertTrue(refused(text))

    def test_the_engines_own_override_is_not_a_way_past(self):
        for text in ["loop-engine event %s go --override '{}'" % LEAD, "loop-engine event %s go --advice-exception '{}'" % LEAD, "loop-engine event %s go --override={}" % LEAD]:
            with self.subTest(text=text):
                self.assertTrue(refused(text))

    def test_the_catalog_does_not_matter_only_the_id(self):
        for text in ["loop-engine --database /scratch/x.db event %s go" % LEAD, "LOOP_ENGINE_DATABASE=/scratch/x.db loop-engine terminate %s" % LEAD]:
            with self.subTest(text=text):
                self.assertTrue(refused(text))

    def test_a_flag_the_table_lacks_cannot_hide_the_id(self):
        """An unknown flag may take the next word, so the id cannot be placed: a lead's or the coordinator's id anywhere in a write command refuses it."""
        for text in ["loop-engine --weird event --run=%s go" % LEAD, "loop-engine --weird terminate --run-id=%s" % LEAD, "loop-engine start --weird --id=%s p '{}'" % LEAD,
                     "loop-engine --weird event %s go" % LEAD, "loop-engine --weird x event %s go" % LEAD, "loop-engine event --weird %s go" % LEAD,
                     "loop-engine event --weird x %s go" % LEAD, "loop-engine terminate --weird=1 %s" % LEAD, "loop-engine start --weird x p '{}' --id %s" % LEAD]:
            with self.subTest(text=text):
                self.assertTrue(refused(text))

    def test_an_id_the_hook_cannot_read_is_refused_and_says_so(self):
        for text in ["loop-engine event $RUN go", "loop-engine event \"$RUN\" go", "loop-engine event ${RUN} go", "loop-engine terminate $(cat run.id)", "loop-engine append `cat id` n '{}'",
                     "loop-engine event lead-* go", "loop-engine event lead-a-$N go", "loop-engine --human event $RUN go", "loop-engine event --format json --run=$RUN go", "loop-engine --weird event --run=$RUN go", "loop-engine start p '{}' --id \"$RUN\"", "RUN=lead-a-1; loop-engine event $RUN go"]:
            with self.subTest(text=text):
                found = verdict(text)
                self.assertEqual(found[0] if found else None, "bash_engine")
                self.assertIn("cannot tell", found[1])
                self.assertIn("Write the run id out", found[1])
        found = bash_rules.refusal("loop-engine event $RUN go", base.ctx())
        self.assertEqual(found[1].log, {"reason": "run id not readable", "run_kind": "unread"})

    def test_through_mise_the_other_rules_see_the_command_too(self):
        self.assertIsNotNone(verdict("mise exec -- git stash"))
        self.assertIsNotNone(verdict("mise exec -c 'git stash'"))
        self.assertIsNone(verdict("mise exec -- git stash list"))


class Allowed(unittest.TestCase):
    def test_the_same_writes_on_other_runs(self):
        """A `change` run carries no marker: the rule does not judge it. Ids that only look close are not a lead's or the coordinator's run."""
        for run in ["change-46", "run-1234", "lean-change-20261127", "6f1c2b9e", "lead-a-b", "lead-a-", "lead-a", "lead-1", "lead--1", "leader-1", "xlead-a-1", "lead-a-1x",
                    "lead-a-1/", "mylead-a-1", "coordinator-loop", "coordinator-loop-", "coordinator-looper-1", "coordinators-loop-1", "a-lead-a-1", "Lead-a-1"]:
            for verb, template in WRITES:
                with self.subTest(run=run, verb=verb):
                    self.assertFalse(refused(template % run), template % run)

    def test_the_trap_of_a_prefix_match(self):
        """`lead-a-` is a prefix of the workstream named `a-b`'s run `lead-a-b-1`, but the id `lead-a-b` with no number is no run of a lead."""
        self.assertFalse(refused("loop-engine terminate lead-a-b"))
        self.assertTrue(refused("loop-engine terminate lead-a-b-1"))

    def test_reads_on_a_lead_run_and_on_the_coordinator_run(self):
        for run in ["lead-a-1", "coordinator-loop-1"]:
            for text in ["loop-engine list", "loop-engine list --label %s" % run, "loop-engine list --lifecycle active --provider lean-change", "loop-engine show %s" % run,
                         "loop-engine show --compact %s" % run, "loop-engine show %s --view full" % run, "loop-engine --json show %s" % run, "loop-engine history %s" % run,
                         "loop-engine -j history %s" % run, "loop-engine read %s --kind history" % run, "loop-engine read --database /x.db --json %s --kind context --limit 5" % run,
                         "loop-engine explore %s" % run, "loop-engine monitor --run %s --database /x.db" % run, "loop-engine reclaim", "loop-engine reclaim --apply",
                         "loop-engine --help", "loop-engine --version", "loop-engine -V", "loop-engine show --help", "loop-engine", "loop-engine bogus %s" % run,
                         "mise exec -- loop-engine show %s" % run, "sh -c 'loop-engine history %s'" % run, "loop-engine show $RUN", "loop-engine history \"$RUN\"",
                         "loop-engine --weird show %s" % run, "loop-engine show --weird %s" % run,
                         "loop-engine -d /x.db show %s" % run, "loop-engine --db /x.db history %s" % run, "loop-engine -c c.toml read %s --kind history" % run,
                         "loop-engine --run %s show" % run, "loop-engine -- show %s" % run]:
                with self.subTest(text=text):
                    self.assertFalse(refused(text))

    def test_a_write_that_names_no_id_has_none_to_judge(self):
        for text in ["loop-engine start lean-change '{}'", "loop-engine start lean-change '{}' label", "loop-engine terminate", "loop-engine event", "loop-engine append",
                     "echo lead-a-1 | xargs loop-engine terminate"]:
            with self.subTest(text=text):
                self.assertFalse(refused(text))

    def test_the_id_as_data_or_as_text_is_not_the_run(self):
        for text in ["loop-engine append change-1 note '{\"run\":\"lead-a-1\"}'", "loop-engine event change-1 go --override '{\"run\":\"lead-a-1\"}'",
                     "loop-engine terminate change-1 lead-a-1", "loop-engine start p '{\"run\":\"lead-a-1\"}' --id change-2", "loop-engine start lead-a-1 '{}'",
                     "echo loop-engine event lead-a-1 go", "grep 'loop-engine terminate lead-a-1' notes.md", "git commit -m \"loop-engine event lead-a-1\"", "cat loop-engine event lead-a-1",
                     "ls lead-a-1", "mise exec -- echo loop-engine terminate lead-a-1", "loop-engine-wrapper event lead-a-1 go", "my-loop-engine event lead-a-1 go"]:
            with self.subTest(text=text):
                self.assertFalse(refused(text))

    def test_the_workflow_commands_themselves(self):
        for text in ["workflows lead catch-up ship-it", "workflows lead cancel lead-ship-it-3 --why 'stuck'", "workflows lead retire ship-it", "workflows coordinator release evt-1 --why x",
                     "workflows lead override bash-engine --why 'x'"]:
            with self.subTest(text=text):
                self.assertFalse(refused(text))


class WayPast(unittest.TestCase):
    """`BASH_ENGINE_OVERRIDE='<why>'` on the command: one command, a reason, a log line."""

    def notes(self, text, **kw):
        seen = []
        ctx = bash_rules.Context(**dict(base.ctx(**kw)._asdict(), platform="linux", note=lambda rule, matched, extra: seen.append((rule, matched, extra))))
        return bash_rules.refusal(text, ctx), seen

    def test_a_reason_on_the_command_takes_the_refusal_and_is_noted_once(self):
        for text in ["BASH_ENGINE_OVERRIDE='the catch-up cannot repair this claim' loop-engine event %s go" % LEAD, "BASH_ENGINE_OVERRIDE=why loop-engine event %s go" % LEAD,
                     "env BASH_ENGINE_OVERRIDE=why loop-engine event %s go" % LEAD, "sh -c \"BASH_ENGINE_OVERRIDE=why loop-engine event %s go\"" % LEAD,
                     "mise exec -- env BASH_ENGINE_OVERRIDE=why loop-engine event %s go" % LEAD, "A=1 BASH_ENGINE_OVERRIDE=why B=2 loop-engine event %s go" % LEAD,
                     "BASH_ENGINE_OVERRIDE=why loop-engine terminate coordinator-loop-1", "BASH_ENGINE_OVERRIDE=why loop-engine start p '{}' --id %s" % LEAD,
                     "BASH_ENGINE_OVERRIDE=why loop-engine event $RUN go"]:
            with self.subTest(text=text):
                found, seen = self.notes(text)
                self.assertIsNone(found)
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0][0], "bash_engine")
                self.assertEqual(seen[0][2]["reason"], "override")

    def test_the_note_carries_the_why_and_the_kind_of_run_not_the_id(self):
        _, seen = self.notes("BASH_ENGINE_OVERRIDE='cannot repair' loop-engine append %s note '{}'" % LEAD)
        self.assertEqual(seen, [("bash_engine", "loop-engine append", {"reason": "override", "why": "cannot repair", "run_kind": "lead"})])
        _, seen = self.notes("BASH_ENGINE_OVERRIDE='x' loop-engine terminate coordinator-loop-1")
        self.assertEqual(seen[0][2]["run_kind"], "coordinator")
        _, seen = self.notes("BASH_ENGINE_OVERRIDE=" + "w" * 500 + " loop-engine event %s go" % LEAD)
        self.assertEqual(len(seen[0][2]["why"]), 300)

    def test_no_reason_is_no_way_past(self):
        for text in ["BASH_ENGINE_OVERRIDE= loop-engine event %s go" % LEAD, "BASH_ENGINE_OVERRIDE='' loop-engine event %s go" % LEAD, "BASH_ENGINE_OVERRIDE='  ' loop-engine event %s go" % LEAD]:
            with self.subTest(text=text):
                found, seen = self.notes(text)
                self.assertIsNotNone(found)
                self.assertEqual(seen, [])

    def test_a_value_that_is_not_on_the_command_is_not_a_way_past(self):
        for text in ["export BASH_ENGINE_OVERRIDE=why; loop-engine event %s go" % LEAD, "BASH_ENGINE_OVERRIDE=why; loop-engine event %s go" % LEAD,
                     "BASH_ENGINE_OVERRIDE=why\nloop-engine event %s go" % LEAD, "echo BASH_ENGINE_OVERRIDE=why loop-engine event %s go; loop-engine event %s go" % (LEAD, LEAD),
                     "loop-engine event %s go BASH_ENGINE_OVERRIDE=why" % LEAD]:
            with self.subTest(text=text):
                found, seen = self.notes(text)
                self.assertIsNotNone(found)
                self.assertEqual(seen, [])
        found, seen = self.notes("loop-engine event %s go" % LEAD, env={"BASH_ENGINE_OVERRIDE": "why"})  # the hook's own environment: an exported value would outlive the command
        self.assertIsNotNone(found)
        self.assertEqual(seen, [])

    def test_one_command_is_one_use(self):
        found, seen = self.notes("BASH_ENGINE_OVERRIDE=why loop-engine event %s go && loop-engine event %s go" % (LEAD, LEAD))
        self.assertEqual(found[0], "bash_engine")
        self.assertEqual(seen, [])  # a refused command is not run, so the way past on its first half is not used and not logged

    def test_an_override_is_not_logged_when_another_rule_refuses_the_command(self):
        found, seen = self.notes("BASH_ENGINE_OVERRIDE=why loop-engine event %s go; git stash" % LEAD)
        self.assertIsNotNone(found)
        self.assertEqual(seen, [])

    def test_the_override_does_not_reach_another_rule(self):
        self.assertIsNotNone(verdict("BASH_ENGINE_OVERRIDE=why loop-engine event lead-a-1 go; git stash"))
        self.assertIsNone(verdict("BASH_ENGINE_OVERRIDE=why loop-engine event lead-a-1 go"))

    def test_nothing_is_noted_when_the_command_needed_no_way_past(self):
        for text in ["BASH_ENGINE_OVERRIDE=why loop-engine event change-1 go", "BASH_ENGINE_OVERRIDE=why loop-engine show lead-a-1"]:
            with self.subTest(text=text):
                found, seen = self.notes(text)
                self.assertIsNone(found)
                self.assertEqual(seen, [])


class RealHook(unittest.TestCase):
    """The real script in a temp copy: the exit code, the message on stderr and the guard log."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.hooks = Path(cls.tmp) / "hooks"
        cls.hooks.mkdir()
        for name in ("refuse_pattern_kill.py", "bash_rules.py"):
            shutil.copy(HOOKS / name, cls.hooks / name)
        cls.log = Path(cls.tmp) / "guard.jsonl"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.log.unlink(missing_ok=True)

    def run_hook(self, command, tool="Bash"):
        env = {k: v for k, v in os.environ.items() if k != "AGENT_HARNESS_PROFILE"}
        env["AGENT_HARNESS_GUARD_LOG"] = str(self.log)
        payload = {"tool_name": tool, "cwd": self.tmp, "tool_input": {"command": command}}
        return subprocess.run([sys.executable, str(self.hooks / "refuse_pattern_kill.py")], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30)

    def lines(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_a_refusal_exits_2_names_the_command_and_writes_one_line_without_the_id(self):
        run = self.run_hook("loop-engine terminate lead-private-name-7 'a reason with a secret'")
        self.assertEqual(run.returncode, 2)
        self.assertIn("refused in agent sessions", run.stderr)
        self.assertIn("workflows lead cancel RUN --why TEXT", run.stderr)
        (line,) = self.lines()
        self.assertEqual((line["action"], line["rule"], line["matched"], line["reason"], line["run_kind"]), ("refuse", "bash_engine", "loop-engine terminate", "write on a lead run", "lead"))
        self.assertNotIn("private-name", json.dumps(line))
        self.assertNotIn("secret", json.dumps(line))

    def test_the_way_past_runs_the_command_and_writes_one_override_line_with_the_why(self):
        run = self.run_hook("BASH_ENGINE_OVERRIDE='catch-up cannot repair this claim' loop-engine event lead-a-1 go")
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        (line,) = self.lines()
        self.assertEqual((line["action"], line["rule"], line["matched"], line["reason"], line["why"], line["run_kind"]),
                         ("override", "bash_engine", "loop-engine event", "override", "catch-up cannot repair this claim", "lead"))
        self.assertNotIn("lead-a-1", json.dumps(line))

    def test_a_read_and_a_change_run_write_nothing_to_the_log(self):
        for command in ["loop-engine show lead-a-1", "loop-engine history coordinator-loop-1", "loop-engine event change-9 go", "loop-engine list"]:
            with self.subTest(command=command):
                self.assertEqual(self.run_hook(command).returncode, 0)
        self.assertEqual(self.lines(), [])

    def test_the_monitor_tool_is_held_to_it_too(self):
        self.assertEqual(self.run_hook("loop-engine event lead-a-1 go", tool="Monitor").returncode, 2)

    def test_an_error_inside_the_rule_lets_the_command_run(self):
        broken = Path(self.tmp) / "broken"
        broken.mkdir()
        shutil.copy(HOOKS / "refuse_pattern_kill.py", broken / "refuse_pattern_kill.py")
        (broken / "bash_rules.py").write_text("raise RuntimeError('broken')\n")
        env = {k: v for k, v in os.environ.items() if k != "AGENT_HARNESS_PROFILE"}
        run = subprocess.run([sys.executable, str(broken / "refuse_pattern_kill.py")], input=json.dumps({"tool_input": {"command": "loop-engine event lead-a-1 go"}}),
                             capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(run.returncode, 0)


if __name__ == "__main__":
    unittest.main()
