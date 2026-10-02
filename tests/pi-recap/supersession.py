#!/usr/bin/env python3
"""New original-session public request fences old jobs surviving actual departure."""
import json
import os
from pathlib import Path
import sys
import tempfile
from public_helpers import PublicPi

observations = []
evidence = []
for journey in ('switch', 'reload', 'shutdown'):
    with tempfile.TemporaryDirectory(prefix='recap-supersession-') as temporary:
        root = Path(temporary)
        pi = PublicPi(root)
        try:
            pi.send('Inspect older')
            pi.wait(lambda: any(e['event'] == 'settled' for e in pi.events()), 'old work not settled')
            original = next((root / 'sessions').rglob('*.jsonl'))
            native_id = json.loads(original.read_text().splitlines()[0])['id']
            pi.gate.touch()
            pi.send('/recap')
            pi.wait(lambda: len(pi.calls()) == 1, 'old generation never reached backend')
            old = pi.envelopes()[0]
            assert pi.calls()[0]['number'] == 1 and 'FACT_topic=older' in pi.calls()[0]['prompt']
            assert not pi.terminal(old['token'])
            if journey == 'shutdown': pi.stop()
            else: pi.send('/new' if journey == 'switch' else '/reload', 3)
            boundary = len(pi.output)
            if journey == 'switch':
                pi.send('/recap', 1)
                assert 'Nothing to recap yet' in pi.visible(boundary)
                assert 'Observed older:' not in pi.visible(boundary) and not pi.records(), 'foreign session saw old output'
            assert pi.gate.exists() and not pi.terminal(old['token']), 'old work did not survive departure gated'
            # Reload retains the original session; switch and shutdown are resumed
            # through the public --session argument, without releasing old generation.
            if journey != 'reload':
                pi.stop(); pi.launch(original); pi.collect(4)
            assert pi.gate.exists() and not pi.terminal(old['token']), 'old work completed before newer request'
            pi.send('Inspect newer')
            pi.wait(lambda: sum(e['event'] == 'settled' for e in pi.events()) == 2, 'new work not settled')
            before = len(pi.output)
            pi.send('/recap')
            pi.wait(lambda: len(pi.envelopes()) == 2, 'new original-session request missing')
            new = pi.envelopes()[-1]
            assert old['token'] != new['token'] and old['request_key'] == new['request_key'] == 'pi-recap:' + native_id
            assert pi.gate.exists(), 'old gate released early'
            pi.wait(lambda: pi.terminal(new['token']), 'new independent generation did not finish')
            assert pi.terminal(new['token'])['status'] == 'published'
            pi.wait(lambda: 'Observed newer:' in pi.visible(before), 'new narrative not displayed', 5)
            assert pi.gate.exists(), 'new result waited on old gate'
            assert 'Observed older:' not in pi.visible(before), 'old narrative displayed in original UI'
            saved, = [r for r in pi.records() if r['status'] == 'published']
            assert saved['token'] == new['token'] and saved['metadata']['pi']['nativeSessionId'] == native_id
            assert saved['metadata']['pi']['historyId']
            assert 'newer-checks-passed' in saved['summary'] and 'newer-deployment-unfinished' in saved['summary'] and 'Next: newer-review-before-deploy.' in saved['summary']
            assert 'older-checks-passed' in saved['summary'] and 'older-deployment-unfinished' in saved['summary'], 'new capture omitted still-uncovered original work'
            main_calls = sum(e.get('model') == 'main' for e in pi.events())
            assert old['material'] in new['material'], 'old uncompleted capture falsely established coverage'
            assert len(pi.calls()) == 2 and 'FACT_topic=newer' in pi.calls()[-1]['prompt']
            assert pi.calls()[-1]['number'] == 2, 'backend gates not independently controlled'
            # The durable fence may kill the old gated provider before gate release.
            # Its supervisor still must finish with superseded, never success.
            pi.wait(lambda: pi.terminal(old['token']), 'old worker did not observe supersession', 5)
            assert pi.terminal(old['token'])['status'] == 'superseded'
            authoritative = pi.current(new['request_key'])
            assert authoritative['token'] == new['token'] and authoritative['record_id'] == saved['record_id']
            coverage = saved['metadata']['pi']['coverage']
            boundary = len(pi.output); pi.gate.unlink(); pi.collect(2)
            assert 'Observed older:' not in pi.visible(boundary), 'released old result displayed'
            assert [r['record_id'] for r in pi.records() if r['status'] == 'published'] == [saved['record_id']], 'old result saved after new'
            assert pi.current(new['request_key']) == authoritative, 'old result replaced current token/result'
            assert next(r for r in pi.records() if r['record_id'] == saved['record_id'])['metadata']['pi']['coverage'] == coverage, 'old advanced coverage'
            count = len(pi.calls()); before = len(pi.output)
            pi.send('/recap', 2)
            pi.redraw()
            assert len(pi.calls()) == count and len(pi.envelopes()) == 2, 'subsequent request lost authoritative newer coverage'
            assert 'No new activity' in pi.visible(before) and 'Observed newer:' in pi.visible(before), 'no-new did not reuse newer result'
            assert 'Observed older:' not in pi.visible(before)
            # History must show the authoritative saved narrative, while the old
            # attempt remains an honest superseded row with no generated summary.
            before_history = len(pi.output)
            pi.send('/recap history', .5)
            pi.send(saved['record_id'], .3); pi.send('', .5)
            assert 'Observed newer:' in pi.visible(before_history) and saved['record_id'] in pi.visible(before_history), 'history lost authoritative new narrative'
            os.write(pi.master, b'\x1b'); pi.collect(.5)
            old_record, = [r for r in pi.records() if r['token'] == old['token']]
            assert old_record['status'] == 'superseded' and 'summary' not in old_record, 'old narrative saved into history'
            before_history = len(pi.output)
            pi.send('/recap history attempts', .5)
            pi.send(old_record['record_id'], .3); pi.send('', .5)
            assert 'superseded' in pi.visible(before_history), 'old history attempt missing supersession'
            os.write(pi.master, b'\x1b'); pi.collect(.5)
            assert 'Observed older:' not in pi.visible(), 'old narrative reached decoded UI/history'
            assert not any('Observed older:' in r.get('summary', '') for r in pi.records()), 'old narrative reached a stored record'
            pi.send('/new', 1); before = len(pi.output); pi.send('/recap', 1)
            assert 'Nothing to recap yet' in pi.visible(before) and 'Observed newer:' not in pi.visible(before) and 'Observed older:' not in pi.visible(before), 'foreign session saw recap output'
            assert sum(e.get('model') == 'main' for e in pi.events()) == main_calls, 'recap delivery/reuse caused a foreground turn'
            pi.assert_no_transcript_output()
            observations.append(journey + '-old-gated-new-original-request-save-display-superseded-no-old-coverage-foreign-output-no-duplicate')
            evidence.append(dict(journey=journey, native_session_id=native_id, old_token=old['token'], new_token=new['token'], old_terminal=pi.terminal(old['token'])['status'], new_terminal=pi.terminal(new['token'])['status'], independently_gated_backend_calls=[c['number'] for c in pi.calls()], saved_record=saved['record_id'], saved_summary=saved['summary'], coverage_units=len(coverage['units']), old_gate_retained_until_new_delivery=True, original_history_viewed=True, old_attempt_history_status=old_record['status'], full_decoded_ui_old_narrative_absent=True, foreign_session_output_absent=True, post_release_backend_calls=0))
        except Exception:
            print(json.dumps({'completed_cases': observations, 'receipts': [{k: v for k, v in e.items() if k not in ('material', 'background', 'instructions')} for e in pi.receipts()]}), file=sys.stderr)
            print(pi.visible()[-16000:], file=sys.stderr)
            raise
        finally:
            pi.close()
    assert not root.exists(), 'private fixture cleanup failed'
print(json.dumps({'status': 'PASS', 'cases': observations, 'observations': evidence, 'cleanup': 'private Pi/supervisors exited and resources removed'}))
