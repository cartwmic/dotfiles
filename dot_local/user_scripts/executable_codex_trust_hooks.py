#!/usr/bin/env python3
"""Trust the pattern-kill guard hook in Codex.

Codex runs a hook only after it is trusted: a hash of the hook's definition is kept under [hooks.state] in ~/.codex/config.toml, keyed by
the hook's position, and a hook that is new, changed or at another position is skipped silently (that is what Codex's own `/hooks` review
fixes by hand). This script does the same review for exactly one hook, ours, through Codex's own API (`codex app-server`): it asks Codex
for the hooks it sees, picks the one in hooks.json whose command is EQUAL to the guard command, and writes that hook's current key and hash
as trusted. Every other hook, trusted or not, is left alone, and nothing is written when ours is already trusted.

    codex_trust_hooks.py --command CMD            trust our hook when it is untrusted or modified; exit 1 and a loud line when it is missing
                                                  or still not trusted afterwards
    codex_trust_hooks.py --command CMD --check    only report; exit 1 when our hook is not trusted

CMD is the guard command (.chezmoitemplates/codex_guard_command), passed by run_after_90_codex_hook_trust.sh and also read from
$CODEX_GUARD_COMMAND. With no codex binary it prints one INFO line and exits 0 (--check: 1). The candidates, tried in this order: $CODEX_BIN,
`codex` on PATH, then the T3-bundled ~/.t3/tools/codex/<version>/bin/codex, newest first. The first one that starts and answers is used; one
that will not start (for example an npm `codex` whose native binary is gone) is skipped with an INFO line. $CODEX_HOME is passed through.
"""
import glob
import json
import os
import shutil
import subprocess
import sys
import threading

WATCHDOG_SECONDS = 60  # the whole run: an app-server that never answers must not hang an apply


def t3_bundled():
    """T3's bundled Codex binaries, newest version first: ~/.t3/tools/codex/<version>/bin/codex."""
    def version(path):
        name = path.split("/")[-3]
        return tuple(int(p) if p.isdigit() else 0 for p in name.replace("-", ".").split("."))

    return sorted(glob.glob(os.path.expanduser("~/.t3/tools/codex/*/bin/codex")), key=version, reverse=True)


def codex_candidates():
    """The Codex binaries to try, in order, without duplicates: $CODEX_BIN, `codex` on PATH, then T3's bundled ones. A candidate that will
    not start or answer (an npm `codex` whose native binary is gone, for example) is skipped for the next one."""
    names = [os.environ["CODEX_BIN"]] if os.environ.get("CODEX_BIN") else []
    names += [shutil.which("codex")] if shutil.which("codex") else []
    names += t3_bundled()
    return list(dict.fromkeys(names))


class Server:
    """A minimal client for `codex app-server` over stdio (newline-delimited JSON-RPC)."""

    def __init__(self, codex):
        self.proc = subprocess.Popen([codex, "app-server"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.n = 0
        self.watchdog = threading.Timer(WATCHDOG_SECONDS, self.proc.kill)
        self.watchdog.daemon = True
        self.watchdog.start()
        try:
            self.call("initialize", {"clientInfo": {"name": "codex_trust_hooks", "version": "1"}, "capabilities": {}})
            self.proc.stdin.write(json.dumps({"method": "initialized"}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            self.close()  # a failed handshake must not leave the child running
            raise

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


def our_hooks(server, command):
    """The hooks Codex lists that are ours: in a hooks.json, a PreToolUse handler whose command equals the guard command exactly."""
    result = server.call("hooks/list", {"cwds": [os.path.expanduser("~")]})
    return [h for entry in result.get("data", []) for h in entry.get("hooks", [])
            if h.get("command") == command and h.get("eventName") == "preToolUse" and str(h.get("sourcePath", "")).endswith("hooks.json")]


def connect(candidates, command):
    """The first candidate that starts and answers hooks/list, as (server, codex, our hooks). A candidate that cannot start or cannot answer
    is reported on one INFO line and skipped. Raises RuntimeError with every failure when none answers."""
    failures = []
    for codex in candidates:
        try:
            server = Server(codex)
        except Exception as error:
            failures.append("%s: %s" % (codex, error))
            print("[codex_trust_hooks] INFO: %s did not start (%s); trying the next codex" % (codex, error))
            continue
        try:
            return server, codex, our_hooks(server, command)
        except Exception as error:
            server.close()
            failures.append("%s: %s" % (codex, error))
            print("[codex_trust_hooks] INFO: %s started but did not answer (%s); trying the next codex" % (codex, error))
    raise RuntimeError("no codex binary answered (%s)" % "; ".join(failures))


def main(argv):
    check = "--check" in argv
    command = os.environ.get("CODEX_GUARD_COMMAND", "")
    if "--command" in argv and argv.index("--command") + 1 < len(argv):
        command = argv[argv.index("--command") + 1]
    if not command:
        print("[codex_trust_hooks] ERROR: no guard command (pass --command CMD or set CODEX_GUARD_COMMAND)")
        return 1
    candidates = codex_candidates()
    if not candidates:
        print("[codex_trust_hooks] INFO: no codex binary found; the Codex guard hook cannot be trusted here (rules/agent-guard.rules still applies)")
        return 1 if check else 0
    try:
        server, codex, hooks = connect(candidates, command)
    except RuntimeError as error:
        print("[codex_trust_hooks] WARN: %s" % error)
        return 1
    try:
        if not hooks:
            print("[codex_trust_hooks] WARN: Codex lists no guard hook in a hooks.json (is ~/.codex/hooks.json valid JSON with the guard group?)")
            return 1
        pending = [h for h in hooks if h.get("trustStatus") not in ("trusted", "managed")]
        if check:
            print("[codex_trust_hooks] %s: %s" % (codex, ", ".join("%s %s" % (h["key"], h.get("trustStatus")) for h in hooks)))
            return 1 if pending else 0
        for hook in pending:
            server.call("config/value/write", {"keyPath": "hooks.state", "mergeStrategy": "upsert",
                                                "value": {hook["key"]: {"trusted_hash": hook["currentHash"]}}})
        still = [h for h in our_hooks(server, command) if h.get("trustStatus") not in ("trusted", "managed")]
        if still:
            print("[codex_trust_hooks] WARN: the Codex guard hook is still %s after trusting it" % still[0].get("trustStatus"))
            return 1
        print("[codex_trust_hooks] Codex guard hook trusted: %d trusted now, %d already were (codex %s)" % (len(pending), len(hooks) - len(pending), codex))
        return 0
    except Exception as error:  # reported loudly; the caller decides whether it fails anything
        print("[codex_trust_hooks] WARN: %s" % error)
        return 1
    finally:
        server.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
