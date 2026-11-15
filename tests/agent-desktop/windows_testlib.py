"""Shared helpers for test_windows_files.py and test_windows_bridge.py: run the Windows scripts under PowerShell 7 on Linux.

Nothing here touches a real desktop. The scripts run with LOCALAPPDATA, USERPROFILE and HOME pointed at a temp folder, a stub
`ScheduledTasks` module on PSModulePath (the real module exists only on Windows), and stub `curl.exe` and `tar.exe` on PATH.
pwsh must be on PATH (under `mise exec aqua:PowerShell/PowerShell@7.7.0 --` locally; on GitHub's runner it is installed).
A missing pwsh is a failure, never a skip.
"""
import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WINDOWS = REPO / "windows"
VERSION = "1.3.1"
ASSET = "agent-desktop-v%s-x86_64-pc-windows-msvc.tar.gz" % VERSION
RELEASE = "https://github.com/vercel-labs/agent-desktop/releases/download/v%s" % VERSION
TASK_NAME = "agent-desktop"
EIGHT = ("shot", "windows", "focus", "move", "click", "type", "key", "cursor")

STUB_MODULE = r'''
# Stand-in for the Windows ScheduledTasks module. State lives in $env:AD_STUB_STATE.
# The module is slow to load on Windows (over a second), so the agent-desktop client must never call it: every call is logged
# as "module <Name>" and the bridge tests assert there are none during a call. install.ps1 may use it.
$script:State = $env:AD_STUB_STATE
function Write-Call([string]$Text) { Add-Content -LiteralPath (Join-Path $script:State 'calls.log') -Value $Text }
function New-ScheduledTaskAction { param([string]$Execute, [string]$Argument)
    [pscustomobject]@{ Execute = $Execute; Arguments = $Argument } }
function New-ScheduledTaskPrincipal { param([string]$UserId, [string]$LogonType, [string]$RunLevel)
    [pscustomobject]@{ UserId = $UserId; LogonType = $LogonType; RunLevel = $RunLevel } }
function New-ScheduledTaskTrigger { param([switch]$AtLogOn, [string]$User)
    [pscustomobject]@{ Type = $(if ($AtLogOn) { 'LogOn' } else { 'Other' }); UserId = $User } }
function New-ScheduledTaskSettingsSet { param([string]$MultipleInstances, [switch]$AllowStartIfOnBatteries,
        [switch]$DontStopIfGoingOnBatteries, $ExecutionTimeLimit)
    # the real module reports the limit as an ISO 8601 duration, and zero as PT0S
    $limit = 'PT0S'
    if ($ExecutionTimeLimit -and $ExecutionTimeLimit.TotalSeconds -gt 0) { $limit = 'PT' + [int]$ExecutionTimeLimit.TotalMinutes + 'M' }
    [pscustomobject]@{ MultipleInstances = $MultipleInstances; AllowStartIfOnBatteries = [bool]$AllowStartIfOnBatteries
        DontStopIfGoingOnBatteries = [bool]$DontStopIfGoingOnBatteries; ExecutionTimeLimit = $limit } }
function Register-ScheduledTask { param([string]$TaskName, $Action, $Principal, $Settings, $Trigger, [switch]$Force)
    Write-Call "Register-ScheduledTask $TaskName"
    $task = [pscustomobject]@{ TaskName = $TaskName; Actions = @($Action); Principal = $Principal; Settings = $Settings
        Triggers = @($Trigger | Where-Object { $_ }); HasTrigger = ($null -ne $Trigger) }
    ConvertTo-Json -InputObject $task -Depth 5 | Set-Content -LiteralPath (Join-Path $script:State 'task.json') -Encoding UTF8
    $task
}
function Get-ScheduledTask { [CmdletBinding()] param([string]$TaskName)
    Write-Call "module Get-ScheduledTask"
    $f = Join-Path $script:State 'task.json'
    if (-not (Test-Path -LiteralPath $f)) { Write-Error "No MSFT_ScheduledTask objects found with property 'TaskName' equal to '$TaskName'"; return }
    ConvertFrom-Json (Get-Content -LiteralPath $f -Raw)
}
function Start-ScheduledTask { param([string]$TaskName) Write-Call "module Start-ScheduledTask $TaskName" }
function Unregister-ScheduledTask { param([string]$TaskName, $Confirm) Write-Call "module Unregister-ScheduledTask $TaskName" }
Export-ModuleMember -Function *
'''

