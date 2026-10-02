#!/usr/bin/env python3
"""Real public Pi journeys with unfiltered, genuinely published history above 1 MiB."""
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import struct
import subprocess
import termios
import sys
import tempfile
from public_helpers import PublicPi, ROOT, CLI

SOURCES = ['dot_pi/private_agent/extensions/recap/index.ts', 'tests/pi-recap/history_transport.py', 'tests/pi-recap/public_helpers.py', 'tests/pi-recap/public_fixture.ts', 'tests/pi-recap/proof.py']


def digest(paths):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def run():
    observation = dict(case='large-retained-history-public', source_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES}, completed=[])
    with tempfile.TemporaryDirectory(prefix='recap-history-') as temporary:
        root = Path(temporary)
        tmp = root / 'tmp'
        tmp.mkdir(mode=0o700)
        pi = PublicPi(root, environment=dict(TMPDIR=str(tmp), RECAP_PROOF_COMPACTION='manual'), config=dict(model=None, inputBudget=24000), agent_settings=dict(compaction=dict(enabled=False, keepRecentTokens=1)))
        retained = {}
        width = 158
        def redraw():
            nonlocal width
            width = 159 if width == 158 else 158
            fcntl.ioctl(pi.master, termios.TIOCSWINSZ, struct.pack('HHHH', 36, width, 0, 0))
            os.kill(pi.process.pid, signal.SIGWINCH)
            pi.collect(.5)
        try:
            # Use the delivered wrapper and generic create protocol, not fabricated
            # list bytes or direct writes masquerading as published v2 records.
            config = root / 'config/session-recap'
            config.mkdir(parents=True)
            backend = root / 'seed.py'
            backend.write_text("import sys\nsys.stdin.read()\nprint('\\n'.join(f'RETAINED_LINE_{i:04d} completed unrelated investigation; deployment remains pending; next inspect retained evidence.' for i in range(450)))\n")
            (config / 'config.toml').write_text('command = ' + json.dumps([sys.executable, str(backend)]) + '\nauto_publish = false\n')
            (config / 'single-prompt.md').write_text('[[TEXT]]\n')
            (config / 'group-prompt.md').write_text('[[MEMBERS]]\n')
            seed_env = dict(pi.env, SESSION_RECAP_IMPLEMENTATION=str(CLI))
            for i in range(24):
                args = [str(root / '.local/bin/session-recap'), 'create', '--kind', 'single', '--source-kind', 'pi' if i % 2 else 'other', '--source-id', f'retained-{i}']
                if i % 2:
                    args += ['--metadata-json', json.dumps(dict(pi=dict(historyId=f'unrelated-{i}', nativeSessionId=f'other-session-{i}', trigger='manual', coverage=dict(anchor=None, units=[]))))]
                subprocess.run(args, input=f'Unrelated retained investigation {i}', text=True, env=seed_env, capture_output=True, check=True, timeout=15)
            # Honest legacy record fixture, as in the store's existing migration
            # tests. No preferences or old publication lifecycle are imported.
            legacy = root / 'data/session-recap/records/2020-01-01/legacy-history.json'
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text(json.dumps(dict(schema_version=1, record_id='legacy-history', created_at='2020-01-01T00:00:00Z', source_kind='other', source_id='legacy-source', kind='single', status='published', summary='Legacy retained outcome. Next inspect historical evidence.')))
            retained = digest(sorted((root / 'data/session-recap/records').rglob('*.json')))
            listing = subprocess.check_output([str(root / '.local/bin/session-recap'), 'list', '--json'], env=seed_env, timeout=15)
            assert len(listing) > 1024 * 1024 and len(json.loads(listing)['records']) == 25
            observation.update(retained_list_bytes=len(listing), retained_count=len(retained), retained_before_sha256=hashlib.sha256(json.dumps(retained, sort_keys=True).encode()).hexdigest())

            # Observe genuine stdout destination permissions and failed-CLI cleanup
            # without altering successful data, controls, wrapper or env selection.
            original_transport = pi.env['PI_RECAP_CLI']
            transport = root / 'list-observer.py'
            transport.write_text('''import json, os, stat, subprocess, sys
from pathlib import Path
if sys.argv[1] != 'list':
    os.execv(sys.executable, [sys.executable, ORIGINAL, *sys.argv[1:]])
s = os.fstat(1)
with Path(os.environ['HOME'] + '/list-sinks.jsonl').open('a') as f:
    f.write(json.dumps(dict(regular=stat.S_ISREG(s.st_mode), mode=stat.S_IMODE(s.st_mode))) + '\\n')
p = subprocess.run([sys.executable, os.environ['GENUINE_RECAP_CLI'], *sys.argv[1:]])
sys.exit(17 if Path(os.environ['HOME'] + '/fail-list').exists() else p.returncode)
'''.replace('ORIGINAL', repr(original_transport)))
            pi.env['PI_RECAP_CLI'] = str(transport)
            # Reload only this owned Pi to install the test observer and use the
            # retained store on startup discovery as well as command entry.
            text = pi.fixture.read_text().replace("if (number === 1) while", "while")
            text = text.replace("const topic = args.topic;", "const topic = args.topic;\n    log({ event: 'tool-start', topic });\n    while (existsSync(process.env.HOME + '/tool-gate')) await delay(50);")
            text = text.replace("pi.on('agent_settled'", "pi.events.on('recap:saved', (event: any) => log({ event: 'recap-saved', ...event }));\n  pi.on('agent_settled'")
            pi.fixture.write_text(text)
            pi.stop(); pi.launch(); pi.collect(4)
            pi.send('orchard'); pi.wait(lambda: any(e['event'] == 'settled' for e in pi.events()), 'orchard never settled')
            start = len(pi.output); pi.send('/recap', 1)
            setup = 'Recap model (independent of session model)' in pi.visible(start)
            if not setup:
                # Preserve all original current-manual/full/history failures in
                # the same harness before failing closed at first-use setup.
                failures = dict(setup=pi.visible(start).count('Recap operation failed'))
                configured = json.loads((pi.extension / 'config.json').read_text())
                configured['model'] = dict(provider='recap-proof', id='recap')
                (pi.extension / 'config.json').write_text(json.dumps(configured))
                for name, command in [('manual', '/recap'), ('full', '/recap full'), ('history', '/recap history')]:
                    boundary = len(pi.output); pi.send(command, 1); redraw()
                    failures[name] = 'Recap operation failed' in pi.visible(boundary)
                observation.update(original_failures=failures, backend_calls=len(pi.calls()), envelopes=len(pi.envelopes()))
            assert setup, 'large retained history blocked useful unset-model setup and manual/full/history'
            # Only the local scripted provider has credentials in this allowlisted
            # private agent directory. Select recap, not the foreground model.
            os.write(pi.master, b'\x1b[B'); pi.send('', .5)
            assert 'Save recap model' in pi.visible(start)
            pi.send('', .5)  # Current session.
            pi.wait(lambda: len(pi.envelopes()) == 1, 'manual setup did not capture')
            def published():
                return [r for r in pi.records() if r['status'] == 'published' and r.get('metadata', {}).get('pi', {}).get('nativeSessionId') not in {f'other-session-{i}' for i in range(24)} and r.get('metadata', {}).get('pi', {}).get('historyId')]
            def finish(count):
                pi.wait(lambda: len(pi.envelopes()) == count, 'expected capture missing')
                envelope = pi.envelopes()[-1]
                pi.wait(lambda: pi.terminal(envelope['token']), 'captured recap did not complete')
                assert pi.terminal(envelope['token'])['status'] == 'published'
                record_id = pi.terminal(envelope['token'])['record_id']
                pi.wait(lambda: any(e['event'] == 'recap-saved' and e['recordId'] == record_id for e in pi.events()), 'current saved outcome not consumed', 5)
                redraw()
                record = next(r for r in pi.records() if r['record_id'] == record_id)
                facts = re.findall(r'\b(?:orchard|harbor|older|newer)-(?:checks-passed|deployment-unfinished|review-before-deploy)\b', record['summary'])
                topic = re.search(r'Observed \w+:', record['summary']).group()
                assert topic in pi.visible() and all(fact in pi.visible() for fact in facts), 'published outcome/pending/next narrative not displayed'
                return envelope
            first = finish(1)
            assert first['selection']['model'] == dict(provider='recap-proof', id='recap') and first['background'] == ''
            original = published()[0]['metadata']['pi']['nativeSessionId']
            first_record = published()[0]
            assert 'Observed orchard:' in first_record['summary'] and 'orchard-checks-passed' in first_record['summary']
            observation['completed'].append('useful-unset-model-session-setup-manual-incremental')
            def no_new(command='/recap', marker='No new activity'):
                calls, envelopes = len(pi.calls()), len(pi.envelopes())
                start = len(pi.output); pi.send(command, 1); redraw()
                assert marker in pi.visible(start) and len(pi.calls()) == calls and len(pi.envelopes()) == envelopes
                return pi.visible(start)
            assert 'Observed orchard:' in no_new()
            pi.send('/recap full'); full = finish(2)
            assert full['material'] == first['material']
            assert 'Observed orchard:' in no_new('/recap full', 'Reused matching full recap')
            pi.send('harbor'); pi.wait(lambda: sum(e['event'] == 'settled' for e in pi.events()) == 2, 'harbor never settled')
            pi.send('/recap'); incremental = finish(3)
            assert 'FACT_topic=harbor' in incremental['material'] and 'FACT_topic=orchard' not in incremental['material']
            assert 'Observed orchard:' in incremental['background']
            latest = published()[-1]
            assert 'Observed harbor:' in latest['summary'] and latest['summary'] != first_record['summary']
            assert 'Observed harbor:' in no_new()
            observation['completed'].append('manual-full-reuse-incremental-distinct-latest-no-new-no-extra-call')

            # Search actual summary text/IDs through current/all/legacy selectors;
            # select and page down a long genuine generic narrative.
            def history(command, query, expected, scroll=False):
                start = len(pi.output); count = len(pi.calls())
                pi.send(command, 1)
                assert 'Recap history' in pi.visible(start), 'history selector failed to open'
                os.write(pi.master, query.encode()); pi.collect(.5); pi.send('', .5)
                assert 'scroll, Esc close' in pi.visible(start) and expected in pi.visible(start)
                if scroll:
                    boundary = len(pi.output); os.write(pi.master, b'\x1b[6~'); pi.collect(.5)
                    assert 'RETAINED_LINE_0018' in pi.visible(boundary), 'history page-down lost retained text'
                os.write(pi.master, b'\x1b'); pi.collect(.5)
                assert len(pi.calls()) == count, 'history made backend call'
            history('/recap history', 'harbor-checks-passed', 'Observed harbor:')
            other = next(r for r in pi.records() if r['source_id'] == 'retained-1')
            history('/recap history all', other['record_id'], 'RETAINED_LINE_0000', True)
            history('/recap history legacy', 'legacy-history', 'Legacy retained outcome')
            generic = next(r for r in pi.records() if r['source_id'] == 'retained-0')
            history('/recap history legacy', generic['record_id'], 'RETAINED_LINE_0000', True)
            observation['completed'].append('current-all-legacy-summary-search-view-scroll-no-call')
            (root / 'fail-list').touch()
            start = len(pi.output); pi.send('/recap history', 1)
            assert 'Recap operation failed; coverage unchanged' in pi.visible(start)
            assert not list(tmp.glob('pi-recap-records-*')), 'failed CLI output temp leaked'
            (root / 'fail-list').unlink()
            history('/recap history', 'harbor-checks-passed', 'Observed harbor:')
            observation['completed'].append('failed-cli-with-valid-output-safe-error-cleanup-recovery')

            session = next(p for p in (root / 'sessions').rglob('*.jsonl') if PublicPi.lines(p)[0]['id'] == original)
            before = sum(e['event'] == 'recap-saved' for e in pi.events())
            pi.stop(); pi.launch(session); pi.collect(4)
            assert sum(e['event'] == 'recap-saved' for e in pi.events()) > before, 'startup records discovery lost saved recap'
            assert 'Observed harbor:' in no_new()
            pi.send('/new', 1); pi.send('/resume', 1); pi.send('', 2)
            assert 'Observed harbor:' in no_new()
            observation['completed'].append('startup-discovery-resume-and-original-return-authoritative-baseline')

            pi.setting('completed', True)
            pi.send('newer'); pi.wait(lambda: sum(e['event'] == 'settled' for e in pi.events()) == 3, 'automatic work did not settle')
            settlement = finish(4)
            assert 'FACT_topic=newer' in settlement['material'] and 'FACT_topic=harbor' not in settlement['material']
            assert published()[-1]['metadata']['pi']['trigger'] == 'settlement'
            assert 'Observed newer:' in published()[-1]['summary']
            pi.setting('completed', False)
            observation['completed'].append('automatic-settlement-shared-incremental-baseline')

            pi.setting('intervalMinutes', .025); pi.setting('periodic', True)
            toolgate = root / 'tool-gate'; toolgate.touch()
            start = len(pi.output); pi.send('older')
            pi.wait(lambda: any(e['event'] == 'tool-start' and e['topic'] == 'older' for e in pi.events()), 'periodic foreground tool not active')
            periodic = finish(5)
            assert toolgate.exists() and 'ongoing/partial' in periodic['material']
            pi.wait(lambda: 'No new activity' in pi.visible(start) and 'Ongoing:' in pi.visible(start), 'periodic latest/no-new ongoing not displayed', 8)
            pi.collect(2)
            assert len(pi.envelopes()) == 5 and len(pi.calls()) == 5, 'periodic no-new made extra generation calls'
            assert published()[-1]['metadata']['pi']['trigger'] == 'periodic'
            toolgate.unlink(); pi.wait(lambda: sum(e['event'] == 'settled' for e in pi.events()) == 4, 'silent tool did not settle')
            pi.setting('periodic', False)
            pi.send('/recap'); final = finish(6)
            assert 'FACT_result=older-checks-passed' in final['material'], 'partial periodic snapshot hid final tool result'
            observation['completed'].append('periodic-active-silent-tool-latest-no-new-status-final-uncovered')

            pi.setting('beforeCompaction', True)
            pi.send('orchard'); pi.wait(lambda: sum(e['event'] == 'settled' for e in pi.events()) == 5, 'precompaction new work did not settle')
            pi.gate.touch(); start = len(pi.output)
            pi.send('/compact', .2)
            pi.wait(lambda: any(e['event'] == 'compacted' for e in pi.events()), 'native compaction did not finish with recap gated', 8)
            pi.wait(lambda: len(pi.envelopes()) == 7 and len(pi.calls()) == 7, 'before-compaction capture missing', 10)
            compaction = pi.envelopes()[-1]
            assert pi.gate.exists() and not pi.terminal(compaction['token'])
            assert 'FACT_result=orchard-checks-passed' in compaction['material']
            # This accepted captured job must survive leaving its UI, save only
            # under the original identity, and be discoverable on return.
            pi.send('/new', 1); boundary = len(pi.output)
            pi.gate.unlink()
            pi.wait(lambda: pi.terminal(compaction['token']), 'departed captured job did not finish')
            assert pi.terminal(compaction['token'])['status'] == 'published'
            pi.collect(1)
            assert 'Recap saved' not in pi.visible(boundary), 'departed result displayed in new session'
            pi.send('/resume', 1); pi.send('', 2)
            history('/recap history', pi.terminal(compaction['token'])['record_id'], 'Observed orchard:')
            assert published()[-1]['metadata']['pi']['nativeSessionId'] == original
            assert published()[-1]['metadata']['pi']['trigger'] == 'before-compaction'
            assert 'Observed orchard:' in published()[-1]['summary']
            assert len(pi.calls()) == 7 and len(published()) == 7, 'extra backend calls or publications'
            assert len([e for e in pi.events() if e['event'] == 'call' and e.get('model') == 'main']) == 10 + sum(e['event'] == 'native-summary' for e in pi.events()), 'extra foreground model turn'
            pi.assert_no_transcript_output()
            observation['completed'].append('native-nonblocking-precompaction-original-material-captured-published')
            sinks = PublicPi.lines(root / 'list-sinks.jsonl')
            assert sinks and all(s['regular'] and s['mode'] == 0o600 for s in sinks), 'list stdout not private regular-file sink'
            assert not list(tmp.glob('pi-recap-records-*')), 'successful CLI output temp leaked'
            observation.update(status='PASS', recap_calls=len(pi.calls()), publications=len(published()), private_list_file_sinks=len(sinks), successful_and_failed_list_temp_cleanup=True)
        except Exception as exc:
            observation.update(status='FAIL', reason=str(exc))
            raise
        finally:
            (root / 'tool-gate').unlink(missing_ok=True)
            if retained:
                after = digest([Path(p) for p in retained])
                observation.update(retained_after_sha256=hashlib.sha256(json.dumps(after, sort_keys=True).encode()).hexdigest(), retained_unchanged=retained == after, retained_after_count=len(after))
                assert retained == after, 'retained generic/legacy files mutated or pruned'
            pi.close()
            observation['temporary_list_outputs_remaining'] = len(list(tmp.glob('pi-recap-records-*')))
            observation['cleanup'] = 'owned Pi/supervisors exited; only private fixture removed; no raw/auth evidence archived'
            print(json.dumps(observation), flush=True)
    assert not root.exists(), 'private fixture not removed'


if __name__ == '__main__':
    run()
