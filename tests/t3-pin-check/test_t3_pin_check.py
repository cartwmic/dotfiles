"""t3_pin_check.py: the host's T3, dotfiles' [t3Pin] and the budget-steward Dockerfile pin must name the same release.

The real script runs against real git repositories (a bare "origin" and a clone for each of dotfiles and budget-steward), a stand-in `t3`
and `gh` on PATH, a file:// mirror of the release (SHA256SUMS only: no tarball, so a hash cannot come from a download) and a small
in-process Gitea. Run: python3 -m unittest discover -s tests/t3-pin-check
"""
import json
import os
import re
import shutil
import socketserver
import stat
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "dot_local/user_scripts/executable_t3_pin_check.py"
HERE = Path(__file__).resolve().parent
OLD = "0.1.10-nightly.20261116.4800"
NEW = "0.1.10-nightly.20261117.4900"
NEW_X64 = "a" * 63 + "1"
NEW_ARM = "b" * 63 + "2"
GITHUB_URL = "https://github.com/cartwmic/dotfiles.git"
GITEA_URL = "https://gitea.example.test/cartwmic/budget-steward.git"

# `gh pr list` reads gh-prs.json; a successful `gh pr create` adds its PR to that file (so the next run sees it open); the file gh-fail makes create fail.
FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
open(os.environ["FAKE_GH_LOG"], "a").write(" ".join(args) + "\\n")
prs = os.environ["FAKE_GH_PRS"]
if args[:2] == ["pr", "list"]:
    print(open(prs).read() if os.path.exists(prs) else "[]")
elif args[:2] == ["pr", "create"]:
    if os.path.exists(os.path.join(os.path.dirname(prs), "gh-fail")):
        print("gh: HTTP 401: Bad credentials", file=sys.stderr)
        sys.exit(1)
    current = json.load(open(prs)) if os.path.exists(prs) else []
    number = 100 + len(current)
    current.append({"number": number, "url": "https://github.com/cartwmic/dotfiles/pull/%d" % number, "title": args[args.index("--title") + 1],
                    "headRefName": args[args.index("--head") + 1]})
    json.dump(current, open(prs, "w"))
    print("https://github.com/cartwmic/dotfiles/pull/%d" % number)
else:
    print("unexpected gh call: " + " ".join(args), file=sys.stderr)
    sys.exit(9)
