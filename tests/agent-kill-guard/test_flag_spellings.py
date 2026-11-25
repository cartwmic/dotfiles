"""Every spelling of a flag a rule relies on gives the rule the same verdict as the long form.

The rules read gh, git, docker, kubectl, grep and the package managers' flags. Each tool's flag library takes more than `--name value`: `--name=value`, `-n value`, `-nvalue`,
`-n=value`, a cluster of short flags, and `--` to end the flags. A rule that reads only some of these is a hole (the PR-body rule once missed `-fbody=x`, then `-t`). This file
checks the verdict, not the reader: for each case the long form and every other spelling must be refused by the same rule with the same message, or all be allowed.
It uses only `bash_rules.refusal`, so the same file runs against an older bash_rules.py to show which spellings it missed.
"""
import unittest

import test_bash_rules as base

PR_FILE = "/tmp/pr-1-body.aB3xY9"
EDIT_FILE = "/tmp/pr-5-body.aB3xY9"
LIVE = "/home/cartwmic/git/coordinator"
SHA = "0123456789abcdef0123456789abcdef01234567"
LIVE_KW = {"env": {"HOME": "/home/cartwmic"}, "cwd": "/home/cartwmic/tmp-home/x"}
GATES = "ci-main-status --merge-gate coordinator && pr-body-check coordinator 5 && "


def verdict(text, **kw):
    """(rule, message) the hook gives the command, or None when it is allowed."""
    found = base.bash_rules.refusal(text, base.bash_rules.Context(**dict(base.ctx(**kw)._asdict(), platform="linux")))
    return (found[0], str(found[1])) if found else None


