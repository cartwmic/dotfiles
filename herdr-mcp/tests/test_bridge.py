#!/usr/bin/env python3
"""Bridge tests. Fake Herdr socket and fake herdr executable in a temp HOME only.

Black-box tests drive the deployed entry point (the child wrapper) over stdio
MCP, as tunnel-client does. Transport edge cases call generic_request directly.
Run: /usr/bin/python3 -B -m unittest discover -s herdr-mcp/tests -v
"""
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bridge', SRC / 'herdr_control_mcp.py')
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
bridge.SOCK = '/nonexistent-herdr-test.sock'  # in-process tests never reach a real Herdr server

DECOYS = {'CONTROL_PLANE_API_KEY': 'FAKE-KEY', 'OPENAI_API_KEY': 'FAKE-D', 'AWS_SECRET_ACCESS_KEY': 'FAKE-D',
          'CLOUDFLARED_TOKEN': 'FAKE-D', 'MCP_COMMAND': 'FAKE-D', 'GITHUB_TOKEN': 'FAKE-D'}
FAKE_HERDR = '#!/bin/sh\n' \
    'if [ "$1" = "--version" ]; then echo "herdr 0.9.1"; exit 0; fi\n' \
    'if [ "$1" = "status" ]; then exec /bin/sleep 30; fi\n' \
    'for a in "$@"; do printf "ARG<%s>\\n" "$a"; done\n' \
    'env | sed -n "s/=.*//p" | sort | sed "s/^/ENV /"\n' \
    'pwd | sed "s/^/CWD /"\n' \
    'if [ "$2" = "fail" ]; then echo nope >&2; exit 3; fi\n'
BACKTICK = chr(96)


class FakeHerdr:
    """Unix socket server answering one JSON line per connection."""
    def __init__(self, path, responder):
        self.path, self.responder, self.seen = path, responder, []
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(path)
        self.sock.listen(8)
        self.sock.settimeout(.2)
        self.stop = False
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        while not self.stop:
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with conn:
                raw = b''
                while not raw.endswith(b'\n'):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
                request = json.loads(raw)
                self.seen.append(request)
                reply = self.responder(request)
                if reply is not None:
                    conn.sendall((json.dumps(reply) + '\n').encode())

    def close(self):
        self.stop = True
        self.thread.join(2)
        self.sock.close()


def herdr_responder(request):
    method, params = request['method'], request['params']
    if method == 'ping':
        return {'id': request['id'], 'result': {'version': '0.9.1', 'protocol': 22}}
    if method in ('pane.read', 'pane.send_input', 'agent.prompt', 'pane.send_text'):
        return {'id': request['id'], 'result': {'echo': params}}
    if method == 'agent.list':
        return {'id': request['id'], 'result': {'agents': [{'agent_session': {'value': '/private/store', 'kind': 'pi'}}]}}
    if method == 'hang':
        time.sleep(.6)
        return None
    return {'id': request['id'], 'error': {'code': 'unknown_method', 'message': method, 'data': {'n': [1]}}}


