#!/usr/bin/env python3
"""herdr-mcp-tunnel tests: install with install.sh into a temp HOME, then drive the
CLI as the owner and launchd would.

FAKE keys only. The control plane is a closed loopback port (127.0.0.1:9): no
external network and no real credential. Keychain (/usr/bin/security) and
launchd (/bin/launchctl) are replaced by recorded fakes in the test copy, so no
real keychain item, keychain search list, or LaunchAgent is touched. tunnel-client is a
mock (FAKE_CLIENT); the real client is never executed. HERDR_MCP_TEST_ZIP (official
v0.0.16 darwin-arm64 zip) enables an extract-only pin test; without it that test
is skipped, not passed. Every process a test starts is killed
by process group and verified gone; a real tunnel on the machine is never touched.
Run: HERDR_MCP_TEST_ZIP=/path/tunnel-client-v0.0.16-darwin-arm64.zip \
     /usr/bin/python3 -B -m unittest discover -s herdr-mcp/tests -v
"""
import fcntl
import hashlib
import os
import pathlib
import plistlib
import re
import secrets
import select
import shutil
import signal
import subprocess
import tempfile
import termios
import threading
import time
import unittest
import zipfile

SRC = pathlib.Path(__file__).resolve().parents[1]
ZIP = os.environ.get('HERDR_MCP_TEST_ZIP', '')
FAKE = 'FAKE-TEST-KEY-' + 'x' * 26
FAKE_HERDR = '#!/bin/sh\n[ "$1" = "--version" ] && echo "herdr 0.9.1"\n'
DECOYS = {'OPENAI_API_KEY': 'FAKE-DECOY', 'CLOUDFLARED_MANAGED': 'true', 'MCP_SERVER_URL': 'http://evil.invalid/mcp',
          'HEALTH_LISTEN_ADDR': '0.0.0.0:1', 'HTTPS_PROXY': 'http://proxy.invalid:1', 'TUNNEL_CLIENT_CONFIG': '/nonexistent',
          'GITHUB_TOKEN': 'FAKE-DECOY', 'AWS_SECRET_ACCESS_KEY': 'FAKE-DECOY'}
TEST_KEYGUARD = '[[ $k == FAKE-TEST-KEY-* ]] || { k=""; die "TEST COPY accepts fake keys only"; }'
need_zip = unittest.skipUnless(ZIP and os.path.isfile(ZIP), 'HERDR_MCP_TEST_ZIP not set: official-archive pin test skipped')

FAKE_SECURITY = r'''#!/usr/bin/python3 -I
# TEST FAKE of /usr/bin/security: items are files under $HOME/fake-keychain. Logs argv only.
import os, sys, termios
home = os.environ['HOME']
store = os.path.join(home, 'fake-keychain')
os.makedirs(store, exist_ok=True)
with open(os.path.join(home, 'fake-security.argv'), 'a') as log:
    log.write(repr(sys.argv[1:]) + '\n')
args = sys.argv[1:]
if args == ['-i']:  # interactive mode: one command per stdin line (stdin is never logged)
    import shlex
    line = sys.stdin.readline()
    if os.path.exists(os.path.join(home, 'fake-security-echo')):
        sys.stderr.write(line)  # simulate a security that echoes the command
    args = shlex.split(line)
    if args and args[0] == 'add-generic-password' and '-w' in args[:-1]:
        def o(flag):
            return args[args.index(flag) + 1]
        value = o('-w')
        if os.path.exists(os.path.join(home, 'fake-security-truncate')):
            value = value[:128]  # simulate getpass-style truncation
        with open(os.path.join(store, f"{o('-s')}__{o('-a')}"), 'w') as f:
            f.write(value)
        sys.exit(0)
    sys.exit(2)
def opt(flag):
    return args[args.index(flag) + 1] if flag in args[:-1] else None
item = os.path.join(store, f"{opt('-s')}__{opt('-a')}")
cmd = args[0]
if cmd == 'add-generic-password':
    assert args[-1] == '-w', 'key must be prompted, not passed'
    with open('/dev/tty') as tin, open('/dev/tty', 'w') as tout:
        old = termios.tcgetattr(tin)
        new = termios.tcgetattr(tin); new[3] &= ~termios.ECHO
        termios.tcsetattr(tin, termios.TCSANOW, new)
        try:
            tout.write('password data for new item: '); tout.flush(); first = tin.readline().rstrip('\n')
            tout.write('\nretype password for new item: '); tout.flush(); second = tin.readline().rstrip('\n')
        finally:
            termios.tcsetattr(tin, termios.TCSANOW, old)
    if first != second:
        print('passwords do not match', file=sys.stderr); sys.exit(1)
    if os.path.exists(item) and '-U' not in args:
        sys.exit(45)
    with open(item, 'w') as f:
        f.write(first)
elif cmd == 'find-generic-password':
    if not os.path.exists(item):
        sys.exit(44)
    if '-w' in args:
        print(open(item).read())
    else:
        print('keychain: "fake"\nattributes: ...')
elif cmd == 'delete-generic-password':
    if not os.path.exists(item):
        sys.exit(44)
    os.remove(item)
else:
    sys.exit(2)
'''

