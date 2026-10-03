#!/usr/bin/env python3
"""Public captured virtual-preflight supervision, with real Pi and delivered CLI."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from public_helpers import PublicPi, ROOT

SOURCES = ['dot_pi/private_agent/extensions/recap/index.ts', 'dot_pi/private_agent/extensions/recap/backend.mjs', 'dot_local/share/session-recap/session_recap.py', 'tests/pi-recap/preflight.py', 'tests/pi-recap/public_fixture.ts', 'tests/pi-recap/public_helpers.py']

def exited(pid):
    try: os.kill(pid, 0)
    except ProcessLookupError: return True
    return False

def run(case):
    observation = dict(case=case, source_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES})
    with tempfile.TemporaryDirectory(prefix='recap-preflight-') as temporary:
        root = Path(temporary)
        pi = PublicPi(root, config=dict(model=dict(provider='recap-router', id='auto'), timeoutSeconds=4 if case == 'deadline' else 30))
        gate = root / 'budget-gate'
        token = None
        try:
            pi.send('orchard'); pi.wait(lambda: any(e['event'] == 'settled' for e in pi.events()), 'main did not settle')
            original = next((root / 'sessions').rglob('*.jsonl'))
            if case == 'deadline':
                (root / 'budget-delay').write_text('2500'); pi.slow.touch()
            else: gate.touch()
            pi.send('/recap', .2)
            pi.wait(lambda: any(e['event'] == 'route-start' and e['preflight'] for e in pi.events()), 'no public preflight', 12)
            entries = PublicPi.lines(original)
            identity = next(e['data']['nativeSessionId'] for e in entries if e.get('customType') == 'recap-state')
            history = next(e['data']['historyId'] for e in entries if e.get('customType') == 'recap-state')
            key = 'pi-recap:' + identity
            token = pi.current(key)['token']
            pid = next(e['pid'] for e in pi.events() if e['event'] == 'route-start' and e['preflight'])
            if case != 'deadline': pi.wait(lambda: any(e['event'] == 'budget-wait' for e in pi.events()), 'metadata gate not reached')
            boundary = len(pi.output)
            if case in ('switch', 'newer'):
                pi.send('/new', 1)
                if case == 'newer':
                    pi.stop(); pi.launch(original); pi.collect(3)
                    pi.send('/recap', .2)
                    pi.wait(lambda: len([e for e in pi.events() if e['event'] == 'route-start' and e['preflight']]) == 2, 'newest request did not start')
                    assert pi.current(key)['token'] != token
            elif case == 'reload': pi.send('/reload', 2)
            elif case == 'shutdown': pi.stop()
            elif case == 'cancel': pi.send('/recap cancel', .2)
            elif case != 'deadline': raise ValueError(case)
            if case in ('cancel', 'newer'):
                pi.wait(lambda: exited(pid), 'canceled/superseded preflight remains alive with closed gate', 3)
                assert gate.exists(), 'cancel proof opened metadata gate'
                pi.wait(lambda: pi.terminal(token), 'stopped request lacks terminal', 5)
                assert pi.terminal(token)['status'] == ('canceled' if case == 'cancel' else 'superseded')
                assert len([e for e in pi.events() if e['event'] == 'route-start' and e['preflight'] and e['pid'] == pid]) == 1
            if case != 'deadline': gate.unlink()
            pi.wait(lambda: pi.terminal(pi.current(key)['token']) if case == 'newer' else pi.terminal(token), 'captured work lost or did not finish', 18)
            terminal = pi.terminal(pi.current(key)['token']) if case == 'newer' else pi.terminal(token)
            published = [r for r in pi.records() if r['status'] == 'published']
            if case == 'deadline':
                assert terminal['status'] == 'failed' and terminal['failure']['reason'] == 'timed_out', 'separate preflight/generation clocks published beyond deadline'
                failed = [r for r in pi.records() if r['token'] == token]
                assert [r['attempt'] for r in failed] == [1, 2] and all(r['failure'].get('reason') == 'timed_out' for r in failed)
                assert len([e for e in pi.events() if e['event'] == 'route-start' and e['preflight']]) == 2, 'retry did not rerun complete preflight'
                assert not published
                envelope = pi.envelopes()[0]
                elapsed = terminal['time'] - envelope['time']
                assert 7.8 <= elapsed < 11, elapsed
                (root / 'budget-delay').unlink(); pi.slow.unlink()
                pi.send('/recap', .2); pi.wait(lambda: len([r for r in pi.records() if r['status'] == 'published']) == 1, 'safe follow-up did not save')
                published = [r for r in pi.records() if r['status'] == 'published']
                observation['two_attempt_seconds'] = round(elapsed, 3)
            elif case == 'cancel': assert not published and not pi.calls()
            else:
                assert terminal['status'] == 'published' and len(published) == 1
                assert published[0]['token'] != token if case == 'newer' else published[0]['token'] == token
                assert published[0]['metadata']['pi']['nativeSessionId'] == identity
                assert published[0]['metadata']['pi']['historyId'] == history
                assert 'orchard-checks-passed' in published[0]['summary'] and published[0]['metadata']['pi']['coverage']['units']
                if case in ('switch', 'reload', 'shutdown'): assert 'Observed orchard:' not in pi.visible(boundary), 'stale/foreign UI consumed original result'
            if case != 'cancel':
                if case in ('switch', 'reload', 'shutdown'):
                    pi.stop(); pi.launch(original); pi.collect(3)
                before = len(pi.envelopes())
                pi.send('/recap', 1); pi.redraw()
                assert 'No new activity.' in pi.visible(), 'saved original coverage not recovered'
                pi.send('/recap history', 1)
                assert 'Recap history' in pi.visible() and 'published' in pi.visible()
                os.write(pi.master, b'\x1b'); pi.collect(.3)
                assert len(pi.envelopes()) == before, 'no-new duplicated work'
            assert len([e for e in pi.events() if e['event'] == 'call' and e.get('model') == 'main']) == 2, 'recap made foreground turn'
            pi.assert_no_transcript_output()
            observation.update(status='PASS', terminal=terminal['status'], envelopes=len(pi.envelopes()), provider_calls=len(pi.calls()), published=len(published), closed_gate_stop=case in ('cancel', 'newer'), original_association=True, no_extra_turn=True)
        except Exception as exc:
            observation.update(status='FAIL', reason=str(exc), envelopes=len(pi.envelopes()), provider_calls=len(pi.calls()), records=[dict(status=r['status'], attempt=r.get('attempt')) for r in pi.records()])
            raise
        finally:
            gate.unlink(missing_ok=True)
            pi.close()
            observation['provider_boundary'] = [
                {**{k: e[k] for k in ('event', 'model', 'preflight', 'pid', 'number', 'reduction', 'maxTokens', 'time') if k in e},
                 **({'prompt_bytes': len(e['prompt'].encode()), 'prompt_sha256': hashlib.sha256(e['prompt'].encode()).hexdigest()} if 'prompt' in e else {})}
                for e in pi.events() if e['event'] in ('route-start', 'budget-wait', 'budget-resolved', 'call')]
            observation['cli_boundary'] = [{k: e[k] for k in ('event', 'token', 'status', 'attempt', 'input_budget_bytes', 'budget', 'timeout', 'record_id', 'time') if k in e} for e in pi.receipts()]
            observation['saved_records'] = [dict(record_id=r['record_id'], status=r['status'], attempt=r.get('attempt'), token=r.get('token'), original_session=r.get('metadata', {}).get('pi', {}).get('nativeSessionId'), coverage_sha256=hashlib.sha256(json.dumps(r.get('metadata', {}).get('pi', {}).get('coverage'), sort_keys=True).encode()).hexdigest()) for r in pi.records()]
            helpers = {e['pid'] for e in pi.events() if e['event'] == 'route-start' and e['preflight']}
            end = time.monotonic() + 12
            while any(not exited(pid) for pid in helpers) and time.monotonic() < end: time.sleep(.05)
            assert all(exited(pid) for pid in helpers), 'owned preflight cleanup incomplete'
            observation['preflight_pids_exited'] = sorted(helpers)
            observation['cleanup'] = 'owned Pi, preflight helpers and detached supervisors exited; private fixture removed'
            print(json.dumps(observation), flush=True)
    assert not root.exists()

if __name__ == '__main__': run(sys.argv[1])
