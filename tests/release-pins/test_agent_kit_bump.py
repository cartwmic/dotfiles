"""Black-box tests for dot_local/user_scripts/executable_agent_kit_bump.py (playbook rule 7c57de5a in one command).

Each test runs the real script against a scratch world: a bare git origin holding a small chezmoi source with the agent-kit
pin, the 65 install template and an unrelated file; a clone of it as the source checkout; and a scratch HOME (chezmoi's
destination, config and state) applied from that source. chezmoi and git are real. The gh, npm, ci-main-status and
pr-body-check on PATH are scripted fakes; every call goes to one log file, so the order of checks, gates and merge can be
read back. Nothing here reaches GitHub, the real chezmoi source or the real home directory.

    python3 -m unittest discover -s tests/release-pins -v
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/user_scripts/executable_agent_kit_bump.py"
INSTALL_TEMPLATE = "run_onchange_after_65_agent_kit_install.sh.tmpl"
KIT_SRC = "dot_local/share/agent-kit"
KIT_DEST = ".local/share/agent-kit"
PACKAGE = "@cartwmic/agent-kit"
OLD, NEW = "0.50.0", "0.52.0"  # the seeded pin, and the release the tests bump to

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALL_LOG"], "a") as log:
    log.write("gh " + " ".join(args) + "\n")
state_path = os.environ["FAKE_GH_STATE"]
state = json.load(open(state_path)) if os.path.exists(state_path) else {"prs": [], "checks": [[{"name": "tests", "bucket": "pass"}]]}
origin = os.environ["FAKE_ORIGIN"]

def save():
    json.dump(state, open(state_path, "w"))

def git(*a):
    return subprocess.run(["git", "--git-dir", origin, *a], check=True, capture_output=True, text=True).stdout.strip()

def out(value):
    save()
    print(json.dumps(value))
    sys.exit(0)

def fail(message):
    save()
    print(message, file=sys.stderr)
    sys.exit(1)

if args == ["auth", "token"]:
    print("fake-token")
    sys.exit(0)
if args[:1] != ["pr"]:
    fail("fake gh: unexpected " + " ".join(args))
verb = args[1]
if verb == "list":
    head = args[args.index("--head") + 1]
    out([{k: p[k] for k in ("number", "state", "url", "mergeCommit")} for p in state["prs"] if p["head"] == head])
if verb == "create":
    head = args[args.index("--head") + 1]
    title = args[args.index("--title") + 1]
    body = open(args[args.index("--body-file") + 1], encoding="utf-8").read()
    number = 100 + len(state["prs"])
    state["prs"].append({"number": number, "state": "OPEN", "url": "https://example.test/pull/%d" % number, "head": head,
                         "title": title, "body": body, "mergeCommit": None})
    save()
    print("https://example.test/pull/%d" % number)
    sys.exit(0)
pr = [p for p in state["prs"] if p["number"] == int(args[2])][0]
if verb == "checks":
    rounds = state["checks"]
    out(rounds.pop(0) if len(rounds) > 1 else rounds[0])
if verb == "view":
    out({"number": pr["number"], "state": pr["state"], "url": pr["url"], "mergeCommit": pr["mergeCommit"],
         "headRefOid": git("rev-parse", "refs/heads/" + pr["head"])})
if verb == "merge":
    head = git("rev-parse", "refs/heads/" + pr["head"])
    if "--match-head-commit" not in args or args[args.index("--match-head-commit") + 1] != head:
        fail("fake gh: refused, the PR head is no longer %s" % head)
    tree = git("rev-parse", "refs/heads/%s^{tree}" % pr["head"])
    sha = git("commit-tree", tree, "-p", "refs/heads/main", "-m", "%s (#%d)" % (pr["title"], pr["number"]))
    git("update-ref", "refs/heads/main", sha)
    pr.update(state="MERGED", mergeCommit={"oid": sha})
    out({})
fail("fake gh: unexpected pr " + verb)
'''

FAKE_GATE = r'''#!/bin/sh
# A scripted merge gate: logs its call, and refuses when FAKE_GATE_REFUSE names it.
echo "$(basename "$0") $*" >> "$FAKE_CALL_LOG"
if [ "${FAKE_GATE_REFUSE:-}" = "$(basename "$0")" ]; then
  echo "$(basename "$0"): refused by the test" >&2
  exit 1
fi
exit 0
'''

FAKE_NPM = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALL_LOG"], "a") as log:
    log.write("npm " + " ".join(args) + "\n")
version = json.load(open("package.json"))["dependencies"]["@cartwmic/agent-kit"]
if args[:2] == ["install", "--package-lock-only"]:
    json.dump({"lockfileVersion": 3, "packages": {"node_modules/@cartwmic/agent-kit": {"version": version}}}, open("package-lock.json", "w"), indent=2)
elif args[:1] == ["ci"]:
    installed = os.environ.get("FAKE_NPM_INSTALLS") or version
    os.makedirs("node_modules/@cartwmic/agent-kit", exist_ok=True)
    json.dump({"name": "@cartwmic/agent-kit", "version": installed}, open("node_modules/@cartwmic/agent-kit/package.json", "w"))
else:
    sys.exit(1)
'''


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("git"), "needs chezmoi and git")
class AgentKitBumpTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="agent-kit-bump-test-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for name, text in (("gh", FAKE_GH), ("npm", FAKE_NPM), ("ci-main-status", FAKE_GATE), ("pr-body-check", FAKE_GATE)):
            (self.bin / name).write_text(text, encoding="utf-8")
            (self.bin / name).chmod(0o755)
        self.home = self.dir / "home"
        self.origin = self.dir / "origin.git"
        self.checkout = self.dir / "checkout"
        self.call_log = self.dir / "calls.log"
        self.gh_state = self.dir / "gh.json"
        self.refuse = ""
        self.npm_installs = ""
        self.git_env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example.test", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        self.seed = {
            KIT_SRC + "/package.json": json.dumps({"name": "agent-kit-install", "version": "0.0.0", "private": True,
                                                    "dependencies": {PACKAGE: OLD}}, indent=2) + "\n",
            KIT_SRC + "/package-lock.json": '{"lockfileVersion": 3}\n',
            KIT_SRC + "/dot_npmrc": "@cartwmic:registry=https://npm.pkg.github.com\n",
            "dot_unrelated": "unrelated v1\n",
        }

    def env(self):
        return {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / ".config"), "XDG_CACHE_HOME": str(self.home / ".cache"),
                "XDG_STATE_HOME": str(self.home / ".local/state"), "FAKE_CALL_LOG": str(self.call_log),
                "FAKE_GH_STATE": str(self.gh_state), "FAKE_ORIGIN": str(self.origin), "FAKE_GATE_REFUSE": self.refuse,
                "FAKE_NPM_INSTALLS": self.npm_installs, "NODE_AUTH_TOKEN": "fake-token",
                "AGENT_KIT_BUMP_POLL_SECONDS": "0", "TMPDIR": str(self.dir), **self.git_env}

    def sh(self, *cmd, cwd=None):
        result = subprocess.run([str(c) for c in cmd], cwd=cwd, env=self.env(), capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, "%s: %s%s" % (cmd, result.stdout, result.stderr))
        return result.stdout

    def world(self, profile="personal"):
        """Origin with the seed plus one later unrelated commit on main; HOME applied from the seed without scripts."""
        self.sh("git", "init", "-q", "--bare", "-b", "main", self.origin)
        self.sh("git", "clone", "-q", self.origin, self.checkout)
        files = {**self.seed, INSTALL_TEMPLATE: (ROOT / INSTALL_TEMPLATE).read_text(encoding="utf-8")}
        for path, text in files.items():
            (self.checkout / path).parent.mkdir(parents=True, exist_ok=True)
            (self.checkout / path).write_text(text, encoding="utf-8")
        self.sh("git", "-C", self.checkout, "add", "-A")
        self.sh("git", "-C", self.checkout, "commit", "-q", "-m", "seed")
        self.sh("git", "-C", self.checkout, "push", "-q", "origin", "main")
        config = self.home / ".config/chezmoi/chezmoi.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("data:\n  profile: %s\n" % profile, encoding="utf-8")
        self.sh("chezmoi", "--source", self.checkout, "--no-tty", "apply", "-x", "scripts")
        # Someone else's later change on main, not applied here: the bump must not apply it.
        other = self.dir / "other"
        self.sh("git", "clone", "-q", self.origin, other)
        (other / "dot_unrelated").write_text("unrelated v2\n", encoding="utf-8")
        self.sh("git", "-C", other, "commit", "-q", "-am", "unrelated")
        self.sh("git", "-C", other, "push", "-q", "origin", "main")

    def bump(self, version=NEW):
        return subprocess.run([sys.executable, str(SCRIPT), version, "--source", str(self.checkout)], env=self.env(),
                              capture_output=True, text=True, timeout=300)

    def live(self, path):
        target = self.home / path
        return target.read_text(encoding="utf-8") if target.is_file() else None

    def calls(self):
        return self.call_log.read_text(encoding="utf-8").splitlines() if self.call_log.exists() else []

    def prs(self):
        return json.loads(self.gh_state.read_text(encoding="utf-8"))["prs"] if self.gh_state.exists() else []

    def log_lines(self):
        path = self.home / ".local/state/agent-kit-bump/log.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def assert_nothing_applied(self):
        self.assertEqual(self.live(KIT_DEST + "/package.json"), self.seed[KIT_SRC + "/package.json"])
        self.assertFalse((self.home / KIT_DEST / "node_modules").exists())

    def assert_stopped(self, result, step, text):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("stopped at step %s:" % step, result.stderr)
        self.assertIn(text, result.stderr)
        self.assertEqual(self.log_lines()[-1]["step"], step)
        self.assertEqual(self.log_lines()[-1]["outcome"], "stopped")

    def test_happy_path_checks_then_gates_then_merge_then_only_the_pins_applied_and_installed(self):
        self.world()
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("installed: %s %s" % (PACKAGE, NEW), result.stdout)

        prs = self.prs()
        self.assertEqual(len(prs), 1)
        self.assertIn("| 15 | Fast proof |", prs[0]["body"])
        self.assertRegex(prs[0]["body"], r"(?m)^Decisions: none material$")

        # Checks, then the two gates in order, then the squash merge, which must name the head the checks ran on.
        calls = self.calls()
        index = {name: next(i for i, c in enumerate(calls) if c.startswith(name))
                 for name in ("gh pr checks", "ci-main-status", "pr-body-check", "gh pr merge")}
        self.assertLess(index["gh pr checks"], index["ci-main-status"])
        self.assertLess(index["ci-main-status"], index["pr-body-check"])
        self.assertLess(index["pr-body-check"], index["gh pr merge"])
        self.assertEqual(calls[index["pr-body-check"]], "pr-body-check dotfiles 100")
        head = self.sh("git", "--git-dir", self.origin, "rev-parse", "refs/heads/agent-kit-v" + NEW).strip()
        self.assertIn("--match-head-commit " + head, calls[index["gh pr merge"]])

        # Only the two pin files changed on this machine; main's later unrelated change was not applied.
        sha = prs[0]["mergeCommit"]["oid"]
        changed = self.sh("git", "--git-dir", self.origin, "diff", "--name-only", sha + "^", sha).split()
        self.assertEqual(sorted(changed), sorted([KIT_SRC + "/package.json", KIT_SRC + "/package-lock.json"]))
        self.assertEqual(json.loads(self.live(KIT_DEST + "/package.json"))["dependencies"][PACKAGE], NEW)
        self.assertEqual(json.loads(self.live(KIT_DEST + "/package-lock.json"))["packages"]["node_modules/" + PACKAGE]["version"], NEW)
        self.assertEqual(self.live(".unrelated"), "unrelated v1\n")

        # The install ran once, and the installed version is read back from the package npm ci put there.
        installed = json.loads((self.home / KIT_DEST / "node_modules" / PACKAGE / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(installed["version"], NEW)
        self.assertEqual(len([c for c in calls if c.startswith("npm ci")]), 1)

        self.assertEqual([line["step"] for line in self.log_lines()],
                         ["profile", "pr", "publish", "checks", "gates", "merge", "drift", "apply", "install", "verify"])
        self.assertTrue(all(line["outcome"] == "ok" for line in self.log_lines()))

        # A rerun resumes the merged PR: no new PR, no second merge, and it still leaves main's unrelated change alone.
        again = self.bump()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("resuming PR #100 (MERGED)", again.stdout)
        self.assertEqual(len(self.prs()), 1)
        self.assertEqual(len([c for c in self.calls() if c.startswith("gh pr merge")]), 1)
        self.assertEqual(self.live(".unrelated"), "unrelated v1\n")

    def test_red_checks_stop_with_the_pr_open_and_a_rerun_merges_it(self):
        self.world()
        self.gh_state.write_text(json.dumps({"prs": [], "checks": [[{"name": "tests", "bucket": "fail"}]]}), encoding="utf-8")
        result = self.bump()
        self.assert_stopped(result, "checks", "red checks: tests (fail); it is left open at https://example.test/pull/100")
        self.assertFalse(any(c.startswith("gh pr merge") for c in self.calls()))
        self.assert_nothing_applied()
        self.assertEqual(self.prs()[0]["state"], "OPEN")

        self.gh_state.write_text(json.dumps({"prs": self.prs(), "checks": [[{"name": "tests", "bucket": "pass"}]]}), encoding="utf-8")
        again = self.bump()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("resuming PR #100 (OPEN)", again.stdout)
        self.assertEqual(len([c for c in self.calls() if c.startswith("gh pr merge")]), 1)

    def refused_gate(self, gate):
        self.world()
        self.refuse = gate
        result = self.bump()
        self.assert_stopped(result, "gates", gate)
        self.assertFalse(any(c.startswith("gh pr merge") for c in self.calls()))
        self.assert_nothing_applied()
        self.assertEqual(self.prs()[0]["state"], "OPEN")

    def test_a_red_main_stops_before_the_merge_and_applies_nothing(self):
        self.refused_gate("ci-main-status")

    def test_a_pr_body_that_fails_the_body_check_stops_before_the_merge_and_applies_nothing(self):
        self.refused_gate("pr-body-check")

    def test_a_live_edit_to_a_pin_file_stops_before_the_apply(self):
        self.world()
        lock = self.home / KIT_DEST / "package-lock.json"
        lock.write_text(lock.read_text(encoding="utf-8") + "# local\n", encoding="utf-8")
        result = self.bump()
        self.assert_stopped(result, "drift", "neither the pre-PR nor the PR content: %s" % lock)
        self.assertTrue(lock.read_text(encoding="utf-8").endswith("# local\n"))
        self.assertEqual(self.live(KIT_DEST + "/package.json"), self.seed[KIT_SRC + "/package.json"])
        self.assertFalse(any(c.startswith("npm ci") for c in self.calls()))

    def test_an_installed_version_other_than_the_pin_stops_at_verify(self):
        self.world()
        self.npm_installs = "0.0.1"
        result = self.bump()
        self.assert_stopped(result, "verify", "%s 0.0.1 is installed here, not %s" % (PACKAGE, NEW))

    def refused_profile(self, profile):
        self.world(profile=profile)
        result = self.bump()
        self.assert_stopped(result, "profile", "profile is '%s'" % profile)
        self.assertEqual(self.calls(), [])  # no gh, npm or gate call at all
        self.assertEqual(self.sh("git", "--git-dir", self.origin, "branch", "--list", "agent-kit-*"), "")
        self.assert_nothing_applied()

    def test_the_work_profile_is_refused_before_anything(self):
        self.refused_profile("axon-work-computer")

    def test_the_termux_profile_is_refused_before_anything(self):
        self.refused_profile("termux")

    def test_a_pin_already_on_main_and_installed_does_nothing(self):
        self.world()
        self.assertEqual(self.bump().returncode, 0)
        state = json.loads(self.gh_state.read_text(encoding="utf-8"))
        state["prs"] = []  # as if a person had made the bump PR by hand
        self.gh_state.write_text(json.dumps(state), encoding="utf-8")
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("nothing to do", result.stdout)
        self.assertEqual(len([c for c in self.calls() if c.startswith("gh pr create")]), 1)


class BodyTests(unittest.TestCase):
    def test_the_generated_body_has_the_principles_table_and_a_decisions_line(self):
        spec = importlib.util.spec_from_file_location("agent_kit_bump", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        body = module.pr_body(NEW)
        rows = {int(m.group(1)) for m in re.finditer(r"^\| (\d+) \| .+ \| (?:pass|fail|n/a) \| .+ \|$", body, re.M)}
        self.assertEqual(rows, set(range(1, 16)))
        self.assertRegex(body, r"(?m)^Decisions: none material$")
        self.assertEqual(re.findall(r"(?<![\w-])(?:D-\d+|D\d+|MK-\d+|T\d+)(?![\w-])", body), [])


if __name__ == "__main__":
    unittest.main()
