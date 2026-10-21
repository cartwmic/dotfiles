#!/usr/bin/env python3
"""Herdr control MCP bridge (stdio): five reads, herdr_request, herdr_cli.

Python 3.9 stdlib only (runs under /usr/bin/python3 -I -B). herdr_request forwards
one native JSON request over the local Herdr socket; herdr_cli runs one finite
argv of the pinned Herdr executable with shell=False. Never retries; uncertain
writes remain unknown. herdr_cli reads its executable path and SHA-256 pin from
~/.config/herdr-mcp/config (written by `herdr-mcp-tunnel configure`). Every tool
call writes metadata-only start/end records to ~/.local/state/herdr-mcp/audit.log.
"""
import fcntl, hashlib, hmac, json, os, re, secrets, selectors, socket, stat, subprocess, sys, time, uuid

CONFIG_PATH = os.path.expanduser('~/.config/herdr-mcp/config')
CLI_CWD = os.path.expanduser('~')
AUDIT_PATH = os.path.expanduser('~/.local/state/herdr-mcp/audit.log')
AUDIT_MAX_BYTES = 1048576  # rotate before a write would pass this size
AUDIT_KEEP = 5             # audit.log.1 .. audit.log.5; older records are dropped
HASH_KEY_PATH = os.path.join(os.path.dirname(AUDIT_PATH), 'text-hash.key')  # 32 random bytes, mode 0600
# Herdr ids look like w1, w1:t2, w15:p2R. Bounded so free text such as "w1Hunter2" is not logged.
TARGET_ID = re.compile(r'^w[0-9]{1,6}[A-Za-z0-9]{0,2}(:[tp][0-9]{1,6}[A-Za-z0-9]{0,2})?$')
CODE = re.compile(r'^[a-z][a-z0-9_]{0,47}$')
# The 103 request methods of the Herdr 0.9.1 protocol 22 schema: schemas.request.oneOf[*].properties.method.const.
# tests/fixtures/herdr-0.9.1-request-methods.json holds that extraction; test_bridge checks exact equality.
# Anything else is audited as 'unlisted' so a mistyped or abused method string never lands in the log.
KNOWN_METHODS = frozenset({
    'agent.explain', 'agent.focus', 'agent.get', 'agent.list', 'agent.prompt', 'agent.read',
    'agent.rename', 'agent.send_keys', 'agent.start', 'agent.view.clear', 'agent.view.set',
    'agent.wait', 'client.window_title.clear', 'client.window_title.set',
    'client_shell.surface.set', 'command.invoke', 'events.subscribe', 'events.wait',
    'integration.install', 'integration.list', 'integration.uninstall', 'layout.apply',
    'layout.export', 'layout.set_split_ratio', 'notification.show', 'pane.clear_agent_authority',
    'pane.close', 'pane.copy_motion', 'pane.copy_search', 'pane.current', 'pane.edges',
    'pane.edit_scrollback', 'pane.focus', 'pane.focus_direction', 'pane.get',
    'pane.graphics.clear', 'pane.graphics.info', 'pane.graphics.set', 'pane.input.set',
    'pane.layout', 'pane.link.activate', 'pane.link.resolve', 'pane.list', 'pane.move',
    'pane.neighbor', 'pane.process_info', 'pane.read', 'pane.release_agent', 'pane.rename',
    'pane.report_agent', 'pane.report_agent_session', 'pane.report_metadata', 'pane.resize',
    'pane.scroll', 'pane.selection.read', 'pane.send_input', 'pane.send_keys', 'pane.send_text',
    'pane.split', 'pane.swap', 'pane.wait_for_output', 'pane.zoom', 'plugin.action.invoke',
    'plugin.action.list', 'plugin.disable', 'plugin.enable', 'plugin.link', 'plugin.list',
    'plugin.log.list', 'plugin.pane.close', 'plugin.pane.focus', 'plugin.pane.open',
    'plugin.unlink', 'popup.close', 'product_announcement.dismiss', 'release_notes.dismiss',
    'server.agent_manifests', 'server.live_handoff', 'server.reload_agent_manifests',
    'server.reload_config', 'server.stop', 'session.snapshot', 'tab.close', 'tab.create',
    'tab.focus', 'tab.get', 'tab.list', 'tab.move', 'tab.rename', 'workspace.close',
    'workspace.create', 'workspace.focus', 'workspace.get', 'workspace.list', 'workspace.move',
    'workspace.move_block', 'workspace.rename', 'workspace.report_metadata', 'worktree.create',
    'worktree.list', 'worktree.open', 'worktree.remove', 'ping',
})