"""


def write_exec(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def git(repo, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


class FakeGitea(BaseHTTPRequestHandler):
    open_prs = []
    created = []
    fail_post = False

    def log_message(self, *_):
        pass

    def _send(self, payload):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._send(self.open_prs)

    def do_POST(self):
        if self.fail_post:
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.created.append(body)
        url = "https://gitea.example.test/cartwmic/budget-steward/pulls/%d" % (70 + len(self.created))
        self.open_prs.append({"html_url": url, "title": body["title"], "head": {"ref": body["head"]}})
        self._send({"html_url": url})


class Inbox(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    events = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            Inbox.events.append(json.loads(self.rfile.readline()))
            self.wfile.write(b'{"ok":true,"id":1,"duplicate":false}\n')


class Case(unittest.TestCase):
    host = OLD          # what the stand-in `t3 --version` prints
    dotfiles_pin = OLD
    steward_pin = OLD

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.gitea = HTTPServer(("127.0.0.1", 0), FakeGitea)
        FakeGitea.open_prs, FakeGitea.created, FakeGitea.fail_post = [], [], False
        threading.Thread(target=self.gitea.serve_forever, daemon=True).start()
        self.addCleanup(self.gitea.server_close)
        self.addCleanup(self.gitea.shutdown)
        self.env = {
            "PATH": "%s:%s" % (self.dir / "bin", os.environ["PATH"]),
            "HOME": str(self.dir / "home"), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_TERMINAL_PROMPT": "0",
            "XDG_STATE_HOME": str(self.dir / "state"), "FAKE_GH_LOG": str(self.dir / "gh.log"), "FAKE_GH_PRS": str(self.dir / "gh-prs.json"),
            "T3_PIN_CHECK_STEWARD_API": "http://127.0.0.1:%d" % self.gitea.server_port,
            "T3_PIN_CHECK_RELEASE_BASE": (self.dir / "release").as_uri(),
        }
        self.set_host(self.host)
        write_exec(self.dir / "bin/gh", FAKE_GH)
        (self.dir / "gh.log").write_text("")
        self.dotfiles = self.make_repo("dotfiles", GITHUB_URL, {".chezmoidata.toml": (HERE / "chezmoidata.fixture.toml").read_text()},
                                       lambda t: self.retoml(t, self.dotfiles_pin))
        self.steward = self.make_repo("steward", GITEA_URL, {"Dockerfile": (HERE / "Dockerfile.fixture").read_text()},
                                      lambda t: self.redocker(t, self.steward_pin))
        self.release(NEW, NEW_X64, NEW_ARM)

    def set_host(self, version):
        write_exec(self.dir / "bin/t3", '#!/bin/sh\necho "t3 v%s"\n' % version)

    def release(self, version, x64, arm64):
        out = self.dir / "release" / ("v" + version)
        out.mkdir(parents=True, exist_ok=True)
        (out / "SHA256SUMS").write_text("%s  t3-%s-linux-x64.tar.gz\n%s  t3-%s-linux-arm64.tar.gz\n%s  t3-%s-darwin-arm64.zip\n"
                                        % (x64, version, arm64, version, "c" * 64, version))

    @staticmethod
    def shas(version):
        """The fixture's sha256s: the same for both repos at one version, and never the release's own (so a copy of them is caught)."""
        return ("1" * 64, "2" * 64) if version == OLD else ("d" * 64, "e" * 64)

    def retoml(self, text, version):
        x64, arm = self.shas(version)
        text = re.sub(r'(?m)^(version = ")0\.1\.10-nightly[^"]*"', r'\g<1>%s"' % version, text)
        text = re.sub(r'(?m)^sha256X64 = "[^"]*"', 'sha256X64 = "%s"' % x64, text)
        return re.sub(r'(?m)^sha256Arm64 = "[^"]*"', 'sha256Arm64 = "%s"' % arm, text)

    def redocker(self, text, version):
        x64, arm = self.shas(version)
        text = re.sub(r"t3_version=[^;\s]+;", "t3_version=%s;" % version, text)
        text = re.sub(r"(amd64\) t3_arch=x64; t3_sha256=)[0-9a-f]{64}", r"\g<1>" + x64, text)
        return re.sub(r"(arm64\) t3_arch=arm64; t3_sha256=)[0-9a-f]{64}", r"\g<1>" + arm, text)

    def make_repo(self, name, url, files, transform):
        bare = self.dir / (name + ".git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        clone = self.dir / name
        subprocess.run(["git", "init", "-q", "-b", "main", str(clone)], check=True)
        for key, value in (("user.name", "t"), ("user.email", "t@example.test")):
            git(clone, "config", key, value)
        for rel, text in files.items():
            (clone / rel).write_text(transform(text))
        git(clone, "add", "-A")
        git(clone, "commit", "-q", "-m", "init")
        git(clone, "remote", "add", "origin", url)
        git(clone, "config", "url.%s.insteadOf" % bare, url)  # the raw url stays the github or gitea one; git reaches the bare repo
        git(clone, "push", "-q", "origin", "main")
        git(clone, "fetch", "-q", "origin")
        return clone

    def run_check(self, *flags, state=None):
        args = ["python3", str(SCRIPT), "--dotfiles-source", str(self.dotfiles), "--steward-repo", str(self.steward),
                "--coordinator-state", str(state or self.dir / "no-coordinator"), *flags]
        return subprocess.run(args, capture_output=True, text=True, env=self.env, timeout=120)

    def gh_calls(self):
        return (self.dir / "gh.log").read_text().splitlines()

    def show(self, bare, path, branch="main"):
        return git(self.dir / bare, "show", "%s:%s" % (branch, path))

    def branches(self, bare):
        return git(self.dir / bare, "for-each-ref", "--format=%(refname:short)", "refs/heads").split()


class VersionOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("t3_pin_check", SCRIPT)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def less(self, a, b):
        self.assertEqual(self.mod.compare(a, b), -1, "%s should be older than %s" % (a, b))
        self.assertEqual(self.mod.compare(b, a), 1)

    def test_the_incident_pods_on_the_stable_release_are_older_than_the_host_nightly(self):
        self.less("0.1.9", "0.1.10-nightly.20261116.4800")

    def test_numeric_prerelease_parts_compare_as_numbers_not_text(self):
        self.less("0.1.10-nightly.20261116.999", "0.1.10-nightly.20261116.4800")
        self.less("0.1.10-nightly.20261111.4529", "0.1.10-nightly.20261116.4800")

    def test_a_nightly_is_older_than_the_stable_of_the_same_core(self):
        self.less("0.1.10-nightly.20261116.4800", "0.1.10")

    def test_equal_versions_are_equal(self):
        self.assertEqual(self.mod.compare(OLD, OLD), 0)

    def test_a_malformed_version_is_refused_not_ordered(self):
        with self.assertRaises(self.mod.Stop):
            self.mod.compare("latest", OLD)


class InStep(Case):
    def test_all_three_equal_is_in_step_and_exits_0(self):
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("in step", r.stdout)

    def test_it_reads_origin_main_not_the_working_tree(self):
        # the working tree holds an old pin and a stray edit; origin/main is in step
        (self.dotfiles / ".chezmoidata.toml").write_text("[t3Pin]\nversion = \"0.0.1\"\n")
        (self.steward / "Dockerfile").write_text("junk\n")
        r = self.run_check()
        self.assertEqual(r.returncode, 0, r.stderr)


class Drift(Case):
    host = NEW

    def test_host_newer_than_both_pins_is_drift_and_exits_1(self):
        r = self.run_check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("drift:", r.stdout)
        self.assertIn("dotfiles is behind the host", r.stdout)
        self.assertIn("steward is behind the host", r.stdout)


class PinAhead(Case):
    host = OLD
    steward_pin = NEW

    def test_one_pin_behind_and_one_ahead_is_reported_and_is_never_a_downgrade(self):
        self.dotfiles_pin = OLD
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 1)
        self.assertIn("steward is ahead of the host", r.stdout)
        self.assertIn("no downgrade", r.stdout)
        self.assertEqual(self.gh_calls(), [], "no gh call may follow")
        self.assertEqual(FakeGitea.created, [])
        self.assertEqual(self.branches("steward.git"), ["main"])


class SameVersionDifferentSha(Case):
    def test_same_version_with_different_sha256s_is_drift(self):
        text = (self.steward / "Dockerfile").read_text().replace("1" * 64, "f" * 64)
        (self.steward / "Dockerfile").write_text(text)
        git(self.steward, "commit", "-qam", "different sha")
        git(self.steward, "push", "-q", "origin", "main")
        r = self.run_check()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("different sha256s", r.stdout)


class HostOlderThanPins(Case):
    host = "0.1.9"

    def test_it_reports_and_opens_nothing(self):
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ahead of the host", r.stdout)
        self.assertEqual(self.gh_calls(), [])
        self.assertEqual(FakeGitea.created, [])
        self.assertEqual(self.branches("dotfiles.git"), ["main"])
        self.assertEqual(self.branches("steward.git"), ["main"])


class OpenPrs(Case):
    host = NEW

    def test_it_opens_one_pr_per_repo_with_the_shas_from_SHA256SUMS(self):
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        branch = "t3-pin-" + NEW
        dot = self.show("dotfiles.git", ".chezmoidata.toml", branch)
        self.assertIn('version = "%s"' % NEW, dot)
        self.assertIn('sha256X64 = "%s"' % NEW_X64, dot)
        self.assertIn('sha256Arm64 = "%s"' % NEW_ARM, dot)
        dock = self.show("steward.git", "Dockerfile", branch)
        self.assertIn("t3_version=%s;" % NEW, dock)
        self.assertIn("t3_sha256=%s;;" % NEW_X64, dock)
        self.assertIn("t3_sha256=%s;;" % NEW_ARM, dock)
        # nothing else changed in either file
        for bare, path in (("dotfiles.git", ".chezmoidata.toml"), ("steward.git", "Dockerfile")):
            diff = git(self.dir / bare, "diff", "--numstat", "main", branch, "--", path).split()
            self.assertEqual(diff[:2], ["3", "3"], diff)
        creates = [c for c in self.gh_calls() if c.startswith("pr create")]
        self.assertEqual(len(creates), 1)
        self.assertEqual(len(FakeGitea.created), 1)
        self.assertEqual(FakeGitea.created[0]["head"], branch)
        self.assertIn("https://github.com/cartwmic/dotfiles/pull/100", r.stdout)
        self.assertIn("pulls/71", r.stdout)

    def test_a_dry_run_prints_the_diffs_and_pushes_and_opens_nothing(self):
        r = self.run_check("--open-prs", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("+version = \"%s\"" % NEW, r.stdout)
        self.assertIn("+ t3_version=%s;" % NEW, r.stdout)
        self.assertEqual([c for c in self.gh_calls() if c.startswith("pr create")], [])
        self.assertEqual(FakeGitea.created, [])
        self.assertEqual(self.branches("dotfiles.git"), ["main"])
        self.assertEqual(self.branches("steward.git"), ["main"])

    def test_the_pr_bodies_carry_the_principles_table_and_a_decisions_line(self):
        self.run_check("--open-prs")
        body = FakeGitea.created[0]["body"]
        self.assertEqual(body.count("| pass |") + body.count("| n/a |") + body.count("| fail |"), 16)
        self.assertIn("\nDecisions: ", body)
        self.assertIn("SHA256SUMS", body)

    def test_the_bump_is_never_merged_and_main_does_not_move(self):
        self.run_check("--open-prs")
        self.assertFalse([c for c in self.gh_calls() if c.startswith("pr merge")])
        self.assertEqual(git(self.dir / "dotfiles.git", "log", "--format=%s", "main").split("\n")[0], "init")

    def test_a_dirty_checkout_is_left_alone(self):
        (self.dotfiles / "scratch.txt").write_text("keep me")
        (self.steward / "Dockerfile").write_text("# my local edit\n")
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((self.dotfiles / "scratch.txt").read_text(), "keep me")
        self.assertEqual((self.steward / "Dockerfile").read_text(), "# my local edit\n")
        self.assertEqual(git(self.steward, "for-each-ref", "--format=%(refname:short)", "refs/heads").split(), ["main"])

    def test_a_failing_gitea_call_leaves_no_dotfiles_pr_behind(self):
        FakeGitea.fail_post = True
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertEqual([c for c in self.gh_calls() if c.startswith("pr create")], [], "the Gitea PR goes first, so its failure leaves no GitHub PR that blocks a rerun")

    def test_a_release_with_no_sha256_line_opens_nothing(self):
        (self.dir / "release" / ("v" + NEW) / "SHA256SUMS").write_text("%s  t3-%s-linux-x64.tar.gz\n" % (NEW_X64, NEW))
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 3)
        self.assertEqual([c for c in self.gh_calls() if c.startswith("pr create")], [])
        self.assertEqual(FakeGitea.created, [])

    def test_a_release_whose_SHA256SUMS_cannot_be_read_opens_nothing(self):
        (self.dir / "release" / ("v" + NEW) / "SHA256SUMS").unlink()
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(FakeGitea.created, [])

    def creates(self):
        return [c for c in self.gh_calls() if c.startswith("pr create")]

    def test_an_open_dotfiles_bump_pr_is_done_and_only_the_steward_one_is_opened(self):
        (self.dir / "gh-prs.json").write_text(json.dumps([{"number": 5, "url": "https://github.com/cartwmic/dotfiles/pull/5",
                                                           "title": "t3 pin: " + NEW, "headRefName": "t3-pin-" + NEW}]))
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.creates(), [], "dotfiles already has its PR: no second one")
        self.assertEqual(len(FakeGitea.created), 1)
        self.assertIn("dotfiles: PR open https://github.com/cartwmic/dotfiles/pull/5", r.stdout)
        self.assertIn("steward: opened ", r.stdout)

    def test_an_open_steward_bump_pr_is_done_and_only_the_dotfiles_one_is_opened(self):
        FakeGitea.open_prs = [{"html_url": "https://gitea.example.test/cartwmic/budget-steward/pulls/3", "title": "t3 pin: " + NEW,
                               "head": {"ref": "t3-pin-" + NEW}}]
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(FakeGitea.created, [], "steward already has its PR: no second one")
        self.assertIn("steward: PR open https://gitea.example.test/cartwmic/budget-steward/pulls/3", r.stdout)
        self.assertIn("dotfiles: opened ", r.stdout)

    def test_both_already_open_is_the_refusal_and_opens_nothing(self):
        FakeGitea.open_prs = [{"html_url": "https://gitea.example.test/cartwmic/budget-steward/pulls/3", "title": "t3 pin: " + NEW,
                               "head": {"ref": "t3-pin-" + NEW}}]
        (self.dir / "gh-prs.json").write_text(json.dumps([{"number": 5, "url": "https://github.com/cartwmic/dotfiles/pull/5",
                                                           "title": "t3 pin: " + NEW, "headRefName": "t3-pin-" + NEW}]))
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("steward: PR open", r.stderr)
        self.assertIn("dotfiles: PR open", r.stderr)
        self.assertEqual(self.creates(), [])
        self.assertEqual(FakeGitea.created, [])

    def test_half_state_gitea_opened_then_github_fails_is_finished_by_the_next_run_then_refused(self):
        (self.dir / "gh-fail").write_text("")
        r1 = self.run_check("--open-prs")
        self.assertEqual(r1.returncode, 3, r1.stdout + r1.stderr)
        self.assertEqual(len(FakeGitea.created), 1)
        self.assertIn("steward: opened ", r1.stdout, "what was opened before the failure is still reported")
        (self.dir / "gh-fail").unlink()
        r2 = self.run_check("--open-prs")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn("steward: PR open", r2.stdout)
        self.assertIn("dotfiles: opened ", r2.stdout)
        self.assertEqual(len(FakeGitea.created), 1, "the steward PR is not opened twice")
        r3 = self.run_check("--open-prs")
        self.assertEqual(r3.returncode, 4, r3.stdout + r3.stderr)
        self.assertEqual(len(FakeGitea.created), 1)
        self.assertEqual(len([c for c in self.creates()]), 2, "one failed create and one good one; nothing after")
        self.assertEqual(len(json.loads((self.dir / "gh-prs.json").read_text())), 1)

    def test_half_state_the_other_order_dotfiles_open_steward_missing(self):
        # the dotfiles PR exists (opened by hand, or by an earlier run); the steward one was never made
        (self.dir / "gh-prs.json").write_text(json.dumps([{"number": 5, "url": "https://github.com/cartwmic/dotfiles/pull/5",
                                                           "title": "t3 pin: " + NEW, "headRefName": "t3-pin-" + NEW}]))
        FakeGitea.fail_post = True
        r1 = self.run_check("--open-prs")
        self.assertEqual(r1.returncode, 3, r1.stdout + r1.stderr)
        FakeGitea.fail_post = False
        r2 = self.run_check("--open-prs")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn("dotfiles: PR open", r2.stdout)
        self.assertIn("steward: opened ", r2.stdout)
        r3 = self.run_check("--open-prs")
        self.assertEqual(r3.returncode, 4, r3.stdout + r3.stderr)
        self.assertEqual(len(FakeGitea.created), 1)
        self.assertEqual(self.creates(), [])
        self.assertEqual(len(json.loads((self.dir / "gh-prs.json").read_text())), 1)

    def test_no_duplicates_however_many_times_it_runs(self):
        for _ in range(4):
            self.run_check("--open-prs")
        self.assertEqual(len(self.creates()), 1)
        self.assertEqual(len(FakeGitea.created), 1)

    def test_an_open_pr_for_another_version_does_not_block(self):
        (self.dir / "gh-prs.json").write_text(json.dumps([{"number": 5, "url": "u", "title": "t3 pin: 0.1.9", "headRefName": "t3-pin-0.1.9"}]))
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_only_the_repo_that_needs_a_bump_gets_one(self):
        # dotfiles was already bumped by hand (version and the release's sha256s)
        text = (self.dotfiles / ".chezmoidata.toml").read_text()
        text = text.replace('version = "%s"' % OLD, 'version = "%s"' % NEW)
        text = re.sub(r'(?m)^sha256X64 = "[^"]*"', 'sha256X64 = "%s"' % NEW_X64, text)
        text = re.sub(r'(?m)^sha256Arm64 = "[^"]*"', 'sha256Arm64 = "%s"' % NEW_ARM, text)
        (self.dotfiles / ".chezmoidata.toml").write_text(text)
        git(self.dotfiles, "commit", "-qam", "bump")
        git(self.dotfiles, "push", "-q", "origin", "main")
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual([c for c in self.gh_calls() if c.startswith("pr create")], [])
        self.assertEqual(len(FakeGitea.created), 1)

    def test_a_pin_at_the_host_version_with_a_wrong_sha_is_corrected(self):
        # steward already says NEW but with different sha256s than the release lists: not a downgrade, the release's sha256s win
        text = (self.steward / "Dockerfile").read_text().replace("t3_version=%s;" % OLD, "t3_version=%s;" % NEW)
        (self.steward / "Dockerfile").write_text(text)
        git(self.steward, "commit", "-qam", "wrong sha")
        git(self.steward, "push", "-q", "origin", "main")
        r = self.run_check("--open-prs")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("t3_sha256=%s;;" % NEW_X64, self.show("steward.git", "Dockerfile", "t3-pin-" + NEW))


class NotRead(Case):
    def test_a_missing_checkout_is_not_read_and_not_drift(self):
        shutil.rmtree(self.steward)
        r = self.run_check()
        self.assertEqual(r.returncode, 3)
        self.assertIn("does not exist", r.stderr)

    def test_a_dockerfile_with_no_pin_line_is_not_read(self):
        (self.steward / "Dockerfile").write_text("FROM scratch\n")
        git(self.steward, "commit", "-qam", "no pin")
        git(self.steward, "push", "-q", "origin", "main")
        r = self.run_check()
        self.assertEqual(r.returncode, 3, r.stdout)


class Notify(Case):
    host = NEW

    def test_drift_is_posted_to_the_coordinator_inbox(self):
        sock = self.dir / "inbox.sock"
        Inbox.events = []
        server = Inbox(str(sock), Inbox.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        r = self.run_check("--notify", state=self.dir)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(Inbox.events), 1)
        event = Inbox.events[0]
        self.assertEqual(event["source"], "t3-pin-drift")
        self.assertIn("behind the host", event["payload"]["text"])
        self.assertRegex(event["external_key"], r"^t3-pin-drift:[0-9a-f]{12}:\d{4}-\d\d-\d\d$")

    def test_no_inbox_is_said_and_still_exits_1(self):
        r = self.run_check("--notify")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not posted to the coordinator inbox", r.stdout)

    def test_the_dedupe_key_is_stable_for_the_same_drift_and_day_and_differs_for_another_version(self):
        sock = self.dir / "inbox.sock"
        Inbox.events = []
        server = Inbox(str(sock), Inbox.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.run_check("--notify", state=self.dir)
        self.run_check("--notify", state=self.dir)
        self.set_host("0.1.11-nightly.20261118.5000")
        self.run_check("--notify", state=self.dir)
        keys = [e["external_key"] for e in Inbox.events]
        self.assertEqual(len(keys), 3)
        self.assertEqual(keys[0], keys[1], "the inbox drops the repeat because the key repeats")
        self.assertNotEqual(keys[0], keys[2])

    def test_a_source_that_cannot_be_read_is_posted_too(self):
        sock = self.dir / "inbox.sock"
        Inbox.events = []
        server = Inbox(str(sock), Inbox.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        shutil.rmtree(self.steward)
        r = self.run_check("--notify", state=self.dir)
        self.assertEqual(r.returncode, 3)
        self.assertEqual(len(Inbox.events), 1)
        self.assertIn("could not read", Inbox.events[0]["payload"]["text"])

    def test_in_step_posts_nothing(self):
        self.set_host(OLD)
        sock = self.dir / "inbox.sock"
        Inbox.events = []
        server = Inbox(str(sock), Inbox.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        r = self.run_check("--notify", state=self.dir)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(Inbox.events, [])


class Wiring(unittest.TestCase):
    def test_the_schedules_check_unit_runs_the_check_after_every_run_whatever_its_result(self):
        unit = (ROOT / "dot_config/systemd/user/schedules-check.service.tmpl").read_text()
        line = [l for l in unit.splitlines() if l.startswith("ExecStopPost=")]
        self.assertEqual(len(line), 1, "ExecStopPost runs after a failed schedules check too; ExecStartPost would be skipped")
        self.assertIn("t3_pin_check.py --notify", line[0])
        self.assertNotIn("--open-prs", line[0], "a timer-run check reports; it opens no PR")

    def test_no_new_timer_or_recurring_job_was_added(self):
        units = sorted(p.name for p in (ROOT / "dot_config/systemd/user").glob("*pin*"))
        self.assertEqual(units, [])


if __name__ == "__main__":
    unittest.main()
