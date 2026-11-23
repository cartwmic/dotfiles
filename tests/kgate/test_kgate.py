"""Tests for dot_local/bin/executable_kgate.tmpl (rendered here for the personal profile).

Pure parts are called directly (tree hash against real git, profile, version match, pod spec, markers, peak meter).
The client also runs as a real process against a scripted cluster: a fake `ssh` first on PATH answers the kubectl
commands the client sends and runs the "pod" on this machine, and a fake `op` returns scripted secrets. Everything is
checked from outside: exit codes, output, the job record, files that came back, and what the fake cluster was sent.
"""
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import stat
import tarfile
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "dot_local/bin/executable_kgate.tmpl"
DIGEST = "ghcr.io/cartwmic/kgate@sha256:" + "ab" * 32
FAKE_TOKEN = "ops_fake-token-for-tests-only"  # a stand-in service-account token; never a real one
NO_TOKEN = "1Password service account token not set; refusing to use the desktop app (playbook 78819cbd)"


FAKE_NPM = """#!/bin/sh
echo "npm $*" >> "$FAKE_LOG"
case "$1" in
  -v|--version) echo 11.0.0 ;;
  ci)
    [ -z "$FAKE_NPM_FAIL" ] || { echo "npm error broke" >&2; exit 1; }
    mkdir -p node_modules/pkg && echo "built by npm ci" > node_modules/pkg/index.js
    ;;
  *) echo "ran npm $*" ;;
esac
"""
FAKE_NODE = """#!/bin/sh
echo v24.0.0
"""


def render_script(profile):
    """kgate as chezmoi deploys it for a profile: the template through real chezmoi, with a throwaway config (the user's own
    config and its hooks are never read). Only the 1Password help lines depend on the profile."""
    with tempfile.TemporaryDirectory(prefix="kgate-render-") as tmp:
        config = Path(tmp) / "chezmoi.yaml"
        config.write_text("data:\n  profile: %s\n" % profile)
        r = subprocess.run(["chezmoi", "--source", str(ROOT), "--config", str(config), "--config-format", "yaml", "--destination",
                            str(Path(tmp) / "home"), "--persistent-state", str(Path(tmp) / "state.boltdb"), "--no-tty", "execute-template"],
                           input=TEMPLATE.read_text(), capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


_SCRIPT_DIR = None if os.environ.get("KGATE_SCRIPT") else tempfile.mkdtemp(prefix="kgate-script-")
if _SCRIPT_DIR:
    SCRIPT = Path(_SCRIPT_DIR) / "kgate"
    SCRIPT.write_text(render_script("personal"))
    SCRIPT.chmod(0o755)
else:
    SCRIPT = Path(os.environ["KGATE_SCRIPT"])


def load():
    sys.dont_write_bytecode = True  # the script lives in dot_local/bin; leave no __pycache__ there
    loader = importlib.machinery.SourceFileLoader("kgate_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader("kgate_under_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


K = load()

_CACHE_HOME = tempfile.mkdtemp(prefix="kt-cache-")
os.environ["XDG_CACHE_HOME"] = _CACHE_HOME  # no test reads or writes the real ~/.cache/kgate, even one that calls op_read in this process
_COORDINATOR_STATE = tempfile.mkdtemp(prefix="kt-coordinator-")
os.environ["COORDINATOR_STATE_DIR"] = _COORDINATOR_STATE  # no test reads the real coordinator's brake/ folder: a pause that is on there would hold every job


def tearDownModule():
    shutil.rmtree(_CACHE_HOME, True)
    shutil.rmtree(_COORDINATOR_STATE, True)
    if _SCRIPT_DIR:
        shutil.rmtree(_SCRIPT_DIR, True)


def git(cwd, *args, **env):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", **env})


def gitout(cwd, *args):
    """git's stdout as text (stripped)."""
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


class TreeHash(unittest.TestCase):
    def test_equals_what_git_write_tree_gives(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            git(d, "init", "-q")
            (d / "a.b").write_text("one\n")
            (d / "a").mkdir()
            (d / "a" / "b").write_text("two\n")
            (d / "a" / "run.sh").write_text("#!/bin/sh\n")
            (d / "a" / "run.sh").chmod(0o755)
            (d / "z").mkdir()
            (d / "z" / "deep").mkdir()
            (d / "z" / "deep" / "f").write_bytes(b"\x00\x01binary\xff")
            (d / "empty").write_text("")
            (d / "link").symlink_to("a/b")
            (d / "üñí code.txt").write_text("unicode name\n")
            git(d, "add", "-A")
            want = subprocess.run(["git", "-C", str(d), "write-tree"], check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
            files = subprocess.run(["git", "-C", str(d), "ls-files", "-z"], check=True, stdout=subprocess.PIPE).stdout.split(b"\0")
            files = [os.fsdecode(f) for f in files if f]
            self.assertEqual(K.tree_hash(str(d), files), want)

    def test_one_changed_byte_changes_it(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "f").write_text("x")
            before = K.tree_hash(d, ["f"])
            (Path(d) / "f").write_text("y")
            self.assertNotEqual(K.tree_hash(d, ["f"]), before)

    def test_mode_matters(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "f"
            f.write_text("x")
            before = K.tree_hash(d, ["f"])
            f.chmod(0o755)
            self.assertNotEqual(K.tree_hash(d, ["f"]), before)


class Profile(unittest.TestCase):
    GOOD = '''
image = "%s"
cpu = 2
memory = "4Gi"
[tools]
node = "24.22.2"
helm = { version = "4.2.3", cmd = "helm version --short" }
[secrets]
NODE_AUTH_TOKEN = "op://developer/item/password"
''' % DIGEST

    def test_parses(self):
        p = K.parse_profile(self.GOOD)
        self.assertEqual(p["tools"], {"node": ("24.22.2", None), "helm": ("4.2.3", "helm version --short")})
        self.assertEqual(p["secrets"], {"NODE_AUTH_TOKEN": "op://developer/item/password"})

    def test_user_defaults_to_non_root_and_must_be_uid_gid(self):
        self.assertEqual(K.parse_profile("")["user"], "1000:1000")
        self.assertEqual(K.parse_profile('user = "0:0"')["user"], "0:0")
        for bad in ('user = "node"', 'user = 1000', 'user = "1000"'):
            with self.assertRaises(K.Unavailable, msg=bad):
                K.parse_profile(bad)

    def test_the_split_table_is_kgate_splits_and_does_not_change_the_profile(self):
        with_split = K.parse_profile(self.GOOD + '\n[split]\nlist = "ls"\nrun = "sh {items}"\npods = 4\n')
        self.assertEqual(with_split, K.parse_profile(self.GOOD))
        with self.assertRaises(K.Unavailable) as e:
            K.parse_profile('nope = 1\n[split]\nlist = "ls"')
        self.assertIn("unknown keys: nope", str(e.exception))

    def test_rejects_bad_shapes(self):
        for bad in ['nope = 1', '[tools]\nnode = 24', '[tools]\nnode = {cmd = "x"}', '[secrets]\nX = "plain"',
                    '[secrets]\n"1X" = "op://a/b/c"', 'services = "docker"', 'image = ']:
            with self.assertRaises(K.Unavailable, msg=bad):
                K.parse_profile(bad)

    def test_settings(self):
        K.check_settings(DIGEST, 2, "4Gi")
        for args in [("node:24", 2, "4Gi"), (DIGEST, 0, "4Gi"), (DIGEST, 2, "4G"), (DIGEST, "2", "4Gi"), (None, 2, "4Gi")]:
            with self.assertRaises(K.Unavailable, msg=str(args)):
                K.check_settings(*args)

    def test_memory_limit_parses_and_defaults_to_none(self):
        self.assertIsNone(K.parse_profile(self.GOOD)["memory_limit"])
        self.assertEqual(K.parse_profile('memory = "1Gi"\nmemory_limit = "2Gi"')["memory_limit"], "2Gi")

    def test_homelab_ephemeral_storage_and_its_limit_parse(self):
        p = K.parse_profile('ephemeral_storage = "8Gi"\nephemeral_storage_limit = "12Gi"')
        self.assertEqual((p["ephemeral_storage"], p["ephemeral_storage_limit"]), ("8Gi", "12Gi"))
        p = K.parse_profile("")
        self.assertEqual((p["ephemeral_storage"], p["ephemeral_storage_limit"]), (None, None))
        K.parse_profile('ephemeral_storage_limit = "4Gi"')   # equal to the default request is allowed

    def test_bad_homelab_ephemeral_storage_is_refused(self):
        for bad in ('ephemeral_storage = "20G"', 'ephemeral_storage = 20', 'ephemeral_storage_limit = "20G"', 'ephemeral_storage_limit = 1',
                    'ephemeral_storage_limit = "2Gi"',                                  # below the default request
                    'ephemeral_storage = "8Gi"\nephemeral_storage_limit = "4Gi"',       # below the request
                    'cluster = "example"\nephemeral_storage_limit = "20Gi"'):           # a kubectl cluster's limit is its request
            with self.assertRaises(K.Unavailable, msg=bad):
                K.parse_profile(bad)

    def test_priority_class_is_kgate_or_kgate_first_on_the_homelab_only(self):
        # opt-in (coordinator decision #2874): unset keeps the pod in `kgate`; `kgate-first` puts it ahead of waiting `kgate` pods (homelab `k8s/kgate/priorityclass-first.yaml`).
        self.assertIsNone(K.parse_profile("")["priority_class"])
        for ok in ("kgate", "kgate-first", "kgate-main"):   # `kgate-main` (homelab#440, value -40) is the coordinator's main run
            self.assertEqual(K.parse_profile('priority_class = "%s"' % ok)["priority_class"], ok)
        for bad in ('priority_class = "homelab-critical"', 'priority_class = "kgate-last"', 'priority_class = ""', 'priority_class = 1', 'priority_class = true',
                    'cluster = "example"\npriority_class = "kgate"', 'cluster = "example"\npriority_class = "kgate-first"'):   # a kubectl cluster's own policy decides its class
            with self.assertRaises(K.Unavailable, msg=bad):
                K.parse_profile(bad)

    def test_a_homelab_profile_may_set_a_cpu_limit_that_is_a_whole_number(self):
        self.assertIsNone(K.parse_profile("")["cpu_limit"])
        self.assertEqual(K.parse_profile("cpu_limit = 8")["cpu_limit"], 8)
        for bad in ("cpu_limit = 0", 'cpu_limit = "8"', "cpu_limit = true", "cpu_limit = 2.5"):
            with self.assertRaises(K.Unavailable, msg=bad):
                K.parse_profile(bad)

    def test_memory_limit_must_be_at_least_the_request(self):
        K.check_settings(DIGEST, 2, "256Mi", "512Mi")
        K.check_settings(DIGEST, 2, "1Gi", "1024Mi")  # equal is the old behaviour
        for args in [(DIGEST, 2, "1Gi", "512Mi"), (DIGEST, 2, "1Gi", "2G"), (DIGEST, 2, "1Gi", "0Mi"), (DIGEST, 2, "1Gi", 512)]:
            with self.assertRaises(K.Unavailable, msg=str(args)):
                K.check_settings(*args)

    def test_version_match_is_whole_version(self):
        self.assertTrue(K.version_found("v24.22.2", "24.22.2"))
        self.assertTrue(K.version_found("ansible-lint 26.10.1 using ansible-core:2.19.14", "2.19.14"))
        self.assertTrue(K.version_found("rustc 1.98.0 (abc 2026-01-01)", "1.98.0"))
        self.assertFalse(K.version_found("rustc 11.98.0", "1.98.0"))
        self.assertFalse(K.version_found("rustc 1.98.01", "1.98.0"))
        self.assertFalse(K.version_found("rustc 1.98.0.1", "1.98.0"))
        self.assertFalse(K.version_found("", "1.0.0"))


class PodSpec(unittest.TestCase):
    def pod(self, **kw):
        args = dict(job="kgate-1-2", image=DIGEST, cpu=3, memory="6Gi", node=None, secret_env={}, pull=None, memory_limit=None, prefer_nodes=True,
                    ephemeral=K.EPHEMERAL_DEFAULT, ephemeral_limit=None)
        extra = {k: kw.pop(k) for k in ("priority_class", "cpu_limit") if k in kw}   # passed only when a test sets them: the defaults are the signature's own
        args.update(kw)
        items = K.pod_manifests(args["job"], args["image"], args["cpu"], args["memory"], args["node"], args["secret_env"], args["pull"],
                                memory_limit=args["memory_limit"], prefer_nodes=args["prefer_nodes"], ephemeral=args["ephemeral"],
                                ephemeral_limit=args["ephemeral_limit"], **extra)["items"]
        return items[-1], items[:-1]

    def test_limits_and_jobs_follow_the_request(self):
        pod, _ = self.pod()
        c = pod["spec"]["containers"][0]
        self.assertEqual(c["resources"]["requests"], {"cpu": "3", "memory": "6Gi", "ephemeral-storage": "4Gi"})
        self.assertEqual(c["resources"]["limits"], {"memory": "6Gi", "ephemeral-storage": "12Gi"})
        env = {e["name"]: e.get("value") for e in c["env"]}
        self.assertEqual((env["CARGO_BUILD_JOBS"], env["RAYON_NUM_THREADS"], env["MAKEFLAGS"]), ("3", "3", "-j3"))
        self.assertEqual(c["image"], DIGEST)
        self.assertEqual(c["command"], ["tini", "--", "sleep", "infinity"], "PID 1 is an init, so orphans are reaped")

    def test_request_and_limit_render_separately(self):
        pod, _ = self.pod(memory="256Mi", memory_limit="512Mi")
        c = pod["spec"]["containers"][0]
        self.assertEqual(c["resources"], {"requests": {"cpu": "3", "memory": "256Mi", "ephemeral-storage": "4Gi"}, "limits": {"memory": "512Mi", "ephemeral-storage": "12Gi"}})

    def test_the_pod_asks_for_ephemeral_storage_and_a_profile_can_change_it(self):
        # dotfiles#484: a pod with no request is the first one the kubelet evicts when the node is short on disk, and the scheduler cannot keep it off a full node.
        self.assertEqual(K.EPHEMERAL_DEFAULT, "4Gi")
        pod, _ = self.pod()
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["requests"]["ephemeral-storage"], "4Gi")
        pod, _ = self.pod(ephemeral="8Gi")
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["requests"]["ephemeral-storage"], "8Gi")

    def test_the_pod_has_a_default_ephemeral_storage_limit_that_never_falls_below_the_request(self):
        # 2026-11-16 13:37Z (agent-4): a gate with no limit fills the node's disk and the kubelet evicts its neighbours. With a limit it is the one evicted, reported as `evicted:`.
        self.assertEqual(K.EPHEMERAL_LIMIT_DEFAULT, "12Gi")
        pod, _ = self.pod()
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["limits"]["ephemeral-storage"], "12Gi")
        pod, _ = self.pod(ephemeral="25Gi")   # a profile that raises only the request (storycraft): a limit below it would be refused by the API
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["limits"]["ephemeral-storage"], "25Gi")
        pod, _ = self.pod(ephemeral="12Gi")
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["limits"]["ephemeral-storage"], "12Gi")
        pod, _ = self.pod(ephemeral_limit="40Gi")   # an explicit limit wins, larger or smaller than the default
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["limits"]["ephemeral-storage"], "40Gi")
        pod, _ = self.pod(ephemeral_limit="5Gi")
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["limits"]["ephemeral-storage"], "5Gi")

    def test_an_ephemeral_storage_limit_is_rendered_when_set(self):
        pod, _ = self.pod(ephemeral="1Gi", ephemeral_limit="2Gi")
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["limits"], {"memory": "6Gi", "ephemeral-storage": "2Gi"})

    def test_the_pod_runs_in_the_kgate_priority_class_and_only_on_the_homelab(self):
        # A PriorityClass orders scheduling, preemption and eviction: below every app and system pod (homelab `k8s/kgate/priorityclass.yaml`, -100, preemptionPolicy Never).
        # It gives the pod no CPU share at run time. The kubectl cluster's own policy decides its pods' class.
        pod, _ = self.pod()
        self.assertEqual(pod["spec"].get("priorityClassName"), "kgate")
        self.assertEqual(K.PRIORITY_CLASS, "kgate")

    def test_the_pod_runs_in_kgate_first_only_when_asked(self):
        pod, _ = self.pod(priority_class="kgate-first")
        self.assertEqual(pod["spec"]["priorityClassName"], "kgate-first")
        pod, _ = self.pod(priority_class="kgate")
        self.assertEqual(pod["spec"]["priorityClassName"], "kgate")

    def test_a_cpu_limit_is_rendered_only_when_set(self):
        # no CPU limit by default (docs/kgate.md "Placement"); a profile that sets cpu_limit gets limits.cpu equal to it, a string like the request.
        pod, _ = self.pod()
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["limits"], {"memory": "6Gi", "ephemeral-storage": "12Gi"})
        pod, _ = self.pod(cpu_limit=3)
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["limits"], {"memory": "6Gi", "ephemeral-storage": "12Gi", "cpu": "3"})
        self.assertEqual(pod["spec"]["containers"][0]["resources"]["requests"]["cpu"], "3")

    def test_default_render_is_byte_identical_to_the_one_before_memory_limit(self):
        # the pins moved once, when every pod gained the compile caches and the worker counts (tuning_env), and again when the compile caches moved from /tmp to /var/tmp (the only change: NODE_COMPILE_CACHE and PYTHONPYCACHEPREFIX); a profile without scratch_tmpfs or tmp_tmpfs still renders no memory volume
        # sha256 of json.dumps(manifests); re-pinned 2026-11-08 for the G14 preference (the only change from the agent-4 overflow render, #263), 2026-11-16 for the 4 h pod bound (the only change: activeDeadlineSeconds 28800 to 14400, dotfiles#479), and 2026-11-16 for the ephemeral-storage request (the only change: requests gain "ephemeral-storage": "4Gi", dotfiles#484), and 2026-11-16 for the default ephemeral-storage limit (the only changes: the request 3Gi to 4Gi, and limits gain "ephemeral-storage": "12Gi"), and 2026-11-16 for the PriorityClass (the only change: the pod spec gains "priorityClassName": "kgate"), and 2026-11-16 for agent-3 (the only change: the NotIn hostname list gains "ubuntu-server-k8s-agent-3", decision #3311)
        cases = [
            (K.pod_manifests("kgate-1-2", DIGEST, 3, "6Gi", None, {}, None), "5f9dd1b59bac033c124d0185acd027ac2d04d90da42d593dc6c1da515bbd76c9"),
            (K.pod_manifests("kgate-1-2", DIGEST, 2, "1Gi", "ubuntu-server-k8s-agent-1", {"TOK": b"s3cret"}, ("ghcr.io", "u", b"pw")),
             "13bfbb79b9177ba2fd2f08fa6694d64dea3479e03ecdc0d005337747caf98e38"),
            (K.pod_manifests("kgate-9-9", DIGEST, 1, "512Mi", None, {}, None, 1000), "a0a97fdf70c7380507ff778b3970f1bc55f3a507fbd1866fd5c0170ca870e96c"),
        ]
        for manifests, want in cases:
            self.assertEqual(hashlib.sha256(json.dumps(manifests).encode()).hexdigest(), want)

    def test_keeps_off_excluded_nodes(self):
        pod, _ = self.pod()
        exprs = pod["spec"]["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]["matchExpressions"]
        notin = next(e for e in exprs if e["operator"] == "NotIn")
        self.assertEqual(notin["values"], ["ubuntu-server-k8s-master-1", "mac-mini-worker", "ubuntu-server-k8s-agent-3"])
        self.assertIn({"key": "kubernetes.io/arch", "operator": "In", "values": ["amd64"]}, exprs)

    def test_g14_is_preferred_and_the_gpu_node_is_overflow_only(self):
        pod, _ = self.pod()
        pref = pod["spec"]["affinity"]["nodeAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"]
        self.assertEqual(pref, [
            {"weight": 100, "preference": {"matchExpressions": [
                {"key": "kubernetes.io/hostname", "operator": "In", "values": ["cartwmic-g14-wsl"]}]}},
            {"weight": 100, "preference": {"matchExpressions": [
                {"key": "kubernetes.io/hostname", "operator": "NotIn", "values": ["ubuntu-server-k8s-agent-4"]}]}}])

    def test_a_profile_can_leave_the_g14_preference_out(self):
        pod, _ = self.pod(prefer_nodes=False)
        pref = pod["spec"]["affinity"]["nodeAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"]
        self.assertEqual(pref, [
            {"weight": 100, "preference": {"matchExpressions": [
                {"key": "kubernetes.io/hostname", "operator": "NotIn", "values": ["ubuntu-server-k8s-agent-4"]}]}}])

    def test_prefer_nodes_in_a_profile_is_a_bool_and_defaults_true(self):
        base = 'image = "%s"\n' % DIGEST
        self.assertTrue(K.parse_profile(base)["prefer_nodes"])
        self.assertFalse(K.parse_profile(base + "prefer_nodes = false\n")["prefer_nodes"])
        with self.assertRaises(K.Unavailable):
            K.parse_profile(base + 'prefer_nodes = "no"\n')

    def test_the_preference_does_not_widen_the_required_match(self):
        pod, _ = self.pod()
        exprs = pod["spec"]["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]["matchExpressions"]
        self.assertEqual(exprs, [
            {"key": "kubernetes.io/arch", "operator": "In", "values": ["amd64"]},
            {"key": "kubernetes.io/hostname", "operator": "NotIn", "values": ["ubuntu-server-k8s-master-1", "mac-mini-worker", "ubuntu-server-k8s-agent-3"]}])

    def test_prefer_and_overflow_nodes_do_not_overlap(self):
        self.assertFalse(set(K.PREFER_NODES) & set(K.OVERFLOW_NODES))
        self.assertFalse(set(K.PREFER_NODES) & set(K.NEVER_NODES))

    def test_pinned_node(self):
        pod, _ = self.pod(node="ubuntu-server-k8s-agent-1")
        exprs = pod["spec"]["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]["matchExpressions"]
        self.assertEqual(exprs, [{"key": "kubernetes.io/arch", "operator": "In", "values": ["amd64"]},
                                 {"key": "kubernetes.io/hostname", "operator": "In", "values": ["ubuntu-server-k8s-agent-1"]}])

    def test_secrets_are_secrets_not_env_values(self):
        pod, secrets = self.pod(secret_env={"TOK": b"s3cret"}, pull=("ghcr.io", "u", b"pw"))
        self.assertNotIn("s3cret", json.dumps(pod))
        self.assertEqual({s["metadata"]["name"] for s in secrets}, {"kgate-1-2-env", "kgate-1-2-pull"})
        self.assertEqual(pod["spec"]["containers"][0]["envFrom"], [{"secretRef": {"name": "kgate-1-2-env"}}])
        self.assertEqual(pod["spec"]["imagePullSecrets"], [{"name": "kgate-1-2-pull"}])


class RunAsUser(unittest.TestCase):
    def test_root_in_the_pod_hands_the_tree_to_the_user(self):
        with tempfile.TemporaryDirectory() as d:
            tree = Path(d) / "wt"
            (tree / "sub").mkdir(parents=True)
            (tree / "sub" / "f").write_text("x")
            owned = []
            job = {"uid": 1000, "gid": 1001, "own": [str(tree)]}
            how, env = K.prepare_user(job, euid=0, chown=lambda p, u, g: owned.append((p, u, g)), root=d)
            self.assertEqual(how, {"user": 1000, "group": 1001, "extra_groups": []})
            self.assertEqual(env, {"HOME": "/cache/u1000/home", "npm_config_cache": "/cache/u1000/npm", "CARGO_HOME": "/cache/u1000/cargo"})
            paths = {p for p, u, g in owned}
            self.assertTrue({str(tree), str(tree / "sub"), str(tree / "sub" / "f"), d + "/out", d + "/cache/u1000/home"} <= paths)
            self.assertTrue(all((u, g) == (1000, 1001) for p, u, g in owned))

    def test_uid_zero_or_a_non_root_pod_changes_nothing(self):
        self.assertEqual(K.prepare_user({"uid": 0, "gid": 0, "own": []}, euid=0), ({}, {}))
        self.assertEqual(K.prepare_user({"uid": 1000, "gid": 1000, "own": []}, euid=1000), ({}, {}))


class NodeCache(unittest.TestCase):
    """The node cache (/cache in the pod, /var/lib/kgate/cache on the node) is bounded: dotfiles#484, coordinator decision #2755."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kc-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "cache"
        self.root.mkdir()
        self.fds = []

    def lock(self):
        fd = os.open(str(self.root / K.CACHE_LOCK), os.O_RDWR | os.O_CREAT, 0o666)
        self.fds.append(fd)
        self.addCleanup(os.close, fd)
        return fd

    def entry(self, rel, age, kib=64):
        """An entry of about `kib` KiB whose newest file was last used `age` seconds ago."""
        path = self.root / rel
        path.mkdir(parents=True)
        (path / "blob").write_bytes(b"x" * kib * 1024)
        t = time.time() - age
        for each in (path / "blob", path):
            os.utime(each, (t, t))
        return path

    def size(self, *paths):
        return sum(K.entry_use(str(p))[0] for p in paths)

    def test_entries_are_whole_trees_below_the_user_folders(self):
        for rel in ("npm", "cargo-registry", "u1000/npm", "u1000/cargo", "u1000/home/go", "u1000/home/n26", "u1000/home/.cache/go-build", "u1000/home/.cache/ms-playwright"):
            self.entry(rel + "/x", 1)
        (self.root / K.CACHE_LOCK).write_text("")
        self.assertEqual(sorted(os.path.relpath(p, self.root) for p in K.cache_entries(str(self.root))),
                         ["cargo-registry", "npm", "u1000/cargo", "u1000/home/.cache/go-build", "u1000/home/.cache/ms-playwright", "u1000/home/go", "u1000/home/n26", "u1000/npm"])

    def test_each_repo_folder_of_the_npm_install_cache_is_its_own_entry(self):
        for rel in ("u1000/nm/alert-steward", "u1000/nm/budget-steward"):
            self.entry(rel, 1)
        self.assertEqual(sorted(os.path.relpath(p, self.root) for p in K.cache_entries(str(self.root))), ["u1000/nm/alert-steward", "u1000/nm/budget-steward"])

    def test_over_the_cap_the_least_recently_used_entries_go_first_until_it_fits(self):
        old, mid, new = self.entry("u1000/home/old", 3000), self.entry("u1000/npm", 2000), self.entry("u1000/home/.cache/new", 10)
        lock = self.lock()
        gone, freed, skipped = K.trim_cache(str(self.root), self.size(mid, new), lock)
        self.assertEqual((gone, skipped), (1, None))
        self.assertEqual((old.exists(), mid.exists(), new.exists()), (False, True, True))
        self.assertGreaterEqual(freed, 64 * 1024)
        gone, _, _ = K.trim_cache(str(self.root), self.size(new), lock)
        self.assertEqual((gone, mid.exists(), new.exists()), (1, False, True), "the newest entry is the last to go")

    def test_a_recently_used_file_keeps_its_whole_entry_young(self):
        a, b = self.entry("u1000/home/a", 3000), self.entry("u1000/home/b", 2000)
        t = time.time()
        os.utime(a / "blob", (t, t))   # a's old directory, but a file in it was just used
        K.trim_cache(str(self.root), self.size(a), self.lock())
        self.assertEqual((a.exists(), b.exists()), (True, False))

    def test_within_the_cap_nothing_is_removed(self):
        a = self.entry("npm", 5000)
        self.assertEqual(K.trim_cache(str(self.root), self.size(a) + 1, self.lock()), (0, 0, None))
        self.assertTrue(a.exists())

    def test_nothing_is_removed_while_another_job_is_running(self):
        a, b = self.entry("u1000/home/a", 3000), self.entry("u1000/home/b", 2000)
        other = self.lock()
        fcntl.flock(other, fcntl.LOCK_SH)   # a running job holds the shared lock
        self.assertEqual(K.trim_cache(str(self.root), 1, self.lock()), (0, 0, "another job is running on this node"))
        self.assertTrue(a.exists() and b.exists(), "an entry a running job may be using is never removed, over the cap or not")
        fcntl.flock(other, fcntl.LOCK_UN)
        self.assertEqual(K.trim_cache(str(self.root), 1, self.lock())[0], 2)

    def test_a_cut_short_trim_leaves_no_half_entry_and_the_next_one_empties_the_trash(self):
        left = self.root / K.CACHE_TRASH / "0"
        left.mkdir(parents=True)
        (left / "blob").write_text("left over")
        a = self.entry("npm", 100)
        K.trim_cache(str(self.root), 10 ** 9, self.lock())
        self.assertFalse((self.root / K.CACHE_TRASH).exists())
        self.assertTrue(a.exists())

    def test_a_job_holds_the_shared_lock_after_it_trims_an_idle_node(self):
        a, b = self.entry("u1000/home/a", 3000), self.entry("u1000/home/b", 10)
        said = []
        fd = K.hold_cache(str(self.root), self.size(b), said.append)
        self.addCleanup(os.close, fd)
        self.assertEqual((a.exists(), b.exists()), (False, True))
        self.assertEqual(len(said), 1)
        self.assertRegex(said[0], r"^kgate: cache over \d+ MiB: removed the 1 least recently used entries \(\d+ MiB\)\n$")
        self.assertEqual(K.trim_cache(str(self.root), 1, self.lock())[2], "another job is running on this node", "the job's lock is held")
        self.assertTrue(b.exists())

    def test_a_job_that_ends_trims_nothing_so_the_end_line_is_the_last_thing_it_prints(self):
        # dotfiles#493: a trim after the end line ran in the 10 s the client gives the stream to close, was cut off, and the client then blamed CMD for it
        tree = self.tmp / "wt"
        tree.mkdir()
        (tree / "f").write_text("x")
        a, b = self.entry("u1000/home/a", 3000), self.entry("u1000/home/b", 10)
        stale = self.root / "u1000/home/stale"
        job = {"id": "kgate-1-2", "root": str(tree), "cwd": str(tree), "files": ["f"], "tree": K.tree_hash(str(tree), ["f"]), "tools": {},
               "argv": ["sh", "-c", "mkdir %s && head -c 65536 /dev/zero > %s/blob && touch -d '2000-01-01' %s/blob %s" % ((stale,) * 4)],
               "uid": 1000, "gid": 1000, "own": [str(tree)], "head": None, "cache": {"root": str(self.root), "cap": self.size(a, b) + 1}}   # within the cap when the job starts
        (self.tmp / "job.json").write_text(json.dumps(job))
        done = subprocess.run([sys.executable, str(SCRIPT), "--pod", str(self.tmp / "job.json")], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(stale.exists(), "the entry CMD left over the cap is still there: it waits for the next job that starts on an idle node")
        self.assertRegex(done.stdout.splitlines()[-1], r"^kgate\[kgate-1-2\]: end \d+ exit 0$", done.stdout)
        self.assertNotIn("cache over", done.stdout)

    def test_no_cache_folder_is_no_trim(self):
        self.assertIsNone(K.hold_cache(str(self.tmp / "none"), 1, lambda _: None))

    def test_the_pod_trims_before_cmd_runs_and_cmd_still_runs(self):
        # the pod side as a process of its own, on this machine, with the cache pointed at a scratch folder
        tree = self.tmp / "wt"
        tree.mkdir()
        (tree / "f").write_text("x")
        old, new = self.entry("u1000/home/old", 3000), self.entry("u1000/home/new", 10)
        job = {"id": "kgate-1-2", "root": str(tree), "cwd": str(tree), "files": ["f"], "tree": K.tree_hash(str(tree), ["f"]), "argv": ["sh", "-c", "echo cmd-ran"],
               "uid": 1000, "gid": 1000, "own": [str(tree)], "head": None, "tools": {}, "cache": {"root": str(self.root), "cap": self.size(new)}}
        (self.tmp / "job.json").write_text(json.dumps(job))
        done = subprocess.run([sys.executable, str(SCRIPT), "--pod", str(self.tmp / "job.json")], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn("kgate[kgate-1-2]: cache over", done.stdout)
        self.assertIn("cmd-ran", done.stdout)
        self.assertEqual((old.exists(), new.exists()), (False, True))

    def test_the_default_cap_is_eight_gib_unless_the_env_overrides_it(self):
        self.assertEqual((K.CACHE_ROOT, K.CACHE_CAP), ("/cache", int(os.environ.get("KGATE_CACHE_CAP") or 8 << 30)))


class Pieces(unittest.TestCase):
    def test_markers_across_chunks_and_unterminated_output(self):
        m = K.Markers("kgate-1-2")
        for chunk in [b"progress 10%\r", b"progress 100%\nkgate[kgate-1-2]: pe", b"ak 4096 cgroup\nkgate[kgate-1-2]: end 17 ex", b"it 3\n", b"tail without newline"]:
            m.feed(chunk)
        m.close()
        self.assertEqual(m.seen["peak"], "4096 cgroup")
        self.assertEqual(m.seen["end"], "17 exit 3")

    def test_markers_of_another_job_or_printed_by_cmd_are_ignored(self):
        m = K.Markers("kgate-1-2")
        m.feed(b"kgate: hash MISMATCH expected=a found=b\nkgate[kgate-9-9]: end 1 exit 0\nkgate[kgate-1-2]: end 5 exit 0\n")
        self.assertEqual(m.seen, {"end": "5 exit 0"})

    def test_peak_meter_reads_the_kernels_peak(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "memory.peak").write_text("12345\n")
            meter = K.PeakMeter(d)
            meter.start()
            self.assertEqual(meter.stop(), (12345, "cgroup"))

    def test_cpu_usec_reads_usage_usec_from_cpu_stat(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(K.read_cpu_usec(d), "no cpu.stat: null, not zero")
            Path(d, "cpu.stat").write_text("usage_usec 123456\nuser_usec 100000\nsystem_usec 23456\n")
            self.assertEqual(K.read_cpu_usec(d), 123456)
            Path(d, "cpu.stat").write_text("user_usec 1\n")
            self.assertIsNone(K.read_cpu_usec(d))

    def test_the_pod_side_reports_cpu_and_the_commands_own_run_time(self):
        tree = Path(tempfile.mkdtemp(prefix="kgate-pm-"))
        self.addCleanup(shutil.rmtree, tree, True)
        (tree / "f").write_text("x")
        cg = tree / "cg"
        cg.mkdir()
        (cg / "cpu.stat").write_text("usage_usec 987654\n")
        job = {"id": "kgate-1-2", "root": str(tree), "cwd": str(tree), "files": ["f"], "tree": K.tree_hash(str(tree), ["f"]), "argv": ["sleep", "1"],
               "uid": os.getuid(), "gid": os.getgid(), "own": [], "head": None, "tools": {}}
        (tree / "job.json").write_text(json.dumps(job))
        done = subprocess.run([sys.executable, str(SCRIPT), "--pod", str(tree / "job.json")], capture_output=True, text=True, timeout=60,
                              env={**os.environ, "KGATE_CGROUP": str(cg)})
        m = K.Markers("kgate-1-2")
        m.feed(done.stdout.encode())
        m.close()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(m.seen["cpu"], "987654")
        t0, t1 = (float(x) for x in m.seen["clock"].split())
        self.assertTrue(1.0 <= t1 - t0 < 1.5, m.seen)

    def test_peak_meter_samples_when_the_kernel_has_no_peak(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "memory.current").write_text("777\n")
            meter = K.PeakMeter(d)
            meter.start()
            self.assertEqual(meter.stop(), (777, "sampled"))


FAKE_DELETE = r'''
def fake_delete(fake, pods):
    """The delete of a pod, shared by both fakes. FAKE_DELETE_FAIL: "N" fails the first N pod deletes with an etcd timeout, "always" fails every one.
    FAKE_DELETE_HANG: "N" makes the first N pod deletes hang. FAKE_DELETE_SLOW: "S" makes the first pod delete take S seconds, and writes <fake>/delete-started
    when it begins (the test signals the client while it is in flight). A pod delete that succeeds is written to <fake>/deleted-pods."""
    for x in pods:   # the Secrets the quota fake of the homelab keeps (<fake>/secrets/NAME)
        if x.startswith("secret/") and os.path.exists(os.path.join(fake, "secrets", x[7:])):
            os.unlink(os.path.join(fake, "secrets", x[7:]))
    named = [x for x in pods if x.startswith("pod/")]
    if not named:
        return 0   # the sweep's label delete
    fails = os.environ.get("FAKE_DELETE_FAIL", "")
    counter = os.path.join(fake, "delete-tries")
    n = int(open(counter).read()) + 1 if os.path.exists(counter) else 1
    open(counter, "w").write(str(n))
    if os.environ.get("FAKE_DELETE_SLOW") and n == 1:
        import time
        open(os.path.join(fake, "delete-started"), "w").write("x")
        time.sleep(float(os.environ["FAKE_DELETE_SLOW"]))
    if os.environ.get("FAKE_DELETE_HANG") and n <= int(os.environ["FAKE_DELETE_HANG"]):   # the first N pod deletes never answer
        import time
        time.sleep(60)
    if fails and (fails == "always" or n <= int(fails)):
        sys.stderr.write("Error from server: etcdserver: request timed out\n")
        return 1
    with open(os.path.join(fake, "deleted-pods"), "a") as f:
        f.write("\n".join(x[4:] for x in named) + "\n")
    for x in named:   # a pod that is gone no longer counts toward the fake's quota (FAKE_QUOTA_HOLD)
        if os.path.exists(os.path.join(fake, "quota-held", x[4:])):
            os.unlink(os.path.join(fake, "quota-held", x[4:]))
    return 0
'''

FAKE_SSH = r'''#!/usr/bin/env python3
import hashlib, json, os, re, shlex, subprocess, sys
''' + FAKE_DELETE + r'''
fake = os.environ["FAKE"]
# What ssh was asked, apart from the kubectl calls: every argv, and a stand-in for the multiplexed master (ControlMaster=auto makes the ControlPath socket if it
# is not there; `-O exit` removes it), so a test sees what the client left behind.
argv = sys.argv[1:]
with open(os.path.join(fake, "ssh-argv.jsonl"), "a") as f:
    f.write(json.dumps(argv) + "\n")
opts = {argv[i + 1].partition("=")[0]: argv[i + 1].partition("=")[2] for i, x in enumerate(argv[:-1]) if x == "-o"}
socket_path = opts.get("ControlPath", "").replace("%C", hashlib.sha1(argv[-1].encode()).hexdigest())
if "-O" in argv:
    if socket_path and os.path.exists(socket_path):
        os.unlink(socket_path)
    sys.exit(0)
if opts.get("ControlMaster") == "auto" and socket_path and not os.path.exists(socket_path) and not argv[-2:-1] == ["-O"] and not argv[-1].endswith("down"):
    open(socket_path, "w").close()
host, remote = sys.argv[-2], sys.argv[-1]
def log(entry):
    with open(os.path.join(fake, "calls.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")
if remote == "true":
    log({"probe": host})
    sys.exit(255 if host.endswith("down") else 0)
if host.endswith("down") or host.endswith("unreachable"):
    sys.stderr.write("ssh: connect to host %s port 22: Operation timed out\n" % host)
    sys.exit(255)
prefix = "sudo kubectl --kubeconfig /etc/kubernetes/admin.conf -n kgate "
assert remote.startswith(prefix), remote
a = shlex.split(remote[len(prefix):])
log({"kubectl": a})
scenario = os.environ.get("FAKE_POD", "ready")
if a[:2] == ["get", "namespace"]:
    print("namespace/kgate"); sys.exit(0)
if a[0] == "delete":
    sys.exit(fake_delete(fake, a[1:]))
if a[:2] == ["get", "pods"] and os.environ.get("FAKE_PODS_FAIL"):
    sys.stderr.write("Error from server: etcdserver: request timed out\n"); sys.exit(1)
if a[:2] == ["get", "pods"] and os.environ.get("FAKE_PODS") and os.path.exists(os.environ["FAKE_PODS"]):   # the kgate pods the cluster holds: a file the test writes (and empties when room appears)
    print(open(os.environ["FAKE_PODS"]).read()); sys.exit(0)
if a[:2] == ["get", "pods"] or a[:2] == ["get", "secrets"]:
    print(json.dumps({"items": []})); sys.exit(0)
if a[:2] == ["create", "-f"]:
    manifest = json.load(sys.stdin)
    log({"manifest": manifest})
    if os.environ.get("FAKE_QUOTA_CPU"):
        # A namespace ResourceQuota of requests.cpu=FAKE_QUOTA_CPU. The file <fake>/quota-full holds the cpu other jobs use of it (none when the file is not there).
        # Like the API server, the List is made item by item: the Secrets that come first go in, then the pod is refused when it does not fit, and a Secret that is
        # already there is refused (AlreadyExists) whatever happens to the pod. The pod made is logged as {"created": name}.
        limit = int(os.environ["FAKE_QUOTA_CPU"])
        used_file = os.path.join(fake, "quota-full")
        try:
            used = int(open(used_file).read())
        except FileNotFoundError:   # the test took the file away (room()), possibly between a look and a read: no one else uses the quota
            used = 0
        held = os.path.join(fake, "quota-held")   # FAKE_QUOTA_HOLD: the pods made here count toward the quota until they are deleted, as on a real cluster
        if os.environ.get("FAKE_QUOTA_HOLD") and os.path.isdir(held):
            used += sum(int(open(os.path.join(held, n)).read()) for n in os.listdir(held))
        os.makedirs(os.path.join(fake, "secrets"), exist_ok=True)
        failed = False
        for item in manifest["items"]:
            name = item["metadata"]["name"]
            if item["kind"] == "Secret":
                path = os.path.join(fake, "secrets", name)
                if os.path.exists(path):
                    sys.stderr.write('Error from server (AlreadyExists): error when creating "STDIN": secrets "%s" already exists\n' % name); failed = True
                else:
                    open(path, "w").close()
                continue
            spec = item["spec"]   # the pod's request is its containers' and its native sidecars' (init containers that keep running) together
            asked = sum(int(c["resources"]["requests"]["cpu"]) for c in spec["containers"] + [i for i in spec.get("initContainers", []) if i.get("restartPolicy") == "Always"])
            counted = not os.environ.get("FAKE_QUOTA_CLASS") or spec.get("priorityClassName") == os.environ["FAKE_QUOTA_CLASS"]   # a scoped quota (FAKE_QUOTA_CLASS) counts and refuses only pods of that PriorityClass
            if os.environ.get("FAKE_CREATE_ERROR"):
                sys.stderr.write(os.environ["FAKE_CREATE_ERROR"] + "\n"); failed = True
            elif counted and used + asked > limit:
                sys.stderr.write('Error from server (Forbidden): error when creating "STDIN": pods "%s" is forbidden: exceeded quota: %s, requested: requests.cpu=%d, used: requests.cpu=%d, limited: requests.cpu=%d\n'
                                 % (name, os.environ.get("FAKE_QUOTA_NAME", "scratch-cpu"), asked, used, limit)); failed = True
            else:
                log({"created": name})
                if os.environ.get("FAKE_QUOTA_HOLD") and counted:
                    os.makedirs(held, exist_ok=True)
                    open(os.path.join(held, name), "w").write(str(asked))
        sys.exit(1 if failed else 0)
    if os.environ.get("FAKE_CREATE_PENDING"):   # the cluster is full: the pod just created is listed as waiting for room, for the jobs that look next
        pod = manifest["items"][-1]
        pod["metadata"]["creationTimestamp"] = "2026-11-16T12:00:00Z"
        pod["status"] = {"phase": "Pending", "conditions": [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable", "message": "0/7 nodes are available: 7 Insufficient cpu."}]}
        path = os.environ["FAKE_PODS"]
        items = json.load(open(path))["items"] if os.path.exists(path) else []
        json.dump({"items": items + [pod]}, open(path, "w"))
    sys.exit(0)
if a[:2] == ["get", "pod"] and any(x.startswith("jsonpath=") for x in a):
    print(os.environ.get("FAKE_LABEL", "kgate"), end=""); sys.exit(0)
if a[:2] == ["get", "pod"] and os.environ.get("FAKE_GET_FAIL"):   # the API server times out on every read of the pod
    sys.stderr.write("Error from server: etcdserver: request timed out\n"); sys.exit(1)
if a[:2] == ["get", "pod"] and os.environ.get("FAKE_GET_FAIL_FIRST") and "json" in a:   # ... on the first N reads only, then it recovers
    count_file = os.path.join(fake, "get-pod-reads")
    reads = int(open(count_file).read()) if os.path.exists(count_file) else 0
    open(count_file, "w").write(str(reads + 1))
    if reads < int(os.environ["FAKE_GET_FAIL_FIRST"]):
        sys.stderr.write("Error from server: etcdserver: request timed out\n"); sys.exit(1)
if a[:2] == ["get", "events"]:   # the kubelet's Evicted event for a pod that died (FAKE_EVICT_EVENT) outlives the pod
    items = [{"reason": "Killing", "message": "Stopping container job"}] if os.environ.get("FAKE_EVICT_EVENT") and os.path.exists(os.path.join(fake, "died")) else []   # "-": the pod is gone and no event says why
    if items and os.environ["FAKE_EVICT_EVENT"] != "-":
        items.insert(0, {"reason": "Evicted", "message": os.environ["FAKE_EVICT_EVENT"]})
    print(json.dumps({"items": items})); sys.exit(0)
if a[:2] == ["get", "pod"] and os.environ.get("FAKE_EVICT_EVENT") and os.path.exists(os.path.join(fake, "died")):   # the kubelet is deleting the evicted pod, or it is already gone
    if os.environ.get("FAKE_EVICT_GONE"):
        sys.stderr.write('Error from server (NotFound): pods "%s" not found\n' % a[2]); sys.exit(1)
    print(json.dumps({"metadata": {"deletionTimestamp": "2026-11-16T12:00:00Z"}, "status": {"phase": "Running"}})); sys.exit(0)
if a[:2] == ["get", "pod"] and os.environ.get("FAKE_EVICT") and (scenario == "evicted" or os.path.exists(os.path.join(fake, "died"))):
    # the node evicted the pod: it stays as Failed/Evicted with the kubelet's message (FAKE_POD=evicted: before it ran; else after the exec connection died)
    print(json.dumps({"spec": {"nodeName": "fake-node"}, "status": {"phase": "Failed", "reason": "Evicted", "message": os.environ["FAKE_EVICT"]}})); sys.exit(0)
if a[:2] == ["get", "pod"]:
    if scenario == "ready":
        st = {"phase": "Running", "containerStatuses": [{"ready": True, "state": {"running": {}}}]}
    elif scenario == "pullfail":
        st = {"phase": "Pending", "containerStatuses": [{"ready": False, "state": {"waiting": {"reason": "ErrImagePull", "message": "401 unauthorized"}}}]}
    elif scenario == "slow":   # the first two looks (one when the pod is placed, one when kgate waits for it) find the image still being pulled; later looks find the pod running
        reads = os.path.join(fake, "slow-reads")
        n = int(open(reads).read()) + 1 if os.path.exists(reads) else 1
        open(reads, "w").write(str(n))
        if n <= 2:
            st = {"phase": "Pending", "conditions": [{"type": "PodScheduled", "status": "True"}], "containerStatuses": [{"ready": False, "state": {"waiting": {"reason": "ContainerCreating"}}}]}
        else:
            st = {"phase": "Running", "containerStatuses": [{"ready": True, "state": {"running": {}}}]}
    elif scenario == "pulling":   # scheduled to a node, image still being pulled: not Unschedulable
        st = {"phase": "Pending", "conditions": [{"type": "PodScheduled", "status": "True"}], "containerStatuses": [{"ready": False, "state": {"waiting": {"reason": "ContainerCreating"}}}]}
    else:
        st = {"phase": "Pending", "conditions": [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable", "message": "0/7 nodes are available: 7 Insufficient cpu."}]}
    if os.environ.get("FAKE_DOCKER"):   # the pod has a dind sidecar: a native sidecar reports under initContainerStatuses
        healthy = {"name": "dind", "started": True, "restartCount": 0, "state": {"running": {}}}
        died = {"name": "dind", "started": True, "restartCount": 1, "state": {"running": {}}, "lastState": {"terminated": {"exitCode": 137, "reason": "OOMKilled"}}}
        stopped = {"name": "dind", "started": True, "restartCount": 0, "state": {"terminated": {"exitCode": 137, "reason": "OOMKilled"}}}
        side, ended = healthy, os.path.exists(os.path.join(fake, "cmd-ended"))
        if os.environ["FAKE_DOCKER"] == "crash":
            st = {"phase": "Pending", "initContainerStatuses": [{"name": "dind", "started": False, "restartCount": 1, "state": {"terminated": {"exitCode": 127}}}]}
        elif ended:   # reads of the pod after CMD is over are counted (<fake>/ended-reads); "dies" and "stopped" show the daemon gone, FAKE_DOCKER_LAG reads late, as the kubelet does
            reads = os.path.join(fake, "ended-reads")
            n = int(open(reads).read()) + 1 if os.path.exists(reads) else 1
            open(reads, "w").write(str(n))
            if os.environ["FAKE_DOCKER"] in ("dies", "stopped") and n > int(os.environ.get("FAKE_DOCKER_LAG", "0")):
                side = died if os.environ["FAKE_DOCKER"] == "dies" else stopped
        if st.get("phase") == "Running":
            st["initContainerStatuses"] = [side]
    print(json.dumps({"spec": {"nodeName": "fake-node"}, "status": st})); sys.exit(0)
if a[0] == "logs":   # the sidecar's log: what the failing daemon printed
    print("fake dockerd log: line one\nfake dockerd log: cannot start"); sys.exit(0)
if a[0] == "exec" and "-c" in a and a[a.index("-c") + 1] == "dind":   # the sidecar's cgroup, read after CMD
    print("734003200"); sys.exit(0)
if a[0] == "exec" and "-i" in a:
    job = a[2]
    data = sys.stdin.buffer.read()
    # A real pod has a real /tmp; on a Mac /tmp is a symlink tar will not extract through, so the job's own two files go under FAKE.
    jobroot = os.path.join(fake, "jobroot")
    os.makedirs(jobroot, exist_ok=True)
    tar2 = subprocess.run(["tar", "-xf", "-", "--no-same-owner", "-C", jobroot, "tmp/%s" % job], input=data)
    # The pod unpacks onto its own empty disk. Here the shipped worktree has the path of the test's real repo, which other clients are reading at the same moment (git, the
    # hash): tar would delete and recreate each file under them, and a client that looked in between failed with "not a git repository" (dotfiles#732). The files
    # are the very ones that are there, so the worktree is left out of the unpack; whatever else the tar holds is unpacked as before.
    root = json.load(open("%s/tmp/%s/job.json" % (jobroot, job))).get("root") if tar2.returncode == 0 else None
    skip = ["--exclude", root.strip("/")] if root else []
    tar = subprocess.run(["tar", "-xf", "-", "--no-same-owner", "-C", "/", "--exclude", "tmp/kgate-*", *skip], input=data)
    if tar.returncode or tar2.returncode:
        sys.exit(1)
    if os.environ.get("FAKE_TAMPER"):
        with open(os.environ["FAKE_TAMPER"], "ab") as f:
            f.write(b"x")
    env = dict(os.environ, KGATE_OUT=os.path.join(fake, "out"), KGATE_NODE="fake-node")
    os.makedirs(env["KGATE_OUT"], exist_ok=True)
    proc = subprocess.Popen([sys.executable, "%s/tmp/%s/kgate.py" % (jobroot, job), "--pod", "%s/tmp/%s/job.json" % (jobroot, job)], env=env, stdout=subprocess.PIPE)
    for line in iter(proc.stdout.readline, b""):
        sys.stdout.buffer.write(line); sys.stdout.buffer.flush()
        if os.environ.get("FAKE_DIE") and b"]: running" in line:
            proc.kill(); open(os.path.join(fake, "died"), "w").write("x"); sys.stderr.write("error: lost connection to pod\n"); sys.exit(255)
    code = proc.wait()
    open(os.path.join(fake, "cmd-ended"), "w").write("x")   # CMD is over: a dind sidecar the fake kills, dies from here on (FAKE_DOCKER)
    sys.exit(code)
if a[0] == "exec" and a[-1] == "/sys/fs/cgroup/memory.events":   # the container's cgroup, read after the pod was lost
    print("low 0\nhigh 0\nmax 0\noom 0\noom_kill %s" % os.environ.get("FAKE_OOM_KILLS", "0")); sys.exit(0)
if a[0] == "exec":
    out = os.path.join(fake, "out")
    os.makedirs(out, exist_ok=True)
    sys.exit(subprocess.call(["tar", "-cf", "-", "-C", out, "."], env=dict(os.environ, COPYFILE_DISABLE="1")))
sys.stderr.write("fake kubectl: unexpected " + repr(a) + "\n"); sys.exit(2)
'''

FAKE_OP = r'''#!/bin/sh
echo "$*" >> "$FAKE/op-calls"
case "${OP_SERVICE_ACCOUNT_TOKEN-}" in
"") echo unset >> "$FAKE/op-token-checks" ;;
"$FAKE_TOKEN") echo ok >> "$FAKE/op-token-checks" ;;
*) echo wrong >> "$FAKE/op-token-checks" ;;
esac
[ -n "$FAKE_OP_HANG" ] && sleep 120
[ -n "$FAKE_OP_SLEEP" ] && sleep "$FAKE_OP_SLEEP"
[ -n "$FAKE_OP_FAIL" ] && { echo "[ERROR] item not found" >&2; exit 1; }
printf 'value-of-%s' "$(basename "$2")"
'''


FAKE_CLIENT = r'''import json, os, signal, sys, time
state, job_id, run_id, mode = sys.argv[1:5]
def term(*_):
    if mode == "ignore":
        return
    marked = os.path.exists(os.path.join(state, "active", job_id + ".cancel"))
    with open(os.path.join(state, "log.jsonl"), "a") as f:
        f.write(json.dumps({"id": job_id, "job": run_id, "exit": 143,
                            "reason": "cancelled by kgate cancel" if marked else "interrupted (SIGTERM)"}) + "\n")
    os._exit(143)
signal.signal(signal.SIGTERM, term)
print("ready", flush=True)
while True:
    time.sleep(0.1)
'''


def stub_launcher(tmp, name, text):
    """The command that runs the client through a stub script. A test calls launcher() again for each client it starts, and a client that has just started is still reading
    the stub: writing the file in place truncates it first, and a client that reads it then runs an empty script, exits 0 and prints nothing. The new text goes to
    another name and is renamed over the stub, so a reader has all of the old text or all of the new."""
    stub = tmp / name
    new = tmp / (name + ".new")
    new.write_text(text)
    os.replace(new, stub)
    return [sys.executable, str(stub), str(SCRIPT)]


class StubLauncher(unittest.TestCase):
    def test_a_client_that_has_the_stub_open_reads_all_of_its_text_while_the_next_launch_writes_it_again(self):
        tmp = Path(tempfile.mkdtemp(prefix="kt-stub-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        command = stub_launcher(tmp, "s.py", "print('first')\n" * 1000)
        with open(command[1]) as reading:   # a client that has started and has not read the stub yet
            stub_launcher(tmp, "s.py", "print('second')\n")
            self.assertEqual(reading.read(), "print('first')\n" * 1000)
        self.assertEqual(Path(command[1]).read_text(), "print('second')\n", "the next client runs the new text")


class Black(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kt-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.fake = self.tmp / "fake"
        self.state = self.tmp / "state"
        self.home = self.tmp / "home"  # no token file here, so the real ~/.config is never read
        self.cache = self.tmp / "cache"  # the secret cache is per test: a cache hit would hide the op calls these tests count
        for d in (self.bin, self.fake, self.home):
            d.mkdir()
        patch = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.cache)})
        patch.start()
        self.addCleanup(patch.stop)
        for name, text in (("ssh", FAKE_SSH), ("op", FAKE_OP)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / "tracked.txt").write_text("tracked\n")
        (self.repo / ".gitignore").write_text("ignored.txt\nnode_modules/\n")
        self.profile(tools='node = "1.2.3"\n' if False else "")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")
        (self.repo / "untracked.txt").write_text("new\n")
        (self.repo / "tracked.txt").write_text("tracked and changed\n")
        (self.repo / "ignored.txt").write_text("stays here\n")

    def profile(self, tools="", extra="", secrets="", memory="1Gi"):
        (self.repo / "kgate.toml").write_text('image = "%s"\ncpu = 2\nmemory = "%s"\n%s\n[tools]\n%s\n[secrets]\n%s\n' % (DIGEST, memory, extra, tools, secrets))

    def op_env(self):
        """The 1Password token and HOME every test starts with: a stand-in token, and a HOME with no token file."""
        return {"HOME": str(self.home), "OP_SERVICE_ACCOUNT_TOKEN": FAKE_TOKEN, "FAKE_TOKEN": FAKE_TOKEN}

    def kgate(self, *args, host="fake", env=None):
        e = {**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
             "KGATE_SSH": host, "KGATE_SSH_KEY": "/dev/null", "RUN_AND_WAKE_JOB": "20261104T000000Z-abcdef", **self.op_env(), **(env or {})}
        # the module reads KGATE_SSH at import, so run the script as a process
        return subprocess.run([*self.launcher(), *args], cwd=self.repo, env=e, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, timeout=120)

    def launcher(self):
        return [sys.executable, str(SCRIPT)]

    def kgate_popen(self, *args, host="fake", env=None):
        """The client as a process of its own, in a process group of its own (so a test can signal the group the way a stop does, and no test run is in it)."""
        e = {**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
             "KGATE_SSH": host, "KGATE_SSH_KEY": "/dev/null", "RUN_AND_WAKE_JOB": "20261104T000000Z-abcdef", **self.op_env(), **(env or {})}
        return subprocess.Popen([*self.launcher(), *args], cwd=self.repo, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)

    def records(self):
        path = self.state / "kgate" / "log.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def calls(self):
        path = self.fake / "calls.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def op_token_checks(self):
        """What each fake `op` run saw in OP_SERVICE_ACCOUNT_TOKEN: ok (the token), unset, or wrong."""
        path = self.fake / "op-token-checks"
        return path.read_text().split() if path.exists() else []

    # --- the journeys

    def test_passes_with_cmds_exit_code_and_returns_out(self):
        done = self.kgate("--", "sh", "-c", 'echo ran-in-pod; cat tracked.txt untracked.txt; echo result > "$KGATE_OUT/result.txt"')
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ran-in-pod", done.stdout)
        self.assertIn("tracked and changed", done.stdout)          # the uncommitted change shipped
        self.assertIn("new", done.stdout)                           # the untracked file shipped
        rec = self.records()[-1]
        shipped = json.loads((self.fake / "jobroot" / "tmp" / rec["id"] / "job.json").read_text())["files"]
        self.assertEqual(sorted(shipped), [".gitignore", "kgate.toml", "tracked.txt", "untracked.txt"])  # not ignored.txt
        self.assertEqual((rec["exit"], rec["reason"], rec["ran"], rec["cleanup"]), (0, None, True, True))
        self.assertEqual(rec["job"], "20261104T000000Z-abcdef")
        self.assertEqual(rec["node"], "fake-node")
        self.assertEqual(rec["image"], DIGEST)
        self.assertRegex(rec["tree"], r"^[0-9a-f]{40}$")
        self.assertRegex(rec["head"], r"^[0-9a-f]{40}$")
        self.assertEqual(rec["repo"], "repo")
        for key in ("start", "end", "duration_s", "peak_bytes", "peak_source", "out_files", "cmd"):
            self.assertIn(key, rec)
        self.assertEqual(rec["out_files"], 1)
        self.assertEqual((self.state / "kgate" / (rec["id"] + ".out") / "result.txt").read_text(), "result\n")
        self.assertIn("ran-in-pod", (self.state / "kgate" / rec["output"]).read_text())

    def test_tree_hash_in_the_pod_equals_the_one_computed_here(self):
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        rec = self.records()[-1]
        self.assertIn("kgate[%s]: hash ok %s" % (rec["id"], rec["tree"]), done.stdout)

    def test_a_profile_with_install_npm_serves_npm_ci_from_the_node_cache_and_records_it(self):
        for name, text in (("npm", FAKE_NPM), ("node", FAKE_NODE)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        (self.repo / "package.json").write_text("{}\n")
        (self.repo / "package-lock.json").write_text("lock\n")
        self.profile(extra="[install]\nnpm = true\n")
        env = {"KGATE_CACHE_ROOT": str(self.tmp / "nodecache"), "FAKE_LOG": str(self.tmp / "npm.log")}
        for _ in range(2):
            done = self.kgate("--", "sh", "-c", "npm ci && test -f node_modules/pkg/index.js", env=env)
            self.assertEqual(done.returncode, 0, done.stdout)
        first, second = self.records()[-2:]
        self.assertEqual(first["install"], "miss")
        self.assertEqual(second["install"], "hit")
        self.assertTrue(all(isinstance(r["install_s"], float) and r["install_s"] >= 0 for r in (first, second)), (first["install_s"], second["install_s"]))
        self.assertEqual(len(list((self.tmp / "nodecache" / "u1000" / "nm" / "repo").glob("*.tar"))), 1, "one folder per repo, named for the repo")
        done = self.kgate("--", "true", env=env)   # a command that never runs npm ci
        self.assertEqual((done.returncode, self.records()[-1]["install"], self.records()[-1]["install_s"]), (0, "none", 0.0))

    def test_without_install_in_the_profile_npm_ci_is_not_touched(self):
        for name, text in (("npm", FAKE_NPM), ("node", FAKE_NODE)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        (self.repo / "package.json").write_text("{}\n")
        (self.repo / "package-lock.json").write_text("lock\n")
        env = {"KGATE_CACHE_ROOT": str(self.tmp / "nodecache"), "FAKE_LOG": str(self.tmp / "npm.log")}
        done = self.kgate("--", "npm", "ci", env=env)
        self.assertEqual(done.returncode, 0, done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["install"], rec["install_s"]), ("none", 0.0))
        self.assertFalse((self.tmp / "nodecache").exists())
        self.assertEqual((self.tmp / "npm.log").read_text(), "npm ci\n")

    def test_a_job_that_never_ran_has_no_install_in_its_record(self):
        done = self.kgate("--profile", str(self.tmp / "missing.toml"), "--", "true")
        self.assertEqual(done.returncode, 69)
        rec = self.records()[-1]
        self.assertEqual((rec["install"], rec["install_s"]), (None, None))

    def test_cmd_failure_is_cmds_exit_code_not_69(self):
        done = self.kgate("--", "sh", "-c", "echo boom; exit 3")
        self.assertEqual(done.returncode, 3, done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["ran"]), (3, None, True))

    def test_out_comes_back_even_when_cmd_fails(self):
        done = self.kgate("--", "sh", "-c", 'echo trace > "$KGATE_OUT/trace.txt"; exit 1')
        self.assertEqual(done.returncode, 1)
        out = self.state / "kgate" / (self.records()[-1]["id"] + ".out")
        self.assertEqual((out / "trace.txt").read_text(), "trace\n")

    def test_tree_hash_mismatch_is_69_and_cmd_does_not_run(self):
        marker = self.tmp / "cmd-ran"
        done = self.kgate("--", "sh", "-c", "touch %s" % marker, env={"FAKE_TAMPER": str(self.repo / "tracked.txt")})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertFalse(marker.exists())
        self.assertIn("tree hash differs", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"]), (69, False))
        self.assertIn("tree hash differs", rec["reason"])

    def test_wrong_tool_version_is_69_with_tool_expected_and_found(self):
        self.profile(tools='sh = { version = "99.99.99", cmd = "echo sh version 1.2.3" }')
        marker = self.tmp / "cmd-ran"
        done = self.kgate("--", "sh", "-c", "touch %s" % marker)
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertFalse(marker.exists())
        self.assertRegex(done.stdout, r"tool version differs: tool=sh expected=99.99.99 found=\"sh version 1.2.3\"")

    def test_right_tool_version_passes(self):
        self.profile(tools='sh = { version = "1.2.3", cmd = "echo sh version 1.2.3" }\nmissing = "1.0.0"')
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("tool=missing expected=1.0.0", done.stdout)
        self.profile(tools='sh = { version = "1.2.3", cmd = "echo sh version 1.2.3" }')
        self.assertEqual(self.kgate("--", "true").returncode, 0)

    def test_unreachable_cluster_is_69_and_nothing_runs_here(self):
        marker = self.tmp / "cmd-ran"
        done = self.kgate("--", "sh", "-c", "touch %s" % marker, host="cartwmic@unreachable")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertFalse(marker.exists())
        self.assertIn("cluster unreachable", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"]), (69, False))
        self.assertIn("unreachable", rec["reason"])

    def test_host_list_parses_commas_lines_and_comments(self):
        self.assertEqual(K.parse_hosts("a@1, b@2\n# c@3\n\nd@4\n"), ["a@1", "b@2", "d@4"])
        self.assertEqual(K.parse_hosts("a@1"), ["a@1"])
        self.assertEqual(K.parse_hosts(""), [])
        self.assertEqual(K.parse_hosts(None), [])

    def test_first_reachable_host_is_used_and_named(self):
        done = self.kgate("--", "true", host="u@one-down,u@two,u@three")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("kgate: control plane u@two", done.stdout)
        self.assertEqual([c["probe"] for c in self.calls() if "probe" in c], ["u@one-down", "u@two"])
        self.assertTrue(any("kubectl" in c for c in self.calls()))

    def test_host_file_list_is_used_when_kgate_ssh_is_unset(self):
        (self.home / ".config" / "kgate").mkdir(parents=True)
        (self.home / ".config" / "kgate" / "host").write_text("u@one-down\nu@two\n")
        done = self.kgate("--", "true", host="", env={"HOME": str(self.home)})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("kgate: control plane u@two", done.stdout)

    def test_no_host_in_the_list_answers_is_69(self):
        done = self.kgate("--", "true", host="u@a-down,u@b-down")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("no control plane answered", done.stdout)
        self.assertFalse(any("kubectl" in c for c in self.calls()))

    def test_one_host_is_not_probed_and_prints_no_host_line(self):
        done = self.kgate("--", "true", host="u@only")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertNotIn("control plane", done.stdout)
        self.assertFalse(any("probe" in c for c in self.calls()))

    def test_no_host_is_69_names_the_key_and_makes_no_ssh_call(self):
        marker = self.tmp / "cmd-ran"
        home = self.tmp / "no-host-home"
        home.mkdir()
        done = self.kgate("--", "sh", "-c", "touch %s" % marker, host="", env={"HOME": str(home)})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertFalse(marker.exists())
        self.assertIn("sshHosts.kgate", done.stdout)
        self.assertNotIn("cleanup", done.stdout)
        self.assertEqual(self.calls(), [])  # no ssh attempt, not even the cleanup one
        self.assertEqual(self.records()[-1]["exit"], 69)

    def test_pod_that_cannot_pull_its_image_is_69_and_is_cleaned_up(self):
        done = self.kgate("--", "true", env={"FAKE_POD": "pullfail"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("ErrImagePull", done.stdout)
        self.assertTrue(any(c.get("kubectl", [""])[0] == "delete" and any(x.startswith("pod/") for x in c["kubectl"]) for c in self.calls()))
        self.assertTrue(self.records()[-1]["cleanup"])

    def test_pod_that_never_gets_a_node_is_69_after_wait(self):
        done = self.kgate("--wait", "3", "--", "true", env={"FAKE_POD": "pending"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("pod did not start within 3s: Unschedulable", done.stdout)

    def pod_deletes(self):
        return [c for c in self.calls() if c.get("kubectl", [""])[0] == "delete" and any(x.startswith("pod/") for x in c["kubectl"])]

    def test_unschedulable_past_the_scheduling_deadline_is_75_and_the_pod_is_deleted(self):
        done = self.kgate("--sched-wait", "2", "--node", "cartwmic-g14-wsl", "--", "true", env={"FAKE_POD": "pending"})
        self.assertEqual(done.returncode, 75, done.stdout)
        line = [l for l in done.stdout.splitlines() if l.startswith("kgate: pod not scheduled within")]
        self.assertEqual(len(line), 1, done.stdout)
        self.assertIn("pod not scheduled within 2s: 0/7 nodes are available: 7 Insufficient cpu. (pinned to node cartwmic-g14-wsl); exit 75", line[0])
        self.assertTrue(self.pod_deletes())
        rec = self.records()[-1]
        self.assertEqual(rec["exit"], 75)
        self.assertFalse(rec["ran"])
        self.assertTrue(rec["cleanup"])

    def test_no_pin_means_no_pin_in_the_75_line(self):
        done = self.kgate("--sched-wait", "1", "--", "true", env={"FAKE_POD": "pending"})
        self.assertEqual(done.returncode, 75, done.stdout)
        self.assertNotIn("pinned", done.stdout)

    def test_the_scheduling_deadline_defaults_to_30_minutes(self):   # a 75 loses the job's place in the queue, so the default waits longer than a resubmit would
        self.assertEqual(K.parse_args(["--", "true"]).sched_wait, 1800)
        self.assertEqual(K.SCHED_WAIT_S, 1800)

    def test_scheduling_deadline_from_env_and_the_flag_wins(self):
        done = self.kgate("--", "true", env={"FAKE_POD": "pending", "KGATE_SCHED_WAIT": "1"})
        self.assertEqual(done.returncode, 75, done.stdout)
        self.assertIn("pod not scheduled within 1s", done.stdout)
        done = self.kgate("--sched-wait", "2", "--wait", "3", "--", "true", env={"FAKE_POD": "pending", "KGATE_SCHED_WAIT": "1"})
        self.assertEqual(done.returncode, 75, done.stdout)
        self.assertIn("pod not scheduled within 2s", done.stdout)

    def test_a_scheduled_pod_that_is_pulling_is_not_unschedulable(self):
        # scheduled, image pulling: the scheduling deadline does not apply; only --wait ends it (69)
        done = self.kgate("--sched-wait", "1", "--wait", "4", "--", "true", env={"FAKE_POD": "pulling"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("pod did not start within 4s: ContainerCreating", done.stdout)
        self.assertNotIn("pod not scheduled", done.stdout)

    def test_bad_scheduling_deadline_is_64(self):
        for args, env in ((["--sched-wait", "0"], {}), (["--sched-wait", "x"], {}), ([], {"KGATE_SCHED_WAIT": "x"}), ([], {"KGATE_SCHED_WAIT": "-5"})):
            done = self.kgate(*args, "--", "true", env=env)
            self.assertEqual(done.returncode, 64, (args, env, done.stdout))

    # --- a command that names a file the pod will not have

    def outside(self, name, text="echo hi\n"):
        """A real file next to the worktree: it exists here, and kgate does not ship it."""
        d = self.tmp / "outside"
        d.mkdir(exist_ok=True)
        (d / name).write_text(text)
        return d / name

    def refused(self, done, path):
        self.assertEqual(done.returncode, 64, done.stdout)
        self.assertIn("kgate: refused: %s is outside the worktree %s" % (path, self.repo), done.stdout)
        self.assertIn("sh -c", done.stdout)
        self.assertEqual(self.records(), [], "nothing was submitted, so the log has no record")
        self.assertEqual(self.calls(), [], "no ssh or kubectl call was made")

    def test_a_script_outside_the_worktree_is_refused_before_anything_is_submitted(self):
        # the 2026-11-13 loop-engine builder: kgate -- sh /tmp/.../scratchpad/unit.sh
        script = self.outside("unit.sh")
        self.refused(self.kgate("--", "sh", str(script)), script)

    def test_the_profile_may_live_outside_but_the_script_may_not(self):
        # the 2026-11-13 kgate-only builder: --profile /tmp/probe.toml ... -- sh /tmp/probe.sh. kgate reads the profile here, so only the script is refused.
        profile = self.outside("probe.toml", (self.repo / "kgate.toml").read_text())
        script = self.outside("probe.sh")
        self.refused(self.kgate("--profile", str(profile), "--sched-wait", "3600", "--", "sh", str(script)), script)
        done = self.kgate("--profile", str(profile), "--", "echo", "ran")
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_a_relative_path_that_leaves_the_worktree_is_refused(self):
        self.outside("up.sh")
        done = self.kgate("--", "sh", "../outside/up.sh")
        self.refused(done, self.tmp / "outside" / "up.sh")

    def test_a_directory_outside_the_worktree_is_refused(self):
        self.outside("x.sh")
        self.refused(self.kgate("--", "ls", str(self.tmp / "outside")), self.tmp / "outside")

    def test_a_file_in_the_worktree_runs(self):
        done = self.kgate("--", "cat", str(self.repo / "tracked.txt"), "./untracked.txt")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("tracked and changed", done.stdout)

    def test_an_inline_script_runs(self):
        done = self.kgate("--", "sh", "-c", "echo inline-ran")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("inline-ran", done.stdout)

    def test_a_system_path_runs(self):
        done = self.kgate("--", "/bin/sh", "-c", "echo system-ran")
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_a_pod_only_path_that_does_not_exist_here_runs(self):
        done = self.kgate("--", "echo", "/out/result.txt", "/cache/dir", str(self.tmp / "made-in-the-pod.txt"))
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_a_location_itself_runs(self):
        # /tmp and the home folder exist in every pod; only something inside them is the user's own file
        done = self.kgate("--", "echo", "/tmp", "/var/tmp", str(self.home))
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_outside_a_git_worktree_the_run_fails_the_old_way_not_as_a_refusal(self):
        script = self.outside("unit.sh")
        done = subprocess.run([sys.executable, str(SCRIPT), "--", "sh", str(script)], cwd=self.tmp / "outside", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              env={**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
                                   "KGATE_SSH": "fake", "KGATE_SSH_KEY": "/dev/null", **self.op_env()})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertNotIn("refused", done.stdout)

    def test_version_commands_run_in_the_jobs_directory(self):
        # rustup picks the toolchain by directory, so a preflight that ran elsewhere would check the wrong tool
        sub = self.repo / "sub-9.8.7"
        sub.mkdir()
        (sub / "f.txt").write_text("x")
        self.profile(tools='dir = { version = "9.8.7", cmd = "pwd" }')
        done = subprocess.run([sys.executable, str(SCRIPT), "--", "pwd"], cwd=sub, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              env={**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake),
                                   "XDG_STATE_HOME": str(self.state), "KGATE_SSH": "fake", "KGATE_SSH_KEY": "/dev/null", **self.op_env()})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("sub-9.8.7", done.stdout)

    def test_the_repo_is_named_for_the_origin_not_the_folder(self):
        git(self.repo, "remote", "add", "origin", "git@github.com:cartwmic/coordinator.git")
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.records()[-1]["repo"], "coordinator")  # the folder is "repo"

    def test_a_linked_worktree_of_a_clone_is_named_for_the_origin_too(self):
        git(self.repo, "remote", "add", "origin", "https://github.com/cartwmic/coordinator")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "second")
        linked = self.tmp / "wt-x"
        git(self.repo, "worktree", "add", "-q", str(linked), "-b", "side")
        done = subprocess.run([sys.executable, str(SCRIPT), "--", "true"], cwd=linked, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              env={**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake),
                                   "XDG_STATE_HOME": str(self.state), "KGATE_SSH": "fake", "KGATE_SSH_KEY": "/dev/null", **self.op_env()})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.records()[-1]["repo"], "coordinator")

    def test_a_linked_worktree_ships_and_hashes(self):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "second")
        linked = self.tmp / "linked"
        git(self.repo, "worktree", "add", "-q", str(linked), "-b", "side")
        (linked / "only-here.txt").write_text("linked\n")
        done = subprocess.run([sys.executable, str(SCRIPT), "--", "sh", "-c", "git rev-parse --show-toplevel && cat only-here.txt"], cwd=linked,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                              env={**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake),
                                   "XDG_STATE_HOME": str(self.state), "KGATE_SSH": "fake", "KGATE_SSH_KEY": "/dev/null", **self.op_env()})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("linked", done.stdout)
        rec = self.records()[-1]
        self.assertEqual(rec["repo"], "repo")  # named for the main repo, not the worktree folder
        self.assertIn("hash ok " + rec["tree"], done.stdout)

    def test_a_lost_connection_after_start_is_69_unknown_and_not_rerun(self):
        done = self.kgate("--", "sh", "-c", "echo started; sleep 1", env={"FAKE_DIE": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("lost the pod before CMD finished", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"]), (69, True))
        self.assertEqual(sum(1 for c in self.calls() if c.get("kubectl", [""])[0] == "exec" and "-i" in c["kubectl"]), 1)  # one exec: no rerun

    EVICTION = ("The node was low on resource: ephemeral-storage. Threshold quantity: 17.7Gi, available: 17.0Gi. "
                "Container job was using 1.15Gi, request is 0, has larger consumption of ephemeral-storage.")

    def test_a_pod_the_node_evicted_while_running_is_69_and_says_evicted(self):
        # dotfiles#484: the job read as a lost pod, with no word of why. The kubelet's message is on the Failed pod, read before the pod is deleted.
        done = self.kgate("--", "sh", "-c", "echo started; sleep 1", env={"FAKE_DIE": "1", "FAKE_EVICT": self.EVICTION})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("kgate: evicted: " + self.EVICTION + "; exit 69", done.stdout)
        self.assertNotIn("lost the pod before CMD finished", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["ran"], rec["cleanup"]), (69, "evicted: " + self.EVICTION, True, True))
        self.assertEqual(sum(1 for c in self.calls() if c.get("kubectl", [""])[0] == "exec" and "-i" in c["kubectl"]), 1)  # one exec: no rerun
        self.assertEqual(sum(1 for c in self.calls() if "manifest" in c), 1, "one pod created: no retry")
        kube = [c["kubectl"] for c in self.calls() if "kubectl" in c]
        last_read = max(n for n, k in enumerate(kube) if k[:2] == ["get", "pod"])
        first_delete = min(n for n, k in enumerate(kube) if k[0] == "delete" and any(x.startswith("pod/") for x in k))
        self.assertLess(last_read, first_delete, "the status is read before the pod is deleted")

    def test_an_evicted_pod_that_is_already_gone_is_read_from_the_kubelets_event(self):
        # the live run of 2026-11-16: the pod was NotFound by the time kgate looked, but the kubelet's Evicted event was still there
        why = "Pod ephemeral local storage usage exceeds the total limit of containers 512Mi."
        done = self.kgate("--", "sh", "-c", "echo started; sleep 1", env={"FAKE_DIE": "1", "FAKE_EVICT_EVENT": why})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("kgate: evicted: " + why + "; exit 69", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"]), (69, "evicted: " + why))

    def test_an_evicted_pod_already_deleted_is_read_from_the_event_too(self):
        why = "Pod ephemeral local storage usage exceeds the total limit of containers 512Mi."
        done = self.kgate("--", "sh", "-c", "echo started; sleep 1", env={"FAKE_DIE": "1", "FAKE_EVICT_EVENT": why, "FAKE_EVICT_GONE": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("kgate: evicted: " + why + "; exit 69", done.stdout)

    def test_a_pod_that_is_gone_with_no_evicted_event_is_still_a_lost_pod(self):
        done = self.kgate("--", "sh", "-c", "echo started; sleep 1", env={"FAKE_DIE": "1", "FAKE_EVICT_EVENT": "-"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("lost the pod before CMD finished", done.stdout)
        self.assertNotIn("evicted:", done.stdout)

    def test_a_pod_the_node_evicted_before_it_ran_is_69_and_says_evicted(self):
        done = self.kgate("--", "true", env={"FAKE_POD": "evicted", "FAKE_EVICT": self.EVICTION})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("kgate: evicted: " + self.EVICTION + "; exit 69", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["ran"]), (69, "evicted: " + self.EVICTION, False))

    def test_the_pod_carries_the_ephemeral_storage_request_and_a_profile_limit(self):
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        res = next(c["manifest"] for c in self.calls() if "manifest" in c)["items"][-1]["spec"]["containers"][0]["resources"]
        self.assertEqual((res["requests"]["ephemeral-storage"], res["limits"]["ephemeral-storage"]), ("4Gi", "12Gi"))
        self.profile(extra='ephemeral_storage = "20Gi"')
        (self.fake / "calls.jsonl").unlink()
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        res = next(c["manifest"] for c in self.calls() if "manifest" in c)["items"][-1]["spec"]["containers"][0]["resources"]
        self.assertEqual((res["requests"]["ephemeral-storage"], res["limits"]["ephemeral-storage"]), ("20Gi", "20Gi"))
        self.profile(extra='ephemeral_storage = "6Gi"\nephemeral_storage_limit = "7Gi"')
        (self.fake / "calls.jsonl").unlink()
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        res = next(c["manifest"] for c in self.calls() if "manifest" in c)["items"][-1]["spec"]["containers"][0]["resources"]
        self.assertEqual((res["requests"]["ephemeral-storage"], res["limits"]["ephemeral-storage"]), ("6Gi", "7Gi"))

    def pod_spec_sent(self):
        return next(c["manifest"] for c in self.calls() if "manifest" in c)["items"][-1]["spec"]

    def test_the_pod_is_in_kgate_by_default_and_in_kgate_first_when_the_profile_says_so(self):
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        self.assertEqual(self.pod_spec_sent()["priorityClassName"], "kgate")
        self.profile(extra='priority_class = "kgate-first"')
        (self.fake / "calls.jsonl").unlink()
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.pod_spec_sent()["priorityClassName"], "kgate-first")

    def test_a_priority_class_other_than_the_three_is_refused_before_any_pod(self):
        self.profile(extra='priority_class = "homelab-critical"')
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("profile priority_class must be kgate or kgate-first or kgate-main", self.records()[-1]["reason"])
        self.assertFalse(any("manifest" in c for c in self.calls()))

    def test_the_pod_is_in_kgate_main_when_the_profile_or_the_environment_says_so(self):
        self.profile(extra='priority_class = "kgate-main"')
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        self.assertEqual(self.pod_spec_sent()["priorityClassName"], "kgate-main")
        self.assertEqual(self.records()[-1]["priority_class"], "kgate-main")

    def test_KGATE_PRIORITY_CLASS_wins_over_the_profile_key_and_the_default(self):
        done = self.kgate("--", "true", env={"KGATE_PRIORITY_CLASS": "kgate-main"})   # no profile key: the default is overridden
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.pod_spec_sent()["priorityClassName"], "kgate-main")
        self.assertIn("priority class kgate-main\n", done.stdout)
        self.assertEqual(self.records()[-1]["priority_class"], "kgate-main")
        self.profile(extra='priority_class = "kgate-first"')   # a profile key: the environment still wins
        (self.fake / "calls.jsonl").unlink()
        done = self.kgate("--", "true", env={"KGATE_PRIORITY_CLASS": "kgate"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.pod_spec_sent()["priorityClassName"], "kgate")
        (self.fake / "calls.jsonl").unlink()
        done = self.kgate("--", "true", env={"KGATE_PRIORITY_CLASS": ""})   # empty is unset: the profile's key stands
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.pod_spec_sent()["priorityClassName"], "kgate-first")

    def test_an_unknown_KGATE_PRIORITY_CLASS_is_refused_before_any_pod_even_with_a_good_profile_key(self):
        self.profile(extra='priority_class = "kgate-first"')
        done = self.kgate("--", "true", env={"KGATE_PRIORITY_CLASS": "homelab-critical"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("KGATE_PRIORITY_CLASS must be kgate or kgate-first or kgate-main, got 'homelab-critical'", self.records()[-1]["reason"])
        self.assertFalse(any("manifest" in c for c in self.calls()))

    def test_a_homelab_cpu_limit_sets_limits_cpu_and_none_leaves_no_cpu_limit(self):
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        res = self.pod_spec_sent()["containers"][0]["resources"]
        self.assertNotIn("cpu", res["limits"])
        self.profile(extra="cpu_limit = 6")
        (self.fake / "calls.jsonl").unlink()
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        res = self.pod_spec_sent()["containers"][0]["resources"]
        self.assertEqual((res["requests"]["cpu"], res["limits"]["cpu"]), ("4", "6"))

    def test_the_pod_line_and_the_record_name_the_priority_class_and_the_cpu_limit_when_set(self):
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("memory request, priority class kgate\n", done.stdout)
        self.assertNotIn("cpu limit", done.stdout)
        rec = self.records()[-1]
        self.assertEqual(rec["priority_class"], "kgate")
        self.assertNotIn("cpu_limit", rec)
        self.profile(extra='priority_class = "kgate-first"\ncpu_limit = 5')
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("memory request, 5 cpu limit, priority class kgate-first\n", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["priority_class"], rec["cpu_limit"]), ("kgate-first", 5))

    def test_a_homelab_cpu_limit_below_the_request_is_refused_before_any_pod(self):
        self.profile(extra="cpu_limit = 1")   # checked against the raised request (2 -> 4), the one the pod would ask for
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("cpu_limit (1) must be at least cpu (4)", self.records()[-1]["reason"])
        self.assertFalse(any("manifest" in c for c in self.calls()))

    def test_a_command_that_prints_marker_lines_cannot_fake_the_outcome(self):
        done = self.kgate("--", "sh", "-c", "echo 'kgate: hash MISMATCH expected=a found=b'; echo 'kgate: end 1 exit 9'")
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_sigterm_cleans_up_and_exits_143(self):
        import signal as sig
        e = {**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
             "KGATE_SSH": "fake", "KGATE_SSH_KEY": "/dev/null", **self.op_env()}
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "--", "sh", "-c", "echo up; sleep 6"], cwd=self.repo, env=e,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            if "]: running" in line:
                break
        proc.send_signal(sig.SIGTERM)
        rest = proc.stdout.read()
        self.assertEqual(proc.wait(timeout=30), 143, rest)
        self.assertIn("interrupted (SIGTERM)", rest)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["cleanup"]), (143, True))

    def test_secret_unreadable_is_69_before_anything_is_created(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        done = self.kgate("--", "true", env={"FAKE_OP_FAIL": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("op read op://", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.calls()))

    def test_op_that_never_answers_is_69_not_a_hang(self):
        # the 30 s limit is the module's; shorten it by running the module's op_read with a fake that sleeps
        self.profile(secrets='TOK = "op://developer/item/password"')
        script = ("import importlib.machinery as m, importlib.util as u, subprocess, sys\n"
                  "orig = subprocess.run\n"
                  "subprocess.run = lambda *a, **k: orig(*a, **{**k, 'timeout': 1}) if a and a[0][:2] == ['op', 'read'] else orig(*a, **k)\n"
                  "l = m.SourceFileLoader('k', %r); s = u.spec_from_loader('k', l); mod = u.module_from_spec(s); l.exec_module(mod)\n"
                  "sys.exit(mod.main(sys.argv[1:]))\n" % str(SCRIPT))
        e = {**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
             "KGATE_SSH": "fake", "KGATE_SSH_KEY": "/dev/null", "FAKE_OP_HANG": "1", "PYTHONDONTWRITEBYTECODE": "1", **self.op_env()}
        done = subprocess.run([sys.executable, "-c", script, "--", "true"], cwd=self.repo, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("gave no answer", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.calls()))

    def test_secrets_reach_the_pod_as_secrets_and_never_the_log(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        manifest = next(c["manifest"] for c in self.calls() if "manifest" in c)
        kinds = [(i["kind"], i["metadata"]["name"]) for i in manifest["items"]]
        self.assertEqual(len(kinds), 3)  # env Secret, pull Secret, Pod
        raw = json.dumps(manifest["items"][-1])
        self.assertNotIn("value-of-password", raw)
        for text in (done.stdout, (self.state / "kgate" / self.records()[-1]["output"]).read_text(), json.dumps(self.records())):
            self.assertNotIn("value-of-password", text)
        ops = (self.fake / "op-calls").read_text().split("\n")
        self.assertIn("read op://developer/item/password", ops)
        self.assertIn("read op://developer/kgate-github-packages-read/password", ops)

    def test_services_the_pod_cannot_provide_stay_on_the_mac_by_failing(self):
        self.profile(extra='services = ["mssql"]')   # the homelab offers docker (tests/kgate/test_docker.py) and no other service
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("needs mssql", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.calls()))

    def test_unpinned_image_is_69(self):
        done = self.kgate("--image", "node:24", "--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("pinned by digest", done.stdout)

    def test_overflow_node_pin_is_refused(self):
        done = self.kgate("--node", "ubuntu-server-k8s-agent-4", "--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("overflow", done.stdout)

    def test_never_node_is_refused(self):
        done = self.kgate("--node", "mac-mini-worker", "--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("excluded", done.stdout)

    def test_the_runner_node_agent_3_is_refused(self):
        done = self.kgate("--node", "ubuntu-server-k8s-agent-3", "--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("excluded", done.stdout)

    def test_no_profile_and_no_image_is_69(self):
        (self.repo / "kgate.toml").unlink()
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("pinned by digest", done.stdout)

    def test_outside_a_git_worktree_is_69_not_a_mac_run(self):
        marker = self.tmp / "cmd-ran"
        e = {**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state), "KGATE_SSH": "fake", **self.op_env()}
        done = subprocess.run([sys.executable, str(SCRIPT), "--", "touch", str(marker)], cwd=self.tmp, env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertFalse(marker.exists())

    def test_bad_command_line_is_64(self):
        for args in ([], ["true"], ["--wait", "x", "--", "true"], ["--"], ["--bogus", "--", "true"]):
            done = self.kgate(*args)
            self.assertEqual(done.returncode, 64, (args, done.stdout))
        self.assertEqual(self.records(), [])

    # --- the 1Password service-account token: the environment, else the token file. Never the desktop app.

    def assert_no_token(self, *texts):
        for text in texts:
            self.assertNotIn(FAKE_TOKEN, text)

    def test_token_from_the_environment_reaches_every_op_read(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.op_token_checks(), ["ok", "ok"])  # the secret, then the pull credential
        rec = self.records()[-1]
        self.assert_no_token(done.stdout, (self.state / "kgate" / rec["output"]).read_text(), json.dumps(self.records()))

    def test_token_from_the_file_reaches_op_when_the_environment_has_none(self):
        (self.home / ".config/agent-harness").mkdir(parents=True)
        (self.home / ".config/agent-harness/op-service-token").write_text(FAKE_TOKEN + "\n")
        self.profile(secrets='TOK = "op://developer/item/password"')
        done = self.kgate("--", "true", env={"OP_SERVICE_ACCOUNT_TOKEN": ""})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.op_token_checks(), ["ok", "ok"])
        rec = self.records()[-1]
        self.assert_no_token(done.stdout, (self.state / "kgate" / rec["output"]).read_text(), json.dumps(self.records()))

    def test_no_token_is_69_with_the_exact_message_and_op_never_runs(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        marker = self.tmp / "cmd-ran"
        done = self.kgate("--", "sh", "-c", "touch %s" % marker, env={"OP_SERVICE_ACCOUNT_TOKEN": ""})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn(NO_TOKEN + "; exit 69, CMD was not run on this Mac", done.stdout)
        self.assertFalse(marker.exists())
        self.assertFalse((self.fake / "op-calls").exists(), "op was never run, so it could not fall back to the desktop app")
        self.assertFalse(any("manifest" in c for c in self.calls()), "no pod was created")
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"], rec["reason"]), (69, False, NO_TOKEN))

    def test_no_token_also_refuses_a_job_that_only_needs_the_pull_credential(self):
        done = self.kgate("--", "true", env={"OP_SERVICE_ACCOUNT_TOKEN": ""})  # no profile secrets: the ghcr pull credential still needs op
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn(NO_TOKEN, done.stdout)
        self.assertFalse((self.fake / "op-calls").exists())

    def test_a_job_with_no_op_read_needs_no_token(self):
        # no profile secrets and an image on a registry that needs no pull credential: kgate never calls op, so no token is needed
        done = self.kgate("--image", "docker.io/library/alpine@sha256:" + "ef" * 32, "--", "true", env={"OP_SERVICE_ACCOUNT_TOKEN": ""})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertFalse((self.fake / "op-calls").exists())

    # --- the secret cache: each reference is read with `op` at most once a day

    def op_reads(self):
        path = self.fake / "op-calls"
        return path.read_text().splitlines() if path.exists() else []

    def cache_files(self):
        return sorted(p for p in (self.cache / "kgate").iterdir() if p.name != ".lock") if (self.cache / "kgate").exists() else []

    def test_a_second_job_the_same_day_makes_no_op_call_and_gets_the_same_secret(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        first = self.kgate("--", "true")
        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertEqual(self.op_reads(), ["read op://developer/item/password", "read op://developer/kgate-github-packages-read/password"])
        secrets = [c for c in self.calls() if "manifest" in c]
        second = self.kgate("--", "true")
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertEqual(len(self.op_reads()), 2, "the second job read nothing with op")
        self.assertEqual(self.op_token_checks(), ["ok", "ok"])
        self.assertEqual(len(self.cache_files()), 2)
        self.assertEqual(secrets[0]["manifest"]["items"][0]["data"], [c for c in self.calls() if "manifest" in c][-1]["manifest"]["items"][0]["data"])

    def test_an_entry_over_a_day_old_is_read_again_and_replaced(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        old = time.time() - K.SECRET_CACHE_TTL - 60
        for f in self.cache_files():
            os.utime(f, (old, old))
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(len(self.op_reads()), 4, "both references were read again")
        self.assertTrue(all(time.time() - f.stat().st_mtime < 60 for f in self.cache_files()), "the entries were rewritten")
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        self.assertEqual(len(self.op_reads()), 4, "and the new entries are used")

    def test_an_entry_just_under_a_day_old_is_used(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        recent = time.time() - K.SECRET_CACHE_TTL + 300
        for f in self.cache_files():
            os.utime(f, (recent, recent))
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        self.assertEqual(len(self.op_reads()), 2)

    def test_a_failed_read_writes_no_cache_file_and_the_next_job_tries_again(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        done = self.kgate("--", "true", env={"FAKE_OP_FAIL": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertEqual(self.cache_files(), [])
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(len(self.op_reads()), 3, "the failed read, then the secret and the pull credential")

    def test_cache_dir_is_0700_and_entries_are_0600(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        self.assertEqual(stat.S_IMODE((self.cache / "kgate").stat().st_mode), 0o700)
        self.assertEqual(len(self.cache_files()), 2)
        for f in self.cache_files():
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600, f.name)
        self.assertEqual([p.name for p in (self.cache / "kgate").iterdir() if p.name.startswith(".tmp-")], [], "no temp file is left behind")

    def test_a_warm_cache_needs_no_token_and_a_cold_one_still_refuses(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        self.assertEqual(self.kgate("--", "true", env={"OP_SERVICE_ACCOUNT_TOKEN": ""}).returncode, 69)
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        done = self.kgate("--", "true", env={"OP_SERVICE_ACCOUNT_TOKEN": ""})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(len(self.op_reads()), 2, "no op run for the third job")

    def test_a_cache_that_cannot_be_written_still_returns_the_secret_and_says_so(self):
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "HOME": str(self.home),
               "OP_SERVICE_ACCOUNT_TOKEN": FAKE_TOKEN, "FAKE_TOKEN": FAKE_TOKEN}
        with mock.patch.dict(os.environ, env), mock.patch.object(K.tempfile, "mkstemp", side_effect=OSError("disk full")), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.assertEqual(K.op_read("op://developer/item/password"), b"value-of-password")
        self.assertIn("kgate: secret cache not written (disk full)", err.getvalue())
        self.assertEqual(self.cache_files(), [])

    def test_the_cache_dir_falls_back_to_dot_cache_under_home(self):
        done = self.kgate("--", "true", env={"XDG_CACHE_HOME": ""})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue((self.home / ".cache" / "kgate").is_dir())

    def test_reads_of_one_reference_started_together_make_one_op_call(self):
        env = {"PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "FAKE_OP_SLEEP": "1", "HOME": str(self.home),
               "OP_SERVICE_ACCOUNT_TOKEN": FAKE_TOKEN, "FAKE_TOKEN": FAKE_TOKEN}
        got = []
        with mock.patch.dict(os.environ, env):
            threads = [threading.Thread(target=lambda: got.append(K.op_read("op://developer/item/password"))) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
        self.assertEqual(got, [b"value-of-password"] * 4)
        self.assertEqual(self.op_reads(), ["read op://developer/item/password"])

    def test_an_unusable_cache_dir_does_not_fail_the_job(self):
        self.cache.write_text("a file where the cache dir should go\n")
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(len(self.op_reads()), 1, "read with op as before (the pull credential)")
        self.assertIn("kgate: secret cache unusable at", done.stdout)

    def preferred_hosts(self):
        manifest = next(c["manifest"] for c in self.calls() if "manifest" in c)
        pref = manifest["items"][-1]["spec"]["affinity"]["nodeAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"]
        return [(t["preference"]["matchExpressions"][0]["operator"], t["preference"]["matchExpressions"][0]["values"]) for t in pref]

    def test_a_job_with_no_profile_file_still_prefers_the_g14(self):
        (self.repo / "kgate.toml").unlink()
        done = self.kgate("--image", "docker.io/library/alpine@sha256:" + "ef" * 32, "--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.preferred_hosts(), [("In", ["cartwmic-g14-wsl"]), ("NotIn", ["ubuntu-server-k8s-agent-4"])])

    def test_a_profile_with_prefer_nodes_false_sends_no_g14_term(self):
        self.profile(extra="prefer_nodes = false")
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.preferred_hosts(), [("NotIn", ["ubuntu-server-k8s-agent-4"])])

    def test_the_pod_is_sent_the_limits(self):
        self.assertEqual(self.kgate("--cpu", "3", "--mem", "2Gi", "--", "true").returncode, 0)
        manifest = next(c["manifest"] for c in self.calls() if "manifest" in c)
        c = manifest["items"][-1]["spec"]["containers"][0]
        self.assertEqual(c["resources"]["limits"], {"memory": "2Gi", "ephemeral-storage": "12Gi"})
        self.assertEqual(c["resources"]["requests"], {"cpu": "4", "memory": "2Gi", "ephemeral-storage": "4Gi"})   # 3 is raised to the slot

    def pod_resources(self):
        manifest = next(c["manifest"] for c in self.calls() if "manifest" in c)
        return manifest["items"][-1]["spec"]["containers"][0]["resources"]

    def test_request_and_limit_reach_the_pod_and_the_record(self):
        self.profile(memory="256Mi", extra='memory_limit = "512Mi"')
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.pod_resources(), {"requests": {"cpu": "4", "memory": "256Mi", "ephemeral-storage": "4Gi"}, "limits": {"memory": "512Mi", "ephemeral-storage": "12Gi"}})
        rec = self.records()[-1]
        self.assertEqual((rec["mem"], rec["mem_limit"]), ("256Mi", "512Mi"))
        self.assertIn("256Mi memory request, 512Mi limit", done.stdout)

    def test_without_memory_limit_the_limit_is_the_request(self):
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.pod_resources(), {"requests": {"cpu": "4", "memory": "1Gi", "ephemeral-storage": "4Gi"}, "limits": {"memory": "1Gi", "ephemeral-storage": "12Gi"}})
        rec = self.records()[-1]
        self.assertEqual((rec["mem"], rec["mem_limit"]), ("1Gi", "1Gi"))
        self.assertIn("1Gi memory request, priority class kgate\n", done.stdout)

    def test_limit_below_request_is_refused_before_anything_is_created(self):
        marker = self.tmp / "cmd-ran"
        self.profile(memory="1Gi", extra='memory_limit = "512Mi"')
        done = self.kgate("--", "sh", "-c", "touch %s" % marker)
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("memory_limit must be at least memory", done.stdout)
        self.assertFalse(marker.exists())
        self.assertFalse(any("manifest" in c for c in self.calls()))
        self.assertEqual((self.records()[-1]["exit"], self.records()[-1]["ran"]), (69, False))

    def test_memory_limit_that_is_not_a_size_is_refused(self):
        self.profile(extra='memory_limit = "2G"')
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("memory_limit must look like 4Gi or 512Mi", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.calls()))

    def test_mem_sets_the_request_and_the_profile_limit_stays(self):
        self.profile(memory="1Gi", extra='memory_limit = "2Gi"')
        self.assertEqual(self.kgate("--mem", "512Mi", "--", "true").returncode, 0)
        self.assertEqual(self.pod_resources(), {"requests": {"cpu": "4", "memory": "512Mi", "ephemeral-storage": "4Gi"}, "limits": {"memory": "2Gi", "ephemeral-storage": "12Gi"}})

    def test_mem_above_the_profile_limit_is_refused(self):
        self.profile(memory="1Gi", extra='memory_limit = "2Gi"')
        done = self.kgate("--mem", "4Gi", "--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("memory_limit must be at least memory", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.calls()))

    def test_mem_limit_flag_sets_the_limit(self):
        self.assertEqual(self.kgate("--mem-limit", "3Gi", "--", "true").returncode, 0)
        self.assertEqual(self.pod_resources(), {"requests": {"cpu": "4", "memory": "1Gi", "ephemeral-storage": "4Gi"}, "limits": {"memory": "3Gi", "ephemeral-storage": "12Gi"}})

    # -- a homelab pod's CPU request is a whole number of 4-cpu slots (the nodes are split into slots that kgate pods and the pinned CI runners share)

    def sent_cpu(self):
        res = self.pod_resources()
        env = {e["name"]: e.get("value") for e in next(c["manifest"] for c in self.calls() if "manifest" in c)["items"][-1]["spec"]["containers"][0]["env"]}
        return res["requests"]["cpu"], (env["CARGO_BUILD_JOBS"], env["RAYON_NUM_THREADS"], env["MAKEFLAGS"])

    def test_a_request_below_a_slot_is_raised_to_four_and_the_build_parallelism_follows(self):
        for asked in (1, 2, 3):
            (self.fake / "calls.jsonl").unlink(missing_ok=True)
            done = self.kgate("--cpu", str(asked), "--", "true")
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertEqual(self.sent_cpu(), ("4", ("4", "4", "-j4")), "asked %d" % asked)
            self.assertEqual(self.records()[-1]["cpu"], 4)
            self.assertEqual(done.stdout.count("cpu request raised from"), 1)
            self.assertIn("kgate: cpu request raised from %d to 4: a homelab pod takes whole 4-cpu slots\n" % asked, done.stdout)
            self.assertIn(" 4 cpu, ", done.stdout)   # the pod line says what the pod asks for

    def test_a_request_of_exactly_a_slot_is_unchanged_and_says_nothing(self):
        done = self.kgate("--cpu", "4", "--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.sent_cpu(), ("4", ("4", "4", "-j4")))
        self.assertNotIn("raised", done.stdout)

    def test_a_request_above_a_slot_is_rounded_up_to_whole_slots(self):
        for asked, got in ((5, 8), (6, 8), (8, 8), (12, 12)):
            (self.fake / "calls.jsonl").unlink(missing_ok=True)
            done = self.kgate("--cpu", str(asked), "--", "true")
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertEqual(self.sent_cpu(), (str(got), (str(got), str(got), "-j%d" % got)), "asked %d" % asked)
            self.assertEqual(self.records()[-1]["cpu"], got)
            self.assertEqual("raised" in done.stdout, got != asked, "asked %d" % asked)

    def test_a_profile_cpu_is_raised_the_same_way_as_the_flag(self):
        self.profile(extra="")   # cpu = 2 in the test profile
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        self.assertEqual(self.sent_cpu()[0], "4")

    def test_a_cpu_limit_at_or_above_the_raised_request_is_kept(self):
        self.profile(extra="cpu_limit = 4")
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        res = self.pod_resources()
        self.assertEqual((res["requests"]["cpu"], res["limits"]["cpu"]), ("4", "4"))

    def test_the_slot_total_counts_service_containers_and_the_job_container_takes_the_rise(self):
        self.assertEqual(K.SLOT_CPU, 4)
        for job, services, want in ((1, 0, 4), (4, 0, 4), (6, 0, 8), (12, 0, 12), (1, 2, 2), (2, 2, 2), (3, 2, 6), (4, 2, 6), (1, 5, 3)):
            self.assertEqual(K.slot_cpu(job, services), want, (job, services))
            self.assertEqual((want + services) % K.SLOT_CPU, 0, (job, services))

    def test_mem_limit_flag_below_the_request_is_refused(self):
        done = self.kgate("--mem-limit", "512Mi", "--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("memory_limit must be at least memory", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.calls()))

    # --- kgate cancel

    def active(self):
        return self.state / "kgate" / "active"

    def add_entry(self, job_id, run_id, pid, tamper_start=False, node="fake-node", cluster=None, pidns=True):
        """A registry entry for the process `pid`, as the running client would have written it. `pidns`: this test's pid namespace, or False for an entry with no such key (an older client), or the namespace's name."""
        start, command = K.proc_identity(pid)
        self.active().mkdir(parents=True, exist_ok=True)
        entry = {"id": job_id, "job": run_id, "pid": pid, "start": "other" if tamper_start else start, "proc_cmd": command,
                 "cwd": str(self.repo), "argv": ["kgate", "--", "sleep"], "cmd": "sleep 300", "node": node}
        if cluster:
            entry["cluster"] = cluster
        if pidns is not False:
            entry["pidns"] = (os.readlink("/proc/self/ns/pid") if os.path.exists("/proc/self/ns/pid") else None) if pidns is True else pidns
        (self.active() / (job_id + ".json")).write_text(json.dumps(entry))

    def dead_entry(self, job_id, run_id, **kw):
        """An entry whose client was killed -9: the pid is gone."""
        corpse = subprocess.Popen(["sleep", "300"])
        self.add_entry(job_id, run_id, corpse.pid, **kw)
        corpse.kill()
        corpse.wait()

    def fake_client(self, job_id, run_id, mode="term"):
        """A live stand-in for a kgate client that I start, in a process group of its own (so a wrong group signal cannot reach the
        test run): on SIGTERM it writes its end line like the real one."""
        script = self.tmp / "fakeclient.py"
        script.write_text(FAKE_CLIENT)
        (self.state / "kgate").mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen([sys.executable, str(script), str(self.state / "kgate"), job_id, run_id, mode], stdout=subprocess.PIPE, text=True,
                                preexec_fn=lambda: os.setpgid(0, 0))
        def reap():
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            proc.stdout.close()
        self.addCleanup(reap)
        self.assertEqual(proc.stdout.readline().strip(), "ready")
        self.add_entry(job_id, run_id, proc.pid)
        return proc

    def deletes(self):
        return [c["kubectl"] for c in self.calls() if c.get("kubectl", [""])[0] == "delete"]

    def test_cancel_by_kgate_id_signals_that_one_pid_and_no_other(self):
        a = self.fake_client("kgate-1700000001-111", "20261107T000000Z-aaaaaa")
        b = self.fake_client("kgate-1700000002-222", "20261107T000000Z-bbbbbb")
        done = self.kgate("cancel", "kgate-1700000001-111")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(a.wait(timeout=10), 143)
        self.assertIsNone(b.poll())                                        # the other job's client is untouched
        self.assertTrue((self.active() / "kgate-1700000002-222.json").exists())
        end = [r for r in self.records() if r["id"] == "kgate-1700000001-111"]
        self.assertEqual([r["reason"] for r in end], ["cancelled by kgate cancel"])   # the marker was there when SIGTERM came
        self.assertIn("kgate-1700000001-111 ended: exit 143 (cancelled by kgate cancel)", done.stdout)
        self.assertEqual(self.calls(), [])                                 # a live client cleans up itself; cancel touched no cluster

    def test_cancel_by_run_and_wake_id(self):
        a = self.fake_client("kgate-1700000001-111", "20261107T000000Z-aaaaaa")
        b = self.fake_client("kgate-1700000002-222", "20261107T000000Z-bbbbbb")
        done = self.kgate("cancel", "20261107T000000Z-bbbbbb")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(b.wait(timeout=10), 143)
        self.assertIsNone(a.poll())

    def test_cancel_does_not_signal_the_process_group(self):
        a = self.fake_client("kgate-1700000001-111", "20261107T000000Z-aaaaaa")
        bystander = subprocess.Popen(["sleep", "300"], preexec_fn=lambda: os.setpgid(0, a.pid))  # same group as a
        self.addCleanup(lambda: (bystander.kill(), bystander.wait()))
        self.assertEqual(os.getpgid(bystander.pid), os.getpgid(a.pid))
        done = self.kgate("cancel", "kgate-1700000001-111")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(a.wait(timeout=10), 143)
        self.assertIsNone(bystander.poll())

    def test_cancel_matches_the_whole_id_only(self):
        a = self.fake_client("kgate-1700000001-111", "20261107T000000Z-aaaaaa")
        for prefix in ("kgate-1700000001", "kgate-17", "kgate", "20261107T000000Z", "20261107T000000Z-aaaaa", "*", ""):
            done = self.kgate("cancel", prefix)
            self.assertEqual(done.returncode, 64, (prefix, done.stdout))
        self.assertIsNone(a.poll())
        self.assertEqual(self.records(), [])

    def test_two_matches_refuse_and_signal_nothing(self):
        a = self.fake_client("kgate-1700000001-111", "20261107T000000Z-same00")
        b = self.fake_client("kgate-1700000002-222", "20261107T000000Z-same00")
        done = self.kgate("cancel", "20261107T000000Z-same00")
        self.assertEqual(done.returncode, 64, done.stdout)
        self.assertIn("2 running jobs have the id", done.stdout)
        self.assertEqual((a.poll(), b.poll()), (None, None))
        self.assertEqual(self.records(), [])

    def test_no_match_refuses(self):
        a = self.fake_client("kgate-1700000001-111", "20261107T000000Z-aaaaaa")
        done = self.kgate("cancel", "kgate-1700000009-999")
        self.assertEqual(done.returncode, 64, done.stdout)
        self.assertIn("nothing was signalled", done.stdout)
        self.assertIsNone(a.poll())

    def test_a_dead_pid_is_not_signalled_and_goes_the_orphan_way(self):
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")
        done = self.kgate("cancel", "20261107T000000Z-cccccc")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.deletes(), [["delete", "pod/kgate-1700000003-333", "secret/kgate-1700000003-333-env", "secret/kgate-1700000003-333-pull",
                                           "--ignore-not-found", "--grace-period=0", "--wait=true"]])   # exactly these three, nothing else
        rec = self.records()[-1]
        self.assertEqual((rec["id"], rec["job"], rec["exit"], rec["cleanup"], rec["cancelled"]),
                         ("kgate-1700000003-333", "20261107T000000Z-cccccc", 143, True, True))
        self.assertEqual(rec["reason"], "cancelled by kgate cancel (client already gone)")
        self.assertFalse((self.active() / "kgate-1700000003-333.json").exists())

    def test_a_recycled_pid_is_not_signalled(self):
        stranger = subprocess.Popen(["sleep", "300"])                 # alive, but not the process the entry was written for
        self.addCleanup(lambda: (stranger.kill(), stranger.wait()))
        self.add_entry("kgate-1700000004-444", "20261107T000000Z-dddddd", stranger.pid, tamper_start=True)
        done = self.kgate("cancel", "kgate-1700000004-444")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIsNone(stranger.poll())
        self.assertEqual(len(self.deletes()), 1)
        self.assertEqual(self.records()[-1]["reason"], "cancelled by kgate cancel (client already gone)")

    def test_orphan_stops_when_the_pod_is_not_a_kgate_pod(self):
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")
        done = self.kgate("cancel", "kgate-1700000003-333", env={"FAKE_LABEL": "something-else"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertEqual(self.deletes(), [])
        self.assertTrue((self.active() / "kgate-1700000003-333.json").exists())    # still there to retry

    def test_orphan_with_an_unreachable_cluster_keeps_the_entry(self):
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")
        done = self.kgate("cancel", "kgate-1700000003-333", host="cartwmic@unreachable")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("cluster unreachable", done.stdout)
        self.assertTrue((self.active() / "kgate-1700000003-333.json").exists())
        self.assertEqual(self.records(), [])

    def test_an_entry_whose_job_already_ended_only_loses_its_entry(self):
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")
        (self.state / "kgate" / "log.jsonl").write_text(json.dumps({"id": "kgate-1700000003-333", "job": None, "exit": 0, "reason": None}) + "\n")
        done = self.kgate("cancel", "kgate-1700000003-333")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ended: exit 0", done.stdout)
        self.assertEqual((self.calls(), len(self.records())), ([], 1))
        self.assertFalse((self.active() / "kgate-1700000003-333.json").exists())

    # --- a job that starts ends the jobs whose client is gone (dotfiles#479)

    def reaped(self, job_id):
        return [r for r in self.records() if r["id"] == job_id]

    def test_a_starting_job_ends_the_job_whose_client_is_gone_before_it_creates_its_own_pod(self):
        live = self.fake_client("kgate-1700000001-111", "20261107T000000Z-aaaaaa")
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc", node="agent-2")
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        mine = self.records()[-1]
        self.assertEqual(len(self.reaped("kgate-1700000003-333")), 1, "the gone client's job has an end line")
        gone, = self.reaped("kgate-1700000003-333")
        self.assertEqual((gone["exit"], gone["cleanup"], gone["cancelled"], gone["reaped_by"], gone["job"]), (143, True, True, mine["id"], "20261107T000000Z-cccccc"))
        self.assertRegex(gone["reason"], r"^ended by kgate: its client \(pid \d+\) is gone$")
        self.assertIn(["delete", "pod/kgate-1700000003-333", "secret/kgate-1700000003-333-env", "secret/kgate-1700000003-333-pull",
                       "--ignore-not-found", "--grace-period=0", "--wait=true"], self.deletes())
        kinds = [("delete", c["kubectl"][1]) if c["kubectl"][0] == "delete" else ("create",) for c in self.calls() if "kubectl" in c and c["kubectl"][0] in ("delete", "create")]
        self.assertIn(("delete", "pod/kgate-1700000003-333"), kinds, "the gone client's pod was deleted")
        self.assertLess(kinds.index(("delete", "pod/kgate-1700000003-333")), kinds.index(("create",)), "ended before this job's own pod is created")
        self.assertIn("ended kgate-1700000003-333: its client (pid ", done.stdout)
        self.assertFalse((self.active() / "kgate-1700000003-333.json").exists())
        self.assertEqual(list(self.active().glob("*.reap")), [])
        self.assertIsNone(live.poll())                                                      # the live client is not touched
        self.assertTrue((self.active() / "kgate-1700000001-111.json").exists())
        self.assertEqual(self.reaped("kgate-1700000001-111"), [])
        self.assertNotIn("pod/kgate-1700000001-111", [x for d in self.deletes() for x in d])

    def test_the_end_line_makes_kgate_cancel_report_the_reaped_job(self):
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        (self.active()).mkdir(exist_ok=True)
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")      # the same id back in the registry: its end line is already there
        before = self.deletes()
        done = self.kgate("cancel", "kgate-1700000003-333")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ended: exit 143 (ended by kgate: its client", done.stdout)
        self.assertEqual(self.deletes(), before)

    def test_an_entry_that_already_has_an_end_line_only_loses_its_entry(self):
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")
        (self.state / "kgate" / "log.jsonl").write_text(json.dumps({"id": "kgate-1700000003-333", "job": None, "exit": 0, "reason": None}) + "\n")
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        self.assertFalse((self.active() / "kgate-1700000003-333.json").exists())
        self.assertEqual(len(self.reaped("kgate-1700000003-333")), 1)                       # no second end line
        self.assertNotIn("pod/kgate-1700000003-333", [x for d in self.deletes() for x in d])

    def test_a_delete_that_is_not_confirmed_leaves_the_entry_and_does_not_fail_the_new_job(self):
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")
        done = self.kgate("--", "true", env={"FAKE_DELETE_FAIL": "1"})        # the first pod delete (the reap's) times out; the job's own cleanup is the second
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("could not end kgate-1700000003-333", done.stdout)
        self.assertIn("left for the next kgate job", done.stdout)
        self.assertEqual(self.reaped("kgate-1700000003-333"), [])
        self.assertTrue((self.active() / "kgate-1700000003-333.json").exists())
        self.assertEqual(self.kgate("--", "true").returncode, 0)               # the next one finishes it
        self.assertEqual(len(self.reaped("kgate-1700000003-333")), 1)
        self.assertFalse((self.active() / "kgate-1700000003-333.json").exists())

    def test_a_delete_that_hangs_is_cut_off_and_does_not_fail_the_new_job(self):
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")
        command = stub_launcher(self.tmp, "short_launch.py", "import importlib.machinery, importlib.util, sys\n"
                                "loader = importlib.machinery.SourceFileLoader('kg', sys.argv[1])\n"
                                "K = importlib.util.module_from_spec(importlib.util.spec_from_loader('kg', loader))\n"
                                "loader.exec_module(K)\n"
                                "K.CLEANUP_ATTEMPT_S = 1\n"
                                "sys.exit(K.main(sys.argv[2:]))\n")
        self.launcher = lambda: command
        done = self.kgate("--", "true", env={"FAKE_DELETE_HANG": "1"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("could not end kgate-1700000003-333", done.stdout)
        self.assertTrue((self.active() / "kgate-1700000003-333.json").exists())

    def test_a_pod_that_is_not_kgates_is_not_deleted_and_the_new_job_runs(self):
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")
        done = self.kgate("--", "true", env={"FAKE_LABEL": "something-else"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("is not a kgate pod; nothing deleted", done.stdout)
        self.assertEqual(self.reaped("kgate-1700000003-333"), [])
        self.assertTrue((self.active() / "kgate-1700000003-333.json").exists())

    def test_entries_it_cannot_judge_are_left_alone(self):
        self.dead_entry("kgate-1700000001-111", "20261107T000000Z-aaaaaa", cluster="example")       # another cluster
        self.dead_entry("kgate-1700000002-222", "20261107T000000Z-bbbbbb", pidns="pid:[4026539999]")  # another pid namespace: a live client looks gone there
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc", pidns=False)               # written by a client that did not record one
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual([r["id"] for r in self.records()][:-1], [])
        self.assertEqual(sorted(p.name for p in self.active().glob("*.json")), ["kgate-1700000001-111.json", "kgate-1700000002-222.json", "kgate-1700000003-333.json"])
        self.assertEqual([d for d in self.deletes() if d[1].startswith("pod/") and d[1] != "pod/" + self.records()[-1]["id"]], [])

    def test_clients_starting_while_another_holds_the_job_do_not_end_it_and_leave_no_lock_file(self):
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc")
        import fcntl
        fd = os.open(self.active() / "kgate-1700000003-333.json", os.O_RDONLY)      # another client is ending this job
        self.addCleanup(os.close, fd)
        fcntl.flock(fd, fcntl.LOCK_EX)
        for _ in range(2):                                                          # two more clients start while it is held
            self.assertEqual(self.kgate("--", "true").returncode, 0)
        self.assertEqual(self.reaped("kgate-1700000003-333"), [], "neither client ended a job another one holds")
        self.assertTrue((self.active() / "kgate-1700000003-333.json").exists())
        self.assertEqual([p.name for p in self.active().iterdir()], ["kgate-1700000003-333.json"], "no lock file is left behind")
        fcntl.flock(fd, fcntl.LOCK_UN)
        self.assertEqual(self.kgate("--", "true").returncode, 0)                    # once it is free, the next client ends it, once
        self.assertEqual(len(self.reaped("kgate-1700000003-333")), 1)
        self.assertEqual(list(self.active().iterdir()), [])

    def test_the_pod_carries_a_hard_bound_that_fits_the_longest_job_on_record(self):
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        manifest = next(c["manifest"] for c in self.calls() if "manifest" in c)
        bound = manifest["items"][-1]["spec"]["activeDeadlineSeconds"]
        self.assertGreater(bound, 3 * 3600, "the longest legitimate job on record (a 30-run journey repeat) ran 3 h 3 min")
        self.assertLessEqual(bound, 4 * 3600, "past this a job nobody is waiting for must not still hold CPU (it was 8 h)")

    def test_a_client_that_does_not_end_in_time_is_69_and_is_not_forced(self):
        stubborn = self.fake_client("kgate-1700000005-555", "20261107T000000Z-eeeeee", mode="ignore")
        done = self.kgate("cancel", "--wait", "1", "kgate-1700000005-555")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("still running as pid %d" % stubborn.pid, done.stdout)
        self.assertIn("kill -9 %d" % stubborn.pid, done.stdout)
        self.assertIsNone(stubborn.poll())

    def test_list_shows_the_running_jobs_and_changes_nothing(self):
        a = self.fake_client("kgate-1700000001-111", "20261107T000000Z-aaaaaa")
        self.dead_entry("kgate-1700000003-333", "20261107T000000Z-cccccc", node="agent-2")
        before = sorted(p.name for p in self.active().iterdir())
        done = self.kgate("cancel", "--list")
        self.assertEqual(done.returncode, 0, done.stdout)
        lines = done.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertRegex(lines[0], r"^kgate-1700000001-111 job=20261107T000000Z-aaaaaa pid=%d node=fake-node age=\S+ cwd=%s cmd=sleep 300$" % (a.pid, re.escape(str(self.repo))))
        self.assertRegex(lines[1], r"^kgate-1700000003-333 job=20261107T000000Z-cccccc pid=\d+ \(client gone\) node=agent-2 ")
        self.assertEqual(sorted(p.name for p in self.active().iterdir()), before)
        self.assertEqual((self.calls(), self.records(), a.poll()), ([], [], None))
        self.assertIn("no kgate jobs running", self.kgate("cancel", "--list", env={"XDG_STATE_HOME": str(self.tmp / "empty")}).stdout)

    def test_cancel_command_line_errors_are_64(self):
        a = self.fake_client("kgate-1700000001-111", "20261107T000000Z-aaaaaa")
        for args in ((), ("--list", "kgate-1700000001-111"), ("--all",), ("--li",), ("--wait", "x", "kgate-1700000001-111"),
                     ("--wait", "-1", "kgate-1700000001-111"), ("one", "two")):
            done = self.kgate("cancel", *args)
            self.assertEqual(done.returncode, 64, (args, done.stdout))
            self.assertIn("kgate cancel", done.stdout)
        self.assertIsNone(a.poll())

    def test_usage_and_help_name_cancel_and_the_job_command_line_still_works(self):
        self.assertIn("kgate cancel", self.kgate("--help").stdout)
        done = self.kgate("--wait", "5")
        self.assertEqual(done.returncode, 64)
        self.assertIn("kgate cancel --list", done.stdout)
        self.assertEqual(self.kgate("--", "true").returncode, 0)

    def test_the_active_entry_exists_while_the_job_runs_and_is_gone_after(self):
        proc = self.start_job("echo up; sleep 6")
        entries = list(self.active().glob("*.json"))
        self.assertEqual(len(entries), 1)
        e = json.loads(entries[0].read_text())
        self.assertEqual((e["pid"], e["job"], e["node"], e["id"]), (proc.pid, "20261104T000000Z-abcdef", "fake-node", entries[0].stem))
        self.assertEqual(e["thread"], "thread:test-1")   # the builder seat's Stop hook matches a running job to its thread by this
        proc.terminate()
        proc.stdout.read()
        self.assertEqual(proc.wait(timeout=30), 143)
        self.assertEqual(list(self.active().iterdir()), [])

    def test_the_active_entry_is_gone_after_a_normal_finish_and_after_failures(self):
        self.assertEqual(self.kgate("--", "true").returncode, 0)
        self.assertEqual(self.kgate("--", "sh", "-c", "exit 3").returncode, 3)
        self.assertEqual(self.kgate("--", "true", host="cartwmic@unreachable").returncode, 69)
        (self.repo / "kgate.toml").write_bytes(b"\xff\xfe")               # reading the profile now fails in a way kgate did not expect
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("kgate error: UnicodeDecodeError", done.stdout)
        self.assertEqual(len(self.records()), 4)
        self.assertEqual(list(self.active().iterdir()), [])

    def start_job(self, shell_cmd):
        e = {**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
             "KGATE_SSH": "fake", "KGATE_SSH_KEY": "/dev/null", "RUN_AND_WAKE_JOB": "20261104T000000Z-abcdef", "T3CODE_THREAD_ID": "thread:test-1", **self.op_env()}
        proc = subprocess.Popen([sys.executable, str(SCRIPT), "--", "sh", "-c", shell_cmd], cwd=self.repo, env=e,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)  # own group: see fake_client
        def reap():
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            proc.stdout.close()
        self.addCleanup(reap)
        for line in proc.stdout:
            if "]: running" in line:
                return proc
        self.fail("the job never reached running")

    def test_cancel_stops_a_real_client_through_the_whole_path(self):
        job = self.start_job("echo up; sleep 30")
        other = self.start_job("echo up; sleep 30")
        mine = [json.loads(p.read_text()) for p in self.active().glob("*.json") if json.loads(p.read_text())["pid"] == job.pid][0]
        done = self.kgate("cancel", mine["id"])
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(job.wait(timeout=30), 143)
        self.assertIsNone(other.poll())                                  # the second real client is still running
        rec = [r for r in self.records() if r["id"] == mine["id"]][0]
        self.assertEqual((rec["exit"], rec["reason"], rec["cancelled"], rec["cleanup"]), (143, "cancelled by kgate cancel", True, True))
        self.assertEqual(rec["job"], "20261104T000000Z-abcdef")
        self.assertIn(["delete", "pod/" + mine["id"], "secret/%s-env" % mine["id"], "secret/%s-pull" % mine["id"],
                       "--ignore-not-found", "--grace-period=0", "--wait=true"], self.deletes())
        self.assertEqual(len(list(self.active().glob("*.json"))), 1)     # only the other job is left
        self.assertFalse((self.active() / (mine["id"] + ".cancel")).exists())
        other.terminate()
        other.stdout.read()
        other.wait(timeout=30)


# ---------------------------------------------------------------- a second cluster, reached through kubectl

KCL_IMAGE = "registry.example/ci/runner:1@sha256:" + "cd" * 32
KCFG = {"name": "example", "path": "/nowhere/example.toml", "kubeconfig": "/nowhere/kubeconfig", "context": "example-ctx", "namespace": "jobs",
        "registries": ["registry.example", "other.example"], "tree_roots": ["Users", "Volumes", "private"], "user": "65532:65532", "deadline_s": 7200,
        "pod_labels": {"example.org/owner": "team-a", "example.org/tier": "build"}, "pod_annotations": {"example.org/evict-ok": "true"}, "cache_claim_default": None}

FAKE_KUBECTL = r'''#!/usr/bin/env python3
import json, os, re, shlex, shutil, subprocess, sys, time
''' + FAKE_DELETE + r'''
fake = os.environ["FAKE"]
argv = sys.argv[1:]
def log(entry):
    with open(os.path.join(fake, "kcalls.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")
log({"argv": argv})
if argv[:2] == ["--kubeconfig", os.path.join(os.environ["HOME"], ".kube", "config")] and argv[2] == "config":
    if os.environ.get("FAKE_NO_CONTEXT"):
        sys.stderr.write("error: context was not found for specified context: example-ctx\n"); sys.exit(1)
    user = {"token": "fake"} if os.environ.get("FAKE_CONFIG_TOKEN") else {"exec": {"command": "kubelogin", "args": ["get-token", "--login", "devicecode", "--tenant-id", "t"]}}
    print(json.dumps({"apiVersion": "v1", "kind": "Config", "current-context": "example-ctx",
        "clusters": [{"name": "example-ctx", "cluster": {"server": "https://cluster.example"}}],
        "contexts": [{"name": "example-ctx", "context": {"cluster": "example-ctx", "user": "u"}}],
        "users": [{"name": "u", "user": user}]}))
    sys.exit(0)
assert argv[:6] == ["--kubeconfig", os.path.join(os.environ["HOME"], ".kube", "example"), "--context", "example-ctx", "-n", "jobs"], argv
a = argv[6:]
scenario = os.environ.get("FAKE_POD", "ready")
if a[:3] == ["auth", "can-i", "create"]:
    mode = os.environ.get("FAKE_CANI", "yes")
    if mode == "yes":
        print("yes"); sys.exit(0)
    if mode == "no":
        print("no"); sys.exit(1)
    sys.stderr.write("error: You must be logged in to the server (Unauthorized)\n"); sys.exit(1)
if a[0] == "delete":
    sys.exit(fake_delete(fake, a[1:]))
if a[:2] == ["get", "pods"]:
    print(json.dumps({"items": []})); sys.exit(0)
# Pods the fake cluster took away (FAKE_LOST): what is left of each one says why. "event": the pod is gone and the namespace events say Evicted (the autoscaler's
# consolidation); "taint": gone, TaintManagerEviction; "status": the pod is left as Failed/Evicted; "disruption": the pod has a DisruptionTarget condition;
# "other": gone, and the only event is an unrelated one; "none": gone, no event; "deadline": left as Failed/DeadlineExceeded.
lostfile = os.path.join(fake, "lost-pods")
lost = dict(l.split() for l in open(lostfile).read().splitlines()) if os.path.exists(lostfile) else {}
if a[:2] == ["get", "pod"] and a[2] in lost:
    kind = lost[a[2]]
    if kind == "status":
        print(json.dumps({"status": {"phase": "Failed", "reason": "Evicted", "message": "The node was low on resource: memory."}})); sys.exit(0)
    if kind == "disruption":
        print(json.dumps({"status": {"phase": "Running", "conditions": [{"type": "DisruptionTarget", "status": "True", "reason": "DeletionByTaintManager", "message": "Taint manager: deleting due to NoExecute taint"}]}})); sys.exit(0)
    if kind in ("running-cancel", "running-evicted"):   # the pod is still there and Running, with only a stray event about it
        print(json.dumps({"status": {"phase": "Running", "conditions": [{"type": "Ready", "status": "True"}]}})); sys.exit(0)
    if kind == "deadline":
        print(json.dumps({"status": {"phase": "Failed", "reason": "DeadlineExceeded", "message": "Pod was active on the node longer than the specified deadline"}})); sys.exit(0)
    sys.stderr.write('Error from server (NotFound): pods "%s" not found\n' % a[2]); sys.exit(1)
if a[:2] == ["get", "events"]:
    name = a[a.index("--field-selector") + 1].split("involvedObject.name=")[1]
    event = {"event": ("Evicted", "Evicted pod: Underutilized"), "taint": ("TaintManagerEviction", "Marking for deletion Pod jobs/x"),
             "cancel": ("TaintManagerEviction", "Cancelling deletion of Pod jobs/x"), "running-cancel": ("TaintManagerEviction", "Cancelling deletion of Pod jobs/x"),
             "running-evicted": ("Evicted", "Evicted pod: Underutilized"),
             "other": ("Killing", "Stopping container job")}.get(lost.get(name))
    if event is None and lost.get(name, "").startswith("reason="):   # "reason=X": gone, and the only event has reason X
        event = (lost[name][7:], "Marking for deletion Pod jobs/x" if lost[name][7:] == "TaintManagerEviction" else "a message")
    if os.environ.get("FAKE_EVENTS_FAIL"):   # the events read is refused
        sys.stderr.write('Error from server (Forbidden): events is forbidden: User "x" cannot list resource "events"\n'); sys.exit(1)
    print(json.dumps({"items": [{"reason": event[0], "message": event[1]}] if event else []})); sys.exit(0)
if a[:2] == ["create", "-f"]:
    creates = os.path.join(fake, "creates")
    n = int(open(creates).read()) + 1 if os.path.exists(creates) else 1
    open(creates, "w").write(str(n))
    if os.environ.get("FAKE_QUOTA_ON_CREATE") == str(n) and not os.path.exists(os.path.join(fake, "quota-once")):   # refuse that one create, once
        open(os.path.join(fake, "quota-once"), "w").write("x")
        sys.stderr.write('Error from server (Forbidden): error when creating "STDIN": pods "x" is forbidden: exceeded quota: jobs, requested: requests.cpu=2, used: requests.cpu=8, limited: requests.cpu=8\n'); sys.exit(1)
    quota = os.environ.get("FAKE_QUOTA", "")   # "N": refuse the first N creates; "always": refuse every create. The used CPU changes after the first.
    if quota.startswith("long:") and n <= int(quota[5:]):   # four resources exceeded, a message over 300 characters, every request under its limited value
        names = ["limits.cpu", "limits.memory", "requests.cpu", "requests.ephemeral-storage"]
        side = lambda vals: ",".join("%s=%s" % (k, v) for k, v in zip(names, vals))
        sys.stderr.write('Error from server (Forbidden): error when creating "STDIN": pods "kgate-1794437863-45437" is forbidden: exceeded quota: jobs-quota-qqqq, requested: %s, used: %s, limited: %s\n'
                         % (side(["8", "10Gi", "2", "8Gi"]), side(["96", "160Gi", "24", "100Gi"]), side(["96", "160Gi", "24", "100Gi"]))); sys.exit(1)
    if quota and not quota.startswith("long:") and quota != "impossible" and (quota == "always" or n <= int(quota)):
        sys.stderr.write('Error from server (Forbidden): error when creating "STDIN": pods "x" is forbidden: exceeded quota: jobs, requested: requests.cpu=2, used: requests.cpu=%d, limited: requests.cpu=8\n' % (8 if n == 1 else 6)); sys.exit(1)
    if quota == "impossible":   # asks for more than the namespace's own limit: waiting cannot help
        sys.stderr.write('Error from server (Forbidden): error when creating "STDIN": pods "x" is forbidden: exceeded quota: jobs, requested: limits.cpu=16,requests.cpu=2, used: limits.cpu=0,requests.cpu=0, limited: limits.cpu=8,requests.cpu=8\n'); sys.exit(1)
    if os.environ.get("FAKE_CREATE_ECHO_PW"):   # a refusal that echoes the pod spec's SA password back, as an API error might
        pw = next(e["value"] for i in json.load(sys.stdin)["items"] for c in i["spec"].get("initContainers", []) for e in c["env"] if e["name"] == "MSSQL_SA_PASSWORD")
        open(os.path.join(fake, "echoed_pw"), "w").write(pw)
        sys.stderr.write("Error from server (Invalid): pod spec rejected: env MSSQL_SA_PASSWORD=%s\n" % pw); sys.exit(1)
    if os.environ.get("FAKE_CREATE_ERROR"):
        text = os.environ["FAKE_CREATE_ERROR"]
        sys.stderr.write((text if text != "1" else "Error from server (Forbidden): pods is forbidden: violates PodSecurity") + "\n"); sys.exit(1)
    active = os.path.join(os.environ["XDG_STATE_HOME"], "kgate", "active")
    entries = [json.load(open(os.path.join(active, n))) for n in sorted(os.listdir(active))] if os.path.isdir(active) else []
    manifest = json.load(sys.stdin)
    json.dump(manifest, open(os.path.join(fake, "last_manifest.json"), "w"))
    log({"manifest": manifest, "registry": entries}); sys.exit(0)
if a[:2] == ["get", "pod"] and any(x.startswith("jsonpath=") for x in a):
    print(os.environ.get("FAKE_LABEL", "kgate"), end=""); sys.exit(0)
if a[:2] == ["get", "pod"] and os.environ.get("FAKE_GET_FAIL"):   # the API server times out on every read of the pod
    sys.stderr.write("Error from server: etcdserver: request timed out\n"); sys.exit(1)
if a[:2] == ["get", "pod"]:
    polls = os.path.join(fake, "polls")
    n = int(open(polls).read()) + 1 if os.path.exists(polls) else 1
    open(polls, "w").write(str(n))
    pending = lambda msg: {"phase": "Pending", "conditions": [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable", "message": msg}]}
    last = json.load(open(os.path.join(fake, "last_manifest.json"))) if os.path.exists(os.path.join(fake, "last_manifest.json")) else {"items": [{"spec": {"volumes": []}}]}
    has_claim = any("persistentVolumeClaim" in v for i in last["items"] for v in i["spec"]["volumes"])
    rwop = "0/3 nodes are available: 3 node has pod using PersistentVolumeClaim with the same name and ReadWriteOncePod access mode. preemption: 0/3 nodes are available: 3 No preemption victims found for incoming pod."
    if scenario == "ready" or (scenario == "queued" and n > 3) or (scenario == "rwop" and not has_claim) or (scenario == "rwop-r2" and not (has_claim and last["items"][0]["metadata"]["name"].endswith("-r2"))) \
            or (scenario == "rwop-r1" and not (has_claim and not last["items"][0]["metadata"]["name"].endswith("-r2"))) or (scenario == "rwop-gone" and n > 1):
        st = {"phase": "Running", "containerStatuses": [{"ready": True, "state": {"running": {}}}]}
    elif scenario in ("rwop", "rwop-gone", "rwop-r2", "rwop-r1"):   # another pod holds the ReadWriteOncePod claim (rwop-gone: it lets go before the second poll)
        st = pending(rwop)
    elif scenario == "queued":   # a full cluster: the scheduler's capacity message
        st = pending("0/3 nodes are available: 3 Insufficient cpu. preemption: 0/3 nodes are available: 3 No preemption victims found for incoming pod.")
    elif scenario == "noclaim":
        st = pending('0/3 nodes are available: persistentvolumeclaim "example-cache" not found. preemption: 0/3 nodes are available: 3 Preemption is not helpful for scheduling.')
    else:
        st = pending("0/3 nodes fit")
    if last["items"][0]["spec"].get("initContainers"):   # the SQL Server sidecar: a native sidecar reports under initContainerStatuses
        if scenario == "mssql-crash":
            st = {"phase": "Pending", "initContainerStatuses": [{"name": "mssql", "started": False, "restartCount": 1, "state": {"terminated": {"exitCode": 1}}}]}
        else:
            st["initContainerStatuses"] = [{"name": "mssql", "started": True, "restartCount": 0, "state": {"running": {}}}]
    print(json.dumps({"spec": {"nodeName": "fake-kcl-node"}, "status": st})); sys.exit(0)
def sidecar_password():
    spec = json.load(open(os.path.join(fake, "last_manifest.json")))["items"][0]["spec"]["initContainers"][0]
    return next(e["value"] for e in spec["env"] if e["name"] == "MSSQL_SA_PASSWORD")
if a[0] == "logs":
    print("Error 18456: Login failed for user sa, password %s" % sidecar_password()); print("SQL Server is starting"); sys.exit(0)
if a[0] == "exec" and "-c" in a and a[a.index("-c") + 1] == "mssql":
    if "cpu.stat" in a[-1]:
        if os.environ.get("FAKE_NO_SIDECAR_CPU"):
            sys.exit(1)
        print("usage_usec 4200000\nuser_usec 3000000\nsystem_usec 1200000"); sys.exit(0)
    print("734003200"); sys.exit(0)
if a[0] == "exec" and "-i" in a:
    pod, script = a[2], a[-1]
    job = re.sub(r"-r\d+$", "", pod)   # the pod side keeps the job id; the rerun after an eviction has the pod name "<id>-r2"
    pre, _, rest = script.partition("tar -xf - ")
    assert "tar -xf - " + rest == "tar -xf - --no-same-owner -C / && exec sh /cache/%s/kgate.sh /cache/%s" % (job, job), script
    if os.environ.get("FAKE_NO_SH"):   # an image without a shell: the runtime cannot start `sh`, and kubectl says so
        sys.stderr.write('OCI runtime exec failed: exec failed: unable to start container process: exec: "sh": executable file not found in $PATH: unknown\n'); sys.exit(126)
    checked = subprocess.run(["sh", "-c", pre + "true"], env=dict(os.environ, PATH=os.environ.get("FAKE_POD_PATH") or os.environ["PATH"]), stdout=subprocess.PIPE)   # the image's own tools
    if checked.returncode != 0:
        sys.stdout.buffer.write(checked.stdout); sys.stdout.flush(); sys.exit(checked.returncode)
    data = sys.stdin.buffer.read()
    losing = os.environ.get("FAKE_LOST", "")   # "N:kind": the first N execs lose the pod once CMD has started (kubectl exits 0, no end line)
    if losing:
        execs = os.path.join(fake, "execs")
        n = int(open(execs).read()) + 1 if os.path.exists(execs) else 1
        open(execs, "w").write(str(n))
        count, _, kinds = losing.partition(":")   # one kind per lost exec, comma separated; the last is used for any more
        kind = (kinds.split(",") or ["event"])[min(n, len(kinds.split(","))) - 1]
        if n <= int(count):
            for line in ("start 1 node=fake-kcl-node cpus=1", "hash ok x", "preflight ok 0 tools", "running sh"):
                print("kgate[%s]: %s" % (job, line), flush=True)
            time.sleep(float(os.environ.get("FAKE_LOST_DELAY", "0")))
            open(lostfile, "a").write("%s %s\n" % (pod, kind))
            sys.exit(0)
    open(os.path.join(fake, "shipped.tar"), "wb").write(data)
    jobroot = os.path.join(fake, "jobroot")
    os.makedirs(jobroot, exist_ok=True)   # /cache is the pod's emptyDir; here the job's own files go under FAKE
    tar = subprocess.run(["tar", "-xf", "-", "--no-same-owner", "-C", "/", "--exclude", "cache/kgate-*"], input=data)
    tar2 = subprocess.run(["tar", "-xf", "-", "--no-same-owner", "-C", jobroot, "cache/%s" % job], input=data)
    if tar.returncode or tar2.returncode:
        sys.exit(1)
    if os.environ.get("FAKE_TAMPER"):
        with open(os.environ["FAKE_TAMPER"], "ab") as f:
            f.write(b"x")
    out = os.path.join(fake, "out")
    os.makedirs(out, exist_ok=True)
    # the pod's own env: HOME comes from the pod spec (under /cache/<id>, which here lives under FAKE)
    spec = json.load(open(os.path.join(fake, "last_manifest.json")))["items"][0]["spec"]["containers"][0]["env"]
    home = next(e["value"] for e in spec if e["name"] == "HOME")
    env = dict(os.environ, KGATE_OUT=out, KGATE_NODE="fake-kcl-node", HOME=os.path.join(jobroot, home.lstrip("/")),
               **{e["name"]: e["value"] for e in spec if e["name"].startswith(("MSSQL_", "SA_"))})
    d = "%s/cache/%s" % (jobroot, job)
    # A pod has no .git before the script runs. The test repo does, so it is set aside while the pod side runs and put back after.
    root = next(l.split("=", 1)[1] for l in open(d + "/job.sh").read().splitlines() if l.startswith("ROOT="))
    root = shlex.split(root)[0]
    aside = os.path.join(fake, "gitaside")
    shutil.move(os.path.join(root, ".git"), aside)
    try:
        code = subprocess.call(["sh", d + "/kgate.sh", d], env=env)
    finally:
        if os.path.exists(os.path.join(root, ".git")):
            shutil.move(os.path.join(root, ".git"), os.path.join(fake, "podgit"))
        shutil.move(aside, os.path.join(root, ".git"))
    sys.exit(code)
if a[0] == "exec":
    out = os.path.join(fake, "out")
    os.makedirs(out, exist_ok=True)
    sys.exit(subprocess.call(["tar", "-cf", "-", "-C", out, "."], env=dict(os.environ, COPYFILE_DISABLE="1")))
sys.stderr.write("fake kubectl: unexpected " + repr(a) + "\n"); sys.exit(2)
'''


class KubectlProfile(unittest.TestCase):
    def test_cluster_defaults_to_homelab_and_user_follows_it(self):
        self.assertEqual(K.parse_profile("")["cluster"], "homelab")
        self.assertEqual(K.parse_profile("")["user"], "1000:1000")
        p = K.parse_profile('cluster = "example"\nephemeral_storage = "20Gi"')
        self.assertEqual((p["cluster"], p["user"], p["ephemeral_storage"]), ("example", None, "20Gi"))
        self.assertEqual(K.parse_profile('cluster = "example"\nuser = "1001:1001"')["user"], "1001:1001")

    MSSQL_IMG = "registry.example/db/sql@sha256:" + "ee" * 32
    VOL_IMG = "registry.example/tools/flyway@sha256:" + "ff" * 32

    def mssql_profile(self, extra=""):
        return 'cluster = "example"\nservices = ["mssql"]\n%s\n[mssql]\nimage = "%s"\n' % (extra, self.MSSQL_IMG)

    def test_mssql_is_a_service_with_its_own_sizes_and_a_digest_pinned_image(self):
        m = K.parse_profile(self.mssql_profile())["mssql"]
        self.assertEqual((m["image"], m["cpu"], m["cpu_limit"], m["memory"], m["memory_limit"], m["ready_s"]), (self.MSSQL_IMG, 2, 2, "4Gi", "4Gi", 300))
        bad = {"no table": 'cluster = "example"\nservices = ["mssql"]',
               "table without the service": 'cluster = "example"\n[mssql]\nimage = "%s"' % self.MSSQL_IMG,
               "unpinned": 'cluster = "example"\nservices = ["mssql"]\n[mssql]\nimage = "registry.example/db/sql:2019"',
               "homelab": 'services = ["mssql"]\n[mssql]\nimage = "%s"' % self.MSSQL_IMG,
               "unknown key": self.mssql_profile() + 'port = 1',
               "other service": 'cluster = "example"\nservices = ["oracle"]'}
        for what, text in bad.items():
            with self.subTest(what), self.assertRaises(K.Unavailable):
                K.parse_profile(text)

    def test_image_volumes_are_digest_pinned_absolute_unique_and_for_a_kubectl_cluster_only(self):
        ok = K.parse_profile('cluster = "example"\n[[image_volumes]]\nimage = "%s"\npath = "/opt/flyway"' % self.VOL_IMG)
        self.assertEqual(ok["image_volumes"], [{"image": self.VOL_IMG, "path": "/opt/flyway"}])
        one = '[[image_volumes]]\nimage = "%s"\npath = "%s"\n'
        bad = {"unpinned": 'cluster = "example"\n' + one % ("registry.example/t:1", "/opt/f"),
               "relative": 'cluster = "example"\n' + one % (self.VOL_IMG, "opt/f"),
               "dotdot": 'cluster = "example"\n' + one % (self.VOL_IMG, "/opt/../etc"),
               "trailing slash": 'cluster = "example"\n' + one % (self.VOL_IMG, "/opt/f/"),
               "duplicate": 'cluster = "example"\n' + one % (self.VOL_IMG, "/opt/f") + one % (self.VOL_IMG, "/opt/f"),
               "homelab": one % (self.VOL_IMG, "/opt/f")}
        for what, text in bad.items():
            with self.subTest(what), self.assertRaises(K.Unavailable):
                K.parse_profile(text)

    def test_local_hostnames_are_plain_names_never_addresses(self):
        self.assertEqual(K.parse_profile('cluster = "example"\nlocal_hostnames = ["db", "sql.internal"]')["local_hostnames"], ["db", "sql.internal"])
        for bad in ('["10.0.0.5"]', '["127.0.0.1"]', '["db:1433"]', '["a b"]', '"db"'):
            with self.subTest(bad), self.assertRaises(K.Unavailable):
                K.parse_profile('cluster = "example"\nlocal_hostnames = ' + bad)
        with self.assertRaises(K.Unavailable):
            K.parse_profile('local_hostnames = ["db"]')

    def test_cpu_limit_is_a_whole_number_on_a_kubectl_cluster(self):   # the homelab takes it too since dotfiles#<this change>: Profile.test_a_homelab_profile_may_set_a_cpu_limit...
        self.assertIsNone(K.parse_profile('cluster = "example"')["cpu_limit"])
        self.assertEqual(K.parse_profile('cluster = "example"\ncpu_limit = 5')["cpu_limit"], 5)
        for bad in ('cluster = "example"\ncpu_limit = 0', 'cluster = "example"\ncpu_limit = "5"', 'cluster = "example"\ncpu_limit = true'):
            with self.assertRaises(K.Unavailable, msg=bad):
                K.parse_profile(bad)

    def test_the_real_retry_loop_backs_off_5_10_20_40_60_60_and_never_past_the_deadline(self):
        """Drives Job.start_pod with a fake clock and a cluster that refuses six creates: the sleeps are the loop's own."""
        import argparse
        class Clock:
            now, slept = 1000.0, []
            def time(self):
                return self.now
            def sleep(self, secs):
                self.slept.append(secs)
                self.now += secs
        class Cluster:
            name, kind, creates = "example", "kubectl", 0
            def run(self, kargs, stdin=b""):
                if kargs[0] == "create":
                    self.creates += 1
                    ok = self.creates > 6
                    err = b"" if ok else b'Error from server (Forbidden): pods "x" is forbidden: exceeded quota: ns, requested: requests.cpu=1, used: requests.cpu=8, limited: requests.cpu=8'
                    return subprocess.CompletedProcess(kargs, 0 if ok else 1, b"", err)
                pod = {"spec": {"nodeName": "n"}, "status": {"phase": "Running", "containerStatuses": [{"ready": True}]}}
                return subprocess.CompletedProcess(kargs, 0, json.dumps(pod).encode(), b"")
        clock, real, job, job2 = Clock(), K.time, None, None
        with tempfile.TemporaryDirectory() as state:
            old_env = os.environ.get("XDG_STATE_HOME")
            os.environ["XDG_STATE_HOME"] = state
            K.time = clock
            try:
                job = K.Job(argparse.Namespace(command=["true"], wait=3600, sched_wait=600))
                job.cluster, job.console = Cluster(), False
                job.start_pod({"items": []})
                self.assertEqual(clock.slept, [5, 10, 20, 40, 60, 60])
                self.assertEqual(job.rec["quota_wait_s"], 195.0)
                clock.slept.clear()
                job2 = K.Job(argparse.Namespace(command=["true"], wait=30, sched_wait=600))     # a deadline 30 s away: the last sleep is cut to fit
                job2.cluster, job2.console = Cluster(), False
                job2.cluster.creates = -10**6
                with self.assertRaises(K.Unavailable) as ctx:
                    job2.start_pod({"items": []})
                self.assertEqual(clock.slept, [5, 10, 15])
                self.assertRegex(str(ctx.exception), r"^quota not available within 30s: exceeded quota: ns, requested")
            finally:
                for j in (job, job2):
                    if j:
                        j.log.close()
                K.time = real
                if old_env is None:
                    os.environ.pop("XDG_STATE_HOME", None)
                else:
                    os.environ["XDG_STATE_HOME"] = old_env

    def test_quota_impossible_reads_requested_against_limited(self):
        base = "exceeded quota: ns, requested: %s, used: %s, limited: %s"
        self.assertFalse(K.quota_impossible(base % ("requests.cpu=2", "requests.cpu=8", "requests.cpu=8")))
        self.assertTrue(K.quota_impossible(base % ("requests.cpu=9", "requests.cpu=0", "requests.cpu=8")))
        self.assertTrue(K.quota_impossible(base % ("limits.cpu=2,requests.memory=33Gi", "limits.cpu=0,requests.memory=0", "limits.cpu=8,requests.memory=32Gi")))
        self.assertFalse(K.quota_impossible(base % ("requests.memory=512Mi", "requests.memory=1Gi", "requests.memory=1Gi")))
        self.assertTrue(K.quota_impossible(base % ("requests.cpu=1500m", "requests.cpu=0", "requests.cpu=1")))
        self.assertFalse(K.quota_impossible("exceeded quota: unparsable"))

    def test_cache_pvc_is_for_a_kubectl_cluster_only_and_must_be_a_claim_name(self):
        self.assertIsNone(K.parse_profile('cluster = "example"')["cache_pvc"])
        self.assertEqual(K.parse_profile('cluster = "example"\ncache_pvc = "example-cache"')["cache_pvc"], "example-cache")
        for bad in ('cache_pvc = "x"', 'cluster = "homelab"\ncache_pvc = "x"', 'cluster = "example"\ncache_pvc = "Bad_Name"', 'cluster = "example"\ncache_pvc = 1', 'cluster = "example"\ncache_pvc = ""'):
            with self.assertRaises(K.Unavailable, msg=bad):
                K.parse_profile(bad)

    def test_bad_cluster_or_ephemeral_storage_is_refused(self):
        for bad in ('cluster = "a/b"', 'cluster = ""', 'cluster = 1', 'cluster = "example"\nephemeral_storage = "20G"', 'cluster = "example"\nephemeral_storage = 20'):
            with self.assertRaises(K.Unavailable, msg=bad):
                K.parse_profile(bad)


class KubectlPodSpec(unittest.TestCase):
    def pod(self, **kw):
        args = dict(job="kgate-1-2", image=KCL_IMAGE, cpu=8, memory="16Gi", memory_limit="24Gi", ephemeral="20Gi", uid=65532, gid=65532, roots=["/Users"])
        args.update(kw)
        items = K.pod_manifests_kubectl(KCFG, args["job"], args["image"], args["cpu"], args["memory"], args["memory_limit"], args["ephemeral"],
                                    args["uid"], args["gid"], args["roots"])["items"]
        self.assertEqual(len(items), 1, "one Pod and no Secret")
        return items[0]

    def test_it_meets_the_cluster_policy_from_its_cluster_file(self):
        pod = self.pod()
        self.assertEqual(pod["metadata"]["labels"], {"app": "kgate", "kgate-job": "kgate-1-2", "example.org/owner": "team-a", "example.org/tier": "build"})
        self.assertEqual(pod["metadata"]["annotations"], {"example.org/evict-ok": "true"})
        spec = pod["spec"]
        self.assertEqual(spec["activeDeadlineSeconds"], 7200)
        self.assertIs(spec["automountServiceAccountToken"], False)
        self.assertEqual(spec["securityContext"], {"runAsNonRoot": True, "runAsUser": 65532, "runAsGroup": 65532, "seccompProfile": {"type": "RuntimeDefault"}})
        c = spec["containers"][0]
        self.assertEqual(c["securityContext"], {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}})
        self.assertEqual(c["resources"], {"requests": {"cpu": "8", "memory": "16Gi", "ephemeral-storage": "20Gi"},
                                          "limits": {"cpu": "8", "memory": "24Gi", "ephemeral-storage": "20Gi"}})
        self.assertEqual(c["image"], KCL_IMAGE)
        self.assertEqual(c["command"], ["sleep", "86400"], "no tini in the image: a plain sleep longer than the deadline")

    def test_mssql_is_a_native_sidecar_the_job_waits_for_and_both_get_the_password(self):
        sql = {"image": "registry.example/db/sql@sha256:" + "ee" * 32, "cpu": 2, "cpu_limit": 3, "memory": "4Gi", "memory_limit": "5Gi", "ephemeral_storage": "6Gi", "ready_s": 120}
        vols = [{"image": "registry.example/tools/flyway@sha256:" + "ff" * 32, "path": "/mnt/flyway"}]
        items = K.pod_manifests_kubectl(KCFG, "kgate-1-2", KCL_IMAGE, 8, "16Gi", "24Gi", "20Gi", 65532, 65532, ["/Users"],
                                        mssql=sql, image_volumes=vols, local_hostnames=["db"], password="Aa1_secret")["items"]
        self.assertEqual(len(items), 1, "still one Pod and no Secret: the password is set on the pod itself")
        spec = items[0]["spec"]
        (side,) = spec["initContainers"]
        self.assertEqual((side["name"], side["image"], side["restartPolicy"]), ("mssql", sql["image"], "Always"))
        self.assertEqual(side["securityContext"], {"runAsUser": 10001, "runAsGroup": 0, "allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"], "add": ["NET_BIND_SERVICE"]}})
        self.assertEqual(side["resources"], {"requests": {"cpu": "2", "memory": "4Gi", "ephemeral-storage": "6Gi"},
                                             "limits": {"cpu": "3", "memory": "5Gi", "ephemeral-storage": "6Gi"}})
        self.assertEqual(side["startupProbe"]["failureThreshold"], 24)
        self.assertIn("sqlcmd", side["startupProbe"]["exec"]["command"][-1])
        env = {e["name"]: e["value"] for e in side["env"]}
        self.assertEqual((env["ACCEPT_EULA"], env["MSSQL_SA_PASSWORD"]), ("Y", "Aa1_secret"))
        job = {e["name"]: e.get("value") for e in spec["containers"][0]["env"]}
        self.assertEqual((job["MSSQL_HOST"], job["MSSQL_PORT"], job["MSSQL_SA_PASSWORD"]), ("localhost", "1433", "Aa1_secret"))
        self.assertEqual(spec["hostAliases"], [{"ip": "127.0.0.1", "hostnames": ["db"]}])
        self.assertIn({"name": "imgvol0", "mountPath": "/mnt/flyway", "readOnly": True}, spec["containers"][0]["volumeMounts"])
        self.assertIn({"name": "imgvol0", "image": {"reference": vols[0]["image"], "pullPolicy": "IfNotPresent"}}, spec["volumes"])

    def test_a_pod_without_services_has_no_sidecar_aliases_or_password(self):
        spec = self.pod()["spec"]
        self.assertNotIn("initContainers", spec)
        self.assertNotIn("hostAliases", spec)
        self.assertFalse([e for e in spec["containers"][0]["env"] if "MSSQL" in e["name"] or e["name"] == "SA_PASSWORD"])

    def test_cpu_limit_defaults_to_cpu_and_otherwise_splits_request_from_limit(self):
        c = self.pod()["spec"]["containers"][0]
        self.assertEqual((c["resources"]["requests"]["cpu"], c["resources"]["limits"]["cpu"]), ("8", "8"))
        items = K.pod_manifests_kubectl(KCFG, "kgate-1-2", KCL_IMAGE, 2, "6Gi", "10Gi", "8Gi", 65532, 65532, ["/Users"], 5)["items"]
        c = items[0]["spec"]["containers"][0]
        self.assertEqual(c["resources"], {"requests": {"cpu": "2", "memory": "6Gi", "ephemeral-storage": "8Gi"},
                                          "limits": {"cpu": "5", "memory": "10Gi", "ephemeral-storage": "8Gi"}})
        env = {e["name"]: e.get("value") for e in c["env"]}
        self.assertEqual((env["GOMAXPROCS"], env["MAKEFLAGS"], env["CARGO_BUILD_JOBS"], env["RAYON_NUM_THREADS"]), ("5", "-j5", "5", "5"))
    def test_without_cache_pvc_the_cache_is_an_emptydir_and_there_is_no_fsgroup(self):
        pod = self.pod()
        self.assertEqual([v for v in pod["spec"]["volumes"] if v["name"] == "cache"], [{"name": "cache", "emptyDir": {}}])
        self.assertNotIn("fsGroup", pod["spec"]["securityContext"])

    def test_with_cache_pvc_the_cache_is_the_claim_and_the_group_can_write_it(self):
        items = K.pod_manifests_kubectl(KCFG, "kgate-1-2", KCL_IMAGE, 8, "16Gi", "24Gi", "20Gi", 65532, 65533, ["/Users"], cache_pvc="example-cache")["items"]
        pod = items[0]
        self.assertEqual([v for v in pod["spec"]["volumes"] if v["name"] == "cache"], [{"name": "cache", "persistentVolumeClaim": {"claimName": "example-cache"}}])
        self.assertEqual(pod["spec"]["securityContext"], {"runAsNonRoot": True, "runAsUser": 65532, "runAsGroup": 65533, "fsGroup": 65533,
                                                          "fsGroupChangePolicy": "OnRootMismatch", "seccompProfile": {"type": "RuntimeDefault"}})
        self.assertEqual([m["mountPath"] for m in pod["spec"]["containers"][0]["volumeMounts"]], ["/Users", "/cache", "/out"])
        self.assertEqual(len(items), 1, "no PVC is created: the claim belongs to ops")

    def test_it_has_none_of_the_homelab_parts(self):
        text = json.dumps(self.pod())
        for word in ("hostPath", "affinity", "tolerations", "imagePullSecrets", "secretRef", "envFrom", "tini", "mac-mini-worker", "kgate-1-2-env", "kgate-1-2-pull"):
            self.assertNotIn(word, text)

    def test_the_tree_cache_and_out_are_emptydirs(self):
        pod = self.pod(roots=["/Users", "/home"])
        c = pod["spec"]["containers"][0]
        self.assertEqual([(m["name"], m["mountPath"]) for m in c["volumeMounts"]],
                         [("tree0", "/Users"), ("tree1", "/home"), ("cache", "/cache"), ("out", "/out")])
        self.assertEqual(pod["spec"]["volumes"], [{"name": n, "emptyDir": {}} for n in ("tree0", "tree1", "cache", "out")])

    def test_env_has_homes_and_go_caches_under_cache_and_gomaxprocs(self):
        env = {e["name"]: e.get("value") for e in self.pod(cpu=6)["spec"]["containers"][0]["env"]}
        self.assertEqual((env["HOME"], env["GOCACHE"], env["GOMODCACHE"], env["GOMAXPROCS"]), ("/cache/kgate-1-2/home", "/cache/go-build", "/cache/gomod", "6"))
        self.assertEqual(env["npm_config_store_dir"], "/cache/pnpm-store")
        self.assertEqual(env["npm_config_cache"], "/cache/npm")
        self.assertEqual((env["KGATE_OUT"], env["CI"], env["MAKEFLAGS"], env["CARGO_BUILD_JOBS"]), ("/out", "1", "-j6", "6"))

    def test_roots_are_the_top_directories_and_only_from_the_allow_list(self):
        self.assertEqual(K.tree_roots_for(KCFG, "/Users/me/git/r", "/Users/me/git/r/.git", "/Volumes/x/r"), ["/Users", "/Volumes"])
        self.assertEqual(K.tree_roots_for(KCFG, "/Volumes/W/r", "/private/var/r"), ["/Volumes", "/private"])
        for bad in ("/usr/src/r", "/cache/r", "/out/r", "/var/x", "/", "/home/x/r", "/tmp/r", "/etc/r", "/Users2/r"):
            with self.assertRaises(K.Unavailable, msg=bad):
                K.tree_roots_for(KCFG, bad)

    def test_homelab_render_is_unchanged_by_the_kubectl_adapter(self):
        want = "5f9dd1b59bac033c124d0185acd027ac2d04d90da42d593dc6c1da515bbd76c9"  # the same pin as test_default_render_is_byte_identical
        self.assertEqual(hashlib.sha256(json.dumps(K.pod_manifests("kgate-1-2", DIGEST, 3, "6Gi", None, {}, None)).encode()).hexdigest(), want)


class PodTuning(unittest.TestCase):
    """The compile caches, the worker counts and the scratch memory disk, on both kinds of cluster (candidates 3, 5 and 8 of the stack audit)."""

    def homelab(self, **kw):
        items = K.pod_manifests("kgate-1-2", DIGEST, kw.pop("cpu", 4), kw.pop("memory", "6Gi"), None, kw.pop("secret_env", {}), None, **kw)["items"]
        return items[-1]

    def kubectl(self, **kw):
        return K.pod_manifests_kubectl(KCFG, "kgate-1-2", KCL_IMAGE, 2, "6Gi", "10Gi", "8Gi", 65532, 65532, ["/Users"], kw.pop("cpu_limit", 5), **kw)["items"][0]

    def env(self, pod):
        return {e["name"]: e.get("value") for e in pod["spec"]["containers"][0]["env"]}

    def test_every_pod_gets_the_compile_caches_and_the_counts_from_its_cpu(self):
        for pod, cpus in ((self.homelab(), "4"), (self.kubectl(), "5")):
            env = self.env(pod)
            self.assertEqual((env["NODE_COMPILE_CACHE"], env["PYTHONPYCACHEPREFIX"]), ("/var/tmp/kgate-node-cache", "/var/tmp/kgate-pycache"), "on disk, and not in /tmp, which tmp_tmpfs puts in memory")
            self.assertEqual((env["KGATE_CPUS"], env["VITEST_MAX_WORKERS"], env["CI_PAR_JOBS"]), (cpus, cpus, cpus))
            self.assertEqual(env["KGATE_CPUS"], env["CARGO_BUILD_JOBS"], "one number for every tool")
            self.assertNotIn("TMPDIR", env, "no scratch_tmpfs, no change")
            self.assertNotIn("scratch", json.dumps(pod))

    def test_workers_per_cpu_multiplies_the_worker_counts_and_not_kgate_cpus(self):
        for pod, cpus, workers in ((self.homelab(per_cpu=2), "4", "8"), (self.kubectl(per_cpu=3), "5", "15")):
            env = self.env(pod)
            self.assertEqual((env["KGATE_CPUS"], env["VITEST_MAX_WORKERS"], env["CI_PAR_JOBS"]), (cpus, workers, workers))

    def test_a_name_the_profile_already_sets_is_left_to_the_profile(self):
        pod = self.homelab(secret_env={"NODE_COMPILE_CACHE": b"/mine", "CI_PAR_JOBS": b"9"})
        names = [e["name"] for e in pod["spec"]["containers"][0]["env"]]
        self.assertNotIn("NODE_COMPILE_CACHE", names)
        self.assertNotIn("CI_PAR_JOBS", names)
        self.assertIn("PYTHONPYCACHEPREFIX", names)

    def test_a_caller_assignment_in_cmd_wins_in_a_real_shell(self):
        env = {e["name"]: e["value"] for e in K.tuning_env(4, 2, "64Mi")}
        out = subprocess.run(["sh", "-c", 'VITEST_MAX_WORKERS=1 printenv NODE_COMPILE_CACHE VITEST_MAX_WORKERS TMPDIR'], env=env, capture_output=True, text=True).stdout.split()
        self.assertEqual(out, ["/var/tmp/kgate-node-cache", "1", "/kgate-scratch"])

    def test_scratch_tmpfs_is_a_sized_memory_emptydir_mounted_where_tmpdir_points(self):
        for pod in (self.homelab(scratch="256Mi"), self.kubectl(scratch="256Mi")):
            self.assertIn({"name": "scratch", "emptyDir": {"medium": "Memory", "sizeLimit": "256Mi"}}, pod["spec"]["volumes"])
            c = pod["spec"]["containers"][0]
            self.assertIn({"name": "scratch", "mountPath": "/kgate-scratch"}, c["volumeMounts"])
            self.assertEqual(self.env(pod)["TMPDIR"], "/kgate-scratch")

    def test_tmp_tmpfs_is_a_sized_memory_emptydir_mounted_at_tmp_and_the_caches_stay_on_disk(self):
        for pod in (self.homelab(tmp="2Gi"), self.kubectl(tmp="2Gi")):
            self.assertIn({"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "2Gi"}}, pod["spec"]["volumes"])
            c = pod["spec"]["containers"][0]
            self.assertIn({"name": "tmp", "mountPath": "/tmp"}, c["volumeMounts"])
            env = self.env(pod)
            self.assertNotIn("TMPDIR", env, "a program that names /tmp in code and one that reads TMPDIR both land in the mount")
            for path in (env["NODE_COMPILE_CACHE"], env["PYTHONPYCACHEPREFIX"]):
                self.assertFalse(path.startswith("/tmp/"), "a cache under the memory mount would take the pod's memory: " + path)
            self.assertEqual([m["mountPath"] for m in c["volumeMounts"]].count("/tmp"), 1)

    def test_both_memory_folders_can_be_set_and_each_gets_its_own_mount(self):
        for pod in (self.homelab(scratch="256Mi", tmp="2Gi"), self.kubectl(scratch="256Mi", tmp="2Gi")):
            mounts = {m["name"]: m["mountPath"] for m in pod["spec"]["containers"][0]["volumeMounts"]}
            self.assertEqual((mounts["scratch"], mounts["tmp"]), ("/kgate-scratch", "/tmp"))
            self.assertEqual(self.env(pod)["TMPDIR"], "/kgate-scratch")

    def test_the_profile_keys_parse_and_default(self):
        prof = K.parse_profile('image = "x"\nscratch_tmpfs = "256Mi"\ntmp_tmpfs = "2Gi"\nworkers_per_cpu = 2\n')
        self.assertEqual((prof["scratch_tmpfs"], prof["tmp_tmpfs"], prof["workers_per_cpu"]), ("256Mi", "2Gi", 2))
        prof = K.parse_profile('image = "x"\n')
        self.assertEqual((prof["scratch_tmpfs"], prof["tmp_tmpfs"], prof["workers_per_cpu"]), (None, None, 1))

    def test_bad_profile_values_are_refused(self):
        for text in ('scratch_tmpfs = 256', 'scratch_tmpfs = "lots"', 'tmp_tmpfs = 2', 'tmp_tmpfs = "lots"', 'tmp_tmpfs = "0Gi"', 'workers_per_cpu = 0', 'workers_per_cpu = 1.5', 'workers_per_cpu = true'):
            with self.assertRaises(K.Unavailable, msg=text):
                K.parse_profile(text)

    def test_the_memory_folders_must_fit_inside_the_memory_limit_together(self):
        K.check_tmpfs("1Gi")
        K.check_tmpfs("1Gi", scratch_tmpfs=None, tmp_tmpfs=None)
        K.check_tmpfs("1Gi", scratch_tmpfs="256Mi")
        K.check_tmpfs("1Gi", tmp_tmpfs="512Mi", scratch_tmpfs="256Mi")
        for sizes in ({"scratch_tmpfs": "1Gi"}, {"tmp_tmpfs": "1Gi"}, {"scratch_tmpfs": "512Mi", "tmp_tmpfs": "512Mi"}):
            with self.assertRaises(K.Unavailable, msg=str(sizes)):
                K.check_tmpfs("1Gi", **sizes)


class PodSh(unittest.TestCase):
    """The pod side on a kubectl cluster (POSIX sh, no python3) run as a process against a real temp git tree."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ks-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tree = self.tmp / "tree"
        self.tree.mkdir()
        t = self.tree
        git(t, "init", "-q")
        (t / "a.b").write_text("one\n")
        (t / "a").mkdir()
        (t / "a" / "run.sh").write_text("#!/bin/sh\necho ran-it\n")
        (t / "a" / "run.sh").chmod(0o755)
        (t / "deep" / "er").mkdir(parents=True)
        (t / "deep" / "er" / "f").write_bytes(b"\x00\x01binary\xff")
        (t / "empty").write_text("")
        (t / "with space.txt").write_text("space\n")
        (t / "üñí.txt").write_text("unicode\n")
        (t / "crlf.txt").write_bytes(b"line\r\nline\r\n")
        (t / "utf16.txt").write_bytes("wide \u00fc\n".encode("utf-16"))
        (t / ".gitattributes").write_text("* text=auto eol=lf\nutf16.txt working-tree-encoding=UTF-16\n")   # a repo that asks git to convert line endings: the hash must still be of the bytes
        (t / "link").symlink_to("a/b")
        (t / "dangling").symlink_to("nowhere")
        self.files = sorted(os.fsdecode(f) for f in subprocess.run(["git", "-C", str(t), "ls-files", "-co", "-z"], check=True, stdout=subprocess.PIPE).stdout.split(b"\0") if f)
        self.job = self.tmp / "job"
        self.job.mkdir()
        self.cg = self.tmp / "cg"
        self.cg.mkdir()

    def run_sh(self, argv=("sh", "-c", "echo hi"), tools=None, tree=None, env=None, head="1234567890abcdef1234567890abcdef12345678", lock_main=False, cache_cap=None, install_dir=None):
        job = {"id": "kgate-1-2", "root": str(self.tree), "cwd": str(self.tree), "files": self.files, "head": head,
               "tree": tree or K.tree_hash(str(self.tree), self.files), "argv": list(argv), "tools": tools or {}, "cache_cap": cache_cap}
        self.job.mkdir(exist_ok=True)   # the script removes it at the end
        if install_dir:
            job["install_dir"] = install_dir
        (self.job / "install.sh").write_text(K.INSTALL_SH)
        (self.job / "job.sh").write_text(K.job_sh(job))
        (self.job / "files.nul").write_bytes(b"".join(os.fsencode(f) + b"\0" for f in self.files))
        (self.job / "kgate.sh").write_text(K.POD_SH)
        # A pod has no .git before the script runs (none is shipped). This tree is a real repo (the tests use git on it), so it is set aside
        # while the script runs, and the repo the script built is kept at self.podgit.
        aside, self.podgit = self.tmp / "gitaside", self.tmp / "podgit"
        shutil.rmtree(self.podgit, True)
        (self.tree / ".git").rename(aside)
        if lock_main:   # a stale ref lock: git cannot move main to the new commit
            (self.tree / ".git" / "refs" / "heads" / "main.lock").parent.mkdir(parents=True)
            (self.tree / ".git" / "refs" / "heads" / "main.lock").write_text("")
        try:
            done = subprocess.run(["sh", str(self.job / "kgate.sh"), str(self.job)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                  env={**os.environ, "HOME": str(self.tmp / "home"), "KGATE_CGROUP": str(self.cg), "KGATE_NODE": "n1", **(env or {})}, timeout=60)
        finally:
            if (self.tree / ".git").exists():
                (self.tree / ".git").rename(self.podgit)
            aside.rename(self.tree / ".git")
        return done, K.Markers("kgate-1-2")

    def test_the_install_marker_reports_a_cached_npm_ci_and_none_without_one(self):
        fake = self.tmp / "fakebin"
        fake.mkdir()
        for name, text in (("npm", FAKE_NPM), ("node", FAKE_NODE)):
            (fake / name).write_text(text)
            (fake / name).chmod(0o755)
        (self.tree / "package.json").write_text("{}\n")
        (self.tree / "package-lock.json").write_text("lock\n")
        self.files = sorted(os.fsdecode(f) for f in subprocess.run(["git", "-C", str(self.tree), "ls-files", "-co", "-z"], check=True, stdout=subprocess.PIPE).stdout.split(b"\0") if f)
        env = {"PATH": "%s:%s" % (fake, os.environ["PATH"]), "FAKE_LOG": str(self.tmp / "npm.log")}
        cache = str(self.tmp / "nodecache" / "nm" / "repo")
        seen = []
        for argv in (("sh", "-c", "npm ci && node -e 1"), ("sh", "-c", "npm ci"), ("sh", "-c", "npm run x")):
            done, _ = self.run_sh(argv=argv, env=env, install_dir=cache)
            self.assertEqual(done.returncode, 0, done.stdout)
            seen.append(self.markers(done.stdout)["install"])
            shutil.rmtree(self.tree / "node_modules", True)
        self.assertRegex(seen[0], r"^miss [0-9.]+$")
        self.assertRegex(seen[1], r"^hit [0-9.]+$")
        self.assertEqual(seen[2], "none 0.0")
        done, _ = self.run_sh(argv=("sh", "-c", "npm ci"), env=env)   # a profile without [install]: the real npm, no wrapper
        self.assertEqual(self.markers(done.stdout)["install"], "none 0.0")
        ran = [l for l in (self.tmp / "npm.log").read_text().splitlines() if l.startswith("npm ci")]
        self.assertEqual(len(ran), 2, "the real npm ci ran for the miss and for the profile without the step; the hit never reached it")

    def podgit_run(self, *args):
        return subprocess.run(["git", "--git-dir", str(self.podgit), "--work-tree", str(self.tree), *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def markers(self, text):
        m = K.Markers("kgate-1-2")
        m.feed(text.encode())
        m.close()
        return m.seen

    def test_the_hash_git_computes_in_the_pod_equals_the_python_tree_hash(self):
        done, _ = self.run_sh()
        want = K.tree_hash(str(self.tree), self.files)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.markers(done.stdout)["hash"], "ok " + want)
        # and both equal the tree plain git writes for the same files (the executable file and the two symlinks are in it)
        (self.tree / ".git" / "info").mkdir(exist_ok=True)
        (self.tree / ".git" / "info" / "attributes").write_text("* -text -eol -filter -ident -working-tree-encoding\n")
        git(self.tree, "-c", "core.autocrlf=false", "add", "-A")
        oracle = subprocess.run(["git", "-C", str(self.tree), "write-tree"], check=True, stdout=subprocess.PIPE, text=True).stdout.strip()
        self.assertEqual(want, oracle)
        staged = subprocess.run(["git", "-C", str(self.tree), "ls-files", "-s"], stdout=subprocess.PIPE, text=True).stdout
        self.assertRegex(staged, r"100755 \w+ 0\ta/run.sh")
        self.assertRegex(staged, r"120000 \w+ 0\tlink")
        self.assertRegex(staged, r"120000 \w+ 0\tdangling")

    def test_a_changed_byte_a_changed_mode_or_a_changed_link_is_a_mismatch_and_cmd_does_not_run(self):
        base = K.tree_hash(str(self.tree), self.files)
        for what, change in (("byte", lambda: (self.tree / "a.b").write_text("ONE\n")),
                             ("mode", lambda: (self.tree / "a" / "run.sh").chmod(0o644)),
                             ("link", lambda: ((self.tree / "link").unlink(), (self.tree / "link").symlink_to("a/other")))):
            with self.subTest(what):
                change()
                done, _ = self.run_sh(argv=("sh", "-c", "echo SHOULD-NOT-RUN"), tree=base)
                self.assertEqual(done.returncode, 70, done.stdout)
                seen = self.markers(done.stdout)
                self.assertTrue(seen["hash"].startswith("MISMATCH expected=%s found=" % base), done.stdout)
                self.assertNotIn("SHOULD-NOT-RUN", done.stdout)
                self.assertNotIn("running", seen)
                self.setUp()

    def test_a_missing_file_is_a_mismatch_not_a_pass(self):
        base = K.tree_hash(str(self.tree), self.files)
        (self.tree / "a.b").unlink()
        done, _ = self.run_sh(tree=base)
        self.assertEqual(done.returncode, 70, done.stdout)
        self.assertIn("MISMATCH", done.stdout)

    def test_tool_versions_match_as_whole_versions_like_the_python_check(self):
        for text, want, ok in (("go version go1.25.12 linux/amd64", "1.25.12", True), ("v24.22.2", "24.22.2", True), ("rustc 11.98.0", "1.98.0", False),
                               ("rustc 1.98.01", "1.98.0", False), ("rustc 1.98.0.1", "1.98.0", False), ("x 1.98.0", "1.98.0", True),
                               ("1.98.0", "1.98.0", True), ("a.1.98.0", "1.98.0", True), ("x 1.2.3+meta", "1.2.3", True)):
            with self.subTest(text=text, want=want):
                self.assertEqual(K.version_found(text, want), ok)
                done, _ = self.run_sh(tools={"t": (want, "echo %s" % __import__("shlex").quote(text))})
                self.assertEqual(done.returncode, 0 if ok else 71, done.stdout)

    def test_a_wrong_tool_version_is_71_with_tool_expected_and_found_and_cmd_does_not_run(self):
        done, _ = self.run_sh(argv=("sh", "-c", "echo SHOULD-NOT-RUN"), tools={"go": ("1.25.12", "echo go version go1.24.1 linux/amd64")})
        self.assertEqual(done.returncode, 71, done.stdout)
        pre = self.markers(done.stdout)["preflight"]
        self.assertEqual(pre, 'FAILED tool=go expected=1.25.12 found="go version go1.24.1 linux/amd64" (echo go version go1.24.1 linux/amd64 exit 0)')
        self.assertNotIn("SHOULD-NOT-RUN", done.stdout)

    def test_a_tool_that_fails_or_prints_nothing_is_71(self):
        done, _ = self.run_sh(tools={"x": ("1.0.0", "exit 4")})
        self.assertEqual(done.returncode, 71)
        self.assertIn('found="no output" (exit 4 exit 4)', done.stdout)

    def test_tool_checks_run_in_the_jobs_directory_and_pass(self):
        (self.tree / "VERSION").write_text("tool 9.9.9\n")
        git(self.tree, "add", "-A")
        self.files = sorted(set(self.files) | {"VERSION"})
        done, _ = self.run_sh(tools={"a": ("9.9.9", "cat VERSION"), "b": ("2.0.0", "echo 2.0.0")})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.markers(done.stdout)["preflight"], "ok 2 tools")

    def test_cmd_runs_in_the_same_directory_with_its_arguments_and_its_exit_code_is_the_scripts(self):
        for code in (0, 3, 255):
            done, _ = self.run_sh(argv=("sh", "-c", 'pwd; echo "[$1]"; cat a.b; exit %d' % code, "x", "two words"))
            self.assertEqual(done.returncode, code, done.stdout)
            seen = self.markers(done.stdout)
            self.assertIn(str(self.tree), done.stdout)
            self.assertIn("[two words]", done.stdout)
            self.assertIn("one", done.stdout)
            self.assertTrue(seen["end"].endswith(" exit %d" % code), seen)
            self.assertTrue(seen["running"])

    def test_a_command_that_cannot_start_is_127_and_a_killed_one_is_128_plus_the_signal(self):
        done, _ = self.run_sh(argv=("no-such-command-here",))
        self.assertEqual(done.returncode, 127, done.stdout)
        done, _ = self.run_sh(argv=("sh", "-c", "kill -9 $$"))
        self.assertEqual(done.returncode, 137, done.stdout)
        self.assertTrue(self.markers(done.stdout)["end"].endswith(" exit 137"))

    def test_markers_are_the_ones_the_mac_side_reads_even_after_output_without_a_newline(self):
        done, _ = self.run_sh(argv=("printf", "no newline"))
        seen = self.markers(done.stdout)
        self.assertEqual(set(seen), {"start", "hash", "preflight", "running", "peak", "cpu", "clock", "install", "end"})
        self.assertRegex(seen["start"], r"^\d+ node=n1 cpus=\d+$")
        self.assertRegex(seen["end"], r"^\d+ exit 0$")

    def test_peak_memory_comes_from_memory_peak(self):
        (self.cg / "memory.peak").write_text("123456\n")
        done, _ = self.run_sh()
        self.assertEqual(self.markers(done.stdout)["peak"], "123456 cgroup")

    def test_no_memory_peak_is_reported_as_unknown_not_invented(self):
        done, _ = self.run_sh()
        self.assertEqual(self.markers(done.stdout)["peak"], "unknown")

    def test_cpu_comes_from_cpu_stat_usage_usec(self):
        (self.cg / "cpu.stat").write_text("usage_usec 7654321\nuser_usec 7000000\nsystem_usec 654321\nnr_periods 0\n")
        done, _ = self.run_sh()
        self.assertEqual(self.markers(done.stdout)["cpu"], "7654321")

    def test_no_cpu_stat_is_reported_as_unknown_not_invented(self):
        done, _ = self.run_sh()
        self.assertEqual(self.markers(done.stdout)["cpu"], "unknown")

    def test_the_commands_own_wall_time_is_the_two_clock_readings_around_it(self):
        done, _ = self.run_sh(argv=("sleep", "1"))
        t0, t1 = (float(x) for x in self.markers(done.stdout)["clock"].split())
        self.assertGreaterEqual(t1 - t0, 1.0)
        self.assertLess(t1 - t0, 1.5, "setup before CMD (unpack, tree hash, preflight) is not in it")

    def test_the_pod_side_builds_a_one_commit_repo_whose_tree_is_the_macs_hash(self):
        done, _ = self.run_sh(argv=("sh", "-c", "git rev-parse HEAD; git log --format=%an,%ae,%cn,%s | wc -l; git status --porcelain | wc -l; echo KGATE_HEAD=$KGATE_HEAD"))
        self.assertEqual(done.returncode, 0, done.stdout)
        want = K.tree_hash(str(self.tree), self.files)
        head = self.podgit_run("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(self.podgit_run("rev-parse", "HEAD^{tree}").stdout.strip(), want)
        self.assertEqual(self.podgit_run("rev-list", "--count", "HEAD").stdout.strip(), "1")
        self.assertEqual(self.podgit_run("log", "-1", "--date=raw", "--format=%an <%ae> %cn <%ce> %ad %cd").stdout.strip(), "kgate <kgate@localhost> kgate <kgate@localhost> 946684800 +0000 946684800 +0000")
        self.assertEqual(self.podgit_run("status", "--porcelain").stdout, "", "a clean worktree: the index matches the files")
        # CMD sees that repo: git works in its directory, and the Mac's real HEAD is in KGATE_HEAD
        out = done.stdout.split("\n")
        self.assertIn(head, out)
        self.assertIn("KGATE_HEAD=1234567890abcdef1234567890abcdef12345678", out)
        self.assertIn("1", [l.strip() for l in out])      # one commit; the status count line is 0

    def test_the_synthetic_commit_is_the_same_every_time_and_leaves_no_git_identity_in_cmds_env(self):
        self.run_sh()
        first = self.podgit_run("rev-parse", "HEAD").stdout
        done, _ = self.run_sh(argv=("sh", "-c", "env | grep -c '^GIT_\\(AUTHOR\\|COMMITTER\\)' || true"))
        self.assertEqual(self.podgit_run("rev-parse", "HEAD").stdout, first)
        self.assertIn("\n0\n", done.stdout)

    def test_a_mismatch_makes_no_commit(self):
        done, _ = self.run_sh(tree="0" * 40)
        self.assertEqual(done.returncode, 70)
        self.assertNotEqual(self.podgit_run("rev-parse", "--verify", "-q", "HEAD").returncode, 0)

    def test_the_jobs_own_directory_is_removed_at_the_end_pass_or_fail(self):
        for what, kw, code in (("pass", {}, 0), ("cmd fails", {"argv": ("sh", "-c", "exit 3")}, 3), ("hash mismatch", {"tree": "0" * 40}, 70),
                               ("tool mismatch", {"tools": {"x": ("1.0.0", "echo 2.0.0")}}, 71)):
            with self.subTest(what):
                done, _ = self.run_sh(**kw)
                self.assertEqual(done.returncode, code, done.stdout)
                self.assertFalse(self.job.exists(), "the job's files are gone")

    def test_a_dead_clients_old_job_directory_is_swept_and_a_recent_or_other_one_is_not(self):
        old, recent, other = self.tmp / "kgate-1-1", self.tmp / "kgate-2-2", self.tmp / "go-build"
        for d in (old, recent, other):
            (d / "f").parent.mkdir()
            (d / "f").write_text("x")
        two_days = __import__("time").time() - 2 * 86400
        for d in (old, other):
            os.utime(d, (two_days, two_days))
        done, _ = self.run_sh()
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(other.exists(), "only kgate-* directories are swept")

    def test_home_inside_the_job_directory_is_gone_for_the_next_job(self):
        home = self.job / "home"
        done, _ = self.run_sh(argv=("sh", "-c", 'mkdir -p "$HOME/.config/go" && echo x > "$HOME/.gitconfig" && echo y > "$HOME/.config/go/env"'), env={"HOME": str(home)})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertFalse(home.exists())
        done, _ = self.run_sh(argv=("sh", "-c", 'test ! -e "$HOME/.gitconfig" && test ! -e "$HOME/.config/go/env" && echo clean-home'), env={"HOME": str(home)})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("clean-home", done.stdout)

    def test_a_commit_that_fails_after_the_hashes_matched_is_its_own_marker_and_69_not_a_mismatch(self):
        done, _ = self.run_sh(argv=("sh", "-c", "echo SHOULD-NOT-RUN"), lock_main=True)
        self.assertEqual(done.returncode, 69, done.stdout)
        seen = self.markers(done.stdout)
        self.assertTrue(seen["commit"].startswith("FAILED git commit failed:"), done.stdout)
        self.assertNotIn("MISMATCH", done.stdout)
        self.assertNotIn("SHOULD-NOT-RUN", done.stdout)
        self.assertNotIn("running", seen)

    def test_no_head_on_the_mac_gives_an_empty_kgate_head(self):
        done, _ = self.run_sh(argv=("sh", "-c", 'echo "[$KGATE_HEAD]"'), head=None)
        self.assertIn("[]", done.stdout)

    # --- the cache trim (KGATE_CACHE_ROOT points the pod side's /cache at a temp dir; a pod never sets it)

    def cache_entry(self, cache, name, age, kib=2048):
        "One cache entry of about kib KiB whose files were last used age seconds ago."
        path = cache / name
        path.mkdir(parents=True)
        (path / "blob").write_bytes(b"x" * kib * 1024)
        t = time.time() - age
        os.utime(path, (t, t))
        os.utime(path / "blob", (t, t))
        return path

    def cache_file(self, parent, name, age, kib=2048):
        "One plain cache file of about kib KiB last used age seconds ago (the real caches are trimmed at file level)."
        path = parent / name
        parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * kib * 1024)
        t = time.time() - age
        os.utime(path, (t, t))
        return path

    def test_an_over_cap_cache_is_trimmed_oldest_file_first_and_the_job_still_passes(self):
        cache = self.tmp / "cache"
        old = self.cache_entry(cache / "go-build", "old", 3000)
        mid = self.cache_entry(cache / "go-build", "mid", 2000)
        new = self.cache_entry(cache / "go-build", "new", 10)
        done, _ = self.run_sh(cache_cap=3 << 20, env={"KGATE_CACHE_ROOT": str(cache)})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("over the 3072KiB cap: trimming oldest files first", done.stdout)
        self.assertRegex(done.stdout, r"removed [1-9] files in [0-9]+s, now at [0-9]+KiB \(cap 3072KiB\)")
        self.assertFalse((old / "blob").exists())
        self.assertFalse((mid / "blob").exists())
        self.assertTrue((new / "blob").exists(), "the newest file is the last to go")
        self.assertTrue((cache / "go-build").is_dir(), "the cache directory itself is never removed")
        self.assertEqual(self.markers(done.stdout)["hash"], "ok " + K.tree_hash(str(self.tree), self.files))

    def test_a_pnpm_store_is_trimmed_file_by_file_not_wiped_whole(self):
        "A real pnpm store holds only version directories (v3, v10, v11) over content: a trim of whole children would wipe it in one step."
        cache = self.tmp / "cache"
        blobs = cache / "pnpm-store" / "v10" / "files" / "ab"
        old = self.cache_file(blobs, "old", 3000)
        new = self.cache_file(blobs, "new", 10)
        now = time.time()
        for d in (cache / "pnpm-store", cache / "pnpm-store" / "v10", blobs):
            os.utime(d, (now, now))     # the version directories' own mtimes are the newest of all
        done, _ = self.run_sh(cache_cap=3 << 20, env={"KGATE_CACHE_ROOT": str(cache)})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertFalse(old.exists(), "the oldest file goes")
        self.assertTrue(new.exists(), "the newest file survives")
        for kept in (cache / "pnpm-store", cache / "pnpm-store" / "v10", blobs):
            self.assertTrue(kept.is_dir(), "no version or content directory is removed")
        self.assertEqual(sorted(p.name for p in cache.iterdir()), ["pnpm-store"], "nothing is written onto the claim")

    def test_the_pnpm_index_and_links_survive_the_trim_and_files_go_oldest_first(self):
        "pnpm 11 keeps its SQLite index at v11/index.db and whole packages in v11/links/: the trim touches only the version directories' files/ and index/ trees."
        cache = self.tmp / "cache"
        store = cache / "pnpm-store" / "v11"
        old = self.cache_file(store / "files" / "ab", "old", 3000)
        new = self.cache_file(store / "files" / "ab", "new", 10)
        index = self.cache_file(store, "index.db", 4000, kib=64)   # an old, stable store: the index is the oldest thing in it
        wal = self.cache_file(store, "index.db-wal", 4000, kib=64)
        link = self.cache_file(store / "links" / "x" / "node_modules" / "y", "pkg", 3000, kib=64)
        project = self.cache_file(store / "projects" / "p", "state", 3000, kib=64)
        # A links/ or projects/ path that merely contains a /files/ or /index/ part is still links/ or projects/ content:
        # a -path pattern's * crosses /, so it would match these and half-delete a package pnpm treats as installed.
        link_index = self.cache_file(store / "links" / "@x" / "y" / "1.0.0" / "h" / "node_modules" / "y" / "lib" / "index", "b.js", 5000, kib=64)
        project_files = self.cache_file(store / "projects" / "p" / "files", "s", 4000, kib=64)
        done, _ = self.run_sh(cache_cap=3 << 20, env={"KGATE_CACHE_ROOT": str(cache)})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertFalse(old.exists(), "the oldest files/ blob goes first")
        self.assertTrue(new.exists(), "the newest files/ blob survives")
        self.assertTrue(index.exists(), "index.db is never deleted, whatever version directory holds it")
        self.assertTrue(wal.exists(), "the -wal side file survives with it")
        self.assertTrue(link.exists(), "links/ (the global virtual store) is never touched")
        self.assertTrue(project.exists(), "projects/ is never touched")
        self.assertTrue(link_index.exists(), "a links/ path with an /index/ part is never listed")
        self.assertTrue(project_files.exists(), "a projects/ path with a /files/ part is never listed")
        self.assertTrue((store / "files" / "ab").is_dir(), "the content directory survives")

    def test_go_build_buckets_are_trimmed_by_file_age_not_bucket_mtime(self):
        "go-build is 256 bucket directories (00..ff) whose mtimes do not move when Go rewrites the files inside: the file ages decide."
        cache = self.tmp / "cache"
        ff_old = self.cache_file(cache / "go-build" / "ff", "old", 3000)
        ab_mid = self.cache_file(cache / "go-build" / "ab", "mid", 2000)
        new = self.cache_file(cache / "go-build" / "00", "new", 10)
        now = time.time()
        for b in ("00", "ab", "ff"):
            os.utime(cache / "go-build" / b, (now, now))    # every bucket directory's mtime is the newest of all
        done, _ = self.run_sh(cache_cap=5 << 20, env={"KGATE_CACHE_ROOT": str(cache)})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertFalse(ff_old.exists(), "the oldest file goes, whatever bucket it is in")
        self.assertTrue(ab_mid.exists())
        self.assertTrue(new.exists(), "the newest file survives")
        for b in ("00", "ab", "ff"):
            self.assertTrue((cache / "go-build" / b).is_dir(), "no bucket directory is removed")

    def test_an_under_cap_cache_is_left_alone(self):
        cache = self.tmp / "cache"
        keep = self.cache_entry(cache / "go-build", "keep", 3000, kib=64)
        done, _ = self.run_sh(cache_cap=8 << 30, env={"KGATE_CACHE_ROOT": str(cache)})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue(keep.exists())
        self.assertNotIn("trimming", done.stdout)

    def test_a_cap_of_zero_disables_the_trim(self):
        cache = self.tmp / "cache"
        keep = self.cache_entry(cache / "go-build", "keep", 3000, kib=64)
        done, _ = self.run_sh(cache_cap=0, env={"KGATE_CACHE_ROOT": str(cache)})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue(keep.exists())
        self.assertNotIn("trimming", done.stdout)

    def test_a_file_that_cannot_be_removed_is_skipped_and_the_job_still_passes(self):
        cache = self.tmp / "cache"
        stuck = self.cache_entry(cache / "go-build", "stuck", 3000)
        (stuck / "sub").mkdir()
        (stuck / "sub" / "blob").write_bytes(b"x" * 64 * 1024)
        (stuck / "sub").chmod(0)            # rm cannot reach into this, so this file cannot go
        free = self.cache_entry(cache / "go-build", "free", 2000)
        try:
            done, _ = self.run_sh(cache_cap=1 << 20, env={"KGATE_CACHE_ROOT": str(cache)})
        finally:
            (stuck / "sub").chmod(0o755)    # let the test's own cleanup remove what the trim could not
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue((stuck / "sub" / "blob").exists(), "the undeletable file is skipped, not a failed job")
        self.assertFalse((free / "blob").exists(), "the trim goes on with the files it can remove")

    def test_a_vanished_file_is_skipped_and_the_trim_goes_on(self):
        "A file that vanished since the listing is skipped (rm -f ignores it) and the trim goes on with the rest."
        fn = re.search(r"^trim_cache\(\) \{.*?^\}", K.POD_SH, re.S | re.M).group(0)
        cache = self.tmp / "cache"
        keep = self.cache_file(cache / "go-build", "keep", 10, kib=8)
        d = str(cache / "go-build")
        script = fn + "\n" + (   # fn ends at the closing brace with no newline; keep say() on its own line
            'say() { printf "%s\\n" "$*" ; }\n'
            + 'cache_files() { printf "100 2048 /no/such/vanished\\n200 65536 %s/keep\\n" "%s" ; }\n' % (d, d)
            + "trim_cache '%s' go 4\n" % d
        )
        done = subprocess.run(["sh", "-c", script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertFalse(keep.exists(), "the file that is still there goes")
        self.assertIn("over the 4KiB cap: trimming oldest files first", done.stdout)
        self.assertIn("removed 1 files", done.stdout, "the vanished file is not counted as removed")

    def test_a_cache_still_over_cap_after_the_trim_is_logged(self):
        "index.db, links/ and projects/ can exceed the cap on their own: the trim logs what is left instead of failing."
        fn = re.search(r"^trim_cache\(\) \{.*?^\}", K.POD_SH, re.S | re.M).group(0)
        cache = self.tmp / "cache"
        keep = self.cache_file(cache / "go-build", "keep", 10, kib=8)
        d = str(cache / "go-build")
        script = fn + "\n" + (   # fn ends at the closing brace with no newline; keep say() on its own line
            'say() { printf "%s\\n" "$*" ; }\n'
            + "cache_files() { : ; }\n"   # nothing is trimmable: the listing is empty
            + "trim_cache '%s' go 4\n" % d
        )
        done = subprocess.run(["sh", "-c", script], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue(keep.exists())
        self.assertRegex(done.stdout, r"still over cap: [0-9]+KiB not trimmable")

    def test_a_failed_trim_never_fails_the_job(self):
        "rm cannot delete from a directory this user cannot write: the trim removes nothing, says so, and the job passes."
        cache = self.tmp / "cache"
        stuck_dir = cache / "go-build" / "ff"
        stuck = self.cache_file(stuck_dir, "stuck", 3000)
        stuck_dir.chmod(0o555)
        try:
            done, _ = self.run_sh(cache_cap=1 << 20, env={"KGATE_CACHE_ROOT": str(cache)})
        finally:
            stuck_dir.chmod(0o755)      # let the test's own cleanup remove what the trim could not
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue(stuck.exists(), "the undeletable file is still there")
        self.assertRegex(done.stdout, r"removed nothing in [0-9]+s, still at [0-9]+KiB \(cap 1024KiB\)")
        self.assertEqual(self.markers(done.stdout)["hash"], "ok " + K.tree_hash(str(self.tree), self.files))

    def test_no_cache_cap_line_and_no_trim_without_one(self):
        cache = self.tmp / "cache"
        keep = self.cache_entry(cache / "go-build", "keep", 3000, kib=64)
        done, _ = self.run_sh(env={"KGATE_CACHE_ROOT": str(cache)})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue(keep.exists())
        self.assertNotIn("trimming", done.stdout)


SUB_SHA = "1" * 40


def add_uninitialised_submodule(repo, path, sha=SUB_SHA):
    """A gitlink in the index with only an empty directory in the tree: what a clone without --recurse-submodules leaves."""
    git(repo, "update-index", "--add", "--cacheinfo", "160000,%s,%s" % (sha, path))
    (Path(repo) / path).mkdir(parents=True, exist_ok=True)


def add_initialised_submodule(repo, path, tmp):
    """A real submodule, checked out, from an invented local repo."""
    src = Path(tmp) / ("src-" + path.replace("/", "-"))
    src.mkdir()
    git(src, "init", "-q")
    (src / "lib.txt").write_text("library\n")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "lib")
    git(repo, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(src), path)


class Submodules(unittest.TestCase):
    """A submodule (a gitlink in the index) is left out of the file list, the tar and the tree hash; any other directory in the list is refused."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="ksm-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / "a.txt").write_text("a\n")
        (self.repo / "run.sh").write_text("#!/bin/sh\n")
        (self.repo / "run.sh").chmod(0o755)
        os.symlink("a.txt", self.repo / "link")
        (self.repo / "pkg").mkdir()
        (self.repo / "pkg" / "b.txt").write_text("b\n")

    def listing(self):
        skipped = []
        wt, common, files = K.worktree(str(self.repo), skipped)
        return files, skipped

    def git_hash(self, files):
        """The tree hash by git itself: a throwaway index holding exactly `files`."""
        env = {**os.environ, "GIT_INDEX_FILE": str(self.tmp / "idx")}
        run = lambda *a, **kw: subprocess.run(["git", "-c", "core.autocrlf=false", *a], cwd=self.repo, env=env, check=True, stdout=subprocess.PIPE, **kw).stdout
        run("update-index", "--add", "-z", "--stdin", input=b"".join(os.fsencode(f) + b"\0" for f in files))
        return run("write-tree").decode().strip()

    def test_an_uninitialised_submodule_is_skipped(self):
        add_uninitialised_submodule(self.repo, "vendor/lib")
        add_uninitialised_submodule(self.repo, "other")
        git(self.repo, "add", "-A")
        files, skipped = self.listing()
        self.assertEqual(skipped, ["other", "vendor/lib"])
        self.assertEqual(sorted(files), ["a.txt", "link", "pkg/b.txt", "run.sh"])

    def test_an_initialised_submodule_is_skipped_with_its_files(self):
        add_initialised_submodule(self.repo, "vendor/lib", self.tmp)
        git(self.repo, "add", "-A")
        self.assertTrue((self.repo / "vendor/lib/lib.txt").exists())
        files, skipped = self.listing()
        self.assertEqual(skipped, ["vendor/lib"])
        self.assertFalse([f for f in files if f.startswith("vendor/lib")], files)
        self.assertIn(".gitmodules", files)   # a plain tracked file: it ships

    def test_a_directory_that_is_not_a_submodule_is_still_refused(self):
        nested = self.repo / "nested"
        nested.mkdir()
        git(nested, "init", "-q")
        (nested / "x.txt").write_text("x\n")
        git(nested, "add", "-A")
        git(nested, "commit", "-q", "-m", "x")   # an untracked nested repo: `ls-files -o` lists it as a directory, not a gitlink
        with self.assertRaises(K.Unavailable) as caught:
            self.listing()
        self.assertIn("nested", str(caught.exception))
        self.assertIn("not a submodule", str(caught.exception))

    def test_the_hash_is_the_same_with_the_submodule_uninitialised_initialised_or_absent(self):
        files, skipped = self.listing()
        plain = K.tree_hash(str(self.repo), files)
        self.assertEqual(plain, self.git_hash(files))      # kgate's hash is git's, with an executable file and a symlink in the tree
        add_uninitialised_submodule(self.repo, "vendor/lib")
        git(self.repo, "add", "-A")
        files, skipped = self.listing()
        self.assertEqual(skipped, ["vendor/lib"])
        self.assertEqual(K.tree_hash(str(self.repo), files), plain)
        shutil.rmtree(self.repo / "vendor/lib")
        git(self.repo, "rm", "-q", "--cached", "vendor/lib")
        git(self.repo, "reset", "-q")
        (self.repo / "vendor").rmdir()
        add_initialised_submodule(self.repo, "vendor/lib", self.tmp)
        files, skipped = self.listing()
        self.assertEqual(skipped, ["vendor/lib"])
        tracked = [f for f in files if f != ".gitmodules"]
        self.assertEqual(K.tree_hash(str(self.repo), tracked), plain)

    def test_the_hash_still_catches_a_real_change(self):
        add_uninitialised_submodule(self.repo, "vendor/lib")
        files, _ = self.listing()
        before = K.tree_hash(str(self.repo), files)
        (self.repo / "a.txt").write_text("changed\n")
        self.assertNotEqual(K.tree_hash(str(self.repo), files), before)

    def test_the_tar_has_no_submodule_path(self):
        add_initialised_submodule(self.repo, "vendor/lib", self.tmp)
        git(self.repo, "add", "-A")
        wt, common, files = K.worktree(str(self.repo))
        import io, tarfile
        with tarfile.open(fileobj=io.BytesIO(K.archive(wt, common, files, {}, history=False))) as tar:
            names = tar.getnames()
        self.assertIn((wt + "/a.txt").lstrip("/"), names)
        self.assertEqual([n for n in names if "vendor/lib" in n], [])

    def test_the_history_archive_extracts_to_a_clean_tree_with_the_same_hash(self):
        """The homelab ships .git, so the gitlinks stay in HEAD and the index: each skipped submodule gets an empty directory, and git in the pod sees nothing missing."""
        add_initialised_submodule(self.repo, "vendor/my lib", self.tmp)
        add_uninitialised_submodule(self.repo, "other")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "all")
        skipped = []
        wt, common, files = K.worktree(str(self.repo), skipped)
        self.assertEqual(skipped, ["other", "vendor/my lib"])
        out = self.tmp / "pod"
        out.mkdir()
        import io, tarfile
        with tarfile.open(fileobj=io.BytesIO(K.archive(wt, common, files, {}, history=True, skipped=skipped))) as tar:
            names = tar.getnames()
            tar.extractall(out)
        pod = out / wt.lstrip("/")
        for p in skipped:
            self.assertTrue((pod / p).is_dir() and not os.listdir(pod / p), p)
        self.assertEqual([n for n in names if "/.git/modules" in n], [], "a submodule's own repository is not shipped")
        porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=pod, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.assertEqual((porcelain.returncode, porcelain.stdout), (0, b""))
        self.assertEqual(subprocess.run(["git", "diff", "--quiet"], cwd=pod).returncode, 0)
        pod_files, pod_skipped = K.worktree(str(pod))[2], []
        self.assertEqual(pod_files, files)
        self.assertEqual(K.tree_hash(str(pod), pod_files), K.tree_hash(wt, files))


class Archive(unittest.TestCase):
    """What is shipped: the homelab keeps .git and the shared git folder; a kubectl cluster ships the files and the extras only."""

    def repo_and_linked(self):
        tmp = Path(tempfile.mkdtemp(prefix="ka-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        main, linked = tmp / "main", tmp / "linked"
        main.mkdir()
        git(main, "init", "-q")
        (main / "f").write_text("x\n")
        git(main, "add", "-A")
        git(main, "commit", "-q", "-m", "i")
        git(main, "worktree", "add", "-q", str(linked))
        return main, linked

    def names(self, wt, history):
        wt, common, files = K.worktree(str(wt))
        data = K.archive(wt, common, files, {"cache/x/job.sh": b"j"}, history=history)
        import io, tarfile
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            return tar.getnames(), wt, common

    def test_the_default_still_ships_dot_git_and_the_shared_git_folder(self):
        main, linked = self.repo_and_linked()
        names, wt, common = self.names(main, True)
        self.assertIn((wt + "/.git/HEAD").lstrip("/"), names)
        names, wt, common = self.names(linked, True)
        self.assertIn((wt + "/.git").lstrip("/"), names)
        self.assertIn((common + "/HEAD").lstrip("/"), names)

    def test_without_history_there_is_no_git_entry_at_all_but_the_files_and_extras(self):
        main, linked = self.repo_and_linked()
        for wt in (main, linked):
            names, root, common = self.names(wt, False)
            self.assertEqual([n for n in names if re.search(r"(^|/)\.git(/|$)", n)], [])
            self.assertIn((root + "/f").lstrip("/"), names)
            self.assertIn("cache/x/job.sh", names)

    def test_a_git_file_that_vanishes_while_it_is_read_is_left_out_not_fatal(self):
        main, linked = self.repo_and_linked()
        wt, common, files = K.worktree(str(main))
        real_listdir, real_lstat = os.listdir, os.lstat
        ghost = os.path.join(common, "t3-checkpoint-index-0000")

        def listdir(path="."):
            names = real_listdir(path)
            return names + ["t3-checkpoint-index-0000"] if os.fspath(path) == common else names

        def lstat(path, *a, **k):
            if os.fspath(path) == ghost:
                raise FileNotFoundError(2, "No such file or directory", ghost)   # listed, then deleted before tar stats it
            return real_lstat(path, *a, **k)
        with mock.patch("os.listdir", listdir), mock.patch("os.lstat", lstat):
            data = K.archive(wt, common, files, {}, history=True)
        import io, tarfile
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            names = tar.getnames()
        self.assertIn((common + "/HEAD").lstrip("/"), names)
        self.assertNotIn(ghost.lstrip("/"), names)

    def test_a_git_file_deleted_between_stat_and_open_is_left_out(self):
        main, linked = self.repo_and_linked()
        wt, common, files = K.worktree(str(main))
        victim = os.path.join(common, "HEAD")
        real_open = open

        def fake_open(path, *a, **k):
            if os.fspath(path) == victim:
                raise FileNotFoundError(2, "No such file or directory", victim)
            return real_open(path, *a, **k)
        with mock.patch.dict(K.__dict__, {"open": fake_open}):
            data = K.archive(wt, common, files, {}, history=True)
        import io, tarfile
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            names = tar.getnames()
        self.assertNotIn(victim.lstrip("/"), names)
        self.assertIn((common + "/config").lstrip("/"), names)

    def test_a_git_folder_deleted_while_it_is_read_is_left_out_with_what_it_held(self):
        # 2026-11-16 01:51Z: a job died on `.git/worktrees/proof-main-old`, a linked worktree's folder removed between the stat and the listing
        main, linked = self.repo_and_linked()
        wt, common, files = K.worktree(str(main))
        gone = os.path.join(common, "objects", "pack-gone")
        os.makedirs(gone)
        Path(gone, "inside").write_text("x")
        real_listdir = os.listdir

        def listdir(path="."):
            if os.fspath(path) == gone:
                raise FileNotFoundError(2, "No such file or directory", gone)
            return real_listdir(path)
        with mock.patch("os.listdir", listdir):
            data = K.archive(wt, common, files, {}, history=True)
        import io, tarfile
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            names = tar.getnames()
        self.assertNotIn((gone + "/inside").lstrip("/"), names)
        self.assertIn((common + "/HEAD").lstrip("/"), names)

    def lean_repo(self):
        """A repo with a second worktree, an rr-cache entry, reflogs and metadata for two linked worktrees (own, other)."""
        main, own = self.repo_and_linked()
        tmp = main.parent
        other = tmp / "other"
        git(main, "worktree", "add", "-q", "-b", "side", str(other))
        (other / "g").write_text("y\n")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "side")
        common = main / ".git"
        (common / "rr-cache" / "abc").mkdir(parents=True)
        (common / "rr-cache" / "abc" / "preimage").write_text("p\n")
        # names that look like the dropped ones but are not at the top of the git folder
        git(main, "branch", "logs")
        git(main, "branch", "rr-cache-notes")
        return main, own, other

    def extracted(self, wt):
        """(names, pod root) of the history archive of `wt`, extracted under a temp root."""
        w, common, files = K.worktree(str(wt))
        data = K.archive(w, common, files, {}, history=True)
        out = self.tmp_out()
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            names = tar.getnames()
            tar.extractall(out)
        return names, out, w, common

    def tmp_out(self):
        out = Path(tempfile.mkdtemp(prefix="kal-")).resolve()
        self.addCleanup(shutil.rmtree, out, True)
        return out

    def test_the_shared_git_folder_leaves_out_rr_cache_reflogs_and_other_worktrees(self):
        main, own, other = self.lean_repo()
        names, out, w, common = self.extracted(own)
        c = common.lstrip("/")
        own_name = os.path.basename(gitout(own, "rev-parse", "--git-dir"))
        other_name = os.path.basename(gitout(other, "rev-parse", "--git-dir"))
        self.assertNotEqual(own_name, other_name)
        under = lambda *parts: [n for n in names if n == "/".join((c,) + parts) or n.startswith("/".join((c,) + parts) + "/")]
        self.assertEqual(under("rr-cache"), [], "rr-cache stays here")
        self.assertEqual(under("logs"), [], "reflogs stay here")
        self.assertEqual(under("worktrees", other_name), [], "another worktree's metadata stays here")
        self.assertEqual(under("worktrees", own_name, "logs"), [], "the worktree's own reflogs stay here")
        self.assertIn("%s/worktrees/%s/HEAD" % (c, own_name), names, "the shipping worktree's own metadata ships")
        self.assertIn("%s/worktrees/%s/index" % (c, own_name), names)
        for kept in ("HEAD", "config", "packed-refs", "refs/heads/logs", "refs/heads/rr-cache-notes", "refs/heads/side"):
            if os.path.exists(os.path.join(common, kept)):
                self.assertIn("%s/%s" % (c, kept), names, kept)
        self.assertTrue([n for n in names if n.startswith(c + "/objects/")], "objects ship")

    def test_the_main_checkout_ships_no_linked_worktree_metadata(self):
        main, own, other = self.lean_repo()
        names, out, w, common = self.extracted(main)
        dot = (w + "/.git").lstrip("/")
        self.assertEqual([n for n in names if n.startswith(dot + "/worktrees/") and n != dot + "/worktrees"], [])
        self.assertEqual([n for n in names if n == dot + "/rr-cache" or n.startswith(dot + "/rr-cache/") or n == dot + "/logs" or n.startswith(dot + "/logs/")], [])
        self.assertIn(dot + "/HEAD", names)

    def pod_git(self, out, wt, common, gitdir, *args):
        """git against the extracted copy only: the .git file of a linked worktree holds an absolute path back to the real repo, so
        the folders are named explicitly."""
        env = {**os.environ, "GIT_DIR": str(out / gitdir.lstrip("/")), "GIT_COMMON_DIR": str(out / common.lstrip("/")),
               "GIT_WORK_TREE": str(out / wt.lstrip("/"))}
        done = subprocess.run(["git", *args], cwd=out / wt.lstrip("/"), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return done.returncode, done.stdout

    def test_git_in_the_pod_works_without_the_left_out_folders(self):
        main, own, other = self.lean_repo()
        for wt in (own, main):
            names, out, w, common = self.extracted(wt)
            gitdir = gitout(wt, "rev-parse", "--path-format=absolute", "--git-dir")
            self.assertTrue((out / gitdir.lstrip("/") / "HEAD").is_file())
            want = gitout(wt, "rev-parse", "HEAD")
            self.assertEqual(self.pod_git(out, w, common, gitdir, "status", "--porcelain"), (0, ""))
            self.assertEqual(self.pod_git(out, w, common, gitdir, "rev-parse", "HEAD"), (0, want + "\n"))
            self.assertEqual(self.pod_git(out, w, common, gitdir, "log", "-1", "--format=%H"), (0, want + "\n"))
            rc, merged = self.pod_git(out, w, common, gitdir, "merge-tree", "--write-tree", "HEAD", "side")
            self.assertEqual(rc, 0, merged)

    def test_a_worktree_file_that_vanishes_still_fails_the_job(self):
        main, linked = self.repo_and_linked()
        wt, common, files = K.worktree(str(main))
        os.unlink(os.path.join(wt, "f"))
        with self.assertRaises(FileNotFoundError):
            K.archive(wt, common, files, {}, history=True)


class RepoName(unittest.TestCase):
    """The name a job logs for its repo: the origin URL's last part without .git; the folder when there is no origin."""

    def repo(self, folder, origin=None):
        tmp = Path(tempfile.mkdtemp(prefix="krn-")).resolve()
        self.addCleanup(shutil.rmtree, tmp, True)
        repo = tmp / folder
        repo.mkdir()
        git(repo, "init", "-q")
        if origin is not None:
            git(repo, "remote", "add", "origin", origin)
        wt, common, _ = K.worktree(str(repo))
        return K.repo_name(wt, common)

    def test_each_url_form_gives_the_last_part(self):
        for url in ("git@github.com:cartwmic/coordinator.git", "git@github.com:cartwmic/coordinator", "https://github.com/cartwmic/coordinator.git",
                    "https://github.com/cartwmic/coordinator", "https://github.com/cartwmic/coordinator/", "ssh://git@host:2222/a/b/coordinator.git",
                    "/srv/git/coordinator.git", "/srv/git/coordinator"):
            with self.subTest(url=url):
                self.assertEqual(self.repo("some-folder", url), "coordinator")

    def test_no_origin_is_the_folder(self):
        self.assertEqual(self.repo("some-folder"), "some-folder")

    def test_a_folder_that_matches_its_origin_logs_what_it_did_before(self):
        self.assertEqual(self.repo("coordinator", "git@github.com:cartwmic/coordinator.git"), "coordinator")

    def test_an_origin_with_no_name_in_it_is_the_folder(self):
        self.assertEqual(self.repo("some-folder", "/"), "some-folder")


class KubectlBlack(unittest.TestCase):
    """The kubectl adapter through the real script as a process against a fake kubectl: the same contract as the homelab journeys."""
    for _name in ("kgate", "records", "calls", "op_token_checks", "op_env", "active", "add_entry", "dead_entry"):
        locals()[_name] = getattr(Black, _name)

    def launcher(self):
        # The script runs through a stub that shortens two waits (quota retry, cache grace) so the tests do not sleep.
        return stub_launcher(self.tmp, "kcl_launch.py", "import importlib.machinery, importlib.util, sys\n"
                             "loader = importlib.machinery.SourceFileLoader('kg', sys.argv[1])\n"
                             "K = importlib.util.module_from_spec(importlib.util.spec_from_loader('kg', loader))\n"
                             "loader.exec_module(K)\n"
                             "K.QUOTA_FIRST_DELAY = 0.2\n"
                             "K.CACHE_BUSY_S = 0.6\n"
                             "sys.exit(K.main(sys.argv[2:]))\n")

    def setUp(self):
        Black.setUp(self)
        (self.bin / "kubectl").write_text(FAKE_KUBECTL)
        (self.bin / "kubectl").chmod(0o755)
        (self.home / ".kube").mkdir()
        (self.home / ".kube" / "example").write_text("apiVersion: v1\n")
        self.cmd_env = {"KGATE_SSH": ""}
        self.write_cluster()

    def write_cluster(self, name="example", roots=None, drop=(), extra="", registries='["registry.example", "other.example"]', deadline=7200):
        """~/.config/kgate/clusters/<name>.toml in the test HOME. The temp dirs of these tests are under /tmp on Linux, so that top directory is a tree root here."""
        roots = roots or sorted({"Users", "Volumes", "private", self.repo.parts[1]})
        lines = {"kind": 'kind = "kubectl"', "kubeconfig": 'kubeconfig = "~/.kube/example"', "context": 'context = "example-ctx"', "namespace": 'namespace = "jobs"',
                 "registries": "registries = " + registries, "tree_roots": "tree_roots = [%s]" % ", ".join('"%s"' % r for r in roots),
                 "user": 'user = "65532:65532"', "deadline_s": "deadline_s = %d" % deadline}
        text = "\n".join(v for k, v in lines.items() if k not in drop) + "\n[pod_labels]\n\"example.org/owner\" = \"team-a\"\n\"example.org/tier\" = \"build\"\n" \
               "[pod_annotations]\n\"example.org/evict-ok\" = \"true\"\n" + extra
        path = self.home / ".config" / "kgate" / "clusters" / (name + ".toml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def profile(self, tools="", extra="", secrets="", memory="1Gi", image=KCL_IMAGE):
        (self.repo / "kgate.toml").write_text('cluster = "example"\nimage = "%s"\ncpu = 2\nmemory = "%s"\nmemory_limit = "2Gi"\nephemeral_storage = "5Gi"\n%s\n[tools]\n%s\n[secrets]\n%s\n'
                                              % (image, memory, extra, tools, secrets))

    def run_kgate(self, *args, env=None):
        return self.kgate(*args, host="", env={**self.cmd_env, **(env or {})})

    def kcalls(self):
        path = self.fake / "kcalls.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def kubectl_args(self):
        return [c["argv"][6:] for c in self.kcalls() if "argv" in c and c["argv"][2:3] != ["config"]]

    def test_passes_with_cmds_exit_code_and_returns_out(self):
        done = self.run_kgate("--", "sh", "-c", 'echo ran-in-pod; cat tracked.txt untracked.txt; echo result > "$KGATE_OUT/result.txt"')
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ran-in-pod", done.stdout)
        self.assertIn("tracked and changed", done.stdout)          # the uncommitted change shipped
        self.assertIn("new", done.stdout)                           # the untracked file shipped
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["ran"], rec["cleanup"], rec["cluster"]), (0, None, True, True, "example"))
        self.assertEqual((rec["node"], rec["image"], rec["mem"], rec["mem_limit"]), ("fake-kcl-node", KCL_IMAGE, "1Gi", "2Gi"))
        self.assertIn("kgate[%s]: hash ok %s" % (rec["id"], rec["tree"]), done.stdout)
        self.assertEqual(rec["out_files"], 1)
        self.assertEqual((self.state / "kgate" / (rec["id"] + ".out") / "result.txt").read_text(), "result\n")
        import tarfile
        with tarfile.open(self.fake / "shipped.tar") as tar:   # the pod removed its copy at the end
            files = tar.extractfile("cache/%s/files.nul" % rec["id"]).read().split(b"\0")[:-1]
        self.assertFalse((self.fake / "jobroot" / "cache" / rec["id"]).exists(), "the job's own directory is gone from /cache")
        self.assertEqual(sorted(files), [b".gitignore", b"kgate.toml", b"tracked.txt", b"untracked.txt"])  # not ignored.txt

    def test_a_submodule_is_skipped_with_one_line_and_the_pod_hash_matches(self):
        add_initialised_submodule(self.repo, "vendor/lib", self.tmp)
        add_uninitialised_submodule(self.repo, "other")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "submodules")
        done = self.run_kgate("--", "sh", "-c", "echo ran-ok")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ran-ok", done.stdout)
        self.assertIn("kgate: not shipping submodules: other, vendor/lib\n", done.stdout)
        self.assertEqual(done.stdout.count("not shipping submodules"), 1)
        rec = self.records()[-1]
        self.assertIn("kgate[%s]: hash ok %s" % (rec["id"], rec["tree"]), done.stdout)   # the pod rebuilt the index from the shipped list with git: same tree
        import tarfile
        with tarfile.open(self.fake / "shipped.tar") as tar:
            files = tar.extractfile("cache/%s/files.nul" % rec["id"]).read().split(b"\0")[:-1]
        self.assertEqual([f for f in files if f.startswith(b"vendor") or f == b"other"], [])

    def test_a_nested_repo_that_is_not_a_submodule_is_exit_69(self):
        nested = self.repo / "nested"
        nested.mkdir()
        git(nested, "init", "-q")
        (nested / "x.txt").write_text("x\n")
        git(nested, "add", "-A")
        git(nested, "commit", "-q", "-m", "x")
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("nested", done.stdout)
        self.assertEqual(self.kubectl_args(), [], "nothing reached the cluster")

    def test_a_submodule_path_with_a_space_is_skipped_and_the_pod_hash_matches(self):
        add_initialised_submodule(self.repo, "vendor/my lib", self.tmp)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "submodule with a space")
        done = self.run_kgate("--", "sh", "-c", "echo ran-ok")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ran-ok", done.stdout)
        self.assertIn("kgate: not shipping submodules: vendor/my lib\n", done.stdout)
        rec = self.records()[-1]
        self.assertIn("kgate[%s]: hash ok %s" % (rec["id"], rec["tree"]), done.stdout)
        import tarfile
        with tarfile.open(self.fake / "shipped.tar") as tar:
            files = tar.extractfile("cache/%s/files.nul" % rec["id"]).read().split(b"\0")[:-1]
        self.assertEqual([f for f in files if f.startswith(b"vendor")], [])
        self.assertIn(b".gitmodules", files)

    def test_a_linked_worktree_whose_common_dir_is_outside_the_allow_list_is_accepted(self):
        """The common dir is not shipped on a kubectl cluster, so only the worktree's own top directory needs an emptyDir and a place on the allow-list."""
        linked = Path(tempfile.mkdtemp(prefix="kl-", dir=os.path.expanduser("~"))).resolve() / "wt"
        self.addCleanup(shutil.rmtree, linked.parent, True)
        git(self.repo, "worktree", "add", "-q", "-b", "other", str(linked))
        if linked.parts[1] == self.repo.parts[1]:
            self.skipTest("the main repo and the worktree share a top directory here")
        self.write_cluster(roots=[linked.parts[1]])   # the main repo's top directory is not a tree root
        self.repo = linked
        done = self.run_kgate("--", "sh", "-c", "git rev-parse HEAD; test ! -e .git/commondir && echo own-repo")
        self.assertEqual(done.returncode, 0, done.stdout)
        manifest = next(c["manifest"] for c in self.kcalls() if "manifest" in c)
        mounts = [m["mountPath"] for m in manifest["items"][0]["spec"]["containers"][0]["volumeMounts"]]
        self.assertEqual(mounts, ["/" + linked.parts[1], "/cache", "/out"], "no emptyDir for the common dir's top directory")

    def mssql_profile(self, extra="", sql_image="registry.example/db/sql@sha256:" + "ee" * 32, hostnames='["db"]', image=KCL_IMAGE):
        self.profile(image=image, extra='services = ["mssql"]\nlocal_hostnames = %s\n%s\n[mssql]\nimage = "%s"\nready_s = 60\n[[image_volumes]]\nimage = "registry.example/tools/flyway@sha256:%s"\npath = "/mnt/flyway"\n'
                     % (hostnames, extra, sql_image, "ff" * 32))

    def test_mssql_runs_cmd_in_the_job_container_and_the_password_stays_out_of_every_record(self):
        self.mssql_profile()
        done = self.run_kgate("--", "sh", "-c", 'echo "host=$MSSQL_HOST pw=$MSSQL_SA_PASSWORD"')
        self.assertEqual(done.returncode, 0, done.stdout)
        manifest = next(c["manifest"] for c in self.kcalls() if "manifest" in c)
        pw = {e["name"]: e["value"] for e in manifest["items"][0]["spec"]["initContainers"][0]["env"]}["MSSQL_SA_PASSWORD"]
        self.assertIn("host=localhost pw=***", done.stdout)
        self.assertIn("SQL Server ready after", done.stdout)
        self.assertIn("peak mssql 734003200 cgroup", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["services"], rec["service_peak_bytes"]), (0, ["mssql"], 734003200))
        self.assertIn("service_ready_s", rec)
        self.assertIn("pod_start_s", rec)
        self.assertEqual(rec["service_cpu_usec"], 4200000)
        self.assertIn("cpu mssql 4200000 usec", done.stdout)
        everything = done.stdout + (done.stderr or "") + "".join(p.read_text(errors="replace") for p in self.state.rglob("*") if p.is_file())
        self.assertNotIn(pw, everything, "the generated SA password is in the pod spec only")
        execs = [a for a in self.kubectl_args() if a[0] == "exec" and "-i" in a]
        self.assertEqual(execs[0][3:5], ["-c", "job"], "a pod with two containers: CMD goes to the job container")

    def test_each_job_gets_its_own_password(self):
        self.mssql_profile()
        pws = []
        for _ in range(2):
            self.run_kgate("--", "true")
            manifest = [c["manifest"] for c in self.kcalls() if "manifest" in c][-1]
            pws.append(manifest["items"][0]["spec"]["initContainers"][0]["env"][1]["value"])
        self.assertNotEqual(pws[0], pws[1])

    def test_a_sidecar_that_never_becomes_ready_is_69_with_its_masked_log_tail_and_cmd_not_run(self):
        self.mssql_profile()
        done = self.run_kgate("--", "sh", "-c", "echo should-not-run", env={"FAKE_POD": "mssql-crash"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("SQL Server sidecar did not become ready", done.stdout)
        self.assertIn("Login failed for user sa, password ***", done.stdout)
        self.assertNotIn("should-not-run", done.stdout)
        manifest = next(c["manifest"] for c in self.kcalls() if "manifest" in c)
        pw = manifest["items"][0]["spec"]["initContainers"][0]["env"][1]["value"]
        self.assertNotIn(pw, done.stdout + (done.stderr or ""))
        self.assertTrue(self.records()[-1]["cleanup"])
        self.assert_password_nowhere(pw, done)
        self.assertIn("password ***", self.records()[-1]["reason"])
        cancel = self.kgate("cancel", self.records()[-1]["id"], host="", env=self.cmd_env)   # reads the record back and prints it
        self.assertNotIn(pw, cancel.stdout + (cancel.stderr or ""))

    def assert_password_nowhere(self, pw, done):
        """The real generated password is in no state file (log.jsonl, the job log, the registry), nor in stdout or stderr."""
        files = {str(p.relative_to(self.state)): p.read_text(errors="replace") for p in self.state.rglob("*") if p.is_file()}
        self.assertIn("kgate/log.jsonl", files)
        for name, text in files.items():
            self.assertNotIn(pw, text, name)
        self.assertNotIn(pw, done.stdout + (done.stderr or ""))

    def test_a_pod_create_refusal_that_echoes_the_password_is_masked_in_the_record_and_output(self):
        self.mssql_profile()
        done = self.run_kgate("--", "true", env={"FAKE_CREATE_ECHO_PW": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("could not create the pod", done.stdout)
        self.assertIn("MSSQL_SA_PASSWORD=***", done.stdout)
        self.assertIn("MSSQL_SA_PASSWORD=***", self.records()[-1]["reason"])
        pw = (self.fake / "echoed_pw").read_text()
        self.assertRegex(pw, r"^Aa1_[0-9a-f]{32}$")
        self.assert_password_nowhere(pw, done)
        cancel = self.kgate("cancel", self.records()[-1]["id"], host="", env=self.cmd_env)
        self.assertNotIn(pw, cancel.stdout + (cancel.stderr or ""))

    def test_a_password_split_across_two_pipe_reads_is_masked(self):
        pw = "Aa1_" + "0123456789abcdef" * 2
        for cut in range(1, len(pw)):
            with self.subTest(cut=cut):
                job = object.__new__(K.Job)
                job.secret, job.carry, job.console = pw, b"", False
                job.log = tempfile.TemporaryFile()
                self.addCleanup(job.log.close)
                for chunk in (b"before " + pw[:cut].encode(), pw[cut:].encode() + b" after, " + pw.encode() + b" again " + pw[:5].encode()):
                    job.emit(chunk)
                job.flush()
                job.log.seek(0)
                out = job.log.read()
                self.assertNotIn(pw.encode(), out)
                self.assertEqual(out, b"before *** after, *** again " + pw[:5].encode())

    def test_the_sidecar_image_and_the_volume_images_must_come_from_the_cluster_registries(self):
        self.mssql_profile(sql_image="mcr.example/db/sql@sha256:" + "ee" * 32)
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("[mssql] image", done.stdout)
        self.assertIn("must come from registry.example", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.kcalls()))
        self.mssql_profile()
        text = (self.repo / "kgate.toml").read_text().replace("registry.example/tools/flyway", "elsewhere.example/tools/flyway")
        (self.repo / "kgate.toml").write_text(text)
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("image_volumes image", done.stdout)

    def test_a_registries_entry_may_be_a_host_or_a_host_and_path_prefix(self):
        self.write_cluster(registries='["registry.example/team/db"]')
        sql = lambda repo: "registry.example/%s@sha256:%s" % (repo, "ee" * 32)
        job = sql("team/db/job")
        self.mssql_profile(sql_image=sql("team/db"), image=job)              # the repository equals the entry
        self.assertEqual(self.run_kgate("--", "true").returncode, 69)   # the volume image is under tools/, not admitted
        text = (self.repo / "kgate.toml").read_text().replace("registry.example/tools/flyway", "registry.example/team/db/flyway")
        (self.repo / "kgate.toml").write_text(text)
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)         # entry + "/" prefix admits the volume, equality admits the sidecar
        self.mssql_profile(sql_image=sql("team/other"), image=job)           # a sibling repo on the same host
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("[mssql] image", done.stdout)
        self.assertEqual(K.registry_admits(["h.example/a/b"], "h.example/a/bc@sha256:" + "0" * 64), False)
        self.assertEqual(K.registry_admits(["h.example"], "h.example/x/y:1"), True)

    def test_a_tagged_ref_is_admitted_by_its_repository_without_the_tag(self):
        d = "@sha256:" + "ab" * 32
        self.assertTrue(K.registry_admits(["registry.example/team/db"], "registry.example/team/db:1.2" + d))
        self.assertFalse(K.registry_admits(["registry.example/team/db"], "registry.example/team/dbx:1" + d))
        self.assertTrue(K.registry_admits(["registry.example:5000/team/db"], "registry.example:5000/team/db:1" + d))
        self.assertTrue(K.registry_admits(["registry.example:5000"], "registry.example:5000/team/db:1" + d))
        self.assertTrue(K.registry_admits(["registry.example/team/db"], "registry.example/team/db" + d))

    def test_a_ref_without_a_slash_is_a_docker_hub_image_and_is_never_admitted(self):
        d = "@sha256:" + "ab" * 32
        for entry in ("registry.example", "registry.example:5000", "db", "db:1"):
            for ref in ("registry.example" + d, "registry.example:5000" + d, "db:1" + d, "db" + d):
                with self.subTest(entry=entry, ref=ref):
                    self.assertFalse(K.registry_admits([entry], ref))
        self.assertTrue(K.registry_admits(["registry.example"], "registry.example/db" + d))   # host entry, ref under it

    def test_an_image_volume_may_not_cover_the_cache_out_a_tree_root_or_a_system_directory(self):
        for path in ("/cache", "/out", "/cache/x", "/Users", "/Users/me/tool", "/", "/usr", "/usr/local/bin", "/etc/x", "/bin", "/sbin", "/lib", "/lib64/x", "/proc", "/sys/x", "/dev/shm", "/./usr", "/.", "/a/../usr", "/usr/", "/a//b", "/opt/./x"):
            with self.subTest(path):
                self.mssql_profile()
                text = (self.repo / "kgate.toml").read_text().replace("/mnt/flyway", path)
                (self.repo / "kgate.toml").write_text(text)
                done = self.run_kgate("--", "true")
                self.assertEqual(done.returncode, 69, done.stdout)
                self.assertIn("image_volumes path", done.stdout)

    def test_a_quota_refusal_is_waited_out_then_the_job_runs(self):
        done = self.run_kgate("--wait", "60", "--", "sh", "-c", "echo ran-after-quota", env={"FAKE_QUOTA": "3"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ran-after-quota", done.stdout)
        lines = [l for l in done.stdout.splitlines() if l.startswith("kgate: waiting for quota: ")]
        self.assertEqual(len(lines), 2, "once, and once more when the message changed (used 8 to 6)")
        self.assertIn("exceeded quota: jobs, requested: requests.cpu=2, used: requests.cpu=8, limited: requests.cpu=8", lines[0])
        self.assertIn("used: requests.cpu=6", lines[1])
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["cleanup"]), (0, None, True))
        self.assertGreater(rec["quota_wait_s"], 0.3)
        self.assertEqual(int((self.fake / "creates").read_text()), 4)

    def test_a_quota_that_never_frees_is_69_at_the_deadline_with_the_message(self):
        done = self.run_kgate("--wait", "2", "--", "true", env={"FAKE_QUOTA": "always"})
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertRegex(rec["reason"], r"^quota not available within 2s: exceeded quota: jobs, requested: requests.cpu=2, used: requests.cpu=\d+, limited: requests.cpu=8$")
        self.assertGreaterEqual(rec["quota_wait_s"], 1.5)
        self.assertTrue(rec["cleanup"])

    def test_a_request_above_the_namespace_limit_is_69_at_once_not_a_wait(self):
        done = self.run_kgate("--wait", "600", "--", "true", env={"FAKE_QUOTA": "impossible"})
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertRegex(rec["reason"], r"^request exceeds the namespace quota: exceeded quota: jobs, requested: limits.cpu=16,requests.cpu=2")
        self.assertEqual(int((self.fake / "creates").read_text()), 1)
        self.assertLess(rec["duration_s"], 30)

    def test_a_long_real_format_quota_message_is_parsed_whole_and_waits(self):
        text = ('Error from server (Forbidden): error when creating "STDIN": pods "kgate-1794437863-45437" is forbidden: exceeded quota: jobs-quota-qqqq, requested: '
                'limits.cpu=8,limits.memory=10Gi,requests.cpu=2,requests.ephemeral-storage=8Gi, used: limits.cpu=96,limits.memory=160Gi,requests.cpu=24,requests.ephemeral-storage=100Gi, '
                'limited: limits.cpu=96,limits.memory=160Gi,requests.cpu=24,requests.ephemeral-storage=100Gi')
        self.assertGreater(len(text[text.index("exceeded quota:"):]), 300, "the message is longer than what kgate prints")
        full = " ".join(text[text.index("exceeded quota:"):].split())
        self.assertFalse(K.quota_impossible(full))
        self.assertTrue(K.quota_impossible(full[:300]), "cut at 300 characters, the last limited value reads 1 (of 100Gi): the bug this test guards")
        done = self.run_kgate("--wait", "60", "--", "sh", "-c", "echo ran-after-the-long-wait", env={"FAKE_QUOTA": "long:2"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ran-after-the-long-wait", done.stdout)
        self.assertNotIn("request exceeds the namespace quota", done.stdout)
        shown = next(l for l in done.stdout.splitlines() if l.startswith("kgate: waiting for quota: "))
        self.assertEqual(len(shown), len("kgate: waiting for quota: ") + 300, "only what is printed is cut")
        self.assertEqual(int((self.fake / "creates").read_text()), 3)

    def test_a_forbidden_webhook_denial_that_says_exceeded_quota_is_not_a_wait(self):
        for text in ('Error from server (Forbidden): admission webhook "quota.example.com" denied the request: exceeded quota: jobs, requested: requests.cpu=1, used: requests.cpu=0, limited: requests.cpu=8',
                     'Error from server (Forbidden): pods "x" is forbidden: policy says exceeded quota: please ask ops'):
            with self.subTest(text[:60]):
                done = self.run_kgate("--wait", "600", "--", "true", env={"FAKE_CREATE_ERROR": text})
                self.assertEqual(done.returncode, 69, done.stdout)
                self.assertTrue(self.records()[-1]["reason"].startswith("could not create the pod: "))
                self.assertNotIn("waiting for quota", done.stdout)
                self.assertLess(self.records()[-1]["duration_s"], 30)
                (self.fake / "creates").unlink()

    def test_exceeded_quota_text_outside_a_forbidden_create_error_is_not_a_wait(self):
        done = self.run_kgate("--wait", "600", "--", "true", env={"FAKE_CREATE_ERROR": "error: the webhook said exceeded quota: please stop"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertTrue(self.records()[-1]["reason"].startswith("could not create the pod: "))
        self.assertEqual(int((self.fake / "creates").read_text()), 1)

    def test_kgate_cancel_while_the_job_waits_for_quota(self):
        env = {**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state), "KGATE_SSH": "",
               "KGATE_SSH_KEY": "/dev/null", **self.op_env(), "FAKE_QUOTA": "always"}
        proc = subprocess.Popen([*self.launcher(), "--wait", "300", "--", "true"], cwd=self.repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.addCleanup(lambda: (proc.poll() is None and proc.kill(), proc.wait(), proc.stdout.close()))
        for line in proc.stdout:
            if "waiting for quota" in line:
                break
        else:
            self.fail("the job never reached the quota wait")
        job_id = next(json.loads(p.read_text())["id"] for p in (self.state / "kgate" / "active").glob("*.json"))
        done = self.run_kgate("cancel", job_id)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(proc.wait(timeout=30), 143)
        rec = [r for r in self.records() if r["id"] == job_id][0]
        self.assertEqual((rec["exit"], rec["reason"], rec["cancelled"], rec["cleanup"], rec["cluster"]), (143, "cancelled by kgate cancel", True, True, "example"))
        self.assertIn(["delete", "pod/" + job_id, "--ignore-not-found", "--grace-period=0", "--wait=true"], self.kubectl_args())
        self.assertEqual(list((self.state / "kgate" / "active").glob("*.json")), [])

    def test_any_other_create_error_is_an_immediate_69(self):
        done = self.run_kgate("--wait", "600", "--", "true", env={"FAKE_CREATE_ERROR": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertTrue(rec["reason"].startswith("could not create the pod: "), rec["reason"])
        self.assertEqual(rec["quota_wait_s"], 0)
        self.assertEqual(int((self.fake / "creates").read_text()), 1)
        self.assertLess(rec["duration_s"], 30)

    def test_without_a_refusal_the_record_has_no_wait(self):
        self.run_kgate("--", "true")
        self.assertEqual(self.records()[-1]["quota_wait_s"], 0)

    def test_a_kubectl_cluster_asks_for_exactly_the_cpu_it_is_given(self):   # the 4-cpu slot is the homelab's; this adapter is unchanged
        for asked in (1, 3, 6):
            shutil.rmtree(self.fake / "podgit", True)   # the fake pod keeps its repo between runs
            self.assertEqual(self.run_kgate("--cpu", str(asked), "--", "true").returncode, 0)
            c = [c["manifest"] for c in self.kcalls() if "manifest" in c][-1]["items"][0]["spec"]["containers"][0]
            env = {e["name"]: e.get("value") for e in c["env"]}
            self.assertEqual((c["resources"]["requests"]["cpu"], env["CARGO_BUILD_JOBS"]), (str(asked), str(asked)))
            self.assertEqual(self.records()[-1]["cpu"], asked)
        shutil.rmtree(self.fake / "podgit", True)
        self.assertNotIn("raised", self.run_kgate("--cpu", "1", "--", "true").stdout)

    def test_cpu_limit_sizes_the_burst_and_the_build_jobs_not_the_request(self):
        self.profile(extra="cpu_limit = 5")
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)
        c = next(c["manifest"] for c in self.kcalls() if "manifest" in c)["items"][0]["spec"]["containers"][0]
        self.assertEqual((c["resources"]["requests"]["cpu"], c["resources"]["limits"]["cpu"]), ("2", "5"))
        env = {e["name"]: e.get("value") for e in c["env"]}
        self.assertEqual((env["GOMAXPROCS"], env["MAKEFLAGS"], env["CARGO_BUILD_JOBS"], env["RAYON_NUM_THREADS"]), ("5", "-j5", "5", "5"))
        self.assertEqual((self.records()[-1]["cpu"], self.records()[-1]["cpu_limit"]), (2, 5))

    def test_a_kubectl_pod_line_names_a_set_cpu_limit_and_never_a_priority_class(self):   # the cluster's own policy decides the class there
        self.profile(extra="cpu_limit = 5")
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("2Gi limit, 5 cpu limit\n", done.stdout)
        self.assertIsNone(self.records()[-1]["priority_class"])

    def test_KGATE_PRIORITY_CLASS_is_refused_on_a_kubectl_cluster_like_the_profile_key(self):
        done = self.run_kgate("--", "true", env={"KGATE_PRIORITY_CLASS": "kgate-main"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("KGATE_PRIORITY_CLASS is for the homelab only", self.records()[-1]["reason"])

    def test_the_record_carries_the_effective_cpu_limit_even_when_it_defaults(self):
        self.run_kgate("--", "true")
        self.assertEqual((self.records()[-1]["cpu"], self.records()[-1]["cpu_limit"]), (2, 2))

    def test_a_cpu_limit_below_the_request_is_refused(self):
        self.profile(extra="cpu_limit = 1")
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("cpu_limit (1) must be at least cpu (2)", self.records()[-1]["reason"])
        self.assertFalse(any("manifest" in c for c in self.kcalls()))

    def test_the_archive_has_no_git_entries_and_the_pod_builds_the_repo(self):
        done = self.run_kgate("--", "sh", "-c", "git rev-parse HEAD; echo KGATE_HEAD=$KGATE_HEAD")
        self.assertEqual(done.returncode, 0, done.stdout)
        import tarfile
        with tarfile.open(self.fake / "shipped.tar") as tar:
            names = tar.getnames()
        self.assertEqual([n for n in names if re.search(r"(^|/)\.git(/|$)", n)], [])
        self.assertTrue(any(n.endswith("/tracked.txt") for n in names))
        rec = self.records()[-1]
        self.assertIn("KGATE_HEAD=" + rec["head"], done.stdout)
        self.assertIn("kgate[%s]: hash ok %s" % (rec["id"], rec["tree"]), done.stdout)
        podhead = subprocess.run(["git", "--git-dir", str(self.fake / "podgit"), "rev-parse", "HEAD^{tree}"], stdout=subprocess.PIPE, text=True).stdout.strip()
        self.assertEqual(podhead, rec["tree"])
        self.assertTrue((self.repo / ".git").is_dir(), "the Mac-side repo was only set aside by the fake pod")

    def test_home_is_per_job_and_a_file_one_job_writes_there_is_gone_in_the_next(self):
        self.profile(extra='cache_pvc = "example-cache"')
        first = self.run_kgate("--", "sh", "-c", 'echo secret > "$HOME/.npmrc"; echo "HOME=$HOME"')
        self.assertEqual(first.returncode, 0, first.stdout)
        second = self.run_kgate("--", "sh", "-c", 'test ! -e "$HOME/.npmrc" && echo clean-home; echo "HOME=$HOME"')
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertIn("clean-home", second.stdout)
        ids = [r["id"] for r in self.records()[-2:]]
        homes = [next(e["value"] for e in m["manifest"]["items"][0]["spec"]["containers"][0]["env"] if e["name"] == "HOME") for m in self.kcalls() if "manifest" in m]
        self.assertEqual(homes, ["/cache/%s/home" % i for i in ids])
        env = {e["name"]: e["value"] for e in next(m for m in self.kcalls() if "manifest" in m)["manifest"]["items"][0]["spec"]["containers"][0]["env"] if "value" in e}
        self.assertTrue(all(env[k].startswith("/cache/") and not env[k].startswith("/cache/kgate-") for k in ("GOCACHE", "GOMODCACHE", "npm_config_cache", "npm_config_store_dir")), "only the caches are on the disk")

    def test_a_profile_with_cache_pvc_sends_the_claim_and_fsgroup(self):
        self.profile(extra='cache_pvc = "example-cache"')
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        pod = next(c["manifest"] for c in self.kcalls() if "manifest" in c)["items"][0]
        self.assertIn({"name": "cache", "persistentVolumeClaim": {"claimName": "example-cache"}}, pod["spec"]["volumes"])
        self.assertEqual((pod["spec"]["securityContext"]["fsGroup"], pod["spec"]["securityContext"]["fsGroupChangePolicy"]), (65532, "OnRootMismatch"))

    def test_cache_pvc_on_a_homelab_profile_is_refused_before_anything_is_created(self):
        (self.repo / "kgate.toml").write_text('image = "%s"\ncache_pvc = "example-cache"\n' % DIGEST)
        done = self.kgate("--", "true", host="fake")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("cache_pvc is for a profile with cluster", self.records()[-1]["reason"])
        self.assertFalse(any(c["kubectl"][0] == "create" for c in self.calls()))

    def test_a_job_queued_on_capacity_keeps_waiting_with_the_cache_and_does_not_fall_back(self):
        self.profile(extra='cache_pvc = "example-cache"')
        done = self.run_kgate("--wait", "60", "--", "sh", "-c", "echo ran-after-the-wait", env={"FAKE_POD": "queued"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("kgate: waiting for the pod: Unschedulable", done.stdout)
        self.assertNotIn("cache in use", done.stdout)
        self.assertEqual(int((self.fake / "creates").read_text()), 1, "the same pod throughout")
        self.assertEqual(self.records()[-1]["cache"], "pvc")

    def test_a_job_whose_claim_is_held_by_another_runs_cold_without_it(self):
        self.profile(extra='cache_pvc = "example-cache"')
        done = self.run_kgate("--wait", "60", "--", "sh", "-c", "echo ran-cold", env={"FAKE_POD": "rwop"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(done.stdout.count("cache in use by another job; running without it"), 1)
        self.assertIn("ran-cold", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["cache"], rec["exit"], rec["reason"], rec["cleanup"]), ("fallback", 0, None, True))
        creates = [c["manifest"]["items"][0] for c in self.kcalls() if "manifest" in c]
        self.assertEqual(len(creates), 2)
        vols = lambda pod: [v for v in pod["spec"]["volumes"] if v["name"] == "cache"]
        self.assertEqual(vols(creates[0]), [{"name": "cache", "persistentVolumeClaim": {"claimName": "example-cache"}}])
        self.assertEqual(vols(creates[1]), [{"name": "cache", "emptyDir": {}}])
        self.assertNotIn("fsGroup", creates[1]["spec"]["securityContext"])
        self.assertEqual(creates[0]["metadata"]["name"], creates[1]["metadata"]["name"])
        deletes = [a for a in self.kubectl_args() if a[0] == "delete" and a[1] == "pod/" + rec["id"]]
        self.assertGreaterEqual(len(deletes), 2, "deleted before the cold pod, and again at the end")

    def test_a_brief_hold_shorter_than_the_grace_keeps_the_cache(self):
        self.profile(extra='cache_pvc = "example-cache"')
        done = self.run_kgate("--wait", "60", "--", "sh", "-c", "echo ran-warm", env={"FAKE_POD": "rwop-gone"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertNotIn("cache in use", done.stdout)
        self.assertEqual(self.records()[-1]["cache"], "pvc")
        self.assertEqual(int((self.fake / "creates").read_text()), 1)

    def test_the_record_says_cache_none_without_cache_pvc_and_pvc_with_it(self):
        self.run_kgate("--", "true")
        self.assertEqual(self.records()[-1]["cache"], "none")
        self.profile(extra='cache_pvc = "example-cache"')
        self.run_kgate("--", "true")
        self.assertEqual(self.records()[-1]["cache"], "pvc")

    def test_a_missing_claim_is_69_at_once_with_a_clear_reason_and_the_pod_is_deleted(self):
        self.profile(extra='cache_pvc = "example-cache"')
        done = self.run_kgate("--wait", "600", "--", "true", env={"FAKE_POD": "noclaim"})
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertRegex(rec["reason"], r'^the cache claim example-cache does not exist in jobs \(cache_pvc in the profile\)')
        self.assertTrue(rec["cleanup"])
        self.assertLess(rec["duration_s"], 30)

    def test_it_only_ever_talks_to_the_cluster_through_the_one_kubeconfig_and_never_to_homelab(self):
        self.run_kgate("--", "true")
        self.assertTrue(self.kcalls())
        for c in (c for c in self.kcalls() if "argv" in c):
            self.assertEqual(c["argv"][:6], ["--kubeconfig", str(self.home / ".kube" / "example"), "--context", "example-ctx", "-n", "jobs"])
        self.assertEqual(self.calls(), [], "no ssh to the homelab")
        self.assertEqual(self.op_token_checks(), [], "no 1Password read")
        self.assertFalse(any("secret" in " ".join(a) for a in self.kubectl_args()), "the Role has no Secrets")

    def test_the_pod_sent_is_the_cluster_pod_and_nothing_else(self):
        self.run_kgate("--", "true")
        manifest = next(c["manifest"] for c in self.kcalls() if "manifest" in c)
        self.assertEqual([i["kind"] for i in manifest["items"]], ["Pod"])
        pod = manifest["items"][0]
        self.assertEqual(pod["metadata"]["labels"]["example.org/owner"], "team-a")
        self.assertEqual(pod["spec"]["activeDeadlineSeconds"], 7200)
        c = pod["spec"]["containers"][0]
        self.assertEqual(c["resources"]["requests"], {"cpu": "2", "memory": "1Gi", "ephemeral-storage": "5Gi"})
        self.assertEqual(c["resources"]["limits"], {"cpu": "2", "memory": "2Gi", "ephemeral-storage": "5Gi"})
        top = "/" + str(self.repo).lstrip("/").split("/")[0]
        self.assertIn({"name": "tree0", "mountPath": top}, c["volumeMounts"])
        self.assertEqual(pod["spec"]["securityContext"]["runAsUser"], 65532)

    def test_cmd_failure_is_cmds_exit_code_not_69(self):
        done = self.run_kgate("--", "sh", "-c", "echo boom; exit 3")
        self.assertEqual(done.returncode, 3, done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["ran"], rec["cleanup"]), (3, None, True, True))

    def test_out_comes_back_even_when_cmd_fails(self):
        done = self.run_kgate("--", "sh", "-c", 'echo trace > "$KGATE_OUT/trace.txt"; exit 1')
        self.assertEqual(done.returncode, 1)
        self.assertEqual((self.state / "kgate" / (self.records()[-1]["id"] + ".out") / "trace.txt").read_text(), "trace\n")

    def test_the_pod_is_deleted_and_only_the_pod(self):
        self.run_kgate("--", "true")
        rec = self.records()[-1]
        self.assertIn(["delete", "pod/" + rec["id"], "--ignore-not-found", "--grace-period=0", "--wait=true"], self.kubectl_args())

    def test_tree_hash_mismatch_is_69_and_cmd_does_not_run(self):
        done = self.run_kgate("--", "sh", "-c", "echo SHOULD-NOT-RUN", env={"FAKE_TAMPER": str(self.repo / "tracked.txt")})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertNotIn("SHOULD-NOT-RUN", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"], rec["cleanup"]), (69, False, True))
        self.assertRegex(rec["reason"], r"^tree hash differs: expected=[0-9a-f]{40} found=[0-9a-f]{40} \(CMD not run\)$")

    def test_wrong_tool_version_is_69_with_tool_expected_and_found(self):
        self.profile(tools='go = { version = "9.9.9", cmd = "echo go version go1.25.12" }')
        done = self.run_kgate("--", "sh", "-c", "echo SHOULD-NOT-RUN")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertNotIn("SHOULD-NOT-RUN", done.stdout)
        self.assertIn('tool version differs: tool=go expected=9.9.9 found="go version go1.25.12"', self.records()[-1]["reason"])

    def test_right_tool_version_passes(self):
        self.profile(tools='go = { version = "1.25.12", cmd = "echo go version go1.25.12" }')
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)

    def test_the_peak_comes_back_in_the_record(self):
        (self.fake / "cg").mkdir()
        (self.fake / "cg" / "memory.peak").write_text("4242\n")
        done = self.run_kgate("--", "true", env={"KGATE_CGROUP": str(self.fake / "cg")})
        self.assertEqual(done.returncode, 0, done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["peak_bytes"], rec["peak_source"]), (4242, "cgroup"))

    def test_cpu_and_run_time_come_back_in_the_record(self):
        (self.fake / "cg").mkdir()
        (self.fake / "cg" / "cpu.stat").write_text("usage_usec 3141592\nuser_usec 3000000\nsystem_usec 141592\n")
        done = self.run_kgate("--", "sleep", "1", env={"KGATE_CGROUP": str(self.fake / "cg")})
        self.assertEqual(done.returncode, 0, done.stdout)
        rec = self.records()[-1]
        self.assertEqual(rec["cpu_usec"], 3141592)
        self.assertTrue(1.0 <= rec["run_s"] < rec["duration_s"], rec)
        self.assertIn("pod_start_s", rec)
        self.assertNotEqual(rec["run_s"], rec["pod_start_s"], "run_s is the command alone; pod_start_s is the wait for the pod")

    def test_cpu_is_null_in_the_record_when_cpu_stat_cannot_be_read(self):
        (self.fake / "cg").mkdir()
        done = self.run_kgate("--", "true", env={"KGATE_CGROUP": str(self.fake / "cg")})
        self.assertEqual(done.returncode, 0, done.stdout)
        rec = self.records()[-1]
        self.assertIn("cpu_usec", rec)
        self.assertIsNone(rec["cpu_usec"])
        self.assertIsInstance(rec["run_s"], float)

    # --- refusals: all exit 69 before anything is created

    def refused(self, why, *args, env=None):
        done = self.run_kgate(*args, "--", "true", env=env)
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn(why, self.records()[-1]["reason"])
        self.assertFalse(any("manifest" in c for c in self.kcalls()), "nothing was created")
        return done

    def test_a_profile_with_secrets_is_refused(self):
        self.profile(secrets='TOK = "op://developer/item/password"')
        self.refused("cannot have [secrets]")
        self.assertEqual(self.op_token_checks(), [])

    def test_an_image_from_another_registry_is_refused(self):
        self.profile(image="ghcr.io/cartwmic/kgate@sha256:" + "ab" * 32)
        self.refused("must come from registry.example")

    def test_an_image_that_is_not_pinned_by_digest_is_refused(self):
        self.profile(image="registry.example/ci/runner:20261019")
        self.refused("pinned by digest")

    def test_a_root_user_is_refused(self):
        self.profile(extra='user = "0:0"')
        self.refused("non-root")

    def test_a_refused_profile_is_recorded_under_its_cluster_and_never_reaches_for_the_homelab(self):
        for what, setup, args in (("secrets", lambda: self.profile(secrets='TOK = "op://developer/item/password"'), ()),
                                  ("image", lambda: self.profile(image="ghcr.io/cartwmic/kgate@sha256:" + "ab" * 32), ()),
                                  ("unpinned", lambda: self.profile(image="registry.example/x:1"), ()),
                                  ("root", lambda: self.profile(extra='user = "0:0"'), ()),
                                  ("node", self.profile, ("--node", "n1"))):
            with self.subTest(what):
                setup()
                done = self.kgate(*args, "--", "true", host="fake")   # a homelab host is set: it must not be used
                self.assertEqual(done.returncode, 69, done.stdout)
                self.assertEqual(self.records()[-1]["cluster"], "example")
                self.assertEqual(self.calls(), [], "no ssh to the homelab")
                self.assertFalse(any("manifest" in c for c in self.kcalls()))

    def test_node_pinning_is_refused(self):
        self.refused("does not take --node", "--node", "somewhere")

    def test_a_missing_kubeconfig_is_69_and_names_the_one_time_setup(self):
        (self.home / ".kube" / "example").unlink()
        done = self.refused("kgate cluster-setup example --from-context example-ctx")
        self.assertIn("for cluster example is missing", done.stdout)
        self.assertEqual(self.kcalls(), [], "no kubectl ran")

    def test_unreachable_or_signed_out_is_69_with_the_login_hint_and_kubectls_message(self):
        for mode, msg in (("error", "error: You must be logged in to the server (Unauthorized)"), ("no", "no")):
            with self.subTest(mode):
                done = self.refused("sign in to it", env={"FAKE_CANI": mode})
                self.assertIn("context example-ctx", self.records()[-1]["reason"])
                self.assertIn(msg, self.records()[-1]["reason"])
                self.assertIn("kubectl: " + msg, done.stdout)

    def test_nothing_runs_here_when_the_cluster_is_unreachable(self):
        done = self.run_kgate("--", "sh", "-c", "echo RAN-HERE > ran-here.txt", env={"FAKE_CANI": "error"})
        self.assertEqual(done.returncode, 69)
        self.assertFalse((self.repo / "ran-here.txt").exists())

    def path_without(self, *missing):
        """A PATH directory with the tools the pod's own shell needs, minus `missing`: an image that lacks them."""
        d = self.tmp / ("bin-without-" + "-".join(missing))
        d.mkdir(exist_ok=True)
        for name in ("sh", "command", "printf", "tar", "git", "true"):
            found = shutil.which(name)
            if found and name not in missing and not (d / name).exists():
                (d / name).symlink_to(found)
        return str(d)

    def test_an_image_without_git_or_tar_is_69_with_a_clear_reason_not_a_mismatch(self):
        for tool in ("git", "tar"):
            with self.subTest(tool):
                done = self.run_kgate("--", "sh", "-c", "echo SHOULD-NOT-RUN", env={"FAKE_POD_PATH": self.path_without(tool)})
                self.assertEqual(done.returncode, 69, done.stdout)
                self.assertNotIn("SHOULD-NOT-RUN", done.stdout)
                rec = self.records()[-1]
                self.assertEqual(rec["reason"], "image lacks %s; kgate's pod side needs git, tar and sh (CMD not run)" % tool)
                self.assertNotIn("MISMATCH", done.stdout)
                self.assertFalse(rec["ran"])
                self.assertTrue(rec["cleanup"])

    def test_an_image_without_a_shell_is_69_naming_sh(self):
        done = self.run_kgate("--", "true", env={"FAKE_NO_SH": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertEqual(self.records()[-1]["reason"], "image lacks sh; kgate's pod side needs git, tar and sh (CMD not run)")
        self.assertTrue(self.records()[-1]["cleanup"])

    def test_the_tool_check_runs_before_the_unpack_so_a_missing_tool_never_reaches_the_hash(self):
        script = K.KubectlCluster(dict(KCFG)).exec_script("kgate-1-2")
        self.assertLess(script.index("command -v"), script.index("tar -xf -"))
        self.assertIn("exit 69", script)

    def test_a_pod_that_never_gets_a_node_is_69_after_wait(self):
        done = self.run_kgate("--wait", "1", "--", "true", env={"FAKE_POD": "pending"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertRegex(self.records()[-1]["reason"], r"^pod did not start within 1s: Unschedulable 0/3 nodes fit")
        self.assertTrue(self.records()[-1]["cleanup"])

    # --- records, cancel, setup

    def test_the_record_says_which_cluster_ran_it(self):
        self.run_kgate("--", "true")
        self.assertEqual(self.records()[-1]["cluster"], "example")
        (self.repo / "kgate.toml").write_text('image = "%s"\n' % DIGEST)
        self.kgate("--", "true")
        self.assertEqual(self.records()[-1]["cluster"], "homelab")

    def test_cancel_of_a_dead_kubectl_cluster_client_deletes_only_its_pod(self):
        job_id = "kgate-1700000009-999"
        corpse = subprocess.Popen(["sleep", "300"])
        start, command = K.proc_identity(corpse.pid)
        (self.state / "kgate" / "active").mkdir(parents=True)
        (self.state / "kgate" / "active" / (job_id + ".json")).write_text(json.dumps({
            "id": job_id, "job": "rw-1", "pid": corpse.pid, "start": start, "proc_cmd": command, "cwd": str(self.repo),
            "argv": ["kgate", "--", "x"], "cmd": "x", "node": None, "cluster": "example"}))
        corpse.kill()
        corpse.wait()
        done = self.run_kgate("cancel", job_id)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn(["delete", "pod/" + job_id, "--ignore-not-found", "--grace-period=0", "--wait=true"], self.kubectl_args())
        self.assertEqual(self.calls(), [], "no ssh")
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["cluster"], rec["cleanup"], rec["cancelled"]), (143, "example", True, True))

    def test_a_starting_job_ends_the_job_on_its_cluster_whose_client_is_gone(self):
        self.dead_entry("kgate-1700000009-999", "rw-1", cluster="example")
        self.dead_entry("kgate-1700000008-888", "rw-2")                       # a homelab job: not this cluster's to end
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(len([r for r in self.records() if r["id"] == "kgate-1700000009-999"]), 1, "the gone client's job has an end line")
        gone, = [r for r in self.records() if r["id"] == "kgate-1700000009-999"]
        self.assertEqual((gone["exit"], gone["cluster"], gone["cleanup"], gone["cancelled"], gone["reaped_by"]), (143, "example", True, True, self.records()[-1]["id"]))
        self.assertRegex(gone["reason"], r"^ended by kgate: its client \(pid \d+\) is gone$")
        args = self.kubectl_args()
        delete = ["delete", "pod/kgate-1700000009-999", "--ignore-not-found", "--grace-period=0", "--wait=true"]
        self.assertIn(delete, args)
        self.assertLess(args.index(delete), args.index(next(a for a in args if a[:1] == ["create"])), "ended before this job's own pod is created")
        self.assertNotIn("pod/kgate-1700000008-888", [x for a in args for x in a])
        self.assertTrue((self.active() / "kgate-1700000008-888.json").exists())
        self.assertFalse((self.active() / "kgate-1700000009-999.json").exists())

    def test_the_registry_entry_names_the_cluster_before_the_pod_exists(self):
        self.run_kgate("--", "true")
        entries = next(c["registry"] for c in self.kcalls() if "manifest" in c)
        self.assertEqual([e["cluster"] for e in entries], ["example"])

    # --- the cluster file

    def test_a_missing_cluster_file_is_69_naming_the_file_and_how_to_make_one(self):
        (self.home / ".config" / "kgate" / "clusters" / "example.toml").unlink()
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        reason = self.records()[-1]["reason"]
        self.assertIn(str(self.home / ".config" / "kgate" / "clusters" / "example.toml"), reason)
        self.assertIn("kgate cluster-setup example --from-context", reason)
        self.assertEqual(self.records()[-1]["cluster"], "example")
        self.assertEqual(self.calls(), [], "no homelab connection")
        self.assertFalse(any("manifest" in c for c in self.kcalls()))

    def test_a_missing_key_is_69_naming_the_file_and_the_key(self):
        for key in ("kind", "kubeconfig", "context", "namespace", "registries", "tree_roots", "user", "deadline_s"):
            with self.subTest(key):
                path = self.write_cluster(drop=(key,))
                done = self.run_kgate("--", "true")
                self.assertEqual(done.returncode, 69, done.stdout)
                self.assertIn("cluster file %s is missing the key %r" % (path, key), self.records()[-1]["reason"])
                self.assertFalse(any("manifest" in c for c in self.kcalls()))

    def test_an_invalid_cluster_file_is_69_with_the_key_and_the_value(self):
        for extra, bad_key in (('registries = []', "registries"), ('deadline_s = 5', "deadline_s"), ('user = "0:0"', "user"), ('kind = "ssh"', "kind"), ('tree_roots = ["/Users"]', "tree_roots")):
            with self.subTest(bad_key):
                text = self.write_cluster().read_text()
                lines = [l for l in text.splitlines() if not l.startswith(bad_key + " ")]
                (self.home / ".config" / "kgate" / "clusters" / "example.toml").write_text("\n".join([extra] + lines) + "\n")
                done = self.run_kgate("--", "true")
                self.assertEqual(done.returncode, 69, done.stdout)
                self.assertIn(bad_key, self.records()[-1]["reason"])
                self.assertIn("example.toml", self.records()[-1]["reason"])

    def test_an_unknown_key_in_the_cluster_file_is_refused(self):
        self.write_cluster()
        text = (self.home / ".config" / "kgate" / "clusters" / "example.toml").read_text()
        (self.home / ".config" / "kgate" / "clusters" / "example.toml").write_text('flavour = "x"\n' + text)
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("unknown keys: flavour", self.records()[-1]["reason"])

    def test_the_pod_labels_annotations_deadline_and_user_come_from_the_cluster_file(self):
        self.write_cluster(extra="")
        text = (self.home / ".config" / "kgate" / "clusters" / "example.toml").read_text()
        text = text.replace('deadline_s = 7200', 'deadline_s = 1800').replace('"example.org/tier\" = \"build"', '"example.org/tier" = "build"').replace("team-a", "team-b")
        text = text.replace('user = "65532:65532"', 'user = "1234:5678"')
        (self.home / ".config" / "kgate" / "clusters" / "example.toml").write_text(text)
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        pod = next(c["manifest"] for c in self.kcalls() if "manifest" in c)["items"][0]
        self.assertEqual(pod["metadata"]["labels"], {"app": "kgate", "kgate-job": self.records()[-1]["id"], "example.org/owner": "team-b", "example.org/tier": "build"})
        self.assertEqual(pod["metadata"]["annotations"], {"example.org/evict-ok": "true"})
        self.assertEqual(pod["spec"]["activeDeadlineSeconds"], 1800)
        self.assertEqual((pod["spec"]["securityContext"]["runAsUser"], pod["spec"]["securityContext"]["runAsGroup"]), (1234, 5678))

    def test_a_profile_user_overrides_the_cluster_users_default_but_not_root(self):
        self.profile(extra='user = "4321:8765"')
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)
        pod = next(c["manifest"] for c in self.kcalls() if "manifest" in c)["items"][0]
        self.assertEqual(pod["spec"]["securityContext"]["runAsUser"], 4321)

    def test_the_cluster_files_default_cache_claim_is_used_unless_the_profile_names_one(self):
        self.write_cluster(extra="")
        path = self.home / ".config" / "kgate" / "clusters" / "example.toml"
        path.write_text('cache_claim_default = "default-cache"\n' + path.read_text())
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)
        self.assertEqual(self.records()[-1]["cache"], "pvc")
        pod = next(c["manifest"] for c in self.kcalls() if "manifest" in c)["items"][0]
        self.assertIn({"name": "cache", "persistentVolumeClaim": {"claimName": "default-cache"}}, pod["spec"]["volumes"])
        self.profile(extra='cache_pvc = "own-cache"')
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)
        pod = [c["manifest"] for c in self.kcalls() if "manifest" in c][-1]["items"][0]
        self.assertIn({"name": "cache", "persistentVolumeClaim": {"claimName": "own-cache"}}, pod["spec"]["volumes"])

    def set_cache_cap(self, line):
        """A top-level cache_cap key: prepended, because write_cluster's extra lands inside the last table."""
        path = self.write_cluster()
        path.write_text(line + path.read_text())
        return path

    def test_the_cache_cap_reaches_the_pod_side_in_job_sh(self):
        self.set_cache_cap('cache_cap = "4Gi"\n')
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)
        with tarfile.open(self.fake / "shipped.tar") as tar:
            job_sh = next(tar.extractfile(m).read().decode() for m in tar.getmembers() if m.name.endswith("/job.sh"))
        self.assertIn("CACHE_CAP_KIB=4194304", job_sh)
        self.set_cache_cap("")
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)
        with tarfile.open(self.fake / "shipped.tar") as tar:
            job_sh = next(tar.extractfile(m).read().decode() for m in tar.getmembers() if m.name.endswith("/job.sh"))
        self.assertIn("CACHE_CAP_KIB=8388608", job_sh, "the 8Gi default is applied when the cluster file sets no cache_cap")

    def test_a_cache_cap_of_zero_reaches_the_pod_side_as_zero(self):
        self.set_cache_cap("cache_cap = 0\n")
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)
        with tarfile.open(self.fake / "shipped.tar") as tar:
            job_sh = next(tar.extractfile(m).read().decode() for m in tar.getmembers() if m.name.endswith("/job.sh"))
        self.assertIn("CACHE_CAP_KIB=0", job_sh)

    def test_an_invalid_cache_cap_is_refused_with_the_key_named(self):
        for line in ('cache_cap = "huge"\n', 'cache_cap = "8 Gi"\n', "cache_cap = -1\n", "cache_cap = true\n", "cache_cap = 1.5\n"):
            self.set_cache_cap(line)
            done = self.run_kgate("--", "true")
            self.assertEqual(done.returncode, 69, done.stdout)
            self.assertIn("cache_cap", self.records()[-1]["reason"])

    def test_a_cache_cap_above_the_maximum_is_refused_and_one_pib_is_accepted(self):
        for line in ('cache_cap = "16Ei"\n', 'cache_cap = "2Pi"\n', "cache_cap = %d\n" % ((1 << 50) + 1)):
            self.set_cache_cap(line)
            done = self.run_kgate("--", "true")
            self.assertEqual(done.returncode, 69, done.stdout)
            self.assertIn("cache_cap", self.records()[-1]["reason"])
        self.set_cache_cap('cache_cap = "1Pi"\n')   # exactly the maximum is accepted
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)
        with tarfile.open(self.fake / "shipped.tar") as tar:
            job_sh = next(tar.extractfile(m).read().decode() for m in tar.getmembers() if m.name.endswith("/job.sh"))
        self.assertIn("CACHE_CAP_KIB=1099511627776", job_sh)

    def test_a_cache_cap_under_one_kib_is_refused_and_one_kib_is_accepted(self):
        "A cap under 1KiB would reach the pod side as cap // 1024 == 0 KiB and silently disable the trim."
        for line in ('cache_cap = "100m"\n', 'cache_cap = "0.5"\n', 'cache_cap = "1"\n', 'cache_cap = "1023"\n', "cache_cap = 500\n"):
            self.set_cache_cap(line)
            done = self.run_kgate("--", "true")
            self.assertEqual(done.returncode, 69, done.stdout)
            self.assertIn("cache_cap", self.records()[-1]["reason"])
            self.assertIn("under 1KiB", self.records()[-1]["reason"])
        self.set_cache_cap('cache_cap = "1Ki"\n')   # exactly 1KiB is accepted
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)
        with tarfile.open(self.fake / "shipped.tar") as tar:
            job_sh = next(tar.extractfile(m).read().decode() for m in tar.getmembers() if m.name.endswith("/job.sh"))
        self.assertIn("CACHE_CAP_KIB=1", job_sh)

    def test_two_clusters_can_coexist_each_with_its_own_file_and_record(self):
        self.write_cluster(name="second")
        (self.repo / "kgate.toml").write_text(((self.repo / "kgate.toml").read_text()).replace('cluster = "example"', 'cluster = "second"'))
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)
        self.assertEqual(self.records()[-1]["cluster"], "second")

    def test_a_cluster_name_that_is_a_path_is_refused(self):
        for name in ("../etc/x", "a/b", ".hidden"):
            with self.assertRaises(K.Unavailable, msg=name):
                K.parse_profile('cluster = "%s"' % name)

    # --- cluster-setup

    def setup_env(self):
        (self.home / ".kube" / "config").write_text("x")
        return {}

    def test_cluster_setup_writes_the_one_context_a_kubelogin_context_gets_azurecli_and_mode_600(self):
        self.setup_env()
        (self.home / ".kube" / "example").unlink()
        (self.home / ".config" / "kgate" / "clusters" / "example.toml").unlink()
        done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx", "--namespace", "jobs")
        self.assertEqual(done.returncode, 0, done.stdout)
        path = self.home / ".kube" / "kgate-example"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        cfg = json.loads(path.read_text())
        self.assertEqual([c["name"] for c in cfg["contexts"]], ["example-ctx"])
        self.assertEqual(cfg["current-context"], "example-ctx")
        args = cfg["users"][0]["user"]["exec"]["args"]
        self.assertEqual(args[args.index("--login") + 1], "azurecli")
        self.assertEqual(args.count("--login"), 1)

    def test_cluster_setup_leaves_a_context_that_does_not_use_that_login_tool_alone(self):
        self.setup_env()
        (self.home / ".config" / "kgate" / "clusters" / "example.toml").unlink()   # no cluster file yet: --kubeconfig-out picks the path
        done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx", "--kubeconfig-out", str(self.home / "out-kubeconfig"), env={"FAKE_CONFIG_TOKEN": "1"})
        self.assertEqual(done.returncode, 0, done.stdout)
        cfg = json.loads((self.home / "out-kubeconfig").read_text())
        self.assertEqual(cfg["users"][0]["user"], {"token": "fake"})
        self.assertEqual(stat.S_IMODE((self.home / "out-kubeconfig").stat().st_mode), 0o600)

    def test_cluster_setup_writes_a_skeleton_that_kgate_refuses_until_it_is_filled_in(self):
        self.setup_env()
        file = self.home / ".config" / "kgate" / "clusters" / "fresh.toml"
        done = self.run_kgate("cluster-setup", "fresh", "--from-context", "example-ctx", "--namespace", "ns-1")
        self.assertEqual(done.returncode, 0, done.stdout)
        text = file.read_text()
        self.assertIn('context = "example-ctx"', text)
        self.assertIn('namespace = "ns-1"', text)
        self.assertIn('kubeconfig = "~/.kube/kgate-fresh"', text)
        self.assertIn("registries = []", text)
        (self.repo / "kgate.toml").write_text((self.repo / "kgate.toml").read_text().replace('cluster = "example"', 'cluster = "fresh"'))
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("registries", self.records()[-1]["reason"])

    def test_cluster_setup_never_overwrites_an_existing_cluster_file(self):
        self.setup_env()
        file = self.home / ".config" / "kgate" / "clusters" / "example.toml"
        before = file.read_text()
        (self.home / ".kube" / "example").unlink()
        done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(file.read_text(), before)
        self.assertIn("already exists", done.stdout)

    def test_cluster_setup_without_the_context_is_69_and_writes_nothing(self):
        self.setup_env()
        (self.home / ".kube" / "example").unlink()
        (self.home / ".config" / "kgate" / "clusters" / "example.toml").unlink()
        done = self.run_kgate("cluster-setup", "example", "--from-context", "nope", "--kubeconfig-out", str(self.home / "out-kubeconfig"), env={"FAKE_NO_CONTEXT": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertFalse((self.home / "out-kubeconfig").exists())

    def test_cluster_setup_writes_the_kubeconfig_the_cluster_file_names_and_the_job_then_passes_the_reachability_check(self):
        self.setup_env()
        (self.home / ".kube" / "example").unlink()
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        hint = self.records()[-1]["reason"]
        self.assertIn("kgate cluster-setup example --from-context example-ctx", hint)
        done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx")   # the hint, as typed
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertTrue((self.home / ".kube" / "example").exists(), "written where the cluster file says")
        self.assertFalse((self.home / ".kube" / "kgate-example").exists())
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_a_kubeconfig_out_that_differs_from_the_cluster_file_is_refused(self):
        self.setup_env()
        (self.home / ".kube" / "example").unlink()
        done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx", "--kubeconfig-out", str(self.home / ".kube" / "elsewhere"))
        self.assertEqual(done.returncode, 64, done.stdout)
        self.assertIn("names kubeconfig", done.stdout)
        self.assertEqual(list((self.home / ".kube").glob("*")), [self.home / ".kube" / "config"])
        done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx", "--kubeconfig-out", "~/.kube/example")   # the same path is fine
        self.assertEqual(done.returncode, 0, done.stdout)

    def test_cluster_setup_does_not_replace_a_kubeconfig_kgate_did_not_write(self):
        self.setup_env()
        target = self.home / ".kube" / "example"
        target.write_text('{"contexts": [{"name": "mine"}, {"name": "other"}], "users": []}')
        before = target.read_text()
        done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx")
        self.assertEqual(done.returncode, 64, done.stdout)
        self.assertIn("was not written by kgate", done.stdout)
        self.assertEqual(target.read_text(), before)

    def test_cluster_setup_replaces_its_own_marked_one_context_file_and_not_a_marked_file_for_another_cluster(self):
        self.setup_env()
        target = self.home / ".kube" / "example"
        target.unlink()
        self.assertEqual(self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx").returncode, 0)
        cfg = json.loads(target.read_text())
        self.assertEqual(cfg["preferences"]["extensions"], [{"name": "kgate", "extension": {"cluster": "example"}}])
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        again = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx")   # a re-run refreshes it
        self.assertEqual(again.returncode, 0, again.stdout)
        self.write_cluster(name="second")
        done = self.run_kgate("cluster-setup", "second", "--from-context", "example-ctx")   # same kubeconfig, marked for "example"
        self.assertEqual(done.returncode, 64, done.stdout)

    def test_cluster_setup_never_writes_the_users_own_kubeconfig(self):
        self.setup_env()
        own = self.home / ".kube" / "config"
        before = own.read_text()
        (self.home / ".config" / "kgate" / "clusters" / "example.toml").unlink()
        for target in (str(own), "~/.kube/config", str(self.home / ".kube" / ".." / ".kube" / "config")):
            done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx", "--kubeconfig-out", target)
            self.assertEqual(done.returncode, 64, (target, done.stdout))
            self.assertIn("your own kubeconfig", done.stdout)
        self.assertEqual(own.read_text(), before)
        link = self.home / ".kube" / "link"
        link.symlink_to(own)
        done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx", "--kubeconfig-out", str(link))
        self.assertEqual(done.returncode, 64, done.stdout)
        self.assertEqual(own.read_text(), before)

    def test_the_skeleton_is_mode_600_and_escapes_quotes_in_the_values(self):
        self.setup_env()
        (self.home / ".config" / "kgate" / "clusters" / "example.toml").unlink()
        (self.home / ".kube" / "example").unlink()
        done = self.run_kgate("cluster-setup", "fresh", "--from-context", "example-ctx", "--namespace", 'we"ird\\ns')
        self.assertEqual(done.returncode, 0, done.stdout)
        file = self.home / ".config" / "kgate" / "clusters" / "fresh.toml"
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
        import tomllib
        self.assertEqual(tomllib.loads(file.read_text())["namespace"], 'we"ird\\ns')

    def test_pod_labels_may_not_set_kgates_own_labels(self):
        for label in ("app", "kgate-job"):
            with self.subTest(label):
                path = self.write_cluster()
                path.write_text(path.read_text().replace("[pod_labels]", '[pod_labels]\n"%s" = "x"' % label))
                done = self.run_kgate("--", "true")
                self.assertEqual(done.returncode, 69, done.stdout)
                self.assertIn("pod_labels may not set kgate's own labels: %s" % label, self.records()[-1]["reason"])
                self.assertFalse(any("manifest" in c for c in self.kcalls()))

    def test_a_different_context_or_namespace_than_the_cluster_files_is_refused_and_the_working_kubeconfig_is_left_alone(self):
        self.setup_env()
        target = self.home / ".kube" / "example"
        target.unlink()
        self.assertEqual(self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx").returncode, 0)
        working = target.read_text()
        for args, key, given in ((("--from-context", "other-ctx"), "context", "other-ctx"), (("--from-context", "example-ctx", "--namespace", "elsewhere"), "namespace", "elsewhere")):
            done = self.run_kgate("cluster-setup", "example", *args)
            self.assertEqual(done.returncode, 64, done.stdout)
            self.assertIn("example.toml sets %s = " % key, done.stdout)
            self.assertIn(repr(given), done.stdout)
            self.assertEqual(target.read_text(), working, "the working kubeconfig is untouched")
        done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx", "--namespace", "jobs")   # the same values are fine
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.run_kgate("--", "true").returncode, 0)

    def test_a_cluster_file_without_context_or_namespace_is_not_a_base_for_cluster_setup(self):
        self.setup_env()
        for key in ("context", "namespace"):
            self.write_cluster(drop=(key,))
            done = self.run_kgate("cluster-setup", "example", "--from-context", "example-ctx")
            self.assertEqual(done.returncode, 64, done.stdout)
            self.assertIn("has no `%s` key" % key, done.stdout)

    def test_pod_labels_of_the_wrong_type_is_the_file_and_key_error_not_a_crash(self):
        path = self.write_cluster()
        text = path.read_text().replace("[pod_labels]", "[pod_labels_gone]")
        path.write_text("pod_labels = 5\n" + text.replace("[pod_labels_gone]\n\"example.org/owner\" = \"team-a\"\n\"example.org/tier\" = \"build\"\n", ""))
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        reason = self.records()[-1]["reason"]
        self.assertIn("pod_labels must be a table of strings", reason)
        self.assertIn("example.toml", reason)
        self.assertNotIn("TypeError", done.stdout)

    def test_cluster_setup_needs_a_name_and_a_context_and_refuses_homelab(self):
        for args in ((), ("example",), ("homelab", "--from-context", "x"), ("../x", "--from-context", "x")):
            done = self.run_kgate("cluster-setup", *args)
            self.assertEqual(done.returncode, 64, (args, done.stdout))

    # -- the cluster takes the pod away (an eviction): rerun once, and only on evidence

    def pods_created(self):
        return [c["manifest"]["items"][0] for c in self.kcalls() if "manifest" in c]

    def steps(self):
        """The pod creates and pod deletes the client sent, in order."""
        out = []
        for c in self.kcalls():
            if "manifest" in c:
                out.append(("create", c["manifest"]["items"][0]["metadata"]["name"]))
            elif "argv" in c and c["argv"][6:7] == ["delete"] and c["argv"][7].startswith("pod/"):
                out.append(("delete", c["argv"][7][4:]))
        return out

    def lose(self, spec, *args, env=None, cmd=('echo ran-attempt; echo result > "$KGATE_OUT/result.txt"',)):
        (self.fake / "execs").unlink(missing_ok=True)
        return self.run_kgate(*args, "--", "sh", "-c", *cmd, env={"FAKE_LOST": spec, **(env or {})})

    def check_rerun(self, kind, why):
        done = self.lose("1:" + kind)
        self.assertEqual(done.returncode, 0, done.stdout)
        rec = self.records()[-1]
        pods = [p for p in self.pods_created() if p["metadata"]["labels"]["kgate-job"] == rec["id"]]
        self.assertEqual([p["metadata"]["name"] for p in pods], [rec["id"], rec["id"] + "-r2"], "a new pod name in the same job")
        self.assertEqual(self.steps()[-4:], [("create", rec["id"]), ("delete", rec["id"]), ("create", rec["id"] + "-r2"), ("delete", rec["id"] + "-r2")],
                         "the old pod is deleted before the new one is created, and the new one is deleted at the end")
        same = json.loads(json.dumps(pods[1]))
        same["metadata"]["name"], same["spec"]["activeDeadlineSeconds"] = pods[0]["metadata"]["name"], pods[0]["spec"]["activeDeadlineSeconds"]
        self.assertEqual(same, pods[0], "the same tree, profile and CMD: only the name and what is left of the deadline differ")
        self.assertIn("kgate: pod %s was evicted by the cluster (%s); rerunning once\n" % (rec["id"], why), done.stdout)
        self.assertEqual(done.stdout.count("rerunning once"), 1)
        self.assertEqual(done.stdout.splitlines().count("ran-attempt"), 1, "CMD ran in the second pod only")
        self.assertEqual((rec["exit"], rec["reason"], rec["ran"], rec["cleanup"], rec["attempts"]), (0, None, True, True, 2))
        self.assertEqual(rec["evicted"], [{"attempt": 1, "pod": rec["id"], "reason": why}], "the retry is in the record")
        self.assertEqual((self.state / "kgate" / (rec["id"] + ".out") / "result.txt").read_text(), "result\n")
        self.assertEqual(rec["out_files"], 1)

    def test_a_pod_the_autoscaler_evicted_is_rerun_once_and_the_job_passes(self):
        self.check_rerun("event", "Evicted pod: Underutilized")

    def test_a_pod_the_taint_manager_evicted_is_rerun(self):
        self.check_rerun("taint", "TaintManagerEviction: Marking for deletion Pod jobs/x")

    def test_a_pod_left_behind_as_failed_evicted_is_rerun(self):
        self.check_rerun("status", "Evicted: The node was low on resource: memory.")

    def test_a_pod_with_a_disruption_target_condition_is_rerun(self):
        self.check_rerun("disruption", "DeletionByTaintManager: Taint manager: deleting due to NoExecute taint")

    def test_two_evictions_are_69_with_both_reasons_and_no_third_pod(self):
        done = self.lose("2:event,taint")
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertEqual(rec["reason"], "lost the pod twice: pod %s was evicted by the cluster (Evicted pod: Underutilized), the job was rerun once as pod %s-r2, "
                                        "which was evicted too (TaintManagerEviction: Marking for deletion Pod jobs/x); not rerun again" % (rec["id"], rec["id"]))
        self.assertEqual([e["pod"] for e in rec["evicted"]], [rec["id"], rec["id"] + "-r2"])
        self.assertEqual((rec["attempts"], rec["cleanup"], rec["ran"]), (2, True, True))
        self.assertEqual([s for s in self.steps() if s[0] == "create"], [("create", rec["id"]), ("create", rec["id"] + "-r2")])
        self.assertEqual(self.steps()[-1], ("delete", rec["id"] + "-r2"), "nothing is left behind")
        self.assertEqual(done.stdout.count("rerunning once"), 1)

    def test_a_lost_pod_with_no_sign_of_an_eviction_is_69_and_not_rerun(self):
        for kind in ("none", "other", "deadline"):   # no event / an unrelated event / the pod's own deadline ended it
            with self.subTest(kind):
                done = self.lose("1:" + kind)
                self.assertEqual(done.returncode, 69, done.stdout)
                rec = self.records()[-1]
                self.assertTrue(rec["reason"].startswith("lost the pod before CMD finished (kubectl exit 0); the result is unknown and the job is not rerun"), rec["reason"])   # the end reason follows it
                self.assertNotIn("rerunning", done.stdout)
                self.assertEqual([p["metadata"]["name"] for p in self.pods_created() if p["metadata"]["labels"]["kgate-job"] == rec["id"]], [rec["id"]])
                self.assertNotIn("evicted", rec)
                self.assertEqual((rec["attempts"], rec["ran"], rec["cleanup"]), (1, True, True))

    def test_a_taint_manager_cancel_event_is_not_an_eviction(self):
        # Upstream uses reason TaintManagerEviction for "Cancelling deletion of Pod ..." too: the taint cleared and the pod was not deleted.
        for kind in ("cancel", "running-cancel", "running-evicted"):   # pod gone / pod still Running / a Running pod with a stray Evicted event
            with self.subTest(kind):
                done = self.lose("1:" + kind)
                self.assertEqual(done.returncode, 69, done.stdout)
                rec = self.records()[-1]
                self.assertTrue(rec["reason"].startswith("lost the pod before CMD finished (kubectl exit 0); the result is unknown and the job is not rerun"), rec["reason"])   # the end reason follows it
                self.assertNotIn("rerunning", done.stdout)
                self.assertNotIn("evicted", rec)
                self.assertEqual((rec["attempts"], rec["ran"]), (1, True))
                self.assertEqual(self.steps()[-2:], [("create", rec["id"]), ("delete", rec["id"])], "one pod; the only delete is the final cleanup, not a rerun's")
                self.assertEqual(len([p for p in self.pods_created() if p["metadata"]["labels"]["kgate-job"] == rec["id"]]), 1, "CMD was not started again")
                if kind != "cancel":   # a pod that is Running is trusted over the events: they are not even read
                    self.assertNotIn(["get", "events", "--field-selector", "involvedObject.kind=Pod,involvedObject.name=" + rec["id"], "-o", "json"], self.kubectl_args())

    def test_a_job_that_is_not_evicted_has_one_attempt_and_asks_nothing_about_evictions(self):
        done = self.run_kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        rec = self.records()[-1]
        self.assertEqual(rec["attempts"], 1)
        self.assertNotIn("evicted", rec)
        self.assertFalse([a for a in self.kubectl_args() if a[:2] == ["get", "events"]])

    def test_only_an_explicit_list_of_reasons_is_an_eviction(self):
        for reason in ("DisruptionBlocked", "FailedScheduling", "Nominated", "DisruptionTerminating", "Killing"):   # the node autoscaler says a disruption did NOT happen, or no pod went
            with self.subTest(reason):
                done = self.lose("1:reason=" + reason)
                self.assertEqual(done.returncode, 69, done.stdout)
                rec = self.records()[-1]
                self.assertTrue(rec["reason"].startswith("lost the pod before CMD finished (kubectl exit 0); the result is unknown and the job is not rerun"), rec["reason"])   # the end reason follows it
                self.assertNotIn("rerunning", done.stdout)
                self.assertNotIn("evicted", rec)
                self.assertEqual([s for s in self.steps() if s[0] == "create"][-1:], [("create", rec["id"])])
        self.assertEqual(K.EVICTION_REASONS, {"Evicted", "TaintManagerEviction", "Preempted", "Disrupted"})

    def test_each_allowed_reason_is_rerun(self):
        for reason in sorted(K.EVICTION_REASONS):
            with self.subTest(reason):
                shutil.rmtree(self.fake / "podgit", ignore_errors=True)   # the fake pod's tree from the last job
                done = self.lose("1:reason=" + reason)
                self.assertEqual(done.returncode, 0, done.stdout)
                rec = self.records()[-1]
                self.assertEqual(rec["attempts"], 2)
                self.assertEqual(rec["evicted"], [{"attempt": 1, "pod": rec["id"], "reason": reason + (": Marking for deletion Pod jobs/x" if reason == "TaintManagerEviction" else ": a message")}])

    def test_a_failed_events_read_means_no_rerun(self):
        done = self.lose("1:event", env={"FAKE_EVENTS_FAIL": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertTrue(rec["reason"].startswith("lost the pod before CMD finished (kubectl exit 0); the result is unknown and the job is not rerun"), rec["reason"])   # the end reason follows it
        self.assertIn(["get", "events", "--field-selector", "involvedObject.kind=Pod,involvedObject.name=" + rec["id"], "-o", "json"], self.kubectl_args())
        self.assertNotIn("evicted", rec)
        self.assertEqual([s for s in self.steps() if s[0] == "create"], [("create", rec["id"])])

    def test_the_rerun_pod_waits_for_quota_like_any_pod(self):
        done = self.lose("1:event", "--wait", "60", env={"FAKE_QUOTA_ON_CREATE": "2"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("exceeded quota", done.stdout)
        rec = self.records()[-1]
        self.assertEqual(rec["attempts"], 2)
        self.assertEqual(int((self.fake / "creates").read_text()), 3, "the first pod, the refused create of the second, its retry")

    def test_the_rerun_pod_falls_back_to_no_cache_and_the_record_names_that_pod_cache(self):
        self.profile(extra='cache_pvc = "example-cache"')
        done = self.lose("1:event", "--wait", "60", env={"FAKE_POD": "rwop-r2"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(done.stdout.count("cache in use by another job; running without it"), 1)
        rec = self.records()[-1]
        self.assertEqual((rec["attempts"], rec["cache"]), (2, "fallback"))
        vols = lambda pod: [v for v in pod["spec"]["volumes"] if v["name"] == "cache"]
        first, second, third = self.pods_created()
        self.assertEqual(vols(first), [{"name": "cache", "persistentVolumeClaim": {"claimName": "example-cache"}}])
        self.assertEqual(vols(second), [{"name": "cache", "persistentVolumeClaim": {"claimName": "example-cache"}}])
        self.assertEqual(vols(third), [{"name": "cache", "emptyDir": {}}])
        self.assertEqual([p["metadata"]["name"] for p in (second, third)], [rec["id"] + "-r2"] * 2)

    def test_the_record_says_pvc_when_the_first_pod_fell_back_and_the_rerun_pod_got_the_claim(self):
        self.profile(extra='cache_pvc = "example-cache"')
        done = self.lose("1:event", "--wait", "60", env={"FAKE_POD": "rwop-r1"})   # the claim is busy for the first pod only
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(done.stdout.count("cache in use by another job; running without it"), 1)
        rec = self.records()[-1]
        self.assertEqual((rec["attempts"], rec["cache"]), (2, "pvc"))
        vols = lambda pod: [v for v in pod["spec"]["volumes"] if v["name"] == "cache"]
        self.assertEqual([vols(p) for p in self.pods_created()][-1], [{"name": "cache", "persistentVolumeClaim": {"claimName": "example-cache"}}])

    def test_the_wait_deadline_covers_the_retry_and_is_not_reset(self):
        done = self.lose("1:event", "--wait", "1", env={"FAKE_LOST_DELAY": "2"})
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertEqual(rec["reason"], "pod %s was evicted by the cluster (Evicted pod: Underutilized); not rerun: the job's --wait of 1s has passed" % rec["id"])
        self.assertEqual(rec["evicted"], [{"attempt": 1, "pod": rec["id"], "reason": "Evicted pod: Underutilized"}])
        self.assertEqual((rec["attempts"], rec["cleanup"]), (1, True))
        self.assertEqual([s for s in self.steps() if s[0] == "create"], [("create", rec["id"])])

    def test_the_pod_deadline_of_the_rerun_is_what_is_left_of_the_jobs(self):
        self.write_cluster(deadline=120)
        done = self.lose("1:event", env={"FAKE_LOST_DELAY": "1"})
        self.assertEqual(done.returncode, 0, done.stdout)
        first, second = self.pods_created()
        self.assertEqual(first["spec"]["activeDeadlineSeconds"], 120)
        self.assertTrue(100 <= second["spec"]["activeDeadlineSeconds"] <= 119, second["spec"]["activeDeadlineSeconds"])

    def test_no_pod_deadline_left_means_no_rerun(self):
        import argparse
        with tempfile.TemporaryDirectory() as state, mock.patch.dict(os.environ, {"XDG_STATE_HOME": state}):
            job = K.Job(argparse.Namespace(command=["true"], wait=3600, sched_wait=600))
            self.addCleanup(job.log.close)
            sent = []
            job.cluster = type("C", (), {"kind": "kubectl", "run": lambda self, kargs, stdin=b"": sent.append(kargs)})()
            job.kcfg, job.rec["attempts"], job.pod_t0 = {"deadline_s": 60}, 1, time.time() - 61
            with self.assertRaises(K.Unavailable) as caught:
                job.rerun("Evicted pod: Underutilized", None)
            self.assertEqual(str(caught.exception), "pod %s was evicted by the cluster (Evicted pod: Underutilized); not rerun: the pod deadline of 60s has passed" % job.id)
            self.assertEqual(sent, [], "nothing was deleted or created")
            self.assertEqual(job.pod, job.id)

    def test_the_sql_password_is_masked_on_the_rerun_and_is_the_same_for_both_pods(self):
        self.mssql_profile()
        done = self.lose("1:event", cmd=('echo "host=$MSSQL_HOST pw=$MSSQL_SA_PASSWORD"',))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("rerunning once", done.stdout)
        self.assertIn("host=localhost pw=***", done.stdout)
        first, second = self.pods_created()
        pws = [{e["name"]: e["value"] for e in p["spec"]["initContainers"][0]["env"]}["MSSQL_SA_PASSWORD"] for p in (first, second)]
        self.assertEqual(pws[0], pws[1])
        self.assertRegex(pws[0], r"^Aa1_[0-9a-f]{32}$")
        self.assert_password_nowhere(pws[0], done)
        self.assertEqual(self.records()[-1]["services"], ["mssql"])
        execs = [a for a in self.kubectl_args() if a[0] == "exec" and "-i" in a]
        self.assertEqual([a[1:5] for a in execs], [["-i", self.records()[-1]["id"], "-c", "job"], ["-i", self.records()[-1]["id"] + "-r2", "-c", "job"]])

    def test_the_sql_password_is_masked_in_the_double_eviction_reason_too(self):
        self.mssql_profile()
        done = self.lose("2:event", cmd=("true",))
        self.assertEqual(done.returncode, 69, done.stdout)
        pw = self.pods_created()[0]["spec"]["initContainers"][0]["env"][1]["value"]
        self.assert_password_nowhere(pw, done)

    def test_cancel_of_a_dead_client_deletes_the_pod_it_was_on_not_the_first_one(self):
        corpse = subprocess.Popen(["sleep", "300"])
        job_id = "kgate-1700000003-333"
        start, command = K.proc_identity(corpse.pid)
        active = self.state / "kgate" / "active"
        active.mkdir(parents=True, exist_ok=True)
        (active / (job_id + ".json")).write_text(json.dumps({"id": job_id, "job": None, "pid": corpse.pid, "start": start, "proc_cmd": command, "cwd": str(self.repo),
                                                              "argv": ["kgate", "--", "sleep"], "cmd": "sleep 300", "node": "n", "cluster": "example", "pod": job_id + "-r2"}))
        corpse.kill()
        corpse.wait()
        done = self.run_kgate("cancel", job_id)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn(["delete", "pod/" + job_id + "-r2", "--ignore-not-found", "--grace-period=0", "--wait=true"], self.kubectl_args())
        self.assertIn(["get", "pod", job_id + "-r2", "--ignore-not-found", "-o", "jsonpath={.metadata.labels.app}"], self.kubectl_args())
        self.assertEqual((self.records()[-1]["id"], self.records()[-1]["exit"], self.records()[-1]["cleanup"]), (job_id, 143, True))


# ---------------------------------------------------------------- a client that gives up on a pod still deletes it (dotfiles#473)

ORPHAN_LAUNCH = ("import importlib.machinery, importlib.util, sys\n"
                 "loader = importlib.machinery.SourceFileLoader('kg', sys.argv[1])\n"
                 "K = importlib.util.module_from_spec(importlib.util.spec_from_loader('kg', loader))\n"
                 "loader.exec_module(K)\n"
                 "K.CLEANUP_FIRST_DELAY, K.CLEANUP_MAX_DELAY, K.CLEANUP_RETRY_S, K.CLEANUP_ATTEMPT_S = 0.05, 0.1, 3, 1\n"   # the delete retry waits, shortened
                 "K.POLL_RETRY_S = 1\n"                                                                                     # and the retry of a failed read of the pod
                 "sys.exit(K.main(sys.argv[2:]))\n")


class GiveUpDeletesThePod:
    """Both give-up paths of the client (CMD's own non-zero exit, and exit 69 "lost the pod while waiting for it") against a cluster whose API server times out
    on the delete, as etcd did on 2026-11-16: the pod must end up deleted, and the record says whether the delete was confirmed. Run for both cluster kinds."""

    def launcher(self):
        return stub_launcher(self.tmp, "orphan_launch.py", ORPHAN_LAUNCH)

    def deleted(self):
        path = self.fake / "deleted-pods"
        return path.read_text().split() if path.exists() else []

    def tries(self):
        path = self.fake / "delete-tries"
        return int(path.read_text()) if path.exists() else 0

    def test_cmd_fails_and_the_first_deletes_time_out(self):
        done = self.job("--", "sh", "-c", "exit 1", env={"FAKE_DELETE_FAIL": "2"})
        self.assertEqual(done.returncode, 1, done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"]), (1, None))
        self.assertIn(rec["id"], self.deleted(), "the pod was deleted")
        self.assertEqual((rec["cleanup"], rec["cleanup_attempts"]), (True, 3))
        self.assertNotIn("cleanup not confirmed", done.stdout)

    def test_the_pod_is_lost_while_waiting_and_the_first_delete_times_out(self):
        done = self.job("--", "true", env={"FAKE_GET_FAIL": "1", "FAKE_DELETE_FAIL": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"]), (69, False))
        self.assertEqual(rec["reason"], "lost the pod while waiting for it: Error from server: etcdserver: request timed out")
        self.assertIn(rec["id"], self.deleted(), "the pod was deleted")
        self.assertEqual((rec["cleanup"], rec["cleanup_attempts"]), (True, 2))

    def test_a_delete_that_hangs_is_cut_off_and_tried_again(self):
        done = self.job("--", "sh", "-c", "exit 1", env={"FAKE_DELETE_HANG": "1"})
        self.assertEqual(done.returncode, 1, done.stdout)
        rec = self.records()[-1]
        self.assertIn(rec["id"], self.deleted(), "the pod was deleted")
        self.assertEqual((rec["cleanup"], rec["cleanup_attempts"]), (True, 2))

    def test_a_delete_that_never_succeeds_stops_trying_and_says_so(self):
        done = self.job("--", "sh", "-c", "exit 3", env={"FAKE_DELETE_FAIL": "always"})
        self.assertEqual(done.returncode, 3, done.stdout)    # the exit code is still CMD's
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["cleanup"]), (3, False))
        self.assertGreater(rec.get("cleanup_attempts", 0), 1, "it tried again")
        self.assertEqual(self.deleted(), [])
        self.assertIn("cleanup not confirmed for %s: Error from server: etcdserver: request timed out" % rec["id"], done.stdout)

    def test_nothing_was_created_so_one_attempt_and_no_wait(self):
        done = self.job("--", "true", env=self.unreachable_env())
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertNotIn("cleanup_attempts", rec)
        self.assertLessEqual(self.tries(), 1)


class GiveUpHomelab(GiveUpDeletesThePod, unittest.TestCase):
    for _name in ("kgate", "records", "calls", "op_env", "profile", "setUp"):
        locals()[_name] = getattr(Black, _name)

    def job(self, *args, env=None):
        return self.kgate(*args, env=env)

    def unreachable_env(self):
        return {"FAKE_DELETE_FAIL": "always", "KGATE_SSH": "fake-unreachable"}


class GiveUpKubectl(GiveUpDeletesThePod, unittest.TestCase):
    for _name in ("kgate", "records", "calls", "op_token_checks", "op_env"):
        locals()[_name] = getattr(Black, _name)
    for _name in ("setUp", "write_cluster", "profile", "run_kgate", "kcalls"):
        locals()[_name] = getattr(KubectlBlack, _name)

    def job(self, *args, env=None):
        return self.run_kgate(*args, env=env)

    def unreachable_env(self):
        return {"FAKE_DELETE_FAIL": "always", "FAKE_CANI": "no"}


# ---------------------------------------------------------------- a job waits in a local queue while the cluster is full (dotfiles: kgate queue)

class BrakeHomelab(unittest.TestCase):
    """The coordinator's pause: while `$COORDINATOR_STATE_DIR/brake/` holds any file, no pod is made. The job names every reason, looks again on a short poll, and goes on when the
    folder is empty or missing. It does not know what a reason is: the tests use made-up names."""
    for _name in ("kgate", "kgate_popen", "launcher", "records", "calls", "op_env", "profile", "setUp"):
        locals()[_name] = getattr(Black, _name)

    def brake(self, **reasons):
        folder = self.tmp / "coordinator" / "brake"
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in reasons.items():
            (folder / name).write_text(text + "\n")
        return folder

    def env(self):
        return {"COORDINATOR_STATE_DIR": str(self.tmp / "coordinator"), "KGATE_BRAKE_POLL_S": "0.2"}

    def creates(self):
        return sum(1 for c in self.calls() if "manifest" in c)

    def read_until(self, proc, text):
        seen = ""
        for line in proc.stdout:
            seen += line
            if text in line:
                break
        self.assertIn(text, seen)
        return seen

    def start(self, *args, env=None, host="fake"):
        proc = self.kgate_popen(*args, env=env, host=host)
        self.addCleanup(lambda: (proc.poll() is None and os.killpg(proc.pid, 9), proc.wait(), proc.stdout.close()))
        return proc

    def test_a_job_waits_while_the_folder_holds_a_file_then_runs_when_it_is_empty(self):
        folder = self.brake(lag="2026-11-22T10:00:00.000Z Michael's oldest unanswered message has waited 90 s (limit 60 s)")
        proc = self.start("--", "sh", "-c", "echo ran-after-the-pause", env=self.env())
        seen = self.read_until(proc, "paused: ")
        time.sleep(1)
        self.assertIsNone(proc.poll())
        self.assertEqual(self.creates(), 0, "no pod while the pause is on")
        self.assertEqual(self.calls(), [], "not even a look at the cluster")
        (folder / "lag").unlink()
        out, _ = proc.communicate(timeout=60)
        seen += out
        self.assertEqual(proc.returncode, 0, seen)
        self.assertIn("lag: Michael's oldest unanswered message has waited 90 s (limit 60 s)", seen)
        self.assertNotIn("2026-11-22T10:00", seen, "the words are shown without the file's time")
        self.assertIn("the pause lifted after", seen)
        self.assertIn("ran-after-the-pause", seen)
        self.assertEqual(self.creates(), 1)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"]), (0, True))
        self.assertGreater(rec["brake_wait_s"], 0.5)

    def test_a_pause_longer_than_wait_does_not_use_up_the_jobs_wait(self):
        # --wait 3, the pause holds for 5 s, and the pod still needs a second look to be running: without the pause time added to --wait the job
        # would make its pod and then fail "pod did not start within 3s" the moment the pause lifts.
        folder = self.brake(lag="2026-11-22T10:00:00.000Z the inbox is late")
        proc = self.start("--wait", "3", "--", "sh", "-c", "echo ran-after-a-long-pause", env={**self.env(), "FAKE_POD": "slow"})
        seen = self.read_until(proc, "paused: ")
        time.sleep(5)
        self.assertIsNone(proc.poll())
        (folder / "lag").unlink()
        out, _ = proc.communicate(timeout=60)
        seen += out
        self.assertEqual(proc.returncode, 0, seen)
        self.assertNotIn("did not start", seen)
        self.assertIn("ran-after-a-long-pause", seen)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"]), (0, True))
        self.assertGreater(rec["brake_wait_s"], 4.5)

    def test_every_reason_is_named_on_one_line_and_the_job_waits_for_the_last_to_go(self):
        folder = self.brake(lag="2026-11-22T10:00:00Z the inbox is late", cpu="2026-11-22T10:00:01Z the host is at 95 percent cpu")
        proc = self.start("--", "true", env=self.env())
        seen = self.read_until(proc, "paused: ")
        line = next(l for l in seen.splitlines() if "paused: " in l)
        self.assertIn("cpu: the host is at 95 percent cpu; lag: the inbox is late", line)
        (folder / "lag").unlink()
        time.sleep(1)
        self.assertIsNone(proc.poll(), "one reason left: still paused")
        self.assertEqual(self.creates(), 0)
        (folder / "cpu").unlink()
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, seen + out)
        self.assertEqual(self.creates(), 1)

    def test_a_reason_no_one_has_heard_of_holds_the_job_and_a_new_reason_is_named_again(self):
        folder = self.brake(**{"something-new": "2026-11-22T10:00:00Z a trigger kgate has never seen"})
        proc = self.start("--", "true", env=self.env())
        seen = self.read_until(proc, "something-new: a trigger kgate has never seen")
        self.brake(**{"another-one": "2026-11-22T10:00:05Z a second trigger"})
        seen += self.read_until(proc, "another-one: a second trigger")
        for name in ("something-new", "another-one"):
            (folder / name).unlink()
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, seen + out)

    def test_an_empty_or_missing_folder_does_not_hold_the_job(self):
        self.assertEqual(self.kgate("--", "true", env=self.env()).returncode, 0)   # no folder
        self.brake()
        folder = self.tmp / "coordinator" / "brake"
        (folder / ".hidden").write_text("not a reason\n")
        (folder / "sub").mkdir()
        done = self.kgate("--", "true", env=self.env())
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertNotIn("paused", done.stdout)
        self.assertNotIn("brake_wait_s", self.records()[-1])

    def test_the_state_dir_defaults_to_the_coordinators_folder_under_home(self):
        folder = self.home / ".local" / "share" / "coordinator" / "brake"
        folder.mkdir(parents=True)
        (folder / "lag").write_text("2026-11-22T10:00:00Z held\n")
        env = {"COORDINATOR_STATE_DIR": "", "KGATE_BRAKE_POLL_S": "0.2"}
        proc = self.start("--", "true", env=env)
        self.read_until(proc, "lag: held")
        (folder / "lag").unlink()
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, out)

    def test_the_default_folder_is_the_profiles_own_coordinator_state(self):
        """With COORDINATOR_STATE_DIR unset, each profile reads its own coordinator's folder: personal `~/.local/share/coordinator`, work `~/.local/share/coordinator-work`
        (the work coordinator's state, README.md "work profile"). The script is rendered for each profile by real chezmoi."""
        for profile, name in (("personal", "coordinator"), ("work", "coordinator-work")):
            with self.subTest(profile):
                path = self.tmp / ("kgate-" + profile)
                path.write_text(render_script(profile))
                loader = importlib.machinery.SourceFileLoader("kgate_" + profile, str(path))
                spec = importlib.util.spec_from_loader("kgate_" + profile, loader)
                module = importlib.util.module_from_spec(spec)
                loader.exec_module(module)
                with mock.patch.dict(os.environ, {"HOME": str(self.home), "COORDINATOR_STATE_DIR": ""}):
                    self.assertEqual(module.brake_dir(), str(self.home / ".local" / "share" / name / "brake"))
                with mock.patch.dict(os.environ, {"HOME": str(self.home), "COORDINATOR_STATE_DIR": str(self.tmp / "set")}):
                    self.assertEqual(module.brake_dir(), str(self.tmp / "set" / "brake"), "an explicit folder wins on both profiles")

    def test_a_stop_while_paused_ends_the_job_with_no_pod(self):
        self.brake(lag="2026-11-22T10:00:00Z held")
        proc = self.start("--", "true", env=self.env())
        self.read_until(proc, "paused: ")
        os.killpg(proc.pid, signal.SIGTERM)
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 128 + signal.SIGTERM, out)
        self.assertEqual(self.creates(), 0)


class BrakeRerun(unittest.TestCase):
    """The rerun of an evicted pod (`<id>-r2`) makes a pod, so it waits for the coordinator's pause like the first one."""
    for _name in ("kgate", "records", "calls", "op_env", "launcher", "setUp", "write_cluster", "profile", "run_kgate", "kcalls", "pods_created"):
        locals()[_name] = getattr(KubectlBlack, _name)
    kgate_popen = Black.kgate_popen
    read_until = BrakeHomelab.read_until
    start = BrakeHomelab.start

    def test_an_evicted_pod_is_not_rerun_while_the_pause_is_on_and_is_rerun_when_it_lifts(self):
        folder = self.tmp / "coordinator" / "brake"
        env = {**self.cmd_env, "FAKE_LOST": "1:event", "FAKE_LOST_DELAY": "4", "COORDINATOR_STATE_DIR": str(self.tmp / "coordinator"), "KGATE_BRAKE_POLL_S": "0.2"}
        proc = self.start("--", "sh", "-c", "echo ran-attempt", host="", env=env)
        for _ in range(100):   # the first pod is made before the pause starts
            if self.pods_created():
                break
            time.sleep(0.1)
        self.assertEqual(len(self.pods_created()), 1)
        folder.mkdir(parents=True)
        (folder / "lag").write_text("2026-11-22T10:00:00Z the inbox is late\n")
        seen = self.read_until(proc, "paused: ")   # the pod is evicted 4 s in; the rerun then stops at the pause
        self.assertIn("lag: the inbox is late", seen)
        time.sleep(1)
        self.assertIsNone(proc.poll())
        self.assertEqual(len(self.pods_created()), 1, "no second pod while the pause is on")
        (folder / "lag").unlink()
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, seen + out)
        rec = self.records()[-1]
        self.assertEqual([p["metadata"]["name"] for p in self.pods_created()], [rec["id"], rec["id"] + "-r2"])
        self.assertEqual((rec["attempts"], rec["exit"]), (2, 0))
        self.assertGreater(rec["brake_wait_s"], 0.5)

    def test_a_pause_before_the_first_pod_and_another_before_the_rerun_add_up_and_neither_uses_up_wait(self):
        # --wait 6: the first pause (2 s) and the eviction (4 s into the pod) already take the job to 6 s, and the second pause (2 s) to 8 s. The rerun is still
        # allowed because the 4 s of pause are added to --wait, and brake_wait_s is the sum of the two waits, not the last one.
        folder = self.tmp / "coordinator" / "brake"
        folder.mkdir(parents=True)
        (folder / "lag").write_text("2026-11-22T10:00:00Z the inbox is late\n")
        env = {**self.cmd_env, "FAKE_LOST": "1:event", "FAKE_LOST_DELAY": "4", "COORDINATOR_STATE_DIR": str(self.tmp / "coordinator"), "KGATE_BRAKE_POLL_S": "0.2"}
        proc = self.start("--wait", "6", "--", "sh", "-c", "echo ran-attempt", host="", env=env)
        seen = self.read_until(proc, "paused: ")
        time.sleep(2)
        (folder / "lag").unlink()
        seen += self.read_until(proc, "the pause lifted after")
        for _ in range(100):
            if self.pods_created():
                break
            time.sleep(0.1)
        self.assertEqual(len(self.pods_created()), 1)
        (folder / "lag").write_text("2026-11-22T10:00:10Z the inbox is late again\n")
        seen += self.read_until(proc, "paused: ")   # the pod is evicted 4 s in; the rerun then stops at the second pause
        time.sleep(2)
        (folder / "lag").unlink()
        out, _ = proc.communicate(timeout=60)
        seen += out
        self.assertEqual(proc.returncode, 0, seen)
        rec = self.records()[-1]
        self.assertEqual((rec["attempts"], rec["exit"]), (2, 0))
        self.assertGreater(rec["brake_wait_s"], 3.8, "the two waits add up; the second did not overwrite the first")


QUEUE_LAUNCH = ("import importlib.machinery, importlib.util, sys\n"
                "loader = importlib.machinery.SourceFileLoader('kg', sys.argv[1])\n"
                "K = importlib.util.module_from_spec(importlib.util.spec_from_loader('kg', loader))\n"
                "loader.exec_module(K)\n"
                "K.QUEUE_POLL_S, K.QUEUE_LOCAL_POLL_S = 0.2, 0.1\n"      # the queue's look at the cluster, shortened
                "K.QUEUE_QUIET_S = %s\n"      # a wait on a neighbour is reported at once unless a test says otherwise
                "sys.exit(K.main(sys.argv[2:]))\n")


class QueueHomelab(unittest.TestCase):
    """The job profile asks 2 cpu, 1Gi and the default 4Gi of disk. A pod that waits for room and asks no more than that, and is at least as urgent, means the
    cluster has no room for this job either, so the job queues instead of creating a pod that would sit Unschedulable until --sched-wait gives 75."""
    for _name in ("kgate", "kgate_popen", "records", "calls", "op_env", "profile", "setUp"):
        locals()[_name] = getattr(Black, _name)

    def launcher(self):
        return stub_launcher(self.tmp, "queue_launch.py", QUEUE_LAUNCH % getattr(self, "quiet", 0))

    def waiting(self, name="other", cpu="2", memory="1Gi", disk="4Gi", cls="kgate", pin=None, message="0/7 nodes are available: 7 Insufficient cpu."):
        required = [{"key": "kubernetes.io/hostname", "operator": "In", "values": [pin]}] if pin else [{"key": "kubernetes.io/arch", "operator": "In", "values": ["amd64"]}]
        return {"metadata": {"name": name, "creationTimestamp": "2026-11-16T12:00:00Z"},
                "spec": {"priorityClassName": cls, "affinity": {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": [{"matchExpressions": required}]}}},
                         "containers": [{"resources": {"requests": {"cpu": cpu, "memory": memory, "ephemeral-storage": disk}}}]},
                "status": {"phase": "Pending", "conditions": [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable", "message": message}]}}

    def full(self, *pods):
        path = self.tmp / "pods.json"
        path.write_text(json.dumps({"items": list(pods)}))
        return {"FAKE_PODS": str(path)}

    def creates(self):
        return sum(1 for c in self.calls() if "manifest" in c)

    def read_until(self, proc, text):
        seen = ""
        for line in proc.stdout:
            seen += line
            if text in line:
                break
        self.assertIn(text, seen)
        return seen

    def start(self, *args, env=None):
        proc = self.kgate_popen(*args, env=env)
        self.addCleanup(lambda: (proc.poll() is None and os.killpg(proc.pid, 9), proc.wait(), proc.stdout.close()))
        return proc

    def test_a_job_submitted_to_a_full_cluster_waits_then_runs_and_does_not_exit_75(self):
        env = self.full(self.waiting())
        proc = self.start("--", "sh", "-c", "echo ran-after-the-queue", env=env)
        seen = self.read_until(proc, "queued: ")
        time.sleep(1)
        self.assertEqual(self.creates(), 0, "no pod while the cluster is full")
        self.assertIsNone(proc.poll())
        (self.tmp / "pods.json").unlink()   # room appears
        out, _ = proc.communicate(timeout=60)
        seen += out
        self.assertEqual(proc.returncode, 0, seen)
        self.assertIn("ran-after-the-queue", seen)
        self.assertIn("the cluster is full: 1 kgate pod already waits for room", seen)
        self.assertIn("left the queue after", seen)
        self.assertEqual(self.creates(), 1)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"]), (0, True))
        self.assertGreater(rec["queue_wait_s"], 0.5)

    def test_a_job_with_no_waiting_pod_creates_its_pod_at_once_and_is_not_queued(self):
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertNotIn("queued", done.stdout)
        self.assertNotIn("queue_wait_s", self.records()[-1])

    def test_the_queue_counts_against_wait_and_ends_as_69_unschedulable_with_no_pod(self):
        done = self.kgate("--wait", "2", "--", "true", env=self.full(self.waiting()))
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertTrue(rec["reason"].startswith("pod did not start within 2s: Unschedulable (queued, the cluster is full"), rec["reason"])
        self.assertEqual((self.creates(), rec["ran"]), (0, False))

    def test_a_waiting_pod_that_asks_more_does_not_hold_the_job_back(self):
        for pod in (self.waiting(cpu="6"), self.waiting(memory="3Gi"), self.waiting(disk="20Gi")):
            done = self.kgate("--", "true", env=self.full(pod))
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertNotIn("queued", done.stdout)

    def test_a_waiting_pod_that_is_not_out_of_room_does_not_hold_the_job_back(self):
        done = self.kgate("--", "true", env=self.full(self.waiting(message="0/7 nodes are available: 7 node(s) didn't match Pod's node affinity/selector.")))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertNotIn("queued", done.stdout)

    def test_a_pod_pinned_to_one_node_holds_back_only_a_job_pinned_to_that_node(self):
        pinned = self.full(self.waiting(pin="cartwmic-g14-wsl"))
        free = self.kgate("--", "true", env=pinned)
        self.assertEqual(free.returncode, 0, free.stdout)
        self.assertNotIn("queued", free.stdout)
        same = self.kgate("--wait", "1", "--node", "cartwmic-g14-wsl", "--", "true", env=pinned)
        self.assertIn("queued: ", same.stdout)
        other = self.kgate("--node", "ubuntu-server-k8s-agent-1", "--", "true", env=pinned)
        self.assertEqual(other.returncode, 0, other.stdout)
        self.assertNotIn("queued", other.stdout)
        unpinned_waits = self.kgate("--wait", "1", "--node", "cartwmic-g14-wsl", "--", "true", env=self.full(self.waiting()))   # nothing fits anywhere, so nothing fits there
        self.assertIn("queued: ", unpinned_waits.stdout)

    def test_the_main_run_is_not_held_back_by_a_waiting_pr_gate_but_a_pr_gate_is_held_by_the_main_run(self):
        main = self.kgate("--", "true", env={**self.full(self.waiting(cls="kgate")), "KGATE_PRIORITY_CLASS": "kgate-main"})
        self.assertEqual(main.returncode, 0, main.stdout)
        self.assertNotIn("queued", main.stdout)
        first = self.kgate("--", "true", env={**self.full(self.waiting(cls="kgate")), "KGATE_PRIORITY_CLASS": "kgate-first"})
        self.assertEqual(first.returncode, 0, first.stdout)
        gate = self.kgate("--wait", "1", "--", "true", env=self.full(self.waiting(cls="kgate-main")))
        self.assertIn("queued: ", gate.stdout)
        self.assertEqual(self.creates(), 2)

    def test_two_clients_started_together_create_one_pod_while_the_cluster_is_full(self):
        env = {"FAKE_PODS": str(self.tmp / "pods.json"), "FAKE_CREATE_PENDING": "1", "FAKE_POD": "pending"}   # the first pod made fills the cluster
        first = self.start("--wait", "6", "--", "true", env=env)
        second = self.start("--wait", "6", "--", "true", env=env)
        out1, _ = first.communicate(timeout=60)
        out2, _ = second.communicate(timeout=60)
        self.assertEqual(self.creates(), 1, out1 + out2)
        queued = [o for o in (out1, out2) if "queued: " in o]
        self.assertEqual(len(queued), 1, out1 + out2)
        self.assertEqual(sorted((first.returncode, second.returncode)), [69, 69])

    def test_a_job_that_is_stopped_while_queued_ends_143_creates_no_pod_and_leaves_no_ticket(self):
        proc = self.start("--", "true", env=self.full(self.waiting()))
        self.read_until(proc, "queued: ")
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 143, out)
        self.assertEqual(self.creates(), 0)
        self.assertEqual(list((self.state / "kgate" / "queue").glob("kgate-*.json")), [])

    def test_a_job_that_cannot_read_the_waiting_pods_creates_its_pod(self):
        done = self.kgate("--", "true", env={"FAKE_PODS_FAIL": "1"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("could not read the waiting pods", done.stdout)
        self.assertEqual(self.creates(), 1)

    def ticket(self, name, pid, priority=-100, t=1.0, pidns="same"):
        queue = self.state / "kgate" / "queue"
        queue.mkdir(parents=True, exist_ok=True)
        ident = K.proc_identity(pid)
        (queue / (name + ".json")).write_text(json.dumps({"id": name, "pid": pid, "start": ident[0] if ident else "gone", "pidns": K.pid_namespace(), "t": t,
                                                         "shape": {"cpu": 2.0, "mem": float(1 << 30), "disk": float(4 << 30), "pin": None, "priority": priority}}))
        return queue / (name + ".json")

    def test_an_older_live_ticket_that_asks_no_more_holds_the_job_back_until_it_goes(self):
        holder = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        path = self.ticket("kgate-1-1", holder.pid)
        proc = self.start("--", "true")
        self.read_until(proc, "queued: behind kgate-1-1")
        self.assertEqual(self.creates(), 0)
        path.unlink()
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, out)
        self.assertEqual(self.creates(), 1)

    def test_a_lower_priority_ticket_does_not_hold_back_the_main_run_and_a_dead_one_holds_nobody(self):
        holder = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        self.ticket("kgate-1-1", holder.pid)
        main = self.kgate("--", "true", env={"KGATE_PRIORITY_CLASS": "kgate-main"})
        self.assertEqual(main.returncode, 0, main.stdout)
        self.assertNotIn("queued", main.stdout)
        dead = subprocess.Popen(["true"])
        dead.wait()
        ghost = self.ticket("kgate-2-2", dead.pid)
        done = self.kgate("--", "true", env={"KGATE_PRIORITY_CLASS": "kgate-first"})
        self.assertEqual(done.returncode, 0, done.stdout)
        plain = self.kgate("--wait", "1", "--", "true")
        self.assertIn("queued: behind kgate-1-1", plain.stdout)
        self.assertNotIn("kgate-2-2", plain.stdout)
        self.assertFalse(ghost.exists(), "a dead client's ticket is removed")


    def test_a_ticket_past_its_clients_wait_is_cleared_even_when_the_client_looks_alive(self):
        # another pid namespace (the pid cannot be checked) or a stopped client: its ticket must not hold later jobs until their --wait ends
        queue = self.state / "kgate" / "queue"
        holder = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        foreign = self.ticket("kgate-1-1", 4194000)
        foreign.write_text(json.dumps({**json.loads(foreign.read_text()), "pidns": "pid:[4026539999]", "deadline": time.time() - 1000}))
        stopped = self.ticket("kgate-2-2", holder.pid)
        stopped.write_text(json.dumps({**json.loads(stopped.read_text()), "deadline": time.time() - 1000}))
        done = self.kgate("--", "true", env={"KGATE_PRIORITY_CLASS": "kgate-first"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertNotIn("queued", done.stdout)
        self.assertEqual((self.creates(), foreign.exists(), stopped.exists()), (1, False, False))
        self.assertEqual(list(queue.glob("kgate-*.json")), [])

    def test_a_foreign_ticket_still_inside_its_wait_holds_the_job_back_and_never_longer_than_that_wait(self):
        foreign = self.ticket("kgate-1-1", 4194000)
        foreign.write_text(json.dumps({**json.loads(foreign.read_text()), "pidns": "pid:[4026539999]", "deadline": time.time() + 1.5 - K.QUEUE_STALE_S}))
        done = self.kgate("--wait", "30", "--", "true")   # the grace is added to the deadline: the ticket is stale in 1.5 s
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual((self.creates(), foreign.exists()), (1, False))

    def test_a_job_ticket_carries_its_own_wait_deadline(self):
        proc = self.start("--wait", "100", "--", "true", env=self.full(self.waiting()))
        self.read_until(proc, "queued: ")
        (path,) = (self.state / "kgate" / "queue").glob("kgate-*.json")
        deadline = json.loads(path.read_text())["deadline"]
        self.assertTrue(time.time() + 80 < deadline < time.time() + 101, deadline)

    def test_jobs_started_together_on_a_cluster_with_room_do_not_report_a_queue(self):
        # a job that only waits for a neighbour's placement is not reported (the real quiet time), and polls the local queue every 0.1 s here, 0.3 s in the client, not every 3 s
        self.quiet = K.QUEUE_QUIET_S
        procs = [self.start("--", "true") for _ in range(3)]
        outs = [p.communicate(timeout=60)[0] for p in procs]
        for proc, out in zip(procs, outs):
            self.assertEqual(proc.returncode, 0, out)
            self.assertNotIn("queued", out)
            self.assertNotIn("left the queue", out)
        self.assertEqual(self.creates(), 3)
        self.assertTrue(all("queue_wait_s" not in r for r in self.records()), self.records())

    def test_a_wait_on_a_neighbour_that_lasts_is_reported_after_the_quiet_time(self):
        holder = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        self.ticket("kgate-1-1", holder.pid)
        self.quiet = 1.5
        done = self.kgate("--wait", "4", "--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("queued: behind kgate-1-1", done.stdout)
        self.assertEqual(self.creates(), 0)


QUOTA_LAUNCH = QUEUE_LAUNCH.replace("K.QUEUE_QUIET_S", "K.QUOTA_FIRST_DELAY, K.QUOTA_MAX_DELAY = @DELAYS@\nK.QUEUE_QUIET_S")   # the quota retry, shortened too

# The race admit() re-checks for under the flock: a job ahead is refused by the quota after this job's first look at the queue and before it takes the lock. With
# FAKE_RACE_TICKET set, the stub puts that ticket into the queue at the moment the client first asks for the flock, which is exactly between the two looks.
RACE_HOOK = ("import fcntl, os, shutil\n"
             "_flock, _race = fcntl.flock, os.environ.get('FAKE_RACE_TICKET')\n"
             "def flock(fd, op):\n"
             "    global _race\n"
             "    if _race and op & fcntl.LOCK_EX and str(getattr(fd, 'name', '')).endswith('/queue/.lock'):\n"
             "        shutil.copy(_race, os.path.join(os.path.dirname(os.path.realpath(fd.name)), os.path.basename(_race)))\n"
             "        _race = None\n"
             "    return _flock(fd, op)\n"
             "fcntl.flock = flock\n"
             "sys.exit(")


class QuotaHomelab(unittest.TestCase):
    """The homelab's namespace can carry a ResourceQuota. A create it refuses is waited out in the local queue, with the flock let go while the job sleeps, so a job
    that fits is not held up by one that does not. The fake cluster's quota is requests.cpu 12 (FAKE_QUOTA_CPU); <fake>/quota-full says how much other jobs use."""
    for _name in ("kgate", "kgate_popen", "records", "calls", "op_env", "profile", "setUp"):
        locals()[_name] = getattr(Black, _name)
    for _name in ("read_until", "start"):
        locals()[_name] = getattr(QueueHomelab, _name)

    def launcher(self):
        return stub_launcher(self.tmp, "quota_launch.py", (QUOTA_LAUNCH % 0).replace("@DELAYS@", "%s, %s" % getattr(self, "delays", (0.2, 0.4))).replace("sys.exit(", RACE_HOOK))

    def full(self, used, limit=12):
        (self.fake / "quota-full").write_text(str(used))
        return {"FAKE_QUOTA_CPU": str(limit)}

    def room(self):
        (self.fake / "quota-full").unlink()

    def created(self):
        return sum(1 for c in self.calls() if "created" in c)

    def secrets(self):
        path = self.fake / "secrets"
        return sorted(os.listdir(path)) if path.exists() else []

    def refused_creates(self):
        return sum(1 for c in self.calls() if "manifest" in c) - self.created()

    def wait_until_secrets_are_taken_out(self, proc, refusals):
        """Wait for the fake cluster to have refused `refusals` creates and for the Secrets of the last to be gone. Between a refused create and the delete that follows it the
        Secrets are there, so a look at a fixed time can land inside that gap; what the job guarantees is that they are gone before its next try (the fake refuses a Secret that
        is still there). A client that leaves them is refused AlreadyExists, but the fake also refuses the pod for quota, so it keeps retrying and the 30 s limit here is what fails it; one that never retries never gets here."""
        t_end = time.time() + 30
        while self.refused_creates() < refusals or self.secrets():
            self.assertIsNone(proc.poll(), "the job ended while the quota still refused it")
            self.assertLess(time.time(), t_end, "after %d refused creates the Secrets were still there: %s" % (self.refused_creates(), self.secrets()))
            time.sleep(0.02)

    def test_a_job_the_quota_refuses_waits_in_the_queue_then_runs(self):
        env = self.full(used=12)
        proc = self.start("--cpu", "4", "--", "sh", "-c", "echo ran-after-the-quota", env=env)
        seen = self.read_until(proc, "queued: waiting for quota: exceeded quota: scratch-cpu, requested: requests.cpu=4, used: requests.cpu=12, limited: requests.cpu=12")
        self.wait_until_secrets_are_taken_out(proc, 3)   # the first create and two retries (at 0.2 s and 0.4 s)
        self.assertEqual(self.created(), 0, "no pod")
        self.assertIsNone(proc.poll())
        self.room()
        out, _ = proc.communicate(timeout=60)
        seen += out
        self.assertEqual(proc.returncode, 0, seen)
        self.assertIn("ran-after-the-quota", seen)
        self.assertEqual(seen.count("waiting for quota"), 1, "the same message is said once")
        self.assertIn("left the queue after", seen)
        self.assertEqual(self.created(), 1)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"], rec["cleanup"]), (0, True, True))
        self.assertGreater(rec["quota_wait_s"], 0.5)

    def refused_job(self, env, *args, wait="60"):
        """A job the quota refuses (it asks more than is free), started and waiting in the queue: the process, its ticket and what it said so far."""
        proc = self.start("--wait", wait, "--cpu", "12", *args, "--", "sh", "-c", "echo large-ran", env=env)
        said = self.read_until(proc, "queued: waiting for quota")
        (path,) = (self.state / "kgate" / "queue").glob("kgate-*.json")
        return proc, path, said

    def created_cpus(self):
        """The CPU of each pod the fake cluster accepted, in the order it accepted them."""
        asked = {}
        for c in self.calls():
            for item in c.get("manifest", {}).get("items", []):
                if item["kind"] == "Pod":
                    asked[item["metadata"]["name"]] = int(item["spec"]["containers"][0]["resources"]["requests"]["cpu"])
        return [asked[c["created"]] for c in self.calls() if "created" in c]

    def test_a_job_ordered_ahead_is_placed_while_another_sleeps_for_quota(self):
        self.delays = (60, 60)   # the first job sleeps a minute between its tries: holding the flock that long would stop the job ahead of it from being placed
        env = self.full(used=4)   # 8 of the 12 are free: the first job asks 12
        first, _, said = self.refused_job(env)
        second = self.kgate("--wait", "20", "--cpu", "4", "--", "sh", "-c", "echo second-ran", env={**env, "KGATE_PRIORITY_CLASS": "kgate-first"})   # a higher priority: ordered before the first
        self.assertEqual(second.returncode, 0, second.stdout)
        self.assertIn("second-ran", second.stdout)
        self.assertNotIn("another job is being placed", second.stdout)
        self.assertNotIn("queued", second.stdout)
        self.assertIsNone(first.poll(), "the first is still waiting")
        self.assertEqual(self.created(), 1)
        first.send_signal(signal.SIGTERM)
        first.communicate(timeout=30)
        self.assertIn("queued: waiting for quota", said)

    def test_a_job_the_quota_refused_keeps_its_place_and_runs_before_later_jobs_that_fit(self):
        # 4 of the 12 CPU are in use elsewhere. The large job (12) is refused; three small jobs (4) arrive after it and would each fit. They wait behind it.
        env = {**self.full(used=4), "FAKE_QUOTA_HOLD": "1"}
        large, ticket, _ = self.refused_job(env)
        small = [self.start("--wait", "60", "--cpu", "4", "--", "sh", "-c", "echo small-ran", env=env) for _ in range(3)]
        seen = [self.read_until(p, "queued: behind %s, which the quota refused and was first" % ticket.stem) for p in small]
        self.assertEqual((self.created(), [p.poll() for p in small]), (0, [None] * 3), "no later job takes the quota the large job waits for")
        self.room()   # the other 4 CPU are freed: the large job fits at its next try
        outs = [seen[i] + p.communicate(timeout=60)[0] for i, p in enumerate(small)]
        large_out, _ = large.communicate(timeout=60)
        self.assertEqual((large.returncode, [p.returncode for p in small]), (0, [0, 0, 0]), large_out + "".join(outs))
        self.assertIn("large-ran", large_out)
        self.assertTrue(all("small-ran" in o for o in outs))
        self.assertEqual(self.created_cpus()[0], 12, "the large job's pod is the first one the cluster accepted")
        self.assertEqual(sorted(self.created_cpus()), [4, 4, 4, 12])

    def test_a_large_job_is_not_starved_by_a_stream_of_small_jobs_that_fit(self):
        # quota 12 CPU. One small job (4) is running. The large job (12) is refused, and small jobs keep arriving every 0.5 s, each running 1.5 s, so the quota is never
        # empty for the large job to take it. Without a place in line it waits out its whole --wait (69) while the small ones run.
        env = {**self.full(used=0), "FAKE_QUOTA_HOLD": "1"}
        job = ("--wait", "60", "--cpu", "4", "--", "sh", "-c", "sleep 1.5; echo small-ran")
        stream = [self.start(*job, env=env)]
        self.read_until(stream[0], "pod running")
        large = self.start("--wait", "5", "--cpu", "12", "--", "sh", "-c", "echo large-ran", env=env)
        self.read_until(large, "queued: waiting for quota")
        for _ in range(12):
            time.sleep(0.5)
            stream.append(self.start(*job, env=env))
        large_out, _ = large.communicate(timeout=60)
        outs = [p.communicate(timeout=90)[0] for p in stream]
        self.assertEqual(large.returncode, 0, "the large job timed out while %d small jobs ran:\n%s" % (sum("small-ran" in o for o in outs), large_out))
        self.assertIn("large-ran", large_out)
        self.assertEqual([p.returncode for p in stream], [0] * 13, "".join(outs))
        self.assertEqual(self.created_cpus()[:2], [4, 12], "after the small job that was already running, the large job's pod is the next one the cluster accepted")

    def test_a_small_job_does_not_wait_behind_a_job_the_quota_has_not_refused(self):
        # no refusal, no mark: a large job ahead that has not been refused yet is not a reason to wait (the older rule: only a job that asks no more holds one back)
        holder = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        queue = self.state / "kgate" / "queue"
        queue.mkdir(parents=True)
        ident = K.proc_identity(holder.pid)
        (queue / "kgate-1-1.json").write_text(json.dumps({"id": "kgate-1-1", "pid": holder.pid, "start": ident[0], "pidns": K.pid_namespace(), "t": 1.0,
                                                          "shape": {"cpu": 12.0, "mem": float(1 << 30), "disk": float(4 << 30), "pin": None, "priority": -100}}))
        done = self.kgate("--wait", "20", "--cpu", "4", "--", "sh", "-c", "echo small-ran", env=self.full(used=4))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertNotIn("queued", done.stdout)

    def test_a_job_ahead_refused_by_the_quota_after_the_first_look_is_still_waited_behind(self):
        # The job looks at the queue (nothing ahead), then asks for the flock. In between, a job ordered before it is refused by the quota and marks its ticket. The look
        # under the flock must see that ticket: the cluster shows no waiting pod (cluster_full is None), so without the second look the job would create its pod ahead of it.
        holder = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        ident = K.proc_identity(holder.pid)
        race = self.tmp / "kgate-1-1.json"   # not in the queue yet: the stub moves it in when the client first asks for the flock
        race.write_text(json.dumps({"id": "kgate-1-1", "pid": holder.pid, "start": ident[0], "pidns": K.pid_namespace(), "t": 1.0, "quota": True,
                                    "shape": {"cpu": 12.0, "mem": float(1 << 30), "disk": float(4 << 30), "pin": None, "priority": -100}}))   # asks more than this job: only its mark holds this job back
        proc = self.start("--wait", "60", "--cpu", "4", "--", "sh", "-c", "echo ran-after-it", env={**self.full(used=4), "FAKE_RACE_TICKET": str(race)})
        seen = self.read_until(proc, "queued: behind kgate-1-1, which the quota refused and was first")
        time.sleep(1)
        self.assertEqual((self.created(), proc.poll()), (0, None), "no pod is made ahead of the job the quota refused")
        (self.state / "kgate" / "queue" / "kgate-1-1.json").unlink()   # the job ahead gives up its place
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, seen + out)
        self.assertIn("ran-after-it", out)
        self.assertEqual(self.created(), 1)

    def test_a_dead_clients_quota_ticket_does_not_block_the_queue(self):
        env = self.full(used=4)
        large, ticket, _ = self.refused_job(env)
        large.kill()   # no cleanup: the ticket is left behind, marked
        large.wait()
        self.assertTrue(ticket.exists(), "the killed client could not remove its ticket")
        done = self.kgate("--wait", "20", "--cpu", "4", "--", "sh", "-c", "echo small-ran", env=env)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("small-ran", done.stdout)
        self.assertFalse(ticket.exists(), "the dead client's ticket is cleared")

    def test_a_job_that_gives_up_leaves_its_place(self):
        env = self.full(used=4)
        done = self.kgate("--wait", "2", "--cpu", "12", "--", "true", env=env)
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertEqual(list((self.state / "kgate" / "queue").glob("kgate-*.json")), [])
        after = self.kgate("--wait", "20", "--cpu", "4", "--", "sh", "-c", "echo small-ran", env=env)
        self.assertEqual(after.returncode, 0, after.stdout)

    def test_a_job_held_behind_a_refused_one_ends_at_its_wait_and_says_the_quota_is_why(self):
        env = self.full(used=4)
        large, _, _ = self.refused_job(env)
        done = self.kgate("--wait", "2", "--cpu", "4", "--", "true", env=env)
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertRegex(self.records()[-1]["reason"], r"^pod did not start within 2s: Unschedulable \(queued, behind kgate-[^,]+, which the quota refused and was first\)$")
        self.assertEqual(self.created(), 0)

    def test_a_request_above_the_quotas_own_limit_fails_at_once(self):
        done = self.kgate("--wait", "600", "--cpu", "16", "--", "true", env={"FAKE_QUOTA_CPU": "12"})
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertRegex(rec["reason"], r"^request exceeds the namespace quota: exceeded quota: scratch-cpu, requested: requests.cpu=16, used: requests.cpu=0, limited: requests.cpu=12$")
        self.assertNotIn("queued", done.stdout)
        self.assertEqual((self.created(), rec["ran"], rec["cleanup"], self.secrets()), (0, False, True, []))

    def test_a_quota_that_never_frees_ends_at_the_deadline_with_the_message(self):
        done = self.kgate("--wait", "3", "--cpu", "4", "--", "true", env=self.full(used=12))
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertRegex(rec["reason"], r"^quota not available within 3s: exceeded quota: scratch-cpu, requested: requests.cpu=4, used: requests.cpu=12, limited: requests.cpu=12$")
        self.assertIn("quota_wait_s", rec)
        self.assertEqual((self.created(), rec["ran"], rec["cleanup"], self.secrets()), (0, False, True, []))

    def test_the_quota_wait_is_never_longer_than_the_queue_wait_it_is_counted_in(self):
        # The pod's Secrets are deleted after the refusal. That delete takes 2 s here; the quota's clock starts at the refusal, so the queue's must too: quota_wait_s is
        # counted inside queue_wait_s (docs/kgate.md, "Record").
        done = self.kgate("--wait", "4", "--cpu", "4", "--", "true", env={**self.full(used=12), "FAKE_DELETE_SLOW": "2"})
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertGreater(rec["quota_wait_s"], 2, rec)   # the delete's 2 s are part of the wait for quota
        self.assertLessEqual(rec["quota_wait_s"], rec["queue_wait_s"], rec)

    def test_any_other_refusal_stays_fatal_even_when_it_says_exceeded_quota(self):
        for text in ("Error from server (Forbidden): pods is forbidden: violates PodSecurity",
                     "error: the webhook said exceeded quota: please stop"):
            done = self.kgate("--wait", "600", "--cpu", "4", "--", "true", env={"FAKE_QUOTA_CPU": "12", "FAKE_CREATE_ERROR": text})
            self.assertEqual(done.returncode, 69, done.stdout)
            self.assertEqual(self.records()[-1]["reason"], "could not create the pod: " + text)
            self.assertNotIn("queued", done.stdout)

    def test_a_job_stopped_while_it_waits_for_quota_ends_143_and_leaves_nothing(self):
        proc = self.start("--cpu", "4", "--", "true", env=self.full(used=12))
        self.read_until(proc, "queued: waiting for quota")
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 143, out)
        self.assertEqual((self.created(), self.secrets()), (0, []))
        self.assertEqual(list((self.state / "kgate" / "queue").glob("kgate-*.json")), [])


class PodLostReason(unittest.TestCase):
    """dotfiles: 86 jobs in a week were lost pods with no reason printed. The reason is read from the cluster before the pod is deleted."""
    for _name in ("kgate", "launcher", "records", "calls", "op_env", "profile", "setUp"):
        locals()[_name] = getattr(Black, _name)

    def test_a_pod_lost_by_the_oom_killer_says_so(self):
        done = self.kgate("--", "sh", "-c", "echo started; sleep 1", env={"FAKE_DIE": "1", "FAKE_OOM_KILLS": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        rec = self.records()[-1]
        self.assertTrue(rec["reason"].startswith("lost the pod before CMD finished (kubectl exit 255); the result is unknown and the job is not rerun; pod end reason: "), rec["reason"])
        self.assertIn("memory cgroup killed 1 process(es) for running out of memory", rec["reason"])
        self.assertIn("container still running", rec["reason"])
        self.assertEqual(rec["lost_pod"], rec["reason"].split("pod end reason: ")[1])
        self.assertIn("pod end reason: ", done.stdout)

    def test_a_pod_that_is_gone_says_so_and_names_the_events(self):
        done = self.kgate("--", "sh", "-c", "echo started; sleep 1", env={"FAKE_DIE": "1", "FAKE_EVICT_EVENT": "-", "FAKE_EVICT_GONE": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        reason = self.records()[-1]["reason"]
        self.assertIn("pod end reason: the pod is gone (Error from server (NotFound)", reason)
        self.assertIn("event Killing: Stopping container job", reason)

    def test_a_failed_read_of_the_pod_while_waiting_is_retried_and_the_job_runs(self):
        # the API server times out on the first two reads of the pod (the first is the queue's own look after the create), then recovers
        done = self.kgate("--", "true", env={"FAKE_GET_FAIL_FIRST": "2"})
        self.assertEqual(done.returncode, 0, done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"], rec["reason"]), (0, True, None))
        reads = [c for c in self.calls() if c.get("kubectl", [])[:2] == ["get", "pod"] and "json" in c["kubectl"]]
        self.assertGreaterEqual(len(reads), 3)

    def test_a_lost_pod_with_nothing_wrong_to_read_still_keeps_todays_text_first(self):
        done = self.kgate("--", "sh", "-c", "echo started; sleep 1", env={"FAKE_DIE": "1"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertTrue(self.records()[-1]["reason"].startswith("lost the pod before CMD finished (kubectl exit 255); the result is unknown and the job is not rerun"))
        self.assertNotIn("oom", self.records()[-1]["reason"].lower())


# ---------------------------------------------------------------- a process CMD leaves behind does not keep the job alive

ORPHAN_STREAM_LAUNCH = ("import importlib.machinery, importlib.util, sys\n"
                        "loader = importlib.machinery.SourceFileLoader('kg', sys.argv[1])\n"
                        "K = importlib.util.module_from_spec(importlib.util.spec_from_loader('kg', loader))\n"
                        "loader.exec_module(K)\n"
                        "K.END_GRACE_S = 1\n"     # the wait after the end line, shortened
                        "sys.exit(K.main(sys.argv[2:]))\n")


class LeftBehindProcess:
    """CMD starts a background process that outlives it and holds the exec stream open (five coordinator jobs, 2026-11-16, held their pods for hours). The job
    returns with CMD's exit code soon after the end line and the pod is deleted. Run for both cluster kinds."""

    def launcher(self):
        return stub_launcher(self.tmp, "orphan_stream_launch.py", ORPHAN_STREAM_LAUNCH)

    def run_orphan(self, command):
        started = time.time()
        done = self.job("--", "sh", "-c", command)
        return done, time.time() - started

    def test_a_background_process_holding_stdout_does_not_hold_the_job(self):
        done, took = self.run_orphan("( sleep 40 ) & echo hi; exit 3")
        self.assertEqual(done.returncode, 3, done.stdout)
        self.assertLess(took, 25, "the job waited for the process CMD left behind: " + done.stdout)
        self.assertIn("hi", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["ran"]), (3, None, True))
        self.assertIn(rec["id"], (self.fake / "deleted-pods").read_text().split(), "the pod was deleted")
        self.assertTrue(rec["cleanup"])

    def test_the_end_and_peak_lines_still_print(self):
        done, _ = self.run_orphan("( sleep 40 ) & exit 0")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertRegex(done.stdout, r"kgate\[[^\]]+\]: peak ")
        self.assertRegex(done.stdout, r"kgate\[[^\]]+\]: end \d+ exit 0")

    def test_a_leftover_process_that_keeps_writing_after_the_end_line_is_still_cut_off(self):
        # a stream that never goes quiet must not re-arm the grace: the cut is at END_GRACE_S after the end line, not after the last output
        done, took = self.run_orphan("( while :; do echo noise; sleep 0.1; done ) & echo hi; exit 3")
        self.assertEqual(done.returncode, 3, done.stdout)
        self.assertLess(took, 25, "the job waited for the process CMD left behind: " + done.stdout[-400:])
        self.assertRegex(done.stdout, r"kgate\[[^\]]+\]: end \d+ exit 3")
        self.assertIn("CMD left a process holding the exec stream; not waiting for it", done.stdout)
        self.assertIn(self.records()[-1]["id"], (self.fake / "deleted-pods").read_text().split(), "the pod was deleted")

    def test_a_command_that_leaves_nothing_behind_does_not_wait(self):
        done, took = self.run_orphan("exit 4")
        self.assertEqual(done.returncode, 4, done.stdout)
        self.assertNotIn("not waiting", done.stdout)


class LeftBehindHomelab(LeftBehindProcess, unittest.TestCase):
    for _name in ("kgate", "records", "calls", "op_env", "profile", "setUp"):
        locals()[_name] = getattr(Black, _name)

    def job(self, *args, env=None):
        return self.kgate(*args, env=env)


class LeftBehindKubectl(LeftBehindProcess, unittest.TestCase):
    for _name in ("kgate", "records", "calls", "op_token_checks", "op_env"):
        locals()[_name] = getattr(Black, _name)
    for _name in ("setUp", "write_cluster", "profile", "run_kgate", "kcalls"):
        locals()[_name] = getattr(KubectlBlack, _name)

    def job(self, *args, env=None):
        return self.run_kgate(*args, env=env)


# ---------------------------------------------------------------- an interrupted client deletes its pod, or leaves the entry that finds it (dotfiles#481)

class InterruptDeletesThePod:
    """A stop of the client while its pod is Pending/Unschedulable. On 2026-11-16 a stop that signals the whole process group reached the client twice (the
    group's signal, and run-and-wake forwarding it): the second one raised inside the cleanup, the client died with the delete unfinished, and its registry
    entry went with it. Run for both cluster kinds."""

    def launcher(self):
        return stub_launcher(self.tmp, "orphan_launch.py", ORPHAN_LAUNCH)

    def deleted(self):
        path = self.fake / "deleted-pods"
        return path.read_text().split() if path.exists() else []

    def active(self):
        return self.state / "kgate" / "active"

    def pending_client(self, env=None):
        """A client whose pod stays Pending; returns it once it is waiting for the pod, with the output read so far."""
        proc = self.job_popen("--", "true", env={"FAKE_POD": "pending", **(env or {})})
        self.addCleanup(lambda: (proc.poll() is None and os.killpg(proc.pid, 9), proc.wait(), proc.stdout.close()))
        seen = ""
        for line in proc.stdout:
            seen += line
            if "waiting for the pod: " in line:
                break
        self.assertIn("waiting for the pod: ", seen)
        return proc, seen

    def wait_for(self, path, secs=20):
        t_end = time.time() + secs
        while not path.exists():
            self.assertLess(time.time(), t_end, "never appeared: %s" % path)
            time.sleep(0.05)

    def test_one_stop_while_the_pod_is_pending_deletes_it(self):
        proc, seen = self.pending_client()
        proc.send_signal(signal.SIGTERM)
        rest = seen + proc.stdout.read()
        self.assertEqual(proc.wait(timeout=60), 143, rest)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["cleanup"]), (143, "interrupted (SIGTERM)", True))
        self.assertIn(rec["id"], self.deleted())
        self.assertFalse((self.active() / (rec["id"] + ".json")).exists())

    def stop_twice(self, first, second):
        proc, seen = self.pending_client(env={"FAKE_DELETE_SLOW": "30"})
        proc.send_signal(first)
        self.wait_for(self.fake / "delete-started")          # the cleanup's delete is in flight
        os.killpg(proc.pid, second)                          # the stop that signals the whole group: this client and the delete it runs
        rest = seen + proc.stdout.read()
        return proc, rest

    def test_a_second_sigterm_during_the_delete_does_not_stop_the_cleanup(self):
        proc, rest = self.stop_twice(signal.SIGTERM, signal.SIGTERM)
        self.assertEqual(proc.wait(timeout=60), 143, rest)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["cleanup"]), (143, "interrupted (SIGTERM)", True))
        self.assertIn(rec["id"], self.deleted(), "the pod was deleted")
        self.assertGreater(rec["cleanup_attempts"], 1, "the delete the signal cut off was tried again")
        self.assertFalse((self.active() / (rec["id"] + ".json")).exists())
        self.assertIn("kgate: exit 143 (interrupted (SIGTERM))", rest)

    def test_a_second_sigint_during_the_delete_does_not_stop_the_cleanup(self):
        proc, rest = self.stop_twice(signal.SIGINT, signal.SIGINT)
        self.assertEqual(proc.wait(timeout=60), 130, rest)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["cleanup"]), (130, "interrupted (SIGINT)", True))
        self.assertIn(rec["id"], self.deleted(), "the pod was deleted")
        self.assertFalse((self.active() / (rec["id"] + ".json")).exists())

    def left_behind(self):
        """A client stopped while Pending whose delete never succeeds: returns the job id."""
        proc, seen = self.pending_client(env={"FAKE_DELETE_FAIL": "always"})
        proc.send_signal(signal.SIGTERM)
        rest = seen + proc.stdout.read()
        self.assertEqual(proc.wait(timeout=60), 143, rest)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["cleanup"]), (143, False))
        self.assertEqual(self.deleted(), [])
        return rec["id"]

    def test_a_delete_that_is_not_confirmed_keeps_the_entry_and_the_next_client_deletes_the_pod(self):
        job_id = self.left_behind()
        self.assertTrue((self.active() / (job_id + ".json")).exists(), "the entry that finds the pod is kept")
        done = self.job("--", "true")                                   # the next client
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ended %s: its client ended without confirming the pod delete; pod deleted" % job_id, done.stdout)
        self.assertIn(job_id, self.deleted())
        self.assertFalse((self.active() / (job_id + ".json")).exists())
        self.assertEqual([r["exit"] for r in self.records() if r["id"] == job_id], [143], "its own end line stays the only one")

    def test_kgate_cancel_deletes_the_pod_of_a_client_that_could_not(self):
        job_id = self.left_behind()
        done = self.job("cancel", job_id)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ended: exit 143 (interrupted (SIGTERM))", done.stdout)
        self.assertIn(job_id, self.deleted())
        self.assertFalse((self.active() / (job_id + ".json")).exists())

    def test_a_cancel_whose_delete_fails_keeps_the_entry(self):
        stale = self.active()
        stale.mkdir(parents=True, exist_ok=True)
        corpse = subprocess.Popen(["sleep", "300"])
        start, command = K.proc_identity(corpse.pid)
        job_id = "kgate-1700000003-333"
        entry = {"id": job_id, "job": None, "pid": corpse.pid, "start": start, "proc_cmd": command, "cwd": str(self.repo), "argv": ["kgate", "--", "sleep"],
                 "cmd": "sleep 300", "node": "n", "cluster": self.cluster_name}
        (stale / (job_id + ".json")).write_text(json.dumps(entry))
        corpse.kill()
        corpse.wait()
        done = self.job("cancel", job_id, env={"FAKE_DELETE_FAIL": "always"})
        self.assertIn("delete not confirmed", done.stdout)
        self.assertTrue((stale / (job_id + ".json")).exists(), "the pod may still be there: the entry stays")
        done = self.job("cancel", job_id)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertFalse((stale / (job_id + ".json")).exists())


class InterruptHomelab(InterruptDeletesThePod, unittest.TestCase):
    for _name in ("kgate", "kgate_popen", "records", "calls", "op_env", "profile", "setUp"):
        locals()[_name] = getattr(Black, _name)
    cluster_name = "homelab"

    def job(self, *args, env=None):
        return self.kgate(*args, env=env)

    def job_popen(self, *args, env=None):
        return self.kgate_popen(*args, env=env)


class InterruptKubectl(InterruptDeletesThePod, unittest.TestCase):
    for _name in ("kgate", "kgate_popen", "records", "calls", "op_token_checks", "op_env"):
        locals()[_name] = getattr(Black, _name)
    for _name in ("setUp", "write_cluster", "profile", "run_kgate", "kcalls"):
        locals()[_name] = getattr(KubectlBlack, _name)
    cluster_name = "example"

    def job(self, *args, env=None):
        return self.run_kgate(*args, env=env)

    def job_popen(self, *args, env=None):
        return self.kgate_popen(*args, host="", env={**self.cmd_env, **(env or {})})


class SshMux:
    """The homelab adapter runs every ssh of one job through one multiplexed connection (master-1's sshd drops handshakes beyond MaxStartups 10:30:100, and a
    job waiting for a pod used to open a new ssh every 2 s, so 2026-11-16's queued jobs died with exit 69), and closes it on every way out of the job."""

    def launcher(self):
        return stub_launcher(self.tmp, "orphan_launch.py", ORPHAN_LAUNCH)

    def ssh_calls(self):
        path = self.fake / "ssh-argv.jsonl"
        return [json.loads(l) for l in path.read_text().splitlines()] if path.exists() else []

    def control_paths(self, calls):
        return {a[1].partition("=")[2] for c in calls for a in zip(c, c[1:]) if a[0] == "-o" and a[1].startswith("ControlPath=")}

    def assert_one_master_closed_last(self, hosts=None):
        calls = self.ssh_calls()
        working = [c for c in calls if "-O" not in c]
        closing = [c for c in calls if "-O" in c]
        self.assertGreater(len(working), 2, "the job made several ssh calls")
        paths = self.control_paths(calls)
        self.assertEqual(len(paths), 1, "every ssh of the job names the same ControlPath: %s" % paths)
        for c in working:
            self.assertIn("ControlMaster=auto", c)
            self.assertTrue(any(x.startswith("ControlPersist=") for x in c), c)
        self.assertTrue(closing, "the master was closed")
        self.assertEqual(calls[-len(closing):], closing, "the close is the last thing the client does with ssh")
        for c in closing:
            self.assertEqual(c[c.index("-O") + 1], "exit")
        folder = Path(next(iter(paths))).parent
        self.assertFalse(folder.exists(), "no socket or folder is left: %s" % folder)
        return working, closing

    def test_a_job_that_passes_shares_one_connection_and_closes_it(self):
        done = self.job("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assert_one_master_closed_last()

    def test_a_job_that_fails_closes_it(self):
        done = self.job("--", "true", env={"FAKE_POD": "pullfail"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assert_one_master_closed_last()

    def test_a_waiting_job_polls_over_the_one_connection(self):
        # --wait must outlast --sched-wait: the wait deadline starts at the job's start, the scheduling deadline at the pod's creation, so with both at 5 s a slow runner lets a poll land between them and exit 69 instead of 75
        done = self.job("--wait", "60", "--sched-wait", "5", "--", "true", env={"FAKE_POD": "pending"})
        self.assertEqual(done.returncode, 75, done.stdout)
        working, _ = self.assert_one_master_closed_last()
        polls = [c for c in working if "get pod" in c[-1] and "-o json" in c[-1]]
        self.assertGreater(len(polls), 2, "it polled more than twice, all over the same master")

    def test_a_stop_closes_it(self):
        proc = self.job_popen("--", "true", env={"FAKE_POD": "pending"})
        self.addCleanup(lambda: (proc.poll() is None and os.killpg(proc.pid, 9), proc.wait(), proc.stdout.close()))
        seen = ""
        for line in proc.stdout:
            seen += line
            if "waiting for the pod: " in line:
                break
        proc.send_signal(signal.SIGTERM)
        rest = seen + proc.stdout.read()
        self.assertEqual(proc.wait(timeout=60), 143, rest)
        self.assert_one_master_closed_last()

    def test_with_two_hosts_the_one_that_answers_gets_the_connection(self):
        done = self.job("--", "true", host="u@one-down,u@two")
        self.assertEqual(done.returncode, 0, done.stdout)
        working, closing = self.assert_one_master_closed_last()
        self.assertEqual({c[-2] if c[-1] == "true" else c[-2] for c in working if "-O" not in c}, {"u@one-down", "u@two"}, "the first host was only probed")
        self.assertEqual({c[-2] for c in working if "kubectl" in c[-1]}, {"u@two"})

    def test_kgate_cancel_closes_the_connection_it_used(self):
        proc = self.job_popen("--", "true", env={"FAKE_POD": "pending", "FAKE_DELETE_FAIL": "always"})
        self.addCleanup(lambda: (proc.poll() is None and os.killpg(proc.pid, 9), proc.wait(), proc.stdout.close()))
        for line in proc.stdout:
            if "waiting for the pod: " in line:
                break
        proc.send_signal(signal.SIGTERM)
        proc.stdout.read()
        proc.wait(timeout=60)
        job_id = self.records()[-1]["id"]
        before = len(self.ssh_calls())
        done = self.job("cancel", job_id)
        self.assertEqual(done.returncode, 0, done.stdout)
        later = self.ssh_calls()[before:]
        self.assertTrue(later and "-O" in later[-1], "cancel closed its own connection last")
        folder = Path(next(iter(self.control_paths(later)))).parent
        self.assertFalse(folder.exists())


class SshMuxHomelab(SshMux, unittest.TestCase):
    for _name in ("kgate", "kgate_popen", "records", "calls", "op_env", "profile", "setUp"):
        locals()[_name] = getattr(Black, _name)

    def job(self, *args, host="fake", env=None):
        return self.kgate(*args, host=host, env=env)

    def job_popen(self, *args, env=None):
        return self.kgate_popen(*args, env=env)


if __name__ == "__main__":
    unittest.main()