# (name, Context keywords, the long form, its other spellings, the rule that refuses the long form or None when it is allowed)
CASES = [
    # gh pr merge: the repo flag (#450, #1605), in every place and spelling gh reads it
    ("merge: coordinator by --repo", {}, GATES + "gh pr merge 5 --repo cartwmic/coordinator",
     [GATES + "gh pr merge 5 --repo=cartwmic/coordinator", GATES + "gh pr merge 5 -R cartwmic/coordinator", GATES + "gh pr merge 5 -Rcartwmic/coordinator",
      GATES + "gh pr merge 5 -R=cartwmic/coordinator", GATES + "gh -R cartwmic/coordinator pr merge 5", GATES + "gh pr -R cartwmic/coordinator merge 5",
      GATES + "gh pr merge -dRcartwmic/coordinator 5", GATES + "gh pr merge -d -R cartwmic/coordinator 5", GATES + "gh pr merge --delete-branch --repo cartwmic/coordinator 5"], "merge"),
    ("merge: bare, coordinator", {}, "gh pr merge 5 --repo cartwmic/coordinator",
     ["gh pr merge 5 -Rcartwmic/coordinator", "gh pr merge 5 -R cartwmic/coordinator", "gh pr merge 5 --repo=cartwmic/coordinator", "gh pr merge 5 -R=cartwmic/coordinator"], "merge"),
    ("merge: homelab", {}, "gh pr merge 182 --repo cartwmic/cartwmic-homelab-v2",
     ["gh pr merge 182 -Rcartwmic/cartwmic-homelab-v2", "gh pr merge 182 --repo=cartwmic/cartwmic-homelab-v2", "gh pr merge 182 -R=cartwmic/cartwmic-homelab-v2",
      "gh -R cartwmic/cartwmic-homelab-v2 pr merge 182", "gh pr -Rcartwmic/cartwmic-homelab-v2 merge 182"], "merge"),
    ("merge: a PR other than the one checked", {}, "ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge 6 --squash --repo cartwmic/other",
     ["ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge 6 -s -R cartwmic/other", "ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge -sRcartwmic/other 6",
      "ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge 6 -s --repo=cartwmic/other"], "merge"),
    ("merge: a checked PR in another repo is allowed", {}, "ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge 5 --squash --repo cartwmic/other",
     ["ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge 5 -s -Rcartwmic/other", "ci-main-status --merge-gate x && pr-body-check x 5 && gh pr merge -sd 5 --repo=cartwmic/other"], None),
    # gh pr edit / create: the body, the body file and the title
    ("edit: body file, unchecked", {}, "gh pr edit 5 --body-file /tmp/x",
     ["gh pr edit 5 -F /tmp/x", "gh pr edit 5 -F/tmp/x", "gh pr edit 5 -F=/tmp/x", "gh pr edit 5 --body-file=/tmp/x", "gh pr -R o/r edit 5 -F/tmp/x", "gh pr edit 5 -R o/r -F/tmp/x"], "pr_body"),
    ("edit: inline body", {}, "gh pr edit 5 --body x",
     ["gh pr edit 5 -b x", "gh pr edit 5 -bx", "gh pr edit 5 -b=x", "gh pr edit 5 --body=x", "gh pr edit -b x 5"], "pr_body"),
    ("create: inline body", {}, "gh pr create --title t --body x",
     ["gh pr create -t t -b x", "gh pr create -tt -bx", "gh pr create --title=t --body=x", "gh pr new --title t --body x", "gh pr create -dtt -bx"], "pr_body"),
    ("edit: a checked body file", {}, "pr-body-check --body-file %s && gh pr edit 5 --body-file %s" % (EDIT_FILE, EDIT_FILE),
     ["pr-body-check --body-file %s && gh pr edit 5 -F %s" % (EDIT_FILE, EDIT_FILE), "pr-body-check --body-file %s && gh pr edit 5 -F%s" % (EDIT_FILE, EDIT_FILE),
      "pr-body-check --body-file %s && gh pr edit 5 -F=%s" % (EDIT_FILE, EDIT_FILE), "pr-body-check --body-file %s && gh pr edit 5 --body-file=%s" % (EDIT_FILE, EDIT_FILE)], None),
    ("create: a checked body file and title (#450)", {}, "pr-body-check --body-file %s --title T && gh pr create --title T --body-file %s" % (PR_FILE, PR_FILE),
     ["pr-body-check --body-file %s --title T && gh pr create -t T -F%s" % (PR_FILE, PR_FILE), "pr-body-check --body-file %s --title T && gh pr create -tT -F %s" % (PR_FILE, PR_FILE),
      "pr-body-check --body-file %s --title T && gh pr create -t=T -F=%s" % (PR_FILE, PR_FILE), "pr-body-check --body-file %s --title T && gh pr create --title=T --body-file=%s" % (PR_FILE, PR_FILE),
      "pr-body-check --body-file=%s --title=T && gh pr create -t T -F%s" % (PR_FILE, PR_FILE), "pr-body-check --body-file %s --title T && gh pr new -dt T -F %s" % (PR_FILE, PR_FILE)], None),
    ("create: a title the check did not get", {}, "pr-body-check --body-file %s && gh pr create --title T --body-file %s" % (PR_FILE, PR_FILE),
     ["pr-body-check --body-file %s && gh pr create -t T -F%s" % (PR_FILE, PR_FILE), "pr-body-check --body-file %s && gh pr create -tT -F %s" % (PR_FILE, PR_FILE),
      "pr-body-check --body-file %s && gh pr create -t=T --body-file=%s" % (PR_FILE, PR_FILE), "pr-body-check --body-file %s && gh pr create --title=T -F=%s" % (PR_FILE, PR_FILE)], "pr_body"),
    ("edit: a rename with no check", {}, "gh pr edit 5 --title T",
     ["gh pr edit 5 -t T", "gh pr edit 5 -tT", "gh pr edit 5 -t=T", "gh pr edit 5 --title=T", "gh pr edit -tT 5"], "pr_body"),
    ("edit: a rename the check saw", {}, "pr-body-check --body-file %s --title T && gh pr edit 5 --title T" % EDIT_FILE,
     ["pr-body-check --body-file %s --title T && gh pr edit 5 -t T" % EDIT_FILE, "pr-body-check --body-file %s --title T && gh pr edit 5 -tT" % EDIT_FILE,
      "pr-body-check --body-file %s --title T && gh pr edit 5 -t=T" % EDIT_FILE, "pr-body-check --body-file %s --title=T && gh pr edit 5 --title=T" % EDIT_FILE], None),
    ("edit: labels only", {}, "gh pr edit 5 --add-label x", ["gh pr edit 5 --add-label=x", "gh -R o/r pr edit 5 --add-label x"], None),
    # gh api: the method and the fields (#758)
    ("api: body field by PATCH", {}, "gh api repos/o/r/pulls/5 --method PATCH --raw-field body=x",
     ["gh api repos/o/r/pulls/5 --method=PATCH -fbody=x", "gh api repos/o/r/pulls/5 -X PATCH -f body=x", "gh api repos/o/r/pulls/5 -XPATCH -f=body=x",
      "gh api repos/o/r/pulls/5 -X=PATCH --raw-field=body=x", "gh api repos/o/r/pulls/5 -XPATCH -F body=x", "gh api repos/o/r/pulls/5 -XPATCH -Fbody=x",
      "gh api repos/o/r/pulls/5 -iXPATCH -fbody=x", "gh api -XPATCH repos/o/r/pulls/5 -fbody=x"], "pr_body"),
    ("api: body by input file", {}, "gh api repos/o/r/pulls/5 --method PATCH --input /tmp/x",
     ["gh api repos/o/r/pulls/5 --method=PATCH --input=/tmp/x", "gh api repos/o/r/pulls/5 -XPATCH --input /tmp/x"], "pr_body"),
    ("api: issue body", {}, "gh api repos/o/r/issues/5 --method PATCH -f body=x", ["gh api repos/o/r/issues/5 -XPATCH -fbody=x", "gh api repos/o/r/issues/5 --method=PATCH -f=body=x"], "pr_body"),
    ("api: a title (owed separately: a title by api is not read as a body)", {}, "gh api repos/o/r/pulls/5 --method PATCH --raw-field title=x",
     ["gh api repos/o/r/pulls/5 --method=PATCH -ftitle=x", "gh api repos/o/r/pulls/5 -XPATCH -f=title=x", "gh api repos/o/r/pulls/5 -X PATCH -F title=x"], None),
    ("api: a read", {}, "gh api repos/o/r/pulls/5 --jq .title", ["gh api repos/o/r/pulls/5 -q .title", "gh api repos/o/r/pulls/5 --jq=.title", "gh api repos/o/r/pulls/5 -q.title"], None),
    # git in the live coordinator checkout
    ("git: reset --hard in the live checkout", LIVE_KW, "git -C %s reset --hard" % LIVE,
     ["git -C%s reset --hard" % LIVE, "git --git-dir %s/.git reset --hard" % LIVE, "git --git-dir=%s/.git reset --hard" % LIVE, "git --work-tree %s reset --hard" % LIVE,
      "git --work-tree=%s reset --hard" % LIVE, "git -P -C %s reset --hard" % LIVE, "git -pP -C %s reset --hard" % LIVE, "git -c core.editor=true -C %s reset --hard" % LIVE,
      "git -ccore.editor=true -C%s reset --hard" % LIVE, "git -C %s reset --hard --quiet" % LIVE, "git -C %s reset --hard -q" % LIVE], "live_git"),
    ("git: merge in the live checkout", LIVE_KW, "git -C %s merge origin/main" % LIVE,
     ["git -C%s merge origin/main" % LIVE, "git --no-pager -C %s merge origin/main" % LIVE, "git -C %s merge --no-edit origin/main" % LIVE], "live_git"),
    ("git: the deploy fast-forward", LIVE_KW, "git -C %s merge --ff-only %s" % (LIVE, SHA),
     ["git -C%s merge --ff-only %s" % (LIVE, SHA), "git -C %s merge --ff-only --quiet %s" % (LIVE, SHA), "git -C %s merge --ff-only -q %s" % (LIVE, SHA),
      "git -C %s merge -q --ff-only %s" % (LIVE, SHA), "git -C %s merge --ff-only -qv %s" % (LIVE, SHA), "git -C %s merge --ff-only -vq %s" % (LIVE, SHA),
      "git -C %s merge --ff-only --verbose --quiet %s" % (LIVE, SHA)], None),
    ("git: the rollback", LIVE_KW, "git -C %s reset --keep %s" % (LIVE, SHA), ["git -C%s reset --keep %s" % (LIVE, SHA), "git --git-dir=%s/.git reset --keep %s" % (LIVE, SHA)], None),
    ("git: delete a branch", LIVE_KW, "git -C %s branch --delete x" % LIVE,
     ["git -C %s branch -d x" % LIVE, "git -C%s branch -d x" % LIVE, "git -C %s branch -df x" % LIVE, "git -C %s branch --delete --force x" % LIVE], "live_git"),
    ("git: list branches", LIVE_KW, "git -C %s branch --all" % LIVE,
     ["git -C %s branch -a" % LIVE, "git -C%s branch -a" % LIVE, "git -C %s branch -ar" % LIVE, "git -C %s branch --remotes --all" % LIVE, "git -C %s branch --verbose --all" % LIVE,
      "git -C %s branch -avv" % LIVE, "git -C %s branch --list" % LIVE, "git -C %s branch -l" % LIVE], None),
    ("git: stash", LIVE_KW, "git -C %s stash" % LIVE, ["git -C%s stash" % LIVE, "git -C %s stash push" % LIVE], "stash"),
    ("git: stash list", LIVE_KW, "git -C %s stash list" % LIVE, ["git -C%s stash list" % LIVE, "git -C %s stash show" % LIVE, "git -C %s stash list --oneline" % LIVE], None),
    ("git: a read, and the same reset in a scratch checkout", LIVE_KW, "git -C %s log --oneline" % LIVE,
     ["git -C%s log -1" % LIVE, "git -C /tmp/scratch reset --hard", "git -C/tmp/scratch reset --hard", "git --git-dir=/tmp/scratch/.git reset --hard"], None),
    # docker, only on the personal profile
    ("docker: run", {}, "docker run alpine",
     ["docker -H host run alpine", "docker -Hhost run alpine", "docker --host=host run alpine", "docker --host host run alpine", "docker -c ctx run alpine", "docker -cctx run alpine",
      "docker --context=ctx run alpine", "docker -D run alpine", "docker -Dl debug run alpine", "docker --config /tmp/c run alpine", "docker --config=/tmp/c run alpine",
      "docker -l debug run alpine", "docker -ldebug run alpine"], "docker"),
    ("docker: compose up", {}, "docker compose --file x.yml up",
     ["docker compose -f x.yml up", "docker compose -fx.yml up", "docker compose --file=x.yml up", "docker compose -p name up", "docker compose -pname up", "docker compose --project-name name up",
      "docker compose --profile a up", "docker compose --profile=a up", "docker compose --env-file e up", "docker compose --ansi never up", "docker -H h compose -f x.yml up",
      "docker-compose -f x.yml up", "docker-compose --file=x.yml -p n up"], "docker"),
    ("docker: buildx build", {}, "docker buildx --builder b build .", ["docker buildx --builder=b build .", "docker buildx -D build ."], "docker"),
    ("docker: a read", {}, "docker --host h ps", ["docker -Hh ps", "docker --host=h ps", "docker -H h ps", "docker -D -H h ps", "docker -DHh ps", "docker compose -f x.yml ps", "docker-compose -fx.yml ps"], None),
    # kubectl, helm: the context and the kubeconfig
    ("kube: another context", {}, "kubectl --context axon-aks-prod get pods", ["kubectl --context=axon-aks-prod get pods", "kubectl -n x --context axon-aks-prod get pods"], "kube"),
    ("kube: helm's context", {}, "helm --kube-context axon-aks-prod list", ["helm --kube-context=axon-aks-prod list"], "kube"),
    ("kube: the homelab", {"env": {"KUBECONFIG": "/kc/other"}}, "kubectl --context %s get pods" % base.HOMELAB, ["kubectl --context=%s get pods" % base.HOMELAB], None),
    ("kube: a kubeconfig whose current context is another", {}, "kubectl --kubeconfig /kc/other get pods", ["kubectl --kubeconfig=/kc/other get pods"], "kube"),
    ("kube: a kubeconfig on the homelab", {}, "kubectl --kubeconfig /kc/homelab get pods", ["kubectl --kubeconfig=/kc/homelab get pods"], None),
    # the package managers' value options before the subcommand, in the agent host pod
    ("js: npm test in a prefix", {"container": True}, "npm --prefix web test", ["npm --prefix=web test", "npm -C web test", "npm -Cweb test", "npm --cwd web test", "npm --cwd=web test"], "heavy"),
    ("js: pnpm filter", {"container": True}, "pnpm --filter web test", ["pnpm --filter=web test", "pnpm -F web test", "pnpm -Fweb test", "pnpm -w web test", "pnpm --workspace=web test"], "heavy"),
    ("js: a build is not heavy", {"container": True}, "pnpm --filter web build", ["pnpm --filter=web build", "pnpm -F web build", "pnpm -Fweb build"], None),
    # grep and its kin: a value is not a file
    ("credential: a pattern that looks like a file", {}, "grep --regexp .env notes.txt", ["grep --regexp=.env notes.txt", "grep -e .env notes.txt", "grep -e.env notes.txt", "grep -ne .env notes.txt", "grep -ne.env notes.txt"], None),
    ("credential: a glob that looks like a file", {}, "rg --glob .env foo notes.txt", ["rg --glob=.env foo notes.txt", "rg -g .env foo notes.txt", "rg -g.env foo notes.txt", "rg -ng.env foo notes.txt"], None),
    ("credential: a jq argument that looks like a file", {}, "jq --arg k ~/.netrc . notes.json", ["jq --arg k ~/.netrc . notes.json"], None),
    ("credential: the file named after a pattern flag", {}, "grep --regexp x ~/.netrc", ["grep --regexp=x ~/.netrc", "grep -e x ~/.netrc", "grep -ex ~/.netrc", "grep -nex ~/.netrc", "grep -e=x ~/.netrc"], "credential"),
    ("credential: the file after a context count", {}, "grep --after-context 3 x ~/.netrc", ["grep --after-context=3 x ~/.netrc", "grep -A 3 x ~/.netrc", "grep -A3 x ~/.netrc", "grep -nA3 x ~/.netrc"], "credential"),
]