class StdioBridgeTests(unittest.TestCase):
    """Drive the wrapper exactly as tunnel-client does: newline JSON-RPC on stdio."""

    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp(prefix='hmb-', dir='/tmp')).resolve()
        (self.home / '.config' / 'herdr').mkdir(parents=True)
        share = self.home / '.local' / 'share' / 'herdr-mcp'
        share.mkdir(parents=True)
        shutil.copy(SRC / 'herdr_control_mcp.py', share / 'herdr_control_mcp.py')
        shutil.copy(SRC / 'herdr_control_mcp_child.sh', share / 'herdr_control_mcp_child.sh')
        os.chmod(share / 'herdr_control_mcp_child.sh', 0o755)
        self.server = FakeHerdr(str(self.home / '.config' / 'herdr' / 'herdr.sock'), herdr_responder)
        self.proc = subprocess.Popen([str(share / 'herdr_control_mcp_child.sh')], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     env={'HOME': str(self.home), 'PATH': '/usr/bin:/bin', **DECOYS})
        self.next_id = 0

    def tearDown(self):
        self.proc.stdin.close()
        self.assertEqual(self.proc.wait(10), 0)
        self.proc.stdout.close()
        self.proc.stderr.close()
        self.server.close()
        shutil.rmtree(self.home)

    def rpc(self, method, params=None):
        self.next_id += 1
        self.proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': self.next_id, 'method': method,
                                          'params': params or {}}) + '\n')
        self.proc.stdin.flush()
        reply = json.loads(self.proc.stdout.readline())
        self.assertEqual(reply['id'], self.next_id)
        return reply

    def call(self, name, arguments):
        return self.rpc('tools/call', {'name': name, 'arguments': arguments})['result']

    def configure_herdr(self, pin=None):
        exe = self.home / 'herdr'
        exe.write_text(FAKE_HERDR)
        os.chmod(exe, 0o755)
        digest = pin or hashlib.sha256(exe.read_bytes()).hexdigest()
        cfg = self.home / '.config' / 'herdr-mcp'
        cfg.mkdir(exist_ok=True)
        (cfg / 'config').write_text(f'tunnel_id=tunnel_test\nherdr_exe={exe}\nherdr_sha256={digest}\n')

    def test_initialize_and_seven_tools(self):
        init = self.rpc('initialize', {'protocolVersion': '2025-06-18'})['result']
        self.assertEqual(init['serverInfo']['name'], 'herdr-control')
        tools = {t['name']: t for t in self.rpc('tools/list')['result']['tools']}
        self.assertEqual(sorted(tools), sorted(['herdr_status', 'herdr_snapshot', 'herdr_list', 'herdr_get',
                                                'herdr_read', 'herdr_request', 'herdr_cli']))
        for name in ('herdr_request', 'herdr_cli'):
            self.assertFalse(tools[name]['annotations']['idempotentHint'])
            self.assertIn('NEVER automatically retry', tools[name]['description'])
        self.assertEqual(self.rpc('no/such')['error']['code'], -32601)

    def test_reads_status_redaction_and_line_cap(self):
        status = json.loads(self.call('herdr_status', {})['content'][0]['text'])
        self.assertEqual(status['protocol'], 22)
        agents = self.call('herdr_list', {'kind': 'agent'})['content'][0]['text']
        self.assertNotIn('/private/store', agents)
        read = json.loads(self.call('herdr_read', {'pane_id': 'w1:p1', 'lines': 200})['content'][0]['text'])
        self.assertEqual(read['echo']['lines'], 200)
        self.assertEqual([r['method'] for r in self.server.seen], ['ping', 'agent.list', 'pane.read'])

    def test_read_source_matches_herdr_enum(self):
        tools = {t['name']: t for t in self.rpc('tools/list')['result']['tools']}
        self.assertEqual(tools['herdr_read']['inputSchema']['properties']['source']['enum'],
                         ['visible', 'recent', 'recent_unwrapped', 'detection'])
        for given in ('recent_unwrapped', 'recent-unwrapped'):
            self.call('herdr_read', {'pane_id': 'w1:p1', 'source': given})
        self.call('herdr_read', {'pane_id': 'w1:p1'})
        self.assertEqual([r['params']['source'] for r in self.server.seen],
                         ['recent_unwrapped', 'recent_unwrapped', 'recent'])

    def test_request_literal_payload_native_error_and_unknown(self):
        text = '$(do-not-execute); ' + BACKTICK + 'literal' + BACKTICK + '\nsecond'
        ok = self.call('herdr_request', {'method': 'pane.send_input', 'params': {'pane_id': 'w1:p1', 'text': text}})
        self.assertFalse(ok['isError'])
        self.assertEqual(json.loads(ok['content'][0]['text'])['response']['result']['echo']['text'], text)
        err = self.call('herdr_request', {'method': 'bogus.method', 'params': {}})
        self.assertTrue(err['isError'])
        self.assertEqual(json.loads(err['content'][0]['text'])['response']['error']['data'], {'n': [1]})
        hang = self.call('herdr_request', {'method': 'hang', 'params': {}, 'timeout_ms': 300})
        self.assertEqual(json.loads(hang['content'][0]['text'])['outcome'], 'unknown')
        time.sleep(.5)
        # Exactly one socket request per call: never replayed.
        self.assertEqual([r['method'] for r in self.server.seen], ['pane.send_input', 'bogus.method', 'hang'])

    def test_cli_unconfigured_refuses(self):
        out = self.call('herdr_cli', {'argv': ['--version']})
        self.assertTrue(out['isError'])
        self.assertIn('not configured', out['content'][0]['text'])

    def test_cli_argv_literal_env_scrubbed_cwd_home(self):
        self.configure_herdr()
        out = self.call('herdr_cli', {'argv': ['pane', 'list', '$(id)', 'a b;c']})
        data = json.loads(out['content'][0]['text'])
        self.assertFalse(out['isError'], data)
        self.assertEqual(data['exit_code'], 0)
        self.assertIn('ARG<$(id)>\nARG<a b;c>', data['stdout'])
        envs = {l[4:] for l in data['stdout'].splitlines() if l.startswith('ENV ')}
        self.assertFalse(envs & set(DECOYS), envs)
        self.assertLessEqual(envs - {'PWD', 'SHLVL', '_', 'OLDPWD'}, {'HOME', 'PATH', 'TERM', 'NO_COLOR'})
        self.assertIn(f'CWD {self.home}', data['stdout'])
        fail = self.call('herdr_cli', {'argv': ['pane', 'fail']})
        self.assertTrue(fail['isError'])
        self.assertEqual(json.loads(fail['content'][0]['text'])['exit_code'], 3)

    def test_cli_pin_mismatch_and_interactive_refused(self):
        self.configure_herdr(pin='0' * 64)
        self.assertIn('hash mismatch', self.call('herdr_cli', {'argv': ['--version']})['content'][0]['text'])
        self.configure_herdr()
        for argv in ([], ['server'], ['--session', 'x'], ['agent', 'attach', 'x'], ['tab', '--remote=h'], ['--handoff']):
            out = self.call('herdr_cli', {'argv': argv})
            self.assertTrue(out['isError'], argv)
            # Refused before launch: a plain error, not a process result.
            self.assertTrue(out['content'][0]['text'].startswith('error: '), out)
            self.assertNotIn('exit_code', out['content'][0]['text'])

    def test_cli_timeout_unknown_not_retried(self):
        self.configure_herdr()
        started = time.monotonic()
        out = self.call('herdr_cli', {'argv': ['status'], 'timeout_ms': 300})
        data = json.loads(out['content'][0]['text'])
        self.assertTrue(out['isError'])
        self.assertEqual(data['outcome'], 'unknown_after_timeout')
        self.assertLess(time.monotonic() - started, 5)
        self.assertNotEqual(subprocess.run(['/bin/kill', '-0', str(data['pid'])], capture_output=True).returncode, 0)


