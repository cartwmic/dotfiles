#!/usr/bin/env python3
"""Live proof driver for agent-desktop: prepares one device, runs the 14 rows through the real path, saves a record.

usage: live_run.py DEVICE [--out DIR] [--dry-run] [--only J2,J8] [--phase all|prepare|rows] [--unlock-timeout SECS]
  DEVICE   omarchy (this machine) | mac-mini (ssh mac-mini) | g14 (ssh mac-mini, then ssh to the G14)
  --dry-run  print the plan and the preconditions; change nothing, write nothing (safe on Omarchy)
  --only     run just these rows, print the results, write record.partial.json; no install, no record
  --phase    g14 only. prepare = install, install again, read settings, locked-screen check. rows = wait for the
             unlock, run the rows, read settings again, write the record. all = both (default).

Output, under --out (default: <run folder>/proof/DEVICE, i.e. next to this worktree): every command's output as a text
file, every screenshot as a PNG, and record.json (schema 1). At the end the driver runs check_record.py on the record and
exits with its status, so a format problem shows before the device is locked again.

Row meanings: CUA-CRITERIA.md. Rows J1 to J8 use the eight actions of agent-desktop. `agent-desktop ui` (Vercel's program)
is used for the N rows and to read results back. Waits end on a fact (a window appears, a file holds the text) with a
timeout; there is no fixed sleep and no retry wrapper: a failed row is recorded with its error. The only repeat is N3 (the
row itself is "N2 three times").

Device preconditions (INTENT-NOTES.md section 4): Omarchy has a Hyprland session with wlrctl, wtype, grim and foot. The Mac
mini has the console user logged in and kitty holding Screen & System Audio Recording and Accessibility; calls over ssh run in the
kitty helper (agent-desktop-relay), which the install step and its login item start. The G14 is
unlocked for the rows phase (an ask each time); the prepare phase and the locked-screen check need it locked.
Nothing here changes a G14 login, PIN, sleep, power or RustDesk setting; the settings are only read.

Importable without side effects: row(), build_record() and write_record() are what the fixture test uses.
"""
import argparse
import base64
import importlib.util
import json
import os
import re
import shlex
import statistics
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True  # importing proof_sources must not leave a __pycache__ in the tree
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

ROWS = [
    ("J0", "install and health"), ("J1", "screenshot, full and region"), ("J2", "list windows"),
    ("J3", "focus a named window"), ("J4", "move the pointer"), ("J5", "click left and right"),
    ("J6", "type text and read it back"), ("J7", "press a key and a modifier combo"), ("J8", "report the pointer"),
    ("N1", "read three apps by label"), ("N2", "calculator 12 x 34 by labels"), ("N3", "N2 three times in a row"),
    ("N4", "a stale reference is refused"), ("N5", "speed"),
]
ROW_IDS = [r for r, _ in ROWS]
OMARCHY_NOT_OFFERED = ["N1", "N2", "N3", "N4", "N5"]
OMARCHY_NOTE = "not offered: Omarchy's apps do not show their controls by name, so there is no `ui` here"
G14_HOP = "ssh -q -o BatchMode=yes -i ~/.ssh/cartwmic-homelab -o HostKeyAlias=10.19.1.112 michael@10.19.1.89"


# ------------------------------------------------------------------ record format (used by the fixture test too)
def row(rid, status, commands=None, screenshots=None, error="", note=""):
    r = {"id": rid, "status": status, "commands": list(commands or []), "screenshots": list(screenshots or [])}
    if error:
        r["error"] = error
    if note:
        r["note"] = note
    return r


def _proof_sources():
    spec = importlib.util.spec_from_file_location("proof_sources", HERE / "proof_sources.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_record(device, root, rows, install, settings=None, checks=None, made_at=None):
    """The schema-1 record. File names inside it are relative to the folder that holds record.json."""
    digest, files = _proof_sources().digest(device, root)
    rec = {"schema": 1, "device": device, "source_digest": digest, "source_files": files, "install": install, "rows": rows}
    if settings is not None:
        rec["settings"] = settings
    if checks is not None:
        rec["checks"] = checks
    if made_at:
        rec["made_at"] = made_at
    return rec


def write_record(out, rec, name="record.json"):
    Path(out).mkdir(parents=True, exist_ok=True)
    (Path(out) / name).write_text(json.dumps(rec, indent=1) + "\n")
    return Path(out) / name


# ------------------------------------------------------------------ small helpers
class Fail(Exception):
    """A row did not hold: the message is the error text saved with the row."""


def expect(cond, msg):
    if not cond:
        raise Fail(msg)


def wait_for(what, fn, timeout=30.0, interval=0.4):
    """Poll fn() until it returns something truthy; fail with `what` if it never does within timeout."""
    end = time.monotonic() + timeout
    last = None
    while True:
        try:
            last = fn()
            if last:
                return last
        except Fail as e:
            last = e
        if time.monotonic() >= end:
            raise Fail("timed out after %ds waiting for %s%s" % (timeout, what, (" (last: %s)" % last) if last else ""))
        time.sleep(interval)


def json_in(text):
    i = text.find("{")
    if i < 0:
        return None
    try:
        return json.loads(text[i:])
    except ValueError:
        j = text.rfind("}")
        try:
            return json.loads(text[i:j + 1])
        except ValueError:
            return None


def walk(node, fn):
    if isinstance(node, dict):
        fn(node)
        for c in node.get("children") or []:
            walk(c, fn)
    elif isinstance(node, list):
        for c in node:
            walk(c, fn)


def elements(env):
    """Every node of a Vercel snapshot that has a ref."""
    out = []
    tree = ((env or {}).get("data") or {}).get("tree")
    walk(tree, lambda n: out.append(n) if n.get("ref_id") else None)
    return out


def texts(env):
    out = []
    tree = ((env or {}).get("data") or {}).get("tree")
    walk(tree, lambda n: out.extend(str(n[k]) for k in ("name", "value") if n.get(k) is not None))
    return out


def find_box(obj):
    if isinstance(obj, dict):
        if all(k in obj for k in ("x", "y", "width", "height")):
            return obj
        for v in obj.values():
            b = find_box(v)
            if b:
                return b
    return None


def centre(box):
    return int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2)


def png_size(path):
    b = Path(path).read_bytes()
    expect(b[:8] == PNG_SIGNATURE, "%s is not a PNG" % path)
    return struct.unpack(">II", b[16:24])


# ------------------------------------------------------------------ devices
class Result:
    def __init__(self, exit_code, out):
        self.exit, self.out = exit_code, out


class Device:
    name = ""
    prefix = ""

    def raw(self, argv, stdin=None, timeout=60):
        try:
            p = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
            return Result(p.returncode, (p.stdout or "") + (p.stderr or ""))
        except subprocess.TimeoutExpired:
            return Result(124, "TIMEOUT after %ds" % timeout)

    def q(self, args):
        return " ".join(shlex.quote(str(a)) for a in args)

    def ad(self, *args):
        return "agent-desktop " + self.q(args)

    def pull(self, remote, local):
        r = self.sh(self.b64_cmd(remote))
        expect(r.exit == 0, "could not read %s: %s" % (remote, r.out.strip()[:200]))
        Path(local).write_bytes(base64.b64decode("".join(r.out.split())))

    # hooks the rows use; each device overrides what it needs
    def preflight(self):
        return []