FAKE_LAUNCHCTL = r'''#!/usr/bin/python3 -I
# TEST FAKE of /bin/launchctl: 'bootstrap' starts the plist ProgramArguments detached
# (as launchd would at load/login); 'bootout' TERMs and waits for it. Logs argv.
import os, plistlib, signal, subprocess, sys, time
home = os.environ['HOME']
state = os.path.join(home, 'fake-launchd')
os.makedirs(state, exist_ok=True)
with open(os.path.join(home, 'fake-launchctl.argv'), 'a') as log:
    log.write(repr(sys.argv[1:]) + '\n')
args = sys.argv[1:]
pidfile = os.path.join(state, 'pid')
def alive(pid):
    try:
        os.kill(pid, 0); return True
    except ProcessLookupError:
        return False
if args[0] == 'print':
    if not os.path.exists(pidfile):
        sys.exit(113)
    pid = int(open(pidfile).read())
    print('	state = ' + ('running' if alive(pid) else 'not running'))
    if alive(pid):
        print(f'	pid = {pid}')
    sys.exit(0)
if args[0] == 'bootstrap':
    if os.path.exists(pidfile):
        sys.exit(5)
    spec = plistlib.load(open(args[2], 'rb'))
    out = open(spec['StandardOutPath'], 'ab')
    env = {'HOME': home, 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'USER': os.environ.get('USER', 'u'),
           'LOGNAME': os.environ.get('USER', 'u'), 'SHELL': '/bin/zsh', 'TMPDIR': os.environ.get('TMPDIR', '/tmp')}
    proc = subprocess.Popen(spec['ProgramArguments'], stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                            env=env, start_new_session=True)
    open(pidfile, 'w').write(str(proc.pid))
    with open(os.path.join(state, 'history'), 'a') as h:  # every group ever started, for test cleanup
        h.write(f'{proc.pid}\n')
    sys.exit(0)
if args[0] == 'bootout':
    if not os.path.exists(pidfile):
        sys.exit(113)
    pid = int(open(pidfile).read())
    if alive(pid):
        os.kill(pid, signal.SIGTERM)
        for _ in range(200):
            if not alive(pid):
                break
            time.sleep(0.1)
    os.remove(pidfile)
    sys.exit(0 if not alive(pid) else 1)
sys.exit(2)
'''