CALL_ID = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
TARGET_KEYS = ('pane_id', 'tab_id', 'workspace_id', 'target', 'id')


def load_config(path=None):
    """Parse nonsecret key=value lines. Missing file means herdr_cli is unconfigured."""
    cfg = {}
    try:
        with open(path or CONFIG_PATH, encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    cfg[key.strip()] = value.strip()
    except FileNotFoundError:
        pass
    return cfg


CLI_ROOTS = {'--version', '-V', '--default-config', '--skill', 'status', 'server',
             'api', 'workspace', 'worktree', 'tab', 'notification', 'agent', 'pane',
             'session', 'machine', 'channel', 'config', 'integration', 'plugin',
             'completion', 'update'}
CLI_SCHEMA = {'type': 'object', 'additionalProperties': False,
              'properties': {'argv': {'type': 'array', 'items': {'type': 'string'}, 'minItems': 1},
                             'timeout_ms': {'type': 'integer', 'minimum': 100, 'maximum': 310000}},
              'required': ['argv']}


def native_cli(args):
    if not isinstance(args, dict) or set(args) - {'argv', 'timeout_ms'}:
        raise ValueError('Expected argv array and optional timeout_ms only')
    argv = args.get('argv')
    timeout = args.get('timeout_ms', 10000)
    if (not isinstance(argv, list) or not argv or len(argv) > 256 or
            any(not isinstance(a, str) or '\0' in a for a in argv) or
            sum(len(a.encode()) for a in argv) > 131072 or
            type(timeout) is not int or not 100 <= timeout <= 310000):
        raise ValueError('Invalid argv or timeout_ms; nothing launched')
    # No interactive transport or background server hosting through this finite tool.
    if not any(a in ('--help', '-h') for a in argv):
        if '--remote' in argv or any(a.startswith('--remote=') for a in argv) or 'attach' in argv:
            raise ValueError('Interactive attach is unsupported; nothing launched')
        words = list(argv)
        while words and (words[0] in ('--session', '--machine') or words[0].startswith(('--session=', '--machine='))):
            n = 1 if '=' in words[0] else 2
            words = words[n:]
        if not words or words == ['server']:
            raise ValueError('Interactive/default launch or persistent server requires separate supervision')
        if words[0] not in CLI_ROOTS:
            raise ValueError('Unsupported command root; interactive/default startup is not exposed')
    cfg = load_config()
    herdr_exe, herdr_sha = cfg.get('herdr_exe', ''), cfg.get('herdr_sha256', '')
    if not os.path.isabs(herdr_exe) or len(herdr_sha) != 64:
        raise ValueError('herdr_cli is not configured (run: herdr-mcp-tunnel configure); nothing launched')
    digest = hashlib.sha256()
    try:
        with open(herdr_exe, 'rb') as binary:
            for block in iter(lambda: binary.read(1048576), b''):
                digest.update(block)
    except OSError as exc:
        raise ValueError(f'Herdr executable unreadable ({exc.__class__.__name__}); nothing launched')
    if digest.hexdigest() != herdr_sha:
        raise ValueError('Herdr executable hash mismatch; nothing launched')
    env = {k: os.environ[k] for k in ('HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'LC_ALL',
                                     'HERDR_SOCKET_PATH', 'HERDR_CONFIG_PATH',
                                     'XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_RUNTIME_DIR') if k in os.environ}
    env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin', TERM='dumb', NO_COLOR='1')
    output = {'stdout': bytearray(), 'stderr': bytearray()}
    truncated = False
    expired = False
    child = subprocess.Popen([herdr_exe] + argv, cwd=CLI_CWD, env=env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             shell=False, start_new_session=True)
    deadline = time.monotonic() + timeout / 1000
    # Bound output without waiting on descendant-held pipes. Terminate only the original
    # CLI process on deadline; server/workload effects and descendants are never rolled back.
    try:
        with selectors.DefaultSelector() as selector:
            for label, pipe in (('stdout', child.stdout), ('stderr', child.stderr)):
                os.set_blocking(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, label)
            while selector.get_map():
                if time.monotonic() >= deadline:
                    expired = True
                    if child.poll() is None:
                        child.kill()
                    break
                for key, _ in selector.select(min(.1, max(0, deadline-time.monotonic()))):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    dest = output[key.data]
                    room = 1048576 - len(dest)
                    dest.extend(chunk[:room])
                    truncated = truncated or len(chunk) > room
            remaining = max(.001, deadline-time.monotonic())
            try:
                code = child.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                expired = True
                child.kill()
                code = child.wait()
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()
        child.stdout.close()
        child.stderr.close()
    data = {'outcome': 'unknown_after_timeout' if expired else 'process_exited',
            'pid': child.pid, 'exit_code': code, 'timed_out': expired,
            'stdout': output['stdout'].decode('utf-8', 'replace'),
            'stderr': output['stderr'].decode('utf-8', 'replace'), 'output_truncated': truncated,
            'retry': 'Never automatically retry mutations. Inspect actual server state; CLI exit is not workload completion.',
            'cleanup': 'Original CLI waited and pipes closed; descendant/server effects not rolled back or asserted absent.'}
    return {'isError': expired or code != 0,
            'content': [{'type': 'text', 'text': json.dumps(data)}]}

SOCK = os.environ.get("HERDR_SOCKET_PATH") or os.path.expanduser("~/.config/herdr/herdr.sock")
MAX_OUT = 50_000
LIST = {"workspace": "workspace.list", "tab": "tab.list", "pane": "pane.list", "agent": "agent.list"}
GET = {"workspace": ("workspace.get", "workspace_id"), "tab": ("tab.get", "tab_id"),
       "pane": ("pane.get", "pane_id"), "agent": ("agent.get", "target")}
SOURCES = ["visible", "recent", "recent_unwrapped", "detection"]  # Herdr 0.9.1 ReadSource
SOURCE_ALIASES = {"recent-unwrapped": "recent_unwrapped"}  # earlier advertised spelling


def rpc(method, params=None):
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(10)
    s.connect(SOCK)
    s.sendall((json.dumps({"id": "m", "method": method, "params": params or {}}) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        c = s.recv(65536)
        if not c:
            break
        buf += c
    s.close()
    r = json.loads(buf)
    if "error" in r:
        raise RuntimeError(f"{r['error'].get('code')}: {r['error'].get('message')}")
    return r["result"]


def redact(o):
    if isinstance(o, dict):
        return {k: ({kk: vv for kk, vv in v.items() if kk != "value"} if k == "agent_session" and isinstance(v, dict) else redact(v))
                for k, v in o.items()}
    if isinstance(o, list):
        return [redact(x) for x in o]
    return o


KIND = {"type": "string", "enum": list(LIST)}
TOOLS = {
    "herdr_status": ("Ping the Herdr server: version, protocol, capabilities.",
                     {"type": "object", "properties": {}},
                     lambda a: rpc("ping")),
    "herdr_snapshot": ("Full live session snapshot: workspaces, tabs, panes, agents.",
                       {"type": "object", "properties": {}},
                       lambda a: rpc("session.snapshot")),
    "herdr_list": ("List workspaces, tabs, panes, or agents (read-only).",
                   {"type": "object", "properties": {"kind": KIND}, "required": ["kind"]},
                   lambda a: rpc(LIST[a["kind"]])),
    "herdr_get": ("Get one workspace/tab/pane by id (w1, w1:t1, w1:p1) or an agent by name or pane id.",
                  {"type": "object", "properties": {"kind": KIND, "id": {"type": "string"}}, "required": ["kind", "id"]},
                  lambda a: rpc(GET[a["kind"]][0], {GET[a["kind"]][1]: a["id"]})),
    "herdr_read": ("Read recent terminal output of a pane (no input is sent). lines is capped at 200.",
                   {"type": "object", "properties": {"pane_id": {"type": "string"}, "source": {"type": "string", "enum": SOURCES},
                                                      "lines": {"type": "integer", "minimum": 1, "maximum": 200}},
                    "required": ["pane_id"]},
                   lambda a: rpc("pane.read", {"pane_id": a["pane_id"], "source": SOURCE_ALIASES.get(a.get("source", "recent"), a.get("source", "recent")),
                                               "lines": min(int(a.get("lines", 50)), 200)})),
}


def call_tool(name, args):
    if name not in TOOLS:
        raise ValueError(f"unknown tool {name}")
    out = json.dumps(redact(TOOLS[name][2](args or {})), indent=1)
    return out if len(out) <= MAX_OUT else out[:MAX_OUT] + "\n...[truncated]"


REQUEST_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"method": {"type": "string", "minLength": 1},
                   "params": {"type": "object"},
                   "timeout_ms": {"type": "integer", "minimum": 100, "maximum": 310000}},
    "required": ["method", "params"]}


def generic_request(args):
    """One request, one response, never replay. Request IDs are correlation, not deduplication."""
    if (not isinstance(args, dict) or set(args) - {"method", "params", "timeout_ms"}
            or not isinstance(args.get("method"), str) or not args["method"]
            or not isinstance(args.get("params"), dict)):
        raise ValueError("Expected method:string, params:object, optional timeout_ms; no other fields")
    timeout = args.get("timeout_ms", 10000)
    if type(timeout) is not int or not 100 <= timeout <= 310000:
        raise ValueError("timeout_ms must be an integer from 100 to 310000")
    rid = str(uuid.uuid4())
    wire = (json.dumps({"id": rid, "method": args["method"], "params": args["params"]},
                       allow_nan=False) + "\n").encode()
    if len(wire) > 1048576:
        raise ValueError("Request exceeds 1 MiB; nothing sent")
    attempted = False
    deadline = time.monotonic() + timeout / 1000
    try:
        with socket.socket(socket.AF_UNIX) as conn:
            conn.settimeout(max(.001, deadline - time.monotonic()))
            conn.connect(SOCK)
            attempted = True  # A failed sendall may have partially delivered the request.
            conn.sendall(wire)
            buf = bytearray()
            while b"\n" not in buf:
                conn.settimeout(max(.001, deadline - time.monotonic()))
                if time.monotonic() >= deadline:
                    raise TimeoutError("response deadline exceeded")
                chunk = conn.recv(65536)
                if not chunk:
                    raise ConnectionError("EOF before complete response")
                buf.extend(chunk)
                if len(buf) > 8388608:
                    raise ValueError("response exceeds 8 MiB")
            response = json.loads(bytes(buf).split(b"\n", 1)[0])
            # Herdr 0.9.1 parser failures use an empty id before request decoding.
            if (not isinstance(response, dict) or not (response.get("id") == rid or
                    (response.get("id") == "" and isinstance(response.get("error"), dict)
                     and response["error"].get("code") == "invalid_request"))
                    or ("result" in response) == ("error" in response)):
                raise ValueError("unmatched or invalid response envelope")
        # Keep native error code/message/data intact. Existing private session-path redaction
        # applies only to successful results, not to server error objects.
        if "result" in response:
            response["result"] = redact(response["result"])
        payload = {"outcome": "server_response", "response": response,
                   "retry": "Never automatically replay a mutation; inspect state first."}
        return {"isError": "error" in response,
                "content": [{"type": "text", "text": json.dumps(payload)}]}
    except (OSError, ValueError) as exc:
        payload = {"outcome": "unknown" if attempted else "not_sent", "request_id": rid,
                   "transport_error": {"type": type(exc).__name__, "message": str(exc)},
                   "retry": "No automatic retry. Inspect state before any new mutating request."}
        return {"isError": True, "content": [{"type": "text", "text": json.dumps(payload)}]}


def audit_write(record):
    """Append one metadata-only JSON line. Fail open: a logging failure never blocks a call."""
    try:
        line = (json.dumps(record, separators=(',', ':')) + '\n').encode()
        os.makedirs(os.path.dirname(AUDIT_PATH), mode=0o700, exist_ok=True)
        # tunnel-client may run several bridge processes; one lock serializes rotate + append.
        lock = os.open(AUDIT_PATH + '.lock', os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if os.path.getsize(AUDIT_PATH) + len(line) > AUDIT_MAX_BYTES:
                    for n in range(AUDIT_KEEP - 1, 0, -1):
                        if os.path.exists(f'{AUDIT_PATH}.{n}'):
                            os.replace(f'{AUDIT_PATH}.{n}', f'{AUDIT_PATH}.{n + 1}')
                    os.replace(AUDIT_PATH, AUDIT_PATH + '.1')
            except FileNotFoundError:
                pass
            fd = os.open(AUDIT_PATH, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                os.write(fd, line)
            finally:
                os.close(fd)
        finally:
            os.close(lock)  # releases the flock
    except Exception as exc:  # disk full, permissions, symlink refusal
        try:
            print(f'herdr-control: audit log write failed ({type(exc).__name__})', file=sys.stderr, flush=True)
        except Exception:
            pass  # stderr closed: the call still proceeds unaudited


def audit_targets(name, args):
    """Only values shaped like Herdr ids (w1, w1:t2, w15:p2R); never free text."""
    if name == 'herdr_cli':
        # Only the first positional word after the command is a target slot. Message text,
        # option values and --session/--machine values are never scanned: they can be ID-shaped.
        _root, _sub, rest = cli_command(args.get('argv') if isinstance(args.get('argv'), list) else [])
        values = cli_positionals(rest)[:1]
    else:
        params = args.get('params') if name == 'herdr_request' else args
        params = params if isinstance(params, dict) else {}
        values = [params.get(k) for k in TARGET_KEYS]
    found = []
    for v in values:
        if isinstance(v, str) and TARGET_ID.match(v) and v not in found:
            found.append(v)
    return found[:8]


# Subcommand words per CLI root (herdr 0.9.1 --help). Only a word found here is ever logged,
# so free text in later argv positions can never reach the log.
CLI_SUBS = {
    'pane': {'list', 'current', 'get', 'layout', 'process-info', 'neighbor', 'edges', 'focus', 'resize', 'zoom',
             'read', 'rename', 'input', 'split', 'swap', 'move', 'close', 'send-text', 'send-keys', 'wait-output',
             'run', 'report-agent', 'report-agent-session', 'release-agent', 'report-metadata'},
    'agent': {'list', 'get', 'read', 'send-keys', 'prompt', 'rename', 'focus', 'wait', 'attach', 'start', 'explain'},
    'tab': {'list', 'create', 'get', 'focus', 'rename', 'close'},
    'workspace': {'list', 'create', 'get', 'focus', 'rename', 'report-metadata', 'close'},
    'worktree': {'list', 'create', 'open', 'remove'},
    'notification': {'show'}, 'session': {'list', 'attach', 'stop', 'delete'},
    'machine': {'list', 'add', 'rename', 'remove', 'enable', 'disable'},
    'channel': {'show', 'set'}, 'config': {'check', 'reset-keys'},
    'integration': {'install', 'uninstall', 'status'},
    'plugin': {'install', 'uninstall', 'link', 'unlink', 'enable', 'disable', 'list', 'config-dir', 'action', 'log', 'pane'},
    'api': {'snapshot', 'schema'}, 'server': {'stop', 'reload-config'},
}
# Native requests whose params.text is a message sent to a pane; the other send methods carry keys only.
SEND_TEXT_METHODS = frozenset({'agent.prompt', 'pane.send_text', 'pane.send_input'})
CLI_VALUE_OPTIONS = frozenset({'--until', '--timeout'})  # options of 'agent prompt' that take a value


def cli_command(argv):
    """(root, sub, rest) of a herdr argv, after the global --session/--machine options.
    root is None unless it is a known command root; sub is None unless it is in CLI_SUBS[root]."""
    words = [a for a in argv if isinstance(a, str)]
    while words and (words[0] in ('--session', '--machine') or words[0].startswith(('--session=', '--machine='))):
        words = words[1 if '=' in words[0] else 2:]
    if not words or words[0].startswith('-') or words[0] not in CLI_ROOTS:
        return None, None, []
    sub = words[1] if len(words) > 1 and words[1] in CLI_SUBS.get(words[0], ()) else None
    return words[0], sub, words[2 if sub else 1:]


def cli_positionals(rest):
    out, i, literal = [], 0, False
    while i < len(rest):
        a = rest[i]
        if literal or not a.startswith('-'):
            out.append(a)
        elif a == '--':
            literal = True
        elif a in CLI_VALUE_OPTIONS:
            i += 1
        i += 1
    return out


def normalize_text(text):
    """Both the bridge and the report hash this form: LF newlines, no leading/trailing whitespace."""
    return text.replace('\r\n', '\n').replace('\r', '\n').strip()


def load_hash_key(create=False):
    """The per-install HMAC key (32 bytes), or None. Created atomically by the bridge only
    (create=True); the report never creates it. Never raises."""
    try:
        fd = os.open(HASH_KEY_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)  # NONBLOCK: a FIFO must not hang a call
    except FileNotFoundError:
        fd = None
    except OSError:
        return None
    if fd is None:
        if not create:
            return None
        try:
            os.makedirs(os.path.dirname(HASH_KEY_PATH), mode=0o700, exist_ok=True)
            tmp = f'{HASH_KEY_PATH}.{os.getpid()}.{secrets.token_hex(4)}'
            tfd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                os.write(tfd, secrets.token_bytes(32))
            finally:
                os.close(tfd)
            try:
                os.link(tmp, HASH_KEY_PATH)  # atomic; loses cleanly to a concurrent bridge process
            except FileExistsError:
                pass
            finally:
                os.unlink(tmp)
            fd = os.open(HASH_KEY_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077 or st.st_uid != os.geteuid():
            return None  # only our own private regular file is a key; never modified here
        key = os.read(fd, 64)
    except OSError:
        return None
    finally:
        os.close(fd)
    return key if len(key) == 32 else None


def hash_text(text, key):
    """'h1:' + first 128 bits of HMAC-SHA256(key, normalized text). Keyed so a leaked log
    cannot confirm a guessed short message such as 'yes'."""
    mac = hmac.new(key, normalize_text(text).encode('utf-8', 'replace'), hashlib.sha256)
    return 'h1:' + mac.hexdigest()[:32]


def audit_send(name, args):
    """Extra metadata for a text send: CLI subcommand, and text_hash + text_len (never the text).
    Empty dict for anything else. Never raises."""
    try:
        extra, text = {}, None
        if name == 'herdr_cli':
            root, sub, rest = cli_command(args.get('argv') if isinstance(args.get('argv'), list) else [])
            if sub:
                extra['sub'] = sub
            pos = cli_positionals(rest)
            if (root, sub) in (('agent', 'prompt'), ('pane', 'send-text')) and len(pos) >= 2:
                text = pos[1]
            elif (root, sub) == ('pane', 'run') and len(pos) >= 2:
                text = ' '.join(pos[1:])
        elif name == 'herdr_request':
            params = args.get('params') if isinstance(args.get('params'), dict) else {}
            if args.get('method') in SEND_TEXT_METHODS and isinstance(params.get('text'), str):
                text = params['text']
        if text is not None and normalize_text(text):
            key = load_hash_key(create=True)
            if key:
                extra['text_hash'] = hash_text(text, key)
                extra['text_len'] = len(normalize_text(text))
        return extra
    except Exception:
        return {}


def audit_method(name, args):
    """Native method name, or CLI root plus subcommand word. No arguments."""
    if name == 'herdr_request':
        m = args.get('method')
        return m if isinstance(m, str) and m in KNOWN_METHODS else 'unlisted'
    if name == 'herdr_cli':
        # Root command only (the subcommand goes in 'sub'): later argv words can be free text.
        root = cli_command(args.get('argv') if isinstance(args.get('argv'), list) else [])[0]
        return 'cli:' + root if root else 'cli:other'
    if name == 'herdr_list':
        return LIST.get(args.get('kind'), 'invalid') if isinstance(args.get('kind'), str) else 'invalid'
    if name == 'herdr_get':
        return GET[args['kind']][0] if isinstance(args.get('kind'), str) and args['kind'] in GET else 'invalid'
    return {'herdr_status': 'ping', 'herdr_snapshot': 'session.snapshot', 'herdr_read': 'pane.read'}.get(name, 'none')


def audit_outcome(name, result):
    """ok / error / unknown / not_sent plus safe codes only (never messages or payloads)."""
    if name not in ('herdr_request', 'herdr_cli'):
        return ('error' if result.get('isError') else 'ok'), {}
    try:
        data = json.loads(result['content'][0]['text'])
    except (ValueError, KeyError, IndexError, TypeError):
        return 'error', {}
    if name == 'herdr_cli':
        if data.get('timed_out'):
            return 'unknown', {}
        code = data.get('exit_code')
        return ('ok' if code == 0 else 'error'), {'exit_code': code if isinstance(code, int) else None}
    if data.get('outcome') == 'server_response':
        err = data['response'].get('error')
        if isinstance(err, dict):
            code = err.get('code')
            return 'error', {'error_code': code if isinstance(code, str) and CODE.match(code) else 'other'}
        return 'ok', {}
    transport = data.get('transport_error', {}).get('type')
    extra = {'request_id': data.get('request_id'),
             'transport_error': transport if isinstance(transport, str) and transport.isidentifier() and len(transport) <= 48 else 'other'}
    return ('not_sent' if data.get('outcome') == 'not_sent' else 'unknown'), extra


def dispatch(name, args):
    if name == "herdr_cli":
        return native_cli(args)
    if name == "herdr_request":
        return generic_request(args)
    return {"content": [{"type": "text", "text": call_tool(name, args)}]}


def audited_call(name, args, call_id):
    """Run one tool call between 'start' and 'end' metadata records sharing one call id.
    A start without an end means the bridge died mid-call: treat any effect as unknown."""
    safe_args = args if isinstance(args, dict) else {}
    tool = name if name in TOOLS or name in ("herdr_request", "herdr_cli") else "unknown_tool"
    base = {"call": str(uuid.uuid4()), "tool": tool, "method": audit_method(tool, safe_args),
            "targets": audit_targets(tool, safe_args), **audit_send(tool, safe_args)}
    if (isinstance(call_id, int) and not isinstance(call_id, bool)) or (isinstance(call_id, str) and CALL_ID.match(call_id)):
        base["mcp_id"] = call_id
    audit_write({"ts": audit_now(), "event": "start", **base})
    started = time.monotonic()
    try:
        result = dispatch(name, args)
        outcome, extra = audit_outcome(tool, result)
    except ValueError as e:  # validation: nothing sent or launched
        result = {"isError": True, "content": [{"type": "text", "text": f"error: {e}"}]}
        outcome, extra = "rejected", {}
    except Exception as e:
        result = {"isError": True, "content": [{"type": "text", "text": f"error: {e}"}]}
        code = str(e).split(":", 1)[0] if isinstance(e, RuntimeError) else type(e).__name__
        outcome, extra = "error", {"error_code": code if CODE.match(code) or (code.isidentifier() and len(code) <= 48) else "other"}
    audit_write({"ts": audit_now(), "event": "end", **base, "outcome": outcome,
                 "duration_ms": round((time.monotonic() - started) * 1000), **extra})
    return result


def audit_now():
    now = time.time()
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(now)) + '.%03dZ' % (int(now * 1000) % 1000)


def handle(m):
    meth, mid = m.get("method"), m.get("id")
    if meth == "initialize":
        return {"protocolVersion": m["params"].get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                "serverInfo": {"name": "herdr-control", "version": "0.2.0"}}
    if meth == "ping":
        return {}
    if meth == "tools/list":
        return {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s, _) in TOOLS.items()] + [{
            "name": "herdr_request", "inputSchema": REQUEST_SCHEMA,
            "description": "Forward one structured native Herdr socket request. Full control, including terminal commands, close, server stop, integration and worktree changes. No shell interpolation by this bridge. Native errors preserved; timeout/EOF may follow effects. NEVER automatically retry mutations. Uses configured server only; subscriptions end when this single-response connection closes. Verify explicit target IDs before mutation.",
            "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}}, {
            "name": "herdr_cli", "inputSchema": CLI_SCHEMA,
            "description": "Run one finite native Herdr argv invocation with pinned executable, shell=false, fixed cwd, scrubbed environment and closed stdin. Full native Herdr authority; no interactive attach or persistent server launch. Timeout kills/waits only original CLI, effects remain UNKNOWN; NEVER automatically retry. Output capped at 1 MiB per stream.",
            "annotations": {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False, "openWorldHint": True}}]}
    if meth == "tools/call":
        return audited_call(m["params"].get("name"), m["params"].get("arguments"), mid)
    if mid is None:
        return None  # notification
    raise KeyError(meth)


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        m = json.loads(line)
        try:
            res = handle(m)
            if m.get("id") is not None and res is not None:
                print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": res}), flush=True)
        except KeyError:
            print(json.dumps({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": "method not found"}}), flush=True)


if __name__ == "__main__":
    main()
