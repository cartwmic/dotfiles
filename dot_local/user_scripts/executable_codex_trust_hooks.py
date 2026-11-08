#!/usr/bin/env python3
"""Trust the pattern-kill guard hook in Codex.

Codex runs a hook only after it is trusted: a hash of the hook's definition is kept under [hooks.state] in ~/.codex/config.toml, and
a hook that is new or changed is skipped (that is what Codex's own `/hooks` review fixes by hand). This script does the same review for
exactly one hook, ours, through Codex's own app-server API: it asks Codex for the hooks it sees, finds the one whose command runs
refuse_pattern_kill.py, and writes that hook's current hash as trusted. Every other hook, trusted or not, is left alone.

    codex_trust_hooks.py            trust our hook when it is untrusted or modified
    codex_trust_hooks.py --check    only report; exit 1 when our hook is not trusted

Run by apply_harness_config.sh after the Codex config is written. It never fails an apply: no codex binary, or any error, prints one
warning line and exits 0 (use --check to see the truth). The binary: $CODEX_BIN, else `codex` on PATH, else the newest
~/.t3/tools/codex/<version>/bin/codex. $CODEX_HOME is passed through.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import threading

MARKER = "agent-harness/hooks/refuse_pattern_kill.py"
WATCHDOG_SECONDS = 60  # the whole run: an app-server that never answers must not hang an apply


def find_codex():
    if os.environ.get("CODEX_BIN"):
        return os.environ["CODEX_BIN"]
    found = shutil.which("codex")
    if found:
        return found
    candidates = glob.glob(os.path.expanduser("~/.t3/tools/codex/*/bin/codex"))

    def version(path):
        name = path.split("/")[-3]
        return tuple(int(p) if p.isdigit() else 0 for p in name.replace("-", ".").split("."))

    return max(candidates, key=version) if candidates else None


class Server:
    """A minimal client for `codex app-server` over stdio (newline-delimited JSON-RPC)."""

    def __init__(self, codex):
        self.proc = subprocess.Popen([codex, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.n = 0
        self.watchdog = threading.Timer(WATCHDOG_SECONDS, self.proc.kill)
        self.watchdog.daemon = True
        self.watchdog.start()
        self.call("initialize", {"clientInfo": {"name": "codex_trust_hooks", "version": "1"}, "capabilities": {}})
        self.proc.stdin.write(json.dumps({"method": "initialized"}) + "\n")
        self.proc.stdin.flush()

    def call(self, method, params):
        self.n += 1
        self.proc.stdin.write(json.dumps({"id": self.n, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("codex app-server closed before answering %s" % method)
            message = json.loads(line)
            if message.get("id") == self.n:
                if "error" in message:
                    raise RuntimeError("%s: %s" % (method, message["error"]))
                return message.get("result", {})

    def close(self):
        self.watchdog.cancel()
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def our_hooks(server):
    result = server.call("hooks/list", {"cwds": [os.path.expanduser("~")]})
    return [h for entry in result.get("data", []) for h in entry.get("hooks", []) if MARKER in (h.get("command") or "")]


def main(argv):
    check = "--check" in argv
    codex = find_codex()
    if not codex:
        print("[codex_trust_hooks] INFO: no codex binary found; the Codex hook stays untrusted (rules/agent-guard.rules still applies)")
        return 1 if check else 0
    server = None
    try:
        server = Server(codex)
        hooks = our_hooks(server)
        if not hooks:
            print("[codex_trust_hooks] WARN: Codex lists no refuse_pattern_kill hook (is the agent-guard block in ~/.codex/config.toml?)")
            return 1 if check else 0
        pending = [h for h in hooks if h.get("trustStatus") not in ("trusted", "managed")]
        if check:
            print("[codex_trust_hooks] %s: %s" % (codex, ", ".join("%s %s" % (h["key"], h.get("trustStatus")) for h in hooks)))
            return 1 if pending else 0
        for hook in pending:
            server.call("config/value/write", {"keyPath": "hooks.state", "mergeStrategy": "upsert",
                                                "value": {hook["key"]: {"trusted_hash": hook["currentHash"]}}})
        after = our_hooks(server)
        still = [h for h in after if h.get("trustStatus") not in ("trusted", "managed")]
        if still:
            print("[codex_trust_hooks] WARN: the Codex hook is still %s after trusting it" % still[0].get("trustStatus"))
        else:
            print("[codex_trust_hooks] Codex hook trusted: %d trusted now, %d already were" % (len(pending), len(hooks) - len(pending)))
        return 0
    except Exception as error:  # an apply must never fail on this
        print("[codex_trust_hooks] WARN: %s" % error)
        return 1 if check else 0
    finally:
        if server:
            server.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
