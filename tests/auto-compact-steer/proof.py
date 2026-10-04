#!/usr/bin/env python3
"""Real Pi TUI proof for auto-compact steering and the prompt-start-race patch.

Drives Pi's TUI in a PTY with real keys against a local scripted
OpenAI-compatible backend. No credentials, no paid calls. Private mode works on
temporary copies of the installed Pi; --installed reruns selected journeys
against the installed Pi; --prepare-package writes a copy for P3.
"""
import argparse
import fcntl
import hashlib
import http.server
import json
import os
from pathlib import Path
import pty
import shutil
import struct
import subprocess
import tempfile
import termios
import threading
import time

try:
    import pyte
except ImportError:  # fail closed: screen assertions need a terminal emulator
    raise SystemExit('FAIL: python module pyte is required (python3 -m pip install --user pyte)')

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PATCHES = ROOT / 'dot_local/share/pi-patches'
PSR = PATCHES / 'prompt-start-race/patch.mjs'
EXT_SOURCE = ROOT / 'dot_pi/private_agent/extensions/auto-compact'
LIVE_EXT = Path.home() / '.pi/agent/extensions/auto-compact'
# Last commit before the auto-compact steer fix; negative controls run its extension.
BASELINE_REF = 'ba1246bdac5474285a90f5ebafb634099b9e91c2'
INSTALLED = Path(os.environ.get('PI_AUTO_COMPACT_STEER_SOURCE_PACKAGE',
    '/Users/cartwmic/.local/share/mise/installs/node/24.18.1/lib/node_modules/@earendil-works/pi-coding-agent'))
CONTINUATION = 'Continue from where you left off.'
SUMMARY_MARK = 'The messages above are a conversation to summarize'
SIBLINGS = {'headless-extension-drain': 'PI_HEADLESS_PATCH_PACKAGE',
            'standing-reminder-origin': 'PI_STANDING_REMINDER_ORIGIN_PACKAGE',
            'settlement-abort': 'PI_SETTLEMENT_ABORT_PACKAGE',
            'prompt-start-race': 'PI_PROMPT_START_RACE_PACKAGE'}


def require(value, message):
    if not value:
        raise RuntimeError('FAIL: ' + message)


def wait(predicate, label, timeout=30):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.03)
    raise RuntimeError('FAIL: watchdog timeout: ' + label)


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(p.get('text', '') for p in content if isinstance(p, dict))
    return ''


