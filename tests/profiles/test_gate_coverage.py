"""docs/gate-coverage.md says which agent guard rails run on which profile; this test holds it to that.

For the work profile (axon-work-computer) it checks, with real chezmoi renders and the real scripts in a throwaway HOME (nothing is applied anywhere):
- every path a `yes` row names is managed on that profile, and every test file the table names exists;
- the Bash rules: the real hook script, with the rendered `profile` and `coordinator-instance` files beside it, refuses each sample command
  of a `yes` row and lets the `no` rows' samples and a clean command through;
- the gate wrappers (pr-body-check, pr-record, intent-review-check) find the work coordinator's checkout and state directory, and still find
  ~/git/coordinator on personal;
- the agent-traces wrapper falls back to the coordinator checkout's kit on work only;
- the Claude Code, Codex and Cursor hook installers wire the shared hook on work, and the Pi extension and Cursor guard are managed there.

    python3 -m unittest discover -s tests/profiles -v
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_coverage import PROFILES, managed  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs/gate-coverage.md"
WORK, PERSONAL = "axon-work-computer", "personal"
HOOK_SRC = REPO / "dot_local/share/agent-harness/hooks"
CHEZMOI_DEST = ".local/share/agent-harness"


def table():
    """(gate, personal, work, paths, tests) for each row of the table at the top of docs/gate-coverage.md."""
    rows = []
    for line in DOC.read_text().split("\n## ")[0].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if not line.startswith("|") or len(cells) != 5 or cells[0] in ("Gate", "---"):
            continue
        rows.append((cells[0], cells[1], cells[2], re.findall(r"`([^`]+)`", cells[3]), re.findall(r"`([^`]+)`", cells[4])))
    return rows


def chezmoi(args, data, home, stdin=None):
    cfg = Path(home).parent / ("chezmoi-%s.json" % abs(hash(json.dumps(data, sort_keys=True))))
    cfg.write_text(json.dumps({"data": data}))
    r = subprocess.run(["chezmoi", "--source", str(REPO), "--config", str(cfg), "--config-format", "yaml", "--destination", str(home),
                        "--no-tty", *args], input=stdin, capture_output=True, text=True, timeout=120, env=dict(os.environ, HOME=str(home)))
    assert r.returncode == 0, r.stderr
    return r.stdout


def work_data(**extra):
    return {"profile": WORK, "hub": {"enabled": False}, **extra}


def personal_data(**extra):
    return {"profile": PERSONAL, "hub": {"enabled": False}, **extra}


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()

    def render_file(self, target, data):
        """The rendered contents of a managed file (chezmoi cat), for the given chezmoi data."""
        return chezmoi(["cat", str(self.home / target)], data, self.home)

    def render_template(self, source, data):
        return chezmoi(["execute-template"], data, self.home, stdin=(REPO / source).read_text())


class TableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = table()
        cls.managed = {p: managed(p) for p in PROFILES}

    def test_table_parses_and_every_row_says_yes_or_no(self):
        self.assertGreaterEqual(len(self.rows), 10, "gate rows missing from %s" % DOC)
        for gate, personal, work, _, tests in self.rows:
            for cell in (personal, work):
                self.assertRegex(cell, r"^(yes|no)\b", gate)
            self.assertTrue(tests, "%s: no test named" % gate)

    def test_the_tests_the_table_names_exist(self):
        for gate, *_, tests in self.rows:
            for path in tests:
                self.assertTrue((REPO / path).is_file(), "%s: %s does not exist" % (gate, path))

    def test_yes_rows_land_on_their_profiles(self):
        for gate, personal, work, paths, _ in self.rows:
            if work.startswith("no") and personal.startswith("no"):
                self.fail("%s: no on both profiles is not a guard rail on any profile" % gate)
            for column, profile in ((personal, PERSONAL), (work, WORK)):
                if column.startswith("yes"):
                    self.assertTrue(paths, "%s: a yes row names the paths that land" % gate)
                    for path in paths:
                        self.assertIn(path, self.managed[profile], "%s: %s is not managed on %s" % (gate, path, profile))

    def test_every_work_gate_wrapper_that_personal_has_is_on_work(self):
        wrappers = {".local/bin/pr-body-check", ".local/bin/pr-record", ".local/bin/pr-open", ".local/bin/intent-review-check",
                    ".local/bin/ci-main-status", ".local/bin/agent-traces"}
        self.assertEqual(wrappers - self.managed[WORK], set())
        self.assertEqual(wrappers - self.managed[PERSONAL], set())


# Sample commands per Bash rule row: (command, cwd-relative-to-home or None). The substring picks the row by its gate text.
SAMPLES = {
    "`gh pr merge` only after both gates": "gh pr merge 12 -R acme/app",
    "PR body only from a checked body file": "gh pr create --title t --body 'x'",
    "poll loops": "until test -f /tmp/x; do sleep 2; done",
    "unquoted heredoc": "cat <<EOF\n`date`\nEOF",
    "credential config": "cat ~/.netrc",
    "live coordinator checkout": "git -C ~/coordinator-work merge origin/main",
    "heavy jobs": "npm test",
    "kubectl on a context": "kubectl --context axon-aks-prod get pods",
    "local `docker run`": "docker run alpine",
}
CLEAN = ["git status", "ls -la", "gh pr list", "ci-main-status --merge-gate acme/app && pr-body-check acme/app 12 && gh pr merge 12 -R acme/app"]


class WorkHookTest(Base):
    """The real hook, as the work profile renders it: `profile` and `coordinator-instance` from chezmoi, the scripts from the source."""

    def setUp(self):
        super().setUp()
        self.hooks = self.home / ".local/share/agent-harness/hooks"
        self.hooks.mkdir(parents=True)
        for name in ("refuse_pattern_kill.py", "bash_rules.py"):
            shutil.copy(HOOK_SRC / name, self.hooks / name)
        (self.hooks / "profile").write_text(self.render_file(".local/share/agent-harness/hooks/profile", work_data()))
        (self.hooks.parent / "coordinator-instance").write_text(self.render_file(".local/share/agent-harness/coordinator-instance", work_data()))

    def hook(self, command, tool="Bash"):
        env = {k: v for k, v in os.environ.items() if k not in ("AGENT_HARNESS_PROFILE", "AGENT_HARNESS_CONTAINER", "KUBECONFIG")}
        env.update(HOME=str(self.home), AGENT_HARNESS_GUARD_LOG=os.devnull)
        payload = {"tool_name": tool, "cwd": str(self.home), "tool_input": {"command": command}}
        return subprocess.run([sys.executable, str(self.hooks / "refuse_pattern_kill.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=30)

    def test_the_rendered_files_name_the_work_profile_and_checkout(self):
        self.assertEqual((self.hooks / "profile").read_text().strip(), WORK)
        lines = (self.hooks.parent / "coordinator-instance").read_text().splitlines()
        self.assertEqual(lines, [str(self.home / "coordinator-work"), str(self.home / ".local/share/coordinator-work")])

    def test_each_bash_rule_row_fires_or_not_on_work_as_the_table_says(self):
        bash_rows = [row for row in table() if row[0].startswith("Bash rule:")]
        self.assertGreaterEqual(len(bash_rows), 9)
        for gate, _, work, _, _ in bash_rows:
            samples = [cmd for key, cmd in SAMPLES.items() if key in gate]
            self.assertEqual(len(samples), 1, "%s: add one sample command in SAMPLES" % gate)
            r = self.hook(samples[0].replace("~/", str(self.home) + "/"))
            with self.subTest(gate=gate):
                self.assertEqual(r.returncode, 2 if work.startswith("yes") else 0, r.stderr)

    def test_clean_commands_pass(self):
        for command in CLEAN:
            with self.subTest(command=command):
                self.assertEqual(self.hook(command).returncode, 0, self.hook(command).stderr)

    def test_the_work_checkout_from_local_data_is_protected_too(self):
        (self.hooks.parent / "coordinator-instance").write_text(
            self.render_file(".local/share/agent-harness/coordinator-instance", work_data(instances={"coordinator": {"repo": "/srv/work/coordinator"}})))
        self.assertEqual(self.hook("git -C /srv/work/coordinator commit -m x").returncode, 2)
        self.assertEqual(self.hook("git -C /srv/work/coordinator log -1").returncode, 0)


class WrapperTest(Base):
    """pr-body-check, pr-record and intent-review-check run scripts in the coordinator checkout. A fake `node` records which script and which
    state directory the wrapper chose."""
    WRAPPERS = {"pr-body-check": "pr-body-check.ts", "pr-record": "pr-record.ts", "intent-review-check": "intent-review-check.ts"}

    def setUp(self):
        super().setUp()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        node = self.bin / "node"
        node.write_text('#!/bin/sh\nfor a in "$@"; do case "$a" in *.ts) echo "script=$a";; esac; done\necho "state=${COORDINATOR_STATE_DIR:-unset}"\n')
        node.chmod(node.stat().st_mode | stat.S_IXUSR)
        self.log = self.root / "node.log"

    def install(self, data, repo, state=None, with_instance_file=True):
        """A home for `data`'s profile: the instance file chezmoi renders, a fake checkout with the three scripts, and optionally the state dir's pane-bin/ledger."""
        if with_instance_file:
            target = self.home / ".local/share/agent-harness/coordinator-instance"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(self.render_file(".local/share/agent-harness/coordinator-instance", data))
        for script in self.WRAPPERS.values():
            (Path(repo) / "scripts").mkdir(parents=True, exist_ok=True)
            (Path(repo) / "scripts" / script).write_text("// stub\n")
        if state:
            (Path(state) / "pane-bin").mkdir(parents=True, exist_ok=True)
            (Path(state) / "pane-bin/ledger").write_text("#!/bin/sh\n")

    def run_wrapper(self, name, **env):
        pairs = {"HOME": str(self.home), "PATH": "%s:/usr/bin:/bin" % self.bin}
        pairs.update(env)
        return subprocess.run(["/usr/bin/env", "-i", *["%s=%s" % kv for kv in pairs.items()], "/bin/sh", str(REPO / "dot_local/bin" / ("executable_" + name)), "x/y", "1"],
                              capture_output=True, text=True, timeout=60)

    def test_work_wrappers_use_the_work_checkout_and_state_dir(self):
        repo, state = self.home / "coordinator-work", self.home / ".local/share/coordinator-work"
        self.install(work_data(), repo, state)
        for name, script in self.WRAPPERS.items():
            with self.subTest(wrapper=name):
                r = self.run_wrapper(name)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.split(), ["script=%s/scripts/%s" % (repo, script), "state=%s" % state])

    def test_work_wrappers_use_the_checkout_from_local_data(self):
        repo = self.root / "elsewhere/coordinator"
        self.install(work_data(instances={"coordinator": {"repo": str(repo)}}), repo)
        r = self.run_wrapper("pr-body-check")
        self.assertIn("script=%s/scripts/pr-body-check.ts" % repo, r.stdout)

    def test_a_state_dir_without_a_ledger_is_not_exported_and_a_set_one_wins(self):
        repo, state = self.home / "coordinator-work", self.home / ".local/share/coordinator-work"
        self.install(work_data(), repo)  # no pane-bin/ledger under the state dir
        self.assertIn("state=unset", self.run_wrapper("pr-body-check").stdout)
        self.install(work_data(), repo, state)
        self.assertIn("state=/mine", self.run_wrapper("pr-body-check", COORDINATOR_STATE_DIR="/mine").stdout)

    def test_personal_wrappers_still_use_git_coordinator_and_leave_the_state_dir_alone(self):
        repo = self.home / "git/coordinator"
        self.install(personal_data(), repo, self.home / ".local/share/coordinator-work")
        for name, script in self.WRAPPERS.items():
            with self.subTest(wrapper=name):
                r = self.run_wrapper(name)
                self.assertEqual(r.stdout.split(), ["script=%s/scripts/%s" % (repo, script), "state=unset"])

    def test_without_the_instance_file_the_default_is_git_coordinator(self):
        repo = self.home / "git/coordinator"
        self.install(personal_data(), repo, with_instance_file=False)
        self.assertIn("script=%s/scripts/pr-record.ts" % repo, self.run_wrapper("pr-record").stdout)

    def test_coordinator_repo_overrides_the_file(self):
        repo, other = self.home / "coordinator-work", self.root / "other"
        self.install(work_data(), repo)
        self.install(work_data(), other, with_instance_file=False)
        self.assertIn("script=%s/scripts/intent-review-check.ts" % other, self.run_wrapper("intent-review-check", COORDINATOR_REPO=str(other)).stdout)

    def test_a_missing_checkout_exits_2_and_names_it(self):
        self.install(work_data(), self.root / "unused")
        r = self.run_wrapper("pr-body-check")
        self.assertEqual(r.returncode, 2)
        self.assertIn(str(self.home / "coordinator-work"), r.stderr)


class AgentTracesTest(Base):
    """The agent-traces wrapper on work uses the coordinator checkout's kit when the pinned install is missing; personal does not."""

    def setUp(self):
        super().setUp()
        self.node = self.root / "node"
        self.node.write_text('#!/bin/sh\nif [ "$1" = "-p" ]; then echo 22.19.0; exit 0; fi\necho "ran:$*"\n')
        self.node.chmod(self.node.stat().st_mode | stat.S_IXUSR)
        self.repo = self.home / "coordinator-work"
        instance = self.home / ".local/share/agent-harness/coordinator-instance"
        instance.parent.mkdir(parents=True)
        instance.write_text("%s\n" % self.repo)

    def wrapper(self, data):
        path = self.root / ("agent-traces-" + data["profile"])
        path.write_text(self.render_template("dot_local/bin/executable_agent-traces.tmpl", data))
        return path

    def run_it(self, data, **env):
        pairs = {"HOME": str(self.home), "AGENT_TRACES_NODE": str(self.node), "PATH": "/usr/bin:/bin"}
        pairs.update(env)
        return subprocess.run(["/usr/bin/env", "-i", *["%s=%s" % kv for kv in pairs.items()], "/bin/sh", str(self.wrapper(data)), "review", "report"],
                              capture_output=True, text=True, timeout=60)

    def put_kit_in_checkout(self, version="0.69.2"):
        kit = self.repo / "node_modules/@cartwmic/agent-kit"
        cli = kit / "dist/traces/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// fake\n")
        if version:
            (kit / "package.json").write_text('{\n  "name": "@cartwmic/agent-kit",\n  "version": "%s",\n  "type": "module"\n}\n' % version)
        return cli

    def test_work_uses_the_checkouts_kit_when_there_is_no_pinned_install(self):
        cli = self.put_kit_in_checkout()
        r = self.run_it(work_data())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(str(cli), r.stdout)

    def test_the_fallback_prints_one_stderr_line_naming_the_kit_path_and_version(self):
        cli = self.put_kit_in_checkout("0.69.2")
        r = self.run_it(work_data())
        lines = [l for l in r.stderr.splitlines() if l.startswith("agent-traces:")]
        self.assertEqual(len(lines), 1, r.stderr)
        self.assertIn(str(cli), lines[0])
        self.assertIn("version 0.69.2", lines[0])
        self.assertNotIn("version", r.stdout, "the line goes to stderr, not stdout")

    def test_the_fallback_line_says_unknown_when_the_kit_has_no_version(self):
        self.put_kit_in_checkout(version=None)
        self.assertIn("version unknown", self.run_it(work_data()).stderr)

    def test_the_fallback_line_uses_the_coordinator_repo_override(self):
        other = self.root / "elsewhere"
        kit = other / "node_modules/@cartwmic/agent-kit"
        (kit / "dist/traces").mkdir(parents=True)
        (kit / "dist/traces/cli.js").write_text("// fake\n")
        (kit / "package.json").write_text('{"version": "9.9.9"}\n')
        r = self.run_it(work_data(), COORDINATOR_REPO=str(other))
        self.assertIn(str(kit / "dist/traces/cli.js"), r.stderr)
        self.assertIn("version 9.9.9", r.stderr)

    def test_no_line_is_printed_when_the_pinned_install_is_used_or_on_personal(self):
        self.put_kit_in_checkout()
        pinned = self.home / ".local/share/agent-kit/node_modules/@cartwmic/agent-kit/dist/traces/cli.js"
        pinned.parent.mkdir(parents=True)
        pinned.write_text("// pinned\n")
        self.assertEqual(self.run_it(work_data()).stderr, "")
        self.assertEqual(self.run_it(personal_data()).stderr, "")

    def test_work_exits_3_when_the_checkout_has_no_kit_either(self):
        r = self.run_it(work_data())
        self.assertEqual(r.returncode, 3)
        self.assertIn("by hand", r.stderr)

    def test_the_exit_3_line_says_what_was_looked_for_and_where(self):
        pinned = self.home / ".local/share/agent-kit/node_modules/@cartwmic/agent-kit/dist/traces/cli.js"
        alt = self.repo / "node_modules/@cartwmic/agent-kit/dist/traces/cli.js"
        r = self.run_it(work_data())
        self.assertEqual(r.returncode, 3)
        self.assertIn("looked for %s and %s" % (pinned, alt), r.stderr)

    def test_the_exit_3_line_on_personal_names_the_pinned_path_only(self):
        pinned = self.home / ".local/share/agent-kit/node_modules/@cartwmic/agent-kit/dist/traces/cli.js"
        r = self.run_it(personal_data(agentKit={"enabled": False}))
        self.assertEqual(r.returncode, 3)
        self.assertIn("looked for %s)" % pinned, r.stderr)
        self.assertNotIn("coordinator-work", r.stderr)

    def test_the_enabled_but_missing_message_also_names_the_path(self):
        pinned = self.home / ".local/share/agent-kit/node_modules/@cartwmic/agent-kit/dist/traces/cli.js"
        r = self.run_it(personal_data(agentKit={"enabled": True}))
        self.assertEqual(r.returncode, 3)
        self.assertIn("looked for %s" % pinned, r.stderr)

    def test_personal_does_not_fall_back(self):
        self.put_kit_in_checkout()
        self.assertEqual(self.run_it(personal_data()).returncode, 3)

    def test_the_pinned_install_wins_on_work(self):
        self.put_kit_in_checkout()
        pinned = self.home / ".local/share/agent-kit/node_modules/@cartwmic/agent-kit/dist/traces/cli.js"
        pinned.parent.mkdir(parents=True)
        pinned.write_text("// pinned\n")
        self.assertIn(str(pinned), self.run_it(work_data()).stdout)