class Omarchy(Device):
    name = "omarchy"
    scratch = "/tmp/rad-proof"

    def env(self):
        """PATH with ~/.local/bin, and the Wayland/Hyprland session when the agent's shell has neither (as the product script does)."""
        env = dict(os.environ, PATH=os.path.expanduser("~/.local/bin") + ":" + os.environ.get("PATH", ""))
        runtime = env.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
        if not env.get("WAYLAND_DISPLAY"):
            socks = sorted(Path(runtime).glob("wayland-*"))
            socks = [p for p in socks if not p.name.endswith(".lock")]
            if socks:
                env["WAYLAND_DISPLAY"] = socks[0].name
        if not env.get("HYPRLAND_INSTANCE_SIGNATURE"):
            socks = sorted(Path(runtime).glob("hypr/*/.socket.sock"))
            if socks:
                env["HYPRLAND_INSTANCE_SIGNATURE"] = socks[0].parent.name
        return env

    def sh(self, cmd, timeout=60, stdin=None):
        try:
            p = subprocess.run(["sh", "-c", cmd], input=stdin, capture_output=True, text=True, timeout=timeout, env=self.env())
            return Result(p.returncode, (p.stdout or "") + (p.stderr or ""))
        except subprocess.TimeoutExpired:
            return Result(124, "TIMEOUT after %ds" % timeout)

    def b64_cmd(self, remote):
        return "base64 < %s" % shlex.quote(remote)

    def tmp(self, name):
        return "%s/%s" % (self.scratch, name)

    def preflight(self):
        out = []
        for t in ("hyprctl", "wlrctl", "wtype", "grim", "foot", "python3", "chezmoi"):
            ok = self.sh("command -v %s" % t).exit == 0
            out.append(("tool %s" % t, ok))
        out.append(("Hyprland session (cursor read)", self.sh("sh %s cursor >/dev/null 2>&1" % shlex.quote(str(ROOT / "dot_local/bin/executable_agent-desktop"))).exit == 0))
        return out


class MacMini(Device):
    name = "mac-mini"
    _home = None

    @property
    def scratch(self):
        """Absolute path (resolved once over ssh): the quoted `shot FILE` argument must not hold a shell variable."""
        if self._home is None:
            r = self.sh("printf %s \"$HOME\"", timeout=30)
            self._home = r.out.strip().splitlines()[-1] if r.exit == 0 and r.out.strip() else "/Users/unknown"
        return self._home + "/.cache/agent-desktop-proof"

    def sh(self, cmd, timeout=60, stdin=None):
        full = 'export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"; ' + cmd
        return self.raw(["ssh", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "mac-mini", full], stdin=stdin, timeout=timeout)

    def b64_cmd(self, remote):
        return "base64 < %s" % remote

    def tmp(self, name):
        return "%s/%s" % (self.scratch, name)

    def preflight(self):
        r = self.sh("uname -s; id -un", timeout=30)
        return [("ssh mac-mini reachable", r.exit == 0 and "Darwin" in r.out)]


class G14(Device):
    """ssh lands in session 0 with cmd.exe as the shell. Anything that must see the desktop runs in a one-shot
    interactive scheduled task (session 1) that this driver creates and deletes itself; it is not the product's task."""
    name = "g14"
    scratch = "%LOCALAPPDATA%\\agent-desktop\\proof"
    pstmp = "$env:LOCALAPPDATA + '\\agent-desktop\\proof'"

    def q(self, args):
        return " ".join('"%s"' % str(a).replace('"', '\\"') if re.search(r'[\s"&|<>^]', str(a)) or a == "" else str(a) for a in args)

    def _hop(self, remote_cmd, stdin, timeout):
        return self.raw(["ssh", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "mac-mini", G14_HOP + " " + shlex.quote(remote_cmd)], stdin=stdin, timeout=timeout)

    def sh(self, cmd, timeout=60, stdin=None):
        return self._hop(cmd, stdin, timeout)

    def ps(self, script, timeout=120):
        """Run a PowerShell 5.1 script in session 0. One stdin line writes the script to a temp file and runs it with -File
        (the shape the earlier trial's g14ps proved); the script's exit code is passed through."""
        b64 = base64.b64encode(script.encode("utf-8")).decode()
        line = ("$p = \"$env:TEMP\\rad-$PID.ps1\"; [IO.File]::WriteAllBytes($p, [Convert]::FromBase64String('%s')); "
                "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $p; $rc = $LASTEXITCODE; Remove-Item $p -ErrorAction SilentlyContinue; exit $rc\n" % b64)
        return self._hop("powershell.exe -NoProfile -NonInteractive -Command -", line, timeout)

    def b64_cmd(self, remote):
        return 'powershell.exe -NoProfile -NonInteractive -Command "[Convert]::ToBase64String([IO.File]::ReadAllBytes([Environment]::ExpandEnvironmentVariables(\'%s\')))"' % remote

    def tmp(self, name):
        return "%s\\%s" % (self.scratch, name)

    RUNNER_PS = (
        "$d = Join-Path $env:LOCALAPPDATA 'agent-desktop\\proof'\n"
        "try { & powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"$d\\job.ps1\" *>&1 | Out-File -Encoding utf8 \"$d\\out.txt\" } catch { $_ | Out-File -Append \"$d\\out.txt\" }\n"
        "'done' | Out-File \"$d\\done.txt\"\n"
    )

    def s1(self, script, timeout=90):
        """Run a PowerShell script in the desktop session (session 1) through a one-shot interactive task; return its output."""
        job = base64.b64encode(script.encode("utf-8")).decode()
        runner = base64.b64encode(self.RUNNER_PS.encode("utf-8")).decode()
        wrapper = (
            "$d = Join-Path $env:LOCALAPPDATA 'agent-desktop\\proof'; New-Item -ItemType Directory -Force $d | Out-Null\n"
            "[IO.File]::WriteAllBytes(\"$d\\job.ps1\", [Convert]::FromBase64String('%s'))\n"
            "[IO.File]::WriteAllBytes(\"$d\\runner.ps1\", [Convert]::FromBase64String('%s'))\n"
            "Remove-Item \"$d\\done.txt\",\"$d\\out.txt\" -ErrorAction SilentlyContinue\n"
            "schtasks /Create /TN rad-proof-job /TR \"powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $d\\runner.ps1\" /SC ONCE /ST 00:00 /RU $env:USERNAME /IT /F | Out-Null\n"
            "schtasks /Run /TN rad-proof-job | Out-Null\n"
            "$end = (Get-Date).AddSeconds(%d); while (-not (Test-Path \"$d\\done.txt\") -and (Get-Date) -lt $end) { Start-Sleep -Milliseconds 150 }\n"
            "if (Test-Path \"$d\\done.txt\") { Get-Content \"$d\\out.txt\" -Raw } else { 'TIMEOUT waiting for the desktop-session task' }\n"
            "schtasks /Delete /TN rad-proof-job /F | Out-Null\n"
        ) % (job, runner, timeout)
        return self.ps(wrapper, timeout=timeout + 40)

    def is_locked(self):
        r = self.ps("if (Get-Process LogonUI -ErrorAction SilentlyContinue) { 'locked' } else { 'unlocked' }", timeout=60)
        return "unlocked" not in r.out and "locked" in r.out

    def preflight(self):
        r = self.ps("'g14-ok'", timeout=60)
        return [("ssh mac-mini then the G14 reachable", "g14-ok" in r.out)]


DEVICES = {"omarchy": Omarchy, "mac-mini": MacMini, "g14": G14}


