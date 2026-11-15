"""The four bash_rules checks (sleep-poll, heredoc, kube context, merge): what each refuses and what it lets through.

Most cases call bash_rules.check with a Context (pure); the profile file, the Monitor tool, fail-open and the message the Pi extension
looks for go through the real hook script in a temp copy. Nothing here writes inside the repo.
"""
import json
import os
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

HOMELAB = "kubernetes-admin@kubernetes"
KUBE = {"/kc/homelab": "current-context: %s\n" % HOMELAB, "/kc/other": "apiVersion: v1\ncurrent-context: axon-aks-prod\n",
        "/kc/none": "apiVersion: v1\ncontexts: []\n"}


def ctx(profile="personal", tool="Bash", env=None, cwd="/work", files=None, origins=None):
    files = KUBE if files is None else files
    origins = origins or {}
    return bash_rules.Context(tool=tool, profile=profile, env=env or {}, cwd=cwd, read_file=files.get,
                              origin_of=lambda directory: origins.get(directory))


def check(text, **kw):
    return bash_rules.check(text, ctx(**kw))


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
        'gh pr create --body "$(cat <<\'EOF\'\nRuns `make test` first.\nEOF\n)"',
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
                self.assertIn("ecd63156, 385acc43 and ccc6c94b", message)

    def test_the_merge_gate_form_with_both_checks_is_allowed_and_the_exit_code_workaround_is_not(self):
        self.assertIsNone(check("ci-main-status --merge-gate X && pr-body-check X 5 && gh pr merge 5"))
        self.assertIsNone(check("pr-body-check dotfiles 5 && ci-main-status --merge-gate dotfiles && gh pr merge 5 --squash -R cartwmic/dotfiles"))
        self.assertIn("pr-body-check", check("ci-main-status --merge-gate X && gh pr merge 5"))
        message = check("ci-main-status X; [ $? -le 2 ] && gh pr merge 5")
        self.assertIsNotNone(message)
        self.assertIn("merge-pr.sh", message)

    def test_the_refusal_names_a_command_that_satisfies_both_gates(self):
        # The command the refusal prints, with <repo>/<pr> filled in, must itself pass the hook.
        message = check("gh pr merge 12")
        self.assertIn("ci-main-status --merge-gate <repo> && pr-body-check <repo> <pr> && gh pr merge <pr>", message)
        self.assertIsNone(check("ci-main-status --merge-gate dotfiles && pr-body-check dotfiles 12 && gh pr merge 12"))

    def test_both_checks_first_allow_a_repo_that_is_not_the_coordinator(self):
        for text in ["ci-main-status homelab && pr-body-check homelab 182 && gh pr merge 182 -R cartwmic/cartwmic-homelab-v2 --squash",
                     "pr-body-check homelab 182 && ci-main-status homelab && gh pr merge 182 -R cartwmic/cartwmic-homelab-v2 --squash",
                     "ci-main-status dotfiles && pr-body-check dotfiles 5 && gh pr merge 5 -R cartwmic/dotfiles --merge",
                     "pr-body-check dotfiles 5 && ci-main-status dotfiles && pr-body-check dotfiles 1 && gh pr merge 5 -R cartwmic/dotfiles --merge",
                     "cd /tmp && ci-main-status homelab && pr-body-check homelab 182 && gh pr merge 182 --squash",
                     "ci-main-status homelab && pr-body-check homelab 182 &&\n gh pr merge 182",
                     "ci-main-status homelab && pr-body-check homelab 182 && cd /tmp && gh pr merge 182",
                     "ci-main-status homelab && pr-body-check homelab 182 && sh -c 'gh pr merge 182'",
                     "ci-main-status homelab && pr-body-check homelab 182 && gh pr merge 182 -R cartwmic/homelab"]:
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
                self.assertIn("ecd63156, 385acc43 and ccc6c94b", message)

    def test_the_coordinator_is_refused_even_after_ci_main_status(self):
        for text in ["ci-main-status coordinator && pr-body-check coordinator 440 && gh pr merge 440 -R cartwmic/coordinator --merge",
                     "ci-main-status coordinator && pr-body-check coordinator 440 && gh pr merge 440 --repo cartwmic/coordinator",
                     "ci-main-status coordinator && pr-body-check coordinator 440 && gh pr merge 440 --repo=cartwmic/coordinator.git",
                     "ci-main-status coordinator && pr-body-check coordinator 440 && gh pr merge 440 -R https://github.com/cartwmic/coordinator"]:
            with self.subTest(text=text):
                self.assertIn("merge-pr.sh", check(text))

    def test_the_directory_decides_when_there_is_no_repo_flag(self):
        origins = {"/repos/coord": "git@github.com:cartwmic/coordinator.git", "/repos/other": "https://github.com/cartwmic/dotfiles.git",
                   "/work": "https://github.com/cartwmic/coordinator"}
        self.assertIn("merge-pr.sh", check("cd /repos/coord && ci-main-status coordinator && pr-body-check coordinator 1 && gh pr merge 1", origins=origins))
        self.assertIn("merge-pr.sh", check("ci-main-status coordinator && pr-body-check coordinator 1 && gh pr merge 1", origins=origins))  # the hook cwd
        self.assertIsNone(check("cd /repos/other && ci-main-status dotfiles && pr-body-check dotfiles 1 && gh pr merge 1", origins=origins))
        self.assertIsNone(check("cd /repos/coord && ci-main-status coordinator && pr-body-check coordinator 1 && cd /repos/other && gh pr merge 1", origins=origins))
        self.assertIsNone(check("ci-main-status x && pr-body-check x 1 && gh pr merge 1 -R cartwmic/dotfiles", origins=origins))  # -R decides, not the cwd
        self.assertIsNone(check("cd /nowhere && ci-main-status x && pr-body-check x 1 && gh pr merge 1", origins=origins))
        self.assertIsNone(check("cd $d && ci-main-status x && pr-body-check x 1 && gh pr merge 1", origins=origins))

    def test_a_real_checkout_whose_origin_is_the_coordinator(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", "-C", tmp, "init", "-q"], check=True)
            subprocess.run(["git", "-C", tmp, "remote", "add", "origin", "https://github.com/cartwmic/coordinator.git"], check=True)
            self.assertIn("merge-pr.sh", bash_rules.check("cd %s && ci-main-status coordinator && pr-body-check coordinator 1 && gh pr merge 1" % tmp,
                                                        bash_rules.Context(profile="personal", env={}, cwd="/")))
            self.assertIsNone(bash_rules.origin_of(os.path.join(tmp, "missing")))
            self.assertIsNone(bash_rules.origin_of(None))
        with tempfile.TemporaryDirectory() as tmp:  # not a git checkout
            self.assertIsNone(bash_rules.origin_of(tmp))

    def test_the_gated_paths_are_not_gh_commands_the_hook_sees(self):
        for text in ["~/.local/share/coordinator-workspace/bin/merge-pr.sh 440",
                     "COORDINATOR_STATE_DIR=$HOME/.local/share/coordinator node --experimental-strip-types ~/git/coordinator/src/playbook/cli.ts retire fab9b713 --pr --merge",
                     "loop_engine_bump.py v0.49.1", "agent_kit_bump.py v1.4.0", "gh pr view 12", "gh pr list", "echo gh pr merge 12",
                     "git merge main"]:
            with self.subTest(text=text):
                self.assertIsNone(check(text))

    def test_the_work_profile_and_no_profile_do_not_run_it(self):
        for profile in ("axon-work-computer", None):
            self.assertIsNone(check("gh pr merge 12", profile=profile))


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

    def run_hook(self, command, tool="Bash", profile=None, argv=None, hooks=None):
        env = {k: v for k, v in os.environ.items() if k != "AGENT_HARNESS_PROFILE"}
        if profile:
            env["AGENT_HARNESS_PROFILE"] = profile
        payload = {"tool_name": tool, "cwd": self.tmp, "tool_input": {"command": command}}
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
        for text, want in [("personal\n", 2), ("axon-work-computer\n", 0), (None, 0), ("", 0)]:
            with self.subTest(profile_file=text):
                self.set_profile_file(text)
                self.assertEqual(self.run_hook(merge).returncode, want)
        self.set_profile_file(None)

    def test_the_env_var_overrides_the_file(self):
        self.set_profile_file("axon-work-computer\n")
        self.assertEqual(self.run_hook("gh pr merge 12", profile="personal").returncode, 2)
        self.set_profile_file("personal\n")
        self.assertEqual(self.run_hook("gh pr merge 12", profile="axon-work-computer").returncode, 0)
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
                                 ("kubectl --context a get no", "personal"), ("pkill x", None)]:
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
        (broken / "bash_rules.py").write_text("def check(text, ctx):\n    raise RuntimeError('boom')\nContext = lambda **kw: None\n")
        run = self.run_hook("until ok; do sleep 1; done", hooks=broken)
        self.assertEqual((run.returncode, run.stderr), (0, ""))
        self.assertEqual(self.run_hook("pkill x", hooks=broken).returncode, 2)  # the old check still works
        (broken / "bash_rules.py").unlink()  # a missing sibling allows too
        self.assertEqual(self.run_hook("until ok; do sleep 1; done", hooks=broken).returncode, 0)

    def test_the_rendered_profile_file_is_just_the_profile_name(self):
        text = (HOOKS / "profile.tmpl").read_text()
        self.assertEqual(text, "{{ .profile }}\n")


if __name__ == "__main__":
    unittest.main()
