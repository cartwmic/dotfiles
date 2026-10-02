"""Outside-in supervisor checks: private stores and scripted backends only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

CLI = Path(__file__).with_name('session_recap.py')


class RequestCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict({k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR') if k in os.environ},
                        HOME=str(self.root), XDG_DATA_HOME=str(self.root / 'data'),
                        XDG_CONFIG_HOME=str(self.root / 'config'))
        self.backend = self.root / 'backend.py'
        self.backend.write_text('import sys\nsys.stdout.write("recap " + sys.stdin.read())\n')

    def cli(self, *args):
        return json.loads(subprocess.check_output([sys.executable, str(CLI), *args], env=self.env))

    def reserve(self):
        return self.cli('reserve', '--key', 'arbitrary/key', '--json')['token']

    def start(self, token=None, **updates):
        request = dict(schema_version=1, request_key='arbitrary/key', token=token or self.reserve(),
                       kind='single', source_kind='generic', source_id='captured', material='fact alpha',
                       instructions='Recap', command=[sys.executable, str(self.backend)],
                       timeout_seconds=2, recursive=False, input_budget_bytes=4096,
                       backend_identity={'provider': 'fake', 'model': 'script'}, metadata={'coverage': 'opaque'})
        request.update(updates)
        path = self.root / (str(time.time_ns()) + '.json')
        path.write_text(json.dumps(request))
        path.chmod(0o600)
        process = subprocess.Popen([sys.executable, str(CLI), 'run', '--request-file', str(path), '--json-lines'],
                                   env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        accepted = json.loads(process.stdout.readline())
        self.assertFalse(path.exists())
        return process, accepted

    def finish(self, process):
        output, error = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 0, error)
        return json.loads(output.strip().splitlines()[-1])

    def test_saved_current_and_safe_record(self):
        process, accepted = self.start()
        self.assertEqual(accepted['event'], 'accepted')
        terminal = self.finish(process)
        self.assertEqual(terminal['status'], 'published')
        self.assertEqual(self.cli('current', '--key', 'arbitrary/key', '--json')['token'], terminal['token'])
        record = self.cli('read', terminal['record_id'], '--json')['record']
        self.assertEqual(record['attempt'], 1)
        self.assertNotIn('command', record)
        self.assertNotIn('material', record)
        self.assertEqual(record['metadata'], {'coverage': 'opaque'})

    def test_cancel_and_supersede_kill_owned_group(self):
        for cancel in (False, True):
            gate = self.root / 'gate'
            gate.unlink(missing_ok=True)
            self.backend.write_text('import pathlib,time\npathlib.Path(' + repr(str(gate)) + ').write_text("started")\ntime.sleep(30)\nprint("late")\n')
            process, _ = self.start()
            end = time.monotonic() + 3
            while not gate.exists() and time.monotonic() < end:
                time.sleep(.01)
            self.assertTrue(gate.exists())
            if cancel:
                self.assertIsNone(self.cli('cancel', '--key', 'arbitrary/key', '--json')['token'])
            else:
                self.reserve()
            terminal = self.finish(process)
            self.assertEqual(terminal['status'], 'canceled' if cancel else 'superseded')
        records = self.cli('list', '--json')['records']
        self.assertFalse(any(r['status'] == 'published' for r in records))

    def test_timeout_and_one_retry(self):
        calls = self.root / 'calls'
        self.backend.write_text('import pathlib,time\np=pathlib.Path(' + repr(str(calls)) + ')\np.open("a").write("call\\n")\ntime.sleep(5)\n')
        process, _ = self.start(timeout_seconds=.15)
        terminal = self.finish(process)
        self.assertEqual(terminal['status'], 'failed')
        self.assertEqual(terminal['failure']['reason'], 'timed_out')
        self.assertEqual(calls.read_text().splitlines(), ['call', 'call'])
        records = self.cli('list', '--status', 'failed', '--json')['records']
        self.assertEqual(len(records), 2)
        for record in records:
            self.assertEqual(record['failure'], {
                'message': 'attempt deadline exceeded', 'reason': 'timed_out'})
            self.assertNotIn('summary', record)
            self.assertEqual(self.cli('read', record['record_id'], '--json')['record'], record)
        self.assertEqual(self.cli('list', '--status', 'published', '--json')['records'], [])

    def test_retry_success(self):
        flag = self.root / 'flag'
        self.backend.write_text('import pathlib,sys\np=pathlib.Path(' + repr(str(flag)) + ')\nif not p.exists():\n p.touch();sys.exit(4)\nprint("recovered")\n')
        process, _ = self.start()
        result = self.finish(process)
        self.assertEqual(result['status'], 'published')
        self.assertEqual(result['attempt'], 2)

    def test_oversize_off_never_calls(self):
        marker = self.root / 'called'
        self.backend.write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\nprint("no")\n')
        process, _ = self.start(material='x' * 1000, input_budget_bytes=200)
        self.assertEqual(self.finish(process)['status'], 'failed')
        self.assertFalse(marker.exists())

    def test_recursive_all_facts_and_disclosure(self):
        # Scripted reducer removes padding, retaining every numbered fact across chunks.
        self.backend.write_text('import re,sys\nx=sys.stdin.read()\nprint(" ".join(re.findall(r"FACT[0-9]+", x)))\n')
        material = ''.join('FACT%d ' % i + ' ' * 80 for i in range(20))
        process, _ = self.start(material=material, recursive=True, input_budget_bytes=350)
        terminal = self.finish(process)
        self.assertEqual(terminal['status'], 'published')
        record = self.cli('read', terminal['record_id'], '--json')['record']
        for i in range(20):
            self.assertIn('FACT%d' % i, record['summary'])
        self.assertTrue(record['reduced'])
        self.assertIn('chunked and reduced', record['summary'])

    def test_storage_fault_live_unsaved(self):
        # Gate generation until the authoritative records directory is made unwritable structurally.
        gate = self.root / 'release'
        self.backend.write_text('import pathlib,time\np=pathlib.Path(' + repr(str(gate)) + ')\nwhile not p.exists(): time.sleep(.01)\nprint("generated result")\n')
        process, _ = self.start()
        (self.root / 'data/session-recap/records').write_text('not a directory')
        gate.touch()
        terminal = self.finish(process)
        self.assertEqual(terminal['status'], 'generated-unsaved')
        self.assertEqual(terminal['text'], 'generated result')
        self.assertIn('not saved', terminal['warning'])

    def test_owned_descendant_cannot_finish_after_cancel(self):
        marker = self.root / 'descendant-finished'
        started = self.root / 'descendant-started'
        child = ('import pathlib,time; pathlib.Path(' + repr(str(started)) + ').touch(); '
                 'time.sleep(.6); pathlib.Path(' + repr(str(marker)) + ').touch()')
        self.backend.write_text('import subprocess,sys,time\nsubprocess.Popen([sys.executable,"-c",' + repr(child) + '])\ntime.sleep(30)\n')
        process, _ = self.start()
        end = time.monotonic() + 3
        while not started.exists() and time.monotonic() < end:
            time.sleep(.01)
        self.assertTrue(started.exists())
        self.cli('cancel', '--key', 'arbitrary/key', '--json')
        self.assertEqual(self.finish(process)['status'], 'canceled')
        time.sleep(.8)
        self.assertFalse(marker.exists())

    def test_host_exit_detached_completion(self):
        token = self.reserve()
        request = dict(schema_version=1, request_key='arbitrary/key', token=token, kind='single',
                       source_kind='generic', source_id='departed', material='captured before exit',
                       instructions='Recap', command=[sys.executable, str(self.backend)], timeout_seconds=2,
                       recursive=False, input_budget_bytes=4096)
        path = self.root / 'detached.json'
        path.write_text(json.dumps(request))
        events = self.root / 'events'
        launcher = ('import subprocess,sys\nwith open(sys.argv[1],"w") as out:\n'
                    ' subprocess.Popen(sys.argv[2:],stdout=out,stderr=subprocess.DEVNULL,start_new_session=True)\n')
        subprocess.check_call([sys.executable, '-c', launcher, str(events), sys.executable, str(CLI),
                               'run', '--request-file', str(path), '--json-lines'], env=self.env)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            if events.exists() and 'terminal' in events.read_text():
                break
            time.sleep(.02)
        terminal = json.loads(events.read_text().splitlines()[-1])
        self.assertEqual(terminal['status'], 'published')
        self.assertIn('captured before exit', self.cli('read', terminal['record_id'], '--json')['record']['summary'])

    def test_optional_preflight_budget_and_opaque_command(self):
        helper = self.root / 'preflight.py'
        helper.write_text('import json,sys\nassert sys.stdin.read()=="all captured material"\n'
                          'print(json.dumps({"input_budget_bytes":400,"command":[sys.executable,"-c", "import sys; assert len(sys.stdin.read().encode())<=400; print(\\\"adjusted argv used\\\")"]}))\n')
        process, _ = self.start(material='all captured material',
                                preflight={'command': [sys.executable, str(helper)]})
        terminal = self.finish(process)
        self.assertEqual(terminal['status'], 'published')
        self.assertEqual(self.cli('read', terminal['record_id'], '--json')['record']['summary'], 'adjusted argv used')
        archived = json.dumps(self.cli('list', '--json'))
        for value in ('all captured material', str(helper), 'preflight', 'command'):
            self.assertNotIn(value, archived)

    def test_invalid_optional_preflight_envelope_rejected_before_acceptance(self):
        for preflight in (None, {}, {'command': []}, {'command': ['helper'], 'timeout_seconds': 3}):
            with self.subTest(preflight=preflight):
                request = dict(schema_version=1, request_key='arbitrary/key', token=self.reserve(),
                               source_kind='generic', source_id='captured', kind='single',
                               material='complete material', instructions='Recap',
                               command=[sys.executable, str(self.backend)], timeout_seconds=2,
                               input_budget_bytes=4096, recursive=False, preflight=preflight)
                path = self.root / 'invalid-request.json'
                path.write_text(json.dumps(request)); path.chmod(0o600)
                result = subprocess.run([sys.executable, str(CLI), 'run', '--request-file', str(path), '--json-lines'],
                                        env=self.env, capture_output=True, text=True, timeout=5)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertFalse(path.exists())
                self.assertFalse(self.cli('list', '--json')['records'])

    def test_invalid_preflight_output_retried_not_policy_mutation(self):
        helper = self.root / 'preflight.py'
        calls = self.root / 'preflight-calls'
        for result in ({'input_budget_bytes': True}, {'input_budget_bytes': 0},
                       {'input_budget_bytes': 4097}, {'input_budget_bytes': 400, 'metadata': {}},
                       {'input_budget_bytes': 400, 'command': []}, ['unexpected'], 'not JSON'):
            with self.subTest(result=result):
                calls.unlink(missing_ok=True)
                helper.write_text('from pathlib import Path\n'
                                  'Path(' + repr(str(calls)) + ').open("a").write("call\\n")\n'
                                  'print(' + repr(json.dumps(result) if result != 'not JSON' else result) + ')\n')
                process, request = self.start(preflight={'command': [sys.executable, str(helper)]})
                terminal = self.finish(process)
                self.assertEqual(terminal['status'], 'failed')
                self.assertEqual(terminal['attempt'], 2)
                self.assertEqual(calls.read_text().splitlines(), ['call', 'call'])
                records = [r for r in self.cli('list', '--json')['records'] if r['token'] == request['token']]
                self.assertEqual(len(records), 2)
                self.assertTrue(all(r['status'] == 'failed' for r in records))
                self.assertTrue(all(r['metadata'] == {'coverage': 'opaque'} for r in records))

    def test_recursive_deadline_is_whole_attempt(self):
        calls = self.root / 'recursive-calls'
        self.backend.write_text('import pathlib,re,sys,time\nx=sys.stdin.read()\n'
                               'pathlib.Path(' + repr(str(calls)) + ').open("a").write("call\\n")\n'
                               'time.sleep(.12)\nprint(" ".join(re.findall(r"FACT[0-9]+",x)))\n')
        material = ''.join('FACT%d ' % i + ' ' * 80 for i in range(20))
        process, _ = self.start(material=material, recursive=True, input_budget_bytes=350, timeout_seconds=.3)
        terminal = self.finish(process)
        self.assertEqual(terminal['status'], 'failed')
        self.assertLessEqual(len(calls.read_text().splitlines()), 6)
        self.assertFalse(any(r['status'] == 'published' for r in self.cli('list', '--json')['records']))

    def test_cancel_preserves_already_saved_history(self):
        process, _ = self.start()
        terminal = self.finish(process)
        self.cli('cancel', '--key', 'arbitrary/key', '--json')
        record = self.cli('read', terminal['record_id'], '--json')['record']
        self.assertEqual(record['status'], 'published')

    def test_nonshrinking_recursive_pipeline_fails(self):
        self.backend.write_text('import sys\nprint(sys.stdin.read())\n')
        process, _ = self.start(material='unresolved ' * 100, recursive=True, input_budget_bytes=300)
        self.assertEqual(self.finish(process)['status'], 'failed')
        self.assertFalse(any(r['status'] == 'published' for r in self.cli('list', '--json')['records']))

    def test_broken_pipe_detached_save(self):
        gate = self.root / 'release'
        self.backend.write_text('import pathlib,time\np=pathlib.Path(' + repr(str(gate)) + ')\nwhile not p.exists(): time.sleep(.01)\nprint("after departure")\n')
        process, _ = self.start()
        process.stdout.close()
        gate.touch()
        process.wait(timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr.read())
        records = self.cli('list', '--json')['records']
        self.assertEqual(records[0]['summary'], 'after departure')
        process.stderr.close()


if __name__ == '__main__':
    unittest.main()