# Stand-in for schtasks.exe, which is what the client and install.ps1 use to start and end the task (43 ms against 1.1 s for the
# module). Modes, from AD_STUB_MODE: absent (no such task: /Run and /Query exit 1), none (starts nothing), answer (writes the
# answer to the oldest request at once), registered (runs the action install.ps1 registered as a background worker, as the real
# task does, unless a worker is still running: the task allows one instance).
SCHTASKS_STUB = r'''#!/usr/bin/env python3
import json, os, shlex, subprocess, sys

state = os.environ["AD_STUB_STATE"]
mode = os.environ.get("AD_STUB_MODE", "none")
args = sys.argv[1:]
verb = args[0].lower() if args else ""
name = args[args.index("/TN") + 1] if "/TN" in args else ""

def log(text):
    with open(os.path.join(state, "calls.log"), "a") as f:
        f.write(text + "\n")

def alive(pid):
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False

def workers():
    path = os.path.join(state, "workers.pids")
    pids = [int(x) for x in open(path).read().split()] if os.path.exists(path) else []
    return [p for p in pids if alive(p)]

log("schtasks %s %s" % (args[0] if args else "", name))
if verb == "/query":
    if mode == "absent":
        sys.stderr.write("ERROR: The system cannot find the file specified.\n"); sys.exit(1)
    print("TaskName Next Run Time Status"); sys.exit(0)
if verb == "/end":
    for pid in workers():
        os.kill(pid, 9)
    sys.exit(0)
if verb != "/run":
    sys.stderr.write("stub schtasks: unsupported %s\n" % verb); sys.exit(2)
if mode == "absent":
    sys.stderr.write("ERROR: The system cannot find the file specified.\n"); sys.exit(1)
local = os.path.join(os.environ["LOCALAPPDATA"], "agent-desktop")
if mode == "answer":
    requests = sorted(n for n in os.listdir(local) if n.startswith("request-") and n.endswith(".json")) if os.path.isdir(local) else []
    if requests:
        src = os.path.join(local, requests[0])
        with open(src) as f: data = f.read()
        with open(os.path.join(state, "seen-request.json"), "w") as f: f.write(data)
        rid = requests[0][len("request-"):-len(".json")]
        answer = {"exit": int(os.environ.get("AD_STUB_EXIT", "0")), "stdout": os.environ.get("AD_STUB_STDOUT", ""), "stderr": os.environ.get("AD_STUB_STDERR", "")}
        tmp = os.path.join(local, "answer-%s.tmp" % rid)
        with open(tmp, "w") as f: json.dump(answer, f)
        os.rename(tmp, os.path.join(local, "answer-%s.json" % rid))
    sys.exit(0)
if mode == "registered":
    if workers():
        log("schtasks ignored: a worker is running (one instance only)"); sys.exit(0)
    with open(os.path.join(state, "task.json")) as f: task = json.load(f)
    action = task["Actions"][0]
    if action["Execute"] != "powershell.exe":
        sys.stderr.write("unexpected task program %s\n" % action["Execute"]); sys.exit(1)
    argline = action["Arguments"].replace("-WindowStyle Hidden ", "")
    env = {k: os.environ[k] for k in ("PATH", "HOME", "USERPROFILE", "LOCALAPPDATA", "USERNAME", "USERDOMAIN", "COMPUTERNAME") if k in os.environ}
    pwsh = None
    for d in os.environ["PATH"].split(os.pathsep):
        if os.path.isfile(os.path.join(d, "pwsh")): pwsh = os.path.join(d, "pwsh"); break
    out = open(os.path.join(state, "worker-output.txt"), "a")
    proc = subprocess.Popen([pwsh] + shlex.split(argline), env=env, cwd=os.environ["AD_STUB_WORKER_CWD"], stdout=out, stderr=out, stdin=subprocess.DEVNULL, start_new_session=True)
    with open(os.path.join(state, "workers.pids"), "a") as f: f.write("%d\n" % proc.pid)
    log("worker started pid-recorded")
sys.exit(0)
'''

CURL_STUB = r'''#!/bin/sh
# stub curl.exe: curl.exe ... -o FILE URL. Serves the files in $AD_STUB_RELEASE by URL basename and logs every call.
out=""; url=""
while [ $# -gt 0 ]; do
  case $1 in
    -o|--output) out=$2; shift 2 ;;
    http*) url=$1; shift ;;
    *) shift ;;
  esac
done
echo "curl $url" >> "$AD_STUB_STATE/calls.log"
src="$AD_STUB_RELEASE/${url##*/}"
[ -f "$src" ] || { echo "curl: (22) 404 $url" >&2; exit 22; }
cp "$src" "$out"
'''