class Spellings(unittest.TestCase):
    def test_every_spelling_gives_the_long_forms_verdict(self):
        for name, kw, long_form, variants, rule in CASES:
            expected = verdict(long_form, **kw)
            with self.subTest(case=name, text=long_form):
                self.assertEqual(expected[0] if expected else None, rule, "the long form of this case is not %s" % ("refused by %s" % rule if rule else "allowed"))
            for text in variants:
                with self.subTest(case=name, text=text):
                    self.assertEqual(verdict(text, **kw), expected)

    def test_every_case_has_spellings_to_compare(self):
        for name, _, _, variants, _ in CASES:
            self.assertGreaterEqual(len(variants), 1, name)


class FlagBeforeTheVerb(unittest.TestCase):
    """gh takes flags before the verb (`gh pr -t T edit 5`). An unknown one may take a value, so the word after it can be the verb: the reader cannot tell `edit` or `merge`
    from a value. Such a command is refused, whatever follows; `-R owner/repo` before the verb is read as before."""
    REFUSED = [
        "gh pr -t T edit 5", "gh pr -tT edit 5", "gh pr -t=T edit 5", "gh pr --title T edit 5", "gh pr --title=T edit 5", "gh pr -t x merge 5", "gh pr -tx merge 5",
        "gh -t x pr merge 5", "gh -x pr edit 5 --body-file /tmp/x", "gh pr -b x edit 5", "gh pr -F /tmp/x edit 5", "gh pr -d create --title T", "gh --weird pr merge 5",
        "gh -R o/r pr -t x merge 5", "gh pr -R o/r -t x merge 5", "gh pr -R o/r --weird edit 5 --add-label x",
        "pr-body-check --body-file /tmp/pr-5-body.aB3xY9 --title T && gh pr -t T edit 5 --body-file /tmp/pr-5-body.aB3xY9",
        "ci-main-status --merge-gate x && pr-body-check x 5 && gh pr -t x merge 5 --squash --repo cartwmic/other",
    ]
    READ = [  # (text, rule that refuses it or None): a flag gh lists before the verb is still read
        ("gh --version", None), ("gh -h", None), ("gh pr -h", None), ("gh pr --help", None), ("gh -R o/r pr view 5", None), ("gh pr -R o/r view 5", None),
        ("gh -R o/r pr edit 5 --add-label x", None), ("gh pr --repo=o/r edit 5 --add-label x", None), ("gh pr -Ro/r edit 5 --add-label x", None),
        ("gh -R cartwmic/coordinator pr edit 5 --body x", "pr_body"), ("gh pr -R cartwmic/coordinator edit 5 --body x", "pr_body"), ("gh pr -Rcartwmic/coordinator edit 5 -bx", "pr_body"),
        ("gh pr -R cartwmic/cartwmic-homelab-v2 merge 182", "merge"), ("gh --repo=cartwmic/cartwmic-homelab-v2 pr merge 182", "merge"),
        ("gh pr -R o/r edit 5 --title T", "pr_body"),
    ]

    def test_an_unknown_flag_before_the_verb_is_refused_saying_why(self):
        for text in self.REFUSED:
            with self.subTest(text=text):
                found = verdict(text)
                self.assertIsNotNone(found)
                self.assertEqual(found[0], "merge")
                self.assertIn("before its subcommand", found[1])
                self.assertIn("cannot tell", found[1])

    def test_a_flag_gh_lists_before_the_verb_is_read(self):
        for text, rule in self.READ:
            with self.subTest(text=text):
                found = verdict(text)
                self.assertEqual(found[0] if found else None, rule)
                if found:
                    self.assertNotIn("before its subcommand", found[1])

    def test_a_flag_after_the_verb_is_not_a_flag_before_it(self):
        for text in ["gh pr view 5 -t x", "gh pr list --weird", "gh issue list --weird", "gh pr checks 5 -x", "gh issue --weird list", "gh repo -x view"]:
            with self.subTest(text=text):
                self.assertIsNone(verdict(text))

    def test_the_log_line_names_the_flag_without_a_value(self):
        found = base.bash_rules.refusal("gh pr --title=secret edit 5", base.ctx())
        self.assertEqual(found[1].log, {"reason": "flag before the gh subcommand", "flag": "--title"})
        self.assertNotIn("secret", str(found[1]))

    def test_the_refusal_applies_on_both_profiles_and_not_elsewhere(self):
        for profile, refused in (("personal", True), ("axon-work-computer", True), ("termux", False)):
            with self.subTest(profile=profile):
                self.assertEqual(verdict("gh pr -t T edit 5", profile=profile) is not None, refused)

    def test_a_gh_pr_checkout_with_a_flag_before_the_verb_is_refused_in_the_live_checkout_on_every_profile(self):
        """The PR gates run on the two desktop profiles only; the live-checkout rule runs on every profile, so a third profile shows it alone."""
        env = {"HOME": "/home/cartwmic"}
        self.assertIn("before its subcommand", (verdict("gh pr -x co 5", profile="termux", env=env, cwd=LIVE) or ("", ""))[1])
        self.assertIsNone(verdict("gh pr -x co 5", profile="termux", env=env, cwd="/home/cartwmic/tmp-home/x"))


if __name__ == "__main__":
    unittest.main()