class TransportTests(unittest.TestCase):
    """generic_request edge cases against a one-shot socket."""

    def exchange(self, responder, method='pane.send_input', params=None):
        with tempfile.TemporaryDirectory(prefix='hmc-', dir='/tmp') as directory:
            old = bridge.SOCK
            bridge.SOCK = directory + '/s'
            server = FakeHerdr(bridge.SOCK, responder)
            try:
                result = bridge.generic_request({'method': method, 'params': params or {}, 'timeout_ms': 1000})
                time.sleep(.3)
                self.assertEqual(len(server.seen), 1)
                return json.loads(result['content'][0]['text'])
            finally:
                bridge.SOCK = old
                server.close()

    def test_eof_unknown(self):
        self.assertEqual(self.exchange(lambda r: None)['outcome'], 'unknown')

    def test_parser_empty_id(self):
        error = {'code': 'invalid_request', 'message': 'unknown variant'}
        self.assertEqual(self.exchange(lambda r: {'id': '', 'error': error})['response']['error'], error)

    def test_wrong_id_unknown(self):
        self.assertEqual(self.exchange(lambda r: {'id': 'wrong', 'result': {}})['outcome'], 'unknown')

    def test_preconnect_failure_not_sent(self):
        old = bridge.SOCK
        try:
            bridge.SOCK = '/nonexistent-herdr-test.sock'
            out = bridge.generic_request({'method': 'ping', 'params': {}})
            self.assertEqual(json.loads(out['content'][0]['text'])['outcome'], 'not_sent')
        finally:
            bridge.SOCK = old

    def test_validation(self):
        for args in ({}, {'method': 'ping', 'params': {}, 'timeout_ms': True},
                     {'method': 'ping', 'params': {}, 'socket': '/other'}):
            with self.assertRaises(ValueError):
                bridge.generic_request(args)