class Backend(http.server.ThreadingHTTPServer):
    """Scripted OpenAI-compatible chat completions endpoint.

    script(info) returns a plan: ('text', s, prompt_tokens), ('tool', prompt_tokens),
    ('hold', tag), ('summary',) or ('summary-error',) (held until release('summary')), ('error',).
    """
    daemon_threads = True

    def __init__(self, script):
        self.requests = []
        self.script = script
        self.releases = {}
        backend = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def chunk(self, delta, finish=None, usage=None):
                payload = {'id': 'proof', 'object': 'chat.completion.chunk', 'created': 1, 'model': 'proof',
                           'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                if usage is not None:
                    payload['usage'] = usage
                self.wfile.write(('data: ' + json.dumps(payload) + '\n\n').encode())
                self.wfile.flush()

            def usage(self, prompt_tokens):
                return {'prompt_tokens': prompt_tokens, 'completion_tokens': 5, 'total_tokens': prompt_tokens + 5}

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                messages = body.get('messages', [])
                users = [text_of(m.get('content')) for m in messages if m.get('role') == 'user']
                info = {'index': len(backend.requests), 'body': body, 'users': users,
                        'last_user': users[-1] if users else '',
                        'after_tool': bool(messages) and messages[-1].get('role') == 'tool',
                        'has_tool': any(m.get('role') == 'tool' for m in messages),
                        'summary': SUMMARY_MARK in json.dumps(body), 'cancelled': False, 'completed': False}
                backend.requests.append(info)
                plan = backend.script(info)
                info['plan'] = plan[0]
                if plan[0] in ('summary', 'summary-error'):
                    backend.release_event('summary').wait(60)
                    plan = ('error',) if plan[0] == 'summary-error' else ('text', '## Goal\nProof summary.', 50)
                if plan[0] == 'error':
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(b'{"error":{"message":"scripted summary failure"}}')
                    info['completed'] = True
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.end_headers()
                try:
                    self.chunk({'role': 'assistant'})
                    if plan[0] == 'text':
                        self.chunk({'content': plan[1]})
                        self.chunk({}, 'stop', self.usage(plan[2]))
                    elif plan[0] in ('tool', 'tool-held'):
                        if plan[0] == 'tool-held':
                            backend.release_event(plan[2]).wait(60)
                        self.chunk({'tool_calls': [{'index': 0, 'id': f'call_{info["index"]}', 'type': 'function',
                                                    'function': {'name': 'read', 'arguments': json.dumps({'path': 'note.txt'})}}]})
                        self.chunk({}, 'tool_calls', self.usage(plan[1]))  # ('tool', tokens) or ('tool-held', tokens, event)
                    elif plan[0] == 'hold':
                        self.chunk({'content': 'PARTIAL-' + plan[1]})
                        event = backend.release_event(plan[1])
                        while not event.wait(0.1):
                            self.wfile.write(b': keepalive\n\n')
                            self.wfile.flush()
                        self.chunk({'content': ' DONE-' + plan[1]})
                        self.chunk({}, 'stop', self.usage(100))
                    self.wfile.write(b'data: [DONE]\n\n')
                    self.wfile.flush()
                    info['completed'] = True
                except (BrokenPipeError, ConnectionResetError):
                    info['cancelled'] = True

        super().__init__(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def release_event(self, name):
        return self.releases.setdefault(name, threading.Event())

    def release(self, name):
        self.release_event(name).set()

    def with_user(self, text):
        return [r for r in self.requests if not r['summary'] and r['last_user'] == text]


class Pi:
    """One Pi TUI process in a PTY with an isolated home."""

    def __init__(self, package, directory, script, extensions, race=None):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        agent = directory / 'agent'
        agent.mkdir()
        project = directory / 'project'
        project.mkdir()
        (project / 'note.txt').write_text('proof note\n')
        self.trace_path = directory / 'trace.jsonl'
        self.holds = directory / 'holds'
        self.holds.mkdir()
        self.backend = Backend(script)
        (agent / 'models.json').write_text(json.dumps({'providers': {'proof': {
            'baseUrl': f'http://127.0.0.1:{self.backend.server_port}/v1', 'api': 'openai-completions', 'apiKey': 'dummy-local',
            'models': [{'id': 'proof', 'name': 'Proof', 'reasoning': False, 'input': ['text'],
                        'cost': {'input': 0, 'output': 0, 'cacheRead': 0, 'cacheWrite': 0},
                        'contextWindow': 8192, 'maxTokens': 256}]}}}))
        (agent / 'settings.json').write_text(json.dumps({
            'compaction': {'enabled': False, 'keepRecentTokens': 10, 'reserveTokens': 256},
            'retry': {'enabled': False}}))
        env = {k: v for k, v in os.environ.items() if not any(x in k for x in ['API_KEY', 'TOKEN', 'PI_', 'HERDR_'])}
        env.update(HOME=str(directory), PI_CODING_AGENT_DIR=str(agent), PROOF_TRACE=str(self.trace_path),
                   PROOF_HOLDS=str(self.holds), TERM='xterm-256color', NO_COLOR='1')
        if race:
            env['RACE_SPEC'] = json.dumps(race)
        args = ['node', str(package / 'dist/bundle/cli.js'), '--provider', 'proof', '--model', 'proof',
                '--no-skills', '--no-prompt-templates', '--no-extensions', '--extension', str(HERE / 'fixture.mjs')]
        for extension in extensions:
            args += ['--extension', str(extension)]
        self.screen = pyte.Screen(140, 40)
        self.stream = pyte.Stream(self.screen)
        self.raw = []
        self.lock = threading.Lock()
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 140, 0, 0))
        self.process = subprocess.Popen(args, stdin=slave, stdout=slave, stderr=slave, env=env, cwd=project)
        os.close(slave)
        threading.Thread(target=self._read, daemon=True).start()
        wait(lambda: any(e['kind'] == 'ready' for e in self.trace()), 'TUI session ready', 60)
        time.sleep(0.5)

    def _read(self):
        while True:
            try:
                data = os.read(self.master, 65536)
            except OSError:
                break
            if not data:
                break
            text = data.decode(errors='replace')
            with self.lock:
                self.raw.append(text)
                self.stream.feed(text)

    def trace(self):
        if not self.trace_path.exists():
            return []
        return [json.loads(x) for x in self.trace_path.read_text().splitlines() if x.strip()]

    def screen_text(self):
        with self.lock:
            return '\n'.join(self.screen.display)

    def all_output(self):
        with self.lock:
            return ''.join(self.raw)

    def type(self, text, key=b'\r'):
        for ch in text.encode():
            os.write(self.master, bytes([ch]))
            time.sleep(0.005)
        os.write(self.master, key)

    def key(self, data):
        os.write(self.master, data)

    def release_hold(self, point, text):
        (self.holds / f'{point}-{text}').touch()

    def settled(self):
        return sum(e['kind'] == 'settled' for e in self.trace())

    def sessions(self):
        return '\n'.join(p.read_text() for p in (self.directory / 'agent').rglob('*.jsonl'))

    def close(self):
        artifacts = os.environ.get('PI_AUTO_COMPACT_STEER_ARTIFACTS')
        if artifacts:
            out = Path(artifacts) / self.directory.name
            out.mkdir(parents=True, exist_ok=True)
            (out / 'trace.json').write_text(json.dumps(self.trace(), indent=2))
            (out / 'requests.json').write_text(json.dumps([{k: v for k, v in r.items() if k != 'body'} for r in self.backend.requests], indent=2))
            (out / 'screen.txt').write_text(self.screen_text())
            (out / 'output.txt').write_text(self.all_output())
        for name in list(self.backend.releases):
            self.backend.release(name)
        if self.process.poll() is None:
            self.key(b'\x03')
            time.sleep(0.2)
            self.key(b'\x03')
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        os.close(self.master)
        self.backend.shutdown()
        self.backend.server_close()


