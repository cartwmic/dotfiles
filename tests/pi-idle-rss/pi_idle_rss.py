#!/usr/bin/env python3
"""Measure settled idle memory of interactive Pi sessions (cartwmic/dotfiles#14).

One live measured session at a time. Every session runs in a throwaway HOME with an
allowlisted environment, a scripted local model backend and a per-sample ownership
marker; only marker-owned processes are ever signalled. See README.md.
"""
from __future__ import annotations

import argparse
import collections
import fcntl
import functools
import http.server
import json
import os
import pty
import random
import re
import select
import shutil
import signal
import socketserver
import statistics
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import uuid
from pathlib import Path

REAL_HOME = Path(os.environ.get("PI_IDLE_RSS_REAL_HOME") or Path.home())
REAL_AGENT = REAL_HOME / ".pi" / "agent"
MARKER = "PI_IDLE_RSS_SAMPLE"
CRED_STUBS = ("security", "op", "ssh-agent")
CRED_FILE_RE = re.compile(r"(^auth\.json|^mcp-auth|^\.env|\.pem$|^id_(rsa|ed25519|ecdsa)|\.netrc$|^\.npmrc$|^credentials?(\.json)?$)", re.I)
CRED_ENV_RE = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|CREDENTIAL|^OP_|^AWS_|^GH_|^GITHUB_)", re.I)
ENV_ALLOW = ("TERM", "LANG", "LC_ALL", "TMPDIR")


class Fatal(RuntimeError):
    """Cleanup or isolation could not be guaranteed: stop the whole run."""


class SampleRejected(RuntimeError):
    """The sample does not meet its own acceptance conditions (not settled, stage not verified, smoke failed)."""


# ----------------------------------------------------------------- pressure gate
def pressure_level() -> int:
    out = subprocess.run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True, text=True).stdout
    return int(out.strip() or 1)


def free_percent() -> int:
    out = subprocess.run(["memory_pressure", "-Q"], capture_output=True, text=True).stdout
    m = re.search(r"free percentage:\s*(\d+)%", out)
    return int(m.group(1)) if m else 0


def pressure_ok(min_free: int = 30) -> bool:
    """Non-blocking: normal pressure and enough headroom right now."""
    return pressure_level() == 1 and free_percent() >= min_free


def gate(label: str, min_free: int = 30, wait_max: int = 900, poll: int = 15, log=print) -> dict:
    """Block until memory pressure is normal and headroom is sufficient, else abort the run."""
    start = time.time()
    while True:
        level, free = pressure_level(), free_percent()
        if level == 1 and free >= min_free:
            return {"level": level, "free_pct": free, "waited_s": round(time.time() - start)}
        if time.time() - start > wait_max:
            raise Fatal(f"pressure gate '{label}' timed out (level={level}, free={free}%)")
        log(f"[gate] {label}: level={level} free={free}% waiting")
        time.sleep(poll)


class PressureWatcher(threading.Thread):
    """Raises 'rose' when the pressure level is above normal on two consecutive polls."""

    def __init__(self, interval: float = 5.0):
        super().__init__(daemon=True)
        self.interval, self.rose, self._stop = interval, threading.Event(), threading.Event()

    def run(self):
        bad = 0
        while not self._stop.wait(self.interval):
            bad = bad + 1 if pressure_level() > 1 else 0
            if bad >= 2:
                self.rose.set()

    def stop(self):
        self._stop.set()


# -------------------------------------------------------------- process ownership
def parse_ps(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        parts = line.strip().split(None, 4)
        if len(parts) >= 4 and parts[0].isdigit() and parts[1].isdigit() and parts[3].isdigit():
            if parts[2].startswith("Z"):
                continue  # exited, only awaiting reaping by its parent
            rows.append({"pid": int(parts[0]), "ppid": int(parts[1]), "rss_kb": int(parts[3]), "line": parts[4] if len(parts) > 4 else ""})
    return rows


def ps_table() -> list[dict]:
    return parse_ps(subprocess.run(["ps", "-E", "-axww", "-o", "pid=,ppid=,stat=,rss=,command="], capture_output=True, text=True).stdout)


def owned_set(rows: list[dict], marker_value: str, root_pid: int | None = None) -> list[dict]:
    """Processes started by this sample: marker in the environment, or descendants of the root."""
    token = f"{MARKER}={marker_value}"
    owned = {r["pid"]: r for r in rows if token in r["line"]}
    if root_pid is not None:
        children: dict[int, list[dict]] = {}
        for r in rows:
            children.setdefault(r["ppid"], []).append(r)
        stack = [root_pid]
        while stack:
            for c in children.get(stack.pop(), []):
                if c["pid"] not in owned:
                    owned[c["pid"]] = c
                    stack.append(c["pid"])
        if root_pid in {r["pid"] for r in rows}:
            owned.setdefault(root_pid, next(r for r in rows if r["pid"] == root_pid))
    owned.pop(os.getpid(), None)
    return sorted(owned.values(), key=lambda r: r["pid"])


ENV_TOKEN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def cmd_name(line: str) -> str:
    """Executable (and script) basename only, cut before the appended environment; never returns env or args."""
    toks = []
    for t in line.split():
        if ENV_TOKEN_RE.match(t) and toks:
            break
        toks.append(t)
    if not toks:
        return "?"
    name = os.path.basename(toks[0])
    if name in ("node", "python3", "python", "npm", "sh", "bash") and len(toks) > 1:
        name += " " + os.path.basename(toks[1])
    return name


_UNIT = {"B": 1 / 1024, "KB": 1, "MB": 1024, "GB": 1024 * 1024}


def parse_footprint(text: str) -> int | None:
    m = re.search(r"phys_footprint:\s*([\d.]+)\s*(B|KB|MB|GB)\b", text)
    return int(float(m.group(1)) * _UNIT[m.group(2)]) if m else None


def footprint_kb(pid: int) -> int | None:
    out = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True).stdout
    return parse_footprint(out)


def kill_owned(marker_value: str, root_pid: int | None, grace: float = 10.0) -> None:
    """SIGTERM then SIGKILL marker-owned processes only; verify none remain or raise Fatal."""
    token = f"{MARKER}={marker_value}"
    for sig, wait in ((signal.SIGTERM, grace), (signal.SIGKILL, 5.0)):
        rows = owned_set(ps_table(), marker_value, root_pid)
        if not rows:
            return
        for r in rows:
            cur = next((x for x in ps_table() if x["pid"] == r["pid"]), None)
            if cur and (token in cur["line"] or cur["pid"] == root_pid):
                try:
                    os.kill(r["pid"], sig)
                except ProcessLookupError:
                    pass
        end = time.time() + wait
        while time.time() < end:
            if not owned_set(ps_table(), marker_value, root_pid):
                return
            time.sleep(0.5)
    left = owned_set(ps_table(), marker_value, root_pid)
    if left:
        raise Fatal(f"owned processes survived teardown: {[r['pid'] for r in left]}")


