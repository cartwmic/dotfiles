"""Black-box tests for scripts/check-release-pins.py (playbook rule 7c57de5a's check).

Each test runs the real script with a scripted `gh` first on PATH; nothing reaches GitHub. The fake answers the release
endpoints and keeps the pin-lag issues in the JSON state file the test writes, so a test reads back what the script did.
Pull-request mode runs against a real scratch git repository.

    python3 -m unittest tests/release-pins/test_check_release_pins.py
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/check-release-pins.py"
TOOLS = ("loop-engine", "lean-change", "policy-document", "bookends-check")
MISE_PATH = "dot_config/mise/config.toml"
KIT_PATH = "dot_local/share/agent-kit/package.json"

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["FAKE_GH_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]


def fail(message):
    sys.stderr.write(message + "\nsecond line\n")
    sys.exit(1)


def save():
    json.dump(state, open(state_path, "w"))


def option(name):
    return args[args.index(name) + 1]


if args[:1] in (["issue"], ["label"]):
    command = " ".join(args[:2])
    if command in state.get("issue_errors", []):
        fail("HTTP 403: Resource not accessible by integration")
    issues = state.setdefault("issues", [])
    state.setdefault("calls", []).append(command)
    if command == "issue list":
        print(json.dumps([{"number": i["number"], "title": i["title"], "body": i["body"]} for i in issues if i["open"]]))
    elif command == "label create":
        state.setdefault("labels", []).append(args[2])
    elif command == "issue create":
        if "pin-lag" not in state.get("labels", []):
            fail("could not add label: 'pin-lag' not found")
        number = len(issues) + 1
        issues.append({"number": number, "title": option("--title"), "body": option("--body"), "open": True,
                       "label": option("--label")})
        print("https://github.com/cartwmic/dotfiles/issues/%d" % number)
    elif command == "issue edit":
        issue = next(i for i in issues if str(i["number"]) == args[2])
        issue["title"], issue["body"] = option("--title"), option("--body")
    elif command == "issue close":
        next(i for i in issues if str(i["number"]) == args[2])["open"] = False
    save()
    sys.exit(0)
path = args[1] if args[:1] == ["api"] else ""
key = "le" if "loop-engine/releases/latest" in path else "ak" if "packages/npm/agent-kit/versions" in path else None
if key is None:
    sys.stderr.write("fake gh: unexpected " + " ".join(args) + "\n")
    sys.exit(1)
state.setdefault("calls", []).append("release " + key)
save()
if state.get(key + "_silent_exit"):
    sys.exit(state[key + "_silent_exit"])
if state.get(key + "_error"):
    fail(state[key + "_error"])
if key == "le":
    print(state["le_tag"])
else:
    print("\n".join(state["ak_tags"]))
'''


def mise_line(tool, version):
    return '%s = { version = "%s", matching_regex = "^x-", rename_exe = "%s" }' % (tool, version, tool)


def mise(versions):
    """A mise config with the four pins; versions maps tool -> version (default 0.49.0)."""
    return "gh = \"latest\"\n" + "".join(mise_line(t, versions.get(t, "0.49.0")) + "\n" for t in TOOLS)


def kit_package(version):
    return json.dumps({"dependencies": {"@cartwmic/agent-kit": version}})


def all_tools_to(version):
    return dict.fromkeys(TOOLS, version)


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / "bin").mkdir()
        (self.dir / "bin/gh").write_text(FAKE_GH)
        (self.dir / "bin/gh").chmod(0o755)
        # package versions are out of order and include non-release names: the highest X.Y.Z wins, compared as integers
        self.state = {"le_tag": "v0.49.0", "ak_tags": ["0.9.0", "0.10.0", "0.49.0", "0.48.1", "nightly", "0.50.0-rc1"]}

    def run_script(self, *args, cwd=None, **state):
        if (self.dir / "state.json").exists():  # what the fake gh kept from the earlier runs of this test
            self.state.update({k: v for k, v in self.after().items() if k in ("issues", "labels", "calls")})
        self.state.update(state)
        (self.dir / "state.json").write_text(json.dumps(self.state))
        env = {**os.environ, "PATH": "%s:%s" % (self.dir / "bin", os.environ["PATH"]),
               "FAKE_GH_STATE": str(self.dir / "state.json")}
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env,
                              cwd=cwd, timeout=60)

    def after(self):
        """The fake gh's state after the last run: the issues it holds and the calls it saw."""
        return json.loads((self.dir / "state.json").read_text())


