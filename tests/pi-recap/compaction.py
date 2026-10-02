#!/usr/bin/env python3
"""Native public Pi compaction must finish before virtual budget metadata resolves."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from public_helpers import PublicPi, ROOT


SOURCES = ['dot_pi/private_agent/extensions/recap/index.ts', 'dot_pi/private_agent/extensions/recap/helpers.ts', 'dot_pi/private_agent/extensions/recap/backend.mjs', 'tests/pi-recap/compaction.py', 'tests/pi-recap/public_fixture.ts', 'tests/pi-recap/public_helpers.py']


def evidence(case):
    return dict(case=case, source_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCES})


def budget_helpers_exited(pi):
    for pid in {e['pid'] for e in pi.events() if e['event'] == 'budget-wait'}:
        try: os.kill(pid, 0)
        except ProcessLookupError: continue
        return False
    return True


def run(case):
    observation = evidence(case)
    with tempfile.TemporaryDirectory(prefix='recap-virtual-compaction-') as temporary:
        root = Path(temporary)
        pi = PublicPi(root, environment=dict(RECAP_PROOF_COMPACTION=case, RECAP_PROOF_CONTEXT='4096', RECAP_PROOF_MAX_OUTPUT='512'), config=dict(model=dict(provider='recap-router', id='auto'), beforeCompaction=True, inputBudget=24000, timeoutSeconds=30), agent_settings=dict(compaction=dict(enabled=case == 'automatic', reserveTokens=2000, keepRecentTokens=1)))
        budget_gate = root / 'budget-gate'
        try:
            pi.send('orchard')
            pi.wait(lambda: any(e['event'] == 'settled' for e in pi.events()), 'orchard did not settle')
            budget_gate.touch()
            pi.gate.touch()  # Separately prevent generation after metadata is released.
            pi.send('harbor')
            if case == 'manual':
                pi.wait(lambda: len([e for e in pi.events() if e['event'] == 'settled']) == 2, 'harbor did not settle')
                pi.send('/compact', .2)
            pi.wait(lambda: any(e['event'] == 'budget-wait' for e in pi.events()), 'public route metadata never gated', 12)
            before = next(e for e in pi.events() if e['event'] == 'before-compact')
            original = json.dumps(before['branch'])
            assert 'FACT_result=orchard-checks-passed' in original and 'FACT_pending=harbor-deployment-unfinished' in original
            assert not pi.calls() and len(pi.envelopes()) == 1, 'preflight not inside accepted detached envelope'
            # Positive completed native event is required with the route still closed.
            # The fixed implementation takes <1s locally; bounded observation is ample
            # and deliberately shorter than the 30-second metadata timeout.
            started = time.monotonic()
            try:
                pi.wait(lambda: any(e['event'] == 'compacted' for e in pi.events()), 'native compaction blocked by virtual metadata resolution', 5)
            finally:
                observation.update(metadata_gate_closed=budget_gate.exists(), native_completed=any(e['event'] == 'compacted' for e in pi.events()), native_summary_calls=sum(e['event'] == 'native-summary' for e in pi.events()), recap_calls_while_metadata_closed=len(pi.calls()), cli_envelopes_while_metadata_closed=len(pi.envelopes()), observation_seconds=round(time.monotonic() - started, 3), original_branch_sha256=hashlib.sha256(original.encode()).hexdigest())
            compacted = next(e for e in pi.events() if e['event'] == 'compacted')
            assert budget_gate.exists() and not pi.calls() and len(pi.envelopes()) == 1
            assert compacted['reason'] == ('manual' if case == 'manual' else 'threshold') and not compacted['fromExtension'], 'not native compaction'
            assert 'FACT_result=orchard-checks-passed' not in json.dumps(compacted['projection']), 'compaction did not remove original material from native context'
            budget_gate.unlink()
            pi.wait(lambda: pi.calls() and pi.envelopes(), 'captured virtual request never handed off', 15)
            envelope = pi.envelopes()[0]
            assert not pi.terminal(envelope['token']), 'generation gate ineffective'
            material = envelope['material']
            for fact in ('orchard-checks-passed', 'harbor-deployment-unfinished', 'harbor-review-before-deploy'):
                assert fact in material, 'late capture lost original material'
            pi.wait(lambda: any(e['event'] == 'preflight' for e in pi.receipts()), 'supervised preflight not observed')
            assert next(e['input_budget_bytes'] for e in pi.receipts() if e['event'] == 'preflight') < 4096
            pi.gate.unlink()
            pi.wait(lambda: pi.terminal(envelope['token']), 'captured job did not complete')
            assert pi.terminal(envelope['token'])['status'] == 'published'
            saved = [r for r in pi.records() if r['status'] == 'published']
            assert len(saved) == 1
            record = saved[0]
            for fact in ('orchard-checks-passed', 'harbor-deployment-unfinished', 'harbor-review-before-deploy'):
                assert fact in record['summary'], 'saved narrative lacks original outcome/state/next step'
            metadata = record['metadata']['pi']
            ids = [e['id'] for e in before['branch']]
            assert metadata['nativeSessionId'] == before['sessionId'] and metadata['capturedEnd'] == ids[-1]
            assert metadata['trigger'] == 'before-compaction' and len(metadata['coverage']['units']) >= 6
            assert metadata['capturedAt'] < next(e for p in (root / 'sessions').rglob('*.jsonl') for e in PublicPi.lines(p) if e.get('type') == 'compaction')['timestamp']
            pi.collect(1)
            assert len(pi.calls()) == 1 and pi.calls()[0]['maxTokens'] <= 512
            assert len([e for e in pi.events() if e['event'] == 'call' and e.get('model') == 'main']) == 4 + sum(e['event'] == 'native-summary' for e in pi.events()), 'extra main turn beyond conversation and native summaries'
            assert sum(e['event'] == 'settled' for e in pi.events()) == 2, 'compaction recap caused extra agent settlement'
            pi.assert_no_transcript_output()
            observation.update(status='PASS', native_reason=compacted['reason'], original_material_preserved=True, captured_input_ceiling=envelope['budget'], input_budget=next(e['input_budget_bytes'] for e in pi.receipts() if e['event'] == 'preflight'), output_allowance=pi.calls()[0]['maxTokens'], narrative_sha256=hashlib.sha256(record['summary'].encode()).hexdigest(), coverage_sha256=hashlib.sha256(json.dumps(metadata['coverage'], sort_keys=True).encode()).hexdigest(), no_extra_turn=True)
        except Exception as exc:
            observation.update(status='FAIL', reason=str(exc), event_counts={name: sum(e['event'] == name for e in pi.events()) for name in {e['event'] for e in pi.events()}}, compact_failures=[e for e in pi.events() if e['event'] == 'compact-failed'])
            raise
        finally:
            budget_gate.unlink(missing_ok=True)
            pi.wait(lambda: budget_helpers_exited(pi), 'metadata helper did not exit during cleanup', 12)
            pi.close()
            observation['cleanup'] = 'owned Pi/supervisors stopped; metadata/generation gates released; private tree removed'
            print(json.dumps(observation), flush=True)
    assert not root.exists()


def run_guard(case):
    journey = case.removeprefix('guard-')
    observation = evidence(case)
    with tempfile.TemporaryDirectory(prefix='recap-compaction-guard-') as temporary:
        root = Path(temporary)
        pi = PublicPi(root, environment=dict(RECAP_PROOF_COMPACTION='manual', RECAP_PROOF_CONTEXT='4096', RECAP_PROOF_MAX_OUTPUT='512'), config=dict(model=dict(provider='recap-router', id='auto'), beforeCompaction=True, inputBudget=24000, timeoutSeconds=30), agent_settings=dict(compaction=dict(enabled=False, keepRecentTokens=1)))
        gate = root / 'budget-gate'
        try:
            pi.send('orchard'); pi.wait(lambda: any(e['event'] == 'settled' for e in pi.events()), 'main did not settle')
            gate.touch()
            pi.send('/compact', .2)
            pi.wait(lambda: any(e['event'] == 'budget-wait' for e in pi.events()), 'metadata never gated', 12)
            pi.wait(lambda: any(e['event'] == 'compacted' for e in pi.events()), 'native compaction blocked', 5)
            original = next(e for e in pi.events() if e['event'] == 'before-compact')['sessionId']
            old_token = pi.current('pi-recap:' + original)['token']
            if journey == 'switch':
                pi.send('/new', 2)
                pi.send('/resume', 2); pi.send('', 2)
            elif journey == 'reload': pi.send('/reload', 2)
            elif journey == 'cancel': pi.send('/recap cancel', 1)
            elif journey == 'shutdown': pi.stop()
            elif journey == 'newer':
                pi.send('/recap', .2)
                pi.wait(lambda: sum(e['event'] == 'budget-wait' for e in pi.events()) == 2, 'newer metadata request did not start', 12)
                assert pi.current('pi-recap:' + original)['token'] != old_token
            elif journey in ('failure-current', 'failure-stale'):
                (root / 'budget-failure').touch()
                if journey == 'failure-stale': pi.send('/new', 2)
            else: raise ValueError('unknown guarded journey')
            boundary = len(pi.output)
            if journey in ('cancel', 'newer'):
                old_pid = next(e['pid'] for e in pi.events() if e['event'] == 'budget-wait')
                def stopped():
                    try: os.kill(old_pid, 0)
                    except ProcessLookupError: return True
                    return False
                pi.wait(stopped, 'old helper not stopped while metadata gate remains closed', 3)
                assert gate.exists()
            gate.unlink()
            pi.wait(lambda: budget_helpers_exited(pi), 'metadata resolution did not finish', 15)
            pi.collect(1)
            current_token = pi.current('pi-recap:' + original)['token'] if journey == 'newer' else old_token
            pi.wait(lambda: pi.terminal(current_token), 'captured original request did not finish')
            terminal = pi.terminal(current_token)
            published = [r for r in pi.records() if r['status'] == 'published']
            if journey == 'newer':
                assert len(pi.envelopes()) == 2 and len(pi.calls()) == 1 and len(published) == 1
                assert current_token != old_token and terminal['status'] == 'published'
                assert pi.terminal(old_token)['status'] == 'superseded'
            elif journey == 'cancel':
                assert terminal['status'] == 'canceled' and not pi.calls() and not published
            elif journey.startswith('failure-'):
                assert terminal['status'] == 'failed' and terminal['attempt'] == 2 and not pi.calls() and not published
                assert len(pi.records()) == 2, 'preflight failure did not use complete-attempt retry'
                if journey == 'failure-current': assert 'Recap failed; coverage unchanged' in pi.visible(boundary), 'current failure not delivered'
            else:
                assert terminal['status'] == 'published' and len(pi.calls()) == 1 and len(published) == 1
                assert published[0]['metadata']['pi']['nativeSessionId'] == original and published[0]['metadata']['pi']['trigger'] == 'before-compaction'
            if journey in ('switch', 'reload', 'shutdown', 'failure-stale'):
                assert 'Observed orchard:' not in pi.visible(boundary) and 'Recap failed;' not in pi.visible(boundary), 'foreign/stale callback output'
            assert len([e for e in pi.events() if e['event'] == 'call' and e.get('model') == 'main']) == 2 + sum(e['event'] == 'native-summary' for e in pi.events()), 'preflight caused extra model turn'
            pi.assert_no_transcript_output()
            observation.update(status='PASS', native_completed_while_metadata_closed=True, journey=journey, original_token_terminal=pi.terminal(old_token)['status'], envelopes=len(pi.envelopes()), recap_calls=len(pi.calls()), fresh_current_failure_notice=journey == 'failure-current', no_extra_turn=True)
        except Exception as exc:
            observation.update(status='FAIL', reason=str(exc))
            raise
        finally:
            gate.unlink(missing_ok=True)
            pi.wait(lambda: budget_helpers_exited(pi), 'metadata helper did not exit during cleanup', 12)
            pi.close()
            observation['cleanup'] = 'owned Pi, metadata helpers and supervisors exited; private tree removed'
            print(json.dumps(observation), flush=True)
    assert not root.exists()


if __name__ == '__main__':
    (run_guard if sys.argv[1].startswith('guard-') else run)(sys.argv[1])
