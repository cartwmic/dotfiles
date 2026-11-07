"""Tests for dot_local/bin/executable_kgate.

Pure parts are called directly (tree hash against real git, profile, version match, pod spec, markers, peak meter).
The client also runs as a real process against a scripted cluster: a fake `ssh` first on PATH answers the kubectl
commands the client sends and runs the "pod" on this machine, and a fake `op` returns scripted secrets. Everything is
checked from outside: exit codes, output, the job record, files that came back, and what the fake cluster was sent.
"""
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("KGATE_SCRIPT") or ROOT / "dot_local/bin/executable_kgate")
DIGEST = "ghcr.io/cartwmic/kgate@sha256:" + "ab" * 32
FAKE_TOKEN = "ops_fake-token-for-tests-only"  # a stand-in service-account token; never a real one
NO_TOKEN = "1Password service account token not set; refusing to use the desktop app (playbook 78819cbd)"


def load():
    sys.dont_write_bytecode = True  # the script lives in dot_local/bin; leave no __pycache__ there
    loader = importlib.machinery.SourceFileLoader("kgate_under_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader("kgate_under_test", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


K = load()


def git(cwd, *args, **env):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                        "GIT_COMMITTER_EMAIL": "t@t", **env})


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
        args = dict(job="kgate-1-2", image=DIGEST, cpu=3, memory="6Gi", node=None, secret_env={}, pull=None)
        args.update(kw)
        items = K.pod_manifests(args["job"], args["image"], args["cpu"], args["memory"], args["node"], args["secret_env"], args["pull"])["items"]
        return items[-1], items[:-1]

    def test_limits_and_jobs_follow_the_request(self):
        pod, _ = self.pod()
        c = pod["spec"]["containers"][0]
        self.assertEqual(c["resources"]["requests"], {"cpu": "3", "memory": "6Gi"})
        self.assertEqual(c["resources"]["limits"], {"memory": "6Gi"})
        env = {e["name"]: e.get("value") for e in c["env"]}
        self.assertEqual((env["CARGO_BUILD_JOBS"], env["RAYON_NUM_THREADS"], env["MAKEFLAGS"]), ("3", "3", "-j3"))
        self.assertEqual(c["image"], DIGEST)
        self.assertEqual(c["command"], ["tini", "--", "sleep", "infinity"], "PID 1 is an init, so orphans are reaped")

    def test_keeps_off_excluded_nodes(self):
        pod, _ = self.pod()
        exprs = pod["spec"]["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]["matchExpressions"]
        notin = next(e for e in exprs if e["operator"] == "NotIn")
        self.assertEqual(set(notin["values"]), {"ubuntu-server-k8s-agent-4", "ubuntu-server-k8s-master-1", "mac-mini-worker"})
        self.assertIn({"key": "kubernetes.io/arch", "operator": "In", "values": ["amd64"]}, exprs)

    def test_pinned_node(self):
        pod, _ = self.pod(node="ubuntu-server-k8s-agent-1")
        exprs = pod["spec"]["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]["matchExpressions"]
        self.assertIn({"key": "kubernetes.io/hostname", "operator": "In", "values": ["ubuntu-server-k8s-agent-1"]}, exprs)

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

    def test_peak_meter_samples_when_the_kernel_has_no_peak(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "memory.current").write_text("777\n")
            meter = K.PeakMeter(d)
            meter.start()
            self.assertEqual(meter.stop(), (777, "sampled"))


FAKE_SSH = r'''#!/usr/bin/env python3
import json, os, re, shlex, subprocess, sys
fake = os.environ["FAKE"]
host, remote = sys.argv[-2], sys.argv[-1]
def log(entry):
    with open(os.path.join(fake, "calls.jsonl"), "a") as f:
        f.write(json.dumps(entry) + "\n")
if host.endswith("unreachable"):
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
    names = [x for x in a[1:] if "/" in x]
    for n in names:
        pass
    sys.exit(0)
if a[:2] == ["get", "pods"] or a[:2] == ["get", "secrets"]:
    print(json.dumps({"items": []})); sys.exit(0)
if a[:2] == ["create", "-f"]:
    manifest = json.load(sys.stdin)
    log({"manifest": manifest})
    sys.exit(0)
if a[:2] == ["get", "pod"]:
    if scenario == "ready":
        st = {"phase": "Running", "containerStatuses": [{"ready": True, "state": {"running": {}}}]}
    elif scenario == "pullfail":
        st = {"phase": "Pending", "containerStatuses": [{"ready": False, "state": {"waiting": {"reason": "ErrImagePull", "message": "401 unauthorized"}}}]}
    else:
        st = {"phase": "Pending", "conditions": [{"type": "PodScheduled", "status": "False", "reason": "Unschedulable", "message": "0/7 nodes fit"}]}
    print(json.dumps({"spec": {"nodeName": "fake-node"}, "status": st})); sys.exit(0)
if a[0] == "exec" and "-i" in a:
    job = a[2]
    data = sys.stdin.buffer.read()
    # A real pod has a real /tmp; on a Mac /tmp is a symlink tar will not extract through, so the job's own two files go under FAKE.
    jobroot = os.path.join(fake, "jobroot")
    os.makedirs(jobroot, exist_ok=True)
    tar = subprocess.run(["tar", "-xf", "-", "--no-same-owner", "-C", "/", "--exclude", "tmp/kgate-*"], input=data)
    tar2 = subprocess.run(["tar", "-xf", "-", "--no-same-owner", "-C", jobroot, "tmp/%s" % job], input=data)
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
            proc.kill(); sys.stderr.write("error: lost connection to pod\n"); sys.exit(255)
    sys.exit(proc.wait())
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
[ -n "$FAKE_OP_FAIL" ] && { echo "[ERROR] item not found" >&2; exit 1; }
printf 'value-of-%s' "$(basename "$2")"
'''


class Black(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kt-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        self.fake = self.tmp / "fake"
        self.state = self.tmp / "state"
        self.home = self.tmp / "home"  # no token file here, so the real ~/.config is never read
        for d in (self.bin, self.fake, self.home):
            d.mkdir()
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

    def profile(self, tools="", extra="", secrets=""):
        (self.repo / "kgate.toml").write_text('image = "%s"\ncpu = 2\nmemory = "1Gi"\n%s\n[tools]\n%s\n[secrets]\n%s\n' % (DIGEST, extra, tools, secrets))

    def op_env(self):
        """The 1Password token and HOME every test starts with: a stand-in token, and a HOME with no token file."""
        return {"HOME": str(self.home), "OP_SERVICE_ACCOUNT_TOKEN": FAKE_TOKEN, "FAKE_TOKEN": FAKE_TOKEN}

    def kgate(self, *args, host="fake", env=None):
        e = {**os.environ, "PATH": "%s:%s" % (self.bin, os.environ["PATH"]), "FAKE": str(self.fake), "XDG_STATE_HOME": str(self.state),
             "KGATE_SSH": host, "KGATE_SSH_KEY": "/dev/null", "RUN_AND_WAKE_JOB": "20261104T000000Z-abcdef", **self.op_env(), **(env or {})}
        # the module reads KGATE_SSH at import, so run the script as a process
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=self.repo, env=e, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, timeout=120)

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
        self.profile(extra='services = ["docker"]')
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("needs docker", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.calls()))

    def test_unpinned_image_is_69(self):
        done = self.kgate("--image", "node:24", "--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("pinned by digest", done.stdout)

    def test_excluded_node_is_refused(self):
        done = self.kgate("--node", "ubuntu-server-k8s-agent-4", "--", "true")
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

    def test_the_pod_is_sent_the_limits(self):
        self.assertEqual(self.kgate("--cpu", "3", "--mem", "2Gi", "--", "true").returncode, 0)
        manifest = next(c["manifest"] for c in self.calls() if "manifest" in c)
        c = manifest["items"][-1]["spec"]["containers"][0]
        self.assertEqual(c["resources"]["limits"], {"memory": "2Gi"})
        self.assertEqual(c["resources"]["requests"], {"cpu": "3", "memory": "2Gi"})


if __name__ == "__main__":
    unittest.main()
