#!/usr/bin/env python3
"""Installed SDK through the delivered backend, with private local SSE/auth fixtures."""
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / 'dot_pi/private_agent/extensions/recap/backend.mjs'
bodies = []
auth = []
failing = False
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_POST(self):
        bodies.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
        auth.append(self.headers.get('Authorization') == 'Bearer AUTH_SENTINEL_PRIVATE')
        if failing:
            self.send_response(401)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': {'message': 'Controlled failure AUTH_SENTINEL_PRIVATE', 'type': 'authentication_error'}}).encode())
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        chunk = {'id': 'fixture', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'chosen'}
        for delta, finish in [({'role': 'assistant', 'content': 'SDK_RECAP: alpha completed.'}, None), ({}, os.environ.get('RECAP_PROOF_FINISH', 'stop'))]:
            self.wfile.write(('data: ' + json.dumps({**chunk, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')
        self.wfile.flush()

def main():
    sdk = Path(subprocess.check_output(['npm', 'root', '-g'], text=True).strip()) / '@earendil-works/pi-coding-agent/dist/index.js'
    assert sdk.is_file(), sdk
    with tempfile.TemporaryDirectory(prefix='recap-sdk-') as temporary:
        root = Path(temporary)
        agent = root / 'agent'
        extensions = agent / 'extensions'
        extensions.mkdir(parents=True)
        work = root / 'work'
        work.mkdir()
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        fixture = '''export default function(pi) {
 pi.registerProvider("sdk-fixture", {api:"openai-completions",baseUrl:"http://127.0.0.1:PORT/v1",apiKey:"AUTH_SENTINEL_PRIVATE",models:["chosen","unrelated-main"].map(id=>({id,name:id,reasoning:false,input:["text"],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:32768,maxTokens:256}))});
 pi.registerVirtualModel({provider:"router-fixture",id:"auto",route(request,ctx){if(request.reason!=="direct")throw Error("Not direct");return {model:ctx.modelRegistry.find("sdk-fixture","chosen"),thinkingLevel:"off"};}});
 pi.on("before_agent_start",()=>{throw Error("Unexpected agent turn");});
}'''
        (extensions / 'fixture.js').write_text(fixture.replace('PORT', str(server.server_port)))
        (agent / 'settings.json').write_text(json.dumps({'defaultProvider': 'sdk-fixture', 'defaultModel': 'unrelated-main'}))
        env = dict({k: os.environ[k] for k in ('PATH', 'TERM', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR') if k in os.environ}, HOME=str(root), PI_CODING_AGENT_DIR=str(agent), PI_OFFLINE='1', XDG_DATA_HOME=str(root / 'data'), XDG_CONFIG_HOME=str(root / 'config'))
        try:
            for provider, model in [('sdk-fixture', 'chosen'), ('router-fixture', 'auto')]:
                selection = {'model': {'provider': provider, 'id': model}, 'instructions': 'Recap observed work.', 'options': {'thinkingLevel': 'off', 'maxTokens': 256}}
                if provider == 'router-fixture':
                    # Public virtual routing must not carry caller auth to another provider.
                    selection['options'].update(apiKey='VIRTUAL_ONLY_DUMMY', headers={'Authorization': 'Bearer VIRTUAL_ONLY_DUMMY'}, env={'VIRTUAL_DUMMY_TOKEN': 'VIRTUAL_ONLY_DUMMY'})
                result = subprocess.run(['node', str(BACKEND), str(sdk), str(agent), str(work), json.dumps(selection)], input='SOURCE_SENTINEL alpha completed.', text=True, capture_output=True, env=env, timeout=30)
                if os.environ.get('RECAP_PROOF_FINISH') == 'length':
                    assert result.returncode == 1 and result.stdout == '' and result.stderr == 'Recap backend failed\n', 'unfinished SDK response was accepted'
                else:
                    assert result.returncode == 0, result.stderr
                    assert result.stdout == 'SDK_RECAP: alpha completed.', result.stdout
            cli = ROOT / 'dot_local/share/session-recap/session_recap.py'
            def invoke(*args):
                return subprocess.run([sys.executable, str(cli), *args], env=env, text=True, capture_output=True, timeout=40)
            token = json.loads(invoke('reserve', '--key', 'auth-proof', '--json').stdout)['token']
            request = root / 'request.json'
            request.write_text(json.dumps(dict(schema_version=1, request_key='auth-proof', token=token,
                source_kind='generic', source_id='private-auth-proof', kind='single', metadata={},
                material='SOURCE_SENTINEL alpha completed.', instructions='Recap observed work.',
                command=['node', str(BACKEND), str(sdk), str(agent), str(work), json.dumps(selection)],
                backend_identity={'provider': provider, 'model': model}, timeout_seconds=30,
                input_budget_bytes=4096, recursive=False)))
            request.chmod(0o600)
            result = invoke('run', '--request-file', str(request), '--json-lines')
            assert result.returncode == 0, result.stderr
            events = [json.loads(line) for line in result.stdout.splitlines()]
            if os.environ.get('RECAP_PROOF_FINISH') == 'length':
                assert events[-1]['status'] == 'failed', events
                assert len(bodies) == 4, 'unfinished attempt did not retry exactly once'
                assert not [r for r in json.loads(invoke('list', '--json').stdout)['records'] if r['status'] == 'published']
                assert not (agent / 'sessions').exists()
                print(json.dumps({'status': 'PASS', 'case': 'installed-sdk-length-refused-physical-virtual-cli-one-retry', 'requests': len(bodies)}))
                return
            assert events[-1]['status'] == 'published', events
            assert not request.exists(), 'accepted private request retained'
            record = invoke('read', events[-1]['record_id'], '--json')
            assert json.loads(record.stdout)['record']['summary'] == 'SDK_RECAP: alpha completed.'
            assert 'AUTH_SENTINEL_PRIVATE' not in result.stdout + result.stderr + record.stdout
            assert len(bodies) == 3 and all(body['model'] == 'chosen' for body in bodies), bodies
            assert auth == [True, True, True], 'runtime auth not used'
            assert all('SOURCE_SENTINEL' in json.dumps(body['messages']) for body in bodies)
            assert not (agent / 'sessions').exists(), 'backend archived a session'
            for path in root.rglob('*'):
                if path.is_file() and path.name != 'fixture.js':
                    captured = path.read_text(errors='replace')
                    assert 'SOURCE_SENTINEL' not in captured, path
                    assert 'AUTH_SENTINEL_PRIVATE' not in captured, path
            print(json.dumps({'cases': ['installed-sdk-explicit-selection-runtime-auth', 'installed-sdk-virtual-direct-routing', 'no-agent-turn-or-input-archive', 'installed-sdk-cli-runtime-auth-storage-capture-exclusion'], 'requests': len(bodies), 'status': 'PASS'}))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            assert not thread.is_alive(), 'server cleanup failed'
    assert not root.exists(), 'private fixture cleanup failed'

if __name__ == '__main__':
    main()
