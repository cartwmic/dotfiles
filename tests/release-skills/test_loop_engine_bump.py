"""Black-box tests for dot_local/user_scripts/executable_loop_engine_bump.py (playbook rule 7c57de5a in one command).

Each test runs the real script against a scratch world: a bare git origin holding a small chezmoi source, a clone of it
as the source checkout, a scratch HOME (chezmoi's destination, config and state) applied from that source, a scripted
gh that serves a release and the PR (create, checks, squash merge into the bare origin), a fake mise that records
installs. chezmoi, git and apply_harness_config.sh (skills mode) are real. Nothing here reaches GitHub, the real chezmoi
source or the real home directory.

    python3 -m unittest discover -s tests/release-skills -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_import_release_skills import FAKE_GH, GOOD_TREE, Fixture

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/user_scripts/executable_loop_engine_bump.py"
README = ROOT / "dot_local/share/agent-harness/README.md"
SKILLS_SRC = "dot_local/share/agent-harness/canonical/skills"
SKILLS_DEST = ".local/share/agent-harness/canonical/skills"
TOOLS = ("loop-engine", "lean-change", "policy-document", "research")

PR_GH = r'''import subprocess
state.setdefault("calls", []).append(args)
def save():
    json.dump(state, open(os.environ["FAKE_GH_STATE"], "w"))
save()
if args[0] == "pr":
    prs = state.setdefault("prs", [])
    def opt(name):
        return args[args.index(name) + 1]
    def git(*a):
        return subprocess.run(["git", "--git-dir", state["origin"], *a], check=True, capture_output=True, text=True).stdout.strip()
    if args[1] == "list":
        out([{k: p[k] for k in ("number", "state", "url", "mergeCommit")} for p in prs if p["head"] == opt("--head")])
    if args[1] == "create":
        n = 100 + len(prs)
        prs.append({"number": n, "state": "OPEN", "url": "https://example.test/pull/%d" % n, "head": opt("--head"),
                    "title": opt("--title"), "body": opt("--body"), "mergeCommit": None})
        save()
        print("https://example.test/pull/%d" % n)
        sys.exit(0)
    pr = [p for p in prs if p["number"] == int(args[2])][0]
    if args[1] == "checks":
        rounds = state["checks"]
        current = rounds.pop(0) if len(rounds) > 1 else rounds[0]
        save()
        out(current)
    if args[1] == "merge":
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
elif args[0] == "current":
    version = configured(args[1])
    print(version if version in state["installed"].get(args[1], []) else "")
else:
    sys.exit(1)
json.dump(state, open(path, "w"))
'''

def pins(version):
    return "".join('%s = { version = "%s", matching_regex = "^x-", rename_exe = "%s" }\n' % (t, version, t) for t in TOOLS)


@unittest.skipUnless(shutil.which("chezmoi") and shutil.which("git"), "needs chezmoi and git")
class BumpTests(Fixture):
    def setUp(self):
        super().setUp()  # the scripted release v1.0.0 (GOOD_TREE) and a fake gh
        (self.bin / "gh").write_text(FAKE_GH_WITH_PRS)
        (self.bin / "mise").write_text(FAKE_MISE)
        (self.bin / "mise").chmod(0o755)
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
                "TMPDIR": str(self.dir), **self.git_env}

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

    def bump(self, tag="v1.0.0"):
        return subprocess.run([sys.executable, SCRIPT, tag, "--source", self.checkout], env=self.env(),
                              capture_output=True, text=True, timeout=300)

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

    def test_d1_happy_path_one_pr_one_merge_only_the_pr_targets_applied(self):
        self.world()
        result = self.bump()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(len(self.gh_calls("create")), 1)
        self.assertEqual(len(self.gh_calls("merge")), 1)
        pr = self.load()["prs"][0]
        self.assertEqual(pr["head"], "loop-engine-v1.0.0")
        self.assertIn("Profiles: both.", pr["body"])
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
        self.assertIn("installed: loop-engine 1.0.0, lean-change 1.0.0, policy-document 1.0.0, research 1.0.0", result.stdout)
        self.assertIn("+foo skill v1", result.stdout)  # the diff it checked
        lines = self.log_lines()
        self.assertEqual(len({line["id"] for line in lines}), 1)
        self.assertEqual([line["step"] for line in lines],
                         ["profile", "pr", "import", "publish", "checks", "merge", "drift", "apply", "install", "verify"])
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
        self.state["checks"] = [[{"name": "tests", "bucket": "pass"}, {"name": "mise-tests", "bucket": "pass"}]]
        self.save()
        again = self.bump()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("resuming PR #100 (OPEN)", again.stdout)
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
        marker = self.dir / "hook-ran"
        (self.home / ".config/chezmoi/chezmoi.yaml").write_text(
            "data:\n  profile: %s\nhooks:\n  read-source-state:\n    pre:\n      command: touch\n      args: [%s]\n"
            % (profile, json.dumps(str(marker))))
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

class ReadmeTests(unittest.TestCase):
    def test_d4_readme_names_bump_as_the_one_command(self):
        text = README.read_text()
        self.assertIn("loop_engine_bump.py vX.Y.Z", text)
        self.assertIn("7c57de5a", text)


if __name__ == "__main__":
    unittest.main()