class MainModeTests(Fixture):
    """No --base: a push or manual run on main. A lagging pin never fails it; it opens, updates or closes the one issue."""

    def run_check(self, mise_versions=None, kit="0.49.0", **state):
        (self.dir / "mise.toml").write_text(mise(mise_versions or {}))
        (self.dir / "package.json").write_text(kit_package(kit))
        return self.run_script("--mise-config", str(self.dir / "mise.toml"),
                               "--agent-kit-package", str(self.dir / "package.json"), **state)

    def open_issues(self):
        return [i for i in self.after().get("issues", []) if i["open"]]

    def test_all_pins_equal_latest_passes_and_opens_no_issue(self):
        result = self.run_check()
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertTrue(result.stdout.startswith("OK"))
        self.assertIn("agent-kit pin 0.49.0 at latest 0.49.0", result.stdout)
        self.assertEqual(self.after().get("issues", []), [])

    def test_a_lagging_loop_engine_pin_opens_one_labelled_issue_and_passes(self):
        result = self.run_check({"policy-document": "0.48.1"})
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertIn("policy-document pin 0.48.1 lags the latest release 0.49.0", result.stdout)
        (issue,) = self.open_issues()
        self.assertEqual(issue["title"], "Pin lag: policy-document 0.48.1 -> 0.49.0")
        self.assertEqual(issue["label"], "pin-lag")
        self.assertIn("loop_engine_bump.py v0.49.0", issue["body"])
        self.assertIn("pin-lag", self.after()["labels"])

    def test_a_lagging_agent_kit_pin_opens_an_issue_naming_the_bump(self):
        result = self.run_check(kit="0.10.0", ak_tags=["0.49.0", "0.9.0", "0.48.1"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (issue,) = self.open_issues()
        self.assertEqual(issue["title"], "Pin lag: agent-kit 0.10.0 -> 0.49.0")
        self.assertIn("agent_kit_bump.py v0.49.0", issue["body"])

    def test_every_lagging_pin_is_in_the_one_issue(self):
        result = self.run_check(all_tools_to("0.48.1"), kit="0.48.1")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (issue,) = self.open_issues()
        for name in (*TOOLS, "agent-kit"):
            self.assertIn("%s 0.48.1 -> 0.49.0" % name, issue["title"])

    def test_the_issue_text_is_public_text(self):
        self.run_check({"loop-engine": "0.48.1"})
        (issue,) = self.open_issues()
        self.assertNotIn("playbook", issue["title"] + issue["body"])

    def test_agent_kit_latest_is_compared_as_integers(self):
        # string order would call v0.9.0 the highest; the integer order is v0.10.0
        self.run_check(kit="0.9.0", ak_tags=["0.9.0", "0.10.0"])
        self.assertEqual(self.open_issues()[0]["title"], "Pin lag: agent-kit 0.9.0 -> 0.10.0")

    def test_a_second_run_with_the_same_lag_leaves_the_one_issue_alone(self):
        self.run_check({"loop-engine": "0.48.1"})
        result = self.run_check({"loop-engine": "0.48.1"})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(len(self.after()["issues"]), 1)
        self.assertEqual(self.after()["calls"].count("issue create"), 1)
        self.assertNotIn("issue edit", self.after()["calls"])
        self.assertIn("up to date", result.stdout)

    def test_a_changed_lag_updates_the_same_issue(self):
        self.run_check({"loop-engine": "0.48.1"})
        self.run_check({"loop-engine": "0.48.1"}, le_tag="v0.50.0", kit="0.50.0", ak_tags=["0.50.0"])
        (issue,) = self.open_issues()
        self.assertEqual(len(self.after()["issues"]), 1)
        self.assertEqual(issue["number"], 1)
        self.assertIn("loop-engine 0.48.1 -> 0.50.0", issue["title"])
        self.assertIn("lean-change 0.49.0 -> 0.50.0", issue["title"])

    def test_matching_pins_close_the_open_issue(self):
        self.run_check({"loop-engine": "0.48.1"})
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.open_issues(), [])
        self.assertIn("closed pin-lag issue #1", result.stdout)

    def test_a_lag_after_a_closed_issue_opens_a_new_one(self):
        self.run_check({"loop-engine": "0.48.1"})
        self.run_check()
        self.run_check({"loop-engine": "0.48.1"})
        self.assertEqual([i["number"] for i in self.open_issues()], [2])

    def test_loop_engine_unreadable_warns_and_passes_without_touching_issues(self):
        result = self.run_check({"loop-engine": "0.48.1"}, le_error="HTTP 401: Bad credentials")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith("warning: cannot read the latest cartwmic/loop-engine release "
                                                 "(HTTP 401: Bad credentials)"), result.stdout)
        self.assertNotIn("second line", result.stdout + result.stderr)
        self.assertNotIn("OK", result.stdout)
        self.assertNotIn("issue list", self.after().get("calls", []))

    def test_agent_kit_unreadable_warns_naming_the_cause_and_passes(self):
        result = self.run_check(ak_error="HTTP 404: Not Found")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(result.stdout.startswith(
            "warning: cannot read the published versions of the cartwmic/agent-kit package (HTTP 404: Not Found)"),
            result.stdout)
        self.assertIn("packages: read", result.stdout)
        self.assertNotIn("OK", result.stdout)

    def test_a_gh_that_fails_without_a_message_is_named_by_its_exit_code(self):
        result = self.run_check(le_silent_exit=3)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("(gh exited 3)", result.stdout)

    def test_agent_kit_with_no_release_versions_warns(self):
        result = self.run_check(ak_tags=["nightly", "0.50.0-rc1"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("no X.Y.Z versions", result.stdout)

    def test_an_issue_that_cannot_be_written_fails_the_run(self):
        result = self.run_check({"loop-engine": "0.48.1"}, issue_errors=["issue create"])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("cannot open the pin-lag issue (HTTP 403: Resource not accessible by integration)", result.stdout)
        self.assertNotIn("second line", result.stdout + result.stderr)

    def test_an_issue_list_that_cannot_be_read_fails_the_run(self):
        result = self.run_check(issue_errors=["issue list"])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("cannot read the open pin-lag issues", result.stdout)

    def test_a_pin_missing_from_the_config_stops_the_check(self):
        (self.dir / "mise.toml").write_text('gh = "latest"\n')
        (self.dir / "package.json").write_text(kit_package("0.49.0"))
        result = self.run_script("--mise-config", str(self.dir / "mise.toml"),
                                 "--agent-kit-package", str(self.dir / "package.json"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot read the loop-engine pin", result.stderr)


class PullRequestModeTests(Fixture):
    """--base and --head: only the pins the pull request changes are judged, against the merge base."""

    def git(self, *args):
        done = subprocess.run(["git", "-C", str(self.repo), *args], capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def commit(self, files, message="change"):
        for path, text in files.items():
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_text(text)
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def setUp(self):
        super().setUp()
        self.repo = self.dir / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.start = self.commit({MISE_PATH: mise({}), KIT_PATH: kit_package("0.48.1"), "README.md": "one\n"})

    def check(self, base, head, **state):
        return self.run_script("--base", base, "--head", head, cwd=self.repo, **state)

    def branch(self, files, name="pr"):
        self.git("checkout", "-q", "-b", name, self.start)
        return self.commit(files)

    def test_a_pr_that_changes_no_pin_passes_without_looking_up_a_release(self):
        head = self.branch({"README.md": "two\n"})
        result = self.check(self.start, head, le_error="HTTP 500", ak_error="HTTP 500")
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertIn("changes no pin", result.stdout)
        self.assertNotIn("calls", self.after())

    def test_a_pr_that_lags_the_latest_release_but_changes_no_pin_passes(self):
        # main pins 0.49.0 and 0.48.1; the latest releases are newer. The PR did not cause that.
        head = self.branch({"README.md": "two\n"})
        result = self.check(self.start, head, le_tag="v0.60.0", ak_tags=["0.60.0"])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_a_pr_behind_a_bump_on_main_is_not_blamed_for_the_old_pins(self):
        # the PR branched before main bumped the pins; its head still has the old values. Against main's tip they look
        # changed, against the merge base they are not.
        head = self.branch({"README.md": "two\n"})
        self.git("checkout", "-q", "main")
        tip = self.commit({MISE_PATH: mise(all_tools_to("0.50.0")), KIT_PATH: kit_package("0.50.0")}, "bump")
        result = self.check(tip, head, le_tag="v0.50.0", ak_tags=["0.50.0"])
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertIn("changes no pin", result.stdout)

    def test_a_bump_to_the_latest_release_passes(self):
        head = self.branch({MISE_PATH: mise(all_tools_to("0.50.0")), KIT_PATH: kit_package("0.50.0")})
        result = self.check(self.start, head, le_tag="v0.50.0", ak_tags=["0.49.0", "0.50.0"])
        self.assertEqual((result.returncode, result.stderr), (0, ""), result.stdout)
        self.assertIn("sets the loop-engine pin to 0.50.0, the latest release", result.stdout)
        self.assertIn("sets the agent-kit pin to 0.50.0, the latest release", result.stdout)

    def test_a_loop_engine_pin_set_to_an_older_version_fails(self):
        head = self.branch({MISE_PATH: mise({"lean-change": "0.40.0"})})
        result = self.check(self.start, head, le_tag="v0.49.0")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            "lean-change pin set to 0.40.0 by this PR, but the latest release is 0.49.0; "
            "bump it with loop_engine_bump.py v0.49.0"])

    def test_an_agent_kit_pin_set_to_an_older_version_fails(self):
        head = self.branch({KIT_PATH: kit_package("0.30.0")})
        result = self.check(self.start, head, ak_tags=["0.48.1", "0.49.0"])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("agent-kit pin set to 0.30.0 by this PR, but the latest release is 0.49.0", result.stdout)

    def test_a_pin_set_to_a_version_newer_than_the_latest_release_fails(self):
        head = self.branch({KIT_PATH: kit_package("0.99.0")})
        result = self.check(self.start, head, ak_tags=["0.49.0"])
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_one_bad_pin_fails_the_run_though_another_is_right(self):
        head = self.branch({MISE_PATH: mise({"loop-engine": "0.49.0", "lean-change": "0.30.0"}),
                            KIT_PATH: kit_package("0.49.0")})
        result = self.check(self.start, head, ak_tags=["0.49.0"], le_tag="v0.49.0")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("lean-change pin set to 0.30.0", result.stdout)
        self.assertIn("sets the agent-kit pin to 0.49.0, the latest release", result.stdout)

    def test_only_the_changed_pins_are_looked_up(self):
        head = self.branch({KIT_PATH: kit_package("0.49.0")})
        result = self.check(self.start, head, ak_tags=["0.49.0"], le_error="HTTP 500")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.after()["calls"], ["release ak"])

    def test_a_changed_pin_whose_release_cannot_be_read_fails_naming_the_cause(self):
        head = self.branch({MISE_PATH: mise({"loop-engine": "0.50.0"})})
        result = self.check(self.start, head, le_error="HTTP 401: Bad credentials")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("cannot read the latest loop-engine release (HTTP 401: Bad credentials)", result.stdout)
        self.assertNotIn("second line", result.stdout + result.stderr)

    def test_a_pr_that_deletes_the_agent_kit_pin_file_changes_no_pin(self):
        self.git("checkout", "-q", "-b", "pr", self.start)
        self.git("rm", "-q", KIT_PATH)
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "drop")
        result = self.check(self.start, self.git("rev-parse", "HEAD"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_commits_git_cannot_find_stop_the_check(self):
        result = self.check(self.start, "0" * 40)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("cannot find the merge base", result.stdout)

    def test_base_without_head_is_refused(self):
        result = self.run_script("--base", self.start, cwd=self.repo)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("--base and --head go together", result.stderr)

    def test_the_pr_check_never_touches_issues(self):
        head = self.branch({MISE_PATH: mise({"loop-engine": "0.30.0"})})
        self.check(self.start, head, le_tag="v0.49.0")
        self.assertEqual(self.after().get("issues", []), [])


if __name__ == "__main__":
    unittest.main()