FAKE_CLIENT = r'''#!/usr/bin/python3 -I
# TEST FAKE of tunnel-client: help text, loopback /readyz, spawns --mcp.command and
# performs initialize + tools/list over stdio. No network beyond 127.0.0.1.
import http.server, json, os, re, signal, socketserver, subprocess, sys, threading, time
args = sys.argv[1:]
if args[:2] == ['run', '--help']:
    for f in ('--control-plane.tunnel-id', '--mcp.command', '--health.listen-addr', '--health.url-file',
              '--cloudflared.managed', '--allow-remote-ui'):
        print(f'      {f} value   fake help')
    sys.exit(0)
if not args or args[0] != 'run':
    sys.exit(2)
opts, i = {}, 1
while i < len(args):
    a = args[i]
    if '=' in a:
        k, v = a.split('=', 1); opts[k] = v; i += 1
    else:
        opts[a] = args[i + 1] if i + 1 < len(args) and not args[i + 1].startswith('--') else 'true'; i += 2 if opts[a] != 'true' else 1
home = os.environ['HOME']
if not re.fullmatch(r'tunnel_[a-z0-9]{32}', opts.get('--control-plane.tunnel-id', '')):
    print('invalid tunnel ID', file=sys.stderr); sys.exit(1)
with open(os.path.join(home, 'fake-client.env'), 'w') as f:
    f.write('\n'.join(sorted(os.environ)) + '\n')
    f.write('KEY_MATCHES_FAKE=%s\n' % (os.environ.get('CONTROL_PLANE_API_KEY', '').startswith('FAKE-TEST-KEY-')))
    f.write('ARGS=%s\n' % json.dumps(sorted(opts)))
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == '/readyz' else 404); self.end_headers(); self.wfile.write(b'ok')
    def log_message(self, *a):
        pass
srv = socketserver.TCPServer(('127.0.0.1', 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
with open(opts['--health.url-file'], 'w') as f:
    f.write('http://127.0.0.1:%d' % srv.server_address[1])
child = subprocess.Popen([opts['--mcp.command']], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
child.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}}) + '\n')
child.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}) + '\n')
child.stdin.flush()
child.stdout.readline()
tools = json.loads(child.stdout.readline())['result']['tools']
with open(os.path.join(home, 'fake-client.mcp'), 'w') as f:
    f.write('tools=%d\n' % len(tools))
# Startup-probe stand-in: a shell that actually executes a program named codex for ~1.5 s.
fake_codex = os.path.join(home, 'fake-codex', 'codex')
if os.path.exists(fake_codex):
    subprocess.Popen(['/bin/sh', '-c', '"$1" 1.5; exit 0 # app-server-marker', 'sh', fake_codex])
    # Exec in place, like zsh -lc "codex": the same pid goes from a shell to codex.
    subprocess.Popen(['/bin/sh', '-c', 'sleep 0.6; exec "$1" 1.5 # app-server-marker', 'sh', fake_codex])
def stop(*_):
    child.stdin.close(); child.wait(5); sys.exit(0)
signal.signal(signal.SIGTERM, stop)
auth_fail = os.path.exists(os.path.join(home, 'fake-auth-fail'))
while True:  # chatty like the real client, to exercise output draining
    if auth_fail:  # same wording as the real client's 401, with a fake masked key
        print('WARN poll failed; backing off component=controlplane error="controlplane client: '
              'unexpected status 401: invalid_api_key: Incorrect API key provided: FAKE-***"', flush=True)
    else:
        print('fake-client INFO polling', flush=True)
    time.sleep(0.05)
'''


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_group(pgid, timeout=10):
    """TERM then KILL a test-owned process group; return True if it is gone."""
    for sig, wait in ((signal.SIGTERM, timeout / 2), (signal.SIGKILL, timeout / 2)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass  # macOS: group whose leader is a zombie; membership is checked below
        end = time.time() + wait
        while time.time() < end:
            if subprocess.run(['pgrep', '-g', str(pgid)], capture_output=True).returncode != 0:
                return True
            time.sleep(0.1)
    return subprocess.run(['pgrep', '-g', str(pgid)], capture_output=True).returncode != 0


class Env:
    """Temp HOME with files installed by install.sh and a marked test copy of the CLI."""
    def __init__(self, fake_client=True, extra_overrides=()):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix='hml-', dir='/tmp')).resolve()
        self.home = self.root / 'h'
        self.tmp = self.root / 't'
        self.home.mkdir()
        self.tmp.mkdir()
        r = subprocess.run(['/bin/sh', str(SRC / 'install.sh')], env=self.base_env(), capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        self.install_out = r.stdout
        self.share = self.home / '.local' / 'share' / 'herdr-mcp'
        self.cli = self.share / 'herdr-mcp-tunnel'
        self.link = self.home / '.local' / 'bin' / 'herdr-mcp-tunnel'
        fakes = self.root / 'fakes'
        fakes.mkdir()
        for name, text in (('security', FAKE_SECURITY), ('launchctl', FAKE_LAUNCHCTL), ('tunnel-client', FAKE_CLIENT)):
            (fakes / name).write_text(text)
            os.chmod(fakes / name, 0o755)
        self.fake_zip = fakes / 'fake-tunnel-client.zip'
        with zipfile.ZipFile(self.fake_zip, 'w') as z:
            info = zipfile.ZipInfo('tunnel-client')
            info.external_attr = 0o755 << 16
            z.writestr(info, FAKE_CLIENT)
        overrides = ['# TEST COPY - FAKE INPUT ONLY',
                     'EXTRA_ARGS=(--control-plane.base-url http://127.0.0.1:9)',
                     'ZIP_URL=https://127.0.0.1:9/unreachable.zip',
                     f'SECURITY={fakes}/security', f'LAUNCHCTL={fakes}/launchctl']
        if fake_client:  # pins of the mock client; the official pins stay for fake_client=False
            overrides += [f'ZIP_SHA={sha(self.fake_zip)}', f'CLIENT_SHA={sha(fakes / "tunnel-client")}']
        overrides += list(extra_overrides)
        overrides = '\n'.join(overrides)
        (self.home / 'fake-codex').mkdir()
        # A real executable named codex (ad-hoc re-signed copy of sleep; a plain copy is killed).
        shutil.copy('/bin/sleep', self.home / 'fake-codex' / 'codex')
        subprocess.run(['/usr/bin/codesign', '-f', '-s', '-', str(self.home / 'fake-codex' / 'codex')],
                       check=True, capture_output=True)
        text = self.cli.read_text().replace('# @@TEST_OVERRIDES@@', overrides)
        text = text.replace('# @@TEST_KEYGUARD@@', TEST_KEYGUARD)
        assert '@@' not in text
        self.cli.write_text(text)
        self.herdr = self.root / 'herdr'
        self.herdr.write_text(FAKE_HERDR)
        os.chmod(self.herdr, 0o755)
        self.state = self.home / '.local' / 'state' / 'herdr-mcp'
        self.client_dir = self.state / 'tc-v0.0.16'
        self.config = self.home / '.config' / 'herdr-mcp' / 'config'
        self.pointer = self.state / 'run' / 'launcher.ptr'
        self.plist = self.home / 'Library' / 'LaunchAgents' / 'local.herdr-mcp-tunnel.plist'
        self.tunnel = 'tunnel_' + secrets.token_hex(16)  # random fake id, client-valid format
        self.groups = []

    def base_env(self, **extra):
        return {'PATH': '/usr/bin:/bin', 'HOME': str(self.home), 'TMPDIR': str(self.tmp) + '/', 'TERM': 'xterm',
                'LANG': 'en_US.UTF-8', **DECOYS, **extra}

    def run(self, *args, zsh_flags=(), via_link=True):
        r = subprocess.run(['/bin/zsh', *zsh_flags, str(self.link if via_link else self.cli), *args],
                           env=self.base_env(), capture_output=True, text=True, timeout=120,
                           stdin=subprocess.DEVNULL, start_new_session=True)
        return r.returncode, r.stdout + r.stderr

    def configure(self):
        code, out = self.run('configure', '--tunnel-id', self.tunnel, '--herdr', str(self.herdr))
        assert code == 0, out

    def store_key(self, value=FAKE):
        store = self.home / 'fake-keychain'
        store.mkdir(exist_ok=True)
        (store / f'herdr-mcp-tunnel__{self.tunnel}').write_text(value)

    def agent_pid(self):
        f = self.home / 'fake-launchd' / 'pid'
        return int(f.read_text()) if f.exists() else None

    def close(self):
        """Kill every test-owned process group and verify none remain."""
        leftovers = []
        history = self.home / 'fake-launchd' / 'history'
        if history.exists():
            self.groups.extend(int(x) for x in history.read_text().split())
        for pgid in self.groups:
            if not kill_group(pgid):
                leftovers.append(pgid)
        out = subprocess.run(['pgrep', '-f', str(self.root)], capture_output=True, text=True).stdout.split()
        out += subprocess.run(['pgrep', '-f', self.tunnel], capture_output=True, text=True).stdout.split()
        shutil.rmtree(self.root, ignore_errors=True)
        return leftovers + [int(p) for p in out]


class Pty:
    """Run the CLI on a pseudo-terminal, as an owner would."""
    def __init__(self, env, *args):
        self.fd, self.slave = os.openpty()
        self.pid = os.fork()
        if self.pid == 0:
            try:
                os.setsid()
                fcntl.ioctl(self.slave, termios.TIOCSCTTY, 0)
                for fd in (0, 1, 2):
                    os.dup2(self.slave, fd)
                # The outer shell reports the final echo state before the session (and tty) ends.
                outer = ('zsh "$@"; rc=$?; print; print "ECHOSTATE=$(stty -a </dev/tty | tr " " "\\n" | '
                         'grep -x -- "-\\{0,1\\}echo")"; exit $rc')
                os.execve('/bin/zsh', ['zsh', '-c', outer, 'zsh', str(env.link), *args], env.base_env())
            finally:
                os._exit(127)
        env.groups.append(self.pid)  # setsid: pgid == pid
        self.buf, self.status, self.closing = '', None, False
        # Drain the pty continuously: a full pty buffer would block the launcher's writes.
        self.reader = threading.Thread(target=self.drain, daemon=True)
        self.reader.start()

    def drain(self):
        while not self.closing:
            ready, _, _ = select.select([self.fd], [], [], 0.1)
            if ready:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    return
                if not data:
                    return
                self.buf += data.decode('utf8', 'replace')

    def pump(self, seconds=0.2):
        time.sleep(seconds)

    def reap(self):
        if self.status is None:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid:
                self.status = os.waitstatus_to_exitcode(status)
        return self.status is not None

    def until(self, pattern, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            self.pump()
            if re.search(pattern, self.buf):
                return True
            if self.reap():
                self.pump()
                return bool(re.search(pattern, self.buf))
        return False

    def echo(self):
        if not self.reap():
            return bool(termios.tcgetattr(self.slave)[3] & termios.ECHO)
        found = re.search(r'ECHOSTATE=(-?)echo', self.buf)
        return bool(found) and found.group(1) == ''

    def echo_off_soon(self):
        end = time.time() + 5
        while time.time() < end:
            if not self.echo():
                return True
            time.sleep(0.05)
        return False

    def launcher_pid(self):
        for _ in range(50):
            out = subprocess.run(['pgrep', '-P', str(self.pid)], capture_output=True, text=True).stdout.split()
            if out:
                return int(out[0])
            time.sleep(0.1)
        raise RuntimeError('launcher pid not found')

    def send(self, text):
        os.write(self.fd, text.encode())

    def wait(self, timeout=30):
        end = time.time() + timeout
        while time.time() < end:
            self.pump(0.1)
            if self.reap():
                self.pump()
                return self.status
        return None

    def close(self):
        """Bounded: kill the session's process group first, then close the pty."""
        kill_group(self.pid)
        for _ in range(50):
            if self.reap():
                break
            time.sleep(0.1)
        self.closing = True
        self.reader.join(2)
        for fd in (self.slave, self.fd):
            try:
                os.close(fd)
            except OSError:
                pass


class Base(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.ptys = []

    def tearDown(self):
        for p in self.ptys:
            p.close()
        leftovers = self.e.close()
        self.assertEqual(leftovers, [], 'test-owned processes survived cleanup')

    def pty(self, *args):
        p = Pty(self.e, *args)
        self.ptys.append(p)
        return p


class StaticTests(unittest.TestCase):
    def test_pins_match_source(self):
        text = (SRC / 'herdr-mcp-tunnel').read_text()
        self.assertIn('BRIDGE_SHA=' + sha(SRC / 'herdr_control_mcp.py'), text, 'update BRIDGE_SHA in herdr-mcp-tunnel')
        self.assertIn('WRAP_SHA=' + sha(SRC / 'herdr_control_mcp_child.sh'), text, 'update WRAP_SHA in herdr-mcp-tunnel')
        exec_line = [l for l in (SRC / 'herdr_control_mcp_child.sh').read_text().splitlines() if l.startswith('exec ')][0]
        self.assertIn("WRAP_EXEC_LINE='" + exec_line + "'", text)

    def test_syntax_and_inert_markers(self):
        self.assertEqual(subprocess.run(['/bin/zsh', '-n', str(SRC / 'herdr-mcp-tunnel')]).returncode, 0)
        self.assertEqual(subprocess.run(['/bin/sh', '-n', str(SRC / 'install.sh')]).returncode, 0)
        text = (SRC / 'herdr-mcp-tunnel').read_text()
        self.assertIn('\n# @@TEST_OVERRIDES@@\n', text)
        self.assertIn('\n  # @@TEST_KEYGUARD@@\n', text)

    def test_not_auto_deployed_by_chezmoi(self):
        ignore = (SRC.parent / '.chezmoiignore').read_text().splitlines()
        self.assertIn('herdr-mcp', ignore)
        self.assertIn('herdr-mcp/**', ignore)


class InstallTests(Base):
    def test_install_sh_idempotent_and_refuses_foreign_link(self):
        self.assertTrue(os.path.islink(self.e.link))
        self.assertEqual(os.readlink(self.e.link), str(self.e.cli))
        self.assertEqual(sorted(os.listdir(self.e.share)),
                         ['README.md', 'herdr-mcp-tunnel', 'herdr_control_mcp.py', 'herdr_control_mcp_child.sh'])
        self.assertEqual(self.e.share.joinpath('herdr_control_mcp_child.sh').stat().st_mode & 0o777, 0o755)
        self.assertFalse((self.e.home / 'Library').exists())
        self.assertFalse(self.e.state.exists())
        bridge = self.e.share / 'herdr_control_mcp.py'
        mtime = bridge.stat().st_mtime_ns
        r = subprocess.run(['/bin/sh', str(SRC / 'install.sh')], env=self.e.base_env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(bridge.stat().st_mtime_ns, mtime)
        self.assertNotIn('installed ' + str(bridge), r.stdout)
        os.remove(self.e.link)
        self.e.link.write_text('mine')
        r = subprocess.run(['/bin/sh', str(SRC / 'install.sh')], env=self.e.base_env(), capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('not our symlink', r.stdout)
        self.assertEqual(self.e.link.read_text(), 'mine')


class CommandTests(Base):
    def test_usage_and_tracing_refused(self):
        self.assertEqual(self.e.run()[0], 2)
        self.assertEqual(self.e.run('bogus')[0], 2)
        self.assertEqual(self.e.run('status', 'extra')[0], 2)
        self.assertEqual(self.e.run('agent', 'bogus')[0], 2)
        code, out = self.e.run('check', zsh_flags=('-x',))
        self.assertEqual(code, 2)
        self.assertIn('tracing', out)

    def test_check_requires_config(self):
        code, out = self.e.run('check')
        self.assertEqual(code, 1)
        self.assertIn('not configured', out)

    def test_configure(self):
        self.assertIn('--tunnel-id must look like', self.e.run('configure', '--tunnel-id', 'tunnel_short')[1])
        notherdr = self.e.root / 'nh'
        notherdr.write_text('#!/bin/sh\necho other\n')
        os.chmod(notherdr, 0o755)
        code, out = self.e.run('configure', '--tunnel-id', self.e.tunnel, '--herdr', str(notherdr))
        self.assertEqual(code, 1)
        self.assertIn('did not report herdr', out)
        self.assertFalse(self.e.config.exists())
        self.e.configure()
        first = self.e.config.read_text()
        self.assertIn(f'tunnel_id={self.e.tunnel}\nherdr_exe={self.e.herdr}\nherdr_sha256={sha(self.e.herdr)}', first)
        self.assertEqual(self.e.config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.e.config.parent.stat().st_mode & 0o777, 0o700)
        self.e.configure()
        self.assertEqual(self.e.config.read_text(), first)
        self.assertEqual(sorted(os.listdir(self.e.config.parent)), ['config'])

    def test_install_client_refuses_bad_archive_and_failed_download(self):
        bad = self.e.root / 'bad.zip'
        bad.write_bytes(b'PK\x03\x04 not the release')
        code, out = self.e.run('install-client', '--zip', str(bad))
        self.assertEqual(code, 1)
        self.assertIn('archive SHA-256 mismatch', out)
        code, out = self.e.run('install-client')
        self.assertEqual(code, 1)
        self.assertIn('download failed', out)
        self.assertFalse(self.e.client_dir.exists())
        self.assertEqual(os.listdir(self.e.state), [])

    def test_install_client_idempotent_and_refuses_tampered_client(self):
        code, out = self.e.run('install-client', '--zip', str(self.e.fake_zip))
        self.assertEqual(code, 0, out)
        self.assertEqual(sorted(os.listdir(self.e.client_dir)), ['tunnel-client'])
        self.assertEqual(sorted(os.listdir(self.e.state)), ['tc-v0.0.16'])
        client = self.e.client_dir / 'tunnel-client'
        mtime = client.stat().st_mtime_ns
        code, out = self.e.run('install-client', '--zip', str(self.e.fake_zip))
        self.assertEqual(code, 0)
        self.assertIn('already installed', out)
        self.assertEqual(client.stat().st_mtime_ns, mtime)
        client.write_text('#!/bin/sh\necho junk\n')
        code, out = self.e.run('install-client', '--zip', str(self.e.fake_zip))
        self.assertEqual(code, 1)
        self.assertIn('refusing to overwrite', out)
        self.assertEqual(client.read_text(), '#!/bin/sh\necho junk\n')

    @need_zip
    def test_official_archive_pins_extract_only(self):
        """Official v0.0.16 zip against the production pins. Extraction only: never executed."""
        official = Env(fake_client=False)
        try:
            code, out = official.run('install-client', '--zip', ZIP)
            self.assertEqual(code, 0, out)
            self.assertEqual(sorted(os.listdir(official.client_dir)), ['tunnel-client'])
            self.assertEqual(sha(official.client_dir / 'tunnel-client'),
                             '6f1e8d5494d6c4d6c45cd4f6e07b5291459c0b23f4b8cd8266c7a64be3d9a2a0')
        finally:
            self.assertEqual(official.close(), [])

    def test_check_detects_tampering(self):
        self.e.configure()
        self.assertIn('not installed', self.e.run('check')[1])
        self.e.run('install-client', '--zip', str(self.e.fake_zip))
        code, out = self.e.run('check')
        self.assertEqual(code, 0, out)
        self.assertIn('CHECK-OK', out)
        self.e.herdr.write_text(FAKE_HERDR + '# upgraded\n')
        self.assertIn('does not match the configured SHA-256', self.e.run('check')[1])
        self.e.configure()
        bridge = self.e.share / 'herdr_control_mcp.py'
        bridge.write_text(bridge.read_text() + '\n# tampered\n')
        code, out = self.e.run('check')
        self.assertEqual(code, 1)
        self.assertIn('bridge missing or SHA-256 differs', out)

    def test_status_stop_without_launcher(self):
        self.assertEqual(self.e.run('status'), (3, f'not running (no pointer at {self.e.pointer})\n'))
        self.assertEqual(self.e.run('stop')[0], 0)
        self.e.pointer.parent.mkdir(parents=True)
        self.e.pointer.write_text('2999999\nstale\n')
        for cmd in ('status', 'stop'):
            code, out = self.e.run(cmd)
            self.assertEqual(code, 1)
            self.assertIn('stale pointer', out)
        self.assertEqual(self.e.pointer.read_text(), '2999999\nstale\n')

    def test_stop_refuses_foreign_pid(self):
        sleeper = subprocess.Popen(['/bin/sleep', '60'], start_new_session=True)
        self.e.groups.append(sleeper.pid)
        try:
            self.e.pointer.parent.mkdir(parents=True)
            self.e.pointer.write_text(f'{sleeper.pid}\nx\n')
            code, out = self.e.run('stop')
            self.assertEqual(code, 1)
            self.assertIn('stale pointer', out)
            self.assertTrue(alive(sleeper.pid))
            self.assertTrue(self.e.pointer.exists())
        finally:
            sleeper.kill()
            sleeper.wait()

    def key_set(self, first, second=None, prep=None):
        p = self.pty('key', 'set')
        self.assertTrue(p.until('Runtime key') and p.echo_off_soon(), p.buf)
        p.send(first + '\n')
        if p.until('Same key again', 10):
            self.assertTrue(p.echo_off_soon())
            p.send((first if second is None else second) + '\n')
        status = p.wait(20)
        return status, p

    def item(self):
        return self.e.home / 'fake-keychain' / f'herdr-mcp-tunnel__{self.e.tunnel}'

    def assert_no_leak(self, p, *values):
        argv = (self.e.home / 'fake-security.argv').read_text() if (self.e.home / 'fake-security.argv').exists() else ''
        for v in values:
            self.assertNotIn(v, p.buf)
            self.assertNotIn(v, argv)
        self.assertTrue(p.echo())

    def test_key_set_long_key_stored_whole_and_verified(self):
        self.e.configure()
        key = 'FAKE-' + 'sk_proj-' + 'A1b2_C3-d4' * 15  # 163 chars: longer than getpass keeps
        status, p = self.key_set(key)
        self.assertEqual(status, 0, p.buf)
        self.assertIn('stored and verified', p.buf)
        self.assertEqual(self.item().read_text(), key)
        self.assert_no_leak(p, key, key[:40])
        argv = (self.e.home / 'fake-security.argv').read_text()
        self.assertIn("['-i']", argv)
        code, out = self.e.run('key', 'status')
        self.assertEqual(code, 0)
        self.assertIn('present', out)
        self.assertEqual(self.e.run('key', 'delete')[0], 0)
        self.assertFalse(self.item().exists())

    def test_key_set_detects_truncating_store(self):
        self.e.configure()
        (self.e.home / 'fake-security-truncate').write_text('')
        key = 'FAKEkey_' + 'x' * 150
        status, p = self.key_set(key)
        self.assertEqual(status, 1)
        self.assertIn('does not match what was typed', p.buf)
        self.assert_no_leak(p, key, key[:40])

    def test_key_set_discards_security_output(self):
        self.e.configure()
        (self.e.home / 'fake-security-echo').write_text('')
        key = 'FAKEechoed_' + 'y' * 30
        status, p = self.key_set(key)
        self.assertEqual(status, 0, p.buf)
        self.assert_no_leak(p, key)

    def test_key_set_mismatch_and_bad_input_store_nothing(self):
        self.e.configure()
        status, p = self.key_set('FAKEaaaaaaaaaaaaaaaaaaaaaa', 'FAKEbbbbbbbbbbbbbbbbbbbbbb')
        self.assertEqual(status, 1)
        self.assertIn('the two entries differ', p.buf)
        self.assert_no_leak(p, 'FAKEaaaa', 'FAKEbbbb')
        for bad in ('FAKE short', 'FAKEkey x -U -s other' + 'z' * 10, 'FAKE"quoted"' + 'z' * 20,
                    "FAKE'q;rm" + 'z' * 20, 'FAKE$(id)' + 'z' * 20, '-wFAKEoption' + 'z' * 20,
                    'FAKEtab\t' + 'z' * 20, 'FAKEnull\x01' + 'z' * 20, 'FAKE' + 'k' * 401, 'FAKEshort'):
            status, p = self.key_set(bad)
            self.assertEqual(status, 1, repr(bad))
            self.assertIn('key rejected', p.buf, repr(bad))
            self.assert_no_leak(p, bad)
        self.assertFalse(self.item().exists())
        self.assertFalse((self.e.home / 'fake-security.argv').exists())  # security never ran
        self.assertIn('needs a terminal', self.e.run('key', 'set')[1])

    def test_key_set_refuses_tracing(self):
        self.e.configure()
        code, out = self.e.run('key', 'set', zsh_flags=('-x',))
        self.assertEqual(code, 2)
        self.assertIn('tracing', out)
        code, out = self.e.run('key', 'set', zsh_flags=('-v',))
        self.assertEqual(code, 2)

    def test_agent_install_requires_key_and_client(self):
        self.e.configure()
        code, out = self.e.run('agent', 'install')
        self.assertEqual(code, 1)
        self.assertFalse(self.e.plist.exists())
        self.assertFalse((self.e.home / 'fake-launchctl.argv').exists())


class LifecycleTests(Base):
    """Mock tunnel-client (FAKE_CLIENT): the real client is not executed by these tests."""
    def setUp(self):
        super().setUp()
        self.e.configure()
        code, out = self.e.run('install-client', '--zip', str(self.e.fake_zip))
        assert code == 0, out

    def wait_health(self):
        for _ in range(60):
            if list((self.e.state / 'run').glob('tc.*/health.url')):
                return True
            time.sleep(0.5)
        return False

    def assert_client_boundary(self, client):
        argv_all = subprocess.run(['ps', '-axww', '-o', 'command'], capture_output=True, text=True).stdout
        self.assertNotIn('FAKE-TEST-KEY', argv_all)
        client_env = subprocess.run(['ps', 'eww', '-p', str(client)], capture_output=True, text=True).stdout
        self.assertIn('CONTROL_PLANE_API_KEY=', client_env)
        for name in DECOYS:
            self.assertNotIn(name + '=', client_env)
        listen = subprocess.run(['lsof', '-nP', '-a', '-p', str(client), '-iTCP', '-sTCP:LISTEN'],
                                capture_output=True, text=True).stdout.splitlines()[1:]
        self.assertTrue(listen)
        self.assertTrue(all('127.0.0.1:' in l for l in listen), listen)
        seen = (self.e.home / 'fake-client.env').read_text()
        self.assertIn('KEY_MATCHES_FAKE=True', seen)
        for _ in range(50):
            mcp = self.e.home / 'fake-client.mcp'
            if mcp.exists():
                break
            time.sleep(0.1)
        self.assertEqual(mcp.read_text(), 'tools=7\n')  # client -> wrapper -> bridge over stdio

    def assert_children_log(self, client):
        log = self.e.state / 'children.log'
        for _ in range(60):
            text = log.read_text() if log.exists() else ''
            if 'to=codex' in text and 'event=unobserved pid' in text and 'class=codex observed' in text:
                break
            time.sleep(0.1)
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        lines = text.splitlines()
        self.assertTrue(all(f' client={client} ' in l for l in lines), text)
        self.assertRegex(text, r'event=seen pid=\d+ ppid=\d+ depth=1 class=shell')
        self.assertRegex(text, r'event=seen pid=\d+ ppid=\d+ depth=2 class=codex')
        # The wrapper (sh) execs the bridge under the same pid: seen as shell, then reclassified.
        self.assertRegex(text, r'event=reclassified pid=\d+ from=shell to=bridge')
        self.assertRegex(text, r'event=unobserved pid=\d+ class=codex observed_secs=\d+')
        self.assertRegex(text, r'event=reclassified pid=\d+ from=shell to=codex')
        for leaked in ('FAKE', 'app-server', 'marker', '1.5', 'fake-codex', 'sleep', 'CONTROL_PLANE', 'HOME='):
            self.assertNotIn(leaked, text)
        classes = set(re.findall(r'class=(\S+)', text))
        self.assertLessEqual(classes, {'codex', 'shell', 'bridge', 'client', 'other'})

    def test_observer_stops_with_launcher_and_marks_no_synthetic_end(self):
        p = self.pty('start')
        self.assertTrue(p.until('Runtime key') and p.echo_off_soon())
        p.send(FAKE + '\r')
        self.assertTrue(p.until('tunnel-client started', 60), p.buf)
        launcher = p.launcher_pid()
        self.assertTrue(self.wait_health())
        kids = subprocess.run(['pgrep', '-P', str(launcher)], capture_output=True, text=True).stdout.split()
        self.assertEqual(len(kids), 2, kids)  # client + observer subshell
        os.kill(launcher, signal.SIGTERM)
        self.assertEqual(p.wait(30), 143)
        for pid in kids:
            self.assertFalse(alive(int(pid)), pid)
        text = (self.e.state / 'children.log').read_text()
        self.assertNotIn('FAKE', text)

    def test_full_cycle_start_status_stop(self):
        p = self.pty('start')
        self.assertTrue(p.until('Runtime key') and p.echo_off_soon(), p.buf)
        p.send(FAKE + '\r')
        self.assertTrue(p.until('tunnel-client started', 60), p.buf)
        self.assertTrue(self.e.pointer.exists(), p.buf)
        launcher = int(self.e.pointer.read_text().split()[0])
        client = int(re.search(r'tunnel-client started \(pid (\d+)\)', p.buf).group(1))
        self.assertTrue(self.wait_health(), p.buf)
        self.assert_client_boundary(client)
        code, out = self.e.run('status')
        self.assertRegex(out, rf'launcher pid {launcher}; child pids: .*\b{client}\b')
        self.assert_children_log(client)
        self.assertIn('health: http://127.0.0.1:', out)
        self.assertIn('LOCAL-READY (local health only; not authenticated, not end-to-end', out)
        self.assertIn('auth: not checked (interactive start', out)
        self.assertNotRegex(out, r'(?m)^READY$')
        second = self.pty('start')
        self.assertEqual(second.wait(30), 1)
        self.assertIn('already running', second.buf)
        self.assertNotIn('Runtime key', second.buf)
        code, out = self.e.run('stop')
        self.assertEqual(code, 0, out)
        self.assertEqual(p.wait(30), 143)
        self.assertFalse(alive(client))
        self.assertFalse(alive(launcher))
        self.assertTrue(p.echo())
        self.assertFalse(self.e.pointer.exists())
        self.assertEqual(list((self.e.state / 'run').glob('tc.*')), [])
        log = (self.e.state / 'launcher-runs.log').read_text()
        self.assertIn(f'launcher={launcher} client={client} launcher_signal=TERM event=stopped-by-launcher', log)
        self.assertNotIn('FAKE', log + p.buf)
        self.assertEqual(self.e.run('stop')[0], 0)
        self.assertEqual(self.e.run('status')[0], 3)

    def test_rejected_key_starts_nothing(self):
        p = self.pty('start')
        self.assertTrue(p.until('Runtime key') and p.echo_off_soon())
        p.send('FAKE-TEST-KEY-a\r')
        self.assertEqual(p.wait(30), 1)
        self.assertIn('key rejected', p.buf)
        self.assertNotIn('FAKE-TEST-KEY-a', p.buf)
        self.assertTrue(p.echo())
        self.assertFalse(self.e.pointer.exists())
        self.assertNotIn('tunnel-client started', p.buf)

    def test_sigint_at_prompt_restores_terminal(self):
        p = self.pty('start')
        self.assertTrue(p.until('Runtime key') and p.echo_off_soon())
        self.assertTrue(self.e.pointer.exists())
        os.kill(p.launcher_pid(), signal.SIGINT)
        self.assertEqual(p.wait(20), 130)
        self.assertTrue(p.echo())
        self.assertFalse(self.e.pointer.exists())
        self.assertEqual(list((self.e.state / 'run').glob('tc.*')), [])

    def test_duplicate_tunnel_client_refused(self):
        dummy = subprocess.Popen(['/usr/bin/python3', '-c', 'import time; time.sleep(60)',
                                  '--control-plane.tunnel-id', self.e.tunnel], start_new_session=True)
        self.e.groups.append(dummy.pid)
        try:
            p = self.pty('start')
            self.assertEqual(p.wait(30), 1)
            self.assertIn('already running', p.buf)
            self.assertNotIn('Runtime key', p.buf)
            self.e.store_key()
            code, out = self.e.run('run')
            self.assertEqual(code, 1)
            self.assertIn('already running', out)
        finally:
            dummy.kill()
            dummy.wait()

    def test_stale_pointer_reclaimed(self):
        (self.e.state / 'run').mkdir(parents=True)
        stale_dir = self.e.state / 'run' / 'tc.STALE'
        stale_dir.mkdir()
        (stale_dir / 'health.url').write_text('http://127.0.0.1:1')
        self.e.pointer.write_text(f'2999999\n{stale_dir}/health.url\n')
        p = self.pty('start')
        self.assertTrue(p.until('Runtime key'), p.buf)
        self.assertIn('removing stale pointer', p.buf)
        self.assertFalse(stale_dir.exists())
        self.assertEqual(self.e.pointer.read_text().split()[0], str(p.launcher_pid()))

    def test_concurrent_runs_with_stale_pointer_start_one_client(self):
        self.e.store_key()
        run = self.e.state / 'run'
        run.mkdir(parents=True)
        self.e.pointer.write_text('2999999\nstale\n')
        procs = [subprocess.Popen(['/bin/zsh', str(self.e.link), 'run'], env=self.e.base_env(), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
                 for _ in range(3)]
        self.e.groups.extend(p.pid for p in procs)
        try:
            self.assertTrue(self.wait_health())
            time.sleep(1)
            running = [p for p in procs if p.poll() is None]
            self.assertEqual(len(running), 1)
            for p in procs:
                if p is not running[0]:
                    self.assertEqual(p.returncode, 1)
                    self.assertRegex(p.stdout.read(), r'launcher\.lock|already running')
            self.assertEqual(self.e.pointer.read_text().split()[0], str(running[0].pid))
            clients = subprocess.run(['pgrep', '-f', 'control-plane.tunnel-id ' + self.e.tunnel],
                                     capture_output=True, text=True).stdout.split()
            self.assertEqual(len(clients), 1)
            os.kill(running[0].pid, signal.SIGTERM)
            self.assertEqual(running[0].wait(30), 143)
        finally:
            for p in procs:
                if p.poll() is None:
                    p.kill()
                p.wait()
                p.stdout.close()

    def agent_up(self):
        self.e.store_key()
        code, out = self.e.run('agent', 'install')
        self.assertEqual(code, 0, out)
        self.assertTrue(self.wait_health())
        time.sleep(1)

    def test_agent_log_owner_only_even_if_preexisting(self):
        self.e.state.mkdir(parents=True, exist_ok=True)
        log = self.e.state / 'agent.log'
        log.write_text('old\n')
        os.chmod(log, 0o644)
        self.agent_up()
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.e.run('agent', 'uninstall')[0], 0)

    def test_auth_failure_in_current_run_detected(self):
        (self.e.home / 'fake-auth-fail').write_text('')
        self.agent_up()
        code, out = self.e.run('status')
        self.assertEqual(code, 4, out)
        self.assertIn('AUTH-FAILED', out)
        self.assertNotIn('LOCAL-READY', out)
        self.assertNotIn('FAKE-***', out)  # status never prints the client's error text
        self.assertEqual(self.e.run('agent', 'uninstall')[0], 0)

    def test_stale_auth_errors_from_earlier_run_ignored(self):
        self.e.state.mkdir(parents=True, exist_ok=True)
        (self.e.state / 'agent.log').write_text(
            'herdr-mcp-tunnel: run-start run=1-20260101T000000Z-1\n'
            'WARN poll failed unexpected status 401: invalid_api_key\n' * 3)
        self.agent_up()
        code, out = self.e.run('status')
        self.assertEqual(code, 0, out)
        self.assertIn('auth: no control-plane auth error in this run', out)
        self.assertIn('LOCAL-READY', out)
        self.assertEqual(self.e.run('agent', 'uninstall')[0], 0)

    def test_run_requires_keychain_item(self):
        code, out = self.e.run('run')
        self.assertEqual(code, 1)
        self.assertIn('cannot read keychain item', out)
        self.assertFalse(self.e.pointer.exists())
        self.e.store_key('short')
        code, out = self.e.run('run')
        self.assertEqual(code, 1)
        self.assertIn('key rejected', out)
        self.assertNotIn('short', out.replace('key rejected', ''))

    def test_launch_agent_install_status_uninstall(self):
        self.e.store_key()
        code, out = self.e.run('agent', 'install', '--no-load')
        self.assertEqual(code, 0, out)
        self.assertIsNone(self.e.agent_pid())
        spec = plistlib.loads(self.e.plist.read_bytes())
        self.assertEqual(spec['ProgramArguments'], ['/bin/zsh', str(self.e.cli), 'run'])
        self.assertTrue(spec['RunAtLoad'])
        self.assertEqual(spec['KeepAlive'], {'SuccessfulExit': False})
        self.assertNotIn(FAKE, self.e.plist.read_text())
        self.assertEqual(self.e.plist.stat().st_mode & 0o777, 0o644)
        code, out = self.e.run('agent', 'install')
        self.assertEqual(code, 0, out)
        self.assertIn('plist unchanged', out)
        agent = self.e.agent_pid()
        self.assertTrue(agent and alive(agent))
        self.assertTrue(self.wait_health(), (self.e.state / 'agent.log').read_text())
        launcher = int(self.e.pointer.read_text().split()[0])
        self.assertEqual(launcher, agent)
        client = int(subprocess.run(['pgrep', '-f', 'control-plane.tunnel-id ' + self.e.tunnel],
                                    capture_output=True, text=True).stdout.split()[0])
        self.assert_client_boundary(client)
        code, out = self.e.run('agent', 'status')
        self.assertIn('launchd: loaded', out)
        self.assertIn(f'launcher pid {launcher}', out)
        code, out = self.e.run('stop')
        self.assertEqual(code, 1)
        self.assertIn("is the LaunchAgent's", out)
        self.assertTrue(alive(launcher))
        self.assertIn('agent already loaded', self.e.run('agent', 'install')[1])
        code, out = self.e.run('agent', 'uninstall')
        self.assertEqual(code, 0, out)
        self.assertIn(f'launcher pid {launcher} exited', out)
        self.assertFalse(alive(launcher))
        self.assertFalse(alive(client))
        self.assertFalse(self.e.plist.exists())
        self.assertFalse(self.e.pointer.exists())
        self.assertEqual(self.e.run('agent', 'uninstall')[0], 0)
        logs = (self.e.state / 'agent.log').read_text() + (self.e.state / 'launcher-runs.log').read_text()
        self.assertNotIn(FAKE, logs)
        self.assertIn(f'launcher={launcher} client={client} launcher_signal=TERM', logs)
        calls = (self.e.home / 'fake-launchctl.argv').read_text()
        self.assertNotIn(FAKE, calls + (self.e.home / 'fake-security.argv').read_text())



class ChildLogRotationTests(Base):
    def setUp(self):
        self.e = Env(extra_overrides=['CHILD_LOG_MAX=100', 'OBSERVE_FAST_SECS=0'])
        self.ptys = []
        self.e.configure()
        code, out = self.e.run('install-client', '--zip', str(self.e.fake_zip))
        assert code == 0, out

    def test_child_log_bounded(self):
        self.e.store_key()
        proc = subprocess.Popen(['/bin/zsh', str(self.e.link), 'run'], env=self.e.base_env(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        self.e.groups.append(proc.pid)
        try:
            time.sleep(7)  # slow polling (5 s) so at least two polls write records
        finally:
            os.kill(proc.pid, signal.SIGTERM)
            self.assertEqual(proc.wait(30), 143)
        names = sorted(n for n in os.listdir(self.e.state) if n.startswith('children.log'))
        self.assertEqual(names, ['children.log', 'children.log.1'])
        for n in names:
            self.assertLess((self.e.state / n).stat().st_size, 100 + 200)


if __name__ == '__main__':
    unittest.main()
