"""Tests for dot_local/bin/executable_kgate.

Pure parts are called directly (tree hash against real git, profile, version match, pod spec, markers, peak meter).
The client also runs as a real process against a scripted cluster: a fake `ssh` first on PATH answers the kubectl
commands the client sends and runs the "pod" on this machine, and a fake `op` returns scripted secrets. Everything is
checked from outside: exit codes, output, the job record, files that came back, and what the fake cluster was sent.
"""
import hashlib
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

    def test_memory_limit_parses_and_defaults_to_none(self):
        self.assertIsNone(K.parse_profile(self.GOOD)["memory_limit"])
        self.assertEqual(K.parse_profile('memory = "1Gi"\nmemory_limit = "2Gi"')["memory_limit"], "2Gi")

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
        args = dict(job="kgate-1-2", image=DIGEST, cpu=3, memory="6Gi", node=None, secret_env={}, pull=None, memory_limit=None)
        args.update(kw)
        items = K.pod_manifests(args["job"], args["image"], args["cpu"], args["memory"], args["node"], args["secret_env"], args["pull"],
                                memory_limit=args["memory_limit"])["items"]
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

    def test_request_and_limit_render_separately(self):
        pod, _ = self.pod(memory="256Mi", memory_limit="512Mi")
        c = pod["spec"]["containers"][0]
        self.assertEqual(c["resources"], {"requests": {"cpu": "3", "memory": "256Mi"}, "limits": {"memory": "512Mi"}})

    def test_default_render_is_byte_identical_to_the_one_before_memory_limit(self):
        # sha256 of json.dumps(manifests); re-pinned 2026-11-08 for the agent-4 overflow preference (the only change from the 4ef32ef1 render)
        cases = [
            (K.pod_manifests("kgate-1-2", DIGEST, 3, "6Gi", None, {}, None), "c0a96c550ba45917cc2a732409384936977b8a5a42567db9891af4419efa6dd7"),
            (K.pod_manifests("kgate-1-2", DIGEST, 2, "1Gi", "ubuntu-server-k8s-agent-1", {"TOK": b"s3cret"}, ("ghcr.io", "u", b"pw")),
             "f9f91a171d9cbcc3cff44901ebd23a5506fff9db5cb8880153f0fe3f7c11d6b7"),
            (K.pod_manifests("kgate-9-9", DIGEST, 1, "512Mi", None, {}, None, 1000), "dc281cecdc8b40c2a06e9b5b67d792874a73998a59dad9297abfa8e271608d4a"),
        ]
        for manifests, want in cases:
            self.assertEqual(hashlib.sha256(json.dumps(manifests).encode()).hexdigest(), want)

    def test_keeps_off_excluded_nodes(self):
        pod, _ = self.pod()
        exprs = pod["spec"]["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"][0]["matchExpressions"]
        notin = next(e for e in exprs if e["operator"] == "NotIn")
        self.assertEqual(notin["values"], ["ubuntu-server-k8s-master-1", "mac-mini-worker"])
        self.assertIn({"key": "kubernetes.io/arch", "operator": "In", "values": ["amd64"]}, exprs)

    def test_gpu_node_is_overflow_only(self):
        pod, _ = self.pod()
        pref = pod["spec"]["affinity"]["nodeAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"]
        self.assertEqual(pref, [{"weight": 100, "preference": {"matchExpressions": [
            {"key": "kubernetes.io/hostname", "operator": "NotIn", "values": ["ubuntu-server-k8s-agent-4"]}]}}])

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
if a[:2] == ["get", "pod"] and any(x.startswith("jsonpath=") for x in a):
    print(os.environ.get("FAKE_LABEL", "kgate"), end=""); sys.exit(0)
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

    def profile(self, tools="", extra="", secrets="", memory="1Gi"):
        (self.repo / "kgate.toml").write_text('image = "%s"\ncpu = 2\nmemory = "%s"\n%s\n[tools]\n%s\n[secrets]\n%s\n' % (DIGEST, memory, extra, tools, secrets))

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

    def test_overflow_node_pin_is_refused(self):
        done = self.kgate("--node", "ubuntu-server-k8s-agent-4", "--", "true")
        self.assertEqual(done.returncode, 69)
        self.assertIn("overflow", done.stdout)

    def test_never_node_is_refused(self):
        done = self.kgate("--node", "mac-mini-worker", "--", "true")
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

    def pod_resources(self):
        manifest = next(c["manifest"] for c in self.calls() if "manifest" in c)
        return manifest["items"][-1]["spec"]["containers"][0]["resources"]

    def test_request_and_limit_reach_the_pod_and_the_record(self):
        self.profile(memory="256Mi", extra='memory_limit = "512Mi"')
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.pod_resources(), {"requests": {"cpu": "2", "memory": "256Mi"}, "limits": {"memory": "512Mi"}})
        rec = self.records()[-1]
        self.assertEqual((rec["mem"], rec["mem_limit"]), ("256Mi", "512Mi"))
        self.assertIn("256Mi memory request, 512Mi limit", done.stdout)

    def test_without_memory_limit_the_limit_is_the_request(self):
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(self.pod_resources(), {"requests": {"cpu": "2", "memory": "1Gi"}, "limits": {"memory": "1Gi"}})
        rec = self.records()[-1]
        self.assertEqual((rec["mem"], rec["mem_limit"]), ("1Gi", "1Gi"))
        self.assertIn("1Gi memory request\n", done.stdout)

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
        self.assertEqual(self.pod_resources(), {"requests": {"cpu": "2", "memory": "512Mi"}, "limits": {"memory": "2Gi"}})

    def test_mem_above_the_profile_limit_is_refused(self):
        self.profile(memory="1Gi", extra='memory_limit = "2Gi"')
        done = self.kgate("--mem", "4Gi", "--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("memory_limit must be at least memory", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.calls()))

    def test_mem_limit_flag_sets_the_limit(self):
        self.assertEqual(self.kgate("--mem-limit", "3Gi", "--", "true").returncode, 0)
        self.assertEqual(self.pod_resources(), {"requests": {"cpu": "2", "memory": "1Gi"}, "limits": {"memory": "3Gi"}})

    def test_mem_limit_flag_below_the_request_is_refused(self):
        done = self.kgate("--mem-limit", "512Mi", "--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("memory_limit must be at least memory", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.calls()))

    # --- kgate cancel

    def active(self):
        return self.state / "kgate" / "active"

    def add_entry(self, job_id, run_id, pid, tamper_start=False, node="fake-node"):
        """A registry entry for the process `pid`, as the running client would have written it."""
        start, command = K.proc_identity(pid)
        self.active().mkdir(parents=True, exist_ok=True)
        (self.active() / (job_id + ".json")).write_text(json.dumps({
            "id": job_id, "job": run_id, "pid": pid, "start": "other" if tamper_start else start, "proc_cmd": command,
            "cwd": str(self.repo), "argv": ["kgate", "--", "sleep"], "cmd": "sleep 300", "node": node}))

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
             "KGATE_SSH": "fake", "KGATE_SSH_KEY": "/dev/null", "RUN_AND_WAKE_JOB": "20261104T000000Z-abcdef", **self.op_env()}
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


if __name__ == "__main__":
    unittest.main()