class AgentTracesLogTest(Base):
    """Principle 14: the work wrapper leaves a durable record of each run's kit, not just a stderr line. One JSON line per run goes to
    $XDG_STATE_HOME/agent-traces/wrapper.jsonl (default ~/.local/state/agent-traces/wrapper.jsonl): utc, outcome (pinned, fallback or none), kit, version, looked."""

    def setUp(self):
        super().setUp()
        self.node = self.root / "node"
        self.node.write_text('#!/bin/sh\nif [ "$1" = "-p" ]; then echo 22.19.0; exit 0; fi\necho "ran:$*"\n')
        self.node.chmod(self.node.stat().st_mode | stat.S_IXUSR)
        self.repo = self.home / "coordinator-work"
        instance = self.home / ".local/share/agent-harness/coordinator-instance"
        instance.parent.mkdir(parents=True)
        instance.write_text("%s\n" % self.repo)
        self.log = self.home / ".local/state/agent-traces/wrapper.jsonl"
        self.pinned = self.home / ".local/share/agent-kit/node_modules/@cartwmic/agent-kit/dist/traces/cli.js"
        self.alt = self.repo / "node_modules/@cartwmic/agent-kit/dist/traces/cli.js"

    def put_kit(self, cli, version):
        cli.parent.mkdir(parents=True)
        cli.write_text("// fake\n")
        (cli.parent.parent.parent / "package.json").write_text('{\n  "name": "@cartwmic/agent-kit",\n  "version": "%s"\n}\n' % version)

    def run_it(self, data, **env):
        pairs = {"HOME": str(self.home), "AGENT_TRACES_NODE": str(self.node), "PATH": "/usr/bin:/bin"}
        pairs.update(env)
        path = self.root / ("agent-traces-" + data["profile"])
        path.write_text(self.render_template("dot_local/bin/executable_agent-traces.tmpl", data))
        return subprocess.run(["/usr/bin/env", "-i", *["%s=%s" % kv for kv in pairs.items()], "/bin/sh", str(path), "review", "report"],
                              capture_output=True, text=True, timeout=60)

    def lines(self, log=None):
        return [json.loads(l) for l in (log or self.log).read_text().splitlines()]

    def test_a_fallback_run_logs_the_kit_path_and_version(self):
        self.put_kit(self.alt, "0.69.2")
        r = self.run_it(work_data())
        self.assertEqual(r.returncode, 0, r.stderr)
        (line,) = self.lines()
        self.assertEqual((line["outcome"], line["kit"], line["version"]), ("fallback", str(self.alt), "0.69.2"))
        self.assertRegex(line["utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(line["looked"], "%s and %s" % (self.pinned, self.alt))
        self.assertIn("version 0.69.2", r.stderr)  # the stderr line stays

    def test_a_pinned_run_logs_pinned_with_its_version(self):
        self.put_kit(self.alt, "0.69.2")
        self.put_kit(self.pinned, "0.70.0")
        self.assertEqual(self.run_it(work_data()).returncode, 0)
        (line,) = self.lines()
        self.assertEqual((line["outcome"], line["kit"], line["version"], line["looked"]), ("pinned", str(self.pinned), "0.70.0", str(self.pinned)))

    def test_the_exit_3_run_logs_none_and_where_it_looked(self):
        r = self.run_it(work_data())
        self.assertEqual(r.returncode, 3)
        (line,) = self.lines()
        self.assertEqual((line["outcome"], line["kit"], line["version"]), ("none", "", ""))
        self.assertEqual(line["looked"], "%s and %s" % (self.pinned, self.alt))

    def test_each_run_appends_one_line(self):
        self.put_kit(self.alt, "0.69.2")
        for _ in range(3):
            self.run_it(work_data())
        self.assertEqual(len(self.lines()), 3)

    def test_xdg_state_home_moves_the_log(self):
        self.put_kit(self.alt, "0.69.2")
        state = self.root / "xdg"
        self.run_it(work_data(), XDG_STATE_HOME=str(state))
        self.assertFalse(self.log.exists())
        self.assertEqual(self.lines(state / "agent-traces/wrapper.jsonl")[0]["outcome"], "fallback")

    def test_a_log_that_cannot_be_written_changes_nothing(self):
        self.put_kit(self.alt, "0.69.2")
        blocked = self.root / "blocked"
        blocked.write_text("a file where the state directory should be\n")
        ok = self.run_it(work_data(), XDG_STATE_HOME=str(blocked))
        self.assertEqual(ok.returncode, 0)
        self.assertIn("ran:", ok.stdout)
        self.assertEqual([l for l in ok.stderr.splitlines() if not l.startswith("agent-traces: no pinned install")], [])
        shutil.rmtree(self.alt.parent.parent.parent.parent.parent.parent)
        none = self.run_it(work_data(), XDG_STATE_HOME=str(blocked))
        self.assertEqual(none.returncode, 3)

    def test_a_path_with_quotes_stays_valid_json(self):
        odd = self.root / 'odd "repo"'
        alt = odd / "node_modules/@cartwmic/agent-kit/dist/traces/cli.js"
        self.put_kit(alt, "1.2.3")
        self.run_it(work_data(), COORDINATOR_REPO=str(odd))
        self.assertEqual(self.lines()[0]["kit"], str(alt))

    def test_personal_writes_no_wrapper_log(self):
        self.put_kit(self.pinned, "0.70.0")
        self.assertEqual(self.run_it(personal_data()).returncode, 0)
        self.assertFalse(self.log.exists())


class TermuxTest(unittest.TestCase):
    """Termux has neither desktop profile's guard rails: no gate wrapper, no hook, no coordinator-instance file is rendered there.
    (Two layers keep them out: the "not personal or work" block in .chezmoiignore, and the Termux allow-list that already ignores all of
    .local/bin and .local/share but passage-review; the test fails when both let a gate through.)"""

    def test_termux_renders_none_of_the_gates(self):
        on_termux = managed("termux")
        self.assertTrue(on_termux, "chezmoi managed returned nothing for termux")
        paths = {path for _, _, _, paths, _ in table() for path in paths}
        self.assertTrue(paths)
        landed = sorted(p for p in on_termux if any(p == path or p.startswith(path + "/") for path in paths))
        self.assertEqual(landed, [], "gate paths that land on termux")


class HarnessWiringTest(Base):
    """All four harnesses run the one hook script; each installer wires it on work."""

    def test_claude_codex_and_cursor_installers_wire_the_hook_on_work(self):
        for source, marker in (("dot_claude/modify_settings.json.tmpl", "refuse_pattern_kill.py"),
                               ("dot_codex/modify_hooks.json.tmpl", "refuse_pattern_kill.py"),
                               ("dot_cursor/modify_hooks.json.tmpl", "shell_guard.py")):
            with self.subTest(installer=source):
                self.assertIn(marker, self.render_template(source, work_data()))

    def test_pi_extension_cursor_guard_and_hook_scripts_are_managed_on_work(self):
        on_work = managed(WORK)
        for path in (".pi/agent/extensions/refuse-pattern-kill/index.ts", ".cursor/hooks/shell_guard.py",
                     ".local/share/agent-harness/hooks/refuse_pattern_kill.py", ".local/share/agent-harness/hooks/bash_rules.py",
                     ".local/share/agent-harness/hooks/profile", ".local/share/agent-harness/coordinator-instance"):
            self.assertIn(path, on_work)


if __name__ == "__main__":
    unittest.main()