TAR_STUB = r'''#!/bin/sh
echo "tar $*" >> "$AD_STUB_STATE/calls.log"
exec /usr/bin/tar "$@"
'''

REG_STUB = r'''#!/bin/sh
# stub reg.exe for HKCU\Environment: the user PATH value lives in $AD_STUB_STATE/user-path.txt, its kind in user-path.kind
echo "reg $*" >> "$AD_STUB_STATE/calls.log"
case $1 in
  query)
    [ -f "$AD_STUB_STATE/user-path.txt" ] || { echo "ERROR: The system was unable to find the specified registry key or value." >&2; exit 1; }
    kind=REG_EXPAND_SZ; [ -f "$AD_STUB_STATE/user-path.kind" ] && kind=$(cat "$AD_STUB_STATE/user-path.kind")
    printf '\nHKEY_CURRENT_USER\\Environment\n    Path    %s    %s\n\n' "$kind" "$(cat "$AD_STUB_STATE/user-path.txt")" ;;
  add)
    shift
    while [ $# -gt 0 ]; do
      case $1 in
        /t) printf '%s' "$2" > "$AD_STUB_STATE/user-path.kind"; shift 2 ;;
        /d) printf '%s' "$2" > "$AD_STUB_STATE/user-path.txt"; shift 2 ;;
        *) shift ;;
      esac
    done
    echo "The operation completed successfully." ;;
esac
'''

TASKLIST_STUB = r'''#!/bin/sh
# stub tasklist: prints what the real one prints for /FI "IMAGENAME eq LogonUI.exe", from $AD_STUB_TASKLIST (default: no process)
echo "tasklist $*" >> "$AD_STUB_STATE/calls.log"
if [ -n "$AD_STUB_TASKLIST" ]; then
  echo "Image Name                     PID Session Name        Session#    Mem Usage"
  echo "========================= ======== ================ =========== ============"
  echo "$AD_STUB_TASKLIST"
else
  echo "INFO: No tasks are running which match the specified criteria."
fi
'''

UI_STUB = r'''#!/bin/sh
# stub for Vercel's agent-desktop.exe: records its argv, one bracketed word per argument, next to itself.
# It reads nothing from the environment, because the scheduled task's environment is not the caller's.
d=$(dirname "$0")
line=""
for a in "$@"; do line="$line [$a]"; done
echo "$line" >> "$d/ui-calls.txt"
echo "stub ui out"
echo "stub ui err" >&2
if [ -f "$d/ui-exit" ]; then exit "$(cat "$d/ui-exit")"; fi
exit 0
'''


def pwsh():
    path = shutil.which("pwsh")
    if not path:
        raise AssertionError("pwsh is not on PATH. Run under: mise exec aqua:PowerShell/PowerShell@7.7.0 -- python3 -m unittest ...")
    return path


def executable(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def release_files(directory, checksum_ok=True):
    """Make a fake Vercel release: the archive with a stub agent-desktop.exe in it, and checksums.txt."""
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / ASSET
    buf = io.BytesIO()
    data = b"#!/bin/sh\necho vercel stub\n"
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo("agent-desktop.exe")
        info.size = len(data)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(data))
    archive.write_bytes(buf.getvalue())
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if not checksum_ok:
        digest = "0" * 64
    other = hashlib.sha256(b"other").hexdigest()
    (directory / "checksums.txt").write_text("%s  agent-desktop-v%s-aarch64-apple-darwin.tar.gz\n%s  %s\n" % (other, VERSION, digest, ASSET))
    return archive


