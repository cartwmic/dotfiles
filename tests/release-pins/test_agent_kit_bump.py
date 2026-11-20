"""Black-box tests for dot_local/user_scripts/executable_agent_kit_bump.py (playbook rule 7c57de5a in one command).

Each test runs the real script against a scratch world: a bare git origin holding a small chezmoi source with the agent-kit
pin, the 65 install template and an unrelated file; a clone of it as the source checkout; and a scratch HOME (chezmoi's
destination, config and state) applied from that source. chezmoi and git are real. The gh, npm, ci-main-status and
pr-body-check and pr-record on PATH are scripted fakes (pr-record writes nothing: it prints a path under a scratch traces dir); every call goes to one log file, so the order of checks, gates and merge can be
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
PRINCIPLE_HEADINGS = re.findall(r"(?m)^## (\d+)\. (.+)$", (ROOT / "dot_local/share/agent-harness/design-principles.md").read_text())
LAST_PRINCIPLE = (int(PRINCIPLE_HEADINGS[-1][0]), PRINCIPLE_HEADINGS[-1][1])
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
with open(os.environ["FAKE_GH_ENV_LOG"], "a") as env_log:  # what each gh call's environment said: the urgency test reads it
    env_log.write(json.dumps({"args": args, "urgent": os.environ.get("GH_URGENT"), "caller": os.environ.get("GH_CALLER")}) + "\n")
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
if verb == "view" and "files" in args[-1]:  # the PR's changed files, read before anything is pushed
    files = [f for f in git("diff", "--name-only", "main..." + pr["head"]).split("\n") if f]
    out({"files": [{"path": f} for f in files], "changedFiles": pr.get("changedFiles", len(files)), "isCrossRepository": pr.get("fork", False)})
if verb == "view":
    head = git("rev-parse", "refs/heads/" + pr["head"])
    stale = state.get("stale")  # GitHub lags: after a push, report the old head for `count` reads
    if stale and head != stale["oid"] and stale["count"] > 0:
        stale["count"] -= 1
        head = stale["oid"]
    out({"number": pr["number"], "state": pr["state"], "url": pr["url"], "mergeCommit": pr["mergeCommit"],
         "headRefOid": head, "headRefName": pr["head"]})
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
  echo "$(basename "$0"): RED on stdout"
  echo "$(basename "$0"): refused by the test" >&2
  exit 1
fi
exit 0
'''

FAKE_PR_RECORD = r'''#!/bin/sh
# A scripted `pr-record path [OWNER/]REPO#N`: logs its call and prints the record path under a scratch traces dir, so a test never writes the real agent-traces.
echo "pr-record $*" >> "$FAKE_CALL_LOG"
[ "$1" = path ] || exit 2
echo "$FAKE_TRACES_DIR/emitted/review/${2#*/}/pr-record.md"
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
        for name, text in (("gh", FAKE_GH), ("npm", FAKE_NPM), ("ci-main-status", FAKE_GATE), ("pr-body-check", FAKE_GATE), ("pr-record", FAKE_PR_RECORD)):
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
                "FAKE_GH_ENV_LOG": str(self.dir / "gh-env.jsonl"),
                "FAKE_GH_STATE": str(self.gh_state), "FAKE_ORIGIN": str(self.origin), "FAKE_GATE_REFUSE": self.refuse,
                "FAKE_NPM_INSTALLS": self.npm_installs, "NODE_AUTH_TOKEN": "fake-token", "FAKE_TRACES_DIR": str(self.dir / "traces"),
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

    def bump(self, version=NEW, *extra):
        return subprocess.run([sys.executable, str(SCRIPT), version, "--source", str(self.checkout), *extra], env=self.env(),
                              capture_output=True, text=True, timeout=300)

    def live(self, path):
        target = self.home / path
        return target.read_text(encoding="utf-8") if target.is_file() else None

    def record(self, item):
        path = self.dir / "traces/emitted/review" / item / "pr-record.md"
        return path.read_text(encoding="utf-8") if path.exists() else None

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

    def test_every_gh_call_of_a_bump_is_urgent_and_names_the_script(self):
        # Reads too (pr list, pr checks, pr view), not only the merge: the gh budget guard never refuses a GH_URGENT=1
        # call, and GH_CALLER names the script in the gh wrapper's log.
        self.world()
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [json.loads(line) for line in (self.dir / "gh-env.jsonl").read_text(encoding="utf-8").splitlines()]
        verbs = {tuple(c["args"][:2]) for c in calls}
        for verb in (("pr", "list"), ("pr", "checks"), ("pr", "create"), ("pr", "view"), ("pr", "merge")):
            self.assertIn(verb, verbs)
        self.assertEqual({(c["urgent"], c["caller"]) for c in calls}, {("1", "agent_kit_bump")})

    def test_an_existing_record_is_never_overwritten(self):
        self.world()
        existing = self.dir / "traces/emitted/review/dotfiles#100/pr-record.md"
        existing.parent.mkdir(parents=True)
        existing.write_text("kept\n", encoding="utf-8")
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.record("dotfiles#100"), "kept\n")

    def test_happy_path_checks_then_gates_then_merge_then_only_the_pins_applied_and_installed(self):
        self.world()
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("installed: %s %s" % (PACKAGE, NEW), result.stdout)

        prs = self.prs()
        self.assertEqual(len(prs), 1)
        # The description holds none of the bookkeeping; the agent record, at the path `pr-record path dotfiles#100` gave, holds all of it.
        self.assertNotIn("|", prs[0]["body"])
        self.assertNotIn("Decisions:", prs[0]["body"])
        record = self.record("dotfiles#100")
        self.assertIn("| %d | %s |" % LAST_PRINCIPLE, record)
        self.assertTrue(record.endswith("\nDecisions: none material\n"))

        # Checks, then the two gates in order, then the squash merge, which must name the head the checks ran on.
        calls = self.calls()
        index = {name: next(i for i, c in enumerate(calls) if c.startswith(name))
                 for name in ("gh pr checks", "ci-main-status", "pr-record", "pr-body-check", "gh pr merge")}
        self.assertLess(index["gh pr checks"], index["ci-main-status"])
        self.assertLess(index["ci-main-status"], index["pr-body-check"])
        self.assertLess(index["pr-record"], index["pr-body-check"])  # the record exists before the check that reads it
        self.assertLess(index["pr-record"], index["gh pr checks"])  # publish wrote it, right after the PR was made
        gates = next(line for line in self.log_lines() if line["step"] == "gates")
        self.assertTrue(gates["detail"].endswith(" passed"), gates["detail"])  # gates found the record and wrote nothing
        self.assertLess(index["pr-body-check"], index["gh pr merge"])
        self.assertEqual(calls[index["pr-record"]], "pr-record path dotfiles#100")
        self.assertEqual(calls[index["ci-main-status"]], "ci-main-status --merge-gate dotfiles --pr 100")
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

        # The source checkout moved to the merge commit, so a later full apply cannot restore the old pins.
        self.assertEqual(self.sh("git", "-C", self.checkout, "rev-parse", "HEAD").strip(), sha)
        self.assertEqual(self.sh("git", "-C", self.checkout, "status", "--porcelain"), "")

        # The install ran once, and the installed version is read back from the package npm ci put there.
        installed = json.loads((self.home / KIT_DEST / "node_modules" / PACKAGE / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(installed["version"], NEW)
        self.assertEqual(len([c for c in calls if c.startswith("npm ci")]), 1)

        self.assertEqual([line["step"] for line in self.log_lines()],
                         ["profile", "pr", "publish", "checks", "gates", "merge", "source", "drift", "apply", "install", "verify"])
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

        self.assertIsNotNone(self.record("dotfiles#100"))  # publish wrote it before the checks ran
        (self.dir / "traces/emitted/review/dotfiles#100/pr-record.md").unlink()  # a PR made before this script wrote records

        self.gh_state.write_text(json.dumps({"prs": self.prs(), "checks": [[{"name": "tests", "bucket": "pass"}]]}), encoding="utf-8")
        again = self.bump()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("resuming PR #100 (OPEN)", again.stdout)
        self.assertEqual(len([c for c in self.calls() if c.startswith("gh pr merge")]), 1)
        # The gates step wrote the missing record, said so in its log line, and the merge check then read it.
        self.assertIn("| %d | %s |" % LAST_PRINCIPLE, self.record("dotfiles#100"))
        gates = [line for line in self.log_lines() if line["step"] == "gates"][-1]
        self.assertTrue(gates["detail"].endswith("passed (the agent record was missing; wrote it)"), gates["detail"])

    def refused_gate(self, gate):
        self.world()
        self.refuse = gate
        result = self.bump()
        self.assert_stopped(result, "gates", gate)
        self.assertFalse(any(c.startswith("gh pr merge") for c in self.calls()))
        self.assert_nothing_applied()
        self.assertEqual(self.prs()[0]["state"], "OPEN")
        return result

    def test_a_red_main_stops_before_the_merge_and_applies_nothing(self):
        self.refused_gate("ci-main-status")

    def test_the_stop_message_shows_the_gates_stdout_and_its_refusal_reason(self):
        result = self.refused_gate("ci-main-status")
        self.assertIn("ci-main-status: RED on stdout\nci-main-status: refused by the test", result.stderr)

    def test_a_pr_body_that_fails_the_body_check_stops_before_the_merge_and_applies_nothing(self):
        self.refused_gate("pr-body-check")

    def test_the_pr_body_stop_message_shows_the_gates_stdout_and_its_refusal_reason(self):
        # The body check printed on stdout and refused on stderr. The stop message must carry the refusal, not only stdout.
        result = self.refused_gate("pr-body-check")
        self.assertIn("pr-body-check: RED on stdout\npr-body-check: refused by the test", result.stderr)

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


    def test_a_source_checkout_that_cannot_fast_forward_stops_before_apply_and_a_rerun_applies(self):
        self.world()
        self.sh("git", "-C", self.checkout, "commit", "-q", "--allow-empty", "-m", "local only, not pushed")
        result = self.bump()
        self.assert_stopped(result, "source", "cannot fast-forward the chezmoi source checkout")
        self.assertEqual(self.prs()[0]["state"], "MERGED")  # the merge happened; only the source is behind
        self.assert_nothing_applied()
        self.sh("git", "-C", self.checkout, "reset", "-q", "--hard", "origin/main")  # the fix a person makes
        again = self.bump()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("resuming PR #100 (MERGED)", again.stdout)
        self.assertEqual(json.loads(self.live(KIT_DEST + "/package.json"))["dependencies"][PACKAGE], NEW)

    # --pr N: the pin goes onto a Loop Engine bump PR that already exists (two releases landed close together; dotfiles#573).
    LE_BRANCH = "loop-engine-v9.9.9"
    LE_FILES = {"dot_config/mise/config.toml": "[tools]\nloop-engine = \"9.9.9\"\n",
                "dot_local/share/agent-harness/canonical/skills/using-x/SKILL.md": "a skill\n"}

    def existing_pr(self, files=None, state="OPEN"):
        """A PR #7 on a branch from main carrying `files` (default: the Loop Engine's mise config and one skill)."""
        clone = self.dir / "le-clone"
        self.sh("git", "clone", "-q", self.origin, clone)
        self.sh("git", "-C", clone, "switch", "-q", "-c", self.LE_BRANCH)
        for path, text in (self.LE_FILES if files is None else files).items():
            (clone / path).parent.mkdir(parents=True, exist_ok=True)
            (clone / path).write_text(text, encoding="utf-8")
        self.sh("git", "-C", clone, "add", "-A")
        self.sh("git", "-C", clone, "commit", "-q", "-m", "chore(loop-engine): import 9.9.9")
        self.sh("git", "-C", clone, "push", "-q", "origin", self.LE_BRANCH)
        self.gh_state.write_text(json.dumps({"prs": [{"number": 7, "state": state, "url": "https://example.test/pull/7",
                                                      "head": self.LE_BRANCH, "title": "Loop Engine 9.9.9", "body": "", "mergeCommit": None}],
                                             "checks": [[{"name": "tests", "bucket": "pass"}]]}), encoding="utf-8")

    def branch_head(self):
        return self.sh("git", "--git-dir", self.origin, "rev-parse", "refs/heads/" + self.LE_BRANCH).strip()

    def test_pr_pins_onto_the_existing_pr_and_applies_only_the_agent_kit_files(self):
        self.world()
        self.existing_pr()
        before = self.branch_head()
        result = self.bump(NEW, "--pr", "7")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.prs()), 1, "no PR of its own")
        self.assertFalse(any(c.startswith("gh pr create") for c in self.calls()))
        self.assertEqual(self.sh("git", "--git-dir", self.origin, "branch", "--list", "agent-kit-*"), "")

        # One plain commit of the two pin files on top of the PR's head (an ancestor check: a force push would not keep it).
        after = self.sh("git", "--git-dir", self.origin, "rev-parse", "refs/heads/" + self.LE_BRANCH).strip()
        self.assertNotEqual(before, after)
        self.sh("git", "--git-dir", self.origin, "merge-base", "--is-ancestor", before, after)
        pushed = self.sh("git", "--git-dir", self.origin, "diff", "--name-only", before, after).split()
        self.assertEqual(sorted(pushed), sorted([KIT_SRC + "/package.json", KIT_SRC + "/package-lock.json"]))

        # The merge names the pushed head; the checks that ran are the new head's.
        calls = self.calls()
        self.assertIn("--match-head-commit " + after, [c for c in calls if c.startswith("gh pr merge")][0])
        self.assertEqual([c for c in calls if c.startswith("ci-main-status")], ["ci-main-status --merge-gate dotfiles --pr 7"])

        # The PR had no record, so the gates step wrote one before the body check; the PR's description is not touched.
        self.assertIn("| %d | %s |" % LAST_PRINCIPLE, self.record("dotfiles#7"))

        # The kit pin is applied and installed; the Loop Engine files in the same PR are left to loop_engine_bump.py.
        self.assertEqual(json.loads(self.live(KIT_DEST + "/package.json"))["dependencies"][PACKAGE], NEW)
        self.assertEqual(json.loads((self.home / KIT_DEST / "node_modules" / PACKAGE / "package.json").read_text())["version"], NEW)
        self.assertIsNone(self.live(".config/mise/config.toml"))
        self.assertIsNone(self.live(".local/share/agent-harness/canonical/skills/using-x/SKILL.md"))
        self.assertEqual([line["step"] for line in self.log_lines()],
                         ["profile", "pr", "publish", "checks", "gates", "merge", "source", "drift", "apply", "install", "verify"])

        # A rerun resumes the merged PR: no push, no second merge.
        again = self.bump(NEW, "--pr", "7")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(self.branch_head(), after)
        self.assertEqual(len([c for c in self.calls() if c.startswith("gh pr merge")]), 1)

    def test_pr_with_the_pin_already_on_its_head_pushes_nothing(self):
        self.world()
        self.existing_pr()
        self.gh_state.write_text(json.dumps({**json.loads(self.gh_state.read_text()), "checks": [[{"name": "tests", "bucket": "fail"}]]}))
        self.assert_stopped(self.bump(NEW, "--pr", "7"), "checks", "red checks")
        pinned = self.branch_head()  # the first run pushed the pin, then stopped on the red check
        self.gh_state.write_text(json.dumps({**json.loads(self.gh_state.read_text()), "checks": [[{"name": "tests", "bucket": "pass"}]]}))
        result = self.bump(NEW, "--pr", "7")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already pins", result.stdout)
        self.assertEqual(self.sh("git", "--git-dir", self.origin, "log", "--format=%s", "-n", "3", pinned).count("pin %s %s" % (PACKAGE, NEW)), 1)

    def test_the_checks_wait_for_github_to_report_the_pushed_head(self):
        self.world()
        self.existing_pr()
        before = self.branch_head()
        state = json.loads(self.gh_state.read_text())
        state["stale"] = {"oid": before, "count": 3}
        self.gh_state.write_text(json.dumps(state))
        result = self.bump(NEW, "--pr", "7")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = self.calls()
        merge = next(i for i, c in enumerate(calls) if c.startswith("gh pr merge"))
        self.assertIn("--match-head-commit " + self.branch_head(), calls[merge])
        self.assertNotIn("--match-head-commit " + before, calls[merge])
        # Four reads of the PR after the push (three stale, one current) came before the checks.
        views = [i for i, c in enumerate(calls) if c.startswith("gh pr view 7 --json number")]
        self.assertGreaterEqual(len([i for i in views if i < next(i for i, c in enumerate(calls) if c.startswith("gh pr checks"))]), 5)

    def test_a_head_that_never_shows_the_push_stops_without_checks_or_merge(self):
        self.world()
        self.existing_pr()
        state = json.loads(self.gh_state.read_text())
        state["stale"] = {"oid": self.branch_head(), "count": 1000}
        self.gh_state.write_text(json.dumps(state))
        result = self.bump(NEW, "--pr", "7")
        self.assert_stopped(result, "publish", "still reports head")
        self.assertFalse(any(c.startswith(("gh pr checks", "gh pr merge")) for c in self.calls()))

    def test_pr_closed_without_merging_stops(self):
        self.world()
        self.existing_pr(state="CLOSED")
        before = self.branch_head()
        self.assert_stopped(self.bump(NEW, "--pr", "7"), "pr", "was closed without merging")
        self.assertEqual(self.branch_head(), before)
        self.assert_nothing_applied()

    def assert_refused_untouched(self, result, text):
        """Refused before anything is pushed, merged or applied: the PR branch and main are as they were."""
        before_main = self.sh("git", "--git-dir", self.origin, "rev-parse", "refs/heads/main").strip()
        self.assert_stopped(result, "publish", text)
        self.assertEqual(self.branch_head(), self.before_head)
        self.assertEqual(self.sh("git", "--git-dir", self.origin, "rev-parse", "refs/heads/main").strip(), before_main)
        self.assertFalse(any(c.startswith(("gh pr merge", "ci-main-status", "pr-body-check", "npm")) for c in self.calls()), self.calls())
        self.assertEqual(self.prs()[0]["state"], "OPEN")
        self.assert_nothing_applied()

    def refused_pr(self, **kwargs):
        self.world()
        self.existing_pr(**kwargs)
        self.before_head = self.branch_head()
        return self.bump(NEW, "--pr", "7")

    def test_a_pr_with_only_an_unrelated_file_is_refused_before_anything_is_pushed_or_merged(self):
        # The reviewer's probe (dotfiles#575 round 1): a mistyped N must not merge an unrelated PR into main.
        result = self.refused_pr(files={"dot_unrelated_feature": "not a pin\n"})
        self.assert_refused_untouched(result, "outside the agent-kit pins and the Loop Engine pins and skills: dot_unrelated_feature")
        self.assertNotIn("dot_unrelated_feature", self.sh("git", "--git-dir", self.origin, "ls-tree", "-r", "--name-only", "refs/heads/main"))

    def test_a_third_file_beside_the_loop_engine_files_is_refused_before_anything_is_pushed(self):
        result = self.refused_pr(files={**self.LE_FILES, "dot_unrelated_new": "not a pin\n"})
        self.assert_refused_untouched(result, "outside the agent-kit pins and the Loop Engine pins and skills: dot_unrelated_new")

    def test_a_pr_from_a_fork_is_refused_before_anything_is_pushed(self):
        self.world()
        self.existing_pr()
        self.before_head = self.branch_head()
        state = json.loads(self.gh_state.read_text())
        state["prs"][0]["fork"] = True
        self.gh_state.write_text(json.dumps(state))
        self.assert_refused_untouched(self.bump(NEW, "--pr", "7"), "is from a fork")

    def test_a_file_list_shorter_than_the_changed_file_count_is_refused(self):
        self.world()
        self.existing_pr()
        self.before_head = self.branch_head()
        state = json.loads(self.gh_state.read_text())
        state["prs"][0]["changedFiles"] = 150  # gh listed the pages it got, not all 150
        self.gh_state.write_text(json.dumps(state))
        self.assert_refused_untouched(self.bump(NEW, "--pr", "7"), "gh listed 2 of PR #7's 150 changed files")

    def test_a_pr_with_only_one_agent_kit_pin_file_stops_at_drift(self):
        self.world()
        self.existing_pr(files={KIT_SRC + "/package.json": json.dumps({"dependencies": {PACKAGE: NEW}}) + "\n"})
        # --pr would add the second file; to see the one-file shape, merge it as a bare PR that this script did not touch.
        state = json.loads(self.gh_state.read_text())
        sha = self.branch_head()
        self.sh("git", "--git-dir", self.origin, "update-ref", "refs/heads/main", sha)
        state["prs"][0].update(state="MERGED", mergeCommit={"oid": sha})
        self.gh_state.write_text(json.dumps(state))
        self.assert_stopped(self.bump(NEW, "--pr", "7"), "drift", "must change both agent-kit pin files")

    def test_a_source_checkout_not_on_main_stops_before_apply(self):
        self.world()
        self.sh("git", "-C", self.checkout, "checkout", "-q", "-b", "wip")
        result = self.bump()
        self.assert_stopped(result, "source", "is on wip, not main")
        self.assertEqual(self.prs()[0]["state"], "MERGED")
        self.assert_nothing_applied()
        self.assertEqual(self.sh("git", "-C", self.checkout, "branch", "--show-current").strip(), "wip")


