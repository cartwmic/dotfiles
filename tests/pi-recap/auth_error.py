#!/usr/bin/env python3
"""Authenticated provider error through real Pi, SDK and recap supervisor; successful followup."""
import backend
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shutil
import struct
import subprocess
import tempfile
import termios
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'dot_pi/private_agent/extensions/recap'
with tempfile.TemporaryDirectory(prefix='recap-auth-error-') as temporary:
    root = Path(temporary)
    extension = root / 'recap'
    shutil.copytree(SOURCE, extension)
    agent = root / 'agent'
    (agent / 'extensions').mkdir(parents=True)
    fixture = agent / 'extensions/fixture.ts'
    shutil.copy(SOURCE / 'automation-fixture.ts', fixture)
    server = backend.http.server.ThreadingHTTPServer(('127.0.0.1', 0), backend.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    auth_source = agent / 'extensions/auth.js'
    auth_source.write_text('''export default function(pi) {
pi.registerProvider("sdk-auth", {api:"openai-completions",baseUrl:"http://127.0.0.1:PORT/v1",apiKey:"AUTH_SENTINEL_PRIVATE",models:[{id:"chosen",name:"chosen",reasoning:false,input:["text"],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:32768,maxTokens:256}]});
}'''.replace('PORT', str(server.server_port)))
    (extension / 'config.json').write_text(json.dumps({'model': {'provider': 'sdk-auth', 'id': 'chosen'}, 'completed': False, 'periodic': False, 'beforeCompaction': False}))
    log = root / 'events.jsonl'
    wrapper_dir = root / '.local/bin'
    wrapper_dir.mkdir(parents=True)
    shutil.copy(ROOT / 'dot_local/bin/executable_session-recap', wrapper_dir / 'session-recap')
    (wrapper_dir / 'session-recap').chmod(0o700)
    env = dict({k: os.environ[k] for k in ('PATH', 'TERM', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR') if k in os.environ}, HOME=str(root), PI_CODING_AGENT_DIR=str(agent), XDG_DATA_HOME=str(root / 'data'), XDG_CONFIG_HOME=str(root / 'config'), PI_OFFLINE='1', PI_RECAP_CLI=str(ROOT / 'dot_local/share/session-recap/session_recap.py'), RECAP_PROOF_LOG=str(log))
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 140, 0, 0))
    process = subprocess.Popen(['pi', '--offline', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-context-files', '--session-dir', str(root / 'sessions'), '--provider', 'recap-proof', '--model', 'main', '-e', str(fixture), '-e', str(auth_source), '-e', str(extension / 'index.ts')], stdin=slave, stdout=slave, stderr=slave, env=env)
    os.close(slave)
    output = bytearray()
    captures = []
    def collect(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if select.select([master], [], [], .05)[0]:
                try: output.extend(os.read(master, 65536))
                except OSError: break
    def send(text, seconds):
        os.write(master, text.encode() + b'\r'); collect(seconds)
    def invoke(*args):
        result = subprocess.run(['python3', env['PI_RECAP_CLI'], *args], env=env, capture_output=True, text=True, timeout=30)
        captures.append(result.stdout + result.stderr)
        assert result.returncode == 0, 'CLI inspection failed'
        return json.loads(result.stdout)
    def scan():
        assert 'AUTH_SENTINEL_PRIVATE' not in output.decode(errors='replace') + ''.join(captures), 'auth leaked in visible/captured output'
        assert all('AUTH_SENTINEL_PRIVATE' not in json.dumps(body) for body in backend.bodies), 'auth serialized in model request'
        for path in root.rglob('*'):
            if path.is_file() and path != auth_source:
                assert b'AUTH_SENTINEL_PRIVATE' not in path.read_bytes(), f'auth leaked in generated file {path.relative_to(root)}'
    try:
        collect(4)
        send('authenticated-error-followup', 9)
        backend.failing = True
        send('/recap', 9)
        assert len(backend.bodies) == 2 and backend.auth == [True, True], 'authenticated immediate retry not observed'
        assert 'Recap failed; coverage unchanged.' in output.decode(errors='replace'), 'sanitized failure not visible'
        records = invoke('list', '--json')['records']
        assert not any(r['status'] == 'published' for r in records), 'failed generation published'
        assert records and all(r['status'] == 'failed' for r in records), 'failed attempt records absent'
        for row in records:
            failed = invoke('read', row['record_id'], '--json')['record']
            assert failed['failure']['message'], 'failure metadata absent'
        scan()
        backend.failing = False
        send('/recap', 6)
        assert len(backend.bodies) == 3 and all(backend.auth), 'authenticated followup missing'
        assert 'PROOF_TOOL_RESULT' in json.dumps(backend.bodies[-1]) and 'PROOF_FINAL' in json.dumps(backend.bodies[-1]), 'failure advanced coverage'
        saved = [r for r in invoke('list', '--json')['records'] if r['status'] == 'published']
        assert len(saved) == 1, 'followup record missing'
        record = invoke('read', saved[0]['record_id'], '--json')['record']
        assert record['summary'] == 'SDK_RECAP: alpha completed.'
        assert 'SDK_RECAP' in output.decode(errors='replace'), 'successful followup not visible'
        sessions = list((root / 'sessions').rglob('*.jsonl'))
        for path in sessions:
            for line in path.read_text().splitlines():
                if json.loads(line).get('type') == 'message':
                    assert 'SDK_RECAP' not in line, 'recap archived as conversation'
        events = [json.loads(line) for line in log.read_text().splitlines()]
        assert sum(e.get('event') == 'agent-start' for e in events) == 1, 'recap caused extra agent turn'
        assert sum(e.get('model') == 'main' for e in events) == 2, 'recap changed main model requests'
        scan()
        print(json.dumps({'status': 'PASS', 'cases': ['runtime-auth-live-error-sanitized-public-retry', 'auth-error-storage-capture-model-transcript-exclusion', 'authenticated-error-followup-preserves-coverage'], 'requests': len(backend.bodies)}))
    finally:
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
        os.close(master)
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        assert not thread.is_alive(), 'server cleanup failed'
assert not root.exists(), 'private fixture cleanup failed'
