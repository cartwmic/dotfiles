#!/usr/bin/env python3
"""Claude Code Stop hook for the builder seat: refuse to stop while a run-and-wake job or a kgate job that this T3 thread started is still running.

Mistake it ends (Retro proposal 12, playbook rule 19e13f7b): a builder starts a job, ends its session and hands off while the job still
runs, so nobody reads the result. Exit 2 with the reason on stderr keeps the session going; the reason names each running job and how to wait on it.

Which jobs count: only those started from this thread. The thread is T3CODE_THREAD_ID, which both tools record:
  run-and-wake  log.jsonl `start` record, field `thread` (set when the job is woken through T3); the hook names `run-and-wake --wait <job>` as the way to wait
  kgate         <state>/active/<id>.json (the running-jobs registry), field `thread`; a kgate job that run-and-wake started is listed once, as the run-and-wake job
A job counts as running when its process is alive, not when a record merely lacks an end line:
  run-and-wake  no `end` record, same boot, pid alive, and (on Linux) RUN_AND_WAKE_JOB=<job> in that process's environment, so a recycled pid is not taken for the job
  kgate         the entry's client pid has the same start time and command as the entry, in the same pid namespace (what `kgate cancel` checks)
Another thread's jobs, jobs that ended, and jobs whose process is gone never block. With no T3CODE_THREAD_ID (not a T3 session) it allows the stop.
It fails open: any error reading a record or the input allows the stop, so a fault here never traps an agent.

Input: the hook JSON on stdin (not read; only the environment names the thread). Output: exit 2 and the reason on stderr, else exit 0.
With `--count` it only counts: it prints the number of this thread's running jobs (run-and-wake and kgate, each job once) and exits 0, and refuses nothing.
The lead's turn-end check (`coordinator t3 turn-end --jobs N`) takes that number as a fact, so the coordinator holds no run-and-wake or kgate paths.
Test hooks: RUN_AND_WAKE_STATE and KGATE_STATE override the state folders; STOP_JOBS_THREAD overrides T3CODE_THREAD_ID.
"""
import json
import os
import sys

BOOT_ID_FILE = "/proc/sys/kernel/random/boot_id"


def state_dir(env_name, tool):
    return os.environ.get(env_name) or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), tool)


def proc_identity(pid):
    """(start, command) of the live process `pid`, or None when it is gone (a zombie counts as gone). Same pair kgate stores in its registry."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    if os.path.isdir("/proc/self"):
        try:
            with open("/proc/%d/stat" % pid) as f:
                fields = f.read().rsplit(")", 1)[1].split()
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                command = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
        except (OSError, IndexError):
            return None
        return None if fields[0] == "Z" else (fields[19], command)
    import re
    import subprocess
    done = subprocess.run(["ps", "-ww", "-o", "stat=,lstart=,command=", "-p", str(pid)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          env={**os.environ, "LC_ALL": "C"})
    m = re.match(r"\s*(\S+)\s+(\w{3} \w{3} [ \d]\d \d\d:\d\d:\d\d \d{4})\s+(.*)", done.stdout.decode(errors="replace").strip())
    return None if not m or m.group(1).startswith("Z") else (m.group(2), m.group(3))


def pid_namespace():
    try:
        return os.readlink("/proc/self/ns/pid")
    except OSError:
        return None


def boot_id():
    try:
        with open(BOOT_ID_FILE) as f:
            return f.read().strip()
    except OSError:
        return None


def has_job_env(pid, job):
    """True when the process carries RUN_AND_WAKE_JOB=<job>. Where its environment cannot be read (another user, macOS) the pid check alone stands."""
    try:
        with open("/proc/%d/environ" % pid, "rb") as f:
            env = f.read().split(b"\0")
    except OSError:
        return True
    return ("RUN_AND_WAKE_JOB=" + job).encode() in env


def run_and_wake_jobs(thread):
    """Running run-and-wake jobs started by `thread`: a list of dicts (job, pid, ts, cmd)."""
    path = os.path.join(state_dir("RUN_AND_WAKE_STATE", "run-and-wake"), "log.jsonl")
    try:
        with open(path, errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    starts = {}
    for line in lines:
        if thread in line and '"start"' in line:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("event") == "start" and r.get("thread") == thread and isinstance(r.get("job"), str):
                starts[r["job"]] = r
    if not starts:
        return []
    ended = set()
    for line in lines:
        if '"end"' in line and any(j in line for j in starts):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict) and r.get("event") == "end":
                ended.add(r.get("job"))
    boot = boot_id()
    found = []
    for job, r in starts.items():
        pid = r.get("pid")
        if job in ended or proc_identity(pid) is None:
            continue
        if r.get("boot") and boot and r["boot"] != boot:
            continue
        if not has_job_env(pid, job):
            continue
        cmd = r.get("cmd")
        found.append({"job": job, "pid": pid, "ts": r.get("ts"), "cmd": " ".join(cmd) if isinstance(cmd, list) else str(cmd)})
    return found


def kgate_jobs(thread):
    """Running kgate jobs started by `thread`: a list of dicts (id, job, pid, cmd). Entries are the registry's: one file per running client."""
    folder = os.path.join(state_dir("KGATE_STATE", "kgate"), "active")
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    ns = pid_namespace()
    found = []
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name)) as f:
                e = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(e, dict) or e.get("thread") != thread or e.get("id") != name[:-5] or not isinstance(e.get("pid"), int):
            continue
        if e.get("pidns") != ns or proc_identity(e["pid"]) != (e.get("start"), e.get("proc_cmd")):
            continue
        found.append({"id": e["id"], "job": e.get("job"), "pid": e["pid"], "cmd": e.get("cmd")})
    return found