def ext_copy(source, directory, threshold=50):
    """Copy the auto-compact extension and give it a private config (continuation on)."""
    target = directory / 'auto-compact'
    target.mkdir(parents=True)
    for name in ['index.ts', 'config.ts', 'events.ts']:
        shutil.copyfile(source / name, target / name)
    (target / 'config.json').write_text(json.dumps({'enabled': True, 'thresholdPercent': threshold,
                                                    'checkAt': ['turn_end', 'agent_end'], 'continuation': CONTINUATION}))
    return target / 'index.ts'


def baseline_ext(directory):
    """auto-compact as committed before this fix (BASELINE_REF), for negative controls."""
    source = directory / 'baseline-src'
    source.mkdir(parents=True)
    for name in ['index.ts', 'config.ts', 'events.ts']:
        blob = subprocess.run(['git', 'show', f'{BASELINE_REF}:dot_pi/private_agent/extensions/auto-compact/{name}'],
                              cwd=ROOT, check=True, capture_output=True).stdout
        (source / name).write_bytes(blob)
    return source


# ---------------------------------------------------------------- compaction journeys

def compaction_script(steer_plan, summary='summary'):
    def script(info):
        if info['summary']:
            return ('summary-error',) if summary == 'error' else ('summary',)
        if info['last_user'] == 'START' and not info['after_tool']:
            return ('tool', 6000)  # above the 50% threshold of the 8192 window
        if info['after_tool']:
            return ('text', 'AFTER-TOOL', 6000)
        if info['last_user'] == CONTINUATION:
            return ('text', 'CONTINUED-OK', 100)
        if info['last_user'].startswith('STEER-'):
            return steer_plan(info['last_user'])
        return ('text', 'OK-' + info['last_user'], 100)
    return script