class AuditTests(StdioBridgeTests):
    """Metadata-only audit log, driven through the wrapper over stdio."""

    def records(self):
        path = self.home / '.local' / 'state' / 'herdr-mcp' / 'audit.log'
        return path, [json.loads(l) for l in path.read_text().splitlines()]

    def test_audit_records_metadata_only(self):
        self.configure_herdr()
        secret = 'SECRET-PAYLOAD-' + BACKTICK + 'rm -rf' + BACKTICK
        self.call('herdr_status', {})
        self.call('herdr_read', {'pane_id': 'w15:p2R', 'lines': 5})
        self.call('herdr_request', {'method': 'pane.send_input', 'params': {'pane_id': 'w1:p1', 'text': secret}})
        self.call('herdr_request', {'method': 'bogus.method', 'params': {'note': secret}})
        self.call('herdr_request', {'method': 'hang', 'params': {}, 'timeout_ms': 300})
        self.call('herdr_cli', {'argv': ['pane', 'send-text', 'w2:p3', secret, 'w1Hunter2', 'mysecretword']})
        self.call('herdr_request', {'method': 'leaked.password.value', 'params': {'id': 'w9Passwd'}})
        self.call('herdr_cli', {'argv': ['server']})
        self.call('herdr_get', {'kind': 'agent', 'id': 'free text name ' + secret})
        self.call('no_such_tool', {'x': secret})
        path, recs = self.records()
        text = path.read_text()
        for leaked in ('SECRET-PAYLOAD', 'rm -rf', 'free text', '/private/store', 'ARG<', 'ENV ', 'Hunter',
                       'mysecretword', 'leaked', 'Passwd', 'bogus'):
            self.assertNotIn(leaked, text)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        starts = [r for r in recs if r['event'] == 'start']
        ends = [r for r in recs if r['event'] == 'end']
        self.assertEqual(len(starts), 10)
        self.assertEqual([r['call'] for r in starts], [r['call'] for r in ends])
        allowed = {'ts', 'event', 'call', 'tool', 'method', 'sub', 'targets', 'text_hash', 'text_len', 'mcp_id', 'outcome',
                   'duration_ms', 'exit_code', 'error_code', 'request_id', 'transport_error'}
        for r in recs:
            self.assertLessEqual(set(r), allowed, r)
            self.assertRegex(r['ts'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$')
            self.assertIsInstance(r['mcp_id'], int)
        summary = [(r['tool'], r['method'], r['targets'], r['outcome']) for r in ends]
        self.assertEqual(summary, [
            ('herdr_status', 'ping', [], 'ok'),
            ('herdr_read', 'pane.read', ['w15:p2R'], 'ok'),
            ('herdr_request', 'pane.send_input', ['w1:p1'], 'ok'),
            ('herdr_request', 'unlisted', [], 'error'),
            ('herdr_request', 'unlisted', [], 'unknown'),
            ('herdr_cli', 'cli:pane', ['w2:p3'], 'ok'),
            ('herdr_request', 'unlisted', [], 'error'),
            ('herdr_cli', 'cli:server', [], 'rejected'),
            ('herdr_get', 'agent.get', [], 'error'),
            ('unknown_tool', 'none', [], 'rejected')])
        self.assertEqual(ends[3]['error_code'], 'unknown_method')
        self.assertEqual(ends[5]['exit_code'], 0)
        self.assertEqual(ends[4]['transport_error'], 'timeout')
        self.assertRegex(ends[4]['request_id'], r'^[0-9a-f-]{36}$')
        self.assertTrue(all(isinstance(r['duration_ms'], int) and r['duration_ms'] >= 0 for r in ends))


class SendLedgerTests(StdioBridgeTests):
    """Text sends log an HMAC of the text and the real CLI subcommand, never the text."""

    def records(self):
        path = self.home / '.local' / 'state' / 'herdr-mcp' / 'audit.log'
        return path, [json.loads(l) for l in path.read_text().splitlines()]

    def key(self):
        return (self.home / '.local' / 'state' / 'herdr-mcp' / 'text-hash.key').read_bytes()

    def expected(self, text):
        import hmac
        norm = text.replace('\r\n', '\n').strip()
        return 'h1:' + hmac.new(self.key(), norm.encode(), hashlib.sha256).hexdigest()[:32]

    def test_sends_record_hash_length_and_subcommand_only(self):
        self.configure_herdr()
        msg = 'PRIVATE-MESSAGE-7 please deploy ' + BACKTICK + 'x' + BACKTICK
        self.call('herdr_request', {'method': 'agent.prompt', 'params': {'target': 'w1:p1', 'text': msg}})
        self.call('herdr_cli', {'argv': ['agent', 'prompt', '--wait', '--timeout', '5000', 'w1:p1', msg]})
        self.call('herdr_cli', {'argv': ['--session', 'dev', 'pane', 'send-text', 'w1:p1', msg + '\r\n']})
        self.call('herdr_request', {'method': 'pane.send_text', 'params': {'pane_id': 'w1:p1', 'text': msg}})
        self.call('herdr_request', {'method': 'pane.send_input', 'params': {'pane_id': 'w1:p1', 'text': msg, 'keys': ['Enter']}})
        self.call('herdr_cli', {'argv': ['pane', 'run', 'w1:p1', 'echo', 'hi']})
        self.call('herdr_cli', {'argv': ['pane', 'send-keys', 'w1:p1', 'Enter']})
        self.call('herdr_cli', {'argv': ['pane', 'bogus-sub', 'w1:p1', msg]})
        self.call('herdr_request', {'method': 'pane.send_keys', 'params': {'pane_id': 'w1:p1', 'keys': ['h', 'i']}})
        self.call('herdr_read', {'pane_id': 'w1:p1'})
        path, recs = self.records()
        self.assertNotIn('PRIVATE-MESSAGE', path.read_text())
        self.assertNotIn('echo', path.read_text())
        key = path.parent / 'text-hash.key'
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(key.read_bytes()), 32)
        ends = [r for r in recs if r['event'] == 'end']
        starts = [r for r in recs if r['event'] == 'start']
        h = self.expected(msg)
        self.assertRegex(h, r'^h1:[0-9a-f]{32}\Z')
        # start and end carry the same fields, so a call the bridge never finished is still hashed
        for s, e in zip(starts, ends):
            self.assertEqual({k: s.get(k) for k in ('sub', 'text_hash', 'text_len')}, {k: e.get(k) for k in ('sub', 'text_hash', 'text_len')})
        got = [(r['method'], r.get('sub'), r.get('text_hash'), r.get('text_len')) for r in ends]
        n = len(msg)
        self.assertEqual(got, [
            ('agent.prompt', None, h, n),
            ('cli:agent', 'prompt', h, n),
            ('cli:pane', 'send-text', h, n),          # --session prefix skipped, CRLF/whitespace normalized
            ('pane.send_text', None, h, n),
            ('pane.send_input', None, h, n),
            ('cli:pane', 'run', self.expected('echo hi'), 7),
            ('cli:pane', 'send-keys', None, None),   # keys are not message text
            ('cli:pane', None, None, None),          # unknown subcommand word is never logged
            ('pane.send_keys', None, None, None),
            ('pane.read', None, None, None)])

    def test_refused_send_is_still_hashed_and_blank_text_is_not(self):
        self.call('herdr_cli', {'argv': ['agent', 'prompt', 'w1:p1', 'unconfigured']})  # herdr_cli not configured: rejected
        self.call('herdr_request', {'method': 'pane.send_text', 'params': {'pane_id': 'w1:p1', 'text': '  \n '}})
        _path, recs = self.records()
        ends = [r for r in recs if r['event'] == 'end']
        self.assertEqual((ends[0]['outcome'], ends[0]['text_hash'], ends[0]['sub']), ('rejected', self.expected('unconfigured'), 'prompt'))
        self.assertNotIn('text_hash', ends[1])

    def test_unwritable_key_never_blocks_the_send(self):
        state = self.home / '.local' / 'state' / 'herdr-mcp'
        state.mkdir(parents=True, mode=0o700)
        (state / 'text-hash.key').symlink_to('/nonexistent-target')
        out = self.call('herdr_request', {'method': 'agent.prompt', 'params': {'target': 'w1:p1', 'text': 'hello'}})
        self.assertFalse(out.get('isError'))
        _path, recs = self.records()
        self.assertTrue(recs and all('text_hash' not in r for r in recs))

    def test_cli_command_parsing(self):
        cc = bridge.cli_command
        self.assertEqual(cc(['--machine', 'm', '--session=s', 'agent', 'prompt', 'a', 'b']), ('agent', 'prompt', ['a', 'b']))
        self.assertEqual(cc(['pane', 'nope', 'x']), ('pane', None, ['nope', 'x']))
        self.assertEqual(cc(['--version']), (None, None, []))
        self.assertEqual(cc(['bogus', 'list']), (None, None, []))
        self.assertEqual(bridge.cli_positionals(['--wait', '--until', 'idle', 'w1:p1', '--', '-dash text']), ['w1:p1', '-dash text'])


class SendReportTests(StdioBridgeTests):
    """The report, run as installed (python -I -B), against a real bridge log and fake Pi sessions."""

    def setUp(self):
        super().setUp()
        share = self.home / '.local' / 'share' / 'herdr-mcp'
        shutil.copy(SRC / 'herdr_send_report.py', share / 'herdr_send_report.py')
        self.report_path = share / 'herdr_send_report.py'
        self.sessions = self.home / '.pi' / 'agent' / 'sessions' / '--proj--'
        self.sessions.mkdir(parents=True)

    def user_entry(self, content, offset=0.5):
        ts = time.time() + offset
        iso = time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(ts)) + '.000Z'
        return json.dumps({'type': 'message', 'timestamp': iso,
                           'message': {'role': 'user', 'content': content, 'timestamp': int(ts * 1000)}})

    def run_report(self, *args):
        return subprocess.run(['/usr/bin/python3', '-I', '-B', str(self.report_path), *args],
                              env={'HOME': str(self.home), 'PATH': '/usr/bin:/bin'}, capture_output=True, text=True)

    def report(self, *args, expect=0):
        r = self.run_report('--json', *args)
        self.assertEqual(r.returncode, expect, r.stderr)
        return json.loads(r.stdout) if expect == 0 else r

    def test_lists_only_sends_without_a_landing(self):
        self.configure_herdr()
        sent = {'landed': 'first PRIVATE-A', 'blocks': 'second PRIVATE-B\nline two', 'lost': 'third PRIVATE-C',
                'dup': 'again PRIVATE-D'}
        self.call('herdr_request', {'method': 'agent.prompt', 'params': {'target': 'w1:p1', 'text': sent['landed']}})
        self.call('herdr_request', {'method': 'pane.send_text', 'params': {'pane_id': 'w2:p1', 'text': sent['blocks'] + '\r\n'}})
        self.call('herdr_cli', {'argv': ['agent', 'prompt', 'w3:p1', sent['lost']]})
        self.call('herdr_request', {'method': 'agent.prompt', 'params': {'target': 'w4:p1', 'text': sent['dup']}})
        self.call('herdr_request', {'method': 'agent.prompt', 'params': {'target': 'w4:p1', 'text': sent['dup']}})
        self.call('herdr_cli', {'argv': ['pane', 'run', 'w5:p1', 'ls']})
        self.call('herdr_read', {'pane_id': 'w1:p1'})
        self.call('herdr_cli', {'argv': ['agent', 'prompt', 'w9:p9', 'never lands']})  # runs fine, but nothing lands
        (self.sessions / 'a.jsonl').write_text('\n'.join([
            self.user_entry(sent['landed']),
            self.user_entry([{'type': 'text', 'text': sent['blocks']}]),
            self.user_entry(sent['dup']),                       # one landing for two identical sends
            self.user_entry('something else entirely'),
            json.dumps({'type': 'message', 'timestamp': '2026-01-01T00:00:00.000Z',
                        'message': {'role': 'assistant', 'content': sent['lost'], 'timestamp': 1}})]) + '\n')
        out = self.report('--window', '1')
        deadline = time.time() + 6
        while out['summary']['counts'].get('pending') and time.time() < deadline:
            time.sleep(.3)
            out = self.report('--window', '1')
        self.assertEqual(out['summary']['counts'], {'landed': 3, 'unmatched': 3})
        self.assertEqual(out['summary']['shell_runs_not_checked'], 1)
        self.assertEqual([(s['kind'], s['method'], s['targets']) for s in out['unmatched']],
                         [('prompt', 'cli:agent', ['w3:p1']), ('prompt', 'agent.prompt', ['w4:p1']), ('prompt', 'cli:agent', ['w9:p9'])])
        self.assertEqual(out['unmatched'][0]['len'], len(sent['lost']))
        raw = self.run_report('--window', '1').stdout
        self.assertIn('Unmatched sends', raw)
        self.assertNotIn('PRIVATE', raw)
        self.assertNotIn('PRIVATE', json.dumps(out))
        self.assertEqual(self.report('--target', 'w3:p1', '--window', '1')['summary']['sends_checked'], 1)

    def test_landing_outside_the_window_and_pending(self):
        self.call('herdr_request', {'method': 'agent.prompt', 'params': {'target': 'w1:p1', 'text': 'late message'}})
        (self.sessions / 'a.jsonl').write_text(self.user_entry('late message', offset=60) + '\n')
        self.assertEqual(self.report('--window', '0')['summary']['counts'], {'unmatched': 1})
        self.assertEqual(self.report('--window', '600')['summary']['counts'], {'landed': 1})
        (self.sessions / 'a.jsonl').write_text('')
        self.assertEqual(self.report('--window', '600')['summary']['counts'], {'pending': 1})

    def test_unhashed_sends_and_missing_key(self):
        r = self.report(expect=2)  # no send yet: the bridge has not created the key
        self.assertIn('no text-hash key', r.stderr)
        self.call('herdr_request', {'method': 'agent.prompt', 'params': {'target': 'w1:p1', 'text': 'x' * 10}})
        path = self.home / '.local' / 'state' / 'herdr-mcp' / 'audit.log'
        old = {'ts': '2026-10-20T00:00:00.000Z', 'event': 'end', 'call': 'old1', 'tool': 'herdr_request', 'method': 'agent.prompt',
               'targets': [], 'outcome': 'ok', 'duration_ms': 1}
        with open(path, 'a') as handle:
            handle.write(json.dumps(old) + '\n')
        out = self.report('--since', '2026-10-19T00:00:00Z', '--window', '1')
        self.assertEqual(out['summary']['sends_without_hash'], 1)
        (self.home / '.local' / 'state' / 'herdr-mcp' / 'text-hash.key').unlink()
        self.report(expect=2)