def wait_hint(pid, platform=None):
    """How to wait for `pid` without polling. `tail --pid` is GNU only (BSD tail on macOS rejects it); macOS's `caffeinate -w <pid>` blocks until the pid exits."""
    command = "caffeinate -w %d" % pid if (platform or sys.platform) == "darwin" else "tail --pid=%d -f /dev/null" % pid
    return "wait: run `%s` with Bash run_in_background, then t3_background_wait on its task id (no sleep loop)" % command


def run_and_wake_wait_hint(job):
    """How to wait for a run-and-wake job: `run-and-wake --wait <job>` blocks until it ends and prints the result line, and the job's own wake message is then not sent
    (a second message after the result would be a no-news turn). The same text is in `wait_command` in dot_local/bin/executable_run-and-wake; tests/run-and-wake checks that the two agree."""
    return "wait: run `run-and-wake --wait %s` with Bash run_in_background, then t3_background_wait on its task id (no sleep loop); it prints the result and exits with the job's status" % job


def reason(rw, kg):
    lines = ["Do not stop yet: this session started %d job%s that %s still running. Read each result before you hand off." % (
        len(rw) + len(kg), "" if len(rw) + len(kg) == 1 else "s", "is" if len(rw) + len(kg) == 1 else "are")]
    for j in rw:
        lines.append("- run-and-wake job %s (pid %s, started %s): %s\n    %s; the full record is `grep %s ~/.local/state/run-and-wake/log.jsonl`" % (
            j["job"], j["pid"], j["ts"], j["cmd"], run_and_wake_wait_hint(j["job"]), j["job"]))
    for j in kg:
        lines.append("- kgate job %s (client pid %s): %s\n    %s; the result is the record in ~/.local/state/kgate/log.jsonl; to stop it instead: `kgate cancel %s`" % (
            j["id"], j["pid"], j["cmd"], wait_hint(j["pid"]), j["id"]))
    return "\n".join(lines)


def main(argv=()):
    thread = os.environ.get("STOP_JOBS_THREAD") or os.environ.get("T3CODE_THREAD_ID")
    if not thread:
        if "--count" in argv:
            print(0)
        return 0
    rw = run_and_wake_jobs(thread)
    seen = {j["job"] for j in rw}
    kg = [j for j in kgate_jobs(thread) if j["job"] not in seen]
    if "--count" in argv:
        print(len(rw) + len(kg))
        return 0
    if not rw and not kg:
        return 0
    sys.stderr.write(reason(rw, kg) + "\n")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception:
        if "--count" in sys.argv[1:]:
            print(0)
        sys.exit(0)
