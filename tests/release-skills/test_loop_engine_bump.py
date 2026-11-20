"""Black-box tests for dot_local/user_scripts/executable_loop_engine_bump.py (playbook rule 7c57de5a in one command).

Each test runs the real script against a scratch world: a bare git origin holding a small chezmoi source, a clone of it
as the source checkout, a scratch HOME (chezmoi's destination, config and state) applied from that source, a scripted
gh that serves a release and the PR (create, checks, squash merge into the bare origin), a fake mise that records
installs. chezmoi, git and apply_harness_config.sh (skills mode) are real. Nothing here reaches GitHub, the real chezmoi
source or the real home directory.

    python3 -m unittest discover -s tests/release-skills -v
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
from unittest.mock import patch

from test_import_release_skills import FAKE_GH, GOOD_TREE, Fixture

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/user_scripts/executable_loop_engine_bump.py"
_HEADINGS = re.findall(r"(?m)^## (\d+)\. (.+)$", (ROOT / "dot_local/share/agent-harness/design-principles.md").read_text())
LAST_PRINCIPLE = (int(_HEADINGS[-1][0]), _HEADINGS[-1][1])
README = ROOT / "dot_local/share/agent-harness/README.md"
SKILLS_SRC = "dot_local/share/agent-harness/canonical/skills"
SKILLS_DEST = ".local/share/agent-harness/canonical/skills"
TOOLS = ("loop-engine", "lean-change", "policy-document", "research", "bookends-check")

PR_GH = r'''import subprocess
state.setdefault("calls", []).append(args)
def save():
    json.dump(state, open(os.environ["FAKE_GH_STATE"], "w"))
save()
with open(os.environ["FAKE_CALL_LOG"], "a") as call_log:  # one ordered log shared with the scripted gates
    call_log.write(" ".join(["gh"] + args) + "\n")
with open(os.environ["FAKE_GH_ENV_LOG"], "a") as env_log:  # what each gh call's environment said: the urgency test reads it
    env_log.write(json.dumps({"args": args, "urgent": os.environ.get("GH_URGENT"), "caller": os.environ.get("GH_CALLER")}) + "\n")
if args[0] == "pr":
    prs = state.setdefault("prs", [])
    def opt(name):
        return args[args.index(name) + 1]
    def git(*a):
        return subprocess.run(["git", "--git-dir", state["origin"], *a], check=True, capture_output=True, text=True).stdout.strip()
    if args[1] == "list":
        out([dict({k: p[k] for k in ("number", "state", "url", "mergeCommit")},
                  headRefOid=git("rev-parse", "refs/heads/%s" % p["head"])) for p in prs if p["head"] == opt("--head")])
    if args[1] == "create":
        n = 100 + len(prs)
        prs.append({"number": n, "state": "OPEN", "url": "https://example.test/pull/%d" % n, "head": opt("--head"),
                    "title": opt("--title"), "body": opt("--body"), "mergeCommit": None})
        save()
        print("https://example.test/pull/%d" % n)
        sys.exit(0)
    pr = [p for p in prs if p["number"] == int(args[2])][0]
    if args[1] == "checks":
        if state.get("move_head_after_checks"):  # someone pushes to the PR branch while the checks run
            tree = git("rev-parse", "refs/heads/%s^{tree}" % pr["head"])
            old = git("rev-parse", "refs/heads/%s" % pr["head"])
            git("update-ref", "refs/heads/%s" % pr["head"], git("commit-tree", tree, "-p", old, "-m", "pushed after the checks"))
            state["move_head_after_checks"] = False
        rounds = state["checks"]
        current = rounds.pop(0) if len(rounds) > 1 else rounds[0]
        save()
        out(current)
    if args[1] == "merge":
        if "--match-head-commit" in args:  # as real gh: refuse unless the branch is still that commit
            if args[args.index("--match-head-commit") + 1] != git("rev-parse", "refs/heads/%s" % pr["head"]):
                print("Head branch was modified. Review the latest version and try again.", file=sys.stderr)
                sys.exit(1)
        tree = git("rev-parse", "refs/heads/%s^{tree}" % pr["head"])
        sha = git("commit-tree", tree, "-p", "refs/heads/main", "-m", "%s (#%d)" % (pr["title"], pr["number"]))
        git("update-ref", "refs/heads/main", sha)
        pr.update(state="MERGED", mergeCommit={"oid": sha})
        save()
        sys.exit(0)
    if args[1] == "view":
        out({k: pr[k] for k in ("number", "state", "url", "mergeCommit")})
'''
FAKE_GH_WITH_PRS = FAKE_GH.replace('if args[:2] == ["release", "view"]:', PR_GH + 'if args[:2] == ["release", "view"]:')

FAKE_MISE = r'''#!/usr/bin/env python3
import json, os, re, sys
path = os.environ["FAKE_MISE_STATE"]
state = json.load(open(path)) if os.path.exists(path) else {"calls": [], "installed": {}}
args = sys.argv[1:]
state["calls"].append(args)
config = open(os.path.join(os.environ["HOME"], ".config/mise/config.toml")).read()
def configured(tool):
    m = re.search(r'^%s = \{ version = "([^"]+)"' % re.escape(tool), config, re.M)
    return m.group(1) if m else None
if args[0] == "install":
    for tool in args[1:]:
        state["installed"].setdefault(tool, []).append(configured(tool))
elif args[0] == "current":  # as real mise: the configured version, installed or not
    print(configured(args[1]) or "")
elif args[:3] == ["ls", "--installed", "--json"]:  # as real mise: installed versions only; active = the configured one
    print(json.dumps({tool: [{"version": v, "installed": True, "active": v == configured(tool)} for v in sorted(set(vs))]
                      for tool, vs in state["installed"].items() if vs}))
else:
    sys.exit(1)
json.dump(state, open(path, "w"))
'''

FAKE_GATE = r'''#!/bin/sh
# A scripted merge gate: logs its call to FAKE_CALL_LOG, and refuses when FAKE_GATE_REFUSE names it.
echo "$(basename "$0") $*" >> "$FAKE_CALL_LOG"
if [ "${FAKE_GATE_REFUSE:-}" = "$(basename "$0")" ]; then
    echo "$(basename "$0"): RED on stdout"
    echo "refused by the fake $(basename "$0")" >&2
    exit 1
fi
'''


# A scripted `pr-record path [OWNER/]REPO#N`: logs its call and prints the record path under a scratch traces dir, so a test never writes the real agent-traces.
FAKE_PR_RECORD = r'''#!/bin/sh
echo "pr-record $*" >> "$FAKE_CALL_LOG"
[ "$1" = path ] || exit 2
echo "$FAKE_TRACES_DIR/emitted/review/${2#*/}/pr-record.md"
'''


def pins(version):
    return "".join('%s = { version = "%s", matching_regex = "^x-", rename_exe = "%s" }\n' % (t, version, t) for t in TOOLS)


def _load_body_check():
    spec = importlib.util.spec_from_file_location("bump_pr_body", ROOT / "scripts/bump_pr_body.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


body_problems = _load_body_check().problems  # the check shared with tests/release-pins (agent_kit_bump.py)


def assert_clean_body(test, body, *scratch):
    test.assertEqual(body_problems(body, *scratch), [], "the PR body carries script bookkeeping")


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("git"), "needs chezmoi and git")
class BumpTests(Fixture):
    def setUp(self):
        super().setUp()  # the scripted release v1.0.0 (GOOD_TREE) and a fake gh
        (self.bin / "gh").write_text(FAKE_GH_WITH_PRS)
        (self.bin / "mise").write_text(FAKE_MISE)
        (self.bin / "mise").chmod(0o755)
        for gate in ("ci-main-status", "pr-body-check"):
            (self.bin / gate).write_text(FAKE_GATE)
            (self.bin / gate).chmod(0o755)
        (self.bin / "pr-record").write_text(FAKE_PR_RECORD)
        (self.bin / "pr-record").chmod(0o755)
        self.refuse = ""  # the name of a gate the next run should refuse
        self.home = self.dir / "scratch-home"
        self.origin = self.dir / "origin.git"
        self.checkout = self.dir / "checkout"
        self.state["origin"] = str(self.origin)
        self.state["checks"] = [[{"name": "tests", "bucket": "pass"}]]
        self.save()
        self.git_env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example.test", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        self.seed = {
            "dot_config/mise/config.toml": 'gh = "latest"\n' + pins("0.9.0"),
            SKILLS_SRC + "/using-foo-provider/SKILL.md": "foo skill v0\n",
            SKILLS_SRC + "/my-own-skill/SKILL.md": "mine\n",
            "dot_unrelated": "unrelated v1\n",
        }

    def save(self):
        self.state_path.write_text(json.dumps(self.state))

    def load(self):
        self.state = json.loads(self.state_path.read_text())
        return self.state

    def env(self):
        return {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / ".config"), "XDG_CACHE_HOME": str(self.home / ".cache"),
                "XDG_STATE_HOME": str(self.home / ".local/state"), "FAKE_GH_STATE": str(self.state_path),
                "FAKE_MISE_STATE": str(self.dir / "mise.json"), "LOOP_ENGINE_BUMP_POLL_SECONDS": "0",
                "FAKE_CALL_LOG": str(self.dir / "calls.log"), "FAKE_GH_ENV_LOG": str(self.dir / "gh-env.jsonl"),
                "FAKE_GATE_REFUSE": self.refuse, "FAKE_TRACES_DIR": str(self.dir / "traces"), "TMPDIR": str(self.dir), **self.git_env}

    def sh(self, *cmd, cwd=None):
        result = subprocess.run([str(c) for c in cmd], cwd=cwd, env=self.env(), capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, "%s: %s%s" % (cmd, result.stdout, result.stderr))
        return result.stdout

    def world(self, profile="personal", extra=None):
        """Origin with the seed plus one later unrelated commit; HOME applied from the seed commit."""
        self.sh("git", "init", "-q", "--bare", "-b", "main", self.origin)
        self.sh("git", "clone", "-q", self.origin, self.checkout)
        for path, text in {**self.seed, **(extra or {})}.items():
            (self.checkout / path).parent.mkdir(parents=True, exist_ok=True)
            (self.checkout / path).write_text(text)
        tools = self.checkout / "dot_local/user_scripts"
        tools.mkdir(parents=True, exist_ok=True)
        for name in ("executable_import_release_skills.py", "executable_apply_harness_config.sh"):
            shutil.copy(ROOT / "dot_local/user_scripts" / name, tools / name)
        self.sh("git", "-C", self.checkout, "add", "-A")
        self.sh("git", "-C", self.checkout, "commit", "-q", "-m", "seed")
        self.sh("git", "-C", self.checkout, "push", "-q", "origin", "main")
        config = self.home / ".config/chezmoi/chezmoi.yaml"
        config.parent.mkdir(parents=True)
        config.write_text("data:\n  profile: %s\n" % profile)
        self.sh("chezmoi", "--source", self.checkout, "--no-tty", "apply")
        self.sh("sh", self.checkout / "dot_local/user_scripts/executable_apply_harness_config.sh", "skills")
        # Harness settings the bump must leave alone (a full harness apply would rewrite them).
        (self.home / ".codex").mkdir(exist_ok=True)
        (self.home / ".codex/config.toml").write_text("# local edit\n")
        self.sh("mise", "install", *TOOLS)
        # Someone else's later change on main, not applied here: the bump must not apply it.
        other = self.dir / "other"
        self.sh("git", "clone", "-q", self.origin, other)
        (other / "dot_unrelated").write_text("unrelated v2\n")
        self.sh("git", "-C", other, "commit", "-q", "-am", "unrelated")
        self.sh("git", "-C", other, "push", "-q", "origin", "main")
        self.load()
        self.state.pop("calls", None)
        self.save()

    def hook(self):
        """Add a side-effecting read-source-state hook to the scratch chezmoi config; return the file it would make."""
        marker = self.dir / "hook-ran"
        config = self.home / ".config/chezmoi/chezmoi.yaml"
        config.write_text(config.read_text() + "hooks:\n  read-source-state:\n    pre:\n      command: touch\n"
                          "      args: [%s]\n" % json.dumps(str(marker)))
        return marker

    def bump(self, tag="v1.0.0"):
        return subprocess.run([sys.executable, SCRIPT, tag, "--source", self.checkout], env=self.env(),
                              capture_output=True, text=True, timeout=300)

    def record(self, item):
        path = self.dir / "traces/emitted/review" / item / "pr-record.md"
        return path.read_text(encoding="utf-8") if path.exists() else None

    def live(self, path):
        target = self.home / path
        return target.read_text() if target.is_file() else None

    def gh_calls(self, verb):
        return [c for c in self.load().get("calls", []) if c[:2] == ["pr", verb]]

    def mise_installs(self):
        return [c for c in json.loads((self.dir / "mise.json").read_text())["calls"] if c[0] == "install"]

    def log_lines(self):
        path = self.home / ".local/state/loop-engine-bump/log.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def assert_nothing_applied(self):
        self.assertEqual(self.live(".config/mise/config.toml"), self.seed["dot_config/mise/config.toml"])
        self.assertEqual(self.live(SKILLS_DEST + "/using-foo-provider/SKILL.md"), "foo skill v0\n")
        self.assertIsNone(self.live(SKILLS_DEST + "/using-loop-engine/SKILL.md"))
        self.assertEqual(len(self.mise_installs()), 1)  # the setup's own install only

    def assert_stopped(self, result, step, text):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("stopped at step %s:" % step, result.stderr)
        self.assertIn(text, result.stderr)
        self.assertEqual(self.log_lines()[-1]["step"], step)
        self.assertEqual(self.log_lines()[-1]["outcome"], "stopped")

    # d1 -------------------------------------------------------------------------------------------

    def test_every_gh_call_of_a_bump_is_urgent_and_names_the_script(self):
        # Reads too (pr list, pr checks, pr view, release view), not only the merge: the gh budget guard never refuses a
        # GH_URGENT=1 call, and GH_CALLER names the script in the gh wrapper's log.
        self.world()
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        calls = [json.loads(line) for line in (self.dir / "gh-env.jsonl").read_text().splitlines()]
        verbs = {tuple(c["args"][:2]) for c in calls}
        for verb in (("pr", "list"), ("pr", "checks"), ("pr", "create"), ("pr", "view"), ("pr", "merge")):
            self.assertIn(verb, verbs)
        self.assertEqual({(c["urgent"], c["caller"]) for c in calls}, {("1", "loop_engine_bump")})

    def test_d1_happy_path_one_pr_one_merge_only_the_pr_targets_applied(self):
        self.world()
        marker = self.hook()
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker.exists(), "a configured chezmoi hook ran")
        self.assertEqual(len(self.gh_calls("create")), 1)
        self.assertEqual(len(self.gh_calls("merge")), 1)
        pr = self.load()["prs"][0]
        self.assertEqual(pr["head"], "loop-engine-v1.0.0")
        self.assertIn("Both profiles get the pins and skills", pr["body"])
        # The description holds none of the bookkeeping; the agent record, at the path `pr-record path dotfiles#100` gave, holds all of it.
        self.assertNotIn("| %d | %s |" % LAST_PRINCIPLE, pr["body"])
        self.assertNotIn("Decisions:", pr["body"])
        assert_clean_body(self, pr["body"], str(self.dir))
        self.assertNotIn("applied to ", pr["body"])  # the import tool's scratch-dir line is not carried into the description
        record = self.record("dotfiles#100")
        self.assertIn("| %d | %s |" % LAST_PRINCIPLE, record)  # the principles table pr-body-check reads (rule ecd63156)
        self.assertTrue(record.endswith("\nDecisions: none material\n"))  # rule ccc6c94b
        sha = pr["mergeCommit"]["oid"]
        changed = self.sh("git", "--git-dir", self.origin, "diff", "--name-only", sha + "^", sha).split()
        self.assertIn("dot_config/mise/config.toml", changed)
        self.assertTrue(all(p == "dot_config/mise/config.toml" or p.startswith(SKILLS_SRC + "/") for p in changed), changed)
        # Only the PR's targets were applied: pins, the imported skills; not main's unrelated later change.
        self.assertEqual(self.live(".config/mise/config.toml"), 'gh = "latest"\n' + pins("1.0.0"))
        self.assertEqual(self.live(SKILLS_DEST + "/using-foo-provider/SKILL.md"), "foo skill v1\n")
        self.assertEqual(self.live(SKILLS_DEST + "/using-loop-engine/references/PRD.md"), "prd\n")
        self.assertEqual(self.live(SKILLS_DEST + "/my-own-skill/SKILL.md"), "mine\n")
        self.assertEqual(self.live(".unrelated"), "unrelated v1\n")
        for harness in (".claude/skills", ".codex/skills", ".pi/agent/skills", ".agents/skills"):
            self.assertTrue((self.home / harness / "using-other").is_symlink(), harness)
        self.assertEqual(self.live(".codex/config.toml"), "# local edit\n")
        self.assertFalse((self.home / ".pi/agent/mcp.json").exists())
        self.assertFalse((self.home / ".local/share/agent-harness/generated").exists())
        self.assertEqual(self.mise_installs()[-1], ["install", *TOOLS])
        self.assertIn("PR #100 https://example.test/pull/100", result.stdout)
        self.assertIn("merge " + sha, result.stdout)
        self.assertIn("installed: loop-engine 1.0.0, lean-change 1.0.0, policy-document 1.0.0, research 1.0.0, bookends-check 1.0.0", result.stdout)
        self.assertIn("+foo skill v1", result.stdout)  # the diff it checked
        lines = self.log_lines()
        self.assertEqual(len({line["id"] for line in lines}), 1)
        self.assertEqual([line["step"] for line in lines],
                         ["profile", "pr", "import", "publish", "checks", "gates", "merge", "source", "drift", "apply",
                          "install", "verify"])
        self.assertTrue(all(line["outcome"] == "ok" and line["utc"].endswith("Z") for line in lines))
        self.assertEqual(len(self.sh("git", "-C", self.checkout, "worktree", "list").splitlines()), 1)

        # A rerun finds the merged PR and opens nothing new.
        again = self.bump()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("resuming PR #100 (MERGED)", again.stdout)
        self.assertEqual(len(self.gh_calls("create")), 1)
        self.assertEqual(len(self.gh_calls("merge")), 1)
        self.assertEqual(self.live(".unrelated"), "unrelated v1\n")

    def test_d1_pending_checks_are_waited_for(self):
        self.world()
        self.state["checks"] = [[{"name": "tests", "bucket": "pending"}], [], [{"name": "tests", "bucket": "pass"}]]
        self.save()
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("checks: waiting, 1 pending: tests", result.stdout)
        self.assertEqual(len(self.gh_calls("checks")), 3)

    # d2 -------------------------------------------------------------------------------------------

    def test_d1_a_rerun_repairs_links_a_failed_run_left_behind(self):
        self.world()
        blocker = self.home / ".codex/skills"
        shutil.rmtree(blocker)
        blocker.write_text("not a directory\n")  # link_skill_dirs cannot mkdir it
        result = self.bump()
        self.assert_stopped(result, "apply", "apply_harness_config.sh")
        self.assertEqual(self.live(SKILLS_DEST + "/using-foo-provider/SKILL.md"), "foo skill v1\n")  # files were applied
        blocker.unlink()
        again = self.bump()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(len(self.gh_calls("create")), 1)
        self.assertEqual(len(self.gh_calls("merge")), 1)
        self.assertTrue((self.home / ".codex/skills/using-other").is_symlink())

    def test_d2_orphans_stop_at_import_with_the_list(self):
        self.world(extra={SKILLS_SRC + "/using-foo-provider/references/data/old.json": "stale\n"})
        result = self.bump()
        self.assert_stopped(result, "import", "ORPHAN  using-foo-provider/references/data/old.json")
        self.assertEqual(self.gh_calls("create"), [])
        self.assertEqual(self.sh("git", "--git-dir", self.origin, "branch", "--list", "loop-engine-*"), "")
        self.assert_nothing_applied()
        self.assertEqual(len(self.sh("git", "-C", self.checkout, "worktree", "list").splitlines()), 1)

    def test_d2_red_checks_stop_and_a_rerun_resumes_the_open_pr(self):
        self.world()
        self.state["checks"] = [[{"name": "tests", "bucket": "pass"}, {"name": "mise-tests", "bucket": "fail"}]]
        self.save()
        result = self.bump()
        self.assert_stopped(result, "checks", "red checks: mise-tests (fail); it is left open at https://example.test/pull/100")
        self.assertEqual(self.gh_calls("merge"), [])
        self.assert_nothing_applied()
        self.load()
        self.assertIsNotNone(self.record("dotfiles#100"))  # publish wrote it before the checks ran
        (self.dir / "traces/emitted/review/dotfiles#100/pr-record.md").unlink()  # a PR made before this script wrote records
        self.state["checks"] = [[{"name": "tests", "bucket": "pass"}, {"name": "mise-tests", "bucket": "pass"}]]
        self.save()
        again = self.bump()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("resuming PR #100 (OPEN)", again.stdout)
        # The gates step wrote the missing record and said so in its log line.
        self.assertIsNotNone(self.record("dotfiles#100"))
        gates = [line for line in self.log_lines() if line["step"] == "gates"][-1]
        self.assertTrue(gates["detail"].endswith("passed (the agent record was missing; wrote it)"), gates["detail"])
        self.assertEqual(len(self.gh_calls("create")), 1)
        self.assertEqual(self.live(".config/mise/config.toml"), 'gh = "latest"\n' + pins("1.0.0"))

    def test_d2_a_change_outside_the_pr_under_the_skills_tree_stops_before_apply(self):
        self.world()
        (self.home / SKILLS_DEST / "my-own-skill/SKILL.md").write_text("edited live\n")
        result = self.bump()
        self.assert_stopped(result, "drift", "changes the PR did not make: %s" % (self.home / SKILLS_DEST / "my-own-skill/SKILL.md"))
        self.assertIn("nothing was applied", result.stderr)
        self.assertEqual(len(self.gh_calls("merge")), 1)
        self.assert_nothing_applied()
        self.assertEqual(self.live(SKILLS_DEST + "/my-own-skill/SKILL.md"), "edited live\n")

    def test_d2_drift_on_personal_stops_before_any_configured_hook_runs(self):
        self.world()
        marker = self.hook()
        (self.home / SKILLS_DEST / "my-own-skill/SKILL.md").write_text("edited live\n")
        result = self.bump()
        self.assert_stopped(result, "drift", "changes the PR did not make")
        self.assertFalse(marker.exists(), "a configured chezmoi hook ran before the drift stop")
        self.assert_nothing_applied()

    def test_d2_a_live_edit_to_a_pr_target_stops_before_apply(self):
        self.world()
        config = self.home / ".config/mise/config.toml"
        config.write_text(config.read_text() + "# local\n")
        result = self.bump()
        self.assert_stopped(result, "drift", "neither the pre-PR nor the PR content: %s" % config)
        self.assertTrue(config.read_text().endswith("# local\n"))
        self.assertEqual(self.live(SKILLS_DEST + "/using-foo-provider/SKILL.md"), "foo skill v0\n")

    def refused(self, profile):
        self.world(profile=profile)
        marker = self.hook()
        result = self.bump()
        self.assert_stopped(result, "profile", "profile is '%s'" % profile)
        self.assertFalse(marker.exists(), "a source-state hook ran before the refusal")
        self.assertEqual(self.load().get("calls", []), [])
        self.assertEqual(self.sh("git", "--git-dir", self.origin, "branch", "--list", "loop-engine-*"), "")
        self.assert_nothing_applied()

    def test_d2_the_work_profile_is_refused_before_anything(self):
        self.refused("axon-work-computer")

    def test_d2_the_termux_profile_is_refused_before_anything(self):
        self.refused("termux")

    def test_d2_a_version_already_pinned_does_nothing(self):
        self.world()
        self.assertEqual(self.bump().returncode, 0)
        self.load()
        self.state["prs"] = []  # as if a person had made the bump PR by hand
        self.state["calls"] = []
        self.save()
        installs = len(self.mise_installs())
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("nothing to do: v1.0.0 is already pinned on origin/main and installed here", result.stdout)
        self.assertEqual(self.gh_calls("create"), [])
        self.assertEqual(len(self.mise_installs()), installs)

    def test_d2_already_pinned_but_not_installed_stops_and_says_so(self):
        self.world()
        self.assertEqual(self.bump().returncode, 0)
        self.load()
        self.state["prs"] = []  # as if a person had made the bump PR by hand
        self.save()
        mise = json.loads((self.dir / "mise.json").read_text())
        mise["installed"] = {tool: [v for v in versions if v != "1.0.0"] for tool, versions in mise["installed"].items()}
        (self.dir / "mise.json").write_text(json.dumps(mise))  # the pins are applied, the binaries are not
        result = self.bump()
        self.assert_stopped(result, "apply", "v1.0.0 is already pinned on origin/main")
        self.assertIn("loop-engine (not installed)", result.stderr)
        self.assertNotIn("nothing to do", result.stdout)

    # d3 -------------------------------------------------------------------------------------------

    def ordered_calls(self):
        path = self.dir / "calls.log"
        return path.read_text().splitlines() if path.exists() else []

    def checkout_head(self):
        return self.sh("git", "-C", self.checkout, "rev-parse", "HEAD").strip()

    def origin_head(self):
        return self.sh("git", "--git-dir", self.origin, "rev-parse", "refs/heads/loop-engine-v1.0.0").strip()

    def test_d3_checks_then_both_gates_then_a_merge_that_names_the_head_the_checks_ran_on(self):
        self.world()
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = self.ordered_calls()
        positions = [next(i for i, line in enumerate(lines) if line.startswith(p))
                     for p in ("gh pr checks", "ci-main-status --merge-gate dotfiles --pr 100", "pr-body-check dotfiles 100", "gh pr merge")]
        self.assertEqual(positions, sorted(positions), lines)
        # The record is asked for when the PR is made and again at the gates, before the check that reads it.
        records = [i for i, line in enumerate(lines) if line == "pr-record path dotfiles#100"]
        self.assertEqual(len(records), 2, lines)
        self.assertLess(records[0], positions[0])
        self.assertLess(records[1], positions[2])
        gates = next(line for line in self.log_lines() if line["step"] == "gates")
        self.assertTrue(gates["detail"].endswith(" passed"), gates["detail"])  # gates found the record and wrote nothing
        merge = self.gh_calls("merge")[0]
        self.assertEqual(merge[merge.index("--match-head-commit") + 1], self.origin_head())

    def test_d3_a_red_main_stops_before_the_merge_and_applies_nothing(self):
        self.world()
        before = self.checkout_head()
        self.refuse = "ci-main-status"
        result = self.bump()
        self.assert_stopped(result, "gates", "ci-main-status --merge-gate dotfiles --pr 100 exited 1")
        self.assertIn("ci-main-status: RED on stdout\nrefused by the fake ci-main-status", result.stderr, "stdout and the refusal reason from stderr both show")
        self.assertEqual(self.gh_calls("merge"), [])
        self.assertEqual(self.load()["prs"][0]["state"], "OPEN")
        self.assert_nothing_applied()
        self.assertEqual(self.checkout_head(), before)  # the source checkout did not move

    def test_d3_a_pr_body_that_fails_the_body_check_stops_before_the_merge_and_applies_nothing(self):
        self.world()
        self.refuse = "pr-body-check"
        result = self.bump()
        self.assert_stopped(result, "gates", "pr-body-check dotfiles 100 exited 1")
        self.assertEqual(self.gh_calls("merge"), [])
        self.assertEqual(self.load()["prs"][0]["state"], "OPEN")
        self.assert_nothing_applied()

    def test_d3_the_pr_body_stop_message_shows_the_gates_stdout_and_its_refusal_reason(self):
        self.world()
        self.refuse = "pr-body-check"
        result = self.bump()
        self.assert_stopped(result, "gates", "pr-body-check dotfiles 100 exited 1")
        self.assertIn("pr-body-check: RED on stdout\nrefused by the fake pr-body-check", result.stderr, "stdout and the refusal reason from stderr both show")

    def test_d3_a_head_pushed_after_the_checks_is_not_merged(self):
        self.world()
        self.state["move_head_after_checks"] = True
        self.save()
        result = self.bump()
        self.assert_stopped(result, "merge", "gh pr merge 100 failed (exit 1)")
        merge = self.gh_calls("merge")[0]
        self.assertNotEqual(merge[merge.index("--match-head-commit") + 1], self.origin_head())  # the head the checks saw
        self.assertEqual(self.load()["prs"][0]["state"], "OPEN")
        self.assert_nothing_applied()

    def test_d3_the_source_checkout_moves_to_the_merge_commit(self):
        self.world()
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.checkout_head(), self.load()["prs"][0]["mergeCommit"]["oid"])
        self.assertEqual(self.sh("git", "-C", self.checkout, "status", "--porcelain"), "")
        self.assertIn("source", [line["step"] for line in self.log_lines()])

    def test_d3_a_source_checkout_that_cannot_fast_forward_stops_before_apply_and_a_rerun_applies(self):
        self.world()
        self.sh("git", "-C", self.checkout, "commit", "-q", "--allow-empty", "-m", "local only, not pushed")
        result = self.bump()
        self.assert_stopped(result, "source", "cannot fast-forward the chezmoi source checkout")
        self.assertEqual(self.load()["prs"][0]["state"], "MERGED")  # the merge happened; only the source is behind
        self.assert_nothing_applied()
        self.sh("git", "-C", self.checkout, "reset", "-q", "--hard", "origin/main")  # the fix a person makes
        again = self.bump()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("resuming PR #100 (MERGED)", again.stdout)
        self.assertEqual(self.checkout_head(), self.load()["prs"][0]["mergeCommit"]["oid"])
        self.assertEqual(self.live(".config/mise/config.toml"), 'gh = "latest"\n' + pins("1.0.0"))

    def test_d3_a_source_checkout_not_on_main_stops_before_apply(self):
        self.world()
        self.sh("git", "-C", self.checkout, "checkout", "-q", "-b", "wip")
        result = self.bump()
        self.assert_stopped(result, "source", "is on wip, not main")
        self.assertEqual(self.load()["prs"][0]["state"], "MERGED")
        self.assert_nothing_applied()
        self.assertEqual(self.sh("git", "-C", self.checkout, "branch", "--show-current").strip(), "wip")


class ReleaseBodyTests(unittest.TestCase):
    """The PR body the script writes, on the import output of dotfiles#670 (v0.60.0), whose body failed review on these lines."""

    IMPORT_OUTPUT = (
        "tag v0.60.0 of cartwmic/loop-engine = commit e1e526b93754ec786c47a7f3a7243a6d33328e79; 6 bundles, 29 files, every file matches its tree hash\n"
        "coordinating-loop-engine           +0 added  ~1 changed  -0 orphan  =0 same\n"
        "    change  coordinating-loop-engine/SKILL.md\n"
        "pins: 0.59.0 -> 0.60.0 (dot_config/mise/config.toml)\n"
        "applied to /tmp/loop-engine-bump-lm34crxi/wt\n"
        "next: review git diff; chezmoi --source /tmp/loop-engine-bump-lm34crxi/wt apply --dry-run --verbose ~/.local/share/agent-harness/canonical/skills ~/.config/mise/config.toml,\n"
        "      get approval, apply those targets, then run: import_release_skills.py verify-deployed --source /tmp/loop-engine-bump-lm34crxi/wt\n")
    HEAD = "1cb71c062018f0786f7d858436a47b1b98946d73"

    def setUp(self):
        spec = importlib.util.spec_from_file_location("loop_engine_bump_under_test", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def body(self):
        return self.module.pr_body("v0.60.0", self.IMPORT_OUTPUT, self.HEAD, "2026-11-20")

    def test_the_check_names_each_thing_that_failed_dotfiles_670(self):
        old = ("made by `loop_engine_bump.py v0.60.0` (playbook rule 7c57de5a).\n" + self.IMPORT_OUTPUT)
        problems = body_problems(old)
        self.assertEqual(sorted({p.split(":")[0] for p in problems}), ["a next line", "a rule id", "a scratch path", "no Proven section"])
        clean = "## Proven\ncommit e1e526b93754ec786c47a7f3a7243a6d33328e79 matches\n"
        self.assertEqual(body_problems(clean), [])
        self.assertEqual(body_problems(clean + "the merge runs under the standing grant (rule 7c57de5a)"), ["a rule id: rule 7c57de5a"])

    def test_the_body_has_no_scratch_path_next_line_or_rule_id(self):
        assert_clean_body(self, self.body())

    def test_the_body_keeps_the_bundle_summary_and_drops_the_operator_steps(self):
        body = self.body()
        self.assertIn("coordinating-loop-engine           +0 added  ~1 changed", body)
        self.assertIn("    change  coordinating-loop-engine/SKILL.md", body)
        self.assertNotIn("get approval", body)
        self.assertNotIn("applied to", body)

    def test_the_proven_section_names_what_the_script_checked(self):
        proven = self.body().split("## Proven\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("tag v0.60.0 of cartwmic/loop-engine = commit e1e526b9", proven)
        self.assertIn("every file matches its tree hash", proven)
        self.assertIn("pins: 0.59.0 -> 0.60.0 (dot_config/mise/config.toml)", proven)
        self.assertNotIn("|", proven)
        self.assertIn("2026-11-20", proven)
        self.assertIn(self.HEAD, proven)

    def test_the_body_holds_no_bookkeeping_and_says_both_profiles_get_the_pins(self):
        body = self.body()
        self.assertNotIn("| %d | %s |" % LAST_PRINCIPLE, body)
        self.assertNotIn("Decisions:", body)
        self.assertIn("Both profiles get the pins and skills", body)
        for heading in ("What changes", "Why", "How it was checked", "Proven", "Risk and rollback"):
            self.assertIn("## " + heading, body)


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("git"), "needs chezmoi and git")
class PrTargetsTests(unittest.TestCase):
    """pr_targets on a merge commit with the files of dotfiles#573: the Loop Engine bump and the agent-kit pin in one PR."""

    KIT = ("dot_local/share/agent-kit/package.json", "dot_local/share/agent-kit/package-lock.json")
    LE = ("dot_config/mise/config.toml", SKILLS_SRC + "/using-x/SKILL.md")

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="le-pr-targets-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.repo = self.dir / "repo"
        self.git_env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@example.test", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
        spec = importlib.util.spec_from_file_location("loop_engine_bump_under_test", SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def merge_commit(self, files):
        """A repo whose last commit (the stand-in for the squash merge) writes `files`; returns its sha."""
        env = {**os.environ, **self.git_env, "HOME": str(self.home), "XDG_CONFIG_HOME": str(self.home / ".config")}
        def git(*args):
            return subprocess.run(["git", "-C", str(self.repo), *args], env=env, check=True, capture_output=True, text=True).stdout.strip()
        self.repo.mkdir()
        git("init", "-q", "-b", "main")
        (self.repo / "seed").write_text("seed\n")
        git("add", "-A")
        git("commit", "-q", "-m", "seed")
        for name in files:
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text("changed %s\n" % name)
        git("add", "-A")
        git("commit", "-q", "-m", "the PR")
        self.env = patch.dict(os.environ, env)
        return git("rev-parse", "HEAD")

    def targets(self, files):
        sha = self.merge_commit(files)
        with self.env:
            return self.module.pr_targets(self.repo, sha)

    def test_a_combined_pr_gives_the_loop_engine_files_and_leaves_the_agent_kit_pins_out(self):
        targets = self.targets(self.LE + self.KIT)
        self.assertEqual(sorted(name for name, _, _ in targets.values()), sorted(self.LE))

    def test_a_third_file_in_a_combined_pr_still_stops_and_the_message_names_only_it(self):
        with self.assertRaises(self.module.Stop) as stop:
            self.targets(self.LE + self.KIT + ("dot_unrelated",))
        self.assertEqual(stop.exception.step, "drift")
        self.assertIn("outside the pins and skills: dot_unrelated", str(stop.exception))

    def test_one_agent_kit_pin_file_is_skipped_but_any_other_agent_kit_file_stops(self):
        with self.assertRaises(self.module.Stop) as stop:
            self.targets(self.LE + (self.KIT[0], "dot_local/share/agent-kit/dot_npmrc"))
        self.assertIn("outside the pins and skills: dot_local/share/agent-kit/dot_npmrc", str(stop.exception))

    def test_a_pr_with_only_the_agent_kit_pins_stops(self):
        with self.assertRaises(self.module.Stop) as stop:
            self.targets(self.KIT)
        self.assertIn("no Loop Engine pin or skill", str(stop.exception))


class ReadmeTests(unittest.TestCase):
    def test_d4_readme_names_bump_as_the_one_command(self):
        text = README.read_text()
        self.assertIn("loop_engine_bump.py vX.Y.Z", text)
        self.assertIn("7c57de5a", text)


if __name__ == "__main__":
    unittest.main()