class Sandbox:
    """A throwaway Windows-like home: USERPROFILE, LOCALAPPDATA, stub task module, stub curl.exe and tar.exe."""

    def __init__(self, testcase):
        self.tmp = Path(tempfile.mkdtemp(prefix="rad-win-"))
        testcase.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        self.local = self.home / "AppData" / "Local"
        self.state = self.tmp / "state"       # the stub task module's state
        self.release = self.tmp / "release"
        self.stubbin = self.tmp / "stubbin"
        self.mods = self.tmp / "modules"
        self.elsewhere = self.tmp / "elsewhere"   # the worker's and the caller's other working folders
        self.work = self.tmp / "work"
        for d in (self.home, self.local, self.state, self.stubbin, self.mods / "ScheduledTasks", self.elsewhere, self.work):
            d.mkdir(parents=True, exist_ok=True)
        (self.mods / "ScheduledTasks" / "ScheduledTasks.psm1").write_text(STUB_MODULE)
        executable(self.stubbin / "curl.exe", CURL_STUB)
        executable(self.stubbin / "tar.exe", TAR_STUB)
        executable(self.stubbin / "reg.exe", REG_STUB)
        executable(self.stubbin / "schtasks.exe", SCHTASKS_STUB)
        executable(self.stubbin / "tasklist", TASKLIST_STUB)
        self.ui_calls = self.tmp / "ui-calls.txt"
        self.ui_exe = self.tmp / "ui-stub.exe"
        executable(self.ui_exe, UI_STUB)
        self.bin = self.home / ".local" / "bin"
        self.vercel = self.home / ".local" / "share" / "agent-desktop" / "vercel"
        self.log = self.local / "agent-desktop" / "agent-desktop.log"
        self.processes = []
        testcase.addCleanup(self.stop_processes)

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("AGENT_DESKTOP_")}
        env.update(
            HOME=str(self.home), USERPROFILE=str(self.home), LOCALAPPDATA=str(self.local),
            USERNAME="michael", USERDOMAIN="WORKGROUP", COMPUTERNAME="G14",  # USERDOMAIN as an OpenSSH session sets it
            PSModulePath=str(self.mods), AD_STUB_STATE=str(self.state), AD_STUB_RELEASE=str(self.release),
            AD_STUB_WORKER_CWD=str(self.elsewhere),
            PATH=os.pathsep.join([str(self.stubbin), env["PATH"]]),
        )
        env.update(extra)
        return env

    def run(self, script, *args, env=None, cwd=None, timeout=120):
        """Run a script with pwsh -File and return the CompletedProcess (text mode)."""
        return subprocess.run([pwsh(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
                              capture_output=True, text=True, env=env or self.env(), cwd=str(cwd or self.work), timeout=timeout)

    def install(self, source=None, **extra):
        """Run windows/install.ps1 (or the copy in `source`) with the release served from self.release."""
        env = self.env(**extra)
        return self.run((source or WINDOWS) / "install.ps1", env=env)

    def user_path(self):
        f = self.state / "user-path.txt"
        return f.read_text() if f.exists() else None

    def ui_argv_lines(self):
        return self.ui_calls.read_text().splitlines() if self.ui_calls.exists() else []

    def set_ui_exit(self, code):
        (self.tmp / "ui-exit").write_text(str(code))

    def calls(self):
        f = self.state / "calls.log"
        return f.read_text().splitlines() if f.exists() else []

    def task(self):
        return json.loads((self.state / "task.json").read_text())

    def log_lines(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def state_files(self):
        d = self.local / "agent-desktop"
        return sorted(p.name for p in d.iterdir()) if d.exists() else []

    def start_fake_lock_screen(self):
        """A process named LogonUI, which is what Windows runs while the screen is locked."""
        fake = self.tmp / "LogonUI"
        shutil.copy("/bin/sleep", fake)
        proc = subprocess.Popen([str(fake), "300"])
        self.processes.append(proc)
        return proc

    def stop_processes(self):
        for proc in self.processes:
            proc.kill()
            proc.wait()
        for pid in self.worker_pids():
            try:
                os.kill(pid, 9)
            except OSError:
                pass

    def worker_pids(self):
        f = self.state / "workers.pids"
        return [int(x) for x in f.read_text().split()] if f.exists() else []

    def live_workers(self):
        out = []
        for pid in self.worker_pids():
            try:
                if Path("/proc/%d/stat" % pid).read_text().rsplit(")", 1)[1].split()[0] != "Z":
                    out.append(pid)
            except OSError:
                pass
        return out

    def count_calls(self, prefix):
        return len([c for c in self.calls() if c.startswith(prefix)])

    def wait_for(self, what, check, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            got = check()
            if got:
                return got
            time.sleep(0.05)
        raise AssertionError("timed out waiting for " + what)


class WindowsTestCase(unittest.TestCase):
    def setUp(self):
        pwsh()   # fails the test, never skips, when PowerShell 7 is missing