class KnownMethodsTests(unittest.TestCase):
    """KNOWN_METHODS must equal the structurally extracted request methods, exactly."""
    FIXTURE = pathlib.Path(__file__).resolve().parent / 'fixtures' / 'herdr-0.9.1-request-methods.json'

    def test_known_methods_equal_fixture(self):
        fixture = json.loads(self.FIXTURE.read_text())
        self.assertEqual(fixture['count'], 103)
        self.assertEqual(len(fixture['methods']), len(set(fixture['methods'])))
        self.assertEqual(set(bridge.KNOWN_METHODS), set(fixture['methods']))

    @unittest.skipUnless(os.environ.get('HERDR_MCP_TEST_SCHEMA'), 'HERDR_MCP_TEST_SCHEMA not set: schema re-extraction skipped')
    def test_fixture_matches_saved_schema(self):
        raw = pathlib.Path(os.environ['HERDR_MCP_TEST_SCHEMA']).read_bytes()
        fixture = json.loads(self.FIXTURE.read_text())
        self.assertEqual(hashlib.sha256(raw).hexdigest(), fixture['source_sha256'])
        alts = json.loads(raw)['schemas']['request']['oneOf']
        self.assertTrue(all(set(a['properties']) == {'method', 'params'} for a in alts))
        self.assertEqual(sorted(a['properties']['method']['const'] for a in alts), fixture['methods'])