# ------------------------------------------------------------- scripted backend
class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            req = {}
        self.server.requests += 1
        chunk = lambda delta, fin=None, usage=None: "data: " + json.dumps({
            "id": "scripted", "object": "chat.completion.chunk", "created": int(time.time()), "model": "dummy-1",
            "choices": [{"index": 0, "delta": delta, "finish_reason": fin}], **({"usage": usage} if usage else {})}) + "\n\n"
        text = "Scripted summary: earlier conversation covered synthetic topics only." if "summar" in json.dumps(req)[:20000].lower() else "OK."
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if req.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for part in (chunk({"role": "assistant", "content": ""}), chunk({"content": text}), chunk({}, "stop", usage), "data: [DONE]\n\n"):
                self.wfile.write(part.encode())
                self.wfile.flush()
        else:
            data = json.dumps({"id": "scripted", "object": "chat.completion", "model": "dummy-1", "usage": usage,
                               "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)


class Backend(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.requests = 0
        threading.Thread(target=self.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"


# ------------------------------------------------------------- variant handling
def _drop_nested_sdk(agent: Path, package: str) -> None:
    for scope in ("@mariozechner", "@earendil-works"):
        shutil.rmtree(agent / "git" / "github.com" / package / "node_modules" / scope, ignore_errors=True)


# Patches simulate a candidate fix inside the per-session clone of the package checkouts (originals untouched).
PATCHES = {
    "pi-sub-no-nested-sdk": lambda agent: _drop_nested_sdk(agent, "cartwmic/pi-sub"),
}


def parse_variant(spec: str) -> dict:
    """core | full | full-nomcp | full-pkg:SUBSTR | full-mcp:NAME | full-ext:a+b | full-ext:* (combine with '/')."""
    v = {"name": spec, "base": "full", "drop_pkgs": [], "drop_mcp": [], "drop_ext": [], "no_mcp": False, "patches": []}
    if spec == "core":
        v["base"] = "core"
        return v
    parts = spec.split("/")
    if parts[0] != "full" and not parts[0].startswith("full-"):
        raise ValueError(f"unknown variant '{spec}'")
    for p in parts:
        if p == "full":
            continue
        if p == "full-nomcp":
            v["no_mcp"] = True
        elif p.startswith("full-pkg:"):
            v["drop_pkgs"] += p.split(":", 1)[1].split("+")
        elif p.startswith("full-mcp:"):
            v["drop_mcp"] += p.split(":", 1)[1].split("+")
        elif p.startswith("full-patch:"):
            v["patches"] += p.split(":", 1)[1].split("+")
            for n in v["patches"]:
                if n not in PATCHES:
                    raise ValueError(f"unknown patch '{n}'")
        elif p.startswith("full-ext:"):
            v["drop_ext"] += p.split(":", 1)[1].split("+")
        else:
            raise ValueError(f"unknown variant part '{p}'")
    return v


def package_key(source: str) -> str:
    """Last path component of a package source without ref or .git suffix (exact-match key for drop-one variants)."""
    key = re.sub(r"^(git:|https?://|npm:)", "", source).rstrip("/").split("/")[-1]
    return re.sub(r"(\.git)?(@[^@/]*)?$", "", key)


def filter_settings(settings: dict, v: dict, backend_url: str) -> dict:
    s = json.loads(json.dumps(settings))
    s.pop("deviceId", None)
    s["defaultProvider"], s["defaultModel"] = "dummy", "dummy-1"
    s["enabledModels"] = ["dummy/dummy-1"]
    if v["base"] == "core":
        s["packages"] = []
    else:
        def src(e):
            return e if isinstance(e, str) else e.get("source", "")
        s["packages"] = [e for e in s.get("packages", []) if package_key(src(e)) not in v["drop_pkgs"]]
    return s


def filter_mcp(mcp: dict, v: dict) -> dict:
    servers = {}
    for name, cfg in (mcp.get("mcpServers") or {}).items():
        if name in v["drop_mcp"]:
            continue
        cfg = json.loads(json.dumps(cfg))
        if "headers" in cfg:
            cfg["headers"] = {k: "synthetic-not-a-credential" for k in cfg["headers"]}
        if "env" in cfg:
            cfg["env"] = {k: "synthetic-not-a-credential" for k in cfg["env"]}
        servers[name] = cfg
    return {**{k: x for k, x in mcp.items() if k != "mcpServers"}, "mcpServers": servers}


def dummy_models(backend_url: str) -> dict:
    return {"providers": {"dummy": {"baseUrl": backend_url, "api": "openai-completions", "apiKey": "synthetic-not-a-credential",
            "models": [{"id": "dummy-1", "name": "Scripted", "contextWindow": 200000, "maxTokens": 8192, "input": ["text"], "reasoning": False,
                        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}]}}}


def release_paths() -> tuple[Path, Path]:
    version = (REAL_AGENT / "install" / "current-version").read_text().strip()
    pi_bin = REAL_AGENT / "install" / "releases" / version / "node_modules" / ".bin" / "pi"
    node_dir = Path(os.environ.get("XDG_DATA_HOME") or REAL_HOME / ".local/share") / "pi-node" / "current" / "bin"
    if not (node_dir / "node").exists():
        found = shutil.which("node")
        if not found:
            raise Fatal("node not found (needed by the managed Pi launcher)")
        node_dir = Path(found).resolve().parent
    if not pi_bin.exists():
        raise Fatal(f"managed Pi executable missing: {pi_bin}")
    return pi_bin, node_dir


def clone(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if subprocess.run(["cp", "-c", "-R", str(src), str(dst)], capture_output=True).returncode != 0:
        shutil.copytree(src, dst, symlinks=True)


class Store:
    """Read-only-by-convention clones of the large package checkouts, made once per invocation."""

    def __init__(self, root: Path):
        self.root = root
        for name, src in (("git", REAL_AGENT / "git"), ("npm", REAL_AGENT / "npm"), ("npx", REAL_HOME / ".npm" / "_npx"), ("cacache", REAL_HOME / ".npm" / "_cacache")):
            if src.exists():
                clone(src, root / name)


def build_home(v: dict, root: Path, store: Store, backend_url: str, workdir: Path) -> dict:
    """Create the throwaway HOME for a variant. Never copies credential files; returns the manifest."""
    home = root / "home"
    agent = home / ".pi" / "agent"
    (agent / "sessions").mkdir(parents=True)
    manifest = {"provisioned": [], "isolated": [], "excluded": [], "dropped_ext": [], "placed": []}
    (agent / "models.json").write_text(json.dumps(dummy_models(backend_url)))
    settings = json.loads((REAL_AGENT / "settings.json").read_text())
    (agent / "settings.json").write_text(json.dumps(filter_settings(settings, v, backend_url)))
    (agent / "trust.json").write_text(json.dumps({str(workdir): True}))
    for name in ("auth.json", "mcp-auth.json", "models-store.json"):
        manifest["excluded"].append(name)
    if v["base"] == "full":
        for name in ("AGENTS.md", "APPEND_SYSTEM.md", "pi-stamp.json", "pi-sub-bar-settings.json"):
            if (REAL_AGENT / name).exists():
                shutil.copy2(REAL_AGENT / name, agent / name)
                manifest["placed"].append(name)
        if (REAL_AGENT / "bin" / "fd").exists():
            (agent / "bin").mkdir()
            shutil.copy2(REAL_AGENT / "bin" / "fd", agent / "bin" / "fd")
            manifest["placed"].append("bin/fd")
        if (REAL_AGENT / "agents").is_dir():
            shutil.copytree(REAL_AGENT / "agents", agent / "agents")
        ext_src = REAL_AGENT / "extensions"
        (agent / "extensions").mkdir()
        everything = "*" in v["drop_ext"]
        for e in sorted(ext_src.iterdir()):
            if everything or e.name in v["drop_ext"] or e.stem in v["drop_ext"]:
                manifest["dropped_ext"].append(e.name)
                continue
            (shutil.copytree if e.is_dir() else shutil.copy2)(e, agent / "extensions" / e.name)
            manifest["placed"].append("extensions/" + e.name)
        for name in ("git", "npm"):
            if (store.root / name).exists():
                if name == "git" and v["patches"]:
                    clone(store.root / name, agent / name)  # private APFS clone so a patch never touches the shared store
                    for n in v["patches"]:
                        PATCHES[n](agent)
                    manifest["provisioned"].append(f"git (private clone, patches: {','.join(v['patches'])})")
                    continue
                (agent / name).symlink_to(store.root / name)
                manifest["provisioned"].append(f"{name} (clone)")
        if not v["no_mcp"] and (REAL_AGENT / "mcp.json").exists():
            (agent / "mcp.json").write_text(json.dumps(filter_mcp(json.loads((REAL_AGENT / "mcp.json").read_text()), v)))
        # recap CLI: copy the wrapper (so its relative lookup stays in the throwaway HOME), link the code read-only
        wrapper = REAL_HOME / ".local" / "bin" / "session-recap"
        if wrapper.exists():
            (home / ".local" / "bin").mkdir(parents=True)
            shutil.copy2(wrapper, home / ".local" / "bin" / "session-recap")
            code = REAL_HOME / ".local" / "share" / "session-recap"
            (home / ".local" / "share").mkdir(parents=True)
            (home / ".local" / "share" / "session-recap").symlink_to(code)
            manifest["provisioned"].append("~/.local/bin/session-recap (+code, read-only link; state isolated)")
        if (store.root / "npx").exists():
            (home / ".npm").mkdir()
            (home / ".npm" / "_npx").symlink_to(store.root / "npx")
            if (store.root / "cacache").exists():
                (home / ".npm" / "_cacache").symlink_to(store.root / "cacache")
            manifest["provisioned"].append("~/.npm/_npx and _cacache (clones; offline npx so MCP stdio servers start as in a live session)")
    manifest["isolated"].append("everything else under the throwaway HOME")
    tools = home / ".tools"
    stubs = home / ".stubs"
    tools.mkdir()
    stubs.mkdir()
    for c in CRED_STUBS:
        s = stubs / c
        s.write_text("#!/bin/sh\nexit 44\n")
        s.chmod(0o755)
    wanted = ["python3", "node", "npx", "npm", "furi", "git", "rtk", "rg"]
    for c in wanted:
        real = shutil.which(c)
        if real and not (tools / c).exists():
            (tools / c).symlink_to(real)
    return {"home": home, "agent": agent, "stubs": stubs, "tools": tools, "manifest": manifest}


def launch_env(h: dict, marker_value: str, node_dir: Path) -> dict:
    env = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
    env.update({
        "HOME": str(h["home"]), "PI_CODING_AGENT_DIR": str(h["agent"]), "USER": "piidle", "LOGNAME": "piidle",
        "PATH": ":".join([str(h["stubs"]), str(node_dir), str(h["tools"]), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]),
        "PI_OFFLINE": "1", "PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0", "npm_config_offline": "true",
        "TERM": env.get("TERM", "xterm-256color"), "PI_MANAGED_INSTALL_ROOT": str(REAL_AGENT / "install"),
        "SESSION_RECAP_PYTHON": str(h["tools"] / "python3"), MARKER: marker_value,
    })
    return env


# ------------------------------------------------------------------- isolation
def placed_credential_files(home: Path) -> list[str]:
    """Credential-looking file names among files physically placed (symlinked stores are not walked)."""
    found = []
    for dirpath, dirs, files in os.walk(home, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(dirpath) / d).is_symlink()]
        found += [str(Path(dirpath, f).relative_to(home)) for f in files if CRED_FILE_RE.search(f)]
    return found


def credential_env(env: dict) -> list[str]:
    return sorted(k for k in env if CRED_ENV_RE.search(k) and k != MARKER)


def scan_extension_deps(ext_dir: Path) -> dict:
    """Static scan of local extensions for home-relative and credential-service references (names only)."""
    out = {}
    pats = {"home": re.compile(r"homedir\(\)|process\.env\.HOME|Path\.home\(\)|expanduser|\$HOME"),
            "auth_json": re.compile(r"auth\.json"), "keychain": re.compile(r"find-generic-password"),
            "recap_cli": re.compile(r"session-recap"), "cred_helper": re.compile(r"""["'](op|security|ssh-agent|gh|aws|gcloud)["']\s*,""")}
    for p in sorted(ext_dir.rglob("*")):
        if p.suffix not in (".ts", ".mjs", ".js", ".py") or ".test." in p.name or "node_modules" in p.parts:
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        hits = [k for k, rx in pats.items() if rx.search(text)]
        if hits:
            key = p.relative_to(ext_dir).parts[0]
            out.setdefault(key, set()).update(hits)
    return {k: sorted(v) for k, v in out.items()}


CRED_HELPERS = ("op", "security", "ssh-agent", "gh", "aws", "gcloud")


def classify_dependencies(deps: dict, resolved: dict, files_placed: list[str], recap_present: bool) -> dict:
    """Every home-relative / credential reference found by the scan must be accounted for:
    isolated (lives in the throwaway HOME), provisioned (recap CLI present), or excluded (credential file absent,
    helper stubbed or unresolvable). Returns the unclassified ones."""
    unclassified = {}
    for ext, hits in deps.items():
        bad = []
        if "auth_json" in hits and files_placed:
            bad.append("auth_json: credential-looking file placed")
        if ("keychain" in hits or "cred_helper" in hits):
            live = [h for h, where in resolved.items() if where not in ("stub", "absent")]
            if live:
                bad.append("credential helper resolvable to a real binary: " + ",".join(sorted(live)))
        if "recap_cli" in hits and not recap_present:
            bad.append("recap CLI not provisioned")
        if bad:
            unclassified[ext] = bad
    return unclassified


def resolve_helpers(env: dict, stubs: Path) -> dict:
    out = {}
    for h in CRED_HELPERS:
        where = subprocess.run(["sh", "-c", f"command -v {h}"], env=env, capture_output=True, text=True).stdout.strip()
        out[h] = "absent" if not where else ("stub" if where.startswith(str(stubs)) else "real")
    return out


COMMAND_RE = re.compile(r"""registerCommand\(\s*["'`]([A-Za-z0-9:_-]+)["'`]""")


def scan_commands(root: Path) -> set[str]:
    names = set()
    for p in root.rglob("*"):
        if p.suffix not in (".ts", ".mjs", ".js") or ".test." in p.name or "node_modules" in p.parts:
            continue
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        for mt in COMMAND_RE.finditer(text):
            # commands that describe themselves as internal are not listed in the menu
            if re.search(r"description:\s*[\"'`]Internal", text[mt.end(): mt.end() + 160]):
                continue
            names.add(mt.group(1))
    return names


def package_dir(agent: Path, source: str) -> Path | None:
    s = source if isinstance(source, str) else source.get("source", "")
    if s.startswith("npm:"):
        return agent / "npm" / "node_modules" / s[4:].split("@", 1)[0] if not s[4:].startswith("@") else agent / "npm" / "node_modules" / ("@" + s[5:].split("@", 1)[0])
    m = re.match(r"^(?:git:|https?://)(github\.com)/([^/]+)/([^/@]+?)(?:\.git)?(?:@.*)?$", s)
    return agent / "git" / m.group(1) / m.group(2) / m.group(3) if m else None


def expected_commands(agent: Path, v: dict) -> dict:
    """Slash commands that the variant's loaded extensions register as literals, by owner (names only)."""
    out: dict[str, set[str]] = {}
    ext = agent / "extensions"
    if ext.exists():
        for e in sorted(ext.iterdir()):
            if e.is_dir():
                found = scan_commands(e)
                if found:
                    out[f"ext:{e.name}"] = found
    try:
        packages = json.loads((agent / "settings.json").read_text()).get("packages", [])
    except (OSError, ValueError):
        packages = []
    for entry in packages:
        d = package_dir(agent, entry)
        if not d or not d.exists():
            continue
        try:
            entries = json.loads((d / "package.json").read_text()).get("pi", {}).get("extensions", [])
        except (OSError, ValueError):
            entries = []
        found = set()
        for rel in entries or []:
            target = (d / rel).parent if (d / rel).suffix else d / rel
            found |= scan_commands(target)
        if found:
            out[f"pkg:{package_key(entry if isinstance(entry, str) else entry.get('source', ''))}"] = found
    return {k: sorted(vv) for k, vv in out.items()}


MENU_NAME_WIDTH = 30  # the menu truncates long command names


HEADER_RE = re.compile(r"\[Extensions\]\s+((?:[@\w./:+-]+,\s*)*[@\w./:+-]+)")


def header_extensions(head_text: str) -> list[str]:
    """Entries of Pi's startup '[Extensions]' header (every loaded extension, with or without commands)."""
    mt = HEADER_RE.search(head_text)
    return [x.strip() for x in mt.group(1).split(",")] if mt else []


def expected_loaded(agent: Path) -> dict:
    """Owners that must appear in Pi's startup header, as {owner: [set of acceptable exact entries, one set per required entry]}."""
    owners: dict[str, list[set[str]]] = {}
    ext = agent / "extensions"
    if ext.exists():
        for e in sorted(ext.iterdir()):
            if e.is_dir():
                has_entry = any((e / n).exists() for n in ("index.ts", "index.js", "index.mjs")) or (e / "package.json").exists()
                if has_entry:  # config-only or docs-only directories load nothing
                    owners[f"ext:{e.name}"] = [{e.name}]
            elif e.suffix in (".ts", ".js", ".mjs"):
                owners[f"ext:{e.name}"] = [{e.name}]
    try:
        packages = json.loads((agent / "settings.json").read_text()).get("packages", [])
    except (OSError, ValueError):
        packages = []
    for entry in packages:
        src = entry if isinstance(entry, str) else entry.get("source", "")
        d = package_dir(agent, entry)
        key = package_key(src)
        if isinstance(entry, dict) and entry.get("extensions") == []:
            owners[f"pkg:{key}"] = []  # configured with no extensions: it loads nothing by design
            continue
        name = src[4:].split("@", 1)[0] if src.startswith("npm:") and not src[4:].startswith("@") else ("@" + src[5:].split("@", 1)[0] if src.startswith("npm:") else key)
        try:
            entries = json.loads((d / "package.json").read_text()).get("pi", {}).get("extensions", []) if d else []
        except (OSError, ValueError):
            entries = []
        required: list[set[str]] = []
        for rel in entries or []:
            parts = Path(rel).parts
            base = Path(rel).name
            directory = parts[-2] if len(parts) >= 2 and parts[-2] != "." else ""
            cands = {name, key, base, f"{name}:{base}"}
            if directory:
                cands |= {directory, f"{key}/{directory}", f"{name}:{directory}"}
            if len(parts) >= 3 and parts[-3] != ".":
                cands.add(f"{parts[-3]}/{directory}")
            required.append(cands)
        owners[f"pkg:{key}"] = required or [{name, key}]
    return owners


def missing_loaded(tokens: list[str], owners: dict) -> list[str]:
    """Owners with a required entry that no header entry equals exactly (no substring matching: pi-subagents is not pi-sub)."""
    seen = set(tokens) | {t.split(":", 1)[0] for t in tokens}
    missing = []
    for owner, required in owners.items():
        if any(not (cands & seen) for cands in required):
            missing.append(owner)
    return missing


def menu_has(screen_text: str, name: str) -> bool:
    """True when the command menu lists the command: an arrow or space, the (possibly truncated) name, then its source tag."""
    shown = re.escape(name[:MENU_NAME_WIDTH])
    tail = r"[A-Za-z0-9_:-]*" if len(name) > MENU_NAME_WIDTH else ""
    return re.search(r"(?:→\s*|\s)" + shown + tail + r"\s+\[", screen_text) is not None


def preflight(v: dict, root: Path, store: Store, node_dir: Path, workdir: Path) -> dict:
    h = build_home(v, root, store, "http://127.0.0.1:1/v1", workdir)
    env = launch_env(h, "preflight", node_dir)
    checks = []

    def add(name, ok, detail=""):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    probe = subprocess.run([str(node_dir / "node"), "-e", "console.log(require('os').homedir())"], env=env, capture_output=True, text=True)
    add("home-resolves-to-throwaway", probe.stdout.strip() == str(h["home"]), "node os.homedir() inside launch env")
    bad = placed_credential_files(h["home"])
    add("no-credential-looking-files-placed", not bad, f"count={len(bad)}")
    add("no-credential-looking-env", not credential_env(env), f"count={len(credential_env(env))}")
    sec = subprocess.run(["security", "find-generic-password", "-s", "pi-idle-rss-probe"], env=env, capture_output=True, text=True)
    add("keychain-lookup-fails", sec.returncode != 0 and not sec.stdout, f"exit={sec.returncode}")
    which = subprocess.run(["sh", "-c", "command -v security"], env=env, capture_output=True, text=True).stdout.strip()
    add("credential-stub-first-on-path", which == str(h["stubs"] / "security"), "")
    deps = scan_extension_deps(h["agent"] / "extensions") if (h["agent"] / "extensions").exists() else {}
    recap = h["home"] / ".local" / "bin" / "session-recap"
    resolved = resolve_helpers(env, h["stubs"])
    unclassified = classify_dependencies(deps, resolved, placed_credential_files(h["home"]), recap.exists())
    add("home-dependencies-classified", not unclassified, f"extensions_with_refs={len(deps)} unclassified={len(unclassified)} helpers={resolved}")
    exp = expected_commands(h["agent"], v)
    add("expected-commands-found-by-scan", v["base"] == "core" or bool(exp), f"owners={len(exp)} commands={sum(len(x) for x in exp.values())}")
    if recap.exists():
        r = subprocess.run([str(recap), "list", "--json", "--omit-coverage-units"], env=env, capture_output=True, text=True, timeout=60)
        try:
            listed = json.loads(r.stdout or "null")
        except ValueError:
            listed = None
        add("smoke:recap-cli-functional", r.returncode == 0 and listed is not None, f"exit={r.returncode} json={'yes' if listed is not None else 'no'}")
    return {"variant": v["name"], "ok": all(c["ok"] for c in checks), "checks": checks, "manifest": h["manifest"], "extension_deps": deps, "unclassified": unclassified, "expected_commands": exp}


# ----------------------------------------------------------------- pty session
ERROR_RE = re.compile(rb"(?i)failed to load|extension error|cannot find module")


class Session:
    def __init__(self, v: dict, root: Path, store: Store, backend: Backend, node_dir: Path, session_file: Path | None = None):
        self.v, self.root, self.marker = v, root, uuid.uuid4().hex[:12]
        self.workdir = root / "work"
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.h = build_home(v, root, store, backend.url, self.workdir)
        self.env = launch_env(self.h, self.marker, node_dir)
        self.pi_bin, _ = release_paths()
        self.session_file = session_file
        self.expected = expected_commands(self.h["agent"], v)
        self._backend = backend
        self.buf = b""
        self.head = b""
        self.err_count = 0
        self._carry = b""
        self.proc = None
        self.master = None

    def start(self):
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 160, 0, 0))
        args = [str(self.pi_bin), "--model", "dummy/dummy-1"]
        if self.session_file:
            args += ["--session", str(self.session_file)]
        self.proc = subprocess.Popen(args, stdin=slave, stdout=slave, stderr=slave, env=self.env, cwd=self.workdir,
                                     close_fds=True, start_new_session=True)
        os.close(slave)

    def pump(self, seconds: float, abort: threading.Event | None = None) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if abort is not None and abort.is_set():
                return False
            r, _, _ = select.select([self.master], [], [], 0.5)
            if r:
                try:
                    data = os.read(self.master, 65536)
                except OSError:
                    break
                self.buf = (self.buf + data)[-65536:]
                self.err_count += len(ERROR_RE.findall(self._carry + data))
                self._carry = data[-48:]
                if len(self.head) < 60000:
                    self.head += data
        return True

    def send(self, text: str):
        os.write(self.master, text.encode() + b"\r")

    def measure(self) -> dict:
        rows = owned_set(ps_table(), self.marker, self.proc.pid)
        pi = next((r for r in rows if r["pid"] == self.proc.pid), None)
        fps = {r["pid"]: footprint_kb(r["pid"]) for r in rows}
        return {"owned": [{"name": cmd_name(r["line"]), "rss_kb": r["rss_kb"]} for r in rows],
                "rss_pi_kb": pi["rss_kb"] if pi else None, "rss_owned_kb": sum(r["rss_kb"] for r in rows),
                "fp_pi_kb": fps.get(self.proc.pid), "fp_owned_kb": sum(x or 0 for x in fps.values()), "owned_count": len(rows)}

    def screen_text(self, tail: int = 2500) -> str:
        txt = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07", b" ", self.buf).decode("utf8", "ignore")
        return re.sub(r"\s+", " ", txt)[-tail:]

    def head_text(self) -> str:
        txt = re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07", b" ", self.head).decode("utf8", "ignore")
        return re.sub(r"\s+", " ", txt)

    def loaded_check(self) -> dict:
        """Every owner (local extension or package) in the variant must appear in the startup header; load errors fail."""
        tokens = header_extensions(self.head_text())
        owners = expected_loaded(self.h["agent"])
        missing = missing_loaded(tokens, owners) if self.v["base"] != "core" else []
        return {"header_entries": len(tokens), "owners": len(owners), "missing": missing, "load_error_markers": self.load_errors()}

    def child_pids(self) -> set[int]:
        return {r["pid"] for r in owned_set(ps_table(), self.marker, self.proc.pid) if r["pid"] != self.proc.pid}

    def smoke_commands(self, everything: bool = False, abort: threading.Event | None = None) -> dict | None:
        """Type an expected command into the editor and require the command menu to list it, then clear the line.
        The menu lists exactly what the loaded extensions registered; nothing is executed. By default one representative
        command per loaded owner (extension or package); everything=True checks every literal command."""
        missing, checked = [], 0
        for owner, names in sorted(self.expected.items()):
            for n in (names if everything else names[:1]):
                self.buf = b""
                os.write(self.master, ("/" + n).encode())
                if not self.pump(2.5, abort):
                    return None
                checked += 1
                if not menu_has(self.screen_text(), n):
                    missing.append(f"{owner}:{n}")
                os.write(self.master, b"\x15")
                self.pump(0.5)
        return {"checked": checked, "missing": missing}

    def backend_requests(self) -> int:
        return getattr(self, "_backend", None).requests if getattr(self, "_backend", None) else -1

    def load_errors(self) -> int:
        """Cumulative since start; independent of the screen buffer, which the command smoke clears."""
        return self.err_count

    def stop(self):
        try:
            if self.proc and self.proc.poll() is None:
                try:
                    self.send("/quit")
                    self.pump(6)
                except OSError:
                    pass
        finally:
            if self.proc:
                try:
                    kill_owned(self.marker, self.proc.pid)
                finally:
                    try:
                        self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
            if self.master is not None:
                try:
                    os.close(self.master)
                except OSError:
                    pass


def wait_settled(session: Session, abort: threading.Event, window: int = 3, gap: float = 10.0, tol: float = 0.03, max_s: float = 300.0):
    """After the minimum settle, wait until total owned RSS varies by <= tol over a window of readings."""
    hist: list[int] = []
    start = time.time()
    while time.time() - start < max_s:
        if not session.pump(gap, abort):
            return None
        hist.append(sum(r["rss_kb"] for r in owned_set(ps_table(), session.marker, session.proc.pid)))
        if len(hist) >= window and max(hist[-window:]) <= min(hist[-window:]) * (1 + tol):
            return {"settled": True, "extra_wait_s": round(time.time() - start)}
    return {"settled": False, "extra_wait_s": round(time.time() - start)}


def median_reading(session: Session, n: int = 3, gap: float = 5.0, abort: threading.Event | None = None) -> dict | None:
    readings = []
    for _ in range(n):
        readings.append(session.measure())
        if not session.pump(gap, abort):
            return None
    out = {}
    for k in readings[0]:
        if k == "owned":
            out[k] = readings[-1][k]
            continue
        vals = [r[k] for r in readings if r[k] is not None]
        out[k] = int(statistics.median(vals)) if vals else None
    out["pi_readings_kb"] = [r["rss_pi_kb"] for r in readings]
    return out


AGED_STAGES = {"turn": ("after_turn", "continue", 25), "compact": ("after_compact", "/compact", 90), "reload": ("after_reload", "/reload", 60)}


def aged_driver(s: Session, watcher: PressureWatcher, log, order=("turn", "compact", "reload")) -> dict | None:
    """Loaded aged session, then one scripted turn, one compaction and one /reload, each gated and measured."""
    stages = {}

    def reading(name, wait):
        st = wait_settled(s, watcher.rose, max_s=wait)
        if st is None:
            return False
        if not st["settled"]:
            raise SampleRejected(f"unsettled at {name}")
        rd = median_reading(s, abort=watcher.rose)
        if rd is None:
            return False
        stages[name] = {**rd, "settle": st}
        return True

    if not reading("loaded", 420):
        return None
    stages["loaded"]["loaded"] = s.loaded_check()
    sm = s.smoke_commands(everything=False, abort=watcher.rose)
    if sm is None:
        return None
    stages["loaded"]["smoke"] = sm
    for name, command, extra in (AGED_STAGES[k] for k in order):
        # a live aged session is memory-heavy: never wait for pressure to ease with it running; discard and back off
        if watcher.rose.is_set() or not pressure_ok():
            log(f"[aged] pressure not normal before {name}: discarding this sample")
            return None
        before_children = s.child_pids()
        s.send(command)
        if not s.pump(extra, watcher.rose):
            return None
        if not reading(name, 300):
            return None
        stages[name]["backend_requests"] = s.backend_requests()
        if name == "after_compact":
            n = count_marker(s.session_file, b'"type":"compaction"') if s.session_file and Path(s.session_file).exists() else 0
            stages[name]["compaction_entries"] = n
            if n < 1:
                raise SampleRejected("no compaction entry recorded after /compact")
        if name == "after_reload":
            after_children = s.child_pids()
            gone, started = before_children - after_children, after_children - before_children
            stages[name]["child_pids_replaced"] = len(gone)
            stages[name]["child_pids_started"] = len(started)
            # a child that merely exited is not a reload: a new extension-owned child must also have started
            stages[name]["reload_verified"] = bool(before_children) and bool(gone) and bool(started)
            if not before_children:
                raise SampleRejected("/reload cannot be verified: no extension-owned child process existed before it")
            if not stages[name]["reload_verified"]:
                raise SampleRejected("/reload did not restart any extension-owned child process")
    return stages


def accept_sample(ok: bool, reason: str | None, pressure_rose: bool, load_errors: int, loaded: dict | None, smoke: dict | None, v: dict, smoke_required: bool = False) -> tuple:
    """Final decision, taken after every reading and smoke step: (accepted, reason, variant_effects)."""
    if not ok:
        return False, reason or "pressure", None
    if pressure_rose:
        return False, "pressure", None
    if load_errors:
        return False, f"load errors seen ({load_errors})", None
    if loaded is None and v["base"] != "core":
        return False, "loaded-owner inventory missing: no evidence is not a pass", None
    if loaded and loaded.get("missing"):
        return False, "smoke: loaded-extension check failed missing=" + ",".join(loaded["missing"]), None
    if smoke is None and smoke_required:
        return False, "command-registration smoke missing: no evidence is not a pass", None
    if smoke and smoke.get("missing"):
        if v["drop_pkgs"] or v["drop_ext"] or v["drop_mcp"] or v["no_mcp"] or v["patches"]:
            # removing a part can legitimately stop a dependent part from registering a command: a measured effect
            return True, None, list(smoke["missing"])
        return False, "smoke: registered commands missing " + ",".join(smoke["missing"]), None
    return True, None, None


def run_sample(v, root, store, backend, node_dir, settle, out_file, tag="fresh", session_file=None, driver=None, log=print, max_settle=300.0, smoke=False):
    for attempt in range(3):
        reason = None
        before = gate(f"launch {v['name']}", log=log)
        watcher = PressureWatcher()
        watcher.start()
        s = Session(v, root / f"s-{uuid.uuid4().hex[:6]}", store, backend, node_dir, None)
        if callable(session_file):
            s.session_file = session_file(s.root / "aged" / "session.jsonl", s.workdir)
        record = {"variant": v["name"], "tag": tag, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "pressure_before": before, "attempt": attempt}
        try:
            s.start()
            ok = s.pump(settle, watcher.rose)
            if ok and s.proc.poll() is not None:
                record["aborted"] = "pi-exited"
                record["exit_code"] = s.proc.returncode
                record["load_error_markers"] = s.load_errors()
                tail = re.sub(r"\s+", " ", re.sub(rb"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07", b" ", s.buf).decode("utf8", "ignore"))[-400:]
                log(f"[sample] Pi exited early for {v['name']}: {tail}")
                ok = False
                bad_variant = True
            if ok:
                st = wait_settled(s, watcher.rose, max_s=max_settle)
                ok = st is not None
                record["settle"] = st
                if st is not None and not st["settled"]:
                    ok, reason = False, "unsettled"
            if ok and driver:
                try:
                    stages = driver(s, watcher, log)
                except SampleRejected as e:
                    stages, reason = None, f"rejected: {e}"
                ok = stages is not None
            if ok and driver is None:
                reading = median_reading(s, abort=watcher.rose)
                if reading is None:
                    ok = False
                else:
                    record.update(reading)
            if ok and driver is not None:
                first = stages.get("loaded", {})
                record["loaded"], record["smoke"] = first.get("loaded"), first.get("smoke")
            if ok and driver is None:
                record["loaded"] = s.loaded_check()  # cheap (startup header + error count): mandatory on every sample
            if ok and smoke and driver is None:
                sm = s.smoke_commands(everything=(v["name"] == "full"), abort=watcher.rose)
                if sm is None:
                    ok = False
                else:
                    record["smoke"] = sm
            # one final decision after every pump: nothing that arrives later can be missed
            ok, reason, effects = accept_sample(ok, reason, watcher.rose.is_set(), s.load_errors(), record.get("loaded"), record.get("smoke"), v, smoke_required=bool(smoke or driver))
            record["load_error_markers"] = s.load_errors()
            if effects:
                record["variant_effects"] = effects
            if not ok:
                record["aborted"] = reason or "pressure"
                log(f"[sample] discarding sample {v['name']} (attempt {attempt}): {record['aborted']}")
            else:
                record["backend_requests"] = backend.requests
        finally:
            watcher.stop()
            s.stop()
            shutil.rmtree(s.root, ignore_errors=True)
        record["owned_after_teardown"] = len(owned_set(ps_table(), s.marker, None))
        if record.get("aborted") == "pi-exited":
            with open(out_file, "a") as f:
                f.write(json.dumps(record) + "\n")
            return record
        rows = [record]
        if driver and not record.get("aborted"):
            rows = [{**record, "tag": f"{tag}:{name}", **reading} for name, reading in stages.items()]
        with open(out_file, "a") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")
        if not record.get("aborted"):
            return record
        if record["aborted"] == "pressure":
            time.sleep(60)
    raise Fatal(f"sample {v['name']} discarded three times; last reason: {record.get('aborted')}")


# ------------------------------------------------------------- aged sessions
def real_session_stats(days: int = 7, idle_minutes: int = 60) -> dict:
    """Byte size and message count only of the longest recent session idle for a while; content is counted, never kept."""
    root = REAL_AGENT / "sessions"
    cutoff = time.time() - days * 86400
    idle_before = time.time() - idle_minutes * 60
    best = {"bytes": 0, "messages": 0}
    for p in root.rglob("*.jsonl"):
        try:
            st = p.stat()
        except OSError:
            continue
        if st.st_mtime < cutoff or st.st_mtime > idle_before or st.st_size <= best["bytes"]:
            continue
        n = 0
        with open(p, "rb") as f:
            while chunk := f.read(1 << 20):
                n += chunk.count(b'"type":"message"')
        best = {"bytes": st.st_size, "messages": n}
    return best


def aged_tag(size: str, stages: str) -> str:
    """Distinct tag per stage set so a reload-only run is never pooled with a turn+compact+reload run."""
    return f"aged-{size}" if stages == "turn,compact,reload" else f"aged-{size}[{stages.replace(',', '+')}]"


def size_plan(names: str) -> dict:
    """small/medium are fractions of the longest idle real session's size, same bytes-per-message; large matches it."""
    real = real_session_stats()
    if not real["bytes"]:
        raise Fatal("no idle real session found to size the aged condition from")
    per_msg = real["bytes"] / max(1, real["messages"])
    plan = {}
    for n in names.split(","):
        if n == "large":
            b = real["bytes"]
        elif n == "medium":
            b = real["bytes"] // 5
        elif n == "small":
            b = min(1_000_000, real["bytes"])
        elif re.fullmatch(r"\d+", n):
            b = int(n)
        else:
            raise ValueError(f"unknown size '{n}'")
        plan[n] = {"bytes": b, "messages": max(2, int(b / per_msg)) // 2 * 2, "real_reference": real}
    return plan


def count_marker(path: Path, needle: bytes) -> int:
    n = 0
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            n += chunk.count(needle)
    return n


def build_aged_session(path: Path, cwd: Path, total_bytes: int, messages: int, seed: int = 14) -> dict:
    """Synthetic, content-free conversation file with the requested size and message count."""
    rnd = random.Random(seed)
    words = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima"]
    per = max(80, total_bytes // max(1, messages) - 330)
    ts0 = 1_700_000_000_000
    lines = [json.dumps({"type": "session", "version": 3, "id": str(uuid.UUID(int=rnd.getrandbits(128))), "timestamp": "2026-01-01T00:00:00.000Z", "cwd": str(cwd)})]
    parent = None
    for i in range(messages):
        text = " ".join(rnd.choice(words) for _ in range(per // 6))[:per]
        mid = f"{i:08x}"
        if i % 2 == 0:
            msg = {"role": "user", "content": text, "timestamp": ts0 + i * 1000}
        else:
            msg = {"role": "assistant", "content": [{"type": "text", "text": text}], "api": "openai-completions", "provider": "dummy", "model": "dummy-1",
                   "usage": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "totalTokens": 0, "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}},
                   "stopReason": "stop", "timestamp": ts0 + i * 1000}
        lines.append(json.dumps({"type": "message", "id": mid, "parentId": parent, "timestamp": "2026-01-01T00:00:00.000Z", "message": msg}))
        parent = mid
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return {"bytes": path.stat().st_size, "messages": messages}


# ------------------------------------------------------------------- reporting
def summarize(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {"n": len(values), "median": statistics.median(values), "min": min(values), "max": max(values),
            "stdev": statistics.stdev(values) if len(values) > 1 else 0.0}


def load_samples(indir: Path) -> list[dict]:
    rows = []
    for f in sorted(indir.rglob("samples.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if not r.get("aborted") and r.get("rss_pi_kb"):
                    rows.append(r)
    return rows


def mb(kb):
    return None if kb is None else round(kb / 1024, 1)


def fmt(s: dict, scale=1024) -> str:
    if not s.get("n"):
        return "-"
    flag = "" if s["n"] >= 3 else " <3: indicative only"
    return f"{s['median']/scale:.0f} ({s['min']/scale:.0f}-{s['max']/scale:.0f}, n={s['n']}{flag})"


def is_part(variant: str) -> bool:
    """A single removable part (one package, one MCP server, or the local extensions as one part); groups overlap and are aggregates."""
    return variant.startswith("full-pkg:") or variant == "full-ext:*" or (variant.startswith("full-mcp:") and "+" not in variant)


def remainder(mm: dict, spreads: dict, metric: str) -> dict | None:
    """(full - core) minus the effects of single parts that exceed the noise floor of the full configuration."""
    full, core = mm.get(("full", "fresh")), mm.get(("core", "fresh"))
    if not full or not core or not full.get(metric) or not core.get(metric):
        return None
    noise = max(spreads.get(metric, 0) / 2, 15 * 1024)
    effects = {v: full[metric] - m[metric] for (v, tag), m in mm.items() if tag == "fresh" and is_part(v) and m.get(metric)}
    supported = {v: e for v, e in effects.items() if e > noise}
    total = full[metric] - core[metric]
    return {"metric": metric, "noise_mb": noise / 1024, "total_mb": total / 1024, "supported": {v: e / 1024 for v, e in supported.items()},
            "sum_mb": sum(supported.values()) / 1024, "unexplained_mb": (total - sum(supported.values())) / 1024}


def report(indir: Path) -> str:
    rows = load_samples(indir)
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["variant"], r.get("tag", "fresh")), []).append(r)
    all_rows = []
    for f in sorted(indir.rglob("samples.jsonl")):
        all_rows += [json.loads(x) for x in f.read_text().splitlines() if x.strip()]
    rejected = collections.Counter(re.sub(r"^(rejected|smoke).*", r"\1", r.get("aborted", "")) for r in all_rows if r.get("aborted"))
    out = ["# Pi idle memory report", "", "Median (min-max, n) in MB. RSS = resident set; footprint includes compressed pages. 'owned' = Pi plus every process it started (MCP servers, recap workers).", "",
           "| variant | tag | RSS Pi | RSS owned | footprint Pi | footprint owned |", "|---|---|---|---|---|---|"]
    med = {}
    for (var, tag), rs in sorted(groups.items()):
        cols = [summarize([r[k] for r in rs if r.get(k) is not None]) for k in ("rss_pi_kb", "rss_owned_kb", "fp_pi_kb", "fp_owned_kb")]
        med[(var, tag)] = cols[0].get("median")
        out.append(f"| {var} | {tag} | " + " | ".join(fmt(c) for c in cols) + " |")
    effects = {}
    for r in all_rows:
        if r.get("variant_effects") and not r.get("aborted"):
            effects.setdefault(r["variant"], set()).update(r["variant_effects"])
    if effects:
        out += ["", "Variant effects (commands that stopped registering because their owner depended on the removed part): " + "; ".join(f"{v}: {', '.join(sorted(c))}" for v, c in sorted(effects.items())) + "."]
    if rejected:
        out += ["", "Discarded sample attempts (retried): " + ", ".join(f"{k} x{n}" for k, n in sorted(rejected.items())) + "."]
    metrics = {"rss_pi_kb": "RSS Pi", "fp_pi_kb": "footprint Pi", "rss_owned_kb": "RSS owned", "fp_owned_kb": "footprint owned"}
    mm = {(var, tag): {k: summarize([r[k] for r in rs if r.get(k) is not None]).get("median") for k in metrics} for (var, tag), rs in groups.items()}
    low = [(r["variant"], round(r["rss_pi_kb"] / 1024), round(r["fp_pi_kb"] / 1024)) for r in rows if r.get("rss_pi_kb") and r.get("fp_pi_kb") and r["rss_pi_kb"] < 0.75 * r["fp_pi_kb"]]
    full, core = mm.get(("full", "fresh")), mm.get(("core", "fresh"))
    if full and core:
        out += ["", "Core-only vs full (median MB): " + "; ".join(f"{label} {core[k]/1024:.0f} -> {full[k]/1024:.0f}" for k, label in metrics.items() if core.get(k) and full.get(k)) + "."]
        if low:
            out += ["", f"{len(low)} sample(s) had RSS far below footprint (macOS compressed the process's pages while it ran), so RSS is unreliable under memory pressure; footprint (which includes compressed pages) is the attribution metric: " + ", ".join(f"{v} rss {a} vs fp {b}" for v, a, b in low) + "."]
        rows_t = []
        for (v, tag), m in mm.items():
            if tag == "fresh" and v not in ("core", "full"):
                rows_t.append((v, {k: (full[k] - m[k]) / 1024 for k in metrics if full.get(k) and m.get(k)}))
        if rows_t:
            rows_t.sort(key=lambda x: -x[1].get("fp_pi_kb", 0))
            out += ["", "## Attribution (full median minus variant median = MB saved by removing the part; positive = the part costs memory)", "",
                    "| removed | footprint Pi | RSS Pi | footprint owned | RSS owned |", "|---|---|---|---|---|"]
            out += [f"| {v} | " + " | ".join(f"{d.get(k, 0):.0f}" for k in ("fp_pi_kb", "rss_pi_kb", "fp_owned_kb", "rss_owned_kb")) + " |" for v, d in rows_t]
            fr = [r for r in groups.get(("full", "fresh"), [])]
            spreads = {k: (max(r[k] for r in fr if r.get(k)) - min(r[k] for r in fr if r.get(k))) if fr else 0 for k in metrics}
            out += ["", "## Unexplained remainder", "", "Noise floor = half the min-max spread of the full configuration's own samples (at least 15 MB). A part is 'supported' when removing it saves more than the noise floor; groups and the no-MCP variant are aggregates and are not summed.", "",
                    "| metric | full - core | noise floor | supported parts (MB) | sum | unexplained |", "|---|---|---|---|---|---|"]
            for k in ("fp_pi_kb", "rss_pi_kb", "fp_owned_kb", "rss_owned_kb"):
                rm = remainder(mm, spreads, k)
                if rm:
                    parts = ", ".join(f"{v.split(':', 1)[1]} {e:.0f}" for v, e in sorted(rm["supported"].items(), key=lambda x: -x[1])) or "none"
                    out.append(f"| {metrics[k]} | {rm['total_mb']:.0f} | {rm['noise_mb']:.0f} | {parts} | {rm['sum_mb']:.0f} | {rm['unexplained_mb']:.0f} |")
            n_fp = [d["fp_pi_kb"] for _, d in rows_t if "fp_pi_kb" in d]
            out += ["", f"Pi-process footprint effect of single parts ranges {min(n_fp):.0f} to {max(n_fp):.0f} MB; a part whose effect is within the noise floor is not separable from noise. Parts need not add up (interactions, shared dependencies)."]
    return "\n".join(out) + "\n"


SECRET_PATTERNS = [r"sk-[A-Za-z0-9_-]{20,}", r"gh[pousr]_[A-Za-z0-9]{20,}", r"xox[baprs]-[A-Za-z0-9-]{10,}", r"AKIA[0-9A-Z]{16}",
                   r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}\.", r"(?i)bearer\s+[A-Za-z0-9._-]{20,}",
                   r"(?i)api[_-]?key\s*[:=]\s*['\"]?[A-Za-z0-9_-]{16,}", r"\.pi/agent/sessions/", r"\.jsonl\b"]


def scan_post(text: str) -> list[str]:
    return [p for p in SECRET_PATTERNS if re.search(p, text)]


# -------------------------------------------------------------------------- CLI
def attribution_variants() -> list[str]:
    settings = json.loads((REAL_AGENT / "settings.json").read_text())
    names = ["full-nomcp"]  # core and full come from the baseline run
    for e in settings.get("packages", []):
        src = e if isinstance(e, str) else e.get("source", "")
        names.append(f"full-pkg:{package_key(src)}")
    mcp = json.loads((REAL_AGENT / "mcp.json").read_text()).get("mcpServers", {}) if (REAL_AGENT / "mcp.json").exists() else {}
    names += [f"full-mcp:{n}" for n in mcp]
    exts = sorted(p.name for p in (REAL_AGENT / "extensions").iterdir())
    names += ["full-ext:*"] + [f"full-ext:{'+'.join(exts[: len(exts)//2])}", f"full-ext:{'+'.join(exts[len(exts)//2:])}"]
    return names


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pi_idle_rss")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("preflight"); p.add_argument("--variant", default="full"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("measure"); p.add_argument("--variants", required=True); p.add_argument("--samples", type=int, default=3)
    p.add_argument("--settle-seconds", type=int, default=60); p.add_argument("--out", required=True); p.add_argument("--also-aged", action="store_true")
    p.add_argument("--warmup", action="store_true", help="discard one full-config launch first (cold caches after the store clone)")
    p.add_argument("--no-smoke", action="store_true", help="skip the command-registration smoke check (diagnostics only)")
    p = sub.add_parser("aged"); p.add_argument("--variant", default="full"); p.add_argument("--sizes", default="small,large")
    p.add_argument("--samples", type=int, default=3); p.add_argument("--settle-seconds", type=int, default=60); p.add_argument("--out", required=True)
    p.add_argument("--stages", default="turn,compact,reload", help="ordered subset of turn,compact,reload")
    p = sub.add_parser("report"); p.add_argument("--in", dest="indir", required=True); p.add_argument("--out")
    p = sub.add_parser("scan-post"); p.add_argument("file")
    sub.add_parser("real-stats")
    a = ap.parse_args(argv)

    if a.cmd == "report":
        text = report(Path(a.indir))
        if a.out:
            Path(a.out).write_text(text)
        print(text)
        return 0
    if a.cmd == "scan-post":
        hits = scan_post(Path(a.file).read_text())
        print(json.dumps({"ok": not hits, "matched_pattern_count": len(hits)}))
        return 0 if not hits else 1
    if a.cmd == "real-stats":
        print(json.dumps(real_session_stats()))
        return 0

    pi_bin, node_dir = release_paths()
    base = Path(tempfile.mkdtemp(prefix="pi-idle-rss-"))
    os.chmod(base, 0o700)
    log = lambda m: print(m, file=sys.stderr, flush=True)
    backend = None
    try:
        store = Store(base / "store")
        if a.cmd == "preflight":
            res = preflight(parse_variant(a.variant), base / "pf", store, node_dir, base / "pf-work")
            print(json.dumps(res if a.json else {"ok": res["ok"], "checks": [(c["name"], c["ok"]) for c in res["checks"]]}, indent=1))
            return 0 if res["ok"] else 1
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        backend = Backend()
        specs = attribution_variants() if a.cmd == "measure" and a.variants == "attribution" else (a.variants.split(",") if a.cmd == "measure" else [a.variant])
        if a.cmd == "measure" and a.warmup:
            log("[warmup] discarded full-config launch")
            run_sample(parse_variant("full"), base / "run", store, backend, node_dir, a.settle_seconds, out / "warmup.jsonl", tag="warmup", log=log)
        for spec in specs:
            v = parse_variant(spec)
            pf = preflight(v, base / "pf", store, node_dir, base / "pf-work")
            shutil.rmtree(base / "pf", ignore_errors=True)
            if not pf["ok"]:
                raise Fatal(f"isolation check failed for {spec}: {[c['name'] for c in pf['checks'] if not c['ok']]}")
            if a.cmd == "measure":
                for i in range(a.samples):
                    log(f"[measure] {spec} sample {i+1}/{a.samples}")
                    run_sample(v, base / "run", store, backend, node_dir, a.settle_seconds, out / "samples.jsonl", log=log, smoke=(i == 0 and not a.no_smoke))
            else:
                plan = size_plan(a.sizes)
                for size, info in plan.items():
                    log(f"[aged] {spec} size={size} bytes={info['bytes']} messages={info['messages']}")
                    (out / f"plan-{size}.json").write_text(json.dumps(info))

                    def make(path, cwd, info=info):
                        build_aged_session(path, cwd, info["bytes"], info["messages"])
                        return path

                    for i in range(a.samples):
                        log(f"[aged] {spec} {size} sample {i+1}/{a.samples}")
                        run_sample(v, base / "run", store, backend, node_dir, a.settle_seconds, out / "samples.jsonl",
                                   tag=aged_tag(size, a.stages), session_file=make, driver=functools.partial(aged_driver, order=tuple(a.stages.split(","))), log=log)
        return 0
    except Fatal as e:
        print(f"FATAL: {e}", file=sys.stderr)
        return 2
    finally:
        if backend:
            backend.shutdown()
        shutil.rmtree(base, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
