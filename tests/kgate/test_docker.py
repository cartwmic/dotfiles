"""Docker jobs on the homelab (docs/kgate.md, "Docker jobs"): `services = ["docker"]` and a `[docker]` table give the job a privileged dind sidecar.

The profile and the pod spec are checked directly. The queue and the job journeys run the real script as a process against test_kgate.py's fake `ssh` (a
scripted cluster whose "pod" runs on this machine): FAKE_DOCKER says how the dind sidecar behaves (ready, crashes at start, dies after CMD), and FAKE_QUOTA_NAME
and FAKE_QUOTA_CLASS make the fake's ResourceQuota a scoped one, like the homelab's `kgate-docker` quota.
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_kgate as TK  # noqa: E402  (renders kgate once, and gives the fake ssh and op)

K = TK.K
DOCKER_IMG = "docker:29.9.3-dind@sha256:" + "dd" * 32
DOCKER_TABLE = '[docker]\nimage = "%s"\n' % DOCKER_IMG

# The client with the waits a test would otherwise sit through shortened: the quota retry, the queue's look at the cluster, and the re-read of the sidecar after CMD.
LAUNCH = ((TK.QUOTA_LAUNCH % 0).replace("@DELAYS@", "0.2, 0.4")
          .replace("sys.exit(", "K.DOCKER_SETTLE_S, K.DOCKER_SETTLE_POLL_S = 1.5, 0.1\nsys.exit(", 1))


def docker_profile(extra="", table=DOCKER_TABLE):
    return 'image = "%s"\ncpu = 2\nmemory = "1Gi"\nservices = ["docker"]\n%s\n%s' % (TK.DIGEST, extra, table)


class Profile(unittest.TestCase):
    def test_a_docker_profile_has_a_pinned_image_and_sizes_of_its_own(self):
        d = K.parse_profile(docker_profile())["docker"]
        self.assertEqual(d, {"image": DOCKER_IMG, "cpu": 2, "cpu_limit": None, "memory": "4Gi", "memory_limit": "4Gi", "ready_s": K.DOCKER_READY_S})
        d = K.parse_profile(docker_profile(table=DOCKER_TABLE + 'cpu = 4\ncpu_limit = 6\nmemory = "8Gi"\nmemory_limit = "16Gi"\nready_s = 30\n'))["docker"]
        self.assertEqual((d["cpu"], d["cpu_limit"], d["memory"], d["memory_limit"], d["ready_s"]), (4, 6, "8Gi", "16Gi", 30))
        self.assertIsNone(K.parse_profile("")["docker"])

    def test_a_docker_profile_is_refused_when_it_is_incomplete_or_wrong(self):
        bad = {
            "service without a table": 'services = ["docker"]',
            "table without the service": DOCKER_TABLE,
            "no image": docker_profile(table="[docker]\ncpu = 2\n"),
            "image not pinned": docker_profile(table='[docker]\nimage = "docker:29.9.3-dind"\n'),
            "unknown key": docker_profile(table=DOCKER_TABLE + "privileged = false\n"),
            "ready_s below 30": docker_profile(table=DOCKER_TABLE + "ready_s = 29\n"),
            "ready_s not a whole number": docker_profile(table=DOCKER_TABLE + "ready_s = 60.5\n"),
            "ready_s a bool": docker_profile(table=DOCKER_TABLE + "ready_s = true\n"),
            "cpu zero": docker_profile(table=DOCKER_TABLE + "cpu = 0\n"),
            "cpu_limit below cpu": docker_profile(table=DOCKER_TABLE + "cpu = 4\ncpu_limit = 2\n"),
            "memory not a size": docker_profile(table=DOCKER_TABLE + 'memory = "8G"\n'),
            "memory_limit below memory": docker_profile(table=DOCKER_TABLE + 'memory = "8Gi"\nmemory_limit = "4Gi"\n'),
        }
        for why, text in bad.items():
            with self.assertRaises(K.Unavailable, msg=why):
                K.parse_profile(text)

    def test_a_docker_job_always_runs_in_its_own_class_so_a_priority_class_with_it_is_refused(self):
        for key in ("kgate", "kgate-first", "kgate-main", "kgate-docker"):
            with self.assertRaises(K.Unavailable, msg=key) as e:
                K.parse_profile(docker_profile(extra='priority_class = "%s"' % key))
            self.assertIn("kgate-docker", str(e.exception))

    def test_a_kubectl_cluster_does_not_offer_docker(self):
        # the work profile's cluster: privileged pods are not for an employer's cluster (docs/kgate.md, "Docker jobs")
        for text in ('cluster = "example"\n' + docker_profile(), 'cluster = "example"\nservices = ["docker"]', 'cluster = "example"\n' + DOCKER_TABLE):
            with self.assertRaises(K.Unavailable, msg=text):
                K.parse_profile(text)

    def test_a_docker_profile_always_has_a_disk_request_and_a_limit_the_kubelet_enforces(self):
        # a Docker pod always has a disk bound the kubelet enforces: the profile gets the campaign default, not an error
        p = K.parse_profile(docker_profile())
        self.assertEqual((p["ephemeral_storage"], p["ephemeral_storage_limit"]), ("24Gi", "40Gi"), "no disk keys: the plan's campaign default")
        p = K.parse_profile(docker_profile(extra='ephemeral_storage = "50Gi"'))
        self.assertEqual((p["ephemeral_storage"], p["ephemeral_storage_limit"]), ("50Gi", "50Gi"), "a request above the default limit raises the limit with it, as for any homelab pod")
        p = K.parse_profile(docker_profile(extra='ephemeral_storage_limit = "30Gi"'))
        self.assertEqual((p["ephemeral_storage"], p["ephemeral_storage_limit"]), ("24Gi", "30Gi"))
        p = K.parse_profile(docker_profile(extra='ephemeral_storage = "6Gi"\nephemeral_storage_limit = "12Gi"'))
        self.assertEqual((p["ephemeral_storage"], p["ephemeral_storage_limit"]), ("6Gi", "12Gi"), "what the profile sets is kept")
        with self.assertRaises(K.Unavailable, msg="a limit below the Docker default request"):
            K.parse_profile(docker_profile(extra='ephemeral_storage_limit = "20Gi"'))
        for text in ('ephemeral_storage = "512Mi"\nephemeral_storage_limit = "12Gi"', 'ephemeral_storage = "2Gi"\nephemeral_storage_limit = "1Gi"'):
            with self.assertRaises(K.Unavailable, msg="the profile's disk is the pod's total: it must leave the job container something past the sidecar's own: " + text):
                K.parse_profile(docker_profile(extra=text))
        plain = K.parse_profile(TK.Profile.GOOD)
        self.assertEqual((plain["ephemeral_storage"], plain["ephemeral_storage_limit"]), (None, None), "a job without docker keeps today's defaults")

    def test_a_profile_without_the_service_is_as_before(self):
        self.assertIsNone(K.parse_profile(TK.Profile.GOOD)["docker"])
        self.assertEqual(K.parse_profile(TK.Profile.GOOD)["services"], [])


class PodSpec(unittest.TestCase):
    DOCKER = {"image": DOCKER_IMG, "cpu": 4, "cpu_limit": None, "memory": "8Gi", "memory_limit": "16Gi", "ready_s": 120}

    def pod(self, docker=DOCKER, **kw):
        manifests = K.pod_manifests("kgate-1-2", TK.DIGEST, 1, "2Gi", None, {}, None, memory_limit="4Gi", priority_class=K.DOCKER_CLASS, docker=docker, **kw)
        return manifests["items"][-1]["spec"]

    def test_the_sidecar_is_a_privileged_native_dind_sidecar_with_its_own_sizes_and_a_startup_probe(self):
        spec = self.pod()
        (side,) = spec["initContainers"]
        self.assertEqual((side["name"], side["image"], side["restartPolicy"]), ("dind", DOCKER_IMG, "Always"), "an init container that keeps running: the job starts when its probe passes")
        self.assertEqual(side["securityContext"], {"privileged": True})
        self.assertEqual(side["args"], ["dockerd", "--host=tcp://127.0.0.1:2375"], "the image's own entrypoint starts the daemon (args, not command), on the pod's loopback only")
        self.assertNotIn("command", side)
        env = {e["name"]: e["value"] for e in side["env"]}
        self.assertEqual(env, {"DOCKER_TLS_CERTDIR": "", "DOCKER_HOST": "tcp://127.0.0.1:2375"})
        self.assertEqual(side["startupProbe"]["exec"]["command"], ["docker", "info"])
        self.assertEqual(side["startupProbe"]["failureThreshold"] * side["startupProbe"]["periodSeconds"], 120)
        self.assertEqual(side["resources"], {"requests": {"cpu": "4", "memory": "8Gi", "ephemeral-storage": K.DOCKER_SIDECAR_DISK}, "limits": {"memory": "16Gi", "ephemeral-storage": K.DOCKER_SIDECAR_DISK_LIMIT}})

    def test_the_sidecar_has_no_host_path_no_socket_and_only_its_own_data_root(self):
        spec = self.pod()
        (side,) = spec["initContainers"]
        volumes = {v["name"]: v for v in spec["volumes"]}
        self.assertEqual(side["volumeMounts"], [{"name": "docker-data", "mountPath": "/var/lib/docker"}])
        self.assertEqual(volumes["docker-data"], {"name": "docker-data", "emptyDir": {"sizeLimit": "12Gi"}}, "the data root is in the pod's own disk, sized by the job's limit (the default 12Gi here), and goes with the pod")
        self.assertNotIn("docker.sock", json.dumps(side))
        mounted = {m["name"] for m in side["volumeMounts"]}
        self.assertFalse(any("hostPath" in volumes[n] for n in mounted))

    def test_the_job_container_is_not_privileged_keeps_the_cache_and_finds_the_daemon_on_the_pods_loopback(self):
        spec = self.pod()
        (job,) = spec["containers"]
        self.assertNotIn("privileged", json.dumps(job))
        self.assertNotIn("securityContext", job)
        self.assertIn({"name": "cache", "mountPath": "/cache"}, job["volumeMounts"])
        self.assertEqual({"name": "cache", "hostPath": {"path": "/var/lib/kgate/cache", "type": "DirectoryOrCreate"}}, next(v for v in spec["volumes"] if v["name"] == "cache"))
        self.assertNotIn("docker-data", {m["name"] for m in job["volumeMounts"]})
        self.assertIn({"name": "DOCKER_HOST", "value": "tcp://127.0.0.1:2375"}, job["env"])
        self.assertEqual(spec["priorityClassName"], "kgate-docker")

    def test_a_cpu_limit_is_rendered_on_the_sidecar_only_when_the_profile_sets_one(self):
        (side,) = self.pod(docker={**self.DOCKER, "cpu_limit": 6})["initContainers"]
        self.assertEqual(side["resources"]["limits"], {"memory": "16Gi", "cpu": "6", "ephemeral-storage": K.DOCKER_SIDECAR_DISK_LIMIT})

    def test_every_container_has_a_disk_request_and_limit_and_the_data_root_is_sized_by_the_jobs_limit(self):
        # the kubelet enforces the pod's disk only when EVERY container has a limit; the data root is the pod's biggest user of disk
        # the API server does not force these (a pod with none is admitted, and a quota counts it as 0), so the client sets both on every container
        spec = self.pod(ephemeral="24Gi", ephemeral_limit="40Gi")
        (job,), (side,) = spec["containers"], spec["initContainers"]
        every = spec["containers"] + spec["initContainers"]
        self.assertEqual(len(every), 2)
        for c in every:
            for kind in ("requests", "limits"):
                self.assertRegex(c["resources"][kind].get("ephemeral-storage", ""), r"^\d+(Mi|Gi)$", "%s %s" % (c["name"], kind))
        self.assertEqual((side["resources"]["requests"]["ephemeral-storage"], side["resources"]["limits"]["ephemeral-storage"]),
                         (K.DOCKER_SIDECAR_DISK, K.DOCKER_SIDECAR_DISK_LIMIT))
        # the profile's disk is the pod's total: the job container and the sidecar add up to it
        for kind, total in (("requests", "24Gi"), ("limits", "40Gi")):
            self.assertEqual(K.mem_bytes(job["resources"][kind]["ephemeral-storage"]) + K.mem_bytes(side["resources"][kind]["ephemeral-storage"]), K.mem_bytes(total), kind)
        self.assertEqual((job["resources"]["requests"]["ephemeral-storage"], job["resources"]["limits"]["ephemeral-storage"]), ("24064Mi", "39936Mi"))
        self.assertEqual(next(v for v in spec["volumes"] if v["name"] == "docker-data")["emptyDir"], {"sizeLimit": "40Gi"})

    def test_a_profiles_disk_limit_reaches_the_pod_through_the_whole_path(self):
        prof = K.parse_profile(docker_profile(extra='ephemeral_storage = "6Gi"\nephemeral_storage_limit = "12Gi"'))
        spec = self.pod(ephemeral=prof["ephemeral_storage"], ephemeral_limit=prof["ephemeral_storage_limit"])
        self.assertEqual(next(v for v in spec["volumes"] if v["name"] == "docker-data")["emptyDir"], {"sizeLimit": "12Gi"})
        self.assertEqual(spec["containers"][0]["resources"]["limits"]["ephemeral-storage"], "11264Mi", "12Gi in total less the sidecar's 1Gi")
        prof = K.parse_profile(docker_profile())   # nothing set: the campaign default, on both containers and the data root
        spec = self.pod(ephemeral=prof["ephemeral_storage"], ephemeral_limit=prof["ephemeral_storage_limit"])
        self.assertEqual(next(v for v in spec["volumes"] if v["name"] == "docker-data")["emptyDir"], {"sizeLimit": "40Gi"})
        self.assertEqual(spec["containers"][0]["resources"]["requests"]["ephemeral-storage"], "24064Mi", "24Gi in total less the sidecar's 512Mi")

    def test_a_pod_without_docker_has_no_sidecar_no_data_root_and_no_docker_host(self):
        spec = K.pod_manifests("kgate-1-2", TK.DIGEST, 2, "1Gi", None, {}, None)["items"][-1]["spec"]
        self.assertNotIn("initContainers", spec)
        self.assertEqual([v["name"] for v in spec["volumes"]], ["cache", "out"])
        self.assertNotIn("DOCKER_HOST", {e["name"] for e in spec["containers"][0]["env"]})


class Shape(unittest.TestCase):
    """What a pod asks of the cluster, as the queue sees it (blocks() and cluster_full())."""

    def test_a_docker_pods_shape_is_the_job_container_and_its_sidecar_together(self):
        spec = {"image": DOCKER_IMG, "cpu": 4, "cpu_limit": None, "memory": "8Gi", "memory_limit": "16Gi", "ready_s": 120}
        pod = K.pod_manifests("kgate-1-2", TK.DIGEST, 1, "2Gi", None, {}, None, ephemeral="24Gi", priority_class=K.DOCKER_CLASS, docker=spec)["items"][-1]
        shape = K.pod_shape(pod)
        self.assertEqual((shape["cpu"], shape["mem"], shape["disk"]), (5, 10 * 2**30, 24 * 2**30), "the profile's disk is the pod's total, sidecar included")
        self.assertEqual((shape["priority"], shape["class"]), (-100, "kgate-docker"))

    def test_a_one_container_pods_shape_is_unchanged(self):
        pod = K.pod_manifests("kgate-1-2", TK.DIGEST, 3, "6Gi", None, {}, None)["items"][-1]
        shape = K.pod_shape(pod)
        self.assertEqual((shape["cpu"], shape["mem"], shape["disk"], shape["pin"], shape["priority"]), (3, 6 * 2**30, 4 * 2**30, None, -100))
        self.assertEqual(shape["class"], "kgate")

    def test_only_an_init_container_that_keeps_running_counts(self):
        res = lambda cpu: {"resources": {"requests": {"cpu": cpu}}}
        pod = {"spec": {"containers": [res("1")], "initContainers": [dict(res("2"), restartPolicy="Always"), res("8")]}}   # the second init container runs first and ends
        self.assertEqual(K.pod_shape(pod)["cpu"], 3)

    def test_the_queue_ranks_a_docker_pod_with_the_ordinary_ones(self):
        self.assertEqual(K.PRIORITY_VALUES[K.DOCKER_CLASS], K.PRIORITY_VALUES[K.PRIORITY_CLASS])


class SidecarPeak(unittest.TestCase):
    """The dind sidecar is privileged and shares the node's cgroup namespace: its `/sys/fs/cgroup` is the node's root, so the peak is read from the cgroup /proc/self/cgroup names."""

    def read(self, root_files, container_files, self_cgroup):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d, "cgroup")
            for rel, files in (("", root_files), (self_cgroup.lstrip("/"), container_files)):
                (root / rel).mkdir(parents=True, exist_ok=True)
                for name, text in files.items():
                    (root / rel / name).write_text(text)
            Path(d, "self").write_text("0::%s\n" % self_cgroup)
            done = subprocess.run(["sh", "-c", K.SIDECAR_PEAK_SH, "sh", str(root), str(Path(d, "self"))], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            return done.stdout.decode().strip()

    def test_a_shared_cgroup_namespace_reads_the_containers_own_cgroup_not_the_nodes_root(self):
        path = "/kubepods.slice/pod1/cri-containerd-abc.scope"
        self.assertEqual(self.read({"memory.peak": "23949156352\n"}, {"memory.peak": "46563328\n"}, path), "46563328", "the node's root counts the whole machine")

    def test_a_node_whose_root_has_no_peak_file_still_gives_the_containers_number(self):
        path = "/kubepods.slice/pod1/cri-containerd-abc.scope"
        self.assertEqual(self.read({}, {"memory.current": "20439040\n"}, path), "20439040", "the node root has neither file, the container has memory.current only")

    def test_a_private_cgroup_namespace_reads_its_root_as_before(self):
        self.assertEqual(self.read({"memory.peak": "734003200\n"}, {}, "/"), "734003200")

    def test_nothing_readable_prints_nothing(self):
        self.assertEqual(self.read({}, {}, "/kubepods.slice/pod1/x.scope"), "")


class DockerJobs(unittest.TestCase):
    """One Docker job from the client to its exit, against the fake cluster."""
    for _name in ("kgate", "kgate_popen", "records", "calls", "op_env", "profile", "setUp"):
        locals()[_name] = getattr(TK.Black, _name)

    def launcher(self):
        return TK.stub_launcher(self.tmp, "docker_launch.py", LAUNCH)

    def use_docker(self, **kw):
        (self.repo / "kgate.toml").write_text(docker_profile(**kw))

    def manifest(self):
        return next(c["manifest"] for c in self.calls() if "manifest" in c)

    def reads_after_cmd(self):
        path = self.fake / "ended-reads"
        return int(path.read_text()) if path.exists() else 0

    def test_a_sidecar_that_never_becomes_ready_is_69_with_its_log_tail_and_cmd_not_run(self):
        # The homelab's start wait has to look at the sidecar (it did not, before: the homelab offered no services). A pod whose sidecar crash-loops stays Pending with
        # nothing else wrong, so without the look the job would wait out its whole --wait and say only "Pending".
        self.use_docker()
        done = self.kgate("--wait", "30", "--", "sh", "-c", "echo should-not-run", env={"FAKE_DOCKER": "crash"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("the docker sidecar did not become ready (exit 127, 1 restarts); its last log lines:", done.stdout)
        self.assertIn("fake dockerd log: cannot start", done.stdout)
        self.assertIn("(CMD not run)", done.stdout)
        self.assertNotIn("should-not-run", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["ran"], rec["cleanup"]), (69, False, True))
        self.assertIn("the docker sidecar did not become ready", rec["reason"])
        logs = [c["kubectl"] for c in self.calls() if c.get("kubectl", [""])[0] == "logs"]
        self.assertEqual([a[a.index("-c") + 1] for a in logs], ["dind"], "the tail is the sidecar's, not the job container's")

    def test_a_docker_job_runs_cmd_in_the_job_container_and_records_the_class_the_service_and_the_daemons_peak(self):
        self.use_docker()
        done = self.kgate("--", "sh", "-c", "echo ran-with-docker", env={"FAKE_DOCKER": "ready"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ran-with-docker", done.stdout)
        self.assertRegex(done.stdout, r"docker ready after [0-9.]+s")
        self.assertIn("peak dind 734003200 cgroup", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["services"], rec["priority_class"], rec["docker_peak"]), (0, ["docker"], "kgate-docker", 734003200))
        self.assertNotIn("docker_sidecar", rec)
        self.assertNotIn("restarted", done.stdout)
        calls = [c["kubectl"] for c in self.calls() if "kubectl" in c and c["kubectl"][0] == "exec"]
        self.assertTrue(all("-c" in a for a in calls), "every exec says which container: the pod has two")
        spec = self.manifest()["items"][-1]["spec"]
        self.assertEqual((spec["priorityClassName"], [c["name"] for c in spec["containers"]], [c["name"] for c in spec["initContainers"]]), ("kgate-docker", ["job"], ["dind"]))

    def test_the_sidecars_ready_wait_is_the_profiles(self):
        self.use_docker(table=DOCKER_TABLE + "ready_s = 45\n")
        self.kgate("--", "true", env={"FAKE_DOCKER": "ready"})
        probe = self.manifest()["items"][-1]["spec"]["initContainers"][0]["startupProbe"]
        self.assertEqual(probe["failureThreshold"] * probe["periodSeconds"], 45)

    def test_priority_class_from_the_environment_is_refused_with_a_docker_service(self):
        self.use_docker()
        done = self.kgate("--", "true", env={"KGATE_PRIORITY_CLASS": "kgate-main"})
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("kgate-docker", done.stdout)
        self.assertFalse(any("manifest" in c for c in self.calls()), "refused before anything was created")

    def test_a_sidecar_that_dies_after_cmd_started_leaves_cmds_exit_code_and_says_so(self):
        self.use_docker()
        done = self.kgate("--", "sh", "-c", "echo cmd-failed-by-itself; exit 3", env={"FAKE_DOCKER": "dies"})
        self.assertEqual(done.returncode, 3, done.stdout)
        self.assertIn("kgate: the docker daemon restarted during the job (1 restarts, last exit 137, reason OOMKilled); CMD's exit code is unchanged", done.stdout)
        self.assertIn("fake dockerd log: cannot start", done.stdout)
        rec = self.records()[-1]
        self.assertEqual((rec["exit"], rec["reason"], rec["ran"], rec["docker_sidecar"]), (3, None, True, {"restarts": 1, "exit": 137, "reason": "OOMKilled"}))
        self.assertNotIn("docker_peak", rec, "the cgroup the peak is read from is the new container's: unknown, not a small number")
        logs = [c["kubectl"] for c in self.calls() if c.get("kubectl", [""])[0] == "logs"]
        self.assertTrue(logs and "--previous" in logs[0], "the log of the container that died")

    def test_a_job_that_passed_keeps_its_exit_code_0_when_the_daemon_died_after_it(self):
        self.use_docker()
        done = self.kgate("--", "true", env={"FAKE_DOCKER": "dies"})
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("the docker daemon restarted during the job", done.stdout)
        self.assertEqual(self.records()[-1]["docker_sidecar"]["restarts"], 1)

    def test_a_daemon_the_kubelet_has_not_restarted_yet_is_still_named(self):
        self.use_docker()
        done = self.kgate("--", "sh", "-c", "exit 5", env={"FAKE_DOCKER": "stopped"})
        self.assertEqual(done.returncode, 5, done.stdout)
        self.assertIn("the docker daemon stopped during the job (0 restarts, last exit 137, reason OOMKilled)", done.stdout)
        self.assertEqual(self.records()[-1]["docker_sidecar"], {"restarts": 0, "exit": 137, "reason": "OOMKilled"})

    def test_a_death_the_kubelet_shows_a_moment_after_cmd_ended_is_not_missed(self):
        # round-3 review n1: a docker client is cut off the moment the daemon dies, and the pod's status changes about a second later. The status is read again for a few seconds.
        self.use_docker()
        done = self.kgate("--", "sh", "-c", "exit 125", env={"FAKE_DOCKER": "dies", "FAKE_DOCKER_LAG": "4"})
        self.assertEqual(done.returncode, 125, done.stdout)
        self.assertIn("the docker daemon restarted during the job", done.stdout)
        self.assertEqual(self.reads_after_cmd(), 5, "four reads said nothing, the fifth said restarted")

    def test_a_daemon_that_is_fine_is_read_once_when_cmd_passed_and_a_few_times_when_cmd_failed(self):
        self.use_docker()
        done = self.kgate("--", "true", env={"FAKE_DOCKER": "ready"})
        self.assertEqual((done.returncode, self.reads_after_cmd()), (0, 1), done.stdout)
        (self.fake / "ended-reads").unlink(missing_ok=True)
        (self.fake / "cmd-ended").unlink()
        done = self.kgate("--", "sh", "-c", "exit 4", env={"FAKE_DOCKER": "ready"})
        self.assertEqual(done.returncode, 4, done.stdout)
        self.assertGreater(self.reads_after_cmd(), 3, "a failed CMD gets the settle window")
        self.assertNotIn("docker daemon", done.stdout.replace("docker daemon ready", ""))
        self.assertNotIn("docker_sidecar", self.records()[-1])

    def test_a_job_whose_cmd_never_started_says_nothing_about_the_daemon(self):
        self.use_docker()
        done = self.kgate("--", "true", env={"FAKE_DOCKER": "dies", "FAKE_TAMPER": str(self.repo / "tracked.txt")})   # the tree differs in the pod: CMD is not run
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("tree hash differs", done.stdout)
        self.assertNotIn("docker daemon", done.stdout)
        self.assertEqual((self.reads_after_cmd(), "docker_sidecar" in self.records()[-1]), (0, False))

    def test_a_pod_without_the_service_is_not_read_for_a_sidecar(self):
        (self.repo / "kgate.toml").write_text('image = "%s"\ncpu = 2\nmemory = "1Gi"\n' % TK.DIGEST)
        done = self.kgate("--", "sh", "-c", "exit 4", env={"FAKE_DOCKER": "dies"})
        self.assertEqual(done.returncode, 4, done.stdout)
        self.assertNotIn("docker", done.stdout)
        rec = self.records()[-1]
        self.assertTrue("services" not in rec and "docker_sidecar" not in rec and "docker_peak" not in rec, rec)
        self.assertEqual(self.reads_after_cmd(), 0)

    def test_the_other_services_are_still_refused_on_the_homelab(self):
        (self.repo / "kgate.toml").write_text('image = "%s"\nservices = ["mssql"]\n' % TK.DIGEST)
        done = self.kgate("--", "true")
        self.assertEqual(done.returncode, 69, done.stdout)
        self.assertIn("needs mssql", done.stdout)

    def test_a_pod_the_job_never_gets_is_still_deleted_with_its_secrets(self):
        self.use_docker()
        done = self.kgate("--wait", "30", "--", "true", env={"FAKE_DOCKER": "crash"})
        self.assertEqual(done.returncode, 69, done.stdout)
        deleted = (self.fake / "deleted-pods").read_text().split()
        self.assertEqual(deleted, [self.records()[-1]["id"]])


class DockerQueue(unittest.TestCase):
    """The queue rule (coordinator decision #5350): a ticket a quota refused holds back only the jobs that quota counts. The fake cluster's ResourceQuota is 4 CPU; a Docker
    job asks 4 (the job container's 2 and the sidecar's 2) and so does an ordinary job (2, raised to a slot of 4). `kgate-docker` is scoped to its class; `kgate-cpu` is not."""
    for _name in ("kgate", "kgate_popen", "records", "calls", "op_env", "profile"):
        locals()[_name] = getattr(TK.Black, _name)
    for _name in ("read_until", "start", "creates"):
        locals()[_name] = getattr(TK.QueueHomelab, _name)
    for _name in ("created", "room"):
        locals()[_name] = getattr(TK.QuotaHomelab, _name)

    def launcher(self):
        return TK.stub_launcher(self.tmp, "docker_queue_launch.py", LAUNCH)

    def setUp(self):
        TK.Black.setUp(self)
        (self.tmp / "docker.toml").write_text(docker_profile())
        (self.tmp / "plain.toml").write_text('image = "%s"\ncpu = 2\nmemory = "1Gi"\n' % TK.DIGEST)

    def quota(self, name, scoped, used=4):
        (self.fake / "quota-full").write_text(str(used))
        env = {"FAKE_QUOTA_CPU": "4", "FAKE_QUOTA_NAME": name, "FAKE_QUOTA_HOLD": "1", "FAKE_DOCKER": "ready"}
        return {**env, "FAKE_QUOTA_CLASS": "kgate-docker"} if scoped else env

    def job(self, kind, env, say, wait="60"):
        """A job of that kind (docker or plain) started and left running: the process."""
        return self.start("--wait", wait, "--profile", str(self.tmp / (kind + ".toml")), "--", "sh", "-c", "echo %s-ran" % say, env=env)

    def waiting_first(self, kind, env):
        """A job the quota refuses (it is full), started and waiting in the queue: the process and its ticket."""
        proc = self.job(kind, env, "first")
        self.read_until(proc, "queued: waiting for quota")
        (path,) = (self.state / "kgate" / "queue").glob("kgate-*.json")
        return proc, path

    def finish(self, *procs):
        outs = [p.communicate(timeout=90)[0] for p in procs]
        self.assertEqual([p.returncode for p in procs], [0] * len(procs), "".join(outs))
        return outs

    def test_a_docker_job_the_docker_quota_refuses_does_not_hold_back_an_ordinary_job(self):
        env = self.quota("kgate-docker", scoped=True)
        first, ticket = self.waiting_first("docker", env)
        self.assertEqual(json.loads(ticket.read_text())["quota"], "kgate-docker", "the ticket names the quota that refused it")
        done = self.kgate("--wait", "30", "--profile", str(self.tmp / "plain.toml"), "--", "sh", "-c", "echo ordinary-ran", env=env)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("ordinary-ran", done.stdout)
        self.assertNotIn("queued", done.stdout)
        self.assertIsNone(first.poll(), "the docker job is still waiting for its quota")
        self.assertEqual(self.created(), 1)
        self.room()
        (out,) = self.finish(first)
        self.assertIn("first-ran", out)

    def test_a_second_docker_job_waits_behind_the_first_the_docker_quota_refused(self):
        env = self.quota("kgate-docker", scoped=True)
        first, ticket = self.waiting_first("docker", env)
        second = self.job("docker", env, "second")
        seen = self.read_until(second, "queued: behind %s, which the quota refused and was first" % ticket.stem)
        self.assertEqual((self.created(), second.poll()), (0, None), "no pod is made ahead of the docker job the quota refused")
        self.room()
        outs = self.finish(first, second)
        self.assertIn("first-ran", outs[0])
        self.assertIn("second-ran", seen + outs[1])
        made = [c["created"] for c in self.calls() if "created" in c]
        self.assertEqual((len(made), made[0]), (2, ticket.stem), "the job the quota refused first is the first pod the cluster accepts")

    def test_a_job_an_unscoped_quota_refused_holds_back_ordinary_and_docker_jobs_alike(self):
        env = self.quota("kgate-cpu", scoped=False)
        first, ticket = self.waiting_first("plain", env)
        held = [self.job(kind, env, "later") for kind in ("plain", "docker")]
        for proc in held:
            self.read_until(proc, "queued: behind %s, which the quota refused and was first" % ticket.stem)
        self.assertEqual((self.created(), [p.poll() for p in held]), (0, [None, None]))
        self.room()
        self.finish(first, *held)

    def planted(self, quota):
        """A live ticket from an older job that asks for more than any job here, so only its quota mark can hold a job back. Replaces the one before."""
        holder = subprocess.Popen(["sleep", "60"])
        self.addCleanup(lambda: (holder.kill(), holder.wait()))
        queue = self.state / "kgate" / "queue"
        queue.mkdir(parents=True, exist_ok=True)
        entry = {"id": "kgate-1-1", "pid": holder.pid, "start": K.proc_identity(holder.pid)[0], "pidns": K.pid_namespace(), "t": 1.0, "quota": quota,
                 "shape": {"cpu": 12.0, "mem": float(1 << 30), "disk": float(4 << 30), "pin": None, "priority": -100}}
        (queue / "kgate-1-1.json").write_text(json.dumps(entry))

    def test_a_ticket_from_an_older_client_or_naming_a_quota_this_client_does_not_know_holds_everyone_as_before(self):
        for quota in (True, "some-other-quota"):
            with self.subTest(quota=quota):
                self.planted(quota)
                for kind in ("plain", "docker"):
                    done = self.kgate("--wait", "2", "--profile", str(self.tmp / (kind + ".toml")), "--", "true", env={"FAKE_DOCKER": "ready"})
                    self.assertEqual(done.returncode, 69, done.stdout)
                    self.assertIn("queued: behind kgate-1-1, which the quota refused and was first", done.stdout)
                self.assertEqual(self.created(), 0)

    def test_a_scoped_quota_ticket_that_names_the_docker_class_holds_back_only_docker_jobs(self):
        self.planted("kgate-docker")
        ordinary = self.kgate("--wait", "20", "--profile", str(self.tmp / "plain.toml"), "--", "sh", "-c", "echo ordinary-ran", env={"FAKE_DOCKER": "ready"})
        self.assertEqual(ordinary.returncode, 0, ordinary.stdout)
        self.assertNotIn("queued", ordinary.stdout)
        docker = self.kgate("--wait", "2", "--profile", str(self.tmp / "docker.toml"), "--", "true", env={"FAKE_DOCKER": "ready"})
        self.assertEqual(docker.returncode, 69, docker.stdout)
        self.assertIn("queued: behind kgate-1-1, which the quota refused and was first", docker.stdout)


if __name__ == "__main__":
    unittest.main()