class AuditFileTests(unittest.TestCase):
    """Rotation and failure behavior with synthetic records."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix='hma-', dir='/tmp')).resolve()
        self.saved = bridge.AUDIT_PATH, bridge.AUDIT_MAX_BYTES, bridge.SOCK
        bridge.AUDIT_PATH = str(self.dir / 'state' / 'audit.log')
        bridge.SOCK = str(self.dir / 'no-such.sock')  # never the real Herdr socket

    def tearDown(self):
        bridge.AUDIT_PATH, bridge.AUDIT_MAX_BYTES, bridge.SOCK = self.saved
        shutil.rmtree(self.dir)

    def test_rotation_bounded(self):
        bridge.AUDIT_MAX_BYTES = 400
        for n in range(200):
            bridge.audit_write({'n': n, 'pad': 'x' * 40})
        names = sorted(os.listdir(self.dir / 'state'))
        self.assertEqual(names, ['audit.log'] + [f'audit.log.{i}' for i in range(1, bridge.AUDIT_KEEP + 1)]
                         + ['audit.log.lock'])
        for name in names:
            self.assertLessEqual((self.dir / 'state' / name).stat().st_size, 400)
            self.assertEqual((self.dir / 'state' / name).stat().st_mode & 0o777, 0o600)
        newest = [json.loads(l)['n'] for l in (self.dir / 'state' / 'audit.log').read_text().splitlines()]
        self.assertEqual(newest[-1], 199)
        older = [json.loads(l)['n'] for l in (self.dir / 'state' / 'audit.log.1').read_text().splitlines()]
        self.assertEqual(older[-1] + 1, newest[0])

    def test_concurrent_processes_rotate_without_loss(self):
        """Several bridge processes share one log (tunnel-client may run more than one)."""
        script = '\n'.join([
            'import importlib.util, sys',
            f'spec = importlib.util.spec_from_file_location("b", {str(SRC / "herdr_control_mcp.py")!r})',
            'b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)',
            f'b.AUDIT_PATH = {bridge.AUDIT_PATH!r}; b.AUDIT_MAX_BYTES = 8192',
            'for n in range(300): b.audit_write({"p": int(sys.argv[1]), "n": n, "pad": "x" * 8})'])
        procs = [subprocess.Popen(['/usr/bin/python3', '-I', '-B', '-c', script, str(i)]) for i in range(4)]
        try:
            self.assertEqual([p.wait(60) for p in procs], [0, 0, 0, 0])
        finally:
            for p in procs:
                if p.poll() is None:
                    p.kill()
                    p.wait()
        seen = set()
        for name in os.listdir(self.dir / 'state'):
            path = self.dir / 'state' / name
            if name.endswith('.lock'):
                continue
            self.assertLessEqual(path.stat().st_size, 8192, name)
            for line in path.read_text().splitlines():
                rec = json.loads(line)  # no torn or interleaved lines
                seen.add((rec['p'], rec['n']))
        self.assertEqual(len(seen), 1200)  # capacity 6 x 8 KiB exceeds the ~40 KiB written

    def test_stderr_closed_and_log_unwritable(self):
        (self.dir / 'state').write_text('not a directory')
        saved = sys.stderr
        sys.stderr = open(os.devnull, 'w')
        sys.stderr.close()
        try:
            out = bridge.audited_call('herdr_request', {'method': 'ping', 'params': {}, 'timeout_ms': 200}, 8)
        finally:
            sys.stderr = saved
        self.assertEqual(json.loads(out['content'][0]['text'])['outcome'], 'not_sent')

    def test_write_failure_does_not_block_call(self):
        (self.dir / 'state').write_text('not a directory')
        out = bridge.audited_call('herdr_request', {'method': 'ping', 'params': {}, 'timeout_ms': 200}, 7)
        self.assertEqual(json.loads(out['content'][0]['text'])['outcome'], 'not_sent')

    def test_symlinked_log_refused(self):
        (self.dir / 'state').mkdir()
        victim = self.dir / 'victim'
        victim.write_text('keep')
        os.symlink(victim, self.dir / 'state' / 'audit.log')
        bridge.audit_write({'n': 1})
        self.assertEqual(victim.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
