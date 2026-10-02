"""Private PTY/CLI observation harness for the new public lifecycle journeys."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import struct
import subprocess
import sys
import termios
import time

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'dot_pi/private_agent/extensions/recap'
CLI = ROOT / 'dot_local/share/session-recap/session_recap.py'


class PublicPi:
    def __init__(self, root, *, oversized=False, environment=None, config=None, agent_settings=None, seed_defaults=False, terminal=None):
        self.root = root
        self.extension = root / 'recap'
        shutil.copytree(SOURCE, self.extension)
        self.agent = root / 'agent'
        (self.agent / 'extensions').mkdir(parents=True)
        if agent_settings is not None:
            (self.agent / 'settings.json').write_text(json.dumps(agent_settings))
        self.fixture = self.agent / 'extensions/fixture.ts'
        shutil.copy(Path(__file__).with_name('public_fixture.ts'), self.fixture)
        base = json.loads((SOURCE / 'create_config.json').read_text()) if seed_defaults else dict(model=dict(provider='recap-proof', id='recap'), completed=False, periodic=False, beforeCompaction=False, inputBudget=1600, timeoutSeconds=40)
        (self.extension / 'config.json').write_text(json.dumps(base | (config or {})))
        self.log = root / 'provider.jsonl'
        self.transport = root / 'transport.jsonl'
        self.gate = root / 'old-gate'
        self.slow = root / 'slow'
        wrapper = root / 'observe.py'
        # Observe the accepted envelope and stream while forwarding unchanged to the
        # delivered CLI. No replacement receipt, settings, material or generation.
        wrapper.write_text('''import json, os, subprocess, sys, time
from pathlib import Path
log = Path(os.environ['PROOF_TRANSPORT'])
def emit(event):
    with log.open('a') as f: f.write(json.dumps(dict(event, time=time.monotonic())) + '\\n')
if sys.argv[1] == 'run':
    request = json.loads(Path(sys.argv[sys.argv.index('--request-file') + 1]).read_text())
    emit(dict(event='envelope', pid=os.getpid(), token=request['token'], request_key=request['request_key'], recursive=request['recursive'], budget=request['input_budget_bytes'], timeout=request['timeout_seconds'], material=request['material'], background=request.get('background', ''), instructions=request['instructions'], selection=json.loads(request['command'][-1])))
    p = subprocess.Popen([sys.executable, os.environ['GENUINE_RECAP_CLI'], *sys.argv[1:]], stdout=subprocess.PIPE, text=True)
    for line in p.stdout:
        emit(json.loads(line))
        try: print(line, end='', flush=True)
        except BrokenPipeError: sys.stdout = open(os.devnull, 'w')
    code = p.wait()
    emit(dict(event='exited', pid=os.getpid(), token=request['token'], code=code))
    sys.exit(code)
os.execv(sys.executable, [sys.executable, os.environ['GENUINE_RECAP_CLI'], *sys.argv[1:]])
''')
        self.env = dict({k: os.environ[k] for k in ('PATH', 'TERM', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR') if k in os.environ}, HOME=str(root), XDG_DATA_HOME=str(root / 'data'), XDG_CONFIG_HOME=str(root / 'config'), PI_CODING_AGENT_DIR=str(self.agent), PI_OFFLINE='1', PI_RECAP_CLI=str(wrapper), GENUINE_RECAP_CLI=str(CLI), PROOF_TRANSPORT=str(self.transport), RECAP_PROOF_LOG=str(self.log), RECAP_PROOF_COUNTER=str(root / 'counter'), RECAP_PROOF_GATE=str(self.gate), RECAP_PROOF_SLOW=str(self.slow), RECAP_PROOF_OVERSIZED='1' if oversized else '0')
        wrapper_dir = root / '.local/bin'
        wrapper_dir.mkdir(parents=True)
        shutil.copy(ROOT / 'dot_local/bin/executable_session-recap', wrapper_dir / 'session-recap')
        (wrapper_dir / 'session-recap').chmod(0o700)
        self.env.update(environment or {})
        self.master, self.slave = pty.openpty()
        self.tty = os.ttyname(self.slave)
        self.output = bytearray()
        self.terminal_screen = terminal
        self.process = None
        self.launch()
        os.close(self.slave)
        self.collect(4)

    def launch(self, session=None):
        fd = os.open(self.tty, os.O_RDWR)
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 160, 0, 0))
        if self.terminal_screen: self.terminal_screen.resize(160, 36)
        args = ['pi', '--offline', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-context-files', '--provider', 'recap-proof', '--model', 'main', '-e', str(self.fixture), '-e', str(self.extension / 'index.ts'), '--session-dir', str(self.root / 'sessions')]
        if session: args += ['--session', str(session)]
        self.process = subprocess.Popen(args, stdin=fd, stdout=fd, stderr=fd, env=self.env, cwd=self.root)
        os.close(fd)

    def collect(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if select.select([self.master], [], [], .05)[0]:
                try:
                    data = os.read(self.master, 65536)
                    self.output.extend(data)
                    if self.terminal_screen: self.terminal_screen.feed(data)
                except OSError: time.sleep(.05)

    def send(self, value, seconds=.5):
        os.write(self.master, value.encode() + b'\r')
        self.collect(seconds)

    def wait(self, predicate, message, seconds=50):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if predicate(): return
            self.collect(.1)
        raise AssertionError(message)

    @staticmethod
    def lines(path):
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def redraw(self):
        # A terminal resize requests a full rendering rather than Pi's ordinary
        # changed-line-only output (which omits unchanged reused narrative lines).
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 159, 0, 0))
        os.kill(self.process.pid, signal.SIGWINCH)
        self.collect(.5)

    def events(self): return self.lines(self.log)
    def receipts(self): return self.lines(self.transport)
    def envelopes(self): return [e for e in self.receipts() if e['event'] == 'envelope']
    def calls(self): return [e for e in self.events() if e.get('model') == 'recap' and e['event'] == 'call']
    def records(self): return json.loads(subprocess.check_output([sys.executable, str(CLI), 'list', '--json'], env=self.env))['records']
    def current(self, key): return json.loads(subprocess.check_output([sys.executable, str(CLI), 'current', '--key', key, '--json'], env=self.env))
    def terminal(self, token): return next((e for e in self.receipts() if e['event'] == 'terminal' and e['token'] == token), None)
    def visible(self, start=0): return self.output[start:].decode(errors='replace')

    def setting(self, field, value):
        # Real /recap settings selector, Set action and JSON input. Row ordering is
        # the public seed-settings ordering already used by manual.py.
        fields = ['model', 'completed', 'periodic', 'beforeCompaction', 'mode', 'cadence', 'intervalMinutes', 'timeoutSeconds', 'recursion', 'instructions', 'options', 'timeZone']
        defaults_before = (self.extension / 'config.json').read_text()
        start = len(self.output)
        self.send('/recap settings')
        self.wait(lambda: 'Recap session settings' in ('\n'.join(self.terminal_screen.screen.display) if self.terminal_screen else self.visible(start)), 'settings did not open', seconds=10)
        for _ in range(fields.index(field) + 2):
            os.write(self.master, b'\x1b[B'); self.collect(.05)
        self.send(''); self.send('')
        assert f'Set {field}' in ('\n'.join(self.terminal_screen.screen.display) if self.terminal_screen else self.visible(start)), 'wrong setting dialog'
        os.write(self.master, b'\x01\x0b')
        self.send(json.dumps(value))
        os.write(self.master, b'\x1b'); self.collect(.5)
        entries = [json.loads(line) for p in (self.root / 'sessions').rglob('*.jsonl') for line in p.read_text().splitlines()]
        assert any(e.get('customType') == 'recap-state' and e['data']['overrides'].get(field) == value for e in entries), 'public setting not persisted'
        assert (self.extension / 'config.json').read_text() == defaults_before, 'session setting changed defaults'

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill(); self.process.wait()

    def close(self):
        self.gate.unlink(missing_ok=True); self.slow.unlink(missing_ok=True)
        # Cancel only keys created by this private fixture, even on a failed assertion.
        for key in {e['request_key'] for e in self.envelopes()}:
            subprocess.run([sys.executable, str(CLI), 'cancel', '--key', key, '--json'], env=self.env, capture_output=True, timeout=10)
        self.stop()
        end = time.monotonic() + 10
        while time.monotonic() < end:
            started = {e['pid'] for e in self.envelopes()}
            exited = {e['pid'] for e in self.receipts() if e['event'] == 'exited'}
            if started <= exited: break
            self.collect(.1)
        else:
            for pid in started - exited:
                try: os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError: pass
            raise AssertionError('private supervisor did not finish cleanup')
        os.close(self.master)

    def assert_no_transcript_output(self):
        for path in (self.root / 'sessions').rglob('*.jsonl'):
            for line in path.read_text().splitlines():
                if json.loads(line).get('type') == 'message':
                    assert 'recap-deliver-internal' not in line and not any(f'Observed {topic}:' in line for topic in ('orchard', 'harbor', 'older', 'newer')), 'recap entered native transcript'
