"""The eleven bash_rules checks (sleep-poll, heredoc, kube context, merge, PR body, issue body, local docker, heavy jobs in the agent host pod, git stash, git in the live coordinator checkout, credential config): what each refuses and what it lets through.

Most cases call bash_rules.check with a Context (pure); the profile file, the Monitor tool, fail-open and the message the Pi extension
looks for go through the real hook script in a temp copy. Nothing here writes inside the repo.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "dot_local/share/agent-harness/hooks"
sys.path.insert(0, str(HOOKS))
import bash_rules  # noqa: E402

os.environ.setdefault("AGENT_HARNESS_GUARD_LOG", os.devnull)  # the hook logs each refusal; a test run leaves no record in the real state dir

HOMELAB = "kubernetes-admin@kubernetes"
KUBE = {"/kc/homelab": "current-context: %s\n" % HOMELAB, "/kc/other": "apiVersion: v1\ncurrent-context: axon-aks-prod\n",
        "/kc/none": "apiVersion: v1\ncontexts: []\n"}


def ctx(profile="personal", tool="Bash", env=None, cwd="/work", files=None, origins=None, container=False, coordinator_repo=None):
    files = KUBE if files is None else files
    origins = origins or {}
    return bash_rules.Context(tool=tool, profile=profile, env=env or {}, cwd=cwd, read_file=files.get,
                              origin_of=lambda directory: origins.get(directory), container=container, coordinator_repo=coordinator_repo)


def check(text, platform="linux", **kw):
    return bash_rules.check(text, bash_rules.Context(**dict(ctx(**kw)._asdict(), platform=platform)))


class Poll(unittest.TestCase):
    REFUSED = [
        "until test -f /tmp/done; do sleep 2; done",
        "while ! curl -fsS localhost:8080/health; do echo waiting; sleep 5; done",
        "while true\ndo\n  sleep 1\ndone",
        "sh -c 'until test -f /tmp/done; do sleep 2; done'",
        "bash -lc \"while pgrep x; do sleep 1; done\"",
        "sudo timeout 600 sh -c 'until ok; do sleep 3; done'",
        "x=$(until ok; do sleep 1; done)",
        "until ok; do timeout 5 sleep 1; done",
        "until ok; do sh -c 'sleep 1'; done",
        "while read x; do while ! ok; do sleep 1; done; done",
        "until ok; do sleep 1; done | tail -1",
        "nohup sh -c 'while :; do sleep 9; done' &",
    ]
    ALLOWED = [
        "run-and-wake -- sh -c 'until test -f /tmp/done; do sleep 2; done'",
        "run-and-wake -- bash -c \"while ! ok; do sleep 1; done\"",
        "git log -3 --format=%H | while read c; do git show --stat $c; done",
        "gh pr list | while read x; do gh pr view $x; sleep 3; done",
        "while IFS= read -r line; do echo $line; sleep 1; done < file",
        "for p in 448 450; do gh pr view $p; sleep 3; done",
        "sleep 30; echo ok",
        "sleep 30",
        "until ok; do echo waiting; done",
        "echo sleep; grep sleep file",
    ]

    def test_refused(self):
        for text in self.REFUSED:
            with self.subTest(text=text):
                self.assertIn("run-and-wake -- <cmd>", check(text) or "")

    def test_allowed(self):
        for text in self.ALLOWED:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_both_profiles_and_no_profile(self):
        text = "until ok; do sleep 2; done"
        for profile in ("personal", "axon-work-computer", None):
            with self.subTest(profile=profile):
                self.assertTrue(check(text, profile=profile))

    def test_the_monitor_tool_is_exempt(self):
        self.assertIsNone(check("until ok; do sleep 2; done", tool="Monitor"))
        self.assertTrue(check("until ok; do sleep 2; done", tool="Bash"))
        self.assertTrue(check("until ok; do sleep 2; done", tool=None))


class Heredoc(unittest.TestCase):
    REFUSED = [
        "cat > /tmp/x <<EOF\nsee `notes`\nEOF",
        "cat > /tmp/x.md <<-END\n\tsee `notes`\n\tEND",
        "cat <<EOF\nrun $(echo `date`) now\nEOF",
        "cat <<EOF\nescaped backslash \\\\`date`\nEOF",
        'gh pr create --body "$(cat <<EOF\nRuns `make test` first.\nEOF\n)"',
        "sh -c 'cat <<EOF\nuse `x`\nEOF\n'",
        "cat <<EOF > f\nuse `x`\nEOF\necho done",
    ]
    ALLOWED = [
        "cat <<'EOF'\nsee `notes`\nEOF",
        'cat <<"EOF"\nsee `notes`\nEOF',
        "cat <<\\EOF\nsee `notes`\nEOF",
        "cat <<-'EOF'\n\tsee `notes`\n\tEOF",
        "cat > /tmp/x <<EOF\nhello $HOME\nEOF",
        "cat > /tmp/x <<EOF\nrun \\`date\\` later\nEOF",
        'git commit -m "$(cat <<\'EOF\'\nRuns `make test` first.\nEOF\n)"',
        "echo `date`",
    ]

    def test_refused(self):
        for text in self.REFUSED:
            for profile in ("personal", "axon-work-computer"):
                with self.subTest(text=text, profile=profile):
                    self.assertIn("<<'EOF'", check(text, profile=profile) or "")

    def test_allowed(self):
        for text in self.ALLOWED:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_the_scan_records_whether_each_delimiter_was_quoted(self):
        scan = bash_rules.Scan("cat <<A\nx\nA\ncat <<'B'\ny\nB\ncat <<\\C\nz\nC\ncat <<\"D\"\nw\nD\n")
        self.assertEqual([quoted for quoted, _ in scan.documents], [False, True, True, True])


class Kube(unittest.TestCase):
    def refused(self, text, **kw):
        message = check(text, **kw)
        self.assertIsNotNone(message, text)
        self.assertIn(HOMELAB, message)

    def test_a_context_flag_naming_another_cluster(self):
        for text in ["kubectl --context axon-aks-prod get pods", "kubectl --context=axon-aks-prod get pods",
                     "timeout 20 kubectl -n x --context axon-aks-prod get jobs", "helm --kube-context axon-aks-prod list",
                     "helm --kube-context=axon-aks-prod list -A", "k9s --context axon-aks-prod", "sudo -u root kubectl --context a get no",
                     "sh -c 'kubectl --context a get no'", "env FOO=1 kubectl --context a get no"]:
            with self.subTest(text=text):
                self.refused(text, env={"KUBECONFIG": "/kc/homelab"})

    def test_switching_context(self):
        for text in ["kubectl config use-context axon-aks-prod", "kubectx axon-aks-prod", "kubectx -"]:
            with self.subTest(text=text):
                self.refused(text, env={"KUBECONFIG": "/kc/homelab"})

    def test_the_current_context_decides_when_there_is_no_flag(self):
        self.refused("kubectl get pods", env={"KUBECONFIG": "/kc/other"})
        self.refused("helm list", env={"KUBECONFIG": "/kc/other"})
        self.refused("k9s", env={"KUBECONFIG": "/kc/other"})
        self.refused("kubectl get pods", env={"KUBECONFIG": "/kc/none:/kc/other"})  # the first file that sets one
        with mock.patch.dict(os.environ, {"HOME": "/home/x"}):  # ~/.kube/config when nothing else names a kubeconfig
            self.refused("kubectl get pods", files={"/home/x/.kube/config": "current-context: 'a b'\n"}, env={})
        self.refused("kubectl get pods", env={"KUBECONFIG": "/kc/other"}, files=dict(KUBE, **{"/kc/homelab": "x"}))

    def test_kubeconfig_flag_and_inline_assignment_beat_the_process_env(self):
        self.refused("kubectl --kubeconfig /kc/other get pods", env={"KUBECONFIG": "/kc/homelab"})
        self.refused("kubectl --kubeconfig=/kc/other get pods", env={"KUBECONFIG": "/kc/homelab"})
        self.refused("KUBECONFIG=/kc/other kubectl get pods", env={"KUBECONFIG": "/kc/homelab"})
        self.refused("env KUBECONFIG=/kc/other kubectl get pods", env={"KUBECONFIG": "/kc/homelab"})
        self.assertIsNone(check("kubectl --kubeconfig /kc/homelab get pods", env={"KUBECONFIG": "/kc/other"}))
        self.assertIsNone(check("KUBECONFIG=/kc/homelab kubectl get pods", env={"KUBECONFIG": "/kc/other"}))

    def test_a_kubeconfig_flag_to_a_file_that_is_not_here_is_refused_unless_the_context_is_the_homelab(self):
        message = check("kubectl --kubeconfig /nowhere get pods")
        self.assertIn("--context " + HOMELAB, message)
        self.assertIsNone(check("kubectl --kubeconfig /nowhere --context %s get pods" % HOMELAB))
        self.assertIsNone(check("kubectl --kubeconfig $tmp/admin.conf get pods"))  # filled in by the shell at run time
        self.assertIsNone(check("KUBECONFIG=/nowhere kubectl get pods", env={"KUBECONFIG": "/kc/other"}))  # inline: nothing to read

    def test_allowed(self):
        for text, env in [("kubectl get pods", {"KUBECONFIG": "/kc/homelab"}),
                          ("kubectl --context %s -n x get jobs" % HOMELAB, {"KUBECONFIG": "/kc/other"}),
                          ("helm --kube-context %s list" % HOMELAB, {"KUBECONFIG": "/kc/other"}),
                          ("k9s --context=%s" % HOMELAB, {"KUBECONFIG": "/kc/other"}),
                          ("kubectx %s" % HOMELAB, {"KUBECONFIG": "/kc/other"}),
                          ("kubectx", {"KUBECONFIG": "/kc/other"}),
                          ("kubectx -c", {"KUBECONFIG": "/kc/other"}),
                          ("kubectl config use-context %s" % HOMELAB, {"KUBECONFIG": "/kc/other"}),
                          ("kubectl config get-contexts", {"KUBECONFIG": "/kc/other"}),
                          ("kubectl config view", {"KUBECONFIG": "/kc/other"}),
                          ("kubectl get pods", {"KUBECONFIG": "/kc/none"}),  # no current-context
                          ("kubectl get pods", {"KUBECONFIG": "/kc/missing"}),
                          ("kubectl get pods", {}),  # no ~/.kube/config
                          ("ssh master-1 'sudo kubectl --kubeconfig /etc/kubernetes/admin.conf get nodes'", {"KUBECONFIG": "/kc/other"}),
                          ("kgate run -- kubectl --context a get no", {}),
                          ("echo kubectl --context a", {"KUBECONFIG": "/kc/other"})]:
            with self.subTest(text=text, env=env):
                self.assertIsNone(check(text, env=env))

    def test_the_work_profile_and_no_profile_do_not_run_it(self):
        for profile in ("axon-work-computer", None):
            self.assertIsNone(check("kubectl --context axon-aks-prod get pods", profile=profile, env={"KUBECONFIG": "/kc/other"}))
            self.assertIsNone(check("kubectl get pods", profile=profile, env={"KUBECONFIG": "/kc/other"}))


class Merge(unittest.TestCase):
    def test_a_bare_merge_names_the_gated_ways(self):
        for text in ["gh pr merge 12 --squash", "sh -c 'gh pr merge 12'", "eval 'gh pr merge 12'", "sudo gh pr merge 12",
                     "cd /tmp && gh pr merge 12", "gh -R cartwmic/homelab pr merge 12", "gh pr merge 12 && echo ok",
                     "ci-main-status x; gh pr merge 12", "ci-main-status x || gh pr merge 12", "ci-main-status x | gh pr merge 12",
                     "ci-main-status x & gh pr merge 12", "echo $(gh pr merge 12)", "gh pr merge 12 && ci-main-status x",
                     "ci-main-status x && echo; gh pr merge 12"]:
            with self.subTest(text=text):
                message = check(text)
                self.assertIn("merge-pr.sh", message)
                self.assertIn("ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr>", message)
                self.assertIn("ecd63156, 385acc43, ccc6c94b and 5a05bfe8", message)
                self.assertIn("agent record", message)
                self.assertIn("pr-record path <repo>#N", message)
                self.assertIn("`Promises:` line", message)
                self.assertIn("unresolved review thread", message)

    def test_the_merge_gate_form_with_both_checks_is_allowed_and_the_exit_code_workaround_is_not(self):
        self.assertIsNone(check("ci-main-status --merge-gate X && pr-body-check X 5 && gh pr merge 5"))
        # The pin-fix exception (issue 429) adds `--pr N` to the gate; `--merge-gate <repo> --pr N` is still the real gate form, so this still merges.
        self.assertIsNone(check("ci-main-status --merge-gate dotfiles --pr 5 && pr-body-check dotfiles 5 && gh pr merge 5 --squash -R cartwmic/dotfiles"))
        self.assertIsNone(check("pr-body-check dotfiles 5 && ci-main-status --merge-gate dotfiles && gh pr merge 5 --squash -R cartwmic/dotfiles"))
        # The documented chain pins the head the checks read; the hook ignores `--match-head-commit` and reads only the gate shapes and the PR number.
        self.assertIsNone(check("ci-main-status --merge-gate X --pr 5 && pr-body-check X 5 && gh pr merge 5 --squash --match-head-commit " + "a" * 40))
        # eval-cases has no CI: its gate is `--merge-gate eval-cases --pr N` (or the OWNER/REPO form), with the same body check and merge.
        for repo in ("eval-cases", "cartwmic/eval-cases"):
            self.assertIsNone(check(f"ci-main-status --merge-gate {repo} --pr 1 && pr-body-check cartwmic/eval-cases 1 && gh pr merge 1 -R cartwmic/eval-cases --squash --match-head-commit " + "a" * 40))
        self.assertIn("pr-body-check", check("ci-main-status --merge-gate eval-cases --pr 1 && gh pr merge 1 -R cartwmic/eval-cases --squash"))
        self.assertIn("--match-head-commit <head sha>", check("gh pr merge 12"))
        self.assertIn("pr-body-check", check("ci-main-status --merge-gate X && gh pr merge 5"))
        message = check("ci-main-status X; [ $? -le 2 ] && gh pr merge 5")
        self.assertIsNotNone(message)
        self.assertIn("merge-pr.sh", message)

    def test_a_body_file_check_does_not_satisfy_the_merge_rule(self):
        # `pr-body-check --body-file F` is the PR-body create/edit check; it never reads the PR's head runs.
        for text in ["ci-main-status --merge-gate dotfiles && pr-body-check --body-file /tmp/b && gh pr merge 5 -R cartwmic/dotfiles",
                     "ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 5 --body-file /tmp/b && gh pr merge 5 -R cartwmic/dotfiles"]:
            with self.subTest(text=text):
                message = check(text)
                self.assertIn("pr-body-check <repo> <pr>", message)
                self.assertIn("a `pr-body-check` with `--body-file` is not the merge check", message)

    def test_a_bare_ci_main_status_is_not_the_merge_gate(self):
        for text in ["ci-main-status dotfiles && pr-body-check dotfiles 5 && gh pr merge 5 -R cartwmic/dotfiles",
                     "ci-main-status --tip dotfiles && pr-body-check dotfiles 5 && gh pr merge 5 -R cartwmic/dotfiles",
                     "ci-main-status --merge-gate && pr-body-check dotfiles 5 && gh pr merge 5 -R cartwmic/dotfiles",
                     "ci-main-status --merge-gate --all && pr-body-check dotfiles 5 && gh pr merge 5 -R cartwmic/dotfiles"]:
            with self.subTest(text=text):
                self.assertIn("A bare `ci-main-status` (or `--tip`) is not the gate", check(text))

    def test_the_full_form_passes_with_or_without_pr_and_for_every_way_gh_names_the_pr(self):
        for text in ["ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 5 && gh pr merge 5 --squash -R cartwmic/dotfiles",
                     "ci-main-status --merge-gate dotfiles --pr 5 && pr-body-check dotfiles 5 && gh pr merge 5 -R cartwmic/dotfiles",
                     "ci-main-status --merge-gate --pr 5 dotfiles && pr-body-check dotfiles 05 && gh pr merge -R cartwmic/dotfiles 5",
                     "ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 5 && gh pr merge --squash --match-head-commit abc1234 5",
                     "ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 5 && gh pr merge https://github.com/cartwmic/dotfiles/pull/5",
                     "ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 5 && gh pr merge my-branch",  # a branch: the hook cannot see the PR
                     "ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 5 && gh pr merge --squash"]:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_a_pr_body_check_for_another_pr_is_refused(self):
        for text in ["ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 7 && gh pr merge 5 -R cartwmic/dotfiles",
                     "ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 7 && gh pr merge -R cartwmic/dotfiles --subject 7 5",
                     "ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 7 && gh pr merge https://github.com/cartwmic/dotfiles/pull/5"]:
            with self.subTest(text=text):
                message = check(text)
                self.assertIn("checked PR 7, but `gh pr merge` merges PR 5", message)
                self.assertIn("pr-body-check <repo> <pr>", message)

    def test_the_refusal_names_a_command_that_satisfies_both_gates(self):
        # The command the refusal prints, with <repo>/<pr> filled in, must itself pass the hook.
        message = check("gh pr merge 12")
        self.assertIn("ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr>", message)
        self.assertIsNone(check("ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 12 && gh pr merge 12"))

    def test_both_checks_first_allow_a_repo_that_is_not_the_coordinator(self):
        for text in ["ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 5 && gh pr merge 5 -R cartwmic/dotfiles --merge",
                     "pr-body-check dotfiles 5 && ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 1 && gh pr merge 5 -R cartwmic/dotfiles --merge",
                     "cd /tmp && ci-main-status --merge-gate homelab && pr-body-check homelab 182 && gh pr merge 182 --squash",
                     "ci-main-status --merge-gate homelab && pr-body-check homelab 182 &&\n gh pr merge 182",
                     "ci-main-status --merge-gate homelab && pr-body-check homelab 182 && cd /tmp && gh pr merge 182",
                     "ci-main-status --merge-gate homelab && pr-body-check homelab 182 && sh -c 'gh pr merge 182'",
                     "ci-main-status --merge-gate homelab && pr-body-check homelab 182 && gh pr merge 182 -R cartwmic/homelab"]:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_one_check_alone_is_refused_with_the_full_form(self):
        for text in ["ci-main-status dotfiles && gh pr merge 5 -R cartwmic/dotfiles",
                     "pr-body-check dotfiles 5 && gh pr merge 5 -R cartwmic/dotfiles",
                     "ci-main-status dotfiles && echo && gh pr merge 5 -R cartwmic/dotfiles",
                     "pr-body-check dotfiles 5; gh pr merge 5",
                     "ci-main-status dotfiles && pr-body-check dotfiles 5; gh pr merge 5",
                     "ci-main-status dotfiles; pr-body-check dotfiles 5 && gh pr merge 5",
                     "ci-main-status dotfiles && pr-body-check dotfiles 5 || gh pr merge 5",
                     "gh pr merge 5 && ci-main-status dotfiles && pr-body-check dotfiles 5"]:
            with self.subTest(text=text):
                message = check(text)
                self.assertIn("ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr>", message)
                self.assertIn("ecd63156, 385acc43, ccc6c94b and 5a05bfe8", message)
                self.assertIn("agent record", message)
                self.assertIn("pr-record path <repo>#N", message)

    def test_the_coordinator_is_refused_even_after_ci_main_status(self):
        for text in ["ci-main-status --merge-gate coordinator && pr-body-check coordinator 440 && gh pr merge 440 -R cartwmic/coordinator --merge",
                     "ci-main-status --merge-gate coordinator && pr-body-check coordinator 440 && gh pr merge 440 --repo cartwmic/coordinator",
                     "ci-main-status --merge-gate coordinator && pr-body-check coordinator 440 && gh pr merge 440 --repo=cartwmic/coordinator.git",
                     "ci-main-status --merge-gate coordinator && pr-body-check coordinator 440 && gh pr merge 440 -R https://github.com/cartwmic/coordinator"]:
            with self.subTest(text=text):
                message = check(text)
                self.assertIn("~/git/coordinator/scripts/merge-pr.sh", message)
                self.assertNotIn("coordinator-workspace/bin", message)

    def test_only_a_plain_repo_and_number_is_the_merge_check(self):
        """`pr-body-check <repo> <pr>` is the merge check; a flag on it (any spelling) or a body-file form is not, and `--` before the words does not hide them."""
        gate = "ci-main-status --merge-gate x && "
        for check_text in ["pr-body-check x 5", "pr-body-check -- x 5"]:
            with self.subTest(check=check_text):
                self.assertIsNone(check(gate + check_text + " && gh pr merge 5 --squash --repo cartwmic/other"))
        for check_text in ["pr-body-check x 5 --skip-intent-review", "pr-body-check --skip-intent-review x 5", "pr-body-check --repo x 5", "pr-body-check -Z x 5", "pr-body-check x",
                           "pr-body-check x 5 6", "pr-body-check x five"]:
            with self.subTest(check=check_text):
                self.assertIn("without both gates", check(gate + check_text + " && gh pr merge 5 --squash --repo cartwmic/other") or "")

    def test_the_homelab_repo_is_refused_with_its_script_even_after_both_gates_and_even_without_them(self):
        for text in ["ci-main-status --merge-gate homelab && pr-body-check homelab 182 && gh pr merge 182 -R cartwmic/cartwmic-homelab-v2 --squash",
                     "pr-body-check homelab 182 && ci-main-status --merge-gate homelab && gh pr merge 182 -R cartwmic/cartwmic-homelab-v2 --squash",
                     "gh pr merge 182 -R cartwmic/cartwmic-homelab-v2 --squash",
                     "gh pr merge 182 --repo cartwmic/cartwmic-homelab-v2",
                     "gh pr merge 182 --repo=cartwmic/cartwmic-homelab-v2.git",
                     "gh pr merge 182 -R https://github.com/cartwmic/cartwmic-homelab-v2",
                     "gh -R cartwmic/cartwmic-homelab-v2 pr merge 182",
                     "sh -c 'gh pr merge 182 -R cartwmic/cartwmic-homelab-v2'"]:
            with self.subTest(text=text):
                message = check(text)
                self.assertIn("~/git/cartwmic-homelab-v2/scripts/merge-pr.sh N SHA", message)
                self.assertNotIn("--revert-of", message)
                self.assertNotIn("--fix-of", message)
                self.assertNotIn("~/git/coordinator/scripts/merge-pr.sh", message)

    def test_a_repo_that_only_starts_like_the_homelab_repo_is_not_refused_as_homelab(self):
        for text in ["ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge 5 -R cartwmic/cartwmic-homelab-v2-old",
                     "ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge 5 -R cartwmic/cartwmic-homelab-v22"]:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_the_homelab_script_and_its_neighbours_are_not_gh_commands_the_hook_sees(self):
        for text in ["~/git/cartwmic-homelab-v2/scripts/merge-pr.sh 182 abc1234",
                     "cd ~/git/cartwmic-homelab-v2 && scripts/merge-pr.sh 182 abc1234",
                     "gh pr view 182 -R cartwmic/cartwmic-homelab-v2", "gh pr checks 182 -R cartwmic/cartwmic-homelab-v2"]:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_the_directory_decides_when_there_is_no_repo_flag(self):
        origins = {"/repos/coord": "git@github.com:cartwmic/coordinator.git", "/repos/other": "https://github.com/cartwmic/dotfiles.git",
                   "/work": "https://github.com/cartwmic/coordinator"}
        self.assertIn("merge-pr.sh", check("cd /repos/coord && ci-main-status --merge-gate coordinator && pr-body-check coordinator 1 && gh pr merge 1", origins=origins))
        self.assertIn("merge-pr.sh", check("ci-main-status --merge-gate coordinator && pr-body-check coordinator 1 && gh pr merge 1", origins=origins))  # the hook cwd
        self.assertIsNone(check("cd /repos/other && ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 1 && gh pr merge 1", origins=origins))
        self.assertIsNone(check("cd /repos/coord && ci-main-status --merge-gate coordinator && pr-body-check coordinator 1 && cd /repos/other && gh pr merge 1", origins=origins))
        self.assertIsNone(check("ci-main-status --merge-gate x && pr-body-check x 1 && gh pr merge 1 -R cartwmic/dotfiles", origins=origins))  # -R decides, not the cwd
        self.assertIsNone(check("cd /nowhere && ci-main-status --merge-gate x && pr-body-check x 1 && gh pr merge 1", origins=origins))
        self.assertIsNone(check("cd $d && ci-main-status --merge-gate x && pr-body-check x 1 && gh pr merge 1", origins=origins))
        homelab = {"/repos/hl": "git@github.com:cartwmic/cartwmic-homelab-v2.git", "/repos/other": "https://github.com/cartwmic/dotfiles.git"}
        self.assertIn("cartwmic-homelab-v2/scripts/merge-pr.sh N SHA", check("cd /repos/hl && gh pr merge 1 --squash", origins=homelab))
        self.assertIn("cartwmic-homelab-v2/scripts/merge-pr.sh N SHA", check("cd /repos/hl && ci-main-status --merge-gate homelab && pr-body-check homelab 1 && gh pr merge 1", origins=homelab))
        self.assertIsNone(check("cd /repos/hl && ci-main-status --merge-gate x && pr-body-check x 1 && cd /repos/other && gh pr merge 1", origins=homelab))
        self.assertIsNone(check("cd /repos/hl && ci-main-status --merge-gate x && pr-body-check x 1 && gh pr merge 1 -R cartwmic/dotfiles", origins=homelab))  # -R decides

    def test_a_real_checkout_whose_origin_is_the_coordinator(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
            subprocess.run(["git", "-C", tmp, "remote", "add", "origin", "https://github.com/cartwmic/coordinator.git"], check=True)
            self.assertIn("merge-pr.sh", bash_rules.check("cd %s && ci-main-status --merge-gate coordinator && pr-body-check coordinator 1 && gh pr merge 1" % tmp,
                                                        bash_rules.Context(profile="personal", env={}, cwd="/")))
            self.assertIsNone(bash_rules.origin_of(os.path.join(tmp, "missing")))
            self.assertIsNone(bash_rules.origin_of(None))
        with tempfile.TemporaryDirectory() as tmp:  # not a git checkout
            self.assertIsNone(bash_rules.origin_of(tmp))

    def test_the_gated_paths_are_not_gh_commands_the_hook_sees(self):
        for text in ["~/git/coordinator/scripts/merge-pr.sh 440",
                     "COORDINATOR_STATE_DIR=$HOME/.local/share/coordinator node --experimental-strip-types ~/git/coordinator/src/playbook/cli.ts retire fab9b713 --pr --merge",
                     "loop_engine_bump.py v0.49.1", "agent_kit_bump.py v1.4.0", "gh pr view 12", "gh pr list", "echo gh pr merge 12",
                     "git merge main"]:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_the_work_profile_runs_it_and_no_profile_or_termux_does_not(self):
        self.assertIsNotNone(check("gh pr merge 12", profile="axon-work-computer"))
        self.assertIsNone(check("ci-main-status --merge-gate acme/app && pr-body-check acme/app 12 && gh pr merge 12 -R acme/app", profile="axon-work-computer"))
        for profile in ("termux", None):
            self.assertIsNone(check("gh pr merge 12", profile=profile))


class PrBody(unittest.TestCase):
    # a name mktemp made: /tmp/pr-N-body.XXXXXX with the six X filled in (a digit or an uppercase letter among them)
    C = "/tmp/pr-new-body.aB3xY9"   # a create: no PR number yet
    E = "/tmp/pr-5-body.aB3xY9"     # an edit of PR 5

    def test_a_title_the_check_was_not_given_is_refused(self):
        c, e = self.C, self.E
        for text in ["pr-body-check --body-file %s && gh pr create --title t --body-file %s" % (c, c),
                     "pr-body-check --body-file %s --title other && gh pr create --title t --body-file %s" % (c, c),
                     "pr-body-check --body-file %s && gh pr edit 5 --title t --body-file %s" % (e, e)]:
            with self.subTest(text=text):
                message = check(text)
                self.assertIn("was not given", message)
                self.assertIn("pr-body-check --body-file F --title T && gh pr", message)
        # a PR given no --title (an edit that keeps it) needs none on the check
        self.assertIsNone(check("pr-body-check --body-file %s && gh pr edit 5 --body-file %s" % (e, e)))

    def test_gh_short_title_flag_is_read_like_the_long_one(self):
        c, e = self.C, self.E
        for form in ("-t 'Fix task-12'", "-t='Fix task-12'", "-t'Fix task-12'", "--title='Fix task-12'"):
            for verb, f in (("create", c), ("edit 5", e)):
                text = "pr-body-check --body-file %s && gh pr %s %s --body-file %s" % (f, verb, form, f)
                with self.subTest(text=text):
                    self.assertIn("was not given", check(text))
        for form in ("-t t", "-t=t", "-tt"):
            text = "pr-body-check --body-file %s --title t && gh pr create %s --body-file %s" % (c, form, c)
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_a_title_only_edit_needs_a_check_that_saw_the_title(self):
        e = self.E
        for text in ["gh pr edit 5 --title t", "gh pr edit 5 -t t", "pr-body-check --body-file %s --title other && gh pr edit 5 --title t" % e,
                     "pr-body-check --body-file %s && gh pr edit 5 -t t" % e]:
            with self.subTest(text=text):
                self.assertIn("was not given", check(text))
        for text in ["pr-body-check --body-file %s --title t && gh pr edit 5 --title t" % e, "pr-body-check --body-file %s --title t && gh pr edit 5 -t t" % e,
                     "gh pr edit 5 --add-label x"]:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_one_check_must_have_seen_both_the_file_and_the_title(self):
        c, g = self.C, "/tmp/pr-new-body.zZ9yY8"
        text = "pr-body-check --body-file %s --title t && pr-body-check --body-file %s && gh pr create --title t --body-file %s" % (g, c, c)
        self.assertIn("was not given", check(text))
        self.assertIsNone(check("pr-body-check --body-file %s --title t && gh pr create --title t --body-file %s" % (c, c)))

    def test_a_create_or_edit_without_the_check_names_the_chained_form(self):
        for text in ["gh pr create --title t --body-file %s" % self.C, "gh pr edit 5 --body-file %s" % self.E, "gh pr create -F %s" % self.C,
                     "gh pr create --body-file=%s" % self.C, "gh pr new --body-file %s" % self.C, "gh -R cartwmic/dotfiles pr edit 5 -F %s" % self.E,
                     "sh -c 'gh pr create --body-file %s'" % self.C, "cd /tmp && gh pr create --body-file pr-new-body.aB3xY9",
                     "echo $(gh pr create --body-file %s)" % self.C]:
            with self.subTest(text=text):
                message = check(text)
                self.assertIn("refused in agent sessions", message)
                self.assertIn("pr-body-check --body-file F --title T && gh pr", message)
                self.assertIn("agent bookkeeping", message)
                self.assertIn("the PR's agent record (`pr-record path <repo>#N` prints where; playbook 5a05bfe8)", message)
                self.assertIn("a Proven section as plain prose, playbook f5a367b5", message)  # the Proven section stays; only its tables and job ids move
                self.assertIn("a table in the Proven section", message)

    def test_the_check_chained_with_the_same_file_is_allowed(self):
        c, e = self.C, self.E
        for text in ["pr-body-check --body-file %s && gh pr create --body-file %s" % (c, c),
                     "pr-body-check --body-file %s --title t && gh pr create --title t --body-file %s" % (c, c),  # the form the refusal names
                     "pr-body-check --title t --body-file %s && gh pr edit 5 --title t --body-file %s" % (e, e),
                     "pr-body-check --body-file %s && gh pr edit 5 --body-file %s" % (e, e),
                     "pr-body-check --body-file=%s && gh pr create -F %s" % (c, c),
                     "pr-body-check --body-file %s && gh pr new --body-file=%s" % (c, c),
                     "cd /tmp && pr-body-check --body-file pr-new-body.aB3xY9 && gh pr create --body-file pr-new-body.aB3xY9 -R cartwmic/coordinator",
                     "pr-body-check --body-file %s && sh -c 'gh pr create --body-file %s'" % (c, c),
                     "pr-body-check --body-file %s &&\n gh pr create --body-file %s" % (c, c),
                     "pr-body-check --body-file /tmp/pr-new-body.zZ9yY8 && pr-body-check --body-file %s && gh pr create --body-file %s" % (c, c)]:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_a_different_file_or_a_broken_chain_is_refused(self):
        c, e, other = self.C, self.E, "/tmp/pr-new-body.zZ9yY8"
        for text in ["pr-body-check --body-file %s && gh pr create --body-file %s" % (other, c),
                     "pr-body-check --body-file %s && gh pr edit 5 -F %s" % (other, e),
                     "pr-body-check --body-file %s; gh pr create --body-file %s" % (c, c),
                     "pr-body-check --body-file %s || gh pr create --body-file %s" % (c, c),
                     "pr-body-check --body-file %s & gh pr create --body-file %s" % (c, c),
                     "gh pr create --body-file %s && pr-body-check --body-file %s" % (c, c),
                     "pr-body-check cartwmic/dotfiles 5 && gh pr create --body-file %s" % c,  # the saved-PR form reads no file
                     "ci-main-status x && gh pr create --body-file %s" % c]:
            with self.subTest(text=text):
                self.assertIn("pr-body-check --body-file F", check(text))

    def test_a_body_that_is_not_a_checked_file_is_refused(self):
        c = self.C
        for text in ["gh pr create --title t --body 'text'", "gh pr create -b text", "gh pr create --body=text", "gh pr edit 5 --body text",
                     "gh pr create --fill", "gh pr create --title t", "gh pr create", "gh pr create --web",
                     "pr-body-check --body-file - && gh pr create --body-file -", "gh pr create --body-file -",
                     "pr-body-check --body-file %s && gh pr create --title t --body 'text'" % c]:
            with self.subTest(text=text):
                self.assertIn("pr-body-check --body-file F", check(text))

    def test_an_edit_that_sets_no_body_and_other_pr_commands_pass(self):
        for text in ["gh pr edit 5 --add-label x", "gh pr view 5", "gh pr list", "gh pr merge 5 --body-file x",
                     "echo gh pr create", "gh issue create --body-file /tmp/pr-body.md", "gh issue edit 5 --body-file /tmp/pr-body.md"]:
            with self.subTest(text=text):
                self.assertNotIn("pr-body-check --body-file F", check(text) or "")
                self.assertNotIn("mktemp", check(text) or "")

    def test_the_coordinator_is_not_exempt(self):
        c = self.C
        self.assertIn("pr-body-check --body-file F", check("gh pr create -R cartwmic/coordinator --body-file %s" % c))
        self.assertIsNone(check("pr-body-check --body-file %s && gh pr create -R cartwmic/coordinator --body-file %s" % (c, c)))

    def test_the_work_profile_runs_it_and_no_profile_or_termux_does_not(self):
        for text in ("gh pr create --body 'x'", "gh pr edit 5 --body-file /tmp/pr-body.md", "gh pr create --body-file /tmp/pr-body.md"):
            self.assertIsNotNone(check(text, profile="axon-work-computer"))
            for profile in ("termux", None):
                self.assertIsNone(check(text, profile=profile))


class PrBodyNamesPrOpen(unittest.TestCase):
    """The refusal names `pr-open` as the shortest path, with its exact command form, and `pr-open` itself is not refused."""

    def test_a_create_refusal_names_the_pr_open_create_form(self):
        for text in ["gh pr create --title t --fill", "gh pr create --title t --body-file /tmp/pr-body.md", "gh pr new --body 'x'"]:
            with self.subTest(text=text):
                message = check(text)
                self.assertIn("Shortest path: `pr-open --title T --body-file F [--draft]`", message)
                self.assertIn("never reads the agent record", message)
                self.assertIn("pr-body-check <owner/repo> <pr> --skip-intent-review", message)
                self.assertIn("pr-body-check --body-file F --title T && gh pr create --title T", message)  # the chained form is still named

    def test_an_edit_refusal_names_the_pr_open_edit_form(self):
        for text in ["gh pr edit 5 --body 'x'", "gh pr edit 5 --body-file /tmp/pr-5-body.md"]:
            with self.subTest(text=text):
                self.assertIn("`pr-open --edit N --body-file F`", check(text))

    def test_the_body_file_name_refusal_names_it_too(self):
        self.assertIn("Or use `pr-open --title T --body-file F [--draft]`", check("pr-body-check --body-file /tmp/pr-body.md && gh pr create --body-file /tmp/pr-body.md"))
        self.assertIn("Or use `pr-open --edit N --body-file F`", check("pr-body-check --body-file /tmp/pr-body.md && gh pr edit 5 --body-file /tmp/pr-body.md"))

    def test_pr_open_itself_passes_the_hook(self):
        for text in ["pr-open --title t --body-file /tmp/pr-body.md", "pr-open --edit 5 --body-file /tmp/pr-body.md", "pr-open --title t --body-file - --draft"]:
            with self.subTest(text=text):
                self.assertIsNone(check(text))


class IssueBody(unittest.TestCase):
    """`gh issue create` is refused and names `issue-open`, where the profile's coordinator checkout holds the claims command (src/claims/cli.ts)."""
    REFUSED = ["gh issue create --title t --body x", "gh issue create -t t -F body.md", "gh issue new --title t", "gh -R cartwmic/x issue create --title t", "gh issue -R cartwmic/x create",
               "gh issue create --repo cartwmic/x --title t --body-file /tmp/b.md --label bug", "cd /tmp && gh issue create --title t", "echo x | gh issue create --title t --body-file -",
               "sh -c 'gh issue create --title t'", "sudo gh issue create --title t", "gh api repos/cartwmic/x/issues -f title=t -f body=b", "gh api -X POST repos/cartwmic/x/issues --input /tmp/i.json",
               "gh api --method=POST https://api.github.com/repos/cartwmic/x/issues -F title=t"]
    PASSES = ["gh issue edit 5 --body-file /tmp/b.md", "gh issue comment 5 --body hi", "gh issue list", "gh issue view 5", "gh issue close 5", "gh issue status",
              "issue-open --title t --body-file /tmp/b.md", "issue-open --title t --body-file - --dry-run", "echo gh issue create", "grep 'gh issue create' notes.md",
              "gh api repos/cartwmic/x/issues", "gh api repos/cartwmic/x/issues/5/comments -f body=hi", "gh api -X GET repos/cartwmic/x/issues -f labels=bug", "gh pr list"]

    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo, ignore_errors=True)
        (Path(self.repo) / "src/claims").mkdir(parents=True)
        (Path(self.repo) / "src/claims/cli.ts").write_text("// stub\n")

    def issue_check(self, text, **kw):
        kw.setdefault("coordinator_repo", self.repo)
        return check(text, **kw)

    def test_each_form_is_refused_and_names_issue_open(self):
        for text in self.REFUSED:
            with self.subTest(text=text):
                message = self.issue_check(text)
                self.assertIn("issue-open --title T --body-file F", message or "")
                self.assertIn("refused in agent sessions", message)

    def test_other_issue_commands_and_issue_open_pass(self):
        for text in self.PASSES:
            with self.subTest(text=text):
                self.assertIsNone(self.issue_check(text))

    def test_the_refusal_does_not_borrow_the_pr_body_text(self):
        message = self.issue_check("gh issue create --title t")
        for text in ("pr-body-check --body-file F", "mktemp", "pr-open"):
            self.assertNotIn(text, message)
        self.assertIn("`claims ran -- <cmd>`", message)

    def test_both_desktop_profiles_run_it_and_termux_and_no_profile_do_not(self):
        for profile in ("personal", "axon-work-computer"):
            self.assertIsNotNone(self.issue_check("gh issue create --title t", profile=profile))
        for profile in ("termux", None):
            self.assertIsNone(self.issue_check("gh issue create --title t", profile=profile))

    def test_it_waits_until_the_claims_command_is_in_the_checkout(self):
        (Path(self.repo) / "src/claims/cli.ts").unlink()
        for text in ("gh issue create --title t", "gh api repos/cartwmic/x/issues -f title=t"):
            self.assertIsNone(self.issue_check(text))
        self.assertIsNone(self.issue_check("gh issue create --title t", coordinator_repo=str(Path(self.repo) / "missing")))

    def test_with_no_instance_file_it_looks_in_git_coordinator_under_home(self):
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, ignore_errors=True)
        self.assertIsNone(check("gh issue create --title t", env={"HOME": home}))
        (Path(home) / "git/coordinator/src/claims").mkdir(parents=True)
        (Path(home) / "git/coordinator/src/claims/cli.ts").write_text("// stub\n")
        self.assertIn("issue-open", check("gh issue create --title t", env={"HOME": home}))

    def test_the_issue_create_flags_are_read_so_a_value_is_not_taken_for_an_operand(self):
        gh = bash_rules.gh_command(["issue", "new", "--type", "bug", "-t", "T", "-F", "f", "-R", "o/r"])
        self.assertEqual((gh.group, gh.verb, gh.operands), ("issue", "create", []))
        self.assertEqual([gh.argv.value(n) for n in ("type", "title", "body-file", "repo")], ["bug", "T", "f", "o/r"])  # `type` is on the issue row only, not the pr one

    def test_the_refusal_writes_a_reason_for_the_guard_log(self):
        found = bash_rules.refusal("gh issue create --title t", bash_rules.Context(**dict(ctx(coordinator_repo=self.repo)._asdict(), platform="linux")))
        self.assertEqual(found[0], "issue_body")
        self.assertEqual(found[1].log, {"reason": "issue created without issue-open"})
        self.assertEqual(found[2], "gh issue create")
        api = bash_rules.refusal("gh api repos/cartwmic/x/issues -f title=SECRETVALUE", bash_rules.Context(**dict(ctx(coordinator_repo=self.repo)._asdict(), platform="linux")))
        self.assertNotIn("SECRETVALUE", json.dumps(api[1].log))