# ------------------------------------------------------------------ recorder: one command = one saved file
class Rec:
    def __init__(self, dev, out):
        self.dev, self.out = dev, Path(out)
        self.out.mkdir(parents=True, exist_ok=True)
        self.rid = "pre"
        self.n = 0
        self.cmds = []
        self.shots = []

    def begin(self, rid):
        self.rid, self.n, self.cmds, self.shots = rid, 0, [], []

    def sh(self, label, cmd, timeout=60, stdin=None, save=True):
        """Run `cmd` on the device in its shell. Saved with its exit code unless save=False (helper reads)."""
        r = self.dev.sh(cmd, timeout=timeout, stdin=stdin)
        if save:
            self.n += 1
            fname = "%s-%02d-%s.txt" % (self.rid, self.n, re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-")[:40])
            (self.out / fname).write_text("$ %s\nexit=%d\n---\n%s\n" % (cmd if stdin is None else cmd + "  (script on stdin)", r.exit, r.out))
            self.cmds.append({"command": cmd, "exit": r.exit, "output_file": fname})
        return r

    def ps(self, label, script, timeout=120):
        """A PowerShell script run on the G14 (session 0), saved like any command."""
        r = self.dev.ps(script, timeout=timeout)
        self.n += 1
        fname = "%s-%02d-%s.txt" % (self.rid, self.n, re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-")[:40])
        (self.out / fname).write_text("$ powershell script: %s\nexit=%d\n---\n%s\n" % (label, r.exit, r.out))
        self.cmds.append({"command": "powershell script: " + label, "exit": r.exit, "output_file": fname})
        return r

    def note(self, label, text):
        """Save text the driver measured itself (no device command) as a file in the record."""
        self.n += 1
        fname = "%s-%02d-%s.txt" % (self.rid, self.n, re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-")[:40])
        (self.out / fname).write_text(text + "\n")
        self.cmds.append({"command": "measured by the driver: " + label, "exit": 0, "output_file": fname})

    def ad(self, label, *args, timeout=60, save=True):
        return self.sh(label, self.dev.ad(*args), timeout=timeout, save=save)

    def ui(self, label, *args, timeout=90, save=True):
        r = self.ad(label, "ui", *args, timeout=timeout, save=save)
        r.env = json_in(r.out)
        return r

    def shot(self, label, region=None):
        """agent-desktop shot to a device file, then pull the PNG into the record folder."""
        remote = self.dev.tmp("%s-%s.png" % (self.rid, label))
        args = ["shot", remote] + ([region] if region else [])
        r = self.ad("shot " + label, *args)
        expect(r.exit == 0, "shot %s exited %d: %s" % (label, r.exit, r.out.strip()[:200]))
        local = self.out / ("%s-%s.png" % (self.rid, label))
        self.dev.pull(remote, local)
        png_size(local)
        self.shots.append(local.name)
        return local


def run_row(rec, rid, fn):
    rec.begin(rid)
    status, error = "pass", ""
    try:
        fn(rec)
    except Fail as e:
        status, error = "fail", str(e)
    except Exception as e:  # a driver or device problem is still a failed row with its error, never a crash
        status, error = "fail", "%s: %s" % (type(e).__name__, e)
    return row(rid, status, rec.cmds, rec.shots, error)


# ------------------------------------------------------------------ Omarchy rows (the eight actions; foot terminals as targets)
EIGHT = ("shot", "windows", "focus", "move", "click", "type", "key", "cursor")


def omarchy_rows(rec, dev):
    sc = dev.scratch
    state = {}

    def windows():
        r = rec.ad("windows", "windows", save=False)
        expect(r.exit == 0, "`windows` exited %d: %s" % (r.exit, r.out.strip()[:200]))
        lines = r.out.strip().splitlines()
        expect(lines and lines[0].split("\t")[:2] == ["class", "title"], "`windows` printed no header line")
        out = {}
        for ln in lines[1:]:
            f = ln.split("\t")
            if len(f) >= 4:
                out.setdefault(f[0], f)
        return out

    def box(cls):
        f = windows().get(cls)
        expect(f, "no window of class %s" % cls)
        x, y = [int(v) for v in f[2].split(",")]
        w, h = [int(v) for v in f[3].split("x")]
        return x, y, w, h

    def hypr(path):
        r = rec.sh("hyprctl", "hyprctl %s" % path, save=False)
        return r.out

    def active_class():
        j = json_in(hypr("activewindow -j")) or {}
        return j.get("class")

    def ensure_terminals(rec):
        if {"rad-proof-clicks", "rad-proof-type"} <= set(windows()):
            return
        rec.sh("scratch dir", "rm -rf %s; mkdir -p %s" % (sc, sc))
        clicks = ("foot --app-id rad-proof-clicks -e sh -c 'stty -icanon min 1 -echo; printf \"\\033[?1000h\\033[?1006h\"; exec cat -v > %s/clicks.txt' >/dev/null 2>&1 &" % sc)
        typing = "foot --app-id rad-proof-type -e sh -c 'exec cat > %s/typed.txt' >/dev/null 2>&1 &" % sc
        rec.sh("start the click target", clicks)
        rec.sh("start the typing target", typing)
        wait_for("both scratch terminals to show in `windows`", lambda: {"rad-proof-clicks", "rad-proof-type"} <= set(windows()))

    def j0(rec):
        r = rec.sh("which", "command -v agent-desktop")
        expect(r.exit == 0 and r.out.strip().endswith("/.local/bin/agent-desktop"), "agent-desktop is not on PATH at ~/.local/bin/agent-desktop: %s" % r.out.strip())
        r = rec.sh("installed equals the repo", "sha256sum \"$HOME/.local/bin/agent-desktop\"")
        want = rec.sh("rendered source", "chezmoi --source %s cat \"$HOME/.local/bin/agent-desktop\" | sha256sum" % shlex.quote(str(ROOT)))
        expect(r.exit == 0 and want.exit == 0 and r.out.split()[0] == want.out.split()[0], "the installed script differs from what the repo renders")
        r = rec.ad("usage", timeout=30)
        expect(r.exit == 2 and all(a in r.out for a in EIGHT), "no-argument call: expected exit 2 and a usage that names all eight actions, got exit %d" % r.exit)
        r = rec.ad("health", "cursor")
        expect(r.exit == 0 and re.fullmatch(r"-?\d+ -?\d+", r.out.strip()), "`cursor` did not print X Y: %r" % r.out.strip())

    def j1(rec):
        ensure_terminals(rec)
        full = rec.shot("full")
        part = rec.shot("region", "100,100 200x120")
        (fw, fh), (pw, ph) = png_size(full), png_size(part)
        expect(pw < fw and ph < fh, "region shot %dx%d is not smaller than the full shot %dx%d" % (pw, ph, fw, fh))

    def j2(rec):
        ensure_terminals(rec)
        w = wait_for("the scratch terminals in `windows`", lambda: (lambda d: d if {"rad-proof-clicks", "rad-proof-type"} <= set(d) else None)(windows()))
        rec.ad("windows listing", "windows")
        expect(all(len(v) >= 6 for v in w.values()), "a `windows` line has fewer than six columns")

    def j3(rec):
        ensure_terminals(rec)
        for cls in ("rad-proof-type", "rad-proof-clicks", "rad-proof-type"):
            r = rec.ad("focus " + cls, "focus", cls)
            expect(r.exit == 0, "focus %s exited %d: %s" % (cls, r.exit, r.out.strip()[:200]))
            wait_for("%s to be the active window (hyprctl)" % cls, lambda c=cls: active_class() == c)
            rec.note("independent read after focus %s: hyprctl active window class" % cls, str(active_class()))

    def j4(rec):
        for x, y in ((400, 300), (700, 500)):
            r = rec.ad("move %d %d" % (x, y), "move", x, y)
            expect(r.exit == 0, "move exited %d: %s" % (r.exit, r.out.strip()[:200]))
            got = rec.sh("independent read", "hyprctl cursorpos")
            expect(got.out.strip().replace(" ", "") == "%d,%d" % (x, y), "pointer is at %r, wanted %d,%d" % (got.out.strip(), x, y))

    def j5(rec):
        ensure_terminals(rec)
        rec.ad("focus", "focus", "rad-proof-clicks")
        wait_for("the click terminal active", lambda: active_class() == "rad-proof-clicks")
        x, y, w, h = box("rad-proof-clicks")
        cx, cy = x + w // 2, y + h // 2
        for button, code in (("left", "<0;"), ("right", "<2;")):
            r = rec.ad("click " + button, "click", cx, cy, button)
            expect(r.exit == 0, "click %s exited %d: %s" % (button, r.exit, r.out.strip()[:200]))
            wait_for("the terminal to report a %s press (%s)" % (button, code), lambda c=code: c in rec.sh("read clicks", "cat %s/clicks.txt" % sc, save=False).out)
        rec.sh("clicks the terminal received", "cat %s/clicks.txt" % sc)
        rec.shot("after-clicks")

    def j6(rec):
        ensure_terminals(rec)
        rec.ad("focus", "focus", "rad-proof-type")
        wait_for("the typing terminal active", lambda: active_class() == "rad-proof-type")
        r = rec.ad("type", "type", "hello agent-desktop")
        expect(r.exit == 0, "type exited %d: %s" % (r.exit, r.out.strip()[:200]))
        r = rec.ad("key Return", "key", "Return")
        expect(r.exit == 0, "key Return exited %d" % r.exit)
        wait_for("the typed line in the file", lambda: "hello agent-desktop" in rec.sh("read typed", "cat %s/typed.txt" % sc, save=False).out)
        rec.sh("text the terminal received", "cat %s/typed.txt" % sc)

    def j7(rec):
        r = rec.ad("key d ctrl", "key", "d", "ctrl")  # Ctrl+D is end of input: `cat` ends and the terminal closes
        expect(r.exit == 0, "key d ctrl exited %d: %s" % (r.exit, r.out.strip()[:200]))
        wait_for("the typing terminal to close after Ctrl+D", lambda: "rad-proof-type" not in windows())

    def j8(rec):
        r = rec.ad("move", "move", 123, 234)
        expect(r.exit == 0, "move exited %d" % r.exit)
        r = rec.ad("cursor", "cursor")
        expect(r.exit == 0 and r.out.strip() == "123 234", "`cursor` printed %r, wanted '123 234'" % r.out.strip())

    return [("J0", j0), ("J1", j1), ("J2", j2), ("J3", j3), ("J4", j4), ("J5", j5), ("J6", j6), ("J7", j7), ("J8", j8)]


def omarchy_cleanup(rec):
    rec.sh("close scratch windows", "pkill -f '[a]pp-id rad-proof' ; rm -rf %s; true" % rec.dev.scratch, save=False)


# ------------------------------------------------------------------ Mac mini and G14 rows
def desktop_hooks(dev):
    """Per-device pieces the shared Mac/Windows rows need."""
    if dev.name == "mac-mini":
        return dict(
            calc="Calculator", editor="TextEdit",
            calc_names={"clear": ["All Clear", "Clear", "AC"], "1": ["1"], "2": ["2"], "3": ["3"], "4": ["4"], "7": ["7"], "*": ["Multiply"], "=": ["Equals"]},
            n1_apps=[("Finder", ["--app", "Finder"], "Finder"), ("System Settings", ["--app", "System Settings"], "System Settings"), ("Calculator", ["--app", "Calculator"], "Calculator")],
            select_all=("a", ["cmd"]), erase="delete",
        )
    return dict(
        calc="Calculator", editor="rad-proof-pad",
        calc_names={"clear": ["Clear", "All Clear"], "1": ["One"], "2": ["Two"], "3": ["Three"], "4": ["Four"], "7": ["Seven"], "*": ["Multiply by", "Multiply"], "=": ["Equals"]},
        n1_apps=[("Calculator", ["--app", "Calculator"], "Calculator"), ("proof pad", ["--app", "powershell.exe"], "rad-proof-pad"), ("Explorer", ["--app", "explorer.exe"], "This PC")],
        select_all=("a", ["ctrl"]), erase="Delete",
    )


PAD_PS = r"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$d = Join-Path $env:LOCALAPPDATA 'agent-desktop\proof'
$f = New-Object Windows.Forms.Form; $f.Text = 'rad-proof-pad'; $f.StartPosition = 'Manual'; $f.Location = New-Object Drawing.Point(300,200); $f.Size = New-Object Drawing.Size(520,340)
$t = New-Object Windows.Forms.TextBox; $t.Multiline = $true; $t.Dock = 'Fill'; $t.ShortcutsEnabled = $true; $t.AccessibleName = 'Proof text'
$t.ContextMenuStrip = New-Object Windows.Forms.ContextMenuStrip   # empty: a right click shows no menu to dismiss
$f.Controls.Add($t)
$t.Add_TextChanged({ [IO.File]::WriteAllText("$d\pad.txt", $t.Text) })
$t.Add_MouseDown({ Add-Content -Path "$d\clicks.txt" -Value ("{0} {1},{2}" -f $_.Button, $_.X, $_.Y) })
[IO.File]::WriteAllText("$d\pad.txt", ''); [IO.File]::WriteAllText("$d\clicks.txt", '')
[IO.File]::WriteAllText("$d\pad.pid", [string]$PID)
[Windows.Forms.Application]::Run($f)
"""

NATIVE_PS = r"""
Add-Type @"
using System; using System.Runtime.InteropServices; using System.Text;
public class RadW {
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
 [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 public struct POINT { public int X; public int Y; }
}
"@
[void][RadW]::SetProcessDPIAware()
"""


def desktop_rows(rec, dev):
    hk = desktop_hooks(dev)
    win = dev.name == "g14"
    st = {}

    def windows():
        r = rec.ad("windows", "windows", save=False)
        expect(r.exit == 0, "`windows` exited %d: %s" % (r.exit, r.out.strip()[:200]))
        lines = r.out.strip().splitlines()
        expect(len(lines) >= 1 and "\t" in lines[0], "`windows` printed no header line")
        return lines

    def has_window(text):
        return any(text.lower() in ln.lower() for ln in windows()[1:])

    def foreground():
        if not win:
            r = rec.ui("focused window", "list-windows", save=False)
            data = (r.env or {}).get("data") or []
            return " ".join("%s %s" % (w.get("app_name", ""), w.get("title", "")) for w in data if w.get("is_focused"))
        if win:
            return dev.s1(NATIVE_PS + "$s = New-Object Text.StringBuilder 256; [void][RadW]::GetWindowText([RadW]::GetForegroundWindow(), $s, 256); $s.ToString()").out.strip()
        return dev.sh("osascript -e 'tell application \"System Events\" to get name of first application process whose frontmost is true'").out.strip()

    def pointer():
        if win:
            o = dev.s1(NATIVE_PS + "$p = New-Object RadW+POINT; [void][RadW]::GetCursorPos([ref]$p); '{0} {1}' -f $p.X, $p.Y").out.strip()
        else:
            o = dev.sh("osascript -l JavaScript -e 'ObjC.import(\"CoreGraphics\"); var p = $.CGEventGetLocation($.CGEventCreate(null)); Math.round(p.x) + \" \" + Math.round(p.y)'").out.strip()
        m = re.search(r"(-?\d+) (-?\d+)", o)
        expect(m, "independent pointer read gave %r" % o)
        return int(m.group(1)), int(m.group(2))

    def editor_text():
        if win:
            r = dev.ps("Get-Content -Raw ($env:LOCALAPPDATA + '\\agent-desktop\\proof\\pad.txt')")
            return r.out.rstrip("\r\n")
        e = rec.ui("read editor", "snapshot", "--app", hk["editor"], "-i", "--compact", save=False)
        ref = next((n["ref_id"] for n in elements(e.env) if n.get("role") == "textfield" and "TypeText" in (n.get("available_actions") or [])), None)
        expect(ref, "no text area in the TextEdit snapshot")
        g = rec.ui("get value", "get", ref, "--property", "value", save=False)
        return str(((g.env or {}).get("data") or {}).get("value", ""))

    def open_calc():
        if win:
            dev.s1("Start-Process calc.exe")
        else:
            dev.sh("open -a Calculator")
        wait_for("Calculator in `windows`", lambda: has_window("Calculator"), timeout=60)

    def close_calc():
        if win:
            dev.s1("Get-Process CalculatorApp,Calculator -ErrorAction SilentlyContinue | Stop-Process -Force")
        else:
            dev.sh("pkill -x Calculator; true")
        wait_for("Calculator to leave `windows`", lambda: not has_window("Calculator"), timeout=30)

    def open_editor():
        if win:
            b = base64.b64encode(PAD_PS.encode("utf-16-le")).decode()
            dev.s1("Start-Process powershell.exe -ArgumentList '-NoProfile','-WindowStyle','Hidden','-ExecutionPolicy','Bypass','-EncodedCommand','%s'" % b)
        else:
            dev.sh("open -a TextEdit")
        wait_for("the editor in `windows`", lambda: has_window(hk["editor"]), timeout=60)
        if not win:  # TextEdit opens its Open panel first: click New Document by label
            e = rec.ui("TextEdit snapshot", "snapshot", "--app", "TextEdit", "-i", "--compact")
            nd = next((n["ref_id"] for n in elements(e.env) if n.get("name") == "New Document"), None)
            if nd:
                rec.ui("New Document", "click", nd)

    def close_editor():
        if win:
            dev.ps("$p = $env:LOCALAPPDATA + '\\agent-desktop\\proof\\pad.pid'; if (Test-Path $p) { Stop-Process -Id ([int](Get-Content $p)) -Force -ErrorAction SilentlyContinue }")
        else:
            dev.sh("pkill -x TextEdit; true")

    def calc_snapshot(label="calc snapshot", save=True):
        r = snapshot_app(label, ["--app", hk["calc"]], "Calculator", save=save)
        expect(r.exit == 0 and r.env and r.env.get("ok") is not False, "calculator snapshot failed (exit %d): %s" % (r.exit, r.out.strip()[:200]))
        return r.env

    def ref_of(env, key):
        names = hk["calc_names"][key]
        for n in elements(env):
            if n.get("name") in names and n.get("role") in (None, "button"):
                return n["ref_id"]
        raise Fail("no calculator control named %s in the snapshot" % "/".join(names))

    def display(env):
        return " | ".join(texts(env))

    def display_value(env):
        """The calculator's main display: 'Display is X' on Windows, the first static text value on the Mac."""
        for t in texts(env):
            m = re.match(r"Display is (.*)$", t)
            if m:
                return m.group(1).strip()
        vals = []
        walk(((env or {}).get("data") or {}).get("tree"), lambda n: vals.append(str(n["value"])) if n.get("role") == "statictext" and n.get("value") is not None else None)
        return vals[0].strip() if vals else ""

    def ensure_apps(rec):
        if win:
            dev.ps("New-Item -ItemType Directory -Force ($env:LOCALAPPDATA + '\\agent-desktop\\proof') | Out-Null")
        else:
            dev.sh("mkdir -p %s" % dev.scratch)
        if not has_window(hk["calc"]):
            open_calc()
        if not has_window(hk["editor"]):
            open_editor()

    def snapshot_app(label, extra, hint, save=True):
        """snapshot --app NAME; when the tool cannot name the app (hosted windows), snapshot the window by id."""
        r = rec.ui(label, "snapshot", *extra, "-i", "--compact", save=save)
        if r.exit == 0 and r.env and r.env.get("ok") is not False:
            return r
        lw = rec.ui("list windows for " + hint, "list-windows", save=save)
        wid = next((w.get("id") for w in ((lw.env or {}).get("data") or []) if hint.lower() in ("%s %s" % (w.get("app_name", ""), w.get("title", ""))).lower()), None)
        if wid:
            return rec.ui(label + " by window id", "snapshot", "--window-id", wid, "-i", "--compact", save=save)
        return r

    # ----- rows
    def j0(rec):
        r = rec.sh("which", ("where agent-desktop" if win else "command -v agent-desktop"))
        expect(r.exit == 0 and "agent-desktop" in r.out, "agent-desktop is not on PATH in an ssh shell: %s" % r.out.strip()[:200])
        r = rec.ad("usage", timeout=30)
        expect(r.exit == 2 and all(a in r.out for a in EIGHT) and "ui" in r.out, "no-argument call: expected exit 2 and a usage naming all eight actions and ui, got exit %d" % r.exit)
        r = rec.ad("windows", "windows")
        expect(r.exit == 0, "`windows` exited %d: %s" % (r.exit, r.out.strip()[:200]))
        r = rec.ui("ui version", "version")
        expect(r.exit == 0 and "1.3.1" in r.out, "`ui version` did not report 1.3.1 (exit %d): %s" % (r.exit, r.out.strip()[:200]))
        r = rec.ui("ui status", "status")
        expect(r.exit == 0, "`ui status` exited %d: %s" % (r.exit, r.out.strip()[:200]))

    def j1(rec):
        ensure_apps(rec)
        full = rec.shot("full")
        part = rec.shot("region", "100,100 200x120")
        (fw, fh), (pw, ph) = png_size(full), png_size(part)
        expect(pw < fw and ph < fh, "region shot %dx%d is not smaller than the full shot %dx%d" % (pw, ph, fw, fh))

    def j2(rec):
        ensure_apps(rec)
        rec.ad("windows listing", "windows")
        expect(has_window(hk["calc"]) and has_window(hk["editor"]), "`windows` does not list both scratch apps (%s, %s)" % (hk["calc"], hk["editor"]))

    def j3(rec):
        ensure_apps(rec)
        for name in (hk["calc"], hk["editor"], hk["calc"]):
            r = rec.ad("focus " + name, "focus", name)
            expect(r.exit == 0, "focus %s exited %d: %s" % (name, r.exit, r.out.strip()[:200]))
            fg = wait_for("%s to be the foreground window" % name, lambda n=name: (lambda v: v if n.lower() in v.lower() else None)(foreground()), timeout=20)
            rec.note("independent read after focus %s: foreground window" % name, fg)

    def j4(rec):
        for x, y in ((400, 300), (700, 500)):
            r = rec.ad("move %d %d" % (x, y), "move", x, y)
            expect(r.exit == 0, "move exited %d: %s" % (r.exit, r.out.strip()[:200]))
            got = wait_for("the pointer at %d,%d" % (x, y), lambda: (lambda p: p if p == (x, y) else None)(pointer()), timeout=10)
            rec.note("independent read after move %d %d: pointer" % (x, y), "%d %d" % got)

    def j5(rec):
        ensure_apps(rec)
        rec.ad("focus calculator", "focus", hk["calc"])
        env = calc_snapshot("snapshot for coordinates")
        ref = ref_of(env, "7")
        g = rec.ui("bounds of 7", "get", ref, "--property", "bounds")
        box = find_box(g.env)
        expect(box, "no bounds in the reply for the 7 button")
        cx, cy = centre(box)
        r = rec.ad("click left", "click", cx, cy, "left")
        expect(r.exit == 0, "click exited %d: %s" % (r.exit, r.out.strip()[:200]))
        shown = wait_for("a 7 on the calculator display after the left click", lambda: (lambda d: d if "7" in d else None)(display(calc_snapshot("read display", save=False))), timeout=15)
        rec.note("calculator display after the left click", shown)
        rec.ad("focus editor", "focus", hk["editor"])
        if win:
            r = rec.ad("click right", "click", 500, 340, "right")  # inside the pad (it sits at 300,200 and is 520x340)
            expect(r.exit == 0, "click right exited %d: %s" % (r.exit, r.out.strip()[:200]))
            log = wait_for("the pad to log a Right press", lambda: (lambda t: t if "Right" in t else None)(dev.ps("Get-Content -Raw ($env:LOCALAPPDATA + '\\agent-desktop\\proof\\clicks.txt')").out), timeout=15)
            rec.note("click log the pad wrote", log)
        else:
            e = rec.ui("TextEdit snapshot", "snapshot", "--app", "TextEdit", "-i", "--compact")
            ta = next((n for n in elements(e.env) if n.get("role") == "textfield"), None)
            expect(ta, "no TextEdit text area")
            b = find_box(rec.ui("bounds of text area", "get", ta["ref_id"], "--property", "bounds").env)
            expect(b, "no bounds for the TextEdit text area")
            r = rec.ad("click right", "click", int(b["x"] + 100), int(b["y"] + 60), "right")
            expect(r.exit == 0, "click right exited %d: %s" % (r.exit, r.out.strip()[:200]))
            wait_for("a context menu in the menu surface", lambda: (lambda m: m.env and m.env.get("ok") and any(n.get("role") == "menuitem" for n in elements(m.env)))(rec.ui("menu surface", "snapshot", "--app", "TextEdit", "--surface", "menu", "-i", "--compact", save=False)), timeout=15)
            rec.ad("close menu", "key", "escape")
        rec.shot("after-clicks")

    def j6(rec):
        ensure_apps(rec)
        rec.ad("focus editor", "focus", hk["editor"])
        wait_for("the editor in front", lambda: hk["editor"].lower() in foreground().lower(), timeout=20)
        r = rec.ad("type", "type", "hello agent-desktop")
        expect(r.exit == 0, "type exited %d: %s" % (r.exit, r.out.strip()[:200]))
        got = wait_for("the typed text in the editor", lambda: (lambda t: t if "hello agent-desktop" in t else None)(editor_text()), timeout=15)
        rec.note("text read back from the editor", got)

    def j7(rec):
        ensure_apps(rec)
        key, mods = hk["select_all"]
        r = rec.ad("select all", "key", key, *mods)
        expect(r.exit == 0, "key %s %s exited %d: %s" % (key, " ".join(mods), r.exit, r.out.strip()[:200]))
        r = rec.ad("erase", "key", hk["erase"])
        expect(r.exit == 0, "key %s exited %d" % (hk["erase"], r.exit))
        wait_for("the editor to be empty after select-all and delete", lambda: (editor_text() == "") or None, timeout=15)
        rec.note("text read back after select-all and delete", "(empty)")

    def j8(rec):
        r = rec.ad("move", "move", 123, 234)
        expect(r.exit == 0, "move exited %d" % r.exit)
        r = rec.ad("cursor", "cursor")
        expect(r.exit == 0 and r.out.strip() == "123 234", "`cursor` printed %r, wanted '123 234'" % r.out.strip())

    def n1(rec):
        seen = []
        ensure_apps(rec)
        for label, extra, hint in hk["n1_apps"]:
            r = snapshot_app("snapshot " + label, extra, hint)
            expect(r.exit == 0 and r.env and r.env.get("ok") is not False, "snapshot of %s failed (exit %d): %s" % (label, r.exit, r.out.strip()[:200]))
            labelled = [n for n in elements(r.env) if n.get("name")]
            expect(len(labelled) >= 5, "%s: only %d labelled controls" % (label, len(labelled)))
            seen.append("%s=%d" % (label, len(labelled)))

    def calc_sequence(rec):
        env = calc_snapshot()
        for key in ("clear", "1", "2", "*", "3", "4", "="):
            r = rec.ui("click " + key, "click", ref_of(env, key))
            expect(r.exit == 0, "click %s exited %d: %s" % (key, r.exit, r.out.strip()[:200]))
        shown = wait_for("408 on the display", lambda: (lambda d: d if re.search(r"(^|\D)408(\D|$)", d) else None)(display(calc_snapshot("read display", save=False))), timeout=15)
        rec.note("calculator display", shown)

    def n2(rec):
        ensure_apps(rec)
        rec.ad("focus", "focus", hk["calc"])
        calc_sequence(rec)

    def n3(rec):
        ensure_apps(rec)
        for i in range(3):
            calc_sequence(rec)

    def n4(rec):
        ensure_apps(rec)
        env = calc_snapshot("snapshot before the change")
        old = ref_of(env, "7")
        close_calc()
        open_calc()
        r = rec.ui("click the old ref", "click", old)
        expect(r.exit != 0 or (r.env and r.env.get("ok") is False), "the old reference was accepted after the window was recreated (exit 0)")
        expect(re.search(r"STALE|NOT_FOUND|AMBIGUOUS", r.out), "the refusal does not name a stale/not-found reason: %s" % r.out.strip()[:200])
        after = display_value(calc_snapshot("snapshot after"))
        expect(after in ("0", ""), "the display shows %r after the refused click (wanted 0)" % after)

    def n5(rec):
        ensure_apps(rec)
        base = []
        for _ in range(3):
            t = time.perf_counter()
            dev.sh("true")
            base.append((time.perf_counter() - t) * 1000)
        overhead = statistics.median(base)
        t = time.perf_counter()
        env = calc_snapshot("timed snapshot")
        snap = (time.perf_counter() - t) * 1000 - overhead
        ref = ref_of(env, "7")
        times = []
        for _ in range(5):
            t = time.perf_counter()
            rec.ui("timed click", "click", ref)
            times.append((time.perf_counter() - t) * 1000 - overhead)
        rec.note("timings (ssh round trip subtracted)", "snapshot_ms=%d click_ms=%s ssh_overhead_ms=%d" % (snap, ",".join(str(int(x)) for x in times), overhead))
        expect(snap < 3000, "snapshot took %d ms (limit 3000)" % snap)
        expect(statistics.median(times) < 1000, "click median %d ms (limit 1000)" % statistics.median(times))

    return [("J0", j0), ("J1", j1), ("J2", j2), ("J3", j3), ("J4", j4), ("J5", j5), ("J6", j6), ("J7", j7), ("J8", j8),
            ("N1", n1), ("N2", n2), ("N3", n3), ("N4", n4), ("N5", n5)], close_editor, close_calc


# ------------------------------------------------------------------ install steps
def install_omarchy(rec, dev):
    cmd = "chezmoi --source %s apply -x scripts --force \"$HOME/.local/bin/agent-desktop\" && sha256sum \"$HOME/.local/bin/agent-desktop\"" % shlex.quote(str(ROOT))
    r = rec.sh("install", cmd)
    return {"fresh": rec.cmds[-1]}


def install_mac(rec, dev):
    sc = dev.scratch
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True, check=True).stdout
    rec.sh("clean", 'rm -rf "$HOME/.local/bin/agent-desktop" "$HOME/.local/share/agent-desktop" %s; mkdir -p %s/src %s/shots' % (sc, sc, sc))
    tar = subprocess.run(["tar", "-czf", "-", "-C", str(ROOT), "-T", "-"], input=files.encode(), capture_output=True, check=True).stdout
    p = subprocess.run(["ssh", "-q", "mac-mini", "tar -xzf - -C %s/src" % sc], input=tar, capture_output=True, timeout=300)
    expect(p.returncode == 0, "copying the branch to the Mac mini failed: %s" % p.stderr.decode(errors="replace")[:200])
    script = (
        "set -eu; D=%s; cd \"$D/src\"; "
        # the login item is loaded through this library, which a full chezmoi apply installs and this partial install does not
        "mkdir -p \"$HOME/.local/share/launchd-reload\"; "
        "chezmoi --source \"$D/src\" apply -x scripts --force \"$HOME/.local/share/launchd-reload/launchd_reload.sh\"; "
        "chezmoi --source \"$D/src\" execute-template < run_onchange_after_66_agent_desktop_macos.sh.tmpl > \"$D/66.sh\"; "
        "sh \"$D/66.sh\"; test -x \"$HOME/.local/bin/agent-desktop\"; "
        "\"$HOME/.local/bin/agent-desktop-relay\" status; launchctl print \"gui/$(id -u)/com.cartwmic.agent-desktop-relay\" >/dev/null; "
        "ls -l \"$HOME/.local/bin/agent-desktop\" \"$HOME/.local/share/agent-desktop/vercel\"" % sc
    )
    r = rec.sh("fresh install", script, timeout=600)
    return {"fresh": rec.cmds[-1]}


G14_STATE_PS = r"""
$o = [ordered]@{}
$b = Join-Path $env:USERPROFILE '.local\bin'
foreach ($f in 'agent-desktop.ps1','agent-desktop.cmd') { $p = Join-Path $b $f; $o[$f] = if (Test-Path $p) { (Get-FileHash $p).Hash } else { 'absent' } }
$v = Join-Path $env:USERPROFILE '.local\share\agent-desktop\vercel\agent-desktop.exe'
$o['vercel'] = if (Test-Path $v) { (Get-FileHash $v).Hash } else { 'absent' }
$o['path'] = [Environment]::GetEnvironmentVariable('Path','User')
$t = @(schtasks /Query /FO CSV /NH 2>$null | Where-Object { $_ -match 'agent-desktop' })
$o['tasks'] = ($t -join ';')
$o | ConvertTo-Json -Compress
"""

G14_CLEAN_PS = r"""
$ErrorActionPreference = 'Continue'
foreach ($f in 'agent-desktop.ps1','agent-desktop.cmd') { Remove-Item (Join-Path $env:USERPROFILE ".local\bin\$f") -Force -ErrorAction SilentlyContinue }
Remove-Item (Join-Path $env:USERPROFILE '.local\share\agent-desktop') -Recurse -Force -ErrorAction SilentlyContinue
foreach ($line in @(schtasks /Query /FO CSV /NH 2>$null | Where-Object { $_ -match 'agent-desktop' })) { $n = ($line -split '","')[0].Trim('"'); schtasks /Delete /TN $n /F | Out-Null }
'cleaned'
"""

G14_SETTINGS_PS = r"""
function Reg($p,$n){ try { (Get-ItemProperty -Path $p -Name $n -ErrorAction Stop).$n } catch { $null } }
$reg = [ordered]@{
 ScreenSaveActive = Reg 'HKCU:\Control Panel\Desktop' 'ScreenSaveActive'
 ScreenSaveTimeOut = Reg 'HKCU:\Control Panel\Desktop' 'ScreenSaveTimeOut'
 ScreenSaverIsSecure = Reg 'HKCU:\Control Panel\Desktop' 'ScreenSaverIsSecure'
 InactivityTimeoutSecs = Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'InactivityTimeoutSecs'
 DisableLockWorkstation = Reg 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\System' 'DisableLockWorkstation'
 AutoAdminLogon = Reg 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon' 'AutoAdminLogon'
 DontDisplayLockedUserId = Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'DontDisplayLockedUserId'
 PassportForWorkEnabled = Reg 'HKLM:\SOFTWARE\Policies\Microsoft\PassportForWork' 'Enabled'
}
$cur = ''; $pw = @()
foreach ($l in (powercfg /qh SCHEME_CURRENT 2>&1)) {
  if ($l -match 'Power Setting GUID:\s*(\S+)\s*(\(.*\))?') { $cur = $Matches[1] + ' ' + $Matches[2] }
  elseif ($l -match 'Current (AC|DC) Power Setting Index:\s*(\S+)') { $pw += ('{0} {1}={2}' -f $cur, $Matches[1], $Matches[2]) }
}
[ordered]@{ registry = $reg; powercfg = $pw } | ConvertTo-Json -Depth 4 -Compress
"""


def g14_settings(rec, dev, label):
    res = dev.ps(G14_SETTINGS_PS)
    fname = "settings-%s.txt" % label
    (rec.out / fname).write_text("$ read-only registry reads and `powercfg /qh SCHEME_CURRENT` (script in live_run.py G14_SETTINGS_PS)\nexit=%d\n---\n%s\n" % (res.exit, res.out))
    data = json_in(res.out)
    expect(res.exit == 0 and isinstance(data, dict), "could not read the G14 settings (%s): %s" % (label, res.out.strip()[:200]))
    return data, {"command": "read-only G14 settings (%s)" % label, "exit": res.exit, "output_file": fname}


def install_g14(rec, dev):
    sc = dev.scratch
    # the branch's windows/ folder -> a scratch folder on the G14 (a tar over the hop, unpacked with the system tar.exe)
    tar = subprocess.run(["tar", "-czf", "-", "-C", str(ROOT), "windows"], capture_output=True, check=True).stdout
    b64 = base64.b64encode(tar).decode()
    put = (
        "$d = Join-Path $env:USERPROFILE 'agent-desktop-proof'; Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force $d | Out-Null\n"
        "[IO.File]::WriteAllBytes(\"$d\\windows.tgz\", [Convert]::FromBase64String('%s')); tar.exe -xzf \"$d\\windows.tgz\" -C $d; Get-ChildItem \"$d\\windows\" | Select-Object -ExpandProperty Name" % b64
    )
    r = dev.ps(put, timeout=300)
    expect("install.ps1" in r.out, "copying windows/ to the G14 failed: %s" % r.out.strip()[:200])
    rec.ps("clean (removes only what the build installs)", G14_CLEAN_PS)
    install_cmd = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File %USERPROFILE%\\agent-desktop-proof\\windows\\install.ps1"
    before = json_in(dev.ps(G14_STATE_PS).out)
    r1 = rec.sh("install fresh", install_cmd, timeout=600)
    mid = json_in(dev.ps(G14_STATE_PS).out)
    fresh = rec.cmds[-1]
    r2 = rec.sh("install second", install_cmd, timeout=600)
    after = json_in(dev.ps(G14_STATE_PS).out)
    second = dict(rec.cmds[-1])
    second["changed"] = bool(mid != after or "nothing changed" not in r2.out.lower())
    (rec.out / "pre-install-state.json").write_text(json.dumps({"before": before, "after_fresh": mid, "after_second": after}, indent=1))
    return {"fresh": fresh, "second": second}


# ------------------------------------------------------------------ G14 checks around the lock
def g14_locked_check(rec, dev):
    """With the screen locked, `windows` and `shot` must refuse: exit 1 and a message that says the screen is locked.
    A blank screenshot or an empty list with exit 0 is a failure. Needs the G14 locked, so it runs before the unlock."""
    rec.begin("locked")
    locked = dev.is_locked()
    results = []
    for args in (("windows",), ("shot", dev.tmp("locked.png"))):
        results.append(rec.ad("locked " + args[0], *args))
    good = locked and all(r.exit == 1 and "locked" in r.out.lower() for r in results)
    c = dict(rec.cmds[-1])
    c["status"] = "pass" if good else "fail"
    c["exit"] = 1 if all(r.exit == 1 for r in results) else next(r.exit for r in results if r.exit != 1)
    if not locked:
        c["error"] = "the screen was not locked when this check ran"
    elif not good:
        c["error"] = "expected exit 1 and a 'screen locked' message from `windows` and `shot`: got exits %s" % ",".join(str(r.exit) for r in results)
    return c


def g14_ui_via_task(rec, dev):
    """`ui` goes through the scheduled task: it works from the ssh shell (which cannot see the desktop) and the task's two
    sides each leave a log line with a run id."""
    rec.begin("uitask")
    logfile = "($env:LOCALAPPDATA + '\\agent-desktop\\agent-desktop.log')"
    count = "powershell.exe -NoProfile -NonInteractive -Command \"if (Test-Path %s) { (Get-Content %s).Count } else { 0 }\"" % (logfile, logfile)
    n0 = int((re.search(r"\d+", rec.sh("log lines before", count).out) or re.search(r"\d+", "0")).group(0))
    r = rec.ui("ui status", "status")
    ui_cmd = rec.cmds[-1]
    n1 = int((re.search(r"\d+", rec.sh("log lines after", count).out) or re.search(r"\d+", "0")).group(0))
    tail = rec.sh("new log lines", "powershell.exe -NoProfile -NonInteractive -Command \"Get-Content %s | Select-Object -Last %d\"" % (logfile, max(n1 - n0, 1)))
    new = [ln for ln in tail.out.splitlines() if "run=" in ln]
    c = dict(ui_cmd)
    ok = r.exit == 0 and n1 - n0 >= 2 and len(new) >= 2
    c["status"] = "pass" if ok else "fail"
    if not ok:
        c["error"] = "ui status exit %d; %d new log lines (%d with a run id), expected at least 2 (one from each side of the task)" % (r.exit, n1 - n0, len(new))
    return c


# ------------------------------------------------------------------ plan (dry run)
def plan_lines(device):
    lines = ["plan for %s" % device]
    try:
        d, files = _proof_sources().digest(device, ROOT)
        lines.append("source digest %s over %d files: %s" % (d[:12], len(files), ", ".join(files)))
    except Exception as e:
        lines.append("source digest unavailable: %s" % e)
    if device == "omarchy":
        lines += ["step install_fresh: chezmoi --source <this tree> apply the one target ~/.local/bin/agent-desktop (identical bytes: nothing changes)",
                  "uses: foot terminals as click and typing targets; hyprctl as the independent read"]
    elif device == "mac-mini":
        lines += ["step install_fresh: remove ~/.local/bin/agent-desktop and ~/.local/share/agent-desktop, copy the branch to ~/.cache/agent-desktop-proof/src, render and run the 66 install step",
                  "uses: Calculator and TextEdit; osascript for the independent reads; `ui` for the N rows"]
    else:
        lines += ["step install_fresh: copy windows/ over, remove what the build installs, run windows/install.ps1",
                  "step install_second: run windows/install.ps1 again; the state fingerprint and the 'nothing changed' line must show no change",
                  "step settings_before: read lock, sign-in and power settings (read only)",
                  "check locked_screen: with the screen locked, `windows` and `shot` must exit 1 and say the screen is locked",
                  "wait unlock: poll for LogonUI to be gone (a fact), up to --unlock-timeout",
                  "uses: a WinForms pad window (rad-proof-pad) and Calculator, started in the desktop session by one-shot tasks the driver creates and deletes"]
    for rid, title in ROWS:
        if device == "omarchy" and rid in OMARCHY_NOT_OFFERED:
            lines.append("row %s %s: not_offered" % (rid, title))
        else:
            lines.append("row %s %s" % (rid, title))
    if device == "g14":
        lines += ["check ui_via_task: `ui status` works from ssh and leaves at least two run-id log lines (both sides of the task)",
                  "step settings_after: read the same settings; they must equal the first read"]
    lines.append("end: write record.json, then run check_record.py on it")
    return lines


def dry_run(device, dev):
    print("\n".join(plan_lines(device)))
    print("preconditions (read only):")
    for what, ok in dev.preflight() if device == "omarchy" else []:
        print("  %s: %s" % (what, "ok" if ok else "MISSING"))
    if device != "omarchy":
        print("  the %s checks are made when the real run starts (this dry run does not touch the device)" % device)
    return 0


# ------------------------------------------------------------------ main
def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("device", choices=sorted(DEVICES))
    ap.add_argument("--out")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only")
    ap.add_argument("--phase", choices=("all", "prepare", "rows"), default="all")
    ap.add_argument("--unlock-timeout", type=int, default=900)
    a = ap.parse_args(argv)
    device = a.device
    dev = DEVICES[device]()
    if a.dry_run:
        return dry_run(device, dev)
    out = Path(a.out) if a.out else ROOT.parent / "proof" / device
    rec = Rec(dev, out)
    for what, ok in dev.preflight():
        print("precondition %s: %s" % (what, "ok" if ok else "MISSING"))
        if not ok:
            print("stopping: precondition not met", file=sys.stderr)
            return 3
    only = set(a.only.split(",")) if a.only else None
    partial = out / "state.json"
    state = json.loads(partial.read_text()) if (partial.exists() and a.phase == "rows") else {}
    install, settings_before, checks, rows = state.get("install"), state.get("settings_before"), state.get("checks", {}), []
    made_at = None
    path = None
    try:
        if device == "omarchy":
            rows_fns = omarchy_rows(rec, dev)
            closers = [lambda: omarchy_cleanup(rec)]
        else:
            rows_fns, close_editor, close_calc = desktop_rows(rec, dev)
            closers = [close_editor, close_calc]
        if not only and a.phase in ("all", "prepare"):
            rec.begin("install")
            install = {"omarchy": install_omarchy, "mac-mini": install_mac, "g14": install_g14}[device](rec, dev)
            print("install: fresh exit %d" % install["fresh"]["exit"])
            if device == "g14":
                print("install: second run changed=%s" % install["second"]["changed"])
                settings_before, cmd = g14_settings(rec, dev, "before")
                checks["locked_screen"] = g14_locked_check(rec, dev)
                print("locked_screen: %s" % checks["locked_screen"]["status"])
                partial.write_text(json.dumps({"install": install, "settings_before": settings_before, "checks": checks}, indent=1))
                # One unlock is all that is asked for. Do not spend it on a run that cannot give a good record.
                text = "\n".join(str(x) for x in settings_before.get("powercfg", []))
                stop = []
                if install["fresh"]["exit"] != 0:
                    stop.append("the fresh install failed (exit %d)" % install["fresh"]["exit"])
                if install["second"]["exit"] != 0 or install["second"]["changed"]:
                    stop.append("the second install run failed or changed something")
                for needle in ("Console lock display off timeout", "Require a password on wakeup"):
                    if needle not in text:
                        stop.append("the settings read does not hold %r" % needle)
                if checks["locked_screen"]["status"] != "pass":
                    stop.append("the locked-screen check failed: %s" % checks["locked_screen"].get("error", ""))
                if stop:
                    print("stopping before the unlock: " + "; ".join(stop), file=sys.stderr)
                    return 4
                if a.phase == "prepare":
                    print("prepare phase done; unlock the G14, then run with --phase rows")
                    return 0
        if device == "g14" and not only:
            wait_for("the G14 to be unlocked (LogonUI gone)", lambda: not dev.is_locked(), timeout=a.unlock_timeout, interval=5)
        results = {}
        for rid, fn in rows_fns:
            if only and rid not in only:
                continue
            results[rid] = run_row(rec, rid, fn)
            print("row %s %s%s" % (rid, results[rid]["status"], (": " + results[rid]["error"]) if results[rid].get("error") else ""))
            write_record(out, {"rows": list(results.values())}, "rows-so-far.json")  # survives a crash or a re-lock
        for c in closers:
            try:
                c()
            except Exception as e:
                print("cleanup note: %s" % e)
        if only:
            write_record(out, {"rows": list(results.values())}, "record.partial.json")
            return 0
        for rid, title in ROWS:
            if rid not in results:
                results[rid] = row(rid, "not_offered", note=OMARCHY_NOTE)
        rows = [results[r] for r in ROW_IDS]
        settings = None
        if device == "g14":
            try:
                after, cmd = g14_settings(rec, dev, "after")
            except Exception as e:  # a failed read is recorded as a difference, never a lost run
                after = {"unreadable": str(e)}
            settings = {"before": settings_before, "after": after}
            try:
                checks["ui_via_task"] = g14_ui_via_task(rec, dev)
            except Exception as e:
                (out / "uitask-error.txt").write_text("%s: %s\n" % (type(e).__name__, e))
                checks["ui_via_task"] = {"command": "ui_via_task", "exit": -1, "output_file": "uitask-error.txt", "status": "fail", "error": "%s: %s" % (type(e).__name__, e)}
            print("ui_via_task: %s" % checks["ui_via_task"]["status"])
        made_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record = build_record(device, ROOT, rows, install, settings=settings, checks=checks or None, made_at=made_at)
        path = write_record(out, record)
        print("record written: %s" % path)
    except Fail as e:
        print("stopping: %s" % e, file=sys.stderr)
        return 5
    finally:
        if device == "mac-mini":
            rec.sh("remove scratch copy", "rm -rf %s" % dev.scratch, save=False)
        elif device == "g14":
            dev.ps("Remove-Item (Join-Path $env:USERPROFILE 'agent-desktop-proof') -Recurse -Force -ErrorAction SilentlyContinue; Remove-Item ($env:LOCALAPPDATA + '\\agent-desktop\\proof') -Recurse -Force -ErrorAction SilentlyContinue")
    chk = subprocess.run([sys.executable, str(HERE / "check_record.py"), "--device", device, "--record", str(path)], capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    print((chk.stdout or chk.stderr).strip())
    return chk.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