def compaction_journey(package, directory, ext_source, mode, key=b'\r', summary='summary', esc=False, expect_fixed=True):
    """mode 'steer': queue a message during 'Compacting context...'; mode 'none': queue nothing."""
    steer_text = 'STEER-ALT' if key != b'\r' else 'STEER-ENTER'
    steer_plan = (lambda t: ('hold', 'steer')) if esc else (lambda t: ('text', 'REPLY-' + t, 100))
    pi = Pi(package, directory, compaction_script(steer_plan, summary), [ext_copy(ext_source, directory / 'ext')])
    try:
        pi.type('WARMUP')  # an earlier turn gives compaction something to summarize
        wait(lambda: 'OK-WARMUP' in pi.screen_text(), 'warm-up reply')
        pi.type('START')
        wait(lambda: any(r['summary'] for r in pi.backend.requests), 'compaction summary request')
        wait(lambda: 'Compacting context' in pi.screen_text(), 'Compacting context status visible')
        if mode == 'steer':
            pi.type(steer_text, key)
            wait(lambda: steer_text in pi.screen_text(), 'queued message visible during compaction')
        pi.backend.release('summary')
        if mode == 'none':
            wait(lambda: pi.backend.with_user(CONTINUATION), 'continuation request after compaction')
            wait(lambda: 'CONTINUED-OK' in pi.screen_text(), 'continued run reply rendered')
            print('PASS: AC-3 nothing queued -> continuation resumed', flush=True)
            return
        if not expect_fixed:
            def symptom():
                screen = pi.screen_text()
                return ('Failed to send queued message' in screen or 'already processing a prompt' in screen
                        or bool(pi.backend.with_user(CONTINUATION)))
            wait(symptom, 'baseline symptom (prompt-start error or continuation sent)', 20)
            print(f'PASS: negative control (baseline extension, {package.name} Pi) reproduces the defect', flush=True)
            return
        wait(lambda: pi.backend.with_user(steer_text), 'queued message sent after compaction')
        if esc:
            wait(lambda: 'PARTIAL-steer' in pi.screen_text(), 'held reply streaming')
            request = pi.backend.with_user(steer_text)[-1]
            pi.key(b'\x1b')
            wait(lambda: request['cancelled'], 'backend sees stream cancelled after Esc', 10)
            wait(lambda: 'Working' not in pi.screen_text(), 'working indicator cleared', 10)
            pi.type('AFTER-ESC')
            wait(lambda: 'OK-AFTER-ESC' in pi.screen_text(), 'next prompt completes after Esc')
        else:
            wait(lambda: 'REPLY-' + steer_text in pi.screen_text(), 'queued message reply rendered')
        time.sleep(1.5)  # quiet period: a stray continuation would arrive here
        screen = pi.screen_text()
        require('Failed to send queued message' not in screen, 'queued-message failure shown')
        require('Steering:' not in screen and 'Follow-up:' not in screen, 'queued message still pending on screen')
        require(not pi.backend.with_user(CONTINUATION), 'continuation was sent to the backend')
        require(CONTINUATION not in pi.sessions() and CONTINUATION not in screen, 'continuation appears in the transcript')
        print('PASS:', 'AC-5 failed compaction' if summary == 'error' else 'AC-2 Alt+Enter' if key != b'\r' else 'AC-1 Enter',
              '+ AC-4 Esc' if esc else '', '-> queued message replaced continuation', flush=True)
    finally:
        pi.close()


