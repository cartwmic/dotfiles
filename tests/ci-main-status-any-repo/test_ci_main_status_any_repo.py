"""ci-main-status's required-checks gate for any GitHub repo (OWNER/REPO), against a fake `gh`.

Each test states one row of the required_checks decision table (dotfiles #601, round-8 design): the exact set of
status checks GitHub requires to merge into a branch, from the branch response (B) union the branch's active
ruleset rules (R), failing closed whenever the full set cannot be known. The fake gh serves the JSON shapes the
comparer observed live on public repos as a non-admin. Any call to a classic /protection endpoint fails the test:
the gate must read protection from the branch itself.
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "dot_local/bin/executable_ci-main-status"

SHA = "a" * 40   # a default-branch tip
HEAD = "b" * 40   # a PR head

GH_FAKE = textwrap.dedent('''\
    #!/usr/bin/env python3
    import json, os, sys
    from urllib.parse import unquote
    fixture = json.load(open(os.environ["FAKE_GH_FIXTURE"]))
    args = sys.argv[1:]
    with open(os.environ["FAKE_GH_LOG"], "a") as log:
        log.write(" ".join(args) + "\\n")
    def fail(msg, code=1):
        print(msg, file=sys.stderr); sys.exit(code)
    if "/protection" in " ".join(args):   # a classic /protection endpoint: the gate must never call one
        fail("PROTECTION-ENDPOINT-CALLED: " + " ".join(args), code=42)
    if args[:2] == ["pr", "view"]:
        repo = args[args.index("-R") + 1]
        pull = fixture["repos"][repo].get("pulls", {}).get(args[2])
        if pull is None:
            fail("HTTP 404: no PR fixture " + args[2])
        print(json.dumps({"headRefOid": pull["head"]["sha"], "baseRefName": pull["base"]["ref"]}))
    elif args[:2] == ["pr", "checks"]:
        repo = args[args.index("-R") + 1]
        spec = fixture["repos"][repo].get("pr_checks", {}).get(args[2])
        if spec is None:
            fail("HTTP 404: no pr checks fixture " + args[2])
        code = spec.get("exit", 0)
        if code == 1:   # gh pr checks: none reported -- an error on stderr, an empty stdout
            fail(spec.get("error", "no checks reported"))
        if code not in (0, 1, 8):
            print(spec.get("error", "HTTP 500: fake pr checks failure"), file=sys.stderr); sys.exit(code)
        print(json.dumps(spec.get("rows", [])))
        sys.exit(code)   # 0, or 8 with some checks pending (the rows still come)
    elif args[0] == "api":
        path = args[1]
        rest = path[len("repos/"):] if path.startswith("repos/") else path
        repo = "/".join(rest.split("/")[:2])
        r = fixture["repos"].get(repo)
        if r is None:
            fail("HTTP 404: no repo fixture " + repo)
        if "/rules/branches/" in rest:
            name = unquote(rest.split("/rules/branches/")[1].split("?")[0])
            spec = r.get("rules", {}).get(name)
            if spec is None:
                fail("HTTP 404: no branch-rules fixture " + name)
            if isinstance(spec, str):
                fail(spec)
            pages = spec.get("pages") if isinstance(spec, dict) else None
            if pages is None:
                print(json.dumps(spec))
            elif any(isinstance(p, str) for p in pages):
                # a page fails: gh --paginate exits non-zero and the gate reads none of it
                fail(next(p for p in pages if isinstance(p, str)))
            else:
                print(json.dumps([row for p in pages for row in p]))   # gh --paginate merges the pages
        elif "/branches/" in rest:
            name = unquote(rest.split("/branches/")[1].split("?")[0])
            b = r.get("branches", {}).get(name)
            if b is None:
                fail("HTTP 404: no branch fixture " + name)   # a branch that does not exist
            if isinstance(b, str):
                fail(b)   # a named failure, such as a rate limit
            print(json.dumps(b))
        elif "/pulls/" in rest:
            n = rest.split("/pulls/")[1].split("?")[0].split("/")[0]
            pull = r.get("pulls", {}).get(n)
            if pull is None:
                fail("HTTP 404: no pulls fixture " + n)
            if isinstance(pull, str):
                fail(pull)
            print(json.dumps(pull))
        elif "/commits/" in rest and "/check-runs" in rest:
            sha = rest.split("/commits/")[1].split("/")[0]
            rows = r.get("check_runs", {}).get(sha, [])
            print(json.dumps({"total_count": len(rows), "check_runs": rows}))
        elif "/commits/" in rest and rest.split("/commits/")[1].split("?")[0].endswith("/status"):
            sha = rest.split("/commits/")[1].split("/status")[0]
            rows = r.get("statuses", {}).get(sha, [])
            print(json.dumps({"state": "pending", "total_count": len(rows), "statuses": rows}))
        else:
            print(json.dumps({"default_branch": r.get("default_branch", "main")}))
    else:
        fail("fake gh: unhandled " + " ".join(args))
''')


def classic(checks=None, contexts=None, enabled=True, sha=SHA, protected=True):
    """The GET repos/{o}/{r}/branches/{b} response for a classically protected branch: protected, protection with
    enabled and required_status_checks (checks as GitHub carries them, contexts alongside), and the tip."""
    prot = {"enabled": enabled}
    if checks is not None or contexts is not None:
        prot["required_status_checks"] = {"checks": [{"context": c, "app_id": 1} for c in (checks or [])],
                                          "contexts": list(contexts or [])}
    return {"protected": protected, "protection": prot, "commit": {"sha": sha}}


def rule(rtype, contexts=()):
    """One branch rule. A required_status_checks rule carries parameters.required_status_checks; any other type
    carries a plausible parameters the gate never reads past its type."""
    if rtype == "required_status_checks":
        return {"type": rtype, "parameters": {"required_status_checks": [{"context": c} for c in contexts]}}
    return {"type": rtype, "parameters": {}}


def check_row(name, conclusion="success", status="completed", rid=1):
    return {"id": rid, "name": name, "status": status,
            "conclusion": conclusion if status == "completed" else None,
            "started_at": "2026-11-18T10:00:00Z",
            "completed_at": "2026-11-18T10:01:00Z" if status == "completed" else None}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        bindir = t / "bin"
        bindir.mkdir()
        (bindir / "gh").write_text(GH_FAKE)
        (bindir / "gh").chmod(0o755)
        self.log = t / "gh.log"
        self.fixture_path = t / "fixture.json"
        self.repos = {}   # {name: {default_branch, branches, rules, pulls, pr_checks, check_runs, statuses}}
        self.env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
                    "FAKE_GH_LOG": str(self.log), "FAKE_GH_FIXTURE": str(self.fixture_path)}
        for name in ("GH_CALLER", "GH_URGENT"):
            self.env.pop(name, None)

    def tearDown(self):
        self.tmp.cleanup()

    def status(self, *args):
        self.fixture_path.write_text(json.dumps({"repos": self.repos}))
        r = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=self.env, timeout=120)
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        called = [c for c in calls if "/protection" in c]   # a classic /protection endpoint: never called
        self.assertEqual(called, [], "the gate called a classic /protection endpoint: " + ", ".join(called))
        return r.returncode, r.stdout + r.stderr

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []


class Gate(Fixture):
    """The required_checks decision table, end to end through the CLI."""

    def test_cli_cli_trunk_classic_plus_an_allow_rule(self):
        # cli/cli trunk, the real shape: classic protection enabled with 3 checks, plus one ruleset
        # copilot_code_review rule (ALLOW: it gates on reviews, not checks) -> those 3, no ERROR.
        names = ["build (ubuntu-latest)", "build (macos-latest)", "docs"]
        self.repos["cli/cli"] = {
            "default_branch": "trunk",
            "branches": {"trunk": classic(checks=names, contexts=names)},
            "rules": {"trunk": [rule("copilot_code_review")]},
            "check_runs": {SHA: [check_row(n, rid=i + 1) for i, n in enumerate(names)]},
        }
        rc, out = self.status("cli/cli")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  all 3 required checks passed on trunk tip " + SHA[:7], out)

    def test_github_docs_license_scanning_rule_fails_closed(self):
        # github/docs main, the real shape: protection.enabled false, 39 ruleset checks, and an org
        # license_compliance_scanning rule. The gate cannot map that rule to check runs: ERROR row 5a, never GREEN.
        checks_39 = [f"docs-check-{i:02d}" for i in range(1, 40)]
        self.repos["github/docs"] = {
            "branches": {"main": classic(enabled=False)},
            "rules": {"main": [rule("required_status_checks", checks_39), rule("license_compliance_scanning")]},
        }
        rc, out = self.status("github/docs")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)
        self.assertIn("license_compliance_scanning", out)
        self.assertIn("merge box", out)
        self.assertNotIn("GREEN", out)

    def test_ruleset_checks_with_protection_disabled_are_the_set(self):
        # Constructed: enabled false, a ruleset with 39 required_status_checks and only ALLOW-type rules otherwise
        # -> those 39.
        checks_39 = [f"rule-check-{i:02d}" for i in range(1, 40)]
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(enabled=False)},
            "rules": {"main": [rule("required_status_checks", checks_39), rule("pull_request"), rule("non_fast_forward")]},
            "check_runs": {SHA: [check_row(n, rid=i + 1) for i, n in enumerate(checks_39)]},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  all 39 required checks passed on main tip " + SHA[:7], out)

    def test_a_classic_only_check_is_in_the_union(self):
        # A constructed "both": protection requires "classic-only", the rulesets require "ruleset". A gate that
        # kept only the rulesets' set would print GREEN while a required check never ran.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=["classic-only"], contexts=["classic-only"])},
            "rules": {"main": [rule("required_status_checks", ["ruleset"]), rule("merge_queue")]},
            "check_runs": {SHA: [check_row("ruleset")]},   # classic-only never ran
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("GREEN", out)
        self.assertIn("classic-only (not reported)", out)

    def test_django_protected_with_no_checks_anywhere_is_error(self):
        # django/django main, the real shape: protected, enabled, contexts empty, rules []. Nothing is required,
        # so nothing could be proved: ERROR row 9, never GREEN.
        self.repos["django/django"] = {
            "branches": {"main": classic(checks=[], contexts=[])},
            "rules": {"main": []},
        }
        rc, out = self.status("django/django")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)
        self.assertIn("protected, but no required checks in protection or rulesets", out)
        self.assertNotIn("GREEN", out)

    def test_octocat_unprotected_with_no_rules_requires_nothing(self):
        # octocat/Hello-World: protected false, rules []. Row 8: the empty set is proven -- and the gate still
        # exits 1, because nothing to verify is not a pass.
        self.repos["octocat/Hello-World"] = {
            "branches": {"main": {"protected": False, "commit": {"sha": SHA}}},
            "rules": {"main": []},
        }
        rc, out = self.status("octocat/Hello-World")
        self.assertEqual(rc, 1, out)
        self.assertIn("no required checks readable on main", out)
        self.assertIn("failing closed", out)

    def test_enabled_with_no_required_status_checks_object_is_error(self):
        # protection.enabled true with required_status_checks absent: a missing field is malformed here, never a
        # silent default to no checks.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": {"protected": True, "protection": {"enabled": True}, "commit": {"sha": SHA}}},
            "rules": {"main": []},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)
        self.assertNotIn("GREEN", out)

    def test_enabled_with_neither_checks_nor_contexts_is_error(self):
        # n1: GitHub's schema requires both fields, so an enabled required_status_checks with neither is a broken
        # contract; C = {} would be a silent default. ERROR.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": {"protected": True,
                                  "protection": {"enabled": True, "required_status_checks": {}},
                                  "commit": {"sha": SHA}}},
            "rules": {"main": []},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)
        self.assertNotIn("GREEN", out)

    def test_a_rate_limit_on_the_branch_read_is_error(self):
        self.repos["example-org/example-repo"] = {
            "branches": {"main": "HTTP 403: API rate limit exceeded"},
            "rules": {"main": []},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 1, out)
        self.assertIn("rate limit", out)

    def test_a_rate_limit_on_the_rules_read_is_error(self):
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=["tests"], contexts=["tests"])},
            "rules": {"main": "HTTP 403: API rate limit exceeded"},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 1, out)
        self.assertIn("rate limit", out)

    def test_a_failure_on_the_rules_second_page_is_error(self):
        # R's first page reads, the second fails: gh --paginate exits non-zero, and any page failing is ERROR.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=["tests"], contexts=["tests"])},
            "rules": {"main": {"pages": [[rule("required_status_checks", ["tests"])],
                                         "HTTP 500: second page failed"]}},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)
        self.assertNotIn("GREEN", out)

    def test_a_ruleset_rule_with_null_parameters_is_error(self):
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(enabled=False)},
            "rules": {"main": [{"type": "required_status_checks", "parameters": None}]},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)
        self.assertNotIn("GREEN", out)

    def test_pr_uses_the_base_branch(self):
        # The PR case on cli/cli: pulls/7 -> base.ref trunk, then rows 1-9 on trunk -> those 3, verified on the
        # PR head.
        names = ["build", "docs", "lint"]
        self.repos["cli/cli"] = {
            "default_branch": "trunk",
            "branches": {"trunk": classic(checks=names, contexts=names)},
            "rules": {"trunk": [rule("copilot_code_review")]},
            "pulls": {"7": {"base": {"ref": "trunk"}, "head": {"sha": HEAD}}},
            "pr_checks": {"7": {"rows": [{"name": n} for n in names]}},
            "check_runs": {HEAD: [check_row(n, rid=i + 1) for i, n in enumerate(names)]},
        }
        rc, out = self.status("--merge-gate", "cli/cli", "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  all 3 required checks passed on PR #7 head " + HEAD[:7], out)

    def test_a_branch_that_does_not_exist_is_error(self):
        self.repos["example-org/example-repo"] = {"branches": {}, "rules": {}}
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 1, out)
        self.assertIn("HTTP 404", out)

    def test_grafana_workflows_rule_fails_closed(self):
        # grafana/grafana main, the real shape: required workflows from enterprise and org rulesets. The gate
        # cannot map a required workflow to check runs: ERROR row 5a, never GREEN.
        self.repos["grafana/grafana"] = {
            "branches": {"main": classic(enabled=False)},
            "rules": {"main": [rule("workflows"), rule("required_status_checks", ["lint"])]},
        }
        rc, out = self.status("grafana/grafana")
        self.assertEqual(rc, 1, out)
        self.assertIn("workflows", out)
        self.assertIn("merge box", out)
        self.assertNotIn("GREEN", out)

    def test_a_code_coverage_rule_fails_closed(self):
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(enabled=False)},
            "rules": {"main": [rule("code_coverage")]},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 1, out)
        self.assertIn("code_coverage", out)
        self.assertNotIn("GREEN", out)

    def test_an_unknown_future_rule_type_fails_closed(self):
        # A type GitHub has not invented yet: never GREEN, whatever else the response holds.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=["tests"], contexts=["tests"])},
            "rules": {"main": [rule("required_status_checks", ["tests"]), rule("future_gate")]},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 1, out)
        self.assertIn("future_gate", out)
        self.assertNotIn("GREEN", out)

    def test_allow_listed_rules_do_not_fail_closed(self):
        # Rules of ALLOW types only (here pull_request, non_fast_forward) plus required_status_checks: no ERROR,
        # the checks counted.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(enabled=False)},
            "rules": {"main": [rule("pull_request"), rule("non_fast_forward"),
                               rule("required_status_checks", ["tests", "lint"])]},
            "check_runs": {SHA: [check_row("tests"), check_row("lint", rid=2)]},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  all 2 required checks passed on main tip " + SHA[:7], out)

    def test_electron_workflows_rule_fails_closed(self):
        # electron/electron main also carries a workflows rule: ERROR row 5a. (The union itself is covered by the
        # constructed "both" test, without workflows.)
        self.repos["electron/electron"] = {
            "branches": {"main": classic(enabled=False)},
            "rules": {"main": [rule("workflows")]},
        }
        rc, out = self.status("electron/electron")
        self.assertEqual(rc, 1, out)
        self.assertIn("workflows", out)
        self.assertNotIn("GREEN", out)

    def test_contexts_count_when_checks_is_empty(self):
        # Classic checks empty but contexts listed: the contexts are the set (here a commit status carries it).
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=[], contexts=["status-only"])},
            "rules": {"main": []},
            "statuses": {SHA: [{"context": "status-only", "state": "success"}]},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  all 1 required checks passed on main tip " + SHA[:7], out)

    def test_a_branch_name_with_a_slash_is_url_encoded(self):
        self.repos["example-org/example-repo"] = {
            "default_branch": "release/1.2",
            "branches": {"release/1.2": classic(checks=["tests"], contexts=["tests"])},
            "rules": {"release/1.2": [rule("required_status_checks", ["ruleset-check"])]},
            "check_runs": {SHA: [check_row("tests"), check_row("ruleset-check", rid=2)]},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  all 2 required checks passed on release/1.2 tip " + SHA[:7], out)
        calls = self.calls()
        self.assertTrue(any("branches/release%2F1.2" in c for c in calls), calls)
        self.assertTrue(any("rules/branches/release%2F1.2" in c for c in calls), calls)

    def test_the_classic_protection_endpoints_are_never_called(self):
        # status() fails any test whose run called one; this makes the guard explicit on a full protected read.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=["tests"], contexts=["tests"])},
            "rules": {"main": []},
            "check_runs": {SHA: [check_row("tests")]},
        }
        rc, out = self.status("example-org/example-repo")
        self.assertEqual(rc, 0, out)
        self.assertFalse(any("/protection" in c for c in self.calls()))

    def test_rows_8_and_9_exit_1_through_the_merge_gate(self):
        # Row 8: unprotected, nothing required -- the gate still refuses (nothing to verify is not a pass).
        self.repos["octocat/Hello-World"] = {
            "branches": {"main": {"protected": False, "commit": {"sha": SHA}}},
            "rules": {"main": []},
        }
        rc, out = self.status("--merge-gate", "octocat/Hello-World")
        self.assertEqual(rc, 1, out)
        self.assertIn("no required checks readable on main", out)
        # Row 9: protected, enabled, no checks in either source -- its own message.
        self.repos["django/django"] = {
            "branches": {"main": classic(checks=[], contexts=[])},
            "rules": {"main": []},
        }
        rc, out = self.status("--merge-gate", "django/django")
        self.assertEqual(rc, 1, out)
        self.assertIn("protected, but no required checks in protection or rulesets", out)

    def test_malformed_branch_responses_fail_closed(self):
        # Row 3: protected true with protection missing, enabled missing or not a bool, or contexts not a list is
        # malformed -> ERROR, never C = {} and never the contexts read anyway.
        cases = {
            "protection missing": {"protected": True, "commit": {"sha": SHA}},
            "enabled missing": {"protected": True, "commit": {"sha": SHA},
                                "protection": {"required_status_checks": {"checks": [], "contexts": ["tests"]}}},
            "enabled not a bool": {"protected": True, "commit": {"sha": SHA},
                                   "protection": {"enabled": "yes",
                                                  "required_status_checks": {"checks": [], "contexts": ["tests"]}}},
            "contexts not a list": {"protected": True, "commit": {"sha": SHA},
                                    "protection": {"enabled": True,
                                                   "required_status_checks": {"checks": [], "contexts": "tests"}}},
            "protected not a bool": {"protected": "yes", "commit": {"sha": SHA}},
        }
        for label, b in cases.items():
            with self.subTest(label):
                self.repos = {"example-org/example-repo": {"branches": {"main": b}, "rules": {"main": []}}}
                rc, out = self.status("example-org/example-repo")
                self.assertEqual(rc, 1, out + f" ({label})")
                self.assertIn("ERROR", out)
                self.assertNotIn("GREEN", out)

    def test_pr_a_required_check_that_never_started_is_not_green(self):
        # The computed set is {a, b}; the PR rollup (gh pr checks --required) shows only a, passing, because b
        # never started. The gate verifies the computed set on the head, not the rollup: b is missing, so the
        # gate is not GREEN and its message names b.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=["a", "b"], contexts=["a", "b"])},
            "rules": {"main": []},
            "pulls": {"7": {"base": {"ref": "main"}, "head": {"sha": HEAD}}},
            "pr_checks": {"7": {"rows": [{"name": "a"}]}},
            "check_runs": {HEAD: [check_row("a")]},
        }
        rc, out = self.status("--merge-gate", "example-org/example-repo", "--pr", "7")
        self.assertNotEqual(rc, 0, out)
        self.assertNotIn("GREEN", out)
        self.assertIn("b (not reported)", out)

    def test_pr_a_required_check_skipped_by_its_job_condition_passes(self):
        # Classic protection requires six checks. The PR touches none of the files one job builds, so that job is
        # skipped by its condition and its check run concludes skipped. GitHub's merge box passes a skipped
        # required check, so the gate must too: GREEN, not RED. Unrequired skipped runs on the head are ignored.
        required = ["lint", "unit tests", "integration tests", "validate", "pr-title", "ui build"]
        runs = [check_row(n, rid=i + 10) for i, n in enumerate(required[:-1])]
        runs += [check_row("ui build", "skipped", rid=20), check_row("path filter", rid=21),
                 check_row("extra tests", "skipped", rid=22), check_row("pr-title", rid=23)]
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(contexts=required)},
            "rules": {"main": []},
            "pulls": {"190": {"base": {"ref": "main"}, "head": {"sha": HEAD}}},
            "pr_checks": {"190": {"rows": [{"name": n} for n in required]}},
            "check_runs": {HEAD: runs},
        }
        rc, out = self.status("--merge-gate", "example-org/example-repo", "--pr", "190")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  all 6 required checks passed on PR #190 head " + HEAD[:7], out)

    def test_pr_a_rollup_name_the_computed_set_lacks_is_error(self):
        # gh pr checks --required lists c, which the computed set for the base lacks: an under-report -> ERROR.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=["a"], contexts=["a"])},
            "rules": {"main": []},
            "pulls": {"7": {"base": {"ref": "main"}, "head": {"sha": HEAD}}},
            "pr_checks": {"7": {"rows": [{"name": "a"}, {"name": "c"}]}},
            "check_runs": {HEAD: [check_row("a"), check_row("c", rid=2)]},
        }
        rc, out = self.status("--merge-gate", "example-org/example-repo", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)
        self.assertIn("c", out)

    def test_pr_checks_pending_exit_does_not_end_the_check(self):
        # gh pr checks --required exit 8 (some pending): the computed set is still verified on the head.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=["a"], contexts=["a"])},
            "rules": {"main": []},
            "pulls": {"7": {"base": {"ref": "main"}, "head": {"sha": HEAD}}},
            "pr_checks": {"7": {"exit": 8, "rows": [{"name": "a", "state": "PENDING"}]}},
            "check_runs": {HEAD: [check_row("a")]},
        }
        rc, out = self.status("--merge-gate", "example-org/example-repo", "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN", out)

    def test_pr_checks_none_reported_exit_does_not_end_the_check(self):
        # gh pr checks --required exit 1 (none reported): the computed set is still verified on the head.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=["a"], contexts=["a"])},
            "rules": {"main": []},
            "pulls": {"7": {"base": {"ref": "main"}, "head": {"sha": HEAD}}},
            "pr_checks": {"7": {"exit": 1}},
            "check_runs": {HEAD: [check_row("a")]},
        }
        rc, out = self.status("--merge-gate", "example-org/example-repo", "--pr", "7")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN", out)

    def test_pr_checks_failing_with_another_exit_is_error(self):
        # n3: gh pr checks --required exiting with anything but 0, 1 or 8 is unreadable: ERROR, never a pass.
        self.repos["example-org/example-repo"] = {
            "branches": {"main": classic(checks=["a"], contexts=["a"])},
            "rules": {"main": []},
            "pulls": {"7": {"base": {"ref": "main"}, "head": {"sha": HEAD}}},
            "pr_checks": {"7": {"exit": 4, "error": "gh: HTTP 500"}},
        }
        rc, out = self.status("--merge-gate", "example-org/example-repo", "--pr", "7")
        self.assertEqual(rc, 1, out)
        self.assertIn("ERROR", out)
        self.assertNotIn("GREEN", out)

    def test_opentelemetry_code_scanning_rule_fails_closed(self):
        # open-telemetry/opentelemetry-java main, the real shape: a code_scanning rule (CodeQL, zizmor) -> ERROR
        # row 5a.
        self.repos["open-telemetry/opentelemetry-java"] = {
            "branches": {"main": classic(enabled=False)},
            "rules": {"main": [{"type": "code_scanning",
                                "parameters": {"code_scanning_tools": [{"tool": "CodeQL", "level": "errors"},
                                                                       {"tool": "zizmor", "level": "errors"}]}}]},
        }
        rc, out = self.status("open-telemetry/opentelemetry-java")
        self.assertEqual(rc, 1, out)
        self.assertIn("code_scanning", out)
        self.assertNotIn("GREEN", out)

    def test_microsoft_typescript_ruleset_checks(self):
        # microsoft/TypeScript main, the real shape: ALLOW types plus the ruleset checks license/cla and required.
        self.repos["microsoft/TypeScript"] = {
            "branches": {"main": classic(enabled=False)},
            "rules": {"main": [rule("pull_request"), rule("required_status_checks", ["license/cla", "required"])]},
            "check_runs": {SHA: [check_row("license/cla"), check_row("required", rid=2)]},
        }
        rc, out = self.status("microsoft/TypeScript")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  all 2 required checks passed on main tip " + SHA[:7], out)
        self.assertIn("license/cla, required", out)

    def test_hashicorp_terraform_org_repository_rules_are_not_an_error(self):
        # hashicorp/terraform main, the real shape: ALLOW types including the five organization-level repository
        # rules (they govern repositories, not merges), plus 5 ruleset contexts -> those 5, no needless ERROR.
        names = [f"ruleset-{i}" for i in range(1, 6)]
        self.repos["hashicorp/terraform"] = {
            "branches": {"main": classic(enabled=False)},
            "rules": {"main": [rule(t) for t in ("repository_create", "repository_delete", "repository_name",
                                                 "repository_transfer", "repository_visibility", "pull_request")]
                               + [rule("required_status_checks", names)]},
            "check_runs": {SHA: [check_row(n, rid=i + 1) for i, n in enumerate(names)]},
        }
        rc, out = self.status("hashicorp/terraform")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  all 5 required checks passed on main tip " + SHA[:7], out)

    def test_vercel_nextjs_canary_ruleset_checks(self):
        # vercel/next.js canary (its default branch), the real shape: ALLOW types plus 3 ruleset checks -> those 3.
        names = ["build-and-test", "lint", "type-check"]
        self.repos["vercel/next.js"] = {
            "default_branch": "canary",
            "branches": {"canary": classic(enabled=False)},
            "rules": {"canary": [rule("pull_request"), rule("non_fast_forward"),
                                 rule("required_status_checks", names)]},
            "check_runs": {SHA: [check_row(n, rid=i + 1) for i, n in enumerate(names)]},
        }
        rc, out = self.status("vercel/next.js")
        self.assertEqual(rc, 0, out)
        self.assertIn("GREEN  all 3 required checks passed on canary tip " + SHA[:7], out)


if __name__ == "__main__":
    unittest.main()
