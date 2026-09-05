#!/usr/bin/env python3
"""Exercise real Pi --print with auto-compact and a local scripted HTTP backend.

No live credentials/models. Captures are retained at --artifacts. A missing
compaction, continuation, post-compaction write, final output, or clean exit fails.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--extension', type=Path, default=Path.home() / '.pi/agent/extensions/auto-compact/index.ts')
    parser.add_argument('--pi', default=shutil.which('pi'))
    parser.add_argument('--scenario', choices=['inter-turn', 'final-turn', 'summary-error', 'resume-error'], default='inter-turn')
    args = parser.parse_args()
    root = args.artifacts.resolve()
    root.mkdir(parents=True, exist_ok=False)
    agent = root / 'agent'
    agent.mkdir()
    work = root / 'work'
    work.mkdir()
    (work / 'payload.txt').write_text('x' * 12371)
    (agent / 'settings.json').write_text(json.dumps({
        'compaction': {'enabled': False}, 'retry': {'enabled': False},
        'defaultProjectTrust': 'no', 'packages': [],
    }))
    requests = []
    errors = []
    normal_calls = 0
    summary_calls = 0

    class Backend(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            nonlocal normal_calls, summary_calls
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            summary = not body.get('tools')
            requests.append({'summary': summary, 'body': body})
            (root / 'requests.json').write_text(json.dumps(requests, indent=2))
            if summary:
                summary_calls += 1
            else:
                normal_calls += 1
            if (summary and args.scenario == 'summary-error') or (
                not summary and normal_calls > 2 and args.scenario == 'resume-error'
            ):
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': {'message': 'SCRIPTED_FAILURE', 'type': 'invalid_request_error'}}).encode())
                return
            finish = 'stop'
            usage = 1000
            if summary:
                # A real native summarization request, not ctx.compact substitution.
                delta = {'content': 'COMPACTION_PROOF_SUMMARY: Read completed. Next write post-compaction.txt with POST_COMPACTION_ACTION, then say PROOF_DONE.'}
            elif normal_calls == 1:
                usage = 21000
                delta = {'content': 'Retained historical context. ' * 3500}
            elif args.scenario == 'final-turn':
                usage = 123000
                delta = {'content': 'PROOF_DONE'}
            elif normal_calls == 2:
                usage = 120515  # +42 output = the native failure's 120557 tokens
                finish = 'tool_calls'
                delta = {'tool_calls': [{'index': 0, 'id': 'read_payload', 'type': 'function', 'function': {
                    'name': 'read', 'arguments': json.dumps({'path': 'payload.txt'})}}]}
            elif normal_calls == 3:
                # Require the actual extension continuation before doing post-work.
                user_text = '\n'.join(str(m.get('content', '')) for m in body['messages'] if m['role'] == 'user')
                if 'compacted' not in user_text.lower() and 'Continue from where you left off.' not in user_text:
                    errors.append('No continuation in resumed request')
                if args.scenario != 'summary-error' and 'COMPACTION_PROOF_SUMMARY' not in json.dumps(body['messages']):
                    errors.append('No saved summary in resumed context')
                finish = 'tool_calls'
                delta = {'tool_calls': [{'index': 0, 'id': 'write_marker', 'type': 'function', 'function': {
                    'name': 'write', 'arguments': json.dumps({'path': 'post-compaction.txt', 'content': 'POST_COMPACTION_ACTION'})}}]}
            else:
                delta = {'content': 'PROOF_DONE'}
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            chunks = [
                {'choices': [{'index': 0, 'delta': {'role': 'assistant', **delta}, 'finish_reason': None}]},
                {'choices': [{'index': 0, 'delta': {}, 'finish_reason': finish}], 'usage': {
                    'prompt_tokens': usage, 'completion_tokens': 42, 'total_tokens': usage + 42}},
            ]
            try:
                for chunk in chunks:
                    self.wfile.write(('data: ' + json.dumps({'id': 'proof', 'object': 'chat.completion.chunk', 'model': 'scripted', **chunk}) + '\n\n').encode())
                self.wfile.write(b'data: [DONE]\n\n')
            except BrokenPipeError:
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Backend)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    (agent / 'models.json').write_text(json.dumps({'providers': {'proof': {
        'baseUrl': f'http://127.0.0.1:{server.server_port}/v1', 'api': 'openai-completions', 'apiKey': 'dummy-local-only',
        'models': [{'id': 'scripted', 'contextWindow': 272000, 'maxTokens': 16384}],
    }}}))
    command = [args.pi, '--print', '--no-skills', '--no-extensions', '-e', str(args.extension.resolve()),
               '-e', str(HERE / 'observer.ts'), '--model', 'proof/scripted', '--session-dir', str(root / 'sessions'),
               '--system-prompt', 'Follow the scripted task.',
               'Establish historical context.',
               'Read payload.txt, then write post-compaction.txt, then say PROOF_DONE.']
    (root / 'command.json').write_text(json.dumps(command, indent=2))
    env = {**os.environ, 'PI_CODING_AGENT_DIR': str(agent), 'COMPACTION_PROOF_EVENTS': str(root / 'events.jsonl')}
    try:
        result = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True, timeout=45)
        (root / 'stdout').write_text(result.stdout)
        (root / 'stderr').write_text(result.stderr)
    finally:
        server.shutdown()
    sessions = list((root / 'sessions').glob('*.jsonl'))
    entries = [json.loads(line) for path in sessions for line in path.read_text().splitlines()]
    compactions = [e for e in entries if e['type'] == 'compaction']
    events_path = root / 'events.jsonl'
    events = [json.loads(line) for line in events_path.read_text().splitlines()] if events_path.exists() else []
    if args.scenario == 'resume-error':
        if result.returncode == 0 or 'SCRIPTED_FAILURE' not in result.stderr:
            errors.append('Resumed provider failure did not fail closed')
        if len(compactions) != 1 or normal_calls != 3:
            errors.append('Resumed provider failure did not follow completed compaction')
    else:
        if result.returncode != 0:
            errors.append(f'Exit {result.returncode}: {result.stderr}')
        if result.stdout.strip() != 'PROOF_DONE':
            errors.append('Missing final stdout')
        expected = 0 if args.scenario == 'summary-error' else 1
        if len(compactions) != expected:
            errors.append(f'Expected {expected} compactions, got {len(compactions)}')
        if args.scenario == 'final-turn':
            if normal_calls != 2 or (work / 'post-compaction.txt').exists():
                errors.append('Final-turn compaction started spurious work')
        elif not (work / 'post-compaction.txt').exists() or (work / 'post-compaction.txt').read_text() != 'POST_COMPACTION_ACTION':
            errors.append('Missing post-compaction action')
        if args.scenario == 'summary-error' and not any(e['type'] == 'session_compact_failed' for e in events):
            errors.append('No compaction failure event')
    if not events or events[-1]['type'] != 'session_shutdown':
        errors.append('Missing completed shutdown lifecycle')
    if 'Extension error' in result.stderr:
        errors.append('Unexpected extension lifecycle error')
    if args.scenario in ('inter-turn', 'summary-error'):
        continuation_indices = [i for i, e in enumerate(entries) if e.get('message', {}).get('role') == 'user'
                                and ('compacted' in json.dumps(e['message']).lower()
                                     or 'Continue from where you left off.' in json.dumps(e['message']))]
        write_indices = [i for i, e in enumerate(entries) if e.get('message', {}).get('role') == 'toolResult'
                         and e['message'].get('toolName') == 'write']
        if len(continuation_indices) != 1 or len(write_indices) != 1 or continuation_indices[0] >= write_indices[0]:
            errors.append('Native transcript lacks continuation followed by completed write')
        if args.scenario == 'inter-turn' and compactions and continuation_indices:
            if entries.index(compactions[0]) >= continuation_indices[0]:
                errors.append('Continuation preceded saved compaction')
    receipt = {'scenario': args.scenario, 'exit': result.returncode, 'compactions': len(compactions),
               'normal_requests': normal_calls, 'summary_requests': summary_calls, 'errors': errors,
               'artifacts': str(root)}
    (root / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    print(json.dumps(receipt, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