# ---------------------------------------------------------------- race journeys

def race_journey(package, directory, schedule, loser_mode, expect_fixed=True):
    """Two prompts start together. schedule 'late' holds both in before_agent_start;
    'early' holds the loser in its input handler. loser_mode 'steer' or 'followUp'."""
    if schedule == 'settling':
        return settling_journey(package, directory, expect_fixed)
    if loser_mode == 'steer':
        winner, loser = 'RACE-B', 'RACE-A'  # TUI prompt A (no mode) loses -> default steer
        spec = {'marker': 'RACE-A', 'spawn': {'text': 'RACE-B', 'deliverAs': None}}
    else:
        winner, loser = 'RACE-A', 'RACE-B'  # extension follow-up B loses
        spec = {'marker': 'RACE-A', 'spawn': {'text': 'RACE-B', 'deliverAs': 'followUp'}}
    spec['holdInput'] = [loser] if schedule == 'early' else []
    spec['holdBAS'] = [winner, loser] if schedule == 'late' else []

    def script(info):
        if info['has_tool'] and info['index'] == 1:
            return ('hold', 'final') if loser_mode == 'steer' else ('text', 'FINAL-REPLY', 100)
        if info['last_user'] == winner and not info['has_tool']:
            return ('tool-held', 100, 'first')  # held until the loser is queued
        return ('text', 'OK-' + info['last_user'], 100)

    pi = Pi(package, directory, script, [], race=spec)
    label = f'{schedule}/{loser_mode}'
    try:
        start = pi.settled()
        pi.type('RACE-A')
        if schedule == 'late':
            wait(lambda: {e.get('text') for e in pi.trace() if e['kind'] == 'held' and e['point'] == 'bas'} >= {winner, loser},
                 'both prompts past the early check')
            pi.release_hold('bas', winner)
            wait(lambda: pi.backend.requests and winner in pi.backend.requests[0]['last_user'], 'winner reached backend')
            pi.release_hold('bas', loser)
        else:
            wait(lambda: any(e['kind'] == 'held' and e['point'] == 'input' for e in pi.trace()), 'loser held in input handler')
            wait(lambda: pi.backend.requests and winner in pi.backend.requests[0]['last_user'], 'winner reached backend')
            pi.release_hold('input', loser)
        pending = 'Steering:' if loser_mode == 'steer' else 'Follow-up:'
        if expect_fixed:
            wait(lambda: any(pending in line and loser in line for line in pi.screen_text().splitlines()),
                 f'{label}: loser queued in the running run')
        else:
            time.sleep(1.5)
        pi.backend.release('first')
        if not expect_fixed:
            time.sleep(2.5)
            screen = pi.screen_text()
            errored = 'already processing' in screen.lower() or 'specify streamingbehavior' in screen.lower()
            false_settle = pi.settled() - start >= 1 and not all(r['completed'] or r['cancelled'] for r in pi.backend.requests)
            require(errored or false_settle, f'negative control {label}: no error or false settle on unpatched runtime')
            print(f'PASS: negative control {label} unpatched reproduces race defect', flush=True)
            return
        wait(lambda: len(pi.backend.requests) >= 2, 'request after tool result')
        second = pi.backend.requests[1]
        require(second['has_tool'], 'second request is not the post-tool turn')
        if loser_mode == 'steer':
            require(loser in json.dumps(second['body']), f'{label}: steer loser missing from the request after the tool result')
            wait(lambda: 'PARTIAL-final' in pi.screen_text(), 'final reply streaming')
            require(pi.settled() == start, f'{label}: agent_settled emitted while the winning run streams')
            pi.key(b'\x1b')
            wait(lambda: second['cancelled'], f'{label}: Esc cancelled the stream', 10)
        else:
            require(loser not in json.dumps(second['body']), f'{label}: follow-up loser delivered before the final reply')
            wait(lambda: len(pi.backend.requests) >= 3, 'follow-up request after final reply')
            require(pi.backend.requests[2]['last_user'] == loser, f'{label}: follow-up loser not sent after final reply')
            wait(lambda: 'OK-' + loser in pi.screen_text(), 'follow-up reply rendered')
        wait(lambda: pi.settled() - start >= 1, 'run settled')
        time.sleep(1.0)
        screen = pi.screen_text().lower()
        require('already processing' not in screen and 'specify streamingbehavior' not in screen, f'{label}: error shown')
        require(not any(e['kind'] == 'spawn-error' for e in pi.trace()), f'{label}: extension prompt errored')
        require(pi.settled() - start == 1, f'{label}: expected exactly one agent_settled, got {pi.settled() - start}')
        print(f'PASS: AC-6/AC-9 race {label}: no error, both in one run, one agent_settled,',
              'Esc cancelled' if loser_mode == 'steer' else 'follow-up after final', flush=True)
    finally:
        pi.close()