class BodyTests(unittest.TestCase):
    def module(self):
        spec = importlib.util.spec_from_file_location("agent_kit_bump", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_the_generated_description_has_no_bookkeeping_and_says_what_why_how_and_risk(self):
        body = self.module().pr_body(NEW)
        self.assertNotIn("|", body)
        self.assertNotIn("Decisions:", body)
        for heading in ("What changes", "Why", "How it was checked", "Risk and rollback"):
            self.assertIn("## " + heading, body)
        self.assertIn(NEW, body)
        self.assertNotIn("playbook rule", body)
        self.assertNotIn("Profiles: both", body)
        self.assertEqual(re.findall(r"(?<![\w-])(?:D-\d+|D\d+|MK-\d+|T\d+)(?![\w-])", body), [])

    def test_the_record_has_the_principles_table_and_a_decisions_line(self):
        record = self.module().record_text(NEW)
        rows = {int(m.group(1)) for m in re.finditer(r"^\| (\d+) \| .+ \| (?:pass|fail|n/a) \| .+ \|$", record, re.M)}
        self.assertEqual(rows, set(range(1, LAST_PRINCIPLE[0] + 1)))
        self.assertRegex(record, r"(?m)^Decisions: none material$")
        # Nothing else is in the record: the heading, the table and the Decisions line.
        stray = [line for line in record.splitlines() if line and not line.startswith(("Principles (", "|", "Decisions: "))]
        self.assertEqual(stray, [])


if __name__ == "__main__":
    unittest.main()