class IssueBodyRealHook(unittest.TestCase):
    """The real hook script, as the Bash tool's JSON payload reaches it, with the coordinator checkout named by AGENT_HARNESS_COORDINATOR_REPO."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.hooks = Path(cls.tmp) / "hooks"
        shutil.copytree(HOOKS, cls.hooks)
        (cls.hooks / "profile").write_text("personal\n")
        cls.repo = Path(cls.tmp) / "coordinator"
        (cls.repo / "src/claims").mkdir(parents=True)
        (cls.repo / "src/claims/cli.ts").write_text("// stub\n")
        cls.log = Path(cls.tmp) / "guard.jsonl"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_hook(self, command, repo=None):
        env = {k: v for k, v in os.environ.items() if k not in ("AGENT_HARNESS_CONTAINER", "AGENT_HARNESS_PROFILE", "AGENT_HARNESS_COORDINATOR_REPO")}
        env.update(AGENT_HARNESS_GUARD_LOG=str(self.log), AGENT_HARNESS_COORDINATOR_REPO=str(repo or self.repo))
        payload = {"tool_name": "Bash", "cwd": self.tmp, "tool_input": {"command": command}}
        return subprocess.run([sys.executable, str(self.hooks / "refuse_pattern_kill.py")], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30)

    def test_a_bare_issue_create_exits_2_naming_issue_open_and_issue_open_exits_0(self):
        refused = self.run_hook("gh issue create --title t --body-file /tmp/b.md")
        self.assertEqual(refused.returncode, 2)
        self.assertIn("refused in agent sessions", refused.stderr)
        self.assertIn("issue-open --title T --body-file F", refused.stderr)
        for allowed in ("issue-open --title t --body-file /tmp/b.md", "gh issue list", "gh issue edit 5 --body-file /tmp/b.md"):
            self.assertEqual(self.run_hook(allowed).returncode, 0, allowed)

    def test_one_guard_log_line_for_the_refusal(self):
        self.log.unlink(missing_ok=True)
        self.run_hook("gh issue create --title t")
        lines = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual([(l["rule"], l["matched"]) for l in lines], [("issue_body", "gh issue create")])

    def test_it_passes_while_the_checkout_has_no_claims_command(self):
        self.assertEqual(self.run_hook("gh issue create --title t", repo=Path(self.tmp) / "none").returncode, 0)


class PrBodyViaApi(unittest.TestCase):
    """`gh api` on the pulls endpoints sets a PR body without the body check (dotfiles#451): refused, pointing to `pr-open`."""
    REFUSED = ["gh api -X PATCH repos/cartwmic/x/pulls/1 -f body=hi",
               "gh api --method PATCH repos/cartwmic/x/pulls/1 -F body=@/tmp/b",
               "gh api --method=PATCH repos/cartwmic/x/pulls/1 --raw-field body=hi",
               "gh api repos/cartwmic/x/pulls -f title=t -f head=h -f base=main -f body=hi",
               "gh api repos/{owner}/{repo}/pulls --field body=hi",
               "gh api -X POST /repos/cartwmic/x/pulls --input /tmp/pr.json",
               "gh api -H 'Accept: application/json' repos/cartwmic/x/pulls/7/ -X PATCH -f body=hi",
               "sh -c 'gh api -X PATCH repos/cartwmic/x/pulls/1 -f body=hi'",
               "echo ok && gh api -X PATCH repos/cartwmic/x/pulls/1 -f body=hi",
               # attached shorthand values, which gh reads the same way (round-1 note n3)
               "gh api -XPATCH repos/cartwmic/x/pulls/1 -fbody=hi",
               "gh api -X PATCH repos/cartwmic/x/pulls/1 -f=body=hi",
               "gh api -X PATCH repos/cartwmic/x/pulls/1 -Fbody=@/tmp/b",
               "gh api -X PATCH repos/cartwmic/x/pulls/1 -F=body=@/tmp/b",
               "gh api -X PATCH repos/cartwmic/x/pulls/1 --field=body=hi",
               "gh api -X PATCH repos/cartwmic/x/pulls/1 --raw-field=body=hi",
               "gh api -X=PATCH repos/cartwmic/x/pulls/1 -f body=hi"]
    ISSUES_REFUSED = ["gh api -X PATCH repos/cartwmic/x/issues/1 -f body=hi",   # a PR is an issue: this can set a PR body (round-1 note n1)
                      "gh api repos/cartwmic/x/issues/12 -X PATCH -F body=@/tmp/b",
                      "gh api -XPATCH repos/cartwmic/x/issues/12 -fbody=hi",
                      "gh api --method PATCH /repos/cartwmic/x/issues/3/ --input /tmp/i.json"]
    PASSED = ["gh api repos/cartwmic/x/pulls/1",
              "gh api -X GET repos/cartwmic/x/pulls/1 -f body=hi", "gh api -XGET repos/cartwmic/x/pulls/1 -f body=hi",
              "gh api --method=get repos/cartwmic/x/pulls/1 -fbody=hi",
              "gh api repos/cartwmic/x/pulls/1/comments -f body=hi",
              "gh api repos/cartwmic/x/issues/1 -X PATCH -f state=closed",
              "gh api repos/cartwmic/x/issues -f title=t -f body=hi",   # creating an issue
              "gh api repos/cartwmic/x/issues/1/comments -f body=hi",
              "gh api repos/cartwmic/x/issues/1 -X GET -f body=hi",
              "gh api -X PATCH repos/cartwmic/x/issues/1 -f title=t",
              "gh api repos/cartwmic/x/pulls -f title=t -f head=h -f base=main",
              "gh api -X PATCH repos/cartwmic/x/pulls/1 -f state=closed",
              "gh api -X PATCH repos/cartwmic/x/pulls/1 -f title=t",
              "gh api repos/cartwmic/x/pulls --jq '.[].number'",
              "gh pr view 1", "echo gh api -X PATCH repos/cartwmic/x/pulls/1 -f body=hi",
              "pr-open --edit 1 --body-file /tmp/pr-1-body.md"]

    def test_a_pulls_call_that_sets_a_body_is_refused_and_names_pr_open(self):
        for text in self.REFUSED:
            with self.subTest(text=text):
                message = check(text) or ""
                self.assertIn("`gh api` that sets a pull request body (POST, PATCH or PUT", message)
                self.assertIn("`pr-open --title T --body-file F [--draft]`", message)
                self.assertIn("`pr-open --edit N --body-file F`", message)

    def test_a_patch_on_an_issue_number_that_sets_a_body_is_refused_for_it_can_set_a_pr_body(self):
        for text in self.ISSUES_REFUSED:
            with self.subTest(text=text):
                message = check(text) or ""
                self.assertIn("a pull request is an issue too", message)
                self.assertIn("`pr-open --edit N --body-file F`", message)
                self.assertIn("gh issue edit N --body-file F", message)

    def test_other_gh_api_calls_pass(self):
        for text in self.PASSED:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_the_work_profile_runs_it_and_no_profile_or_termux_does_not(self):
        self.assertIsNotNone(check(self.REFUSED[0], profile="axon-work-computer"))
        for profile in ("termux", None):
            self.assertIsNone(check(self.REFUSED[0], profile=profile))


class PrBodyViaApiLog(unittest.TestCase):
    """Each refusal of a gh api body write is one JSON line in the guard log (principle 14): reason, method and endpoint, and the command with every field value redacted. An allowed call writes none."""
    SECRET = "ghp_notARealToken123456789"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.hooks = Path(self.tmp) / "hooks"
        shutil.copytree(HOOKS, self.hooks)
        (self.hooks / "profile").write_text("personal\n")
        self.log = Path(self.tmp) / "state" / "guard.jsonl"

    def run_hook(self, command):
        env = {k: v for k, v in os.environ.items() if k not in ("AGENT_HARNESS_CONTAINER", "AGENT_HARNESS_GUARD_LOG", "AGENT_HARNESS_PROFILE")}
        env["AGENT_HARNESS_GUARD_LOG"] = str(self.log)
        payload = {"tool_name": "Bash", "cwd": self.tmp, "tool_input": {"command": command}}
        return subprocess.run([sys.executable, str(self.hooks / "refuse_pattern_kill.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=30)

    def records(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_a_refusal_writes_one_line_and_an_allowed_call_writes_none(self):
        for allowed in ("gh api repos/cartwmic/x/pulls/1", "gh api -X PATCH repos/cartwmic/x/pulls/1 -f state=closed", "gh api -X GET repos/cartwmic/x/pulls/1 -f body=hi"):
            self.assertEqual(self.run_hook(allowed).returncode, 0)
        self.assertEqual(self.records(), [])
        run = self.run_hook("gh api -X PATCH repos/cartwmic/x/pulls/1 -f body=hello-body-text")
        self.assertEqual(run.returncode, 2)
        (record,) = self.records()
        self.assertEqual((record["action"], record["rule"], record["tool"], record["matched"]), ("refuse", "pr_body", "Bash", "PATCH repos/cartwmic/x/pulls/1"))
        self.assertRegex(record["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        self.assertIn("PATCH", record["reason"])
        self.assertIn("pulls", record["reason"])
        self.assertEqual(record["command"], "gh api -X PATCH repos/cartwmic/x/pulls/1 -f body=<redacted>")
        self.assertNotIn("hello-body-text", self.log.read_text())

    def test_a_title_refusal_logs_its_reason(self):
        run = self.run_hook("pr-body-check --body-file /tmp/pr-new-body.aB3xY9 && gh pr create --title t --body-file /tmp/pr-new-body.aB3xY9")
        self.assertEqual(run.returncode, 2)
        (record,) = self.records()
        self.assertEqual((record["rule"], record["reason"]), ("pr_body", "title not given to the check"))
        self.assertEqual(record["matched"], "gh pr create --title")
        run = self.run_hook("gh pr create --title t --body-file /tmp/pr-new-body.aB3xY9")  # a missing check is another refusal: no title reason
        self.assertEqual(run.returncode, 2)
        self.assertNotIn("reason", self.records()[-1])

    def test_the_record_never_holds_a_body_a_header_a_token_or_a_query(self):
        for command in ("gh api -X PATCH repos/cartwmic/x/pulls/1 -H 'Authorization: token %s' -f body=%s -f title=%s" % ((self.SECRET,) * 3),
                        "GH_TOKEN=%s gh api repos/cartwmic/x/pulls -fbody=%s" % ((self.SECRET,) * 2),
                        "gh api -XPATCH 'repos/cartwmic/x/issues/4?access_token=%s' -F body=%s" % ((self.SECRET,) * 2)):
            self.assertEqual(self.run_hook(command).returncode, 2)
        self.assertNotIn(self.SECRET, self.log.read_text())
        self.assertEqual(len(self.records()), 3)
        self.assertEqual([r["matched"] for r in self.records()], ["PATCH repos/cartwmic/x/pulls/1", "POST repos/cartwmic/x/pulls", "PATCH repos/cartwmic/x/issues/4"])

    def test_an_input_file_refusal_names_the_file_and_says_input(self):
        self.assertEqual(self.run_hook("gh api -X POST repos/cartwmic/x/pulls --input /tmp/pr.json").returncode, 2)
        (record,) = self.records()
        self.assertIn("--input", record["reason"])
        self.assertEqual(record["command"], "gh api -X POST repos/cartwmic/x/pulls --input /tmp/pr.json")


class PrBodyNamesFileListFlags(unittest.TestCase):
    """The PR-body refusal names the file-list flags that let a playbook-only PR pass pr-body-check (dotfiles#454)."""

    def test_the_refusal_names_the_flags(self):
        for text in ["gh pr create --title t --fill", "gh pr edit 5 --body 'x'", "gh pr create --body-file /tmp/pr-body.md"]:
            with self.subTest(text=text):
                message = check(text)
                for flag in ("--files-file F", "--pr N [--repo R]", "--base REF"):
                    self.assertIn(flag, message)

    def test_the_wrapper_header_and_readme_name_them_too(self):
        for path in ("dot_local/bin/executable_pr-body-check", "dot_local/share/agent-harness/README.md"):
            text = (ROOT / path).read_text()
            with self.subTest(path=path):
                for flag in ("--files-file", "--pr N", "--base REF"):
                    self.assertIn(flag, text)


class PrBodyFileName(unittest.TestCase):
    """The body file's name: not a fixed shared name, and for an edit it names the PR number (2026-11-15: /tmp/pr-body.md put #347's body on #345)."""
    FIX = "F=$(mktemp /tmp/pr-N-body.XXXXXX)"
    FIXED = ["/tmp/pr-body.md", "/tmp/body.md", "/tmp/pr-5-body.md", "/tmp/pr-5-body.markdown", "pr-body.md", "/tmp/pr345.md", "/tmp/pr-5-body"]

    def chained(self, verb, name):
        title = " --title t" if "--title t" in verb else ""  # the check gets the title the PR is given
        return "pr-body-check --body-file %s%s && gh pr %s --body-file %s" % (name, title, verb, name)

    def test_a_fixed_name_is_refused_for_create_and_edit_even_when_checked(self):
        for name in self.FIXED:
            for verb, n in (("create --title t", "N"), ("edit 5", "5")):
                with self.subTest(name=name, verb=verb):
                    message = check(self.chained(verb, name))
                    self.assertIn("F=$(mktemp /tmp/pr-%s-body.XXXXXX)" % n, message)
                    self.assertIn("a fixed name like /tmp/pr-body.md can be overwritten by another session", message)
                    self.assertIn("`%s`" % name, message)
                    self.assertNotIn("pr-body-check --body-file F --title T && gh pr", message)  # the chain is right; only the name is wrong

    def test_a_name_with_another_number_or_none_is_refused_for_an_edit(self):
        for name in ["/tmp/pr-4-body.aB3xY9", "/tmp/pr-45-body.aB3xY9", "/tmp/pr-55-body.aB3xY9", "/tmp/pr-body.aB3xY9", "/tmp/pr-345-body.aB3xY9"]:
            with self.subTest(name=name):
                message = check(self.chained("edit 5", name))
                self.assertIn("does not contain PR number 5", message)
                self.assertIn("F=$(mktemp /tmp/pr-5-body.XXXXXX)", message)

    def test_the_right_number_in_a_mktemp_name_is_allowed(self):
        for text in [self.chained("edit 345 --repo cartwmic/cartwmic-homelab-v2", "/tmp/pr-345-body.aB3xY9"),
                     self.chained("edit --repo x 345", "/tmp/pr-345-body.Qw9ErT"),
                     self.chained("edit https://github.com/o/r/pull/345", "/tmp/pr-345-body.aB3xY9"),
                     self.chained("edit 5", "/tmp/345-5-body.aB3xY9"),
                     self.chained("create --title t", "/tmp/pr-body.aB3xY9"),
                     self.chained("create --title t", "/tmp/pr-345-body.aB3xY9"),
                     self.chained("edit my-branch", "/tmp/pr-body.aB3xY9")]:  # no number to compare: only the mktemp shape counts
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_a_variable_from_mktemp_in_the_same_command_is_allowed(self):
        for text in ['F=$(mktemp /tmp/pr-345-body.XXXXXX); cat > "$F" <<\'EOF\'\nbody\nEOF\n'
                     'pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"',
                     'F=$(mktemp /tmp/pr-345-body.XXXXXX) && pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"',
                     'F=$(mktemp -t pr-345-body.XXXXXX) && pr-body-check --body-file ${F} && gh pr edit 345 -F ${F}',
                     'F=$(mktemp --suffix .md /tmp/pr-345-body.XXXXXX); pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"',
                     'F="$(mktemp /tmp/pr-345-body.XXXXXXXX)"; pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"',
                     'F=`mktemp /tmp/pr-345-body.XXXXXX`; pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"',
                     'F=$(mktemp /tmp/pr-new-body.XXXXXX); pr-body-check --body-file "$F" --title t && gh pr create --title t --body-file "$F"',
                     'F=$(mktemp); pr-body-check --body-file "$F" --title t && gh pr create --title t --body-file "$F"',
                     'F=$(mktemp -p /tmp pr-345-body.XXXXXX); pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"']:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_a_variable_that_is_not_a_mktemp_name_is_refused(self):
        for text in ['F=$(mktemp /tmp/pr-4-body.XXXXXX); pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"',  # wrong number
                     'F=$(mktemp); pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"',  # tmp.XXXXXXXXXX names no number
                     'F=$(mktemp /tmp/pr-345-body.XXX); pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"',  # too short
                     'F=/tmp/pr-345-body.md; pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"',
                     'pr-body-check --body-file "$F" && gh pr edit 345 --body-file "$F"',  # F set in an earlier call: not known here
                     'F=$(mktemp /tmp/pr-345-body.XXXXXX); pr-body-check --body-file "$G" && gh pr edit 345 --body-file "$G"']:
            with self.subTest(text=text):
                self.assertIn("F=$(mktemp /tmp/pr-", check(text))

    def test_a_heredoc_that_quotes_the_fix_line_does_not_stand_in_for_the_assignment(self):
        body = "Fix: F=$(mktemp /tmp/pr-451-body.XXXXXX) and --body-file $F"
        real = 'F=$(mktemp /tmp/pr-4-body.XXXXXX); cat > "$F" <<\'EOF\'\n%s\nEOF\npr-body-check --body-file "$F" && gh pr edit 451 --body-file "$F"' % body
        self.assertIn("does not contain PR number 451", check(real))
        unassigned = 'cat > /tmp/x <<\'EOF\'\n%s\nEOF\npr-body-check --body-file "$F" && gh pr edit 451 --body-file "$F"' % body
        self.assertIn("F=$(mktemp /tmp/pr-451-body.XXXXXX)", check(unassigned))

    def test_the_real_2026_11_15_command_is_refused(self):
        real = "gh pr edit 345 --body-file /tmp/pr-body.md 2>&1 | tail -1; gh pr checks 345 2>&1 | head -3"
        for text in [real, "pr-body-check --body-file /tmp/pr-body.md && " + real]:
            with self.subTest(text=text):
                message = check(text)
                self.assertIn("F=$(mktemp /tmp/pr-345-body.XXXXXX)", message)
                self.assertIn("a fixed name like /tmp/pr-body.md can be overwritten by another session", message)


class Docker(unittest.TestCase):
    REFUSED = [
        ("docker run --rm alpine true", "docker run"),
        ("docker build -t x .", "docker build"),
        ("docker compose up -d", "docker compose up"),
        ("docker container run alpine", "docker container run"),
        ("docker image build .", "docker image build"),
        ("docker buildx build --push .", "docker buildx build"),
        ("docker builder build .", "docker builder build"),
        ("docker-compose up", "docker compose up"),
        ("docker-compose -f x.yml up -d", "docker compose up"),
        ("docker compose -f x.yml -p demo up", "docker compose up"),
        ("docker --context other run alpine", "docker run"),
        ("docker -H ssh://host build .", "docker build"),
        ("sudo docker run alpine", "docker run"),
        ("sudo -u root docker build .", "docker build"),
        ("env A=1 docker run alpine", "docker run"),
        ("timeout 200 docker run --rm alpine true", "docker run"),
        ("bash -c 'docker run alpine'", "docker run"),
        ("sh -lc \"cd /x && docker build .\"", "docker build"),
        ("cd /x && docker compose up", "docker compose up"),
        ("echo hi; docker run alpine", "docker run"),
        ("true || docker build .", "docker build"),
        ("which docker && docker run alpine | tail -3", "docker run"),
        ("x=$(docker run alpine)", "docker run"),
        ("find . -name x -exec docker build . \\;", "docker build"),
        ("run-and-wake -- docker build .", "docker build"),
    ]
    ALLOWED = [
        "docker ps", "docker ps -a --filter name=run", "docker images", "docker image ls", "docker inspect build",
        "docker manifest inspect ghcr.io/x/y@sha256:abc", "docker compose ps", "docker compose logs run", "docker compose down",
        "docker buildx ls", "docker buildx imagetools inspect x", "docker rmi x", "docker logs run", "docker version", "docker info",
        "docker-compose ps", "echo docker run", "grep 'docker run' notes.md", "git commit -m 'no docker build here'",
        "cat Dockerfile.build", "dockerd --version", "podman ps",
        "kgate -- docker build .", "run-and-wake -- kgate -- docker run alpine true", "kgate --cpu 4 -- sh -c 'docker build .'",
        "ssh kgate-host docker run alpine",
    ]

    def test_refused_with_the_fix_named(self):
        for text, spelling in self.REFUSED:
            with self.subTest(text=text):
                message = check(text) or ""
                self.assertIn("`%s` is refused in agent sessions" % spelling, message)
                self.assertIn("kgate", message)
                self.assertIn("throwaway namespace on the homelab cluster", message)

    def test_allowed(self):
        for text in self.ALLOWED:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_only_personal_linux_runs_it(self):
        text = "docker run alpine true"
        for profile, platform, want in [("personal", "linux", True), ("personal", "darwin", False), ("axon-work-computer", "linux", False),
                                        ("axon-work-computer", "darwin", False), (None, "linux", False)]:
            with self.subTest(profile=profile, platform=platform):
                self.assertEqual(bool(check(text, profile=profile, platform=platform)), want)

    def test_the_hosts_own_platform_is_used_when_the_context_has_none(self):
        with mock.patch.object(bash_rules.sys, "platform", "darwin"):
            self.assertIsNone(bash_rules.check("docker run alpine", ctx()))
        with mock.patch.object(bash_rules.sys, "platform", "linux"):
            self.assertTrue(bash_rules.check("docker run alpine", ctx()))


class Heavy(unittest.TestCase):
    """In the agent host pod a test, journey or stress run is refused and kgate is named; kgate runs, light commands and every other machine pass."""
    REFUSED = [
        ("npx vitest run", "npx vitest"), ("vitest", "vitest"), ("vitest run --reporter=dot", "vitest"), ("bunx vitest", "bunx vitest"),
        ("pnpm exec vitest run", "pnpm exec vitest"), ("npm exec vitest", "npm exec vitest"), ("pnpm dlx vitest", "pnpm dlx vitest"),
        ("npm test", "npm test"), ("npm t", "npm t"), ("npm test -- --run foo", "npm test"), ("npm --prefix web test", "npm test"),
        ("npm run test", "npm run test"), ("npm run test:unit", "npm run test:unit"), ("npm run-script test", "npm run-script test"),
        ("npm run journeys", "npm run journeys"), ("npm run stress", "npm run stress"), ("npm run vitest", "npm run vitest"),
        ("pnpm test", "pnpm test"), ("pnpm run test:unit", "pnpm run test:unit"), ("pnpm test:unit", "pnpm test:unit"),
        ("yarn test", "yarn test"), ("yarn vitest", "yarn vitest"), ("bun test", "bun test"), ("bun run test", "bun run test"),
        ("python3 scripts/journeys.py --skip-evals", "python3 scripts/journeys.py"), ("python3 -u scripts/journeys.py", "python3 scripts/journeys.py"),
        ("stress --cpu 8", "stress"), ("stress-ng --cpu 4 --timeout 60s", "stress-ng"),
        ("timeout 900 npm test", "npm test"), ("sh -c 'cd x && npm test'", "npm test"), ("cd x && npx vitest run", "npx vitest"),
        ("run-and-wake -- npm test", "npm test"), ("heavy-gate npm test", "npm test"), ("nohup npm test &", "npm test"),
        ("sudo npm test", "npm test"), ("env CI=1 npm test", "npm test"), ("x=$(npm test)", "npm test"), ("echo hi; npm test | tail -5", "npm test"),
        ("find . -name x -exec vitest run {} \\;", "vitest"),
        ("yarn workspace web test", "yarn test"), ("yarn workspace web run test:unit", "yarn run test:unit"),
        ("node node_modules/.bin/vitest run", "node vitest"), ("node node_modules/vitest/vitest.mjs run", "node vitest"),
        ("corepack pnpm test", "pnpm test"), ("corepack npm run test:unit", "npm run test:unit"),
        ("uv run scripts/journeys.py", "journeys.py"), ("uv run python3 scripts/journeys.py --skip-evals", "python3 scripts/journeys.py"),
    ]
    ALLOWED = [
        "kgate -- npm test", "run-and-wake -- kgate -- npx vitest run", "kgate --cpu 4 -- sh -c 'npm ci && npm test'",
        "run-and-wake -- scripts/kgate-journeys.sh", "scripts/kgate-journeys.sh", "scripts/main-journeys.sh",
        "git status", "git log --oneline -5", "npm run typecheck", "npm run lint", "npm ci", "npm install", "npm run build", "npm view vitest version",
        "npm install vitest", "npx tsc --noEmit src/x.ts", "node scripts/x.ts", "node --experimental-strip-types scripts/check-close-commands.ts",
        "pnpm install", "pnpm lint", "yarn build", "bun install", "python3 scripts/other.py", "python3 -m unittest tests.x",
        "echo npm test", "git commit -m 'npm test and vitest'", "grep -rn vitest package.json", "cat vitest.config.ts", "ls scripts/journeys",
        "ssh kgate-host npm test",
        "npm run typecheck:test", "npm run lint:test", "pnpm typecheck:test", "pnpm lint:test", "yarn run typecheck:test",  # light checks that mention test
        "npx playwright test", "make test", "yarn workspace web build", "corepack enable", "corepack pnpm install", "uv run scripts/other.py",
        "node node_modules/.bin/tsc --noEmit", "node scripts/vitest-notes.ts",
    ]

    def test_refused_with_kgate_named(self):
        for text, spelling in self.REFUSED:
            with self.subTest(text=text):
                message = check(text, container=True) or ""
                self.assertIn("`%s` is refused in agent sessions in the agent host pod" % spelling, message)
                self.assertIn("run-and-wake -- kgate -- <cmd>", message)

    def test_allowed(self):
        for text in self.ALLOWED:
            with self.subTest(text=text):
                self.assertIsNone(check(text, container=True))

    def test_only_the_pod_runs_it(self):
        text = "npx vitest run"
        for profile, container, want in [("personal", True, True), ("axon-work-computer", True, True), (None, True, True),
                                         ("personal", False, False), ("axon-work-computer", False, False), (None, False, False)]:
            with self.subTest(profile=profile, container=container):
                self.assertEqual(bool(check(text, profile=profile, container=container)), want)

    def test_the_rule_is_named_in_the_refusal_record(self):
        full = bash_rules.Context(**dict(ctx(container=True)._asdict(), platform="linux"))
        self.assertEqual(bash_rules.refusal("npm test", full)[0], "heavy")
        self.assertEqual(bash_rules.refusal("docker run x", full)[0], "docker")
        self.assertIsNone(bash_rules.refusal("git status", full))
        self.assertEqual(bash_rules.refusal("npx vitest run", full)[2], "npx vitest")   # the matched name, for the guard log
        self.assertIsNone(bash_rules.refusal("docker run x", full)[2])


class LiveGit(unittest.TestCase):
    """Git that changes the live coordinator checkout (the daemon runs from it) is refused on every profile; reads, fetch, the deploy's
    `merge --ff-only <sha>`, the `reset --keep <sha>` rollback and worktrees are not. HOME comes from the Context, not the test machine."""
    LIVE = "/home/cartwmic/git/coordinator"
    SHA = "0123456789abcdef0123456789abcdef01234567"
    HOME = {"HOME": "/home/cartwmic"}

    def live(self, text, cwd="/home/cartwmic/tmp-home/x", **kw):
        return check(text, env=self.HOME, cwd=cwd, **kw)

    REFUSED = [
        # the real 2026-11-16 command, in each form the live checkout can be reached
        ("cd /home/cartwmic/git/coordinator && git merge origin/main", "git merge"),
        ("git -C /home/cartwmic/git/coordinator merge origin/main", "git merge"),
        ("cd ~/git/coordinator && git merge origin/main", "git merge"),
        ("cd $HOME/git/coordinator && git merge origin/main", "git merge"),
        ('cd "$HOME/git/coordinator" && git merge origin/main', "git merge"),
        ("cd ${HOME}/git/coordinator; git merge origin/main", "git merge"),
        ("cd ~/git/coordinator/ && git merge origin/main", "git merge"),
        ("cd ~/git/coordinator/src && git merge origin/main", "git merge"),
        ("cd ~/tmp-home && cd ../git/coordinator && git merge origin/main", "git merge"),
        ("pushd ~/git/coordinator && git merge origin/main", "git merge"),
        ("git -C ~/git/coordinator merge origin/main", "git merge"),
        ('git -C "$HOME/git/coordinator" merge origin/main', "git merge"),
        ("git -C $HOME/git/coordinator merge origin/main", "git merge"),
        ("cd ~ && git -C git/coordinator merge origin/main", "git merge"),
        ("cd ~/git && git -C coordinator merge origin/main", "git merge"),
        ("git -c core.editor=true -C ~/git/coordinator --no-pager merge origin/main", "git merge"),
        ("git --git-dir=$HOME/git/coordinator/.git merge origin/main", "git merge"),
        ("git --work-tree ~/git/coordinator reset --hard", "git reset"),
        ("GIT_WORK_TREE=~/git/coordinator git checkout main", "git checkout"),
        ("cd ~/tmp-home/x && git -C ~/git/coordinator merge origin/main", "git merge"),
        ("cd ~/git/coordinator && echo hi | git merge origin/main", "git merge"),
        ("bash -c 'cd ~/git/coordinator && git merge origin/main'", "git merge"),
        ("cd ~/git/coordinator && sudo git merge origin/main", "git merge"),
        ("cd ~/git/coordinator && x=$(git merge origin/main)", "git merge"),
        ("cd ~/git/coordinator && true || git merge origin/main", "git merge"),
        # the 2026-11-11 reviewer
        ("cd ~/git/coordinator && git fetch origin pull/438/head:pr438 && git checkout pr438", "git checkout"),
        ("cd ~/git/coordinator && git checkout pr438", "git checkout"),
        # `gh pr checkout` runs git fetch and checkout in the directory it runs in
        ("cd ~/git/coordinator && gh pr checkout 438", "gh pr checkout"),
        ("cd ~/git/coordinator && gh pr co 438", "gh pr checkout"),
        ("cd $HOME/git/coordinator && gh pr checkout https://github.com/cartwmic/coordinator/pull/438", "gh pr checkout"),
        ("cd ~/git/coordinator && gh pr checkout --detach 438", "gh pr checkout"),
        ("cd ~/git/coordinator && gh pr checkout 438 -R cartwmic/coordinator", "gh pr checkout"),
        ("cd ~/git/coordinator/src && gh pr checkout 438", "gh pr checkout"),
        ("cd ~/git/coordinator && echo go; timeout 60 gh pr checkout 438 | tail -1", "gh pr checkout"),
        ("bash -c 'cd ~/git/coordinator && gh pr checkout 438'", "gh pr checkout"),
        # every changing verb
        ("cd ~/git/coordinator && git pull", "git pull"),
        ("cd ~/git/coordinator && git pull --ff-only", "git pull"),
        ("cd ~/git/coordinator && git merge --no-ff x", "git merge"),
        ("cd ~/git/coordinator && git merge --ff-only origin/main", "git merge"),
        ("cd ~/git/coordinator && git merge --ff-only main", "git merge"),
        ("cd ~/git/coordinator && git merge --ff-only 0123abc extra", "git merge"),
        ("cd ~/git/coordinator && git merge --ff-only --squash 0123abc", "git merge"),
        ("cd ~/git/coordinator && git reset --hard origin/main", "git reset"),
        ("cd ~/git/coordinator && git reset", "git reset"),
        ("cd ~/git/coordinator && git reset --keep origin/main", "git reset"),
        ("cd ~/git/coordinator && git reset --keep HEAD~1", "git reset"),
        ("cd ~/git/coordinator && git reset --hard 0123abc", "git reset"),
        ("cd ~/git/coordinator && git switch main", "git switch"),
        ("cd ~/git/coordinator && git restore .", "git restore"),
        ("cd ~/git/coordinator && git commit -m x", "git commit"),
        ("cd ~/git/coordinator && git commit --amend", "git commit"),
        ("cd ~/git/coordinator && git rebase origin/main", "git rebase"),
        ("cd ~/git/coordinator && git cherry-pick abc1234", "git cherry-pick"),
        ("cd ~/git/coordinator && git revert abc1234", "git revert"),
        ("cd ~/git/coordinator && git clean -fd", "git clean"),
        ("cd ~/git/coordinator && git am x.patch", "git am"),
        ("cd ~/git/coordinator && git apply x.patch", "git apply"),
        ("cd ~/git/coordinator && git add -A", "git add"),
        ("cd ~/git/coordinator && git rm x", "git rm"),
        ("cd ~/git/coordinator && git mv a b", "git mv"),
        ("cd ~/git/coordinator && git branch -D old", "git branch"),
        ("cd ~/git/coordinator && git branch -f main origin/main", "git branch"),
        ("cd ~/git/coordinator && git branch newbranch", "git branch"),
        ("cd ~/git/coordinator && git update-ref refs/heads/main abc1234", "git update-ref"),
        ("cd ~/git/coordinator && git symbolic-ref HEAD refs/heads/x", "git symbolic-ref"),
    ]
    ALLOWED = [
        # the deploy, the rollback and the main-run start
        "cd ~/git/coordinator && git fetch origin && git merge --ff-only 0123456789abcdef0123456789abcdef01234567",
        "git -C ~/git/coordinator merge --ff-only 0123abc",
        "cd ~/git/coordinator && git merge --ff-only 0123abcDEF",
        "cd ~/git/coordinator && git merge -q --ff-only 0123456",
        "cd ~/git/coordinator && git merge --abort",
        "git -C ~/git/coordinator merge --abort",
        "cd ~/git/coordinator && git reset --keep 0123abc",
        "cd ~/git/coordinator && git reset --keep 0123456789abcdef0123456789abcdef01234567",
        "run-and-wake -- bash -c 'cd ~/git/coordinator && { git fetch -q origin main || git fetch -q origin main; } && s=$(git show origin/main:scripts/main-journeys.sh) && exec bash -c \"$s\" main-journeys.sh'",
        "cd ~/git/coordinator && { git fetch -q origin main || git fetch -q origin main; } && git show origin/main:scripts/main-journeys.sh",
        # fetch, worktrees and reads
        "cd ~/git/coordinator && git fetch origin",
        "cd ~/git/coordinator && git fetch origin main:refs/remotes/origin/main",
        "git -C ~/git/coordinator fetch",
        "cd ~/git/coordinator && git worktree add ~/tmp-home/x origin/main",
        "cd ~/git/coordinator && git worktree add -b feat/x ~/tmp-home/reset origin/main",
        "git -C ~/git/coordinator worktree add ~/tmp-home/merge origin/main",
        "cd ~/git/coordinator && git worktree remove ~/tmp-home/x",
        "cd ~/git/coordinator && git worktree remove --force ~/tmp-home/x",
        "cd ~/git/coordinator && git worktree prune",
        "cd ~/git/coordinator && git worktree list",
        "cd ~/git/coordinator && git show origin/main:scripts/main-journeys.sh",
        "cd ~/git/coordinator && git log --oneline -5",
        "cd ~/git/coordinator && git log --grep reset --grep merge",
        "cd ~/git/coordinator && git diff origin/main",
        "cd ~/git/coordinator && git status --short",
        "cd ~/git/coordinator && git rev-parse HEAD",
        "cd ~/git/coordinator && git show stash@{0}",
        "cd ~/git/coordinator && git stash list",
        "cd ~/git/coordinator && git stash show -p",
        "cd ~/git/coordinator && git merge-base HEAD origin/main",
        "cd ~/git/coordinator && git branch",
        "cd ~/git/coordinator && git branch -a",
        "cd ~/git/coordinator && git branch --show-current",
        "cd ~/git/coordinator && git branch --list 'feat/*'",
        "cd ~/git/coordinator && git branch --contains abc1234",
        "cd ~/git/coordinator && git describe --tags",
        "cd ~/git/coordinator && git blame README.md",
        "cd ~/git/coordinator && git ls-files",
        "cd ~/git/coordinator && git remote -v",
        "cd ~/git/coordinator && git config --get remote.origin.url",
        "cd ~/git/coordinator && git push origin HEAD",
        "cd ~/git/coordinator && echo git reset --hard",
        "cd ~/git/coordinator && grep -n 'git merge' docs/deploy.md",
        # gh in a worktree or another checkout, and the PR commands that change nothing here
        "cd ~/tmp-home/x && gh pr checkout 438",
        "cd ~/git/coordinator-notes && gh pr checkout 438",
        "cd ~/git/coordinator && gh pr view 438",
        "cd ~/git/coordinator && gh pr diff 438",
        "cd ~/git/coordinator && gh pr list",
        "cd ~/git/coordinator && gh pr status",
        "cd ~/git/coordinator && echo gh pr checkout 438",
        "cd ~/git/coordinator && cd ~/tmp-home/x && gh pr checkout 438",
        'cd "$WT" && gh pr checkout 438',
        # the same verbs in a worktree or another checkout
        "cd ~/tmp-home/x && git merge origin/main",
        "cd ~/tmp-home/x && git reset --hard origin/main",
        "git -C ~/tmp-home/x checkout feat/y",
        "git -C /home/cartwmic/tmp-home/x commit -m x",
        "cd ~/git/coordinator-notes && git commit -m x",
        "cd ~/git/coordinator.old && git checkout x",
        "cd ~/git && git -C other pull",
        "cd ~/git/coordinator && cd ~/tmp-home/x && git commit -m x",
        "cd ~/git/coordinator && git -C ~/tmp-home/x commit -m x",
        "git --git-dir=$HOME/tmp-home/x/.git --work-tree=$HOME/tmp-home/x checkout y",
        "cd /Users/other/git/coordinator && git merge origin/main",
        # a target the hook cannot know
        'cd "$WT" && git commit -m x',
        "git -C $WT reset --hard",
        "cd $(mktemp -d) && git commit -m x",
        "cd $COORD && git merge origin/main",
    ]

    def test_refused_with_the_fix_named(self):
        for text, spelling in self.REFUSED:
            with self.subTest(text=text):
                message = self.live(text) or ""
                self.assertIn("`%s` in the live coordinator checkout (~/git/coordinator) is refused in agent sessions" % spelling, message)
                self.assertIn("use a git worktree (git worktree add ~/tmp-home/<name> origin/main)".capitalize(), message)
                self.assertIn("the live checkout runs the daemon; only fetch and the deploy's `git merge --ff-only <sha>` are allowed there", message)
                self.assertIn('coordinator AGENTS.md, "The live checkout"', message)

    def test_allowed(self):
        for text in self.ALLOWED:
            with self.subTest(text=text):
                self.assertIsNone(self.live(text))

    def test_a_session_whose_directory_is_the_live_checkout(self):
        for text in ["git merge origin/main", "git checkout pr438", "git pull", "git commit -m x", "git reset --hard", "git -c a=b stash",
                     "gh pr checkout 438", "gh pr co 438"]:
            with self.subTest(text=text):
                self.assertTrue(self.live(text, cwd=self.LIVE))
        for text in ["git fetch origin", "git merge --ff-only " + self.SHA, "git reset --keep 0123abc", "git status", "git log -1",
                     "git worktree add ~/tmp-home/x origin/main", "git show origin/main:scripts/main-journeys.sh", "git merge --abort",
                     "gh pr view 438", "gh pr diff 438"]:
            with self.subTest(text=text):
                self.assertIsNone(self.live(text, cwd=self.LIVE))

    def test_leaving_the_live_checkout_is_not_refused(self):
        for text in ["cd ~/tmp-home/x && git commit -m x", "git -C /home/cartwmic/tmp-home/x reset --hard", 'cd "$WT" && git commit -m x',
                     "cd ~/tmp-home/x && gh pr checkout 438",
                     "cd ~/tmp-home/x && git merge origin/main"]:
            with self.subTest(text=text):
                self.assertIsNone(self.live(text, cwd=self.LIVE))

    def test_a_command_substitution_runs_in_the_directory_of_the_command_around_it(self):
        self.assertTrue(self.live("cd ~/git/coordinator && x=$(git merge origin/main)"))
        self.assertTrue(self.live("cd ~/tmp-home/x && cd ~/git/coordinator && echo `git merge origin/main`"))
        self.assertTrue(self.live("echo $(cd ~/git/coordinator && git merge origin/main)"))
        self.assertIsNone(self.live("cd ~/git/coordinator && cd ~/tmp-home/x && x=$(git commit -m x)"))
        self.assertIsNone(self.live("x=$(git commit -m x) && cd ~/git/coordinator", cwd="/home/cartwmic/tmp-home/x"))

    def test_every_profile_and_no_profile_run_it(self):
        for profile in ("personal", "axon-work-computer", None):
            with self.subTest(profile=profile):
                self.assertTrue(self.live("cd ~/git/coordinator && git merge origin/main", profile=profile))
                self.assertIsNone(self.live("cd ~/git/coordinator && git merge --ff-only " + self.SHA, profile=profile))

    def test_home_comes_from_the_context_not_the_test_machine(self):
        text = "cd ~/git/coordinator && git merge origin/main"
        self.assertTrue(check(text, env={"HOME": "/Users/mac"}, cwd="/x"))
        self.assertIsNone(check("cd /home/cartwmic/git/coordinator && git merge origin/main", env={"HOME": "/Users/mac"}, cwd="/x"))
        self.assertTrue(check("cd /Users/mac/git/coordinator && git merge origin/main", env={"HOME": "/Users/mac"}, cwd="/x"))
        self.assertTrue(check("git -C $HOME/git/coordinator merge origin/main", env={"HOME": "/Users/mac"}, cwd="/x"))


class Stash(unittest.TestCase):
    """`git stash` that writes the stash list is refused in any directory and on every profile: every worktree of a repo shares one list
    (2026-11-24: two builders in coordinator worktrees took each other's stashes). `list` and `show` pass. The refusal names the fix."""
    REFUSED = [
        "git stash",
        "git stash push -m x",
        "git stash pop",
        "git stash save x",
        "git stash apply",
        "git stash drop",
        "git stash clear",
        "git stash store 0123abc",
        "git stash branch newbranch",
        "git stash -q",
        "git stash --keep-index",
        "git -C ~/tmp-home/x stash push -m x",
        "git -C ~/git/coordinator stash pop",
        "git -C ~/git/coordinator stash -Z",  # an unknown flag on a write: the stash rule answers before the flag table
        "git -C/home/cartwmic/tmp-home/x stash pop",
        "git --no-pager -C ~/tmp-home/x stash pop",
        "git --git-dir=/home/cartwmic/tmp-home/x/.git stash pop",
        "git -c a=b stash",
        "git --foo stash pop",
        "cd ~/tmp-home/x && git stash pop",
        "cd ~/tmp-home/x && git stash push -m x && echo done",
        "git status; git stash pop",
        "sh -c 'git stash pop'",
        "echo $(git stash pop)",
        "git stash pop || true",
        "cd ~/git/coordinator && git stash push -m x",
    ]
    ALLOWED = [
        "git stash list",
        "git stash list --oneline",
        "git stash show",
        "git stash show -p",
        "git stash show stash@{1} --stat",
        "git -C ~/tmp-home/x stash list",
        "git --no-pager stash list",
        "git -C ~/git/coordinator stash show -p",
        "cd ~/git/coordinator && git stash list",
        "git show stash@{0}",
        "git log stash@{0}",
        "git worktree add ~/tmp-home/x origin/main",
        "echo git stash pop",  # a word, not a command
    ]
    PROFILES = [{"profile": "personal"}, {"profile": "axon-work-computer"}, {"profile": "personal", "container": True}]
    WORKTREE = {"cwd": "/home/cartwmic/tmp-home/x", "env": {"HOME": "/home/cartwmic"}}

    def stash_refusal(self, text, **kw):
        return bash_rules.refusal(text, bash_rules.Context(**dict(ctx(**dict(self.WORKTREE, **kw))._asdict(), platform="linux")))

    def test_writes_are_refused_in_any_directory_and_on_every_profile(self):
        for text in self.REFUSED:
            for kw in self.PROFILES:
                with self.subTest(text=text, **kw):
                    found = self.stash_refusal(text, **kw)
                    self.assertEqual((found[0], found[2]) if found else None, ("stash", "git stash"))

    def test_read_only_forms_pass(self):
        for text in self.ALLOWED:
            with self.subTest(text=text):
                self.assertIsNone(self.stash_refusal(text))

    def test_the_refusal_names_the_fix(self):
        message = check("git -C ~/tmp-home/x stash push -m x", cwd="/x")
        self.assertIn("`git stash` is refused in agent sessions", message)
        self.assertIn("Commit your work in progress on your branch", message)
        self.assertIn("git worktree add <path> origin/main", message)
        self.assertIn("`git stash list` and `git stash show` are allowed", message)

    def test_the_live_checkout_gets_the_same_refusal(self):
        message = check("cd ~/git/coordinator && git stash pop", env={"HOME": "/home/cartwmic"}, cwd="/x")
        self.assertIn("`git stash` is refused in agent sessions", message)
        self.assertNotIn("live coordinator checkout", message)


class Credential(unittest.TestCase):
    """Credential config read raw, or hidden by a line regex, is refused on every profile; the reader and checks that print no value are not.
    REFUSED holds the command shapes of 2026-11-16 (retro proposal 10): RustDesk key and password bytes printed after a regex redaction."""
    READER = "~/.local/share/agent-harness/bin/config-show"

    REFUSED = [
        'cat ~/.config/rustdesk/RustDesk.toml | sed -E "s/(password|salt|enc_id|key_pair|id) *=.*/\\1 = <hidden>/" | head -20',
        'sed -E "s/(password|key)( *=).*/\\1\\2 <hidden>/" ~/.config/rustdesk/peers/74320507.toml | head -30',
        "sed -E 's/(password|key|id)[^=]*=.*/\\1 = <redacted>/I' ~/.config/rustdesk/peers/1171670957.toml | head -50",
        'grep -i -E "keyboard|view_style" ~/.config/rustdesk/*.toml 2>/dev/null | grep -v -i -E "password|key_pair|enc_id" | head',
        'grep -n -E "^\\[|^[a-z_]+ *=" ~/.config/rustdesk/peers/1171670957.toml | grep -v -i -E "password|key" | head -30',
        "grep -i keyboard ~/.config/rustdesk/RustDesk2.toml",
        # other readers, other credential files, other ways to name the path
        "cat ~/.config/rclone/rclone.conf",
        "cat $HOME/.config/rustdesk/RustDesk.toml",
        'cat "${HOME}/.config/rustdesk/RustDesk.toml"',
        "cat /home/u/.config/rustdesk/peers/1.toml",
        "cat < ~/.config/rclone/rclone.conf",
        "cd ~/.config/rustdesk && cat peers/1.toml",
        "cd ~/.config/rustdesk/peers && head -5 1.toml",
        "cat ~/Library/Preferences/com.carriez.RustDesk/RustDesk.toml",
        "cat 'C:\\Windows\\ServiceProfiles\\LocalService\\AppData\\Roaming\\RustDesk\\config\\RustDesk.toml'",
        "cat .env", "cat app/.env.production", "tail -n 20 prod.env", "cat ~/.netrc", "head ~/.git-credentials", "less ~/.aws/credentials",
        "cat ~/.docker/config.json", "jq . ~/.config/gh/hosts.yml", "yq .token secrets.yaml", "awk '{print $2}' ~/.config/rclone/rclone.conf",
        "bat ~/.config/agent-harness/op-service-token", "sort ~/.pgpass", "strings ~/.npmrc",
        "sudo cat ~/.config/rustdesk/RustDesk.toml", "timeout 5 cat ~/.config/rustdesk/RustDesk.toml", "sh -c 'cat ~/.config/rustdesk/RustDesk.toml'",
        "echo $(cat ~/.config/rustdesk/RustDesk.toml)", "find ~ -name x -exec cat ~/.netrc {} \\;",
        "grep -rn password ~/.config/rclone", "grep -v '^#' ~/.config/rclone/rclone.conf",
        # the pattern is skipped, the files after it still count; a `<` input counts; an -e pattern leaves every word a file
        "grep -rn token .env", "grep -e token -e key .env", "grep -A3 token ~/.netrc", "rg -g '*.toml' key ~/.config/rustdesk",
        "jq .x ~/.config/gh/hosts.yml", "jq --arg a b .x secrets.json", "grep token < .env", "cat <.env", "sed 's/a/b/' < ~/.netrc",
        "cat foo > out.txt .env", "diff .env.example .env", "cat -- .env",
        # a regex redaction of secret words, on any input
        "cat app.log | sed -E 's/(token|password)=[^ ]*/\\1=<hidden>/g'",
        "env | sed 's/\\(.*KEY.*=\\).*/\\1***/'",
        "perl -pe 's/(secret\\s*=\\s*).*/$1<redacted>/' out.txt",
        "awk '{gsub(/password=[^ ]+/, \"password=XXXX\")}1' out.txt",
        "pwsh -c \"(Get-Content f.txt) -replace '(password|key)=.*','$1=<hidden>'\"",
    ]
    ALLOWED = [
        READER + " ~/.config/rustdesk/RustDesk.toml",
        READER + " ~/.config/rustdesk/peers/1.toml --show view_style",
        "config-show ~/.config/rclone/rclone.conf --format ini",
        "ls ~/.config/rustdesk ~/.config/rustdesk/peers", "stat ~/.config/rustdesk/RustDesk.toml", "wc -l ~/.config/rclone/rclone.conf",
        "grep -l keyboard ~/.config/rustdesk/*", "grep -c password ~/.config/rustdesk/RustDesk.toml", "grep -q token .env",
        "grep -rl token ~/.config/rclone", "test -f ~/.netrc", "cp ~/.config/rclone/rclone.conf /tmp/backup.conf", "chmod 600 ~/.netrc",
        "rm ~/.config/rustdesk/RustDesk2.toml", "sed -i 's/token/TOKEN/' ~/.netrc", "sed -i.bak 's/a=1/a=2/' .env",
        "cat README.md", "cat .env.example", "cat .env.sample", "cat config.toml", "cat ~/.config/hypr/hyprland.lua", "sed -n 1,5p ~/git/foo/main.py",
        "grep -rn password src/", "grep -n token docs/auth.md", "jq .name package.json", "yq .version Chart.yaml", "cat environment.md",
        "git commit -m \"never sed s/password/<hidden>/ a config\"", "sed -i 's/password/<password>/' app.py",
        "sed 's/foo/bar/' ~/git/x/config.toml", "sed -E 's/token/TOKEN/' notes.txt", "sed 's/password/passphrase/' doc.md",
        "cat > pr.md <<'EOF'\nrefused: sed 's/password/<hidden>/' ~/.config/rustdesk/RustDesk.toml\nEOF",
        "echo cat ~/.config/rustdesk/RustDesk.toml", "grep pkill ~/git/notes.md",
        # a search pattern, filter or script that names a credential file is not a file read (review round 1, f1)
        "grep -rn '\\.env' src/", "grep -rn rclone.conf docs/", "rg RustDesk.toml ~/notes", "jq .env package.json",
        "grep -rn 'credentials.json' .", "grep -n -e .netrc README.md", "rg -g '*.env' token src/", "sed -n '/.env/p' notes.md",
        "awk '/rclone.conf/' notes.md", "yq .env.example config.yaml", "grep -rn -A3 .pgpass docs/", "jq --arg f .env '.x' package.json",
        # a `>` or `>>` target is written, not read (f2)
        "cat > .env <<'EOF'\nA=1\nEOF", "cat foo.txt > .env", "cat > ~/.netrc", "cat foo >> .env", "cat foo >.env", "cat foo 2>/dev/null >> ~/.netrc",
        "cat foo &> ~/.config/rclone/rclone.conf", "cat <<'EOF' >.env\nA=1\nEOF", "echo hi | tee .env", "sed 's/a/b/' in.txt > ~/.config/rclone/rclone.conf",
    ]

    def test_refused_shapes_name_the_reader_on_every_profile(self):
        for profile in ("personal", "axon-work-computer", None):
            for text in self.REFUSED:
                with self.subTest(profile=profile, text=text):
                    message = check(text, profile=profile, env={"HOME": "/home/u"})
                    self.assertTrue(message)
                    self.assertIn("refused in agent sessions", message)
                    self.assertIn(self.READER + " FILE", message)

    def test_allowed_shapes_pass_on_every_profile(self):
        for profile in ("personal", "axon-work-computer", None):
            for text in self.ALLOWED:
                with self.subTest(profile=profile, text=text):
                    self.assertIsNone(check(text, profile=profile, env={"HOME": "/home/u"}))

    def test_the_refusal_suggests_diffing_two_reader_outputs(self):
        self.assertIn("diff their `config-show` outputs", check("diff .env.example .env", env={"HOME": "/home/u"}))

    def test_the_read_refusal_names_the_file_and_the_show_flag(self):
        message = check("cat ~/.config/rustdesk/RustDesk.toml", env={"HOME": "/home/u"})
        self.assertIn("`cat` on credential config (RustDesk.toml)", message)
        self.assertIn("--show KEY", message)

    def test_the_refusal_never_repeats_a_secret_from_the_command(self):
        message = check("sed -E 's/(password)=hunter2/\\1=<hidden>/' ~/.config/rustdesk/RustDesk.toml", env={"HOME": "/home/u"})
        self.assertNotIn("hunter2", message)

    def test_a_relative_path_uses_the_commands_directory(self):
        self.assertTrue(check("cat peers/1.toml", cwd="/home/u/.config/rustdesk"))
        self.assertIsNone(check("cat peers/1.toml", cwd="/home/u/git/app"))


class DoorDelivery(unittest.TestCase):
    """Rule `door`: a command named by a playbook rule's `At:` line is refused once with the rule text, by asking the coordinator's renderer (here a stub script).
    The real script and `bash_rules.py` are copied beside a `door.json` that points at the stub and an index of the prefixes the renderer answers for."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.hooks = Path(self.tmp) / "hooks"
        self.hooks.mkdir()
        for name in ("refuse_pattern_kill.py", "bash_rules.py"):
            shutil.copy(HOOKS / name, self.hooks / name)
        self.state = Path(self.tmp) / "state"
        (self.state / "t3-hook").mkdir(parents=True)
        self.calls = Path(self.tmp) / "calls.jsonl"
        self.log = Path(self.tmp) / "guard.jsonl"
        self.stub = Path(self.tmp) / "stub.py"
        self.set_renderer('print(json.dumps({"text": "This call is refused in agent sessions this once (door cmd:gh pr create): rule 1234abcd"}))')
        self.set_index(["gh pr create", "kubectl"])
        self.set_config({"enabled": True, "command": [sys.executable, str(self.stub)], "state": str(self.state)})

    def set_renderer(self, body):
        self.stub.write_text("import json, sys\nask = json.load(sys.stdin)\nopen(%r, 'a').write(json.dumps(ask) + '\\n')\n%s\n" % (str(self.calls), body))

    def set_index(self, cmds):
        (self.state / "t3-hook" / "door-index.json").write_text(json.dumps({"cmds": cmds, "tools": []}))

    def set_config(self, config):
        (self.hooks / "door.json").write_text(json.dumps(config))

    def asked(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def run_hook(self, command, payload=None, profile=None):
        env = {k: v for k, v in os.environ.items() if k not in ("AGENT_HARNESS_CONTAINER", "AGENT_HARNESS_DOOR", "AGENT_HARNESS_PROFILE", "COORDINATOR_STATE_DIR")}
        if profile:
            env["AGENT_HARNESS_PROFILE"] = profile
        env["AGENT_HARNESS_GUARD_LOG"] = str(self.log)
        body = {"tool_name": "Bash", "cwd": self.tmp, "session_id": "run-1", "tool_input": {"command": command}}
        body.update(payload or {})
        return subprocess.run([sys.executable, str(self.hooks / "refuse_pattern_kill.py")], input=json.dumps(body), capture_output=True, text=True, env=env, timeout=30)

    def test_a_command_at_a_door_is_refused_with_the_rule_text_and_names_the_run(self):
        run = self.run_hook("gh pr create --title x")
        self.assertEqual(run.returncode, 2)
        self.assertIn("refused in agent sessions", run.stderr)
        self.assertIn("1234abcd", run.stderr)
        (ask,) = self.asked()
        self.assertEqual((ask["run"], ask["kind"], ask["value"], ask["adapter"]), ("run-1", "cmd", "gh pr create --title x", "claude"))

    def test_the_renderer_is_not_started_for_a_command_no_door_names(self):
        for command in ("ls -la", "gh pr view 3", "git status && echo hi", "gh pr"):
            with self.subTest(command=command):
                self.assertEqual(self.run_hook(command).returncode, 0)
        self.assertEqual(self.asked(), [])

    def test_a_prefix_matches_by_words_and_through_a_path_a_pipe_and_a_compound(self):
        for command in ("/usr/bin/kubectl get pods", "echo x | kubectl apply -f -", "cd /tmp && gh pr create"):
            with self.subTest(command=command):
                self.assertEqual(self.run_hook(command).returncode, 2)
        self.assertEqual(self.run_hook("kubectlx get pods").returncode, 0)

    def test_a_repo_flag_before_the_gh_subcommand_does_not_hide_the_door(self):
        for command in ("gh -R owner/repo pr create --title x", "gh --repo owner/repo pr create", "gh --repo=owner/repo pr create", "gh -R=owner/repo pr create"):
            with self.subTest(command=command):
                self.assertEqual(self.run_hook(command, {"session_id": "run-" + str(abs(hash(command)))}).returncode, 2)
        self.assertEqual([ask["value"] for ask in self.asked()].count("gh pr create --title x"), 1)
        self.assertEqual({ask["value"] for ask in self.asked()}, {"gh pr create --title x", "gh pr create"})
        # only the flag straight after gh is dropped: a `-R` elsewhere, and other gh commands, are as typed
        self.assertEqual(self.run_hook("gh -R owner/repo pr view 3").returncode, 0)

    def test_pr_open_reaches_its_door_on_both_profiles(self):
        self.set_index(["gh pr create", "pr-open", "kubectl"])
        self.set_renderer('print(json.dumps({"text": "This call is refused in agent sessions this once (door cmd:pr-open): rule 1234abcd"}))')
        for profile in ("personal", "axon-work-computer"):
            with self.subTest(profile=profile):
                run = self.run_hook("pr-open --edit 5 --body-file /tmp/pr-5-body.AbCdEf", {"session_id": "run-" + profile}, profile=profile)
                self.assertEqual(run.returncode, 2)
                self.assertIn("door cmd:pr-open", run.stderr)
        self.assertEqual({ask["value"] for ask in self.asked()}, {"pr-open --edit 5 --body-file /tmp/pr-5-body.AbCdEf"})

    def test_the_told_refusal_writes_no_guard_log_line_of_its_own(self):
        self.assertEqual(self.run_hook("gh pr create").returncode, 2)
        self.assertFalse(self.log.exists())

    def test_a_renderer_with_nothing_to_tell_lets_the_command_run(self):
        self.set_renderer("print('{}')")
        self.assertEqual(self.run_hook("gh pr create").returncode, 0)
        self.assertEqual(len(self.asked()), 1)

    def test_a_renderer_that_fails_or_prints_rubbish_lets_the_command_run(self):
        for body in ("sys.exit(3)", "print('not json')", "print(json.dumps({'text': 5}))"):
            with self.subTest(body=body):
                self.set_renderer(body)
                self.assertEqual(self.run_hook("gh pr create").returncode, 0)

    def records(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_a_renderer_that_fails_is_one_door_failed_line_that_names_the_failure_and_never_the_command(self):
        for body, want in (("sys.exit(3)", "exited 3"), ("print('not json')", "not readable"), ("sys.stderr.write('t3-hook --door: no playbook\\n')", "no playbook"), ("sys.stderr.write('boom\\n'); sys.exit(1)", "exited 1: boom")):
            with self.subTest(body=body):
                self.log.unlink(missing_ok=True)
                self.set_renderer(body)
                self.assertEqual(self.run_hook("gh pr create --body SECRET-VALUE").returncode, 0)
                (record,) = self.records()
                self.assertEqual((record["action"], record["run"], record["adapter"]), ("door-failed", "run-1", "claude"))
                self.assertIn(want, record["reason"])
                self.assertNotIn("SECRET-VALUE", self.log.read_text())

    def test_the_callers_wait_longer_than_the_renderer_so_a_hang_is_logged_not_killed(self):
        # A renderer that hangs is cut off after DOOR_TIMEOUT seconds and logged as a `door-failed` line. The hosts that run this script (Pi's extension, the Codex hook, Cursor's shell_guard) must not stop it first.
        inner = int(re.search(r"timeout=(\d+),\s*env=dict\(self\.env, COORDINATOR_STATE_DIR", (HOOKS / "refuse_pattern_kill.py").read_text()).group(1))
        pi = re.search(r"timeout:\s*(\d+)_(\d{3})", (ROOT / "dot_pi/private_agent/extensions/refuse-pattern-kill/index.ts").read_text())
        codex = re.search(r"timeout:\s*(\d+)\}", (ROOT / "dot_codex/modify_hooks.json.tmpl").read_text())
        cursor = re.search(r"timeout\s*=\s*(\d+)", (ROOT / "dot_cursor/hooks/executable_shell_guard.py").read_text())
        for name, outer in (("Pi", int(pi.group(1)) if pi.group(2) == "000" else None), ("Codex", int(codex.group(1))), ("Cursor", int(cursor.group(1)))):
            self.assertIsNotNone(outer, name)
            self.assertGreater(outer, inner, "%s stops the classifier after %s s, before its %s s renderer wait" % (name, outer, inner))

    def test_nothing_to_tell_and_a_told_refusal_write_no_failure_line(self):
        self.set_renderer("print('{}')")
        self.assertEqual(self.run_hook("gh pr create").returncode, 0)
        self.set_renderer("print(json.dumps({'text': 'This call is refused in agent sessions this once: x'}))")
        self.assertEqual(self.run_hook("gh pr create").returncode, 2)
        self.set_renderer("pass")
        self.assertEqual(self.run_hook("gh pr create").returncode, 0)
        self.assertEqual(self.records(), [])

    def test_no_session_id_no_config_or_a_disabled_config_means_no_door(self):
        self.assertEqual(self.run_hook("gh pr create", {"session_id": ""}).returncode, 0)
        self.set_config({"enabled": False, "command": [sys.executable, str(self.stub)], "state": str(self.state)})
        self.assertEqual(self.run_hook("gh pr create").returncode, 0)
        (self.hooks / "door.json").unlink()
        self.assertEqual(self.run_hook("gh pr create").returncode, 0)
        self.assertEqual(self.asked(), [])

    def test_a_missing_or_broken_index_means_no_door_and_a_broken_one_is_in_the_log(self):
        (self.state / "t3-hook" / "door-index.json").write_text("{not json")
        self.assertEqual(self.run_hook("gh pr create").returncode, 0)
        (record,) = self.records()
        self.assertEqual((record["action"], record["run"]), ("door-failed", "run-1"))
        self.assertIn("index could not be read", record["reason"])
        self.log.unlink()
        (self.state / "t3-hook" / "door-index.json").unlink()
        self.assertEqual(self.run_hook("gh pr create").returncode, 0)
        self.assertEqual(self.asked(), [])
        self.assertEqual(self.records(), [])  # no index yet is not a failure

    def test_a_door_json_that_is_there_and_broken_is_in_the_log_and_a_missing_one_is_not(self):
        for text in ("{not json", "[1]", json.dumps({"enabled": True}), json.dumps({"enabled": True, "command": ["x"]})):
            with self.subTest(text=text):
                self.log.unlink(missing_ok=True)
                (self.hooks / "door.json").write_text(text)
                self.assertEqual(self.run_hook("gh pr create").returncode, 0)
                (record,) = self.records()
                self.assertEqual(record["action"], "door-failed")
                self.assertIn("door.json", record["reason"])
        self.log.unlink(missing_ok=True)
        (self.hooks / "door.json").unlink()
        self.assertEqual(self.run_hook("gh pr create").returncode, 0)
        self.assertEqual(self.records(), [])

    def test_cursor_is_named_by_its_conversation_id(self):
        run = self.run_hook("gh pr create", {"session_id": None, "conversation_id": "conv-9"})
        self.assertEqual(run.returncode, 2)
        (ask,) = self.asked()
        self.assertEqual((ask["run"], ask["adapter"]), ("conv-9", "cursor"))

    def test_the_adapter_is_taken_from_the_payload_when_the_caller_names_it(self):
        self.assertEqual(self.run_hook("gh pr create", {"adapter": "pi"}).returncode, 2)
        self.assertEqual(self.asked()[0]["adapter"], "pi")

    def test_another_rule_refuses_first_and_the_renderer_is_not_asked(self):
        self.set_index(["gh pr create", "gh pr merge"])
        run = self.run_hook("gh pr merge 3 && gh pr create", profile="personal")
        self.assertEqual(run.returncode, 2)
        self.assertNotIn("1234abcd", run.stderr)
        self.assertEqual(self.asked(), [])

    def render(self, profile, extra=""):
        home = Path(self.tmp) / ("home-" + profile + str(len(extra)))
        home.mkdir()
        config = Path(self.tmp) / (profile + str(len(extra)) + ".yaml")
        config.write_text("data:\n  profile: %s\n%s" % (profile, extra))
        run = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(config), "--config-format", "yaml", "--destination", str(home), "execute-template"],
                             input=(HOOKS / "door.json.tmpl").read_text(), capture_output=True, text=True, env=dict(os.environ, HOME=str(home)), timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        return home, json.loads(run.stdout)

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
    def test_the_rendered_file_names_each_profiles_own_renderer_and_state_directory(self):
        home, personal = self.render("personal")
        self.assertEqual(personal["state"], str(home / ".local/share/coordinator"))
        self.assertEqual(personal["command"][-2:], [str(home / "git/coordinator/src/t3-hook/hook.ts"), "--door"])
        home, work = self.render("axon-work-computer")
        self.assertEqual(work["state"], str(home / ".local/share/coordinator-work"))
        self.assertEqual(work["command"][-2:], [str(home / "coordinator-work/src/t3-hook/hook.ts"), "--door"])
        for config in (personal, work):
            self.assertIs(config["enabled"], True)

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is not installed")
    def test_remove_coordinator_hook_renders_the_door_off(self):
        _, off = self.render("personal", "  agentHost:\n    removeCoordinatorHook: true\n")
        self.assertIs(off["enabled"], False)
        _, on = self.render("personal", "  agentHost:\n    removeCoordinatorHook: false\n")
        self.assertIs(on["enabled"], True)

    def test_a_renderer_that_tells_once_per_run_lets_the_same_command_pass_the_second_time(self):
        told = Path(self.tmp) / "told.json"
        self.set_renderer("""
import os
told = %r
seen = json.load(open(told)) if os.path.exists(told) else []
if ask["run"] in seen:
    print("{}")
else:
    json.dump(seen + [ask["run"]], open(told, "w"))
    print(json.dumps({"text": "This call is refused in agent sessions this once (door cmd:gh pr create): rule 1234abcd"}))
""" % str(told))
        self.assertEqual(self.run_hook("gh pr create").returncode, 2)
        self.assertEqual(self.run_hook("gh pr create").returncode, 0)
        self.assertEqual(self.run_hook("gh pr create", {"session_id": "run-2"}).returncode, 2)


class Hook(unittest.TestCase):
    """The real script, copied beside a `profile` file in a temp dir."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.hooks = Path(cls.tmp) / "hooks"
        cls.hooks.mkdir()
        for name in ("refuse_pattern_kill.py", "bash_rules.py"):
            shutil.copy(HOOKS / name, cls.hooks / name)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_hook(self, command, tool="Bash", profile=None, argv=None, hooks=None, cwd=None, extra_env=None):
        env = {k: v for k, v in os.environ.items() if k != "AGENT_HARNESS_PROFILE"}
        if profile:
            env["AGENT_HARNESS_PROFILE"] = profile
        env.update(extra_env or {})
        payload = {"tool_name": tool, "cwd": cwd or self.tmp, "tool_input": {"command": command}}
        if tool is None:
            del payload["tool_name"]
        return subprocess.run([sys.executable, str((hooks or self.hooks) / "refuse_pattern_kill.py")] + (argv or []),
                              input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=30)

    def set_profile_file(self, text):
        path = self.hooks / "profile"
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text)

    def test_the_profile_comes_from_the_file_beside_the_script(self):
        merge = "gh pr merge 12"
        for text, want in [("personal\n", 2), ("axon-work-computer\n", 2), ("termux\n", 0), (None, 0), ("", 0)]:
            with self.subTest(profile_file=text):
                self.set_profile_file(text)
                self.assertEqual(self.run_hook(merge).returncode, want)
        self.set_profile_file(None)

    def test_the_env_var_overrides_the_file(self):
        self.set_profile_file("termux\n")
        self.assertEqual(self.run_hook("gh pr merge 12", profile="personal").returncode, 2)
        self.set_profile_file("personal\n")
        self.assertEqual(self.run_hook("gh pr merge 12", profile="termux").returncode, 0)
        self.set_profile_file(None)

    def test_poll_and_heredoc_run_with_no_profile_at_all(self):
        self.set_profile_file(None)
        self.assertEqual(self.run_hook("until ok; do sleep 1; done").returncode, 2)
        self.assertEqual(self.run_hook("cat <<EOF\n`date`\nEOF").returncode, 2)

    def test_monitor_skips_sleep_poll_only(self):
        self.assertEqual(self.run_hook("until ok; do sleep 1; done", tool="Monitor").returncode, 0)
        self.assertEqual(self.run_hook("until ok; do sleep 1; done", tool="Bash").returncode, 2)
        self.assertEqual(self.run_hook("until ok; do sleep 1; done", tool=None).returncode, 2)  # Pi sends no tool name
        self.assertEqual(self.run_hook("pkill x", tool="Monitor").returncode, 2)
        self.assertEqual(self.run_hook("gh pr merge 1", tool="Monitor", profile="personal").returncode, 2)

    def test_every_refusal_carries_the_phrase_the_pi_extension_looks_for(self):
        for command, profile in [("until ok; do sleep 1; done", None), ("cat <<EOF\n`x`\nEOF", None), ("gh pr merge 1", "personal"),
                                 ("gh pr create --body-file b.md", "personal"),
                                 ("kubectl --context a get no", "personal"), ("pkill x", None),
                                 ("cd ~/git/coordinator && git merge origin/main", None),
                                 ("cat ~/.config/rustdesk/RustDesk.toml", None)] + (
                [("docker build .", "personal")] if sys.platform.startswith("linux") else []):
            with self.subTest(command=command):
                run = self.run_hook(command, profile=profile)
                self.assertEqual(run.returncode, 2)
                self.assertIn("refused in agent sessions", run.stderr)

    def test_the_command_flag_works_too(self):
        run = self.run_hook("", argv=["--command", "until ok; do sleep 1; done"])
        self.assertEqual(run.returncode, 2)
        self.assertIn("run-and-wake", run.stderr)

    def test_an_error_inside_the_new_rules_allows_the_command(self):
        broken = Path(self.tmp) / "broken"
        broken.mkdir()
        shutil.copy(HOOKS / "refuse_pattern_kill.py", broken / "refuse_pattern_kill.py")
        (broken / "bash_rules.py").write_text("def refusal(text, ctx):\n    raise RuntimeError('boom')\nContext = lambda **kw: None\n")
        run = self.run_hook("until ok; do sleep 1; done", hooks=broken)
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        self.assertEqual(self.run_hook("pkill x", hooks=broken).returncode, 2)  # the old check still works
        (broken / "bash_rules.py").unlink()  # a missing sibling allows too
        self.assertEqual(self.run_hook("until ok; do sleep 1; done", hooks=broken).returncode, 0)

    def set_container_file(self, text):
        path = self.hooks / "container"
        if text is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(text)

    def run_pod_hook(self, command, container_env=None, log=None):
        env = {k: v for k, v in os.environ.items() if k not in ("AGENT_HARNESS_CONTAINER", "AGENT_HARNESS_GUARD_LOG")}
        if container_env is not None:
            env["AGENT_HARNESS_CONTAINER"] = container_env
        env["AGENT_HARNESS_GUARD_LOG"] = str(log or os.devnull)
        payload = {"tool_name": "Bash", "cwd": self.tmp, "tool_input": {"command": command}}
        return subprocess.run([sys.executable, str(self.hooks / "refuse_pattern_kill.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=30)

    def test_the_pod_comes_from_the_container_file_beside_the_script(self):
        for text, want in [("true\n", 2), ("false\n", 0), (None, 0), ("", 0)]:
            with self.subTest(container_file=text):
                self.set_container_file(text)
                run = self.run_pod_hook("npx vitest run")
                self.assertEqual(run.returncode, want)
                if want:
                    self.assertIn("kgate", run.stderr)
        self.set_container_file(None)

    def test_the_container_env_var_overrides_the_file(self):
        self.set_container_file("false\n")
        self.assertEqual(self.run_pod_hook("npm test", container_env="true").returncode, 2)
        self.set_container_file("true\n")
        self.assertEqual(self.run_pod_hook("npm test", container_env="false").returncode, 0)
        self.set_container_file(None)

    def test_the_heavy_refusal_carries_the_phrase_the_pi_extension_blocks_on(self):   # refuse-pattern-kill/index.ts REFUSAL_MARK
        self.set_container_file("true\n")
        run = self.run_pod_hook("npx vitest run")
        self.assertEqual(run.returncode, 2)
        self.assertIn("refused in agent sessions", run.stderr)
        self.set_container_file(None)

    def test_in_the_pod_kgate_runs_and_light_commands_pass_through_the_real_script(self):
        self.set_container_file("true\n")
        for command in ("kgate -- npm test", "run-and-wake -- kgate -- npx vitest run", "git status", "npm run typecheck"):
            with self.subTest(command=command):
                self.assertEqual(self.run_pod_hook(command).returncode, 0)
        self.set_container_file(None)

    def test_a_refusal_is_one_json_line_in_the_guard_log(self):
        log = Path(self.tmp) / "state" / "guard.jsonl"
        log.parent.mkdir(exist_ok=True)
        log.unlink(missing_ok=True)
        self.assertEqual(self.run_pod_hook("npm test", container_env="true", log=log).returncode, 2)
        self.assertEqual(self.run_pod_hook("git status", container_env="true", log=log).returncode, 0)  # an allowed command writes nothing
        self.assertEqual(self.run_pod_hook("npm test", container_env="false", log=log).returncode, 0)
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]["action"], records[0]["rule"], records[0]["tool"]), ("refuse", "heavy", "Bash"))
        self.assertNotIn("command", records[0])  # a refused command can hold a token
        self.assertRegex(records[0]["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")

    def test_the_record_holds_the_matched_command_and_the_directory_but_not_the_rest_of_the_command(self):
        log = Path(self.tmp) / "state" / "guard.jsonl"
        log.parent.mkdir(exist_ok=True)
        log.unlink(missing_ok=True)
        secret = "ghp_notARealToken123456789"
        self.assertEqual(self.run_pod_hook("API_KEY=%s npx vitest run --reporter=%s" % (secret, secret), container_env="true", log=log).returncode, 2)
        self.assertEqual(self.run_pod_hook("npm run test:unit -- --token %s" % secret, container_env="true", log=log).returncode, 2)
        self.assertEqual(self.run_pod_hook("until ok; do sleep 1; done", container_env="true", log=log).returncode, 2)  # a rule with no fixed list
        text = log.read_text()
        self.assertNotIn(secret, text)
        self.assertNotIn("--reporter", text)
        self.assertNotIn("--token", text)
        records = [json.loads(line) for line in text.splitlines()]
        self.assertEqual([(r["rule"], r["matched"]) for r in records], [("heavy", "npx vitest"), ("heavy", "npm run test:unit"), ("poll", None)])
        for record in records:
            self.assertEqual(record["cwd"], self.tmp)

    def test_a_record_without_a_tool_name_is_still_logged(self):   # the Pi extension sends tool_name "bash"; other callers may send none
        log = Path(self.tmp) / "state" / "guard.jsonl"
        log.parent.mkdir(exist_ok=True)
        log.unlink(missing_ok=True)
        env = {k: v for k, v in os.environ.items() if k != "AGENT_HARNESS_GUARD_LOG"}
        env.update(AGENT_HARNESS_CONTAINER="true", AGENT_HARNESS_GUARD_LOG=str(log))
        for payload, tool in (({"tool_name": "bash", "tool_input": {"command": "npm test"}}, "bash"), ({"tool_input": {"command": "npm test"}}, None)):
            run = subprocess.run([sys.executable, str(self.hooks / "refuse_pattern_kill.py")], input=json.dumps(payload),
                                 capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(run.returncode, 2)
        self.assertEqual([json.loads(line)["tool"] for line in log.read_text().splitlines()], ["bash", None])

    @unittest.skipUnless(sys.platform.startswith("linux"), "the docker rule runs on Linux only")
    def test_the_reviewers_real_docker_runs_are_refused_through_the_real_script(self):
        """Homelab#288 round 2: the reviewer ran the pinned Yamtrack image with `docker run` (recorded tool calls in fixtures/)."""
        for name in ("docker-run-yamtrack-reviewer-1.json", "docker-run-yamtrack-reviewer-2.json"):
            payload = json.loads((Path(__file__).parent / "fixtures" / name).read_text())
            env = dict(os.environ, AGENT_HARNESS_PROFILE="personal")
            with self.subTest(fixture=name):
                run = subprocess.run([sys.executable, str(self.hooks / "refuse_pattern_kill.py")], input=json.dumps(payload),
                                     capture_output=True, text=True, env=env, timeout=30)
                self.assertEqual(run.returncode, 2)
                self.assertIn("`docker run` is refused in agent sessions", run.stderr)
                self.assertIn("kgate", run.stderr)
                self.assertIn("throwaway namespace", run.stderr)

    @unittest.skipUnless(sys.platform.startswith("linux"), "the docker rule runs on Linux only")
    def test_docker_is_left_alone_on_the_work_profile_and_with_no_profile(self):
        self.set_profile_file(None)
        self.assertEqual(self.run_hook("docker run alpine", profile="personal").returncode, 2)
        self.assertEqual(self.run_hook("docker run alpine", profile="axon-work-computer").returncode, 0)
        self.assertEqual(self.run_hook("docker run alpine").returncode, 0)
        self.assertEqual(self.run_hook("docker ps", profile="personal").returncode, 0)

    def run_fixture(self, name, home="/home/cartwmic", profile=None):
        payload = json.loads((Path(__file__).parent / "fixtures" / name).read_text())
        env = {k: v for k, v in os.environ.items() if k != "AGENT_HARNESS_PROFILE"}
        env["HOME"] = home
        if profile:
            env["AGENT_HARNESS_PROFILE"] = profile
        return subprocess.run([sys.executable, str(self.hooks / "refuse_pattern_kill.py")], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=30)

    def test_the_real_live_checkout_commands_are_refused_through_the_real_script(self):
        """2026-11-16: a builder ran `git merge origin/main` in ~/git/coordinator (and reset it 13 s later); 2026-11-11: a reviewer checked out
        PR #438 there and the daemon restarted onto PR code. The fixtures are hand-built in the hook's PreToolUse JSON shape from the
        command texts (no transcript of the 11-11 command survives, so both its likely forms are here: `git checkout` and `gh pr checkout`)."""
        for name, spelling in [("live-git-merge-cd.json", "git merge"), ("live-git-merge-C.json", "git merge"),
                               ("live-git-checkout-pr438.json", "git checkout"), ("live-gh-pr-checkout-438-cd.json", "gh pr checkout"),
                               ("live-gh-pr-checkout-438-cwd.json", "gh pr checkout")]:
            for profile in ("personal", "axon-work-computer", None):
                with self.subTest(fixture=name, profile=profile):
                    run = self.run_fixture(name, profile=profile)
                    self.assertEqual(run.returncode, 2)
                    self.assertIn("`%s` in the live coordinator checkout" % spelling, run.stderr)
                    self.assertIn("refused in agent sessions", run.stderr)
                    self.assertIn("git worktree add ~/tmp-home/<name> origin/main", run.stderr)

    def test_the_deploy_and_the_main_run_start_pass_through_the_real_script(self):
        for name in ("live-git-ffonly-deploy.json", "live-git-main-run-start.json", "live-git-merge-abort.json"):
            with self.subTest(fixture=name):
                run = self.run_fixture(name)
                self.assertEqual((run.returncode, run.stderr), (0, ""))

    def test_the_fixture_home_decides_not_the_machine_it_runs_on(self):
        run = self.run_fixture("live-git-merge-cd.json", home="/Users/mac")
        self.assertEqual(run.returncode, 0)  # that command names /home/cartwmic/git/coordinator, which is no checkout of /Users/mac

    def test_the_real_rustdesk_commands_are_refused_through_the_real_script(self):
        """2026-11-16 (retro proposal 10): agents printed RustDesk key and password bytes after a line-regex redaction. The fixtures hold the
        command texts as the sessions ran them (no values in them), in the hook's PreToolUse JSON shape."""
        names = ("credential-rustdesk-cat-sed.json", "credential-rustdesk-sed-peer.json", "credential-rustdesk-grep-v.json",
                 "credential-powershell-replace.json")
        for profile in ("personal", "axon-work-computer"):
            for name in names:
                with self.subTest(fixture=name, profile=profile):
                    run = self.run_fixture(name, profile=profile)
                    self.assertEqual(run.returncode, 2)
                    self.assertIn("refused in agent sessions", run.stderr)
                    self.assertIn("agent-harness/bin/config-show FILE", run.stderr)

    def test_the_reader_and_an_ordinary_read_pass_through_the_real_script(self):
        for command in ("~/.local/share/agent-harness/bin/config-show ~/.config/rustdesk/RustDesk.toml", "cat README.md", "grep -l key ~/.config/rustdesk/*"):
            with self.subTest(command=command):
                run = self.run_hook(command, profile="personal")
                self.assertEqual((run.returncode, run.stderr), (0, ""))

    def test_the_rendered_profile_file_is_just_the_profile_name(self):
        text = (HOOKS / "profile.tmpl").read_text()
        self.assertEqual(text, "{{ .profile }}\n")

    def test_a_stash_write_is_refused_and_a_read_passes_through_the_real_script(self):
        """The commands of the 2026-11-24 incident, sent to the real script the way Claude Code sends them: JSON on stdin, from a worktree.
        Three writes are refused with the fix on stderr; `git stash list` passes. Every profile file gives the same answer."""
        worktree = f"{self.tmp}/wt-a"
        for profile in (None, "personal", "axon-work-computer"):
            for command, want in [("git stash", 2), ("git stash pop", 2), ("git -C %s stash push -m x" % worktree, 2), ("git stash list", 0)]:
                with self.subTest(profile=profile, command=command):
                    run = self.run_hook(command, profile=profile, cwd=worktree)
                    self.assertEqual(run.returncode, want, run.stderr)
                    if want == 2:
                        self.assertIn("refused in agent sessions", run.stderr)
                        self.assertIn("git worktree add <path> origin/main", run.stderr)

    def test_a_stash_refusal_writes_one_guard_log_line_naming_the_rule(self):
        log = Path(self.tmp) / "guard.jsonl"
        run = self.run_hook("git stash pop", extra_env={"AGENT_HARNESS_GUARD_LOG": str(log)})
        self.assertEqual(run.returncode, 2, run.stderr)
        record = json.loads(log.read_text().splitlines()[-1])
        self.assertEqual((record["action"], record["rule"], record["matched"]), ("refuse", "stash", "git stash"))


class LiveGitWorkCheckout(unittest.TestCase):
    """The work coordinator runs from its own checkout (~/coordinator-work, or the path in local data), which the `coordinator-instance` file names:
    git that changes it is refused as in ~/git/coordinator, and the same file's other path stays protected."""
    HOME = {"HOME": "/Users/test"}
    WORK = "/Users/test/coordinator-work"

    def work(self, text, cwd="/Users/test/tmp-home/x", repo=WORK, **kw):
        return check(text, env=self.HOME, cwd=cwd, profile="axon-work-computer", coordinator_repo=repo, **kw)

    def test_the_work_checkout_is_refused(self):
        for text, spelling in [("cd /Users/test/coordinator-work && git merge origin/main", "git merge"),
                               ("git -C /Users/test/coordinator-work commit -m x", "git commit"),
                               ("cd ~/coordinator-work && git checkout main", "git checkout"),
                               ("cd /Users/test/coordinator-work/src && git add -A", "git add")]:
            with self.subTest(text=text):
                self.assertIn(spelling, self.work(text) or "")

    def test_gh_pr_checkout_in_the_work_checkout_is_refused(self):
        self.assertIn("gh pr checkout", self.work("gh pr checkout 5", cwd="/Users/test/coordinator-work") or "")
        self.assertIsNone(self.work("gh pr checkout 5", cwd="/Users/test/tmp-home/x"))

    def test_a_path_set_in_local_data_is_refused_too(self):
        self.assertIn("git merge", self.work("git -C /Volumes/Workshop/work/coordinator merge origin/main", repo="/Volumes/Workshop/work/coordinator") or "")

    def test_the_old_path_is_still_refused_on_work(self):
        self.assertIn("git merge", self.work("git -C /Users/test/git/coordinator merge origin/main") or "")

    def test_the_refusal_names_the_work_checkout_not_git_coordinator(self):
        msg = self.work("git -C /Users/test/coordinator-work merge origin/main") or ""
        self.assertIn("(/Users/test/coordinator-work)", msg)
        self.assertNotIn("~/git/coordinator", msg)
        self.assertIn("(/Users/test/coordinator-work)", self.work("gh pr checkout 5", cwd="/Users/test/coordinator-work") or "")

    def test_the_merge_refusals_name_the_work_merge_script(self):
        for text in ["gh pr merge 12 -R cartwmic/coordinator", "gh pr merge 12 -R acme/app"]:
            with self.subTest(text=text):
                msg = self.work(text) or ""
                self.assertIn("/Users/test/coordinator-work/scripts/merge-pr.sh", msg)
                self.assertNotIn("~/git/coordinator", msg)

    def test_the_other_pr_and_coordinator_merge_refusals_name_the_work_merge_script(self):
        script = "/Users/test/coordinator-work/scripts/merge-pr.sh"
        other = self.work("ci-main-status --merge-gate acme/app && pr-body-check acme/app 5 && gh pr merge 12 -R acme/app") or ""
        self.assertIn(script, other)
        self.assertNotIn("~/git/coordinator", other)
        coordinator = self.work("ci-main-status --merge-gate cartwmic/coordinator && pr-body-check cartwmic/coordinator 12 && gh pr merge 12 -R cartwmic/coordinator") or ""
        self.assertIn(script, coordinator)
        self.assertNotIn("~/git/coordinator", coordinator)

    def test_personal_refusals_still_name_git_coordinator(self):
        msg = check("git -C /Users/test/git/coordinator merge origin/main", env=self.HOME, cwd="/Users/test/tmp-home/x", profile="personal") or ""
        self.assertIn("(~/git/coordinator)", msg)
        merge = check("gh pr merge 12 -R acme/app", env=self.HOME, cwd="/Users/test/tmp-home/x", profile="personal") or ""
        self.assertIn("~/git/coordinator/scripts/merge-pr.sh", merge)

    def test_reads_worktrees_and_other_checkouts_pass(self):
        for text in ["git -C /Users/test/coordinator-work log -3", "git -C /Users/test/coordinator-work fetch",
                     "git -C /Users/test/coordinator-work worktree add ~/tmp-home/x origin/main",
                     "git -C /Users/test/coordinator-work-notes commit -m x", "cd /Users/test/tmp-home/x && git commit -m x"]:
            with self.subTest(text=text):
                self.assertIsNone(self.work(text))

    def test_without_the_file_the_work_checkout_is_not_known(self):
        self.assertIsNone(self.work("git -C /Users/test/coordinator-work commit -m x", repo=None))


if __name__ == "__main__":
    unittest.main()