def settling_journey(package, directory, expect_fixed=True):
    """The loser resumes while the winner's run has ended but its agent_settled
    handlers are still awaited (settlement-abort keeps isStreaming true then).
    The loser must not be queued into the finished run; it runs once settlement ends."""
    spec = {'marker': 'RACE-A', 'spawn': {'text': 'RACE-B', 'deliverAs': None},
            'holdInput': ['RACE-A'], 'holdBAS': [], 'holdSettled': ['1']}
    pi = Pi(package, directory, lambda info: ('text', 'OK-' + info['last_user'], 100), [], race=spec)
    label = 'settling/steer'
    try:
        pi.type('RACE-A')
        wait(lambda: any(e['kind'] == 'held' and e['point'] == 'settled' for e in pi.trace()), 'winner run ended; settlement held')
        require(pi.backend.with_user('RACE-B'), 'winner did not reach the backend')
        pi.release_hold('input', 'RACE-A')
        time.sleep(1.0)
        screen = pi.screen_text().lower()
        if not expect_fixed:
            pi.release_hold('settled', '1')
            time.sleep(2.0)
            screen = pi.screen_text().lower()
            require('specify streamingbehavior' in screen or 'already processing' in screen or not pi.backend.with_user('RACE-A'),
                    f'negative control {label}: loser neither errored nor got stuck')
            print(f'PASS: negative control {label} unpatched reproduces the defect', flush=True)
            return
        require(not pi.backend.with_user('RACE-A'), f'{label}: loser started before settlement finished')
        pi.release_hold('settled', '1')
        wait(lambda: pi.backend.with_user('RACE-A'), f'{label}: loser reached the backend after settlement')
        wait(lambda: 'OK-RACE-A' in pi.screen_text(), f'{label}: loser reply rendered')
        time.sleep(1.0)
        screen = pi.screen_text()
        require('already processing' not in screen.lower() and 'specify streamingbehavior' not in screen.lower(), f'{label}: error shown')
        require('Steering:' not in screen and 'Follow-up:' not in screen, f'{label}: loser stuck in the queue')
        require(pi.settled() == 2, f'{label}: expected one agent_settled per run (2), got {pi.settled()}')
        print(f'PASS: AC-6 race {label}: loser waited for final settlement, then ran; no error, nothing stuck', flush=True)
    finally:
        pi.close()


# ---------------------------------------------------------------- patch mechanics (AC-7)

def fingerprint(package):
    paths = [package / 'dist/core/agent-session.js', package / 'dist/core/extensions/types.d.ts']
    paths += sorted((package / 'dist/bundle/chunks').glob('*.js'))
    return {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def run_patch(name, package, profile='personal', check=False, success=True):
    env = {**os.environ, SIBLINGS[name]: str(package), 'PI_CHEZMOI_PROFILE': profile}
    result = subprocess.run(['node', str(PATCHES / name / 'patch.mjs')] + (['--check'] if check else []),
                            env=env, cwd=ROOT, text=True, capture_output=True)
    require((result.returncode == 0) == success, f'{name} {profile} check={check}: ' + result.stdout + result.stderr)
    return result


def mechanics(root):
    package = root / 'mech'
    shutil.copytree(INSTALLED, package, symlinks=True)
    trigger = (ROOT / 'run_onchange_after_30_apply_pi_patches.sh.tmpl').read_text()
    require(trigger.count('include "dot_local/share/pi-patches/prompt-start-race/patch.mjs" | sha256sum') == 1,
            'onchange script must hash prompt-start-race exactly once')
    run_patch('prompt-start-race', package, 'termux')
    baseline = fingerprint(package)
    run_patch('prompt-start-race', package, check=True, success=False)
    # normal helper over a private patch root (only patches with a package override)
    patches = root / 'patches'
    patches.mkdir()
    for name in SIBLINGS:
        shutil.copytree(PATCHES / name, patches / name)
    helper_env = {**os.environ, 'HOME': str(root / 'helper-home'), 'PI_PATCHES_ROOT': str(patches), 'PI_CHEZMOI_PROFILE': 'personal',
                  **{var: str(package) for var in SIBLINGS.values()}}
    subprocess.run(['sh', str(ROOT / 'dot_local/user_scripts/executable_apply_pi_patches.sh')], env=helper_env, cwd=ROOT, check=True, capture_output=True)
    run_patch('prompt-start-race', package, check=True)
    patched = fingerprint(package)
    require(patched != baseline, 'helper did not apply prompt-start-race')
    subprocess.run(['sh', str(ROOT / 'dot_local/user_scripts/executable_apply_pi_patches.sh')], env=helper_env, cwd=ROOT, check=True, capture_output=True)
    require(fingerprint(package) == patched, 're-apply changed files')
    require(not (root / 'helper-home/.local/state/chezmoi-pi-patches').exists(), 'private helper wrote receipts')
    for name in SIBLINGS:
        run_patch(name, package, check=True)
    print('PASS: AC-7 helper apply, --check, idempotent re-apply, all siblings --check', flush=True)
    run_patch('prompt-start-race', package, 'termux')
    run_patch('prompt-start-race', package, 'termux', check=True)
    require(fingerprint(package) == baseline, 'disabled profile reversal not exact')
    for name in ['headless-extension-drain', 'standing-reminder-origin', 'settlement-abort']:
        run_patch(name, package, check=True)
    print('PASS: AC-7 disabled profile exact reversal, siblings intact', flush=True)
    target = package / 'dist/core/agent-session.js'
    saved = target.read_text()
    anchor = '        const normalized = await this._normalizePromptImages(currentImages);\n'
    for mutated in [saved.replace(anchor, '/* moved */\n'), saved.replace(anchor, anchor + anchor)]:
        target.write_text(mutated)
        before = fingerprint(package)
        run_patch('prompt-start-race', package, success=False)
        require(fingerprint(package) == before, 'anchor refusal wrote files')
    target.write_text(saved)
    print('PASS: AC-7 missing/ambiguous anchor refusal without writes', flush=True)
    # order: settlement-abort before and after prompt-start-race
    run_patch('settlement-abort', package, 'termux')
    run_patch('prompt-start-race', package)
    run_patch('settlement-abort', package)
    order_a = fingerprint(package)
    run_patch('settlement-abort', package, 'termux')
    run_patch('prompt-start-race', package, 'termux')
    run_patch('settlement-abort', package)
    run_patch('prompt-start-race', package)
    require(fingerprint(package) == order_a == patched, 'application order changes the result')
    run_patch('settlement-abort', package, check=True)
    run_patch('prompt-start-race', package, check=True)
    print('PASS: AC-7 both application orders identical; settlement-abort --check passes', flush=True)


# ---------------------------------------------------------------- driver

def private_packages(root):
    patched = root / 'patched'
    shutil.copytree(INSTALLED, patched, symlinks=True)
    run_patch('prompt-start-race', patched)
    run_patch('prompt-start-race', patched, check=True)
    unpatched = root / 'unpatched'
    shutil.copytree(INSTALLED, unpatched, symlinks=True)
    run_patch('prompt-start-race', unpatched, 'termux')
    return patched, unpatched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--installed', action='store_true', help='run journeys against the installed Pi and live extension')
    parser.add_argument('--journeys', default='', help='comma list for --installed, e.g. AC-1,AC-4')
    parser.add_argument('--prepare-package', help='write a private Pi copy with prompt-start-race applied (settlement-abort reversed)')
    args = parser.parse_args()
    version = json.loads((INSTALLED / 'package.json').read_text())['version']
    require(version == '1.0.0', f'requires Pi 1.0.0, found {version}')
    original = fingerprint(INSTALLED)
    print('IDENTITY:', INSTALLED, 'Pi', version, flush=True)

    if args.prepare_package:
        target = Path(args.prepare_package)
        require(target.is_absolute() and str(target).startswith('/tmp/'), 'prepare target must be an absolute /tmp path')
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(INSTALLED, target, symlinks=True)
        run_patch('settlement-abort', target, 'termux')
        run_patch('prompt-start-race', target)
        run_patch('prompt-start-race', target, check=True)
        print('PASS: prepared', target, 'with prompt-start-race applied, settlement-abort reversed', flush=True)
        return

    with tempfile.TemporaryDirectory(prefix='auto-compact-steer-') as temp:
        root = Path(temp)
        if args.installed:
            wanted = set(filter(None, args.journeys.split(','))) or {'AC-1', 'AC-4'}
            require(wanted <= {'AC-1', 'AC-4'}, 'installed mode supports AC-1 and AC-4')
            require(LIVE_EXT.exists(), f'live extension missing: {LIVE_EXT}')
            if 'AC-1' in wanted:
                compaction_journey(INSTALLED, root / 'installed-ac1', LIVE_EXT, 'steer')
            if 'AC-4' in wanted:
                compaction_journey(INSTALLED, root / 'installed-ac4', LIVE_EXT, 'steer', esc=True)
            print('PASS: installed journeys', ','.join(sorted(wanted)), flush=True)
        else:
            patched, unpatched = private_packages(root)
            baseline = baseline_ext(root)
            compaction_journey(unpatched, root / 'neg-ac1', baseline, 'steer', expect_fixed=False)
            compaction_journey(patched, root / 'neg-ac1-patched', baseline, 'steer', expect_fixed=False)  # patch alone still sends the continuation
            race_journey(unpatched, root / 'neg-early', 'early', 'steer', expect_fixed=False)
            race_journey(unpatched, root / 'neg-late', 'late', 'steer', expect_fixed=False)
            race_journey(unpatched, root / 'neg-settling', 'settling', 'steer', expect_fixed=False)
            compaction_journey(patched, root / 'ac1', EXT_SOURCE, 'steer')
            compaction_journey(patched, root / 'ac2', EXT_SOURCE, 'steer', key=b'\x1b\r')
            compaction_journey(patched, root / 'ac3', EXT_SOURCE, 'none')
            compaction_journey(patched, root / 'ac4', EXT_SOURCE, 'steer', esc=True)
            compaction_journey(patched, root / 'ac5', EXT_SOURCE, 'steer', summary='error')
            for schedule in ['late', 'early']:
                for mode in ['steer', 'followUp']:
                    race_journey(patched, root / f'race-{schedule}-{mode}', schedule, mode)
            race_journey(patched, root / 'race-settling', 'settling', 'steer')
            mechanics(root)
    require(fingerprint(INSTALLED) == original, 'installed package changed')
    print('PASS: installed runtime unchanged', flush=True)


if __name__ == '__main__':
    main()
